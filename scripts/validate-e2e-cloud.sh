#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Code Factory — End-to-End Cloud Health Check
# ═══════════════════════════════════════════════════════════════════
#
# Validates all subsystems required for the Code Factory to operate.
# Run after deployment or before onboarding a new project.
#
# Usage:
#   bash scripts/validate-e2e-cloud.sh --profile $AWS_PROFILE
#   bash scripts/validate-e2e-cloud.sh  # uses AWS_PROFILE env var
#
# Exit codes:
#   0 — All checks passed
#   1 — One or more checks failed
# ═══════════════════════════════════════════════════════════════════

set -uo pipefail

# ─── Configuration ───────────────────────────────────────────────
REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
CLUSTER_NAME="fde-${ENVIRONMENT}-cluster"
ECR_REPO_STRANDS="fde-${ENVIRONMENT}-strands-agent"
ECR_REPO_ONBOARDING="fde-${ENVIRONMENT}-onboarding-agent"
EVENT_BUS="fde-${ENVIRONMENT}-factory-bus"
SECRETS_ID="fde-${ENVIRONMENT}/alm-tokens"
BEDROCK_MODEL="us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --profile)
      export AWS_PROFILE="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --environment)
      ENVIRONMENT="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: bash scripts/validate-e2e-cloud.sh [--profile PROFILE] [--region REGION] [--environment ENV]"
      exit 1
      ;;
  esac
done

# ─── Helpers ─────────────────────────────────────────────────────
PASS=0
FAIL=0
WARNINGS=0

check_pass() {
  echo "  ✅ $1"
  PASS=$((PASS + 1))
}

check_fail() {
  echo "  ❌ $1"
  echo "     → Fix: $2"
  FAIL=$((FAIL + 1))
}

check_warn() {
  echo "  ⚠️  $1"
  WARNINGS=$((WARNINGS + 1))
}

section() {
  echo ""
  echo "━━━ $1 ━━━"
}

# ─── Pre-flight: Verify AWS credentials ─────────────────────────
section "AWS Credentials"

IDENTITY=$(aws sts get-caller-identity --region "$REGION" --output json 2>&1) || {
  echo "  ❌ AWS credentials not valid"
  echo "     → Fix: aws sso login --profile ${AWS_PROFILE:-your-profile}"
  exit 1
}

