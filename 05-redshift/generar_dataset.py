"""
Punto 5 - genera el dataset de prueba: customers.csv (200 filas) y
orders.csv (500 filas, relacionadas por customer_id). Sin librerias
externas de generacion de datos (Faker, etc.), solo listas fijas + random.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)  # reproducible

OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

NOMBRES = [
    "Ana", "Luis", "Maria", "Carlos", "Sofia", "Pedro", "Laura", "Diego",
    "Valentina", "Andres", "Camila", "Juan", "Isabella", "Santiago", "Mariana",
    "Felipe", "Daniela", "Alejandro", "Gabriela", "Nicolas",
]
APELLIDOS = [
    "Gomez", "Rodriguez", "Martinez", "Lopez", "Garcia", "Perez", "Sanchez",
    "Ramirez", "Torres", "Flores", "Castro", "Vargas", "Ortiz", "Rojas",
]
CIUDADES = ["Medellin", "Bogota", "Cali", "Barranquilla", "Bucaramanga", "Pereira"]
CATEGORIAS = ["Electronica", "Hogar", "Ropa", "Deportes", "Libros", "Juguetes"]

N_CUSTOMERS = 200
N_ORDERS = 500


def generar_customers():
    filas = []
    for customer_id in range(1, N_CUSTOMERS + 1):
        nombre = f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)}"
        ciudad = random.choice(CIUDADES)
        email = f"cliente{customer_id}@correo-prueba.com"
        fecha_registro = date(2024, 1, 1) + timedelta(days=random.randint(0, 700))
        filas.append([customer_id, nombre, email, ciudad, fecha_registro.isoformat()])

    path = OUT_DIR / "customers.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["customer_id", "nombre", "email", "ciudad", "fecha_registro"])
        writer.writerows(filas)
    print(f"customers.csv: {len(filas)} filas -> {path}")


def generar_orders():
    filas = []
    for order_id in range(1, N_ORDERS + 1):
        customer_id = random.randint(1, N_CUSTOMERS)
        categoria = random.choice(CATEGORIAS)
        monto = round(random.uniform(10000, 500000), 2)
        fecha_orden = date(2024, 6, 1) + timedelta(days=random.randint(0, 400))
        filas.append([order_id, customer_id, categoria, monto, fecha_orden.isoformat()])

    path = OUT_DIR / "orders.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "customer_id", "categoria", "monto", "fecha_orden"])
        writer.writerows(filas)
    print(f"orders.csv: {len(filas)} filas -> {path}")


if __name__ == "__main__":
    generar_customers()
    generar_orders()
