# ADR-017: React Portal for Factory Observability UX

## Status
Accepted

## Date
2026-05-07

## Context

The Autonomous Code Factory operates headless — agents ingest tasks, run the FDE protocol, and deliver PRs without human intervention. But human stakeholders (PM, Staff Engineer, Tech Lead) need to understand **what the factory decided and why** without tailing CloudWatch logs.

### Previous State

The original dashboard was a monolithic `index.html` (500+ lines) with:
- Zero external dependencies (per ADR-011 YAGNI principle and SEC 6)
- Three flat panels (agents, flow, logs)
- No navigation between sections
- No structured reasoning visibility
- No gate decision transparency
- No internationalization
- No accessibility compliance

### Why ADR-011 (YAGNI) No Longer Applies

ADR-011 established the principle: "Don't add complexity until proven necessary." The threshold has been crossed:

| ADR-011 Assumption | Current Reality | Threshold Crossed |
|-------------------|-----------------|-------------------|
| Single operator (Staff Engineer) | 3 personas (PM, Staff Engineer, Tech Lead) | Multi-persona UX requires navigation |
| English-only | 3 markets (en-US, pt-BR, es) | i18n requires framework support |
| No accessibility requirement | Enterprise adoption requires WCAG AA | Assistive tech validation requires semantic HTML + ARIA |
| Simple 3-panel view | 5 views (Pipeline, Agents, Reasoning, Gates, Health) | Component reuse across views requires framework |
| Read-only status | Structured reasoning API with typed contracts | Type safety requires TypeScript |

The monolithic approach was correct for a prototype. It is incorrect for an enterprise-grade observability layer serving multiple personas across multiple languages with accessibility compliance.

### Design Space Explored

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| Keep monolithic HTML + ES modules | Zero deps, simple deploy | Can't scale to 5+ views, no type safety, no i18n framework, no component reuse | Rejected (proven insufficient) |
| Web Components (native) | No framework, standards-based | No ecosystem for i18n, accessibility testing harder, no type safety | Rejected |
| Svelte/SvelteKit | Small bundle, good DX | Smaller ecosystem, fewer enterprise adopters, less hiring pool | Rejected |
| Vue 3 + Vite | Good DX, smaller than React | Smaller ecosystem for enterprise tooling | Rejected |
| **React + Vite + Tailwind + TypeScript** | Largest ecosystem, best accessibility tooling (react-aria, axe-core), TypeScript for API contracts, Tailwind for design tokens, Vite for fast builds | npm dependencies (supply chain risk), build step required | **Selected** |

### Key Constraints

- **Supply chain risk mitigation**: `package-lock.json` pinned, `npm audit` in CI, no CDN-hosted libraries (all bundled)
- **Build output is static**: Vite produces static HTML/CSS/JS — same S3+CloudFront deploy pattern as before
- **No runtime server**: No Node.js server, no SSR — pure client-side SPA
- **API contract typed**: TypeScript interfaces enforce the structured event schema at compile time

## Decision

### Architecture: React SPA with Vite Build Pipeline

```
infra/portal-src/          (SOURCE — React + TypeScript + Tailwind)
    ↓ npm run build (Vite)
infra/dashboard/           (BUILD OUTPUT — static HTML/CSS/JS)
    ↓ scripts/deploy-dashboard.sh
S3 bucket → CloudFront     (DEPLOYED — edge-cached static site)
```

### Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | React 18 | Largest ecosystem, best accessibility tooling, TypeScript-first |
| Build tool | Vite | Fast builds (<3s), native ESM, tree-shaking |
| Styling | Tailwind CSS | Design tokens as utility classes, no CSS-in-JS runtime cost |
| Icons | Lucide React | Tree-shakeable, accessible (aria-label support), MIT license |
| i18n | i18next + react-i18next | Industry standard, supports 3 languages (en-US, pt-BR, es) |
| Type safety | TypeScript (strict mode) | Compile-time validation of API contracts |

### Portal Architecture (5 Views)

| View | Route | Persona | What It Shows |
|------|-------|---------|---------------|
| Pipeline | `#pipeline` | PM | Task flow with status dots, project filter |
| Agents | `#agents` | Staff Engineer | Agent cards with stage timeline, progress |
| Reasoning | `#reasoning` | PM + Tech Lead | Structured CoT timeline with phase/gate metadata |
| Gates | `#gates` | Tech Lead | Gate pass/fail decisions with criteria |
| Health | `#health` | Staff Engineer | DORA metrics + system diagnostics |

### Structured Reasoning API

New endpoint: `GET /status/tasks/{task_id}/reasoning`

