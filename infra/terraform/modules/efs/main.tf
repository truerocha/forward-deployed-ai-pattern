# ═══════════════════════════════════════════════════════════════════
# EFS — Elastic File System for Agent Workspaces
# ═══════════════════════════════════════════════════════════════════
#
# Provides shared persistent storage for ECS agent tasks.
# Each task execution mounts /workspaces/{task_id}/{repo}/ via EFS.
# Used by: distributed_orchestrator, agent_runner, perturbation_engine,
#          behavioral_benchmark, call_graph_extractor.
#
# Performance: General Purpose (bursting) for dev, Provisioned for prod.
# Encryption: At-rest via AWS-managed KMS key.
# Lifecycle: Transition to IA after 30 days (cost optimization).
# ═══════════════════════════════════════════════════════════════════

variable "name_prefix" {
  description = "Resource naming prefix (e.g., fde-dev)"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where EFS mount targets will be created"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for EFS mount targets"
  type        = list(string)
}

variable "ecs_security_group_id" {
  description = "Security group ID of ECS tasks that will mount EFS"
  type        = string
}

variable "throughput_mode" {
  description = "EFS throughput mode: bursting or provisioned"
  type        = string
  default     = "bursting"
  validation {
    condition     = contains(["bursting", "provisioned", "elastic"], var.throughput_mode)
    error_message = "Throughput mode must be bursting, provisioned, or elastic."
  }
}

variable "provisioned_throughput_mibps" {
  description = "Provisioned throughput in MiB/s (only when throughput_mode = provisioned)"
  type        = number
  default     = 128
}

# ─── EFS File System ─────────────────────────────────────────────
resource "aws_efs_file_system" "workspaces" {
  creation_token = "${var.name_prefix}-agent-workspaces"
  encrypted      = true

  performance_mode = "generalPurpose"
  throughput_mode  = var.throughput_mode

  # Only set when provisioned mode is selected
  provisioned_throughput_in_mibps = var.throughput_mode == "provisioned" ? var.provisioned_throughput_mibps : null

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  lifecycle_policy {
    transition_to_primary_storage_class = "AFTER_1_ACCESS"
  }

  tags = {
    Name        = "${var.name_prefix}-agent-workspaces"
    Component   = "efs"
    Environment = var.environment
  }
}

# ─── EFS Mount Targets (one per private subnet) ─────────────────
resource "aws_efs_mount_target" "workspaces" {
  count = length(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.workspaces.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

# ─── EFS Access Point (scoped to /workspaces) ───────────────────
resource "aws_efs_access_point" "workspaces" {
  file_system_id = aws_efs_file_system.workspaces.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/workspaces"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name      = "${var.name_prefix}-workspaces-ap"
    Component = "efs"
  }
}

# ─── EFS Access Points: Domain Isolation (Fase 3) ───────────────
# Three isolated paths for Strands, A2A, and shared handoff channel.
# Each domain mounts only its own path + shared. Zero cross-contamination.
# Well-Architected: SEC 3 (Least privilege), REL 10 (Fault isolation)

resource "aws_efs_access_point" "strands" {
  file_system_id = aws_efs_file_system.workspaces.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/workspaces/strands"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name      = "${var.name_prefix}-strands-ap"
    Component = "efs"
    Domain    = "strands"
  }
}

resource "aws_efs_access_point" "a2a" {
  file_system_id = aws_efs_file_system.workspaces.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/workspaces/a2a"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name      = "${var.name_prefix}-a2a-ap"
    Component = "efs"
    Domain    = "a2a"
  }
}

resource "aws_efs_access_point" "shared" {
  file_system_id = aws_efs_file_system.workspaces.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/workspaces/shared"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name      = "${var.name_prefix}-shared-ap"
    Component = "efs"
    Domain    = "shared"
  }
}

# ─── EFS Backup Policy ──────────────────────────────────────────
resource "aws_efs_backup_policy" "workspaces" {
  file_system_id = aws_efs_file_system.workspaces.id

  backup_policy {
    status = var.environment == "prod" ? "ENABLED" : "DISABLED"
  }
}

# ─── Outputs ─────────────────────────────────────────────────────
output "file_system_id" {
  description = "EFS file system ID"
  value       = aws_efs_file_system.workspaces.id
}

output "file_system_arn" {
  description = "EFS file system ARN"
  value       = aws_efs_file_system.workspaces.arn
}

output "access_point_id" {
  description = "EFS access point ID for /workspaces (legacy — all domains)"
  value       = aws_efs_access_point.workspaces.id
}

output "access_point_arn" {
  description = "EFS access point ARN"
  value       = aws_efs_access_point.workspaces.arn
}

output "strands_access_point_id" {
  description = "EFS access point ID for /workspaces/strands (Fase 3)"
  value       = aws_efs_access_point.strands.id
}

output "a2a_access_point_id" {
  description = "EFS access point ID for /workspaces/a2a (Fase 3)"
  value       = aws_efs_access_point.a2a.id
}

output "shared_access_point_id" {
  description = "EFS access point ID for /workspaces/shared (Fase 3)"
  value       = aws_efs_access_point.shared.id
}

output "mount_target_ids" {
  description = "List of EFS mount target IDs"
  value       = aws_efs_mount_target.workspaces[*].id
}

output "security_group_id" {
  description = "EFS security group ID"
  value       = aws_security_group.efs.id
}
