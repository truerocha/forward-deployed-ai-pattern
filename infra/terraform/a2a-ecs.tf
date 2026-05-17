# ─────────────────────────────────────────────────────────────────────────────
# A2A Protocol — ECS Fargate Infrastructure
#
# Deploys three A2A agent services (pesquisa, escrita, revisao) as independent
# ECS Fargate services with AWS Cloud Map service discovery.
#
# IMPORTANT: This file uses EXISTING resources from main.tf and distributed-infra.tf:
#   - aws_ecs_cluster.factory (ECS cluster)
#   - aws_iam_role.ecs_task_execution (execution role)
#   - aws_iam_role.ecs_task (task role — Bedrock + DynamoDB access)
#   - aws_ecr_repository.strands_agent (shared ECR repo, tag-based selection)
#   - module.vpc (VPC, subnets, security group)
#   - module.dynamodb_distributed.knowledge_table_name (knowledge table)
#   - aws_cloudwatch_log_group.factory (shared log group)
#   - local.name_prefix, local.region
#
# No new IAM roles, ECR repos, or VPCs are created — zero drift risk.
#
# Ref: ADR-034 (A2A Protocol), ADR-009 (AWS Cloud Infrastructure)
# ─────────────────────────────────────────────────────────────────────────────

# ─── Cloud Map Service Discovery Namespace ───────────────────────────────────

resource "aws_service_discovery_private_dns_namespace" "a2a" {
  name        = "fde.local"
  description = "FDE A2A agent service discovery namespace"
  vpc         = module.vpc.vpc_id

  tags = {
    Component = "a2a-protocol"
  }
}

# ─── DynamoDB Table for A2A Workflow State Checkpointing ─────────────────────

resource "aws_dynamodb_table" "a2a_workflow_state" {
  name         = "${local.name_prefix}-a2a-workflow-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "workflow_id"
  range_key    = "checkpoint_key"

  attribute {
    name = "workflow_id"
    type = "S"
  }

  attribute {
    name = "checkpoint_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component = "a2a-protocol"
    Purpose   = "workflow-checkpointing"
  }
}

# ─── IAM: A2A-specific DynamoDB access (appended to existing task role) ──────

resource "aws_iam_role_policy" "ecs_task_a2a_dynamodb" {
  name = "${local.name_prefix}-a2a-dynamodb-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.a2a_workflow_state.arn,
          "${aws_dynamodb_table.a2a_workflow_state.arn}/index/*"
        ]
      }
    ]
  })
}

# ─── ECS Task Definitions (one per A2A agent type) ───────────────────────────

resource "aws_ecs_task_definition" "a2a_agent" {
  for_each = {
    pesquisa = { port = 9001, cpu = "512", memory = "1024" }
    escrita  = { port = 9002, cpu = "512", memory = "1024" }
    revisao  = { port = 9003, cpu = "256", memory = "512" }
  }

  family                   = "${local.name_prefix}-a2a-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  # EFS volume for workspace persistence — standard for all FDE containers.
  # Available immediately on container start (no ENI dependency for local writes).
  # Ref: TASK-f49dbb7c lesson learned — all containers need local storage fallback.
  volume {
    name = "workspaces"

    efs_volume_configuration {
      file_system_id          = module.efs.file_system_id
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = module.efs.access_point_id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "a2a-${each.key}"
      image     = "${aws_ecr_repository.strands_agent.repository_url}:a2a-${each.key}-latest"
      essential = true

      mountPoints = [
        {
          sourceVolume  = "workspaces"
          containerPath = "/workspaces"
          readOnly      = false
        }
      ]

      portMappings = [{
        containerPort = each.value.port
        hostPort      = each.value.port
        protocol      = "tcp"
      }]

      environment = [
        { name = "A2A_AGENT_TYPE", value = each.key },
        { name = "A2A_PORT", value = tostring(each.value.port) },
        { name = "AWS_REGION", value = local.region },
        { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id },
        { name = "A2A_STATE_TABLE", value = aws_dynamodb_table.a2a_workflow_state.name },
        { name = "KNOWLEDGE_TABLE", value = module.dynamodb_distributed.knowledge_table_name },
        { name = "MEMORY_TABLE", value = module.dynamodb_distributed.memory_table_name },
        { name = "A2A_SESSIONS_BUCKET", value = aws_s3_bucket.factory_artifacts.id },
        { name = "PROJECT_ID", value = var.project_id },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "LOG_LEVEL", value = var.environment == "prod" ? "WARNING" : "INFO" },
        # OTEL: traces to ADOT sidecar on localhost
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
        { name = "OTEL_SERVICE_NAME", value = "${local.name_prefix}-a2a-${each.key}" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "deployment.environment=${var.environment},service.namespace=fde-a2a" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.factory.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "a2a-${each.key}"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:${each.value.port}/.well-known/agent-card.json || exit 1"]
        interval    = 10
        timeout     = 3
        retries     = 2
        startPeriod = 30
      }
    },
    # ADOT Sidecar for distributed tracing
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
          "awslogs-stream-prefix" = "a2a-adot-${each.key}"
        }
      }
    }
  ])

  tags = {
    Component = "a2a-protocol"
    AgentType = each.key
  }
}

