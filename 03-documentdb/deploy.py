"""
Punto 3 - despliegue de DocumentDB Serverless + EC2 bastion para el tunel SSH.

Uso:
    AWS_PROFILE=user_cli python deploy.py create
    AWS_PROFILE=user_cli python deploy.py destroy
"""

import argparse
import os
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
PROJECT = "taller-aws-eia"
PUNTO = "3"
OWNER = "Luis Brito Rincon"

MY_IP = "181.205.176.178/32"  # IP publica de mi casa, solo SSH desde aca

KEY_NAME = "taller-aws-eia-punto3-bastion-key"
KEY_FILE = os.path.join(os.path.dirname(__file__), f"{KEY_NAME}.pem")

BASTION_SG_NAME = "taller-aws-eia-punto3-bastion-sg"
DOCDB_SG_NAME = "taller-aws-eia-punto3-docdb-sg"
BASTION_NAME = "taller-aws-eia-punto3-bastion"

DB_SUBNET_GROUP_NAME = "taller-aws-eia-punto3-docdb-subnet-group"
CLUSTER_ID = "taller-aws-eia-punto3-docdb-cluster"
INSTANCE_ID = "taller-aws-eia-punto3-docdb-instance"
DB_USERNAME = "tallerdbadmin"

TAGS = [
    {"Key": "Project", "Value": PROJECT},
    {"Key": "Punto", "Value": PUNTO},
    {"Key": "Owner", "Value": OWNER},
]


def tag_spec(resource_type: str, extra_tags: list | None = None) -> list:
    return [{"ResourceType": resource_type, "Tags": TAGS + (extra_tags or [])}]


def get_default_vpc_and_subnets(ec2):
    vpc_id = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    subnet_ids = [
        s["SubnetId"]
        for s in ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
    ]
    return vpc_id, subnet_ids


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


def create_bastion(ec2, vpc_id: str, subnet_id: str) -> tuple[str, str]:
    print(f"Creando key pair '{KEY_NAME}'...")
    key = ec2.create_key_pair(KeyName=KEY_NAME, TagSpecifications=tag_spec("key-pair"))
    with open(KEY_FILE, "w") as f:
        f.write(key["KeyMaterial"])
    os.chmod(KEY_FILE, 0o400)
    print(f"  llave privada guardada en: {KEY_FILE}")

    print(f"Creando SG del bastion (SSH solo desde {MY_IP})...")
    bastion_sg_id = ec2.create_security_group(
        GroupName=BASTION_SG_NAME,
        Description="SG del bastion EC2 (punto 3): SSH solo desde mi IP",
        VpcId=vpc_id,
        TagSpecifications=tag_spec("security-group"),
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=bastion_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": MY_IP, "Description": "Mi IP de casa"}],
            }
        ],
    )
    print(f"  bastion SG: {bastion_sg_id}")

    print("Lanzando instancia EC2 bastion (t3.micro, CON IP publica para SSH)...")
    ami_id = get_latest_al2023_ami(ec2)
    response = ec2.run_instances(
        ImageId=ami_id,
        InstanceType="t3.micro",
        MinCount=1,
        MaxCount=1,
        KeyName=KEY_NAME,
        NetworkInterfaces=[
            {
                "DeviceIndex": 0,
                "SubnetId": subnet_id,
                "Groups": [bastion_sg_id],
                "AssociatePublicIpAddress": True,
            }
        ],
        TagSpecifications=tag_spec("instance", [{"Key": "Name", "Value": BASTION_NAME}]),
    )
    instance_id = response["Instances"][0]["InstanceId"]
    print(f"  esperando a que '{instance_id}' quede 'running'...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
    public_ip = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["PublicIpAddress"]
    print(f"  bastion listo: {instance_id} ({public_ip})")
    return bastion_sg_id, public_ip


def create_docdb(ec2, docdb, vpc_id: str, subnet_ids: list, bastion_sg_id: str) -> tuple[str, str]:
    print("Creando SG de DocumentDB (27017 solo desde el SG del bastion)...")
    docdb_sg_id = ec2.create_security_group(
        GroupName=DOCDB_SG_NAME,
        Description="SG de DocumentDB (punto 3): solo acepta conexiones desde el bastion",
        VpcId=vpc_id,
        TagSpecifications=tag_spec("security-group"),
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=docdb_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 27017,
                "ToPort": 27017,
                "UserIdGroupPairs": [{"GroupId": bastion_sg_id}],
            }
        ],
    )
    print(f"  docdb SG: {docdb_sg_id}")

    docdb.create_db_subnet_group(
        DBSubnetGroupName=DB_SUBNET_GROUP_NAME,
        DBSubnetGroupDescription="Subnet group para DocumentDB (punto 3)",
        SubnetIds=subnet_ids,
        Tags=TAGS,
    )

    print(f"Creando cluster DocumentDB Serverless '{CLUSTER_ID}' (0.5-1 DCU, contrasena en Secrets Manager)...")
    docdb.create_db_cluster(
        DBClusterIdentifier=CLUSTER_ID,
        Engine="docdb",
        EngineVersion="5.0.0",
        MasterUsername=DB_USERNAME,
        ManageMasterUserPassword=True,
        DBSubnetGroupName=DB_SUBNET_GROUP_NAME,
        VpcSecurityGroupIds=[docdb_sg_id],
        ServerlessV2ScalingConfiguration={"MinCapacity": 0.5, "MaxCapacity": 1.0},
        StorageEncrypted=True,
        BackupRetentionPeriod=1,
        Tags=TAGS,
    )
    print(f"Creando instancia '{INSTANCE_ID}' (db.serverless) en el cluster...")
    docdb.create_db_instance(
        DBInstanceIdentifier=INSTANCE_ID,
        DBInstanceClass="db.serverless",
        Engine="docdb",
        DBClusterIdentifier=CLUSTER_ID,
        Tags=TAGS,
    )
    print("  esperando a que la instancia quede 'available' (puede tardar varios minutos)...")
    docdb.get_waiter("db_instance_available").wait(DBInstanceIdentifier=INSTANCE_ID)

    cluster_info = docdb.describe_db_clusters(DBClusterIdentifier=CLUSTER_ID)["DBClusters"][0]
    endpoint = cluster_info["Endpoint"]
    secret_arn = cluster_info["MasterUserSecret"]["SecretArn"]
    print(f"  DocumentDB listo: {endpoint}")
    print(f"  secreto de la contrasena: {secret_arn}")
    return endpoint, secret_arn


