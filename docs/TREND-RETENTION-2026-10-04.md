# Daily discovery retention correction

Previously the 365-day series read only the 30-day detailed event store. After
compaction, surviving collection telemetry could therefore appear beside an
incorrect zero discovery count. The per-host compacted summary cannot recover
the missing day-by-day chronology from first/last observations or bounded totals.

New publications preserve completed UTC-day discovery aggregates separately in
`data/history/discovery-summary.json` (365 days, 2 MiB maximum). Each day uses
retained detail **or** one retained aggregate, never their sum. Detail remains
authoritative after the compaction watermark; older aggregates freeze their
recorded counting method, brand/source policy and evidence-facet coverage. They
are not silently reclassified using today's inventory. Compacted host transitions
can support reobservation chronology but never manufacture daily counts.

`retentionMethodVersion: 1` adds `discoveryBasis` to each row. A compacted day
without an exact saved aggregate has `discovery: null` and basis `unknown`.
`omittedUnknownDays` is separate from `omittedZeroDays`; missing dates before
`discoveryCompleteFrom` must not be filled with zero. Both language interfaces
label unavailable history and omit its discovery bar. Collection attempts,
schedule denominators and listening bounds are unchanged.

The complete machine-readable series retains up to 365 days. To keep the existing
512 KiB HTML budget, the chart and its embedded hydration data show at most the
latest 90 recorded dates, with an explicit EN/LT date-window and total-row notice.
The linked JSON retains the complete saved series. This display limit does not
alter the data, aggregate-retention period or collection coverage.

The reviewed recovery file `config/trend-recovery-2026-10-01.json` preserves the
30 September daily discovery aggregates from data revision
`3d80a765404f50afbe50c3dc49472751a2e13b65`, generated at
`2026-10-01T00:40:26.566Z`. Its source JSON is 61,266 bytes with SHA-256
`39429a7671571118e437e6b481cbfbbac5fbc83bd339adc28c0fb54e11cdd4b7`.
The recovery is not applied before that cutoff and replaces only compacted days.
For example, 1–3 September retain 16, 19 and 17 daily unique signals; older
August values without a trusted retained aggregate remain unknown. No missed
listening windows, maliciousness verdicts or month-wide unique totals are inferred.

Daily unique counts are candidate-days when added, not unique monthly hosts.
Use deduplicated signal IDs from a pinned complete monthly archive for the latter.
