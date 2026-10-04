from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hecavex_radar.daily_trends import build_daily_trends, build_daily_trends_from_repository
from hecavex_radar.history import append_history_events, build_history_events, compact_history
from hecavex_radar.publication import MAXIMUM_TRENDS_BYTES, _json_bytes
from hecavex_radar.trend_retention import ARCHIVE, load_retained_discovery


def event(identifier: str, timestamp: str, *, publication: bool = False) -> dict[str, object]:
    return {"eventId": identifier * 32, "signalId": "a" * 20, "observedAt": timestamp,
            "eventType": "status-transition" if publication else "observation", "brand": "Revolut",
            "sources": ["CertStream"], "previousStatus": None,
            "reasonCodes": ["first-publication"] if publication else ["suspicious-context"]}


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def context(repository: Path, watermark: str | None) -> None:
    write(repository / "data/history/summary.json", {"compactedThrough": watermark, "signals": []})


def test_completed_daily_counts_survive_30_day_compaction_without_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "data/history/daily/2026-09-01/events.ndjson"
    row = event("1", "2026-09-01T00:00:00.000Z")
    write(path, row)
    first = build_daily_trends_from_repository(tmp_path, [], {}, "2026-09-02T00:00:00.000Z", days=35)
    expected = next(item for item in first["series"] if item["date"] == "2026-09-01")["discovery"]
    assert expected["events"] == expected["uniqueSignals"] == 1
    # Real compaction removes the detailed file. A replay cannot inflate counts.
    path.unlink()
    context(tmp_path, "2026-09-03")
    later = build_daily_trends_from_repository(tmp_path, [], {}, "2026-10-04T12:00:00.000Z", days=35)
    retained = next(item for item in later["series"] if item["date"] == "2026-09-01")
    assert retained["discovery"] == expected
    assert retained["discoveryBasis"] == "retained-aggregate"
    write(path, row)
    replay = build_daily_trends_from_repository(tmp_path, [], {}, "2026-10-04T13:00:00.000Z", days=35)
    assert next(item for item in replay["series"] if item["date"] == "2026-09-01")["discovery"] == expected


def test_compacted_host_totals_are_not_fabricated_daily_counts(tmp_path: Path) -> None:
    context(tmp_path, "2026-09-03")
    write(tmp_path / "data/certstream/2026-09-01/attempts.ndjson",
          {"endedAt": "2026-09-01T12:00:00.000Z", "outcome": "healthy-empty", "listeningSeconds": 480})
    result = build_daily_trends_from_repository(tmp_path, [], {}, "2026-10-04T12:00:00.000Z", days=35)
    row = next(item for item in result["series"] if item["date"] == "2026-09-01")
    assert row["discovery"] is None
    assert row["discoveryBasis"] == "unknown"
    assert row["collectorCoverage"]["recordedAttempts"] == 1
    assert result["omittedUnknownDays"] > 0
    assert result["discoveryCompleteFrom"] == "2026-09-04"


def test_duplicate_identity_exact_utc_boundary_and_partial_day_not_retained(tmp_path: Path) -> None:
    earlier = event("1", "2026-09-01T23:59:59.999Z")
    later = event("2", "2026-09-02T00:00:00.000Z")
    future = event("3", "2026-09-02T00:00:00.001Z")
    result = build_daily_trends([earlier, earlier, later, future], [], [], {},
                              "2026-09-02T00:00:00.000Z", days=2)
    assert [row["discovery"]["events"] for row in result["series"]] == [1, 1]
    assert result["series"][1]["partialDay"] is True
    with pytest.raises(ValueError, match="Conflicting"):
        build_daily_trends([earlier, {**earlier, "brand": "DHL"}], [], [], {},
                           "2026-09-02T00:00:00.000Z", days=2)
    write(tmp_path / "data/history/daily/2026-09-02/events.ndjson", later)
    build_daily_trends_from_repository(tmp_path, [], {}, "2026-09-02T12:00:00.000Z", days=2)
    assert json.loads((tmp_path / ARCHIVE).read_bytes())["rows"] == []


def test_compacted_transition_supports_reobservation_not_daily_counts() -> None:
    context_row = {"id": "a" * 20, "firstSeen": "2026-08-01T00:00:00.000Z",
                   "observationCount": 9999, "statusTransitions": [
                       {"observedAt": "2026-08-02T00:00:00.000Z", "previousStatus": None,
                        "reasonCodes": ["first-publication"]}]}
    result = build_daily_trends([event("1", "2026-09-01T12:00:00.000Z")], [], [], {},
                              "2026-09-02T00:00:00.000Z", days=2, historical_signals=[context_row])
    assert result["series"][0]["discovery"]["reobservations"] == 1
    assert result["series"][0]["discovery"]["events"] == 1


