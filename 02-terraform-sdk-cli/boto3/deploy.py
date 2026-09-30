"""
Punto 2 - version Boto3: mismo stack que la version Terraform (S3 + EC2 + RDS),
pero sin ningun archivo de estado. Los recursos se identifican por nombre fijo
y tags (Project/Punto/Owner/Method), y el destroy los busca por esos mismos
criterios en vez de leer un tfstate.

Uso:
    AWS_PROFILE=user_cli python deploy.py create
    AWS_PROFILE=user_cli python deploy.py destroy
"""

import argparse
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
PROJECT = "taller-aws-eia"
PUNTO = "2"
OWNER = "Luis Brito Rincon"
METHOD = "boto3"

BUCKET_NAME = "taller-aws-eia-punto2-boto3"
EC2_SG_NAME = "taller-aws-eia-punto2-boto3-ec2-sg"
RDS_SG_NAME = "taller-aws-eia-punto2-boto3-rds-sg"
DB_SUBNET_GROUP_NAME = "taller-aws-eia-punto2-boto3-db-subnet-group"
DB_IDENTIFIER = "taller-aws-eia-punto2-boto3-mysql"
DB_USERNAME = "tallerdbadmin"
EC2_NAME = "taller-aws-eia-punto2-boto3-ec2"

TAGS = [
    {"Key": "Project", "Value": PROJECT},
    {"Key": "Punto", "Value": PUNTO},
    {"Key": "Owner", "Value": OWNER},
    {"Key": "Method", "Value": METHOD},
]


def tag_spec(resource_type: str, extra_tags: list | None = None) -> list:
    tags = TAGS + (extra_tags or [])
    return [{"ResourceType": resource_type, "Tags": tags}]


def get_default_vpc_and_subnets(ec2):
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    vpc_id = vpcs["Vpcs"][0]["VpcId"]
    subnets = ec2.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )["Subnets"]
    subnet_ids = [s["SubnetId"] for s in subnets]
    return vpc_id, subnet_ids


def create_bucket(s3, region: str) -> str:
    print(f"Creando bucket S3 '{BUCKET_NAME}'...")
    s3.create_bucket(
        Bucket=BUCKET_NAME,
        CreateBucketConfiguration={"LocationConstraint": region},
    )
    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_tagging(Bucket=BUCKET_NAME, Tagging={"TagSet": TAGS})
    print(f"  bucket listo: {BUCKET_NAME}")
    return BUCKET_NAME


def create_security_groups(ec2, vpc_id: str) -> tuple[str, str]:
    print("Creando security groups...")
    ec2_sg = ec2.create_security_group(
        GroupName=EC2_SG_NAME,
        Description="SG minimo de la EC2 de prueba (boto3): sin ingreso",
        VpcId=vpc_id,
        TagSpecifications=tag_spec("security-group"),
    )
    ec2_sg_id = ec2_sg["GroupId"]

    rds_sg = ec2.create_security_group(
        GroupName=RDS_SG_NAME,
        Description="SG de RDS (boto3): solo acepta conexiones desde el SG de la EC2",
        VpcId=vpc_id,
        TagSpecifications=tag_spec("security-group"),
    )
    rds_sg_id = rds_sg["GroupId"]

    ec2.authorize_security_group_ingress(
        GroupId=rds_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 3306,
                "ToPort": 3306,
                "UserIdGroupPairs": [{"GroupId": ec2_sg_id}],
            }
        ],
    )
    print(f"  EC2 SG: {ec2_sg_id} | RDS SG: {rds_sg_id}")
    return ec2_sg_id, rds_sg_id


def get_latest_al2023_ami(ec2) -> str:
    images = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": ["al2023-ami-*-x86_64"]},
            {"Name": "virtualization-type", "Values": ["hvm"]},
        ],
    )["Images"]
    images.sort(key=lambda i: i["CreationDate"], reverse=True)
    return images[0]["ImageId"]


