# Flow 16: Risk Inference Engine

> Predictive risk scoring before agent execution — blocks, escalates, or passes tasks based on P(Failure|Context).

## Trigger

- **Orchestrator**: After Scope Check passes, before Conductor receives the task
- **Feature Flag**: `RISK_ENGINE_ENABLED`

## Flow

```mermaid
---
title: Risk Inference Engine Flow
---
%%{init: {'flowchart': {'rankSpacing': 80, 'nodeSpacing': 40}}}%%
flowchart LR
    subgraph Intake
        DC[Data Contract<br/>from Router]
    end

    subgraph "Signal Extraction"
        SE[Signal Extractor<br/>13 normalized signals]
        H[Historical Signals<br/>CFR, recurrence, hotspot]
        CX[Complexity Signals<br/>files, cyclomatic, deps, cross-module]
        DT[DORA Trend Signals<br/>lead time, deploy freq]
        O[Organism Signal<br/>O1-O5 level]
        P[Protective Signals<br/>coverage, prior success, catalog]
    end

    subgraph "Inference"
        WS[Weighted Sum<br/>Σ wᵢ × sᵢ]
        SIG[Sigmoid<br/>σ z = 1 div 1+e⁻ᶻ]
        RS[Risk Score<br/>P F|C in 0 to 1]
    end

    subgraph "Classification"
        CD{Classification<br/>Decision}
        PASS[Pass<br/>score less than τ_warn]
        WARN[Warn<br/>τ_warn to τ_escalate]
        ESC[Escalate<br/>τ_escalate to τ_block]
        BLOCK[Block<br/>score gte τ_block]
    end

    subgraph "Action"
        CONT[Continue to<br/>Conductor]
        PORTAL[Emit Warning<br/>to Portal]
        GATES[Tighten<br/>Autonomy Gates]
        EJECT[Eject to<br/>Staff Engineer]
    end

    subgraph "Feedback Loop"
        OUTCOME[Task Outcome<br/>success/failure]
        RO[Recursive Optimizer<br/>gradient descent]
        WU[Weight Update<br/>lr=0.01, decay=0.001]
    end

    DC --> SE
    SE --> H & CX & DT & O & P
    H & CX & DT & O & P --> WS
    WS --> SIG --> RS --> CD

    CD -->|"< 0.08"| PASS --> CONT
    CD -->|"0.08-0.15"| WARN --> PORTAL --> CONT
    CD -->|"0.15-0.40"| ESC --> GATES --> CONT
    CD -->|">= 0.40"| BLOCK --> EJECT

    CONT --> OUTCOME
    OUTCOME --> RO --> WU --> SE
```

## Thresholds

| Threshold | Value | Action |
|-----------|-------|--------|
| τ_warn | 0.08 | Emit warning to portal |
| τ_escalate | 0.15 | Tighten autonomy gates |
| τ_block | 0.40 | Eject to Staff Engineer |

## Signals (13 total)

| Category | Count | Signals |
|----------|-------|---------|
| Historical | 3 | Change failure rate, failure recurrence, repo hotspot |
| Complexity | 4 | File count, cyclomatic complexity, dependency depth, cross-module |
| DORA Trend | 2 | Lead time trend, deployment frequency trend |
| Organism | 1 | Organism level (O1-O5) |
| Protective | 3 | Test coverage, prior success rate, catalog confidence |

## Recursive Optimizer

After each task completes:
- **False negative** (predicted safe, actually failed) → increase risk weights
- **False positive** (predicted risky, actually succeeded) → decrease risk weights
- Learning rate: 0.01, weight decay: 0.001, max magnitude: 5.0

## Related

- [ADR-022](../adr/ADR-022-risk-inference-engine.md) — Architecture decision
- [Design Doc](../design/pec-intelligence-layer.md) — PEC Intelligence Layer
- [Flow 17](17-dora-forecast.md) — DORA Forecast (consumes risk-adjusted CFR)
