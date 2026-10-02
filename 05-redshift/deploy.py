"""
Punto 5 - carga del dataset + consultas en Redshift Serverless, todo via
Redshift Data API (sin tunel, sin password en el codigo).

El namespace/workgroup ('default-namespace'/'default-workgroup') y el rol
IAM para leer S3 ya los dejo creados el profesor (cuenta compartida, IAM
gestionado centralizadamente - ver README). No creo cluster propio: uso
lo que ya existe.

Uso:
    AWS_PROFILE=user_cli python deploy.py load    # sube a S3 + crea tablas + COPY
    AWS_PROFILE=user_cli python deploy.py query   # corre las 3 consultas
    AWS_PROFILE=user_cli python deploy.py destroy # borra solo lo mio (tablas + bucket)
"""

import argparse
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
PROJECT = "taller-aws-eia"
PUNTO = "5"
OWNER = "Luis Brito Rincon"

WORKGROUP_NAME = "default-workgroup"
DATABASE = "dev"
SECRET_ARN = "arn:aws:secretsmanager:us-east-2:802655955683:secret:taller-redshift-credenciales-l0vVt0"

# Rol que me dio el profesor (Redshift -> lectura de S3), ya asociado al namespace
REDSHIFT_S3_ROLE_ARN = "arn:aws:iam::802655955683:role/service-role/AmazonRedshift-CommandsAccessRole-20261002T065107"

BUCKET_NAME = "taller-aws-eia-punto5-dataset"
DATA_DIR = Path(__file__).parent / "data"

TAGS = [
    {"Key": "Project", "Value": PROJECT},
    {"Key": "Punto", "Value": PUNTO},
    {"Key": "Owner", "Value": OWNER},
]


def upload_dataset():
    s3 = boto3.client("s3", region_name=REGION)
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

    for nombre in ("customers.csv", "orders.csv"):
        local_path = DATA_DIR / nombre
        key = f"dataset/{nombre}"
        s3.upload_file(str(local_path), BUCKET_NAME, key)
        print(f"  subido: s3://{BUCKET_NAME}/{key}")


def run_sql(redshift_data, sql, description=""):
    resp = redshift_data.execute_statement(
        WorkgroupName=WORKGROUP_NAME,
        Database=DATABASE,
        SecretArn=SECRET_ARN,
        Sql=sql,
    )
    statement_id = resp["Id"]
    while True:
        status = redshift_data.describe_statement(Id=statement_id)
        state = status["Status"]
        if state in ("FINISHED", "FAILED", "ABORTED"):
            break
        time.sleep(1.5)
    if state != "FINISHED":
        raise RuntimeError(f"{description or sql[:60]} -> {state}: {status.get('Error')}")
    return statement_id


def crear_tablas_y_cargar(redshift_data):
    print("Creando tablas (schema degr02user4_punto5)...")
    run_sql(redshift_data, "CREATE SCHEMA IF NOT EXISTS degr02user4_punto5;", "create schema")
    run_sql(redshift_data, """
        DROP TABLE IF EXISTS degr02user4_punto5.orders;
        DROP TABLE IF EXISTS degr02user4_punto5.customers;
    """, "drop tablas previas")
    run_sql(redshift_data, """
        CREATE TABLE degr02user4_punto5.customers (
            customer_id INTEGER PRIMARY KEY,
            nombre VARCHAR(100),
            email VARCHAR(100),
            ciudad VARCHAR(50),
            fecha_registro DATE
        );
    """, "create customers")
    run_sql(redshift_data, """
        CREATE TABLE degr02user4_punto5.orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES degr02user4_punto5.customers(customer_id),
            categoria VARCHAR(50),
            monto DECIMAL(12,2),
            fecha_orden DATE
        );
    """, "create orders")
    print("  tablas creadas.")

    print("Cargando con COPY desde S3...")
    run_sql(redshift_data, f"""
        COPY degr02user4_punto5.customers FROM 's3://{BUCKET_NAME}/dataset/customers.csv'
        IAM_ROLE '{REDSHIFT_S3_ROLE_ARN}'
        CSV IGNOREHEADER 1;
    """, "copy customers")
    run_sql(redshift_data, f"""
        COPY degr02user4_punto5.orders FROM 's3://{BUCKET_NAME}/dataset/orders.csv'
        IAM_ROLE '{REDSHIFT_S3_ROLE_ARN}'
        CSV IGNOREHEADER 1;
    """, "copy orders")
    print("  datos cargados.")


