# Period metrics

Use this contract when changing a period count, UTC window, coverage statement,
complete-cohort reader or export. Durable identity and clocks are defined in
[OBSERVATIONS.md](OBSERVATIONS.md).

| Change | Owning source | Focused verification |
| --- | --- | --- |
| Period queries, exact day membership and clock completeness | `hecavex_radar/period_metrics.py` | `tests/test_period_metrics.py` |
| Public records, coverage and current eligibility | `hecavex_radar/observation_runtime.py` | `tests/test_observation_runtime.py` |
| Public index/parts and schemas | `hecavex_radar/observation_publication.py`, `observation_schemas.py` | `tests/test_observation_publication.py` |
| Browser cohort verification and overview (full panel on the history pages; 30-day summary on the overview, which embeds metrics without records) | `src/lib/periodMetrics.ts`, `src/components/PeriodOverview.tsx` | `scripts/period-metrics.test.mjs` |

## Population and time basis

The headline population is **distinct canonical hostnames observed during the
selected observation-time period**, among the complete currently eligible recorded
inventory. It includes subdomains as separate identities. Private-PSL domain
groups are a separately deduplicated secondary count.

The inventory derives from durable accepted facts and bounded trusted recovery,
not the expiring legacy history summary or the current dashboard shortlist.
Current registry and review policy determine the public projection. A changed
policy can therefore change the public eligible population while all original
facts remain archived. Counts are exact within this declared recorded population;
they are not a census of every domain registered or every phishing hostname.

New publications use `timeBasis: source-observation-or-explicit-collector-fallback`;
`identityUnit` is `canonical-hostname`; `population` is
`public-eligible-recorded-hostnames`. A usable provider timestamp determines
membership. Otherwise, the actual collector timestamp determines membership and
the fact explicitly records `collector-time-fallback`; the unknown provider time
is never asserted as known. This keeps an accepted hostname visible without
claiming a provider observation date. Archive replay preserves the original
collector fallback rather than moving the observation to every sync's current
time.

New hostname records summarize timing origins in the additive
`sourceTimeProvenances` field. `provider-observation-time` establishes a usable
provider boundary, `collector-time-fallback` identifies the declared fallback,
and `legacy-normalized-unknown` means earlier normalization provenance cannot be
reconstructed. These are per-host summaries, not a claim that every historical
observation uses the same origin. Older v1 records without the summary and old
metrics declaring `source-observation-time` remain valid archived artifacts;
their missing provenance remains unknown. Consumers accept only these two
declared time bases.

A complete cohort explicitly containing a collector fallback cannot declare
the older provider-only time basis. Producer and browser validation reject that
contradiction; accepting archived formats does not weaken this semantic check.

Provider observation, Radar recording and actual publication clocks remain
separate. A late imported event with a trustworthy provider timestamp belongs
to its source period even when Radar records it much later.

A completed UTC month closes the time window, not the underlying evidence.
Late observations, recovered facts and current-policy corrections can revise a
later publication's totals for that month. Compare the declared cutoff, cohort
digest and policy versions; earlier committed releases retain their original
facts and results. Do not silently freeze a month or treat a revised total as a
new live observation.

## Window definitions

All windows use canonical UTC milliseconds and half-open bounds
`[startInclusive, endExclusive)`. The artifact has one explicit `asOf` cutoff.
Public logical rows contain only effective observation facts at or before that cutoff.

| Key | Start | Exclusive end |
| --- | --- | --- |
| `30d`, `90d`, `365d` | `asOf` minus exactly that many UTC days | `asOf` plus one millisecond |
| `all` | null: every retained recorded effective observation | `asOf` plus one millisecond |
| `month:YYYY-MM` | UTC start of the calendar month | UTC start of the next month |

The one-millisecond upper increment includes facts exactly equal to the
millisecond-resolution cutoff. Calendar months use whole UTC boundaries; the
current month still contains only facts available through `asOf`, and its
partial-day state is explicit. The contract also permits `year:YYYY` with whole
UTC calendar-year boundaries; the current builder emits the rolling, all and
calendar-month windows.

The `all` label means all recorded history since the declared available boundary.
Unknown earlier coverage remains unknown. `all` is not an assertion of complete
universal history.

## Counts

Each window carries:

- `uniqueHostnames`: distinct eligible canonical IDs with an actual observation
  inside the window.
- `domainGroups`: distinct private-PSL parents of those selected hostnames.
- `candidateDays`: distinct `(hostname ID, UTC effective observation day)` memberships inside
  the window. Repeated providers or paths on that day do not multiply this count.
