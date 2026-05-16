# ADR-034: Agent-to-Agent (A2A) Protocol Integration with Strands SDK

## Status

Accepted

## Date

2026-05-16

## Context

The FDE factory pipeline executes multi-phase workflows (Reconnaissance → Engineering → Reporting) using Strands Agents on Amazon Bedrock. The current architecture (ADR-019, ADR-020) dispatches agents via ECS RunTask with environment variable parameterization, but agents communicate indirectly through shared state in DynamoDB/S3 rather than directly with each other.

This creates several limitations:
1. **Tight coupling**: The orchestrator must understand each agent's internal contract
2. **No streaming**: Results are only available after full agent completion
3. **Monolithic scaling**: All agents share the same task definition resources
4. **No capability discovery**: The orchestrator hardcodes agent capabilities

The Google Agent-to-Agent (A2A) protocol provides a standardized way for agents to discover each other's capabilities and communicate via structured JSON-RPC messages. The Strands Agents SDK (v1.0+) includes native A2A support via `strands.a2a`.

## Decision

We adopt the A2A protocol for inter-agent communication within the FDE factory, implemented via the Strands SDK's `A2AServer` and `A2AAgent` abstractions.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    A2A Workflow Graph (Orchestrator)              │
│                                                                  │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐                │
│  │ PESQUISA │────▶│ ESCRITA  │────▶│ REVISAO  │──┐             │
│  │ (Phase 1)│     │(Phase 2-3)│     │ (Phase 4)│  │             │
│  └──────────┘     └──────────┘     └──────────┘  │             │
│                         ▲                          │             │
│                         └──────── feedback ────────┘             │
│                                                                  │
│  State: DynamoDB checkpointing (Saga pattern)                   │
│  Discovery: AWS Cloud Map (pesquisa.fde.local:9001)             │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Choices

1. **Each agent = independent ECS Service** with its own Cloud Map DNS entry
2. **A2AAgent proxy** in the orchestrator — no direct code imports between agents
3. **Pydantic data contracts** enforce type safety at graph edges
4. **DynamoDB checkpointing** enables fault recovery (resume from last node)
5. **Lazy Agent Card discovery** — capabilities fetched on first invocation
6. **Feedback loop routing** — reviewer can route back to writer (max 3 cycles)

### Data Contracts

| Contract | Producer | Consumer | Purpose |
|----------|----------|----------|---------|
| `ConteudoBruto` | Pesquisa | Escrita | Research findings |
| `RelatorioFinal` | Escrita | Revisao | Technical deliverable |
| `FeedbackRevisao` | Revisao | Escrita (rework) | Quality feedback |
| `ContextoWorkflow` | Orchestrator | DynamoDB | Checkpoint state |

### Infrastructure

| Resource | Purpose |
|----------|---------|
| Cloud Map namespace `fde.local` | Internal DNS for agent discovery |
| DynamoDB `fde-{env}-a2a-workflow-state` | Workflow checkpointing |
| ECR `fde-{env}-a2a-agents` | Shared image repository |
| 3x ECS Services | Independent agent scaling |

## Consequences

### Positive

- **Decoupled scaling**: Research agent can scale independently of reviewer
- **Zero-downtime upgrades**: Blue/green via Cloud Map weight shifting
- **Fault tolerance**: Checkpoint-based recovery skips completed nodes
- **Streaming ready**: A2AAgent supports `.stream()` for real-time token flow
- **Future-proof**: Moving agents to separate repos/languages requires zero orchestrator changes
- **Observability**: Each agent has its own CloudWatch log stream and health check

### Negative

- **Network overhead**: HTTP calls between containers (mitigated by VPC-local traffic)
- **Complexity**: More moving parts than monolith (3 services vs 1)
- **Cold start**: Each agent container has independent cold start (mitigated by min capacity)
- **Dependency**: Requires `strands-agents[a2a]` extra (adds FastAPI/uvicorn to image)

### Neutral

- Compatible with existing distributed orchestrator (ADR-019) — A2A is an alternative execution path
- Does not replace the monolith entrypoint — both paths coexist (ADR-030 dual-path)
- DynamoDB costs are minimal (PAY_PER_REQUEST, TTL cleanup)

## Alternatives Considered

1. **Direct function calls**: Simpler but prevents independent scaling and language flexibility
2. **SQS-based messaging**: Async but adds latency and complexity for synchronous workflows
3. **Step Functions**: AWS-native but vendor lock-in and limited agent reasoning support
4. **Custom gRPC**: High performance but requires schema management and code generation

## Related

- ADR-019: Agentic Squad Architecture
- ADR-020: Conductor Orchestration Pattern
- ADR-030: Cognitive Router Dual-Path
- ADR-009: AWS Cloud Infrastructure
- ADR-010: Data Contract Task Input
