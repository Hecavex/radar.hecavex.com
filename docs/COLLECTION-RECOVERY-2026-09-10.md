# CertStream collection gaps: 8-10 September 2026

Recorded on 10 September 2026. This is an operational incident note, not an estimate of phishing prevalence.

## What the public numbers mean

The published daily record for 8 and 9 September contains seven CertStream attempts against 96 planned attempts on each day. Each complete listening window lasts eight minutes in a planned fifteen-minute interval. Seven windows therefore represent about 3.89% of the day listening, against a planned ceiling of 53.33%.

The low attempt count is a collection gap. It is not evidence that phishing activity fell. The signal count can include observations from other passive sources and is not the number of CertStream windows. Historical missed listening time cannot be collected retrospectively. The repair must not increase historical counts or replace missing observations with estimates.

## Reproduced failure

A completed collector can produce two GitHub events:

1. Its explicit repository-dispatch completion message admits the cadence relay job, which waits on the existing six-minute environment timer.
2. GitHub also sends a workflow-run completion event. Successful workflow-run events are intentionally ignored by the relay job, because the explicit message already owns that handoff.

The old concurrency group applied to the entire workflow and cancelled an existing run before the second event's job condition was evaluated. The second event consequently cancelled the valid waiting relay, then skipped its own job. No relay remained to request the next window.

The latest observed pair was [waiting relay 34425019839](https://github.com/Hecavex/radar.hecavex.com/actions/runs/34425019839), cancelled at 01:19:46 UTC on 10 September, and [successful-completion fallback 34425023712](https://github.com/Hecavex/radar.hecavex.com/actions/runs/34425023712), created at that time and skipped. The previous pair, [34417101787](https://github.com/Hecavex/radar.hecavex.com/actions/runs/34417101787) and [34417107123](https://github.com/Hecavex/radar.hecavex.com/actions/runs/34417107123), shows the same ordering around 23:28:45 UTC on 9 September. Both cancelled relay jobs had no executed steps.

## Repair and safeguards

Concurrency now belongs to the admitted relay job, not the whole workflow. Eligible pending handoffs queue without cancelling the owner. A successful workflow-run event cannot claim that group through a skipped job. Existing checks for an active child collector and the collector's persisted due guard remain responsible for deduplication.

The repair preserves the six-minute environment wait, eight-minute listening window, one-listener boundary, bounded job timeout and passive-only collection. It does not add a second service, raise provider request budgets or rely on a laptop remaining online.

Regression tests replay both completion-event orders, the previously cancelling policy, eligible failure duplicates, non-main events and child-owner deduplication. They read the real workflow condition and concurrency configuration. The model tests do not replace a real hosted handoff or a multi-day operational observation.

The Trends view also identifies days with no recorded attempts or fewer than half of the planned attempt count. Its summary anchors the limitation to the latest complete day in the saved data. This uses the existing below-half health threshold, not a phishing severity score. Data freshness remains separate from collection completeness.

## Acceptance boundary

A deployment alone does not prove cadence recovery. Observe a completed collector, its admitted relay surviving the duplicate successful-completion event, and a naturally dispatched successor. Preserve the resulting real attempt history for a separate 48-hour assessment. GitHub scheduling and external source availability still have limits even when the relay is correct.

The independent URLScan timeout/backlog and indexed-CT provider states are separate from this event-cancellation defect. Do not close their health findings because the CertStream relay is repaired.

References: [GitHub concurrency semantics](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency), [public daily trends](https://radar.hecavex.com/data/daily-trends.json), [aggregate pipeline health](https://radar.hecavex.com/data/pipeline-health.json).
