# Conductor Orchestration Pattern — Design Document

> Status: **Implemented (Phase 1)**
> Date: 2026-05-11
> Sources: `2512.04388v5.pdf` (Nielsen et al., ICLR 2026) + `Indice Mestre de Design e Implantacao.md` + `O Mapa de Leitura do Engenheiro.md`
> Artifact: `src/core/orchestration/conductor.py`
> Governance: Changes require Staff SWE approval.

---

## 1. Executive Summary

This document describes the integration of the **RL Conductor pattern** (Nielsen et al., ICLR 2026) into the FDE Code Factory's distributed orchestration layer. The Conductor replaces static squad manifests with dynamically generated workflow plans that adapt to task complexity.

### What We Extracted from the Paper

| Paper Concept | FDE Implementation | Why It Fits |
|---------------|-------------------|-------------|
| Conductor model generates workflow plans | `Conductor.generate_plan()` via Bedrock reasoning | Our orchestrator already dispatches agents — now it dispatches *intelligently* |
| Subtask decomposition with focused instructions | `WorkflowStep.subtask` field | Agents perform better with targeted instructions vs generic role prompts |
| Communication topology (access lists) | `WorkflowStep.access_list` -> SCD section permissions | We already have SCD sections — now access is intentional, not broadcast |
| Adaptive worker selection | `_AGENT_CAPABILITIES` + organism-driven pool | Our model tier system already differentiates — now selection is task-aware |
| Recursive self-referential scaling | `Conductor.should_recurse()` + `refine_plan()` | Maps to anti-instability loop: when confidence is low, re-plan |
| Task difficulty adaptivity | `_ORGANISM_COMPLEXITY` mapping | Our organism ladder already classifies — now it drives workflow shape |

### What We Did NOT Extract (Not Applicable)

| Paper Concept | Why Not | Our Alternative |
|---------------|---------|-----------------|
| RL training of 7B model | We don't train custom models; we use Bedrock | Bedrock reasoning model generates plans via prompt engineering |
| GRPO optimization | Requires training infrastructure | Deterministic topology selection + Bedrock reasoning |
| Benchmark evaluation (GPQA, LiveCodeBench) | Academic benchmarks, not SWE tasks | DORA metrics + fidelity scoring |
| Unbounded recursion | Cost risk in production | Bounded to max 2 recursive levels |

---

## 2. Architecture Integration

### 2.1 Where the Conductor Sits

```
Task Intake (Issue/Spec)
  |
  v
Organism Ladder (complexity classification: O1-O5)
  |
  v
+--------------------------------------------------+
|  CONDUCTOR (NEW)                                  |
|                                                   |
|  Input: task + organism + knowledge context       |
|  Output: WorkflowPlan (steps + topology)          |
|                                                   |
|  Uses Bedrock reasoning to:                       |
|    1. Decompose task into subtasks                |
|    2. Assign agents by capability matching        |
|    3. Define communication topology               |
|    4. Estimate token budget                       |
+-------------------------+------------------------+
                          |
                          v
+--------------------------------------------------+
|  DISTRIBUTED ORCHESTRATOR (existing)              |
|                                                   |
|  Receives: WorkflowPlan.to_squad_manifest_stages  |
|  Executes: ECS RunTask per agent per stage        |
|  Monitors: DynamoDB SCD polling                   |
+-------------------------+------------------------+
                          |
                          v
+--------------------------------------------------+
|  RECURSIVE CHECK (NEW)                            |
|                                                   |
|  If confidence < threshold:                       |
|    Conductor.refine_plan() -> re-execute          |
|  Else:                                            |
|    Complete -> record metrics                     |
+--------------------------------------------------+
```

### 2.2 Mapping to PEC Blueprint (Indice Mestre)

| PEC Layer | Conductor Role |
|-----------|---------------|
| **Parte 1: Fundacao** | Conductor IS the PEC's "Risk Inference Engine" for orchestration decisions |
| **Parte 2: Cerebro Matematico** | Organism ladder feeds complexity signal to Conductor |
| **Parte 3: Ecossistema de Dados** | Knowledge context from Pinecone/DynamoDB enriches Conductor input |
| **Parte 4: Orquestracao** | Conductor generates the Strands SOP-compatible workflow plan |
| **Parte 5: Interface** | Conductor plans are visible in portal (topology visualization) |
| **Parte 6: Governanca** | Recursive refinement IS the RCA loop for orchestration failures |
| **Parte 7: Sprints** | Conductor deploys in Sprint 2 (after basic distributed execution) |

### 2.3 Communication Topology Types

| Topology | When Used | Agent Pattern |
|----------|-----------|---------------|
| **Sequential** | O1-O2 tasks, simple changes | Plan -> Implement -> Validate |
| **Parallel** | O3 tasks, independent subtasks | Multiple agents work independently |
| **Tree** | O3-O4 tasks, hierarchical decomposition | Architect decomposes -> developers implement branches |
| **Debate** | O4 tasks, high-stakes decisions | Multiple approaches -> arbiter selects best |
| **Recursive** | O5 tasks, novel problems | Conductor re-enters to refine strategy |

---

## 3. Key Design Decisions

### 3.1 Why Bedrock Reasoning Instead of RL-Trained Model

The paper trains a 7B model with GRPO. We use Bedrock's reasoning tier because:
1. No training infrastructure needed
2. Bedrock models already have strong decomposition capabilities
3. Our task domain (SWE) is narrower than the paper's (math + code + science)
4. Cost is acceptable: one Conductor call per task (~4K tokens)

### 3.2 Why Bounded Recursion (Max 2)

