#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# validate-dispatch-permissions.sh — SEC 3: IAM Least Privilege Contract Test
#
# Validates that the EventBridge role has ecs:RunTask permission for
# the CURRENT task definition revision. Catches the drift that occurs
# when `terraform apply -target` updates the task def but not the IAM policy.
#
# Usage:
#   bash scripts/validate-dispatch-permissions.sh
#   bash scripts/validate-dispatch-permissions.sh --profile profile-rocand
#
# Exit codes:
#   0 — All permissions aligned
#   1 — Permission mismatch detected (deploy required)
#
# Well-Architected: SEC 3 — Manage permissions centrally
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

PROFILE_ARG=""
if [[ "${1:-}" == "--profile" && -n "${2:-}" ]]; then
    PROFILE_ARG="--profile $2"
fi

REGION="${AWS_REGION:-us-east-1}"
echo "═══════════════════════════════════════════════════════════════"
echo "  SEC 3: Dispatch Permission Validation"
echo "  Region: $REGION"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 1. Get current task definition ARN from EventBridge target
echo "① Checking EventBridge target task definition..."
TARGET_TASK_DEF=$(aws $PROFILE_ARG events list-targets-by-rule \
    --rule fde-dev-dispatch-distributed \
    --event-bus-name fde-dev-factory-bus \
    --region "$REGION" \
    --query 'Targets[0].EcsParameters.TaskDefinitionArn' \
    --output text 2>/dev/null)

if [[ -z "$TARGET_TASK_DEF" || "$TARGET_TASK_DEF" == "None" ]]; then
    echo "   ❌ FAIL: Cannot read EventBridge target task definition"
    exit 1
fi
echo "   Target: $TARGET_TASK_DEF"

# 2. Get IAM policy allowed resources
echo ""
echo "② Checking IAM role permissions..."
IAM_RESOURCES=$(aws $PROFILE_ARG iam get-role-policy \
    --role-name fde-dev-eventbridge-ecs \
    --policy-name fde-dev-eventbridge-run-task \
    --region "$REGION" \
    --query 'PolicyDocument.Statement[0].Resource' \
    --output text 2>/dev/null)

echo "   Allowed: $IAM_RESOURCES"

# 3. Validate alignment
echo ""
echo "③ Validating alignment..."
if echo "$IAM_RESOURCES" | grep -q "$TARGET_TASK_DEF"; then
    echo "   ✅ PASS: IAM allows RunTask for current target revision"
else
    echo "   ❌ FAIL: IAM does NOT allow RunTask for $TARGET_TASK_DEF"
    echo ""
    echo "   FIX: Run 'terraform apply' (without -target) to sync IAM with task def"
    echo "   ROOT CAUSE: terraform apply -target updates task def but not IAM policy"
    exit 1
fi

# 4. Validate EventBridge role has PassRole for task roles
echo ""
echo "④ Checking PassRole permissions..."
TASK_ROLE=$(aws $PROFILE_ARG ecs describe-task-definition \
    --task-definition "$TARGET_TASK_DEF" \
    --region "$REGION" \
    --query 'taskDefinition.taskRoleArn' \
    --output text 2>/dev/null)

EXEC_ROLE=$(aws $PROFILE_ARG ecs describe-task-definition \
    --task-definition "$TARGET_TASK_DEF" \
    --region "$REGION" \
    --query 'taskDefinition.executionRoleArn' \
    --output text 2>/dev/null)

PASS_ROLE_RESOURCES=$(aws $PROFILE_ARG iam get-role-policy \
    --role-name fde-dev-eventbridge-ecs \
    --policy-name fde-dev-eventbridge-run-task \
    --region "$REGION" \
    --query 'PolicyDocument.Statement[1].Resource' \
    --output text 2>/dev/null)

PASS_OK=true
if ! echo "$PASS_ROLE_RESOURCES" | grep -q "$TASK_ROLE"; then
    echo "   ❌ FAIL: Cannot PassRole to task role: $TASK_ROLE"
    PASS_OK=false
fi
if ! echo "$PASS_ROLE_RESOURCES" | grep -q "$EXEC_ROLE"; then
    echo "   ❌ FAIL: Cannot PassRole to execution role: $EXEC_ROLE"
    PASS_OK=false
fi

if [[ "$PASS_OK" == "true" ]]; then
    echo "   ✅ PASS: PassRole allowed for both task and execution roles"
fi

# 5. Check DLQ depth (operational health)
echo ""
echo "⑤ Checking DLQ depth..."
DLQ_DEPTH=$(aws $PROFILE_ARG sqs get-queue-attributes \
    --queue-url "https://sqs.$REGION.amazonaws.com/$(aws $PROFILE_ARG sts get-caller-identity --query Account --output text)/fde-dev-dispatch-dlq" \
    --attribute-names ApproximateNumberOfMessages \
    --region "$REGION" \
    --query 'Attributes.ApproximateNumberOfMessages' \
    --output text 2>/dev/null)

if [[ "$DLQ_DEPTH" -gt 0 ]]; then
    echo "   ⚠️  WARN: DLQ has $DLQ_DEPTH messages (failed dispatches)"
else
    echo "   ✅ PASS: DLQ empty"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Validation complete"
echo "═══════════════════════════════════════════════════════════════"
