# HECAVEX Radar

This repository is the operational source and public change record for [radar.hecavex.com](https://radar.hecavex.com), a HECAVEX-operated, read-only research service for recently observed potential phishing domains and URLs targeting Lithuanian brands.

It is not presented as a starter site, downloadable product, self-hosting package, or general-purpose phishing platform. The public source supports transparency, reproducible data handling, and review of the live service. The production service, its schedules, source access, review decisions, domain, and publication process are maintained by HECAVEX.

## Live service

- [Radar dashboard](https://radar.hecavex.com/) — current validated candidate observations
- [Changes](https://radar.hecavex.com/changes/) and [candidate history](https://radar.hecavex.com/history/) — bounded publication events, reobservations, status changes, and retained provenance
- [Brand activity](https://radar.hecavex.com/brands/) — the reviewed Lithuanian registry, permanent brand hubs, and per-brand change feeds
- [Trends](https://radar.hecavex.com/trends/) — coverage-aware discovery series and bounded public review-quality measures
- [Associations](https://radar.hecavex.com/associations/) — typed shared-evidence relationships with an explicit non-attribution boundary
- [Local indicator tools](https://radar.hecavex.com/tools/) — browser-only checks against downloaded public artifacts
- [Reporting evidence utility](https://radar.hecavex.com/reporting/) — non-sending browser tool for an active reviewed confirmation; it cannot create a review or contact a candidate
- [Dataset distributions](https://radar.hecavex.com/dataset/) — machine-readable entry points, schemas, integrity metadata, and release boundaries
- [Lithuanian edition](https://radar.hecavex.com/lt/) — localized overview, changes, brand registry, and methodology
- [Methodology](https://radar.hecavex.com/methodology/) and [technical reference](https://radar.hecavex.com/docs/) — collection limits, schemas, operations, security boundaries, and data terms

Radar combines sampled live Certificate Transparency observations, bounded checkpointed searches of the public `crt.sh` index, passive searches of existing public URLScan reports, and an optional deliberately limited HECAVEX public export. For already published candidates it can add point-in-time DNS-over-HTTPS and RDAP context, retained routing context, and a bounded semantic context-change journal without requesting the candidate webpage. The Python pipeline validates every accepted record and defangs the dashboard, history, event, trend, and association artifacts. One STIX 2.1 projection carries observations; a second carries only explicitly reviewed, time-bounded Indicators and, when public observation history exists for an Indicator, a linked Sighting summary. Reviewed decisions can also drive a disabled-by-default MISP feed, while the official-domain registry is published separately as a MISP warning list. The React interface renders the static artifacts without an application server, account system, public write path, or database connection.

## Publication and safety boundaries

- Public source labels are limited to CertStream, URLScan, and HECAVEX. The HECAVEX label represents either a configured sanitized service export or an explicitly accepted sanitized local review candidate; `discoveredVia` distinguishes those paths.
- Dashboard and history indicators are defanged before publication. Credentials, query strings, fragments, and sensitive-looking path data are excluded.
- The observation-only STIX 2.1 distribution is the deliberate exception to display defanging: it contains raw domain-name observables only, with no URL paths or TLP marking. The separate reviewed Indicator distribution applies the standard TLP:CLEAR marking to deliberately exported confirmations. That marking does not relicense source evidence. Treat values in either feed as untrusted data and do not browse, resolve, scan, or block them without independent review.
- CertStream matches are research leads, not confirmation of phishing. Qualifying records are published as `suspected`; the collector reads certificate names and never visits candidate hosts.
- The hourly `crt.sh` poller replays a bounded set of reviewed brand-keyword searches from persisted per-query cursors. It improves recovery within those declared queries but is not complete CT-log collection and does not support a global coverage claim.
- URLScan is optional passive corroboration. Radar searches existing public reports and never submits or opens a candidate URL. Missing or non-public scan visibility does not suppress an independently qualifying CertStream record.
- URLScan-derived temporal baselines and context changes remain disabled unless HECAVEX explicitly confirms the intended redistribution is permitted. An API key is authentication, not publication permission.
- DNS and RDAP enrichment runs only for current published candidates. It stores defanged DNS answers and limited registrar, lifecycle, and status fields; it does not retrieve a candidate page or retain registrant contact data. Missing context is unknown, not benign.
- Screenshots and evidence links are URLScan-only. Opening evidence may contact `urlscan.io`, never the observed host.
- The public registry and matcher are separate from HECAVEX private collectors, proprietary detection logic, and internal case history.
- `matchScore` is a ranking aid, not a probability, verdict, analyst confidence, or actor attribution. `confidence` remains only as a deprecated equal alias during consumer migration.
- Radar is best-effort public research. It provides no monitoring, notification, response, takedown, coverage, availability, or service-level guarantee.

## Operating model

The service is published through reviewed GitHub Actions workflows. Cron schedules are UTC and may start late.

| Operation | Schedule or trigger | Service artifact |
| --- | --- | --- |
| CertStream sample | `8,23,38,53 * * * *` | Defanged candidate archive and latest bounded collection-health record |
| CertStream cadence relay | Finalized collector completion plus a six-minute protected wait | Deduplicated next collection dispatch when no newer run is active; native cron remains the backstop |
| Snapshot cadence relay | Successful collector completion | Dispatches an overdue sync, or queues one follow-up when a candidate-producing run overlaps an in-progress sync |
| CT keyword search | `43 * * * *` | Per-brand query checkpoints and qualifying rows in the shared CT candidate archive |
| URLScan hunt | `37 */2 * * *` | Bounded hunt-state ledger and validated daily archive when the optional source is configured |
| Official asset pivot | `47 3,15 * * *` | Stable first-party favicon/JavaScript hashes and independently qualified public URLScan observations |
| DNS and RDAP context | `13 1,7,13,19 * * *` | Rotating, 14-day point-in-time context for published candidates |
| Temporal passive context | `31 1,7,13,19 * * *` | Bounded DNS/RDAP/routing baselines and semantic context-change journal; URLScan-derived fields remain permission-gated |
| Snapshot synchronization | `17 * * * *` | Live snapshot; STIX and gated MISP projections; warning list; retained history; event, feed, trend, quality, coverage, review-queue, association, and integrity artifacts |
| Site deployment | Successful code CI, material snapshot sync, or failed CertStream health | Static production pages for `radar.hecavex.com` |
| Analyst provider check | Manual, one existing signal ID | Optional VirusTotal request with no provider result exposed by public Actions; Safe Browsing remains private/local-only |
| Pipeline health evaluator | `11 */2 * * *` | One deduplicated aggregate health issue that closes after recovery |
| Live publication verifier | `37 */2 * * *` | Atomic data-pair, English/Lithuanian route, canonical, language, and custom-404 checks with one recoverable health issue |
| Sanitized review proposal | Maintainer-only manual dispatch | Draft pull request containing one bounded proposal; it does not publish a review decision |
| Weekly dataset release | `29 6 * * 1` | Reproducible archive, manifest, SPDX 2.3 inventory, checksums, and workflow attestations after repository release gates pass |

The CertStream listener runs for eight-minute bounded windows at an intended four-per-hour cadence: at most 768 minutes, or 53.3% of a day, if every run starts and completes. Native cron slots are backed by a completion relay that waits six minutes without occupying a runner, suppresses itself when a newer collection is active, and dispatches one next bounded run. When an automated worker arrives up to five minutes before the persisted 15-minute boundary because of scheduler jitter, the worker waits only until that boundary, re-reads the persisted claim, and starts only if no newer attempt owns the slot. This preserves the hard coverage ceiling without discarding a valid nominal window. The collector emits one fixed, credential-free completion event after finalization so handoffs do not depend on recursive `workflow_run` delivery. Snapshot writers use a separate fixed event, preventing an unrelated sync from canceling a pending collector timer. A second relay checks snapshot freshness after a successful collection and dispatches an overdue sync at most once per 45 minutes. When a candidate-producing collection overlaps an in-progress sync, it queues one follow-up unless one is already waiting, so the older checkout cannot strand the new candidate until the ordinary interval. These relays reduce dependence on GitHub's best-effort cron dispatcher but do not create continuous coverage or survive a complete Actions trigger outage. The dashboard publishes the latest attempt's actual timing, aggregate counts, outcome, schedule delay, last success, and freshness without retaining raw certificate names.

The separate hourly `crt.sh` job rotates through six reviewed brand queries by default, processes at most 500 result rows per query, and bootstraps no more than seven days of indexed results. Each query keeps a numeric result-ID checkpoint but also replays up to 50 prior rows inside a 1,000-ID overlap so a modest late-indexing reorder is not silently skipped. A query with more new rows than the current cap retains its partial checkpoint. Rotation advances by the queries actually attempted, including a failing or partial query, so one slow brand cannot starve all later brands. A provider error still stops the run and honours the existing cooldown without spending additional request allowance. Accepted matches use the same matcher and date-partitioned CT archive as the live listener; both discovery methods can be retained for one domain on the same day. These safeguards do not prove that `crt.sh` indexed every certificate, that every Lithuanian brand name is queryable, or that Radar covered every public CT log. [ADR 0001](docs/decisions/0001-ct-coverage.md) distinguishes this useful indexed replay from complete log-index coverage.

Four times per day, a credential-free context job rotates through up to 20 current published candidates. It asks Cloudflare's DNS-over-HTTPS endpoint for A, AAAA, CNAME, NS, and MX answers and discovers the relevant RDAP service from IANA's bootstrap registry. RDAP is queried at the registrable parent and the defanged queried scope is retained so subdomain context is not mistaken for a separate registration. Records older than 14 days or no longer present in the current snapshot are removed. Only defanged answers, minimum observed TTL, registrar, registration/update/expiry times, and status codes can reach the optional signal-detail sidecar and aggregate health. This context can support bounded related-observation edges, but neither shared infrastructure nor registration metadata attributes an operator or proves maliciousness.

The URLScan workflow runs at minute 37 every two hours. Each run attempts exact passive lookups for the complete bounded set of at most 250 candidates observed during the rolling previous seven days, subject to conservative request budgets. A deterministic candidate cursor preserves progress only when an operator lowers the per-run selection or a request budget interrupts the set. Each provider query also keeps a hash-only `search_after` checkpoint in `data/urlscan/search-checkpoints.json`; provider totals and cursor/page progress determine whether that query is complete, partial, or still backlogged. An unavailable request or exhausted budget cannot clear or advance the checkpoint, and public pipeline health exposes only aggregate completeness and oldest-backlog progress, never the query text. The hunter performs only searches of existing public reports and retrieval of public result documents: it does not submit scans or visit candidate hosts. A missing `URLSCAN_API_KEY` is a successful, explicit skip with no API request. The checked-in hunt-state ledger records configuration, UTC budget counters, candidate cursor progress, and the latest outcome, but no credential or candidate domain.

At 03:47 and 15:47 UTC, a second passive URLScan job rotates through every reviewed official domain for each brand. It retains bounded first-party favicon and JavaScript SHA-256 hashes only after support from two distinct public scans, rejects hashes known to be shared by multiple registry brands within the retained collision ledger, and uses them only to discover public reports. A matching candidate still needs independent same-brand domain or provider-verdict evidence before it can enter the URLScan archive; title evidence also requires a URLScan phishing verdict. No official page, asset, or candidate is fetched directly.

At 01:31, 07:31, 13:31, and 19:31 UTC, the temporal context job rotates over retained public DNS/RDAP context and caches bounded RIPEstat prefix, ASN, and optionally RPKI state. It compares normalized components with the previous baseline and keeps a 60-day semantic change journal by default. URLScan-derived baselines, journal entries, and public detail fields are excluded while `URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED` is not exactly `true`.

The hunt-state file is workflow evidence, not bootstrap configuration: its first checked-in value and later transitions must come from a scheduled or manually dispatched GitHub Actions run, never from locally generated placeholder output. Snapshot synchronization maps an unconfigured hunt to a public `skipped` source state while retaining previously validated URLScan observations; it does not recast absence of enrichment as benign evidence.

## Source and generated-data revisions

The migration workflow separates reviewed source on `main` from generated state on the data-only `radar-data` branch. Code, workflows, dependency locks, the brand registry, matcher fixtures and sanitized review decisions remain source-controlled on `main`. Only the source-owned allowlisted generated paths are imported from `radar-data`, never executable content. Paths below are checkout-relative, not a claim that a source checkout contains the latest operational state.

Collectors use the latest operational data revision. Snapshot publication records the exact source and input-data revisions. Pages builds trusted current source with validated operational data, requires the publication marker to match that source, and records `sourceRevision` and `dataRevision` in `/.well-known/hecavex-release.json`. A source change invalidates an older-source publication. Weekly exports select the publication view rather than an arbitrary collector update.

This describes the checked-in migration contract, not evidence that branch bootstrap, repository protection or production cutover has completed. Those are explicit owner operations in the [deployment runbook](docs/DEPLOYMENT.md#source-and-data-cutover). Source CI uses a pinned coherent fixture, not mutable collector state, and cannot publish that fixture.

## Public service artifacts

| Path | Role in `radar.hecavex.com` |
| --- | --- |
| `public/data/radar.json` | Current checked and bounded dashboard snapshot |
| `public/data/radar.stix.json` | Current observation-only STIX 2.1 Bundle; raw domain-name observables, not a verdict or TAXII endpoint |
| `public/data/radar-reviewed.stix.json` | Analyst-reviewed STIX 2.1 Indicators with explicit expiry/revocation semantics and linked public-history Sightings when available; not an automated blocklist |
| `public/data/radar.index.json` and `radar-shards/` | Complete accepted newest-first signal set in independently hashed 256 KiB shards |
| `public/data/history.json` | Bounded public candidate-history projection |
| `public/data/collection-health.json` | Latest bounded CertStream attempt health; no raw candidates |
| `public/data/pipeline-health.json` | Sanitized 24-hour and seven-day collection, screening, enrichment, and publication aggregates |
| `public/data/changes.json` | Aggregate first-publication, reobservation, and status-change view |
| `public/data/related-observations.json` | Typed shared-evidence associations with explicit non-attribution semantics |
| `public/data/events.json` | Defanged, newest-first, 30-day publication event stream, bounded to 1,000 first-publication, reobservation, status-change, and review-retraction events |
| `public/data/events.atom.xml`, `events.rss.xml`, and `events.feed.json` | Atom, RSS 2.0, and JSON Feed 1.1 views of the same bounded global event stream |
| `public/data/brand-feeds.json` and `public/data/brands/<slug>/` | Deterministic directory and Atom/RSS/JSON Feed views for every reviewed registry brand; an empty feed means no event in the bounded window, not no phishing activity |
| `public/data/daily-trends.json` | Sparse, coverage-aware UTC discovery series for up to 365 days; not a phishing-prevalence measure |
| `public/data/quality-metrics.json` | Aggregate public-review sample, coverage, latency, and exclusion measures; deliberately does not claim precision from an incomplete review sample |
| `public/data/misp/manifest.json` | Reviewed-only MISP static-feed manifest; `{}` is the valid current output when no active reviewed confirmation qualifies, and the feed remains disabled until importer/tombstone acceptance testing passes |
| `public/data/misp-warninglists/hecavex-official-domains/list.json` | MISP hostname warning list built from the reviewed official-domain registry; a match is not a benign verdict |
| `public/reporting/` | Non-sending browser utility that can prepare a bounded evidence manifest for one active, unexpired reviewed confirmation; it cannot create or submit a review |
| `public/data/feed-manifest.json` and `*.sha256` | Generator revision, copied source `fetchedAt` timestamps, counts, artifact lengths, and release-integrity digests for the atomic hourly release |
| `public/data/schemas/` | Versioned Draft 2020-12 schemas used by the publisher and CI |
| `public/data/signals/` | Lazy, per-signal CertStream/URLScan evidence, optional DNS/RDAP/routing context, and bounded semantic context changes; 16 KiB each and 3 MiB in aggregate |
| GitHub Releases tagged `radar-data-YYYY-Www` | On a successful gated run: reproducible public-data package plus validated bounded context-journal partitions, standalone manifest, SPDX 2.3 inventory, `SHA256SUMS`, and workflow-provenance attestations |
| `data/brands-lt.json` | Reviewed Lithuanian brand and official-domain registry |
| `data/certstream/` | Date-partitioned successful sample metadata and defanged CT candidates |
| `data/ct-search/` | Bounded `crt.sh` provider state, rotating query cursor, and per-brand result checkpoints; no unpublished domain names |
| `data/enrichment/domain-context.json` | Rotating, credential-free DNS/RDAP context for current published candidates; 14-day default retention |
| `data/enrichment/passive-context.json` and `data/history/context/` | Created after a material temporal-context run; bounded baselines and semantic change journal with URLScan-derived content permission-gated |
| `data/urlscan/` | Date-partitioned validated URLScan observations, bounded detail context, hunt/official-asset state, and hash-only provider pagination checkpoints |
| `data/urlscan/search-checkpoints.json` | Created after material provider pagination progress; per-query SHA-256 identifier, `search_after` cursor, bounded count, completion state, and progress time, never query text |
| `data/history/` | Deterministic daily events, compacted history summary, and bounded context-change partitions |
| `data/coverage/brand-coverage.json` | Deterministic per-brand collection, registry-review, matcher-corpus, and public-review coverage ledger; not a prevalence measure |
| `data/review/review-queue.json` | Deterministic balanced worklist of public candidates; not a random sample and not a review decision |
| `data/matcher/lithuanian-brands-v1.json` | Versioned synthetic/reserved/official-domain matcher regression corpus checked by CI |
| `data/review/public-decisions.json` | Explicitly exported, sanitized review decisions only |

Public snapshots and their schemas are documented in the [data contract](docs/DATA-CONTRACT.md). Third-party observations and screenshots remain subject to their source terms; see [data licensing and attribution](DATA-LICENSE.md).

The four-per-hour `collection-health.json` document is intentionally outside the hourly release manifest and checksum set because the collector replaces it independently. Routine healthy state reaches the site with the next hourly snapshot; a committed collector failure can request an immediate verified deployment. Its synchronized, bounded aggregate appears in `pipeline-health.json`. This prevents a newer health measurement from making an otherwise atomic hourly manifest stale.

The Monday release workflow freezes a validated publication from one exact data revision, excluding only that independently changing health document, and adds validated bounded `data/history/context/` journal partitions when present. Historical backfills still execute only the current `main` toolchain: an explicit legacy `source_sha` contributes only bounded historical source-branch data blobs in a separate temporary root, while `data_sha` selects the dedicated data branch. Neither supplies executable code or dependency files. The weekly manifest retains `sourceCommit` for that selected data revision and `toolingCommit` for the trusted current source toolchain. URLScan-derived context rows remain excluded unless `URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED` is exactly `true`. It also derives an SPDX 2.3 dependency inventory from the current trusted Python runtime and pnpm locks. Release immutability is a repository setting, not something the workflow silently enables. HECAVEX must enable it before setting the workflow's operator-confirmation variable; a successful future release is then protected against tag or asset replacement and independently attested. No weekly package should be inferred until a release appears in GitHub. See [weekly dataset releases](docs/DATASET-RELEASES.md).

## HECAVEX maintenance

Repository changes are evaluated against the live service's safety, provenance, accessibility, and publication guarantees. Collector credentials remain in GitHub Actions secrets. Private false-positive notes and analyst identity remain outside Git; only an intentional sanitized export can enter the public pipeline.

The checked-in review proposal workflow creates a draft pull request only after a maintainer supplies bounded, defanged fields. It does not execute issue text or publish a review decision. CODEOWNERS and CI document the expected review path, but repository rules must separately require those checks and reviews; history protection against deletion, force-push, and non-linear updates is not the same control. GitHub Actions must also be permitted to create pull requests before this workflow can operate.

The current public review sample contains no completed analyst assessments, so precision remains unavailable and the reviewed MISP manifest is expected to be empty. This is an honest external gate, not a collector failure. MISP importer/tombstone acceptance and URLScan redistribution permission remain operator checks outside repository tests.

The manual `Ephemeral analyst provider check` workflow can query VirusTotal for one signal that is already in the current public snapshot. It derives the hostname from that checked-in record, accepts no arbitrary URL, does not browse the candidate, and cannot modify Radar data, match scores, status, or suppression. Because this is a public repository, the workflow intentionally omits provider results from its summary, logs, artifacts, and commits. Google Safe Browsing is deliberately excluded from public Actions: its v5 protocol requires every result, including a no-match, to remain cached until the provider-supplied expiry. A maintainer can inspect Google or VirusTotal details only through the same bounded command in a private local environment; the ignored `.radar-local/provider-check-cache.json` honors Safe Browsing expiry. A provider no-match or missing record is unknown, never a benign verdict.

The optional private pivot handoff is local-only. `hecavex-handoff` exports current passive CertStream/URLScan-backed rows to the git-ignored `data/hecavex/` boundary without making a network request. Analysts can review that file, record an accepted candidate with `hecavex-review add`, and intentionally export only sanitized decisions. See the [private review workflow](docs/REVIEW-WORKFLOW.md).

Brand additions and corrections belong in [`data/brands-lt.json`](data/brands-lt.json) and must cite authoritative sources. Complete official-domain coverage is important because official domains and their subdomains are suppressed before scoring. Matching and correction rules are documented in [Detection and brand matching](docs/DETECTION.md) and the [Private review workflow](docs/REVIEW-WORKFLOW.md).

The main implementation areas are:

| Path | Maintained responsibility |
| --- | --- |
| `hecavex_radar/` | Collectors, matching, normalization, review boundary, history, and publication |
| `src/` | Static production interface and prerendered public pages |
| `.github/workflows/` | Collection, synchronization, verification, and Pages publication |
| `requirements/` | Reviewed, hash-locked Python automation environments |

Maintainers run the complete repository gate before production changes:

```sh
pnpm check
```

That gate covers Python and frontend linting and type checks; the production build; links, fragments, metadata, CSP, hydration, and no-JavaScript behavior; serious accessibility findings; responsive overflow; and keyboard navigation. The pinned toolchains and maintainer-only environment preparation are recorded in [the change policy](CONTRIBUTING.md) and [deployment runbook](docs/DEPLOYMENT.md).

## Documentation index

- [Architecture](docs/ARCHITECTURE.md)
- [Public data contract](docs/DATA-CONTRACT.md)
- [Data sources and provenance](docs/DATA-SOURCES.md)
- [Detection and brand matching](docs/DETECTION.md)
- [Candidate history](docs/HISTORY.md)
- [Weekly dataset releases](docs/DATASET-RELEASES.md)
- [MISP sharing](docs/MISP-SHARING.md)
- [Private review workflow](docs/REVIEW-WORKFLOW.md)
- [Deployment and schedules](docs/DEPLOYMENT.md)
- [Performance budgets](docs/PERFORMANCE.md)
- [Data licensing and attribution](DATA-LICENSE.md)
- [Security policy](SECURITY.md)

Original software and documentation are licensed under the [Apache License 2.0](LICENSE). That license does not relicense third-party data, screenshots, trademarks, or source material, and it does not designate modified copies as a HECAVEX-operated service.
