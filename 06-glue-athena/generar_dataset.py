"""
Punto 6 - genera productos.csv (25 filas, >= 20 pedidos). A proposito dejo
un par de columnas con formato ambiguo (fecha como texto DD/MM/YYYY,
en_oferta como Si/No en vez de booleano) para tener algo real que corregir
en el esquema que infiera el crawler.
"""

import csv
import random
from pathlib import Path

random.seed(7)

OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

PRODUCTOS = [
    ("Laptop 14 pulgadas", "Electronica"), ("Mouse inalambrico", "Electronica"),
    ("Teclado mecanico", "Electronica"), ("Monitor 24 pulgadas", "Electronica"),
    ("Audifonos bluetooth", "Electronica"), ("Camiseta algodon", "Ropa"),
    ("Pantalon jean", "Ropa"), ("Chaqueta impermeable", "Ropa"),
    ("Tenis running", "Deportes"), ("Balon de futbol", "Deportes"),
    ("Mancuernas 5kg", "Deportes"), ("Colchoneta yoga", "Deportes"),
    ("Sofa 3 puestos", "Hogar"), ("Lampara de mesa", "Hogar"),
    ("Juego de ollas", "Hogar"), ("Aspiradora", "Hogar"),
    ("Novela de misterio", "Libros"), ("Libro de cocina", "Libros"),
    ("Comic coleccionable", "Libros"), ("Set de bloques", "Juguetes"),
    ("Muneca articulada", "Juguetes"), ("Carro a control remoto", "Juguetes"),
    ("Rompecabezas 500 piezas", "Juguetes"), ("Bicicleta montana", "Deportes"),
    ("Cafetera electrica", "Hogar"),
]


def main():
    filas = []
    for i, (nombre, categoria) in enumerate(PRODUCTOS, start=1):
        precio = round(random.uniform(15000, 2500000), 2)
        stock = random.randint(0, 200)
        dia = random.randint(1, 28)
        mes = random.randint(1, 12)
        fecha_lanzamiento = f"{dia:02d}/{mes:02d}/2024"  # texto DD/MM/YYYY a proposito
        en_oferta = random.choice(["Si", "No"])  # texto a proposito, no booleano
        filas.append([i, nombre, categoria, precio, stock, fecha_lanzamiento, en_oferta])

    path = OUT_DIR / "productos.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["product_id", "nombre", "categoria", "precio", "stock", "fecha_lanzamiento", "en_oferta"])
        writer.writerows(filas)
    print(f"productos.csv: {len(filas)} filas -> {path}")


if __name__ == "__main__":
    main()
