# ═══════════════════════════════════════════════════════════════════
# Forward Deployed Engineer — AWS Cloud Infrastructure
# ═══════════════════════════════════════════════════════════════════
#
# Provisions the cloud layer for the Autonomous Code Factory:
#   - ECR repository for Strands agent Docker images
#   - ECS Fargate cluster + service for headless agent execution
#   - Bedrock model access for LLM inference
#   - AgentCore Runtime integration
#   - Secrets Manager for ALM tokens
#   - S3 bucket for factory artifacts (specs, notes, reports)
#   - IAM roles with least-privilege policies
#
# Usage:
#   cd infra/terraform
#   terraform init
#   terraform plan -var-file="factory.tfvars"
#   terraform apply -var-file="factory.tfvars"
# ═══════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend: use local state by default.
  # For shared state, uncomment and configure:
  # backend "s3" {
  #   bucket = "my-tf-state"
  #   key    = "fde-factory/terraform.tfstate"
  #   region = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "fde-code-factory"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

# ─── Data Sources ────────────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name
  name_prefix = "fde-${var.environment}"
}

# ─── ECR: Container Registry for Strands Agent ──────────────────
resource "aws_ecr_repository" "strands_agent" {
  name                 = "${local.name_prefix}-strands-agent"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Component = "strands-agent"
  }
}

resource "aws_ecr_lifecycle_policy" "strands_agent" {
  repository = aws_ecr_repository.strands_agent.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Preserve ADOT sidecar images (never expire)"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["adot-"]
          countType     = "imageCountMoreThan"
          countNumber   = 50
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Keep last 10 non-ADOT images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ─── ECS: Fargate Cluster for Headless Agent Execution ──────────
resource "aws_ecs_cluster" "factory" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Component = "ecs-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "factory" {
  cluster_name = aws_ecs_cluster.factory.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 1
    capacity_provider = "FARGATE"
  }
}

# ─── CloudWatch Logs ─────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "factory" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 30

  tags = {
    Component = "logging"
  }
}

# ─── S3: Factory Artifacts Bucket ────────────────────────────────
resource "aws_s3_bucket" "factory_artifacts" {
  bucket        = "${local.name_prefix}-artifacts-${local.account_id}"
  force_destroy = var.environment != "prod"

  tags = {
    Component = "artifacts"
  }
}

resource "aws_s3_bucket_versioning" "factory_artifacts" {
  bucket = aws_s3_bucket.factory_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "factory_artifacts" {
  bucket = aws_s3_bucket.factory_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "factory_artifacts" {
  bucket = aws_s3_bucket.factory_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─── Secrets Manager: ALM Tokens ────────────────────────────────
resource "aws_secretsmanager_secret" "alm_tokens" {
  name                    = "${local.name_prefix}/alm-tokens"
  description             = "ALM platform tokens for the Code Factory (GitHub, Asana, GitLab)"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = {
    Component = "secrets"
  }
}

# ─── IAM: ECS Task Execution Role ───────────────────────────────
resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.name_prefix}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = { Component = "iam" }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name = "${local.name_prefix}-secrets-access"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.alm_tokens.arn]
      }
    ]
  })
}

# ─── IAM: ECS Task Role (what the container can do) ─────────────
resource "aws_iam_role" "ecs_task" {
  name = "${local.name_prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = { Component = "iam" }
}

resource "aws_iam_role_policy" "ecs_task_bedrock" {
  name = "${local.name_prefix}-bedrock-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream"
        ]
        Resource = [
          "arn:aws:bedrock:${local.region}::foundation-model/${var.bedrock_model_id}",
          "arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/${var.bedrock_model_id}",
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/us.*"
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.factory_artifacts.arn,
          "${aws_s3_bucket.factory_artifacts.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.factory.arn}:*"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_dynamodb" {
  name = "${local.name_prefix}-dynamodb-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
        "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"
      ]
      Resource = [
        aws_dynamodb_table.prompt_registry.arn,
        "${aws_dynamodb_table.prompt_registry.arn}/index/*",
        aws_dynamodb_table.task_queue.arn,
        "${aws_dynamodb_table.task_queue.arn}/index/*",
        aws_dynamodb_table.agent_lifecycle.arn,
        "${aws_dynamodb_table.agent_lifecycle.arn}/index/*",
        aws_dynamodb_table.dora_metrics.arn,
        "${aws_dynamodb_table.dora_metrics.arn}/index/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_agentcore" {
  count = var.enable_agentcore ? 1 : 0
  name  = "${local.name_prefix}-agentcore-access"
  role  = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeAgent", "bedrock:GetAgent", "bedrock:ListAgents"]
        Resource = "*"
      }
    ]
  })
}

