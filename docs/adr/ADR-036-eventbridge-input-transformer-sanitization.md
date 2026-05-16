# ADR-036: EventBridge InputTransformer Sanitization

## Status

**Accepted** — 2025-05-16

## Context

### Problem Statement

Events emitted by the `webhook_ingest` Lambda via EventBridge `PutEvents` were accepted successfully (FailedEntryCount=0), but the downstream ECS target was not being started. Manual events with clean data worked correctly. The failure was **silent** — no error logs, no DLQ messages, no CloudWatch metrics indicated the failure.

### Root Cause (5 Whys Analysis)

1. **Why doesn't the ECS task start?** — The EventBridge rule matches the event, but the target invocation fails.
2. **Why does the target invocation fail?** — The InputTransformer produces invalid JSON after placeholder substitution.
3. **Why is the JSON invalid?** — The `<title>` placeholder is substituted with a raw string value that contains double quotes (`"`), newlines (`\n`), or backslashes (`\`).
4. **Why do these characters appear?** — The `title` field comes from GitHub issue titles, which are user-generated and can contain any character.
5. **Why doesn't EventBridge escape the values?** — The InputTransformer performs **raw text substitution** — it does not JSON-escape values when inserting them into the template. This is documented AWS behavior.

### Pipeline Edge

```
webhook_ingest Lambda (Producer)
    → EventBridge PutEvents (Detail JSON)
        → InputTransformer (input_paths + input_template)
            → ECS RunTask (containerOverrides JSON)
```

The failure occurs at the InputTransformer boundary — the Detail JSON is valid, but the **output** of the InputTransformer is not valid JSON when user-generated fields contain special characters.

### Why Manual Tests Passed

Manual test events used `"title": "manual test"` — no special characters. Production events carry GitHub issue titles that may contain quotes, newlines, paths with backslashes, etc.

## Decision

Implement a **defense-in-depth** approach with three layers:

### Layer 1: Producer Sanitization (Prevents)

A shared utility (`infra/terraform/lambda/shared/eventbridge_sanitizer.py`) sanitizes all user-generated string fields before EventBridge emission:
- Double quotes (`"`) → single quotes (`'`)
- Backslashes (`\`) → forward slashes (`/`)
- Newlines/carriage returns → spaces
- Control characters (U+0000-U+001F) → removed
- Depth values clamped to `[0.0, 1.0]` with 3 decimal precision, NaN/Inf → 0.0

Applied in both `webhook_ingest` and `reaper` Lambdas via shared import.

### Layer 2: Dead Letter Queue (Detects)

An SQS DLQ attached to the EventBridge ECS target captures any events where the target invocation still fails (e.g., ECS RunTask capacity errors, future InputTransformer issues). CloudWatch alarm triggers on any DLQ message.

### Layer 3: Contract Test (Prevents Regression)

A pytest contract test (`tests/integration/test_eventbridge_input_transformer_contract.py`) simulates the exact InputTransformer behavior and validates that sanitized output always produces valid JSON. Covers adversarial inputs: quotes, newlines, backslashes, control characters, all fields simultaneously.

## Alternatives Considered

### A. Sanitization Only (No DLQ)

- **Pro**: Simplest, lowest blast radius
- **Con**: No detection if sanitization has gaps or new failure modes emerge
- **Rejected**: Insufficient observability for a silent failure class

### B. Eliminate InputTransformer (Lambda Intermediary)

- **Pro**: Eliminates the entire class of bugs
- **Con**: +100ms latency, +1 Lambda to maintain, Terraform state migration risk, breaking change to container entrypoint
- **Rejected for now**: Over-engineering for current scale. Documented as future option if DLQ alarm fires repeatedly.

### C. Container Fetches from DynamoDB (No env vars)

- **Pro**: Single source of truth, no InputTransformer needed
- **Con**: Container needs DynamoDB permissions, +50ms latency, breaking change to all containers
- **Rejected for now**: Requires coordinated container + infra change. Future consideration.

## Consequences

### Positive

- Silent failures eliminated — sanitization prevents, DLQ detects, test prevents regression
- Zero breaking changes — same JSON structure, same env vars, same container behavior
- Observability improved — WARNING logs when sanitization alters values, DLQ alarm for failures
- Both producers (webhook_ingest + reaper) use shared utility — no drift

### Negative

- Title content is slightly altered (quotes become single quotes) — acceptable for display purposes
- Shared module requires inclusion in both Lambda deployment zips (build process update)
- DLQ adds ~$0.01/month cost (negligible)

### Risks Accepted

- If a future field is added to the event without sanitization, the bug can recur → mitigated by contract test that validates the full flow
- Sanitization may mask upstream bugs (e.g., HTML-encoded content) → mitigated by WARNING logs with sample of original value

## Well-Architected Alignment

| Pillar | Question | How Addressed |
|--------|----------|---------------|
| Reliability | REL 4: Design interactions to prevent failures | Sanitize at producer boundary |
| Reliability | REL 11: Use fault isolation | DLQ isolates failed events |
| Operational Excellence | OPS 8: Understand operational health | DLQ alarm + sanitization WARNING logs |
| Security | SEC 8: Protect data in transit | Prevents injection via crafted issue titles |

## Files Changed

| File | Change |
|------|--------|
| `infra/terraform/lambda/shared/__init__.py` | New — shared package |
| `infra/terraform/lambda/shared/eventbridge_sanitizer.py` | New — sanitization utility |
| `infra/terraform/lambda/webhook_ingest/index.py` | Modified — uses sanitize_dispatch_detail |
| `infra/terraform/lambda/reaper/index.py` | Modified — uses sanitize_dispatch_detail |
| `infra/terraform/cognitive_router.tf` | Modified — DLQ + alarm added |
| `tests/integration/test_eventbridge_input_transformer_contract.py` | New — contract test |
| `docs/adr/ADR-036-eventbridge-input-transformer-sanitization.md` | This document |

## Validation

- 22 contract tests pass (0.14s)
- Adversarial test covers all user-generated fields with quotes + newlines + backslashes + control chars simultaneously
- Depth edge cases: NaN, Infinity, negative, >1.0, None, invalid string — all handled

## Future Considerations

If the DLQ alarm fires repeatedly despite sanitization:
1. Investigate whether the failure is InputTransformer or ECS RunTask capacity
2. Consider migrating to Lambda intermediary (Option B) to eliminate InputTransformer entirely
3. Consider container-fetches-from-DynamoDB pattern (Option C) for single source of truth
