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
    elapsed = [0.0]
    monkeypatch.setattr(live_smoke, "monotonic", lambda: elapsed[0], raising=False)
    monkeypatch.setattr(live_smoke, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
                        raising=False)


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
    findings = evaluate_publication(expected, live, live_snapshot, grace_minutes=30,
                                    now=datetime(2026, 8, 30, 12, 31, tzinfo=UTC))
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
        main = '<main id="main-content">Radar</main>'
        marker = live_smoke.NOT_FOUND_MARKER.decode() if expected_status == 404 else main
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
    timeouts: list[float] = []
    identity_requests = 0

    def fetch(base_url: str, path: str, maximum_bytes: int, nonce: str, **kwargs) -> tuple[int, bytes]:
        nonlocal identity_requests
        del base_url, maximum_bytes, nonce
        if "timeout_seconds" in kwargs:
            timeouts.append(kwargs["timeout_seconds"])
        if path == "/.well-known/hecavex-release.json":
            identity_requests += 1
            return 200, json.dumps({"schemaVersion": 1, "repository": "Hecavex/radar.hecavex.com",
                                    "revision": "b" * 40}).encode()
        if path == "/data/feed-manifest.json":
            return 200, json.dumps(manifest).encode()
        if path == "/data/radar.json":
            return 200, snapshot
        _, status, language, canonical = next(route for route in live_smoke.ROUTES if route[0] == path)
        content = live_smoke.NOT_FOUND_MARKER.decode() if status == 404 else '<main id="main-content">Radar</main>'
        return status, f'<html lang="{language}"><link rel="canonical" href="{canonical}">{content}</html>'.encode()

    monkeypatch.setattr(live_smoke, "_fetch", fetch)
    assert live_smoke.main(["--repository", str(tmp_path), "--expected-revision", revision]) == 1
    assert identity_requests == 6
    assert live_smoke.monotonic() == 60
    assert timeouts and all(0 < seconds <= 20 for seconds in timeouts)


def test_propagation_grace_uses_elapsed_time_since_expected_sync() -> None:
    expected_snapshot = _snapshot("2026-08-30T11:55:00.000Z")
    expected = _manifest("2026-08-30T11:55:00.000Z", expected_snapshot)
    live_snapshot = _snapshot("2026-08-30T11:02:00.000Z")
    live = _manifest("2026-08-30T11:02:00.000Z", live_snapshot)
    assert evaluate_publication(expected, live, live_snapshot,
                                now=datetime(2026, 8, 30, 12, tzinfo=UTC)) == []
    findings = evaluate_publication(expected, live, live_snapshot,
                                    now=datetime(2026, 8, 30, 12, 26, tzinfo=UTC))
    assert any("older than" in finding for finding in findings)


@pytest.mark.parametrize("transient", ["identity", "manifest"])
def test_exact_release_waits_until_identity_and_data_are_coherent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transient: str,
) -> None:
    now = "2026-08-30T12:00:00.000Z"
    snapshot = _snapshot(now)
    manifest = _manifest(now, snapshot)
    old_snapshot = _snapshot("2026-08-30T11:50:00.000Z")
    old_manifest = _manifest("2026-08-30T11:50:00.000Z", old_snapshot)
    path = tmp_path / "public/data/feed-manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = {"identity": 0}

    def fetch(base_url: str, route: str, maximum_bytes: int, nonce: str, **kwargs) -> tuple[int, bytes]:
        del base_url, maximum_bytes, nonce, kwargs
        if route == "/.well-known/hecavex-release.json":
            calls["identity"] += 1
            source = "b" * 40 if transient == "identity" and calls["identity"] == 1 else "a" * 40
            return 200, json.dumps({"schemaVersion": 1, "repository": "Hecavex/radar.hecavex.com",
                                    "revision": source, "sourceRevision": source, "dataRevision": "c" * 40}).encode()
        old = transient == "manifest" and calls["identity"] == 1
        if route == "/data/feed-manifest.json":
            return 200, json.dumps(old_manifest if old else manifest).encode()
        if route == "/data/radar.json":
            return 200, old_snapshot if old else snapshot
        _, status, language, canonical = next(row for row in live_smoke.ROUTES if row[0] == route)
        content = live_smoke.NOT_FOUND_MARKER.decode() if status == 404 else '<main id="main-content">Radar</main>'
        return status, f'<html lang="{language}"><link rel="canonical" href="{canonical}">{content}</html>'.encode()

    monkeypatch.setattr(live_smoke, "_fetch", fetch)
    assert live_smoke.main(["--repository", str(tmp_path), "--expected-revision", "a" * 40,
                            "--expected-data-revision", "c" * 40]) == 0
    assert calls["identity"] == 2
    assert live_smoke.monotonic() == 10


def test_corrupt_identity_fails_without_rollout_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "public/data/feed-manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_manifest("2026-08-30T12:00:00.000Z", _snapshot("2026-08-30T12:00:00.000Z"))),
                    encoding="utf-8")
    calls = []

    def fetch(*args, **kwargs):
        calls.append(args)
        return 200, b"not-json"

    monkeypatch.setattr(live_smoke, "_fetch", fetch)
    assert live_smoke.main(["--repository", str(tmp_path), "--expected-revision", "a" * 40]) == 1
    assert len(calls) == 1
    assert live_smoke.monotonic() == 0


def test_exact_release_cannot_pass_after_retry_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = "2026-08-30T12:00:00.000Z"
    snapshot = _snapshot(now)
    manifest = _manifest(now, snapshot)
    path = tmp_path / "public/data/feed-manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    elapsed = [0.0]
    monkeypatch.setattr(live_smoke, "monotonic", lambda: elapsed[0])

    def fetch(base_url: str, route: str, maximum_bytes: int, nonce: str, **kwargs) -> tuple[int, bytes]:
        del base_url, maximum_bytes, nonce, kwargs
        if route == "/.well-known/hecavex-release.json":
            return 200, json.dumps({"schemaVersion": 1, "repository": "Hecavex/radar.hecavex.com",
                                    "revision": "a" * 40}).encode()
        if route == "/data/feed-manifest.json":
            return 200, json.dumps(manifest).encode()
        if route == "/data/radar.json":
            elapsed[0] = 61.0
            return 200, snapshot
        _, status, language, canonical = next(row for row in live_smoke.ROUTES if row[0] == route)
        content = live_smoke.NOT_FOUND_MARKER.decode() if status == 404 else '<main id="main-content">Radar</main>'
        return status, f'<html lang="{language}"><link rel="canonical" href="{canonical}">{content}</html>'.encode()

    monkeypatch.setattr(live_smoke, "_fetch", fetch)
    assert live_smoke.main(["--repository", str(tmp_path), "--expected-revision", "a" * 40]) == 1
