#!/usr/bin/env bash
# Punto 2 - version AWS CLI: mismo stack (S3 + EC2 + RDS) que Terraform y Boto3,
# tambien sin ningun archivo de estado. Nombres fijos + tags para poder
# encontrar y destruir los recursos despues.
#
# Uso:
#   AWS_PROFILE=user_cli bash deploy.sh create
#   AWS_PROFILE=user_cli bash deploy.sh destroy

set -euo pipefail

REGION="us-east-2"
PROJECT="taller-aws-eia"
PUNTO="2"
OWNER="Luis Brito Rincon"

BUCKET_NAME="taller-aws-eia-punto2-cli"
EC2_SG_NAME="taller-aws-eia-punto2-cli-ec2-sg"
RDS_SG_NAME="taller-aws-eia-punto2-cli-rds-sg"
DB_SUBNET_GROUP_NAME="taller-aws-eia-punto2-cli-db-subnet-group"
DB_IDENTIFIER="taller-aws-eia-punto2-cli-mysql"
DB_USERNAME="tallerdbadmin"
EC2_NAME="taller-aws-eia-punto2-cli-ec2"

# JSON (no shorthand) porque OWNER trae espacios y el shorthand de la CLI los corta mal
TAGS_JSON='{"Key":"Project","Value":"'"$PROJECT"'"},{"Key":"Punto","Value":"'"$PUNTO"'"},{"Key":"Owner","Value":"'"$OWNER"'"},{"Key":"Method","Value":"cli"}'

aws_() {
  aws --profile "${AWS_PROFILE:-user_cli}" --region "$REGION" "$@"
}

