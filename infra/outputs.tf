output "function_url" {
  description = "Public entry point. With function_url_auth_type = AWS_IAM callers must sign the request."
  value       = aws_lambda_function_url.api.function_url
}

output "function_name" {
  description = "Function CI updates on deploy."
  value       = aws_lambda_function.api.function_name
}

output "ecr_repository_url" {
  description = "Where CI pushes the image."
  value       = aws_ecr_repository.app.repository_url
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
