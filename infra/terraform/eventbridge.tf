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
    detail = {
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
        Effect    = "Allow"
        Action    = ["ecs:RunTask"]
        Resource  = [aws_ecs_task_definition.strands_agent.arn]
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

  # COE-011: EventBridge InputTransformer + ECS targets cannot reliably pass
  # complex JSON objects as environment variable values. The ECS RunTask API
  # silently rejects the overrides when the value contains unescaped JSON.
  #
  # Solution: Extract individual scalar fields from the event and pass them
  # as separate environment variables. The agent_entrypoint.py reconstructs
  # the event from these flat env vars (EVENT_SOURCE, EVENT_ACTION, etc.).
  #
  # This pattern is proven in production (task 03b21106, 2026-05-07).
  input_transformer_paths = {
    source      = "$.source"
    detailType  = "$.detail-type"
    action      = "$.detail.action"
    labelName   = "$.detail.label.name"
    issueNumber = "$.detail.issue.number"
    issueTitle  = "$.detail.issue.title"
    repoName    = "$.detail.repository.full_name"
  }

  input_transformer_template = <<-TEMPLATE
    {
      "containerOverrides": [{
        "name": "strands-agent",
        "environment": [
          {"name": "EVENT_SOURCE", "value": "<source>"},
          {"name": "EVENT_DETAIL_TYPE", "value": "<detailType>"},
          {"name": "EVENT_ACTION", "value": "<action>"},
          {"name": "EVENT_LABEL", "value": "<labelName>"},
          {"name": "EVENT_ISSUE_NUMBER", "value": "<issueNumber>"},
          {"name": "EVENT_ISSUE_TITLE", "value": "<issueTitle>"},
          {"name": "EVENT_REPO", "value": "<repoName>"}
        ]
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
