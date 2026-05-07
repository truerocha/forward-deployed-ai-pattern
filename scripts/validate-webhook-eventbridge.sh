#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Webhook → EventBridge Integration Validator
# ═══════════════════════════════════════════════════════════════════
#
# Tests the full path: API Gateway → EventBridge → Rule Match → Target
# Uses three isolation strategies to pinpoint failures:
#
#   Test 1: Direct PutEvents (bypasses API Gateway)
#           → Confirms rule pattern matches the expected payload
#
#   Test 2: Webhook POST to API Gateway (full path)
#           → Confirms API Gateway forwards to EventBridge correctly
#
#   Test 3: Check CloudWatch Logs for catch-all rule
#           → Confirms events arrive on the bus
#
# Prerequisites:
#   - AWS credentials configured
#   - Terraform applied (eventbridge-observability.tf deployed)
#   - jq installed
#
# Usage:
#   bash scripts/validate-webhook-eventbridge.sh
#   bash scripts/validate-webhook-eventbridge.sh --profile my-profile
#   bash scripts/validate-webhook-eventbridge.sh --environment staging
#
# Exit codes:
#   0 — All tests passed
#   1 — One or more tests failed
# ═══════════════════════════════════════════════════════════════════

set -uo pipefail

# ─── Configuration ───────────────────────────────────────────────
REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
EVENT_BUS="fde-${ENVIRONMENT}-factory-bus"
LOG_GROUP="/aws/events/fde-${ENVIRONMENT}-factory-bus"
WAIT_SECONDS=10

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
      EVENT_BUS="fde-${ENVIRONMENT}-factory-bus"
      LOG_GROUP="/aws/events/fde-${ENVIRONMENT}-factory-bus"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# ─── Helpers ─────────────────────────────────────────────────────
PASS=0
FAIL=0
CORRELATION_ID="validate-$(date +%s)-$$"
CORRELATION_ID_2=""

check_pass() {
  echo "  ✅ $1"
  PASS=$((PASS + 1))
}

check_fail() {
  echo "  ❌ $1"
  echo "     → $2"
  FAIL=$((FAIL + 1))
}

section() {
  echo ""
  echo "━━━ $1 ━━━"
}

# ─── Pre-flight ──────────────────────────────────────────────────
section "Pre-flight Checks"

# Verify AWS credentials
aws sts get-caller-identity --region "$REGION" > /dev/null 2>&1 || {
  echo "  ❌ AWS credentials not valid. Run: aws sso login"
  exit 1
}
check_pass "AWS credentials valid"

# Verify jq is installed
command -v jq > /dev/null 2>&1 || {
  echo "  ❌ jq not installed. Run: brew install jq"
  exit 1
}
check_pass "jq available"

# Verify event bus exists
aws events describe-event-bus \
  --name "$EVENT_BUS" \
  --region "$REGION" > /dev/null 2>&1 || {
  check_fail "Event bus '$EVENT_BUS' not found" \
    "Run: terraform apply -var-file=factory.tfvars"
  exit 1
}
check_pass "Event bus '$EVENT_BUS' exists"

# ═══════════════════════════════════════════════════════════════════
# TEST 1: Direct PutEvents — Does the rule pattern match?
# ═══════════════════════════════════════════════════════════════════
section "Test 1: Direct PutEvents (rule pattern validation)"

# Simulate the exact GitHub issues.labeled payload structure
GITHUB_PAYLOAD=$(cat <<PAYLOAD
{
  "action": "labeled",
  "label": {
    "id": 99999,
    "url": "https://api.github.com/repos/test/test/labels/factory-ready",
    "name": "factory-ready",
    "color": "0e8a16",
    "default": false,
    "description": "Ready for autonomous code factory"
  },
  "issue": {
    "number": 42,
    "title": "Test issue for webhook validation",
    "body": "This is a validation test",
    "labels": [
      { "name": "factory-ready" }
    ]
  },
  "repository": {
    "full_name": "test-org/test-repo"
  },
  "sender": {
    "login": "validate-script"
  },
  "_validation": {
    "correlation_id": "$CORRELATION_ID",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "test": "direct-put-events"
  }
}
PAYLOAD
)

