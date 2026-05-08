# ═══════════════════════════════════════════════════════════════════
# EventBridge Observability — Bus Logging + Failed Delivery Alarms
# ═══════════════════════════════════════════════════════════════════
#
# Root cause analysis (COE-011):
#   Webhook delivered (HTTP 200) but no ECS task ran.
#   HTTP 200 confirms API Gateway received the request, but does NOT
#   confirm EventBridge accepted the event or that a rule matched.
#
# This file adds:
#   1. Catch-all logging rule — captures ALL events on the bus
#   2. CloudWatch alarm for EventBridge FailedInvocations
#   3. CloudWatch alarm for API Gateway 4xx/5xx on webhook routes
#
# Well-Architected alignment:
#   OPS 6: Workload telemetry — see every event on the bus
#   OPS 8: Respond to events — alarm when delivery fails
#   REL 9: Fault isolation — identify which hop is broken
# ═══════════════════════════════════════════════════════════════════

# ─── CloudWatch Log Group for EventBridge Bus Events ─────────────

resource "aws_cloudwatch_log_group" "eventbridge_bus" {
  name              = "/aws/events/${local.name_prefix}-factory-bus"
  retention_in_days = 14
  tags              = { Component = "observability" }
}

# ─── Catch-All Rule: Log Every Event on the Bus ─────────────────
# This rule matches ALL events regardless of source or detail-type.
# Purpose: confirm events reach the bus and inspect their structure.
# Cost: minimal (CloudWatch Logs ingestion only, 14-day retention).

resource "aws_cloudwatch_event_rule" "bus_catch_all" {
  name           = "${local.name_prefix}-bus-catch-all-log"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Logs all events on the factory bus for observability (OPS 6)"
  event_pattern  = jsonencode({ "source" = [{ "prefix" = "" }] })
  tags           = { Component = "observability" }
}

resource "aws_cloudwatch_event_target" "bus_catch_all_logs" {
  rule           = aws_cloudwatch_event_rule.bus_catch_all.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "catch-all-cloudwatch-logs"
  arn            = aws_cloudwatch_log_group.eventbridge_bus.arn
}

# ─── Resource Policy: Allow EventBridge to write to CloudWatch Logs ──

resource "aws_cloudwatch_log_resource_policy" "eventbridge_to_logs" {
  policy_name = "${local.name_prefix}-eventbridge-to-logs"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.eventbridge_bus.arn}:*"
    }]
  })
}

# ─── Alarm: EventBridge Rule FailedInvocations ───────────────────
# Fires when EventBridge matches a rule but fails to invoke the target
# (e.g., ECS RunTask fails due to IAM, capacity, or network issues).

