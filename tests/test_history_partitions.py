from __future__ import annotations

import json
from pathlib import Path

import pytest

from hecavex_radar.history import _atomic_write, _write_public_if_changed, read_public_history
from hecavex_radar.history_partitions import PART_BYTES, read_document, write_document


def test_default_5000_retained_rows_roundtrip_without_raising_response_limit(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    # Substantial per-row transition/replay data, not just empty placeholder IDs.
    payload = {"schemaVersion": 1, "dataset": "history", "generatedAt": "2026-09-07T00:00:00.000Z",
               "signals": [{"id": str(index), "retainedEvidence": "x" * 5000} for index in range(5000)]}
    write_document(path, payload, 512 * 1024, _atomic_write)
    index = json.loads(path.read_bytes())
    assert index["schemaVersion"] == 2
    assert index["signalCount"] == 5000
    assert path.stat().st_size < 512 * 1024
    assert all((tmp_path / row["path"]).stat().st_size <= PART_BYTES for row in index["partitions"])
    assert read_document(path, 512 * 1024) == payload


@pytest.mark.parametrize("damage", ["missing", "digest", "duplicate", "escape", "count"])
def test_history_partitions_fail_closed_on_incomplete_or_tampered_history(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "history.json"
    payload = {"schemaVersion": 1, "signals": [{"id": index, "evidence": "x" * 1000} for index in range(600)]}
    write_document(path, payload, 512 * 1024, _atomic_write)
    index = json.loads(path.read_bytes())
    part = tmp_path / index["partitions"][0]["path"]
    if damage == "missing":
        part.unlink()
    elif damage == "digest":
        part.write_bytes(b"x" * part.stat().st_size)
    elif damage == "duplicate":
        index["partitions"].append(index["partitions"][0])
    elif damage == "escape":
        index["partitions"][0]["path"] = "../outside.json"
    else:
        index["signalCount"] -= 1
    path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError):
        read_document(path, 512 * 1024)


def test_durable_25000_host_summary_roundtrips_at_finite_partition_budget(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    payload = {"schemaVersion": 1, "dataset": "radar-history-summary", "signals": [
        {"id": index, "recentEventIds": [f"{number:032x}" for number in range(64)]} for index in range(25000)
    ]}
    write_document(path, payload, 12 * 1024 * 1024, _atomic_write)
    assert path.stat().st_size <= 12 * 1024 * 1024
    assert read_document(path, 12 * 1024 * 1024) == payload


def test_successful_rewrite_removes_only_unreferenced_generated_parts(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    payload = {"schemaVersion": 1, "signals": [{"id": index, "evidence": "x" * 1000} for index in range(600)]}
    write_document(path, payload, 512 * 1024, _atomic_write)
    parts = path.parent / "history-parts"
    unrelated = parts / "maintainer-notes.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    small = {"schemaVersion": 1, "signals": payload["signals"][:1]}
    write_document(path, small, 512 * 1024, _atomic_write)
    assert read_document(path, 512 * 1024) == small
    assert list(parts.iterdir()) == [unrelated]


def test_public_history_writer_and_strict_reader_preserve_5000_valid_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    monkeypatch.chdir(tmp_path)
    timestamp = "2026-09-07T00:00:00.000Z"
    rows = []
    for index in range(5000):
        domain = f"swedbank-login-fixture-{index}[.]example"
        rows.append({
            "id": hashlib.sha256(domain.encode()).hexdigest()[:20], "domain": domain, "brand": "Swedbank",
            "firstSeen": timestamp, "lastSeen": timestamp, "observationCount": 1,
            "sources": ["CertStream"], "latestStatus": "suspected", "reasonCodes": ["first-publication"],
            "statusTransitions": [{
                "eventId": f"{index:032x}", "observedAt": timestamp, "previousStatus": None,
                "status": "suspected", "sources": ["CertStream"], "reasonCodes": ["first-publication"],
            }],
        })
    payload = {"schemaVersion": 1, "dataset": "history", "generatedAt": timestamp,
               "detailRetentionDays": 30, "summaryRetentionDays": 730, "signals": rows}
    path = tmp_path / "public/data/history.json"
    _write_public_if_changed(path, payload)
    assert read_public_history(path) == payload
    assert json.loads(path.read_bytes())["signalCount"] == 5000