# Put event directly on the bus
DETAIL_JSON=$(echo "$GITHUB_PAYLOAD" | jq -c .)

PUT_RESULT=$(aws events put-events \
  --region "$REGION" \
  --entries "[{
    \"EventBusName\": \"$EVENT_BUS\",
    \"Source\": \"fde.github.webhook\",
    \"DetailType\": \"issue.labeled\",
    \"Detail\": $(echo "$DETAIL_JSON" | jq -Rs .)
  }]" 2>&1) || {
  check_fail "PutEvents API call failed" "$PUT_RESULT"
}

FAILED_COUNT=$(echo "$PUT_RESULT" | jq -r '.FailedEntryCount // 0')
if [[ "$FAILED_COUNT" == "0" ]]; then
  check_pass "PutEvents succeeded (event placed on bus)"
else
  ERROR_CODE=$(echo "$PUT_RESULT" | jq -r '.Entries[0].ErrorCode // "unknown"')
  ERROR_MSG=$(echo "$PUT_RESULT" | jq -r '.Entries[0].ErrorMessage // "unknown"')
  check_fail "PutEvents failed: $ERROR_CODE — $ERROR_MSG" \
    "Check IAM permissions for events:PutEvents on $EVENT_BUS"
fi

# Wait for event to propagate
echo "  ⏳ Waiting ${WAIT_SECONDS}s for event propagation..."
sleep "$WAIT_SECONDS"

# Check CloudWatch Logs for the catch-all rule
LOG_EVENTS=$(aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --region "$REGION" \
  --start-time "$(($(date +%s) - 60))000" \
  --filter-pattern "$CORRELATION_ID" \
  --query 'events[].message' \
  --output json 2>/dev/null) || LOG_EVENTS="[]"

EVENT_COUNT=$(echo "$LOG_EVENTS" | jq 'length')
if [[ "$EVENT_COUNT" -gt 0 ]]; then
  check_pass "Event visible in catch-all logs (correlation: $CORRELATION_ID)"

  # Parse the logged event to verify structure
  LOGGED_SOURCE=$(echo "$LOG_EVENTS" | jq -r '.[0]' | jq -r '.source // empty')
  LOGGED_DETAIL_TYPE=$(echo "$LOG_EVENTS" | jq -r '.[0]' | jq -r '.["detail-type"] // empty')
  LOGGED_ACTION=$(echo "$LOG_EVENTS" | jq -r '.[0]' | jq -r '.detail.action // empty')
  LOGGED_LABEL=$(echo "$LOG_EVENTS" | jq -r '.[0]' | jq -r '.detail.label.name // empty')

  echo "  📋 Logged event structure:"
  echo "     source:      $LOGGED_SOURCE"
  echo "     detail-type: $LOGGED_DETAIL_TYPE"
  echo "     action:      $LOGGED_ACTION"
  echo "     label.name:  $LOGGED_LABEL"

  if [[ "$LOGGED_ACTION" == "labeled" && "$LOGGED_LABEL" == "factory-ready" ]]; then
    check_pass "Event detail matches rule pattern (action=labeled, label.name=factory-ready)"
  else
    check_fail "Event detail does NOT match rule pattern" \
      "Rule expects detail.action=[\"labeled\"] AND detail.label.name=[\"factory-ready\"]"
  fi
else
  check_fail "Event NOT visible in catch-all logs" \
    "Either the catch-all rule is not deployed or the log group does not exist. Run: terraform apply"
fi

# ═══════════════════════════════════════════════════════════════════
# TEST 2: Webhook POST to API Gateway (full path)
# ═══════════════════════════════════════════════════════════════════
section "Test 2: API Gateway Webhook POST (full path)"

# Get the API Gateway URL
API_URL=$(aws apigatewayv2 get-apis \
  --region "$REGION" \
  --query "Items[?contains(Name,'webhook')].ApiEndpoint | [0]" \
  --output text 2>/dev/null) || API_URL=""