ACCOUNT=$(echo "$IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
ARN=$(echo "$IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")
check_pass "Authenticated as: $ARN (account: $ACCOUNT)"

# ─── Check 1: ECS Cluster ───────────────────────────────────────
section "ECS Cluster"

CLUSTER_STATUS=$(aws ecs describe-clusters \
  --clusters "$CLUSTER_NAME" \
  --region "$REGION" \
  --query 'clusters[0].status' \
  --output text 2>/dev/null) || CLUSTER_STATUS="NOT_FOUND"

if [[ "$CLUSTER_STATUS" == "ACTIVE" ]]; then
  check_pass "Cluster '$CLUSTER_NAME' is ACTIVE"
else
  check_fail "Cluster '$CLUSTER_NAME' status: $CLUSTER_STATUS" \
    "terraform apply -var-file=factory.tfvars"
fi

# ─── Check 2: ECR Images ────────────────────────────────────────
section "ECR Images"

for REPO in "$ECR_REPO_STRANDS" "$ECR_REPO_ONBOARDING"; do
  IMAGE_PUSHED=$(aws ecr describe-images \
    --repository-name "$REPO" \
    --region "$REGION" \
    --query 'imageDetails | sort_by(@, &imagePushedAt) | [-1].imagePushedAt' \
    --output text 2>/dev/null) || IMAGE_PUSHED="NOT_FOUND"

  if [[ "$IMAGE_PUSHED" == "NOT_FOUND" || "$IMAGE_PUSHED" == "None" ]]; then
    check_fail "ECR repo '$REPO' has no images" \
      "docker build + docker push to $REPO"
  else
    check_pass "ECR '$REPO' has image (pushed: $IMAGE_PUSHED)"
  fi
done

# Check ADOT sidecar image (required by task definition, COE: 5-Whys image dependency gap)
ADOT_TAG="adot-v0.40.0"
ADOT_CHECK=$(aws ecr describe-images \
  --repository-name "$ECR_REPO_STRANDS" \
  --image-ids imageTag="$ADOT_TAG" \
  --region "$REGION" \
  --query 'imageDetails[0].imagePushedAt' \
  --output text 2>/dev/null) || ADOT_CHECK="NOT_FOUND"

if [[ "$ADOT_CHECK" == "NOT_FOUND" || "$ADOT_CHECK" == "None" ]]; then
  check_fail "ADOT sidecar image '$ECR_REPO_STRANDS:$ADOT_TAG' missing" \
    "make docker-build-adot (task definition requires this image)"
else
  check_pass "ADOT sidecar '$ADOT_TAG' exists (pushed: $ADOT_CHECK)"
fi

# ─── Check 3: EventBridge Rules ─────────────────────────────────
section "EventBridge Rules"

RULES=$(aws events list-rules \
  --event-bus-name "$EVENT_BUS" \
  --region "$REGION" \
  --query 'Rules[].{Name:Name,State:State}' \
  --output json 2>/dev/null) || RULES="[]"

RULE_COUNT=$(echo "$RULES" | python3 -c "import sys,json; rules=json.load(sys.stdin); print(len(rules))")
ENABLED_COUNT=$(echo "$RULES" | python3 -c "import sys,json; rules=json.load(sys.stdin); print(sum(1 for r in rules if r['State']=='ENABLED'))")

if [[ "$RULE_COUNT" -ge 4 ]]; then
  check_pass "EventBridge bus '$EVENT_BUS' has $RULE_COUNT rules ($ENABLED_COUNT enabled)"
else
  check_fail "EventBridge bus '$EVENT_BUS' has only $RULE_COUNT rules (expected ≥4)" \
    "terraform apply — missing onboarding or ALM rules"
fi

# Check specifically for onboarding rule
ONBOARDING_RULE=$(echo "$RULES" | python3 -c "
import sys,json
rules=json.load(sys.stdin)
onboard = [r for r in rules if 'onboarding' in r['Name']]
print('ENABLED' if onboard and onboard[0]['State']=='ENABLED' else 'MISSING')
")

if [[ "$ONBOARDING_RULE" == "ENABLED" ]]; then
  check_pass "Onboarding trigger rule is ENABLED"
else
  check_fail "Onboarding trigger rule not found or disabled" \
    "terraform apply — onboarding.tf may not have been applied"
fi

# ─── Check 4: Bedrock Model Access ──────────────────────────────
section "Bedrock Model Access"

echo '{"anthropic_version":"bedrock-2023-05-31","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}' > /tmp/bedrock-health-body.json
BEDROCK_RESULT=$(aws bedrock-runtime invoke-model \
  --model-id "$BEDROCK_MODEL" \
  --region "$REGION" \
  --body fileb:///tmp/bedrock-health-body.json \
  --content-type "application/json" \
  /tmp/bedrock-health-check.json 2>&1) && BEDROCK_OK=true || BEDROCK_OK=false

if $BEDROCK_OK; then
  check_pass "Bedrock model '$BEDROCK_MODEL' responds (Haiku accessible)"
  rm -f /tmp/bedrock-health-check.json
else
  if echo "$BEDROCK_RESULT" | grep -q "AccessDeniedException"; then
    check_fail "Bedrock model access denied" \
      "AWS Console → Bedrock → Model access → Enable Claude 3 Haiku"
  else
    check_fail "Bedrock model invocation failed" \
      "Check IAM permissions and model availability in $REGION"
  fi
fi

# ─── Check 5: Secrets Manager ───────────────────────────────────
section "Secrets Manager"

SECRET_VALUE=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRETS_ID" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>/dev/null) || SECRET_VALUE="NOT_FOUND"

if [[ "$SECRET_VALUE" == "NOT_FOUND" ]]; then
  check_fail "Secret '$SECRETS_ID' not found" \
    "aws secretsmanager create-secret --name $SECRETS_ID --secret-string '{\"github_pat\":\"...\"}'"
else
  # Verify it has the expected keys (without printing values)
  HAS_GITHUB=$(echo "$SECRET_VALUE" | python3 -c "
import sys,json
try:
  s=json.load(sys.stdin)
  print('YES' if s.get('github_pat') else 'EMPTY')
except: print('INVALID')
")
  if [[ "$HAS_GITHUB" == "YES" ]]; then
    check_pass "Secret '$SECRETS_ID' exists with github_pat configured"
  elif [[ "$HAS_GITHUB" == "EMPTY" ]]; then
    check_warn "Secret '$SECRETS_ID' exists but github_pat is empty"
  else
    check_fail "Secret '$SECRETS_ID' has invalid JSON format" \
      "Update secret with valid JSON: {\"github_pat\":\"ghp_...\",\"gitlab_pat\":\"\",\"bitbucket_pat\":\"\"}"
  fi
fi

# ─── Check 6: S3 Artifacts Bucket ───────────────────────────────
section "S3 Artifacts Bucket"

BUCKET_NAME="fde-${ENVIRONMENT}-artifacts-${ACCOUNT}"
aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" 2>/dev/null && BUCKET_OK=true || BUCKET_OK=false

if $BUCKET_OK; then
  check_pass "S3 bucket '$BUCKET_NAME' is accessible"
else
  check_fail "S3 bucket '$BUCKET_NAME' not accessible" \
    "terraform apply — bucket may not exist or IAM lacks access"
fi

# ─── Check 7: API Gateway Webhook ───────────────────────────────
section "API Gateway Webhook"

API_URL=$(aws apigatewayv2 get-apis \
  --region "$REGION" \
  --query "Items[?contains(Name,'webhook')].ApiEndpoint | [0]" \
  --output text 2>/dev/null) || API_URL=""

if [[ -n "$API_URL" && "$API_URL" != "None" ]]; then
  check_pass "API Gateway webhook endpoint: $API_URL"

  # Test connectivity
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_URL/webhook/github" \
    -H "Content-Type: application/json" \
    -d '{"test":"health-check"}' 2>/dev/null) || HTTP_CODE="000"

  if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "400" ]]; then
    check_pass "Webhook endpoint responds (HTTP $HTTP_CODE)"
  elif [[ "$HTTP_CODE" == "403" ]]; then
    check_fail "Webhook returns 403 Forbidden" \
      "Check API Gateway authorization settings"
  else
    check_warn "Webhook returned HTTP $HTTP_CODE (expected 200 or 400)"
  fi
else
  check_fail "API Gateway webhook not found" \
    "terraform apply — apigateway.tf may not have been applied"
fi

# ─── Summary ─────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULTS: $PASS passed, $FAIL failed, $WARNINGS warnings"
echo "═══════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "  ⛔ Factory is NOT ready for operation. Fix the failures above."
  exit 1
else
  echo ""
  echo "  🟢 Factory is operational. Ready to onboard projects."
  exit 0
fi
