# =============================================================================
# Dashboard Status API — Lambda + API Gateway route for /status/tasks
# Serves task pipeline status to the observability dashboard.
# =============================================================================

# --- Lambda: Dashboard Status ---

data "archive_file" "dashboard_status_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/dashboard_status/index.py"
  output_path = "${path.module}/.build/dashboard_status.zip"
}

resource "aws_lambda_function" "dashboard_status" {
  function_name    = "${local.name_prefix}-dashboard-status"
  role             = aws_iam_role.dashboard_status_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128
  filename         = data.archive_file.dashboard_status_zip.output_path
  source_code_hash = data.archive_file.dashboard_status_zip.output_base64sha256

  environment {
    variables = {
      TASK_QUEUE_TABLE      = aws_dynamodb_table.task_queue.name
      AGENT_LIFECYCLE_TABLE = aws_dynamodb_table.agent_lifecycle.name
      DORA_METRICS_TABLE    = aws_dynamodb_table.dora_metrics.name
      METRICS_TABLE         = module.dynamodb_distributed.metrics_table_name
      PROMPT_REGISTRY_TABLE = aws_dynamodb_table.prompt_registry.name
      TASK_DEF_FAMILY       = aws_ecs_task_definition.strands_agent.family
      EVENT_BUS_NAME        = aws_cloudwatch_event_bus.factory.name
      ENVIRONMENT           = var.environment
      AWS_REGION_NAME       = var.aws_region
    }
  }

  tags = { Component = "dashboard" }
}

# --- IAM Role for Dashboard Lambda ---

resource "aws_iam_role" "dashboard_status_role" {
  name = "${local.name_prefix}-dashboard-status-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = { Component = "dashboard" }
}

resource "aws_iam_role_policy" "dashboard_status_policy" {
  name = "dashboard-status-permissions"
  role = aws_iam_role.dashboard_status_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem", "dynamodb:DescribeTable"]
        Resource = [
          aws_dynamodb_table.task_queue.arn,
          "${aws_dynamodb_table.task_queue.arn}/index/*",
          aws_dynamodb_table.agent_lifecycle.arn,
          "${aws_dynamodb_table.agent_lifecycle.arn}/index/*",
          aws_dynamodb_table.dora_metrics.arn,
          "${aws_dynamodb_table.dora_metrics.arn}/index/*",
          aws_dynamodb_table.prompt_registry.arn,
          module.dynamodb_distributed.metrics_table_arn,
          "${module.dynamodb_distributed.metrics_table_arn}/index/*",
        ]
      },
      {
        # Agent lifecycle reconciliation: mark stale/completed agents
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.agent_lifecycle.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition"]
        Resource = ["*"]
      },
      {
        # SRE Readiness: ECS task listing, ECR image metadata, CloudWatch Logs
        Effect = "Allow"
        Action = [
          "ecs:ListTasks",
          "ecs:DescribeTasks",
          "ecr:DescribeImages",
          "logs:FilterLogEvents",
          "lambda:GetFunctionConfiguration"
        ]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["events:ListRules"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
      }
    ]
  })
}

# --- API Gateway Integration ---

resource "aws_apigatewayv2_integration" "dashboard_status" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.dashboard_status.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "dashboard_status" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/tasks"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_health" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/health"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_registries" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/registries"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_metrics" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/metrics"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_reasoning" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/tasks/{task_id}/reasoning"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_history" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/history"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_capacity" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/capacity"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_apigatewayv2_route" "dashboard_sre_readiness" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /status/sre-readiness"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_status.id}"
}

resource "aws_lambda_permission" "dashboard_status_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dashboard_status.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}
