locals {
  common_tags = {
    Project = var.project_tag
    Punto   = var.punto_tag
    Owner   = var.owner_tag
  }
}

# Usamos la VPC por defecto: no hay razon para levantar una VPC propia
# en un ejercicio de una sola instancia EC2 y una sola instancia RDS.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

# --- S3 ---

resource "aws_s3_bucket" "demo" {
  bucket        = "taller-aws-eia-punto2-${random_id.suffix.hex}"
  force_destroy = true
  tags          = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "demo" {
  bucket                  = aws_s3_bucket.demo.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- Security groups ---

resource "aws_security_group" "ec2" {
  name        = "taller-aws-eia-punto2-ec2-sg"
  description = "SG minimo de la EC2 de prueba: sin ingreso, egreso abierto"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_security_group" "rds" {
  name        = "taller-aws-eia-punto2-rds-sg"
  description = "SG de RDS: solo acepta conexiones desde el SG de la EC2 de prueba"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_db_subnet_group" "demo" {
  name       = "taller-aws-eia-punto2-db-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
  tags       = local.common_tags
}

# --- EC2 ---

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "demo" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = "t3.micro"
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  associate_public_ip_address = false # evita el cargo por IPv4 publica; no necesitamos entrar por SSH en este punto

  tags = merge(local.common_tags, { Name = "taller-aws-eia-punto2-ec2" })
}

# --- RDS ---
# Contrasena administrada por Secrets Manager (manage_master_user_password):
# no queda ninguna contrasena en el tfstate ni en el codigo.

resource "aws_db_instance" "demo" {
  identifier                  = "taller-aws-eia-punto2-mysql"
  engine                      = "mysql"
  engine_version              = "8.0"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp2"
  username                    = var.db_username
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.demo.name
  vpc_security_group_ids      = [aws_security_group.rds.id]
  publicly_accessible         = false
  multi_az                    = false
  skip_final_snapshot         = true
  deletion_protection         = false
  apply_immediately           = true

  tags = local.common_tags
}
