"""
Punto 6 - Glue Data Catalog + Athena.

Uso:
    AWS_PROFILE=user_cli python deploy.py setup          # bucket + db + carga datos
    AWS_PROFILE=user_cli python deploy.py crawler-create  # crea el crawler (necesita rol IAM)
    AWS_PROFILE=user_cli python deploy.py crawler-run      # corre el crawler
    AWS_PROFILE=user_cli python deploy.py athena-setup     # crea el workgroup de Athena
    AWS_PROFILE=user_cli python deploy.py query            # corre consultas de ejemplo
    AWS_PROFILE=user_cli python deploy.py destroy          # elimina todo
"""

import argparse
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
PROJECT = "taller-aws-eia"
PUNTO = "6"
OWNER = "Luis Brito Rincon"

BUCKET_NAME = "taller-aws-eia-punto6-datos"
DATA_PREFIX = "productos"
DATA_DIR = Path(__file__).parent / "data"

GLUE_DB_NAME = "taller_aws_eia_punto6"
CRAWLER_NAME = "taller-aws-eia-punto6-crawler"

ATHENA_WORKGROUP = "taller-aws-eia-punto6-wg"
ATHENA_RESULTS_PREFIX = "athena-results/"

# ARN del rol que me dio el profesor para el crawler (glue.amazonaws.com -> S3 + Glue Catalog)
GLUE_CRAWLER_ROLE_ARN = "PENDIENTE"

TAGS = [
    {"Key": "Project", "Value": PROJECT},
    {"Key": "Punto", "Value": PUNTO},
    {"Key": "Owner", "Value": OWNER},
]


def setup():
    s3 = boto3.client("s3", region_name=REGION)
    glue = boto3.client("glue", region_name=REGION)

    print(f"Creando bucket '{BUCKET_NAME}'...")
    try:
        s3.create_bucket(Bucket=BUCKET_NAME, CreateBucketConfiguration={"LocationConstraint": REGION})
    except ClientError as e:
        if e.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
            raise
        print("  (ya existia, sigo)")
    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_tagging(Bucket=BUCKET_NAME, Tagging={"TagSet": TAGS})

    key = f"{DATA_PREFIX}/productos.csv"
    s3.upload_file(str(DATA_DIR / "productos.csv"), BUCKET_NAME, key)
    print(f"  subido: s3://{BUCKET_NAME}/{key}")

    print(f"Creando base de datos de Glue '{GLUE_DB_NAME}'...")
    try:
        glue.create_database(DatabaseInput={"Name": GLUE_DB_NAME})
        print("  base de datos creada.")
    except ClientError as e:
        if e.response["Error"]["Code"] != "AlreadyExistsException":
            raise
        print("  (ya existia, sigo)")


def crawler_create():
    if GLUE_CRAWLER_ROLE_ARN == "PENDIENTE":
        print("Falta el ARN del rol IAM para el crawler (GLUE_CRAWLER_ROLE_ARN). Pide el rol al profesor primero.")
        return
    glue = boto3.client("glue", region_name=REGION)
    print(f"Creando crawler '{CRAWLER_NAME}'...")
    glue.create_crawler(
        Name=CRAWLER_NAME,
        Role=GLUE_CRAWLER_ROLE_ARN,
        DatabaseName=GLUE_DB_NAME,
        Targets={"S3Targets": [{"Path": f"s3://{BUCKET_NAME}/{DATA_PREFIX}/"}]},
        Tags={t["Key"]: t["Value"] for t in TAGS},
    )
    print("  crawler creado.")


def crawler_run():
    glue = boto3.client("glue", region_name=REGION)
    print(f"Corriendo crawler '{CRAWLER_NAME}'...")
    glue.start_crawler(Name=CRAWLER_NAME)
    while True:
        info = glue.get_crawler(Name=CRAWLER_NAME)["Crawler"]
        state = info["State"]
        print(f"  estado: {state}")
        if state == "READY":
            break
        time.sleep(10)
    last_run = info.get("LastCrawl", {})
    print(f"  resultado: {last_run.get('Status')} - {last_run.get('MessagePrefix', '')}")

    tables = glue.get_tables(DatabaseName=GLUE_DB_NAME)["TableList"]
    for t in tables:
        print(f"\nTabla descubierta: {t['Name']}")
        for col in t["StorageDescriptor"]["Columns"]:
            print(f"  {col['Name']}: {col['Type']}")