- `firstRecordedHostnames`: nullable count querying first-ever Radar recording
  clocks across the complete eligible inventory.
- `firstPublishedHostnames`: nullable count of first successfully captured
  verified publication receipts for modern tracked eligible hostnames with known
  first recording clocks.
- `exactWithinRecordedData: true` and the separate `completeCollection` flag.

Recording/publication counts query their own clocks independently of observation-time
membership. A January source observation first recorded in October can contribute
to October's recording count while contributing zero to October's observed-host
count.

A hostname observed on 20 days contributes one distinct hostname and 20
candidate-days. Two subdomains of one private-PSL parent contribute two hostnames
and one group. Observations in January and March contribute zero February
membership. Summing daily distinct counts does not produce period-distinct
hostnames; first/last bounds do not establish intermediate-day membership.

For a rolling window's partial lower UTC day, use
`observedDayLastSeen[day] >= startInclusive`. The per-day latest timestamp is
sufficient because rolling windows run through `asOf` and calendar windows use
whole UTC days. The durable store retains the full original timestamps for other
future query shapes. Consumers must not silently generalize this public day map
to arbitrary intraday end cutoffs.

## Coverage and unknown clocks

Coverage contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `availableFrom` | Earliest effective observation timestamp in the public eligible recorded population, or null. |
| `recordedFrom` | Activation watermark for reliable future Radar recording capture, or null. |
| `publicationRecordedFrom` | Activation watermark for captured verified publication receipts in the modern tracked cohort, or null. |
| `recoveredFrom`, `recoveredThrough` | First/last recovered UTC partition days, or null. |
| `recoveredDays`, `missingDays` | Sorted unique UTC days with recovered partitions or known unavailable partitions in the declared recovery scope. |
| `historyComplete`, `collectionComplete` | Explicit completeness claims; unknown prehistory or collection gaps keep them false. |
| `historicalRecordingTimesComplete` | Whether historical first recording clocks are established for the declared population. |
| `historicalPublicationTimesComplete` | Whether historical first captured verified receipt clocks are established in the declared tracked scope. |
| `basis` | `recorded-and-recovered-observation-facts`. |
| `partialCurrentDay` | Whether the current UTC day is still partial. |

A recovered partition with zero eligible events and an unavailable partition are
different states. Missing input never establishes a zero collection result.
Exact counts within known recorded facts remain numeric even when collection
coverage is partial; their coverage flags and stated population qualify them.

First-clock counts remain null when historical clocks are unknown, except for a
window starting at or after the corresponding capture activation watermark.
In that post-activation interval, known legacy hostnames cannot become newly
recorded identities, and publication counts enumerate the modern tracked receipt
cohort. Legacy unknown publication clocks remain null even when the hostname is
verified present. Failed/canceled runs or receipt compare-and-swap gaps do not
establish the earliest-ever actual publication; first captured receipt counts
make no complete-publication or prevalence claim. A window crossing the watermark
remains null. `all` remains null unless historical clocks are complete within the
declared scope. A claim of complete historical clocks contradicted by a null
hostname clock fails validation.

## Artifact and cohort binding

`/data/period-metrics-v1.json` contains `schemaVersion: 1`,
`dataset: radar-period-metrics`, `generatedAt`, `asOf`, time basis, identity unit,
population, `hostnamesSha256`, grouping, coverage, policy versions and `windows`.
`generatedAt` equals `asOf`.

`hostnamesSha256` binds the exact bytes of `/data/observed-hostnames-v1.json`.
That index binds every current hostname part by path, bytes, hash and exact count.
Metrics and inventory use the same cutoff, grouping, coverage and policy
versions. `policyVersions` has the exact keys `identity`, `matching`, `review`,
`metrics` and `store`. Grouping identifies the bundled private PSL version and
digest. Existing release metadata binds source and input data identities; these
artifacts do not claim the eventual commit hash of their own generated output.

A consumer verifies the index hash, every part, total count, canonical IDs and
record membership, then recomputes every window before enabling complete filters
and export. A missing part, digest mismatch, mixed cutoff or divergent count
fails the cohort. Server-rendered authoritative counts can remain visible with a
clearly bounded preview; export remains disabled until the complete cohort is
coherent. Unknown history is shown as unknown, and a known zero recorded
population is shown as zero with its coverage scope.

Snapshot v2, legacy history, daily trends and the publication-event change stream
retain their separate meanings. Their rows or daily totals must not replace the
period inventory behind these metrics.
