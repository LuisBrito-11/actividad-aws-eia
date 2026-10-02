# Punto 6 — AWS Glue Data Catalog + Athena

## Objetivo

Subir un dataset a S3, descubrirlo con un crawler de Glue, corregir el esquema inferido, consultarlo desde Athena (filtro + agrupación), agregar registros y verificar que el catálogo se actualiza, y comparar crawler vs tabla manual.

## Qué guarda el Data Catalog

El Data Catalog **no guarda datos**, solo **metadatos**: nombres de bases/tablas, columnas y sus tipos, ubicación en S3, formato del archivo (CSV, Parquet, etc.). Los datos reales siempre viven en S3; el catálogo es el "índice" que le dice a Athena (o a Glue ETL, o a Redshift Spectrum) dónde están y cómo leerlos.

- **Base de datos**: agrupador lógico de tablas (como un namespace).
- **Tabla**: metadatos de un dataset — apunta a una ruta de S3 y describe su esquema (columnas/tipos).
- **Crawler**: programa que recorre una ruta de S3, infiere el esquema (lee una muestra de los archivos) y crea/actualiza automáticamente la tabla en el catálogo.

## Qué hice

1. Generé `data/productos.csv` (25 filas) con dos columnas a propósito "sucias": `fecha_lanzamiento` en formato texto `DD/MM/YYYY`, y `en_oferta` con valores `Si`/`No` en vez de booleano real.
2. Subí el CSV a S3 y creé la base de datos del catálogo (`taller_aws_eia_punto6`).
3. **Rol IAM para el crawler**: pedí ayuda al profesor otra vez (mismo patrón de los puntos 2-5), pero esta vez terminé con `iam:CreateRole` habilitado para mi usuario — lo creé yo mismo, le adjunté la política administrada `AWSGlueServiceRole` (es la única que me dejan adjuntar; `iam:AttachRolePolicy` me lo dejan usar solo con esa política puntual, lo confirmé intentando con `AmazonS3ReadOnlyAccess` y me lo negó).
4. **Problema real que encontré**: `AWSGlueServiceRole` solo da `s3:GetObject` sobre rutas que contienen literalmente `aws-glue-` en el nombre (bucket o carpeta) — lo until revisé en el JSON de la política. Por eso subí los datos a `s3://.../aws-glue-productos/` en vez de un nombre cualquiera: así el rol sí puede leerlos sin necesitar una política adicional que no me dejan adjuntar.
5. Corrí el crawler. Esquema inferido:

   | Columna | Tipo inferido | ¿Correcto? |
   |---|---|---|
   | product_id | bigint | Sí |
   | nombre | string | Sí |
   | categoria | string | Sí |
   | precio | double | Sí |
   | stock | bigint | Sí |
   | fecha_lanzamiento | string | **No** — es una fecha, pero el formato `DD/MM/YYYY` no lo reconoce el clasificador de Glue |
   | en_oferta | string | **No** — debería ser booleano, pero `Si`/`No` no son literales booleanos reconocidos |

6. **Corrección**: en vez de forzar el tipo en el catálogo (ver el hallazgo de la comparación abajo, eso pierde datos), corregí en la consulta de Athena con `date_parse(fecha_lanzamiento, '%d/%m/%Y')` y `CASE WHEN en_oferta = 'Si' THEN true ELSE false END`.
7. Corrí 2 consultas con Athena: un filtro y una agrupación.
8. Agregué 3 productos nuevos (`productos_nuevos.csv`, mismo prefijo S3), volví a correr el crawler, y confirmé con `SELECT COUNT(*)` que pasó de 25 a **28 filas** sin tocar nada más.
9. **Crawler vs tabla manual**: creé una tabla manual (`CreateTable` directo, sin crawler) declarando a mano `fecha_lanzamiento=date` y `en_oferta=boolean` — los tipos que "deberían ser". Al consultarla, esas dos columnas salieron **`NULL` en todas las filas**, sin ningún error. El SerDe de Athena no pudo parsear `"13/11/2024"` como `date` ni `"Si"` como `boolean`, y en vez de fallar, simplemente descarta el valor. El crawler, al ser conservador e inferir `string` cuando no está seguro, **preserva el dato crudo** y permite corregirlo a propósito en la consulta — mucho más seguro que adivinar mal a mano.

