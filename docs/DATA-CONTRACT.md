# Public data contract

Radar records potential impersonation leads, not a list of proven phishing sites. The primary reporting unit is a **unique canonical hostname observed during the selected UTC period**. Subdomains count separately; registrable domain groups appear as a separate metric using the bundled public/private suffix list. Unicode and its IDNA ASCII encoding identify the same hostname.

## Choose a contract

| Task | Artifact | Contract and implementation |
| --- | --- | --- |
| Count or export observed hostnames | `/data/observed-hostnames-v1.json` index and its digest-bound parts | [Observed hostnames](OBSERVATIONS.md); `observation_store.py`, `observation_publication.py` |
| Compare 30/90/365 days, a calendar month or all recorded observations | `/data/period-metrics-v1.json` | [Period metrics](PERIOD-METRICS.md); `period_metrics.py` |
| Inspect the current recent shortlist | `/data/radar.json`, `/data/radar.index.json` and shards | [Compatible snapshot contract](LEGACY-DATA-CONTRACT.md#public-snapshot) |
| Read legacy summaries or recent event details | `/data/history.json`, event feeds | [History and retention](HISTORY.md), [compatible feeds](LEGACY-DATA-CONTRACT.md#publication-event-and-syndication-feeds) |
| Inspect provider evidence or passive context | `/data/signals/<id>.json` | [Evidence sidecars](LEGACY-DATA-CONTRACT.md#per-signal-detail-sidecars) |
| Consume explicit analyst decisions | Sanitized review export, reviewed STIX/MISP | [Review contract](LEGACY-DATA-CONTRACT.md#sanitized-review-decisions), [sharing gates](MISP-SHARING.md) |
| Validate a complete publication | `/data/feed-manifest.json` and checksum companions | [Integrity](LEGACY-DATA-CONTRACT.md#complete-signal-distribution-and-integrity), `publication.py` |
| Implement or review a change | Producer/reader tests | [Source map](CODEMAP.md), [deployment and migration](DEPLOYMENT.md) |

Every artifact has its own explicit wire version. The new observation contracts are version 1; the recent snapshot remains version 2. Machine schemas live under `/data/schemas/`. Accept listed versions only. The Python producer validates canonical identities, scope, defanging, schemas, counts and digests; the browser independently verifies the complete period cohort before enabling filtered exports.

## Records and clocks

An observed-hostname record has a stable `id`, defanged ASCII `domain`, `domainGroup`, `brand`, effective observation `firstSeen`/`lastSeen`, exact `observedDays` and per-day latest observation timestamps, independent `firstRecordedAt`/`firstPublishedAt`, `sources`, `match`, optional explicit `assessment`, and `recordAvailable`. New exports include `sourceTimeProvenances`, distinguishing provider timestamps, declared collector-time fallbacks and unknown legacy normalization. Older v1 records without that additive field remain readable with unknown timing provenance. See the [field definitions](OBSERVATIONS.md) for the exact shape.

Matching reasons and score describe why a hostname qualified. An assessment describes a separately recorded analyst decision, with its own confidence and evidence references. A match never automatically becomes a malicious verdict. `confirmed-suspicious` remains **suspicious**. Live provider destinations and private notes do not enter these exports.

`firstSeen` uses a valid provider observation time, or an explicitly identified collector time when the provider time is missing, invalid or unacceptably future-dated. The durable provenance retains the unavailable provider time and fallback reason; historical normalization cannot be retroactively verified. This clock does not establish registration, website activity or actual publication. Recording begins when durable capture is activated. `firstPublishedAt` means the first successfully captured verified publication receipt after activation. Capture verifies the exact source/data release and served hostname cohort after Pages succeeds. A failed or canceled receipt job can miss an earlier served publication, so this is not an earliest-ever public timestamp. Legacy recording and publication times remain `null`; later reobservation does not manufacture an earlier clock.

## Coverage, totals and retention

Period totals count membership in actual preserved observation days. They do not infer daily activity between first and last sighting and do not sum monthly unique counts. Candidate-days and domain groups are separate measures. Current review/matcher policy controls the public population; corrections can change a published population without deleting archived source facts.

The durable store has no rolling expiry. The older recent event and summary views retain their bounded compatibility windows. Git recovery imports only bounded regular blobs from explicitly trusted source/data ancestry, preserves provenance and checks reconciliation before becoming authoritative. Missing days and unknown older times remain explicit in `coverage`. “All recorded” means all eligible retained/recovered facts, not complete lifetime or Internet coverage.

The index always describes the complete cohort through bounded partitions. A missing partition, inconsistent total, unsupported version or digest mismatch fails visibly. A bounded static preview preserves authoritative totals while the browser verifies the complete cohort. It cannot enable a partial export. Capacity exhaustion fails publication instead of silently evicting history.

## Curated IDN match evidence

The current-release character provenance remains `/data/idn-matches-v1.json`; see [its compatible contract](LEGACY-DATA-CONTRACT.md#curated-idn-match-evidence) and [detection policy](DETECTION.md). IDN admission still produces a name-only, suspected, unreviewed lead unless independent review supplies another assessment.

## Website Dataset metadata

The existing [Dataset metadata contract](LEGACY-DATA-CONTRACT.md#website-dataset-metadata) remains compatible. Dataset distribution metadata and a successful build do not prove actual live publication.

## Website analytics boundary

The existing [analytics boundary](LEGACY-DATA-CONTRACT.md#website-analytics-boundary) remains unchanged. Indicator queries and exports run locally in the browser; query content does not enter analytics or a remote search request.