create() {
  echo "Buscando VPC y subnets por defecto..."
  VPC_ID=$(aws_ ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text)
  SUBNET_ID=$(aws_ ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" --query "Subnets[0].SubnetId" --output text)
  SUBNET_ID_2=$(aws_ ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" --query "Subnets[1].SubnetId" --output text)
  SUBNET_ID_3=$(aws_ ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" --query "Subnets[2].SubnetId" --output text)
  echo "  VPC: $VPC_ID"

  echo "Creando bucket S3 '$BUCKET_NAME'..."
  aws_ s3api create-bucket --bucket "$BUCKET_NAME" \
    --create-bucket-configuration LocationConstraint="$REGION" > /dev/null
  aws_ s3api put-public-access-block --bucket "$BUCKET_NAME" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws_ s3api put-bucket-tagging --bucket "$BUCKET_NAME" --tagging "TagSet=[{Key=Project,Value=$PROJECT},{Key=Punto,Value=$PUNTO},{Key=Owner,Value=$OWNER},{Key=Method,Value=cli}]"
  echo "  bucket listo"

  echo "Creando security groups..."
  EC2_SG_ID=$(aws_ ec2 create-security-group --group-name "$EC2_SG_NAME" \
    --description "SG minimo de la EC2 de prueba (cli): sin ingreso" --vpc-id "$VPC_ID" \
    --tag-specifications "[{\"ResourceType\":\"security-group\",\"Tags\":[$TAGS_JSON]}]" --query "GroupId" --output text)
  RDS_SG_ID=$(aws_ ec2 create-security-group --group-name "$RDS_SG_NAME" \
    --description "SG de RDS (cli): solo acepta conexiones desde el SG de la EC2" --vpc-id "$VPC_ID" \
    --tag-specifications "[{\"ResourceType\":\"security-group\",\"Tags\":[$TAGS_JSON]}]" --query "GroupId" --output text)
  aws_ ec2 authorize-security-group-ingress --group-id "$RDS_SG_ID" \
    --protocol tcp --port 3306 --source-group "$EC2_SG_ID" > /dev/null
  echo "  EC2 SG: $EC2_SG_ID | RDS SG: $RDS_SG_ID"

  echo "Lanzando instancia EC2 (t3.micro, sin IP publica)..."
  AMI_ID=$(aws_ ec2 describe-images --owners amazon \
    --filters Name=name,Values="al2023-ami-*-x86_64" Name=virtualization-type,Values=hvm \
    --query "sort_by(Images, &CreationDate)[-1].ImageId" --output text)
  INSTANCE_ID=$(aws_ ec2 run-instances --image-id "$AMI_ID" --instance-type t3.micro \
    --network-interfaces "DeviceIndex=0,SubnetId=$SUBNET_ID,Groups=$EC2_SG_ID,AssociatePublicIpAddress=false" \
    --tag-specifications "[{\"ResourceType\":\"instance\",\"Tags\":[$TAGS_JSON,{\"Key\":\"Name\",\"Value\":\"$EC2_NAME\"}]}]" \
    --query "Instances[0].InstanceId" --output text)
  echo "  esperando a que '$INSTANCE_ID' quede 'running'..."
  aws_ ec2 wait instance-running --instance-ids "$INSTANCE_ID"
  echo "  EC2 lista: $INSTANCE_ID"

  echo "Creando RDS '$DB_IDENTIFIER' (db.t4g.micro, MySQL, contrasena en Secrets Manager)..."
  aws_ rds create-db-subnet-group --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" \
    --db-subnet-group-description "Subnet group para el stack de prueba (cli)" \
    --subnet-ids "$SUBNET_ID" "$SUBNET_ID_2" "$SUBNET_ID_3" \
    --tags "[$TAGS_JSON]" > /dev/null
  aws_ rds create-db-instance --db-instance-identifier "$DB_IDENTIFIER" \
    --engine mysql --engine-version 8.0 --db-instance-class db.t4g.micro \
    --allocated-storage 20 --storage-type gp2 \
    --master-username "$DB_USERNAME" --manage-master-user-password \
    --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" --vpc-security-group-ids "$RDS_SG_ID" \
    --no-publicly-accessible --no-multi-az --backup-retention-period 0 \
    --tags "[$TAGS_JSON]" > /dev/null
  echo "  esperando a que RDS quede 'available' (puede tardar varios minutos)..."
  aws_ rds wait db-instance-available --db-instance-identifier "$DB_IDENTIFIER"
  ENDPOINT=$(aws_ rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" --query "DBInstances[0].Endpoint.Address" --output text)
  SECRET_ARN=$(aws_ rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" --query "DBInstances[0].MasterUserSecret.SecretArn" --output text)
  echo "  RDS lista: $ENDPOINT"
  echo "  secreto de la contrasena: $SECRET_ARN"

  echo ""
  echo "=== Resumen ==="
  echo "Bucket S3:  $BUCKET_NAME"
  echo "EC2:        $INSTANCE_ID"
  echo "RDS:        $ENDPOINT"
}

destroy() {
  echo "Eliminando RDS '$DB_IDENTIFIER' (si existe)..."
  if aws_ rds delete-db-instance --db-instance-identifier "$DB_IDENTIFIER" \
      --skip-final-snapshot --delete-automated-backups > /dev/null 2>&1; then
    echo "  esperando a que se elimine..."
    aws_ rds wait db-instance-deleted --db-instance-identifier "$DB_IDENTIFIER"
    echo "  RDS eliminada."
  else
    echo "  RDS: no existe o ya se elimino."
  fi

  aws_ rds delete-db-subnet-group --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" 2>/dev/null \
    && echo "  DB subnet group eliminado." || echo "  DB subnet group: no existe o ya se elimino."

  echo "Buscando instancias EC2 con tag Name=$EC2_NAME..."
  INSTANCE_IDS=$(aws_ ec2 describe-instances \
    --filters "Name=tag:Name,Values=$EC2_NAME" "Name=instance-state-name,Values=running,stopped,pending" \
    --query "Reservations[].Instances[].InstanceId" --output text)
  if [ -n "$INSTANCE_IDS" ]; then
    echo "  terminando: $INSTANCE_IDS"
    aws_ ec2 terminate-instances --instance-ids $INSTANCE_IDS > /dev/null
    aws_ ec2 wait instance-terminated --instance-ids $INSTANCE_IDS
    echo "  EC2 terminada."
  else
    echo "  EC2: no se encontro ninguna con ese tag."
  fi

  for SG_NAME in "$RDS_SG_NAME" "$EC2_SG_NAME"; do
    SG_ID=$(aws_ ec2 describe-security-groups --filters Name=group-name,Values="$SG_NAME" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "None")
    if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
      aws_ ec2 delete-security-group --group-id "$SG_ID" && echo "  SG '$SG_NAME' eliminado."
    else
      echo "  SG '$SG_NAME': no existe o ya se elimino."
    fi
  done

  echo "Vaciando y eliminando bucket '$BUCKET_NAME' (si existe)..."
  if aws_ s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
    aws_ s3 rm "s3://$BUCKET_NAME" --recursive > /dev/null
    aws_ s3api delete-bucket --bucket "$BUCKET_NAME"
    echo "  bucket eliminado."
  else
    echo "  bucket: no existe o ya se elimino."
  fi

  echo ""
  echo "Destroy completo."
}

case "${1:-}" in
  create) create ;;
  destroy) destroy ;;
  *) echo "Uso: $0 {create|destroy}"; exit 1 ;;
esac