# ─── ADR-014: Secret Isolation — Task role fetches ALM tokens at runtime ──
resource "aws_iam_role_policy" "ecs_task_alm_secrets" {
  name = "${local.name_prefix}-alm-secrets-read"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.alm_tokens.arn]
      }
    ]
  })
}

# ─── OTEL: X-Ray write permissions for ADOT sidecar ─────────────
resource "aws_iam_role_policy" "ecs_task_xray" {
  name = "${local.name_prefix}-xray-write"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
          "xray:GetSamplingStatisticSummaries"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# ─── VPC: Networking for ECS Fargate ─────────────────────────────
module "vpc" {
  source = "./modules/vpc"

  name_prefix = local.name_prefix
  vpc_cidr    = var.vpc_cidr
  environment = var.environment
}

# ─── ECS Task Definition ────────────────────────────────────────
resource "aws_ecs_task_definition" "strands_agent" {
  family                   = "${local.name_prefix}-strands-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.agent_cpu
  memory                   = var.agent_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "strands-agent"
      image     = "${aws_ecr_repository.strands_agent.repository_url}:latest"
      essential = true

      environment = [
        { name = "AWS_REGION", value = local.region },
        { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id },
        { name = "BEDROCK_MODEL_REASONING", value = var.bedrock_model_reasoning },
        { name = "BEDROCK_MODEL_STANDARD", value = var.bedrock_model_standard },
        { name = "BEDROCK_MODEL_FAST", value = var.bedrock_model_fast },
        { name = "FACTORY_BUCKET", value = aws_s3_bucket.factory_artifacts.id },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "PROMPT_REGISTRY_TABLE", value = aws_dynamodb_table.prompt_registry.name },
        { name = "TASK_QUEUE_TABLE", value = aws_dynamodb_table.task_queue.name },
        { name = "AGENT_LIFECYCLE_TABLE", value = aws_dynamodb_table.agent_lifecycle.name },
        { name = "DORA_METRICS_TABLE", value = aws_dynamodb_table.dora_metrics.name },
        # OTEL distributed tracing — sends to ADOT sidecar on localhost
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
        { name = "OTEL_SERVICE_NAME", value = "${local.name_prefix}-strands-agent" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "deployment.environment=${var.environment},service.namespace=fde-factory" },
        { name = "OTEL_SEMCONV_STABILITY_OPT_IN", value = "gen_ai_latest_experimental" },
        # ADR-019: Agentic Squad mode
        { name = "SQUAD_MODE", value = "dynamic" },
        { name = "FDE_AGENT_NAME", value = "FDE Squad Leader" },
        { name = "FDE_AGENT_EMAIL", value = "fde-squad@factory.local" },
      ]

      secrets = [
        # ALM tokens removed from container env vars (ADR-014: Secret Isolation).
        # Tokens are fetched from Secrets Manager at tool invocation time via
        # _fetch_alm_token() in agents/tools.py. This prevents the LLM from
        # observing token values in its context window.
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.factory.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "strands-agent"
        }
      }
    },
    # ADOT Sidecar — AWS Distro for OpenTelemetry Collector
    # Receives traces from the Strands agent on localhost:4318 (OTLP/HTTP)
    # and exports them to AWS X-Ray for distributed trace visualization.
    # Non-essential: agent continues if ADOT fails to start.
    # Image copied to private ECR via `docker buildx imagetools create`
    # to preserve the OCI image index with platform descriptors (COE-020).
    {
      name      = "adot-collector"
      image     = "${aws_ecr_repository.strands_agent.repository_url}:adot-v0.40.0"
      essential = false

      command = ["--config=/etc/ecs/ecs-xray.yaml"]

      portMappings = [
        { containerPort = 4317, protocol = "tcp" },
        { containerPort = 4318, protocol = "tcp" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.factory.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "adot-collector"
        }
      }
    }
  ])

  tags = { Component = "strands-agent" }
}

resource "aws_ecs_service" "strands_agent" {
  count           = var.enable_ecs_service ? 1 : 0
  name            = "${local.name_prefix}-strands-agent"
  cluster         = aws_ecs_cluster.factory.id
  task_definition = aws_ecs_task_definition.strands_agent.arn
  desired_count   = var.agent_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnet_ids
    security_groups  = [module.vpc.ecs_security_group_id]
    assign_public_ip = false
  }

  tags = { Component = "strands-agent" }
}
