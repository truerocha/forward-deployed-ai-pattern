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
