# Data sources and provenance

These are the sources and provenance boundaries of the HECAVEX-operated [radar.hecavex.com](https://radar.hecavex.com) service. Source operators define their own access, attribution, rate, and redistribution terms. Apache-2.0 licenses original Radar software, not third-party data or HECAVEX operation.

## Repository provenance

After the explicit source/data cutover, the paths in this document refer to generated state materialized from `radar-data` into a trusted `main` checkout, except source-owned registry, matcher and review inputs. Relative source-tree links may show retained historical data, not the latest operational state. Use an exact data revision for reproduction or the public service distributions for published data.

The source-owned boundary validates the data manifest inventory before use. Its operational view selects the latest collector state. Its publication view selects the latest snapshot marker commit. The marker identifies the source revision and input data revision, while trusted release tooling records the selected data commit separately. These identifiers establish input/code identity, not provider completeness, permission, benignness or analyst confirmation. See [Architecture](ARCHITECTURE.md#source-and-data-trust-boundary) for ownership and [Deployment](DEPLOYMENT.md#source-and-data-cutover) for activation requirements. The presence of this documentation does not establish a completed production cutover.

## Certificate Transparency

CertStream emits Certificate Transparency log updates over a websocket. The collector reads certificate DNS names, rejects official domains, applies the public Lithuanian-brand heuristic, and archives only matching defanged domains. It does not retrieve or browse those domains.

- [CertStream documentation](https://certstream.dev/docs.html)
- [CertStream architecture](https://certstream.dev/architecture.html)
- [`reloading01/certstream-server-rust`](https://github.com/reloading01/certstream-server-rust), the server used by the scheduled workflow
- [certstream-server-rust MIT license](https://github.com/reloading01/certstream-server-rust/blob/main/LICENSE)

The production workflow starts a digest-pinned `certstream-server-rust` container and connects to its runner-local lite stream unless HECAVEX configures a monitored `CERTSTREAM_URL`. The lite stream omits DER and certificate chains while retaining the leaf fields needed for bounded public context. Maintainer diagnostic invocations without that setting use the compatibility endpoint at `wss://certstream.calidog.io/`; that behavior is not the service's durable collection design. Certificate issuance is not proof of phishing, so CT records remain `suspected`.

For a qualifying hostname, Radar may retain only the leaf subject country and normalized common name, issuer text, validity period, serial, fingerprints already present in the stream, and up to 12 same-registrable certificate names. It does not calculate absent fingerprints or retain DER, chains, extensions, certificate links, unrelated SANs, email addresses, or live URLs. All retained names and indicator-like text are sanitized and defanged before the public candidate archive is written.

The interim GitHub Actions sampler is scheduled at 08, 23, 38, and 53 minutes past each UTC hour for an eight-minute window. If all 96 daily runs start and complete, that is at most 768 listening minutes, or 53.3% of a day. GitHub Actions can delay or drop scheduled events, so the configured ceiling is not observed coverage.

Each scheduled attempt replaces [`public/data/collection-health.json`](../public/data/collection-health.json) with its actual start, end, websocket listening seconds, messages, DNS names, matches, newly archived records, outcome, scheduling delay, and last successful window. The file retains only the latest attempt and aggregate counters. Every successful window is also recorded in the day's bounded `attempts.ndjson`, so a zero-match window has an explicit dated partition. Neither artifact exposes certificate names, and neither can establish coverage between sampled windows.

### Checkpointed `crt.sh` keyword search

Radar also queries the public [`crt.sh`](https://crt.sh/) JSON search index once per hour at minute 43. This is a second CT discovery path, not a replacement name in the public source list: accepted rows remain `CertStream` source observations for compatibility, while `discoveredVia` distinguishes `ct-search-api` from `certstream-live`.

The poller derives one conservative search term from each reviewed registry brand, avoids unsafe short or ambiguous aliases, and rotates through six brand queries per run by default. Each query has an independent persisted result-ID cursor in `data/ct-search/state.json`. A first query bootstraps at most seven days of indexed results. Later runs process at most 500 rows by default while replaying up to 50 previously seen rows inside a 1,000-ID overlap. The overlap catches bounded late-indexing reorder; it is not an unlimited rewind. At least one slot remains available for a new row when one exists. If more new rows remain, the query reports `partial`, increments `queriesBacklogged`, and resumes before ordinary rotation advances. Runtime settings are bounded to 24 queries per run, 2,000 rows per query, a 30-day bootstrap, 10,000 replay IDs, and 250 replay rows. Results still pass the current official-domain suppression, brand matcher, score threshold, archive schema, and deduplication used for live CertStream candidates.

This is replayable coverage only for the declared keyword queries and for records available from the provider's search index. It does not enumerate CT logs, checkpoint a log tree size, guarantee `crt.sh` availability or indexing completeness, recover names that do not contain a selected term, or support a claim of complete global CT coverage. The live eight-minute samples and the indexed search therefore remain complementary bounded discovery mechanisms.

`data/ct-search/state.json` is capped at 128 KiB. It contains the provider name, rotating query position, reviewed brand/query labels, per-query result ID and timestamps, and aggregate latest-run counters including the number of backlogged queries. It contains no unpublished certificate name or candidate domain. The workflow writes `completed`, `partial`, or `failed` state and stages the state plus any accepted CT archive rows before its final step reports a polling failure. Archive-cap failures do not advance a query checkpoint. A hard cancellation, checkout outage, or exhausted Git push retry remains outside what the stopped workflow can record.

The public registry is [`data/brands-lt.json`](../data/brands-lt.json). Official domains, subdomains, and reviewed `excludedDomains` are suppressed before scoring. See [Detection rules](DETECTION.md) for matching and archive revalidation.

## URLScan

At minute 37 every two hours, the scheduled hunter uses URLScan's authenticated search and result APIs to inspect already-existing public reports from the rolling previous seven days. Every search includes `task.visibility:public`, and both the search summary and result detail must independently report public visibility; missing, unlisted, or private visibility is rejected. The hunter performs bounded brand-domain queries, exact-domain queries for at most 250 recent CT, recent Radar-snapshot, and transient discovery seeds, stricter title checks, and a small number of exact primary HTML response SHA-256 pivots. Each run attempts the complete bounded candidate set; a deterministic cursor preserves progress only when an operator lowers the per-run selection or a request budget interrupts it.

Automated validation requires a result to independently support the same Lithuanian brand; an input seed alone is never published. Official brand domains and subdomains are suppressed. Arbitrary resource hashes and hostname-wide allow-listing are deliberately excluded because both create broad false positives.

- [URLScan Search API](https://docs.urlscan.io/pages/search-api-reference)
- [URLScan API overview](https://urlscan.io/docs/api/)
- [URLScan result format](https://urlscan.io/docs/result/)
- [URLScan quotas](https://docs.urlscan.io/apis/urlscan-openapi/generic)

URLScan credentials belong only in a process environment or the `URLSCAN_API_KEY` GitHub Actions secret. The hunter performs public search and result retrieval only: it does not submit scans, visit candidate sites, or store the credential in repository data. If the secret is absent, it makes no API request and records an explicit successful skip.

Accepted public results can also contribute a bounded page title and HTTP status, IP and autonomous-system context, URLScan's own verdict score/categories, and the limited TLS fields exposed for the same final hostname. A submitted candidate that independently matches the registry remains the indicator when the scan redirects, including when the destination is official; final-page hosting, screenshot, page, or TLS data is not assigned to that candidate. The defanged final hostname is retained as redirect context because redirects can be conditional or part of cloaking, not as a benign verdict. Provider assessment remains separate from Radar confidence. Page bodies, response content, extracted emails, cookies, request headers, and Google Safe Browsing state are not published.

The local UTC ledger defaults to no more than 25 search and 100 result requests per run, and 900 search and 8,000 result requests per day. These are intentionally below URLScan's published fixed-window quotas and are scheduling safeguards, not the provider's billing record. Every attempted request increments the local counter before transport, including an attempt that fails or receives HTTP 429. Reaching Radar's own cap produces a successful `budget-limited` run. Provider rate limiting instead produces a failed, degraded run, retains the previous successful timestamp and checkpoint, and stops further requests. API use and published metadata remain subject to URLScan's terms and quotas.

The twelve scheduled runs can therefore issue at most 300 searches and 1,200 result retrievals per UTC day, with at most one scheduled run in an hour. Manual dispatches share the persisted daily counters, run under the same serialized writer group, and must not be used to burst provider windows.

`data/urlscan/hunt-state.json` persists the numeric progress cursor, bounded candidate counts, UTC request counters, configuration state, timestamps, and latest outcome. It contains neither keys nor domains. The state distinguishes a completed attempt, local budget exhaustion, failure, and an unconfigured successful skip without rewriting historical observations.

`data/urlscan/search-checkpoints.json` separately persists a SHA-256 query identifier, the provider `search_after`
cursor, bounded results-seen count, completion state, and `lastProgressAt` for each active query. It never stores the query
text. Continuation is based on the provider total, returned page length, and cursor progress; the provider's `has_more`
flag is not treated as a page-completion flag. An unavailable request or exhausted local budget does not clear a cursor or
mark a backlog complete. Snapshot synchronization exposes only aggregate complete, partial, and backlog counts plus the
oldest backlog progress time in pipeline health.

A missing checkpoint file is a valid first-run bootstrap. A malformed or unreadable existing checkpoint is not treated as
an empty checkpoint: a configured hunt stops before any provider request and, when the prior bounded hunt ledger is
readable, persists a failed health transition without logging query text or the underlying exception.

### Official first-party asset pivots

A separate passive URLScan job runs at 03:47 and 15:47 UTC. It rotates through every reviewed `officialDomains` value across the registry, querying official sites one at a time so a high-volume brand cannot crowd other brands out of a combined result page. It retrieves only existing public URLScan reports and derives SHA-256 hashes only for successful first-party favicon and JavaScript responses. It never downloads an asset directly, submits a scan, or contacts a candidate host. Reports without a valid observation time, and observations older than 45 days, are not allowed to refresh the asset state.

An asset becomes pivot-eligible only while the same digest has timestamped support from at least two distinct public scans of a reviewed official site inside the 45-day evidence window. Within the retained collision ledger, hash ownership is remembered separately from the per-brand pivot shortlist, so a common library or icon learned for different brands in different runs remains blocked even when one copy falls outside a brand's top hashes. This memory is deliberately bounded rather than exhaustive: older entries can be evicted when an entry cap is reached. Active assets, retained pruned-hash ownership, and retained shared-hash tombstones expire from their latest official scan observation after 45 days. The state is bounded to three favicon and ten JavaScript pivot hashes per brand, 600 pruned ownership entries, 300 shared-hash tombstones, three timestamped supporting scans per asset, and 512 KiB overall at `data/urlscan/official-brand-assets.json`.

An exact hash match is discovery evidence only. Before publication, the candidate's public result document must contain the same typed resource hash and independently identify the same brand through the candidate-domain matcher or URLScan brand verdict. A matching page title qualifies only when URLScan also classifies the result as phishing. Conflicting brand evidence is rejected. When a submitted candidate redirects to an official page, the submitted hostname remains the candidate and the final hostname is retained only as redirect context; official destination metadata cannot qualify or enrich the candidate. The hash itself is not written as brand evidence and cannot make an otherwise unqualified row publishable.

The twice-daily job has its own conservative UTC ledger: at most 40 searches and 100 result retrievals per run, and 80 searches and 400 result retrievals per day. By default, it rotates 20 entries across every reviewed official domain, rather than sampling only the first website recorded for each brand, and pivots up to 12 eligible hashes per run. With the registry's maximum 598 per-brand pivot slots, two daily runs complete a hash-search rotation in less than 25 days, inside the default 30-day public-report lookback. Request exhaustion advances only work actually attempted, including a provider call that returns an error. These counters do not contain an API key and remain below the separate provider-wide account quota; operators must still consider the request use of the two-hour URLScan hunt.

The state records whether the optional key was configured and the latest completed, budget-limited, failed, or safely skipped outcome. Snapshot synchronization folds this credential-free status into the existing URLScan source note; it does not create another public source label.

## Passive DNS and RDAP context

At 01:13, 07:13, 13:13, and 19:13 UTC, Radar rotates through up to 20 candidates already present in the current published snapshot. For each selected hostname it sends only A, AAAA, CNAME, NS, and MX questions to Cloudflare's DNS-over-HTTPS endpoint and uses the [IANA RDAP bootstrap registry](https://data.iana.org/rdap/dns.json) to select the authoritative domain-registration service. The collector never sends HTTP traffic to the candidate hostname, follows page redirects, executes content, submits a form, or asks a third party to scan the page.

The bounded state at `data/enrichment/domain-context.json` can retain:

- up to 12 defanged answers for each supported DNS record type, the minimum TTL observed across successful answers, and the number of DNS question types completed;
- the defanged registrable parent actually queried, registrar name, registration, update, and expiry timestamps, and normalized RDAP status codes; and
- the public signal ID, defanged domain, collection time, rotating cursor, and aggregate latest-run outcome.

Registrant names, organizations, email addresses, telephone numbers, postal addresses, RDAP entity handles, remarks, raw responses, and candidate page content are not retained. A missing registration section can mean that no usable bootstrap service or public RDAP record was available; it is unknown, not evidence of benign status. Stored rows are capped at 2,500 and 4 MiB, are discarded after 14 days by default, and are removed sooner when the candidate leaves the current snapshot.

DNS and registration are independent context families. A temporary IANA RDAP-bootstrap failure still permits the selected DNS questions to refresh, publishes null registration for that point-in-time row, and marks the run partial. A total DNS failure does not replace the previous retained context. Only NOERROR and NXDOMAIN responses count as completed DNS questions.

Current records can appear as optional `domainContext` in the same-origin per-signal detail sidecar and as aggregate outcome/count metadata in `public/data/pipeline-health.json`. DNS values can also contribute to the bounded related-observation graph under its temporal, fan-out, and multi-family evidence rules. A shared address, nameserver, mail route, alias, registrar, or lifecycle date does not establish common control, a campaign, an actor, or maliciousness.

A separate bounded temporal collector rotates over the retained DNS/RDAP rows and caches RIPEstat prefix and ASN context;
optional RPKI validation is disabled unless explicitly enabled. It compares normalized components with the previous
baseline and writes semantic change records to `data/history/context/YYYY-MM-DD/events.ndjson`, retained for 60 days by
default and bounded from 30 to 90 days. The public signal-detail projection retains at most six recent changes per
signal and exposes only component hashes, changed-field names, timestamps, and allowlisted source references.

URLScan-derived baselines, change records, and public change projection are disabled by default. They are enabled only
when the repository variable `URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED` is exactly `true`, which records an explicit
operator confirmation that the intended redistribution is permitted. The API key alone does not provide that
confirmation. DNS, RDAP, RIPEstat, and RPKI context remain independent of this gate.

## Transient discovery seeds

Discovery lists are processed in memory, filtered through the Lithuania registry, and capped before they can trigger exact passive URLScan lookups. They are not copied into `data/`, do not create dashboard rows, and never appear as public source labels. The adapters use [PhishDestroy Primary Active](https://github.com/phishdestroy/destroylist) and CERT Polska's [active-domain text list](https://hole.cert.pl/domains/v2/domains.txt); their upstream license and processing conditions still apply.

The published observation source is URLScan, while discovery-input attribution remains documented in [Data licensing and attribution](../DATA-LICENSE.md).

## HECAVEX public export

The optional HECAVEX service input must use a deliberately limited public-export endpoint following the [public data contract](DATA-CONTRACT.md). Records pass the same automated schema, safety, and brand-scope checks as other inputs. The production feed requires HTTPS; the HTTP loopback exception exists only for local maintainer validation. The export must not expose a private dashboard, database, collector API, detector output, credentials, or internal case history.

The repository default is explicitly disabled (`HECAVEX_ENABLED=false`). Radar does not ship or infer an endpoint or token. Until HECAVEX provisions a deliberately public, read-only export and configures the documented variable and secret, the dashboard reports this source as not configured and continues with the other sources.

## Optional analyst provider checks

Google Safe Browsing and VirusTotal are not Radar discovery, publication, or scoring sources. A maintainer may manually dispatch the `Ephemeral analyst provider check` workflow with the 20-character identifier of a signal already present in `public/data/radar.json`. The public workflow derives the hostname from that repository snapshot, refuses arbitrary URLs and redirects, calls only VirusTotal's fixed API host, caps the response, and writes no result to Git or the public dataset.

The VirusTotal result is reduced in process to the provider's last-analysis counters and timestamp. It never changes `matchScore`, lifecycle state, review disposition, or retention. Public Actions summaries, logs, and artifacts are retained and visible, so the workflow deliberately emits only a generic completion result. Inspect provider details only by running the bounded command in a private local environment.

Google Safe Browsing v5 requires every queried URL result, including a no-match, to be cached until its individual `cacheDuration` expires. Radar therefore does not pass the Google key to public Actions. The private local command uses the git-ignored `.radar-local/provider-check-cache.json`, validates the provider duration, reuses unexpired entries, and atomically persists both match and no-match responses. A no-match or missing provider record remains unknown, not benign.

The public workflow reads only the repository Actions secret `VIRUSTOTAL_API_KEY`. A Google Safe Browsing key belongs only in the private local process environment as `GOOGLE_SAFE_BROWSING_API_KEY`; it must not be stored in this public repository's Actions configuration. Neither credential belongs in repository variables, workflow inputs, artifacts, issue text, or Pages code. The operator remains responsible for the providers' current usage, attribution, commercial-use, and redistribution conditions.

## Quality and review artifacts are not sources

`data/coverage/brand-coverage.json`, `data/review/review-queue.json`, and `data/matcher/lithuanian-brands-v1.json` are derived governance and regression artifacts. They do not collect a domain, create a public source label, or establish a verdict. The coverage ledger makes zero-signal brands and incomplete collector/review state explicit; the balanced queue organizes public candidates for later review; and the matcher corpus exercises reserved-domain synthetic and reviewed official-domain cases in CI.

Similarly, a file below `data/review/proposals/` is a sanitized draft proposal awaiting pull-request review, not a decision. Only an intentionally exported entry in `data/review/public-decisions.json` can affect synchronization, and the current public sample can legitimately contain no completed assessment.

## Screenshots

Screenshots are optional and URLScan-only. The publisher accepts HTTPS URLs on exactly `urlscan.io`, removes query strings and fragments, and rejects credentials, non-default ports, and subdomains. The dashboard loads a screenshot only when requested and never embeds or contacts the observed site.
