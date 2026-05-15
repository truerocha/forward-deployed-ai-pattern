# ADR-031: Cloudscape UX Reformulation

## Status
Accepted

## Date
2026-05-14

## Context

The portal UX (infra/portal-src/) was built with React + Tailwind CSS + Lucide icons + framer-motion. While functional, it used a custom design system (bento cards, rail navigation, custom CSS variables) that diverged from the AWS Cloudscape Design System patterns used across AWS console experiences.

This created:
- Inconsistent UX vocabulary compared to other AWS tools stakeholders use daily
- Custom CSS maintenance burden (200+ utility classes, dark/light mode overrides)
- No alignment with cloudscape.design/patterns/ (Service Dashboard, Dashboard Items, Side Navigation)
- Accessibility gaps (custom components lacked ARIA patterns that Cloudscape provides natively)

## Decision

Reformulate the portal UX to apply Cloudscape Design System patterns while preserving the existing data layer, API contracts, and persona-based observability model.

### Design Reference
- cloudscape.design/patterns/general/service-dashboard/ — Static dashboard pattern
- cloudscape.design/patterns/general/service-dashboard/dashboard-items/ — Dashboard item structure
- amazon.design/projects — Cloudscape Open Source Design System design philosophy

### Technology Changes

| Before | After |
|--------|-------|
| Tailwind CSS | @cloudscape-design/global-styles (design tokens) |
| Custom rail navigation | Cloudscape SideNavigation |
| Custom header | Cloudscape TopNavigation |
| Custom bento-card class | Cloudscape Container + Header |
| Lucide icons (in layout) | Cloudscape iconName props |
| framer-motion (in layout) | Cloudscape native transitions |
| Custom dark mode (data-theme) | Cloudscape awsui-dark-mode class |
| postcss + tailwind.config.js | Removed (zero PostCSS config) |

### Architecture

```
TopNavigation (identity + utilities)
  AppLayout
    SideNavigation (7 views + Observability)
    BreadcrumbGroup
    Content (view-specific)
      PipelineView (Table + ColumnLayout)
      AgentsView (Cards<Agent>)
      ReasoningView (Table + StatusIndicator)
      GatesView (Container + ExpandableSection)
      HealthView (ColumnLayout + KeyValuePairs)
      RegistriesView (Container + KeyValuePairs)
      ObservabilityView (Tabs + Grid)
        Per-persona card grid (Container pattern)
```

### Card Migration Pattern

All 17 dashboard cards follow the Cloudscape Dashboard Item pattern:
- Container with Header variant="h3" (title + description + actions)
- Content area with Cloudscape primitives (ColumnLayout, ProgressBar, StatusIndicator, KeyValuePairs)
- Footer with Box fontSize="body-s" color="text-body-secondary"
- Empty state: StatusIndicator type="pending" centered

Cards with custom SVG visualizations (MaturityRadar, BrainSimCard) use Cloudscape CSS variables for colors to adapt to dark/light mode automatically.

### Code Splitting

```
vendor-react.js      50 KB (React, i18next)
cloudscape-data.js  186 KB (Table, Cards, ProgressBar, etc.)
cloudscape-core.js  576 KB (AppLayout, TopNavigation, SideNavigation, etc.)
index.js            445 KB (App + all views + card components)
```

### Logo

Dual-mode SVG mark (factory-logo-dark.svg / factory-logo-light.svg) using AWS architecture icon visual language: code brackets inside a dashed gear ring, within a rounded square container with orange border.

## Consequences

### Positive
- Unified UX vocabulary with AWS console experiences
- Native dark mode via awsui-dark-mode (no custom CSS variables)
- WCAG 2.1 AA compliance via Cloudscape built-in accessibility
- Removed 71 npm packages (Tailwind + PostCSS ecosystem)
- Smooth theme transitions (0.3s CSS transition)
- Proper keyboard navigation and ARIA labels on all interactive elements

### Negative
- Cloudscape CSS is larger than Tailwind (~1 MB total CSS across 3 chunks)
- cloudscape-core.js chunk exceeds 500 KB (Vite warning) — acceptable for internal tool
- Cards with custom SVG visualizations still use inline styles

### Removed
- tailwindcss, autoprefixer, postcss, @tailwindcss/vite (71 packages)
- tailwind.config.js, postcss.config.js
- Custom CSS variables — replaced by Cloudscape design tokens
- Custom rail navigation component
- Custom Header component

## Related
- ADR-017 — React Portal for Factory Observability UX (original architecture)
- ADR-011 — Multi-Cloud Adapter YAGNI (Tailwind was the original YAGNI-compliant choice)
