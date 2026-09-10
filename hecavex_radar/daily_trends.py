from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .listening_coverage import coverage_bounds, intersects
from .provenance import REASON_CODES

MAXIMUM_DAYS = 365
MAXIMUM_DAILY_BYTES = 25 * 1024 * 1024
MAXIMUM_DAILY_ROWS = 25_000
MAXIMUM_LINE_BYTES = 16 * 1024
KNOWN_SOURCES = frozenset({"CertStream", "URLScan", "HECAVEX"})
KNOWN_EVIDENCE_TIERS = frozenset({"name-only", "corroborated", "reviewed"})
KNOWN_OUTCOMES = frozenset({"healthy-empty", "healthy-matches", "no-input", "partial", "failed"})
SIGNAL_ID = re.compile(r"^[0-9a-f]{20}$")


@dataclass(slots=True)
class _SignalFacets:
    brand: str | None = None
    sources: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(UTC)
    except ValueError:
        return None
    canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _safe_brand(value: object) -> str | None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 80:
        return None
    if any(character in value for character in (".", "/", "\\", "@", "<", ">", "[", "]")):
        return None
    if any(ord(character) < 32 for character in value):
        return None
    return value


def _counts(values: Iterable[str], maximum: int = 64) -> dict[str, int]:
    counter = Counter(values)
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:maximum])


def _percentage(numerator: float, denominator: float, digits: int = 2) -> float | None:
    return None if denominator <= 0 else min(100.0, round(100 * numerator / denominator, digits))


def _read_daily_rows(root: Path, filename: str, start: date, end: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current = start
    while current <= end:
        path = root / current.isoformat() / filename
        try:
            if path.stat().st_size > MAXIMUM_DAILY_BYTES:
                raise ValueError(f"Daily trend input exceeds {MAXIMUM_DAILY_BYTES} bytes: {path}")
            body = path.read_bytes()
        except FileNotFoundError:
            current += timedelta(days=1)
            continue
        if len(body.splitlines()) > MAXIMUM_DAILY_ROWS:
            raise ValueError(f"Daily trend input exceeds {MAXIMUM_DAILY_ROWS} rows: {path}")
        for line_number, raw_line in enumerate(body.splitlines(), start=1):
            if not raw_line or len(raw_line) > MAXIMUM_LINE_BYTES:
                raise ValueError(f"Daily trend input contains an invalid line at {path}:{line_number}.")
            try:
                value: Any = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"Daily trend input contains invalid JSON at {path}:{line_number}.") from error
            if isinstance(value, dict):
                rows.append(value)
        current += timedelta(days=1)
    return rows


