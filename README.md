# Taller AWS — Ingeniería de Datos (Universidad EIA, 2026-2)

Entrega de la actividad "Taller AWS": Secrets Manager, Terraform/Boto3/CLI (S3+EC2+RDS), DocumentDB, Neptune, Redshift y Glue Data Catalog + Athena.

## Índice de puntos

| Punto | Servicio | Carpeta | Estado |
|---|---|---|---|
| 0 | Preparación (cuenta, perfil CLI, herramientas) | — | ✅ |
| 1 | AWS Secrets Manager | [01-secrets-manager/](01-secrets-manager/) | ✅ |
| 2 | Terraform + Boto3 + CLI (S3, EC2, RDS) | [02-terraform-sdk-cli/](02-terraform-sdk-cli/) | ✅ |
| 3 | Amazon DocumentDB | [03-documentdb/](03-documentdb/) | ✅ |
| 4 | Amazon Neptune | [04-neptune/](04-neptune/) | ✅ |
| 5 | Amazon Redshift | [05-redshift/](05-redshift/) | ✅ |
| 6 | AWS Glue Data Catalog + Athena | [06-glue-athena/](06-glue-athena/) | ✅ |

Cada carpeta tiene su propio README con objetivo, arquitectura, pasos de reproducción, preguntas respondidas, costos y evidencias.

## Prerequisitos

- AWS CLI v2, autenticado con perfil `user_cli` (`aws configure list --profile user_cli`).
- Terraform >= 1.16.
- Python 3.10+ con entorno virtual (`python -m venv .venv`, luego `pip install -r requirements.txt`).
- Git, cliente SSH.
- MongoDB Compass (Punto 3).

## Contexto de la cuenta

Cuenta AWS proporcionada por el profesor (usuario IAM `de-gr02-user-4` con permisos limitados, sin acceso root ni a IAM). Es una **cuenta compartida** entre varios estudiantes: todos los recursos de este taller están etiquetados `Project=taller-aws-eia` y `Owner=Luis Brito Rincon` para poder identificarlos y no interferir con recursos de otros. No fue posible crear una alerta de AWS Budgets (`budgets:ViewBudget` denegado) — por eso se es especialmente estricto en destruir todo recurso facturable al cerrar cada punto (ver evidencia de limpieza en cada carpeta `evidence/0X/`).

- Región usada para todo el taller: **us-east-2**.
- El perfil `user_cli` es un alias local (`~/.aws/config` / `credentials`) sobre las credenciales del usuario IAM entregado por el profesor; no se creó ningún usuario IAM nuevo en AWS.

## Seguridad

- Ninguna contraseña, access key ni token vive en el código o el repo. Las contraseñas de bases de datos se gestionan con AWS Secrets Manager y se recuperan en tiempo de ejecución.
- Antes de cada commit se corre `bash scripts/scan_secrets.sh`.
- `*.tfstate`, `*.pem`, `*.key`, `.env` y `*.tfvars` están en `.gitignore` y nunca se suben.

## Cómo reproducir

Instrucciones detalladas dentro de cada carpeta `0X-.../README.md`.
