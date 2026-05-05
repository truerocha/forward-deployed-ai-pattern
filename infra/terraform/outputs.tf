output "ecr_repository_url" {
  description = "ECR repository URL for Strands agent images"
  value       = aws_ecr_repository.strands_agent.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.factory.name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.factory.arn
}

output "artifacts_bucket" {
  description = "S3 bucket for factory artifacts"
  value       = aws_s3_bucket.factory_artifacts.id
}

output "secrets_arn" {
  description = "Secrets Manager ARN for ALM tokens"
  value       = aws_secretsmanager_secret.alm_tokens.arn
}

output "task_definition_arn" {
  description = "ECS task definition ARN for Strands agent"
  value       = aws_ecs_task_definition.strands_agent.arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks"
  value       = module.vpc.private_subnet_ids
}


output "webhook_api_url" {
  description = "API Gateway URL for ALM webhooks"
  value       = aws_apigatewayv2_api.webhook.api_endpoint
}

output "webhook_github_url" {
  description = "GitHub webhook URL — configure in repo Settings → Webhooks"
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook/github"
}

output "webhook_gitlab_url" {
  description = "GitLab webhook URL — configure in project Settings → Webhooks"
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook/gitlab"
}

output "webhook_asana_url" {
  description = "Asana webhook URL — configure via Asana API"
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook/asana"
}

output "event_bus_name" {
  description = "EventBridge custom event bus name"
  value       = aws_cloudwatch_event_bus.factory.name
}


output "prompt_registry_table" {
  description = "DynamoDB table for Prompt Registry"
  value       = aws_dynamodb_table.prompt_registry.name
}

output "task_queue_table" {
  description = "DynamoDB table for Task Queue"
  value       = aws_dynamodb_table.task_queue.name
}

output "agent_lifecycle_table" {
  description = "DynamoDB table for Agent Lifecycle"
  value       = aws_dynamodb_table.agent_lifecycle.name
}
