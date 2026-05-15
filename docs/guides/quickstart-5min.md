# 5-Minute Quickstart — See the Factory Work

> No tokens. No cloud accounts. No configuration.
> Just clone, run, and see what the Autonomous Code Factory produces.

---

## What You'll See

In 5 minutes you'll:
1. Run the test suite and confirm the pipeline works end-to-end
2. See how the Evidence Extractor detects patterns in code
3. See how findings flow through the pipeline to produce a review
4. Understand the project structure enough to explore further

---

## Prerequisites

| Tool | Check | Install |
|------|-------|---------|
| Python 3.10+ | `python3 --version` | [python.org](https://www.python.org/downloads/) or `brew install python` |
| Git | `git --version` | `brew install git` |

That's it. No tokens, no Docker, no AWS, no Node.js needed for this path.

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/truerocha/forward-deployed-engineer-pattern.git
cd forward-deployed-engineer-pattern
```

---

## Step 2: Run the Test Suite

```bash
# Full suite — 1078+ tests, all self-contained
python3 -m pytest tests/ -v --tb=short
```

You'll see tests organized by layer:

| Test Group | What It Validates |
|-----------|-------------------|
| `tests/test_knowledge_*` | WAF corpus integrity, mapping consistency |
| `tests/test_contract_*` | Cross-layer data contracts (6 invariants) |
| `tests/test_portal_*` | Portal UI rendering logic |
| `tests/test_facts_*` | Evidence extraction patterns |
| `tests/test_publish_*` | Finding generation and sanitization |

---

## Step 3: Run Scoped Tests to Explore Layers

```bash
# Knowledge layer — see how WAF mappings work
python3 scripts/run_tests.py --scope knowledge

# Contract tests — see the 6 cross-layer invariants
python3 scripts/run_tests.py --scope contract

# Portal UI — see how findings become HTML
python3 scripts/run_tests.py --scope portal-ui
```

---

## Step 4: Understand the Pipeline

The core pipeline transforms code into a Well-Architected review:

```
Your Code
  → Evidence Extractor (detects 53 patterns via regex)
    → Evidence Catalog (normalizes + deduplicates)
      → Deterministic Reviewer (maps evidence to WAF questions)
        → Publish Tree (scores severity, adds recommendations)
          → Publish Sanitizer (produces clean JSON artifacts)
            → Portal (renders HTML the user reads)
```

Key files to explore:

| File | Lines | What It Does |
|------|-------|-------------|
| `src/pipeline/facts_extractor.py` | ~992 | Detects code patterns (IaC, security, reliability) |
| `src/pipeline/evidence_catalog.py` | ~625 | Normalizes raw matches into structured evidence |
| `src/pipeline/deterministic_reviewer.py` | ~387 | Maps evidence to WAF best practice questions |
| `src/pipeline/publish_tree.py` | ~2001 | Generates findings with severity and recommendations |
| `src/pipeline/publish_sanitizer.py` | ~1527 | Produces final JSON artifacts |

---

## Step 5: Explore the Knowledge Layer

The factory's intelligence comes from structured knowledge, not just code:

```bash
# See how WAF pillars are defined
head -50 src/knowledge/waf_security_corpus.py

# See how evidence maps to WAF questions
head -30 config/mappings/fact_type_question_map.yaml

# See recommendation templates
head -30 config/mappings/recommendation_templates.yaml
```

---

## What's Next?

| If you want to... | Go to... |
|-------------------|----------|
| Understand the architecture | [Design Document](../architecture/design-document.md) |
| See why decisions were made | [33 ADRs](../adr/) |
| Deploy the factory to your project | [Adoption Guide](fde-adoption-guide.md) |
| Deploy cloud infrastructure (AWS) | [Deployment Setup](deployment-setup.md) |
| See feature flow diagrams | [15 Flows](../flows/README.md) |

---

## Key Concepts (30-second version)

| Concept | One-liner |
|---------|-----------|
| **FDE** | An AI agent that knows your project's architecture before writing code |
| **Factory** | Orchestrates multiple FDEs across your projects |
| **Spec** | A structured description of what to build (the human writes this) |
| **Hook** | An automated quality gate that fires on events (file save, task start/end) |
| **Steering** | Config that gives the AI context about your project |
| **Régua** | The quality standard — what "good" looks like for this project |
| **L2/L3/L4** | How many gates are active: L2=basic, L3=standard, L4=full governance |
| **ALM** | Your project board (GitHub Projects, Asana, or GitLab) |
| **MCP** | How AI agents connect to external tools (GitHub API, etc.) |

---

## FAQ

**Q: Do the scripts connect to live cloud resources?**
A: No. The test suite is fully self-contained. The deployment scripts (`pre-flight-fde.sh`, etc.) only connect to resources you explicitly configure — and cloud deployment defaults to "no".

**Q: Can I use this without Kiro IDE?**
A: Yes. The pattern exports rules to 6 platforms: Kiro, Q Developer, Cursor, Cline, Claude Code, and Copilot. See `.amazonq/`, `.cursor/`, `.claude/`, and `.clinerules/` directories.

**Q: What if I just want the hooks and steerings for my project?**
A: Run `bash scripts/provision-workspace.sh --project` from your project directory. It copies the factory template without any cloud setup.

**Q: Is AWS required?**
A: No. AWS is only needed if you want headless agent execution (agents running without your machine). Local-only mode is the default and fully functional.
