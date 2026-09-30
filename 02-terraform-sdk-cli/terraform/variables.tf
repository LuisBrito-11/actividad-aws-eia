variable "aws_region" {
  description = "Region unica usada para todo el taller"
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "Perfil de AWS CLI a usar (nunca root)"
  type        = string
  default     = "user_cli"
}

variable "project_tag" {
  type    = string
  default = "taller-aws-eia"
}

variable "punto_tag" {
  type    = string
  default = "2"
}

variable "owner_tag" {
  type    = string
  default = "Luis Brito Rincon"
}

variable "db_username" {
  description = "Usuario maestro de RDS (la contrasena la genera y gestiona Secrets Manager)"
  type        = string
  default     = "tallerdbadmin"
}
