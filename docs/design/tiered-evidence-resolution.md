# Tiered Evidence Resolution — Design Document

> **Status**: Design
> **Date**: 2026-05-15
> **ADR**: ADR-033 Feature 6
> **Synapse Alignment**: Synapse 5 (Epistemic Stance Awareness)

## Problem

Our evidence-to-finding resolution uses flat confidence scoring. A direct regex
match and a composite multi-evidence inference get the same treatment.

## Solution

Formalize evidence resolution into typed tiers with decreasing confidence.

## Resolution Tiers

| Tier | Name | Confidence | Method | Example |
|------|------|-----------|--------|---------|
| 0 | Explicit | 0.90-1.00 | Direct YAML lookup | `iam_policy_wildcard` → SEC 3 |
| 0b | Composite | 0.75-0.89 | Multiple facts combine | 3 encryption facts → SEC 8 |
| 1 | Inferred | 0.50-0.74 | BP addressability walk | `logging_enabled` → infers OPS 8 |
| 2 | Transitive | 0.30-0.49 | Cross-pillar inference | Security → reliability gap |

## Design Principles

1. **Conservative**: Missed binding > misleading finding
2. **Fixpoint loop**: Tier 1 iterates until stable (max 5 iterations)
3. **Audit trail**: Every evidence carries its resolution_chain
4. **Domain source required**: Must cite specific corpus/YAML entry

## Resolution Pipeline

```
Step 1: Explicit (Tier 0) — direct YAML lookup
Step 2: Composite (Tier 0b) — multi-fact grouping
Step 3: Inferred (Tier 1) — fixpoint loop over BP chains
Step 4: Transitive (Tier 2) — cross-pillar inference
```

## Risk Engine Integration

New signal: `evidence_resolution_depth` (weight +0.8, risk direction)
Deep resolution = more uncertainty = higher risk score.

## Migration Path

1. Add tier/chain fields to evidence records (additive)
2. Existing mappings auto-classify as Tier 0
3. Tier 1-2 surface NEW findings, don't reclassify existing
4. Portal renders tier badges when present (backward compatible)
