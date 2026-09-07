# Public data contract

This contract governs the artifacts published by [radar.hecavex.com](https://radar.hecavex.com). The service's Python publisher is the normative producer of public data: it normalizes, scopes, and defangs every accepted observation before writing a snapshot. The browser checks the snapshot version and structure before rendering it; that structural check is not a substitute for producer-side validation.

## Public snapshot

The dashboard reads `public/data/radar.json` with this top-level shape:

```json
{
  "schemaVersion": 2,
  "dataset": "live",
  "generatedAt": "2026-08-21T09:15:00.000Z",
  "lastSuccessfulSyncAt": "2026-08-21T10:17:00.000Z",
  "signals": [],
  "sources": []
}
```

`generatedAt` is the UTC time of the latest material snapshot change. `lastSuccessfulSyncAt` is the most recent successful publisher run, including a run that validated the same observations and made no material data change. It is never earlier than `generatedAt`. The dashboard uses `lastSuccessfulSyncAt` for publisher freshness and reports `generatedAt` separately as the data-change time. Public timestamps use canonical `YYYY-MM-DDTHH:mm:ss.sssZ` form.

### Version compatibility and migration

Contract versions are allowlisted, not interpreted as minimum versions. A consumer must reject a live snapshot whose
`schemaVersion` is not listed below, even when the remaining fields happen to resemble the current shape.

| Artifact | Produced version | Accepted versions | Migration behavior |
| --- | ---: | --- | --- |
| Live Radar snapshot (`radar.json`) | 2 | 2 only | No read migration. Versions 1, 3, and unknown versions are rejected. A future version must update the schema, every consumer, the minimal fixture, and both Python and browser contract gates in one change. |
| Sanitized review decisions (`public-decisions.json`) | 3 | 1, empty-assessment 2, and 3 | Version 1 has no assessments and preserves the legacy candidate `matchScore` migration. Version 2 is accepted only with an empty `assessments` array. Writers emit version 3 with immutable public-observation admission provenance. |

The live-snapshot compatibility gate covers these readers:

| Consumer | Boundary exercised by CI | Accepted live version |
| --- | --- | ---: |
| Browser dashboard | `src/lib/data.ts::parseSnapshot` | 2 |
| HECAVEX analyst handoff | `hecavex_radar.hecavex::read_snapshot_signals` | 2 |
| DNS/RDAP enrichment | `hecavex_radar.domain_context::_snapshot_signals` | 2 |
| Synchronization retention and count guard | `hecavex_radar.sync::_load_existing_snapshot` and `_existing_signal_count` | 2 |
| URLScan seed selection | `hecavex_radar.urlscan::_load_radar_snapshot_seeds` | 2 |
| Publication event feeds | `hecavex_radar.event_feeds::build_event_feeds` | 2 |
| Observation-only STIX projection | `hecavex_radar.stix::build_stix_bundle` | 2 |
| Manual provider corroboration | `hecavex_radar.provider_checks::_load_signal` | 2 |
| Stratified review queue | `hecavex_radar.review_queue::build_review_queue` | 2 |
| Review brand-resolution fallback | `hecavex_radar.review::_current_brand` | 2 |
| Aggregate pipeline-health sentinel | `hecavex_radar.health_sentinel::_evaluate_snapshot` | 2 |

`tests/fixtures/radar-snapshot-v2-minimal.json` is the smallest checked-in positive fixture shared by the contract tests.
`tests/test_snapshot_contracts.py` passes both that fixture and the checked-in generated snapshot through every Python
reader above, checks the intentional review-v1 migration, and rejects live versions 1 and 3. The
`pnpm verify:contracts` gate applies the same positive and negative cases to the browser loader.

Before publication, observations and retained rows are checked against the current Lithuanian brand registry. Official or suppressed hosts, observations without a resolved registry brand, reviewed exclusions, and conflicting brand/domain mappings are dropped. The dashboard snapshot is capped at 512 KiB. The publisher proves the largest newest-first prefix that fits even if every row had a detail sidecar; it therefore cannot fail later merely because valid enrichment adds `detailAvailable`. The complete accepted ordered set is written to deterministic 256 KiB shards and indexed by `radar.index.json`, which reports both complete and dashboard counts. This is a presentation boundary, not silent data loss.

### Signal fields

Each signal represents one normalized host. Observations of different paths on that host share one public row.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | First 20 hexadecimal characters of SHA-256 over the normalized defanged hostname. |
| `url` | string | Defanged HTTP(S) indicator; userinfo is rejected, query and fragment are removed, and nested URLs and sensitive path segments are redacted. |
| `domain` | string | Defanged normalized hostname. |
| `firstSeen` | UTC timestamp | Canonical millisecond form; invalid or missing input becomes the normalized `lastSeen`, and it is never later than `lastSeen`. |
| `lastSeen` | UTC timestamp | Canonical millisecond form; invalid or missing input becomes the UTC synchronization time. |
| `sources` | string[] | Deduplicated observation providers: `CertStream`, `URLScan`, or `HECAVEX`. Discovery-seed lineage is not included. |
| `status` | enum | `active`, `suspected`, `offline`, `mitigated`, or `unknown`. |
| `brand` | string or null | Registry-resolved claimed target, not attribution. |
| `country` | string or null | Hosting observation, not actor location. |
| `host` | string or null | Provider/ASN text or a defanged address. |
| `screenshotUrl` | string or null | Optional HTTPS URL on exactly `urlscan.io`, never a subdomain. Credentials and explicit ports are rejected; query and fragment are removed before publication. |
| `referenceUrl` | string or null | Optional canonical `https://urlscan.io/result/<uuid>/` report URL. |
| `hashes` | string[] | Up to eight unique, lowercase, non-empty SHA-256 hashes of primary HTML response bodies. |
| `reasonCodes` | string[] (optional) | Up to 16 controlled public provenance labels. They explain automated acceptance inputs; they are not verdicts or private detector features. |
| `discoveredVia` | string[] (optional) | Controlled collection lineage such as live CertStream, checkpointed CT search, public URLScan report, HECAVEX export, or review export. |
| `corroboratedBy` | string[] (optional) | Controlled supporting-evidence lineage. Discovery and corroboration remain separate; a second label is not analyst confirmation. |
| `detailAvailable` | `true` (optional) | Declares that one validated same-origin detail sidecar exists for this signal. Absence means no sidecar; `false` is invalid. |
| `matchScore` | integer | Rounded 0-100 matcher/ranking score. It is not a probability, maliciousness verdict, or analyst confidence. |
| `evidenceTier` | enum | `name-only`, `corroborated`, or `reviewed`. Corroboration means an additional bounded source/evidence input, not confirmation. A primary-HTML hash captured in the same provider observation remains context; it counts only when an explicit cross-observation pivot or another independent input is present. |
| `reviewState` | enum | `unreviewed`, `needs-review`, `confirmed-suspicious`, `false-positive`, `benign-brand-reference`, or `inconclusive`. Only an explicit sanitized analyst assessment can set a reviewed disposition. Suppressed rows normally do not remain in the snapshot. |
| `ltRelevance` | enum | `lithuanian-targeting`, `lithuanian-brand-relevance`, `global-brand-reference`, or `unknown`. Registry scope alone produces `lithuanian-brand-relevance`; it is not evidence that a page targeted Lithuania. |
| `confidence` | integer | Deprecated transition alias. It is always identical to `matchScore`; new consumers must use `matchScore`. |

When signals merge, the publisher unions sources and hashes, keeps the earliest `firstSeen` and latest `lastSeen`, selects the most specific safe path, and keeps the highest `matchScore`. Conflicting non-null brands for one host invalidate the merged row. Status comes from the observation with the newest `lastSeen`; only observations at the same time use the tie-break order `active`, `suspected`, `unknown`, `offline`, then `mitigated`. The newest non-null country, host, screenshot, and reference metadata wins. The final list is newest-first and capped by `RADAR_MAX_SIGNALS`.

### Source fields

The top-level `sources` array reports the state of each supported public source.

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | `CertStream`, `URLScan`, or `HECAVEX`. |
| `homepage` | string | Fixed provider homepage paired with `name`; arbitrary source links are rejected by the viewer. |
| `fetchedAt` | UTC timestamp or null | Canonical millisecond form for the current successful archive/feed load, current failed-attempt time, or previous successful load when recent rows are retained. |
| `records` | non-negative integer | Accepted records represented for that source, not a lifetime total. |
| `state` | enum | `healthy`, `partial`, or `skipped`. |
| `note` | string or null | Short public collection or retention note. |

`partial` means an attempted source was unavailable or only retained recent rows remain. `skipped` means the source was not configured for that publication.
For archive-backed inputs, `healthy` confirms that the publisher loaded and validated the available archive; it is not an upstream collector-uptime or freshness guarantee.

## Complete signal distribution and integrity

`public/data/radar.index.json` indexes the complete accepted signal set in the same deterministic newest-first order used by the dashboard. Each row identifies a numbered file below `public/data/radar-shards/`, its signal count, byte length, SHA-256 digest, and first/last signal IDs. Every shard is independently capped at 256 KiB and validated against `radar-shard-v1.schema.json`. Stale numbered shards are removed during the same synchronization.

`public/data/feed-manifest.json` records the publisher name/version, checked-out generator Git revision, an exact copy of each snapshot source's `fetchedAt` value under `sourceFetchedAt`, complete and dashboard counts, and the length and SHA-256 digest of every atomic hourly release artifact. A source timestamp is source-specific archive-read or provider-state evidence; it is not a proven observation or coverage cut-off. Each listed artifact also has a conventional adjacent `.sha256` file. The manifest deliberately does not digest itself; `feed-manifest.json.sha256` provides that outer integrity value without creating a recursive document.

`public/data/collection-health.json` is replaced and deployed independently four times per hour, so it is deliberately excluded from the hourly manifest and adjacent checksum set. Its latest available bounded values are copied into the next synchronized `pipeline-health.json` release. This keeps the manifest atomic instead of making it stale every time the independent health path advances.

Versioned Draft 2020-12 JSON Schemas are published below `public/data/schemas/`. Synchronization validates generated JSON before publication, CI revalidates the checked-in artifacts and all index/manifest digests, and the observation and reviewed STIX files additionally pass the standard STIX 2.1 validator. A digest proves byte integrity and release consistency, not that a candidate is malicious.

## Publication event and syndication feeds

`public/data/events.json` is the canonical defanged publication-event record used by the `/changes/` interface and all
syndication views. Its window is the 30 days ending at `generatedAt`. It is ordered newest first, retains at most 1,000
events, and exposes `totalAvailable` plus `truncated` so a consumer can distinguish a complete bounded window from a
size-limited view. Event types are:

- `first-publication`: the first explicit public status transition for a signal;
- `reobservation`: a later source observation for an already published signal;
- `status-change`: an explicit transition with a non-null previous status; and
- `retraction`: an intentionally exported revoked analyst assessment, not an inference from disappearance.

Each event contains a deterministic 32-character ID, canonical time, public signal ID and stable retained signal path,
defanged domain, reviewed registry brand, current and previous status where applicable, and supported public source labels.
The event stream is a current-policy projection of durable history: a row is emitted only while its signal ID belongs to
the dashboard snapshot or filtered public history. Matcher, registry, or review revalidation can therefore remove
a row from this projection without deleting the underlying bounded history or asserting that the domain is benign. It
contains no clickable candidate URL, query, fragment, analyst identity, or private note. Absence from a later collection
window never creates a retraction or status event.

`public/data/events.atom.xml`, `public/data/events.rss.xml`, and `public/data/events.feed.json` are Atom, RSS 2.0, and JSON
Feed 1.1 projections of exactly the selected global event set. Feed links are absolute same-origin HTTPS URLs to signal
records that exist in the same static release; indicator text remains defanged. The event JSON is capped at 1 MiB and each
syndication document at 2 MiB.

`public/data/brand-feeds.json` is the deterministic directory for per-brand Atom, RSS, and JSON Feed files below
`public/data/brands/<slug>/`. A feed is emitted for every reviewed registry brand, including a valid empty feed. Each brand
feed is only a filtered view of the already bounded global event set, never a separate collection result. Consequently, an
empty brand feed means no publishable event for that brand in the sampled 30-day window; it does not mean the brand had no
phishing activity. Slugs are normalized, collision-safe publication identifiers and must be read from the directory rather
than reconstructed by a consumer. The directory is capped at 128 brands and 256 KiB. Every global and per-brand feed is
listed in the atomic release manifest and has an adjacent checksum.

## STIX 2.1 projection

`public/data/radar.stix.json` is a static STIX 2.1 Bundle generated from exactly the same accepted signal list as
`public/data/radar.json`. It is a pull/download distribution, not a TAXII discovery, Collections, filtering, pagination,
authentication, or push service. A qualifying source observation reaches it after the next successful hourly snapshot
synchronization and Pages deployment; GitHub Actions schedules can start late or fail.

The Bundle contains exactly two objects for each current Radar row, ordered by normalized domain and signal ID:

1. One standard `domain-name` Cyber-observable Object with a deterministic UUIDv5 identifier and normalized raw DNS
   value. This value is intentionally refanged for STIX interoperability. It never contains a scheme, port, path, query,
   fragment, credential, or IP address.
2. One linked `observed-data` Domain Object representing exactly one latest public observation. Its `first_observed` and
   `last_observed` both equal the Radar row's `lastSeen`, `number_observed` is `1`, and `object_refs` contains only the
   corresponding Domain Name identifier. Radar's merged first/last interval remains separate namespaced metadata rather
   than being misrepresented as an exact STIX event count.

The Observed Data object uses `created = firstSeen` and `modified = generatedAt`. Its deterministic identifier includes
both the stable Radar signal ID and `firstSeen`; discovering an earlier historical first-seen boundary therefore creates a
new STIX object instead of illegally changing `created` on an existing version. Bundle, Domain Name, and Observed Data IDs
use separate deterministic UUIDv5 namespaces. The standard OASIS namespace is used only for the Domain Name SCO's
ID-contributing `value`; HECAVEX uses its own namespace for Bundle and Observed Data IDs.

Radar context is carried only in source-unique custom properties:

| Property | Meaning |
| --- | --- |
| `x_hecavex_com_signal_id` | Corresponding 20-character public Radar signal ID. |
| `x_hecavex_com_sources` | Sorted supported public source labels. |
| `x_hecavex_com_status` | Current Radar status; it is not STIX revocation. |
| `x_hecavex_com_matching_score` | Radar's 0-100 matching/ranking score; it is deliberately not mapped to standard STIX `confidence`. |
| `x_hecavex_com_evidence_tier` | Snapshot evidence tier; it does not assert maliciousness. |
| `x_hecavex_com_review_state` | Snapshot review state. The observation feed remains non-indicator data even for a reviewed row. |
| `x_hecavex_com_lt_relevance` | Explicit Lithuanian relevance classification. |
| `x_hecavex_com_observation_only` | Always `true`; inclusion is an observation, not a verdict. |
| `x_hecavex_com_radar_first_seen`, `x_hecavex_com_radar_last_seen` | Full merged Radar observation interval. |
| `x_hecavex_com_brand` | Optional registry-resolved claimed target, not attribution. |
| `x_hecavex_com_reason_codes` | Optional controlled public provenance labels. |

`x_hecavex_com_sources` retains the complete fixed source-label list. An optional `external_references` array is emitted only
when the row has both URLScan provenance and a validated canonical public URLScan result URL; it then contains exactly one
entry with `source_name: "URLScan"` and that `url`. The property is omitted otherwise. The projection contains no STIX
Indicator, detection pattern, standard `confidence`, `revoked` state, malware label, threat-actor attribution, block
decision, screenshot, certificate, network detail, hash, or candidate URL path.

The producer rejects duplicate or mismatched domains and IDs, malformed timestamps, unsupported sources, unsafe reference
URLs, non-canonical fields, unexpected object counts, and output above 2 MiB. The production build independently verifies
an exact one-to-one correspondence with `radar.json` before deployment. STIX consumers must treat every raw domain value as
untrusted data and must not browse, resolve, scan, or block it without independent review.

### Analyst-reviewed Indicator projection

`public/data/radar-reviewed.stix.json` is a separate static STIX 2.1 Bundle. It never promotes an automated observation merely because its matcher score is high. An Indicator appears only after an operator records an explicit `confirmed-suspicious` assessment and intentionally exports the sanitized review ledger. Inconclusive reviews and unreviewed candidates are omitted. When there are no exported confirmations or retained revoked Indicator lifecycles, the Bundle validly contains only the HECAVEX Radar Identity.

Each published Indicator has a deterministic ID derived from the public signal ID and first confirmation boundary, a STIX domain-name pattern, `valid_from` equal to that confirmation time, and the bounded analyst expiry as `valid_until`. A correction keeps the same Indicator ID and `created` value while advancing `modified`. A retraction preserves the Indicator and ID with `revoked: true`; it does not erase previously distributed intelligence. A later fresh confirmation starts a new Indicator lifecycle and ID. Expiry does not silently become revocation: after expiry the dashboard state returns to `needs-review`, while the Indicator retains its past `valid_until` boundary.

Indicators use the HECAVEX Radar Identity through `created_by_ref` and the standard TLP:CLEAR marking reference. Standard STIX `confidence` is emitted only when the analyst explicitly records a bounded analyst-confidence value. It is separate from the automated `matchScore`. Controlled custom properties carry the public signal ID, brand, review disposition and reason, evidence-code list, and Lithuanian relevance. The feed is a static download, not TAXII, an automated blocklist, or a direction to visit the listed host.

When an Indicator's signal ID and domain match a current signal or retained public history summary, the Bundle also contains
one deterministic STIX 2.1 `sighting` object tied to that exact Indicator lifecycle through `sighting_of_ref`. Its
`first_seen`, `last_seen`, and `count` come from the bounded public summary. A current row without a history count contributes
`1`; when current and retained summaries overlap, publication takes the broadest interval and the greatest available count
rather than adding overlapping totals. The Sighting carries the same Identity and TLP:CLEAR marking plus
`x_hecavex_com_signal_id` and `x_hecavex_com_observation_scope: "public-history-summary"`. No Sighting is emitted when no
matching public observation summary exists.

A Sighting is observation context, not an additional analyst confirmation, a claim that the candidate is currently live,
or an exact event ledger. A revoked Indicator can retain a Sighting because retraction does not erase the fact that the
signal was previously observed. Sighting IDs are derived from the Indicator ID, so a later fresh confirmation lifecycle has
its own Indicator and Sighting pair.

## Per-signal detail sidecars

When a live row contains `"detailAvailable": true`, the dashboard may request exactly
`public/data/signals/<first-two-ID-characters>/<20-character-ID>.json`. The path is derived from the already validated
signal ID; no domain or source text enters the request path. Files are same-origin static JSON and are fetched only after
a reader opens that row's evidence dialog.

Each file uses this exact top-level shape:

```json
{
  "schemaVersion": 1,
  "dataset": "signal-detail",
  "signalId": "c1f2e72a0b04a2a80c44",
  "domain": "login-brand[.]example",
  "generatedAt": "2026-08-21T09:15:00.000Z",
  "observations": [
    {
      "source": "URLScan",
      "observedAt": "2026-08-21T08:59:00.000Z",
      "page": {"title": "Brand account", "httpStatus": 200},
      "network": {
        "ipAddress": "192[.]0[.]2[.]10",
        "asn": 64500,
        "asnDescription": "Example network",
        "asnRegistry": "ARIN"
      },
      "assessment": {
        "urlscanVerdictScore": 75,
        "urlscanCategories": ["phishing"],
        "redirectedToDomain": "www[.]official-brand[.]example"
      },
      "certificate": {
        "countryName": null,
        "issuer": "Example CA",
        "commonName": "login-brand[.]example",
        "notBefore": "2026-08-20T00:00:00.000Z",
        "notAfter": "2026-11-18T00:00:00.000Z",
        "subjectAltNames": ["login-brand[.]example"],
        "subjectAltNameCount": 1,
        "serialNumberHex": "01ab",
        "fingerprints": {"md5": null, "sha1": null, "sha256": null}
      }
    }
  ],
  "domainContext": {
    "observedAt": "2026-08-21T09:10:00.000Z",
    "dns": {
      "a": ["192[.]0[.]2[.]10"],
      "aaaa": [],
      "cname": [],
      "ns": ["ns1[.]example"],
      "mx": [],
      "minimumTtl": 300,
      "queriesCompleted": 5
    },
    "registration": {
      "domain": "example[.]com",
      "registrar": "Example Registrar",
      "registeredAt": "2026-08-20T08:00:00.000Z",
      "updatedAt": null,
      "expiresAt": "2027-08-20T08:00:00.000Z",
      "statuses": ["client-transfer-prohibited"]
    }
  },
  "contextChanges": [
    {
      "eventId": "0123456789abcdef0123456789abcdef",
      "observedAt": "2026-08-21T09:12:00.000Z",
      "component": "dns",
      "changeType": "dns-a-changed",
      "changedFields": ["a"],
      "source": {
        "name": "Cloudflare DNS",
        "observedAt": "2026-08-21T09:10:00.000Z",
        "referenceUrl": "https://cloudflare-dns.com/dns-query"
      },
      "evidence": {
        "previousSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "currentSha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "primaryHtmlSha256": [],
        "certificateSha256": null
      }
    }
  ]
}
```

A sidecar contains at most one latest retained observation for each of `CertStream` and `URLScan`, and therefore at most
two observations. It may also contain exactly one optional `domainContext` object for the same current signal. A
CertStream observation has only certificate context; its page, network, and assessment fields are null. A URLScan
observation can contain page, network, provider assessment, and TLS context. Page, network, and TLS fields are retained
only when URLScan's final page hostname equals the signal hostname, preventing redirect destinations from being
attributed to the candidate. A different final hostname is retained only as the defanged
`assessment.redirectedToDomain`; it documents observed redirect behavior and is neither a benign verdict nor proof that
every visitor received the same destination. `urlscanVerdictScore` is URLScan's integer score from -100 to 100 and is
separate from Radar confidence.

`domainContext.observedAt` is the point-in-time lookup boundary and cannot be later than the sidecar's `generatedAt`.
`dns` contains duplicate-free defanged A, AAAA, CNAME, NS, and MX answers, at most 12 of each, the lowest TTL found in
successful answers, and a 0-5 `queriesCompleted` count. An MX item retains its numeric preference before the defanged
hostname. `registration` is either null or an exact allowlist containing an optional defanged registrable-parent
`domain`, nullable registrar, registration, update, and expiry fields, plus at most 16 normalized RDAP status codes. The
parent records the scope actually sent to the IANA-selected RDAP service; it does not assert that a candidate subdomain
is separately registered. Null or missing context means unavailable or expired, not benign. Registrar text and
lifecycle fields are registration context, not ownership or actor attribution.

`contextChanges` is optional and contains at most six newest entries for the same signal from the retained 30-90 day
temporal journal. The exact semantic types are:

- DNS: `first-resolving`, `stopped-resolving`, `dns-a-changed`, `dns-aaaa-changed`, `dns-cname-changed`,
  `dns-ns-changed`, and `dns-mx-changed`;
- RDAP: `rdap-registrar-changed`, `rdap-status-changed`, and `rdap-expiry-changed`;
- URLScan: `urlscan-title-changed`, `urlscan-redirect-changed`, `urlscan-http-status-changed`,
  `urlscan-ip-changed`, `urlscan-asn-changed`, `urlscan-primary-html-sha256-changed`,
  `urlscan-certificate-fingerprint-changed`, and `certificate-reissued`.

The first complete DNS baseline emits `first-resolving` when at least one A, AAAA, or CNAME answer is already present;
an initial non-resolving baseline emits no lifecycle event. A later transition to no A, AAAA, or CNAME answers emits
`stopped-resolving`. TTL and collection-time drift do not create events. RIPEstat prefix, ASN, and optional RPKI values
remain bounded cached context and do not create a public journal type.

Each sidecar entry exposes the Radar journal timestamp in `observedAt`, the provider observation boundary and bounded
provider reference in `source`, the exact semantic field names, and SHA-256 digests of the complete bounded before and
after components. It never exposes those before/after components. URLScan entries may additionally expose at most two
already-retained primary-document SHA-256 values and one primary-document certificate SHA-256 fingerprint. URLScan
baselines, private journal rows, and sidecar entries are all omitted unless the repository variable
`URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED` is exactly `true`; possession of an API key does not establish permission.

The private version 2 NDJSON journal row persists the same signal/domain identity, `sourceObservedAt`,
`sourceReference`, bounded `before` and `after` objects, their `previousHash` and `currentHash`, and a deterministic event
ID. Existing rows are contract-checked and hash-verified before append, duplicate IDs fail closed, and a failed state
write rolls back the same-run journal mutation. The public loader independently checks semantic field changes, both
component hashes, and the deterministic event ID before projection.

Each file is capped at 16 KiB. The complete sidecar set is capped at 3 MiB and selected in live-snapshot order, so the
newest qualifying rows take priority if the aggregate boundary is reached. Unchanged observation content preserves the
existing file and its `generatedAt` value instead of creating timestamp-only rewrites. Synchronization deletes validated
orphan sidecar paths and sets `detailAvailable` only after the corresponding file has passed producer checks.

Certificate names, IP addresses, and indicator-like text are defanged. Text is bounded, control/format characters are
removed, email addresses are redacted, and live HTTP(S) schemes are neutralized. Certificate SAN samples are limited to
12 names under the candidate's registrable domain; `subjectAltNameCount` counts only related names, not every DNS name on
the original certificate. Domain context never contains registrant names, organizations, email addresses, telephone
numbers, postal addresses, RDAP entity handles, raw DNS/RDAP documents, or candidate page content. Missing hashes are not
calculated. The viewer treats every field as text and provides copy controls only; it never turns an observed indicator
into a link.

## CertStream collection health

The dashboard separately reads `public/data/collection-health.json`. This is operational evidence for the latest sampled CertStream attempt, not a signal source and not a candidate archive:

```json
{
  "schemaVersion": 1,
  "dataset": "certstream-collection-health",
  "generatedAt": "2026-08-21T19:21:53.656Z",
  "expectedIntervalSeconds": 900,
  "staleAfterSeconds": 2700,
  "lastSuccessAt": "2026-08-21T19:21:53.656Z",
  "freshness": {
    "status": "current",
    "referenceAt": "2026-08-21T19:21:53.656Z",
    "ageSeconds": 0
  },
  "latestAttempt": {
    "startedAt": "2026-08-21T19:13:30.000Z",
    "collectorStartedAt": "2026-08-21T19:13:43.649Z",
    "endedAt": "2026-08-21T19:21:53.656Z",
    "trigger": "schedule",
    "scheduledFor": "2026-08-21T19:08:00.000Z",
    "scheduleStatus": "delayed",
    "delaySeconds": 330,
    "expectedListeningSeconds": 480,
    "listeningSeconds": 480.0,
    "messages": 89532,
    "dnsNames": 160340,
    "matches": 0,
    "newRecords": 0,
    "connectionAttempts": 1,
    "connections": 1,
    "outcome": "healthy-empty",
    "summary": "Input was processed successfully; no candidate matched the publication heuristic."
  }
}
```

`startedAt` and `endedAt` bound the actual workflow attempt. `collectorStartedAt` is null when collector setup fails. `listeningSeconds` is the accumulated time with an open websocket, excluding setup, retry waits, and connection closing. `messages` counts valid JSON stream messages, `dnsNames` counts extracted certificate DNS names, `matches` counts qualifying heuristic matches before archive deduplication, and `newRecords` counts unique rows appended to the daily archive. None of these fields contains a domain, URL, certificate, candidate ID, or detector payload.

Collection outcomes are independent of scheduling timeliness:

| `outcome` | Meaning |
| --- | --- |
| `healthy-empty` | A bounded window completed with usable DNS-name input and at least 90% of its expected listening time, but no candidate matched. |
| `healthy-matches` | The same healthy-window conditions passed and one or more candidates matched. |
| `no-input` | A connection opened, but no certificate DNS names were received. |
| `partial` | Some usable input was processed, but the window was interrupted, failed, or accumulated less than 90% of expected listening time. |
| `failed` | The workflow could not establish or complete a usable collector connection. |

`scheduleStatus` is `scheduled`, `delayed`, `relayed`, `manual`, or `unknown`. A scheduled attempt becomes `delayed` when its actual start is more than `CERTSTREAM_DELAY_THRESHOLD_SECONDS` after the most recent configured slot; the default threshold is 300 seconds. This is a nearest-slot inference, not GitHub's original event queue timestamp. A platform delay longer than one 15-minute interval can therefore be understated. A completion-relay invocation uses `trigger: cadence-relay`, `scheduleStatus: relayed`, and no inferred slot or delay because it was not started by a cron slot. Delay or relay provenance does not replace the collection outcome, so either run can still be accurately described as healthy-empty, no-input, partial, or failed.

`lastSuccessAt` advances only for `healthy-empty` or `healthy-matches`. The producer records freshness relative to that timestamp at write time; the viewer recalculates it against its current clock using `staleAfterSeconds`. A due workflow invocation atomically replaces the file in its runner workspace when the attempt can be finalized. That replacement becomes public only after the subsequent guarded commit, push, and Pages deployment succeed; a cadence invocation suppressed by the persisted due guard does not create an attempt. Its schema has an exact fixed field set, its writer caps it at 32 KiB, and it retains no attempt history, preventing per-run file growth. A runner cancellation, platform failure, exhausted push retry, or deployment failure can therefore leave the public document at the last successfully published attempt and cannot be made observable by the stopped workflow itself.

Before the first instrumented workflow completes, the checked-in bootstrap document uses `latestAttempt: null`, `lastSuccessAt: null`, and unavailable freshness. This is intentionally different from synthesizing metrics from an older configured duration or incomplete logs. Normal workflow output always replaces `latestAttempt` with the complete fixed-field object above.

## Checkpointed CT-search state

`data/ct-search/state.json` is the bounded operational contract for the hourly `crt.sh` keyword poller. It is not a
public signal distribution or a CT-log checkpoint. The version 1 document has the exact top-level fields
`schemaVersion`, `dataset`, `provider`, `generatedAt`, `queryCursor`, `queries`, and `latestRun`.

- `dataset` is `ct-search-state` and `provider` is `crt.sh`.
- `queryCursor` rotates the bounded brand-query set. `queries` contains at most 128 entries keyed by stable `brand:`
  identifiers. Each exact entry holds the reviewed search `term`, resolved `brand`, monotonic `lastId`, nullable
  `lastEntryAt` and `lastRunAt`, and nullable `completed`, `partial`, or `failed` `lastOutcome`.
- `latestRun` is null before the first run or contains `startedAt`, `endedAt`, `outcome`, `queriesAttempted`,
  `queriesCompleted`, `rowsProcessed`, `dnsNames`, `matches`, `newRecords`, and `queriesBacklogged`. Outcome is
  `completed`, `partial`, or `failed`; counters are non-negative aggregate integers.

The file is capped at 128 KiB and contains no certificate name, unpublished domain, URL, or credential. A first query is
bounded to the configured seven-day default bootstrap. Subsequent runs process up to 500 rows per query by default and
replay at most 50 prior rows inside a 1,000-ID overlap. A backlog is marked partial and resumed before query rotation;
an archive-cap failure does not advance the checkpoint. This makes the declared provider query resumable after ordinary
downtime and catches a bounded late-indexing reorder. It does not
assert that `crt.sh` indexed every certificate, that a keyword finds every relevant name, or that the cursor corresponds
to an RFC 9162 log tree position. The workflow commits this state and accepted shared CT archive rows before propagating
a failed polling result when execution can still reach the finalizer.

## DNS and RDAP context state

`data/enrichment/domain-context.json` is the credential-free version 1 state consumed by synchronization. Its exact
top-level fields are `schemaVersion`, `dataset`, `generatedAt`, `cursor`, `latestRun`, and `records`; `dataset` is
`domain-context`. `latestRun` is null or contains `startedAt`, `endedAt`, `outcome`, `attempted`, and `completed`, where
outcome is `completed`, `partial`, `failed`, or `empty`.

Each record contains the current public `signalId`, matching defanged `domain`, `observedAt`, the exact DNS fields
documented for a sidecar, and the nullable registration allowlist including the optional defanged registrable-parent
scope actually queried. The state is capped at 2,500 records and 4 MiB.
Synchronization accepts only rows no older than 14 days by default and only while the ID/domain pair remains in the live
snapshot. The collector sends no HTTP request to the candidate webpage. It performs DNS-over-HTTPS questions and
IANA-bootstrapped RDAP lookups only, and it retains no registrant PII or raw provider response.

## Rolling pipeline health, changes, trends, and review quality

`public/data/pipeline-health.json` provides bounded 24-hour and seven-day aggregate views across collection, screening, enrichment, and publication. It includes scheduled versus recorded CertStream attempts, actual listening time and listening coverage, messages, DNS names, matches, new archive rows, URLScan enrichment-section counts, history-event counts, and current source state. Its current section can also expose a sanitized `ctSearch` latest-run summary and a sanitized `domainContext` latest-run summary with retained record count. The URLScan summary includes strict `checkpointCoverage` aggregate fields: query, complete, partial, and backlog counts plus nullable `oldestBacklogProgressAt`. Those summaries omit query text and hashes, cursors, candidate IDs, domains, DNS answers, and RDAP values. Expected live-stream slots and the scheduled-listening ceiling come from the latest published collector interval and duration. Indexed CT search is reported separately and never added to live-listening coverage. Missing workflow history cannot be reconstructed; only successful attempt rows committed to the bounded public archive are counted.

`public/data/changes.json` separates first publication, actual status change, observation, and reobservation counts. It groups only bounded totals by source, status, controlled reason, and registry brand. It contains no domain, URL, signal ID, private review note, or detector payload; signal-level public chronology remains in `history.json`.

`public/data/daily-trends.json` provides a sparse UTC series covering at most 365 days. For each retained day it separates
recorded CertStream schedule/listening coverage from discovery activity, marks a still-open UTC day as partial, and reports
event, unique-signal, observation, reobservation, first-publication, and status-change counts. Brand, source, evidence-tier,
and controlled-reason facets count unique signals within that day. Dates with neither a recorded attempt nor a discovery
event are omitted and counted in `omittedZeroDays`; consumers can derive expected live-listener slots from
`collectorSchedule`. The series measures Radar activity under the coverage printed beside it, not Lithuanian phishing
prevalence or total incident volume.

`countingMethodVersion: 2` classifies a reobservation only when its timestamp is strictly later than retained
first-publication provenance, falling back to the inventory's `firstSeen`, matching event-feed semantics. A paired
publication observation is excluded; absent earlier provenance remains unclassified. Version 1 subtracted distinct
observed IDs separately each UTC day and undercounted returning observations. See [the versioned correction](TRENDS-CORRECTIONS.md).

`public/data/quality-metrics.json` describes only the bounded public analyst-review sample for a window of at most 365 days.
It reports sanitized dated positive, negative, inconclusive and retracted outcomes and facets, coverage among eligible
signals represented in public history, first-observation-to-review latency when supportable, and current exported
exclusion-policy counts. Current suppressions have no public decision timestamp, so they are not silently inserted into
timed review metrics. The contract deliberately publishes `precision.available: false`, a zero sample, and a null estimate
until the completed decisions are linked to a defensible probability sample or a review census. These values must not be
presented as Radar-wide accuracy or false-positive rates. The document contains aggregate counters only, never a domain,
URL, signal ID, analyst identity, or private note.

## Related observations

`public/data/related-observations.json` publishes a bounded association graph over current dashboard rows. Strong edges require an exact primary-HTML SHA-256 or certificate SHA-256. Supporting edges require evidence from at least two independent families. Eligible bounded families include network location, DNS A/AAAA/CNAME/NS/MX context, redirect destination, and certificate SAN; mechanically related values within one family do not satisfy the requirement alone. Two hostnames below the same registrable domain are not treated as independent infrastructure and do not receive an edge merely for sharing their certificate, address, or content. Evidence values seen on more than 12 current signals are suppressed, candidate observations must be within seven days, and at most 2,000 strongest deterministic edges are retained.

The graph says only that two observations share public evidence. It does not identify a campaign, operator, malware family, infrastructure owner, or threat actor. ASN alone and the mechanically related IP-plus-ASN pair never create an edge. Cluster IDs are stable hashes of connected public signal IDs and carry no attribution semantics.

## Archive formats

Archive files are newline-delimited JSON and use the Europe/Vilnius calendar date.

### CertStream

`data/certstream/YYYY-MM-DD/attempts.ndjson` stores one aggregate row for each successful sampled window, partitioned by the Europe/Vilnius date on which the window ended. The fixed row records an identifier, collector start and end, expected and actual listening seconds, message and DNS-name counts, matches, newly archived records, and either `healthy-empty` or `healthy-matches`. It is capped at 256 rows and 256 KiB per day and contains no certificate names or candidate identifiers.

The attempt file makes a successful zero-match window explicit without claiming continuous coverage. An absent `domains.ndjson` alongside `attempts.ndjson` means no candidate was archived in those recorded windows only; it says nothing about unobserved portions of the day.

`data/certstream/YYYY-MM-DD/domains.ndjson` stores one candidate per normalized domain per Vilnius day:

```json
{
  "schemaVersion": 1,
  "id": "8eaf01bd355d5f450e81",
  "observedAt": "2026-08-21T09:15:00.000Z",
  "indicatorType": "domain",
  "domain": "secure-brand[.]example",
  "registrableDomain": "secure-brand[.]example",
  "source": "CertStream",
  "collectionMethod": "ct-search-api",
  "brand": "Example Brand",
  "confidence": 95,
  "reasons": ["brand text match: example brand", "suspicious token: secure"],
  "certificate": {
    "countryName": "US",
    "issuer": "Example CA",
    "commonName": "secure-brand[.]example",
    "notBefore": "2026-08-21T08:00:00.000Z",
    "notAfter": "2026-11-19T08:00:00.000Z",
    "subjectAltNames": ["secure-brand[.]example"],
    "subjectAltNameCount": 1,
    "serialNumberHex": "01ab",
    "fingerprints": {"md5": null, "sha1": "0000000000000000000000000000000000000000", "sha256": null}
  }
}
```

`certificate` is optional. When present, it uses the same bounded certificate fields as the public sidecar, with at most
12 same-registrable SAN samples and at most 500 related names counted. Invalid common names and country values are omitted;
issuer text is sanitized before this public Git archive is written. DER, chains, extensions, certificate URLs, and unrelated
SANs are never retained.

`collectionMethod` is optional on legacy rows and otherwise is `certstream-live` or `ct-search-api`. It preserves discovery
lineage while both paths retain the compatible public source label `CertStream`; it is not corroboration or a verdict.
The archive `id` hashes the normalized refanged domain, unlike the public snapshot ID, which hashes the defanged hostname.
IDs from different artifact types are therefore not join keys. A daily CertStream file is capped at 25,000 valid records
and 25 MiB. Reasons contain only contributions from the open heuristic.

### URLScan

`data/urlscan/YYYY-MM-DD/signals.ndjson` stores public signal fields plus:

```json
{
  "schemaVersion": 2,
  "hashType": "primary-html-sha256",
  "brandEvidence": ["domain", "primary-html-sha256"]
}
```

Each complete record remains defanged and uses the same host-based ID namespace as the public snapshot. `brandEvidence` is a non-empty, duplicate-free list containing only `domain`, `title`, `verdict`, or `primary-html-sha256`, and at least one of the first three values is required. The hash label records supplemental pivot provenance; it is not brand evidence by itself.

A current hostname match must agree with the declared brand. When the hostname no longer matches, only a row backed by title or verdict evidence may remain, and it must still resolve to a current registry brand and pass suppression and collision checks. Before a row can enter the archive, its URLScan search summary and result detail must both identify the scan as public; missing, unlisted, or private visibility is rejected. Version 1 rows and legacy version 2 rows without typed evidence are rejected. References use the canonical URLScan result path, screenshots use the fixed URLScan policy, and resource or empty-body hashes are rejected. A daily file is capped at 2,500 records and 20 MiB.

`data/urlscan/YYYY-MM-DD/intelligence.ndjson` stores the allowlisted context used to produce detail sidecars. Each exact
schema row has dataset `signal-intelligence`, the live signal ID/domain, and one URLScan observation containing nullable
page, network, assessment, and certificate sections. One newest record per signal/source is retained in a daily partition.
Rows are capped at 16 KiB, with the same 2,500-record and 20 MiB daily boundaries as signal archives. This archive contains
no API key, page body, request headers, cookie, extracted email, or candidate-site response content.

`data/urlscan/hunt-state.json` is the bounded operational state document for the two-hour hunter. It uses schema version 1 and dataset `urlscan-hunt-state`, and contains exactly the following state classes:

- `generatedAt`, `lastRunAt`, and `budgetDay` identify the persisted state transition and UTC counter window. Individual no-change runs remain visible in Actions history.
- `configured` and `lastOutcome` distinguish `completed`, `budget-limited`, `failed`, and the successful `skipped-not-configured` state.
- `searchRequests`, `resultRequests`, `lastRunSearchRequests`, and `lastRunResultRequests` are local counts of successful API responses, not provider billing counters.
- `candidateCursor`, `candidateCount`, and `selectedCandidates` are aggregate bounded-set progress values. They never contain a domain or URL.

The document is capped at 32 KiB, uses an exact fixed-field schema, and is replaced atomically when its non-timestamp state changes. It contains no API key, authentication material, candidate domain, or result payload. Missing credentials cause no API request and record `configured: false` with `skipped-not-configured`; repeated identical skips within one UTC day do not create timestamp-only commits. HTTP 429 or exhaustion of a conservative internal cap stops further requests and records an observable bounded outcome while preserving prior archive rows.

A checked-in hunt state is operational evidence produced by GitHub Actions, not a hand-authored default or locally generated fixture. Synchronization publishes `skipped` for `skipped-not-configured`, `partial` for failed or budget-limited refreshes, and `healthy` only for a completed configured hunt. Valid historical archive rows remain independently visible in every case.

### Candidate history

`data/history/daily/YYYY-MM-DD/events.ndjson` uses UTC partitions and stores exact-schema, defanged events. An event has:

| Field | Type | Notes |
| --- | --- | --- |
| `schemaVersion` | integer | Always `1`. |
| `eventId` | string | First 32 hexadecimal characters of SHA-256 over the immutable event identity fields. |
| `signalId` | string | Same host-based ID namespace as the public live snapshot. |
| `eventType` | enum | `observation` or `status-transition`. |
| `observedAt` | UTC timestamp | Source observation boundary or explicit transition time. |
| `domain` | string | Canonical defanged hostname. |
| `brand` | string | One current registry-resolved target. |
| `sources` | string[] | One or more supported public sources. |
| `status` | enum | Same values as the live snapshot. |
| `previousStatus` | enum or null | Set only for a status transition; null for observation events and first publication. |
| `confidence` | integer | Score recorded with the event; not part of event identity. |
| `reasonCodes` | string[] | Controlled public provenance labels; not part of event identity. |

Event identity includes schema version, signal ID, event type, observation time, sources, status, and previous status. It deliberately excludes confidence and reason wording so replaying one observation after a scoring change cannot create a second event. Daily files are capped at 10,000 events and 8 MiB; invalid, duplicate, oversized, or over-cap input fails closed instead of being skipped or truncated.

After the detail window, events compact into `data/history/summary.json`. The public `public/data/history.json` projection exposes `id`, `domain`, `brand`, `firstSeen`, `lastSeen`, `observationCount`, `sources`, `latestStatus`, `reasonCodes`, and up to 16 typed `statusTransitions`. Private review suppressions and current brand rules are re-applied before every projection. The complete projection is capped at 512 KiB and fails closed rather than truncating. See [Candidate history](HISTORY.md) for retention limits.

## HECAVEX input and operator handoff

### Configured source input

A configured HECAVEX endpoint may return an array of signal objects or `{ "signals": [...] }`:

```json
{
  "signals": [
    {
      "url": "https://suspicious.example/path?private=value",
      "firstSeen": "2026-08-21T08:05:00Z",
      "lastSeen": "2026-08-21T09:15:00Z",
      "status": "suspected",
      "brand": "Example Brand",
      "country": "LT",
      "host": "Example Hosting / AS64500",
      "screenshotUrl": "https://urlscan.io/screenshots/11111111-1111-1111-1111-111111111111.png",
      "referenceUrl": "https://urlscan.io/result/11111111-1111-1111-1111-111111111111/",
      "hashType": "primary-html-sha256",
      "hashes": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
      "confidence": 78
    }
  ]
}
```

`indicator` or `domain` may replace `url`, and existing defanged values are accepted. Accepted aliases are `first_seen`, `last_seen`, `brandTargeted`, `brand_targeted`, `hosting`, `screenshot_url`, `reference_url`, `confidenceScore`, and `confidence_score`. Hashes are accepted only when `hashType` is `primary-html-sha256`. Any supplied `source` is ignored; accepted rows are attributed to `HECAVEX`.

Missing or unrecognized status becomes `unknown`; missing or invalid confidence becomes `50`. Timestamp normalization follows the public rules above. A syntactically valid row may still be dropped by Lithuanian registry scoping.

The feed URL must use HTTPS, omit credentials, and use the default port. HTTP is accepted only from `localhost`, `127.0.0.1`, or `::1` for local maintainer validation; production service workflows require HTTPS.

### Operator candidate handoff

When `HECAVEX_CANDIDATE_OUTPUT` names a file below `data/hecavex/`, synchronization atomically writes a git-ignored document with `schemaVersion: 1`, `dataset: "hecavex-candidates"`, `generatedAt`, `disposition: "potential"`, and `signals`.

The handoff is limited to 2,500 signals and 20 MiB. It includes only defanged public fields backed by CertStream or URLScan; HECAVEX-only observations and discovery-seed provenance are excluded. This is an operator-workstation file export for private review. It performs no HTTP upload and uses no credentials.

## Sanitized review decisions

`data/review/public-decisions.json` is the only operator-review artifact accepted by synchronization. New exports use `schemaVersion: 3`, dataset `radar-review-decisions`, a canonical UTC `generatedAt`, and three bounded arrays. The loader accepts the version 1 shape as containing no assessments. It accepts a version 2 file only when `assessments` is empty; provenance-free version 2 assessments fail closed.

- `suppressions` contain a deterministic decision ID, defanged domain, `exact` or `subdomains` scope, optional resolved brand, and one controlled correction reason.
- `candidates` contain a deterministic decision ID, public signal ID, defanged URL and domain, observation time, current matcher-resolved brand, `matchScore` no greater than the matcher result, the deprecated equal `confidence` alias, and controlled reason codes including `manual-review`.
- `assessments` contain one sanitized terminal record per review lifecycle: a stable lifecycle assessment and signal ID, defanged domain, resolved brand, controlled review disposition/reason/evidence codes, Lithuanian relevance, first-review and modified times, required bounded expiry for confirmations, optional analyst confidence, an explicit revocation flag, and `admissionSource`. The admission object fixes the already-published signal ID, defanged domain, canonical brand, observation time, sorted source names, and a canonical SHA-256 integrity digest. `observedAt` cannot be later than `reviewedAt`. The digest detects accidental mutation; it is not a signature, maliciousness verdict, or proof of analyst identity. Corrections and retractions copy the original admission bytes and replace the exported terminal version of their original lifecycle; a later fresh confirmation adds a new lifecycle record without deleting the older revoked or expired record. The dashboard applies only the lifecycle with the latest modification boundary.

Each array is capped at 2,500 records and the file is capped at 2 MiB. Duplicate IDs, unsafe values, future timestamps, cross-brand decisions, unrecognized controlled values, or manual candidates that no longer pass the current matcher make synchronization fail. A first assessment is admitted only for an exact signal in the validated complete current shard set or bounded retained public history. A matcher result by itself is not assessment provenance. A dated assessment retains its immutable public-observation admission and canonical brand, so later matcher tightening cannot erase valid review history; its domain, signal ID, controlled evidence, admission digest, and timestamp lifecycle are still revalidated on every read and before reviewed STIX publication. A manual candidate is always attributed to `HECAVEX` and normalized to `suspected`. Private notes and raw evidence are never exported; evidence codes describe the classes of evidence used, not their contents. The private SQLite event ledger and its notes are outside this contract and must never be committed.

## Deliberately excluded

- Userinfo, query parameters, fragments, cookies, page bodies/response content, and credentials. A bounded page title may be retained in a sidecar.
- Extracted email addresses and Google Safe Browsing classifications.
- Private observation IDs, analyst identities, internal endpoints, and unbounded or event-level collection telemetry. The aggregate latest-attempt health fields documented above are deliberately public.
- Detector features, proprietary rules, private evidence graphs, analyst working notes, and case data. The bounded public related-observation artifact contains only already published, typed association evidence and carries an explicit non-attribution boundary.
- Discovery-seed provider names and raw seed records.
- Internal HECAVEX case history.

## Website analytics boundary

Website measurement is separate from the public Radar data contract. When the public `HECAVEX_ANALYTICS_TOKEN` build variable is configured, and unless the browser reports `navigator.doNotTrack === "1"` or `window.doNotTrack === "1"`, each rendered page loads the cookieless Cloudflare Web Analytics beacon from `https://static.cloudflareinsights.com/beacon.min.js`; the beacon sends page-view and browser-performance metrics to `https://cloudflareinsights.com`. Cloudflare documents that the beacon does not set or access cookies or browser storage. Keyless local and CI builds omit the loader; the production Pages gate requires it.

Radar configures no custom analytics events. Snapshot rows, indicator text, evidence, search text, filter selections, unpublished candidates, and operator-review data are not serialized into analytics payloads. Cloudflare remains the processor of the ordinary page and performance measurements described in its [Web Analytics data-collection documentation](https://developers.cloudflare.com/web-analytics/data-metrics/data-origin-and-collection/). The portfolio privacy notice is published at [hecavex.com/en/privacy](https://hecavex.com/en/privacy/).
