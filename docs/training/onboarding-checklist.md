# New Developer Onboarding Checklist

> Training Guide — Activity 3.23

## Welcome to the Autonomous Code Factory

This checklist guides you through your first week working with the factory. Complete each section in order — each step builds on the previous one.

---

## Phase 1: Read and Understand (Day 1)

### Required Reading

- [ ] **Architecture Overview** — Read [docs/architecture/design-document.md](../architecture/design-document.md)
  - Understand the 5 planes: VSM, FDE, Context, Data, Control
  - Know what "autonomy levels" (L1-L5) mean
  - Understand the "organism ladder" (O1-O5) for task complexity

- [ ] **How Specs Work** — Read [docs/training/effective-specs.md](./effective-specs.md)
  - Specs are the control plane — everything starts from a spec
  - Learn the three pillars: user value, acceptance criteria, context

- [ ] **Understanding Gates** — Read [docs/training/understanding-gates.md](./understanding-gates.md)
  - Know what each gate checks
  - Understand why gates exist (quality, not bureaucracy)

- [ ] **ADR-002: Spec as Control Plane** — Read [docs/adr/ADR-002-spec-as-control-plane.md](../adr/ADR-002-spec-as-control-plane.md)
  - Why the spec drives everything
  - How autonomy level is determined from the spec

- [ ] **Quickstart Guide** — Read [docs/quickstart.md](../quickstart.md)
  - Local development setup
  - How to run the factory locally

### Key Concepts to Understand

After reading, you should be able to answer:
1. What is the difference between L1 and L5 autonomy?
2. What does the adversarial gate check?
3. What makes a good user value statement?
4. What happens when a gate rejects your work?
5. What is the circuit breaker and when does it trigger?

---

## Phase 2: Set Up Your Environment (Day 1-2)

### Development Environment

- [ ] Clone the repository
  ```bash
  git clone <repo-url>
  cd forward-deployed-ai-pattern
  ```

- [ ] Install Python dependencies
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

- [ ] Verify the test suite passes
  ```bash
  make test
  ```

- [ ] Set up your IDE with recommended extensions
  - Python language server (Pylance/Pyright)
  - Linter (ruff or flake8)
  - Type checker (mypy)

### Factory Configuration

- [ ] Configure your AWS credentials (for DynamoDB access)
  ```bash
  aws configure --profile factory-dev
  ```

- [ ] Set environment variables (see `.env.example`)
  ```bash
  cp .env.example .env
  # Edit .env with your project-specific values
  ```

- [ ] Verify factory connectivity
  ```bash
  make verify-setup
  ```

### Starter Profile

- [ ] Run the starter profile to see the factory in action
  ```bash
  make run-starter-profile
  ```
  This executes a pre-configured L1 task so you can observe the full pipeline:
  spec → DOR gate → implementation → adversarial gate → DoD gate → PR

---

## Phase 3: Complete 3 L1 Tasks (Day 2-5)

L1 tasks are fully supervised — the factory assists but you approve every step. This is how you build intuition for how the factory works.

### Task 1: Documentation Update (Simplest)

- [ ] Pick an L1 documentation task from the backlog
- [ ] Write a spec following the template
- [ ] Submit to the factory
- [ ] Observe: DOR gate evaluation
- [ ] Observe: Implementation generation
- [ ] Review the output and approve/reject
- [ ] Observe: DoD gate evaluation
- [ ] Merge the PR

**Learning goal:** Understand the basic flow from spec to merged PR.

### Task 2: Small Code Change (Add a field/method)

- [ ] Pick an L1 code task (e.g., "add a new field to dataclass X")
- [ ] Write a spec with acceptance criteria
- [ ] Submit and observe the adversarial gate in action
- [ ] If rejected: read the feedback, understand why, fix it
- [ ] Successfully pass all gates and merge

**Learning goal:** Experience gate feedback and the revision cycle.

### Task 3: Bug Fix (Requires context)

- [ ] Pick an L1 bug fix task
- [ ] Write a spec with root cause analysis and context
- [ ] Include "existing tests must continue to pass" in criteria
- [ ] Submit and observe how the factory uses context
- [ ] Verify the fix addresses the root cause

**Learning goal:** Understand how context provision affects factory output quality.

---

## Phase 4: Review and Reflect (Day 5)

### Self-Assessment

- [ ] Review your gate pass rates across the 3 tasks
  - How many first-pass successes?
  - What were the common rejection reasons?

- [ ] Check your Happy Time ratio
  - How much time was creative vs toil?
  - What caused the most toil?

- [ ] Identify your top improvement area
  - Spec writing?
  - Understanding gate expectations?
  - Context provision?

### Team Check-in

- [ ] Schedule a 30-minute check-in with your team lead
- [ ] Discuss:
  - What surprised you about the factory?
  - What felt friction-heavy?
  - What questions do you have about higher autonomy levels?

---

## Phase 5: Level Up (Week 2+)

Once you've completed the onboarding:

- [ ] Try an L2 task (factory executes, you review before merge)
- [ ] Read about the organism ladder in the design document
- [ ] Explore the portal dashboard for your project metrics
- [ ] Review the DORA metrics for your team
- [ ] Consider proposing an ADR if you see a process improvement

### Progression Path

```
L1 (Week 1)     → You approve every step
L2 (Week 2-3)   → Factory executes, you review output
L3 (Month 2)    → Factory executes with periodic check-ins
L4 (Month 3+)   → Factory executes autonomously, you review PRs
L5 (Earned)     → Full autonomy for trusted patterns
```

Autonomy level progression is earned through consistent quality, not time served.

---

## Resources

| Resource | Location |
|----------|----------|
| Architecture docs | `docs/architecture/` |
| ADR decisions | `docs/adr/` |
| Training guides | `docs/training/` |
| Spec templates | `docs/templates/` |
| Example tasks | `docs/example/` |
| Quickstart | `docs/quickstart.md` |
| Factory design | `docs/design/` |

---

## Getting Help

- **Stuck on a gate rejection?** Read the feedback carefully — it includes a suggestion.
- **Confused about a concept?** Check the ADR that explains the decision.
- **Factory behaving unexpectedly?** Check the flight log at `docs/flight_log_v1.md`.
- **Need human help?** Ask in the team channel or tag your team lead.

---

## Completion Criteria

You've completed onboarding when:
- [x] All required reading done
- [x] Environment set up and verified
- [x] 3 L1 tasks completed and merged
- [x] Self-assessment completed
- [x] Team check-in done

Welcome to the factory. Build great things.