# ─── Cloud Map Service Discovery Services ────────────────────────────────────

resource "aws_service_discovery_service" "a2a" {
  for_each = {
    pesquisa = 9001
    escrita  = 9002
    revisao  = 9003
  }

  name = each.key

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.a2a.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Component = "a2a-protocol"
  }
}

# ─── ECS Services (one per agent type) ───────────────────────────────────────

resource "aws_ecs_service" "a2a" {
  for_each = {
    pesquisa = { port = 9001, desired_count = 1 }
    escrita  = { port = 9002, desired_count = 1 }
    revisao  = { port = 9003, desired_count = 1 }
  }

  name            = "${local.name_prefix}-a2a-${each.key}"
  cluster         = aws_ecs_cluster.factory.id
  task_definition = aws_ecs_task_definition.a2a_agent[each.key].arn
  desired_count   = each.value.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnet_ids
    security_groups  = [module.vpc.ecs_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.a2a[each.key].arn
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Component = "a2a-protocol"
    AgentType = each.key
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ─── Auto Scaling: A2A Services (Fase 1 — independent scaling) ───────────────
# Each A2A service scales independently based on CPU utilization.
# This prevents neighborhood noise from Strands burst affecting A2A latency.
# Threshold: CPU > 70% → scale out. CPU < 30% → scale in.
# Min=1 (always available), Max=3 (cost cap for dev).
# Well-Architected: PERF 1 (Right-size), COST 7 (Right-size resources)

resource "aws_appautoscaling_target" "a2a" {
  for_each = toset(["pesquisa", "escrita", "revisao"])

  max_capacity       = var.environment == "prod" ? 5 : 3
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.factory.name}/${aws_ecs_service.a2a[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "a2a_cpu" {
  for_each = toset(["pesquisa", "escrita", "revisao"])

  name               = "${local.name_prefix}-a2a-${each.key}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.a2a[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.a2a[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.a2a[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# ─── CloudWatch Alarm: A2A Latency (Fase 2 trigger) ─────────────────────────
# If A2A p99 response time exceeds 3s, it indicates neighborhood noise.
# This alarm is the decision gate for Fase 2 (cluster separation).
# Well-Architected: OPS 8 (Anticipate failure), PERF 4 (Monitor resources)

resource "aws_cloudwatch_metric_alarm" "a2a_latency_gate" {
  alarm_name          = "${local.name_prefix}-a2a-latency-fase2-gate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "A2A CPU > 85% sustained — evaluate Fase 2 (cluster separation) for latency isolation"

  dimensions = {
    ClusterName = aws_ecs_cluster.factory.name
    ServiceName = "${local.name_prefix}-a2a-pesquisa"
  }

  tags = {
    Component = "a2a-protocol"
    Purpose   = "fase2-decision-gate"
  }
}

# ─── Outputs ─────────────────────────────────────────────────────────────────

output "a2a_namespace_id" {
  description = "Cloud Map namespace ID for A2A service discovery"
  value       = aws_service_discovery_private_dns_namespace.a2a.id
}

output "a2a_state_table_name" {
  description = "DynamoDB table name for A2A workflow state"
  value       = aws_dynamodb_table.a2a_workflow_state.name
}

output "a2a_state_table_arn" {
  description = "DynamoDB table ARN for A2A workflow state"
  value       = aws_dynamodb_table.a2a_workflow_state.arn
}

output "a2a_agent_endpoints" {
  description = "Internal DNS endpoints for A2A agents"
  value = {
    pesquisa = "http://pesquisa.fde.local:9001"
    escrita  = "http://escrita.fde.local:9002"
    revisao  = "http://revisao.fde.local:9003"
  }
}
