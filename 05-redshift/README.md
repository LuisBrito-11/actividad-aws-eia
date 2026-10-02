# Punto 5 — Amazon Redshift

## Objetivo

Desplegar Redshift de bajo costo, cargar un dataset de 2 tablas relacionadas desde S3 con `COPY`, y ejecutar consultas (filtro, JOIN, agregación) vía Redshift Data API, con la contraseña gestionada por Secrets Manager.

## Qué es Redshift

Redshift es el data warehouse de AWS: una base de datos **columnar** (guarda los datos por columna, no por fila) pensada para **OLAP** (Online Analytical Processing) — consultas que agregan y escanean muchas filas de pocas columnas, típico de reportes y analítica, no transacciones puntuales. Usa arquitectura **MPP** (Massively Parallel Processing): varios nodos de cómputo procesan la consulta en paralelo, coordinados por un nodo líder que reparte el trabajo y junta los resultados.

**Componentes principales:**
- **Modo aprovisionado**: nodo líder (planifica y coordina) + nodos de cómputo (guardan datos y ejecutan).
- **Modo Serverless**: en vez de nodos fijos, hay un **namespace** (los datos: bases, tablas, permisos, snapshots) y un **workgroup** (la capacidad de cómputo que lo sirve, medida en RPUs).

## Redshift vs RDS

| | Redshift | RDS |
|---|---|---|
| Tipo de carga | OLAP (analítica, agregaciones sobre muchas filas) | OLTP (transacciones puntuales, lecturas/escrituras pequeñas y frecuentes) |
| Almacenamiento | Columnar | Por filas |
| Caso de uso | Dashboard de ventas que agrega millones de pedidos por mes/categoría/ciudad | Sistema de checkout de una tienda online, que inserta/actualiza un pedido a la vez |

Uso Redshift cuando necesito agregar/analizar grandes volúmenes; uso RDS cuando necesito muchas transacciones pequeñas con baja latencia (como ya hice en el Punto 2).

## Serverless vs aprovisionado — con números

Precios verificados con la AWS Pricing API (región us-east-2, consultado 2026-10-02):

| Opción | Precio |
|---|---|
| Provisionado más chico (`dc2.large`, single-node, storage incluido) | **$0.25/hora** |
| Serverless, capacidad base mínima **4 RPU** | $0.36/RPU-hora × 4 = **$1.44/hora** mientras hay consultas activas |

A primera vista parece que gana el provisionado, pero **Redshift Serverless solo cobra cuando hay consultas corriendo** (confirmé esto en la documentación oficial de facturación: *"A query or transaction is only metered and recorded after it completes"*, con un mínimo de 60 segundos por consulta) — no cobra por capacidad reservada inactiva. Para esta práctica (carga puntual + 3 consultas cortas, el resto del tiempo sin actividad), el costo real de Serverless termina siendo unos pocos minutos de RPU-hora, más barato en la práctica que dejar un cluster aprovisionado encendido por horas sin necesitarlo todo ese tiempo.

**Terminé usando Serverless** porque así quedó configurado el namespace compartido de la clase (ver sección siguiente), con el *price-performance target* en "Optimizes for cost" — el ajuste correcto para este caso de uso puntual.

## IAM: namespace compartido y el camino hasta llegar aquí

Como en los puntos anteriores, mi usuario no tiene ningún permiso IAM (`iam:CreateRole` denegado). Este punto necesitaba además un **rol que Redshift pudiera asumir para leer S3** (requisito de `COPY`), así que le pedí al profesor que lo creara.

Lo que pasó en la práctica, en orden:
1. El profesor creó el rol `AmazonRedshift-CommandsAccessRole-...`, pero yo no tenía `iam:PassRole` sobre ese ARN — no podía asociarlo yo mismo a un cluster propio.
2. Para resolverlo, el profesor creó directamente un **namespace y workgroup Serverless compartidos** (`default-namespace`/`default-workgroup`) con el rol ya asociado desde su lado — así no necesito `PassRole` en ningún momento, porque la asociación ya la hizo él.
3. El namespace venía con capacidad base fija en 128 RPU (el default de AWS, no el mínimo de 4) — lo señalé porque a esa capacidad cada consulta corta sale cara. El profesor lo cambió a **escalado automático por precio-rendimiento** (sin piso fijo), la opción correcta para este caso.
4. Hubo un secreto (`taller-redshift-credenciales`) cuya contraseña no coincidía con la del namespace; until se sincronizó con la contraseña real que está usando el curso, actualicé yo mismo el valor del secreto (`put-secret-value`) para que calzara.

