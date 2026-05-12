# Flow 17: DORA Forecast Engine

> Forward-looking DORA metric projections — detects trajectory degradation before it impacts delivery.

## Trigger

- **Task Completion**: After any task outcome is recorded
- **Weekly Snapshot**: Scheduled DynamoDB write of aggregated metrics
- **Feature Flag**: `DORA_FORECAST_ENABLED`

## Flow

```mermaid
---
title: DORA Forecast Engine Flow
---
%%{init: {'flowchart': {'rankSpacing': 80, 'nodeSpacing': 40}}}%%
flowchart LR
    subgraph "Data Collection"
        TC[Task Completion]
        DM[DORA Metrics<br/>DynamoDB]
        WS[Weekly Snapshots<br/>DF, LT, CFR, MTTR]
    end

    subgraph "Projection"
        EWMA[EWMA Projector<br/>α=0.3]
        T7[T+7d Projection]
        T30[T+30d Projection]
    end

    subgraph "Classification"
        LC[Level Classifier<br/>per metric]
        ELITE[Elite]
        HIGH[High]
        MED[Medium]
        LOW[Low]
    end

    subgraph "Analysis"
        WL[Weakest Link<br/>Analysis]
        HP[Health Pulse<br/>0-100 composite]
    end

    subgraph "Risk Integration"
        RES[Risk Engine Score<br/>P F given C]
        RACFR[Risk-Adjusted CFR<br/>blend α=0.3]
    end

    subgraph "Output"
        SUN[Portal DORA Sun Card<br/>gradient visualization]
        ALERT{Health Pulse<br/>below 50?}
        NOTIFY[Staff Engineer<br/>Notification]
        OK[Normal Operation]
    end

    TC --> DM --> WS
    WS --> EWMA
    EWMA --> T7 & T30
    T7 & T30 --> LC
    LC --> ELITE & HIGH & MED & LOW
    ELITE & HIGH & MED & LOW --> WL
    WL --> HP

    RES --> RACFR
    RACFR --> LC

    HP --> SUN
    HP --> ALERT
    ALERT -->|Yes| NOTIFY
    ALERT -->|No| OK
```

## EWMA Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| α (smoothing factor) | 0.3 | Balances responsiveness with stability |
| Minimum snapshots | 3 | Below this, fallback to current-week classification |
| Projection horizons | T+7d, T+30d | Short-term tactical + medium-term strategic |

## Health Pulse Calculation

```
health_pulse = Σ(metric_score_i × weight_i) × 100

metric_score: Elite=1.0, High=0.75, Medium=0.5, Low=0.25
weights: DF=0.25, LT=0.25, CFR=0.30, MTTR=0.20
```

## Risk-Adjusted CFR

```
risk_adjusted_cfr = 0.7 × historical_cfr + 0.3 × avg_risk_score
```

Blends historical failure rate with the Risk Engine's predictive scores to produce a forward-looking CFR estimate.

## Related

- [ADR-023](../adr/ADR-023-dora-forecast-engine.md) — Architecture decision
- [Design Doc](../design/pec-intelligence-layer.md) — PEC Intelligence Layer
- [Flow 16](16-risk-inference.md) — Risk Inference (produces risk scores consumed here)
- [Flow 19](19-persona-portal.md) — Persona Portal (renders DORA Sun card)
