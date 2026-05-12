# ADR-023: DORA Forecast Engine

> Status: **Accepted**
> Date: 2026-05-12
> Deciders: Staff SWE (rocand)
> Source: PEC Blueprint Chapter 2 (DORA-Driven AI Mathematical Engineering)
> Related: ADR-022 (Risk Inference Engine), ADR-013 (Enterprise-Grade Autonomy), ADR-017 (React Portal)

## Context

DORA metrics (Deployment Frequency, Lead Time for Changes, Change Failure Rate, Mean Time to Recovery) are retrospective. The factory collects them after each task completes and stores weekly snapshots in DynamoDB. Today these metrics answer "how did we perform?" — they cannot answer "where are we heading?"

The factory needs forward-looking projections to enable:
1. Proactive autonomy adjustment before degradation becomes critical
2. Early detection of metric trajectory decline (T+7d, T+30d)
3. A single health pulse score for the Portal DORA Sun card
4. Identification of the weakest link metric driving team focus
5. Risk-adjusted CFR that blends inference engine scores with historical failure rate

Without forecasting, the system reacts to degradation after it happens. With forecasting, the system detects trajectory changes and adjusts before impact.

## Decision

Implement an EWMA-based DORA Forecast Engine at `src/core/metrics/dora_forecast.py` with the following capabilities:

### Architecture

```
Weekly DORA Snapshots (DynamoDB)
  → EWMA Projector (α=0.3)
    → T+7d and T+30d projections for all 4 metrics
      → Level Classification (Elite/High/Medium/Low per DORA benchmarks)
        → Weakest Link Analysis (lowest-classified metric)
          → Health Pulse (0-100 composite score)
            → Portal DORA Sun Card
```

### Components

| Module | Responsibility |
|--------|---------------|
| `EWMAProjector` | Computes exponentially weighted moving average projections |
| `LevelClassifier` | Maps metric values to Elite/High/Medium/Low per DORA benchmarks |
| `WeakestLinkAnalyzer` | Identifies the metric dragging overall performance down |
| `HealthPulseCalculator` | Computes composite 0-100 score from all 4 metrics |
| `RiskAdjustedCFR` | Blends historical CFR with Risk Engine P(F) scores |

### DORA Level Thresholds

| Metric | Elite | High | Medium | Low |
|--------|-------|------|--------|-----|
| Deployment Frequency | Multiple/day | Daily-Weekly | Weekly-Monthly | < Monthly |
| Lead Time | < 1 hour | 1 day-1 week | 1 week-1 month | > 1 month |
| Change Failure Rate | < 5% | 5-10% | 10-15% | > 15% |
| Mean Time to Recovery | < 1 hour | < 1 day | 1 day-1 week | > 1 week |

### Health Pulse Formula

```
health_pulse = Σ(metric_score_i × weight_i) × 100

Where:
  metric_score_i = {Elite: 1.0, High: 0.75, Medium: 0.5, Low: 0.25}
  weight_i = {DF: 0.25, LT: 0.25, CFR: 0.30, MTTR: 0.20}
```

### Risk-Adjusted CFR

```
risk_adjusted_cfr = (1 - α) × historical_cfr + α × avg_risk_score

Where α = 0.3 (blending factor)
```

### Integration Points

1. **Portal**: Health Pulse drives the DORA Sun card gradient (green → yellow → red)
2. **Risk Engine**: Risk-adjusted CFR feeds back as a signal for future risk scoring
3. **Conductor**: Weakest link metric influences task prioritization recommendations
4. **Alerts**: Health Pulse < 50 triggers Staff Engineer notification

## Consequences

### Positive

- Proactive degradation detection — trajectory decline visible at T+7d before metrics actually drop
- Health Pulse provides single-number summary for Portal DORA Sun card
- Weakest Link analysis drives team focus to the metric that matters most
- Risk-adjusted CFR creates a feedback loop between Risk Engine and DORA metrics
- Feature-flagged (`DORA_FORECAST_ENABLED`) for safe rollout

### Negative

- Requires 3+ weekly snapshots for valid EWMA projection (cold start period)
- EWMA smoothing (α=0.3) may lag sudden changes — a spike takes 2-3 weeks to fully reflect
- Health Pulse is a composite — individual metric degradation may be masked if others are strong

### Risks

| Risk | Mitigation |
|------|------------|
| Insufficient snapshot history | Fallback to current-week-only classification when < 3 snapshots |
| EWMA lag on sudden changes | Alert on single-week drops > 2 standard deviations |
| Health Pulse masking | Weakest Link analysis surfaces individual metric issues |
| Stale projections | Recalculate on every new snapshot, not on a timer |

## Testing

33 tests covering:
- EWMA projection accuracy (8 tests)
- Level classification boundaries (6 tests)
- Weakest link identification (5 tests)
- Health pulse calculation (5 tests)
- Risk-adjusted CFR blending (4 tests)
- Edge cases (insufficient data, single snapshot) (3 tests)
- Serialization and DynamoDB integration (2 tests)

Command: `python3 -m pytest tests/test_dora_forecast_engine.py -v`

## Well-Architected Alignment

| Pillar | Alignment |
|--------|-----------|
| OPS 4 | Health Pulse provides single observability metric for leadership |
| REL 3 | Early degradation detection prevents reliability incidents |
| PERF 2 | EWMA computation is O(n) on snapshot count — negligible |
| COST 4 | Proactive adjustment prevents costly failure cascades |
| SUS 2 | Fewer failures = fewer retry tokens |
