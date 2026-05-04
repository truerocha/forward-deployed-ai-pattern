# Forward Deployed AI Engineers (FDEs) — A Design Pattern for Kiro

> Status: **playbook/runbook — reusable outside Cognitive WAFR scope**
> Date: 2026-04-24
> Origin: COE-052 post-mortem + research synthesis
> Applicability: Any enterprise-grade AI-assisted development with Kiro
> Naming: "Forward Deployed" reflects that the AI agent is deployed into the project's context — its pipeline, its knowledge architecture, its quality standards — not operating from generic training data.

---

## Table of Contents

- [1. Purpose and Scope](#1-purpose-and-scope)
- [2. Research Foundations](#2-research-foundations)
  - [2.1 GenAI for Software Architecture (Esposito et al., 2025)](#21-genai-for-software-architecture-esposito-et-al-2025)
  - [2.2 GenAI-Native Design Principles (Vandeputte et al., 2025)](#22-genai-native-design-principles-vandeputte-et-al-2025)
  - [2.3 Future of Development Environments (Shonan Meeting 222, 2025)](#23-future-of-development-environments-shonan-meeting-222-2025)
  - [2.4 Prompt Patterns in AI-Assisted Code Generation (DiCuffa et al., 2025)](#24-prompt-patterns-in-ai-assisted-code-generation-dicuffa-et-al-2025)
  - [2.5 Synthesis: What the Research Tells Us About AI-Assisted Engineering](#25-synthesis-what-the-research-tells-us-about-ai-assisted-engineering)
- [3. The Problem: Why Standard AI-Assisted Development Fails at Enterprise Grade](#3-the-problem-why-standard-ai-assisted-development-fails-at-enterprise-grade)
- [3.1 The Deeper Problem: The Agent as Code Writer vs Knowledge Worker](#31-the-deeper-problem-the-agent-as-code-writer-vs-knowledge-worker)
  - [Role 1: Code Writer](#role-1-code-writer--the-agent-changes-computational-logic)
  - [Role 2: Knowledge Worker](#role-2-knowledge-worker--the-agent-changes-domain-artifacts)
  - [The Four Recurring LLM Failure Patterns](#the-four-recurring-llm-failure-patterns-91-94)
  - [How This Changes the Protocol](#how-this-changes-the-protocol)
- [4. The Four-Phase Autonomous Engineering Protocol](#4-the-four-phase-autonomous-engineering-protocol)
  - [Phase 1: Reconnaissance and Setup](#phase-1-reconnaissance-and-setup)
  - [Phase 2: Task Intake — Structured Prompt Contract](#phase-2-task-intake--structured-prompt-contract)
  - [Phase 3: Multi-Turn Engineering — Recipe-Aware Iteration](#phase-3-multi-turn-engineering--recipe-aware-iteration)
  - [Phase 4: Completion and Reporting](#phase-4-completion-and-reporting)
- [5. Kiro Implementation: Steering, Hooks, and Activation](#5-kiro-implementation-steering-hooks-and-activation)
  - [5.1 Steering File (Phase 1 — Always-On Mindset)](#51-steering-file-phase-1--always-on-mindset)
  - [5.2 preToolUse Hook (Phase 3.a — Adversarial Gate)](#52-pretooluse-hook-phase-3a--adversarial-gate)
  - [5.3 postTaskExecution Hook (Phase 3.b-3.d + Phase 4)](#53-posttaskexecution-hook-phase-3b-3d--phase-4)
  - [5.4 Definition of Ready / Definition of Done — Task Quality Gates](#54-definition-of-ready--definition-of-done--task-quality-gates)
  - [5.5 Architecture Diagram Generation — Visual Validation of Changes](#55-architecture-diagram-generation--visual-validation-of-changes)
- [6. Engineering Level Classification](#6-engineering-level-classification)
- [7. Applying This Pattern to Other Projects](#7-applying-this-pattern-to-other-projects)
- [8. How to Use — Kiro IDE and Kiro CLI](#8-how-to-use--kiro-ide-and-kiro-cli)
  - [8.1 Artifact Inventory](#81-artifact-inventory)
  - [8.2 Activation — Kiro IDE](#82-activation--kiro-ide)
  - [8.3 Activation — Kiro CLI](#83-activation--kiro-cli)
  - [8.4 Operating Under the Protocol](#84-operating-under-the-protocol)
  - [8.5 Deactivation](#85-deactivation)
  - [8.6 Partial Activation (Engineering Levels)](#86-partial-activation-engineering-levels)
  - [8.7 Quick Reference Card](#87-quick-reference-card)
- [9. Empirical Validation — Bare vs FDE Quality Threshold](#9-empirical-validation--bare-vs-fde-quality-threshold)
- [10. References](#10-references)

---

## 1. Purpose and Scope

This document defines the **Forward Deployed AI Engineers (FDEs)** design pattern for enterprise-grade AI-assisted development using Kiro. The name reflects the core principle: the AI agent is **deployed into** the project's specific context — its pipeline architecture, its knowledge artifacts, its quality standards (régua), and its governance boundaries — rather than operating from generic training data.

An FDE is not a general-purpose coding assistant. It is an AI agent that has been forward-deployed into a specific workspace with:
- **System awareness** — it knows the pipeline chain, module boundaries, and data flow
- **Quality standards** — it measures against the project's régua, not its own judgment
- **Structured interaction** — it follows the Context + Instruction pattern, not ad-hoc questions
- **Recipe discipline** — it executes a predefined engineering sequence, carrying context across steps

The pattern addresses a fundamental gap in current AI-assisted development: **the agent optimizes for function correctness, not for pipeline correctness.** When the product is a data pipeline (input transforms through multiple stages to produce output), testing individual functions is necessary but not sufficient. The product-level invariant — "given this input, the output tells the right story" — must be tested end-to-end.

This pattern was derived from:
- A real post-mortem of 20 cascading fixes in a single session (COE-052)
- Three peer-reviewed research papers and one empirical study on GenAI in software engineering
- The operational experience of building a 10,000+ line evidence pipeline

The pattern is implemented through Kiro's activation mechanisms: **steering files** (always-on context), **preTaskExecution hooks** (readiness gates), **preToolUse hooks** (action gates), and **postTaskExecution hooks** (validation enforcement).

---

## 2. Research Foundations

Three research papers and one empirical study ground this pattern in the current state of the art. Each contributes a specific insight that shapes the protocol.

### 2.1 GenAI for Software Architecture (Esposito et al., 2025)

**Source**: Esposito, M., Palagiano, F., Lenarduzzi, V., Taibi, D. "Generative AI for Software Architecture: Applications, Challenges, and Future Directions." [arXiv:2503.13310v2](https://arxiv.org/abs/2503.13310v2). Journal of Systems and Software, 2025.

This multivocal literature review analyzed 46 studies (36 peer-reviewed, 10 gray literature) on GenAI applied to software architecture. Key findings relevant to this pattern:

**Finding 1: 85% of studies involve human interaction with the model.** GenAI in software architecture is used as an assistive tool, not an autonomous decision-maker. The research consensus is that fully autonomous AI-driven architectural decisions are not yet viable. This validates our protocol's emphasis on human-in-the-loop verification at every phase.

**Finding 2: 93% of studies lack formal validation of AI-generated architectural output.** The overwhelming majority of studies do not report how they validated the correctness of GenAI outputs. This mirrors our post-mortem finding: the test suite validates code structure, not product behavior. The absence of systematic validation is the norm, not the exception.

**Finding 3: Few-shot prompting (31%) is the dominant technique, but most studies (48%) don't report their model enhancement approach.** The field lacks standardized practices for how to structure AI interactions for architectural tasks. Our protocol fills this gap by defining a structured four-phase interaction model.

**Finding 4: GenAI is applied mostly to early SDLC phases (Requirements-to-Architecture 40%, Architecture-to-Code 32%).** The later phases — testing, validation, maintenance — are underserved. Our protocol explicitly addresses the validation and verification phases that the research shows are neglected.

**Finding 5: LLM accuracy (15%) and hallucinations (8%) are the top reported challenges.** The agent can produce structurally correct but semantically wrong output. Our adversarial multi-turn phase (3.a) directly addresses this by forcing the agent to challenge its own assumptions before committing code.

Content was rephrased for compliance with licensing restrictions. [Original source](https://arxiv.org/abs/2503.13310v2).

### 2.2 GenAI-Native Design Principles (Vandeputte et al., 2025)

**Source**: Vandeputte, F. et al. "Foundational Design Principles and Patterns for Building Robust and Adaptive GenAI-Native Systems." [arXiv:2508.15411](https://arxiv.org/abs/2508.15411). ACM Onward! '25, Singapore, 2025.

This paper proposes five foundational pillars for GenAI-native systems: **reliability, excellence, evolvability, self-reliance, and assurance.** It introduces architectural patterns including the GenAI-native cell, programmable router, and organic substrate. Key insights for our protocol:

**Principle 1: Design for fault-tolerance, not pass/fail.** Traditional software uses binary pass/fail criteria. GenAI-native systems should use "utility-based sufficiency criteria" — the output is sufficiently useful most of the time. This reframes how we evaluate AI-generated code: not "does it compile?" but "does the pipeline produce correct output for the user?"

**Principle 2: Include verification and mitigation at all levels.** The paper advocates for integrating verification throughout the software stack and lifecycle, not just at the unit test level. Dependent assets should not presume the reliability of upstream outputs. This directly supports our Phase 3.b requirement to test upstream and downstream in the data journey, not just the changed node.

**Principle 3: Minimize dependency on cognitive processing.** A foundational guideline is to systematically reduce reliance on open-ended GenAI processing in critical paths. The paper proposes a "programmable router" pattern that routes routine work through traditional logic and reserves cognitive processing for exceptional cases. Applied to our protocol: the agent should use deterministic verification (contract tests, schema checks, smoke tests) wherever possible, reserving judgment calls for genuinely ambiguous situations.

**Principle 4: Systematic quality verification and retrospectives.** The paper advocates for continuous learning and feedback loops at strategic points, drawing from Kaizen and Six Sigma methodologies. Our Phase 3.c (5W2H validation) and Phase 3.d (5 Whys for issues) are direct implementations of this principle — structured retrospective reasoning applied at the task level, not just at the sprint level.

**Principle 5: Promote consistency over creativity.** Unless required, GenAI-native systems should restrain creativity and prefer consistent, repeatable behavior. Applied to our protocol: the agent should match existing project conventions, not introduce novel patterns. The steering file enforces this by requiring the agent to read existing code before writing new code.

**Pattern: Reflective Processor.** The paper proposes that GenAI assets should include meta-cognition and self-regulation mechanisms — disambiguating the task before processing, triggering additional verification, and assessing the usefulness of results. Our Phase 3.a (adversarial multi-turn) implements this pattern: the agent challenges its own implementation before committing.

**Pattern: Continual Self-reflection.** Quality assurance mechanisms including feedback loops, auditing trails, and self-consistency checks. Our postTaskExecution hook implements this: after every task, the agent validates edge contracts, runs pipeline tests, and reports what was and wasn't verified.

Content was rephrased for compliance with licensing restrictions. [Original source](https://arxiv.org/abs/2508.15411).

### 2.3 Future of Development Environments (Shonan Meeting 222, 2025)

**Source**: Hu, X., Kula, R.G., Treude, C. "The Future of Development Environments with AI Foundation Models: NII Shonan Meeting 222 Report." [arXiv:2511.16092v1](https://arxiv.org/abs/2511.16092v1). November 2025.

This report summarizes discussions among 33 experts from Software Engineering, AI, and HCI on how GenAI will reshape IDEs. Key insights for our protocol:

**Insight 1: GenAI is evolution, not revolution.** Breakout Group 2 reached consensus that GenAI represents a continued evolution of SE tools, not a replacement of engineering discipline. The core tasks — design, coding, debugging, testing — remain unchanged; GenAI automates the mechanical aspects. This validates our protocol's position: the agent handles code generation, but the engineer drives scope, verification, and architectural decisions.

**Insight 2: Source code remains the deterministic artifact.** The group explicitly challenged the claim that "prompts are the new source code," noting that source code is the only representation that deterministically creates the same program every time. Until GenAI can prove isomorphic program equivalence, source code remains primary. Our protocol respects this: the agent writes source code, not prompts. The steering and hooks are governance mechanisms, not substitutes for code.

**Insight 3: Greenfield does not generalize to brownfield.** GenAI excels at generating new code but struggles with the complexity of established systems. Our protocol addresses this directly in Phase 1 (Reconnaissance): before writing any code, the agent must understand the existing system, its conventions, its data flow, and its test infrastructure.

**Insight 4: The IDE should be an adaptive cognitive companion.** Breakout Group 3 envisioned future IDEs as context-aware systems that adapt to the developer's persona, project context, and workflow. Kiro's steering files and hooks are an early implementation of this vision — they provide project-specific context and workflow enforcement that adapts the agent's behavior to the project's engineering standards.

**Insight 5: "All you need is another agent" is a misconception.** The experts noted that while agents automate specific tasks, fundamental uncertainty during software development necessitates human involvement for coordination. Our protocol embeds this: the agent works autonomously within phases but the human sets scope (Phase 2) and reviews output (Phase 4).

Content was rephrased for compliance with licensing restrictions. [Original source](https://arxiv.org/abs/2511.16092v1).

### 2.4 Prompt Patterns in AI-Assisted Code Generation (DiCuffa et al., 2025)

**Source**: DiCuffa, S., Zambrana, A., Yadav, P., Madiraju, S., Suman, K., AlOmar, E.A. "Exploring Prompt Patterns in AI-Assisted Code Generation: Towards Faster and More Effective Developer-AI Collaboration." [arXiv:2506.01604](https://arxiv.org/abs/2506.01604). Stevens Institute of Technology, 2025.

This empirical study analyzed 20,594 real developer-ChatGPT conversations from the DevGPT dataset, classifying seven distinct prompt patterns and measuring their effectiveness in reducing the number of interactions needed to reach a satisfactory outcome. The study provides the first large-scale empirical evidence for which prompt structures minimize iteration count while maximizing output quality.

#### 5W2H Analysis — What This Paper Tells Us

| Dimension | Answer |
|-----------|--------|
| **WHAT** | Empirical ranking of 7 prompt patterns by effectiveness and efficiency. "Context and Instruction" and "Recipe" patterns consistently outperform simple Question patterns. Structured prompts reduce iterations by 30-50% compared to unstructured questions. |
| **WHERE** | In the interaction layer between developer and AI — the prompt itself. This is the layer our protocol governs through steering files and hook prompts. |
| **WHEN** | At the moment of task intake (Phase 2) and at every agent-to-tool interaction (Phase 3.a). The prompt structure determines whether the first interaction produces a useful result or triggers a reactive fix cycle. |
| **WHO** | Developers using AI assistants for code generation, debugging, and architecture tasks. In our protocol, the "developer" is both the human engineer and the Kiro steering/hook system that structures the agent's interactions. |
| **WHY** | Because unstructured prompts (simple questions) require more iterations to reach satisfactory outcomes. The study quantifies what our COE-052 post-mortem observed qualitatively: vague task intake leads to cascading fixes. |
| **HOW** | By combining context (background information about the system) with specific instructions (what to do), developers reduce ambiguity. The "Context and Instruction" pattern achieved a score ratio of 12.10 (PR) and 13.58 (Issues) — the highest across both datasets. |
| **HOW MUCH** | The study analyzed 3,515 closed PRs and 5,261 closed Issues. The "Recipe" pattern required the fewest prompts on average (7.07 for PRs). The "Context and Instruction" pattern achieved the best balance of effectiveness and efficiency across both datasets. |

#### 5 Whys Analysis — Why This Matters for Our Protocol

**Symptom**: Developers require multiple iterations with AI assistants to achieve satisfactory code output, even for well-understood tasks.

1. **Why do developers need multiple iterations?** Because the initial prompt lacks sufficient structure to guide the AI toward the correct output on the first attempt.

2. **Why does the initial prompt lack structure?** Because developers default to the simplest interaction pattern — asking a question — without providing the context, constraints, and output format the AI needs to produce a precise answer.

3. **Why do developers default to simple questions?** Because there is no systematic framework that maps task types to optimal prompt structures. The developer's intuition ("just ask") is the default, and it is suboptimal.

4. **Why is there no systematic framework?** Because prior research focused on prompt engineering as a manual skill, not as an automatable engineering discipline. The insight that prompt structure can be codified into reusable patterns — and that these patterns have measurable, statistically significant differences in effectiveness (ANOVA F=27.04, p<10⁻³²) — is new empirical evidence.

5. **Root cause**: The interaction between developer and AI lacks a **structural contract** — a predefined pattern that encodes context, instructions, and output format before the AI begins processing. Without this contract, every interaction starts from zero context, and the AI must infer what the developer wants through iterative clarification.

**How our protocol addresses this root cause**: The FDE protocol already implements the two most effective patterns identified by DiCuffa et al., but through a different mechanism — **automation rather than manual prompt crafting**:

| DiCuffa Pattern | Protocol Equivalent | How It's Automated |
|---|---|---|
| **Context and Instruction** | Steering file (§5.1) + DoR gate (§5.4) | The steering provides system context (pipeline chain, module boundaries, knowledge architecture). The DoR gate provides task-specific instructions (applicable standards, acceptance criteria). Together, they form a "Context and Instruction" prompt that the agent receives before every task — without the developer having to craft it manually. |
| **Recipe** | Phase 1→2→3→4 protocol + postTaskExecution hook (§5.3) | The four-phase protocol is a recipe: reconnaissance → intake → multi-turn engineering → completion. The postTaskExecution hook enforces the recipe's validation steps (contract tests → edge validation → 5W2H → 5 Whys → report). The developer doesn't write the recipe — the protocol encodes it. |
| **Template** | 5W2H template (Phase 3.c) + DoD compliance matrix (§5.4) | The 5W2H and compliance matrix are output templates that the agent fills in. They standardize the agent's reasoning output, making it reviewable and comparable across tasks. |
| **Output Automator** | preToolUse hook (§5.2) + postTaskExecution hook (§5.3) | The hooks automate output structure: the adversarial gate produces a structured 7-question checklist before every write; the pipeline validation produces a structured completion report after every task. |
| **Persona** | Steering file preamble | "You are operating as a Forward Deployed AI Engineer (FDE)" — the steering assigns the agent a persona with specific engineering standards, anti-patterns to avoid, and a defined pipeline to protect. |

#### Key Findings Relevant to Our Protocol

**Finding 1: "Context and Instruction" is the most efficient pattern across both datasets.** This validates our steering file design (§5.1): the steering provides context (pipeline chain, module boundaries, knowledge architecture) and the hooks provide instructions (adversarial questions, validation steps). The combination is not accidental — it maps directly to the empirically most effective prompt pattern.

**Finding 2: Simple Question patterns require the most iterations.** This explains why the reactive cycle (§3, Failure Mode 4) produces cascading fixes: each interaction is a simple question ("fix this bug") without the context and instruction structure that would guide the agent toward a correct first attempt. The protocol's Phase 1 (reconnaissance) exists precisely to prevent this — by loading context before the agent sees the task.

**Finding 3: The "Recipe" pattern achieves the highest effectiveness score (102.64) with the fewest prompts (7.07).** This validates our four-phase protocol structure: a predefined sequence of steps (reconnaissance → intake → engineering → completion) that the agent follows for every task. The protocol is a recipe that the developer activates, not a question they ask.

**Finding 4: Structured patterns show statistically significant differences in effectiveness (ANOVA p<10⁻³²).** This is not a marginal improvement — the difference between structured and unstructured prompts is highly significant. This provides empirical justification for the protocol's overhead: the steering files, hooks, and DoR/DoD gates add complexity, but the evidence shows that this structure produces measurably better outcomes with fewer iterations.

**Finding 5: Pattern effectiveness varies by task type (PRs vs Issues).** "Recipe" excels for PRs (structured, multi-step tasks), while "Context and Instruction" excels for Issues (problem-solving with context). This maps to our engineering level classification (§6): L3-L4 tasks (cross-module, architectural) benefit from the full recipe (all four hooks), while L2 tasks (targeted fixes) benefit from context + instruction (steering + adversarial gate only).

Content was rephrased for compliance with licensing restrictions. [Original source](https://arxiv.org/abs/2506.01604).

### 2.5 Synthesis: What the Research Tells Us About AI-Assisted Engineering

The four papers converge on six principles that directly shape this protocol:

| Principle | Esposito et al. | Vandeputte et al. | Shonan 222 | DiCuffa et al. | Protocol Phase |
|---|---|---|---|---|---|
| **Human oversight is non-negotiable** | 85% of studies use human interaction | Balance autonomy with safety and control | Human coordination remains essential | Developers guide AI through structured prompts, not delegation | Phase 1.b (acknowledge), Phase 4 (report) |
| **Validation is the weakest link** | 93% lack formal validation | Verification at all levels, not just unit tests | Source code remains the deterministic artifact | Effectiveness measured by closed outcomes, not just generated code | Phase 3.b (pipeline testing), Phase 3.c (5W2H), DoD gate (§5.4) |
| **Consistency over creativity** | Few-shot prompting dominates (structured input) | Promote consistency over creativity | Evolution, not revolution | Structured patterns outperform unstructured by statistically significant margins | Phase 1 (read before write), Steering (match conventions) |
| **Fault-tolerance, not pass/fail** | Accuracy and hallucinations are top challenges | Utility-based sufficiency criteria | Greenfield doesn't generalize to brownfield | "Context and Instruction" reduces ambiguity that causes hallucination | Phase 3.a (adversarial challenge) |
| **Systematic retrospectives** | Absence of evaluation frameworks is a key gap | Kaizen and Six Sigma for GenAI quality | Prompt-as-documentation for traceability | Template and Recipe patterns standardize output for review | Phase 3.c (5W2H), Phase 3.d (5 Whys) |
| **Structure reduces iteration** | — | Minimize dependency on cognitive processing | — | Structured prompts reduce iterations by 30-50% vs simple questions (p<10⁻³²) | Steering (context), Hooks (instruction), DoR/DoD (template) |

---

## 3. The Problem: Why Standard AI-Assisted Development Fails at Enterprise Grade

Standard AI-assisted development follows a reactive cycle:

```
User reports symptom → Agent traces cause → Agent fixes code
→ Agent runs tests → Tests pass → Agent declares done
→ User finds next gap → Repeat
```

This cycle produces locally correct fixes that cascade into system-level failures. The COE-052 post-mortem documented 20 sub-fixes in one session, where each fix created the conditions for the next bug. The root cause analysis (5 Whys) identified five failure modes:

| # | Failure Mode | Research Grounding |
|---|---|---|
| 1 | Agent reads only the function being fixed, not its consumers | Vandeputte: "dependent assets should not presume reliability of upstream outputs" |
| 2 | Verification scope matches fix scope, not impact scope | Esposito: 93% of studies lack formal validation of AI outputs |
| 3 | No product-level acceptance test exists | Vandeputte: "verification and mitigation at all levels" |
| 4 | Each interaction is treated as independent | Shonan: IDE should be context-aware cognitive companion |
| 5 | Fixes target the symptom instance, not the bug class | Vandeputte: "systematic quality verification and retrospectives" |

The root cause, stated as a design principle:

> **Pipeline products require pipeline tests.**
> When the product is a data pipeline, testing individual transforms is necessary but not sufficient.
> The product-level invariant is: "given this input, the output tells the right story."
> That invariant must be tested end-to-end, not inferred from node-level correctness.

---

## 3.1 The Deeper Problem: The Agent as Code Writer vs Knowledge Worker

Section 3 frames the problem as a pipeline testing gap: the agent tests nodes, not edges. But the COE-052 post-mortem (deep-cognitive-analysis.md §9) reveals a deeper structural problem that pipeline testing alone cannot solve. The agent operates in **two roles simultaneously**, and the protocol must govern both.

### Role 1: Code Writer — The Agent Changes Computational Logic

This is the role the protocol already addresses. The agent modifies functions, fixes bugs, adds features. The verification strategy is structural: does the output match the consumer's expected schema? Do contract tests pass? Does the pipeline produce correct output?

### Role 2: Knowledge Worker — The Agent Changes Domain Artifacts

This is the role the protocol misses. In many enterprise systems, the critical quality problems are not in the code — they are in the **configuration data** that encodes domain knowledge:

- Mapping files that route evidence to framework questions
- Template files that generate recommendations
- Addressability configs that calibrate severity
- Regex patterns that determine what gets detected
- Threshold rules that distinguish "good" from "needs improvement"

These are **knowledge artifacts**, not code artifacts. They require a fundamentally different verification strategy: not "does it compile?" but "is this semantically correct within the domain?"

### The Four Recurring LLM Failure Patterns (§9.1–9.4)

The COE-052 post-mortem identified four failure patterns that emerge specifically when the agent operates as a knowledge worker without knowing it:

**Pattern 1: The Reactive Fix Cycle (§9.1)**

```
User reports symptom → Agent traces to code-level cause
→ Agent fixes code → Tests pass → Agent declares done
→ User tests with different workload → New symptom appears
→ Repeat
```

The agent optimizes for **passing the test suite**, not for **product correctness**. The test suite validates code structure. It does not validate product behavior. Every fix was locally correct but scoped to the reported symptom, not to the class of problem.

**What the protocol must add:** The agent cannot intuit what the user will test next. But it can ask: "What other workloads, inputs, or scenarios would exercise the code I just changed?" This is **anticipatory verification** — testing not just what changed, but what the user will exercise next. Phase 3.a (adversarial multi-turn) partially addresses this with "What input would break this fix?" but it must be extended to include "What other workload would reveal a sibling bug?"

**Pattern 2: Architecture-Unaware Symptom Fixing (§9.2, Problem 1)**

The agent fixes the symptom within the current architecture. It never asks: "Is the architecture right, or am I patching a wrong design?"

When the user said "findings are all MEDIUM severity," the agent traced to the severity map and patched it. The right question was: "Why is the severity map flat? Is a flat map the right architecture, or should severity come from a different source entirely?" That question would have led to the FCM risk engine and BP addressability — one architectural change instead of 20 symptom patches.

**What the protocol must add:** Phase 3.a must include an **architectural challenge**: "Can the current architecture support this fix correctly, or is the architecture itself the problem? If I'm patching the same area for the third time, the architecture is wrong."

**Pattern 3: Domain Knowledge Gaps (§9.2, Problems 2 and 3)**

The agent doesn't carry domain knowledge across sessions. It builds mappings that are structurally correct (fact type → question) but semantically imprecise (the wrong question for the evidence). A domain expert would know that REL 4 ("prevent failures") and REL 5 ("mitigate failures") require different evidence. The agent maps both to `timeout_config` because the regex matches.

The agent also treats knowledge artifacts as code. It writes a YAML mapping entry the same way it writes a Python function — structurally. But a YAML mapping that routes `timeout_config` to the wrong WAF question is not a syntax error. It's a **domain error** that no test suite will catch unless the test encodes the domain knowledge the agent lacks.

**What the protocol must add:**

1. **Domain knowledge grounding in Phase 1.** During reconnaissance, the agent must identify not just the pipeline modules but also the **knowledge sources** — where does domain knowledge live? What is the single source of truth? If knowledge is scattered (§9.3: "10+ files in 5+ formats"), the agent must flag this as a risk before making changes.

2. **Code vs knowledge artifact distinction in Phase 3.a.** The preToolUse hook must ask a different question for knowledge artifacts: not "have you read the downstream consumer?" but "have you validated this change against the domain source of truth? Is this mapping semantically correct, or just structurally valid?"

3. **Domain validation in Phase 3.b.** Pipeline testing for knowledge artifacts means: "Does this mapping produce the correct domain outcome?" — not just "Does the downstream module accept this input?" A mapping that routes `timeout_config` to REL 4 instead of REL 5 will pass every contract test but produce wrong findings.

**Pattern 4: Stateless Pipeline Limitations (§9.4)**

The pipeline can't reason (detecting presence ≠ evaluating quality), can't consolidate (file-level findings ≠ component-level insights), and can't learn (each run starts from scratch). These are architectural limitations, not code bugs.

**What the protocol must add:** Phase 1 reconnaissance must identify which pipeline limitations are relevant to the current task. If the task involves severity calibration, the agent must know that the pipeline detects presence but not quality — and that any severity change requires domain-level reasoning, not just code-level changes. If the task involves finding consolidation, the agent must know that the pipeline groups by file, not by component — and that consolidation requires connecting to the code graph, not just merging findings.

### How This Changes the Protocol

The four patterns require three additions to the protocol:

**Addition 1: Knowledge Architecture Awareness (Phase 1)**

During reconnaissance, the agent must map not just the computational pipeline but also the **knowledge architecture**:
- Where does domain knowledge live? (single source of truth, or scattered?)
- Which artifacts are code (functions, classes, modules) and which are knowledge (mappings, templates, configs, thresholds)?
- What is the domain validation strategy for knowledge artifacts? (Who or what confirms semantic correctness?)

**Addition 2: Dual Verification Strategy (Phase 3.a and 3.b)**

The preToolUse hook and pipeline testing must distinguish between two artifact types:

| Aspect | Code Artifact | Knowledge Artifact |
|---|---|---|
| **Verification question** | Does the output match the consumer's schema? | Is this semantically correct within the domain? |
| **Test strategy** | Contract tests, schema validation, integration tests | Domain validation against source of truth, cross-reference with framework documentation |
| **Failure mode** | Structural — wrong type, missing field, broken contract | Semantic — correct structure, wrong meaning |
| **preToolUse question** | "Have you read the downstream consumer?" | "Have you validated against the domain source of truth?" |
| **Example** | Function returns wrong shape → contract test catches it | Mapping routes evidence to wrong question → no test catches it |

**Addition 3: Architectural Challenge Escalation (Phase 3.a)**

When the agent encounters the same area for the third time in a session, or when a fix requires patching multiple scattered locations, the adversarial challenge must escalate from "is this the right fix?" to "is this the right architecture?":

- Am I patching the same module/area repeatedly? → The architecture may be wrong.
- Is domain knowledge scattered across multiple files? → A unified knowledge source may be needed.
- Does the pipeline detect presence but not quality? → A reasoning or threshold layer may be needed.
- Does the pipeline group by file but the user thinks in components? → A consolidation layer may be needed.

These are not code fixes. They are **architectural decisions** that the agent should surface to the engineer (Phase 4) rather than attempt to resolve through incremental patches.

### Research Grounding for These Additions

| Addition | Vandeputte et al. | Esposito et al. | Shonan 222 | DiCuffa et al. |
|---|---|---|---|---|
| Knowledge architecture awareness | "Collective competency ecosystems" — share knowledge efficiently across assets | "Lack of architecture-specific datasets" — domain knowledge is the missing ingredient | "Prompt-as-documentation" — capture reasoning and domain context | "Context and Instruction" pattern — providing domain context in the prompt reduces iterations and improves output quality |
| Dual verification strategy | "Utility-based sufficiency criteria" — different quality standards for different asset types | "93% lack formal validation" — the gap is specifically in semantic validation, not structural | "Source code remains deterministic" — but knowledge artifacts are not deterministic | "Recipe" pattern — step-by-step verification sequences produce higher effectiveness scores than ad-hoc validation |
| Architectural challenge escalation | "Evolve towards reliable and efficient systems" — monitor bespoke behaviors and evolve architecture | "GenAI applied mostly to early SDLC phases" — architectural reasoning is underserved | "Greenfield doesn't generalize to brownfield" — existing architecture constrains what the agent can do | Structured patterns reduce iteration count — escalating to architecture review early prevents the cascading fix cycle that unstructured interactions produce |

---

## 4. The Four-Phase Autonomous Engineering Protocol

```
Phase 1: RECONNAISSANCE & SETUP ──── Before any code
  ├── 1.   Understand environment, tooling, autonomous capabilities
  ├── 1.a  Set up environment and pre-reqs
  └── 1.b  Acknowledge pre-reqs, dependencies, and impact

Phase 2: TASK INTAKE (Structured) ─── The specification
  ├── 2.1  Map task to system understanding from Phase 1
  └── 2.2  Reformulate intake as Context + Instruction contract

Phase 3: MULTI-TURN ENGINEERING ───── The work (Recipe)
  ├── 3.   Multi-turn code solving (recipe-aware, context-carrying)
  ├── 3.a  Adversarial multi-turn: challenge implementation
  ├── 3.b  Pipeline testing: contract + upstream/downstream
  ├── 3.c  5W2H reasoning: validate against all guidance
  └── 3.d  5 Whys for issues: root cause → future-proof fix

Phase 4: COMPLETION ───────────────── Inform the user
  └── 4.   Finish and report what was delivered and validated
```

### Phase 1: Reconnaissance and Setup

**Research grounding**: Esposito et al. found that GenAI is applied mostly to early SDLC phases, with later phases underserved. Shonan Meeting 222 noted that greenfield approaches don't generalize to brownfield. Vandeputte et al. advocate for understanding the system before acting.

**What the agent does before writing any code:**

**1. Understand the environment.** Identify which modules in the system are affected by the task. Read the data flow and locate the task's position in it. Identify upstream producers and downstream consumers of each affected module. Check available tooling: test runners, linters, build commands, smoke tests.

Additionally, map the **knowledge architecture** (§3.1, Addition 1):
- Which artifacts are **code** (functions, classes, modules) and which are **knowledge** (mappings, templates, configs, thresholds, regex patterns)?
- Where does domain knowledge live? Is there a single source of truth, or is it scattered?
- What is the domain validation strategy for knowledge artifacts? Who or what confirms semantic correctness?

**1.a Set up pre-reqs.** Verify the development environment can run the affected tests. Confirm test data (fixtures, sample inputs) exists for validation. Identify which test scopes cover the affected modules. If pre-reqs are missing, set them up or flag them to the user.

**1.b Acknowledge dependencies and impact.** Before proceeding to implementation, state explicitly:
- **AFFECTED MODULES**: which files will change
- **ARTIFACT TYPE**: code artifact or knowledge artifact (§3.1) — this determines the verification strategy
- **UPSTREAM DEPENDENCY**: what feeds data into these modules
- **DOWNSTREAM IMPACT**: what consumes the output of these modules
- **DOMAIN SOURCE OF TRUTH**: for knowledge artifacts, what is the authoritative reference? (framework docs, corpus files, official specifications)
- **RISK**: what breaks if the change is wrong — structural risk (contract violation) or semantic risk (correct structure, wrong meaning)?
- **TEST COVERAGE**: which existing tests validate the affected edges, and do they cover semantic correctness or only structural correctness?

This acknowledgment serves as a contract between the agent and the engineer. If the agent cannot state the impact, it hasn't understood the system well enough to change it. If the agent cannot identify the domain source of truth for a knowledge artifact, it should flag this gap before proceeding.

### Phase 2: Task Intake — Structured Prompt Contract

**Research grounding**: DiCuffa et al.'s empirical finding that "Context and Instruction" is the most efficient prompt pattern (score ratio 12.10 PR, 13.58 Issues), while "Simple Question" requires the most iterations. The COE-052 post-mortem's Failure Mode 4: each interaction treated as independent, without accumulated context.

The task specification arrives in any format — a user prompt, a spec task, a bug report, a feature request. **The protocol does not prescribe the input format, but it prescribes that the agent must reformulate the intake into a structured prompt contract before beginning implementation.**

This is the critical refinement: the raw intake (often a "Simple Question" pattern — "fix the severity bug") must be transformed into a "Context and Instruction" pattern before the agent writes any code. The DoR gate (§5.4) enforces this transformation.

**Step 2.1: Map the task to the system understanding from Phase 1:**
- Which modules does this task touch?
- Which edges in the data flow are affected?
- What is the expected change in pipeline output?
- What artifact type is involved — code artifact or knowledge artifact? (§3.1)

**Step 2.2: Reformulate the intake as a Context + Instruction prompt contract:**

| Component | What It Contains | Source |
|-----------|-----------------|--------|
| **Context** | Pipeline chain position (which edges), module boundaries, upstream/downstream dependencies, knowledge architecture (if knowledge artifact), applicable quality standards from the régua (§5.4) | Phase 1 reconnaissance + steering file + DoR gate |
| **Instruction** | What specifically needs to change, what the acceptance criteria are, what "done" looks like according to the régua, what test scopes must pass | Task description + DoR gate acceptance criteria |
| **Constraints** | What must NOT change (governance boundaries, existing contracts, upstream interfaces), what is out of scope | Phase 1.b acknowledgment |

**Why this matters**: DiCuffa et al. showed that the difference between structured and unstructured prompts is statistically significant (ANOVA p<10⁻³²). By reformulating every intake — regardless of how the user phrased it — into the empirically most effective pattern, the protocol prevents the cascading fix cycle at its origin. The agent doesn't start from a vague question; it starts from a structured contract that includes system context, specific instructions, and explicit constraints.

**Example transformation:**

```
RAW INTAKE (Simple Question pattern):
  "Fix the severity distribution — findings are all MEDIUM"

REFORMULATED (Context + Instruction pattern):
  CONTEXT: Severity is assigned in publish_tree.py via _FACT_CLASS_SEVERITY
  (flat map) and refined by the FCM risk engine via BP addressability scores
  in evidence_bp_addressability.yaml. The pipeline edge E4 (publish_tree →
  publish_sanitizer) carries severity-scored findings. Downstream, the portal
  renders severity in the strip chart and Eisenhower matrix.

  INSTRUCTION: Investigate why severity distribution is flat (all MEDIUM).
  Determine whether the root cause is in the flat severity map, the BP
  addressability config, or the risk engine logic. The fix must produce
  a non-flat distribution (>1 severity level) validated by contract tests
  (--scope contract) and visual inspection of the portal strip chart.

  CONSTRAINTS: Do not modify the portal renderers (E6). Do not change
  the evidence_catalog interface (E2). The WAF corpus files are the
  domain source of truth for severity calibration.
```

The reformulated version gives the agent everything it needs to produce a correct first attempt — or at minimum, to ask the right clarifying questions instead of guessing.

### Phase 3: Multi-Turn Engineering — Recipe-Aware Iteration

**Research grounding**: Vandeputte et al.'s Reflective Processor pattern (meta-cognition before action), Continual Self-reflection pattern (quality assurance after action), and the principle of minimizing dependency on cognitive processing (use deterministic verification where possible). Esposito et al.'s finding that accuracy and hallucinations are the top challenges. Shonan Meeting 222's consensus that human coordination remains essential for complex tasks. DiCuffa et al.'s finding that the "Recipe" pattern achieves the highest effectiveness score (102.64) with the fewest prompts (7.07) — a predefined sequence of steps outperforms ad-hoc iteration.

**The Recipe Principle**: Phase 3 is not a free-form multi-turn conversation. It is a **recipe** — a predefined sequence of steps (3 → 3.a → 3.b → 3.c → 3.d) where each step builds on the output of the previous one. The agent must carry forward the accumulated context from all previous steps, not treat each step as an independent interaction.

This addresses the COE-052 root cause directly: the cascading fix cycle happened because each turn was treated as a fresh problem (the "Simple Question" anti-pattern). In the recipe model, each turn is a **step in a known sequence**, and the agent knows what step it's on, what came before, and what comes next.

**Recipe state tracking**: At each step, the agent maintains awareness of:
- **Current step**: Which phase (3, 3.a, 3.b, 3.c, 3.d) is active
- **Accumulated context**: What was discovered in previous steps (modules affected, artifact types, domain sources of truth, fixes applied)
- **Remaining steps**: What validation and reporting still needs to happen
- **Intake contract**: The structured Context + Instruction from Phase 2 — this is the reference point for every step, not the raw user prompt

**3. Multi-turn code solving.** The agent writes code in iterative turns, considering the Phase 1 context and the Phase 2 intake contract at every step. Each turn produces a working increment that can be tested. The agent does not write the entire solution in one pass — it builds incrementally, validating at each step.

When multiple turns are needed within this step, each turn must reference the intake contract (Phase 2) and the accumulated context from previous turns. The agent must not regress to the "Simple Question" pattern — each turn is a refinement within the recipe, not a new problem.

**3.a Adversarial multi-turn.** After writing a solution, the agent challenges it:
- What assumption does this fix rely on?
- What input would break this fix?
- Does this fix address the bug **class** or just this **instance**?
- Are there parallel code paths with the same vulnerability?
- What happens to downstream consumers when this change is applied?
- **What other workload or scenario would reveal a sibling bug?** (anticipatory verification — §3.1, Pattern 1)

For **knowledge artifacts** (mappings, templates, configs), add domain-specific challenges (§3.1, Addition 2):
- Is this change semantically correct within the domain, or just structurally valid?
- Have I validated against the domain source of truth (framework docs, corpus, official specs)?
- Would a domain expert agree with this mapping/template/threshold, or did I infer it from pattern matching?

**Architectural challenge escalation** (§3.1, Addition 3): If the agent is patching the same area for the third time, or if the fix requires changes in multiple scattered locations, escalate:
- Am I patching a wrong design instead of fixing a bug?
- Is domain knowledge scattered when it should be unified?
- Does the pipeline lack a capability (reasoning, consolidation, memory) that this fix is trying to work around?
- Should I surface this as an architectural decision to the engineer rather than attempting another incremental patch?

This is the Reflective Processor pattern applied to development: disambiguate, verify, and assess before committing. The agent acts as its own adversary, attempting to find the failure mode before the user does.

**3.b Pipeline testing (data journey).** Test not just the changed node, but the data journey through the pipeline:
- **CONTRACT**: Does the output match the consumer's expected schema?
- **UPSTREAM**: Does the change handle all variations the producer emits?
- **DOWNSTREAM**: Does the next module produce correct output with this change?
- **PRODUCT**: If a smoke test exists, run it. If not, state explicitly: "No product-level smoke test exists — pipeline output was not validated end-to-end."

For **knowledge artifacts**, apply the dual verification strategy (§3.1, Addition 2):
- **DOMAIN**: Does this mapping/template/config produce the correct domain outcome? A mapping that routes evidence to the wrong framework question will pass every contract test but produce wrong findings.
- **SEMANTIC CROSS-CHECK**: Can the change be validated against the domain source of truth? If the project has a corpus, official docs, or framework specification, check the change against it.
- **COVERAGE**: Does the change affect all instances of the pattern, or just the reported one? (e.g., fixing one fact type's WAF mapping without checking the other 52)

This implements Vandeputte et al.'s principle of "verification and mitigation at all levels." The agent tests at the edge (module boundary) for code artifacts, and at the domain boundary (semantic correctness) for knowledge artifacts.

**3.c 5W2H reasoning.** For the delivered task, reason through:
- **WHAT** was changed and what does it produce?
- **WHERE** in the pipeline does this change sit?
- **WHEN** does this change take effect (build time, runtime, publish time)?
- **WHO** is affected (which modes, which users, which downstream systems)?
- **WHY** was this the right approach vs alternatives?
- **HOW** was it validated?
- **HOW MUCH** of the pipeline was tested?

This implements Vandeputte et al.'s Systematic Quality Verification principle. The 5W2H is not a checklist to fill out — it's a reasoning framework that forces the agent to justify the change against the full system context.

**3.d 5 Whys for issues.** When an issue is found during development:
1. State the symptom
2. Ask Why 5 times to reach the root cause
3. Plan the fix at the root cause level
4. Design the fix considering upstream/downstream impact
5. Test the fix at the pipeline level, not just the node level
6. Apply the fix in a future-proof manner — does this prevent the entire **class** of bug, not just this instance?

This implements the post-mortem's core lesson: fix the class, not the instance. The 5 Whys prevents the cascading fix pattern where each symptom-level fix creates the next bug.

### Phase 4: Completion and Reporting

**Research grounding**: Shonan Meeting 222's concept of "prompt-as-documentation" — capturing reasoning, alternatives, and decisions as part of the project record. Vandeputte et al.'s Comprehensive Logging and Introspectability pattern.

The agent reports to the user:
- **What was delivered**: the concrete changes made
- **What was validated**: which tests passed, which pipeline edges were verified
- **What was NOT validated**: which parts of the pipeline could not be tested, and why
- **Residual risks**: any known gaps, edge cases, or follow-up items
- **5W2H summary**: the structured reasoning for the change

This report serves as the task's documentation. It captures not just what changed, but why it changed, how it was validated, and what remains unverified.

---

## 5. Kiro Implementation: Steering, Hooks, and Activation

The four-phase protocol maps to Kiro's three activation mechanisms. Each mechanism covers a different moment in the interaction lifecycle.

```
PROMPT ARRIVES
  │
  ▼
┌─────────────────────────────────────────┐
│  Steering File (always-on)              │  ← Phase 1: Loaded before the
│  Sets the mindset and protocol.         │     agent thinks. Defines the
│  Defines pipeline awareness,            │     reconnaissance protocol and
│  module boundaries, anti-patterns.      │     engineering standards.
└─────────────────────────────────────────┘
  │
  Agent reads code, plans the fix
  │
  ▼
┌─────────────────────────────────────────┐
│  preToolUse Hook (write operations)     │  ← Phase 3.a: Fires at the
│  Gates every write with adversarial     │     moment of action. Forces
│  questions: downstream consumers?       │     the agent to justify the
│  parallel paths? root cause?            │     change before making it.
└─────────────────────────────────────────┘
  │
  Agent writes the fix, runs tests
  │
  ▼
┌─────────────────────────────────────────┐
│  postTaskExecution Hook                 │  ← Phase 3.b-3.d + Phase 4:
│  Enforces pipeline testing, 5W2H       │     Fires after task completion.
│  validation, 5 Whys for issues,        │     Forces pipeline-level
│  and structured completion report.      │     validation and reporting.
└─────────────────────────────────────────┘
```

### 5.1 Steering File (Phase 1 — Always-On Mindset)

The steering file loads into every agent interaction. It encodes the Phase 1 reconnaissance protocol and the Phase 3 engineering standards as standing instructions.

**What it contains:**
- The pipeline chain for the specific project (module A → module B → module C → output)
- The key module boundaries where bugs live (edge contracts)
- The Phase 1 protocol: understand environment, set up pre-reqs, acknowledge impact
- The Phase 3 standards: adversarial challenge, pipeline testing, 5W2H, 5 Whys
- Anti-patterns to avoid: symptom chasing, node-scoped verification, independent interaction assumption

**Why always-on:** The steering sets the agent's mindset before it sees the task. Without it, the agent defaults to the reactive cycle (symptom → trace → fix → test → done). With it, the agent starts from system understanding and works toward a validated change.

**Adaptation for other projects:** Replace the pipeline chain and module boundaries with the specific project's architecture. The protocol phases and anti-patterns are universal.

### 5.2 preToolUse Hook (Phase 3.a — Adversarial Gate)

The preToolUse hook fires before every write operation. It forces the agent to answer adversarial questions before committing a change.

**What it asks:**
1. Have you completed Phase 1.b (stated affected modules, artifact type, upstream dependency, downstream impact, risk)?
2. Have you read at least one downstream consumer of the function you are modifying?
3. Have you searched for the same pattern in parallel code paths?
4. Is this change addressing the root cause or the reported symptom?
5. What input or scenario would break this change?
6. **For knowledge artifacts**: Have you validated this change against the domain source of truth? Is this semantically correct, or just structurally valid? (§3.1, Addition 2)
7. **Architectural escalation**: Am I patching the same area again? If so, is the architecture wrong? (§3.1, Addition 3)

**Why preToolUse on write:** This is the moment of highest leverage — the agent is about to change the system. If the agent hasn't read the downstream consumer, it will discover the impact after the change, not before. The hook forces discovery before action.

**Scope consideration:** For projects with non-pipeline files (docs, configs, tests), the hook can be scoped to specific file patterns using `toolTypes` regex. For maximum coverage, keep it on all writes and let the agent self-assess relevance.

### 5.3 postTaskExecution Hook (Phase 3.b-3.d + Phase 4)

The postTaskExecution hook fires after completing a spec task. It enforces pipeline-level validation and structured reporting.

**What it enforces:**

**Phase 3.b — Pipeline Testing:**
- CONTRACT: Does the output of changed modules match what downstream consumers expect?
- UPSTREAM: Were all input variations from the producer tested?
- DOWNSTREAM: Does the next module produce correct output with this change?
- PRODUCT: Run the product smoke test if it exists. If not, state the gap.

**Phase 3.c — 5W2H Validation:**
- WHAT, WHERE, WHEN, WHO, WHY, HOW, HOW MUCH — for the delivered task.

**Phase 3.d — 5 Whys (if issues were found):**
- For each issue encountered, apply 5 Whys to the root cause.
- Confirm the fix addresses the root cause, not the symptom.
- Confirm the fix prevents the bug class, not just this instance.

**Phase 4 — Completion Report:**
- What was delivered, what was validated, what was NOT validated, residual risks.

**Why postTaskExecution:** This fires at the natural completion boundary — when the agent believes the task is done. It's the last gate before the user sees the result. Without it, the agent declares "done" based on node-level tests, and the user discovers the pipeline-level failure.

### 5.4 Definition of Ready / Definition of Done — Task Quality Gates

Sections 5.2 and 5.3 gate the **action** (write) and the **completion** (task done). But they do not gate the **start** — the moment the agent begins working on a task. Without a start gate, the agent can begin implementation before it has sufficient context, leading to the reactive fix cycle described in §3.1 Pattern 1.

Additionally, the postTaskExecution hook in §5.3 validates pipeline correctness but does not validate **conformance to the project's quality standards** — the reference documents, frameworks, and governance artifacts that define what "done" means for the project.

This section introduces two additional hooks that close these gaps: a **Definition of Ready (DoR)** gate before task start, and a **Definition of Done (DoD)** gate after task completion. Together with the existing hooks, they form a complete quality lifecycle:

```
Task arrives
  │
  ▼
┌─────────────────────────────────────────┐
│  preTaskExecution — DoR Gate            │  ← "Do I have enough context
│  Validates readiness before the agent   │     to start? Have I identified
│  begins implementation.                 │     the quality standards that
│                                         │     apply to this task?"
└─────────────────────────────────────────┘
  │
  Agent implements (with preToolUse adversarial gate on each write)
  │
  ▼
┌─────────────────────────────────────────┐
│  postTaskExecution — DoD Gate           │  ← "Does the delivered work
│  Validates conformance to the project's │     meet the project's quality
│  quality standards and governance       │     standards? Can I prove it?"
│  artifacts.                             │
├─────────────────────────────────────────┤
│  postTaskExecution — Pipeline Validation│  ← (existing §5.3 hook)
│  Validates pipeline correctness,        │     "Is the pipeline correct?
│  5W2H, 5 Whys, completion report.       │     What was validated?"
└─────────────────────────────────────────┘
```

#### 5.4.1 The Concept: Project Artifacts as the Agent's Régua

Every project has artifacts that define quality — architecture documents, framework guidelines, compliance checklists, governance policies, test contracts. In traditional development, engineers internalize these standards over time. The agent does not. It must be explicitly pointed to the **régua** (measuring stick) for each task.

The DoR/DoD mechanism solves this by:

1. **Declaring reference artifacts** in the steering file — the project's quality standards that the agent must consult.
2. **Enforcing consultation at task start** (DoR) — the agent must identify which standards apply and confirm it has read them.
3. **Enforcing validation at task end** (DoD) — the agent must prove the delivered work conforms to those standards.

This mechanism is **generic** — it works for any project, any framework, any set of quality standards. The steering file declares what the régua is; the hooks enforce that the agent uses it.

#### 5.4.2 Generic DoR/DoD Architecture

The mechanism has three components:

**Component 1: Reference Artifact Declaration (Steering)**

The steering file declares the project's quality reference artifacts — the documents, frameworks, and governance policies that define "ready" and "done." This is project-specific content that adapts the generic mechanism to the workspace.

```markdown
## Quality Reference Artifacts (Régua)

| Category | Artifacts | What They Define |
|----------|-----------|-----------------|
| Architecture standards | docs/architecture/*.md | Structural patterns, module boundaries, data flow |
| Framework compliance | docs/wellarchitected/*.md | Pillar-specific best practices and questions |
| Governance policies | docs/operations/repo-governance.md | What requires review, what is self-service |
| Test contracts | docs/testing/*.md | What must be tested, at what scope |
| Domain knowledge | src/knowledge/*_corpus.py | Authoritative domain definitions |
| Agent readiness | docs/agent_readiness/checklist.md | Onboarding and production readiness criteria |
```

The agent uses this table to identify which artifacts are relevant to the current task. Not every task touches every category — the DoR gate asks the agent to identify the applicable subset.

**Component 2: preTaskExecution Hook — Definition of Ready**

The DoR hook fires before the agent begins implementation. It asks the agent to confirm readiness by identifying the applicable quality standards and confirming it has the context to meet them.

```json
{
  "name": "Definition of Ready Gate",
  "version": "1.0.0",
  "when": {
    "type": "preTaskExecution"
  },
  "then": {
    "type": "askAgent",
    "prompt": "DEFINITION OF READY — PRE-TASK GATE\n\nBefore starting this task, confirm readiness against the project's quality reference artifacts:\n\n1. APPLICABLE STANDARDS: Which quality reference artifacts (from the steering) apply to this task? List each category and the specific documents.\n\n2. STANDARDS CONSULTED: For each applicable artifact, have you read the relevant sections? If not, read them now before proceeding.\n\n3. ACCEPTANCE CRITERIA: Based on the applicable standards, what are the specific acceptance criteria for this task? What does 'done' look like according to the régua?\n\n4. SCOPE vs STANDARDS: Does the task scope align with what the standards require? Are there standards that apply but are out of scope for this task? Document any intentional exclusions.\n\n5. KNOWLEDGE GAPS: Are there applicable standards you cannot evaluate (missing documents, unclear criteria, ambiguous requirements)? Flag these as risks.\n\nIf you cannot identify the applicable standards or define acceptance criteria, gather the missing context BEFORE starting implementation."
  }
}
```

**Component 3: postTaskExecution Hook — Definition of Done**

The DoD hook fires after task completion, before the pipeline validation hook (§5.3). It asks the agent to prove conformance to the standards identified in the DoR gate.

```json
{
  "name": "Definition of Done Gate",
  "version": "1.0.0",
  "when": {
    "type": "postTaskExecution"
  },
  "then": {
    "type": "askAgent",
    "prompt": "DEFINITION OF DONE — POST-TASK GATE\n\nTask marked complete. Before reporting, validate the delivered work against the project's quality reference artifacts:\n\n1. COMPLIANCE MATRIX: For each standard identified in the DoR gate:\n\n| Standard | Criteria | Met? | Evidence | Gap? |\n|----------|----------|------|----------|------|\n| (fill for each applicable standard) | | Yes/No/Partial | What was done | What remains |\n\n2. CROSS-STANDARD IMPACT: Does compliance with one standard conflict with another? If trade-offs exist, are they documented and justified?\n\n3. GOVERNANCE CHECK: Were any governed artifacts modified? If so, was the governance process followed?\n\n4. VALIDATION vs VERIFICATION: Distinguish between:\n   - VERIFICATION: 'Did I build it right?' (tests pass, contracts hold)\n   - VALIDATION: 'Did I build the right thing?' (output meets the standard's intent, not just its structure)\n\n5. RESIDUAL GAPS: What standards are NOT fully met? For each gap:\n   - Is it a known limitation of this task's scope?\n   - Does it require a follow-up task?\n   - Does it represent a risk to the project?\n\nSummarize: PASS (all applicable standards met), PARTIAL (gaps documented with justification), or BLOCK (governance violation or unresolved conflict)."
  }
}
```

#### 5.4.3 How DoR/DoD Interacts with Existing Hooks

The four hooks form a complete quality lifecycle. Each fires at a different moment and validates a different concern:

| Hook | Event | Phase | What It Validates | Concern |
|------|-------|-------|-------------------|---------|
| DoR Gate | preTaskExecution | Before Phase 1 | Agent has identified applicable standards and acceptance criteria | **Readiness** — does the agent know what "done" looks like? |
| Adversarial Gate (§5.2) | preToolUse (write) | Phase 3.a | Each write is justified against downstream consumers, parallel paths, root cause | **Correctness** — is this the right change? |
| DoD Gate | postTaskExecution | After Phase 3 | Delivered work conforms to the project's quality standards | **Conformance** — does the work meet the régua? |
| Pipeline Validation (§5.3) | postTaskExecution | Phase 3.b-4 | Pipeline correctness, 5W2H reasoning, 5 Whys, completion report | **Completeness** — was the pipeline validated end-to-end? |

The DoD Gate and Pipeline Validation are both `postTaskExecution` hooks. They fire sequentially — the DoD gate validates conformance to standards, then the pipeline validation validates technical correctness and produces the completion report. Together, they answer two distinct questions: "Did I build the right thing?" (DoD) and "Did I build it right?" (Pipeline Validation).

#### 5.4.4 Adapting DoR/DoD to Any Project

The DoR/DoD mechanism is generic. To apply it to a new project:

**Step 1: Identify the project's quality reference artifacts.** What documents, frameworks, or governance policies define quality for this project? These become the "Régua" table in the steering file.

Examples by project type:

| Project Type | Typical Régua Artifacts |
|---|---|
| AWS infrastructure | Well-Architected Framework lenses, security policies, IAM guidelines |
| Web application | Design system tokens, accessibility standards (WCAG), API contracts |
| Data pipeline | Schema contracts, data quality rules, SLA definitions |
| ML system | Model cards, fairness metrics, evaluation benchmarks |
| Regulated industry | Compliance frameworks (SOC2, HIPAA, PCI-DSS), audit checklists |
| Open source library | Semantic versioning policy, API compatibility contracts, contribution guidelines |

**Step 2: Declare the artifacts in the steering file.** Add a "Quality Reference Artifacts" section to the project's steering file, listing each category, the specific documents, and what they define.

**Step 3: Create the DoR and DoD hooks.** Use the generic hook templates from §5.4.2. The hooks themselves are project-agnostic — they ask the agent to identify and validate against whatever standards the steering declares. No hook customization is needed.

**Step 4: Optionally create a fileMatch steering for automatic context injection.** For projects where specific file patterns always require specific standards (e.g., touching `*.tf` files always requires the infrastructure security policy), create a `fileMatch` steering that auto-loads the relevant standards when those files are read.

```markdown
---
inclusion: fileMatch
fileMatchPattern: "**/*.tf,**/modules/**/*.tf"
---

# Infrastructure Quality Context — Auto-Loaded

When modifying Terraform files, the following standards apply:
- Security: docs/security/infrastructure-security-policy.md
- Cost: docs/architecture/cost-guardrails.md
- Tagging: docs/operations/tagging-standard.md
```

**Step 5: Calibrate with engineering levels (§6).** Not every task needs the full DoR/DoD cycle:

| Level | DoR/DoD Behavior |
|---|---|
| L1 — Routine | DoR/DoD hooks self-assess as "not applicable — no quality standards affected" |
| L2 — Targeted | DoR identifies 1-2 applicable standards; DoD validates against them |
| L3 — Cross-module | Full DoR/DoD with compliance matrix |
| L4 — Architectural | Full DoR/DoD + human review of the compliance matrix before proceeding |

#### 5.4.5 Example: Cognitive WAFR with DoR/DoD

For the Cognitive WAFR project, the régua includes:

| Category | Artifacts | What They Define |
|----------|-----------|-----------------|
| WAF Framework | `docs/wellarchitected/wellarchitected-*.md` | Six-pillar best practices, lens-specific guidance |
| WAF Corpus | `src/knowledge/waf_*_corpus.py` | Authoritative pillar definitions, questions, design principles |
| Architecture | `docs/architecture/tech-design-document.md` | Module boundaries, data flow, hexagonal architecture |
| Governance | `docs/operations/repo-governance.md` | What requires review, KP as canonical truth |
| Agent Readiness | `docs/agent_readiness/checklist.md` | Production readiness criteria, prompt hash integrity |
| Test Contracts | `docs/testing/fixture-governance.md`, `docs/testing/viewer-test-contract.md` | What must be tested, fixture management rules |
| Prompt Governance | `docs/prompt-governance.md` | Prompt architecture standard, hash computation |

The DoR gate asks: "Which of these apply to the current task? Have you read the relevant sections?"

The DoD gate asks: "For each applicable standard, does the delivered work conform? Show the compliance matrix."

A `fileMatch` steering auto-loads WAF context when pipeline modules or knowledge artifacts are touched:

```markdown
---
inclusion: fileMatch
fileMatchPattern: "**/publish_tree.py,**/publish_sanitizer.py,**/facts_extractor.py,**/evidence_catalog.py,**/deterministic_reviewer.py,**/waf_*_corpus.py,**/mappings/**/*.yaml"
---
```

This ensures the agent always has the WAF régua in context when working on the pipeline, even if the user forgets to load `#fde` or `#wellarchitected`.

#### 5.4.6 Research Grounding

The DoR/DoD mechanism is grounded in the same research foundations as the rest of the protocol:

| Principle | Research Source | DoR/DoD Application |
|---|---|---|
| Verification at all levels | Vandeputte et al.: "Include verification and mitigation at all levels" | DoR verifies readiness; DoD verifies conformance; Pipeline Validation verifies correctness — three levels |
| Systematic quality verification | Vandeputte et al.: Kaizen and Six Sigma for GenAI quality | DoR/DoD implements the "check before start, check after finish" pattern from lean manufacturing |
| Human oversight is non-negotiable | Esposito et al.: 85% of studies use human interaction | The compliance matrix in DoD is a human-readable artifact that the engineer can review |
| Prompt-as-documentation | Shonan 222: Capture reasoning and decisions as project record | The DoR acceptance criteria and DoD compliance matrix become part of the task's documentation |
| Consistency over creativity | Vandeputte et al.: Promote consistency over creativity | The régua ensures the agent measures against the project's standards, not its own judgment |
| Structure reduces iteration | DiCuffa et al.: "Context and Instruction" pattern achieves highest efficiency | DoR provides context (applicable standards) + instruction (acceptance criteria) — the empirically most effective prompt structure. DoD provides a template (compliance matrix) — the third most effective pattern |

### 5.5 Architecture Diagram Generation — Visual Validation of Changes

Sections 5.1–5.4 govern the agent's reasoning and validation through text-based mechanisms (steering, hooks, compliance matrices). But architecture is inherently visual — a compliance matrix can confirm that module boundaries are respected, but it cannot show whether the data flow is coherent, whether a new component fits the existing topology, or whether the change introduces a visual anti-pattern (convergence, orphan nodes, star topology).

This section integrates architecture diagram generation into the protocol, so that tasks involving architectural changes produce or update visual artifacts as part of the Definition of Done.

#### 5.5.1 The Concept: Diagrams as Architectural Validation Artifacts

Architecture diagrams are not documentation — they are **validation artifacts**. A diagram that accurately represents the system's data flow serves as a visual regression test: if the diagram looks wrong after a change, the architecture may be wrong too.

The protocol treats diagram generation as a first-class engineering activity:

1. **Diagram steering** (`aws-architecture-diagrams` and `diagram-engineering`) provides deterministic layout rules — the agent doesn't improvise visual design.
2. **A diagram generation script** (`scripts/generate_diagrams.py`) codifies the project's architecture as executable Python using the `diagrams` package.
3. **The DoD gate** (§5.4) includes diagram validation when the task touches architectural components.

#### 5.5.2 Two-Layer Steering Architecture for Diagrams

Diagram generation is governed by two steering files that work at different levels:

| Steering | Scope | Inclusion | What It Provides |
|----------|-------|-----------|-----------------|
| `aws-architecture-diagrams.md` | Global (any workspace) | `auto` — always loaded | High-level design pattern: layout rules, cluster rules, arrow rules, node rules, flow design rules, pre/post-generation checklists |
| `diagram-engineering.md` | Global (any workspace) | `fileMatch` on `**/generate_*diagram*.py,**/diagrams/**,**/*.mmd` | Deterministic ILR (Iterative Layout Refinement) protocol: spine identification, weight-based layout control, convergence elimination, visual validation checklist |

The first steering answers **what** a good diagram looks like. The second answers **how** to make Graphviz produce one reliably.

Both are global — they apply to any workspace, not just the originating project. Any project that generates architecture diagrams benefits from these rules.

#### 5.5.3 The Diagram Generation Script Pattern

Each project that uses this protocol should maintain a diagram generation script that codifies the project's architecture as executable code. The script:

1. **Lives in `scripts/generate_diagrams.py`** (or equivalent path for the project).
2. **Produces PNG diagrams** in a standard output directory (e.g., `docs/assets/diagrams/`).
3. **Contains one function per diagram**, each with an ILR analysis docstring that documents the spine, branches, and decorative elements.
4. **Is idempotent** — running it always produces the same diagrams from the same code.

The script is the **single source of truth** for the project's architecture diagrams. When the architecture changes, the script changes. When the script changes, the diagrams update.

Example structure:

```python
#!/usr/bin/env python3
"""Generate architecture diagrams for [Project Name].

Produces PNG diagrams in docs/assets/diagrams/ using the Python diagrams package.
"""

def diagram_1_system_overview():
    """Diagram 1: System Overview.

    ILR Analysis:
      Spine: Input → Process A → Process B → Output
      Branches: Monitoring off Process A, Audit off Process B
      Decorative: IAM, CloudWatch in cluster labels
    """
    # ... diagram code following aws-architecture-diagrams steering ...

def diagram_2_data_flow():
    """Diagram 2: Data Flow Detail.
    ...
    """

if __name__ == "__main__":
    diagram_1_system_overview()
    diagram_2_data_flow()
```

#### 5.5.4 When Diagrams Are Required — Integration with DoR/DoD

Not every task requires diagram updates. The protocol uses the engineering level classification (§6) to determine when diagrams are part of the DoD:

| Level | Diagram Requirement |
|---|---|
| L1 — Routine | No diagram update needed |
| L2 — Targeted | No diagram update unless the change affects a module boundary (edge E1-E6) |
| L3 — Cross-module | Review existing diagrams for accuracy. Update if the change affects the data flow topology |
| L4 — Architectural | **Mandatory**: update or create diagrams that reflect the architectural change. Run `scripts/generate_diagrams.py` and validate output |

The DoR gate (§5.4.2) should identify whether the task affects architecture:

```
DoR Question: Does this task change the system's data flow topology,
add/remove components, or modify module boundaries?
  → Yes: Diagram update is part of the DoD
  → No: Diagram update is not required
```

The DoD gate (§5.4.2) should validate diagram accuracy:

```
DoD Check: If diagram update was required:
  1. Was scripts/generate_diagrams.py updated to reflect the change?
  2. Were the diagrams regenerated and visually validated?
  3. Do the diagrams pass the ILR validation checklist (diagram-engineering steering)?
```

#### 5.5.5 Adapting Diagram Generation to Any Project

To apply this pattern to a new project:

**Step 1: Install the global steering files.** Copy `aws-architecture-diagrams.md` and `diagram-engineering.md` to `~/.kiro/steering/`. These are project-agnostic and provide the design pattern and ILR protocol.

**Step 2: Create the diagram generation script.** Write `scripts/generate_diagrams.py` (or equivalent) with one function per diagram. Each function should have an ILR analysis docstring.

**Step 3: Add diagram validation to the DoD.** The generic DoD hook (§5.4.2) already asks "For each standard identified in the DoR gate, does the delivered work conform?" If the DoR identifies diagram update as required, the DoD will validate it.

**Step 4: Optionally create a project-specific diagram steering.** If the project has specific diagram conventions beyond the global rules (e.g., specific color coding for domain concepts, specific cluster naming), create a `fileMatch` steering that loads when diagram files are touched.

Prerequisites for diagram generation:
- GraphViz: `dot -V` (provides the layout engine)
- Python diagrams package: `pip install diagrams`

---

## 6. Engineering Level Classification

Not every task requires the full protocol. The engineering level scales with the risk and complexity of the change.

| Level | Task Profile | Protocol Phases | Kiro Mechanisms |
|---|---|---|---|
| **L1 — Routine** | Typo fix, comment update, doc change. No pipeline impact. | Phase 2 + Phase 4 (minimal) | Steering only. Hooks self-assess as not applicable. |
| **L2 — Targeted** | Single-module change with known downstream consumers. Bug fix in one function. | Phase 1.b + Phase 2 + Phase 3 + Phase 4 | Steering + preToolUse hook. postTaskExecution optional. |
| **L3 — Cross-module** | Change affects multiple modules in the pipeline. New feature touching 2+ stages. | Full Phase 1 + Phase 2 + Full Phase 3 + Phase 4 | All three mechanisms active. |
| **L4 — Architectural** | New pipeline stage, data model change, module boundary redesign. | Full protocol with extended Phase 1 (map all affected modules) and extended Phase 3.a (adversarial review of architecture, not just code). | All three mechanisms + human review gate before Phase 3. |

The agent should self-classify the engineering level based on the task description and the Phase 1 reconnaissance. If uncertain, default to L3.

**Research grounding:** Vandeputte et al.'s programmable router pattern — route routine work through fast traditional processing, reserve cognitive processing for exceptional cases. The engineering level classification is the router: L1 tasks get minimal protocol overhead, L4 tasks get full adversarial review.

---

## 7. Applying This Pattern to Other Projects

This pattern is not specific to Cognitive WAFR. To apply it to any project:

**Step 1: Define the pipeline.** Every software product has a data flow — input enters, transforms happen, output reaches the user. Map the stages and the edges between them. This becomes the pipeline chain in the steering file.

**Step 2: Identify the module boundaries.** The bugs live at the edges between modules, where data transforms. List the key edges and what transforms at each one. This becomes the "Key Module Boundaries" table in the steering file.

**Step 3: Identify the product-level invariant.** What is the end-to-end property that must hold? "Given this input, the output should..." This becomes the smoke test criterion and the product-level check in the postTaskExecution hook.

**Step 4: Calibrate the engineering levels.** What constitutes a routine change vs an architectural change in this project? Define the levels based on the project's risk profile.

**Step 5: Create the three Kiro artifacts:**
- Steering file with the pipeline chain, module boundaries, and protocol phases
- preToolUse hook with the adversarial questions adapted to the project's architecture
- postTaskExecution hook with the pipeline testing and 5W2H validation

**Step 6: Set up diagram generation (§5.5):**
- Install the global diagram steering files (`aws-architecture-diagrams.md` and `diagram-engineering.md`) in `~/.kiro/steering/`
- Create `scripts/generate_diagrams.py` with one function per architecture diagram, each with an ILR analysis docstring
- Add diagram validation to the DoD criteria for L3+ tasks

**Example for a web application:**

```
Pipeline: API Request → Middleware → Controller → Service → Repository
  → Database → Response Serializer → HTTP Response → Client Renders

Module Boundaries:
  E1: Middleware → Controller (auth context, request parsing)
  E2: Controller → Service (business logic input validation)
  E3: Service → Repository (query construction)
  E4: Repository → Database (SQL execution)
  E5: Response Serializer → HTTP Response (status codes, headers)

Product-level invariant: "Given a valid API request, the response
  contains correct data with appropriate status code and headers."
```

**Example for a data pipeline:**

```
Pipeline: Ingestion → Validation → Transform → Enrichment
  → Aggregation → Storage → API → Dashboard

Module Boundaries:
  E1: Ingestion → Validation (schema conformance)
  E2: Validation → Transform (clean data contract)
  E3: Transform → Enrichment (join keys present)
  E4: Enrichment → Aggregation (dimension alignment)
  E5: Storage → API (query result shape)

Product-level invariant: "Given raw input data, the dashboard
  shows accurate aggregations with no missing dimensions."
```

---

## 8. How to Use — Kiro IDE and Kiro CLI

This section provides step-by-step instructions for activating, operating, and deactivating the FDE protocol in both the Kiro IDE (graphical) and the Kiro CLI (terminal).

### 8.1 Artifact Inventory

The protocol consists of three artifacts that work together:

| Artifact | Path | Type | Default State |
|----------|------|------|---------------|
| Steering file | `.kiro/steering/fde.md` | Manual inclusion steering | Inactive — loads only when user provides `#fde` in chat |
| DoR gate hook | `.kiro/hooks/fde-dor-gate.kiro.hook` | preTaskExecution | `"enabled": false` — must be enabled manually |
| Adversarial gate hook | `.kiro/hooks/fde-adversarial-gate.kiro.hook` | preToolUse on write | `"enabled": false` — must be enabled manually |
| DoD gate hook | `.kiro/hooks/fde-dod-gate.kiro.hook` | postTaskExecution | `"enabled": false` — must be enabled manually |
| Pipeline validation hook | `.kiro/hooks/fde-pipeline-validation.kiro.hook` | postTaskExecution | `"enabled": false` — must be enabled manually |
| Quality context steering (optional) | `.kiro/steering/<project>-quality-context.md` | fileMatch steering | Active when matching files are read |
| Diagram design pattern (global) | `~/.kiro/steering/aws-architecture-diagrams.md` | Auto inclusion steering | Always active — provides layout, cluster, arrow, and node rules |
| Diagram ILR protocol (global) | `~/.kiro/steering/diagram-engineering.md` | fileMatch steering | Active when diagram scripts or `.mmd` files are read |
| Diagram generation script | `scripts/generate_diagrams.py` | Python script | Project-specific — codifies architecture as executable diagrams |

All three core artifacts (steering + adversarial gate + pipeline validation) must be active for the base protocol. The DoR and DoD gate hooks add the quality standards layer. The fileMatch steering provides automatic context injection for pipeline-critical files. The diagram steering files are global and apply to any workspace.

### 8.2 Activation — Kiro IDE

**Step 1: Load the steering into the chat context.**

In the Kiro chat input, type `#` and select `fde` from the context picker. This loads the steering file into the current conversation. The agent now operates as a Forward Deployed AI Engineer with the full pipeline chain, module boundaries, knowledge architecture, and protocol phases.

Alternatively, type your prompt and include `#fde` inline:

```
#fde Fix the severity distribution in publish_sanitizer.py
```

**Step 2: Enable the hooks.**

Open the **Agent Hooks** section in the Kiro explorer sidebar (left panel). You will see:

```
Agent Hooks
  ├── compassionate-language-review     (disabled)
  ├── diagram-design-pattern            (enabled)
  ├── diagram-ilr-review                (enabled)
  ├── diagram-layout-review             (enabled)
  ├── fde-adversarial-gate       (disabled)  ← enable this
  ├── fde-dod-gate               (disabled)  ← enable this
  ├── fde-dor-gate               (disabled)  ← enable this
  ├── fde-pipeline-validation    (disabled)  ← enable this
  └── portal-diagram-ilr                (enabled)
```

Click on `fde-dor-gate` and toggle it to **enabled**.
Click on `fde-adversarial-gate` and toggle it to **enabled**.
Click on `fde-dod-gate` and toggle it to **enabled**.
Click on `fde-pipeline-validation` and toggle it to **enabled**.

Alternatively, use the Command Palette (`Cmd+Shift+P` on macOS) and search for `Open Kiro Hook UI` to manage hooks.

**Step 3: Verify activation.**

After enabling, the protocol is fully active. You can verify by sending a test prompt:

```
#fde What is the current pipeline chain for offline mode?
```

The agent should respond with the pipeline chain from the steering (E1-E6) without you needing to explain the architecture.

**What happens when active:**

- Every **spec task start** triggers the DoR gate hook. The agent must identify applicable quality standards, confirm it has read them, and define acceptance criteria before implementation begins.
- Every **write operation** (file create, file edit, strReplace) triggers the adversarial gate hook. The agent must answer 7 questions before the write proceeds.
- Every **spec task completion** triggers the DoD gate hook followed by the pipeline validation hook. The DoD gate validates conformance to the project's quality standards (compliance matrix). The pipeline validation hook runs contract tests, validates edges, applies 5W2H reasoning, and produces a completion report.
- The steering provides the **context** for all hooks — the pipeline chain, module boundaries, knowledge artifacts, quality reference artifacts, and anti-patterns.

### 8.3 Activation — Kiro CLI

When using Kiro from the terminal (headless or CLI mode), the activation is done through the prompt and file editing.

**Step 1: Load the steering by referencing it in your prompt.**

```bash
kiro chat "#fde Fix the deduplication logic in publish_tree.py"
```

Or if using an interactive session:

```
> #fde
> Fix the deduplication logic in publish_tree.py
```

**Step 2: Enable the hooks by editing the hook files.**

Open the hook files and change `"enabled": false` to `"enabled": true`:

```bash
# Enable the adversarial gate
# Edit .kiro/hooks/fde-adversarial-gate.kiro.hook
# Change: "enabled": false → "enabled": true

# Enable the pipeline validation
# Edit .kiro/hooks/fde-pipeline-validation.kiro.hook
# Change: "enabled": false → "enabled": true
```

Kiro detects hook file changes automatically — no restart required.

**Step 3: Verify activation.**

```bash
kiro chat "#fde List the module boundaries for the offline pipeline"
```

The agent should respond with the E1-E6 edge table from the steering.

### 8.4 Operating Under the Protocol

Once active, the protocol changes how the agent works. Here is what to expect at each phase:

**Phase 1 — Reconnaissance (automatic).**

When you give the agent a task, it will first map the affected modules, identify artifact types (code vs knowledge), state upstream/downstream dependencies, and acknowledge the risk. You will see output like:

```
AFFECTED MODULES: publish_tree.py (code artifact), fact_type_question_map.yaml (knowledge artifact)
ARTIFACT TYPE: Mixed — code + knowledge
UPSTREAM: evidence_catalog.py produces evidence records consumed by publish_tree
DOWNSTREAM: publish_sanitizer.py consumes findings from publish_tree
DOMAIN SOURCE OF TRUTH: WAF corpus files (src/knowledge/waf_*_corpus.py)
RISK: Structural (contract violation if finding shape changes) + Semantic (wrong WAF question mapping)
TEST COVERAGE: contract tests cover E3-E4 edges; knowledge tests cover mapping layer
```

**Phase 3.a — Adversarial gate (on every write).**

Before each write, the hook fires and the agent answers the 7 adversarial questions. For routine writes (docs, comments), the agent self-assesses as "not applicable — no pipeline impact" and proceeds. For pipeline writes, you will see the agent pause to verify downstream consumers, check parallel paths, and validate domain correctness.

If the agent cannot answer a question, it will read the missing context before proceeding. This is the intended behavior — discovery before action.

**Phase 3.b-3.d — Validation (on task completion).**

After completing a spec task, the hook fires and the agent:
1. Runs contract tests (`python3 scripts/run_tests.py --scope contract`)
2. Validates edge contracts for the affected modules
3. Checks severity distribution if the change touches the finding pipeline
4. Applies 5W2H reasoning to the delivered task
5. Applies 5 Whys to any issues found during development
6. Produces a structured completion report

**Phase 4 — Completion report.**

The agent's final message will include:
- What was delivered
- What was validated (which test scopes, which edges)
- What was NOT validated (and why)
- Residual risks or follow-up items

### 8.5 Deactivation

**Kiro IDE:**

1. Open the **Agent Hooks** explorer sidebar.
2. Toggle `fde-dor-gate` to **disabled**.
3. Toggle `fde-adversarial-gate` to **disabled**.
4. Toggle `fde-dod-gate` to **disabled**.
5. Toggle `fde-pipeline-validation` to **disabled**.
6. The steering unloads automatically when the conversation ends or when you stop referencing `#fde`.

**Kiro CLI:**

1. Edit all four hook files and change `"enabled": true` back to `"enabled": false`.
2. Stop including `#fde` in your prompts.

The protocol is fully deactivated. The agent returns to standard development behavior.

### 8.6 Partial Activation (Engineering Levels)

You don't always need the full protocol. Use partial activation based on the engineering level of the task:

| Engineering Level | What to Activate | When to Use |
|---|---|---|
| **L1 — Routine** | Steering only (`#fde` in chat). No hooks. | Typo fix, comment update, doc change. No pipeline impact. |
| **L2 — Targeted** | Steering + adversarial gate hook. No validation hooks. | Single-module bug fix with known downstream consumers. |
| **L3 — Cross-module** | Steering + all four hooks (DoR + adversarial + DoD + pipeline validation). | Change affects multiple pipeline modules. New feature touching 2+ stages. |
| **L4 — Architectural** | Steering + all four hooks + explicit human review gate. | New pipeline stage, data model change, module boundary redesign. Tell the agent: "Do not proceed past Phase 1.b without my approval." |

**L1 example (Kiro IDE):**

```
#fde Fix the typo in the executive summary renderer
```

No hooks needed. The steering provides context but the agent self-classifies as L1 and skips the adversarial gate.

**L3 example (Kiro IDE):**

Enable both hooks, then:

```
#fde Add BP addressability for service_posture fact types in evidence_bp_addressability.yaml
```

The agent will:
1. Map the knowledge architecture (Phase 1)
2. Identify this as a knowledge artifact change
3. Read the WAF corpus files as domain source of truth
4. Write the YAML with adversarial gate validation (Phase 3.a)
5. Run contract tests and validate the risk engine output (Phase 3.b)
6. Apply 5W2H reasoning (Phase 3.c)
7. Report what was delivered and validated (Phase 4)

**L4 example (Kiro IDE):**

Enable both hooks, then:

```
#fde I want to add a consolidation stage between publish_tree and publish_sanitizer. Do not proceed past Phase 1.b without my approval.
```

The agent will complete Phase 1 (reconnaissance, pre-reqs, impact acknowledgment) and stop for your review before writing any code.

### 8.7 Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│  FDE PROTOCOL — QUICK REFERENCE                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ACTIVATE:                                              │
│    Chat:  #fde <your task>               │
│    Hooks: Enable fde-dor-gate                    │
│           Enable fde-adversarial-gate            │
│           Enable fde-dod-gate                    │
│           Enable fde-pipeline-validation         │
│                                                         │
│  DEACTIVATE:                                            │
│    Hooks: Disable all four hooks                        │
│    Chat:  Stop referencing #fde          │
│                                                         │
│  QUALITY LIFECYCLE:                                     │
│    preTaskExecution  → DoR Gate (readiness)              │
│    preToolUse/write  → Adversarial Gate (correctness)   │
│    postTaskExecution → DoD Gate (conformance)            │
│    postTaskExecution → Pipeline Validation (completeness)│
│                                                         │
│  ENGINEERING LEVELS:                                    │
│    L1 Routine:      Steering only                       │
│    L2 Targeted:     Steering + adversarial gate         │
│    L3 Cross-module: Steering + all four hooks           │
│    L4 Architectural: All hooks + human gate             │
│                                                         │
│  PIPELINE CHAIN:                                        │
│    E1: facts_extractor → evidence_catalog               │
│    E2: evidence_catalog → deterministic_reviewer        │
│    E3: deterministic_reviewer → publish_tree            │
│    E4: publish_tree → publish_sanitizer                 │
│    E5: publish_sanitizer → JSON artifacts               │
│    E6: JSON artifacts → Portal JS renderers             │
│                                                         │
│  KEY COMMANDS:                                          │
│    Contract tests: run_tests.py --scope contract        │
│    Knowledge tests: run_tests.py --scope knowledge      │
│    Full suite:      run_tests.py                        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 9. Empirical Validation — Bare vs FDE Quality Threshold

To validate that the FDE mechanism produces measurably higher quality agent responses, we conducted a controlled comparison using the same task scenario with and without the protocol active.

### 9.1 Methodology

**Scenario**: "Fix the severity distribution — findings are all MEDIUM" — a real task from the Cognitive WAFR project that touches both code artifacts (publish_tree.py) and knowledge artifacts (severity map, BP addressability config).

**Bare condition**: The agent receives only the raw task description (Simple Question pattern). No steering, no hooks, no protocol context.

**FDE condition**: The agent operates with the full FDE protocol — steering loaded (`#fde`), all four hooks active (DoR gate, adversarial gate, DoD gate, pipeline validation).

**Quality rubric**: 18 objective, checkable criteria derived from the FDE protocol phases. Each criterion is binary (met/not met) and tested by automated keyword and pattern matching against the response text. The rubric covers:

| Phase | Criteria Count | What It Measures |
|-------|---------------|-----------------|
| Phase 1 (Reconnaissance) | 4 | Module identification, pipeline position, artifact type, downstream impact |
| Phase 2 (Structured Intake) | 2 | Acceptance criteria, constraints |
| Phase 3.a (Adversarial) | 3 | Root cause investigation, parallel paths, domain knowledge validation |
| Phase 3.b (Pipeline Testing) | 2 | Test scope specification, edge contract validation |
| Phase 3.c (5W2H) | 4 | What, where, why, how validated |
| Phase 3.d (5 Whys) | 1 | Investigation beyond surface symptom |
| Phase 4 (Completion) | 1 | Reports what was and was NOT validated |
| Anti-patterns | 1 | Avoids symptom chasing |

### 9.2 Results

```
======================================================================
DETAILED COMPARISON: BARE vs FDE
======================================================================
Criterion                             Bare    FDE  Delta
----------------------------------------------------------------------
  identifies_affected_modules         FAIL   PASS   +FDE
  identifies_pipeline_position        FAIL   PASS   +FDE
  identifies_artifact_type            FAIL   PASS   +FDE
  identifies_downstream_impact        FAIL   PASS   +FDE
  states_acceptance_criteria          PASS   PASS      =
  states_constraints                  FAIL   PASS   +FDE
  considers_root_cause                FAIL   PASS   +FDE
  considers_parallel_paths            FAIL   PASS   +FDE
  validates_domain_knowledge          FAIL   PASS   +FDE
  specifies_test_scope                PASS   PASS      =
  validates_edge_contract             FAIL   PASS   +FDE
  answers_what                        PASS   PASS      =
  answers_where                       PASS   PASS      =
  answers_why                         FAIL   PASS   +FDE
  answers_how_validated               FAIL   PASS   +FDE
  investigates_beyond_symptom         PASS   PASS      =
  reports_what_validated              FAIL   PASS   +FDE
  avoids_symptom_chasing              PASS   PASS      =
----------------------------------------------------------------------
  FDE wins: 12  |  Bare wins: 0  |  Ties: 6
  BARE total: 6/18 (33%)
  FDE total:  18/18 (100%)
======================================================================
```

| Metric | Bare | FDE | Threshold | Result |
|--------|------|-----|-----------|--------|
| Quality score | 6/18 (33%) | 18/18 (100%) | — | **+67% improvement** |
| Minimum threshold (75%) | — | 100% | ≥75% | **PASS** |
| Improvement ratio | — | — | ≥30% | **67% — PASS** |
| Criteria where FDE wins | — | 12 | — | — |
| Criteria where Bare wins | 0 | — | — | — |

### 9.3 Analysis

The bare response exhibits the exact failure patterns documented in §3 and §3.1:

1. **Symptom chasing** (§3.1, Pattern 1): The bare response jumps directly to patching `_FACT_CLASS_SEVERITY` without investigating why the map is flat or whether the risk engine path is the intended architecture.

2. **Node-scoped verification** (§3, Failure Mode 2): The bare response runs "all tests" without specifying which test scopes validate the affected edges. It does not check downstream consumers.

3. **Domain knowledge gaps** (§3.1, Pattern 3): The bare response assigns severity values without referencing the WAF corpus files — the domain source of truth. The assignments are plausible but not validated.

4. **No structured reporting** (§3, Failure Mode 5): The bare response declares "done" without reporting what was validated, what was NOT validated, or what residual risks remain.

The FDE response, by contrast, follows the full protocol recipe and produces a structured output that addresses all 18 quality criteria. The key differentiators are:

- **Phase 2 reformulation**: The FDE response transforms the bare question into a Context + Instruction + Constraints contract before writing any code
- **Root cause analysis**: The FDE response applies 5 Whys and discovers the architectural root cause (incomplete BP addressability), not just the surface symptom (flat map)
- **Domain validation**: The FDE response validates severity assignments against 6 WAF corpus files
- **Structured reporting**: The FDE response explicitly states what was validated, what was NOT validated, and what residual risks remain

### 9.4 Reproducibility

The test is fully automated and reproducible:

```bash
# Run the structural E2E test (48 tests)
python3 -m pytest tests/test_fde_e2e_protocol.py -v

# Run the quality threshold test (6 tests)
python3 -m pytest tests/test_fde_quality_threshold.py -v -s
```

The quality rubric is defined in `tests/test_fde_quality_threshold.py` and can be extended with additional criteria as the protocol evolves. The bare and FDE response fixtures are in `tests/fixtures/fde_quality/`.

---

## 10. References

1. Esposito, M., Palagiano, F., Lenarduzzi, V., Taibi, D. (2025). "Generative AI for Software Architecture: Applications, Challenges, and Future Directions." *Journal of Systems and Software*. [arXiv:2503.13310v2](https://arxiv.org/abs/2503.13310v2).

2. Vandeputte, F. et al. (2025). "Foundational Design Principles and Patterns for Building Robust and Adaptive GenAI-Native Systems." *ACM Onward! '25*, Singapore. [arXiv:2508.15411](https://arxiv.org/abs/2508.15411).

3. Hu, X., Kula, R.G., Treude, C. (2025). "The Future of Development Environments with AI Foundation Models: NII Shonan Meeting 222 Report." [arXiv:2511.16092v1](https://arxiv.org/abs/2511.16092v1).

4. DiCuffa, S., Zambrana, A., Yadav, P., Madiraju, S., Suman, K., AlOmar, E.A. (2025). "Exploring Prompt Patterns in AI-Assisted Code Generation: Towards Faster and More Effective Developer-AI Collaboration." Stevens Institute of Technology. [arXiv:2506.01604](https://arxiv.org/abs/2506.01604).

5. COE-052 Post-Mortem. "How Incremental Delivery Obscured the Holistic View." In: `docs/design/deep-cognitive-analysis.md`, §14.

6. COE-052 Recurring Errors Analysis. "Recurring Errors in the LLM-Assisted Development Process." In: `docs/design/deep-cognitive-analysis.md`, §9. Identifies four failure patterns: reactive fix cycle (§9.1), architecture-unaware symptom fixing (§9.2), domain knowledge gaps (§9.2–9.3), and stateless pipeline limitations (§9.4).

---

*This document is a living playbook. As the protocol is applied to more projects and more post-mortems are conducted, the phases, hooks, and engineering levels should be refined based on empirical evidence.*
