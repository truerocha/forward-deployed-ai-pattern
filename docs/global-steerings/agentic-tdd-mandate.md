---
inclusion: auto
---

# Agentic TDD Mandate (Universal Law)

These rules apply to ALL workspaces, ALL interactions, ALL engineering levels.

## SHIFT-LEFT TESTING
Write tests BEFORE production code. See them fail first. The test is the specification of behavior.

## HALTING CONDITION
Ythis implementation objective is EXCLUSIVELY to make the approved test bar green while satisfying all constraints from the spec. Do not over-engineer. Do not add features not in the spec.

## ANTI-LAZY MOCK
STRICTLY PROHIBITED: Mocking the core business rule under test. Tests must exercise real behavior.
- Allowed: Mocking external I/O (HTTP calls, database, file system) with realistic responses
- Forbidden: Mocking the function being tested, mocking validation logic, mocking business rules

## TEST IMMUTABILITY
Once the human approves test files (marked with `@human-approved` comment), you are PROHIBITED from:
- Relaxing assertions (changing === to includes, removing checks)
- Removing test cases
- Modifying expected values to match ythis implementation
- Adding skip/pending/xfail markers

If tests fail, fix the PRODUCTION code. Never the approved test.
