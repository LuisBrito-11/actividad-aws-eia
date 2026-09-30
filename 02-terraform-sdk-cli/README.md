# Punto 2 — Terraform + Boto3 + AWS CLI (S3 + EC2 + RDS)

## Objetivo

Desplegar el mismo stack (bucket S3, instancia EC2, instancia RDS) con tres métodos distintos, destruyendo todo entre cada versión, y comparar los tres enfoques.

## Qué es Terraform

Terraform es una herramienta de Infraestructura como Código (IaC) declarativa: yo describo en archivos `.tf` **cómo quiero que quede** la infraestructura, y Terraform calcula qué acciones tomar para llegar ahí, guardando el resultado en un archivo de estado (`terraform.tfstate`).

El ciclo de trabajo es:
- **`init`**: descarga los providers necesarios (aquí, `hashicorp/aws` y `hashicorp/random`) y prepara el directorio de trabajo.
- **`plan`**: compara mi configuración contra el estado actual y muestra qué va a crear/cambiar/destruir, sin tocar nada todavía.
- **`apply`**: ejecuta esos cambios contra AWS.
- **`destroy`**: elimina todo lo que Terraform tiene registrado en el estado.

## Permisos IAM para user_cli

Antes de empezar pensé que tocaría iterar permisos de `user_cli` como pide el enunciado (crear la política mínima a partir de los errores `AccessDenied`), pero como ya documenté en el Punto 1, mi usuario no tiene ningún permiso IAM — el profesor administra eso de forma centralizada para toda la cuenta. En la práctica esto significa que no puedo crear ni ajustar políticas yo mismo: simplemente usé los permisos que ya tenía, y **no me topé con ningún `AccessDenied` real** al crear VPC, security groups, S3, EC2 ni RDS en ninguna de las tres versiones — el profesor ya dejó los permisos necesarios habilitados para este ejercicio.

## Las tres versiones

Usé la **VPC por defecto** (con sus 3 subnets) en vez de crear una propia: para una sola EC2 y una sola RDS no hay razón para levantar networking adicional, y evita el riesgo de terminar necesitando un NAT Gateway.

Stack idéntico en las tres versiones:
- Bucket S3 con bloqueo de acceso público.
- Security group de EC2 sin ningún ingreso permitido.
- Security group de RDS que solo acepta el puerto 3306 desde el security group de la EC2.
- Instancia EC2 `t3.micro`, Amazon Linux 2023, **sin IP pública** (evito el cargo de $0.005/hora por IPv4 pública — no la necesito porque no me conecto por SSH en este punto).
- Instancia RDS `db.t4g.micro`, MySQL 8.0, 20 GB gp2 (mínimo permitido), **sin acceso público**, sin Multi-AZ, `skip_final_snapshot`/`--skip-final-snapshot`, y **contraseña maestra gestionada por Secrets Manager** (`manage_master_user_password` / `--manage-master-user-password`) — así no queda ninguna contraseña en el tfstate, en mi código, ni en ningún log.

### 1. Terraform (`terraform/`)

Apliqué (`terraform apply`) y verifiqué los 8 recursos creados (EC2 `running`, RDS `available`, bucket existente, secreto de RDS con mis tags heredados). Evidencia: [`../evidence/02/01_terraform_apply_verificacion.txt`](../evidence/02/01_terraform_apply_verificacion.txt). Destruí con `terraform destroy` y confirmé que no quedó nada: [`../evidence/02/02_destroy_verificacion.txt`](../evidence/02/02_destroy_verificacion.txt).

### 2. Boto3 (`boto3/deploy.py`)

Script Python con `create()` y `destroy()`. A diferencia de Terraform, **no hay ningún archivo de estado**: `destroy()` encuentra sus propios recursos buscando por nombre fijo (`taller-aws-eia-punto2-boto3-*`) y tags — el RDS y el bucket por identificador/nombre fijo, la EC2 y los security groups filtrando por el tag `Name`/`group-name`. Usé `waiter`s (`instance_running`, `db_instance_available`, `instance_terminated`, `db_instance_deleted`) para esperar a que cada paso realmente termine antes de seguir.

