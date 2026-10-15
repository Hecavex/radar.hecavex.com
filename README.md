# HECAVEX Radar

Source for [radar.hecavex.com](https://radar.hecavex.com/), a public, read-only view of screened potential phishing infrastructure relevant to Lithuanian brands. Python maintains bounded passive observations and sanitized publications; React/Vite renders the static website.

## Read and explore

- [Current candidates](https://radar.hecavex.com/) and [Lietuviškai](https://radar.hecavex.com/lt/): screened observations with source and freshness context.
- [History](https://radar.hecavex.com/history/), [Changes](https://radar.hecavex.com/changes/) and [Trends](https://radar.hecavex.com/trends/): retained observations, publication events and coverage-aware series.
- [Brands](https://radar.hecavex.com/brands/), [dataset](https://radar.hecavex.com/dataset/) and [methodology](https://radar.hecavex.com/methodology/): registry scope, machine-readable releases and analytical limits.
- [Public documentation](https://radar.hecavex.com/docs/): service usage and data interpretation.

## Find and change the source

Start with [the code map](docs/CODEMAP.md). `src/` owns the interface and static routes; `hecavex_radar/` owns collection, matching, normalization, review boundaries and publication; `.github/workflows/` owns scheduled operation and Pages; `requirements/` holds hash-locked Python environments.

| Task | Authoritative guide |
| --- | --- |
| Local preparation, contribution and complete checks | [Change policy](CONTRIBUTING.md) and [Python locks](requirements/README.md) |
| Trusted source/data revisions, schedules, limits and Pages | [Deployment runbook](docs/DEPLOYMENT.md) |
| System responsibilities | [Architecture](docs/ARCHITECTURE.md) and [code map](docs/CODEMAP.md) |
| Snapshot, history, feeds, schemas and integrity | [Public data contract](docs/DATA-CONTRACT.md) and [history](docs/HISTORY.md) |
| Provider provenance and brand matching | [Sources](docs/DATA-SOURCES.md) and [detection](docs/DETECTION.md) |
| Intentional sanitized analyst export | [Private review workflow](docs/REVIEW-WORKFLOW.md) |
| Reproducible weekly packages and MISP gates | [Dataset releases](docs/DATASET-RELEASES.md) and [MISP sharing](docs/MISP-SHARING.md) |
| Accessible interface and performance | [Interface contract](docs/design-interface.md) and [performance](docs/PERFORMANCE.md) |

Run `pnpm check` before production changes. Use the pinned toolchains and preparation in [CONTRIBUTING.md](CONTRIBUTING.md). Source CI fixtures are synthetic and cannot replace governed public data. Source and data are independent revisions; a successful local build does not prove a live publication.

## Interpretation, privacy and rights

Candidates, automated match scores, corroboration and analyst assessments remain distinct. Radar does not measure phishing prevalence, prove maliciousness or authorize automatic blocking. Missing data means unknown, and defanged indicators are text rather than navigation links. Collection is bounded and best-effort; there is no monitoring, notification, response, takedown or availability SLA.

Private notes, raw case evidence, identities and credentials stay outside Git. Public decisions require an explicit sanitized export. Provider authentication does not establish redistribution permission. Optional archived screenshots require an explicit reader action. Measurement is DNT-aware and its scope is recorded in [the data contract](docs/DATA-CONTRACT.md#website-analytics-boundary).

Original software and documentation are [Apache-2.0](LICENSE). Third-party observations, screenshots, trademarks and source material retain their terms under [DATA-LICENSE.md](DATA-LICENSE.md). Package and data-directory READMEs remain with their owning files to preserve provenance, safety and reproduction details. Report vulnerabilities privately using [SECURITY.md](SECURITY.md).

Related HECAVEX properties: [Research](https://hecavex.com/en/), [APT Notes](https://apt.hecavex.com/) and [Labs](https://labs.hecavex.com/).
