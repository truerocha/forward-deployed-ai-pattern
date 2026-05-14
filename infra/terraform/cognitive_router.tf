# ═══════════════════════════════════════════════════════════════════
# Cognitive Router — EventBridge Rules for Dispatched Tasks
# ═══════════════════════════════════════════════════════════════════
#
# The webhook_ingest Lambda (enhanced as cognitive router) emits
# fde.internal/task.dispatched events with target_mode in the detail.
#
# Two rules filter by target_mode and start the correct ECS task:
#   Rule 1: target_mode=distributed → orchestrator task def
#   Rule 2: target_mode=monolith → (no-op, monolith already running from
#            the always-on Target 2 on the original ALM rules)
#
# Architecture (dual-path, zero SPOF):
#   EventBridge ALM rule fires →
#     Target 1: webhook_ingest Lambda (cognitive routing, ~200ms)
#       → Emits fde.internal/task.dispatched {target_mode, depth}
#     Target 2: ECS monolith (always starts, 30s cold start)
#       → Checks task_queue: DISPATCHED → exit | READY → run as fallback
#
#   EventBridge dispatch rules (this file):
#     Rule: target_mode=distributed → ECS orchestrator task def
#     (monolith rule is informational — monolith already running)
#
# Risk mitigations:
#   Risk 1 (Lambda timeout): Lambda never calls ecs.run_task() directly.
#     It emits a lightweight event (~200ms total). EventBridge starts ECS.
#   Risk 4 (Task def not deployed): Both task defs always exist (Terraform).
#     If orchestrator RunTask fails, monolith is already running as fallback.
#   Risk 5 (Lambda SPOF): Monolith always starts from original ALM rule.
#     If Lambda fails, task stays READY → monolith runs as fallback.
#
# Well-Architected alignment:
#   REL 9: Fault isolation — dual-path prevents single point of failure
#   OPS 8: Observability — dispatch events carry depth + signals metadata
#   COST 7: Right-sizing — simple tasks stay on monolith (no orchestrator overhead)
# ═══════════════════════════════════════════════════════════════════

# ─── Rule: Dispatch to Distributed (Orchestrator) ────────────────
# Fires when Lambda decides depth ≥ 0.5 → distributed execution.
# Starts the orchestrator ECS task which then dispatches the agent squad.

resource "aws_cloudwatch_event_rule" "dispatch_distributed" {
  name           = "${local.name_prefix}-dispatch-distributed"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Routes high-depth tasks to distributed orchestrator (cognitive router)"

  event_pattern = jsonencode({
    source      = ["fde.internal"]
    detail-type = ["task.dispatched"]
    detail = {
      target_mode = ["distributed"]
    }
  })

  tags = { Component = "cognitive-router", DispatchTarget = "distributed" }
}

resource "aws_cloudwatch_event_target" "dispatch_distributed_ecs" {
  rule           = aws_cloudwatch_event_rule.dispatch_distributed.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "dispatch-orchestrator"
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_count          = 1
    task_definition_arn = module.ecs_distributed.orchestrator_task_definition_arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = module.vpc.private_subnet_ids
      security_groups  = [module.vpc.ecs_security_group_id]
      assign_public_ip = false
    }
  }

  # Pass task_id and depth as env vars to the orchestrator
  input_transformer {
    input_paths = {
      taskId     = "$.detail.task_id"
      targetMode = "$.detail.target_mode"
      depth      = "$.detail.depth"
      repo       = "$.detail.repo"
      issueId    = "$.detail.issue_id"
      title      = "$.detail.title"
      priority   = "$.detail.priority"
    }
    input_template = <<-TEMPLATE
      {
        "containerOverrides": [{
          "name": "orchestrator",
          "environment": [
            {"name": "TASK_ID", "value": "<taskId>"},
            {"name": "TARGET_MODE", "value": "<targetMode>"},
            {"name": "DEPTH", "value": "<depth>"},
            {"name": "EVENT_REPO", "value": "<repo>"},
            {"name": "EVENT_ISSUE_ID", "value": "<issueId>"},
            {"name": "EVENT_ISSUE_TITLE", "value": "<title>"},
            {"name": "EVENT_PRIORITY", "value": "<priority>"}
          ]
        }]
      }
    TEMPLATE
  }
}

# ─── Rule: Dispatch to Monolith (Informational) ─────────────────
# Fires when Lambda decides depth < 0.5 → monolith execution.
# The monolith is ALREADY running from the always-on Target 2 on the
# original ALM rules. This rule exists for observability only — it
# logs the routing decision to CloudWatch for dashboards.
#
# No ECS target needed: monolith is already started by the original
# EventBridge rule (dual-path architecture).

resource "aws_cloudwatch_event_rule" "dispatch_monolith" {
  name           = "${local.name_prefix}-dispatch-monolith"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Logs monolith routing decisions (monolith already running from ALM rule)"

  event_pattern = jsonencode({
    source      = ["fde.internal"]
    detail-type = ["task.dispatched"]
    detail = {
      target_mode = ["monolith"]
    }
  })

  tags = { Component = "cognitive-router", DispatchTarget = "monolith" }
}

# Log monolith dispatch decisions to CloudWatch for observability
resource "aws_cloudwatch_event_target" "dispatch_monolith_log" {
  rule           = aws_cloudwatch_event_rule.dispatch_monolith.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "dispatch-monolith-log"
  arn            = aws_cloudwatch_log_group.cognitive_router.arn
}

# ─── CloudWatch Log Group for Routing Decisions ──────────────────
resource "aws_cloudwatch_log_group" "cognitive_router" {
  name              = "/aws/events/${local.name_prefix}-cognitive-router"
  retention_in_days = 30
  tags              = { Component = "cognitive-router" }
}

# Allow EventBridge to write to the log group
resource "aws_cloudwatch_log_resource_policy" "cognitive_router_events" {
  policy_name = "${local.name_prefix}-cognitive-router-events"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EventBridgeToCloudWatch"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.cognitive_router.arn}:*"
    }]
  })
}

# ─── CloudWatch Alarm: Lambda Failure Rate ───────────────────────
# If the cognitive router Lambda fails >3 times in 5 minutes, alert.
# The monolith fallback handles execution, but we want visibility.

resource "aws_cloudwatch_metric_alarm" "cognitive_router_errors" {
  alarm_name          = "${local.name_prefix}-cognitive-router-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 3
  alarm_description   = "Cognitive router Lambda error rate high — monolith fallback active"

  dimensions = {
    FunctionName = aws_lambda_function.webhook_ingest.function_name
  }

  tags = { Component = "cognitive-router" }
}

# ─── CloudWatch Alarm: Dispatch Latency ──────────────────────────
# Alert if Lambda duration exceeds 500ms (target is <200ms).

resource "aws_cloudwatch_metric_alarm" "cognitive_router_latency" {
  alarm_name          = "${local.name_prefix}-cognitive-router-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Average"
  threshold           = 500
  alarm_description   = "Cognitive router Lambda latency exceeds 500ms target"

  dimensions = {
    FunctionName = aws_lambda_function.webhook_ingest.function_name
  }

  tags = { Component = "cognitive-router" }
}
