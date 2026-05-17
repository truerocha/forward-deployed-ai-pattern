# ═══════════════════════════════════════════════════════════════════
# Fase 2: A2A Cluster Separation + Service Connect
# ═══════════════════════════════════════════════════════════════════
#
# ACTIVATION: Apply this file when the Fase 2 decision gate alarm fires:
#   fde-dev-a2a-latency-fase2-gate (CPU > 85% sustained 15min)
#
# What this does:
#   1. Creates a dedicated ECS cluster for A2A services
#   2. Enables Service Connect (replaces Cloud Map DNS with native LB)
#   3. Creates isolated EFS access points per domain
#   4. Migrates A2A services to the new cluster
#
# Rollback: Set `var.enable_a2a_cluster_separation = false` → services
#           stay on the shared cluster (a2a-ecs.tf handles them).
#
# Well-Architected alignment:
#   PERF 1: Right-size resources per workload characteristics
#   REL 10: Use fault isolation to protect workload
#   OPS 8: Anticipate failure (alarm-gated activation)
#   COST 7: Right-size (A2A = 256-512 CPU, Strands = 1024-4096 CPU)
# ═══════════════════════════════════════════════════════════════════

variable "enable_a2a_cluster_separation" {
  description = "Enable Fase 2: dedicated A2A cluster with Service Connect. Activate when fde-dev-a2a-latency-fase2-gate alarm fires."
  type        = bool
  default     = false
}

# ─── Dedicated A2A Cluster ───────────────────────────────────────────────────

resource "aws_ecs_cluster" "a2a" {
  count = var.enable_a2a_cluster_separation ? 1 : 0

  name = "${local.name_prefix}-a2a-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  # Service Connect namespace (replaces Cloud Map for intra-cluster discovery)
  service_connect_defaults {
    namespace = aws_service_discovery_http_namespace.a2a_connect[0].arn
  }

  tags = {
    Component = "a2a-protocol"
    Fase      = "2"
    Purpose   = "latency-isolation"
  }
}

resource "aws_ecs_cluster_capacity_providers" "a2a" {
  count        = var.enable_a2a_cluster_separation ? 1 : 0
  cluster_name = aws_ecs_cluster.a2a[0].name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 1
    capacity_provider = "FARGATE"
  }
}

# ─── Service Connect Namespace (HTTP-based, replaces DNS) ────────────────────

resource "aws_service_discovery_http_namespace" "a2a_connect" {
  count       = var.enable_a2a_cluster_separation ? 1 : 0
  name        = "${local.name_prefix}-a2a"
  description = "Service Connect namespace for A2A agents (Fase 2)"

  tags = {
    Component = "a2a-protocol"
    Fase      = "2"
  }
}

# ─── EFS Access Points (domain isolation) ────────────────────────────────────

resource "aws_efs_access_point" "a2a_workspaces" {
  count          = var.enable_a2a_cluster_separation ? 1 : 0
  file_system_id = module.efs.file_system_id

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
    Name      = "${local.name_prefix}-a2a-workspaces-ap"
    Component = "efs"
    Domain    = "a2a"
  }
}

resource "aws_efs_access_point" "strands_workspaces" {
  count          = var.enable_a2a_cluster_separation ? 1 : 0
  file_system_id = module.efs.file_system_id

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
    Name      = "${local.name_prefix}-strands-workspaces-ap"
    Component = "efs"
    Domain    = "strands"
  }
}

resource "aws_efs_access_point" "shared_workspaces" {
  count          = var.enable_a2a_cluster_separation ? 1 : 0
  file_system_id = module.efs.file_system_id

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
    Name      = "${local.name_prefix}-shared-workspaces-ap"
    Component = "efs"
    Domain    = "shared"
  }
}

# ─── A2A Services on Dedicated Cluster (with Service Connect) ────────────────

resource "aws_ecs_service" "a2a_isolated" {
  for_each = var.enable_a2a_cluster_separation ? {
    pesquisa = { port = 9001, desired_count = 1 }
    escrita  = { port = 9002, desired_count = 1 }
    revisao  = { port = 9003, desired_count = 1 }
  } : {}

  name            = "${local.name_prefix}-a2a-${each.key}"
  cluster         = aws_ecs_cluster.a2a[0].id
  task_definition = aws_ecs_task_definition.a2a_agent[each.key].arn
  desired_count   = each.value.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnet_ids
    security_groups  = [module.vpc.ecs_security_group_id]
    assign_public_ip = false
  }

  # Service Connect: native load balancing + circuit breaker + metrics
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.a2a_connect[0].arn

    service {
      port_name      = "${each.key}-port"
      discovery_name = each.key

      client_alias {
        port     = each.value.port
        dns_name = "${each.key}.fde.local"
      }
    }
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Component = "a2a-protocol"
    AgentType = each.key
    Fase      = "2"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ─── Auto Scaling for Isolated A2A Services ──────────────────────────────────

resource "aws_appautoscaling_target" "a2a_isolated" {
  for_each = var.enable_a2a_cluster_separation ? toset(["pesquisa", "escrita", "revisao"]) : toset([])

  max_capacity       = var.environment == "prod" ? 5 : 3
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.a2a[0].name}/${aws_ecs_service.a2a_isolated[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "a2a_isolated_cpu" {
  for_each = var.enable_a2a_cluster_separation ? toset(["pesquisa", "escrita", "revisao"]) : toset([])

  name               = "${local.name_prefix}-a2a-${each.key}-isolated-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.a2a_isolated[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.a2a_isolated[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.a2a_isolated[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# ─── Outputs (Fase 2) ───────────────────────────────────────────────────────

output "a2a_cluster_arn" {
  description = "Dedicated A2A cluster ARN (Fase 2)"
  value       = var.enable_a2a_cluster_separation ? aws_ecs_cluster.a2a[0].arn : ""
}

output "a2a_service_connect_namespace" {
  description = "Service Connect namespace ARN for A2A (Fase 2)"
  value       = var.enable_a2a_cluster_separation ? aws_service_discovery_http_namespace.a2a_connect[0].arn : ""
}

output "efs_access_points" {
  description = "EFS access points per domain (Fase 2)"
  value = var.enable_a2a_cluster_separation ? {
    a2a     = aws_efs_access_point.a2a_workspaces[0].id
    strands = aws_efs_access_point.strands_workspaces[0].id
    shared  = aws_efs_access_point.shared_workspaces[0].id
  } : {}
}
