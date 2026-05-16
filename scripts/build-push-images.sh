#!/usr/bin/env bash
# scripts/build-push-images.sh — Build and push all Docker images to ECR.
#
# Usage:
#   bash scripts/build-push-images.sh              # Build and push all images
#   bash scripts/build-push-images.sh --only a2a   # Build only A2A images
#   bash scripts/build-push-images.sh --only agent # Build only strands-agent
#   bash scripts/build-push-images.sh --dry-run    # Show what would be built
#
# Prerequisites:
#   - Docker running locally
#   - AWS credentials configured (uses AWS_PROFILE if set)
#   - ECR repository exists (created by Terraform)
#
# This script ensures the correct build order:
#   1. Authenticate to ECR
#   2. Build images from Dockerfiles
#   3. Push with correct tags
#   4. Force-deploy ECS services that reference updated images
#
# Ref: COE — Terraform creates infra but images are runtime artifacts.
#      This script bridges the gap between code changes and deployed containers.
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-785640717688}"
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/fde-${ENVIRONMENT}-strands-agent"
CLUSTER="fde-${ENVIRONMENT}-cluster"

# Parse arguments
DRY_RUN=false
ONLY=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --only) shift; ONLY="${2:-}" ;;
    a2a|agent|onboarding|orchestrator) ONLY="$arg" ;;
  esac
done

# ═══════════════════════════════════════════════════════════════
# IMAGE REGISTRY — All buildable images in the project
# Format: "name|dockerfile|tags|ecs_services_to_redeploy"
# ═══════════════════════════════════════════════════════════════
IMAGES=(
  "agent|Dockerfile.strands-agent|latest|"
  "a2a|Dockerfile.a2a-agent|a2a-pesquisa-latest,a2a-escrita-latest,a2a-revisao-latest|fde-${ENVIRONMENT}-a2a-pesquisa,fde-${ENVIRONMENT}-a2a-escrita,fde-${ENVIRONMENT}-a2a-revisao"
  "orchestrator|Dockerfile.orchestrator|orchestrator-latest|"
  "onboarding|Dockerfile.onboarding-agent|onboarding-latest|"
)

LOG_PREFIX="[build-push]"
FAILURES=0
BUILT=0

echo "$LOG_PREFIX $(date -u '+%Y-%m-%d %H:%M:%S UTC') — Image build/push starting"
echo "$LOG_PREFIX Region: $REGION | Account: $ACCOUNT_ID | Env: $ENVIRONMENT"
echo "$LOG_PREFIX ECR: $ECR_REPO"
echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 1: ECR Authentication
# ═══════════════════════════════════════════════════════════════
if [ "$DRY_RUN" = false ]; then
  echo "$LOG_PREFIX 🔐 Authenticating to ECR..."
  aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com" >/dev/null 2>&1
  echo "$LOG_PREFIX ✅ ECR authenticated"
  echo ""
fi

# ═══════════════════════════════════════════════════════════════
# STEP 2: Build and Push
# ═══════════════════════════════════════════════════════════════
for entry in "${IMAGES[@]}"; do
  IFS='|' read -r name dockerfile tags services <<< "$entry"

  # Filter if --only specified
  if [[ -n "$ONLY" && "$ONLY" != "$name" ]]; then
    continue
  fi

  DOCKERFILE_PATH="infra/docker/$dockerfile"

  # Verify Dockerfile exists
  if [[ ! -f "$REPO_ROOT/$DOCKERFILE_PATH" ]]; then
    echo "$LOG_PREFIX ⚠️  [$name] Dockerfile not found: $DOCKERFILE_PATH — skipping"
    continue
  fi

  echo "$LOG_PREFIX ── [$name] ──────────────────────────────────────"
  echo "$LOG_PREFIX   Dockerfile: $DOCKERFILE_PATH"
  echo "$LOG_PREFIX   Tags: $tags"

  if [ "$DRY_RUN" = true ]; then
    echo "$LOG_PREFIX   🏁 DRY RUN — would build and push"
    echo ""
    continue
  fi

  # Build with all tags
  TAG_ARGS=""
  IFS=',' read -ra TAG_ARRAY <<< "$tags"
  for tag in "${TAG_ARRAY[@]}"; do
    TAG_ARGS="$TAG_ARGS -t ${ECR_REPO}:${tag}"
  done

  echo -n "$LOG_PREFIX   Building... "
  if docker build -f "$REPO_ROOT/$DOCKERFILE_PATH" $TAG_ARGS "$REPO_ROOT" >/dev/null 2>&1; then
    echo "✅"
  else
    echo "❌"
    echo "$LOG_PREFIX   ⚠️  Build failed — check Dockerfile and dependencies"
    ((FAILURES++))
    continue
  fi

  # Push each tag
  for tag in "${TAG_ARRAY[@]}"; do
    echo -n "$LOG_PREFIX   Pushing :${tag}... "
    if docker push "${ECR_REPO}:${tag}" >/dev/null 2>&1; then
      echo "✅"
    else
      echo "❌"
      ((FAILURES++))
    fi
  done

  # Force-deploy ECS services if specified
  if [[ -n "$services" ]]; then
    IFS=',' read -ra SVC_ARRAY <<< "$services"
    for svc in "${SVC_ARRAY[@]}"; do
      echo -n "$LOG_PREFIX   Deploying $svc... "
      if aws ecs update-service --cluster "$CLUSTER" --service "$svc" \
           --force-new-deployment --output text --query 'service.serviceName' >/dev/null 2>&1; then
        echo "✅"
      else
        echo "⚠️  (service may not exist yet)"
      fi
    done
  fi

  ((BUILT++))
  echo ""
done

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════
echo "$LOG_PREFIX ═══════════════════════════════════════════════════"
if [ $FAILURES -gt 0 ]; then
  echo "$LOG_PREFIX ⚠️  $BUILT built, $FAILURES failed"
  exit 1
else
  echo "$LOG_PREFIX ✅ $BUILT image(s) built and pushed successfully"
fi
echo "$LOG_PREFIX ═══════════════════════════════════════════════════"
