# ═══════════════════════════════════════════════════════════════════
# ECS — Parametrized Agent Task Definition
# ═══════════════════════════════════════════════════════════════════
#
# Generic task definition for all squad agents. The orchestrator
# launches instances of this task with different environment variables
# to specialize each agent (role, model tier, stage, permissions).
#
# Parametrization via environment overrides at RunTask time:
#   - AGENT_ROLE: swe-developer, swe-adversarial, code-sec, etc.
#   - AGENT_STAGE: 1-6 (pipeline stage number)
#   - MODEL_TIER: fast (Haiku) | reasoning (Sonnet) | deep (Opus)
#   - TASK_ID: unique execution identifier
#   - SCD_TABLE: DynamoDB table for shared context
#   - SQUAD_MANIFEST_KEY: S3 key for the manifest JSON
#   - ORGANISM_LEVEL: O1-O5 complexity classification
#   - KNOWLEDGE_CONTEXT: serialized knowledge annotations
#   - USER_VALUE_STATEMENT: extracted user value for DoD validation
#   - AGENT_SUBTASK: Conductor-generated focused instruction (ADR-020)
#   - AGENT_ACCESS_LIST: Communication topology as JSON array (ADR-020)
#   - AGENT_STEP_INDEX: Step position in Conductor workflow plan (ADR-020)
#
# EFS mount: /workspaces/{task_id}/{repo}/ for shared file access.
# Networking: Private subnets only, egress to Bedrock + GitHub/GitLab.
# ═══════════════════════════════════════════════════════════════════

variable "name_prefix" {
  description = "Resource naming prefix (e.g., fde-dev)"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "ecr_repository_url" {
  description = "ECR repository URL for agent images"
  type        = string
}

variable "execution_role_arn" {
  description = "ECS task execution role ARN (pulls images, writes logs)"
  type        = string
}

variable "task_role_arn" {
  description = "ECS task role ARN (what the container can do at runtime)"
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch log group name for agent logs"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "efs_file_system_id" {
  description = "EFS file system ID for workspace mounts"
  type        = string
}

variable "efs_access_point_id" {
  description = "EFS access point ID for /workspaces"
  type        = string
}

variable "scd_table_name" {
  description = "DynamoDB SCD table name"
  type        = string
}

variable "metrics_table_name" {
  description = "DynamoDB metrics table name"
  type        = string
}

variable "memory_table_name" {
  description = "DynamoDB memory table name"
  type        = string
}

variable "knowledge_table_name" {
  description = "DynamoDB knowledge table name"
  type        = string
}

variable "artifacts_bucket" {
  description = "S3 bucket name for factory artifacts"
  type        = string
}

variable "bedrock_model_id" {
  description = "Default Bedrock model ID (overridable per agent via MODEL_TIER)"
  type        = string
}

variable "bedrock_model_reasoning" {
  description = "Bedrock model for reasoning-tier agents"
  type        = string
  default     = ""
}

variable "bedrock_model_standard" {
  description = "Bedrock model for standard-tier agents"
  type        = string
  default     = ""
}

variable "bedrock_model_fast" {
  description = "Bedrock model for fast-tier agents"
  type        = string
  default     = ""
}

variable "agent_cpu" {
  description = "CPU units for agent tasks (1024 = 1 vCPU)"
  type        = string
  default     = "1024"
}

variable "agent_memory" {
  description = "Memory (MiB) for agent tasks"
  type        = string
  default     = "2048"
}

# ─── Agent Task Definition ───────────────────────────────────────
resource "aws_ecs_task_definition" "agent" {
  family                   = "${var.name_prefix}-squad-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.agent_cpu
  memory                   = var.agent_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  volume {
    name = "workspaces"

    efs_volume_configuration {
      file_system_id          = var.efs_file_system_id
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = var.efs_access_point_id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "squad-agent"
      image     = "${var.ecr_repository_url}:latest"
      essential = true

      mountPoints = [
        {
          sourceVolume  = "workspaces"
          containerPath = "/workspaces"
          readOnly      = false
        }
      ]

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id },
        { name = "BEDROCK_MODEL_REASONING", value = var.bedrock_model_reasoning },
        { name = "BEDROCK_MODEL_STANDARD", value = var.bedrock_model_standard },
        { name = "BEDROCK_MODEL_FAST", value = var.bedrock_model_fast },
        { name = "SCD_TABLE", value = var.scd_table_name },
        { name = "METRICS_TABLE", value = var.metrics_table_name },
        { name = "MEMORY_TABLE", value = var.memory_table_name },
        { name = "KNOWLEDGE_TABLE", value = var.knowledge_table_name },
        { name = "FACTORY_BUCKET", value = var.artifacts_bucket },
        # Parametrized at RunTask time via overrides:
        # AGENT_ROLE, AGENT_STAGE, MODEL_TIER, TASK_ID,
        # SQUAD_MANIFEST_KEY, ORGANISM_LEVEL, KNOWLEDGE_CONTEXT,
        # USER_VALUE_STATEMENT
        # Conductor-injected (ADR-020):
        # AGENT_SUBTASK — focused instruction from Conductor plan
        # AGENT_ACCESS_LIST — communication topology (JSON array)
        # AGENT_STEP_INDEX — step position in workflow plan
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
        { name = "OTEL_SERVICE_NAME", value = "${var.name_prefix}-squad-agent" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "deployment.environment=${var.environment},service.namespace=fde-factory" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "squad-agent"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "test -f /tmp/agent_ready || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
    },
    # ADOT Sidecar for distributed tracing
    {
      name      = "adot-collector"
      image     = "${var.ecr_repository_url}:adot-v0.40.0"
      essential = false

      command = ["--config=/etc/ecs/ecs-xray.yaml"]

      portMappings = [
        { containerPort = 4317, protocol = "tcp" },
        { containerPort = 4318, protocol = "tcp" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "adot-agent"
        }
      }
    }
  ])

  tags = {
    Component   = "squad-agent"
    Environment = var.environment
  }
}

# ─── Outputs ─────────────────────────────────────────────────────
output "agent_task_definition_arn" {
  description = "ARN of the parametrized agent task definition"
  value       = aws_ecs_task_definition.agent.arn
}

output "agent_task_definition_family" {
  description = "Family name of the agent task definition"
  value       = aws_ecs_task_definition.agent.family
}

output "agent_task_definition_revision" {
  description = "Latest revision of the agent task definition"
  value       = aws_ecs_task_definition.agent.revision
}