The paper allows unbounded recursive calls. We bound at 2 because:
1. Each recursion doubles cost (new Conductor call + re-execution)
2. Our anti-instability loop already handles persistent failures
3. 2 levels covers: initial plan -> refinement -> final attempt
4. Beyond 2, the problem is likely architectural (not orchestration)

### 3.3 Why Access Lists Instead of Broadcast

The paper's key finding: "Communication topology matters - not every agent needs to see everything." Our implementation:
- `access_list: []` = agent works independently (no context pollution)
- `access_list: ["all"]` = agent sees all previous outputs (verification steps)
- `access_list: [0, 2]` = agent sees specific outputs (targeted context)

This maps directly to SCD section read permissions in DynamoDB.

### 3.4 Why Organism Level Drives Topology

The paper discovers that harder problems need more steps and more complex topologies. Our organism ladder already classifies task complexity. The mapping:
- O1 (trivial): 2 steps, sequential
- O2 (simple): 3 steps, sequential
- O3 (moderate): 4 steps, tree
- O4 (complex): 5 steps, debate
- O5 (novel): 6 steps, recursive

---

## 4. Integration with Existing Components

### 4.1 DistributedOrchestrator Integration

```python
from src.core.orchestration.conductor import Conductor
from src.core.orchestration.distributed_orchestrator import (
    DistributedOrchestrator, SquadManifest, AgentSpec
)

# Conductor generates the plan
conductor = Conductor()
plan = conductor.generate_plan(
    task_id="task-123",
    task_description="Implement JWT refresh rotation",
    organism_level="O3",
    knowledge_context={"auth_module": "src/auth/"},
    user_value_statement="Users stay logged in without manual re-auth",
)

# Convert plan to SquadManifest stages
stages_dict = plan.to_squad_manifest_stages()

# Build SquadManifest for orchestrator
manifest = SquadManifest(
    task_id="task-123",
    project_id="payment-service",
    organism_level="O3",
    user_value_statement="Users stay logged in without manual re-auth",
    autonomy_level=4,
    stages={
        stage_num: [
            AgentSpec(
                role=agent["role"],
                model_tier=agent["model_tier"],
                stage=stage_num,
                timeout_seconds=agent["timeout_seconds"],
                retry_max=agent["retry_max"],
            )
            for agent in agents
        ]
        for stage_num, agents in stages_dict.items()
    },
    knowledge_context={"auth_module": "src/auth/"},
)

# Execute
orchestrator = DistributedOrchestrator()
results = orchestrator.execute(manifest)

# Check if recursive refinement needed
execution_result = {"stage_results": [r.__dict__ for r in results]}
if conductor.should_recurse(plan, execution_result):
    refined_plan = conductor.refine_plan(
        original_plan=plan,
        execution_result=execution_result,
        task_description="Implement JWT refresh rotation",
    )
    # Re-execute with refined plan...
```

### 4.2 Agent Runner Integration

The `agent_runner.py` already reads SCD sections. The Conductor's access lists are enforced by:
1. Conductor generates `access_list` per step
2. Orchestrator writes access permissions to SCD metadata
3. Agent runner reads ONLY permitted sections (existing behavior)

The new addition: the `subtask` field from WorkflowStep is injected into the agent's system prompt as a **focused instruction**, replacing the generic role-based prompt.

### 4.3 Anti-Instability Loop Integration

The Conductor's recursive refinement complements the anti-instability loop:
- **Anti-instability loop**: reduces autonomy level when CFR rises (governance)
- **Conductor recursion**: refines coordination strategy when confidence is low (orchestration)

They operate at different levels:
- Anti-instability = "should we trust the system less?" (level change)
- Conductor recursion = "should we try a different approach?" (strategy change)

---

## 5. Observability

### 5.1 Metrics Emitted

| Metric | Source | Purpose |
|--------|--------|---------|
| `conductor.plan_generated` | Conductor | Track plan generation rate |
| `conductor.topology_selected` | Conductor | Distribution of topology types |
| `conductor.steps_per_plan` | Conductor | Workflow complexity trend |
| `conductor.recursive_triggered` | Conductor | How often refinement is needed |
| `conductor.fallback_used` | Conductor | Conductor reasoning failures |
| `conductor.tokens_used` | Bedrock usage | Cost of planning overhead |

### 5.2 Portal Integration

New card: **ConductorPlanCard.tsx** showing:
- Current plan topology (visual graph)
- Step-by-step progress with agent assignments
- Access list visualization (who sees what)
- Recursive depth indicator
- Planning rationale (Conductor's reasoning)

---

## 6. Cost Analysis

| Component | Per-Task Cost | Monthly (100 tasks) |
|-----------|--------------|---------------------|
| Conductor plan generation | ~$0.02 (4K tokens reasoning) | ~$2.00 |
| Recursive refinement (20% of tasks) | ~$0.02 additional | ~$0.40 |
| **Total Conductor overhead** | **~$0.024 avg** | **~$2.40** |

The Conductor adds ~$2.40/month for 100 tasks. The efficiency gains (fewer retries, better agent assignment, targeted context) are expected to save 15-30% on total agent execution cost.

---

## 7. References

1. Nielsen, S., Cetin, E., Schwendeman, P., et al. "Learning to Orchestrate Agents in Natural Language with the Conductor." ICLR 2026. arXiv:2512.04388v5.
2. FDE Blueprint: Indice Mestre de Design e Implantacao (Parte 4: Orquestracao Avancada)
3. FDE Blueprint: O Mapa de Leitura do Engenheiro (Passo 3: Regras do Jogo)
4. ADR-019: Agentic Squad Architecture
5. docs/design/fde-core-brain-development.md (Wave 1: Distributed Infrastructure)