if [[ -z "$API_URL" || "$API_URL" == "None" ]]; then
  check_fail "API Gateway webhook endpoint not found" \
    "Run: terraform apply -var-file=factory.tfvars"
else
  check_pass "API Gateway endpoint: $API_URL"

  # Update correlation ID for this test
  CORRELATION_ID_2="validate-apigw-$(date +%s)-$$"
  WEBHOOK_PAYLOAD=$(echo "$GITHUB_PAYLOAD" | \
    jq --arg cid "$CORRELATION_ID_2" '._validation.correlation_id = $cid | ._validation.test = "api-gateway-webhook"')

  # Send webhook POST (mimicking GitHub)
  HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "$API_URL/webhook/github" \
    -H "Content-Type: application/json" \
    -H "X-GitHub-Event: issues" \
    -H "X-GitHub-Delivery: $CORRELATION_ID_2" \
    -d "$WEBHOOK_PAYLOAD" 2>/dev/null)

  HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed '$d')
  HTTP_CODE=$(echo "$HTTP_RESPONSE" | tail -n 1)

  if [[ "$HTTP_CODE" == "200" ]]; then
    check_pass "API Gateway returned HTTP 200"

    # Check if EventBridge accepted the event
    # The response body from EventBridge-PutEvents integration contains FailedEntryCount
    APIGW_FAILED=$(echo "$HTTP_BODY" | jq -r '.FailedEntryCount // "unknown"' 2>/dev/null)
    if [[ "$APIGW_FAILED" == "0" ]]; then
      check_pass "EventBridge accepted the event (FailedEntryCount=0)"
    elif [[ "$APIGW_FAILED" == "unknown" ]]; then
      echo "  ⚠️  Could not parse EventBridge response from API Gateway"
      echo "     Response body: $HTTP_BODY"
    else
      check_fail "EventBridge rejected the event (FailedEntryCount=$APIGW_FAILED)" \
        "Check API Gateway integration request_parameters and IAM role"
      echo "     Response: $HTTP_BODY"
    fi

    # Wait and check logs
    echo "  ⏳ Waiting ${WAIT_SECONDS}s for event propagation..."
    sleep "$WAIT_SECONDS"

    LOG_EVENTS_2=$(aws logs filter-log-events \
      --log-group-name "$LOG_GROUP" \
      --region "$REGION" \
      --start-time "$(($(date +%s) - 60))000" \
      --filter-pattern "$CORRELATION_ID_2" \
      --query 'events[].message' \
      --output json 2>/dev/null) || LOG_EVENTS_2="[]"

    EVENT_COUNT_2=$(echo "$LOG_EVENTS_2" | jq 'length')
    if [[ "$EVENT_COUNT_2" -gt 0 ]]; then
      check_pass "API Gateway → EventBridge path confirmed (event in logs)"
    else
      check_fail "Event NOT in catch-all logs after API Gateway POST" \
        "API Gateway returned 200 but event did not reach EventBridge bus. Check IAM role permissions."
    fi
  else
    check_fail "API Gateway returned HTTP $HTTP_CODE (expected 200)" \
      "Response: $HTTP_BODY"
  fi
fi

# ═══════════════════════════════════════════════════════════════════
# TEST 3: Rule Match Verification
# ═══════════════════════════════════════════════════════════════════
section "Test 3: Rule Match Verification"

# Check EventBridge metrics for the GitHub rule
RULE_NAME="fde-${ENVIRONMENT}-github-factory-ready"

