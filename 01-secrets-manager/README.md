# Punto 1 — AWS Secrets Manager

## Objetivo

Crear un secreto de prueba, leerlo desde una aplicación (Python/Boto3) sin credenciales en el código, entender el control de acceso IAM, demostrar el manejo de versiones (`AWSCURRENT`/`AWSPREVIOUS`) al rotar el valor, y eliminarlo dejando evidencia.

## Qué es AWS Secrets Manager

Servicio administrado para guardar y recuperar secretos (credenciales de bases de datos, API keys, o cualquier texto/JSON arbitrario) cifrados en reposo con KMS. A diferencia de Parameter Store (SSM), está pensado específicamente para secretos con rotación, versionado y, en varios servicios de AWS (RDS, DocumentDB, Redshift), integración nativa para que el propio servicio gestione la contraseña sin que nadie la vea en texto plano.

**Control de acceso:**
- **Políticas basadas en identidad** (IAM): qué usuario/rol puede llamar `secretsmanager:GetSecretValue`, `DescribeSecret`, etc., sobre qué ARN.
- **Políticas de recursos** (resource policy en el propio secreto): permiten acceso cross-account o desde otro principal sin tocar la política del usuario.
- **KMS**: el secreto se cifra con una llave (por defecto `aws/secretsmanager`, o una llave propia); leer el valor requiere también permiso `kms:Decrypt` sobre esa llave (implícito si se usa la llave por defecto y el usuario ya tiene permiso sobre el secreto).

**Crear vs recuperar vs rotar:**
- **Crear** (`create-secret`): guarda el valor inicial, genera un ARN con sufijo aleatorio de 6 caracteres (evita colisiones de nombre si se borra y se vuelve a crear un secreto con el mismo nombre).
- **Recuperar desde una aplicación** (`get_secret_value` vía SDK): en tiempo de ejecución, nunca hardcodeado; siempre trae la versión marcada `AWSCURRENT` salvo que se pida una versión específica.
- **Rotar**: cambiar el valor. Puede ser manual (`put-secret-value`) o automático (Lambda de rotación programada). Cada `put-secret-value` crea una nueva versión marcada `AWSCURRENT` y mueve la versión anterior a `AWSPREVIOUS`. Esto es lo que se conoce como **version staging**.

## Qué se hizo

1. Se creó el secreto `taller-aws-eia/punto1/demo-db-credentials` con credenciales **ficticias** (JSON `{"username": "demo_user", "password": "..."}`), etiquetado `Project=taller-aws-eia`, `Punto=1`, `Owner=Luis Brito Rincon`.
2. **Política IAM de mínimo privilegio — bloqueada por permisos de cuenta.** Ver sección siguiente.
3. Programa Python (`get_secret.py`) que lee el secreto por nombre (variable de entorno `SECRET_NAME`), sin ninguna credencial de AWS en el código — usa la cadena de credenciales estándar de Boto3 (perfil `user_cli` vía `AWS_PROFILE`).
4. Demostrar acceso restringido a un segundo secreto — **no realizado**, ver limitación abajo.
5. Se modificó el valor con `put-secret-value` y se corrió **el mismo script sin cambios**: trajo la versión nueva (`AWSCURRENT`), confirmando que `list-secret-version-ids` marca la anterior como `AWSPREVIOUS`. Evidencia: [`evidence/01/paso5_rotacion_y_relectura.txt`](../evidence/01/paso5_rotacion_y_relectura.txt).
6. Se eliminó el secreto con `delete-secret --force-delete-without-recovery` (apropiado solo para secretos de prueba; en producción se usaría el borrado con ventana de recuperación) y se confirmó con `describe-secret` y `list-secrets --filters`. Evidencia: [`evidence/01/paso6_eliminacion.txt`](../evidence/01/paso6_eliminacion.txt).

### Ventana de recuperación por defecto

Por defecto, `delete-secret` (sin `--force-delete-without-recovery`) programa el borrado con una ventana de recuperación de **7 a 30 días** (parámetro `RecoveryWindowInDays`, default 30). Durante esa ventana el secreto no se puede leer ni recrear con el mismo nombre, pero sí se puede restaurar (`restore-secret`). Se usó el borrado forzado sin ventana porque es un secreto de prueba sin valor real que proteger.

## Política IAM de mínimo privilegio (pasos 2 y 4) — gestionada centralmente por el profesor

El ejercicio pide crear una política IAM que permita solo `secretsmanager:GetSecretValue`/`DescribeSecret` sobre el ARN de este secreto, asignarla a una identidad de prueba distinta al usuario de trabajo, y demostrar `AccessDenied` sobre un segundo secreto.

El usuario `de-gr02-user-4` (cuenta proporcionada por el profesor) **no tiene ningún permiso IAM**, ni siquiera de lectura sobre sí mismo: se confirmó `AccessDenied` en `iam:CreatePolicy`, `iam:CreateRole`, `iam:PutUserPolicy` y hasta en `iam:GetUser` (consultarse a sí mismo). Consultado el profesor, confirmó que **la gestión de identidades y control de acceso IAM la centraliza él** para todos los estudiantes con cuenta vinculada — no es una tarea que le corresponda al estudiante en esta modalidad de cuenta (a diferencia de quien usa cuenta propia, donde sí crea y ajusta sus propias políticas).

