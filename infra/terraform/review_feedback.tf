# ═══════════════════════════════════════════════════════════════════
# Review Feedback Loop — Closes the Human-Agent Learning Gap (ADR-027)
# ═══════════════════════════════════════════════════════════════════
#
# Problem:
#   The factory operates open-loop with respect to human PR reviews.
#   When a reviewer submits "changes_requested" or comments "re-work",
#   the factory has no mechanism to detect, record, learn, or re-execute.
#   DORA CFR is understated (only counts pipeline crashes, not human rejections).
#
# Solution:
#   New EventBridge rules match PR review events and trigger:
#     1. Review Feedback Lambda (classifies + records metrics + emits rework)
#     2. Existing webhook_ingest Lambda (updates task_queue status)
#
# Architecture:
#   GitHub PR Review → API Gateway → EventBridge (new rules below)
#     → Target 1: review_feedback Lambda (this file)
#     → Target 2: webhook_ingest Lambda (existing, added as target)
#   If full_rework: review_feedback Lambda → EventBridge (fde.internal/task.rework_requested)
#     → ECS RunTask (re-executes pipeline with feedback context)
#
# Well-Architected:
#   OPS 6: Every review event captured and classified
#   REL 2: Decoupled detection from re-execution
#   COST 5: Lambda pay-per-invocation (~$0.50/month)
#   SEC 8: Review rejections treated as quality incidents
#
# Two-Way Door:
#   Disable by setting var.review_feedback_enabled = false
#   Lambda remains deployed but EventBridge rules are disabled
#   Rollback: terraform apply with review_feedback_enabled = false (< 30s)
# ═══════════════════════════════════════════════════════════════════

# ─── Feature Flag ────────────────────────────────────────────────

variable "review_feedback_enabled" {
  description = "Enable the review feedback loop (ADR-027). Set false to disable without destroying."
  type        = bool
  default     = true
}

# ─── EventBridge Rules ───────────────────────────────────────────

# Rule 1: PR Review submitted (changes_requested, approved, commented)
resource "aws_cloudwatch_event_rule" "pr_review_submitted" {
  name           = "${local.name_prefix}-pr-review-submitted"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Triggers review feedback processing when a PR review is submitted"
  state          = var.review_feedback_enabled ? "ENABLED" : "DISABLED"

  event_pattern = jsonencode({
    source      = ["fde.github.webhook"]
    detail-type = ["pull_request_review.submitted"]
    detail = {
      review = {
        state = ["changes_requested", "approved", "commented"]
      }
    }
  })

  tags = { Component = "review-feedback", ADR = "027" }
}

# Rule 2: Issue comment on PR with re-work signal
resource "aws_cloudwatch_event_rule" "pr_rework_comment" {
  name           = "${local.name_prefix}-pr-rework-comment"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Triggers review feedback when a PR comment contains re-work signals"
  state          = var.review_feedback_enabled ? "ENABLED" : "DISABLED"

  event_pattern = jsonencode({
    source      = ["fde.github.webhook"]
    detail-type = ["issue_comment.created"]
    detail = {
      issue = {
        pull_request = [{ "exists" = true }]
      }
    }
  })

  tags = { Component = "review-feedback", ADR = "027" }
}

# Rule 3: Internal rework event → ECS re-execution
resource "aws_cloudwatch_event_rule" "task_rework_requested" {
  name           = "${local.name_prefix}-task-rework-requested"
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  description    = "Re-triggers ECS agent when a task rework is requested from review feedback"
  state          = var.review_feedback_enabled ? "ENABLED" : "DISABLED"

  event_pattern = jsonencode({
    source      = ["fde.internal"]
    detail-type = ["task.rework_requested"]
  })

  tags = { Component = "review-feedback", ADR = "027" }
}

# ─── Lambda Function ─────────────────────────────────────────────

data "archive_file" "review_feedback_zip" {
  type        = "zip"
  output_path = "${path.module}/.build/review_feedback.zip"

  source {
    content  = file("${path.module}/lambda/review_feedback/index.py")
    filename = "index.py"
  }
}

resource "aws_lambda_function" "review_feedback" {
  function_name    = "${local.name_prefix}-review-feedback"
  role             = aws_iam_role.review_feedback_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 256
  filename         = data.archive_file.review_feedback_zip.output_path
  source_code_hash = data.archive_file.review_feedback_zip.output_base64sha256

  environment {
    variables = {
      METRICS_TABLE    = module.dynamodb_distributed.metrics_table_name
      TASK_QUEUE_TABLE = aws_dynamodb_table.task_queue.name
      EVENT_BUS_NAME   = aws_cloudwatch_event_bus.factory.name
      PROJECT_ID       = "global"
      ENVIRONMENT      = var.environment
      AWS_REGION_NAME  = var.aws_region
    }
  }

  tags = { Component = "review-feedback", ADR = "027" }
}