# Check MatchedEvents metric (use macOS-compatible date)
START_TIME=$(date -u -v-5M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

MATCHED=$(aws cloudwatch get-metric-statistics \
  --namespace "AWS/Events" \
  --metric-name "MatchedEvents" \
  --dimensions "Name=RuleName,Value=$RULE_NAME" \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 60 \
  --statistics Sum \
  --region "$REGION" \
  --query 'Datapoints[].Sum' \
  --output json 2>/dev/null) || MATCHED="[]"

TOTAL_MATCHED=$(echo "$MATCHED" | jq 'add // 0')

# Check Invocations metric
INVOCATIONS=$(aws cloudwatch get-metric-statistics \
  --namespace "AWS/Events" \
  --metric-name "Invocations" \
  --dimensions "Name=RuleName,Value=$RULE_NAME" \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 60 \
  --statistics Sum \
  --region "$REGION" \
  --query 'Datapoints[].Sum' \
  --output json 2>/dev/null) || INVOCATIONS="[]"

TOTAL_INVOCATIONS=$(echo "$INVOCATIONS" | jq 'add // 0')

# Check FailedInvocations metric
FAILED_INV=$(aws cloudwatch get-metric-statistics \
  --namespace "AWS/Events" \
  --metric-name "FailedInvocations" \
  --dimensions "Name=RuleName,Value=$RULE_NAME" \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 60 \
  --statistics Sum \
  --region "$REGION" \
  --query 'Datapoints[].Sum' \
  --output json 2>/dev/null) || FAILED_INV="[]"

TOTAL_FAILED_INV=$(echo "$FAILED_INV" | jq 'add // 0')

echo "  📊 Rule '$RULE_NAME' metrics (last 5 min):"
echo "     MatchedEvents:     $TOTAL_MATCHED"
echo "     Invocations:       $TOTAL_INVOCATIONS"
echo "     FailedInvocations: $TOTAL_FAILED_INV"

if [[ $(echo "$TOTAL_MATCHED > 0" | bc 2>/dev/null || echo "0") == "1" ]]; then
  check_pass "Rule matched events in the last 5 minutes"
  if [[ $(echo "$TOTAL_INVOCATIONS > 0" | bc 2>/dev/null || echo "0") == "1" ]]; then
    check_pass "Target was invoked (ECS RunTask triggered)"
  else
    check_fail "Rule matched but target invocation count is 0" \
      "Check EventBridge → ECS IAM role and ECS task definition"
  fi
  if [[ $(echo "$TOTAL_FAILED_INV > 0" | bc 2>/dev/null || echo "0") == "1" ]]; then
    check_fail "FailedInvocations detected — ECS target failed" \
      "Check ECS task definition, subnets, security groups, and IAM PassRole"
  fi
else
  echo "  ℹ️  No MatchedEvents in last 5 min (expected if this is the first test)"
  echo "     The direct PutEvents test above should have triggered a match."
  echo "     If catch-all logs show the event but MatchedEvents=0, the rule pattern is wrong."
fi

# ═══════════════════════════════════════════════════════════════════
# DIAGNOSIS SUMMARY
# ═══════════════════════════════════════════════════════════════════
section "Diagnosis Summary"

echo ""
echo "  Correlation IDs for log search:"
echo "    Test 1 (direct):  $CORRELATION_ID"
echo "    Test 2 (webhook): ${CORRELATION_ID_2:-N/A}"
echo ""
echo "  CloudWatch Logs Insights query:"
echo "    fields @timestamp, source, detail.action, detail.label.name"
echo "    | filter @message like '$CORRELATION_ID'"
echo "    | sort @timestamp desc"
echo ""
echo "  Troubleshooting decision tree:"
echo "    1. If Test 1 (direct PutEvents) failed → IAM or bus issue"
echo "    2. If Test 1 passed but Test 2 failed → API Gateway integration issue"
echo "    3. If both passed but no MatchedEvents → Rule pattern mismatch"
echo "    4. If MatchedEvents > 0 but no Invocations → Target (ECS) issue"
echo "    5. If FailedInvocations > 0 → ECS RunTask failing (IAM/network/capacity)"
echo ""

# ─── Summary ─────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════"
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "  ⛔ Webhook → EventBridge path has issues. See failures above."
  exit 1
else
  echo ""
  echo "  🟢 Webhook → EventBridge → Rule Match path is operational."
  exit 0
fi
