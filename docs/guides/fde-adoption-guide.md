# Forward Deployed Engineer — Adoption Guide

> How to onboard a new project into the Autonomous Code Factory.
> Estimated time: 30 minutes for first project, 10 minutes for subsequent.

---

## Prerequisites

| Requirement | Check Command | Install |
|-------------|--------------|---------|
| Kiro IDE or CLI | `kiro --version` | [kiro.dev](https://kiro.dev) |
| Git | `git --version` | `brew install git` |
| Node.js (for MCP) | `node --version` | `brew install node` |
| GitHub token | `echo $GITHUB_TOKEN` | GitHub Settings → Developer Settings → Personal Access Tokens |
| Docker (for ship-readiness) | `docker --version` | [docker.com](https://docker.com) |
| Playwright (for UI projects) | `npx playwright --version` | `npx playwright install` |

Optional:
- GitLab token: `echo $GITLAB_TOKEN` (if using GitLab mirror)
- Asana token: `echo $ASANA_TOKEN` (if using Asana for ALM)

## Step 1: Set Up Global Factory Infrastructure (One-Time)

This creates the universal laws and shared resources that ALL your projects inherit.

```bash
# Run the provision script from the factory template repo
git clone https://github.com/truerocha/forward-deployed-engineer-pattern.git ~/factory-template
cd ~/factory-template
bash scripts/provision-workspace.sh --global
```

Or manually:

```bash
# 1. Global steerings (universal laws — loaded in every interaction)
mkdir -p ~/.kiro/steering
cp ~/factory-template/docs/global-steerings/agentic-tdd-mandate.md ~/.kiro/steering/
cp ~/factory-template/docs/global-steerings/adversarial-protocol.md ~/.kiro/steering/

# 2. Global MCP config (shared credentials)
mkdir -p ~/.kiro/settings
cat > ~/.kiro/settings/mcp.json << 'MCP'
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      },
      "disabled": false,
      "autoApprove": ["search_repositories", "get_file_contents", "list_issues", "get_issue"]
    }
  }
}
MCP

# 3. Global notes directory (cross-project insights)
mkdir -p ~/.kiro/notes/shared

# 4. Factory state file (human-maintained dashboard)
touch ~/.kiro/factory-state.md

# 5. Set environment variables (add to ~/.zshrc or ~/.bashrc)
echo 'export GITHUB_TOKEN="ghp_your_token_here"' >> ~/.zshrc
echo 'export GITLAB_TOKEN="glpat-your_token_here"' >> ~/.zshrc  # if using GitLab
source ~/.zshrc
```

## Step 2: Onboard a Project

```bash
# Run the provision script
cd ~/projects/my-project
bash ~/factory-template/scripts/provision-workspace.sh --project
```

Or manually:

```bash
# 1. Create factory structure
mkdir -p .kiro/{steering,hooks,specs/holdout,notes/project,notes/archive,meta,settings}

# 2. Copy hooks and steerings from template
cp ~/factory-template/.kiro/hooks/*.kiro.hook .kiro/hooks/
cp ~/factory-template/.kiro/steering/*.md .kiro/steering/
cp ~/factory-template/.kiro/specs/WORKING_MEMORY.md .kiro/specs/
cp ~/factory-template/.kiro/notes/README.md .kiro/notes/
cp ~/factory-template/.kiro/meta/feedback.md .kiro/meta/
cp ~/factory-template/.kiro/meta/refinement-log.md .kiro/meta/

# 3. IMPORTANT: Customize .kiro/steering/fde.md for YOUR project
# Open the file and replace:
#   - Pipeline chain → your project's data flow
#   - Module boundaries → your project's edges
#   - Régua → your project's quality standards
#   - Test infrastructure → your project's test commands
```

## Step 3: Choose Engineering Level

Enable hooks based on your project's needs:

| Level | When | Hooks to Enable |
|-------|------|----------------|
| **L2** | Single-module fixes, known scope | adversarial-gate, test-immutability, circuit-breaker |
| **L3** | Multi-module changes, features | All L2 + dor-gate, dod-gate, pipeline-validation, enterprise-backlog, enterprise-docs, ship-readiness, notes-consolidate, prompt-refinement |
| **L4** | Architecture changes | All L3 + enterprise-release, alternative-exploration |

To enable a hook, edit the `.kiro.hook` file and change `"enabled": false` to `"enabled": true`.

## Step 4: Your First Task

```
1. Write a spec:
   Create .kiro/specs/my-first-feature.md using the NLSpec format
   (see docs/blueprint/fde-blueprint-design.md §3.3 for template)

2. Add frontmatter:
   ---
   status: ready
   issue: "#123"
   level: L3
   ---

3. In Kiro chat:
   #fde Execute the spec in .kiro/specs/my-first-feature.md

4. The agent will:
   - DoR gate fires → validates readiness
   - Reconnaissance → maps affected modules
   - TDD → generates tests first, asks you to approve
   - Implementation → makes tests green
   - Adversarial gate → challenges each write
   - DoD gate → validates conformance

5. Review the completion report

6. Trigger ship-readiness:
   Click "FDE Ship-Readiness Validation" in Agent Hooks panel

7. If SHIP-READY, trigger release:
   Click "FDE Enterprise Release Manager" in Agent Hooks panel

8. Review the MR in GitHub/GitLab

9. Approve and merge
```

## Step 5: Daily Operations

```
Morning:
  - Update ~/.kiro/factory-state.md with current status of each project
  - Write/approve specs for today's work
  - Approve test contracts generated by agents

Midday:
  - Review MRs from completed tasks
  - Trigger ship-readiness for tasks ready to ship
  - Trigger releases for validated tasks

Afternoon:
  - Write observations in .kiro/meta/feedback.md
  - Plan next milestone specs
  - Trigger notes consolidation if >20 notes accumulated
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Hook not firing | `"enabled": false` in hook file | Change to `"enabled": true` |
| MCP not connecting | Token expired or not set | Check `echo $GITHUB_TOKEN`, regenerate if needed |
| Agent ignores steering | Steering not loaded | Type `#fde` in chat to load, or check `inclusion: manual` in frontmatter |
| Circuit breaker halts all operations | ENVIRONMENT error detected | Fix the infrastructure issue (Docker, ports, permissions), then retry |
| DoR gate blocks execution | Spec missing `status: ready` | Add YAML frontmatter with `status: ready` |
| Tests keep failing after 3 attempts | Agent stuck in loop | Check if it's an environment issue; review the circuit breaker output |

---

## Detailed Daily Rhythm (3 Projects in Parallel)

### Morning Block (09:00–10:00) — DISPATCH

```
09:00  Open ~/.kiro/factory-state.md
       Review: which projects have pending MRs? Which are blocked?
       Update status for each workspace.

09:10  PROJECT A (payment-service)
       Open Kiro IDE on ~/projects/payment-service
       Review yesterday's completion report in .kiro/specs/
       If MR pending: review in GitHub, approve or request changes
       If blocked: read circuit breaker output, fix environment issue
       If ready for next task: write spec for today's feature

09:25  PROJECT B (analytics-dashboard)
       Switch to ~/projects/analytics-dashboard workspace
       Same review cycle: completion report → MR → next spec

09:40  PROJECT C (infra-terraform)
       Switch to ~/projects/infra-terraform workspace
       Same review cycle

09:55  All specs written and marked status: ready
       Update ~/.kiro/factory-state.md with today's plan
```

### Midday Block (10:00–12:00) — EXECUTE + MONITOR

```
10:00  PROJECT A: #fde Execute the spec in .kiro/specs/payment-webhook.md
       Agent starts: DoR → Reconnaissance → TDD
       While agent works, switch to PROJECT B

10:05  PROJECT B: #fde Execute the spec in .kiro/specs/chart-performance.md
       Agent starts in this workspace
       Switch to PROJECT C

10:10  PROJECT C: #fde Execute the spec in .kiro/specs/vpc-refactor.md
       All 3 agents now working in parallel (separate Kiro windows or CLI)

10:30  Check back on PROJECT A
       Agent may have generated tests — review and approve
       Add // @human-approved to test files you've validated
       Agent continues to implementation

11:00  Check PROJECT B — same cycle
11:30  Check PROJECT C — same cycle

12:00  Lunch. Agents continue working if using Kiro CLI in background.
```

### Afternoon Block (14:00–16:00) — HARVEST + REFINE

```
14:00  Review completion reports from all 3 projects
       For each completed task:
       - Read the 5W2H summary
       - Check: did the DoD gate pass?
       - Check: any residual risks noted?

14:30  SHIP-READINESS
       For tasks that passed DoD:
       Click "FDE Ship-Readiness Validation" in Agent Hooks panel
       Wait for Docker E2E + holdout results
       If SHIP-READY: proceed to release
       If NOT READY: read failure details, decide if spec needs refinement

15:00  RELEASE
       For ship-ready tasks:
       Click "FDE Enterprise Release Manager" in Agent Hooks panel
       Agent creates semantic commit + opens MR
       Review MR in GitHub/GitLab
       Approve and merge

15:30  REFINE
       Write observations in .kiro/meta/feedback.md
       Examples:
       - "The adversarial gate caught a missing null check — good"
       - "Circuit breaker classified a test timeout as CODE when it was ENV"
       - "DoD gate didn't check accessibility — should add"

16:00  PLAN TOMORROW
       Write specs for tomorrow's tasks
       Update ~/.kiro/factory-state.md
```

### Weekly Block (Friday 16:00–17:00) — META

```
16:00  Trigger "FDE Prompt Refinement" hook
       Review the Factory Health Report
       Review suggested prompt improvements
       Apply approved changes to hooks/steerings

16:30  Trigger "FDE Notes Consolidation" hook
       Review archive candidates (notes >90 days)
       Review merge candidates (duplicate notes)
       Confirm or reject proposals

17:00  Update ~/.kiro/factory-state.md with weekly summary
       Plan next week's milestones
```

---

## Project Type Walkthroughs

### Onboarding a Next.js App

**Step 1: Provision**

```bash
cd ~/projects/my-nextjs-app
bash ~/factory-template/scripts/provision-workspace.sh --project
```

**Step 2: Customize `.kiro/steering/fde.md`**

Replace the pipeline chain with:

```markdown
## Pipeline Chain

Next.js Request → Middleware → Page/API Route → Server Components
  → Data Fetching (Prisma/tRPC) → Database
  → Client Components → Browser Renders → User Sees the Page

## Module Boundaries

| Edge | Producer | Consumer | What Transforms |
|------|----------|----------|-----------------|
| E1 | middleware.ts | page.tsx / route.ts | Auth context, headers, redirects |
| E2 | Server Components | Data layer (Prisma) | Props → database queries |
| E3 | Data layer | Server Components | Raw DB rows → typed domain objects |
| E4 | Server Components | Client Components | Server-rendered HTML + serialized props |
| E5 | Client Components | Browser | React hydration + interactivity |
| E6 | API routes | External consumers | JSON responses |

## Test Infrastructure

| Scope | Command | What It Validates |
|-------|---------|-------------------|
| Unit | npm test | Component logic, utilities |
| Integration | npm run test:integration | API routes + database |
| E2E | npx playwright test | Full user flows in browser |
| Type check | npx tsc --noEmit | Type safety |
| Lint | npm run lint | Code style + Next.js rules |
```

**Step 3: Ship-readiness setup**

Create `docker-compose.test.yml`:

```yaml
services:
  app:
    build: .
    ports: ["3000:3000"]
    environment:
      - DATABASE_URL=postgresql://test:test@db:5432/testdb
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: testdb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test"]
      interval: 5s
      timeout: 5s
      retries: 5
```

**Step 4: Holdout scenarios**

Create `.kiro/specs/holdout/navigation.feature`:

```gherkin
Feature: Core Navigation (Holdout — agent never sees this)

  Scenario: Unauthenticated user is redirected to login
    Given I am not logged in
    When I visit /dashboard
    Then I am redirected to /login

  Scenario: Authenticated user sees dashboard
    Given I am logged in as "test@example.com"
    When I visit /dashboard
    Then I see the dashboard heading
```

**Step 5: Enable hooks for L3 and start**

```bash
# Enable all L3 hooks (edit each file: "enabled": true)
# Then in Kiro:
#fde Execute the spec in .kiro/specs/user-auth.md
```

---

### Onboarding a Python Microservice

**Step 1: Provision**

```bash
cd ~/projects/my-python-service
bash ~/factory-template/scripts/provision-workspace.sh --project
```

**Step 2: Customize `.kiro/steering/fde.md`**

Replace the pipeline chain with:

```markdown
## Pipeline Chain

HTTP Request → FastAPI Router → Dependency Injection → Service Layer
  → Repository Layer → Database (PostgreSQL/Redis)
  → Response Serializer → HTTP Response → Client

## Module Boundaries

| Edge | Producer | Consumer | What Transforms |
|------|----------|----------|-----------------|
| E1 | Router (routes/) | Service (services/) | Validated request → business operation |
| E2 | Service | Repository (repos/) | Business logic → data access call |
| E3 | Repository | Database | ORM query → SQL execution |
| E4 | Repository | Service | DB rows → domain models |
| E5 | Service | Router | Domain result → response schema |
| E6 | Router | Client | Pydantic model → JSON response |

## Test Infrastructure

| Scope | Command | What It Validates |
|-------|---------|-------------------|
| Unit | pytest tests/unit/ | Service logic, utilities |
| Integration | pytest tests/integration/ | API + database (testcontainers) |
| E2E | pytest tests/e2e/ | Full request/response cycles |
| Type check | mypy src/ | Type safety |
| Lint | ruff check src/ | Code style |
| BDD | pytest --bdd tests/bdd/ | Behavioral scenarios |
```

**Step 3: Ship-readiness setup**

Create `docker-compose.test.yml`:

```yaml
services:
  app:
    build: .
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://test:test@db:5432/testdb
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: testdb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test"]
      interval: 5s
      timeout: 5s
      retries: 5
  redis:
    image: redis:7
  test-runner:
    build:
      context: .
      dockerfile: Dockerfile.test
    depends_on:
      app:
        condition: service_started
    command: pytest tests/e2e/ -v
```

**Step 4: Holdout scenarios**

Create `.kiro/specs/holdout/health.feature`:

```gherkin
Feature: Service Health (Holdout — agent never sees this)

  Scenario: Health endpoint returns OK
    Given the service is running
    When I GET /health
    Then the response status is 200
    And the body contains "status": "healthy"

  Scenario: Service handles database unavailability
    Given the database is down
    When I GET /health
    Then the response status is 503
    And the body contains "database": "unavailable"
```

**Step 5: BDD setup**

Create `tests/bdd/conftest.py`:

```python
import pytest
from pytest_bdd import given, when, then, parsers
from httpx import AsyncClient
from app.main import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
```

**Step 6: Enable hooks for L3 and start**

```bash
# Enable all L3 hooks
# Then in Kiro:
#fde Execute the spec in .kiro/specs/payment-webhook.md
```

---

## Extended Troubleshooting

| # | Problem | Symptoms | Cause | Fix |
|---|---------|----------|-------|-----|
| 1 | Hook not firing | Agent writes without adversarial challenge | `"enabled": false` in hook file | Edit hook file: change to `"enabled": true` |
| 2 | MCP not connecting | "No MCP configured" in hook output | Token expired or env var not set | Run `echo $GITHUB_TOKEN` — if empty, set it in `~/.zshrc` and `source ~/.zshrc` |
| 3 | Agent ignores steering | Agent doesn't mention pipeline chain or module boundaries | Steering not loaded in chat | Type `#fde` at the start of your message to load the steering |
| 4 | Circuit breaker halts all operations | Agent reports ENVIRONMENT ERROR on every command | Real infrastructure issue (Docker down, port in use) | Fix the infra issue first: restart Docker, stop process on port, etc. |
| 5 | DoR gate blocks execution | "Spec not marked as READY" | Missing YAML frontmatter | Add `---\nstatus: ready\n---` at the top of the spec file |
| 6 | Tests keep failing after 3 attempts | Agent reports "3 approaches failed, rolling back" | Problem may be too complex for current spec | Refine the spec: add more constraints, break into smaller tasks |
| 7 | Ship-readiness Docker timeout | "DOCKER TIMEOUT — containers failed to start" | Docker Compose health checks failing | Check `docker compose logs` manually; fix Dockerfile or health check |
| 8 | Agent modifies approved tests | Test immutability gate not catching | Hook not enabled, or test file missing `@human-approved` marker | Enable `fde-test-immutability` hook AND add `// @human-approved` to test file first line |
| 9 | Enterprise hooks skip silently | "NO MCP - SKIPPED" in output | MCP server not configured or disabled | Check `.kiro/settings/mcp.json` — ensure `"disabled": false` for the server you need |
| 10 | Notes directory growing too large | >50 notes, agent takes long to consult | No consolidation run | Trigger "FDE Notes Consolidation" hook to archive old notes |
| 11 | Agent creates MR on wrong branch | MR targets wrong base branch | Agent was on main when it started | Always create a feature branch before starting: `git checkout -b feat/my-feature` |
| 12 | Adversarial gate fires on doc changes | Gate challenges writes to README or docs | Gate fires on ALL writes by design | Agent should self-assess as "not a pipeline file — proceed". If too noisy, consider scoping `toolTypes` to specific file patterns |
| 13 | Working memory file grows too large | >30 lines, agent appends instead of replacing | Agent not following checkpoint protocol | The enterprise-docs hook clears working memory after each task. Ensure it's enabled. |
| 14 | Cross-workspace notes not visible | Agent in Project B can't see notes from Project A | Notes written to `.kiro/notes/project/` (local) instead of `~/.kiro/notes/shared/` (global) | Check the enterprise-docs hook output — generic insights should go to `~/.kiro/notes/shared/` |
| 15 | Provision script fails | "Not a git repository" error | Running `--project` outside a git repo | Run `git init` first, or `cd` into the correct project directory |
