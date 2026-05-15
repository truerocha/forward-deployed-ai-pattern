# Cloudscape Design UX Pattern — Code Factory Portal

> Version: 1.0 | Date: 2026-05-14 | Author: FDE Squad
> Status: Accepted | Ref: ADR-031

## Purpose

This document defines the UX pattern extraction and design guidance for any project that wants to align with the Code Factory portal experience. It codifies the decisions made during the Cloudscape migration and serves as the canonical reference for building consistent observability dashboards using AWS Cloudscape Design System.

## Design Philosophy

The portal follows the **Cloudscape Service Dashboard** pattern from cloudscape.design/patterns/general/service-dashboard/:

- **Monitor**: Users monitor overall system health and track trends
- **Investigate**: Users filter and drill down to root causes
- **Be informed**: Dashboard provides guidance and service updates

We extend this with **persona-based filtering** — each role (PM, SWE, SRE, Architect, Staff) sees a curated subset of dashboard items relevant to their decision-making context.

---

## Shell Architecture

```
TopNavigation (identity + utilities)
  AppLayout
    SideNavigation (7 views + Observability)
    BreadcrumbGroup
    Content (view-specific)
```

### Components Used

| Shell Element | Cloudscape Component | Props |
|---------------|---------------------|-------|
| Top bar | TopNavigation | identity, utilities, i18nStrings |
| Side panel | SideNavigation | header, items, activeHref, onFollow |
| Layout | AppLayout | navigation, breadcrumbs, content, toolsHide, headerSelector |
| Breadcrumbs | BreadcrumbGroup | items |
| i18n wrapper | I18nProvider | locale, messages |

### Navigation Pattern