def create():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    docdb = session.client("docdb")

    vpc_id, subnet_ids = get_default_vpc_and_subnets(ec2)
    bastion_sg_id, bastion_ip = create_bastion(ec2, vpc_id, subnet_ids[0])
    endpoint, secret_arn = create_docdb(ec2, docdb, vpc_id, subnet_ids, bastion_sg_id)

    print("\n=== Resumen ===")
    print(f"Bastion IP publica: {bastion_ip}")
    print(f"Llave SSH:          {KEY_FILE}")
    print(f"DocumentDB endpoint:{endpoint}")
    print(f"Secreto contrasena: {secret_arn}")
    print("\nComando para el tunel SSH:")
    print(f"  ssh -i {KEY_FILE} -L 27017:{endpoint}:27017 ec2-user@{bastion_ip}")


def destroy():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    docdb = session.client("docdb")

    try:
        docdb.delete_db_instance(DBInstanceIdentifier=INSTANCE_ID)
        print(f"Eliminando instancia '{INSTANCE_ID}', esperando...")
        docdb.get_waiter("db_instance_deleted").wait(DBInstanceIdentifier=INSTANCE_ID)
        print("  instancia eliminada.")
    except ClientError as e:
        print(f"  instancia: {e.response['Error']['Code']}")

    try:
        docdb.delete_db_cluster(DBClusterIdentifier=CLUSTER_ID, SkipFinalSnapshot=True)
        print(f"Eliminando cluster '{CLUSTER_ID}', esperando (docdb no tiene waiter para esto, hago polling manual)...")
        # botocore no trae un waiter "db_cluster_deleted" para DocumentDB, asi que espero a mano
        while True:
            try:
                status = docdb.describe_db_clusters(DBClusterIdentifier=CLUSTER_ID)["DBClusters"][0]["Status"]
                print(f"    estado: {status}")
                time.sleep(15)
            except ClientError as inner:
                if inner.response["Error"]["Code"] == "DBClusterNotFoundFault":
                    break
                raise
        print("  cluster eliminado.")
    except ClientError as e:
        print(f"  cluster: {e.response['Error']['Code']}")

    try:
        docdb.delete_db_subnet_group(DBSubnetGroupName=DB_SUBNET_GROUP_NAME)
        print("  db subnet group eliminado.")
    except ClientError as e:
        print(f"  db subnet group: {e.response['Error']['Code']}")

    reservations = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [BASTION_NAME]},
            {"Name": "instance-state-name", "Values": ["running", "stopped", "pending"]},
        ]
    )["Reservations"]
    instance_ids = [i["InstanceId"] for r in reservations for i in r["Instances"]]
    if instance_ids:
        print(f"Terminando bastion {instance_ids}...")
        ec2.terminate_instances(InstanceIds=instance_ids)
        ec2.get_waiter("instance_terminated").wait(InstanceIds=instance_ids)
        print("  bastion terminado.")
    else:
        print("  bastion: no se encontro (puede que ya este borrado).")

    for sg_name in (DOCDB_SG_NAME, BASTION_SG_NAME):
        try:
            sgs = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [sg_name]}])["SecurityGroups"]
            for sg in sgs:
                ec2.delete_security_group(GroupId=sg["GroupId"])
                print(f"  SG '{sg_name}' eliminado.")
        except ClientError as e:
            print(f"  SG '{sg_name}': {e.response['Error']['Code']}")

    try:
        ec2.delete_key_pair(KeyName=KEY_NAME)
        print(f"  key pair '{KEY_NAME}' eliminado de AWS.")
    except ClientError as e:
        print(f"  key pair: {e.response['Error']['Code']}")
    if os.path.exists(KEY_FILE):
        os.remove(KEY_FILE)
        print(f"  llave privada local borrada: {KEY_FILE}")

    print("\nDestroy completo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "destroy"])
    args = parser.parse_args()
    create() if args.action == "create" else destroy()
