# Base AWS resources: provider, image registry, log groups, the GitHub Actions
# OIDC trust and the monthly budget guard.
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
  description = "Tag of the image both services run. CI rewrites it on every deploy; `bootstrap` before the first one."
  type        = string
  default     = "bootstrap"
}

variable "vector_backend" {
  description = "Retriever the API talks to: pinecone or opensearch."
  type        = string
  default     = "pinecone"

  validation {
    condition     = contains(["pinecone", "opensearch"], var.vector_backend)
    error_message = "vector_backend must be pinecone or opensearch."
  }
}

variable "ollama_base_url" {
  description = "Ollama HTTP API the chain calls. Must be reachable from the tasks: a localhost default only works for a local run."
  type        = string
  default     = "http://localhost:11434"
}

variable "ollama_model" {
  description = "Model the chain generates with, and embeds with unless embedding_model overrides it."
  type        = string
  default     = "llama3.1:8b"
}

variable "embedding_model" {
  description = "Embedding model served by the same Ollama API, used at index time and at query time."
  type        = string
  default     = "nomic-embed-text"
}

variable "api_desired_count" {
  description = "Number of API tasks. Two keeps the service up while one task deploys, at twice the Fargate cost."
  type        = number
  default     = 1
}

variable "ui_desired_count" {
  description = "Number of Streamlit tasks."
  type        = number
  default     = 1
}

variable "monthly_budget_usd" {
  description = "Budget alarm threshold. Billing data lags by hours, so spend can pass it slightly."
  type        = number
  default     = 5
}

variable "alert_email" {
  description = "Address the budget alarm writes to."
  type        = string
}

variable "github_repo" {
  description = "owner/name of the repository allowed to deploy."
  type        = string
  default     = "juandsep/document-rag-assistant"
}

variable "github_branch" {
  description = "Branch whose pushes may assume the deploy role."
  type        = string
  default     = "dev"
}

variable "create_github_oidc_provider" {
  description = "Set to false when the account already has the token.actions.githubusercontent.com provider: AWS allows only one per account and apply fails with EntityAlreadyExists."
  type        = bool
  default     = true
}

variable "rag_secret_json" {
  description = "JSON body of the application secret. Placeholders by default: replace the value with `aws secretsmanager put-secret-value` after apply, so the real credentials never sit in a .tfvars file."
  type        = string
  sensitive   = true
  default     = <<-JSON
    {
      "PINECONE_API_KEY": "REPLACE_ME",
      "OLLAMA_API_KEY": "",
      "MLFLOW_TRACKING_URI": "REPLACE_ME"
    }
  JSON
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  secret_arn  = aws_secretsmanager_secret.app.arn
  container_env = [
    { name = "PORT", value = "8000" },
    { name = "VECTOR_BACKEND", value = var.vector_backend },
    { name = "OLLAMA_BASE_URL", value = var.ollama_base_url },
    { name = "OLLAMA_MODEL", value = var.ollama_model },
    { name = "EMBEDDING_MODEL", value = var.embedding_model },
  ]
  # Keys the container reads out of Secrets Manager. Keep in sync with the JSON
  # body above and with the variables documented in README.md.
  secret_env = [
    { name = "PINECONE_API_KEY", valueFrom = "${local.secret_arn}:PINECONE_API_KEY::" },
    { name = "OLLAMA_API_KEY", valueFrom = "${local.secret_arn}:OLLAMA_API_KEY::" },
    { name = "MLFLOW_TRACKING_URI", valueFrom = "${local.secret_arn}:MLFLOW_TRACKING_URI::" },
  ]
}

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # Deploys keep tags that a rollback may still point at.
  lifecycle {
    prevent_destroy = false
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
  name              = "/ecs/${local.name_prefix}-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "ui" {
  name              = "/ecs/${local.name_prefix}-ui"
  retention_in_days = 14
}

# Budget guard: the cheapest way to find out that a Fargate service was left
# running. Billing data lags, so this warns rather than stops anything.
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
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
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

    # Only a push to the deployment branch of the one repository may assume it.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

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
    sid    = "Rollout"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService",
    ]
    resources = ["*"]
  }

  # Registering a task definition runs it as the task and execution roles.
  statement {
    sid       = "PassTaskRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.task.arn, aws_iam_role.execution.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${local.name_prefix}-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_permissions.json
}