- Hash-based routing (#pipeline, #agents, etc.)
- SideNavigation.onFollow prevents default and calls window.location.hash = view
- AppLayout.headerSelector="#top-nav" offsets content below the sticky TopNavigation

---

## Dashboard Item Pattern

Every card/widget follows the Cloudscape Dashboard Item structure:

```tsx
<Container
  header={
    <Header
      variant="h3"
      description="Subtitle or context"
      actions={<Badge color="blue">STATUS</Badge>}
    >
      Card Title
    </Header>
  }
  footer={
    <Box fontSize="body-s" color="text-body-secondary">
      Footer metadata
    </Box>
  }
>
  {/* Content: one visualization type, max two combined */}
</Container>
```

### Rules

1. One goal per card — each card serves one definitive user goal
2. Max 2 visualization types — do not combine table + chart + list
3. No long logs in cards — use a dedicated view (Reasoning) for log streams
4. Empty state — always provide: StatusIndicator type="pending"
5. Footer — always include metadata (count, timestamp, or context)
6. Header actions — use Badge for status, not buttons (cards are read-only)

### Content Primitives

| Data Type | Cloudscape Component | When to Use |
|-----------|---------------------|-------------|
| Key metrics (2-4 values) | ColumnLayout variant="text-grid" | Overview cards |
| Labeled pairs | KeyValuePairs | Configuration, details |
| Progress/completion | ProgressBar | Task progress, budget usage |
| Status with label | StatusIndicator | Health, gate results |
| Categorization | Badge | Severity, tier, level |
| Tabular data | Table (in dedicated view only) | Logs, task lists |
| Selection | SegmentedControl | Level/mode filtering |
| Custom viz | Inline SVG with CSS variables | Radar, sparkline, gauge |

---

## Grid Layout

The Observability view uses Cloudscape Grid with persona-filtered cards:

```tsx
<Grid gridDefinition={cards.map(() => ({ colspan: { l: 6, m: 6, default: 12 } }))}>
  {cards.map(card => <div key={name}>{card}</div>)}
</Grid>
```

### Sizing Rules

| Size | Grid Columns | Use For |
|------|-------------|---------|
| Medium (default) | 6 of 12 (2 per row) | Most dashboard items |
| Full width | 12 of 12 | Tables, timelines |
| Small | 4 of 12 (3 per row) | Simple status indicators |

---

## Persona Routing

The Observability view uses Cloudscape Tabs for persona selection:

```tsx
<Tabs
  activeTabId={persona}
  onChange={({ detail }) => onPersonaChange(detail.activeTabId)}
  tabs={[
    { id: 'PM', label: 'Product Manager', content: renderCards() },
    { id: 'SWE', label: 'Software Engineer', content: renderCards() },
  ]}
/>
```

### Persona Card Matrix

| Card | PM | SWE | SRE | Architect | Staff |
|------|:--:|:---:|:---:|:---------:|:-----:|
| DORA Sun | x | | x | | x |
| DORA Metrics | x | | x | | x |
| Cost Breakdown | x | | x | | x |
| Value Stream | x | | | x | x |
| Trust Score | x | | | | x |
| Net Friction | x | | | x | |
| Live Timeline | | x | | | |
| Gate Feedback | | x | | | |
| Squad Execution | | x | | | x |
| Branch Evaluation | | x | | | |
| Human Input | | x | | | |
| Data Quality | | | x | x | |
| Gate History | | | x | | |
| Maturity Radar | | | | x | x |
| Brain Simulation | | | | x | x |
| Conductor Plan | | x | | x | |

---

## Dark Mode

### Implementation

```tsx
// Toggle
document.body.classList.toggle('awsui-dark-mode');

// FOUC prevention (in head before any CSS loads)
(function() {
  var theme = localStorage.getItem('fde-theme');
  if (!theme) theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  if (theme === 'dark') document.documentElement.classList.add('awsui-dark-mode');
})();
```

### Smooth Transition

```css
body { transition: background-color 0.3s ease, color 0.3s ease; }
body * { transition: background-color 0.2s ease, border-color 0.2s ease, color 0.15s ease; }
```

### Custom SVG Adaptation

SVGs must use Cloudscape CSS variables for theme-awareness:

```
stroke="var(--color-border-divider-default, #414d5c)"  /* grid lines */
fill="var(--color-background-container-content, white)" /* backgrounds */
stroke="#FF9900"                                         /* accent (constant) */
```

---

## Logo Pattern

Dual-mode SVG logos sized for the TopNavigation identity slot (28x28px):

| Mode | File | Design |
|------|------|--------|
| Dark | factory-logo-dark.svg | Squid Ink fill, white strokes, orange accent |
| Light | factory-logo-light.svg | White fill, Squid Ink strokes, orange accent |

The logo uses AWS Architecture Icon visual vocabulary: rounded square container, dashed circle (gear ring), code brackets as primary symbol, forward slash as pipeline flow indicator.

---

## Color System

### Primary Palette

| Token | Value | Usage |
|-------|-------|-------|
| Squid Ink | #232F3E | Navigation, dark backgrounds |
| Smile Orange | #FF9900 | Accent only (never body text on white) |
| White | #FFFFFF | Light backgrounds, reverse text |

### Status Colors (StatusIndicator)

| Type | Meaning | Use |
|------|---------|-----|
| success | Passed, healthy, complete | Gate pass, task complete |
| error | Failed, critical | Gate fail, task error |
| warning | Degraded, conditional | Conditional pass, threshold |
| in-progress | Running, active | Task executing, agent working |
| pending | Waiting, no data | Empty states, queued |
| stopped | Idle, stable | No change, flat trend |

---

## Typography

Cloudscape uses Open Sans (loaded via global-styles). No custom font imports needed.

| Element | Cloudscape Variant | Size |
|---------|-------------------|------|
| Page title | Header variant="h1" | 28px |
| Section title | Header variant="h2" | 22px |
| Card title | Header variant="h3" | 18px |
| Key label | Box variant="awsui-key-label" | 12px uppercase |
| Large value | Box variant="awsui-value-large" | 42px |
| Medium value | Box fontSize="heading-m" | 20px |
| Body | Box (default) | 14px |
| Secondary | Box color="text-body-secondary" | 14px muted |
| Code | Box variant="code" | 13px monospace |
| Footer | Box fontSize="body-s" | 12px |

---

## Build Configuration

### Vite Setup

```ts
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { chunkSizeWarningLimit: 800 },
});
```

### Why No Code Splitting

Cloudscape components share React context internally. Manual chunk splitting causes React.createContext to be undefined when chunks load out of order. Single bundle eliminates this class of errors. The 1.2 MB JS bundle (360 KB gzipped) is acceptable for an internal tool.

### Dependencies

- @cloudscape-design/components ^3
- @cloudscape-design/global-styles ^1
- @cloudscape-design/design-tokens ^3
- @cloudscape-design/collection-hooks ^1

### Removed (do not re-add)

- tailwindcss, autoprefixer, postcss
- tailwind.config.js, postcss.config.js
- Custom CSS variables (--bg-main, --text-main)

---

## Deploy Pipeline

```
infra/portal-src/     SOURCE (React + TypeScript)
  npm run build
infra/portal-src/dist/  BUILD OUTPUT
  deploy-dashboard.sh --build
infra/dashboard/      DEPLOY STAGING
  aws s3 sync (SSE-S3)
S3 bucket/dashboard/  PRODUCTION
  CloudFront (OAC)
User browser          SERVED
```

---

## Accessibility Compliance

| Requirement | Implementation |
|-------------|---------------|
| WCAG 2.1 AA contrast | Cloudscape design tokens enforce 4.5:1 minimum |
| Keyboard navigation | enableKeyboardNavigation on Table/Cards |
| Screen reader | Semantic HTML via Cloudscape components |
| Focus management | focus-visible outline: 2px solid #FF9900 |
| ARIA labels | ariaLabels prop on AppLayout, TopNavigation |
| Color not sole indicator | StatusIndicator uses icon + text + color |

---

## Anti-Patterns (Lessons Learned)

| Anti-Pattern | What Happened | Fix |
|-------------|---------------|-----|
| Manual chunk splitting with React | React.createContext undefined at runtime | Single bundle, no manualChunks |
| Complex SVG logo at 28px | Unreadable text, invisible in dark mode | Simple geometric icon with dual variants |
| data-theme attribute for dark mode | Does not integrate with Cloudscape tokens | Use awsui-dark-mode class on body |
| Tailwind utilities inside Cloudscape | Conflicting styles, broken dark mode | Remove Tailwind entirely |
| height: 100% without min-height | AppLayout renders with zero height | Add min-height: 100vh |
| key prop on Cloudscape components | TypeScript error (not in component props) | Wrap in div with key |

---

## Reuse Checklist

For any new project adopting this pattern:

1. Install: @cloudscape-design/components, global-styles, design-tokens, collection-hooks
2. Import @cloudscape-design/global-styles/index.css in your entry point
3. Set html, body, #root { height: 100%; min-height: 100vh; margin: 0; padding: 0; }
4. Use AppLayout + TopNavigation + SideNavigation shell
5. Use Container + Header variant="h3" for every dashboard card
6. Use StatusIndicator for all status displays (never raw colored text)
7. Use awsui-dark-mode class for dark mode (not custom CSS variables)
8. Do NOT use manualChunks in Vite — single bundle is safer
9. Add FOUC prevention script in head before CSS loads
10. Create dual-mode logo SVGs (28x28, simple geometry)
