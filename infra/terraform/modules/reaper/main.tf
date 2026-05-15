# ═══════════════════════════════════════════════════════════════════
# Scheduled Reaper Lambda — Self-healing for stuck tasks
#
# Triggered every 5 minutes by CloudWatch Events. Runs independently
# of the orchestrator so stuck tasks are healed even when no new events arrive.
#
# Fixes: Pipeline loose end #1 — stuck tasks block concurrency slots indefinitely.
# Reference: ADR-034, WAF Reliability pillar (REL 11)
# ═══════════════════════════════════════════════════════════════════

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "task_queue_table_name" {
  description = "DynamoDB table name for the task queue"
  type        = string
  default     = "fde-dev-task-queue"
}

variable "task_queue_table_arn" {
  description = "DynamoDB table ARN for IAM permissions"
  type        = string
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 60
}

variable "schedule_expression" {
  description = "CloudWatch Events schedule expression"
  type        = string
  default     = "rate(5 minutes)"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

# ─── IAM Role ───────────────────────────────────────────────────

resource "aws_iam_role" "reaper_lambda" {
  name = "fde-${var.environment}-reaper-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "reaper_dynamodb" {
  name = "fde-${var.environment}-reaper-dynamodb"
  role = aws_iam_role.reaper_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:PutItem",
        ]
        Resource = [
          var.task_queue_table_arn,
          "${var.task_queue_table_arn}/index/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "reaper_logs" {
  role       = aws_iam_role.reaper_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ─── Lambda Function ────────────────────────────────────────────

resource "aws_lambda_function" "reaper" {
  function_name = "fde-${var.environment}-reaper"
  role          = aws_iam_role.reaper_lambda.arn
  handler       = "reaper_handler.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout
  memory_size   = 256

  # Package is built by CI/CD pipeline (Docker image or zip)
  filename         = "${path.module}/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/placeholder.zip")

  environment {
    variables = {
      TASK_QUEUE_TABLE = var.task_queue_table_name
      ENVIRONMENT      = var.environment
      AWS_REGION       = "us-east-1"
    }
  }

  tags = var.tags
}

# ─── CloudWatch Events Rule (5-minute schedule) ────────────────

resource "aws_cloudwatch_event_rule" "reaper_schedule" {
  name                = "fde-${var.environment}-reaper-schedule"
  description         = "Trigger reaper Lambda every 5 minutes to heal stuck tasks"
  schedule_expression = var.schedule_expression

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "reaper_target" {
  rule      = aws_cloudwatch_event_rule.reaper_schedule.name
  target_id = "reaper-lambda"
  arn       = aws_lambda_function.reaper.arn
}

resource "aws_lambda_permission" "allow_cloudwatch" {
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

output "reaper_lambda_name" {
  description = "Name of the reaper Lambda function"
  value       = aws_lambda_function.reaper.function_name
}
