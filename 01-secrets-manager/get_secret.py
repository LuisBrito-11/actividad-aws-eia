"""
Lee un secreto de AWS Secrets Manager por nombre (variable de entorno SECRET_NAME).
No hay credenciales de AWS en el codigo: boto3 usa la cadena de credenciales normal
(perfil user_cli via AWS_PROFILE, o variables de entorno / rol asumido).

Uso:
    AWS_PROFILE=user_cli SECRET_NAME=taller-aws-eia/punto1/demo-db-credentials \
        python get_secret.py
"""

import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-2")


def get_secret(secret_name: str) -> dict:
    client = boto3.client("secretsmanager", region_name=REGION)
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as error:
        # Se deja el codigo de error visible para diagnostico, sin filtrar detalles internos.
        print(f"Error al leer el secreto '{secret_name}': {error.response['Error']['Code']}")
        raise
    return json.loads(response["SecretString"])


def main() -> None:
    secret_name = os.environ.get("SECRET_NAME")
    if not secret_name:
        print("Falta la variable de entorno SECRET_NAME", file=sys.stderr)
        sys.exit(1)

    secret = get_secret(secret_name)
    print(f"Secreto '{secret_name}' leido correctamente:")
    print(f"  username: {secret.get('username')}")
    print(f"  password: {secret.get('password')}")


if __name__ == "__main__":
    main()