Returns the full chain-of-thought timeline for a single task, including:
- Phase transitions (intake → reconnaissance → engineering → completion)
- Gate decisions (pass/fail with criteria evaluated)
- Autonomy level and confidence assessment
- Context summaries (max 300 chars, never raw code or customer data)

### Data Classification for Exposed Events

| Field | Classification | Exposure Rule |
|-------|---------------|---------------|
| `msg` (max 200 chars) | Operational | Safe to expose — describes pipeline actions |
| `phase`, `gate_name`, `gate_result` | Operational | Safe to expose — pipeline metadata |
| `criteria` (max 150 chars) | Operational | Safe to expose — gate evaluation criteria |
| `context` (max 300 chars) | Operational | Safe to expose — summarized reasoning |
| `autonomy_level`, `confidence` | Operational | Safe to expose — pipeline configuration |
| File paths, module names | Customer Confidential | **NEVER in events** — orchestrator must not emit |
| Source code, diffs | Customer Confidential | **NEVER in events** — only in PR delivery |
| Credentials, tokens | Secret | **NEVER in events** — ADR-014 fetch-use-discard |

**Security control**: The orchestrator is the sole event emitter. It constructs event messages from pipeline state, never from raw code or customer input. No automated sanitization layer exists — the control is architectural (emitter discipline), not filtering.

### i18n Governance

| Aspect | Decision |
|--------|----------|
| Supported languages | en-US (primary), pt-BR, es |
| Translation source | Inline in `src/i18n.ts` (current: ~30 strings per language) |
| Maintenance owner | Ops team |
| Scaling threshold | Extract to JSON resource files when >100 strings or >5 languages |
| Fallback | en-US (missing keys render in English) |

### WCAG Compliance

| Aspect | Decision |
|--------|----------|
| Target level | WCAG 2.1 AA |
| Validation method | Assistive technology testing (screen readers) |
| Semantic HTML | All views use semantic elements (`<nav>`, `<main>`, `<section>`, `<article>`) |
| ARIA attributes | All interactive elements have `aria-label` or `aria-describedby` |
| Color contrast | Design tokens enforce 4.5:1 minimum ratio (AA) |
| Keyboard navigation | All views navigable via Tab/Enter/Escape |
| Focus management | Route changes move focus to view title |

### Supersession of ADR-011 (Partial)

ADR-011 (Multi-Cloud Adapter YAGNI) established the principle of not adding complexity until proven necessary. This ADR **partially supersedes** ADR-011 for the observability layer only:

- **ADR-011 still applies to**: infrastructure code, agent code, pipeline modules, Terraform
- **ADR-011 is superseded for**: the user-facing portal, where multi-persona UX, i18n, and accessibility requirements have crossed the "proven necessary" threshold

The portal is the only component where npm dependencies are acceptable. All other factory components remain zero-dependency Python.

## Consequences

### Positive
- Multi-persona UX enables PM, Staff Engineer, and Tech Lead to each have their own journey
- TypeScript catches API contract drift at compile time (not runtime)
- i18n enables adoption in 3 markets without code changes
- WCAG AA compliance enables enterprise adoption in accessibility-regulated environments
- Component reuse across 5 views reduces maintenance burden vs 5 separate HTML files
- Vite build is <3s — faster than the old manual editing cycle

### Negative
- npm dependencies introduce supply chain risk (mitigated by lockfile + audit)
- Build step required before deploy (mitigated by `scripts/deploy-dashboard.sh` handling it)
- Developers need React/TypeScript knowledge to modify the portal
- Bundle size (~200KB gzipped) larger than the old monolith (~15KB)
- Two source locations to understand: `portal-src/` (source) vs `dashboard/` (output)

### Risks
- npm supply chain attack → mitigated by pinned versions, `npm audit`, no CDN
- React major version upgrade → mitigated by Vite's framework-agnostic build
- i18n string drift between languages → mitigated by TypeScript key enforcement
- Accessibility regression → mitigated by automated axe-core checks in CI (future)

## Related

- **ADR-011** — Multi-Cloud Adapter YAGNI (partially superseded for portal layer)
- **ADR-009** — AWS Cloud Infrastructure (CloudFront + S3 hosting)
- **ADR-014** — Secret Isolation (credentials never in events)
- **Design Doc** — `docs/design/portal_design_doc.md` (full implementation details)
- **Import Plan** — `docs/design/import_portal_plan.md` (migration procedure)
- **WA OPS 3** — Know your workload (observability for operators)
- **WA SEC 6** — Protect compute (supply chain risk assessment)
- **WA PERF 1** — Select appropriate resource types
