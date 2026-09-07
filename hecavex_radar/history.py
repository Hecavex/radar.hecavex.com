from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from .brands import (
    BrandRegistry,
    domain_match_brands,
    is_brand_collision,
    is_suppressed_domain,
    normalize_domain,
    resolve_brand_name,
    score_domain,
)
from .history_partitions import read_document, write_document
from .models import RadarSignal, ReasonCode, SignalStatus
from .provenance import normalize_reason_codes
from .safety import defang_host, stable_id

MAXIMUM_EVENT_BYTES = 8 * 1024
MAXIMUM_DAILY_BYTES = 8 * 1024 * 1024
MAXIMUM_DAILY_EVENTS = 10_000
MAXIMUM_SUMMARY_BYTES = 12 * 1024 * 1024
MAXIMUM_PUBLIC_BYTES = 512 * 1024
MAXIMUM_SUMMARY_SIGNALS = 25_000
MAXIMUM_TRANSITIONS = 16
MAXIMUM_RECENT_EVENT_IDS = 64
UTC_MILLISECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
EVENT_ID = re.compile(r"^[a-f\d]{32}$")
SIGNAL_ID = re.compile(r"^[a-f\d]{20}$")
KNOWN_SOURCES = frozenset({"CertStream", "URLScan", "HECAVEX"})
KNOWN_STATUSES = frozenset({"active", "suspected", "offline", "mitigated", "unknown"})


class HistoryEvent(TypedDict):
    schemaVersion: Literal[1]
    eventId: str
    signalId: str
    eventType: Literal["observation", "status-transition"]
    observedAt: str
    domain: str
    brand: str
    sources: list[str]
    status: SignalStatus
    previousStatus: SignalStatus | None
    confidence: int
    reasonCodes: list[ReasonCode]


class HistoryTransition(TypedDict):
    eventId: str
    observedAt: str
    previousStatus: SignalStatus | None
    status: SignalStatus
    sources: list[str]
    reasonCodes: list[ReasonCode]


class HistorySummarySignal(TypedDict):
    id: str
    domain: str
    brand: str
    firstSeen: str
    lastSeen: str
    observationCount: int
    sources: list[str]
    latestStatus: SignalStatus
    statusObservedAt: str
    reasonCodes: list[ReasonCode]
    statusTransitions: list[HistoryTransition]
    recentEventIds: list[str]


class HistorySummary(TypedDict):
    schemaVersion: Literal[1]
    dataset: Literal["radar-history-summary"]
    generatedAt: str
    compactedThrough: str | None
    signals: list[HistorySummarySignal]


class PublicHistorySignal(TypedDict):
    id: str
    domain: str
    brand: str
    firstSeen: str
    lastSeen: str
    observationCount: int
    sources: list[str]
    latestStatus: SignalStatus
    reasonCodes: list[ReasonCode]
    statusTransitions: list[HistoryTransition]


class PublicHistory(TypedDict):
    schemaVersion: Literal[1]
    dataset: Literal["history"]
    generatedAt: str
    detailRetentionDays: int
    summaryRetentionDays: int
    signals: list[PublicHistorySignal]


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not UTC_MILLISECONDS.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    canonical = parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _day(value: str) -> str:
    parsed = _timestamp(value)
    if parsed is None:
        raise ValueError("History event has a non-canonical timestamp.")
    return parsed.astimezone(UTC).date().isoformat()


def _bounded_path(value: str | Path, label: str) -> Path:
    repository = Path.cwd().resolve()
    target = (repository / value).resolve()
    if target == repository or not target.is_relative_to(repository):
        raise ValueError(f"{label} must stay inside the repository.")
    return target


def _canonical_domain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = normalize_domain(value.replace("[.]", "."))
    return value if normalized and defang_host(normalized) == value else None


def _event_identifier(payload: dict[str, object]) -> str:
    identity = {
        key: payload[key]
        for key in (
            "schemaVersion",
            "signalId",
            "eventType",
            "observedAt",
            "sources",
            "status",
            "previousStatus",
        )
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _event(
    signal: RadarSignal,
    *,
    event_type: Literal["observation", "status-transition"],
    previous_status: SignalStatus | None,
    extra_reason: ReasonCode | None = None,
) -> HistoryEvent | None:
    brand = signal["brand"]
    if not brand:
        return None
    reasons = list(signal.get("reasonCodes", []))
    if extra_reason:
        reasons.append(extra_reason)
    normalized_reasons = normalize_reason_codes(reasons)
    if not normalized_reasons:
        return None
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "signalId": signal["id"],
        "eventType": event_type,
        "observedAt": signal["lastSeen"],
        "domain": signal["domain"],
        "brand": brand,
        "sources": sorted(set(signal["sources"])),
        "status": signal["status"],
        "previousStatus": previous_status,
        "confidence": signal["confidence"],
        "reasonCodes": normalized_reasons,
    }
    event: HistoryEvent = cast(HistoryEvent, {**payload, "eventId": _event_identifier(payload)})
    return event if _is_event(event) else None


