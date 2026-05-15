# ADR-032: FDE Extension Opt-In System

## Status
Accepted

## Date
2026-05-15

## Context

FDE hooks (DoR gate, adversarial gate, DoD gate, pipeline validation) fire on every task regardless of project context. A customer doing a simple bug fix doesn't need the adversarial gate. A team using Cursor instead of Kiro can't use hooks at all but wants the methodology guidance.

Additionally, new capabilities (brown-field elevation, DDD design phase, multi-platform export) need a mechanism to be enabled per-project without modifying the core pipeline.

The AI-DLC framework (awslabs/aidlc-workflows) uses an extension opt-in pattern where `*.opt-in.md` files present questions during requirements analysis. We adopt a similar philosophy but implement it as a JSON profile that the hooks read at runtime.

## Decision

Introduce `fde-profile.json` at project root as the single configuration point for FDE behavior. Hooks check this file before executing. Missing file = all gates ON (backward compatible).

### Profile Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "version": { "const": "1.0" },
    "profile": { "enum": ["minimal", "standard", "strict", "custom"] },
    "gates": {
      "type": "object",
      "properties": {
        "dor": { "type": "boolean", "default": true },
        "adversarial": { "type": "boolean", "default": true },
        "dod": { "type": "boolean", "default": true },
        "pipeline-validation": { "type": "boolean", "default": true },
        "branch-evaluation": { "type": "boolean", "default": true },
        "icrl-feedback": { "type": "boolean", "default": true }
      }
    },
    "extensions": {
      "type": "object",
      "properties": {
        "multi-platform-export": { "type": "boolean", "default": false },
        "brown-field-elevation": { "type": "boolean", "default": false },
        "ddd-design-phase": { "type": "boolean", "default": false }
      }
    },
    "conductor": {
      "type": "object",
      "properties": {
        "auto-design-threshold": { "type": "number", "default": 0.5, "description": "Cognitive depth above which DDD design phase activates automatically" }
      }
    }
  },
  "required": ["version", "profile"]
}
```

### Profile Presets

| Preset | DoR | Adversarial | DoD | Pipeline | Branch Eval | ICRL | Extensions |
|--------|:---:|:-----------:|:---:|:--------:|:-----------:|:----:|:----------:|
| minimal | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | none |
| standard | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | none |
| strict | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | all |
| custom | per config | per config | per config | per config | per config | per config | per config |

### Hook Integration

Each hook's prompt includes a preamble:

```
Check fde-profile.json at project root.
If file exists AND gates.{this_gate} is false: SKIP — respond "Gate skipped per fde-profile.json"
If file missing OR gates.{this_gate} is true OR key missing: EXECUTE normally.
```

### Validation

`scripts/validate-fde-profile.py` validates:
1. JSON schema conformance
2. Profile preset consistency (if preset != "custom", gates must match preset definition)
3. Extension dependency checks (ddd-design-phase requires brown-field-elevation for brown-field projects)

## Consequences

### Positive
- Projects can tune FDE intensity without modifying hooks
- New extensions ship as opt-in without breaking existing users
- Profile is version-controlled — team agrees on enforcement level
- Aligns with AI-DLC extension opt-in philosophy

### Negative
- One more file at project root
- Hooks have slightly more complex logic (check file before executing)
- Risk of teams setting "minimal" and losing quality benefits

### Mitigations
- Default (no file) = full enforcement — you must actively opt out
- `strict` profile cannot be downgraded without a commit (auditable)
- Portal shows active profile in the Health view

## Related
- ADR-029 — Cognitive Autonomy Model (depth-based decisions)
- ADR-020 — Conductor Orchestration Pattern (step injection)
- AI-DLC extensions system (awslabs/aidlc-workflows)
