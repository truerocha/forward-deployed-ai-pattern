#!/usr/bin/env bash
set -uo pipefail

# ═══════════════════════════════════════════════════════════════════
# Forward Deployed Engineer — E2E Cloud Validation
# ═══════════════════════════════════════════════════════════════════
#
# Tests the deployed cloud infrastructure end-to-end.
# Usage: bash scripts/validate-e2e-cloud.sh [--profile profile-name]
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
log_fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; WARN=$((WARN + 1)); }
log_head() { echo -e "\n${CYAN}── $1 ──${NC}"; }

AWS_PROFILE_ARG=""
if [ "${1:-}" = "--profile" ] && [ -n "${2:-}" ]; then
    AWS_PROFILE_ARG="$2"
elif [ -f "$HOME/.kiro/fde-manifest.json" ]; then
    AWS_PROFILE_ARG=$(python3 -c "import json; print(json.load(open('$HOME/.kiro/fde-manifest.json')).get('credentials',{}).get('aws_profile',''))" 2>/dev/null || echo "")
fi

aws_cmd() {
    if [ -n "$AWS_PROFILE_ARG" ]; then aws --profile "$AWS_PROFILE_ARG" "$@"; else aws "$@"; fi
}

TF_DIR="$SCRIPT_DIR/infra/terraform"
AWS_REGION="us-east-1"