def build_history_events(
    observations: list[RadarSignal],
    current: list[RadarSignal],
    previous_statuses: dict[str, SignalStatus],
) -> list[HistoryEvent]:
    current_by_id = {signal["id"]: signal for signal in current}
    events: list[HistoryEvent] = []
    for signal in observations:
        published = current_by_id.get(signal["id"])
        if published is None or published["brand"] != signal["brand"]:
            continue
        for observed_at in dict.fromkeys((signal["firstSeen"], signal["lastSeen"])):
            boundary = cast(RadarSignal, {**signal, "lastSeen": observed_at})
            observation = _event(boundary, event_type="observation", previous_status=None)
            if observation:
                events.append(observation)

    for signal in current:
        previous = previous_statuses.get(signal["id"])
        if previous == signal["status"]:
            continue
        transition = _event(
            signal,
            event_type="status-transition",
            previous_status=previous,
            extra_reason="first-publication" if previous is None else "source-status-change",
        )
        if transition:
            events.append(transition)
    unique = {event["eventId"]: event for event in events}
    return sorted(unique.values(), key=lambda item: (item["observedAt"], item["eventId"]))


def _is_event(value: Any, expected_day: str | None = None) -> bool:
    fields = {
        "schemaVersion",
        "eventId",
        "signalId",
        "eventType",
        "observedAt",
        "domain",
        "brand",
        "sources",
        "status",
        "previousStatus",
        "confidence",
        "reasonCodes",
    }
    if not isinstance(value, dict) or set(value) != fields:
        return False
    domain = _canonical_domain(value.get("domain"))
    observed = _timestamp(value.get("observedAt"))
    sources = value.get("sources")
    reasons = value.get("reasonCodes")
    previous = value.get("previousStatus")
    payload = {key: value[key] for key in fields if key != "eventId"}
    return bool(
        value.get("schemaVersion") == 1
        and isinstance(value.get("eventId"), str)
        and EVENT_ID.fullmatch(value["eventId"])
        and value["eventId"] == _event_identifier(payload)
        and isinstance(value.get("signalId"), str)
        and SIGNAL_ID.fullmatch(value["signalId"])
        and domain is not None
        and value["signalId"] == stable_id(domain.lower())
        and value.get("eventType") in {"observation", "status-transition"}
        and observed is not None
        and (expected_day is None or observed.date().isoformat() == expected_day)
        and isinstance(value.get("brand"), str)
        and 0 < len(value["brand"]) <= 120
        and value["brand"].strip() == value["brand"]
        and isinstance(sources, list)
        and 1 <= len(sources) <= len(KNOWN_SOURCES)
        and sources == sorted(set(sources))
        and all(source in KNOWN_SOURCES for source in sources)
        and value.get("status") in KNOWN_STATUSES
        and (previous is None or previous in KNOWN_STATUSES)
        and (value["eventType"] == "status-transition" or previous is None)
        and type(value.get("confidence")) is int
        and 0 <= value["confidence"] <= 100
        and isinstance(reasons, list)
        and 1 <= len(reasons) <= 16
        and reasons == normalize_reason_codes(reasons)
    )


def read_event_file(path: Path) -> list[HistoryEvent]:
    try:
        if path.stat().st_size > MAXIMUM_DAILY_BYTES:
            raise ValueError(f"History archive exceeds 8 MiB: {path}")
        body = path.read_bytes()
    except FileNotFoundError:
        return []
    expected_day = path.parent.name if path.name == "events.ndjson" else None
    records: list[HistoryEvent] = []
    for line_number, raw_line in enumerate(body.splitlines(), start=1):
        if not raw_line or len(raw_line) > MAXIMUM_EVENT_BYTES:
            raise ValueError(f"History archive contains an invalid line at {path}:{line_number}.")
        try:
            value: Any = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"History archive contains invalid JSON at {path}:{line_number}.") from error
        if not _is_event(value, expected_day):
            raise ValueError(f"History archive contains an invalid event at {path}:{line_number}.")
        records.append(value)
        if len(records) > MAXIMUM_DAILY_EVENTS:
            raise ValueError(f"History archive contains more than {MAXIMUM_DAILY_EVENTS} events: {path}.")
    if len({event["eventId"] for event in records}) != len(records):
        raise ValueError(f"History archive contains duplicate event IDs: {path}.")
    return records