def athena_setup():
    s3 = boto3.client("s3", region_name=REGION)
    athena = boto3.client("athena", region_name=REGION)

    try:
        s3.put_object(Bucket=BUCKET_NAME, Key=ATHENA_RESULTS_PREFIX)
    except ClientError:
        pass

    print(f"Creando workgroup de Athena '{ATHENA_WORKGROUP}'...")
    try:
        athena.create_work_group(
            Name=ATHENA_WORKGROUP,
            Configuration={
                "ResultConfiguration": {"OutputLocation": f"s3://{BUCKET_NAME}/{ATHENA_RESULTS_PREFIX}"},
                "BytesScannedCutoffPerQuery": 1_000_000_000,  # 1 GB limite por consulta, por si acaso
                "EnforceWorkGroupConfiguration": True,
            },
            Tags=TAGS,
        )
        print("  workgroup creado.")
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidRequestException":
            raise
        print("  (ya existia, sigo)")


def run_athena_query(athena, sql, description=""):
    resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": GLUE_DB_NAME},
        WorkGroup=ATHENA_WORKGROUP,
    )
    qid = resp["QueryExecutionId"]
    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1.5)
    if state != "SUCCEEDED":
        raise RuntimeError(f"{description or sql[:60]} -> {state}: {status.get('StateChangeReason')}")
    return qid


def fetch_athena_results(athena, qid):
    resp = athena.get_query_results(QueryExecutionId=qid)
    rows = resp["ResultSet"]["Rows"]
    header = [c.get("VarCharValue") for c in rows[0]["Data"]]
    out = []
    for row in rows[1:]:
        values = [c.get("VarCharValue") for c in row["Data"]]
        out.append(dict(zip(header, values)))
    return out


def query():
    athena = boto3.client("athena", region_name=REGION)

    print("\n--- Consulta 1 (filtro): productos de Electronica con precio > 500000 ---")
    qid = run_athena_query(athena, f"""
        SELECT product_id, nombre, categoria, precio
        FROM {GLUE_DB_NAME}.productos
        WHERE categoria = 'Electronica' AND CAST(precio AS DOUBLE) > 500000
        ORDER BY CAST(precio AS DOUBLE) DESC;
    """, "filtro")
    for row in fetch_athena_results(athena, qid):
        print(f"  {row}")

    print("\n--- Consulta 2 (agrupacion): cantidad de productos y stock total por categoria ---")
    qid = run_athena_query(athena, f"""
        SELECT categoria, COUNT(*) AS num_productos, SUM(CAST(stock AS INTEGER)) AS stock_total
        FROM {GLUE_DB_NAME}.productos
        GROUP BY categoria
        ORDER BY stock_total DESC;
    """, "agrupacion")
    for row in fetch_athena_results(athena, qid):
        print(f"  {row}")


def destroy():
    s3 = boto3.client("s3", region_name=REGION)
    glue = boto3.client("glue", region_name=REGION)
    athena = boto3.client("athena", region_name=REGION)

    try:
        glue.delete_crawler(Name=CRAWLER_NAME)
        print("  crawler eliminado.")
    except ClientError as e:
        print(f"  crawler: {e.response['Error']['Code']}")

    try:
        glue.delete_database(Name=GLUE_DB_NAME)
        print(f"  base de datos '{GLUE_DB_NAME}' eliminada.")
    except ClientError as e:
        print(f"  base de datos: {e.response['Error']['Code']}")

    try:
        athena.delete_work_group(WorkGroup=ATHENA_WORKGROUP, RecursiveDeleteOption=True)
        print("  workgroup de athena eliminado.")
    except ClientError as e:
        print(f"  workgroup: {e.response['Error']['Code']}")

    try:
        objects = s3.list_objects_v2(Bucket=BUCKET_NAME)
        for obj in objects.get("Contents", []):
            s3.delete_object(Bucket=BUCKET_NAME, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET_NAME)
        print(f"  bucket '{BUCKET_NAME}' eliminado.")
    except ClientError as e:
        print(f"  bucket: {e.response['Error']['Code']}")

    print("\nDestroy completo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=[
        "setup", "crawler-create", "crawler-run", "athena-setup", "query", "destroy",
    ])
    args = parser.parse_args()
    {
        "setup": setup,
        "crawler-create": crawler_create,
        "crawler-run": crawler_run,
        "athena-setup": athena_setup,
        "query": query,
        "destroy": destroy,
    }[args.action]()
