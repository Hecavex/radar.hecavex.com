# Candidate history

The history published at [radar.hecavex.com/history/](https://radar.hecavex.com/history/) answers two narrow questions: when did the operated public pipeline accept an observation for this host, and when did a supported source explicitly change its status? It is not a reputation database and does not infer current liveness.

## Event identity

Each history event has a 32-character identifier derived from its signal ID, event type, observation time, sources, status, and previous status. Mutable confidence values and explanatory labels are not part of the identity. Replaying an unchanged source archive therefore cannot increase the observation count, even if registry wording or scoring changes later.

The 20-character `signalId` uses the same normalized defanged-host namespace as `public/data/radar.json`. Cross-brand observations for one signal ID are rejected rather than merged.

Two event types exist:

- `observation` records a validated first-seen or last-seen boundary from an accepted source record.
- `status-transition` records first publication or an explicit change from one supported status to another.

CertStream and URLScan always supply `suspected`. Only a validated HECAVEX input can supply `active`, `offline`, or `mitigated`. A host disappearing from recent archives creates no event.

## Retention and compaction

Daily detail lives at `data/history/daily/YYYY-MM-DD/events.ndjson` in UTC partitions. A file is capped at 10,000 events and 8 MiB. Detail is kept for 30 days by default. Invalid JSON, invalid events, duplicate IDs, or an exceeded cap fail synchronization instead of being skipped or truncated.

After the detail window, events compact into `data/history/summary.json`. The summary keeps first and last observation time, a bounded observation count, source and reason unions, latest explicit status, up to 16 transitions, and up to 64 recent event IDs per host. It is capped at 25,000 hosts and 12 MiB. Entries expire after 730 days by default. Git retains the committed history of partitions removed from the working tree.

`compactedThrough` is a closed UTC-day watermark. If an already compacted partition reappears through source replay, it is discarded without changing counts. Late observations dated on or before that watermark require an intentional history rebuild from Git archives; normal synchronization does not reopen compacted days.

`public/data/history.json` is a bounded projection of the compacted summary and retained detail. It is revalidated against the current brand registry and sanitized review decisions on every synchronization. The default row cap is 5,000 hosts. Synchronization refuses a count overflow instead of silently truncating history.

Small histories retain the inline v1 document. When compact serialization would exceed 512 KiB, the public document becomes a v2 partition index with `partitionFormat: hecavex-history-partitions-v1`, an exact `signalCount`, empty inline `signals`, and a `partitions` inventory. Each content-addressed `history-parts/<sha256>.json` contains at most 256 KiB and declares its exact hash, byte size and row count in the index. An empty inline array in a partition index is not an empty history. Consumers must resolve every partition and verify the declared count and hashes. Radar's browser, build, review admission, quality metrics, event routes and publication validator do this before using history.

The durable 12 MiB summary uses the same format in `summary-parts/` when needed. Both stores have a finite maximum of 512 partitions, and retain the 25,000-host hard ceiling. Writers preflight all chunks, write content-addressed parts first and replace the index last. Missing, oversized, repeated, escaped or altered parts fail closed. This does not erase old history to improve coverage. Current public parts enter the atomic feed manifest and checksum set. The 256 MiB complete deployment budget and existing per-response gates still apply.

Growth regressions exercise 5,000 substantial public rows and 25,000 durable rows with the full 64-ID replay-hint allocation. Record cardinality and bytes are independent limits. Unusually large transitions can still exhaust the finite total deployment budget, in which case publication must fail visibly rather than claiming complete delivery.

HTML embeds at most 64 KiB of history as an explicitly labelled preview. The archive browser loads and validates the complete index and every part. The local IOC checker is disabled until that succeeds, so a missing partition cannot turn into a false no-match result. Brand pages show at most 50 recent historical rows with the complete count and archive link. The original full records still receive durable bilingual signal routes. After an index is committed, only unreferenced generated content-addressed part files are removed from the working tree. Earlier committed releases remain recoverable in Git.

The separate 30-day publication-event stream is filtered through the current matcher, registry, and review policy. Only
events whose IDs still have an emitted route in the dashboard snapshot or filtered public history reach the Changes
page and feeds. Filtering this projection does not erase daily or compacted history and is not a benign verdict, status
transition, or analyst retraction.

Configuration:

| Variable | Default | Range |
| --- | ---: | ---: |
| `RADAR_HISTORY_DETAIL_DAYS` | 30 | 7-90 |
| `RADAR_HISTORY_SUMMARY_DAYS` | 730 | 30-3,650 |
| `RADAR_HISTORY_MAX_SIGNALS` | 5,000 | 1-25,000 |
| `RADAR_HISTORY_ROOT` | `data/history` | repository-relative |
| `RADAR_HISTORY_OUTPUT` | `public/data/history.json` | repository-relative |

Running synchronization twice over unchanged inputs advances only the live snapshot's successful-sync heartbeat and source check times. Its `generatedAt` data-change timestamp, daily events, compacted summary, and public history remain unchanged.
