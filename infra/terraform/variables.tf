variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "bedrock_model_id" {
  description = "Amazon Bedrock foundation model ID"
  type        = string
  default     = "anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "enable_agentcore" {
  description = "Enable Amazon Bedrock AgentCore Runtime integration"
  type        = bool
  default     = false
}

variable "enable_ecs_service" {
  description = "Deploy ECS service (set false for task-only mode)"
  type        = bool
  default     = false
}

variable "agent_cpu" {
  description = "CPU units for Strands agent task (1024 = 1 vCPU)"
  type        = string
  default     = "1024"
}

variable "agent_memory" {
  description = "Memory (MiB) for Strands agent task"
  type        = string
  default     = "2048"
}

variable "agent_desired_count" {
  description = "Number of agent instances (when ECS service is enabled)"
  type        = number
  default     = 1
}

variable "vpc_cidr" {
  description = "CIDR block for the factory VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "tf_state_bucket" {
  description = "S3 bucket for Terraform state (configure via backend-config)"
  type        = string
  default     = ""
}
