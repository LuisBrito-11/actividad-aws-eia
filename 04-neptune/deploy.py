"""
Punto 4 - despliegue de Neptune (aprovisionado, db.t4g.medium) + EC2 bastion
para el tunel SSH. Mismo patron que el Punto 3 (DocumentDB).

Neptune no usa usuario/contrasena de base de datos por defecto (el acceso se
controla por red/security group, o por IAM SigV4 si se habilita), asi que
aqui no hay ningun secreto de Secrets Manager que crear.

Uso:
    AWS_PROFILE=user_cli python deploy.py create
    AWS_PROFILE=user_cli python deploy.py destroy
"""

import argparse
import os
import time
import urllib.request

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
PROJECT = "taller-aws-eia"
PUNTO = "4"
OWNER = "Luis Brito Rincon"

KEY_NAME = "taller-aws-eia-punto4-bastion-key"
KEY_FILE = os.path.join(os.path.dirname(__file__), f"{KEY_NAME}.pem")

BASTION_SG_NAME = "taller-aws-eia-punto4-bastion-sg"
NEPTUNE_SG_NAME = "taller-aws-eia-punto4-neptune-sg"
BASTION_NAME = "taller-aws-eia-punto4-bastion"

DB_SUBNET_GROUP_NAME = "taller-aws-eia-punto4-neptune-subnet-group"
CLUSTER_ID = "taller-aws-eia-punto4-neptune-cluster"
INSTANCE_ID = "taller-aws-eia-punto4-neptune-instance"

TAGS = [
    {"Key": "Project", "Value": PROJECT},
    {"Key": "Punto", "Value": PUNTO},
    {"Key": "Owner", "Value": OWNER},
]


def tag_spec(resource_type: str, extra_tags: list | None = None) -> list:
    return [{"ResourceType": resource_type, "Tags": TAGS + (extra_tags or [])}]


def get_my_ip() -> str:
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=5) as resp:
        return resp.read().decode().strip() + "/32"


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
    my_ip = get_my_ip()
    print(f"Mi IP publica actual: {my_ip}")

    print(f"Creando key pair '{KEY_NAME}'...")
    key = ec2.create_key_pair(KeyName=KEY_NAME, TagSpecifications=tag_spec("key-pair"))
    with open(KEY_FILE, "w") as f:
        f.write(key["KeyMaterial"])
    os.chmod(KEY_FILE, 0o400)

    print(f"Creando SG del bastion (SSH solo desde {my_ip})...")
    bastion_sg_id = ec2.create_security_group(
        GroupName=BASTION_SG_NAME,
        Description="SG del bastion EC2 (punto 4): SSH solo desde mi IP",
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
                "IpRanges": [{"CidrIp": my_ip, "Description": "Mi IP de casa"}],
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


def create_neptune(ec2, neptune, vpc_id: str, subnet_ids: list, bastion_sg_id: str) -> str:
    print("Creando SG de Neptune (8182 solo desde el SG del bastion)...")
    neptune_sg_id = ec2.create_security_group(
        GroupName=NEPTUNE_SG_NAME,
        Description="SG de Neptune (punto 4): solo acepta conexiones desde el bastion",
        VpcId=vpc_id,
        TagSpecifications=tag_spec("security-group"),
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=neptune_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 8182,
                "ToPort": 8182,
                "UserIdGroupPairs": [{"GroupId": bastion_sg_id}],
            }
        ],
    )
    print(f"  neptune SG: {neptune_sg_id}")

    neptune.create_db_subnet_group(
        DBSubnetGroupName=DB_SUBNET_GROUP_NAME,
        DBSubnetGroupDescription="Subnet group para Neptune (punto 4)",
        SubnetIds=subnet_ids,
        Tags=TAGS,
    )

    print(f"Creando cluster Neptune '{CLUSTER_ID}' (sin password, el acceso lo controla el security group)...")
    neptune.create_db_cluster(
        DBClusterIdentifier=CLUSTER_ID,
        Engine="neptune",
        DBSubnetGroupName=DB_SUBNET_GROUP_NAME,
        VpcSecurityGroupIds=[neptune_sg_id],
        StorageEncrypted=True,
        BackupRetentionPeriod=1,
        Tags=TAGS,
    )
    print(f"Creando instancia '{INSTANCE_ID}' (db.t4g.medium, aprovisionada) en el cluster...")
    neptune.create_db_instance(
        DBInstanceIdentifier=INSTANCE_ID,
        DBInstanceClass="db.t4g.medium",
        Engine="neptune",
        DBClusterIdentifier=CLUSTER_ID,
        Tags=TAGS,
    )
    print("  esperando a que la instancia quede 'available' (puede tardar varios minutos)...")
    neptune.get_waiter("db_instance_available").wait(DBInstanceIdentifier=INSTANCE_ID)

    cluster_info = neptune.describe_db_clusters(DBClusterIdentifier=CLUSTER_ID)["DBClusters"][0]
    endpoint = cluster_info["Endpoint"]
    print(f"  Neptune listo: {endpoint}")
    return endpoint


