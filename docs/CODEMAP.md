# Radar source map

Use semantic ownership rather than generated pages as the starting point for a change. Paths are relative to this repository. `dist/` is build output; `public/data/` and `data/` are governed publication inputs/artifacts, not UI source.

## Interface entry points

| Responsibility | Source | Related checks |
| --- | --- | --- |
| Overview, snapshot loading and hydration | `src/main.tsx`, `src/App.tsx`, `src/lt/LtRadarApp.tsx` | Snapshot bootstrap contracts; browser refresh/error/no-JS checks |
| Candidate view, filters and exports | `src/components/Dashboard.tsx`, `FilterBar.tsx`, `SignalTable.tsx`, `ExportActions.tsx` | `src/lib/dashboard.ts`, `src/lib/export.ts`; filter, clipboard, defanging and mobile tests |
| Changes feed and filter recovery | `src/pages/ChangesPage.tsx` | Changes EN/LT filtering, pagination and empty-state browser checks |
| Discovery trends and coverage presentation | `src/pages/TrendsPage.tsx`, `src/lib/trendFreshness.ts` | Trend bounds, cutoff, partial-day, sparse-series and collection-warning checks |
| Static-route dispatcher, associations/tools/dataset | `src/StaticPages.tsx`, `src/staticPage.tsx` | Static-page bootstrap and route checks |
| Shared static-page framing and UTC formatting | `src/components/ArtifactPageShell.tsx`, `src/lib/staticPageFormat.ts` | EN/LT route and source geometry assertions |
| Local indicator analysis and relationships | `src/components/BrowserIocChecker.tsx`, `AssociationExplorer.tsx`, `src/lib/iocCheck.ts`, `relatedObservations.ts` | Local-only/network-boundary and relationship evidence tests |
| History, signal and brand pages | `src/HistoryApp.tsx`, `SignalPage.tsx`, `BrandActivityPage.tsx`, `BrandScopePage.tsx` | History partitions, retained data and signal-detail checks |
| Methodology and technical documentation | `src/components/Methodology.tsx`, `Documentation.tsx`, `src/lt/LtMethodologyPage.tsx`, `LtDocumentation.tsx` | EN/LT documentation and terminology checks |
| Portfolio navigation and footer | `src/components/SiteHeader.tsx`, `SiteFooter.tsx` | Exact routes/order, mobile navigation, focus and accessibility checks |

## Presentation ownership

`src/styles.css` is the stable bundler entry point. It imports the ordered module index `src/styles/foundation.css`, then `src/styles/portfolio-interface.css` (the September 2026 portfolio presentation layer). The foundation index is not a monolithic implementation; these semantic modules own its rules:

| Module under `src/styles/` | Responsibility |
| --- | --- |
| `fonts.css`, `tokens-and-base.css` | Self-hosted type faces, palette, sizing tokens, document/reset and accessibility primitives |
| `site-shell.css` | Network/product rows, portfolio links, mobile menu and main frame |
| `overview-summary.css`, `overview-navigation-layout.css` | Introduction, freshness, summary metrics, activity strip, route navigation and later layout refinements |
| `collection-health.css` | Sampling disclosure, collector attempt health and labelled status states |
| `reading-pages.css` | Methodology and documentation reading layouts, tables and code samples |
| `brand-registry.css` | Brand scope, registry filters and evidence values |
| `candidate-filters.css`, `candidate-table.css` | Search/filter/export controls, candidate table, status/evidence labels and pagination |
| `evidence-dialog.css` | Candidate modal, captured evidence, provenance and bounded observation details |
| `record-pages.css` | Durable signal/brand records, timeline, comparisons and related observations |
| `activity-pages.css` | Changes feed, event filters, discovery trends, quality and dataset distributions |
| `footer-and-states.css` | Footer, initial/error states and basic buttons |
| `responsive-foundations.css`, `portfolio-geometry.css` | Responsive table/navigation/prose behavior and shared heading/spacing geometry |
| `research-brief.css` | Local evidence-note draft controls |

Import order is intentional: existing later refinements follow earlier component and responsive rules. Do not alphabetically reorder it. `scripts/verify-site.mjs` reads imports recursively, so the source geometry gate checks the actual complete entry rather than an unbundled copy. `src/components/intelligenceTools.css` owns the indicator/association tools, not the shared shell. Self-hosted type assets and licenses live under `public/fonts/`.

See `docs/design-interface.md` for typography, layout and interaction invariants. Avoid adding route-specific shell widths or parallel copies of the same shared styles.

## Data and trust boundaries

- `src/lib/*Bootstrap.ts` validates data embedded during static rendering and fetched for hydration. `src/types.ts` describes frontend records; validation remains required at boundaries.
- `vite.config.ts` and `src/prerender.ts` produce static HTML, safe bootstrap payloads and deployment manifests. They must retain usable no-JavaScript output and content-security policy compatibility.
- `hecavex_radar/` owns collectors, publication, durable history and quality artifacts. Its source revision is separate from the `radar-data` branch. A visual change must not alter collection schedules, credentials, source/data trust, review state, schema or distribution semantics.
- Candidate domains remain defanged and non-clickable as live destinations. A candidate is a lead, not a verdict. An association is not attribution; an absent measurement is not zero.
- Trends keep unique signals, recorded attempts, planned slots, listening bounds, planned ceiling and data cutoff separate. Never silently replace unknowns with zeros or imply that a partial day is complete.
- Filters may share an allowlisted controlled state in the URL; free-text indicator searches stay local. Clipboard failure offers an explicit manual-copy fallback.

## Verification and delivery

- `scripts/verify-site.mjs`: static routes, data semantics, font assets, layout geometry, responsive interactions, accessibility and performance budgets.
- `scripts/verify-snapshot-contract.mjs`: frontend snapshot/data invariants.
- `scripts/*test.mjs` and `tests/`: history/deployment/gzip and collector/publication/security tests.
- `pnpm check:frontend`: lint, typecheck, data contracts, production build and static/browser checks.
- `pnpm check`: full Python/frontend/publication gate. CI materializes an immutable isolated fixture before this command; do not commit fixture replacement as live operational data.
- `.github/workflows/ci.yml` and deployment workflows own checked publication. Source changes use a pull request; a pushed branch is not proof of deployment.

The September 2026 extraction preserves the `StaticPages.tsx` public exports so callers and static rendering do not acquire a second route registry or dependency cycle.
