# The API: one container image on Lambda, reached through a Function URL.
#
# No load balancer and no VPC: the Function URL is HTTPS on a public hostname
# and costs nothing, and Lambda keeps its default network access, so no NAT
# gateway or subnet has to exist for the function to reach Ollama and S3.

resource "aws_lambda_function" "api" {
  function_name = "${local.name_prefix}-api"
  role          = aws_iam_role.function.arn

  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  architectures = ["x86_64"]

  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_s

  # A public URL with unbounded concurrency is an open tap on the model host.
  reserved_concurrent_executions = var.reserved_concurrency

  environment {
    variables = local.function_env
  }

  # The adapter extension takes over the runtime; nothing else is configured
  # here, so the same image still runs with `docker run` or uvicorn locally.
  depends_on = [aws_cloudwatch_log_group.api]
}

data "aws_iam_policy_document" "function_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "function" {
  name               = "${local.name_prefix}-function"
  assume_role_policy = data.aws_iam_policy_document.function_assume.json
}

resource "aws_iam_role_policy_attachment" "function_logs" {
  role       = aws_iam_role.function.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# What the chain may do: read the corpus and read its own credentials.
resource "aws_iam_role_policy" "function" {
  name = "${local.name_prefix}-runtime"
  role = aws_iam_role.function.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.corpus.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.corpus.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [aws_ssm_parameter.app.arn]
      },
    ]
  })
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = var.function_url_auth_type

  cors {
    allow_origins = ["*"]
    allow_methods = ["POST"]
    allow_headers = ["content-type", "x-api-key"]
  }
}

# A Function URL with NONE auth is only reachable if the resource policy says so.
resource "aws_lambda_permission" "function_url" {
  count = var.function_url_auth_type == "NONE" ? 1 : 0

  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
