"""Exact effective-time queries over the complete eligible hostname cohort."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import TypedDict, cast

from .observation_store import canonical_hostname, grouping_metadata, validate_timestamp

METRICS_VERSION = "radar-period-metrics-effective-time-v2"
TIME_BASIS = "source-observation-or-explicit-collector-fallback"
TIME_BASES = frozenset({"source-observation-time", TIME_BASIS})
MAXIMUM_CALENDAR_MONTHS = 1200
POLICY_KEYS = {"identity", "matching", "review", "metrics", "store"}
COVERAGE_KEYS = {
    "availableFrom", "recordedFrom", "publicationRecordedFrom", "recoveredFrom", "recoveredThrough",
    "recoveredDays", "missingDays", "historyComplete", "collectionComplete", "historicalRecordingTimesComplete",
    "historicalPublicationTimesComplete", "basis", "partialCurrentDay",
}


class PeriodWindow(TypedDict):
    key: str
    startInclusive: str | None
    endExclusive: str
    uniqueHostnames: int
    domainGroups: int
    candidateDays: int
    firstRecordedHostnames: int | None
    firstPublishedHostnames: int | None
    exactWithinRecordedData: bool
    completeCollection: bool


class PeriodMetrics(TypedDict):
    schemaVersion: int
    dataset: str
    generatedAt: str
    asOf: str
    timeBasis: str
    identityUnit: str
    population: str
    hostnamesSha256: str
    grouping: dict[str, object]
    coverage: dict[str, object]
    policyVersions: dict[str, str]
    windows: list[PeriodWindow]


def _day(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Observation day must be a canonical UTC date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Invalid observation day.") from error
    if parsed.isoformat() != value:
        raise ValueError("Noncanonical observation day.")
    return value


def validate_coverage(value: Mapping[str, object]) -> dict[str, object]:
    if set(value) != COVERAGE_KEYS or value["basis"] != "recorded-and-recovered-observation-facts":
        raise ValueError("Invalid observation coverage fields.")
    for key in ("availableFrom", "recordedFrom", "publicationRecordedFrom"):
        if value[key] is not None:
            validate_timestamp(value[key])
    for key in ("recoveredFrom", "recoveredThrough"):
        if value[key] is not None:
            _day(value[key])
    for key in ("recoveredDays", "missingDays"):
        days = value[key]
        if not isinstance(days, list) or [_day(day) for day in days] != sorted(set(days)):
            raise ValueError("Observation coverage dates must be sorted and unique.")
    for key in ("historyComplete", "collectionComplete", "historicalRecordingTimesComplete",
                "historicalPublicationTimesComplete", "partialCurrentDay"):
        if type(value[key]) is not bool:
            raise ValueError("Observation coverage completeness must be explicit booleans.")
    return dict(value)


def _records(records: Sequence[Mapping[str, object]], as_of: str) -> list[Mapping[str, object]]:
    seen: set[str] = set()
    for record in records:
        domain = record.get("domain")
        if not isinstance(domain, str):
            raise ValueError("Period record is missing its canonical defanged hostname.")
        host = canonical_hostname(domain)
        if (record.get("id") != host["id"] or record.get("domain") != host["domain"]
                or record.get("domainGroup") != host["domainGroup"] or host["id"] in seen):
            raise ValueError("Period hostname identity or duplicate record mismatch.")
        first = validate_timestamp(record.get("firstSeen"))
        last = validate_timestamp(record.get("lastSeen"))
        days, day_last = record.get("observedDays"), record.get("observedDayLastSeen")
        if (first > last or last > as_of or not isinstance(days, list) or not isinstance(day_last, dict)
                or not days or [_day(day) for day in days] != sorted(set(days)) or sorted(day_last) != days):
            raise ValueError("Period observation day membership is inconsistent.")
        for day, timestamp in day_last.items():
            validated = validate_timestamp(timestamp)
            if not isinstance(day, str) or validated[:10] != day or not first <= validated <= last:
                raise ValueError("Period per-day latest source timestamp is inconsistent.")
        if days[0] != first[:10] or days[-1] != last[:10] or day_last[days[-1]] != last:
            raise ValueError("Period first/last boundaries disagree with exact day membership.")
        for key in ("firstRecordedAt", "firstPublishedAt"):
            if record.get(key) is not None and validate_timestamp(record[key]) > as_of:
                raise ValueError("Period recording/publication timestamp exceeds asOf.")
        seen.add(host["id"])
    return list(records)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _within(timestamp: str, start: str | None, end: str) -> bool:
    return (start is None or timestamp >= start) and timestamp < end


def _clock_count(records: Sequence[Mapping[str, object]], *, field: str, start: str | None, end: str,
                 coverage: Mapping[str, object]) -> int | None:
    recording = field == "firstRecordedAt"
    complete = coverage["historicalRecordingTimesComplete" if recording else "historicalPublicationTimesComplete"]
    activation = coverage["recordedFrom" if recording else "publicationRecordedFrom"]
    if complete and any(record.get(field) is None for record in records):
        raise ValueError("Historical clock completeness contradicts unknown hostname clocks.")
    if not complete and (start is None or not isinstance(activation, str) or start < activation):
        return None
    return sum(isinstance(record.get(field), str) and _within(cast(str, record[field]), start, end)
               for record in records)


def _window(records: Sequence[Mapping[str, object]], key: str, start: str | None, end: str,
            coverage: Mapping[str, object]) -> PeriodWindow:
    selected: list[Mapping[str, object]] = []
    candidate_days = 0
    for record in records:
        day_last = cast(dict[str, str], record["observedDayLastSeen"])
        matched = sum(_within(timestamp, start, end) for timestamp in day_last.values())
        if matched:
            selected.append(record)
            candidate_days += matched
    return {
        "key": key, "startInclusive": start, "endExclusive": end,
        "uniqueHostnames": len(selected), "domainGroups": len({record["domainGroup"] for record in selected}),
        "candidateDays": candidate_days,
        "firstRecordedHostnames": _clock_count(records, field="firstRecordedAt", start=start, end=end,
                                               coverage=coverage),
        "firstPublishedHostnames": _clock_count(records, field="firstPublishedAt", start=start, end=end,
                                                coverage=coverage),
        "exactWithinRecordedData": True, "completeCollection": cast(bool, coverage["collectionComplete"]),
    }


def build_period_metrics(
    records: Sequence[Mapping[str, object]], *, as_of: str, hostnames_sha256: str,
    coverage: Mapping[str, object], policy_versions: Mapping[str, str], time_basis: str = TIME_BASIS,
) -> PeriodMetrics:
    validate_timestamp(as_of)
    if time_basis not in TIME_BASES:
        raise ValueError("Unsupported observation time basis.")
    if re.fullmatch(r"[a-f0-9]{64}", hostnames_sha256) is None:
        raise ValueError("Period metrics require the exact hostname index SHA-256.")
    if (set(policy_versions) != POLICY_KEYS
            or any(not isinstance(value, str) or not value.strip() for value in policy_versions.values())):
        raise ValueError("Period metrics require every explicit policy version.")
    normalized_coverage = validate_coverage(coverage)
    normalized_records = _records(records, as_of)
    if time_basis == "source-observation-time" and any(
        "collector-time-fallback" in cast(list[str], record.get("sourceTimeProvenances", []))
        for record in normalized_records
    ):
        raise ValueError("Source-only time basis contradicts explicit collector-time fallback.")
    current = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    end = _iso(current + timedelta(milliseconds=1))
    windows = [_window(normalized_records, f"{days}d", _iso(current - timedelta(days=days)), end,
                       normalized_coverage) for days in (30, 90, 365)]
    windows.append(_window(normalized_records, "all", None, end, normalized_coverage))
    starts = [cast(str, record["firstSeen"]) for record in normalized_records]
    if isinstance(normalized_coverage["availableFrom"], str):
        starts.append(normalized_coverage["availableFrom"])
    earliest = min(starts, default=as_of)[:7]
    month = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calendar_windows: list[PeriodWindow] = []
    while month.strftime("%Y-%m") >= earliest:
        next_month = (month.replace(year=month.year + 1, month=1)
                      if month.month == 12 else month.replace(month=month.month + 1))
        calendar_windows.append(_window(normalized_records, f"month:{month:%Y-%m}", _iso(month), _iso(next_month),
                                        normalized_coverage))
        if len(calendar_windows) > MAXIMUM_CALENDAR_MONTHS:
            raise ValueError("Period calendar span exceeds the explicit supported budget.")
        month = (month.replace(year=month.year - 1, month=12)
                 if month.month == 1 else month.replace(month=month.month - 1))
    windows.extend(calendar_windows)
    return {
        "schemaVersion": 1, "dataset": "radar-period-metrics", "generatedAt": as_of, "asOf": as_of,
        "timeBasis": time_basis, "identityUnit": "canonical-hostname",
        "population": "public-eligible-recorded-hostnames", "hostnamesSha256": hostnames_sha256,
        "grouping": grouping_metadata(), "coverage": normalized_coverage, "policyVersions": dict(policy_versions),
        "windows": windows,
    }
