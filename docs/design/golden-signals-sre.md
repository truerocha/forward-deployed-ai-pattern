# Golden Signals for SRE Persona — Technical Design

## Goal of This Doc

Define the data contract, thresholds, and rendering behavior for the Golden Signals card in the SRE persona view. This document serves as the canonical reference for what the card shows, where data comes from, and how signal health is computed.

---

## Executive Summary

The SRE persona needs a consolidated view of the 4 Golden Signals (Latency, Traffic, Errors, Saturation) applied to the SDLC pipeline — not infrastructure metrics, but **software delivery health**. The card consolidates data already available in the `/status/tasks` API response into the SRE framework defined by Google's SRE Book (Ch.6).

---

## Problem Statement

1. The SRE persona previously saw only a Cost card — a finance metric, not an operational one
2. DORA metrics were duplicated across views without SRE-specific interpretation
3. Operational signals (stuck tasks, dispatch failures, capacity) were hidden in the Health page, not surfaced in the SRE workflow
4. No single view answered: "Is the delivery pipeline healthy right now?"

---

## Requirements

### Functional Requirements

| Signal | Metric | Source Field | Display |
|--------|--------|-------------|---------|
| Latency | Avg pipeline execution time | `metrics.avg_duration_ms` | Human-readable (min/h) + status indicator |
| Traffic | Tasks completed per 24h | `dora.throughput_24h` | Count + status indicator |
| Traffic | Active agents | `metrics.active_agents` | Count (secondary) |
| Errors | Change Failure Rate | `dora.change_failure_rate_pct` | Percentage + status indicator |
| Errors | Failed tasks (24h) | `metrics.failed_24h` | Count (secondary) |
| Errors | Dispatch blocked | `metrics.dispatch_stuck` | Count (conditional — only shown when > 0) |
| Saturation | Agent capacity | Derived from `/status/health` checks `agent_capacity` | Percentage + status indicator |
| Saturation | Stuck tasks | Derived from `/status/health` checks `stuck_tasks` | Count (conditional — only shown when > 0) |

### Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Render time | < 50ms (no additional API calls — data already in factoryData) |
| Data freshness | Same as dashboard polling interval (5s) |
| Empty state | Card does not render when `metrics` or `dora` is null |
| Accessibility | All status indicators have ARIA labels |

---

## Signal Health Thresholds

### Latency (Pipeline Execution Time)

| Status | Condition | Meaning |
|--------|-----------|---------|
| 🟢 Success | avg_duration_ms < 900,000 (15 min) | Elite/High DORA performance |
| 🟡 Warning | 900,000 ≤ avg_duration_ms ≤ 3,600,000 (15-60 min) | Medium DORA performance |
| 🔴 Error | avg_duration_ms > 3,600,000 (60 min) | Low DORA performance — pipeline bottleneck |

### Traffic (Throughput)

| Status | Condition | Meaning |
|--------|-----------|---------|
| 🟢 Success | throughput_24h ≥ 5 | High delivery velocity |
| 🟡 Warning | 1 ≤ throughput_24h < 5 | Normal delivery velocity |
| 🟡 Warning | throughput_24h = 0 | Idle (not an error — no tasks submitted) |

### Errors (Failure Rate)

| Status | Condition | Meaning |
|--------|-----------|---------|
| 🟢 Success | CFR < 5% AND failed_24h = 0 AND dispatch_stuck = 0 | Clean delivery |
| 🟡 Warning | 5% ≤ CFR ≤ 15% OR failed_24h > 0 OR dispatch_stuck > 0 | Degraded — investigate |
| 🔴 Error | CFR > 15% OR failed_24h > 3 OR dispatch_stuck > 2 | Critical — immediate action |

### Saturation (Capacity)

| Status | Condition | Meaning |
|--------|-----------|---------|
| 🟢 Success | capacity < 50% AND stuck_tasks = 0 | Healthy headroom |
| 🟡 Warning | 50% ≤ capacity ≤ 80% OR stuck_tasks > 0 | Approaching limits |
| 🔴 Error | capacity > 80% OR stuck_tasks > 2 | Saturated — scale or investigate |

