# How to Write Specs That the Factory Executes Well

> Training Guide — Activity 3.21

## Why This Matters

The Autonomous Code Factory executes tasks from specifications. The quality of the spec directly determines the quality of the output. A well-written spec passes gates on the first attempt; a vague spec triggers multiple rejection cycles, wasting time and increasing toil.

This guide teaches you how to write specs that the factory understands, executes correctly, and delivers on the first pass.

---

## The Three Pillars of a Good Spec

### 1. User Value Statement

Every spec must start with a clear statement of **who** benefits and **what** value they receive.

**Good:**
```
As a platform engineer, I need a health-check endpoint that returns
service status so that our monitoring system can detect outages within 30 seconds.
```

**Bad:**
```
Add a health check endpoint.
```

The good example tells the factory:
- Who cares (platform engineer)
- What they need (health-check endpoint with status)
- Why it matters (monitoring detects outages in 30s)

This context enables the factory to make correct trade-off decisions autonomously.

### 2. Acceptance Criteria

Acceptance criteria define **done**. They must be specific, testable, and unambiguous.

**Good:**
```
Acceptance Criteria:
- GET /health returns 200 with JSON body {"status": "healthy", "version": "x.y.z"}
- Response time < 100ms at p99
- Returns 503 if database connection fails
- Includes dependency health: database, cache, message queue
- No authentication required on this endpoint
```

**Bad:**
```
Acceptance Criteria:
- Endpoint works correctly
- Good performance
- Handles errors
```

Rules for acceptance criteria:
- Each criterion is independently verifiable
- Include specific values (status codes, thresholds, formats)
- State what happens in failure cases
- Mention security/auth requirements explicitly

### 3. Context Provision

Provide the factory with context it cannot infer from the codebase alone.

**Good:**
```
Context:
- This service uses FastAPI (see src/main.py)
- Health checks are consumed by AWS ALB target group health checks
- Database connection pool is managed by src/db/pool.py
- Existing pattern: see src/routes/readiness.py for similar endpoint
- Constraint: Must not import any business logic modules
```

**Bad:**
```
Context:
- It's a Python service
```

Useful context includes:
- Which existing patterns to follow
- External consumers of this feature
- Constraints that aren't obvious from code
- Related files the factory should read

---

## Examples: Good vs Bad Specs

### Example 1: API Endpoint

**❌ Bad Spec:**
```
Title: Add user search
Description: Users should be able to search for other users.
```

**✅ Good Spec:**
```
Title: Add user search endpoint with pagination

User Value: As a team lead, I need to search for team members by name or email
so I can quickly add them to projects without knowing their exact username.

Acceptance Criteria:
- GET /api/v1/users/search?q={query}&page={n}&size={n}
- Searches across: display_name, email, username fields
- Case-insensitive partial matching
- Returns paginated results (default page_size=20, max=100)
- Response includes: id, display_name, email, avatar_url
- Empty query returns 400 with descriptive error
- Requires authenticated session (existing auth middleware)
- Results exclude deactivated users
- Response time < 200ms for datasets up to 10k users

Context:
- Follow existing search pattern in src/routes/project_search.py
- User model is in src/models/user.py
- Use existing SQLAlchemy full-text search (see src/db/search.py)
- Index already exists on users(display_name, email)
```

### Example 2: Bug Fix

**❌ Bad Spec:**
```
Title: Fix the timeout bug
Description: Sometimes requests time out.
```

**✅ Good Spec:**
```
Title: Fix connection pool exhaustion causing request timeouts

User Value: As an end user, I expect API responses within 2 seconds
instead of the current 30-second timeouts occurring during peak load.

Root Cause: Connection pool (max_size=5) is exhausted when concurrent
requests exceed 5. Connections are not released on exception paths
in src/services/payment_service.py lines 45-67.

Acceptance Criteria:
- All database connections released in finally blocks
- Connection pool size increased to 20 (matching ALB max connections)
- Add connection pool metrics (active, idle, waiting)
- Existing test_payment_service.py tests continue to pass
- New test: concurrent requests (10x) complete without timeout

Context:
- Pool config is in src/config/database.py
- The bug manifests under load (>5 concurrent requests)
- Related: see incident report in docs/incidents/2024-01-15.md
```

---

## Common Rejection Patterns and How to Avoid Them

### 1. "Insufficient acceptance criteria"

**Why rejected:** The gate cannot determine when the task is done.

**Fix:** Add specific, testable criteria with concrete values.

### 2. "Ambiguous scope"

**Why rejected:** The spec could be interpreted multiple ways.

**Fix:** Be explicit about what IS and IS NOT in scope. Use "Out of scope:" section.

### 3. "Missing error handling specification"

**Why rejected:** The spec only describes the happy path.

**Fix:** Always specify behavior for: invalid input, missing data, service failures, auth failures.

### 4. "No user value statement"

**Why rejected:** The factory cannot validate that the implementation serves a real need.

**Fix:** Start every spec with "As a [role], I need [thing] so that [value]."

### 5. "Conflicting requirements"

**Why rejected:** Two acceptance criteria contradict each other.

**Fix:** Review criteria for logical consistency. If trade-offs exist, state the priority.

### 6. "Insufficient context for autonomous execution"

**Why rejected:** The factory would need to guess about patterns, constraints, or conventions.

**Fix:** Point to existing patterns, state constraints, mention related files.

---

## Spec Checklist

Before submitting a spec, verify:

- [ ] User value statement with role, need, and benefit
- [ ] 3+ specific, testable acceptance criteria
- [ ] Error/edge cases addressed
- [ ] Security/auth requirements stated (even if "none needed")
- [ ] Performance expectations included (if applicable)
- [ ] Context section with relevant files and patterns
- [ ] Scope boundaries clear (what's NOT included)
- [ ] No ambiguous terms ("fast", "good", "proper", "correct")

---

## Quick Reference: Spec Template

```markdown
## Title: [Concise, specific title]

### User Value
As a [role], I need [specific capability] so that [measurable benefit].

### Acceptance Criteria
- [Specific, testable criterion with concrete values]
- [Error case handling]
- [Performance requirement]
- [Security requirement]

### Context
- Pattern to follow: [file path]
- Consumed by: [external system/user]
- Constraints: [non-obvious limitations]
- Related: [relevant files, docs, or decisions]

### Out of Scope
- [Explicitly excluded items]
```

---

## Further Reading

- [Understanding Gates](./understanding-gates.md) — What each gate checks
- [Onboarding Checklist](./onboarding-checklist.md) — Getting started with the factory
- [ADR-002: Spec as Control Plane](../adr/ADR-002-spec-as-control-plane.md) — Why specs drive everything