def _atomic_write(path: Path, body: bytes, maximum: int) -> None:
    if len(body) > maximum:
        raise ValueError(f"Refusing to write oversized history artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def append_history_events(root: str | Path, events: list[HistoryEvent]) -> int:
    archive_root = _bounded_path(root, "RADAR_HISTORY_ROOT")
    groups: dict[str, list[HistoryEvent]] = {}
    for event in events:
        if not _is_event(event):
            raise ValueError("Refusing to archive an invalid history event.")
        groups.setdefault(_day(event["observedAt"]), []).append(event)

    added = 0
    for day, additions in sorted(groups.items()):
        path = archive_root / "daily" / day / "events.ndjson"
        existing = read_event_file(path)
        known = {event["eventId"] for event in existing}
        unique_by_id = {
            event["eventId"]: event for event in additions if event["eventId"] not in known
        }
        unique = sorted(unique_by_id.values(), key=lambda event: (event["observedAt"], event["eventId"]))
        if not unique:
            continue
        combined = existing + unique
        if len(combined) > MAXIMUM_DAILY_EVENTS:
            raise ValueError(
                f"Refusing to exceed {MAXIMUM_DAILY_EVENTS} events in one UTC history partition: {path}."
            )
        lines = [json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in combined]
        body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        _atomic_write(path, body, MAXIMUM_DAILY_BYTES)
        added += max(0, len(combined) - len(existing))
    return added


def _empty_summary(now: str) -> HistorySummary:
    return {
        "schemaVersion": 1,
        "dataset": "radar-history-summary",
        "generatedAt": now,
        "compactedThrough": None,
        "signals": [],
    }


def _valid_transition(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "eventId",
        "observedAt",
        "previousStatus",
        "status",
        "sources",
        "reasonCodes",
    }:
        return False
    previous = value.get("previousStatus")
    sources = value.get("sources")
    reasons = value.get("reasonCodes")
    return bool(
        isinstance(value.get("eventId"), str)
        and EVENT_ID.fullmatch(value["eventId"])
        and _timestamp(value.get("observedAt")) is not None
        and (previous is None or previous in KNOWN_STATUSES)
        and value.get("status") in KNOWN_STATUSES
        and isinstance(sources, list)
        and sources == sorted(set(sources))
        and all(source in KNOWN_SOURCES for source in sources)
        and isinstance(reasons, list)
        and reasons == normalize_reason_codes(reasons)
        and bool(reasons)
    )


def _valid_summary_signal(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "domain",
        "brand",
        "firstSeen",
        "lastSeen",
        "observationCount",
        "sources",
        "latestStatus",
        "statusObservedAt",
        "reasonCodes",
        "statusTransitions",
        "recentEventIds",
    }:
        return False
    domain = _canonical_domain(value.get("domain"))
    first = _timestamp(value.get("firstSeen"))
    last = _timestamp(value.get("lastSeen"))
    status_at = _timestamp(value.get("statusObservedAt"))
    sources = value.get("sources")
    reasons = value.get("reasonCodes")
    transitions = value.get("statusTransitions")
    event_ids = value.get("recentEventIds")
    return bool(
        domain
        and isinstance(value.get("id"), str)
        and SIGNAL_ID.fullmatch(value["id"])
        and value["id"] == stable_id(domain.lower())
        and isinstance(value.get("brand"), str)
        and 0 < len(value["brand"]) <= 120
        and first is not None
        and last is not None
        and status_at is not None
        and first <= last
        and type(value.get("observationCount")) is int
        and 0 <= value["observationCount"] <= 2_147_483_647
        and isinstance(sources, list)
        and sources == sorted(set(sources))
        and all(source in KNOWN_SOURCES for source in sources)
        and value.get("latestStatus") in KNOWN_STATUSES
        and isinstance(reasons, list)
        and reasons == normalize_reason_codes(reasons)
        and isinstance(transitions, list)
        and len(transitions) <= MAXIMUM_TRANSITIONS
        and all(_valid_transition(transition) for transition in transitions)
        and isinstance(event_ids, list)
        and len(event_ids) <= MAXIMUM_RECENT_EVENT_IDS
        and len(event_ids) == len(set(event_ids))
        and all(isinstance(identifier, str) and EVENT_ID.fullmatch(identifier) for identifier in event_ids)
    )


def _load_summary(path: Path, now: str) -> HistorySummary:
    try:
        if path.stat().st_size > MAXIMUM_SUMMARY_BYTES:
            raise ValueError("History summary exceeds 12 MiB.")
        value: Any = read_document(path, MAXIMUM_SUMMARY_BYTES)
    except FileNotFoundError:
        return _empty_summary(now)
    except json.JSONDecodeError as error:
        raise ValueError("History summary is invalid JSON.") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "dataset", "generatedAt", "compactedThrough", "signals"}
        or value.get("schemaVersion") != 1
        or value.get("dataset") != "radar-history-summary"
        or _timestamp(value.get("generatedAt")) is None
        or (
            value.get("compactedThrough") is not None
            and not isinstance(value.get("compactedThrough"), str)
        )
        or not isinstance(value.get("signals"), list)
        or len(value["signals"]) > MAXIMUM_SUMMARY_SIGNALS
        or not all(_valid_summary_signal(signal) for signal in value["signals"])
    ):
        raise ValueError("History summary does not match schema version 1.")
    compacted = value.get("compactedThrough")
    if isinstance(compacted, str):
        try:
            compacted_date = date.fromisoformat(compacted)
            reference = _timestamp(now)
            if (
                compacted_date.isoformat() != compacted
                or reference is None
                or compacted_date > reference.astimezone(UTC).date()
            ):
                raise ValueError
        except ValueError as error:
            raise ValueError("History summary compactedThrough is invalid or in the future.") from error
    return cast(HistorySummary, value)


