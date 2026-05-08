# AI Stance — Code Factory Position on AI Usage

> DORA Capability C1: Clear and communicated AI stance.
> DORA Finding O15: Work intensification guardrail.
> DORA Finding O21: Continuous AI positioning.
> Last updated: 2026-05-08

---

## 1. What AI Does in This Factory

The Code Factory uses AI (Amazon Bedrock foundation models) as an **execution engine** within a governance-first architecture. AI handles:

- **Construction**: Writing code from structured specifications
- **Review**: Adversarial challenge of every write operation
- **Evaluation**: Branch evaluation and quality scoring
- **Fidelity**: Measuring how closely execution matches intent
- **Context**: Semantic memory and cross-session learning

AI does NOT make architectural decisions, set priorities, or determine what to build. Those remain human responsibilities.

## 2. Autonomy Spectrum (L1-L5)

| Level | AI Role | Human Role | When to Use |
|-------|---------|------------|-------------|
| L1 | Suggests only | Decides and executes everything | Learning mode, unfamiliar domain |
| L2 | Executes with approval | Reviews every action before it happens | Sensitive changes, new team members |
| L3 | Executes with gates | Reviews gate outputs, intervenes on rejection | Standard development, established teams |
| L4 | Executes autonomously | Reviews PRs, monitors metrics | Mature repos, proven patterns |
| L5 | Self-optimizing | Monitors dashboards, handles escalations | High-maturity repos with clean CFR history |

The anti-instability loop automatically reduces autonomy when Change Fail Rate rises. This is mechanical, not discretionary.

## 3. Work Intensification Guardrail (DORA O15)

**Explicit policy**: Autonomy levels reduce human toil. They do NOT justify increased workload expectations.

- L4/L5 autonomy means the factory handles more routine work
- It does NOT mean developers should take on more tasks
- If tasks-per-developer-per-week increases >20% after autonomy promotion, the DoR gate will warn about work intensification
- Managers must not use factory throughput as justification for headcount reduction or workload increase

This is not a suggestion. It is a governance boundary enforced by the metrics system.

## 4. Continuous AI Architecture (DORA O21)

Per DORA 2025's "Continuous AI" concept, this factory operates as a living part of the development pipeline:

- **Perceiving**: EventBridge receives work items from any board system
- **Operating**: ECS agents execute autonomously within governance boundaries
- **Collaborating**: Human-in-the-loop at L2/L3 via WebSocket for clarification
- **Learning**: Cross-session memory improves context provision over time
- **Self-governing**: Anti-instability loop, gate optimizer, and maturity scorer provide self-regulation

The factory is not a tool you invoke. It is a team member that operates continuously within defined boundaries.

## 5. What AI Must NOT Do

- Make architectural decisions without human review (ADR process required)
- Deploy to production without branch evaluation passing
- Modify governance rules (hooks, profiles, thresholds) without Staff Engineer approval
- Access secrets directly (ADR-014: tokens fetched at tool invocation time, never in LLM context)
- Override the anti-instability loop (only Staff Engineer manual override)
- Weaken tests to make them pass (test immutability hook enforces this)

## 6. Model Selection Policy

| Use Case | Model Tier | Rationale |
|----------|-----------|-----------|
| Gates (DoR, DoD, adversarial) | Fast (Haiku) | Deterministic checks, low latency, low cost |
| Implementation (code writing) | Reasoning (Sonnet) | Complex reasoning, code generation |
| Architecture review | Deep (Opus) | Nuanced analysis, multi-file understanding |
| Fidelity scoring | Fast (Haiku) | Structured scoring, deterministic |
| Cost tracking | N/A | Passive observation, no model invocation |

Model tier is set per-agent in the Squad Manifest. The orchestrator does not override model selection.

## 7. Data Handling

- **Code**: Processed in EFS within VPC. Never leaves AWS account boundary.
- **Metrics**: Stored in DynamoDB with encryption at rest. No PII.
- **Memory**: Structured decisions stored in DynamoDB. Semantic memory in Bedrock KB (OpenSearch Serverless).
- **Secrets**: AWS Secrets Manager only. Never in environment variables visible to LLM.
- **Logs**: CloudWatch with 30-day retention. No code content in logs (only metadata).

## 8. Incident Response

If AI produces harmful output (security vulnerability, data leak, incorrect architecture):

1. Circuit breaker classifies as CODE error
2. Anti-instability loop detects CFR rise
3. Autonomy automatically reduces
4. Staff Engineer reviews audit trail
5. Root cause analysis via 5 Whys
6. Governance rule added to prevent recurrence

The factory is designed to fail safely and learn from failures mechanically.

---

*This document is the authoritative AI stance for the Code Factory. Changes require Staff Engineer approval and must be reflected in the DoR gate prompt.*
