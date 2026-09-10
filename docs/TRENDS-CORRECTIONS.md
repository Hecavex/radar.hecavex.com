# Daily trends counting correction, version 2

Effective with the first publication using this source revision (7 September 2026).
`countingMethodVersion: 2` corrects `discovery.reobservations`: version 1 subtracted
distinct observed IDs separately each day, losing returning candidates observed
once on a later UTC day. Version 2 uses the event-feed definition: an observation
strictly later than retained first-publication provenance, with inventory firstSeen
as a fallback. A paired first-publication observation is excluded. Missing earlier
provenance does not manufacture a publication or reobservation.

The normal publisher rebuilds derived daily trends from retained events. Raw event
history is preserved. Consumers comparing releases must retain the counting method
version; earlier published counts are not silently presented as version 2.
Scheduled slots, recorded attempts, listening coverage and recall are unaffected.
# Coverage bounds method 2 — 10 September 2026

The next publication from the coverage-bounds source replaces the previous sum-and-cap wall-clock estimate with conservative interval bounds. This is independent of discovery/reobservation counting method 2, which is unchanged. Original generated data and immutable releases are not edited by the source change; newly generated history projections identify the coverage method in each `coverageBounds.methodVersion`.

`listeningSeconds` and `listeningCoveragePercent` now expose the conservative lower bound when `coverageBounds` is present. `lowerSeconds` and `upperSeconds` bound unique listening time clipped to the measurement window. `reportedWorkerSeconds` separately sums original totals attributed by attempt end; it can include time outside that window and is not coverage. Attempt counts remain attributed once, while a midnight-spanning attempt contributes clipped coverage bounds to both dates.

Totals and attempt envelopes do not locate reconnect gaps. Overlapping attempts therefore can produce a range rather than an invented exact interval. Missing/invalid envelopes are unknown, never synthesized from the duration. `precision` is `exact`, `bounded`, or `unknown`; the browser displays bounds and labels pre-method-2 data as a legacy estimate. This changes neither recorded original attempts nor inferred detection recall.