Encontré un bug real al primer intento: `run_instances` no acepta `SubnetId`/`SecurityGroupIds` a nivel de instancia **a la vez** que `NetworkInterfaces` — hay que elegir uno de los dos. Lo arreglé quitando los parámetros redundantes.

Evidencia: [`../evidence/02/03_boto3_create_output.txt`](../evidence/02/03_boto3_create_output.txt) y [`../evidence/02/04_boto3_destroy_output.txt`](../evidence/02/04_boto3_destroy_output.txt).

### 3. AWS CLI (`cli/deploy.sh`)

Script `bash` con las funciones `create` y `destroy`, mismo patrón que Boto3 (nombres fijos, sin estado, busca sus recursos por tag/nombre para destruir).

Bug real que encontré aquí: el shorthand de la AWS CLI para `--tags`/`--tag-specifications` (`Key=...,Value=...`) se rompe cuando un valor tiene espacios — mi tag `Owner=Luis Brito Rincon` partía mal el string. Lo resolví armando los tags como JSON explícito (`--tags '[{"Key":"...","Value":"..."}]'`) en vez de shorthand.

Evidencia: [`../evidence/02/05_cli_create_output.txt`](../evidence/02/05_cli_create_output.txt) y [`../evidence/02/06_cli_destroy_output.txt`](../evidence/02/06_cli_destroy_output.txt).

## Cómo se autentica `user_cli` en cada método

Los tres usan la misma cadena de credenciales de AWS (perfil local `~/.aws/credentials`), solo cambia cómo se lo indico a cada herramienta:
- **CLI**: `aws --profile user_cli ...` (o `export AWS_PROFILE=user_cli`).
- **Boto3**: variable de entorno `AWS_PROFILE=user_cli` antes de correr el script (o `boto3.Session(profile_name="user_cli")` si lo quisiera fijo en el código).
- **Terraform**: variable `aws_profile` en `variables.tf` (default `"user_cli"`), que el provider usa directamente — no toca ninguna credencial hardcodeada.

## Qué guarda el `tfstate` y por qué no tiene contraseñas

El `terraform.tfstate` guarda, en JSON, **todos los atributos de cada recurso que Terraform administra**: IDs, ARNs, configuración completa, y cualquier atributo que el provider devuelva — incluyendo, en muchos casos, valores sensibles si uno los pone directo en el `.tf` (por ejemplo, una contraseña puesta como `master_password = "..."` terminaría en texto plano ahí). Por eso usé `manage_master_user_password = true`: la contraseña nunca la genero ni la paso yo, AWS la crea directo en Secrets Manager, y Terraform solo guarda el **ARN del secreto** en el estado, nunca el valor. El `tfstate` no se sube al repo (`.gitignore`) precisamente porque, aunque en este caso no tiene secretos, sí tiene el detalle completo de la infraestructura (IDs de recursos, configuración de red, etc.) que no tiene por qué ser público.

## Comparación de los tres métodos

| Aspecto | Terraform | Boto3 | AWS CLI |
|---|---|---|---|
| Paradigma | Declarativo (describo el resultado) | Imperativo (describo los pasos) | Imperativo |
| Estado | `tfstate` — sabe qué existe y qué falta | Ninguno — hay que buscar por tag/nombre | Ninguno — igual |
| Idempotencia | Alta: `apply` de nuevo no duplica nada | La programo yo a mano (o no la tengo) | La programo yo a mano (o no la tengo) |
| Rollback | `destroy` revierte todo lo que está en el estado | Tengo que escribir mi propio `destroy()` | Igual, a mano |
| Legibilidad | Buena para ver "qué hay", `plan` explica el cambio | Buena para lógica condicional/compleja | Rápido para scripts cortos, se vuelve feo si crece |
| Curva de aprendizaje | Hay que aprender HCL y el modelo de estado | Si ya sé Python, es directo | Si ya conozco los comandos, es directo |
| Manejo de errores | Si algo falla a medio camino, el estado queda parcial pero consistente | Yo decido qué pasa si un paso falla (try/except) | Por defecto, `set -e` corta el script; hay que manejar cada caso |

