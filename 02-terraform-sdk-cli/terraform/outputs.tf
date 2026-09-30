output "s3_bucket_name" {
  value = aws_s3_bucket.demo.bucket
}

output "ec2_instance_id" {
  value = aws_instance.demo.id
}

output "rds_endpoint" {
  value = aws_db_instance.demo.endpoint
}

output "rds_secret_arn" {
  description = "ARN del secreto que Secrets Manager crea automaticamente para la contrasena maestra de RDS"
  value       = aws_db_instance.demo.master_user_secret[0].secret_arn
}
