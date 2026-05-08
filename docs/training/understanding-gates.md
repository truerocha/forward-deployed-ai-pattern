# Understanding Gates: What Each Gate Checks and How to Pass

> Training Guide — Activity 3.22

## Overview

Gates are quality checkpoints in the factory pipeline. They exist to catch problems early, before they reach production. Understanding what each gate checks — and why — helps you write code and specs that pass on the first attempt.

Every gate produces a unified output: `{gate_name, status, feedback, next_action}`. When a gate rejects, it tells you exactly what failed and what to fix.

---

## Gate Pipeline Order

```
Spec → [DOR Gate] → Implementation → [Adversarial Gate] → [DoD Gate] → [Pipeline Gate] → Deploy
```

Each gate has a specific purpose. Skipping or weakening gates increases downstream failure rates.

---

## Gate 1: Definition of Ready (DOR)

**Purpose:** Ensures the spec is complete enough for autonomous execution.

**What it checks:**
- User value statement is present and specific
- Acceptance criteria are testable and unambiguous
- Context is sufficient for the assigned autonomy level
- Scope boundaries are defined
- No conflicting requirements

**Common rejection reasons:**

| Rejection | Fix |
|-----------|-----|
| "Missing user value statement" | Add "As a [role], I need [X] so that [Y]" |
| "Acceptance criteria not testable" | Replace vague terms with specific values |
| "Insufficient context for L4+ execution" | Add file paths, patterns, constraints |
| "Ambiguous scope" | Add "Out of scope" section |
| "Conflicting criteria" | Resolve contradictions, state priority |

**Tips for passing DOR:**
- Use the spec template from [effective-specs.md](./effective-specs.md)
- Include at least 3 acceptance criteria
- Mention error cases explicitly
- State auth/security requirements even if "none"

---

## Gate 2: Adversarial Review Gate

**Purpose:** An independent AI reviewer challenges the implementation for correctness, security, and completeness.

**What it checks:**
- Implementation matches all acceptance criteria
- Error handling covers failure paths
- Security: no injection vulnerabilities, proper auth checks
- No regressions to existing functionality
- Code follows project conventions and patterns
- Test coverage for new behavior

**Common rejection reasons:**

| Rejection | Fix |
|-----------|-----|
| "Missing error handling for [X]" | Add try/except with specific exception types |
| "Acceptance criterion [N] not satisfied" | Re-read the criterion literally and implement it |
| "Security: user input not validated" | Add input validation before processing |
| "No test for new behavior" | Add unit test covering the new code path |
| "Breaks existing pattern in [file]" | Follow the established pattern, don't invent new ones |
| "Function too complex (cyclomatic > 10)" | Extract helper functions, simplify logic |

**Tips for passing adversarial review:**
- Read acceptance criteria literally — each one must be demonstrably met
- Add error handling for every external call (DB, API, file I/O)
- Write tests before or alongside implementation
- Follow existing patterns in the codebase (check similar files)
- Keep functions focused and under 50 lines

**Fast path:** Trusted patterns (>98% pass rate over 30 days) at L5 can skip this gate. See gate optimizer documentation.

---

## Gate 3: Definition of Done (DoD)

**Purpose:** Verifies the complete deliverable meets quality standards.

**What it checks:**
- All acceptance criteria marked as satisfied
- Tests pass (unit, integration as applicable)
- No lint/type errors introduced
- Documentation updated if public API changed
- Changelog entry added for user-facing changes
- PR description is complete and accurate

**Common rejection reasons:**

| Rejection | Fix |
|-----------|-----|
| "Tests failing" | Fix the failing tests (do NOT delete them) |
| "Type errors introduced" | Run mypy/pyright and fix type annotations |
| "Missing changelog entry" | Add entry to CHANGELOG.md |
| "PR description incomplete" | Fill in all sections of the PR template |
| "Documentation not updated" | Update docstrings/README for API changes |

**Tips for passing DoD:**
- Run the full test suite locally before submitting
- Run linters and type checkers
- Update docs for any public interface changes
- Write a clear PR description explaining what and why

---

## Gate 4: Pipeline Gate (CI/CD)

