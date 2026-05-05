# ═══════════════════════════════════════════════════════════════════
# API Gateway — Webhook Receiver for ALM Platforms
# ═══════════════════════════════════════════════════════════════════
#
# Receives webhooks from GitHub, GitLab, and Asana.
# Forwards events to EventBridge custom bus with platform-specific source.
# Routes: POST /webhook/github, POST /webhook/gitlab, POST /webhook/asana
# ═══════════════════════════════════════════════════════════════════

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name_prefix}-webhook-api"
  protocol_type = "HTTP"
  description   = "Receives ALM webhooks and forwards to EventBridge for agent orchestration"
  tags          = { Component = "apigateway" }
}

resource "aws_apigatewayv2_stage" "webhook" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.apigateway.arn
    format = jsonencode({
      requestId    = "$context.requestId"
      ip           = "$context.identity.sourceIp"
      requestTime  = "$context.requestTime"
      httpMethod   = "$context.httpMethod"
      routeKey     = "$context.routeKey"
      status       = "$context.status"
    })
  }

  tags = { Component = "apigateway" }
}

resource "aws_cloudwatch_log_group" "apigateway" {
  name              = "/apigateway/${local.name_prefix}-webhook"
  retention_in_days = 14
  tags              = { Component = "logging" }
}

# ─── IAM: API Gateway → EventBridge PutEvents ───────────────────

resource "aws_iam_role" "apigateway_eventbridge" {
  name = "${local.name_prefix}-apigw-eventbridge"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
    }]
  })
  tags = { Component = "iam" }
}

resource "aws_iam_role_policy" "apigateway_eventbridge" {
  name = "${local.name_prefix}-apigw-put-events"
  role = aws_iam_role.apigateway_eventbridge.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["events:PutEvents"]
      Resource = [aws_cloudwatch_event_bus.factory.arn]
    }]
  })
}

# ─── Integrations: API Gateway → EventBridge ────────────────────

resource "aws_apigatewayv2_integration" "github_webhook" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_subtype    = "EventBridge-PutEvents"
  credentials_arn        = aws_iam_role.apigateway_eventbridge.arn
  payload_format_version = "1.0"
  request_parameters = {
    "EventBusName" = aws_cloudwatch_event_bus.factory.arn
    "Source"       = "fde.github.webhook"
    "DetailType"   = "issue.labeled"
    "Detail"       = "$request.body"
  }
}

resource "aws_apigatewayv2_integration" "gitlab_webhook" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_subtype    = "EventBridge-PutEvents"
  credentials_arn        = aws_iam_role.apigateway_eventbridge.arn
  payload_format_version = "1.0"
  request_parameters = {
    "EventBusName" = aws_cloudwatch_event_bus.factory.arn
    "Source"       = "fde.gitlab.webhook"
    "DetailType"   = "issue.updated"
    "Detail"       = "$request.body"
  }
}

resource "aws_apigatewayv2_integration" "asana_webhook" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_subtype    = "EventBridge-PutEvents"
  credentials_arn        = aws_iam_role.apigateway_eventbridge.arn
  payload_format_version = "1.0"
  request_parameters = {
    "EventBusName" = aws_cloudwatch_event_bus.factory.arn
    "Source"       = "fde.asana.webhook"
    "DetailType"   = "task.moved"
    "Detail"       = "$request.body"
  }
}

# ─── Routes ──────────────────────────────────────────────────────

resource "aws_apigatewayv2_route" "github_webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/github"
  target    = "integrations/${aws_apigatewayv2_integration.github_webhook.id}"
}

resource "aws_apigatewayv2_route" "gitlab_webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/gitlab"
  target    = "integrations/${aws_apigatewayv2_integration.gitlab_webhook.id}"
}

resource "aws_apigatewayv2_route" "asana_webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/asana"
  target    = "integrations/${aws_apigatewayv2_integration.asana_webhook.id}"
}
