# ═══════════════════════════════════════════════════════════════════
# EventBridge — ALM Webhook → ECS Fargate Agent Orchestration
# ═══════════════════════════════════════════════════════════════════
#
# Flow: ALM Webhook → API Gateway → EventBridge → ECS RunTask
#
# GitHub/GitLab/Asana send webhooks to API Gateway.
# API Gateway forwards to EventBridge custom event bus.
# EventBridge rules match "factory-ready" events and trigger ECS RunTask.
# ═══════════════════════════════════════════════════════════════════

resource "aws_cloudwatch_event_bus" "factory" {
  name = "${local.name_prefix}-factory-bus"
  tags = { Component = "eventbridge" }
}

# ─── Rules: one per ALM platform ────────────────────────────────

resource "aws_cloudwatch_event_rule" "github_factory_ready" {
  name           = "${local.name_prefix}-github-factory-ready"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Triggers ECS agent when GitHub issue is labeled factory-ready"
  event_pattern = jsonencode({
    source      = ["fde.github.webhook"]
    detail-type = ["issue.labeled"]
    detail      = { action = ["labeled"], label = { name = ["factory-ready"] } }
  })
  tags = { Component = "eventbridge" }
}

resource "aws_cloudwatch_event_rule" "gitlab_factory_ready" {
  name           = "${local.name_prefix}-gitlab-factory-ready"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Triggers ECS agent when GitLab issue is labeled factory-ready"
  event_pattern = jsonencode({
    source      = ["fde.gitlab.webhook"]
    detail-type = ["issue.updated"]
    detail      = {
      action = ["update"]
    }
  })
  tags = { Component = "eventbridge" }
}

resource "aws_cloudwatch_event_rule" "asana_factory_ready" {
  name           = "${local.name_prefix}-asana-factory-ready"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Triggers ECS agent when Asana task moves to In Progress"
  event_pattern = jsonencode({
    source      = ["fde.asana.webhook"]
    detail-type = ["task.moved"]
  })
  tags = { Component = "eventbridge" }
}

# ─── IAM: EventBridge → ECS RunTask ─────────────────────────────

resource "aws_iam_role" "eventbridge_ecs" {
  name = "${local.name_prefix}-eventbridge-ecs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
    }]
  })
  tags = { Component = "iam" }
}

resource "aws_iam_role_policy" "eventbridge_ecs_run_task" {
  name = "${local.name_prefix}-eventbridge-run-task"
  role = aws_iam_role.eventbridge_ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = [aws_ecs_task_definition.strands_agent.arn]
        Condition = { ArnLike = { "ecs:cluster" = aws_ecs_cluster.factory.arn } }
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_task_execution.arn, aws_iam_role.ecs_task.arn]
      }
    ]
  })
}

# ─── Targets: ECS RunTask with event passthrough ─────────────────

locals {
  ecs_target_config = {
    task_definition_arn = aws_ecs_task_definition.strands_agent.arn
    subnets             = module.vpc.private_subnet_ids
    security_groups     = [module.vpc.ecs_security_group_id]
  }

  input_transformer_paths = {
    source     = "$.source"
    detailType = "$.detail-type"
    detail     = "$.detail"
  }

  input_transformer_template = <<-TEMPLATE
    {
      "containerOverrides": [{
        "name": "strands-agent",
        "environment": [{
          "name": "EVENTBRIDGE_EVENT",
          "value": "{\"source\":\"<source>\",\"detail-type\":\"<detailType>\",\"detail\":<detail>}"
        }]
      }]
    }
  TEMPLATE
}

resource "aws_cloudwatch_event_target" "github_ecs" {
  rule           = aws_cloudwatch_event_rule.github_factory_ready.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "github-ecs-agent"
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_count          = 1
    task_definition_arn = local.ecs_target_config.task_definition_arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = local.ecs_target_config.subnets
      security_groups  = local.ecs_target_config.security_groups
      assign_public_ip = false
    }
  }

  input_transformer {
    input_paths    = local.input_transformer_paths
    input_template = local.input_transformer_template
  }
}

resource "aws_cloudwatch_event_target" "gitlab_ecs" {
  rule           = aws_cloudwatch_event_rule.gitlab_factory_ready.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "gitlab-ecs-agent"
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_count          = 1
    task_definition_arn = local.ecs_target_config.task_definition_arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = local.ecs_target_config.subnets
      security_groups  = local.ecs_target_config.security_groups
      assign_public_ip = false
    }
  }

  input_transformer {
    input_paths    = local.input_transformer_paths
    input_template = local.input_transformer_template
  }
}

resource "aws_cloudwatch_event_target" "asana_ecs" {
  rule           = aws_cloudwatch_event_rule.asana_factory_ready.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "asana-ecs-agent"
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_count          = 1
    task_definition_arn = local.ecs_target_config.task_definition_arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = local.ecs_target_config.subnets
      security_groups  = local.ecs_target_config.security_groups
      assign_public_ip = false
    }
  }

  input_transformer {
    input_paths    = local.input_transformer_paths
    input_template = local.input_transformer_template
  }
}
