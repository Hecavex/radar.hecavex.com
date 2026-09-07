from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hecavex_radar import live_smoke
from hecavex_radar.live_smoke import evaluate_publication


@pytest.fixture(autouse=True)
def fixed_live_check_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_smoke, "_now", lambda: datetime(2026, 8, 30, 12, tzinfo=UTC))


def test_matching_old_live_and_repository_snapshots_are_not_fresh() -> None:
    snapshot = _snapshot("2026-08-30T12:00:00.000Z")
    manifest = _manifest("2026-08-30T12:00:00.000Z", snapshot)
    findings = evaluate_publication(manifest, manifest, snapshot, now=datetime(2026, 8, 31, tzinfo=UTC))
    assert any("stale in absolute time" in finding for finding in findings)


def _snapshot(generated_at: str, synced_at: str | None = None) -> bytes:
    return (
        json.dumps(
            {
                "schemaVersion": 2,
                "dataset": "live",
                "generatedAt": generated_at,
                "lastSuccessfulSyncAt": synced_at or generated_at,
                "signals": [],
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _manifest(generated_at: str, snapshot: bytes) -> dict[str, object]:
    return {
        "generatedAt": generated_at,
        "artifacts": [
            {
                "path": "/data/radar.json",
                "bytes": len(snapshot),
                "sha256": hashlib.sha256(snapshot).hexdigest(),
            }
        ],
    }


def test_live_publication_accepts_atomic_current_snapshot() -> None:
    generated_at = "2026-08-30T12:00:00.000Z"
    snapshot = _snapshot(generated_at)
    manifest = _manifest(generated_at, snapshot)
    assert evaluate_publication(manifest, manifest, snapshot) == []


def test_live_publication_accepts_heartbeat_without_a_material_data_change() -> None:
    synced_at = "2026-08-30T12:00:00.000Z"
    snapshot = _snapshot("2026-08-30T10:00:00.000Z", synced_at)
    manifest = _manifest(synced_at, snapshot)
    assert evaluate_publication(manifest, manifest, snapshot) == []


def test_live_publication_rejects_stale_or_non_atomic_snapshot() -> None:
    expected_snapshot = _snapshot("2026-08-30T12:00:00.000Z")
    expected = _manifest("2026-08-30T12:00:00.000Z", expected_snapshot)
    live_snapshot = _snapshot("2026-08-30T09:00:00.000Z", "2026-08-30T10:00:00.000Z")
    live = _manifest("2026-08-30T10:00:00.000Z", live_snapshot)
    live["generatedAt"] = "2026-08-30T10:05:00.000Z"
    findings = evaluate_publication(expected, live, live_snapshot, grace_minutes=30)
    assert any("older than" in finding for finding in findings)
    assert any("atomic synchronization timestamp" in finding for finding in findings)


def test_live_publication_rejects_manifest_digest_drift() -> None:
    generated_at = "2026-08-30T12:00:00.000Z"
    snapshot = _snapshot(generated_at)
    manifest = _manifest(generated_at, snapshot)
    artifact = manifest["artifacts"][0]
    assert isinstance(artifact, dict)
    artifact["sha256"] = "0" * 64
    findings = evaluate_publication(manifest, manifest, snapshot)
    assert any("digest" in finding for finding in findings)


def test_same_sync_compares_live_artifact_with_checked_in_artifact() -> None:
    synced_at = "2026-08-30T12:00:00.000Z"
    expected_snapshot = _snapshot("2026-08-30T10:00:00.000Z", synced_at)
    live_snapshot = _snapshot("2026-08-30T11:00:00.000Z", synced_at)
    expected_manifest = _manifest(synced_at, expected_snapshot)
    live_manifest = _manifest(synced_at, live_snapshot)

    findings = evaluate_publication(expected_manifest, live_manifest, live_snapshot)

    assert any("checked-in artifact" in finding for finding in findings)


def test_live_smoke_retries_one_transitional_manifest_snapshot_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced_at = "2026-08-30T12:00:00.000Z"
    current_snapshot = _snapshot("2026-08-30T10:00:00.000Z", synced_at)
    current_manifest = _manifest(synced_at, current_snapshot)
    transition_snapshot = _snapshot("2026-08-30T09:00:00.000Z", "2026-08-30T11:00:00.000Z")
    expected_path = tmp_path / "public" / "data" / "feed-manifest.json"
    expected_path.parent.mkdir(parents=True)
    expected_path.write_text(json.dumps(current_manifest), encoding="utf-8")
    calls = {"manifest": 0, "snapshot": 0}

    def fake_fetch(base_url: str, path: str, maximum_bytes: int, nonce: str) -> tuple[int, bytes]:
        del base_url, maximum_bytes, nonce
        if path == "/data/feed-manifest.json":
            calls["manifest"] += 1
            return 200, (json.dumps(current_manifest) + "\n").encode()
        if path == "/data/radar.json":
            calls["snapshot"] += 1
            payload = transition_snapshot if calls["snapshot"] == 1 else current_snapshot
            return 200, payload
        expected_route = next(route for route in live_smoke.ROUTES if route[0] == path)
        _, expected_status, language, canonical = expected_route
        canonical_markup = f'<link rel="canonical" href="{canonical}">' if canonical else ""
        marker = "This route has no signal." if expected_status == 404 else '<main id="main-content">Radar</main>'
        return expected_status, f'<html lang="{language}">{canonical_markup}{marker}</html>'.encode()

    monkeypatch.setattr(live_smoke, "_fetch", fake_fetch)

    assert live_smoke.main(["--repository", str(tmp_path), "--base-url", "https://radar.example"]) == 0
    assert calls == {"manifest": 2, "snapshot": 2}


def test_deployment_checks_exact_commit_even_when_snapshot_is_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    synced_at = "2026-08-30T12:00:00.000Z"
    snapshot = _snapshot(synced_at)
    manifest = _manifest(synced_at, snapshot)
    expected_path = tmp_path / "public" / "data" / "feed-manifest.json"
    expected_path.parent.mkdir(parents=True)
    expected_path.write_text(json.dumps(manifest), encoding="utf-8")

    def fetch(base_url: str, path: str, maximum_bytes: int, nonce: str) -> tuple[int, bytes]:
        del base_url, maximum_bytes, nonce
        if path == "/.well-known/hecavex-release.json":
            return 200, json.dumps({"schemaVersion": 1, "repository": "Hecavex/radar.hecavex.com",
                                    "revision": "b" * 40}).encode()
        if path == "/data/feed-manifest.json":
            return 200, json.dumps(manifest).encode()
        if path == "/data/radar.json":
            return 200, snapshot
        _, status, language, canonical = next(route for route in live_smoke.ROUTES if route[0] == path)
        content = 'This route has no signal.' if status == 404 else '<main id="main-content">Radar</main>'
        return status, f'<html lang="{language}"><link rel="canonical" href="{canonical}">{content}</html>'.encode()

    monkeypatch.setattr(live_smoke, "_fetch", fetch)
    assert live_smoke.main(["--repository", str(tmp_path), "--expected-revision", revision]) == 1
