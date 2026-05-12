# PEC Intelligence Layer — Risk, Forecast, Knowledge, and Persona UX

> Status: **Implemented**
> Date: 2026-05-12
> Sources: PEC Blueprint (Indice Mestre), Nielsen et al. 2512.04388v5, DORA State of DevOps 2024
> Governance: Changes require Staff SWE approval.

---

## 1. Goal of This Doc

Document the PEC Intelligence Layer — the mathematical and observability spine connecting risk scoring, predictive metrics, semantic code navigation, and role-filtered UX. This is the consolidated design for 4 PEC Blueprint features deployed as a cohesive system.

---

## 2. Executive Summary

Four components form a closed-loop intelligence system:

| Component | Role | Timing |
|-----------|------|--------|
| Risk Inference Engine | Scores tasks pre-execution | Before Conductor |
| DORA Forecast Engine | Projects team trajectory post-execution | After task completion |
| Code Knowledge Base | Provides semantic navigation for agents | During reconnaissance |
| Persona Portal UX | Filters observability per role | At portal render time |

The system operates as a feedback loop: Risk Engine prevents costly failures → Squad executes → DORA Forecast detects trajectory changes → Portal surfaces insights per persona → Risk Engine incorporates new outcomes.

---

## 3. Problem Statement

| # | Problem | Impact |
|---|---------|--------|
| 1 | No predictive risk scoring before execution | Tasks fail after 15+ minutes of compute, wasting tokens and time |
| 2 | DORA metrics are retrospective only | No forward projection — degradation detected after it happens |
| 3 | Agents cannot semantically search code | They grep or read files blindly, missing architectural context |
| 4 | Portal shows all cards to all roles | Cognitive overload — PMs see infra details, SREs see value streams |

---

## 4. Architecture

### 4.1 The PEC Spine (Left-to-Right)

```
Task Intake → Risk Engine [P(F|C)] → Conductor → Squad Execution → DORA Forecast → Portal (Persona-filtered)
                                                        |
                                                        ├── Code KB (agents query during reconnaissance)
                                                        |
                                                        └── Task Outcome → Risk Engine (weight update)
```

### 4.2 Integration Points

```
Router
  → Scope Check
    → RISK ENGINE (new) ─────────────────────────────────────────┐
      → Autonomy Level                                           │
        → Conductor                                              │
          → Squad Execution ──→ Code KB queries                  │
            → Task Outcome                                       │
              → DORA Metrics (DynamoDB)                           │
                → DORA FORECAST ENGINE (new)                      │
                  → PORTAL (Persona-filtered) (new)              │
                    → Risk Engine weight update ◄────────────────┘
```

---

## 5. Components

| Component | Location | Key Modules | Tests |
|-----------|----------|-------------|-------|
| Risk Inference Engine | `src/core/risk/` | `risk_signals.py`, `inference_engine.py`, `risk_config.py` | 33 unit tests |
| DORA Forecast Engine | `src/core/metrics/dora_forecast.py` | `DORAForecastEngine`, `EWMAProjector`, `HealthPulse` | 33 unit tests |
| Code KB Integration | `src/tools/query_code_kb/` | `query_code_kb` tool, `incremental_indexer`, hybrid search | 5 integration tests |
| Persona Portal UX | `portal/src/components/` | `PersonaFilteredCards`, `DoraSunCard`, `PersonaRouter` | TypeScript compilation + Vite build |

---

## 6. Information Flow

### 6.1 Risk Engine Flow

```
Data Contract → Signal Extractor (13 signals) → Weighted Sum → Sigmoid → Classification
  → [pass] Continue to Conductor
  → [warn] Emit to Portal
  → [escalate] Tighten autonomy gates
  → [block] Eject to Staff Engineer
```

### 6.2 DORA Forecast Flow

```
Task Outcome → DORA Metrics (DynamoDB) → Weekly Snapshots → EWMA Projection
  → Level Classification (Elite/High/Medium/Low)
  → Weakest Link Analysis
  → Health Pulse (0-100)
  → Portal DORA Sun Card
```

### 6.3 Code KB Flow

```
Agent Query → query_code_kb tool → QueryAPI → [parallel]
  → Vector Search (Bedrock Titan Embeddings)
  → Keyword Search (BM25)
  → Hybrid Merge (0.6v + 0.4k) → Ranked Results → Agent Context
```

### 6.4 Persona Portal Flow

```
User Opens Portal → PersonaRouter (tab selection) → Persona Config (cards list)
  → PersonaFilteredCards → Render only visible cards per role
```

---

## 7. Testing Design

| Layer | Count | Command |
|-------|-------|---------|
| Risk Engine unit tests | 33 | `python3 -m pytest tests/test_risk_inference_engine.py -v` |
| DORA Forecast unit tests | 33 | `python3 -m pytest tests/test_dora_forecast_engine.py -v` |
| Code KB integration tests | 5 | `python3 -m pytest tests/test_code_kb_integration.py -v` |
| Portal TypeScript compilation | — | `cd portal && npx tsc --noEmit` |
| Portal Vite build | — | `cd portal && npx vite build` |

Total: 66 unit tests + 5 integration tests + build verification.

---

## 8. Well-Architected Alignment

| Pillar | Alignment | How |
|--------|-----------|-----|
| OPS | Observability per persona | Each role sees only relevant metrics — reduces noise, increases signal |
| SEC | Risk blocks unsafe tasks | High-risk changes require human review before execution |
| REL | Forecast detects degradation early | EWMA projection identifies trajectory decline at T+7d, not after incident |
| PERF | Sigmoid is O(1), no external calls | Risk scoring adds ~5ms per task — negligible overhead |
| COST | Prevents wasted compute on high-risk tasks | Blocking a 15-min doomed task saves ~$0.50 in tokens per occurrence |
| SUS | Fewer retries = fewer tokens | Reduced failure rate means less redundant LLM invocation |

---

## 9. Feature Flags

| Flag | Default | Controls |
|------|---------|----------|
| `RISK_ENGINE_ENABLED` | `true` | Risk scoring and classification |
| `DORA_FORECAST_ENABLED` | `true` | EWMA projection and health pulse |
| `CODE_KB_ENABLED` | `true` | Semantic code search for agents |
| `PERSONA_PORTAL_ENABLED` | `true` | Role-filtered card rendering |

---

## 10. References

- [ADR-022: Risk Inference Engine](../adr/ADR-022-risk-inference-engine.md)
- [ADR-023: DORA Forecast Engine](../adr/ADR-023-dora-forecast-engine.md)
- [PEC Blueprint — Indice Mestre](../blueprint/fde-blueprint-design.md)
- Nielsen et al., "Scaling LLM Test-Time Compute Optimally" (2512.04388v5, ICLR 2026)
- [Flow 16: Risk Inference](../flows/16-risk-inference.md)
- [Flow 17: DORA Forecast](../flows/17-dora-forecast.md)
- [Flow 18: Code KB Query](../flows/18-code-kb-query.md)
- [Flow 19: Persona Portal](../flows/19-persona-portal.md)