def _signal_evidence(signals: Sequence[Mapping[str, object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for signal in signals[:25_000]:
        signal_id = signal.get("id")
        tier = signal.get("evidenceTier")
        if (
            isinstance(signal_id, str)
            and SIGNAL_ID.fullmatch(signal_id)
            and isinstance(tier, str)
            and tier in KNOWN_EVIDENCE_TIERS
        ):
            result[signal_id] = tier
    return result


def _collector_schedule(pipeline_health: Mapping[str, object]) -> tuple[int, int, str]:
    raw_windows = pipeline_health.get("windows")
    if isinstance(raw_windows, list):
        for raw in raw_windows:
            if not isinstance(raw, dict) or raw.get("hours") != 24:
                continue
            collection = raw.get("collection")
            if not isinstance(collection, dict):
                continue
            slots = collection.get("scheduledSlots")
            ceiling = collection.get("scheduledListeningCeilingPercent")
            if (
                type(slots) is int
                and slots > 0
                and isinstance(ceiling, (int, float))
                and not isinstance(ceiling, bool)
                and 0 <= float(ceiling) <= 100
            ):
                interval = max(60, round(86_400 / slots))
                listening = max(0, round((float(ceiling) / 100) * 86_400 / slots))
                if interval <= 86_400 and listening <= interval:
                    return interval, listening, "pipeline-health-24h-window"
    return 900, 240, "documented-default"


def _event_time(row: Mapping[str, object]) -> datetime | None:
    return _timestamp(row.get("observedAt"))


def _attempt_time(row: Mapping[str, object]) -> datetime | None:
    for field_name in ("endedAt", "collectorStartedAt", "startedAt"):
        parsed = _timestamp(row.get(field_name))
        if parsed is not None:
            return parsed
    return None


def _daily_discovery(
    events: Sequence[Mapping[str, object]], evidence_by_signal: Mapping[str, str],
    first_publications_by_signal: Mapping[str, str],
) -> dict[str, object]:
    observations = [event for event in events if event.get("eventType") == "observation"]
    transitions = [event for event in events if event.get("eventType") == "status-transition"]
    reobservations = sum(
        str(event.get("observedAt", "")) > first_publications_by_signal[identifier]
        for event in observations
        for identifier in [str(event.get("signalId", ""))]
        if identifier in first_publications_by_signal
    )
    first_publications = 0
    for event in transitions:
        reasons = event.get("reasonCodes")
        if event.get("previousStatus") is None and isinstance(reasons, list) and "first-publication" in reasons:
            first_publications += 1
    status_changes = sum(event.get("previousStatus") is not None for event in transitions)

    by_signal: dict[str, _SignalFacets] = {}
    for event in events:
        signal_id = event.get("signalId")
        if not isinstance(signal_id, str) or not SIGNAL_ID.fullmatch(signal_id):
            continue
        facets = by_signal.setdefault(signal_id, _SignalFacets())
        brand = _safe_brand(event.get("brand"))
        if facets.brand is None and brand is not None:
            facets.brand = brand
        sources = event.get("sources")
        if isinstance(sources, list):
            facets.sources.update(
                source for source in sources if isinstance(source, str) and source in KNOWN_SOURCES
            )
        reasons = event.get("reasonCodes")
        if isinstance(reasons, list):
            facets.reasons.update(
                reason for reason in reasons if isinstance(reason, str) and reason in REASON_CODES
            )

    brands = [facets.brand for facets in by_signal.values() if facets.brand is not None]
    sources = [source for facets in by_signal.values() for source in facets.sources]
    reasons = [reason for facets in by_signal.values() for reason in facets.reasons]
    evidence = [evidence_by_signal[signal_id] for signal_id in by_signal if signal_id in evidence_by_signal]
    return {
        "events": len(events),
        "uniqueSignals": len(by_signal),
        "observations": len(observations),
        "reobservations": reobservations,
        "firstPublications": first_publications,
        "statusChanges": status_changes,
        "facetSampleSize": len(by_signal),
        "evidenceClassifiedSignals": len(evidence),
        "byBrand": _counts(brands),
        "bySource": _counts(sources),
        "byEvidenceTier": _counts(evidence),
        "byReason": _counts(reasons),
    }


def _daily_coverage(
    attempts: Sequence[Mapping[str, object]],
    window_seconds: int,
    expected_interval: int,
    expected_listening: int,
    *,
    start: datetime,
    end: datetime,
    overlapping_attempts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    scheduled_slots = window_seconds // expected_interval if expected_interval else 0
    healthy = sum(attempt.get("outcome") in {"healthy-empty", "healthy-matches"} for attempt in attempts)
    outcomes: list[str] = []
    for attempt in attempts:
        outcome = attempt.get("outcome")
        if isinstance(outcome, str) and outcome in KNOWN_OUTCOMES:
            outcomes.append(outcome)
    bounds = coverage_bounds(overlapping_attempts, start, end)
    listening_seconds = float(str(bounds["lowerSeconds"]))
    return {
        "windowSeconds": window_seconds,
        "scheduledSlots": scheduled_slots,
        "recordedAttempts": len(attempts),
        "healthyAttempts": healthy,
        "recordedSchedulePercent": _percentage(len(attempts), scheduled_slots, 1),
        "listeningCoveragePercent": _percentage(listening_seconds, window_seconds),
        "scheduledListeningCeilingPercent": _percentage(
            scheduled_slots * expected_listening, window_seconds
        ),
        "listeningSeconds": listening_seconds,
        "coverageBounds": bounds,
        "outcomes": _counts(outcomes),
    }


def build_daily_trends(
    history_events: Sequence[Mapping[str, object]],
    collection_attempts: Sequence[Mapping[str, object]],
    signal_inventory: Sequence[Mapping[str, object]],
    pipeline_health: Mapping[str, object],
    generated_at: str,
    *,
    days: int = MAXIMUM_DAYS,
) -> dict[str, object]:
    generated = _timestamp(generated_at)
    if generated is None:
        raise ValueError("Daily trends require a canonical UTC generatedAt timestamp.")
    if not 1 <= days <= MAXIMUM_DAYS:
        raise ValueError(f"Daily trends must contain between 1 and {MAXIMUM_DAYS} days.")
    first_day = generated.date() - timedelta(days=days - 1)
    expected_interval, expected_listening, schedule_source = _collector_schedule(pipeline_health)
    evidence_by_signal = _signal_evidence(signal_inventory)
    # As in the event feed, explicit first publication takes precedence over
    # inventory firstSeen. No provenance means no invented reobservation.
    first_seen = {
        str(signal["id"]): str(signal["firstSeen"])
        for signal in signal_inventory
        if isinstance(signal.get("id"), str) and _timestamp(signal.get("firstSeen")) is not None
    }
    publications: dict[str, str] = {}
    for event in history_events:
        observed = _event_time(event)
        reasons = event.get("reasonCodes")
        identifier = event.get("signalId")
        if (observed is not None and observed <= generated and isinstance(identifier, str)
                and event.get("eventType") == "status-transition"
                and event.get("previousStatus") is None
                and isinstance(reasons, list) and "first-publication" in reasons):
            stamp = str(event["observedAt"])
            publications[identifier] = min(publications.get(identifier, stamp), stamp)
    first_seen.update(publications)

    events_by_day: dict[str, list[Mapping[str, object]]] = {}
    for event in history_events:
        observed = _event_time(event)
        signal_id = event.get("signalId")
        if (
            observed is None
            or not first_day <= observed.date() <= generated.date()
            or observed > generated
            or event.get("eventType") not in {"observation", "status-transition"}
            or not isinstance(signal_id, str)
            or not SIGNAL_ID.fullmatch(signal_id)
        ):
            continue
        events_by_day.setdefault(observed.date().isoformat(), []).append(event)
    attempts_by_day: dict[str, list[Mapping[str, object]]] = {}
    for attempt in collection_attempts:
        observed = _attempt_time(attempt)
        if (
            observed is None
            or not first_day <= observed.date() <= generated.date()
            or observed > generated
            or attempt.get("outcome") not in KNOWN_OUTCOMES
        ):
            continue
        attempts_by_day.setdefault(observed.date().isoformat(), []).append(attempt)

    series: list[dict[str, object]] = []
    current = first_day
    while current <= generated.date():
        key = current.isoformat()
        start = datetime.combine(current, time.min, tzinfo=UTC)
        end = min(start + timedelta(days=1), generated)
        window_seconds = max(0, int((end - start).total_seconds()))
        day_events = sorted(
            events_by_day.get(key, []),
            key=lambda row: (str(row.get("observedAt", "")), str(row.get("eventId", ""))),
        )
        day_attempts = sorted(
            attempts_by_day.get(key, []),
            key=lambda row: (
                str(row.get("endedAt", "")),
                str(row.get("collectorStartedAt", "")),
                str(row.get("startedAt", "")),
            ),
        )
        # The series is intentionally sparse. Consumers fill missing UTC dates
        # with zero recorded attempts and zero discovery events using the
        # published range and collector schedule. This keeps a full-year static
        # artifact comfortably bounded without hiding coverage gaps.
        overlaps = [row for row in collection_attempts if row.get("outcome") in KNOWN_OUTCOMES
                    and intersects(row, start, end)]
        if day_events or day_attempts or overlaps or current == generated.date():
            series.append(
                {
                    "date": key,
                    "partialDay": end < start + timedelta(days=1),
                    "collectorCoverage": _daily_coverage(
                        day_attempts,
                        window_seconds,
                        expected_interval,
                        expected_listening,
                        start=start,
                        end=end,
                        overlapping_attempts=overlaps,
                    ),
                    "discovery": _daily_discovery(day_events, evidence_by_signal, first_seen),
                }
            )
        current += timedelta(days=1)

    return {
        "schemaVersion": 1,
        "dataset": "radar-daily-trends",
        "countingMethodVersion": 2,
        "reobservationSemantics": (
            "Version 2: observations strictly after retained first-publication provenance, falling back to "
            "inventory firstSeen. Unknown earlier provenance is unclassified, not a new publication. "
            "This corrects version 1, which subtracted each day's distinct observed IDs."
        ),
        "generatedAt": generated_at,
        "retentionDays": days,
        "from": first_day.isoformat(),
        "to": generated.date().isoformat(),
        "semantics": (
            "Counts describe Radar discovery and publication activity under the collector coverage shown beside "
            "them. They are not a measure of Lithuanian phishing prevalence or total incident volume."
        ),
        "facetSemantics": "Brand, source, evidence and reason facets count unique signals within each UTC day.",
        "seriesSemantics": (
            "The series is sparse. Missing UTC dates inside the stated range mean zero recorded attempts and "
            "zero discovery events; consumers can derive scheduled slots from collectorSchedule."
        ),
        "omittedZeroDays": days - len(series),
        "collectorSchedule": {
            "expectedIntervalSeconds": expected_interval,
            "expectedListeningSeconds": expected_listening,
            "derivedFrom": schedule_source,
        },
        "series": series,
        "privacy": "Aggregate counters only; no domains, URLs, signal identifiers or collector payloads.",
    }


def build_daily_trends_from_repository(
    repository: Path,
    signal_inventory: Sequence[Mapping[str, object]],
    pipeline_health: Mapping[str, object],
    generated_at: str,
    *,
    days: int = MAXIMUM_DAYS,
) -> dict[str, object]:
    generated = _timestamp(generated_at)
    if generated is None:
        raise ValueError("Daily trends require a canonical UTC generatedAt timestamp.")
    if not 1 <= days <= MAXIMUM_DAYS:
        raise ValueError(f"Daily trends must contain between 1 and {MAXIMUM_DAYS} days.")
    first_day = generated.date() - timedelta(days=days - 1)
    # Collectors may partition close-to-midnight attempts using the runner's
    # calendar date. Read one padding day on each side, then let the pure
    # builder enforce the exact UTC window from record timestamps.
    padded_start = first_day - timedelta(days=1)
    padded_end = generated.date() + timedelta(days=1)
    events = _read_daily_rows(repository / "data/history/daily", "events.ndjson", padded_start, padded_end)
    attempts = _read_daily_rows(repository / "data/certstream", "attempts.ndjson", padded_start, padded_end)
    return build_daily_trends(
        events,
        attempts,
        signal_inventory,
        pipeline_health,
        generated_at,
        days=days,
    )