def create():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    neptune = session.client("neptune")

    vpc_id, subnet_ids = get_default_vpc_and_subnets(ec2)
    bastion_sg_id, bastion_ip = create_bastion(ec2, vpc_id, subnet_ids[0])
    endpoint = create_neptune(ec2, neptune, vpc_id, subnet_ids, bastion_sg_id)

    print("\n=== Resumen ===")
    print(f"Bastion IP publica: {bastion_ip}")
    print(f"Llave SSH:          {KEY_FILE}")
    print(f"Neptune endpoint:   {endpoint}")
    print("\nComando para el tunel SSH (puerto 8182, el de Neptune):")
    print(f"  ssh -i {KEY_FILE} -L 8182:{endpoint}:8182 ec2-user@{bastion_ip}")


def update_my_ip():
    """Actualiza la regla del SG del bastion si mi IP publica cambio."""
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    my_ip = get_my_ip()
    sgs = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [BASTION_SG_NAME]}])["SecurityGroups"]
    if not sgs:
        print("No encontre el SG del bastion, ¿ya desplegaste?")
        return
    sg = sgs[0]
    current_cidrs = {
        r["CidrIpv4"]
        for perm in sg["IpPermissions"]
        for r in perm.get("IpRanges", [])
        if perm.get("FromPort") == 22
    }
    if my_ip in current_cidrs:
        print(f"Mi IP ({my_ip}) ya esta autorizada, no hay que hacer nada.")
        return
    for old_cidr in current_cidrs:
        ec2.revoke_security_group_ingress(GroupId=sg["GroupId"], IpProtocol="tcp", FromPort=22, ToPort=22, CidrIp=old_cidr)
        print(f"  revocada IP vieja: {old_cidr}")
    ec2.authorize_security_group_ingress(GroupId=sg["GroupId"], IpProtocol="tcp", FromPort=22, ToPort=22, CidrIp=my_ip)
    print(f"  autorizada IP nueva: {my_ip}")


def destroy():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    neptune = session.client("neptune")

    try:
        neptune.delete_db_instance(DBInstanceIdentifier=INSTANCE_ID)
        print(f"Eliminando instancia '{INSTANCE_ID}', esperando...")
        neptune.get_waiter("db_instance_deleted").wait(DBInstanceIdentifier=INSTANCE_ID)
        print("  instancia eliminada.")
    except ClientError as e:
        print(f"  instancia: {e.response['Error']['Code']}")

    try:
        neptune.delete_db_cluster(DBClusterIdentifier=CLUSTER_ID, SkipFinalSnapshot=True)
        print(f"Eliminando cluster '{CLUSTER_ID}', esperando (polling manual, no hay waiter)...")
        while True:
            try:
                status = neptune.describe_db_clusters(DBClusterIdentifier=CLUSTER_ID)["DBClusters"][0]["Status"]
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
        neptune.delete_db_subnet_group(DBSubnetGroupName=DB_SUBNET_GROUP_NAME)
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

    for sg_name in (NEPTUNE_SG_NAME, BASTION_SG_NAME):
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
        try:
            os.remove(KEY_FILE)
            print(f"  llave privada local borrada: {KEY_FILE}")
        except PermissionError:
            print(f"  no pude borrar {KEY_FILE} (permiso denegado), borrar a mano.")

    print("\nDestroy completo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "destroy", "update-ip"])
    args = parser.parse_args()
    if args.action == "create":
        create()
    elif args.action == "destroy":
        destroy()
    else:
        update_my_ip()