def _new_summary_signal(event: HistoryEvent) -> HistorySummarySignal:
    transition: list[HistoryTransition] = []
    if event["eventType"] == "status-transition":
        transition.append(
            {
                "eventId": event["eventId"],
                "observedAt": event["observedAt"],
                "previousStatus": event["previousStatus"],
                "status": event["status"],
                "sources": event["sources"],
                "reasonCodes": event["reasonCodes"],
            }
        )
    return {
        "id": event["signalId"],
        "domain": event["domain"],
        "brand": event["brand"],
        "firstSeen": event["observedAt"],
        "lastSeen": event["observedAt"],
        "observationCount": int(event["eventType"] == "observation"),
        "sources": event["sources"],
        "latestStatus": event["status"],
        "statusObservedAt": event["observedAt"],
        "reasonCodes": event["reasonCodes"],
        "statusTransitions": transition,
        "recentEventIds": [event["eventId"]],
    }


def _merge_events(
    initial: list[HistorySummarySignal], events: list[HistoryEvent]
) -> list[HistorySummarySignal]:
    merged = {signal["id"]: cast(HistorySummarySignal, {**signal}) for signal in initial}
    conflicted: set[str] = set()
    for event in sorted(events, key=lambda item: (item["observedAt"], item["eventId"])):
        identifier = event["signalId"]
        if identifier in conflicted:
            continue
        current = merged.get(identifier)
        if current is None:
            merged[identifier] = _new_summary_signal(event)
            continue
        if current["domain"] != event["domain"] or current["brand"] != event["brand"]:
            merged.pop(identifier, None)
            conflicted.add(identifier)
            continue
        if event["eventId"] in current["recentEventIds"]:
            continue
        current["firstSeen"] = min(current["firstSeen"], event["observedAt"])
        current["lastSeen"] = max(current["lastSeen"], event["observedAt"])
        current["sources"] = sorted(set(current["sources"] + event["sources"]))
        current["reasonCodes"] = normalize_reason_codes(current["reasonCodes"] + event["reasonCodes"])
        if event["eventType"] == "observation":
            current["observationCount"] = min(2_147_483_647, current["observationCount"] + 1)
        if event["observedAt"] >= current["statusObservedAt"]:
            current["latestStatus"] = event["status"]
            current["statusObservedAt"] = event["observedAt"]
        if event["eventType"] == "status-transition":
            transition: HistoryTransition = {
                "eventId": event["eventId"],
                "observedAt": event["observedAt"],
                "previousStatus": event["previousStatus"],
                "status": event["status"],
                "sources": event["sources"],
                "reasonCodes": event["reasonCodes"],
            }
            transitions = {item["eventId"]: item for item in current["statusTransitions"]}
            transitions[transition["eventId"]] = transition
            current["statusTransitions"] = sorted(
                transitions.values(), key=lambda item: (item["observedAt"], item["eventId"])
            )[-MAXIMUM_TRANSITIONS:]
        current["recentEventIds"] = (current["recentEventIds"] + [event["eventId"]])[-MAXIMUM_RECENT_EVENT_IDS:]
    return sorted(merged.values(), key=lambda item: (item["lastSeen"], item["id"]), reverse=True)