resource "aws_cloudwatch_log_group" "review_feedback" {
  name              = "/aws/lambda/${local.name_prefix}-review-feedback"
  retention_in_days = 14
  tags              = { Component = "review-feedback", ADR = "027" }
}

# ─── IAM Role ────────────────────────────────────────────────────

resource "aws_iam_role" "review_feedback_role" {
  name = "${local.name_prefix}-review-feedback-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = { Component = "review-feedback", ADR = "027" }
}

resource "aws_iam_role_policy" "review_feedback_policy" {
  name = "review-feedback-permissions"
  role = aws_iam_role.review_feedback_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ]
        Resource = [
          module.dynamodb_distributed.metrics_table_arn,
          aws_dynamodb_table.task_queue.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = [aws_cloudwatch_event_bus.factory.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
        ]
      }
    ]
  })
}

# ─── EventBridge Targets ─────────────────────────────────────────

# Target: PR review submitted → Review Feedback Lambda
resource "aws_cloudwatch_event_target" "pr_review_feedback" {
  rule           = aws_cloudwatch_event_rule.pr_review_submitted.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "pr-review-feedback-lambda"
  arn            = aws_lambda_function.review_feedback.arn
}

# Target: PR rework comment → Review Feedback Lambda
resource "aws_cloudwatch_event_target" "pr_rework_comment_feedback" {
  rule           = aws_cloudwatch_event_rule.pr_rework_comment.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "pr-rework-comment-feedback-lambda"
  arn            = aws_lambda_function.review_feedback.arn
}

# Target: Rework requested → ECS RunTask (re-execution with feedback context)
resource "aws_cloudwatch_event_target" "rework_ecs" {
  rule           = aws_cloudwatch_event_rule.task_rework_requested.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "rework-ecs-agent"
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

  # Pass rework context as environment variables to the agent
  input_transformer {
    input_paths = {
      taskId        = "$.detail.task_id"
      repo          = "$.detail.repo"
      prNumber      = "$.detail.pr_number"
      reworkAttempt = "$.detail.rework_attempt"
      reviewer      = "$.detail.reviewer"
      constraint    = "$.detail.constraint"
    }

    input_template = <<-TEMPLATE
      {
        "containerOverrides": [{
          "name": "${local.ecs_target_config.container_name}",
          "environment": [
            {"name": "EVENT_SOURCE", "value": "fde.internal"},
            {"name": "EVENT_DETAIL_TYPE", "value": "task.rework_requested"},
            {"name": "EVENT_TASK_ID", "value": "<taskId>"},
            {"name": "EVENT_REPO", "value": "<repo>"},
            {"name": "EVENT_PR_NUMBER", "value": "<prNumber>"},
            {"name": "EVENT_REWORK_ATTEMPT", "value": "<reworkAttempt>"},
            {"name": "EVENT_REVIEWER", "value": "<reviewer>"},
            {"name": "EVENT_REWORK_CONSTRAINT", "value": "<constraint>"}
          ]
        }]
      }
    TEMPLATE
  }
}

# ─── Lambda Permissions (allow EventBridge to invoke) ────────────

resource "aws_lambda_permission" "review_feedback_pr_review" {
  statement_id  = "AllowEventBridgePRReview"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.review_feedback.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.pr_review_submitted.arn
}

resource "aws_lambda_permission" "review_feedback_rework_comment" {
  statement_id  = "AllowEventBridgeReworkComment"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.review_feedback.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.pr_rework_comment.arn
}

# ─── CloudWatch Alarms ───────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "rework_circuit_breaker" {
  alarm_name          = "${local.name_prefix}-rework-circuit-breaker"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ReworkCircuitBreakerTripped"
  namespace           = "FDE/Factory"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "A task has exceeded max rework attempts — Staff Engineer review required"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ProjectId = "global"
  }

  tags = { Component = "review-feedback", ADR = "027" }
}

resource "aws_cloudwatch_metric_alarm" "high_pr_rejection_rate" {
  alarm_name          = "${local.name_prefix}-high-pr-rejection-rate"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "PRRejectedByHuman"
  namespace           = "FDE/Factory"
  period              = 3600
  statistic           = "Sum"
  threshold           = 3
  alarm_description   = "3+ PRs rejected by human reviewers in 3 hours — quality degradation signal"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ProjectId = "global"
  }

  tags = { Component = "review-feedback", ADR = "027" }
}