def load():
    upload_dataset()
    redshift_data = boto3.client("redshift-data", region_name=REGION)
    crear_tablas_y_cargar(redshift_data)


def fetch_results(redshift_data, statement_id):
    resp = redshift_data.get_statement_result(Id=statement_id)
    cols = [c["name"] for c in resp["ColumnMetadata"]]
    rows = []
    for record in resp["Records"]:
        row = []
        for field in record:
            row.append(next(iter(field.values())) if field else None)
        rows.append(dict(zip(cols, row)))
    return rows


def query():
    redshift_data = boto3.client("redshift-data", region_name=REGION)

    print("\n--- Consulta 1 (filtro): pedidos de Electronica con monto > 300000 ---")
    sid = run_sql(redshift_data, """
        SELECT order_id, customer_id, categoria, monto
        FROM degr02user4_punto5.orders
        WHERE categoria = 'Electronica' AND monto > 300000
        ORDER BY monto DESC
        LIMIT 10;
    """, "filtro")
    for row in fetch_results(redshift_data, sid):
        print(f"  {row}")

    print("\n--- Consulta 2 (JOIN): gasto total por cliente, con nombre y ciudad ---")
    sid = run_sql(redshift_data, """
        SELECT c.customer_id, c.nombre, c.ciudad, COUNT(o.order_id) AS num_pedidos, SUM(o.monto) AS gasto_total
        FROM degr02user4_punto5.customers c
        JOIN degr02user4_punto5.orders o ON c.customer_id = o.customer_id
        GROUP BY c.customer_id, c.nombre, c.ciudad
        ORDER BY gasto_total DESC
        LIMIT 10;
    """, "join + agregacion por cliente")
    for row in fetch_results(redshift_data, sid):
        print(f"  {row}")

    print("\n--- Consulta 3 (agregacion): ventas totales y promedio por ciudad ---")
    sid = run_sql(redshift_data, """
        SELECT c.ciudad, COUNT(o.order_id) AS num_pedidos, SUM(o.monto) AS ventas_totales, AVG(o.monto) AS ticket_promedio
        FROM degr02user4_punto5.customers c
        JOIN degr02user4_punto5.orders o ON c.customer_id = o.customer_id
        GROUP BY c.ciudad
        ORDER BY ventas_totales DESC;
    """, "agregacion por ciudad")
    for row in fetch_results(redshift_data, sid):
        print(f"  {row}")


def destroy():
    """Solo borro lo mio: las tablas/schema que cree y el bucket S3.
    El namespace/workgroup/secreto los administra el profesor, no los toco."""
    redshift_data = boto3.client("redshift-data", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    try:
        run_sql(redshift_data, "DROP SCHEMA IF EXISTS degr02user4_punto5 CASCADE;", "drop schema")
        print("  schema 'degr02user4_punto5' (tablas incluidas) eliminado.")
    except Exception as e:
        print(f"  schema: {e}")

    try:
        objects = s3.list_objects_v2(Bucket=BUCKET_NAME)
        for obj in objects.get("Contents", []):
            s3.delete_object(Bucket=BUCKET_NAME, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET_NAME)
        print(f"  bucket '{BUCKET_NAME}' eliminado.")
    except ClientError as e:
        print(f"  bucket: {e.response['Error']['Code']}")

    print("\nDestroy completo (namespace/workgroup/secreto compartidos, no se tocan).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["load", "query", "destroy"])
    args = parser.parse_args()
    {"load": load, "query": query, "destroy": destroy}[args.action]()
