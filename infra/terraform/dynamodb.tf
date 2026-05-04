# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Prompt Registry + Task Queue + Agent Lifecycle
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "prompt_registry" {
  name         = "${local.name_prefix}-prompt-registry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "prompt_name"
  range_key    = "version"

  attribute {
    name = "prompt_name"
    type = "S"
  }

  attribute {
    name = "version"
    type = "N"
  }

  tags = { Component = "prompt-registry" }
}

resource "aws_dynamodb_table" "task_queue" {
  name         = "${local.name_prefix}-task-queue"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "task_id"

  attribute {
    name = "task_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  tags = { Component = "task-queue" }
}

resource "aws_dynamodb_table" "agent_lifecycle" {
  name         = "${local.name_prefix}-agent-lifecycle"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "agent_instance_id"

  attribute {
    name = "agent_instance_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  tags = { Component = "agent-lifecycle" }
}