**Purpose:** Automated verification that the code builds, tests pass, and quality metrics are met.

**What it checks:**
- Build succeeds
- All tests pass (unit, integration, e2e)
- Code coverage meets threshold
- No security vulnerabilities (dependency scan)
- Performance benchmarks not regressed
- Docker image builds successfully (if applicable)

**Common rejection reasons:**

| Rejection | Fix |
|-----------|-----|
| "Build failure" | Check import errors, missing dependencies |
| "Test failure in [test_file]" | Fix the code, not the test |
| "Coverage below threshold" | Add tests for uncovered paths |
| "Security vulnerability in [dep]" | Update the dependency or add override with justification |
| "Performance regression" | Profile and optimize the hot path |

**Tips for passing pipeline:**
- Run `make test` (or equivalent) locally first
- Check that all new dependencies are pinned
- Don't ignore CI failures — they catch real bugs

---

## Gate 5: Test Immutability Gate

**Purpose:** Prevents modification of human-approved tests (tests marked with `# @human-approved`).

**What it checks:**
- Approved test files are not modified
- Test assertions are not weakened
- Test cases are not removed

**Common rejection reasons:**

| Rejection | Fix |
|-----------|-----|
| "Attempted to modify approved test" | Fix production code to satisfy the test |
| "Test assertion changed" | Revert test change, fix implementation instead |

**Tips:**
- If a test fails, the production code is wrong — fix the code
- Never modify a `# @human-approved` test file
- New tests (without the marker) can be freely modified

---

## Gate 6: Circuit Breaker

**Purpose:** Halts execution when repeated failures indicate a systemic problem.

**What it checks:**
- Consecutive failure count per task
- Error classification (transient vs permanent)
- Resource exhaustion signals

**When it triggers:**
- 3 consecutive failures on the same task
- Permanent error detected (e.g., missing dependency, invalid architecture)
- Token budget exhausted

**What to do when circuit-broken:**
- Read the accumulated feedback from all attempts
- The problem is likely architectural, not incremental
- Revise the spec or approach fundamentally
- Consider reducing autonomy level for this task

---

## Reducing Gate Friction

### General Principles

1. **Read the feedback.** Gate rejections include specific reasons and suggestions. Follow them.
2. **Fix forward, don't work around.** If a gate rejects, fix the root cause. Don't try to game the gate.
3. **Learn from patterns.** If you see the same rejection repeatedly, update your spec template or coding habits.
4. **Use the fast path.** Trusted patterns skip adversarial review. Build trust by consistently passing.

### Metrics to Watch

- **Gate pass rate:** Your personal pass rate across gates. Target: >90% first-pass.
- **Time in gates:** If >20% of task time is spent in gates, something is wrong upstream.
- **Happy Time ratio:** Creative work should be >60% of total time. High gate friction reduces this.

### When Gates Feel Too Strict

Gates are calibrated based on data. If you believe a gate is incorrectly rejecting:
1. Check if the rejection feedback is accurate
2. If the gate is wrong, report it (this improves calibration)
3. If the gate is right but the rule seems excessive, propose an ADR to change the rule

---

## Quick Reference: Gate Summary

| Gate | When | Checks | Pass Rate Target |
|------|------|--------|-----------------|
| DOR | Before implementation | Spec completeness | >95% |
| Adversarial | After implementation | Correctness, security | >90% |
| DoD | Before PR merge | Quality standards | >95% |
| Pipeline | CI/CD | Build, tests, coverage | >98% |
| Test Immutability | On file write | Approved tests unchanged | 100% |
| Circuit Breaker | On repeated failure | Systemic issues | N/A |

---

## Further Reading

- [Effective Specs](./effective-specs.md) — Write specs that pass DOR first time
- [Onboarding Checklist](./onboarding-checklist.md) — Getting started
- [Gate Output Schema](../../src/core/governance/gate_output_schema.py) — Technical schema definition
- [Gate Feedback Formatter](../../src/core/governance/gate_feedback_formatter.py) — How feedback is structured
- [ADR-012: Adversarial Review](../adr/ADR-012-adversarial-review-over-engineering-and-gaps.md) — Design decisions
