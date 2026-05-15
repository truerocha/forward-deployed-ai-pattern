# Pipeline Process Tracing — Design Document

> **Status**: Design
> **Date**: 2026-05-15
> **ADR**: ADR-033 Feature 7
> **Synapse Alignment**: Synapse 6 (Transparency)

## Problem

Pipeline observability is log-based. We know which module ran, but not which
execution flow a specific review followed or where it diverged from expected
behavior. Phase 3.b (Pipeline Testing) lacks structural validation.

## Solution

Instrument the WAFR pipeline to emit structured process traces that can be
queried, compared against baselines, and validated mechanically.

## Process Trace Structure

```
Process: WAFR-Review-{trace_id}
  Step 0: facts_extractor (E1) — input: repo_files → output: 127 facts [450ms]
  Step 1: evidence_catalog (E2) — input: 127 facts → output: 89 evidence [120ms]
  Step 2: deterministic_reviewer (E3) — input: 89 evidence → output: 45 assessments [80ms]
  Step 3: publish_tree (E4) — input: 45 assessments → output: 23 findings [200ms]
  Step 4: publish_sanitizer (E5) — input: 23 findings → output: 23 enriched [150ms]
  Funnel ratio: 0.18 (healthy filtering)
  Total duration: 1000ms
  Anomalies: 0
```

## Validation Rules (Phase 3.b)

| Rule | Condition | Severity |
|------|-----------|----------|
| Zero output | Step produces 0 when baseline expects >0 | BLOCK |
| Amplification | Step output >3x baseline (bug, not filtering) | WARN |
| Funnel inversion | Output > input at any step | BLOCK |
| Duration spike | Step >5x baseline duration | WARN |
| Funnel ratio drift | Total ratio outside 0.5x-2.0x of baseline | WARN |

## Baseline Management

- Baselines generated from known-good runs on reference fixtures
- Stored as JSON in `tests/baselines/process_trace_baseline.json`
- Regenerated when pipeline architecture changes (part of DoD)
- Comparison is ratio-based, not absolute (handles different repo sizes)

## Integration with Phase 3.b

Enhanced Phase 3.b:
1. Run pipeline on test fixture
2. Compare trace against baseline
3. Report deviations as structured findings
4. Any BLOCK-severity deviation = pipeline testing FAILS

## Implementation Steps

1. Add `ProcessTrace` dataclass to `src/pipeline/`
2. Wrap each pipeline module call with trace emission
3. Generate baseline from current test fixture run
4. Add `compare_trace.py` script for Phase 3.b validation
5. Integrate trace output into product smoke test assertions
