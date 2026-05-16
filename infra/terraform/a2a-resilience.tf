# ─────────────────────────────────────────────────────────────────────────────
# A2A Resilience & Observability Infrastructure
#
# Extends the A2A ECS deployment with:
#   - SQS Dead Letter Queue for failed workflow isolation
#   - SQS retry queue with redrive policy
#   - CloudWatch alarm on DLQ message count (operational alerting)
#   - IAM permissions for SQS (appended to existing ecs_task role)
#
# IMPORTANT: Uses EXISTING resources only:
#   - aws_iam_role.ecs_task (from main.tf)
#   - aws_dynamodb_table.a2a_workflow_state (from a2a-ecs.tf)
#   - local.name_prefix
#
# X-Ray permissions already exist in main.tf (aws_iam_role_policy.ecs_task_xray).
# ADOT sidecar already included in a2a-ecs.tf task definitions.
#
# Ref: ADR-034 (A2A Protocol), ADR-004 (Circuit Breaker)
# ─────────────────────────────────────────────────────────────────────────────

# ─── SQS Dead Letter Queue ───────────────────────────────────────────────────

resource "aws_sqs_queue" "a2a_dlq" {
  name                       = "${local.name_prefix}-a2a-workflow-dlq"
  message_retention_seconds  = 1209600  # 14 days
  visibility_timeout_seconds = 300
  receive_wait_time_seconds  = 20  # Long polling

  sqs_managed_sse_enabled = true

  tags = {
    Component = "a2a-protocol"
    Purpose   = "dead-letter-queue"
  }
}

# ─── SQS Retry Queue (redrive to DLQ after 3 receives) ──────────────────────

resource "aws_sqs_queue" "a2a_retry_queue" {
  name                       = "${local.name_prefix}-a2a-workflow-retry"
  message_retention_seconds  = 86400  # 1 day
  visibility_timeout_seconds = 600    # 10 min (matches agent timeout)
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.a2a_dlq.arn
    maxReceiveCount     = 3
  })

  sqs_managed_sse_enabled = true

  tags = {
    Component = "a2a-protocol"
    Purpose   = "retry-queue"
  }
}

# ─── CloudWatch Alarm: DLQ Messages (Operational Alert) ──────────────────────

resource "aws_cloudwatch_metric_alarm" "a2a_dlq_messages" {
  alarm_name          = "${local.name_prefix}-a2a-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300  # 5 minutes
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "A2A workflow sent to DLQ after exhausting retries — requires investigation"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.a2a_dlq.name
  }

  tags = {
    Component = "a2a-protocol"
  }
}

# ─── IAM: SQS Permissions (appended to existing task role) ───────────────────

resource "aws_iam_role_policy" "ecs_task_a2a_sqs" {
  name = "${local.name_prefix}-a2a-sqs-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = [
          aws_sqs_queue.a2a_dlq.arn,
          aws_sqs_queue.a2a_retry_queue.arn
        ]
      }
    ]
  })
}

# ─── Outputs ─────────────────────────────────────────────────────────────────

output "a2a_dlq_url" {
  description = "SQS DLQ URL for failed A2A workflows"
  value       = aws_sqs_queue.a2a_dlq.url
}

output "a2a_dlq_arn" {
  description = "SQS DLQ ARN"
  value       = aws_sqs_queue.a2a_dlq.arn
}

output "a2a_retry_queue_url" {
  description = "SQS retry queue URL"
  value       = aws_sqs_queue.a2a_retry_queue.url
}
