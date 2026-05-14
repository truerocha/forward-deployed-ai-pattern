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
  description = "Amazon Bedrock foundation model ID (use us. prefix for inference profiles)"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "bedrock_model_reasoning" {
  description = "Bedrock model for reasoning-tier agents (architect, adversarial, security review)"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "bedrock_model_standard" {
  description = "Bedrock model for standard-tier agents (developer, code analysis, intake)"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "bedrock_model_fast" {
  description = "Bedrock model for fast-tier agents (reporting, committer, cost analysis)"
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
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

variable "max_concurrent_tasks" {
  description = "Maximum concurrent tasks per repo (infrastructure-driven concurrency limit). Injected as env var into agent containers."
  type        = number
  default     = 3
  validation {
    condition     = var.max_concurrent_tasks >= 1 && var.max_concurrent_tasks <= 10
    error_message = "max_concurrent_tasks must be between 1 and 10 (safety cap)."
  }
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

# ─── Execution Mode: Two-Way Door (ADR-020) ─────────────────────
# ADR-030: This variable is now a LEGACY KILL SWITCH only.
# The cognitive router Lambda decides routing per-task based on depth.
# This variable no longer controls EventBridge targets (always monolith).
# It will be removed after 7 days of stable cognitive routing.
# See: cognitive_router_sunset.tf for automated reminder.
variable "execution_mode" {
  description = "LEGACY: Pipeline execution mode. Retained as emergency kill switch during cognitive router validation. Will be removed after monitoring confirms stability."
  type        = string
  default     = "monolith"
  validation {
    condition     = contains(["monolith", "distributed"], var.execution_mode)
    error_message = "execution_mode must be 'monolith' or 'distributed'."
  }
}
