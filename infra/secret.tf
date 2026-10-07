# The application secret.
#
# No credential is written into this repository or into a .tfvars file: the
# secret is created with placeholders and the real values are pushed with
#   aws ssm put-parameter --name <app_secret_parameter> --type SecureString \
#     --value file://secret.json --overwrite

# A standard-tier SecureString costs nothing and is encrypted with the
# AWS-managed aws/ssm key; Secrets Manager would bill $0.40 a month for the
# same few keys, which was most of the idle bill.
resource "aws_ssm_parameter" "app" {
  name        = "/${local.name_prefix}/app"
  description = "Vector store, LLM and MLflow credentials for ${local.name_prefix}."
  type        = "SecureString"
  tier        = "Standard"
  value       = var.rag_secret_json

  # The real value is pushed outside Terraform; apply must not put the
  # placeholders back.
  lifecycle {
    ignore_changes = [value]
  }
}
