output "alb_dns_name" {
  description = "Public entry point: API paths plus the Streamlit UI."
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  description = "Where CI pushes the image."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "Cluster both services run in."
  value       = aws_ecs_cluster.main.name
}

output "api_service_name" {
  description = "Service CI rolls out on deploy."
  value       = aws_ecs_service.api.name
}

output "ui_service_name" {
  description = "Service CI rolls out on deploy."
  value       = aws_ecs_service.ui.name
}

output "corpus_bucket" {
  description = "S3 bucket holding the document corpus."
  value       = aws_s3_bucket.corpus.id
}

output "deploy_role_arn" {
  description = "Role GitHub Actions assumes through OIDC: set as the AWS_DEPLOY_ROLE repository variable."
  value       = aws_iam_role.deploy.arn
}

output "app_secret_arn" {
  description = "Secret to fill with `aws secretsmanager put-secret-value` before the first deploy."
  value       = aws_secretsmanager_secret.app.arn
}
