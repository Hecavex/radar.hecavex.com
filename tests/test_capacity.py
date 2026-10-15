from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hecavex_radar import capacity
from hecavex_radar.observation_store import append_observations
from hecavex_radar.public_schemas import RADAR_SCHEMA
from hecavex_radar.publication import _budget_candidate, _json_bytes


def test_capacity_accepts_valid_dashboard_between_256_and_512_kib(tmp_path: Path) -> None:
    now = "2026-10-15T12:00:00.000Z"
    signals = []
    for number in range(400):
        domain = f"login-{number:04d}-{'x' * 40}[.]example"
        signals.append({
            "id": hashlib.sha256(domain.encode()).hexdigest()[:20], "domain": domain,
            "url": f"hxxps://{domain}", "firstSeen": now, "lastSeen": now,
            "sources": ["URLScan"], "status": "suspected", "brand": "Example",
            "country": None, "host": None, "screenshotUrl": None, "referenceUrl": None,
            "hashes": [], "reasonCodes": ["brand-domain-match"], "matchScore": 90,
            "evidenceTier": "name-only", "reviewState": "unreviewed",
            "ltRelevance": "lithuanian-brand-relevance", "confidence": 90,
        })
    homepages = {"CertStream": "https://certstream.dev/", "URLScan": "https://urlscan.io/",
                 "HECAVEX": "https://hecavex.com/"}
    sources = [{"name": name, "homepage": homepages[name], "fetchedAt": now,
                "records": 400 if name == "URLScan" else 0,
                "state": "healthy" if name == "URLScan" else "skipped", "note": None}
               for name in ("CertStream", "URLScan", "HECAVEX")]
    document = _budget_candidate(signals, sources, now)
    Draft202012Validator(RADAR_SCHEMA).validate(document)
    payload = _json_bytes(document, pretty=True)
    assert 256 * 1024 < len(payload) < 512 * 1024
    path = tmp_path / "public/data/radar.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    row = next(row for row in capacity.inventory(tmp_path) if row["path"] == "public/data/radar.json")

    assert row["records"] == 400
    assert row["maximumBytes"] == 512 * 1024
    assert row["headroomBytes"] == 512 * 1024 - len(payload)


def test_capacity_report_aggregates_operational_bytes_and_warns_without_payload(tmp_path: Path) -> None:
    root = tmp_path / "data/certstream/2026-10-01"
    root.mkdir(parents=True)
    (root / "domains.ndjson").write_text('{"candidate":"must-not-appear"}\n', encoding="utf-8")
    (root / "attempts.ndjson").write_text('{"outcome":"healthy-empty"}\n', encoding="utf-8")
    report_builder = getattr(capacity, "capacity_report", None)
    assert callable(report_builder), "Operational capacity report is required."

    report = report_builder(tmp_path, warning_percent=0)

    assert report["activeFiles"] == 2
    assert report["activeBytes"] == sum(path.stat().st_size for path in root.iterdir())
    assert report["archiveMonths"] == ["2026-10"]
    assert report["warnings"]
    assert "must-not-appear" not in json.dumps(report)


def test_capacity_rejects_oversized_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "public/data/radar.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b" " * (512 * 1024 + 1))
    with pytest.raises(ValueError, match="budget"):
        capacity.inventory(tmp_path)


def test_capacity_refuses_linked_archive_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == data or original(path))
    with pytest.raises(ValueError, match="linked archive"):
        capacity.capacity_report(tmp_path)


def test_capacity_reports_durable_observation_part_and_total_headroom(tmp_path: Path) -> None:
    append_observations(tmp_path, [{
        "domain": "revolut-login[.]example", "sources": ["CertStream"],
        "sourceObservedAt": "2026-09-01T12:00:00.000Z", "sourceTimeProvenance": "legacy-history-boundary",
        "radarRecordedAt": None, "importedAt": "2026-10-15T12:00:00.000Z", "providerEventId": None,
        "originalMatch": {"brand": "Revolut", "score": None, "reasonCodes": [], "policyVersion": "legacy-unknown"},
        "assessment": None, "provenance": [],
    }], updated_at="2026-10-15T12:00:00.000Z")

    row = next((row for row in capacity.inventory(tmp_path)
                if row["path"] == "data/history/observations/index.json"), None)

    assert row is not None, "Durable fact headroom must be visible independently of expiring legacy summaries."
    assert row["records"] == 1 and row["hostnames"] == 1
    assert row["partitions"] == 2
    assert row["maximumBytes"] == row["maximumPartitionBytes"] == 256 * 1024
    assert row["maximumStoreBytes"] == 128 * 1024 * 1024
    assert row["storeHeadroomBytes"] > 0


def test_capacity_aggregate_limit_fails_instead_of_only_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "data/certstream/2026-10-01/domains.ndjson"
    path.parent.mkdir(parents=True)
    path.write_text('{"domain":"synthetic"}\n', encoding="utf-8")
    monkeypatch.setattr(capacity, "MAX_TOTAL", 1)
    with pytest.raises(ValueError, match="hard limit"):
        capacity.capacity_report(tmp_path)


def packed_observation_inventory(*, partitions: int = 5) -> list[dict[str, object]]:
    return [{"path": "data/history/observations/index.json", "bytes": 1000, "maximumBytes": 256 * 1024,
             "partitions": partitions, "maximumPartitions": 512,
             "partitionBytes": 128 * 1024 * 1024 // 100, "maximumStoreBytes": 128 * 1024 * 1024,
             "largestPartitionBytes": 256 * 1024 * 99 // 100, "maximumPartitionBytes": 256 * 1024}]


def test_normally_packed_observation_part_is_not_a_store_exhaustion_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(capacity, "inventory", lambda root: packed_observation_inventory())
    report = capacity.capacity_report(tmp_path)
    assert report["warnings"] == []


def test_observation_partition_pressure_warns_with_count_units(tmp_path, monkeypatch):
    monkeypatch.setattr(capacity, "inventory", lambda root: packed_observation_inventory(partitions=410))
    report = capacity.capacity_report(tmp_path)
    warning = next(item for item in report["warnings"] if item["path"].endswith("/partitions"))
    assert warning["unit"] == "partitions" and warning["used"] == 410 and warning["maximum"] == 512
    assert "bytes" not in warning and "maximumBytes" not in warning


def test_active_file_pressure_warns_with_files_headroom_and_count_units(tmp_path, monkeypatch):
    directory = tmp_path / "data/enrichment"
    directory.mkdir(parents=True)
    for number in range(4):
        (directory / f"fixture-{number}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(capacity, "MAXIMUM_ACTIVE_FILES", 5)
    report = capacity.capacity_report(tmp_path)
    warning = next(item for item in report["warnings"] if item["unit"] == "files")
    assert warning["used"] == 4 and warning["maximum"] == 5
    assert report["headroomFiles"] == 1
    assert "bytes" not in warning


def test_aggregate_headroom_includes_root_transport_manifest_and_publication_marker(tmp_path, monkeypatch):
    (tmp_path / "radar-data-manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "radar-publication.json").write_text("{}", encoding="utf-8")
    report = capacity.capacity_report(tmp_path)
    assert report["activeFiles"] == 2 and report["activeBytes"] == 4
    monkeypatch.setattr(capacity, "MAX_TOTAL", 3)
    with pytest.raises(ValueError, match="hard limit"):
        capacity.capacity_report(tmp_path)