Mi conclusión después de hacerlo tres veces: Terraform es el que menos pienso tener que mantener a mano (el estado hace el trabajo pesado), pero Boto3 fue el más cómodo para meterle lógica (el bug de `run_instances` fue fácil de diagnosticar con el traceback de Python). La CLI es la más rápida para algo puntual, pero el bug del shorthand con espacios me hubiera costado más tiempo si no lo hubiera visto ya en Boto3/Terraform antes.

## Preguntas de costos

Precios verificados con la AWS Pricing API oficial (región us-east-2, consultado 2026-09-30):

| Recurso | Precio |
|---|---|
| RDS `db.t4g.micro` MySQL Single-AZ | $0.016/hora |
| RDS storage gp2 (20 GB, mínimo para MySQL) | $0.115/GB-mes ≈ $0.0032/hora |
| EC2 `t3.micro` Linux | $0.0104/hora |
| EBS gp3 (8 GB raíz) | $0.08/GB-mes ≈ $0.0009/hora |
| Secreto de RDS en Secrets Manager | $0.40/mes ≈ $0.0005/hora |

**Total: ~$0.031 USD/hora** por cada versión del stack completo.

- **1 hora encendido**: ~$0.031 USD.
- **1 semana (168 horas) encendido sin parar**: ~$5.21 USD — este es el costo si alguien se olvida de apagarlo, no algo que yo dejé corriendo.
- **Qué sigue cobrando sin tráfico**: la instancia EC2 (por hora, tenga o no conexiones), la instancia RDS (por hora), el almacenamiento EBS de la EC2 y el storage de RDS (por GB-mes, independiente del uso), y el secreto de RDS en Secrets Manager ($0.40/mes prorrateado). El bucket S3 vacío no cuesta casi nada.
- **Costo que añade el secreto de RDS**: los $0.40/mes (≈$0.0005/hora) de Secrets Manager — comparado con el resto del stack, es la parte más barata, y a cambio evito tener la contraseña maestra en texto plano en cualquier lado.

En la práctica, cada una de las tres versiones estuvo arriba menos de una hora (la creé, verifiqué, tomé capturas, y destruí), así que el costo real de todo el Punto 2 fue de unos pocos centavos de dólar.

## Resultados

| Versión | Resultado | Evidencia creación | Evidencia destroy |
|---|---|---|---|
| Terraform | 8 recursos creados y verificados; destruidos sin dejar nada | [`01_terraform_apply_verificacion.txt`](../evidence/02/01_terraform_apply_verificacion.txt) | [`02_destroy_verificacion.txt`](../evidence/02/02_destroy_verificacion.txt) |
| Boto3 | Mismo stack creado con waiters; bug de `run_instances` corregido | [`03_boto3_create_output.txt`](../evidence/02/03_boto3_create_output.txt) | [`04_boto3_destroy_output.txt`](../evidence/02/04_boto3_destroy_output.txt) |
| AWS CLI | Mismo stack creado; bug de shorthand con espacios corregido | [`05_cli_create_output.txt`](../evidence/02/05_cli_create_output.txt) | [`06_cli_destroy_output.txt`](../evidence/02/06_cli_destroy_output.txt) |

Las capturas de consola de las tres versiones (S3, EC2, RDS, secreto) están en `evidencias-taller-aws.docx` en la raíz del repo (documento local, no se sube a git).

## Checklist de cierre

- [x] Recursos creados con etiquetas `Project=taller-aws-eia`, `Punto=2`, `Owner=Luis Brito Rincon` (más `Method` en Boto3/CLI para distinguir versión).
- [x] Ninguna contraseña en código, logs ni repo — las tres versiones usan contraseña gestionada por Secrets Manager.
- [x] Código probado y reproducible (las tres versiones corrieron completas, con bugs reales encontrados y corregidos).
- [x] Preguntas de costos respondidas con precios verificados (fuente y fecha citadas).
- [x] Recursos destruidos + verificación, en las tres versiones.
- [x] Capturas de consola tomadas para las tres versiones (en el Word de evidencias).