def launch_ec2(ec2, subnet_id: str, ec2_sg_id: str) -> str:
    print("Lanzando instancia EC2 (t3.micro, sin IP publica)...")
    ami_id = get_latest_al2023_ami(ec2)
    response = ec2.run_instances(
        ImageId=ami_id,
        InstanceType="t3.micro",
        MinCount=1,
        MaxCount=1,
        NetworkInterfaces=[
            {
                "DeviceIndex": 0,
                "SubnetId": subnet_id,
                "Groups": [ec2_sg_id],
                "AssociatePublicIpAddress": False,
            }
        ],
        TagSpecifications=tag_spec("instance", [{"Key": "Name", "Value": EC2_NAME}]),
    )
    instance_id = response["Instances"][0]["InstanceId"]
    print(f"  esperando a que '{instance_id}' quede 'running'...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
    print(f"  EC2 lista: {instance_id}")
    return instance_id


def create_rds(rds, subnet_ids: list, rds_sg_id: str) -> str:
    print(f"Creando RDS '{DB_IDENTIFIER}' (db.t4g.micro, MySQL, contrasena en Secrets Manager)...")
    rds.create_db_subnet_group(
        DBSubnetGroupName=DB_SUBNET_GROUP_NAME,
        DBSubnetGroupDescription="Subnet group para el stack de prueba (boto3)",
        SubnetIds=subnet_ids,
        Tags=TAGS,
    )
    rds.create_db_instance(
        DBInstanceIdentifier=DB_IDENTIFIER,
        Engine="mysql",
        EngineVersion="8.0",
        DBInstanceClass="db.t4g.micro",
        AllocatedStorage=20,
        StorageType="gp2",
        MasterUsername=DB_USERNAME,
        ManageMasterUserPassword=True,
        DBSubnetGroupName=DB_SUBNET_GROUP_NAME,
        VpcSecurityGroupIds=[rds_sg_id],
        PubliclyAccessible=False,
        MultiAZ=False,
        BackupRetentionPeriod=0,
        Tags=TAGS,
    )
    print("  esperando a que RDS quede 'available' (puede tardar varios minutos)...")
    rds.get_waiter("db_instance_available").wait(DBInstanceIdentifier=DB_IDENTIFIER)
    info = rds.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)["DBInstances"][0]
    endpoint = info["Endpoint"]["Address"]
    secret_arn = info["MasterUserSecret"]["SecretArn"]
    print(f"  RDS lista: {endpoint}")
    print(f"  secreto de la contrasena: {secret_arn}")
    return endpoint


def create():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    s3 = session.client("s3")
    rds = session.client("rds")

    vpc_id, subnet_ids = get_default_vpc_and_subnets(ec2)
    bucket = create_bucket(s3, REGION)
    ec2_sg_id, rds_sg_id = create_security_groups(ec2, vpc_id)
    instance_id = launch_ec2(ec2, subnet_ids[0], ec2_sg_id)
    endpoint = create_rds(rds, subnet_ids, rds_sg_id)

    print("\n=== Resumen ===")
    print(f"Bucket S3:  {bucket}")
    print(f"EC2:        {instance_id}")
    print(f"RDS:        {endpoint}")


def _find_by_tag(items: list, tag_key: str, tag_value: str) -> list:
    """Filtra una lista de recursos (con campo 'Tags') por tag Key/Value."""
    result = []
    for item in items:
        for tag in item.get("Tags", []):
            if tag["Key"] == tag_key and tag["Value"] == tag_value:
                result.append(item)
                break
    return result


def destroy():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    s3 = session.client("s3")
    rds = session.client("rds")

    # RDS: buscamos por identificador fijo (no por tag, es mas directo)
    try:
        rds.delete_db_instance(
            DBInstanceIdentifier=DB_IDENTIFIER,
            SkipFinalSnapshot=True,
            DeleteAutomatedBackups=True,
        )
        print(f"Eliminando RDS '{DB_IDENTIFIER}', esperando...")
        rds.get_waiter("db_instance_deleted").wait(DBInstanceIdentifier=DB_IDENTIFIER)
        print("  RDS eliminada.")
    except ClientError as e:
        print(f"  RDS: {e.response['Error']['Code']} (puede que ya no exista)")

    try:
        rds.delete_db_subnet_group(DBSubnetGroupName=DB_SUBNET_GROUP_NAME)
        print("  DB subnet group eliminado.")
    except ClientError as e:
        print(f"  DB subnet group: {e.response['Error']['Code']}")

    # EC2: buscamos instancias por el tag Name+Project (no tenemos state file)
    reservations = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [EC2_NAME]},
            {"Name": "instance-state-name", "Values": ["running", "stopped", "pending"]},
        ]
    )["Reservations"]
    instance_ids = [i["InstanceId"] for r in reservations for i in r["Instances"]]
    if instance_ids:
        print(f"Terminando EC2 {instance_ids}...")
        ec2.terminate_instances(InstanceIds=instance_ids)
        ec2.get_waiter("instance_terminated").wait(InstanceIds=instance_ids)
        print("  EC2 terminada.")
    else:
        print("  EC2: no se encontro ninguna con ese tag (puede que ya este borrada).")

    # Security groups: por nombre fijo
    for sg_name in (RDS_SG_NAME, EC2_SG_NAME):  # RDS SG primero: depende del EC2 SG
        try:
            sgs = ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [sg_name]}]
            )["SecurityGroups"]
            for sg in sgs:
                ec2.delete_security_group(GroupId=sg["GroupId"])
                print(f"  SG '{sg_name}' eliminado.")
        except ClientError as e:
            print(f"  SG '{sg_name}': {e.response['Error']['Code']}")

    # S3: el bucket es de nombre fijo, hay que vaciarlo antes de borrarlo
    try:
        objects = s3.list_objects_v2(Bucket=BUCKET_NAME)
        for obj in objects.get("Contents", []):
            s3.delete_object(Bucket=BUCKET_NAME, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET_NAME)
        print(f"  Bucket '{BUCKET_NAME}' eliminado.")
    except ClientError as e:
        print(f"  Bucket: {e.response['Error']['Code']} (puede que ya no exista)")

    print("\nDestroy completo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "destroy"])
    args = parser.parse_args()

    if args.action == "create":
        create()
    else:
        destroy()
