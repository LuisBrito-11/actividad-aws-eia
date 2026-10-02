"""
Punto 4 - modelo de grafo (personas, empresas, ciudades), insercion por
Gremlin y 3 consultas que recorren relaciones (multi-salto).

Neptune no pide usuario/contrasena: el acceso lo controla el security group
(solo el bastion le puede hablar al puerto 8182), asi que no hay ningun
secreto de Secrets Manager que recuperar aqui.

Conecto via el tunel SSH (localhost:8182). TLS esta activo por defecto en
Neptune, pero como voy por localhost el hostname del certificado no
coincide -> desactivo la verificacion de hostname/CA (mismo caso que
DocumentDB en el punto 3, solo que aqui no hay bundle de CA que usar porque
Neptune no ofrece uno propio para este escenario de tunel).

Uso (con el tunel SSH ya levantado en 127.0.0.1:8182):
    python queries.py
"""

import ssl

from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __
from gremlin_python.process.traversal import P, T

ENDPOINT = "wss://localhost:8182/gremlin"


def connect():
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    conn = DriverRemoteConnection(ENDPOINT, "g", ssl_options=ssl_context)
    return traversal().with_remote(conn), conn


def limpiar(g):
    g.V().drop().iterate()


def cargar_grafo(g):
    personas = ["Ana", "Luis", "Maria", "Carlos", "Sofia", "Pedro"]
    empresas = ["TechCorp", "DataSoft", "CloudWorks"]
    ciudades = ["Medellin", "Bogota", "Cali"]

    for nombre in personas:
        g.add_v("person").property("name", nombre).iterate()
    for nombre in empresas:
        g.add_v("company").property("name", nombre).iterate()
    for nombre in ciudades:
        g.add_v("city").property("name", nombre).iterate()

    def v(nombre):
        return __.V().has("name", nombre)

    # WORKS_AT: cada persona trabaja en una empresa (6 aristas)
    trabajos = [
        ("Ana", "TechCorp"), ("Luis", "TechCorp"),
        ("Maria", "DataSoft"), ("Carlos", "DataSoft"),
        ("Sofia", "CloudWorks"), ("Pedro", "CloudWorks"),
    ]
    for persona, empresa in trabajos:
        g.V().has("name", persona).add_e("WORKS_AT").to(v(empresa)).iterate()

    # LIVES_IN: cada persona vive en una ciudad (6 aristas)
    vive_en = [
        ("Ana", "Medellin"), ("Luis", "Medellin"),
        ("Maria", "Bogota"), ("Carlos", "Bogota"),
        ("Sofia", "Cali"), ("Pedro", "Cali"),
    ]
    for persona, ciudad in vive_en:
        g.V().has("name", persona).add_e("LIVES_IN").to(v(ciudad)).iterate()

    # LOCATED_IN: cada empresa esta en una ciudad (3 aristas)
    ubicada_en = [("TechCorp", "Medellin"), ("DataSoft", "Bogota"), ("CloudWorks", "Cali")]
    for empresa, ciudad in ubicada_en:
        g.V().has("name", empresa).add_e("LOCATED_IN").to(v(ciudad)).iterate()

    # KNOWS: red de amistad entre personas (6 aristas, direccionales)
    conoce_a = [
        ("Ana", "Luis"), ("Ana", "Maria"), ("Luis", "Carlos"),
        ("Maria", "Sofia"), ("Carlos", "Pedro"), ("Sofia", "Pedro"),
    ]
    for p1, p2 in conoce_a:
        g.V().has("name", p1).add_e("KNOWS").to(v(p2)).iterate()

    total_v = g.V().count().next()
    total_e = g.E().count().next()
    print(f"Grafo cargado: {total_v} vertices, {total_e} aristas.")


def consultas(g):
    print("\n--- Consulta 1: amigos de amigos de Ana (2 saltos por KNOWS) ---")
    amigos_directos = g.V().has("name", "Ana").out("KNOWS").values("name").to_list()
    print(f"  amigos directos de Ana: {amigos_directos}")
    amigos_de_amigos = (
        g.V().has("name", "Ana")
        .out("KNOWS").out("KNOWS")
        .dedup()
        .values("name")
        .to_list()
    )
    print(f"  amigos de amigos (2 saltos, puede incluir directos/Ana): {amigos_de_amigos}")

    print("\n--- Consulta 2: en que ciudad queda la empresa de cada persona (camino persona -> empresa -> ciudad) ---")
    resultados = (
        g.V().has_label("person")
        .project("persona", "empresa", "ciudad_de_la_empresa")
        .by("name")
        .by(__.out("WORKS_AT").values("name"))
        .by(__.out("WORKS_AT").out("LOCATED_IN").values("name"))
        .to_list()
    )
    for r in resultados:
        print(f"  {r}")

    print("\n--- Consulta 3: compañeros de trabajo (personas conectadas por trabajar en la misma empresa) ---")
    companeros = (
        g.V().has_label("person").as_("p1")
        .out("WORKS_AT").in_("WORKS_AT")
        .where(P.neq("p1"))
        .as_("p2")
        .select("p1", "p2")
        .by("name")
        .dedup()
        .to_list()
    )
    for c in companeros:
        print(f"  {c}")


def main():
    g, conn = connect()
    try:
        limpiar(g)
        cargar_grafo(g)
        consultas(g)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
