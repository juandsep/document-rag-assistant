# Base AWS resources: provider, image registry, the function log group, the
# GitHub Actions OIDC trust, the deploy role and the budget guard.
#
# State is local (terraform.tfstate, git-ignored), matching the reference project
# `uplift-modeling-pipeline`. Move it to an S3 backend before a second person
# applies this.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

variable "region" {
  description = "AWS region everything is created in."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Repository name, used as the prefix of every resource."
  type        = string
  default     = "document-rag-assistant"
}

variable "environment" {
  description = "Environment name: staging or production."
  type        = string
  default     = "staging"
}

variable "image_tag" {
  description = "Tag of the image the function runs. CI rewrites it on every deploy; `bootstrap` before the first one."
  type        = string
  default     = "bootstrap"
}

variable "vector_backend" {
  description = "Retriever the chain talks to: qdrant (deployed) or local (development only, the image ships no index)."
  type        = string
  default     = "qdrant"

  validation {
    condition     = contains(["local", "qdrant"], var.vector_backend)
    error_message = "vector_backend must be local or qdrant."
  }
}

variable "qdrant_url" {
  description = "Qdrant Cloud cluster URL (https://<id>.<region>.aws.cloud.qdrant.io). Its API key goes in the SecureString, not here."
  type        = string
  default     = ""
}

variable "ollama_base_url" {
  description = "Ollama HTTP API the chain calls: Ollama Cloud by default. Its key goes in the SecureString as OLLAMA_API_KEY."
  type        = string
  default     = "https://ollama.com"
}

variable "ollama_model" {
  description = "Model the chain generates with, on Ollama Cloud's free plan. gpt-oss:120b keeps the question's language when the passages are in another one, which gpt-oss:20b does not reliably."
  type        = string
  default     = "gpt-oss:120b"
}

variable "lambda_memory_mb" {
  description = "Function memory. CPU scales with it, so this is the knob for latency: 1024 MB keeps a retrieval round trip to a couple of seconds."
  type        = number
  default     = 1024

  validation {
    condition     = var.lambda_memory_mb >= 128 && var.lambda_memory_mb <= 10240
    error_message = "lambda_memory_mb must be between 128 and 10240."
  }
}

variable "lambda_timeout_s" {
  description = "Function timeout. The chain waits on Ollama, so it is generous compared with a CPU-bound handler."
  type        = number
  default     = 60

  validation {
    condition     = var.lambda_timeout_s >= 3 && var.lambda_timeout_s <= 900
    error_message = "lambda_timeout_s must be between 3 and 900."
  }
}

variable "reserved_concurrency" {
  description = "Hard ceiling on concurrent invocations, and the only guard that actually caps what a reachable URL can spend. -1 leaves the account-wide pool unbounded."
  type        = number
  default     = 2
}

variable "function_url_auth_type" {
  description = "NONE (default) makes the URL public so the Streamlit UI can call it; /query still demands the API_KEY from the SecureString in an X-API-Key header. AWS_IAM makes callers sign with SigV4 instead."
  type        = string
  default     = "NONE"

  validation {
    condition     = contains(["AWS_IAM", "NONE"], var.function_url_auth_type)
    error_message = "function_url_auth_type must be AWS_IAM or NONE."
  }
}

variable "monthly_budget_usd" {
  description = "Budget alarm threshold. The stack idles under a dollar, so this alarm is meant to fire when something is actually wrong."
  type        = number
  default     = 2
}

variable "alert_email" {
  description = "Address the budget alarm and the CloudWatch alarms write to."
  type        = string
}

variable "github_repo" {
  description = "Repository allowed to deploy, as GitHub's immutable OIDC subject prefix names it: owner@owner_id/name@repo_id. Read it with `gh api repos/<owner>/<name>/actions/oidc/customization/sub` (sub_claim_prefix, without `repo:`). The ids keep a renamed or recreated repository from inheriting the role."
  type        = string
  default     = "juandsep@30062465/document-rag-assistant@1396685576"
}

variable "github_branch" {
  description = "Branch whose pushes may assume the deploy role."
  type        = string
  default     = "dev"
}

variable "github_oidc_thumbprint" {
  description = "Thumbprint of the token.actions.githubusercontent.com certificate. Only used when this configuration creates the provider."
  type        = string
  default     = "6938fd4d98bab03faadb97b34396831e3780aea1"
}

variable "create_github_oidc_provider" {
  description = "Set to false when the account already has the token.actions.githubusercontent.com provider: AWS allows only one per account and apply fails with EntityAlreadyExists."
  type        = bool
  default     = true
}

variable "rag_secret_json" {
  description = "JSON body of the application secret. Placeholders by default: replace the value with `aws ssm put-parameter --overwrite` after apply, so the real credentials never sit in a .tfvars file."
  type        = string
  sensitive   = true
  default     = <<-JSON
    {
      "QDRANT_API_KEY": "REPLACE_ME",
      "OLLAMA_API_KEY": "REPLACE_ME",
      "API_KEY": "REPLACE_ME"
    }
  JSON
}

locals {
  name_prefix = "${var.project}-${var.environment}"

  # Plain configuration the function reads at import. Nothing here is a
  # credential: keys are read from the SecureString named by
  # APP_SECRET_PARAMETER.
  function_env = {
    VECTOR_BACKEND       = var.vector_backend
    QDRANT_URL           = var.qdrant_url
    OLLAMA_BASE_URL      = var.ollama_base_url
    OLLAMA_MODEL         = var.ollama_model
    APP_SECRET_PARAMETER = aws_ssm_parameter.app.name

    # The adapter in docker/Dockerfile forwards to the port the image listens on.
    AWS_LWA_PORT                    = "8000"
    AWS_LWA_READINESS_CHECK_PATH    = "/health"
    AWS_LWA_READINESS_CHECK_TIMEOUT = "5"
  }
}

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 20 images, expire the rest."
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = 14
}

# Budget guard: the cheapest way to find out that something is burning money.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# Deploys authenticate through GitHub's OIDC provider: no access keys anywhere.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [var.github_oidc_thumbprint]
}

data "aws_iam_openid_connect_provider" "existing" {
  count = var.create_github_oidc_provider ? 0 : 1

  url = "https://token.actions.githubusercontent.com"
}

locals {
  oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.existing[0].arn
}

data "aws_iam_policy_document" "deploy_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only a push to the deployment branch of the one repository may assume it.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${local.name_prefix}-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_assume.json
}

data "aws_iam_policy_document" "deploy_permissions" {
  statement {
    sid       = "EcrLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid    = "RollOut"
    effect = "Allow"
    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]
    resources = [aws_lambda_function.api.arn]
  }

  # Updating the function's configuration sets its execution role.
  statement {
    sid       = "PassFunctionRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.function.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${local.name_prefix}-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_permissions.json
}
