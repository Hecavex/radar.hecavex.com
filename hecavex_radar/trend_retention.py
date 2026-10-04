"""Bounded, aggregate-only daily discovery retention; never infer counts from hosts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .history_partitions import read_document
from .public_schemas import DAILY_TRENDS_SCHEMA

ARCHIVE = "data/history/discovery-summary.json"
RECOVERY = "config/trend-recovery-2026-10-01.json"
MAXIMUM_BYTES = 2 * 1024 * 1024


def _document(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > MAXIMUM_BYTES:
        raise ValueError("Daily discovery archive exceeds its safe input boundary")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Daily discovery archive must be an object")
    return value


def _rows(document: dict[str, Any], generated_at: str) -> dict[str, dict[str, Any]]:
    if (set(document) != {"schemaVersion", "dataset", "countingMethodVersion", "rows"}
            or document["schemaVersion"] != 1 or document["dataset"] != "radar-discovery-summary"
            or document["countingMethodVersion"] != 2
            or not isinstance(document["rows"], list) or len(document["rows"]) > 365):
        raise ValueError("Invalid daily discovery summary")
    schema = DAILY_TRENDS_SCHEMA["properties"]["series"]["items"]["properties"]["discovery"]  # type: ignore[index]
    validator = Draft202012Validator({**schema, "$defs": DAILY_TRENDS_SCHEMA["$defs"]})
    result: dict[str, dict[str, Any]] = {}
    for row in document["rows"]:
        if (not isinstance(row, dict) or set(row) != {"date", "computedAt", "discovery"}
                or not isinstance(row["date"], str) or not isinstance(row["computedAt"], str)):
            raise ValueError("Invalid retained discovery row")
        day = date.fromisoformat(row["date"])
        computed = datetime.fromisoformat(row["computedAt"].replace("Z", "+00:00"))
        if (day.isoformat() != row["date"] or not row["computedAt"].endswith("Z")
                or computed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != row["computedAt"]
                or computed.date() <= day or row["date"] in result):
            raise ValueError("Retained discovery requires a unique, closed UTC day")
        discovery = row["discovery"]
        if discovery is None or not validator.is_valid(discovery):
            raise ValueError("Invalid retained discovery counters")
        if (discovery["uniqueSignals"] > discovery["events"]
                or discovery["facetSampleSize"] != discovery["uniqueSignals"]
                or discovery["evidenceClassifiedSignals"] > discovery["uniqueSignals"]
                or discovery["reobservations"] > discovery["observations"]
                or discovery["observations"] + discovery["firstPublications"]
                + discovery["statusChanges"] != discovery["events"]):
            raise ValueError("Inconsistent retained discovery counters")
        if row["computedAt"] <= generated_at:
            result[row["date"]] = row
    return result


def load_retained_discovery(repository: Path, generated_at: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    recovery = _document(repository / RECOVERY)
    if recovery is not None:
        if (set(recovery) != {"source", "summary"} or not isinstance(recovery["source"], dict)
                or not isinstance(recovery["summary"], dict)):
            raise ValueError("Invalid reviewed discovery recovery")
        # This file is reviewed source, never imported from the operational data branch.
        result.update(_rows(recovery["summary"], generated_at))
    persisted = _document(repository / ARCHIVE)
    if persisted is not None:
        result.update(_rows(persisted, generated_at))
    return result


def history_context(repository: Path, generated_at: str) -> tuple[str | None, list[dict[str, Any]]]:
    path = repository / "data/history/summary.json"
    if not path.exists():
        return None, []
    summary = read_document(path, 12 * 1024 * 1024)
    watermark = summary.get("compactedThrough")
    if watermark is not None and (
        not isinstance(watermark, str) or date.fromisoformat(watermark).isoformat() != watermark
        or watermark >= generated_at[:10]
    ):
        raise ValueError("Invalid daily discovery compaction watermark")
    signals = summary.get("signals", [])
    if not isinstance(signals, list) or len(signals) > 25_000:
        raise ValueError("Invalid daily discovery historical context")
    # firstSeen and explicit transitions support chronology only. observationCount,
    # first/last boundaries and recentEventIds cannot reconstruct daily totals.
    return watermark, signals


def persist_discovery(
    repository: Path, trends: dict[str, Any], previous: dict[str, dict[str, Any]], *, archive_path: Path | None = None,
) -> None:
    generated_at = trends["generatedAt"]
    first = (date.fromisoformat(generated_at[:10]) - timedelta(days=364)).isoformat()
    rows = {day: row for day, row in previous.items() if first <= day < generated_at[:10]}
    for row in trends["series"]:
        if not row["partialDay"] and row["discovery"] is not None:
            # Replace a complete day; never add the retained and active counters.
            if row["discoveryBasis"] == "retained-aggregate" and row["date"] in rows:
                continue
            if row["date"] in rows and rows[row["date"]]["discovery"] == row["discovery"]:
                continue
            rows[row["date"]] = {"date": row["date"], "computedAt": generated_at,
                                  "discovery": row["discovery"]}
    document = {"schemaVersion": 1, "dataset": "radar-discovery-summary", "countingMethodVersion": 2,
                "rows": [rows[day] for day in sorted(rows)]}
    _rows(document, generated_at)
    body = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(body) > MAXIMUM_BYTES:
        raise ValueError("Daily discovery summary exceeds 2 MiB")
    target = archive_path if archive_path is not None else repository / ARCHIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() == body:
        return
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(body)
    temporary.replace(target)


def preserve_compacting_discovery(
    history_root: Path, events: Sequence[Mapping[str, object]],
    historical_signals: Sequence[Mapping[str, object]], generated_at: str,
) -> None:
    """Capture the last available detail even after a long publisher outage.

    Called before the history compactor deletes files. The import is delayed to
    keep the aggregation and storage modules independent during initialization.
    """
    from .daily_trends import build_daily_trends

    path = history_root / "discovery-summary.json"
    document = _document(path)
    previous = _rows(document, generated_at) if document is not None else {}
    trends = cast(dict[str, Any], build_daily_trends(
        events, [], [], {}, generated_at, historical_signals=historical_signals,
    ))
    # Keep previously captured evidence facets if all underlying activity/facets
    # are unchanged. New or changed days have no inferred historical evidence tier.
    for row in trends["series"]:
        saved = previous.get(row["date"])
        if saved is not None and all(
            row["discovery"][key] == saved["discovery"][key]
            for key in row["discovery"] if key not in {"byEvidenceTier", "evidenceClassifiedSignals"}
        ):
            row["discovery"] = saved["discovery"]
    persist_discovery(history_root.parent.parent, trends, previous, archive_path=path)
