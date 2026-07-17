output "ecs_cluster_name" { value = aws_ecs_cluster.this.name }
output "task_role_arn" { value = aws_iam_role.task.arn }
output "documents_bucket" { value = aws_s3_bucket.documents.id }
output "db_endpoint" { value = aws_rds_instance.postgres.endpoint }
