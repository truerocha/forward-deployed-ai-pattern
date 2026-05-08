# ═══════════════════════════════════════════════════════════════════
# API Gateway WebSocket Module — Real-time Bidirectional Communication
# ═══════════════════════════════════════════════════════════════════
#
# Provides a WebSocket API for portal ↔ agent real-time messaging.
# Routes: $connect, $disconnect, $default, sendmessage
# Connections tracked in DynamoDB (PK: connectionId).
#
# Activity 4.01 — HITL WebSocket Infrastructure
# ═══════════════════════════════════════════════════════════════════

variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Invoke ARN of the Lambda function handling WebSocket messages"
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the Lambda function (for permission grants)"
  type        = string
}

# ─── DynamoDB: Active Connections Table ─────────────────────────

resource "aws_dynamodb_table" "connections" {
  name         = "${var.name_prefix}-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  attribute {
    name = "project_id"
    type = "S"
  }

  global_secondary_index {
    name            = "project-index"
    hash_key        = "project_id"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.name_prefix}-ws-connections"
    Environment = var.environment
    Module      = "apigw_ws"
  }
}

# ─── API Gateway WebSocket API ──────────────────────────────────

resource "aws_apigatewayv2_api" "websocket" {
  name                       = "${var.name_prefix}-ws-api"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"

  tags = {
    Name        = "${var.name_prefix}-ws-api"
    Environment = var.environment
  }
}

# ─── Lambda Integration ─────────────────────────────────────────

resource "aws_apigatewayv2_integration" "lambda" {
  api_id             = aws_apigatewayv2_api.websocket.id
  integration_type   = "AWS_PROXY"
  integration_uri    = var.lambda_invoke_arn
  integration_method = "POST"
}

# ─── Routes ─────────────────────────────────────────────────────

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "sendmessage" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "sendmessage"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# ─── Stage: $default with auto-deploy ───────────────────────────

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.websocket.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 500
    throttling_rate_limit  = 1000
  }

  tags = {
    Name        = "${var.name_prefix}-ws-stage"
    Environment = var.environment
  }
}

# ─── IAM: Allow API Gateway to invoke Lambda ────────────────────

resource "aws_lambda_permission" "apigw_connect" {
  statement_id  = "AllowAPIGatewayWSConnect"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*/$connect"
}

resource "aws_lambda_permission" "apigw_disconnect" {
  statement_id  = "AllowAPIGatewayWSDisconnect"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*/$disconnect"
}

resource "aws_lambda_permission" "apigw_default" {
  statement_id  = "AllowAPIGatewayWSDefault"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*/$default"
}

resource "aws_lambda_permission" "apigw_sendmessage" {
  statement_id  = "AllowAPIGatewayWSSendMessage"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*/sendmessage"
}

# ─── Outputs ────────────────────────────────────────────────────

output "websocket_api_id" {
  description = "ID of the WebSocket API"
  value       = aws_apigatewayv2_api.websocket.id
}

output "websocket_api_endpoint" {
  description = "WebSocket API endpoint URL"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "connection_table_name" {
  description = "DynamoDB table name for active WebSocket connections"
  value       = aws_dynamodb_table.connections.name
}

output "connection_table_arn" {
  description = "DynamoDB table ARN for IAM policies"
  value       = aws_dynamodb_table.connections.arn
}