def _daily_files(root: Path) -> list[Path]:
    daily = root / "daily"
    try:
        return sorted(daily.glob("????-??-??/events.ndjson"))
    except OSError:
        return []


def compact_history(root: str | Path, now: datetime, detail_days: int, summary_days: int) -> HistorySummary:
    archive_root = _bounded_path(root, "RADAR_HISTORY_ROOT")
    summary_path = archive_root / "summary.json"
    now_text = now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    summary = _load_summary(summary_path, now_text)
    cutoff = now.astimezone(UTC).date() - timedelta(days=detail_days)
    old_files = [path for path in _daily_files(archive_root) if path.parent.name < cutoff.isoformat()]
    watermark = summary["compactedThrough"]
    uncompacted_files = [
        path for path in old_files if watermark is None or path.parent.name > watermark
    ]
    if uncompacted_files:
        events = [event for path in uncompacted_files for event in read_event_file(path)]
        summary["signals"] = _merge_events(summary["signals"], events)
        summary["compactedThrough"] = max(path.parent.name for path in uncompacted_files)

    summary_cutoff = now.astimezone(UTC) - timedelta(days=summary_days)
    summary["signals"] = [
        signal
        for signal in summary["signals"]
        if (last_seen := _timestamp(signal["lastSeen"])) is not None and last_seen >= summary_cutoff
    ]
    if len(summary["signals"]) > MAXIMUM_SUMMARY_SIGNALS:
        raise ValueError("Retained history exceeds 25,000 hosts. Refusing silent historical eviction.")
    summary["generatedAt"] = now_text
    existing_summary: object = None
    with suppress(FileNotFoundError, json.JSONDecodeError, OSError):
        existing_summary = read_document(summary_path, MAXIMUM_SUMMARY_BYTES)
    if _stable_artifact_view(existing_summary) != _stable_artifact_view(summary):
        write_document(summary_path, dict(summary), MAXIMUM_SUMMARY_BYTES, _atomic_write)
    for path in old_files:
        path.unlink(missing_ok=True)
        with suppress(OSError):
            path.parent.rmdir()
    return summary


def _valid_public_signal(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "domain",
        "brand",
        "firstSeen",
        "lastSeen",
        "observationCount",
        "sources",
        "latestStatus",
        "reasonCodes",
        "statusTransitions",
    }:
        return False
    domain = _canonical_domain(value.get("domain"))
    first = _timestamp(value.get("firstSeen"))
    last = _timestamp(value.get("lastSeen"))
    sources = value.get("sources")
    reasons = value.get("reasonCodes")
    transitions = value.get("statusTransitions")
    return bool(
        domain
        and isinstance(value.get("id"), str)
        and SIGNAL_ID.fullmatch(value["id"])
        and value["id"] == stable_id(domain.lower())
        and isinstance(value.get("brand"), str)
        and 0 < len(value["brand"]) <= 120
        and value["brand"].strip() == value["brand"]
        and first is not None
        and last is not None
        and first <= last
        and type(value.get("observationCount")) is int
        and 0 <= value["observationCount"] <= 2_147_483_647
        and isinstance(sources, list)
        and 1 <= len(sources) <= len(KNOWN_SOURCES)
        and sources == sorted(set(sources))
        and all(source in KNOWN_SOURCES for source in sources)
        and value.get("latestStatus") in KNOWN_STATUSES
        and isinstance(reasons, list)
        and 1 <= len(reasons) <= 16
        and reasons == normalize_reason_codes(reasons)
        and isinstance(transitions, list)
        and len(transitions) <= MAXIMUM_TRANSITIONS
        and all(_valid_transition(transition) for transition in transitions)
    )


