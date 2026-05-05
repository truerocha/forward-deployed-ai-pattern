# Data Contract: Task Input for the Code Factory

> Status: Draft
> Date: 2026-05-04
> ADR: ADR-010 (pending)
> Scope: Defines the well-scoped input that all agents and flows consume

## 1. Problem Statement

The Code Factory receives work items from three ALM platforms (GitHub Projects, Asana, GitLab). Each platform has different field structures. The agents downstream (Reconnaissance, Engineering, Reporting) need a consistent, well-scoped input to operate without ambiguity.

Without a well-scoped input, agents guess at module boundaries, make assumptions about constraints, and don't know which ALM to update.

## 2. Data Contract Definition

### 2.1 Required Fields (Agent Cannot Start Without These)

| Field | Type | Description | Validated By |
|-------|------|-------------|-------------|
| `title` | string | One-line summary | DoR Gate |
| `description` | string (markdown) | Full description with acceptance criteria | DoR Gate |
| `type` | enum | `feature` / `bugfix` / `infrastructure` / `documentation` | Issue template |
| `priority` | enum | `P0` / `P1` / `P2` / `P3` | Issue template |
| `level` | enum | `L2` / `L3` / `L4` | Issue template |
| `source` | enum | `github` / `asana` / `gitlab` / `direct` | Router |
| `acceptance_criteria` | string[] | List of testable criteria | DoR Gate |
| `tech_stack` | string[] | Languages, frameworks, services involved | Issue template |

### 2.2 Optional Fields (Agent Uses If Present, Infers If Absent)

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `spec_path` | string | Path to existing spec file | Agent creates one |
| `depends_on` | string[] | Task IDs this task depends on | Empty |
| `repo` | string | `owner/repo` for code changes | Current workspace |
| `branch_strategy` | enum | `feature` / `hotfix` / `release` | `feature` |
| `target_environment` | string[] | `aws` / `azure` / `gcp` / `on-prem` | Inferred from tech_stack |
| `constraints` | string | What must NOT change | Empty |
| `related_docs` | string[] | Links to design docs, specs, ADRs | Empty |
| `estimated_complexity` | enum | `small` / `medium` / `large` | Inferred by Recon agent |

### 2.3 Agent-Populated Fields (Set During Execution)

| Field | Type | Set By | Description |
|-------|------|--------|-------------|
| `task_id` | string | Task Queue | TASK-xxxxxxxx |
| `status` | enum | Task Queue | PENDING/READY/IN_PROGRESS/COMPLETED/FAILED/BLOCKED |
| `assigned_agent` | string | Orchestrator | Which agent is working |
| `agent_instance_id` | string | Lifecycle Manager | AGENT-xxxxxxxx |
| `prompt_version` | int | Prompt Registry | Which prompt version was used |
| `prompt_hash` | string | Prompt Registry | SHA-256 of prompt content |
| `result` | string | Engineering Agent | Completion summary |
| `completion_report_s3` | string | Reporting Agent | S3 URI of full report |

## 3. Validation Rules

### 3.1 DoR Gate Validation

```
REQUIRED: title is not empty
REQUIRED: description is not empty
REQUIRED: type is one of [feature, bugfix, infrastructure, documentation]
REQUIRED: priority is one of [P0, P1, P2, P3]
REQUIRED: level is one of [L2, L3, L4]
REQUIRED: acceptance_criteria has at least 1 item
REQUIRED: tech_stack has at least 1 item
WARNING:  constraints is empty (agent will infer)
WARNING:  related_docs is empty (agent starts from scratch)
```

### 3.2 Task Queue Validation

```
REQUIRED: title is not empty
REQUIRED: source is one of [github, asana, gitlab, direct]
IF depends_on is not empty: all referenced task_ids must exist
IF priority is P0: task is placed at front of queue
```

## 4. Platform Mapping

### GitHub Issue Form → Data Contract

| Data Contract Field | GitHub Form Field | Type |
|---|---|---|
| title | Issue title | input |
| description | Description | textarea |
| type | Type dropdown | dropdown |
| priority | Priority dropdown | dropdown |
| level | Engineering Level dropdown | dropdown |
| acceptance_criteria | Acceptance Criteria | textarea (parsed as list) |
| tech_stack | Tech Stack | checkboxes |
| constraints | Constraints | textarea |
| related_docs | Related Documents | textarea |
| depends_on | Dependencies | input |
| target_environment | Target Environment | checkboxes |

