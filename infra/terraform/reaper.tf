# ═══════════════════════════════════════════════════════════════════
# Scheduled Reaper Lambda — Self-healing for stuck tasks (ADR-022)
# ═══════════════════════════════════════════════════════════════════
#
# Triggered every 5 minutes by CloudWatch Events. Heals:
#   1. Stuck tasks (IN_PROGRESS/READY with no heartbeat)
#   2. Counter drift (ungraceful ECS stops leave phantom slots)
#   3. Queued tasks blocked by freed slots
#
# Two-Way Door: disable by setting reaper_enabled = false
# ═══════════════════════════════════════════════════════════════════

variable "reaper_enabled" {
  description = "Enable the scheduled reaper Lambda. Set false to disable without destroying."
  type        = bool
  default     = true
}

# ─── Package ─────────────────────────────────────────────────────

data "archive_file" "reaper" {
  type        = "zip"
  source_file = "${path.module}/lambda/reaper/index.py"
  output_path = "${path.module}/.build/reaper.zip"
}

# ─── IAM ─────────────────────────────────────────────────────────

resource "aws_iam_role" "reaper_lambda" {
  name = "${local.name_prefix}-reaper-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "reaper_dynamodb" {
  name = "${local.name_prefix}-reaper-dynamodb"
  role = aws_iam_role.reaper_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
        ]
        Resource = [
          aws_dynamodb_table.task_queue.arn,
          "${aws_dynamodb_table.task_queue.arn}/index/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = [aws_cloudwatch_event_bus.factory.arn]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "reaper_logs" {
  role       = aws_iam_role.reaper_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ─── Lambda Function ────────────────────────────────────────────

resource "aws_lambda_function" "reaper" {
  function_name    = "${local.name_prefix}-reaper"
  role             = aws_iam_role.reaper_lambda.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 90
  memory_size      = 256
  filename         = data.archive_file.reaper.output_path
  source_code_hash = data.archive_file.reaper.output_base64sha256

  environment {
    variables = {
      TASK_QUEUE_TABLE   = aws_dynamodb_table.task_queue.name
      EVENT_BUS_NAME     = aws_cloudwatch_event_bus.factory.name
      ENVIRONMENT        = var.environment
      REAPER_MAX_RETRIES = "3"
    }
  }

  tags = { Component = "reaper", ADR = "022" }
}

# ─── CloudWatch Events Rule (5-minute schedule) ────────────────

resource "aws_cloudwatch_event_rule" "reaper_schedule" {
  name                = "${local.name_prefix}-reaper-schedule"
  description         = "Trigger reaper Lambda every 5 minutes to heal stuck tasks"
  schedule_expression = "rate(5 minutes)"
  state               = var.reaper_enabled ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "reaper_target" {
  rule      = aws_cloudwatch_event_rule.reaper_schedule.name
  target_id = "reaper-lambda"
  arn       = aws_lambda_function.reaper.arn
}

resource "aws_lambda_permission" "reaper_cloudwatch" {
  statement_id  = "AllowCloudWatchInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reaper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reaper_schedule.arn
}

# ─── Outputs ────────────────────────────────────────────────────

output "reaper_lambda_arn" {
  description = "ARN of the reaper Lambda function"
  value       = aws_lambda_function.reaper.arn
}