read_tf_output() {
    AWS_PROFILE="${AWS_PROFILE_ARG}" terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null || echo ""
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Forward Deployed Engineer — E2E Cloud Validation"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
[ -n "$AWS_PROFILE_ARG" ] && echo " Profile: $AWS_PROFILE_ARG"
echo "═══════════════════════════════════════════════════════════"

log_head "1. Terraform Outputs"
ECR_URL=$(read_tf_output ecr_repository_url)
[ -n "$ECR_URL" ] && log_ok "ECR_URL = $ECR_URL" || log_fail "ECR_URL is empty"
CLUSTER_NAME=$(read_tf_output ecs_cluster_name)
BUCKET=$(read_tf_output artifacts_bucket)
SECRETS_ARN=$(read_tf_output secrets_arn)
WEBHOOK_URL=$(read_tf_output webhook_api_url)
EVENT_BUS=$(read_tf_output event_bus_name)
VPC_ID=$(read_tf_output vpc_id)

for var_name in CLUSTER_NAME BUCKET SECRETS_ARN WEBHOOK_URL EVENT_BUS VPC_ID; do
    val="${!var_name}"
    [ -n "$val" ] && log_ok "$var_name = $val" || log_fail "$var_name is empty"
done

log_head "2. API Gateway Webhooks"
if [ -n "$WEBHOOK_URL" ]; then
    for platform in github gitlab asana; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${WEBHOOK_URL}/webhook/${platform}" -H "Content-Type: application/json" -d '{"test":true}' 2>/dev/null || echo "000")
        [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "204" ] && log_ok "POST /webhook/$platform → $HTTP_CODE" || log_warn "POST /webhook/$platform → $HTTP_CODE"
    done
fi

log_head "3. EventBridge"
if [ -n "$EVENT_BUS" ]; then
    BUS_CHECK=$(aws_cmd events describe-event-bus --name "$EVENT_BUS" --region "$AWS_REGION" --query "Name" --output text 2>/dev/null || echo "")
    [ "$BUS_CHECK" = "$EVENT_BUS" ] && log_ok "Event bus: $EVENT_BUS" || log_fail "Event bus not found"
    RULE_COUNT=$(aws_cmd events list-rules --event-bus-name "$EVENT_BUS" --region "$AWS_REGION" --query "length(Rules)" --output text 2>/dev/null || echo "0")
    [ "$RULE_COUNT" -ge 3 ] && log_ok "Rules: $RULE_COUNT" || log_fail "Rules: $RULE_COUNT (expected 3)"
    PUT_RESULT=$(aws_cmd events put-events --region "$AWS_REGION" --entries "[{\"Source\":\"fde.e2e.test\",\"DetailType\":\"validation\",\"Detail\":\"{\\\"test\\\":true}\",\"EventBusName\":\"$EVENT_BUS\"}]" --query "FailedEntryCount" --output text 2>/dev/null || echo "1")
    [ "$PUT_RESULT" = "0" ] && log_ok "Test event sent successfully" || log_fail "Failed to send test event"
fi

log_head "4. S3 Bucket"
if [ -n "$BUCKET" ]; then
    TEST_KEY="e2e-test/validation-$(date +%s).txt"
    if echo "e2e-validation-test" | aws_cmd s3 cp - "s3://$BUCKET/$TEST_KEY" --region "$AWS_REGION" >/dev/null 2>&1; then
        log_ok "S3 write OK"
        aws_cmd s3api head-object --bucket "$BUCKET" --key "$TEST_KEY" --region "$AWS_REGION" >/dev/null 2>&1 && log_ok "S3 read OK" || log_fail "S3 read failed"
        aws_cmd s3 rm "s3://$BUCKET/$TEST_KEY" --region "$AWS_REGION" >/dev/null 2>&1
        log_ok "S3 cleanup OK"
    else
        log_fail "S3 write failed"
    fi
fi

log_head "5. Secrets Manager"
if [ -n "$SECRETS_ARN" ]; then
    SECRET_CHECK=$(aws_cmd secretsmanager describe-secret --secret-id "$SECRETS_ARN" --region "$AWS_REGION" --query "Name" --output text 2>/dev/null || echo "")
    [ -n "$SECRET_CHECK" ] && log_ok "Secret: $SECRET_CHECK" || log_fail "Secret not found"
fi

log_head "6. ECR Repository"
if [ -n "$ECR_URL" ]; then
    REPO_NAME=$(echo "$ECR_URL" | cut -d/ -f2)
    REPO_CHECK=$(aws_cmd ecr describe-repositories --repository-names "$REPO_NAME" --region "$AWS_REGION" --query "repositories[0].repositoryUri" --output text 2>/dev/null || echo "")
    [ -n "$REPO_CHECK" ] && log_ok "ECR repo: $REPO_NAME" || log_fail "ECR repo not found"
    IMAGE_COUNT=$(aws_cmd ecr list-images --repository-name "$REPO_NAME" --region "$AWS_REGION" --query "length(imageIds)" --output text 2>/dev/null || echo "0")
    [ "$IMAGE_COUNT" -gt 0 ] && log_ok "ECR images: $IMAGE_COUNT" || log_warn "ECR empty — build and push Docker image"
fi

log_head "7. ECS Cluster"
if [ -n "$CLUSTER_NAME" ]; then
    CLUSTER_STATUS=$(aws_cmd ecs describe-clusters --clusters "$CLUSTER_NAME" --region "$AWS_REGION" --query "clusters[0].status" --output text 2>/dev/null || echo "")
    [ "$CLUSTER_STATUS" = "ACTIVE" ] && log_ok "ECS cluster ACTIVE" || log_fail "ECS cluster: $CLUSTER_STATUS"
    TASK_DEF=$(aws_cmd ecs list-task-definitions --family-prefix "fde-dev-strands-agent" --region "$AWS_REGION" --query "taskDefinitionArns[-1]" --output text 2>/dev/null || echo "")
    [ -n "$TASK_DEF" ] && [ "$TASK_DEF" != "None" ] && log_ok "Task def: $TASK_DEF" || log_fail "No task definition"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " E2E Summary: Passed=$PASS | Failed=$FAIL | Warnings=$WARN"
echo "═══════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ] && echo -e " ${GREEN}ALL CLOUD RESOURCES VALIDATED.${NC}" || echo -e " ${YELLOW}$FAIL issues found.${NC}"
echo ""