### Asana Task → Data Contract

| Data Contract Field | Asana Field | Type |
|---|---|---|
| title | Task name | text |
| description | Task notes | text |
| type | Custom field "Type" | enum |
| priority | Custom field "Priority" | enum |
| level | Custom field "Engineering Level" | enum |
| acceptance_criteria | Subtasks or notes section | text |
| tech_stack | Custom field "Tech Stack" | multi-select |
| depends_on | Task dependencies | dependency |

### GitLab Issue → Data Contract

| Data Contract Field | GitLab Field | Type |
|---|---|---|
| title | Issue title | text |
| description | Issue description (template) | markdown |
| type | Scoped label `type::*` | label |
| priority | Scoped label `priority::*` | label |
| level | Scoped label `level::*` | label |
| acceptance_criteria | Description section | markdown |
| tech_stack | Labels `stack::*` | labels |
| depends_on | Related issues (blocks) | relation |

## 5. Agent Consumption Matrix

| Component | Reads | Writes |
|-----------|-------|--------|
| **Router** | source, type, full issue body | data_contract (all fields) |
| **Constraint Extractor** | constraints, related_docs, tech_stack | extracted constraints (CTR-xxx objects) |
| **DoR Gate** | extracted constraints, tech_stack | pass/fail + failures + warnings |
| **Agent Builder** | tech_stack, type, extracted constraints | specialized AgentDefinition (prompt + tools) |
| **Prompt Registry** | tech_stack (as context_tags) | prompt_version, prompt_hash |
| **Reconnaissance** | title, description, tech_stack, related_docs, injected constraints | estimated_complexity, spec_path |
| **Engineering** | All required + spec_path, injected constraints, acceptance_criteria | result, branch name |
| **Reporting** | task_id, source, result, acceptance_criteria | completion_report_s3, ALM update |
| **Task Queue** | task_id, status, depends_on, priority | status transitions |
| **Lifecycle Manager** | agent_instance_id, task_id | status transitions, execution_time_ms |

## 6. Pipeline Flow (InProgress Event)

```
EventBridge Event (InProgress)
  │
  ▼
Router.route_event()
  ├── Extracts data_contract from platform-specific payload
  ├── GitHub: parses issue form sections (### headers, checkboxes)
  ├── GitLab: reads scoped labels (type::, priority::, stack::)
  └── Asana: reads custom fields + notes sections
  │
  ▼
ConstraintExtractor.extract_and_validate(data_contract)
  ├── Pass 1: Rule-based extraction (regex, no LLM cost)
  │   └── Version pins, latency thresholds, auth mandates, exclusions
  ├── Pass 2: LLM-based extraction (Bedrock, catches nuanced constraints)
  ├── Merge + deduplicate (rule-based takes precedence)
  └── DoR Gate: validate constraints against tech_stack
  │
  ▼
DoR Gate Result
  ├── PASS → continue to Agent Builder
  └── FAIL → pipeline blocked, error reported to ALM
  │
  ▼
AgentBuilder.build_pipeline_agents(data_contract, extraction_result)
  ├── Resolves prompts from Prompt Registry (tech_stack as context_tags)
  ├── Falls back to base prompts if no Registry match
  ├── Injects extracted constraints block into agent prompts
  ├── Selects tool set based on task type
  └── Registers transient agent definitions (scoped to task_id)
  │
  ▼
Orchestrator._execute_pipeline([recon-TASK-xxx, eng-TASK-xxx, report-TASK-xxx])
  ├── Each stage passes output as context to the next
  └── Results written to S3, ALM updated
```

## 7. Open Questions

1. ~~Should the data contract be stored in DynamoDB (with the task) or as a separate S3 object?~~ **Resolved**: Stored in the RoutingDecision, persisted to S3 as part of the extraction report.
2. How do we handle tasks that span multiple repos?
3. Should the agent request clarification by commenting on the issue, or block and wait?
4. What is the maximum task size before decomposition into subtasks?
