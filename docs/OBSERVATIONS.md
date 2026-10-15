# Durable observations and hostname inventory

Use this contract when changing accepted observation identity, durable storage,
historical recovery, eligibility, recording clocks or publication receipts. For
period queries and their public counts, use [PERIOD-METRICS.md](PERIOD-METRICS.md).
Legacy event retention is defined in [HISTORY.md](HISTORY.md).

| Change | Owning source | Focused verification |
| --- | --- | --- |
| Identity, deduplication, durable parts, public logical rows | `hecavex_radar/observation_store.py` | `tests/test_observation_store.py` |
| Live capture, recovery import, current policy projection | `hecavex_radar/observation_runtime.py` | `tests/test_observation_runtime.py` |
| Trusted Git recovery and missing intervals | `hecavex_radar/history_recovery.py` | `tests/test_history_recovery.py` |
| Public index and complete part validation | `hecavex_radar/observation_publication.py`, `observation_schemas.py` | `tests/test_observation_publication.py` |
| Actual publication clocks | `hecavex_radar/publication_receipts.py` | `tests/test_publication_receipts.py` |

## Identity and facts

The identity unit is a canonical hostname. IDNA uses the pinned `idna` package,
UTS 46 nontransitional processing and STD3 rules. The public hostname is the
lowercase, defanged ACE representation. Its existing 20-hex identifier is
`stable_id(defanged_hostname.lower())`. A Unicode label and its valid A-label
share an identity. Different confusable hostnames and different subdomains keep
different identities; matching a reviewed brand never changes hostname identity.

Each hostname also has a defanged Unicode display and a private-PSL registrable
parent. Grouping records the pinned `tldextract` version, `privateSuffixes: true`
and the SHA-256 of its bundled PSL snapshot. For a valid hostname without a
recognized public suffix, the group is the hostname itself. Grouping does not
merge hostname identities.

An observation is an accepted source timestamp for a canonical hostname and a
sorted source set. Its full SHA-256 identity includes `hostnameId`, `sources`,
`sourceObservedAt` and a nullable `providerEventId`. A provider ID enters the key
only when the provider actually supplies a trustworthy identity. Scores, status,
reason labels, clocks, legacy event IDs and provenance are separate annotations.

Re-ingesting the same observation unions distinct match, assessment and provenance
annotations without increasing observation cardinality. Legacy event IDs include
status-related fields; they remain provenance and never replace the normalized
observation key. Distinct annotation variants remain inspectable.

Only explicit source boundaries create membership. An observation on January 1
and another on March 1 establish two observed days. They establish no February
membership. Repeated source paths or timestamps do not multiply a hostname's
membership in a UTC day. Status transitions and legacy `first-publication`
markers remain legacy evidence; they do not independently create observations.

## Storage and retention

The operational store is `data/history/observations/index.json`, with
`schemaVersion: 1` and `dataset: radar-observation-store-v1`. It references
content-addressed JSON arrays under `months/YYYY-MM/<sha256>.json` and
`hosts/<sha256>.json`. Observation partitions use the source timestamp's UTC
month. The hostname inventory is independent of current brand eligibility and
the expiring compatibility summary.

The current index retains every accepted fact. The 30-day detail and 730-day
legacy summary settings never expire this store. Reclassification, suppression
or disappearance from the current dashboard does not remove archived facts.
Changing IDNA or PSL identity policy requires an explicit migration; a mismatched
stored identity profile fails validation.

Each index and part is at most 256 KiB. A cohort supports at most 512 parts and
128 MiB of referenced part bytes. A single observation, including its provenance
variants, must fit one part. Capacity failures abort instead of evicting rows.
The complete operational tree must also fit the data-branch transport limits.

Writers validate all capacity before writing, write content-addressed parts first
and atomically replace the index last. Every reader checks regular paths,
allowlisted partition paths, hashes, sizes, exact counts, unique observation IDs
and agreement with the independent hostname inventory. Missing, altered or linked
parts fail closed. After the new index commits, only obsolete generated part
encodings are removed from the working tree. Every fact remains referenced by
the current index; earlier committed encodings remain recoverable through Git.

Recovery reads regular data blobs reachable from explicitly pinned trusted Git
heads and writes an isolated `recovery.json` with `recovery.sha256`. Import checks
that companion digest, uses the bundle's `availablePartitionDays` for recovered
coverage and keeps missing partitions explicit. Unresolved transition-only
boundaries block import before facts or metadata are written. Recovery copies
known source boundaries without inventing interior days, recording clocks or
publication clocks. Actual import time is supplied separately from bundle
generation time.

First capture also validates the retained raw legacy summary and imports its
first/last source boundaries, including rows excluded from the current public
history. Summary observation counts establish no additional days. This preserves
available earlier boundaries independently of current registry or review policy.
Bootstrap follows the configured legacy history root; durable observations keep
their independent `data/history/observations/` location.

## Separate clocks

All known timestamps are canonical UTC strings with millisecond precision.
Unknown historical clocks are explicit `null`.

