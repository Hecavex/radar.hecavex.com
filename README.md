# HECAVEX Radar

Source for [radar.hecavex.com](https://radar.hecavex.com/), a public, read-only view of screened potential phishing infrastructure relevant to Lithuanian brands. Python maintains bounded passive observations and sanitized publications; React/Vite renders the static website.

## Read and explore

- [Observed hostnames](https://radar.hecavex.com/) and [Lietuviškai](https://radar.hecavex.com/lt/): unique hostnames over 30/90/365 days, calendar months or all recorded data, with a separate recent shortlist.
- [History](https://radar.hecavex.com/history/), [Changes](https://radar.hecavex.com/changes/) and [Trends](https://radar.hecavex.com/trends/): retained observations, publication events and coverage-aware series.
- [Brands](https://radar.hecavex.com/brands/), [dataset](https://radar.hecavex.com/dataset/) and [methodology](https://radar.hecavex.com/methodology/): registry scope, machine-readable releases and analytical limits.
- [Public documentation](https://radar.hecavex.com/docs/): service usage and data interpretation.

## Find and change the source

Start with [the code map](docs/CODEMAP.md). `src/` owns the interface and static routes; `hecavex_radar/` owns collection, matching, normalization, review boundaries and publication; `.github/workflows/` owns scheduled operation and Pages; `requirements/` holds hash-locked Python environments.

Current generated data lives on the [radar-data branch](https://github.com/Hecavex/radar.hecavex.com/tree/radar-data), while protected `main` owns trusted executable code and configuration. The `data/` and `public/data/` JSON copies on `main` are a frozen 2026-09-07 snapshot: the local dev fixture that `pnpm dev`, `pnpm build` and most tests read, and the seed for a missing-branch `data_branch bootstrap`. They are not current data, and code changes do not regenerate them; keep them, and do not commit regenerated output over them. CI replaces them with the pinned fixture from `.github/workflows/ci.yml` (`python -m hecavex_radar.data_branch materialize-fixture`, then `offline_publication` and `quality_artifacts`); run those in a throwaway checkout to reproduce CI. Tests that need that regenerated fixture skip locally on the unmodified frozen copy (`tests/ci_fixture.py`). The [live release identity](https://radar.hecavex.com/.well-known/hecavex-release.json) binds the served source and data revisions. See [data navigation](data/README.md).

| Task | Authoritative guide |
| --- | --- |
| Local preparation, contribution and complete checks | [Change policy](CONTRIBUTING.md) and [Python locks](requirements/README.md) |
| Trusted source/data revisions, schedules, limits and Pages | [Deployment runbook](docs/DEPLOYMENT.md) |
| System responsibilities | [Architecture](docs/ARCHITECTURE.md) and [code map](docs/CODEMAP.md) |
| Snapshot, history, feeds, schemas and integrity | [Public data contract](docs/DATA-CONTRACT.md) and [history](docs/HISTORY.md) |
| Durable observed hostnames and period totals | [Observation records](docs/OBSERVATIONS.md) and [period metrics](docs/PERIOD-METRICS.md) |
| Provider provenance and brand matching | [Sources](docs/DATA-SOURCES.md) and [detection](docs/DETECTION.md) |
| Intentional sanitized analyst export | [Private review workflow](docs/REVIEW-WORKFLOW.md) |
| Reproducible weekly packages and MISP gates | [Dataset releases](docs/DATASET-RELEASES.md) and [MISP sharing](docs/MISP-SHARING.md) |
| Accessible interface and performance | [Interface contract](docs/design-interface.md) and [performance](docs/PERFORMANCE.md) |

Run `pnpm check` before production changes. Use the pinned toolchains and preparation in [CONTRIBUTING.md](CONTRIBUTING.md). Source CI fixtures are synthetic and cannot replace governed public data. Source and data are independent revisions; a successful local build does not prove a live publication.

## Interpretation, privacy and rights

Candidates, automated match scores, corroboration and analyst assessments remain distinct. Radar does not measure phishing prevalence, prove maliciousness or authorize automatic blocking. Missing data means unknown, and defanged indicators are text rather than navigation links. Collection is bounded and best-effort; there is no monitoring, notification, response, takedown or availability SLA.

Private notes, raw case evidence, identities and credentials stay outside Git. Public decisions require an explicit sanitized export. Provider authentication does not establish redistribution permission. Optional archived screenshots require an explicit reader action. Measurement is DNT-aware and its scope is recorded in [the data contract](docs/DATA-CONTRACT.md#website-analytics-boundary).

Original software and documentation are [Apache-2.0](LICENSE). Third-party observations, screenshots, trademarks and source material retain their terms under [DATA-LICENSE.md](DATA-LICENSE.md). Package and data-directory READMEs remain with their owning files to preserve provenance, safety and reproduction details. Report vulnerabilities privately using [SECURITY.md](SECURITY.md).

Related HECAVEX property: [Research](https://hecavex.com/en/).
