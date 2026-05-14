# ═══════════════════════════════════════════════════════════════════
# Webhook Ingest Lambda — Bridges EventBridge events to DynamoDB task_queue
# ═══════════════════════════════════════════════════════════════════
#
# Problem (COE-012):
#   Webhooks arrive on EventBridge and trigger ECS RunTask directly,
#   but the task_queue table is never populated. The dashboard shows
#   nothing because it reads from task_queue.
#
# Solution:
#   Add this Lambda as a SECOND target on the same EventBridge rules.
#   It writes the task record to DynamoDB so the dashboard can display it.
#   The ECS target continues to handle execution independently.
#
# Architecture:
#   EventBridge Rule → Target 1: ECS RunTask (executes the task)
#                    → Target 2: This Lambda (records the task for dashboard)
#
# Well-Architected alignment:
#   OPS 6: Telemetry — every task tracked from ingestion
#   REL 2: Decoupled write from execution
# ═══════════════════════════════════════════════════════════════════

# ─── Lambda Function ─────────────────────────────────────────────

data "archive_file" "webhook_ingest_zip" {
  type        = "zip"
  output_path = "${path.module}/.build/webhook_ingest.zip"

  source {
    content  = file("${path.module}/lambda/webhook_ingest/index.py")
    filename = "index.py"
  }
}

resource "aws_lambda_function" "webhook_ingest" {
  function_name    = "${local.name_prefix}-webhook-ingest"
  role             = aws_iam_role.webhook_ingest_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128
  filename         = data.archive_file.webhook_ingest_zip.output_path
  source_code_hash = data.archive_file.webhook_ingest_zip.output_base64sha256

  environment {
    variables = {
      TASK_QUEUE_TABLE          = aws_dynamodb_table.task_queue.name
      AGENT_LIFECYCLE_TABLE     = aws_dynamodb_table.agent_lifecycle.name
      METRICS_TABLE             = module.dynamodb_distributed.metrics_table_name
      EVENT_BUS_NAME            = aws_cloudwatch_event_bus.factory.name
      ENVIRONMENT               = var.environment
      AWS_REGION_NAME           = var.aws_region
      DEPTH_THRESHOLD           = "0.5"
      COGNITIVE_ROUTING_ENABLED = "true"
    }
  }

  tags = { Component = "webhook-ingest", Architecture = "cognitive-router" }
}

resource "aws_cloudwatch_log_group" "webhook_ingest" {
  name              = "/aws/lambda/${local.name_prefix}-webhook-ingest"
  retention_in_days = 14
  tags              = { Component = "webhook-ingest" }
}

# ─── IAM Role ────────────────────────────────────────────────────

resource "aws_iam_role" "webhook_ingest_role" {
  name = "${local.name_prefix}-webhook-ingest-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = { Component = "webhook-ingest" }
}

resource "aws_iam_role_policy" "webhook_ingest_policy" {
  name = "webhook-ingest-permissions"
  role = aws_iam_role.webhook_ingest_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBWriteTaskQueue"
        Effect = "Allow"
        Action = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Scan"]
        Resource = [
          aws_dynamodb_table.task_queue.arn,
          aws_dynamodb_table.agent_lifecycle.arn,
        ]
      },
      {
        Sid    = "DynamoDBReadMetrics"
        Effect = "Allow"
        Action = ["dynamodb:Query", "dynamodb:GetItem"]
        Resource = [
          module.dynamodb_distributed.metrics_table_arn,
          "${module.dynamodb_distributed.metrics_table_arn}/index/*",
        ]
      },
      {
        Sid      = "EventBridgePutDispatchEvent"
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = [aws_cloudwatch_event_bus.factory.arn]
      },
      {
        Sid      = "CloudWatchLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
      }
    ]
  })
}

# ─── EventBridge Targets (second target on existing rules) ───────
# Each ALM rule now has TWO targets:
#   1. ECS RunTask (existing, in eventbridge.tf)
#   2. This Lambda (new, writes to DynamoDB for dashboard)

resource "aws_cloudwatch_event_target" "github_ingest" {
  rule           = aws_cloudwatch_event_rule.github_factory_ready.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "github-webhook-ingest"
  arn            = aws_lambda_function.webhook_ingest.arn
}

resource "aws_cloudwatch_event_target" "gitlab_ingest" {
  rule           = aws_cloudwatch_event_rule.gitlab_factory_ready.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "gitlab-webhook-ingest"
  arn            = aws_lambda_function.webhook_ingest.arn
}

resource "aws_cloudwatch_event_target" "asana_ingest" {
  rule           = aws_cloudwatch_event_rule.asana_factory_ready.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  target_id      = "asana-webhook-ingest"
  arn            = aws_lambda_function.webhook_ingest.arn
}

# ─── Lambda Permissions (allow EventBridge to invoke) ────────────

resource "aws_lambda_permission" "github_ingest_invoke" {
  statement_id  = "AllowEventBridgeGitHub"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.github_factory_ready.arn
}

resource "aws_lambda_permission" "gitlab_ingest_invoke" {
  statement_id  = "AllowEventBridgeGitLab"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.gitlab_factory_ready.arn
}

resource "aws_lambda_permission" "asana_ingest_invoke" {
  statement_id  = "AllowEventBridgeAsana"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.asana_factory_ready.arn
}