Por esa razón, para esta entrega los pasos 2 y 4 se dan por **satisfechos a nivel de cuenta** por el profesor y no se replican manualmente desde el estudiante. Se deja documentado, como evidencia del razonamiento y como entregable de diseño, el **JSON de política de mínimo privilegio** que se aplicaría en un escenario con cuenta propia: [`../iam/punto1_read_only_secret_policy.json`](../iam/punto1_read_only_secret_policy.json) — permite únicamente `GetSecretValue` y `DescribeSecret` sobre `arn:...:secret:taller-aws-eia/punto1/demo-db-credentials-*` (el `-*` cubre el sufijo aleatorio de 6 caracteres que Secrets Manager agrega al ARN), asignada a una identidad de prueba distinta a `user_cli`.

## Preguntas de costos

Precios verificados en la página oficial: https://aws.amazon.com/secrets-manager/pricing/ (consultado 2026-09-30, región us-east-2).

- **Almacenamiento**: **US$0.40 por secreto por mes**, prorrateado por el tiempo real que existe el secreto (no por mes completo). En esta práctica el secreto existió menos de una hora → costo de almacenamiento despreciable (fracción de centavo).
- **Llamadas a la API**: **US$0.05 por cada 10,000 llamadas** (`GetSecretValue`, `PutSecretValue`, `DescribeSecret`, etc. cuentan). En esta práctica se hicieron ~10 llamadas → costo $0.00 (muy por debajo del bloque de 10,000).
- **Si el programa consulta el mismo secreto repetidamente** (por ejemplo, en cada request de una API que arranca conexiones a una base de datos): el costo crece linealmente con el número de llamadas, a $0.05 por cada 10,000. Con tráfico alto (millones de requests/mes) esto sí se vuelve significativo, aunque sigue siendo barato comparado con, por ejemplo, una brecha de seguridad por hardcodear credenciales.
- **Cuándo conviene cachear en memoria**: cuando la frecuencia de lectura es alta (muchas invocaciones por segundo/minuto) y la latencia de red hacia Secrets Manager (típicamente decenas de milisegundos) no es aceptable en el camino crítico, o cuando se quiere evitar acercarse a los límites de tasa de la API (rate limits por cuenta/región). AWS ofrece la librería oficial **AWS Secrets Manager Caching Client** (disponible para Python, Java, .NET, Go) que cachea el valor en memoria del proceso con un TTL configurable (por defecto 1 hora) y solo vuelve a llamar a la API cuando expira o cuando se detecta un cambio de versión.
- **Contrapartida del caching**: si el secreto rota (por ejemplo, una Lambda de rotación automática cambia la contraseña de una RDS cada 30 días), una aplicación con caché **no verá el nuevo valor hasta que expire el TTL**, lo que puede causar fallos de autenticación transitorios si la rotación invalida la versión anterior antes de que el caché la refresque. Por eso el TTL debe ser menor que la ventana de gracia de la rotación, y conviene manejar el error de autenticación forzando una relectura (invalidando el caché) como fallback.

## Resultados

| Paso | Resultado | Evidencia |
|---|---|---|
| Lectura inicial (paso 3) | `username=demo_user`, `password` original leído correctamente vía Boto3 | [`evidence/01/paso3_lectura_inicial.txt`](../evidence/01/paso3_lectura_inicial.txt) |
| Rotación + relectura (paso 5) | Nueva versión `AWSCURRENT`, anterior pasó a `AWSPREVIOUS`; el mismo script trajo el valor nuevo sin cambios de código | [`evidence/01/paso5_rotacion_y_relectura.txt`](../evidence/01/paso5_rotacion_y_relectura.txt) |
| Eliminación (paso 6) | `delete-secret` confirmado; `list-secrets` ya no lo muestra | [`evidence/01/paso6_eliminacion.txt`](../evidence/01/paso6_eliminacion.txt) |

## Capturas de consola sugeridas (las tomas tú)

Si quieres complementar con capturas de la consola de AWS (opcional, ya que toda la evidencia de CLI está guardada):
- `01_secreto_creado.png` — consola de Secrets Manager mostrando el secreto `taller-aws-eia/punto1/demo-db-credentials` antes de eliminarlo, con sus tags visibles.
- `02_versiones_secreto.png` — pestaña "Versions" del secreto mostrando `AWSCURRENT` y `AWSPREVIOUS` tras la rotación.

## Checklist de cierre

- [x] Recursos creados con etiquetas `Project=taller-aws-eia`, `Punto=1`, `Owner=Luis Brito Rincon`.
- [x] Ninguna contraseña real en código, logs ni repo (las credenciales usadas son ficticias, creadas solo para esta demo).
- [x] Código probado y reproducible (`get_secret.py` + comandos documentados arriba).
- [x] Preguntas de costos respondidas con precios verificados (fuente y fecha citadas).
- [x] Recurso eliminado + verificación (`evidence/01/paso6_eliminacion.txt`).
- [ ] Capturas de consola (pendiente, opcionales — el secreto ya fue eliminado).
- [x] Paso 2/4 (política IAM de mínimo privilegio en identidad separada): gestionado centralmente por el profesor a nivel de cuenta; diseño documentado como referencia.
