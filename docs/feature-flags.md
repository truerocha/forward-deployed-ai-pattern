# Feature Flags — Progressive Rollout Configuration

> All new functionality is gated by feature flags. Default: disabled.
> Flags are environment variables read at runtime by the relevant module.
> No code change required to enable/disable — just update ECS task environment.

---

## Core Flags (Wave 1)

| Flag | Default | Module | What It Controls |
|------|---------|--------|-----------------|
| `ANTI_INSTABILITY_OBSERVE_ONLY` | `true` | `anti_instability_loop.py` | When `true`, logs recommendations but does not auto-adjust autonomy. Set to `false` after 30-day baseline. |
| `COST_ALERT_THRESHOLD` | `2.00` | `cost_tracker.py` | USD threshold per task. CloudWatch alarm fires when exceeded. |
| `MAX_CONCURRENT_AGENTS` | `6` | `distributed_orchestrator.py` | Maximum parallel agents per pipeline stage. |
| `STAGE_TIMEOUT_SECONDS` | `600` | `distributed_orchestrator.py` | Maximum seconds per stage before timeout. |
| `DISPATCH_MODE` | `parallel-within-stage` | `distributed_orchestrator.py` | Agent dispatch strategy. Options: `parallel-within-stage`, `sequential`. |

## Governance Flags (Wave 1)

| Flag | Default | Module | What It Controls |
|------|---------|--------|-----------------|
| `GATE_FEEDBACK_STRUCTURED` | `true` | `gate_feedback_formatter.py` | When `true`, all gate rejections include structured JSON feedback. |
| `USER_VALUE_REQUIRED` | `false` | `user_value_validator.py` | When `true`, DoR gate rejects specs without user value statement (score < 40). Start with `false` (warning-only). |
| `GATE_OPTIMIZER_ENABLED` | `false` | `gate_optimizer.py` | When `true`, trusted patterns at L5 skip adversarial gate. Requires 30 days of observation data. |

## Metrics Flags (Wave 1)

| Flag | Default | Module | What It Controls |
|------|---------|--------|-----------------|
| `DORA_PER_LEVEL_ENABLED` | `true` | `dora_metrics.py` | Track DORA metrics per autonomy level. Should always be `true`. |
| `VSM_TRACKING_ENABLED` | `true` | `vsm_tracker.py` | Track value stream stage transitions. |
| `VERIFICATION_SCALING_ENABLED` | `false` | `verification_metrics.py` | When `true`, auto-scales evaluation agents when queue depth > 3. |
| `TRUST_METRICS_ENABLED` | `true` | `trust_metrics.py` | Track PR acceptance rate and gate override rate. |

## Add-On Flags (Wave 5 — Independent)

| Flag | Default | Module | What It Controls |
|------|---------|--------|-----------------|
| `ENABLE_AIDLC_ADAPTER` | `false` | `aidlc_adapter.py` | AI-DLC S3 artifact import. Requires AI-DLC deployed separately. |
| `ENABLE_ATLASSIAN` | `false` | `atlassian_mcp_proxy.py` | Confluence + Jira integration. Requires OAuth app registration. |

---

## Rollout Strategy

### Phase 1: Observe (Days 1-30)
All flags at defaults. Anti-instability in observe-only mode. Metrics collecting baseline data.

### Phase 2: Activate Governance (Days 31-60)
- Set `ANTI_INSTABILITY_OBSERVE_ONLY=false` (auto-adjustments active)
- Set `USER_VALUE_REQUIRED=true` (DoR enforces user value)
- Review 30-day cost data, adjust `COST_ALERT_THRESHOLD` if needed

### Phase 3: Optimize (Days 61+)
- Set `GATE_OPTIMIZER_ENABLED=true` (trusted patterns skip adversarial)
- Set `VERIFICATION_SCALING_ENABLED=true` (auto-scale evaluation)
- Review calibration report, adjust autonomy levels if needed

---

## How to Change a Flag

### ECS Task Definition (persistent)
Update the environment variable in the Terraform task definition and apply:
```hcl
{ name = "ANTI_INSTABILITY_OBSERVE_ONLY", value = "false" }
```

### Runtime Override (temporary, for testing)
Use ECS RunTask override for a single execution:
```bash
aws ecs run-task --overrides '{"containerOverrides":[{"name":"orchestrator","environment":[{"name":"ANTI_INSTABILITY_OBSERVE_ONLY","value":"false"}]}]}'
```

### DynamoDB Override (per-project)
Store project-specific overrides in the metrics table:
```
PK: {project_id}, SK: "config#feature_flags"
```
The orchestrator checks this before using environment defaults.

---

## Flag Governance

| Action | Requires |
|--------|----------|
| Change default in Terraform | Staff Engineer approval |
| Enable add-on flag | Staff Engineer decision (per-project) |
| Disable safety flag (anti-instability, test-immutability) | Staff Engineer + documented justification |
| Add new flag | PR review + documentation update |

---

*All flags follow the principle: safe by default, opt-in to power. No flag should make the system less safe when enabled.*