| Clock | Meaning |
| --- | --- |
| `sourceObservedAt` | Timestamp established by the source boundary, with separate time provenance. |
| `radarRecordedAt` | Known time Radar accepted the individual fact after capture activation. |
| `importedAt` | Separately supplied recovery/import time; it does not establish historical Radar admission. |
| `firstRecordedAt` | First-ever tracked Radar recording for a public hostname, only when the retained evidence establishes it. |
| `firstPublishedAt` | First successfully captured verified publication receipt since activation, scoped to modern tracked hostnames with known first recording. |

Historical source times remain usable when their original Radar recording time
is unknown. Importing or observing an old hostname again never substitutes the
migration time for its first-ever recording. If any accepted legacy fact has an
unknown recording clock, the hostname's `firstRecordedAt` remains null. Replaying
an observation cannot replace an unknown original clock with the replay time.

Preparation time, snapshot `generatedAt`, sync heartbeat, source `firstSeen` and
legacy `first-publication` event time do not establish an actual publication.
Publication capture runs after successful release verification and binds full
source/data revisions, the exact public hostname-index digest and the served
tracked hostname IDs. It validates the local complete index, every part and
recomputed metrics, then compares the exact served bytes of all those artifacts
before writing a receipt. Requests have finite response, aggregate and time
budgets; redirects are refused. Receipts are retained by publication UTC month
under `data/history/publications/`; capture activation is separate. Legacy
hostnames keep unknown first publication clocks, including when a caller
mistakenly supplies them in a receipt map.

The receipt cohort includes only modern tracked hostnames whose first Radar
recording is known. This clock identifies the first successfully captured
verified receipt. A failed or canceled run, or a receipt compare-and-swap failure
after deployment, cannot establish the earliest-ever actual publication. A later
captured receipt makes no claim that the hostname was never served earlier.
Receipt-derived counts describe this tracked capture scope, not complete public
publication or prevalence. Archive capacity and activation consistency are
validated before any receipt metadata is written.

## Public eligible projection

The archive preserves original observations and policy annotations. Each public
projection applies the current reviewed registry, collision checks and sanitized
review policy to those facts. A suppression changes public eligibility while
retaining the archived observations. Public eligibility is a candidate rule,
not a maliciousness verdict.

The complete logical hostname record carries identity/group/brand, source first
and last timestamps, nullable first recording/publication clocks, sorted
`observedDays`, `observedDayLastSeen`, sorted sources, a versioned `match`, nullable
`assessment` and `recordAvailable`. The day map has exactly the same keys as
`observedDays`; each value is the latest retained source timestamp on that day,
at or before `asOf`. It supports the partial lower day of rolling queries without
publishing every individual event.

`match.score` is a nullable candidate match score. Its `reasonCodes` describe the
attributed matching evidence and `policyVersion` identifies that rule set. The
envelope separately identifies identity, matching, review, metrics and store
policies. Historical unknown matching policy remains distinguishable from the
current matcher. A domain match is recomputed under the current matcher; archived
labels must not be presented as its current explanation.

The current matching fingerprint includes the registry, explicit algorithm
version, trusted matcher/reason-mapping source hashes, Unicode security profile,
private-PSL profile, curated IDN profile and effective rollback setting. Source
hashes normalize CRLF so the same trusted source has the same fingerprint on
Windows and Linux. Historical off-domain evidence retains its original match
score, reasons and policy attribution while current eligibility is reported in
the envelope.

An assessment is either null or an explicit review decision with exactly
`verdict`, `assessedAt`, `decisionId`, `analystConfidence` and
`evidenceReferences`. Verdicts are `malicious`, `suspicious`, `benign` or
`inconclusive`. `confirmed-suspicious` maps to `suspicious`. Provider operational
status and a high match score cannot create a malicious verdict. Analyst
confidence is a separate nullable 0–100 value. Public evidence references come
from the sanitized public review projection; private notes and raw references
stay outside public records.

`recordAvailable` is true only when a corresponding record route is in the
published detail cohort. A retained hostname without that route remains usable
as a defanged identity and period member.

## Public wire format

`/data/observed-hostnames-v1.json` is always an index, including at zero records.
It contains `schemaVersion: 1`, `dataset: radar-observed-hostnames`, `generatedAt`,
`asOf`, `recordCount`, coverage, policy versions, grouping and partition
descriptors. It contains no empty inline `records` or `signals` collection.

Each descriptor names `/data/observed-hostnames-parts/<sha256>.json`, its exact
byte size, SHA-256 and record count. Each part is a JSON array. All records are
sorted by ID and the complete set supports at most 25,000 rows and 512 parts;
the index and each response are capped at 256 KiB. Zero records require zero
parts. Consumers resolve every declared part and verify the complete cohort
before enabling complete filtering or export. A bounded HTML preview remains a
preview when full loading fails.

These v1 artifacts are independent of snapshot v2 and the inline/partitioned
legacy history wire versions. See the generated public schemas and
[PERIOD-METRICS.md](PERIOD-METRICS.md) for metrics binding and coverage semantics.