def test_recovery_is_cutoff_bounded_and_restores_only_compacted_days(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    # Isolate reviewed recovery from any aggregate archive regenerated by source CI.
    recovery_path = "config/trend-recovery-2026-10-01.json"
    write(tmp_path / recovery_path, json.loads((repository / recovery_path).read_bytes()))
    assert load_retained_discovery(tmp_path, "2026-09-30T23:59:59.999Z") == {}
    recovered = load_retained_discovery(tmp_path, "2026-10-04T00:00:00.000Z")
    assert [recovered[f"2026-09-0{day}"]["discovery"]["uniqueSignals"] for day in (1, 2, 3)] == [16, 19, 17]
    result = build_daily_trends([event("1", "2026-09-04T12:00:00.000Z")], [], [], {},
                              "2026-10-04T00:00:00.000Z", days=35,
                              compacted_through="2026-09-03", retained_discovery=recovered)
    assert next(row for row in result["series"] if row["date"] == "2026-09-04")["discovery"]["uniqueSignals"] == 1


def test_archive_rejects_duplicates_and_inconsistent_counters(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "config/trend-recovery-2026-10-01.json"
    document = json.loads(source.read_bytes())["summary"]
    document["rows"] = [document["rows"][0], document["rows"][0]]
    write(tmp_path / ARCHIVE, document)
    with pytest.raises(ValueError, match="unique"):
        load_retained_discovery(tmp_path, "2026-10-04T00:00:00.000Z")
    document["rows"] = document["rows"][:1]
    document["rows"][0]["discovery"]["uniqueSignals"] = 9999
    write(tmp_path / ARCHIVE, document)
    with pytest.raises(ValueError, match="Inconsistent"):
        load_retained_discovery(tmp_path, "2026-10-04T00:00:00.000Z")


def test_retention_does_not_change_collection_coverage() -> None:
    attempt = {"collectorStartedAt": "2026-09-01T00:00:00.000Z", "endedAt": "2026-09-01T00:08:00.000Z",
               "listeningSeconds": 480, "outcome": "healthy-empty"}
    original = build_daily_trends([], [attempt], [], {}, "2026-10-04T00:00:00.000Z", days=35)
    retained = build_daily_trends([], [attempt], [], {}, "2026-10-04T00:00:00.000Z", days=35,
                                 compacted_through="2026-09-03")
    before = next(row for row in original["series"] if row["date"] == "2026-09-01")
    after = next(row for row in retained["series"] if row["date"] == "2026-09-01")
    assert json.dumps(before["collectorCoverage"]) == json.dumps(after["collectorCoverage"])
    assert before["discovery"]["uniqueSignals"] == 0
    assert after["discovery"] is None


def test_noncanonical_retained_timestamp_is_rejected(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "config/trend-recovery-2026-10-01.json"
    document = json.loads(source.read_bytes())["summary"]
    document["rows"] = document["rows"][:1]
    document["rows"][0]["computedAt"] = "2026-10-01T00:40:26Z"
    write(tmp_path / ARCHIVE, document)
    with pytest.raises(ValueError, match="closed UTC day"):
        load_retained_discovery(tmp_path, "2026-10-04T00:00:00.000Z")


def test_compactor_preserves_last_available_detail_before_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures/radar-snapshot-v2-minimal.json"
    signals = json.loads(fixture.read_bytes())["signals"]
    monkeypatch.chdir(tmp_path)
    events = build_history_events(signals, signals, {})
    root = tmp_path / "data/history"
    append_history_events(root, events)
    path = root / "daily/2026-08-25/events.ndjson"
    assert path.exists()
    compact_history(root, datetime(2026, 10, 4, tzinfo=UTC), 30, 730)
    assert not path.exists()
    retained = load_retained_discovery(tmp_path, "2026-10-04T00:00:00.000Z")
    assert retained["2026-08-25"]["discovery"]["events"] == 3
    assert retained["2026-08-25"]["discovery"]["uniqueSignals"] == 1
    assert retained["2026-08-25"]["discovery"]["evidenceClassifiedSignals"] == 0
    # Replayed detail at or below the closed watermark is not added again.
    append_history_events(root, events)
    compact_history(root, datetime(2026, 10, 5, tzinfo=UTC), 30, 730)
    assert load_retained_discovery(tmp_path, "2026-10-05T00:00:00.000Z") == retained


def test_representative_365_day_series_fits_existing_publication_byte_budget() -> None:
    source = Path(__file__).resolve().parents[1] / "config/trend-recovery-2026-10-01.json"
    saved = json.loads(source.read_bytes())["summary"]["rows"]
    representative = max((row["discovery"] for row in saved), key=lambda row: len(json.dumps(row)))
    generated = datetime(2026, 10, 4, tzinfo=UTC)
    retained = {
        (generated - timedelta(days=offset)).date().isoformat(): {"discovery": representative}
        for offset in range(1, 365)
    }
    result = build_daily_trends([], [], [], {}, "2026-10-04T00:00:00.000Z",
                               compacted_through="2026-10-03", retained_discovery=retained)
    assert len(result["series"]) == 365
    assert len(_json_bytes(result)) <= MAXIMUM_TRENDS_BYTES
