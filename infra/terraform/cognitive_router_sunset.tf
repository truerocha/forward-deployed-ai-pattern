# ═══════════════════════════════════════════════════════════════════
# Cognitive Router — Sunset Reminder (Self-Enforcing Cleanup)
# ═══════════════════════════════════════════════════════════════════
#
# Problem: ADR-030 says "remove execution_mode after 7 days of stable
# cognitive routing." But ADR text is passive — nobody reads it again.
#
# Solution: Infrastructure that REMINDS you:
#   1. CloudWatch alarm evaluates 168 hourly periods (7 days)
#   2. If cognitive router Lambda has zero errors for 7 consecutive days
#      → alarm transitions to OK → SNS notification fires
#   3. SNS message: "Safe to remove execution_mode variable"
#   4. Terraform output on every plan/apply shows the sunset notice
#
# This file is SELF-DELETING: when you remove execution_mode, delete
# this file too (the alarm and SNS topic are no longer needed).
# ═══════════════════════════════════════════════════════════════════

# ─── SNS Topic: Sunset Notification ─────────────────────────────
resource "aws_sns_topic" "cognitive_router_sunset" {
  name = "${local.name_prefix}-cognitive-router-sunset"
  tags = { Component = "cognitive-router", Purpose = "sunset-reminder" }
}

# ─── CloudWatch Alarm: 7 Days Stable ────────────────────────────
# Evaluates 168 consecutive 1-hour periods (7 days).
# If Lambda errors = 0 for all 168 periods → transitions to OK.
# OK transition → SNS notification: "safe to remove execution_mode."
#
# This is a "good news" alarm: it fires when things are STABLE,
# not when they break. The notification is the cleanup signal.

resource "aws_cloudwatch_metric_alarm" "cognitive_router_stable_7d" {
  alarm_name          = "${local.name_prefix}-cognitive-router-stable-7d"
  comparison_operator = "LessThanOrEqualToThreshold"
  evaluation_periods  = 168
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 3600
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  alarm_description = <<-DESC
    ADR-030 Sunset Signal: Cognitive router has been error-free for 7 days.
    ACTION REQUIRED: Remove var.execution_mode from variables.tf and factory.tfvars.
    Also delete this file (cognitive_router_sunset.tf) — it served its purpose.
  DESC

  dimensions = {
    FunctionName = aws_lambda_function.webhook_ingest.function_name
  }

  # Notify when stable (OK = 7 days clean)
  ok_actions = [aws_sns_topic.cognitive_router_sunset.arn]

  tags = { Component = "cognitive-router", Purpose = "sunset-reminder" }
}

# ─── Terraform Output: Visible on every plan/apply ───────────────
output "cognitive_router_sunset_notice" {
  description = "ADR-030 sunset status. When alarm reaches OK, remove execution_mode variable."
  value = var.execution_mode == "distributed" ? (
    "⚠️  execution_mode is LEGACY — cognitive router decides per-task. Monitor 'cognitive-router-stable-7d' alarm. When OK → remove variable + this file."
  ) : (
    "execution_mode=monolith — cognitive routing may be disabled. Check COGNITIVE_ROUTING_ENABLED on webhook_ingest Lambda."
  )
}
