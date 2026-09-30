"""
Punto 3 - conexion a DocumentDB desde Python (via tunel SSH en localhost:27017),
insercion de documentos y consultas (filtro, orden, agregacion).

La contrasena se recupera de Secrets Manager en tiempo de ejecucion, nunca
esta escrita en este archivo.

Uso (con el tunel SSH ya levantado en 127.0.0.1:27017):
    AWS_PROFILE=user_cli python queries.py
"""

import json
import os

import boto3
import pymongo

REGION = "us-east-2"
SECRET_ARN = "arn:aws:secretsmanager:us-east-2:802655955683:secret:rds!cluster-7e7cfc03-2176-4fde-b942-2c7e76ce888c-QaLd2G"
CA_FILE = os.path.join(os.path.dirname(__file__), "global-bundle.pem")


def get_db_credentials() -> dict:
    client = boto3.client("secretsmanager", region_name=REGION)
    value = client.get_secret_value(SecretId=SECRET_ARN)
    return json.loads(value["SecretString"])


def main() -> None:
    creds = get_db_credentials()
    username = creds["username"]
    password = creds["password"]

    # tlsAllowInvalidHostnames=true porque el certificado es del hostname real
    # de DocumentDB, pero por el tunel SSH nos conectamos a 127.0.0.1
    uri = (
        f"mongodb://{username}:{password}@127.0.0.1:27017/"
        "?tls=true&retryWrites=false&directConnection=true&tlsAllowInvalidHostnames=true"
    )
    client = pymongo.MongoClient(uri, tlsCAFile=CA_FILE, serverSelectionTimeoutMS=10000)

    db = client["taller_aws_eia"]
    coll = db["estudiantes"]
    coll.delete_many({})  # por si se corre el script varias veces

    documentos = [
        {"nombre": "Ana", "programa": "Ing. de Datos", "semestre": 6, "promedio": 4.3},
        {"nombre": "Luis", "programa": "Ing. de Datos", "semestre": 8, "promedio": 4.6},
        {"nombre": "Maria", "programa": "Ing. de Sistemas", "semestre": 4, "promedio": 3.9},
        {"nombre": "Carlos", "programa": "Ing. de Sistemas", "semestre": 10, "promedio": 4.1},
        {"nombre": "Sofia", "programa": "Ing. de Datos", "semestre": 2, "promedio": 4.0},
        {"nombre": "Pedro", "programa": "Ing. Biomedica", "semestre": 6, "promedio": 3.7},
        {"nombre": "Laura", "programa": "Ing. de Datos", "semestre": 9, "promedio": 4.8},
        {"nombre": "Diego", "programa": "Ing. Biomedica", "semestre": 3, "promedio": 3.5},
        {"nombre": "Valentina", "programa": "Ing. de Sistemas", "semestre": 7, "promedio": 4.4},
        {"nombre": "Andres", "programa": "Ing. de Datos", "semestre": 5, "promedio": 4.2},
        {"nombre": "Camila", "programa": "Ing. Biomedica", "semestre": 8, "promedio": 4.0},
    ]
    result = coll.insert_many(documentos)
    print(f"Insertados {len(result.inserted_ids)} documentos en 'taller_aws_eia.estudiantes'.")

    print("\n--- Filtro: estudiantes de Ing. de Datos con promedio >= 4.2 ---")
    for doc in coll.find(
        {"programa": "Ing. de Datos", "promedio": {"$gte": 4.2}},
        {"_id": 0},
    ):
        print(doc)

    print("\n--- Ordenacion: todos los estudiantes por promedio descendente ---")
    for doc in coll.find({}, {"_id": 0, "nombre": 1, "promedio": 1}).sort("promedio", -1):
        print(doc)

    print("\n--- Agregacion: promedio de nota y conteo de estudiantes por programa ---")
    pipeline = [
        {
            "$group": {
                "_id": "$programa",
                "promedio_del_programa": {"$avg": "$promedio"},
                "cantidad_estudiantes": {"$sum": 1},
            }
        },
        {"$sort": {"promedio_del_programa": -1}},
    ]
    for doc in coll.aggregate(pipeline):
        print(doc)

    client.close()


if __name__ == "__main__":
    main()
