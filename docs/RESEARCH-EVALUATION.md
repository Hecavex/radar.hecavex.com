# Bounded research evaluation and reuse

## Human assessment remains a gate

The offline `ranking_evaluation` module freezes a current published cohort with exact source/data revisions and a deterministic cohort digest. It does not create dispositions or modify Radar. Use a manifest-verified snapshot from the chosen publication, not the mutable working checkout:

```sh
python -m hecavex_radar.ranking_evaluation freeze SNAPSHOT.json --source SOURCE_SHA --data DATA_SHA
python -m hecavex_radar.ranking_evaluation evaluate COHORT.json INTENTIONALLY_EXPORTED_DECISIONS.json --k 20
```

Both commands print JSON; save only where intentionally appropriate. A decision requires a unique cohort `signalId`, canonical `reviewedAt` after the frozen cutoff, `reviewMethod: human`, a nonempty `evidenceReference`, and an outcome of `confirmed-suspicious`, `false-positive`, `benign-brand-reference`, or `inconclusive`. This is a consumer evaluation contract, not permission to set public Radar review states. Synthetic test labels and AI-assisted comparisons must never be passed off as human assessments.

Outputs compare rule ranking with chronological, deterministic and brand-stratified baselines. Each denominator includes unresolved and missing reviews; positive yield among the resolved subset is labelled separately. Brand, score and evidence/source facets describe this fixed cohort, not population precision, calibration or Lithuanian prevalence. Source facets can overlap. The tool rejects a changed cohort digest and never reports population precision as available.

Real closure requires a documented sampling/census protocol, authentic evidence-backed labels, a separate review of disagreements, and forward/held-out evaluation. Protocol timing and genuine reviewer identity cannot be proved by accepting a `human` string. No current accuracy claim follows from shipping this module. Do not choose a stopping rule based on obtaining a desired positive rate.

## Revision-bound handoff

Per-signal plain-text handoffs include source and selected data revisions, the feed-manifest SHA-256, signal ID, and whether the record came from the current snapshot or retained history. The GitHub data-tree link is pinned to the exact data revision. Verify `public/data/feed-manifest.json` against that digest, then its declared artifact hashes and the index's complete-shard descriptors. Local development builds without a selected data revision say unknown instead of pretending the source checkout is live data. The current canonical signal URL remains a convenient evolving view, not the immutable reference.

## Lifecycle-safe offline consumer

```sh
python -m hecavex_radar.consumer_example BEFORE_PUBLIC_DATA AFTER_PUBLIC_DATA \
  --before-manifest SHA256 --after-manifest SHA256 --as-of 2026-09-10T12:00:00.000Z
```

Inputs are separately obtained pinned publications. The example makes no network request. It verifies the supplied manifest identities, bounded files, complete snapshot shards and history partitions before comparing IDs. It does not infer a safe/offline state from disappearance; it distinguishes snapshot additions, changed observation boundaries and metadata/policy interpretation changes. It retains whether a missing current row remains in history. Reviewed Indicator expiry and revocation are evaluated independently at the explicit as-of time, never converted to automatic blocking instructions.

Current public timestamps are normalized UTC values; older contracts do not identify every source-reported versus fallback timestamp. The example explicitly carries `published-normalized; original-vs-fallback-unspecified`, not a fictional distinction. Source-removal causes likewise stay unknown unless authoritative metadata exists. Upstream timestamp-provenance enrichment and a real consumer pilot remain separate acceptance work. This example is not a TAXII service, production ingestion SLA, or a reputation database.

## Shared context and query custody

New association output uses `shared-context` for supporting-only edges. Multiple DNS/network families can come from one service; small-sample rarity is not global rarity. Exact shared evidence remains inspectable. Legacy `corroborated-supporting` artifacts remain readable but are displayed as context, not independent corroboration. Temporal and high-fanout filters remain unchanged.

URLScan checkpoints now record a bounded query-family label without query terms. The read-only `audit_ownership(state, planned_queries)` helper identifies matches to an explicitly supplied plan. Absence from that plan does not retire or clear a cursor. Legacy hashes with no recoverable owner remain `legacy-unclassified`; active broad-query progression must not be confused with the age of a different unresolved cursor. Existing continuation and quota/error guards remain in force. Do not erase unresolved history to improve a health counter.
