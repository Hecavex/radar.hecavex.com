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
