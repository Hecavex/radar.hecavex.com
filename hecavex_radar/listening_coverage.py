"""Conservative wall-clock bounds from totals, never invented connection segments."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime


def stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        return result if result.isoformat(timespec="milliseconds").replace("+00:00", "Z") == value else None
    except ValueError:
        return None


def intersects(row: Mapping[str, object], start: datetime, end: datetime) -> bool:
    stopped = stamp(row.get("endedAt"))
    began = stamp(row.get("collectorStartedAt"))
    return bool(stopped and ((began and began < end and stopped > start)
                            or (not began and start < stopped <= end)))


def coverage_bounds(rows: Sequence[Mapping[str, object]], start: datetime, end: datetime, *,
                    reported_rows: Sequence[Mapping[str, object]] | None = None) -> dict[str, object]:
    """Bound union duration using connected totals and enclosing attempt intervals.

    For each overlap component, sum of guaranteed clipped totals minus maximal
    envelope overlap is a lower bound; so is its largest individual total.
    Upper bound is min(sum of possible clipped totals, union of envelopes).
    This is deliberately conservative, not a reconstruction of reconnect times.
    """
    window = max(0.0, (end - start).total_seconds())
    spans: list[tuple[float, float, float, float]] = []
    unknown = 0
    unknown_upper = 0.0
    # Worker totals follow end-time/count attribution, not interval overlap.
    # In particular, midnight-ending attempts have zero overlap with the new
    # day but their count and reported worker total belong to that new day.
    reported = 0.0
    for row in rows if reported_rows is None else reported_rows:
        raw, stopped = row.get("listeningSeconds"), stamp(row.get("endedAt"))
        if (not isinstance(raw, bool) and isinstance(raw, (int, float))
                and math.isfinite(raw) and raw >= 0 and stopped and start <= stopped < end):
            reported += raw
    for row in rows:
        raw = row.get("listeningSeconds")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
            unknown += 1
            unknown_upper += window
            continue
        began, stopped = stamp(row.get("collectorStartedAt")), stamp(row.get("endedAt"))
        if began is None or stopped is None or stopped < began or raw > (stopped - began).total_seconds() + 0.002:
            unknown += 1
            unknown_upper += min(raw, window)
            continue
        left, right = max(start, began), min(end, stopped)
        if right <= left:
            continue
        envelope = (stopped - began).total_seconds()
        clipped = (right - left).total_seconds()
        total = min(raw, envelope)
        minimum = max(0.0, total - (envelope - clipped))
        maximum = min(total, clipped)
        spans.append(((left - start).total_seconds(), (right - start).total_seconds(), minimum, maximum))
    lower = upper = 0.0
    group: list[tuple[float, float, float, float]] = []
    group_end = 0.0

    def bounds(items: list[tuple[float, float, float, float]]) -> tuple[float, float]:
        if not items:
            return 0.0, 0.0
        union = max(item[1] for item in items) - items[0][0]
        overlap = sum(item[1] - item[0] for item in items) - union
        return (max(max(item[2] for item in items), sum(item[2] for item in items) - overlap),
                min(union, sum(item[3] for item in items)))

    for span in sorted(spans):
        if group and span[0] >= group_end:
            low, high = bounds(group)
            lower, upper = lower + low, upper + high
            group = []
        group.append(span)
        group_end = max(group_end, span[1])
    low, high = bounds(group)
    lower = min(window, lower + low)
    upper = min(window, upper + high + unknown_upper)
    # Outward rounding keeps the serialized interval conservative.
    lower = math.floor(max(0.0, lower) * 1000) / 1000
    upper = min(window, math.ceil(max(lower, upper) * 1000) / 1000)
    return {
        "methodVersion": 2,
        "lowerSeconds": lower,
        "upperSeconds": upper,
        "precision": "unknown" if unknown else "exact" if lower == upper else "bounded",
        "unknownAttempts": unknown,
        "reportedWorkerSeconds": round(reported, 3),
    }