### Overall Health Badge

| Badge | Condition |
|-------|-----------|
| **HEALTHY** (green) | All 4 signals are 🟢 |
| **DEGRADED** (blue) | Any signal is 🟡, none are 🔴 |
| **CRITICAL** (red) | Any signal is 🔴 |

---

## Data Flow

```
Dashboard Lambda (/status/tasks)
  → API Response: { metrics: {..., dora: {...}}, tasks: [...] }
    → App.tsx fetches every 5s
      → ObservabilityView receives factoryData
        → GoldenSignalsCard receives:
            metrics = { ...factoryData.metrics, dora: factoryData.dora }
            health = apiStatus (from /status/health, fetched separately)
```

### Data Contract (Props)

```typescript
interface GoldenSignalsCardProps {
  metrics: {
    active: number;
    completed_24h: number;
    failed_24h: number;
    avg_duration_ms: number;
    active_agents: number;
    dispatch_stuck: number;
    dora: {
      lead_time_avg_ms: number;
      success_rate_pct: number;
      throughput_24h: number;
      change_failure_rate_pct: number;
      level: string;
    };
  } | null;
  health: {
    status: string;
    checks: Array<{ name: string; status: string; detail: string }>;
  } | null;
}
```

---

## Component Architecture

```
GoldenSignalsCard.tsx
├── getLatencyStatus(avgMs) → 'success' | 'warning' | 'error'
├── getTrafficStatus(throughput) → 'success' | 'warning' | 'error'
├── getErrorsStatus(cfr, failed, stuck) → 'success' | 'warning' | 'error'
├── getSaturationStatus(activeAgents, max, stuckCount) → 'success' | 'warning' | 'error'
├── getOverallStatus(statuses[]) → 'success' | 'warning' | 'error'
├── formatDuration(ms) → string
├── extractStuckCount(health) → number
└── extractCapacityPct(health) → number
```

### Rendering

- Uses Cloudscape `Container` + `Header` + `ColumnLayout(4)` + `StatusIndicator`
- 4 columns, one per signal
- Each column: label → primary metric with status indicator → secondary detail
- Header has overall health `Badge`
- Returns `null` when `metrics` is null (suppressed by hasData filter)

---

## Persona Placement

| Persona | Has Golden Signals? | Rationale |
|---------|-------------------|-----------|
| **SRE** | ✅ First card | Primary operational view |
| **Staff** | Consider adding | Staff needs system-level health too |
| PM | No | PM cares about value stream, not operational signals |
| SWE | No | SWE cares about their task execution, not system health |
| Architect | No | Architect cares about design quality, not runtime signals |

---

## Testing Scenarios

See `GoldenSignalsCard.test.tsx` for the full behavioral specification. Key scenarios:

1. **Null suppression**: returns null when metrics is null
2. **Latency thresholds**: 3 tests (success/warning/error at 10min/36min/120min)
3. **Traffic display**: throughput count + active agents
4. **Error signals**: CFR%, failed count, dispatch_stuck conditional display
5. **Saturation**: capacity %, stuck tasks conditional display
6. **Overall health**: green when all healthy, red when any signal is error

---

## Future Enhancements

| Enhancement | Priority | Description |
|-------------|----------|-------------|
| Sparkline trends | Medium | Show 7-day trend per signal (requires metrics history) |
| Health endpoint integration | Low | Pass `apiStatus` to get real-time saturation from health checks |
| Alert thresholds config | Low | Make thresholds configurable via factory-config.json |
| SLO burn rate | Medium | Add error budget consumption rate |

---

## References

- Google SRE Book, Chapter 6: Monitoring Distributed Systems
- DORA Metrics: Accelerate (Forsgren, Humble, Kim)
- ADR-023: DORA Forecast Engine
- ADR-031: Cloudscape UX Reformulation
- Component: `infra/portal-src/src/components/GoldenSignalsCard.tsx`
- Test spec: `infra/portal-src/src/components/GoldenSignalsCard.test.tsx`
