# ECS Fargate: one cluster, two services (API and Streamlit UI), one image.
#
# The image is the same for both: it has no CMD change to build, so the UI
# service overrides the command instead of paying for a second image.

resource "aws_ecs_cluster" "main" {
  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Pulls the image and injects the secret into the container environment.
resource "aws_iam_role" "execution" {
  name               = "${local.name_prefix}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${local.name_prefix}-read-secret"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.app.arn]
    }]
  })
}

# What the application itself may do while it runs: read the corpus, nothing else.
resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_corpus" {
  name = "${local.name_prefix}-corpus-read"
  role = aws_iam_role.task.id

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
    ]
  })
}

# python instead of curl: the runtime image is python:*-slim and has no curl.
locals {
  api_healthcheck = ["CMD-SHELL", "python -c 'import os,urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/health\").read()'"]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "rag-api"
    image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    command   = ["sh", "-c", "uvicorn rag.api:app --host 0.0.0.0 --port 8000"]

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    environment = local.container_env
    secrets     = local.secret_env

    healthCheck = {
      command     = local.api_healthcheck
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 20
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "ui" {
  family                   = "${local.name_prefix}-ui"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "rag-ui"
    image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    command   = ["sh", "-c", "streamlit run src/rag/ui.py --server.port 8501 --server.address 0.0.0.0"]

    portMappings = [{
      containerPort = 8501
      protocol      = "tcp"
    }]

    # The UI only renders what the API returns: it calls it through the load
    # balancer and needs neither the model nor the vector store credentials.
    environment = [
      { name = "RAG_API_URL", value = "http://${aws_lb.main.dns_name}" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ui.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ui"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "rag-api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The target group has to exist before the service registers into it.
  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "ui" {
  name            = "${local.name_prefix}-ui"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui.arn
  desired_count   = var.ui_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ui.arn
    container_name   = "rag-ui"
    container_port   = 8501
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]
}
