# Corpus storage and the application secret.
#
# No credential is written into this repository or into a .tfvars file: the
# secret is created with placeholders and the real values are pushed with
#   aws secretsmanager put-secret-value --secret-id <arn> --secret-string file://secret.json

resource "aws_s3_bucket" "corpus" {
  bucket = "${local.name_prefix}-corpus"
}

resource "aws_s3_bucket_versioning" "corpus" {
  bucket = aws_s3_bucket.corpus.id

  versioning_configuration {
    # Reindexing writes new objects; a superseded corpus version has to be
    # recoverable without relying on a local copy.
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket = aws_s3_bucket.corpus.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id

  rule {
    id     = "expire-noncurrent"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_secretsmanager_secret" "app" {
  name        = "${local.name_prefix}/app"
  description = "Vector store, LLM and MLflow credentials for ${local.name_prefix}."
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = var.rag_secret_json
}