resource "aws_cloudwatch_metric_alarm" "eventbridge_failed_invocations" {
  alarm_name          = "${local.name_prefix}-eventbridge-failed-invocations"
  alarm_description   = "EventBridge matched a rule but failed to invoke the ECS target"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/Events"
  metric_name = "FailedInvocations"
  dimensions = {
    RuleName = aws_cloudwatch_event_rule.github_factory_ready.name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]
  ok_actions    = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm: API Gateway 5xx Errors on Webhook Routes ────────────
# If API Gateway returns 5xx, the EventBridge PutEvents call failed.
# This catches IAM permission issues or bus ARN mismatches.

resource "aws_cloudwatch_metric_alarm" "webhook_api_5xx" {
  alarm_name          = "${local.name_prefix}-webhook-api-5xx"
  alarm_description   = "API Gateway webhook returning 5xx — EventBridge PutEvents likely failing"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/ApiGateway"
  metric_name = "5xx"
  dimensions = {
    ApiId = aws_apigatewayv2_api.webhook.id
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm: API Gateway 4xx Errors on Webhook Routes ────────────
# 4xx errors indicate malformed requests or auth issues from GitHub.
# Threshold set to 5 to avoid noise from scanners/bots.

resource "aws_cloudwatch_metric_alarm" "webhook_api_4xx" {
  alarm_name          = "${local.name_prefix}-webhook-api-4xx"
  alarm_description   = "API Gateway webhook returning 4xx — check request format or auth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 5
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/ApiGateway"
  metric_name = "4xx"
  dimensions = {
    ApiId = aws_apigatewayv2_api.webhook.id
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}


# ═══════════════════════════════════════════════════════════════════
# ECS Failure Handler — Closes the "silent failure" gap (COE-020)
#
# Problem: ECS task fails to start (CannotPullContainer, etc.) but
# nobody knows — the portal shows "ingested" forever, no alerts fire.
#
# Solution:
#   1. EventBridge rule captures ECS Task State Change (STOPPED)
#   2. Scheduled rule runs every 5 min to detect stuck tasks
#   3. Lambda updates DynamoDB + emits portal event + sends SNS alert
# ═══════════════════════════════════════════════════════════════════

# ─── Lambda Function: ECS Failure Handler ────────────────────────

resource "aws_lambda_function" "ecs_failure_handler" {
  function_name = "${local.name_prefix}-ecs-failure-handler"
  runtime       = "python3.12"
  handler       = "index.handler"
  timeout       = 30
  memory_size   = 128

  role = aws_iam_role.ecs_failure_handler.arn

  filename         = data.archive_file.ecs_failure_handler_zip.output_path
  source_code_hash = data.archive_file.ecs_failure_handler_zip.output_base64sha256

  environment {
    variables = {
      TASK_QUEUE_TABLE        = aws_dynamodb_table.task_queue.name
      SNS_TOPIC_ARN           = aws_sns_topic.pipeline_alerts.arn
      ENVIRONMENT             = var.environment
      AWS_REGION_NAME         = var.aws_region
      STUCK_THRESHOLD_MINUTES = "5"
    }
  }

  tags = { Component = "observability" }
}

data "archive_file" "ecs_failure_handler_zip" {
  type        = "zip"
  output_path = "${path.module}/.build/ecs_failure_handler.zip"

  source {
    content  = file("${path.module}/lambda/ecs_failure_handler/index.py")
    filename = "index.py"
  }
}

resource "aws_cloudwatch_log_group" "ecs_failure_handler" {
  name              = "/aws/lambda/${local.name_prefix}-ecs-failure-handler"
  retention_in_days = 30
  tags              = { Component = "observability" }
}

# ─── IAM Role ────────────────────────────────────────────────────

resource "aws_iam_role" "ecs_failure_handler" {
  name = "${local.name_prefix}-ecs-failure-handler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Component = "observability" }
}

resource "aws_iam_role_policy" "ecs_failure_handler" {
  name = "${local.name_prefix}-ecs-failure-handler-policy"
  role = aws_iam_role.ecs_failure_handler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.pipeline_alerts.arn]
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:GetItem"]
        Resource = [
          aws_dynamodb_table.task_queue.arn,
          "${aws_dynamodb_table.task_queue.arn}/index/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:*:*:*"]
      }
    ]
  })
}

# ─── EventBridge Rule: ECS Task State Change (STOPPED with error) ─

resource "aws_cloudwatch_event_rule" "ecs_task_failure" {
  name        = "${local.name_prefix}-ecs-task-failure"
  description = "Captures ECS task failures (CannotPullContainer, OOM, etc.)"

  event_pattern = jsonencode({
    "source"      = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    "detail" = {
      "lastStatus" = ["STOPPED"]
      "clusterArn" = [aws_ecs_cluster.factory.arn]
    }
  })

  tags = { Component = "observability" }
}

resource "aws_cloudwatch_event_target" "ecs_task_failure_lambda" {
  rule      = aws_cloudwatch_event_rule.ecs_task_failure.name
  target_id = "ecs-failure-handler"
  arn       = aws_lambda_function.ecs_failure_handler.arn
}

resource "aws_lambda_permission" "ecs_failure_from_eventbridge" {
  statement_id  = "AllowECSFailureEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ecs_failure_handler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_failure.arn
}

# ─── Scheduled Rule: Stuck Task Detection (every 5 min) ──────────

resource "aws_cloudwatch_event_rule" "stuck_task_detection" {
  name                = "${local.name_prefix}-stuck-task-detection"
  description         = "Runs every 5 min to detect tasks stuck in ingested/workspace"
  schedule_expression = "rate(5 minutes)"
  tags                = { Component = "observability" }
}

resource "aws_cloudwatch_event_target" "stuck_task_detection_lambda" {
  rule      = aws_cloudwatch_event_rule.stuck_task_detection.name
  target_id = "stuck-task-detector"
  arn       = aws_lambda_function.ecs_failure_handler.arn
}

resource "aws_lambda_permission" "stuck_detection_from_eventbridge" {
  statement_id  = "AllowStuckDetectionSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ecs_failure_handler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.stuck_task_detection.arn
}