**Por ser un namespace compartido con el resto de la clase**, no creé tablas sueltas: todo lo mío vive en un schema propio, **`degr02user4_punto5`** (nombrado con mi usuario para no chocar con el de otro estudiante), y al destruir solo elimino ese schema y mi bucket — nunca toco el namespace/workgroup/secreto compartidos.

## Dataset

Generé `customers.csv` (200 filas) y `orders.csv` (500 filas, relacionadas por `customer_id`) con `generar_dataset.py` — datos ficticios, sin librerías externas de generación. Están en [`data/`](data/).

## Qué hice

1. Subí el dataset a S3 (`taller-aws-eia-punto5-dataset`).
2. Creé el schema y las tablas `customers`/`orders` vía Redshift Data API (`execute_statement`, polling con `describe_statement`, resultados con `get_statement_result` — nunca una contraseña en el código, todo autenticado con el `SecretArn`).
3. Cargué los datos con `COPY ... IAM_ROLE '...'` desde S3.
4. Corrí 3 consultas (ver abajo).
5. Destruí solo lo mío (schema + bucket).

Código: [`generar_dataset.py`](generar_dataset.py), [`deploy.py`](deploy.py). Evidencia: [`../evidence/05/01_load_output.txt`](../evidence/05/01_load_output.txt), [`../evidence/05/02_query_output.txt`](../evidence/05/02_query_output.txt).

## Las 3 consultas — qué responden e interpretación

| Consulta | Pregunta de negocio | Lo que encontré |
|---|---|---|
| **Filtro**: pedidos de Electrónica > $300.000 | ¿Cuáles son los pedidos grandes de la categoría más cara de reponer? | El pedido más alto fue de $499.790 — útil para priorizar atención a pedidos de alto valor. |
| **JOIN + agregación**: gasto total por cliente | ¿Quiénes son mis clientes más valiosos? | El cliente #143 (Nicolas Castro, Cali) gastó $2.335.927 en 8 pedidos — candidato a programa de fidelización. |
| **Agregación**: ventas y ticket promedio por ciudad | ¿Qué ciudad vende más, y dónde gasta más cada cliente en promedio? | Pereira tuvo más pedidos (87) pero Bogotá tuvo el ticket promedio más alto ($282.627) — con menos pedidos, Bogotá genera compras más grandes por transacción. |

## Preguntas de costos

- **Qué modalidad cuesta menos**: Serverless con escalado por costo, porque solo cobra durante las consultas activas (mínimo 60 segundos cada una) — para una práctica puntual como esta, mucho más barato que un cluster aprovisionado encendido todo el tiempo que dura el ejercicio.
- **Cómo se cobran cómputo y almacenamiento**: cómputo en RPU-hora (por segundo, con mínimo de 60s por consulta); almacenamiento (Redshift Managed Storage) por GB-mes, facturado aparte del cómputo.
- **Qué podría seguir cobrando después**: si el namespace/workgroup quedan creados (aunque sea compartido y gestionado por el profesor), el storage de lo que haya cargado sigue sumando GB-mes; los snapshots automáticos también se cobran por GB-mes si se acumulan.

## Checklist de cierre

- [x] Dataset de 2 tablas relacionadas (`customers`, `orders`), en el repo.
- [x] Carga vía S3 + `COPY`, sin contraseña en el código (Secrets Manager + rol IAM).
- [x] 3 consultas (filtro, JOIN, agregación) vía Redshift Data API, interpretadas.
- [x] Comparación conceptual con RDS (OLAP vs OLTP, caso de uso para cada uno).
- [x] Preguntas de costos respondidas con precios verificados.
- [x] Bucket S3 propio eliminado y verificado.
- [x] Schema propio (`degr02user4_punto5`): no lo pude limpiar directamente (el secreto compartido desapareció antes de correr el `destroy`), pero quedó resuelto de todas formas porque el namespace/workgroup compartido completo se eliminó después (coordinado con mi compañero que también lo usaba) — confirmado con `get-workgroup`/`get-namespace`.
- [x] Snapshot manual que creé (`taller-aws-eia-base-capacity-fix`, para poder bajar la capacidad base) eliminado y verificado.
