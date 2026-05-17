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
  description    = "Routes dispatched tasks to strands-agent ECS via TASK_ID (distributed + reaper redispatch)"

  # Only match "distributed" — monolith tasks are handled by the always-on
  # ALM rule (Target 2 in eventbridge.tf). Matching "monolith" here caused
  # fan-out: 2 containers for the same task (ALM rule + dispatch rule).
  #
  # The reaper emits with target_mode="distributed" for re-dispatch to ensure
  # this rule fires and starts a container with TASK_ID.
  # Ref: TASK-f49dbb7c — fan-out caused duplicate containers and race conditions.
  event_pattern = jsonencode({
    source      = ["fde.internal"]
    detail-type = ["task.dispatched"]
    detail = {
      target_mode = ["distributed"]
    }
  })

  tags = { Component = "cognitive-router", DispatchTarget = "strands-agent" }
}

# ─── Dead Letter Queue for Target Invocation Failures ────────────
# Captures events where the InputTransformer or ECS RunTask fails silently.
# Without this, failed target invocations are lost with no observability.
# Well-Architected: REL 11 — Use fault isolation to protect your workload

resource "aws_sqs_queue" "dispatch_dlq" {
  name                      = "${local.name_prefix}-dispatch-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = { Component = "cognitive-router", Purpose = "dead-letter" }
}

resource "aws_sqs_queue_policy" "dispatch_dlq_policy" {
  queue_url = aws_sqs_queue.dispatch_dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowEventBridgeSendMessage"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.dispatch_dlq.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_cloudwatch_event_rule.dispatch_distributed.arn
        }
      }
    }]
  })
}

resource "aws_cloudwatch_event_target" "dispatch_distributed_ecs" {
  rule           = aws_cloudwatch_event_rule.dispatch_distributed.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "dispatch-orchestrator"
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  # Dead letter queue — captures events where InputTransformer or RunTask fails
  dead_letter_config {
    arn = aws_sqs_queue.dispatch_dlq.arn
  }

  ecs_target {
    task_count          = 1
    task_definition_arn = aws_ecs_task_definition.strands_agent.arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = module.vpc.private_subnet_ids
      security_groups  = [module.vpc.ecs_security_group_id]
      assign_public_ip = false
    }
  }

  # Pass task_id and depth as env vars to the strands-agent (monolith fallback)
  # When orchestrator is ready: change task_definition_arn back to
  # module.ecs_distributed.orchestrator_task_definition_arn and container name to "orchestrator"
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
          "name": "strands-agent",
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

# ─── OPS 6: Log ALL dispatch_distributed events to CloudWatch ────
# Provides visibility into every dispatch attempt — success or failure.
# The ECS target above may fail silently (IAM, capacity, etc.) but
# this log target always succeeds, giving operators a complete audit trail.
resource "aws_cloudwatch_event_target" "dispatch_distributed_log" {
  rule           = aws_cloudwatch_event_rule.dispatch_distributed.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "dispatch-distributed-log"
  arn            = aws_cloudwatch_log_group.cognitive_router.arn
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

# ─── ECS Target for Monolith Dispatch (single-path formalization) ────────
# In distributed mode, tasks with depth < 0.5 are routed here by the Lambda.
# Previously these tasks relied on the always-on Target 2 (ALM rule → ECS),
# which is now conditional (only active in monolith mode for rollback).
# This target ensures monolith tasks get a container in distributed mode.
#
# Only active when execution_mode = "distributed" — in monolith mode,
# the ALM rule targets handle everything directly.
resource "aws_cloudwatch_event_target" "dispatch_monolith_ecs" {
  count          = var.execution_mode == "distributed" ? 1 : 0
  rule           = aws_cloudwatch_event_rule.dispatch_monolith.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "dispatch-monolith-ecs"
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_count          = 1
    task_definition_arn = aws_ecs_task_definition.strands_agent.arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = module.vpc.private_subnet_ids
      security_groups  = [module.vpc.ecs_security_group_id]
      assign_public_ip = false
    }
  }

  # Same InputTransformer as dispatch_distributed — passes task_id and metadata
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
          "name": "strands-agent",
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

# ─── CloudWatch Alarm: Dispatch DLQ Depth ────────────────────────
# Alert if ANY messages land in the DLQ — indicates InputTransformer
# or ECS RunTask failures that bypass the sanitization layer.
# Well-Architected: OPS 8 — Understand operational health

resource "aws_cloudwatch_metric_alarm" "dispatch_dlq_depth" {
  alarm_name          = "${local.name_prefix}-dispatch-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Dispatch DLQ has messages — EventBridge target invocation failed (InputTransformer or RunTask)"

  dimensions = {
    QueueName = aws_sqs_queue.dispatch_dlq.name
  }

  tags = { Component = "cognitive-router", Severity = "high" }
}

# ─── REL 11: DLQ Reprocessing via ecs-failure-handler ────────────
# When RunTask fails at the EventBridge target level (IAM denied, capacity),
# the event lands in the DLQ. This event source mapping triggers the
# ecs-failure-handler Lambda to extract the task_id and re-dispatch.
# The handler already has _attempt_redispatch logic — we just need to
# route DLQ messages to it.

resource "aws_lambda_event_source_mapping" "dispatch_dlq_reprocess" {
  event_source_arn = aws_sqs_queue.dispatch_dlq.arn
  function_name    = aws_lambda_function.ecs_failure_handler.arn
  batch_size       = 1
  enabled          = true

  # Process one at a time to avoid thundering herd on retry
  maximum_batching_window_in_seconds = 30
}

# Grant the failure handler permission to read from the DLQ
resource "aws_iam_role_policy" "ecs_failure_handler_dlq" {
  name = "${local.name_prefix}-failure-handler-dlq"
  role = aws_iam_role.ecs_failure_handler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ]
      Resource = aws_sqs_queue.dispatch_dlq.arn
    }]
  })
}
