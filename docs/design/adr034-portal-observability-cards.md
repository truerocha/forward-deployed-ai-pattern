# ADR-034 Portal Observability Cards — Design Document

> **Status**: Design
> **Date**: 2026-05-15
> **Ref**: ADR-034 Features 4, 5, 6, 7
> **Pattern**: Cloudscape Design UX Pattern (docs/design/cloudscape-design-ux-pattern.md)

## Principle: No Noise, Maximum Signal

The portal has 18 cards across 5 personas. ADR-034 introduces 4 observable data
streams. Design goal: **add signal without adding noise**.

Rules:
1. One goal per card
2. Persona-filtered — only show to roles that act on the data
3. Progressive disclosure — summary first, drill-down on demand
4. No card unless it drives a DECISION

---

## New Cards (3 total)

F4 (DoD) and F5 (Compound Review) consolidate into one "Quality Gate" card —
they serve the same decision: "Is this task done to standard?"

### Card 1: Quality Gate Compliance

**Personas**: SWE, Staff
**Decision**: "Which dimension fails most?" / "Should I tighten gates?"
**Content**: Pass rate, top failing dimension, most active review lens,
7-dimension mini heatmap (StatusIndicator per dimension).
**Data**: Aggregated DoD gate structured output.

### Card 2: Pipeline Health

**Personas**: SRE, Staff
**Decision**: "Is the pipeline degrading?" / "Which step is anomalous?"
**Content**: 5-step funnel with counts + ProgressBar, funnel ratio,
total duration, anomaly count, healthy/warning StatusIndicator.
**Data**: ProcessTrace JSON from F7.

### Card 3: Evidence Confidence

**Personas**: Architect, Staff
**Decision**: "Are findings well-grounded?" / "Need more explicit mappings?"
**Content**: Tier breakdown with ProgressBar per tier, high-confidence
ratio badge (green >70%, red otherwise).
**Data**: Tier distribution from F6.

---

## Updated Persona Matrix (delta only)

| New Card | PM | SWE | SRE | Architect | Staff |
|----------|:--:|:---:|:---:|:---------:|:-----:|
| Quality Gate | | x | | | x |
| Pipeline Health | | | x | | x |
| Evidence Confidence | | | | x | x |

**Noise check**: Each persona sees at most +1 new card. PM sees +0.
Staff goes from 10→13 (acceptable for oversight role, under 16 limit).

---

## Data Contracts

```typescript
interface QualityGateData {
  period: string;
  totalTasks: number;
  passRate: number;
  dimensions: { name: string; passCount: number; totalCount: number }[];
  topLens: string;
  topFailDimension: string;
}

interface PipelineHealthData {
  traceId: string;
  timestamp: string;
  healthy: boolean;
  funnelRatio: number;
  totalMs: number;
  anomalyCount: number;
  steps: { module: string; edge: string; inputCount: number; outputCount: number; durationMs: number }[];
}

interface EvidenceConfidenceData {
  totalEvidence: number;
  totalFindings: number;
  highConfidenceRatio: number;
  tiers: { name: string; range: string; count: number }[];
}
```

---

## Implementation Priority

| Card | Depends On | Effort | When |
|------|-----------|--------|------|
| Quality Gate | F4 DoD data (already producing) | 1 day | Phase B |
| Pipeline Health | F7 ProcessTrace | 2 days | Phase C |
| Evidence Confidence | F6 Tiered Resolution | 1 day | Phase C |

## File Names

- `infra/portal-src/src/components/QualityGateCard.tsx`
- `infra/portal-src/src/components/PipelineHealthCard.tsx`
- `infra/portal-src/src/components/EvidenceConfidenceCard.tsx`