def read_public_history(path: str | Path) -> PublicHistory | None:
    target = _bounded_path(path, "RADAR_HISTORY_OUTPUT")
    try:
        if target.stat().st_size > MAXIMUM_PUBLIC_BYTES:
            raise ValueError("Public history exceeds 512 KiB.")
        value: Any = read_document(target, MAXIMUM_PUBLIC_BYTES)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as error:
        raise ValueError("Public history is invalid JSON.") from error
    fields = {
        "schemaVersion",
        "dataset",
        "generatedAt",
        "detailRetentionDays",
        "summaryRetentionDays",
        "signals",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Public history does not match schema version 1.")
    detail_days = value.get("detailRetentionDays")
    summary_days = value.get("summaryRetentionDays")
    signals = value.get("signals")
    if (
        value.get("schemaVersion") != 1
        or value.get("dataset") != "history"
        or _timestamp(value.get("generatedAt")) is None
        or type(detail_days) is not int
        or not 7 <= detail_days <= 90
        or type(summary_days) is not int
        or not 30 <= summary_days <= 3_650
        or summary_days < detail_days
        or not isinstance(signals, list)
        or len(signals) > MAXIMUM_SUMMARY_SIGNALS
        or not all(_valid_public_signal(signal) for signal in signals)
        or len({signal["id"] for signal in signals}) != len(signals)
    ):
        raise ValueError("Public history does not match schema version 1.")
    return cast(PublicHistory, value)


def previous_statuses(path: str | Path) -> dict[str, SignalStatus]:
    history = read_public_history(path)
    if history is None:
        return {}
    return {signal["id"]: signal["latestStatus"] for signal in history["signals"]}


def _stable_artifact_view(value: object) -> object:
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key != "generatedAt"}


def _write_public_if_changed(path: Path, payload: PublicHistory) -> None:
    try:
        existing: object = read_document(path, MAXIMUM_PUBLIC_BYTES)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing = None
    if _stable_artifact_view(existing) == _stable_artifact_view(payload):
        return
    write_document(path, dict(payload), MAXIMUM_PUBLIC_BYTES, _atomic_write)


def update_history(
    *,
    root: str | Path,
    output: str | Path,
    events: list[HistoryEvent],
    now: datetime,
    registry: BrandRegistry,
    is_suppressed: Callable[[str, str], bool],
    detail_days: int = 30,
    summary_days: int = 730,
    maximum_signals: int = 5_000,
) -> Path:
    archive_root = _bounded_path(root, "RADAR_HISTORY_ROOT")
    public_path = _bounded_path(output, "RADAR_HISTORY_OUTPUT")
    append_history_events(root, events)
    compacted = compact_history(root, now, detail_days, summary_days)
    detailed_events = [event for path in _daily_files(archive_root) for event in read_event_file(path)]
    combined = _merge_events(compacted["signals"], detailed_events)
    public_signals: list[PublicHistorySignal] = []
    for signal in combined:
        normalized = normalize_domain(signal["domain"].replace("[.]", "."))
        match = score_domain(normalized, registry) if normalized else None
        matched_brands = domain_match_brands(normalized, registry) if normalized else frozenset()
        typed_off_domain_evidence = bool(
            {"brand-title-match", "provider-verdict", "hecavex-public-export"}.intersection(
                signal["reasonCodes"]
            )
        )
        if (
            normalized is None
            or is_suppressed_domain(normalized, registry)
            or len(matched_brands) > 1
            or is_brand_collision(normalized, signal["brand"], registry)
            or resolve_brand_name(signal["brand"], registry) != signal["brand"]
            or (match is not None and match.brand != signal["brand"])
            or (match is None and not typed_off_domain_evidence)
            or is_suppressed(signal["domain"], signal["brand"])
        ):
            continue
        public_signals.append(
            {
                "id": signal["id"],
                "domain": signal["domain"],
                "brand": signal["brand"],
                "firstSeen": signal["firstSeen"],
                "lastSeen": signal["lastSeen"],
                "observationCount": signal["observationCount"],
                "sources": signal["sources"],
                "latestStatus": signal["latestStatus"],
                "reasonCodes": signal["reasonCodes"],
                "statusTransitions": signal["statusTransitions"],
            }
        )
        if len(public_signals) > maximum_signals:
            raise ValueError("Eligible public history exceeds its configured row limit. No rows were silently omitted.")
    now_text = now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    payload: PublicHistory = {
        "schemaVersion": 1,
        "dataset": "history",
        "generatedAt": now_text,
        "detailRetentionDays": detail_days,
        "summaryRetentionDays": summary_days,
        "signals": public_signals,
    }
    _write_public_if_changed(public_path, payload)
    return public_path
