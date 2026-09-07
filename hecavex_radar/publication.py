"""Bounded machine-readable publication, health, and relationship artifacts."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import tldextract
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from . import __version__
from .brands import load_brand_registry
from .daily_trends import build_daily_trends_from_repository
from .event_feeds import (
    MAXIMUM_EVENT_JSON_BYTES,
    MAXIMUM_SYNDICATION_BYTES,
    build_brand_event_feeds,
    build_event_feeds,
    read_recent_history_events,
)
from .models import RadarSignal, RadarSource, SignalDetail
from .public_schemas import (
    BRAND_FEEDS_SCHEMA,
    CHANGES_SCHEMA,
    DAILY_TRENDS_SCHEMA,
    EVENTS_SCHEMA,
    JSON_FEED_SCHEMA,
    MANIFEST_SCHEMA,
    MISP_EVENT_SCHEMA,
    MISP_MANIFEST_SCHEMA,
    MISP_WARNINGLIST_SCHEMA,
    PIPELINE_HEALTH_SCHEMA,
    PUBLIC_SCHEMAS,
    QUALITY_METRICS_SCHEMA,
    RADAR_INDEX_SCHEMA,
    RADAR_SCHEMA,
    RADAR_SHARD_SCHEMA,
    RELATED_SCHEMA,
    SCHEMA_BASE,
)
from .quality_metrics import build_quality_metrics
from .safety import refang
from .sharing import MISP_EVENT_UUID, build_misp_feed, build_official_domain_warninglist

MAXIMUM_DASHBOARD_BYTES = 512 * 1024
MAXIMUM_SHARD_BYTES = 256 * 1024
MAXIMUM_RELATION_BYTES = 512 * 1024
MAXIMUM_RELATION_EDGES = 2_000
MAXIMUM_EVIDENCE_FANOUT = 12
MAXIMUM_AGGREGATE_BYTES = 128 * 1024
MAXIMUM_BRAND_FEED_DIRECTORY_BYTES = 256 * 1024
MAXIMUM_QUALITY_BYTES = 256 * 1024
MAXIMUM_TRENDS_BYTES = 512 * 1024
MAXIMUM_MISP_BYTES = 2 * 1024 * 1024
MAXIMUM_WARNINGLIST_BYTES = 512 * 1024
PUBLIC_DATA = Path("public/data")
CHECKSUM_SUFFIX = ".sha256"
RELATION_WINDOW = timedelta(days=7)
STRONG_EVIDENCE = frozenset({"primary-html-sha256", "certificate-sha256"})
SUPPORTING_EVIDENCE = frozenset(
    {
        "certificate-san",
        "redirect-domain",
        "ip-address",
        "asn",
        "dns-a",
        "dns-aaaa",
        "dns-cname",
        "dns-ns",
        "dns-mx",
    }
)
SUPPORTING_FAMILY = {
    "certificate-san": "certificate-name",
    "redirect-domain": "navigation",
    "ip-address": "network-location",
    "asn": "network-location",
    "dns-a": "network-location",
    "dns-aaaa": "network-location",
    "dns-cname": "dns-alias",
    "dns-ns": "dns-authority",
    "dns-mx": "mail-routing",
}
RELATION_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(),
    cache_dir=None,
    include_psl_private_domains=True,
)


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if _utc_timestamp(parsed) == value else None


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    return (json.dumps(value, ensure_ascii=False, indent=indent, separators=separators) + "\n").encode("utf-8")


def _atomic_bytes(target: Path, body: bytes, maximum: int) -> Path:
    repository = Path.cwd().resolve()
    resolved = target.resolve()
    public_data = (repository / PUBLIC_DATA).resolve()
    if not resolved.is_relative_to(public_data):
        raise ValueError("Public publication artifacts must stay below public/data/.")
    if not body or len(body) > maximum:
        raise ValueError(f"Refusing to publish {resolved.name} outside its {maximum}-byte boundary.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, resolved)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return resolved


def _write_json(target: Path, value: object, maximum: int, *, pretty: bool = False) -> Path:
    return _atomic_bytes(target, _json_bytes(value, pretty=pretty), maximum)


def _schema_errors(instance: object, schema: Mapping[str, object]) -> list[str]:
    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            validator.iter_errors(instance),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    ]


def _validate(instance: object, schema: Mapping[str, object], label: str) -> None:
    errors = _schema_errors(instance, schema)
    if errors:
        raise ValueError(f"{label} failed JSON Schema validation: {'; '.join(errors[:8])}")


def _stix_validation_diagnostics(result: object) -> list[str]:
    diagnostics: list[str] = []
    fatal = cast(object | None, getattr(result, "fatal", None))
    if fatal is not None:
        diagnostics.append(str(fatal))
    object_results = cast(Sequence[object], getattr(result, "object_results", ()))
    for object_result in object_results:
        errors = cast(Sequence[object], getattr(object_result, "errors", ()))
        diagnostics.extend(str(error) for error in errors)
    return diagnostics


def write_schema_documents() -> list[Path]:
    target_root = PUBLIC_DATA / "schemas"
    paths: list[Path] = []
    for name, schema in sorted(PUBLIC_SCHEMAS.items()):
        Draft202012Validator.check_schema(schema)
        paths.append(_write_json(target_root / name, schema, 128 * 1024, pretty=True))
    return paths


def _copy_sources_for(signals: Sequence[RadarSignal], sources: Sequence[RadarSource]) -> list[RadarSource]:
    copied: list[RadarSource] = []
    for source in sources:
        name = source["name"]
        represented = sum(name in signal["sources"] for signal in signals)
        copied.append(cast(RadarSource, {**source, "records": represented}))
    return copied


def apply_source_counts(signals: Sequence[RadarSignal], sources: list[RadarSource]) -> None:
    """Mutate the snapshot source rows to describe only represented dashboard rows."""

    for source in sources:
        source["records"] = sum(source["name"] in signal["sources"] for signal in signals)


def _budget_candidate(
    signals: Sequence[RadarSignal],
    sources: Sequence[RadarSource],
    generated_at: str,
) -> dict[str, object]:
    # Reserve the optional detailAvailable field for every row. The real
    # snapshot can only be smaller, so a later enrichment cannot cross the cap.
    reserved_signals = [cast(RadarSignal, {**signal, "detailAvailable": True}) for signal in signals]
    return {
        "schemaVersion": 2,
        "dataset": "live",
        "generatedAt": generated_at,
        "lastSuccessfulSyncAt": generated_at,
        "signals": reserved_signals,
        "sources": _copy_sources_for(reserved_signals, sources),
    }


def fit_dashboard_signals(
    signals: list[RadarSignal],
    sources: Sequence[RadarSource],
    generated_at: str,
    maximum_bytes: int = MAXIMUM_DASHBOARD_BYTES,
) -> list[RadarSignal]:
    """Select the longest newest-first prefix that is proven to fit the snapshot cap."""

    if not signals:
        return []
    low = 0
    high = len(signals)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = _budget_candidate(signals[:middle], sources, generated_at)
        if len(_json_bytes(candidate, pretty=True)) <= maximum_bytes:
            low = middle
        else:
            high = middle - 1
    if low == 0:
        raise RuntimeError("Snapshot metadata and one bounded signal do not fit the dashboard byte budget.")
    return signals[:low]


def _partition_shards(signals: Sequence[RadarSignal], generated_at: str) -> list[dict[str, object]]:
    shards: list[dict[str, object]] = []
    current: list[RadarSignal] = []
    for signal in signals:
        candidate_signals = [*current, signal]
        candidate = {
            "schemaVersion": 1,
            "dataset": "radar-signal-shard",
            "generatedAt": generated_at,
            "shard": len(shards) + 1,
            "signals": candidate_signals,
        }
        if current and len(_json_bytes(candidate)) > MAXIMUM_SHARD_BYTES:
            shard = {
                "schemaVersion": 1,
                "dataset": "radar-signal-shard",
                "generatedAt": generated_at,
                "shard": len(shards) + 1,
                "signals": current,
            }
            shards.append(shard)
            current = [signal]
        else:
            current = candidate_signals
    if current:
        shards.append(
            {
                "schemaVersion": 1,
                "dataset": "radar-signal-shard",
                "generatedAt": generated_at,
                "shard": len(shards) + 1,
                "signals": current,
            }
        )
    for shard in shards:
        if len(_json_bytes(shard)) > MAXIMUM_SHARD_BYTES:
            raise RuntimeError("One normalized signal exceeds the signal-shard byte budget.")
    return shards


def write_signal_shards(
    signals: Sequence[RadarSignal],
    dashboard_signal_count: int,
    generated_at: str,
) -> tuple[Path, dict[str, object]]:
    shard_root = PUBLIC_DATA / "radar-shards"
    shard_root.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()
    shard_rows: list[dict[str, object]] = []
    for shard in _partition_shards(signals, generated_at):
        number = cast(int, shard["shard"])
        raw_signals = cast(list[RadarSignal], shard["signals"])
        body = _json_bytes(shard)
        _validate(shard, RADAR_SHARD_SCHEMA, f"signal shard {number}")
        target = shard_root / f"{number:04d}.json"
        _atomic_bytes(target, body, MAXIMUM_SHARD_BYTES)
        expected.add(target.resolve())
        shard_rows.append(
            {
                "number": number,
                "path": f"/data/radar-shards/{number:04d}.json",
                "signals": len(raw_signals),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "firstSignalId": raw_signals[0]["id"],
                "lastSignalId": raw_signals[-1]["id"],
            }
        )
    for path in shard_root.glob("[0-9][0-9][0-9][0-9].json"):
        if path.resolve() not in expected:
            path.unlink()
    index: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-signal-index",
        "generatedAt": generated_at,
        "signalCount": len(signals),
        "dashboardSignalCount": dashboard_signal_count,
        "shards": shard_rows,
    }
    _validate(index, RADAR_INDEX_SCHEMA, "signal shard index")
    return _write_json(PUBLIC_DATA / "radar.index.json", index, 256 * 1024, pretty=True), index


def _read_json(path: Path, maximum: int) -> object | None:
    try:
        if path.stat().st_size > maximum:
            return None
        return cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_ndjson(path: Path, maximum_bytes: int, maximum_rows: int) -> list[dict[str, object]]:
    try:
        if path.stat().st_size > maximum_bytes:
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return []
    rows: list[dict[str, object]] = []
    for line in lines[:maximum_rows]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(cast(dict[str, object], value))
    return rows


def _recent_archive_rows(root: Path, filename: str, start: datetime, end: datetime) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for directory in sorted(root.glob("????-??-??")):
        try:
            day = datetime.strptime(directory.name, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if day > end + timedelta(days=1) or day < start - timedelta(days=1):
            continue
        rows.extend(_read_ndjson(directory / filename, 25 * 1024 * 1024, 25_000))
    return rows


def _rows_in_window(
    rows: Iterable[dict[str, object]],
    fields: Sequence[str],
    start: datetime,
    end: datetime,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for row in rows:
        timestamps = (_parse_timestamp(row.get(field)) for field in fields)
        observed = next((timestamp for timestamp in timestamps if timestamp is not None), None)
        if observed is not None and start <= observed <= end:
            selected.append(row)
    return selected


def _counter(rows: Iterable[dict[str, object]], field: str) -> int:
    total = 0
    for row in rows:
        value = row.get(field)
        if type(value) is int:
            total += value
    return total


def _numeric_total(rows: Iterable[dict[str, object]], field: str) -> float:
    total = 0.0
    for row in rows:
        value = row.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
    return total


def _event_rows(repository: Path, start: datetime, end: datetime) -> list[dict[str, object]]:
    rows = _recent_archive_rows(repository / "data/history/daily", "events.ndjson", start, end)
    return _rows_in_window(rows, ("observedAt",), start, end)


def _aggregate(values: Iterable[object], maximum: int = 32) -> dict[str, int]:
    counts = Counter(value for value in values if isinstance(value, str) and value)
    return dict(sorted(counts.most_common(maximum), key=lambda item: (-item[1], item[0])))


def _flatten_list_field(rows: Iterable[dict[str, object]], field: str) -> Iterable[object]:
    for row in rows:
        value = row.get(field)
        if isinstance(value, list):
            yield from value


def build_change_aggregate(repository: Path, generated_at: str) -> dict[str, object]:
    end = _parse_timestamp(generated_at)
    if end is None:
        raise ValueError("Change aggregate requires a canonical generatedAt timestamp.")
    windows: list[dict[str, object]] = []
    for hours in (24, 168):
        start = end - timedelta(hours=hours)
        events = _event_rows(repository, start, end)
        observations = [row for row in events if row.get("eventType") == "observation"]
        transitions = [row for row in events if row.get("eventType") == "status-transition"]
        first_publications = [
            row
            for row in transitions
            if row.get("previousStatus") is None
            and isinstance(row.get("reasonCodes"), list)
            and "first-publication" in cast(list[object], row["reasonCodes"])
        ]
        actual_changes = [row for row in transitions if row.get("previousStatus") is not None]
        unique_observed = {row.get("signalId") for row in observations if isinstance(row.get("signalId"), str)}
        windows.append(
            {
                "hours": hours,
                "from": _utc_timestamp(start),
                "to": generated_at,
                "events": len(events),
                "uniqueSignals": len({row.get("signalId") for row in events if isinstance(row.get("signalId"), str)}),
                "firstPublications": len(first_publications),
                "statusChanges": len(actual_changes),
                "observations": len(observations),
                "reobservations": max(0, len(observations) - len(unique_observed)),
                "bySource": _aggregate(_flatten_list_field(events, "sources")),
                "byStatus": _aggregate(row.get("status") for row in events),
                "byReason": _aggregate(_flatten_list_field(events, "reasonCodes")),
                "byBrand": _aggregate((row.get("brand") for row in events), maximum=64),
            }
        )
    artifact: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-change-aggregate",
        "generatedAt": generated_at,
        "privacy": "Aggregate counters only; signal-level history remains in history.json.",
        "windows": windows,
    }
    _validate(artifact, CHANGES_SCHEMA, "change aggregate")
    return artifact


def _urlscan_enrichment(rows: Sequence[dict[str, object]]) -> dict[str, int]:
    sections = Counter[str]()
    signal_ids: set[str] = set()
    for row in rows:
        signal_id = row.get("signalId")
        if isinstance(signal_id, str):
            signal_ids.add(signal_id)
        observation = row.get("observation")
        if not isinstance(observation, dict):
            continue
        for key in ("page", "network", "assessment", "certificate", "dns", "rdap"):
            if observation.get(key) is not None:
                sections[key] += 1
    return {
        "observations": len(rows),
        "uniqueSignals": len(signal_ids),
        "page": sections["page"],
        "network": sections["network"],
        "assessment": sections["assessment"],
        "certificate": sections["certificate"],
        "dns": sections["dns"],
        "rdap": sections["rdap"],
    }


def _canonical_public_timestamp(value: object) -> str | None:
    parsed = _parse_timestamp(value)
    if parsed is None or not isinstance(value, str) or _utc_timestamp(parsed) != value:
        return None
    return value


def _public_certstream_summary(value: object) -> dict[str, object] | None:
    """Return only aggregate, fixed-field CertStream health for the public roll-up."""

    if not isinstance(value, dict):
        return None
    generated_at = _canonical_public_timestamp(value.get("generatedAt"))
    if generated_at is None:
        return None
    last_success_raw = value.get("lastSuccessAt")
    last_success = None if last_success_raw is None else _canonical_public_timestamp(last_success_raw)
    if last_success_raw is not None and last_success is None:
        return None
    freshness_raw = value.get("freshness")
    if not isinstance(freshness_raw, dict) or freshness_raw.get("status") not in {"current", "stale", "unavailable"}:
        return None
    reference_raw = freshness_raw.get("referenceAt")
    reference = None if reference_raw is None else _canonical_public_timestamp(reference_raw)
    age_seconds = freshness_raw.get("ageSeconds")
    if reference_raw is None:
        if freshness_raw["status"] != "unavailable" or age_seconds is not None or last_success is not None:
            return None
    elif (
        reference is None
        or reference != last_success
        or freshness_raw["status"] == "unavailable"
        or not isinstance(age_seconds, (int, float))
        or isinstance(age_seconds, bool)
        or not 0 <= float(age_seconds) <= 31_536_000
    ):
        return None
    freshness: dict[str, object] = {
        "status": freshness_raw["status"],
        "referenceAt": reference,
        "ageSeconds": age_seconds,
    }
    latest_raw = value.get("latestAttempt")
    latest: dict[str, object] | None = None
    if latest_raw is not None:
        if not isinstance(latest_raw, dict):
            return None
        started_at = _canonical_public_timestamp(latest_raw.get("startedAt"))
        ended_at = _canonical_public_timestamp(latest_raw.get("endedAt"))
        started_time = _parse_timestamp(started_at)
        ended_time = _parse_timestamp(ended_at)
        generated_time = _parse_timestamp(generated_at)
        outcome = latest_raw.get("outcome")
        listening = latest_raw.get("listeningSeconds")
        counters = {field: latest_raw.get(field) for field in ("messages", "dnsNames", "matches", "newRecords")}
        if (
            started_at is None
            or ended_at is None
            or started_time is None
            or ended_time is None
            or generated_time is None
            or started_time > ended_time
            or ended_time > generated_time
            or outcome not in {"healthy-empty", "healthy-matches", "no-input", "partial", "failed"}
            or not isinstance(listening, (int, float))
            or isinstance(listening, bool)
            or not 0 <= float(listening) <= 86_400
            or any(type(counter) is not int or not 0 <= counter <= 2_000_000_000 for counter in counters.values())
        ):
            return None
        latest = {
            "startedAt": started_at,
            "endedAt": ended_at,
            "outcome": outcome,
            "listeningSeconds": listening,
            **counters,
        }
    if latest is None and last_success is not None:
        return None
    return {
        "generatedAt": generated_at,
        "lastSuccessAt": last_success,
        "freshness": freshness,
        "latestAttempt": latest,
    }


def _public_urlscan_summary(value: object) -> dict[str, object] | None:
    """Return one strict credential-free URLScan run summary."""

    if not isinstance(value, dict):
        return None
    generated_at = _canonical_public_timestamp(value.get("generatedAt"))
    last_attempt_at = _canonical_public_timestamp(value.get("lastRunAt"))
    generated_time = _parse_timestamp(generated_at)
    last_attempt_time = _parse_timestamp(last_attempt_at)
    configured = value.get("configured")
    outcome = value.get("lastOutcome")
    failure_code = value.get("lastFailureCode")
    raw_coverage = value.get("checkpointCoverage")
    if raw_coverage is None:
        raw_coverage = {
            "queries": 0,
            "complete": 0,
            "partial": 0,
            "backlog": 0,
            "oldestBacklogProgressAt": None,
        }
    if (
        generated_at is None
        or last_attempt_at is None
        or generated_time is None
        or last_attempt_time is None
        or last_attempt_time > generated_time
        or not isinstance(configured, bool)
        or outcome not in {"skipped-not-configured", "completed", "budget-limited", "failed"}
        or not isinstance(raw_coverage, dict)
        or set(raw_coverage) != {"queries", "complete", "partial", "backlog", "oldestBacklogProgressAt"}
    ):
        return None
    counts = [raw_coverage.get(field) for field in ("queries", "complete", "partial", "backlog")]
    oldest = raw_coverage.get("oldestBacklogProgressAt")
    if (
        not all(type(item) is int and 0 <= item <= 256 for item in counts)
        or raw_coverage["complete"] + raw_coverage["partial"] != raw_coverage["queries"]
        or raw_coverage["backlog"] > raw_coverage["partial"]
        or (raw_coverage["backlog"] == 0) != (oldest is None)
        or (oldest is not None and _canonical_public_timestamp(oldest) is None)
    ):
        return None
    summary = {
        "generatedAt": generated_at, "configured": configured, "lastOutcome": outcome,
        "lastAttemptAt": last_attempt_at, "checkpointCoverage": dict(raw_coverage),
    }
    if failure_code in {"unknown", "state-capacity", "state-invalid", "provider-rate-limit", "provider-error"}:
        summary["lastFailureCode"] = failure_code
    return summary


def build_pipeline_health(
    repository: Path,
    snapshot: Mapping[str, object],
    generated_at: str,
) -> dict[str, object]:
    end = _parse_timestamp(generated_at)
    if end is None:
        raise ValueError("Pipeline health requires a canonical generatedAt timestamp.")
    cert_rows = _recent_archive_rows(repository / "data/certstream", "attempts.ndjson", end - timedelta(days=8), end)
    urlscan_rows = _recent_archive_rows(
        repository / "data/urlscan", "intelligence.ndjson", end - timedelta(days=8), end
    )
    latest_cert = _read_json(repository / "public/data/collection-health.json", 32 * 1024)
    latest_urlscan = _read_json(repository / "data/urlscan/hunt-state.json", 32 * 1024)
    latest_ct_search = _read_json(repository / "data/ct-search/state.json", 128 * 1024)
    latest_domain_context = _read_json(repository / "data/enrichment/domain-context.json", 4 * 1024 * 1024)
    expected_interval = 900
    expected_listening = 240
    if isinstance(latest_cert, dict):
        configured_interval = latest_cert.get("expectedIntervalSeconds")
        if type(configured_interval) is int and 60 <= configured_interval <= 86_400:
            expected_interval = configured_interval
        latest_attempt = latest_cert.get("latestAttempt")
        if isinstance(latest_attempt, dict):
            configured_listening = latest_attempt.get("expectedListeningSeconds")
            if type(configured_listening) is int and 0 <= configured_listening <= 86_400:
                expected_listening = configured_listening
    raw_sources = snapshot.get("sources")
    sources = cast(list[dict[str, object]], raw_sources) if isinstance(raw_sources, list) else []
    raw_signals = snapshot.get("signals")
    signals = cast(list[dict[str, object]], raw_signals) if isinstance(raw_signals, list) else []
    windows: list[dict[str, object]] = []
    for hours in (24, 168):
        start = end - timedelta(hours=hours)
        attempts = _rows_in_window(cert_rows, ("endedAt", "collectorStartedAt"), start, end)
        # Archive intelligence timestamps live in the nested observation object.
        enrichments: list[dict[str, object]] = []
        for row in urlscan_rows:
            observation = row.get("observation")
            observed = _parse_timestamp(observation.get("observedAt")) if isinstance(observation, dict) else None
            if observed is not None and start <= observed <= end:
                enrichments.append(row)
        events = _event_rows(repository, start, end)
        first_publications = sum(
            row.get("eventType") == "status-transition"
            and row.get("previousStatus") is None
            and isinstance(row.get("reasonCodes"), list)
            and "first-publication" in cast(list[object], row["reasonCodes"])
            for row in events
        )
        window_seconds = hours * 3_600
        expected_slots = max(1, window_seconds // expected_interval)
        healthy_attempts = sum(row.get("outcome") in {"healthy-empty", "healthy-matches"} for row in attempts)
        # Multiple manual or retried attempts can overlap the same wall-clock
        # period. Keep the raw attempt count, but cap time-based coverage at the
        # window boundary so it remains a coverage measure rather than summed
        # worker time.
        listening_seconds = round(min(_numeric_total(attempts, "listeningSeconds"), window_seconds), 3)
        windows.append(
            {
                "hours": hours,
                "from": _utc_timestamp(start),
                "to": generated_at,
                "collection": {
                    "scheduledSlots": expected_slots,
                    "recordedAttempts": len(attempts),
                    "healthyAttempts": healthy_attempts,
                    "recordedSchedulePercent": min(100.0, round(100 * len(attempts) / expected_slots, 1)),
                    "listeningCoveragePercent": min(
                        100.0,
                        round(100 * listening_seconds / window_seconds, 2),
                    ),
                    "scheduledListeningCeilingPercent": min(
                        100.0,
                        round(100 * expected_slots * expected_listening / window_seconds, 2),
                    ),
                    "expectedListeningSeconds": _counter(attempts, "expectedListeningSeconds"),
                    "listeningSeconds": listening_seconds,
                    "messages": _counter(attempts, "messages"),
                    "dnsNames": _counter(attempts, "dnsNames"),
                    "outcomes": _aggregate(row.get("outcome") for row in attempts),
                },
                "screening": {
                    "matches": _counter(attempts, "matches"),
                    "newArchiveRecords": _counter(attempts, "newRecords"),
                    "firstPublications": first_publications,
                    "bySource": _aggregate(_flatten_list_field(events, "sources")),
                },
                "enrichment": _urlscan_enrichment(enrichments),
                "publication": {
                    "events": len(events),
                    "observations": sum(row.get("eventType") == "observation" for row in events),
                    "statusTransitions": sum(row.get("eventType") == "status-transition" for row in events),
                    "uniqueSignals": len(
                        {row.get("signalId") for row in events if isinstance(row.get("signalId"), str)}
                    ),
                },
            }
        )
    artifact: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-pipeline-health",
        "generatedAt": generated_at,
        "privacy": "Aggregate counters only; no candidate names or detector payloads.",
        "current": {
            "publishedSignals": len(signals),
            "sourceStates": {str(source.get("name")): source.get("state") for source in sources},
            "sourceRecords": {
                str(source.get("name")): source.get("records")
                for source in sources
                if type(source.get("records")) is int
            },
            "certstream": _public_certstream_summary(latest_cert),
            "urlscan": _public_urlscan_summary(latest_urlscan),
            "ctSearch": _public_state_summary(
                latest_ct_search,
                (
                    "queriesAttempted",
                    "queriesCompleted",
                    "queriesBacklogged",
                    "rowsProcessed",
                    "dnsNames",
                    "matches",
                    "newRecords",
                ),
                allowed_outcomes=frozenset({"completed", "partial", "failed", "deferred-backoff"}),
                failure_codes=True,
            ),
            "domainContext": _public_state_summary(
                latest_domain_context,
                ("attempted", "completed"),
                record_count=True,
            ),
        },
        "windows": windows,
    }
    _validate(artifact, PIPELINE_HEALTH_SCHEMA, "pipeline health")
    return artifact


def _public_state_summary(
    state: object,
    counters: Sequence[str],
    *,
    record_count: bool = False,
    failure_codes: bool = False,
    allowed_outcomes: frozenset[str] = frozenset({"completed", "partial", "failed", "empty"}),
) -> dict[str, object] | None:
    """Expose only bounded operational counters from a private collector state."""

    if not isinstance(state, dict):
        return None
    generated_at = _canonical_public_timestamp(state.get("generatedAt"))
    latest = state.get("latestRun")
    if generated_at is None or not isinstance(latest, dict):
        return None
    started_at = _canonical_public_timestamp(latest.get("startedAt"))
    ended_at = _canonical_public_timestamp(latest.get("endedAt"))
    generated_time = _parse_timestamp(generated_at)
    started_time = _parse_timestamp(started_at)
    ended_time = _parse_timestamp(ended_at)
    outcome = latest.get("outcome")
    if (
        generated_time is None
        or started_time is None
        or ended_time is None
        or not isinstance(outcome, str)
        or outcome not in allowed_outcomes
        or started_time > ended_time
        or ended_time > generated_time
    ):
        return None
    run: dict[str, object] = {
        "startedAt": started_at,
        "endedAt": ended_at,
        "outcome": outcome,
    }
    for field in counters:
        value = latest.get(field)
        if type(value) is not int or not 0 <= value <= 2_000_000_000:
            return None
        run[field] = value
    if failure_codes:
        raw_codes = latest.get("failureCodes", [])
        allowed_codes = {
            "provider-timeout",
            "provider-http",
            "provider-network",
            "invalid-response",
            "validation",
            "internal",
        }
        if (
            not isinstance(raw_codes, list)
            or len(raw_codes) > 8
            or len(raw_codes) != len(set(cast(list[object], raw_codes)))
            or not all(isinstance(code, str) and code in allowed_codes for code in raw_codes)
        ):
            return None
        run["failureCodes"] = list(raw_codes)
    summary: dict[str, object] = {"generatedAt": generated_at, "latestRun": run}
    if record_count:
        records = state.get("records")
        if not isinstance(records, list) or len(records) > 25_000:
            return None
        summary["recordCount"] = len(records)
    provider = state.get("provider")
    if isinstance(provider, str) and provider in {"crt.sh"}:
        summary["provider"] = provider
        from .ct_search import _normalize_state, _valid_state

        normalized = _normalize_state(state)
        if _valid_state(normalized):
            summary["providerHealth"] = cast(dict[str, object], normalized)["providerHealth"]
    return summary


def _detail_evidence(details: Mapping[str, SignalDetail]) -> dict[tuple[str, str], set[str]]:
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for signal_id, detail in details.items():
        for observation in detail.get("observations", []):
            network = observation.get("network")
            if isinstance(network, dict):
                ip_address = network.get("ipAddress")
                asn = network.get("asn")
                if isinstance(ip_address, str) and ip_address:
                    index[("ip-address", ip_address)].add(signal_id)
                if type(asn) is int:
                    index[("asn", str(asn))].add(signal_id)
            assessment = observation.get("assessment")
            if isinstance(assessment, dict):
                redirect = assessment.get("redirectedToDomain")
                if isinstance(redirect, str) and redirect:
                    index[("redirect-domain", redirect)].add(signal_id)
            certificate = observation.get("certificate")
            if isinstance(certificate, dict):
                fingerprints = certificate.get("fingerprints")
                sha256 = fingerprints.get("sha256") if isinstance(fingerprints, dict) else None
                if isinstance(sha256, str) and sha256:
                    index[("certificate-sha256", sha256)].add(signal_id)
                sans = certificate.get("subjectAltNames")
                if isinstance(sans, list):
                    for san in sans:
                        if isinstance(san, str) and san:
                            index[("certificate-san", san)].add(signal_id)
        context = detail.get("domainContext")
        dns = context.get("dns") if isinstance(context, dict) else None
        if isinstance(dns, dict):
            for field, evidence_type in (
                ("a", "dns-a"),
                ("aaaa", "dns-aaaa"),
                ("cname", "dns-cname"),
                ("ns", "dns-ns"),
                ("mx", "dns-mx"),
            ):
                values = dns.get(field)
                if not isinstance(values, list):
                    continue
                for raw in values:
                    if not isinstance(raw, str) or not raw:
                        continue
                    value = raw.partition(" ")[2] if field == "mx" and " " in raw else raw
                    if value:
                        index[(evidence_type, value)].add(signal_id)
    return index


def _relation_registrable_domain(domain: str) -> str:
    """Return a stable eTLD+1 for an already validated defanged domain."""
    raw = refang(domain).casefold()
    extracted = RELATION_EXTRACT(raw)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return raw


def _relation_nodes(
    edges: Sequence[Mapping[str, object]],
    signal_map: Mapping[str, RadarSignal],
) -> list[dict[str, str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        left = cast(str, edge["source"])
        right = cast(str, edge["target"])
        adjacency[left].add(right)
        adjacency[right].add(left)
    cluster_by_signal: dict[str, str] = {}
    unvisited = set(adjacency)
    while unvisited:
        seed = min(unvisited)
        component: set[str] = set()
        pending = [seed]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(sorted(adjacency[current] - component, reverse=True))
        unvisited -= component
        cluster_id = hashlib.sha256("\n".join(sorted(component)).encode()).hexdigest()[:16]
        for signal_id in component:
            cluster_by_signal[signal_id] = cluster_id
    return [
        {"signalId": signal_id, "domain": signal_map[signal_id]["domain"], "clusterId": cluster_id}
        for signal_id, cluster_id in sorted(cluster_by_signal.items())
    ]


def build_related_observations(
    signals: Sequence[RadarSignal],
    details: Mapping[str, SignalDetail],
    generated_at: str,
) -> dict[str, object]:
    signal_map = {signal["id"]: signal for signal in signals}
    evidence = _detail_evidence(details)
    for signal in signals:
        for value in signal.get("hashes", []):
            evidence[("primary-html-sha256", value)].add(signal["id"])

    pair_evidence: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    high_fanout = 0
    temporal_pairs = 0
    for (evidence_type, value), members in sorted(evidence.items()):
        known_members = sorted(member for member in members if member in signal_map)
        if len(known_members) < 2:
            continue
        if len(known_members) > MAXIMUM_EVIDENCE_FANOUT:
            high_fanout += 1
            continue
        for left, right in itertools.combinations(known_members, 2):
            # Root and subdomain observations are different URLs, but they are
            # not independent infrastructure. Publishing their shared
            # certificate, IP, or hash as an association inflates the graph
            # with a relationship already implied by the hostname itself.
            if _relation_registrable_domain(signal_map[left]["domain"]) == _relation_registrable_domain(
                signal_map[right]["domain"]
            ):
                continue
            left_time = _parse_timestamp(signal_map[left]["lastSeen"])
            right_time = _parse_timestamp(signal_map[right]["lastSeen"])
            if left_time is None or right_time is None or abs(left_time - right_time) > RELATION_WINDOW:
                temporal_pairs += 1
                continue
            pair_evidence[(left, right)].append({"type": evidence_type, "value": value})

    candidates: list[dict[str, object]] = []
    for (left, right), values in pair_evidence.items():
        values = sorted(values, key=lambda item: (item["type"], item["value"]))[:8]
        types = {item["type"] for item in values}
        has_strong = bool(types & STRONG_EVIDENCE)
        supporting_types = types & SUPPORTING_EVIDENCE
        supporting_families = {SUPPORTING_FAMILY[evidence_type] for evidence_type in supporting_types}
        if not has_strong and len(supporting_families) < 2:
            continue
        strength = "strong" if has_strong else "corroborated-supporting"
        edge_key = json.dumps([left, right, values], separators=(",", ":"), sort_keys=True)
        candidates.append(
            {
                "id": hashlib.sha256(edge_key.encode()).hexdigest()[:20],
                "source": left,
                "target": right,
                "strength": strength,
                "evidence": values,
            }
        )
    candidates.sort(
        key=lambda edge: (
            0 if edge["strength"] == "strong" else 1,
            -len(cast(list[object], edge["evidence"])),
            str(edge["source"]),
            str(edge["target"]),
        )
    )
    edge_limit = max(0, len(candidates) - MAXIMUM_RELATION_EDGES)
    edges = candidates[:MAXIMUM_RELATION_EDGES]

    nodes = _relation_nodes(edges, signal_map)
    artifact: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-related-observations",
        "generatedAt": generated_at,
        "semantics": (
            "Shared evidence is a bounded association between public observations. It is not campaign, operator, "
            "malware, infrastructure ownership, or threat-actor attribution."
        ),
        "nodes": nodes,
        "edges": edges,
        "suppressedEvidence": {
            "highFanoutValues": high_fanout,
            "temporalPairs": temporal_pairs,
            "edgeLimit": edge_limit,
        },
    }
    _validate(artifact, RELATED_SCHEMA, "related observations")
    body = _json_bytes(artifact, pretty=True)
    if len(body) > MAXIMUM_RELATION_BYTES:
        # Deterministically reduce the edge budget and recompute connected
        # components from only the retained edges. A cluster must never imply a
        # path through an edge that was removed to satisfy the byte boundary.
        while edges and len(body) > MAXIMUM_RELATION_BYTES:
            edges = edges[: max(0, len(edges) - max(1, len(edges) // 10))]
            edge_limit = len(candidates) - len(edges)
            artifact["edges"] = edges
            artifact["nodes"] = _relation_nodes(edges, signal_map)
            artifact["suppressedEvidence"] = {
                "highFanoutValues": high_fanout,
                "temporalPairs": temporal_pairs,
                "edgeLimit": edge_limit,
            }
            body = _json_bytes(artifact, pretty=True)
    _validate(artifact, RELATED_SCHEMA, "related observations")
    if len(body) > MAXIMUM_RELATION_BYTES:
        raise RuntimeError("Related-observation metadata cannot fit the public byte budget.")
    return artifact


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksum(path: Path) -> Path:
    digest = _sha256(path)
    body = f"{digest}  {path.name}\n".encode("ascii")
    return _atomic_bytes(path.with_name(path.name + CHECKSUM_SUFFIX), body, 256)


def _git_revision(repository: Path) -> str | None:
    executable = shutil.which("git")
    if executable is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - executable is resolved with shutil.which.
            [executable, "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip().lower()
    return revision if len(revision) == 40 and all(character in "0123456789abcdef" for character in revision) else None


def write_feed_manifest(
    repository: Path,
    snapshot: Mapping[str, object],
    complete_signal_count: int,
    artifact_schemas: Mapping[Path, str | None],
) -> Path:
    generated_at = snapshot.get("lastSuccessfulSyncAt")
    if not isinstance(generated_at, str) or _parse_timestamp(generated_at) is None:
        raise ValueError("Feed manifest requires a canonical successful-sync timestamp.")
    source_fetched_at: dict[str, str | None] = {}
    raw_sources = snapshot.get("sources")
    if isinstance(raw_sources, list):
        for raw_source in raw_sources:
            if isinstance(raw_source, dict) and isinstance(raw_source.get("name"), str):
                fetched = raw_source.get("fetchedAt")
                source_fetched_at[cast(str, raw_source["name"])] = fetched if isinstance(fetched, str) else None
    artifact_rows: list[dict[str, object]] = []
    for relative, schema in sorted(artifact_schemas.items(), key=lambda item: item[0].as_posix()):
        path = (repository / relative).resolve()
        if not path.is_file() or not path.is_relative_to((repository / PUBLIC_DATA).resolve()):
            continue
        if path.name.endswith(".stix.json"):
            media_type = "application/stix+json"
        elif path.name.endswith(".feed.json"):
            media_type = "application/feed+json"
        elif path.name.endswith(".atom.xml"):
            media_type = "application/atom+xml"
        elif path.name.endswith(".rss.xml"):
            media_type = "application/rss+xml"
        else:
            media_type = "application/json"
        artifact_rows.append(
            {
                "path": "/" + relative.relative_to("public").as_posix(),
                "mediaType": media_type,
                "schema": schema,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    raw_signals = snapshot.get("signals")
    dashboard_count = len(raw_signals) if isinstance(raw_signals, list) else 0
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-feed-manifest",
        "generatedAt": generated_at,
        "generator": {"name": "hecavex-radar", "version": __version__, "revision": _git_revision(repository)},
        "sourceFetchedAt": dict(sorted(source_fetched_at.items())),
        "counts": {
            "completeSignals": complete_signal_count,
            "dashboardSignals": dashboard_count,
            "dashboardOmitted": max(0, complete_signal_count - dashboard_count),
            "artifacts": len(artifact_rows),
        },
        "artifacts": artifact_rows,
    }
    _validate(manifest, MANIFEST_SCHEMA, "feed manifest")
    target = _write_json(PUBLIC_DATA / "feed-manifest.json", manifest, 256 * 1024, pretty=True)
    write_checksum(target)
    return target


def publish_supplemental_artifacts(
    snapshot: Mapping[str, object],
    complete_signals: Sequence[RadarSignal],
    details: Mapping[str, SignalDetail],
    *,
    history: Mapping[str, object] | None = None,
    review_export: Mapping[str, object] | None = None,
    misp_enabled: bool = False,
) -> list[Path]:
    repository = Path.cwd().resolve()
    generated_at = snapshot.get("lastSuccessfulSyncAt")
    if not isinstance(generated_at, str):
        raise ValueError("Supplemental publication requires lastSuccessfulSyncAt.")
    dashboard_signals = snapshot.get("signals")
    if not isinstance(dashboard_signals, list):
        raise ValueError("Supplemental publication requires snapshot signals.")
    _validate(snapshot, RADAR_SCHEMA, "live snapshot")
    schema_paths = write_schema_documents()
    index_path, _ = write_signal_shards(complete_signals, len(dashboard_signals), generated_at)
    changes = build_change_aggregate(repository, generated_at)
    changes_path = _write_json(PUBLIC_DATA / "changes.json", changes, MAXIMUM_AGGREGATE_BYTES, pretty=True)
    health = build_pipeline_health(repository, snapshot, generated_at)
    health_path = _write_json(PUBLIC_DATA / "pipeline-health.json", health, MAXIMUM_AGGREGATE_BYTES, pretty=True)
    relations = build_related_observations(cast(list[RadarSignal], dashboard_signals), details, generated_at)
    relations_path = _write_json(
        PUBLIC_DATA / "related-observations.json",
        relations,
        MAXIMUM_RELATION_BYTES,
        pretty=True,
    )

    effective_history = history
    if effective_history is None:
        from .history import read_public_history
        loaded_history = read_public_history(repository / PUBLIC_DATA / "history.json")
        effective_history = cast(Mapping[str, object], loaded_history) if isinstance(loaded_history, dict) else {
            "signals": list(complete_signals)
        }
    effective_review: Mapping[str, object] = review_export or {
        "schemaVersion": 3,
        "dataset": "radar-review-decisions",
        "generatedAt": generated_at,
        "suppressions": [],
        "candidates": [],
        "assessments": [],
    }

    history_signals = effective_history.get("signals")
    if not isinstance(history_signals, list) or len(history_signals) > 25_000:
        raise ValueError("Supplemental publication requires bounded public history signals.")
    route_signals = [*dashboard_signals, *history_signals]
    if any(
        not isinstance(signal, dict)
        or not isinstance(signal.get("id"), str)
        or re.fullmatch(r"[a-f0-9]{20}", cast(str, signal["id"])) is None
        for signal in route_signals
    ):
        raise ValueError("Supplemental publication route inputs contain an invalid signal identity.")
    route_signal_ids = {
        cast(str, cast(dict[str, object], signal)["id"])
        for signal in route_signals
    }
    recent_events = read_recent_history_events(repository / "data/history", generated_at)
    event_bundle = build_event_feeds(
        recent_events,
        snapshot,
        generated_at,
        effective_review,
        available_signal_ids=route_signal_ids,
    )
    _validate(event_bundle.artifact, EVENTS_SCHEMA, "event stream")
    events_path = _atomic_bytes(PUBLIC_DATA / "events.json", event_bundle.event_json, MAXIMUM_EVENT_JSON_BYTES)
    atom_path = _atomic_bytes(PUBLIC_DATA / "events.atom.xml", event_bundle.atom, MAXIMUM_SYNDICATION_BYTES)
    rss_path = _atomic_bytes(PUBLIC_DATA / "events.rss.xml", event_bundle.rss, MAXIMUM_SYNDICATION_BYTES)
    json_feed_value = json.loads(event_bundle.json_feed)
    _validate(json_feed_value, JSON_FEED_SCHEMA, "JSON Feed")
    json_feed_path = _atomic_bytes(
        PUBLIC_DATA / "events.feed.json", event_bundle.json_feed, MAXIMUM_SYNDICATION_BYTES
    )

    registry = load_brand_registry(repository / "data" / "brands-lt.json")
    brand_values = [entry.brand for entry in registry.entries] + [
        brand
        for signal in [*complete_signals, *(history_signals if isinstance(history_signals, list) else [])]
        if isinstance(signal, dict) and isinstance((brand := signal.get("brand")), str)
    ]
    brand_bundles = build_brand_event_feeds(event_bundle.artifact, brand_values)
    brand_root = repository / PUBLIC_DATA / "brands"
    if brand_root.exists():
        shutil.rmtree(brand_root)
    brand_paths: list[Path] = []
    brand_rows: list[dict[str, object]] = []
    for bundle in brand_bundles:
        relative_root = PUBLIC_DATA / "brands" / bundle.slug
        bundle_paths = {
            "atom": _atomic_bytes(
                relative_root / "events.atom.xml", bundle.atom, MAXIMUM_SYNDICATION_BYTES
            ),
            "rss": _atomic_bytes(
                relative_root / "events.rss.xml", bundle.rss, MAXIMUM_SYNDICATION_BYTES
            ),
            "jsonFeed": _atomic_bytes(
                relative_root / "events.feed.json", bundle.json_feed, MAXIMUM_SYNDICATION_BYTES
            ),
        }
        _validate(json.loads(bundle.json_feed), JSON_FEED_SCHEMA, f"{bundle.brand} JSON Feed")
        brand_paths.extend(bundle_paths.values())
        brand_rows.append(
            {
                "brand": bundle.brand,
                "slug": bundle.slug,
                "eventCount": bundle.event_count,
                **{
                    name: "/" + path.relative_to(repository / "public").as_posix()
                    for name, path in bundle_paths.items()
                },
            }
        )
    brand_directory = {
        "schemaVersion": 1,
        "dataset": "radar-brand-feeds",
        "generatedAt": generated_at,
        "semantics": (
            "Each per-brand feed is a filtered view of the same bounded 30-day global event stream. "
            "An empty feed means no publishable event in that sampled window, not no phishing activity."
        ),
        "brands": brand_rows,
    }
    _validate(brand_directory, BRAND_FEEDS_SCHEMA, "brand feed directory")
    brand_directory_path = _write_json(
        PUBLIC_DATA / "brand-feeds.json",
        brand_directory,
        MAXIMUM_BRAND_FEED_DIRECTORY_BYTES,
        pretty=True,
    )

    assessments = effective_review.get("assessments")
    misp_manifest, misp_event = build_misp_feed(assessments if misp_enabled else [], generated_at)
    _validate(misp_manifest, MISP_MANIFEST_SCHEMA, "reviewed MISP manifest")
    _validate(misp_event, MISP_EVENT_SCHEMA, "reviewed MISP event")
    misp_manifest_path = _write_json(
        PUBLIC_DATA / "misp" / "manifest.json",
        misp_manifest,
        MAXIMUM_MISP_BYTES,
        pretty=True,
    )
    misp_event_path = _write_json(
        PUBLIC_DATA / "misp" / f"{MISP_EVENT_UUID}.json",
        misp_event,
        MAXIMUM_MISP_BYTES,
        pretty=True,
    )
    warninglist = build_official_domain_warninglist(registry)
    _validate(warninglist, MISP_WARNINGLIST_SCHEMA, "official-domain MISP warning list")
    warninglist_path = _write_json(
        PUBLIC_DATA / "misp-warninglists" / "hecavex-official-domains" / "list.json",
        warninglist,
        MAXIMUM_WARNINGLIST_BYTES,
        pretty=True,
    )

    quality = build_quality_metrics(effective_review, effective_history, generated_at)
    _validate(quality, QUALITY_METRICS_SCHEMA, "quality metrics")
    quality_path = _write_json(
        PUBLIC_DATA / "quality-metrics.json", quality, MAXIMUM_QUALITY_BYTES, pretty=True
    )
    trends = build_daily_trends_from_repository(
        repository,
        cast(Sequence[Mapping[str, object]], complete_signals),
        health,
        generated_at,
    )
    _validate(trends, DAILY_TRENDS_SCHEMA, "daily trends")
    trends_path = _write_json(
        PUBLIC_DATA / "daily-trends.json", trends, MAXIMUM_TRENDS_BYTES, pretty=True
    )

    schema_by_path: dict[Path, str | None] = {
        PUBLIC_DATA / "radar.json": f"{SCHEMA_BASE}radar-v2.schema.json",
        PUBLIC_DATA / "radar.stix.json": "https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html",
        PUBLIC_DATA / "radar-reviewed.stix.json": "https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html",
        PUBLIC_DATA / "radar.index.json": f"{SCHEMA_BASE}radar-index-v1.schema.json",
        PUBLIC_DATA / "history.json": None,
        PUBLIC_DATA / "changes.json": f"{SCHEMA_BASE}changes-v1.schema.json",
        PUBLIC_DATA / "pipeline-health.json": f"{SCHEMA_BASE}pipeline-health-v1.schema.json",
        PUBLIC_DATA / "related-observations.json": f"{SCHEMA_BASE}related-observations-v1.schema.json",
        PUBLIC_DATA / "events.json": f"{SCHEMA_BASE}events-v1.schema.json",
        PUBLIC_DATA / "events.atom.xml": None,
        PUBLIC_DATA / "events.rss.xml": None,
        PUBLIC_DATA / "events.feed.json": f"{SCHEMA_BASE}json-feed-v1.schema.json",
        PUBLIC_DATA / "brand-feeds.json": f"{SCHEMA_BASE}brand-feeds-v1.schema.json",
        PUBLIC_DATA / "quality-metrics.json": f"{SCHEMA_BASE}quality-metrics-v1.schema.json",
        PUBLIC_DATA / "daily-trends.json": f"{SCHEMA_BASE}daily-trends-v1.schema.json",
        PUBLIC_DATA / "misp" / "manifest.json": f"{SCHEMA_BASE}misp-manifest-v1.schema.json",
        PUBLIC_DATA / "misp" / f"{MISP_EVENT_UUID}.json": f"{SCHEMA_BASE}misp-event-v1.schema.json",
        PUBLIC_DATA / "misp-warninglists" / "hecavex-official-domains" / "list.json": (
            f"{SCHEMA_BASE}misp-warninglist-v1.schema.json"
        ),
    }
    for path in brand_paths:
        relative = path.relative_to(repository)
        schema_by_path[relative] = (
            f"{SCHEMA_BASE}json-feed-v1.schema.json" if path.name.endswith(".feed.json") else None
        )
    from .history_partitions import partition_paths
    for path in partition_paths(repository / PUBLIC_DATA / "history.json"):
        schema_by_path[path.relative_to(repository)] = None
    for path in schema_paths:
        schema_by_path[path.relative_to(repository)] = None
    for path in schema_by_path:
        absolute = repository / path
        if absolute.is_file():
            write_checksum(absolute)
    # Collection health is an independently deployed latest-attempt document,
    # not part of this atomic hourly release. Remove the legacy companion so a
    # wildcard staging step cannot reintroduce a permanently stale digest.
    (repository / PUBLIC_DATA / "collection-health.json.sha256").unlink(missing_ok=True)
    manifest_path = write_feed_manifest(repository, snapshot, len(complete_signals), schema_by_path)
    return [
        index_path,
        changes_path,
        health_path,
        relations_path,
        events_path,
        atom_path,
        rss_path,
        json_feed_path,
        brand_directory_path,
        quality_path,
        trends_path,
        misp_manifest_path,
        misp_event_path,
        warninglist_path,
        *brand_paths,
        manifest_path,
        *schema_paths,
    ]


def _load_required_json(path: Path, maximum: int) -> object:
    value = _read_json(path, maximum)
    if value is None:
        raise ValueError(f"{path.as_posix()} is missing, invalid, or oversized.")
    return value


def validate_publication(repository: Path, validate_stix: bool = False) -> None:
    if (repository / PUBLIC_DATA / "collection-health.json.sha256").exists():
        raise ValueError("Volatile collection health must not have a release checksum companion.")
    schema_targets = {
        PUBLIC_DATA / "radar.json": (RADAR_SCHEMA, MAXIMUM_DASHBOARD_BYTES),
        PUBLIC_DATA / "radar.index.json": (RADAR_INDEX_SCHEMA, 256 * 1024),
        PUBLIC_DATA / "pipeline-health.json": (PIPELINE_HEALTH_SCHEMA, MAXIMUM_AGGREGATE_BYTES),
        PUBLIC_DATA / "changes.json": (CHANGES_SCHEMA, MAXIMUM_AGGREGATE_BYTES),
        PUBLIC_DATA / "related-observations.json": (RELATED_SCHEMA, MAXIMUM_RELATION_BYTES),
        PUBLIC_DATA / "events.json": (EVENTS_SCHEMA, MAXIMUM_EVENT_JSON_BYTES),
        PUBLIC_DATA / "events.feed.json": (JSON_FEED_SCHEMA, MAXIMUM_SYNDICATION_BYTES),
        PUBLIC_DATA / "brand-feeds.json": (BRAND_FEEDS_SCHEMA, MAXIMUM_BRAND_FEED_DIRECTORY_BYTES),
        PUBLIC_DATA / "quality-metrics.json": (QUALITY_METRICS_SCHEMA, MAXIMUM_QUALITY_BYTES),
        PUBLIC_DATA / "daily-trends.json": (DAILY_TRENDS_SCHEMA, MAXIMUM_TRENDS_BYTES),
        PUBLIC_DATA / "misp" / "manifest.json": (MISP_MANIFEST_SCHEMA, MAXIMUM_MISP_BYTES),
        PUBLIC_DATA / "misp" / f"{MISP_EVENT_UUID}.json": (MISP_EVENT_SCHEMA, MAXIMUM_MISP_BYTES),
        PUBLIC_DATA / "misp-warninglists" / "hecavex-official-domains" / "list.json": (
            MISP_WARNINGLIST_SCHEMA,
            MAXIMUM_WARNINGLIST_BYTES,
        ),
        PUBLIC_DATA / "feed-manifest.json": (MANIFEST_SCHEMA, 256 * 1024),
    }
    for relative, (schema, maximum) in schema_targets.items():
        _validate(_load_required_json(repository / relative, maximum), schema, relative.as_posix())
    misp_manifest = cast(
        dict[str, object],
        _load_required_json(repository / PUBLIC_DATA / "misp" / "manifest.json", MAXIMUM_MISP_BYTES),
    )
    misp_event_path = repository / PUBLIC_DATA / "misp" / f"{MISP_EVENT_UUID}.json"
    misp_event = cast(dict[str, object], _load_required_json(misp_event_path, MAXIMUM_MISP_BYTES))
    misp_event_row = cast(dict[str, object], misp_event["Event"])
    misp_attributes = cast(list[object], misp_event_row["Attribute"])
    if misp_attributes:
        if set(misp_manifest) != {MISP_EVENT_UUID} or misp_event_row["published"] is not True:
            raise ValueError("A non-empty reviewed MISP event must be published and indexed exactly once.")
        misp_manifest_row = cast(dict[str, object], misp_manifest[MISP_EVENT_UUID])
        if (
            misp_event_row["uuid"] != MISP_EVENT_UUID
            or misp_manifest_row["Orgc"] != misp_event_row["Orgc"]
            or misp_manifest_row["integrity:sha256"] != _sha256(misp_event_path)
        ):
            raise ValueError("Reviewed MISP manifest metadata or event integrity does not match its event file.")
    elif misp_manifest or misp_event_row["published"] is not False:
        raise ValueError("An empty reviewed MISP event must remain unpublished and absent from its manifest.")
    for name, expected_schema in PUBLIC_SCHEMAS.items():
        Draft202012Validator.check_schema(expected_schema)
        published_schema = _load_required_json(repository / PUBLIC_DATA / "schemas" / name, 128 * 1024)
        if published_schema != expected_schema:
            raise ValueError(f"Published schema {name} does not match the current generator source.")
    snapshot = cast(
        dict[str, object],
        _load_required_json(repository / PUBLIC_DATA / "radar.json", MAXIMUM_DASHBOARD_BYTES),
    )
    index = cast(dict[str, object], _load_required_json(repository / PUBLIC_DATA / "radar.index.json", 256 * 1024))
    public_root = (repository / "public").resolve()
    complete_ids: list[str] = []
    seen_ids: set[str] = set()
    shard_paths: set[str] = set()
    for expected_number, raw_shard in enumerate(cast(list[object], index["shards"]), start=1):
        shard_row = cast(dict[str, object], raw_shard)
        shard_relative = cast(str, shard_row["path"]).removeprefix("/")
        path = (public_root / shard_relative).resolve()
        if (
            not path.is_relative_to(public_root)
            or cast(int, shard_row["number"]) != expected_number
            or shard_relative in shard_paths
        ):
            raise ValueError("Signal shard index contains a non-sequential, duplicate, or unsafe path.")
        shard_paths.add(shard_relative)
        value = _load_required_json(path, MAXIMUM_SHARD_BYTES)
        _validate(value, RADAR_SHARD_SCHEMA, path.as_posix())
        if path.stat().st_size != shard_row["bytes"] or _sha256(path) != shard_row["sha256"]:
            raise ValueError(f"{path.as_posix()} does not match its shard index digest.")
        shard = cast(dict[str, object], value)
        shard_signals = cast(list[dict[str, object]], shard["signals"])
        shard_ids = [cast(str, signal["id"]) for signal in shard_signals]
        if (
            shard["shard"] != expected_number
            or shard["generatedAt"] != index["generatedAt"]
            or len(shard_ids) != shard_row["signals"]
            or shard_ids[0] != shard_row["firstSignalId"]
            or shard_ids[-1] != shard_row["lastSignalId"]
            or any(identifier in seen_ids for identifier in shard_ids)
        ):
            raise ValueError(f"{path.as_posix()} does not match its index row or contains duplicate signal IDs.")
        complete_ids.extend(shard_ids)
        seen_ids.update(shard_ids)
    dashboard_signals = cast(list[dict[str, object]], snapshot["signals"])
    dashboard_ids = [cast(str, signal["id"]) for signal in dashboard_signals]
    if (
        len(complete_ids) != index["signalCount"]
        or len(dashboard_ids) != index["dashboardSignalCount"]
        or dashboard_ids != complete_ids[: len(dashboard_ids)]
    ):
        raise ValueError("Signal index counts or dashboard-prefix ordering do not match the published signal sets.")
    from .history import read_public_history
    history_artifact = read_public_history(repository / PUBLIC_DATA / "history.json")
    if not isinstance(history_artifact, dict) or not isinstance(history_artifact.get("signals"), list):
        raise ValueError("Public history does not provide a bounded signal collection.")
    history_ids = {
        cast(str, signal.get("id"))
        for signal in cast(list[object], history_artifact["signals"])
        if isinstance(signal, dict)
        and isinstance(signal.get("id"), str)
        and re.fullmatch(r"[a-f0-9]{20}", cast(str, signal["id"]))
    }
    if len(history_ids) != len(cast(list[object], history_artifact["signals"])):
        raise ValueError("Public history contains an invalid or duplicate signal identity.")
    route_signal_ids = set(dashboard_ids) | history_ids
    event_stream = cast(
        dict[str, object],
        _load_required_json(repository / PUBLIC_DATA / "events.json", MAXIMUM_EVENT_JSON_BYTES),
    )
    for raw_event in cast(list[object], event_stream["events"]):
        event = cast(dict[str, object], raw_event)
        identifier = cast(str, event["signalId"])
        if identifier not in route_signal_ids or event["signalPath"] != f"/signals/{identifier}/":
            raise ValueError(
                "An event references a signal outside the dashboard and retained-history route set."
            )
    manifest = cast(dict[str, object], _load_required_json(repository / PUBLIC_DATA / "feed-manifest.json", 256 * 1024))
    successful_sync_at = snapshot["lastSuccessfulSyncAt"]
    generation_artifacts = {
        "radar index": index,
        "feed manifest": manifest,
        "change aggregate": cast(
            dict[str, object],
            _load_required_json(repository / PUBLIC_DATA / "changes.json", MAXIMUM_AGGREGATE_BYTES),
        ),
        "pipeline health": cast(
            dict[str, object],
            _load_required_json(repository / PUBLIC_DATA / "pipeline-health.json", MAXIMUM_AGGREGATE_BYTES),
        ),
        "related observations": cast(
            dict[str, object],
            _load_required_json(repository / PUBLIC_DATA / "related-observations.json", MAXIMUM_RELATION_BYTES),
        ),
        "event stream": event_stream,
        "brand feed directory": cast(
            dict[str, object],
            _load_required_json(
                repository / PUBLIC_DATA / "brand-feeds.json", MAXIMUM_BRAND_FEED_DIRECTORY_BYTES
            ),
        ),
        "quality metrics": cast(
            dict[str, object],
            _load_required_json(repository / PUBLIC_DATA / "quality-metrics.json", MAXIMUM_QUALITY_BYTES),
        ),
        "daily trends": cast(
            dict[str, object],
            _load_required_json(repository / PUBLIC_DATA / "daily-trends.json", MAXIMUM_TRENDS_BYTES),
        ),
    }
    mismatched_generations = [
        label for label, artifact in generation_artifacts.items() if artifact.get("generatedAt") != successful_sync_at
    ]
    if mismatched_generations:
        raise ValueError(
            "Publication artifacts do not share the successful-sync boundary: "
            + ", ".join(mismatched_generations)
        )
    expected_source_times = {
        cast(str, source["name"]): cast(str | None, source["fetchedAt"])
        for source in cast(list[dict[str, object]], snapshot["sources"])
    }
    if manifest.get("sourceFetchedAt") != dict(sorted(expected_source_times.items())):
        raise ValueError("Feed-manifest source timestamps do not match the live snapshot source rows.")
    counts = cast(dict[str, int], manifest["counts"])
    artifacts = cast(list[object], manifest["artifacts"])
    if (
        counts["completeSignals"] != len(complete_ids)
        or counts["dashboardSignals"] != len(dashboard_ids)
        or counts["dashboardOmitted"] != len(complete_ids) - len(dashboard_ids)
        or counts["artifacts"] != len(artifacts)
    ):
        raise ValueError("Feed-manifest counts do not reconcile with the index and dashboard snapshot.")
    expected_manifest_schemas: dict[str, str | None] = {
        "/data/radar.json": f"{SCHEMA_BASE}radar-v2.schema.json",
        "/data/radar.stix.json": "https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html",
        "/data/radar-reviewed.stix.json": "https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html",
        "/data/radar.index.json": f"{SCHEMA_BASE}radar-index-v1.schema.json",
        "/data/history.json": None,
        "/data/changes.json": f"{SCHEMA_BASE}changes-v1.schema.json",
        "/data/pipeline-health.json": f"{SCHEMA_BASE}pipeline-health-v1.schema.json",
        "/data/related-observations.json": f"{SCHEMA_BASE}related-observations-v1.schema.json",
        "/data/events.json": f"{SCHEMA_BASE}events-v1.schema.json",
        "/data/events.atom.xml": None,
        "/data/events.rss.xml": None,
        "/data/events.feed.json": f"{SCHEMA_BASE}json-feed-v1.schema.json",
        "/data/brand-feeds.json": f"{SCHEMA_BASE}brand-feeds-v1.schema.json",
        "/data/quality-metrics.json": f"{SCHEMA_BASE}quality-metrics-v1.schema.json",
        "/data/daily-trends.json": f"{SCHEMA_BASE}daily-trends-v1.schema.json",
        "/data/misp/manifest.json": f"{SCHEMA_BASE}misp-manifest-v1.schema.json",
        f"/data/misp/{MISP_EVENT_UUID}.json": f"{SCHEMA_BASE}misp-event-v1.schema.json",
        "/data/misp-warninglists/hecavex-official-domains/list.json": (
            f"{SCHEMA_BASE}misp-warninglist-v1.schema.json"
        ),
        **{f"/data/schemas/{name}": None for name in PUBLIC_SCHEMAS},
    }
    brand_directory = cast(
        dict[str, object],
        _load_required_json(
            repository / PUBLIC_DATA / "brand-feeds.json", MAXIMUM_BRAND_FEED_DIRECTORY_BYTES
        ),
    )
    brand_rows = cast(list[dict[str, object]], brand_directory["brands"])
    for row in brand_rows:
        for field in ("atom", "rss", "jsonFeed"):
            feed_reference = cast(str, row[field])
            expected_manifest_schemas[feed_reference] = (
                f"{SCHEMA_BASE}json-feed-v1.schema.json" if field == "jsonFeed" else None
            )
    from .history_partitions import partition_paths
    for part in partition_paths(repository / PUBLIC_DATA / "history.json"):
        expected_manifest_schemas["/" + part.relative_to(repository / "public").as_posix()] = None
    manifest_paths: set[str] = set()
    for raw_artifact in artifacts:
        artifact = cast(dict[str, object], raw_artifact)
        manifest_artifact_path = cast(str, artifact["path"])
        artifact_relative = manifest_artifact_path.removeprefix("/")
        path = (public_root / artifact_relative).resolve()
        if not path.is_relative_to(public_root) or manifest_artifact_path in manifest_paths:
            raise ValueError("Feed manifest contains a duplicate or unsafe artifact path.")
        manifest_paths.add(manifest_artifact_path)
        if artifact["schema"] != expected_manifest_schemas.get(manifest_artifact_path):
            raise ValueError(f"{manifest_artifact_path} has an incorrect manifest schema reference.")
        if not path.is_file() or path.stat().st_size != artifact["bytes"] or _sha256(path) != artifact["sha256"]:
            raise ValueError(f"{path.as_posix()} does not match the feed manifest.")
        checksum = path.with_name(path.name + CHECKSUM_SUFFIX)
        expected = f"{artifact['sha256']}  {path.name}\n"
        try:
            checksum_body = checksum.read_text(encoding="ascii")
        except (FileNotFoundError, OSError, UnicodeDecodeError) as error:
            raise ValueError(f"{checksum.as_posix()} is missing or unreadable.") from error
        if checksum_body != expected:
            raise ValueError(f"{checksum.as_posix()} does not match its artifact.")
    expected_manifest_paths = set(expected_manifest_schemas)
    if manifest_paths != expected_manifest_paths:
        missing = sorted(expected_manifest_paths - manifest_paths)
        unexpected = sorted(manifest_paths - expected_manifest_paths)
        raise ValueError(
            "Feed manifest artifact set is not canonical; missing="
            + ",".join(missing)
            + "; unexpected="
            + ",".join(unexpected)
        )

    expected_event_urls = [
        "https://radar.hecavex.com" + cast(str, event["signalPath"])
        for event in cast(list[dict[str, object]], event_stream["events"])
    ]
    global_json_feed = cast(
        dict[str, object],
        _load_required_json(
            repository / PUBLIC_DATA / "events.feed.json", MAXIMUM_SYNDICATION_BYTES
        ),
    )
    global_json_urls = [
        cast(dict[str, object], item).get("url")
        for item in cast(list[object], global_json_feed["items"])
    ]
    if global_json_urls != expected_event_urls:
        raise ValueError("Global JSON Feed links do not match canonical event destinations.")

    expected_xml_urls: dict[Path, list[str]] = {
        repository / PUBLIC_DATA / "events.atom.xml": expected_event_urls,
        repository / PUBLIC_DATA / "events.rss.xml": expected_event_urls,
    }
    for row in brand_rows:
        expected_brand_urls = [
            "https://radar.hecavex.com" + cast(str, event["signalPath"])
            for event in cast(list[dict[str, object]], event_stream["events"])
            if event["brand"] == row["brand"]
        ]
        for field in ("atom", "rss"):
            expected_xml_urls[
                repository / "public" / cast(str, row[field]).removeprefix("/")
            ] = expected_brand_urls
    for path, expected_urls in expected_xml_urls.items():
        try:
            root = ET.fromstring(path.read_bytes())  # noqa: S314 - generated local static publication.
        except (OSError, ET.ParseError) as error:
            raise ValueError(f"{path.as_posix()} is missing or invalid XML.") from error
        expected_root = "feed" if path.name.endswith(".atom.xml") else "rss"
        if root.tag.rsplit("}", 1)[-1] != expected_root:
            raise ValueError(f"{path.as_posix()} has an unexpected syndication root element.")
        if expected_root == "feed":
            links: list[str] = []
            for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                link = entry.find("{http://www.w3.org/2005/Atom}link")
                href = link.get("href") if link is not None else None
                if not isinstance(href, str):
                    raise ValueError(f"{path.as_posix()} contains an event without a canonical link.")
                links.append(href)
        else:
            links = [cast(str, item.findtext("link")) for item in root.findall("channel/item")]
        if links != expected_urls:
            raise ValueError(f"{path.as_posix()} links do not match canonical event destinations.")
    for row in brand_rows:
        feed_path = repository / "public" / cast(str, row["jsonFeed"]).removeprefix("/")
        feed = _load_required_json(feed_path, MAXIMUM_SYNDICATION_BYTES)
        _validate(feed, JSON_FEED_SCHEMA, feed_path.as_posix())
        items = cast(list[object], cast(dict[str, object], feed)["items"])
        expected_brand_urls = [
            "https://radar.hecavex.com" + cast(str, event["signalPath"])
            for event in cast(list[dict[str, object]], event_stream["events"])
            if event["brand"] == row["brand"]
        ]
        if (
            len(items) != row["eventCount"]
            or [cast(dict[str, object], item).get("url") for item in items] != expected_brand_urls
        ):
            raise ValueError(f"{feed_path.as_posix()} does not match its brand event projection.")
    feed_manifest_path = repository / PUBLIC_DATA / "feed-manifest.json"
    manifest_checksum = feed_manifest_path.with_name(feed_manifest_path.name + CHECKSUM_SUFFIX)
    expected_manifest_checksum = f"{_sha256(feed_manifest_path)}  {feed_manifest_path.name}\n"
    try:
        manifest_checksum_body = manifest_checksum.read_text(encoding="ascii")
    except (FileNotFoundError, OSError, UnicodeDecodeError) as error:
        raise ValueError("Feed-manifest checksum is missing or unreadable.") from error
    if manifest_checksum_body != expected_manifest_checksum:
        raise ValueError("Feed-manifest checksum does not match its artifact.")
    if validate_stix:
        try:
            from stix2validator import ValidationOptions, validate_file  # type: ignore[import-untyped]
        except ImportError as error:
            raise RuntimeError("stix2-validator is required for --stix validation.") from error
        for name in ("radar.stix.json", "radar-reviewed.stix.json"):
            result = validate_file(
                str(repository / PUBLIC_DATA / name),
                options=ValidationOptions(version="2.1"),
            )
            if not result.is_valid:
                diagnostics = _stix_validation_diagnostics(result)
                errors = "; ".join(diagnostics[:8]) or "validator returned no diagnostics"
                raise ValueError(f"{name} failed standard STIX 2.1 validation: {errors}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate generated Radar publication artifacts.")
    parser.add_argument("--stix", action="store_true", help="Also run the standard OASIS STIX validator.")
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        validate_publication(Path.cwd().resolve(), validate_stix=options.stix)
    except Exception as error:
        print(f"Publication validation failed: {error}", file=sys.stderr)
        return 1
    print("Validated Radar schemas, digests, shards, manifest, and publication boundaries.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