Código: [`generar_dataset.py`](generar_dataset.py), [`deploy.py`](deploy.py). Evidencia: [`../evidence/06/`](../evidence/06/).

## ¿Hace falta algún secreto de Secrets Manager?

**No.** Todo este punto funciona con permisos IAM normales sobre S3, Glue y Athena — no hay ninguna base de datos con usuario/contraseña de por medio, el acceso lo controla directamente la política adjunta a mi rol/usuario. Esto cambiaría si en vez de Athena/S3 me conectara a este dataset vía **JDBC** desde una herramienta externa (por ejemplo, un BI conectado a Athena con usuario/contraseña, o una conexión de Glue a una base de datos relacional externa) — ahí sí tocaría guardar esas credenciales en Secrets Manager, porque ya no sería autenticación nativa de AWS sino un login a un sistema aparte.

## Preguntas de costos

Precios verificados con la AWS Pricing API (región us-east-2, consultado 2026-10-02):

- **Crawler**: se cobra por **DPU-hora** ($0.44/DPU-hora), con un mínimo de 10 minutos de facturación por corrida. Cada corrida de mi crawler (un CSV de unos KB) tomó muy poco tiempo real, pero el mínimo de 10 min aplica igual — dos corridas completas en este punto, costo total estimado bajo $0.15.
- **Catálogo**: $1 por cada 100.000 objetos (tablas/particiones) por mes — con 1-2 tablas, el costo es $0.00002/mes, literalmente despreciable.
- **S3**: centavos de centavo por el tamaño del CSV (unos KB) + las peticiones del crawler.
- **Athena**: **$5 por TB escaneado**. Mis consultas escanearon un CSV de pocos KB — muy por debajo de cualquier redondeo visible en la factura.
- **Efecto del volumen escaneado**: con datasets grandes, usar **Parquet en vez de CSV** (columnar, comprimido) reduce drásticamente los bytes escaneados porque Athena solo lee las columnas que la consulta pide; **particionar** por fecha/categoría permite que Athena descarte carpetas enteras sin leerlas (`WHERE categoria = 'X'` con partición por categoría no escanea las demás); y hacer `SELECT` de columnas específicas en vez de `SELECT *` reduce los bytes leídos incluso en formato columnar. En mi caso (CSV sin particiones, dataset de prueba) no importa, pero en un dataset de producción de cientos de GB es la diferencia entre pagar centavos o cientos de dólares por consulta.

## Checklist de cierre

- [x] Dataset con ≥20 registros subido a S3.
- [x] Base de datos y crawler de Glue, esquema revisado y errores identificados.
- [x] Corrección de los tipos mal inferidos (fecha, booleano) aplicada en las consultas.
- [x] Consultas con filtro y agrupación en Athena.
- [x] Registros agregados, crawler re-ejecutado, catálogo actualizado y verificado (25 → 28 filas).
- [x] Comparación real crawler vs tabla manual, con hallazgo concreto (pérdida silenciosa de datos).
- [x] Explicación de por qué no hace falta un secreto adicional.
- [x] Preguntas de costos respondidas con precios verificados.
- [x] Recursos destruidos + verificación: crawler, base de datos, workgroup de Athena y bucket confirmados eliminados ([`../evidence/06/04_destroy_verificacion.txt`](../evidence/06/04_destroy_verificacion.txt)).
- [ ] Rol IAM (`taller-aws-eia-punto6-glue-crawler-role`): no lo pude borrar yo (`iam:DeleteRole`/`DetachRolePolicy` denegados). Sin costo (los roles IAM son gratis), pendiente de que el profesor lo elimine si lo considera necesario.
