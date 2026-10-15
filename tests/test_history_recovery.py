from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hecavex_radar.history import _event_identifier
from hecavex_radar.normalize import stable_id


def git(root: Path, *args: str, payload: bytes | None = None) -> str:
    executable = shutil.which("git")
    assert executable is not None
    result = subprocess.run(  # noqa: S603 - trusted Git, test-created data and no shell.
        [executable, "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false",
         "-c", f"core.hooksPath={root / 'no-hooks'}", "-c", "commit.gpgsign=false",
         "-C", str(root), *args], input=payload, capture_output=True, check=True,
    )
    return result.stdout.decode().strip()


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "archive"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Recovery test")
    git(root, "config", "user.email", "recovery@example.invalid")
    return root


def event(day: str, *, confidence: int = 80, transition: bool = False) -> dict[str, object]:
    domain = "revolut-login[.]example"
    payload = {"schemaVersion": 1, "signalId": stable_id(domain),
               "eventType": "status-transition" if transition else "observation",
               "observedAt": f"{day}T12:00:00.000Z", "domain": domain, "brand": "Revolut",
               "sources": ["CertStream"], "status": "suspected", "previousStatus": None,
               "confidence": confidence,
               "reasonCodes": ["first-publication"] if transition else ["brand-domain-match"]}
    return {**payload, "eventId": _event_identifier(payload)}


def commit_day(root: Path, day: str, events: list[dict[str, object]]) -> str:
    path = root / f"data/history/daily/{day}/events.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in events), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "Archive accepted facts")
    return git(root, "rev-parse", "HEAD")


def recover():
    assert importlib.util.find_spec("hecavex_radar.history_recovery") is not None, "Bounded Git recovery is required."
    return importlib.import_module("hecavex_radar.history_recovery").recover_git_history


def test_recovery_discovers_deleted_partitions_and_preserves_annotation_variants(tmp_path: Path) -> None:
    root = repository(tmp_path)
    commit_day(root, "2026-09-01", [event("2026-09-01", confidence=90), event("2026-09-01", transition=True)])
    commit_day(root, "2026-09-01", [event("2026-09-01", confidence=80), event("2026-09-01", transition=True)])
    commit_day(root, "2026-09-02", [event("2026-09-02")])
    git(root, "rm", "data/history/daily/2026-09-01/events.ndjson")
    git(root, "commit", "-m", "Compact old detail")
    head = git(root, "rev-parse", "HEAD")

    result = recover()(root, [], "2026-09-01T00:00:00.000Z", "2026-09-04T00:00:00.000Z",
                       trusted_heads=[head], imported_at="2026-10-15T12:00:00.000Z")

    assert result["observationCount"] == 2
    assert len(result["observations"]) == 3
    assert {row["originalMatch"]["legacyConfidence"] for row in result["observations"]} == {80, 90}
    assert all(row["radarRecordedAt"] is None and row["providerEventId"] is None
               for row in result["observations"])
    assert all(row["sourceTimeProvenance"] == "legacy-history-boundary" for row in result["observations"])
    assert len(result["legacyEvents"]) == 4
    assert result["coverage"]["missingDays"] == ["2026-09-03"]
    assert result["coverage"]["completeCollection"] is False
    assert all(len(row["sha256"]) == 64 and len(row["commit"]) == 40 for row in result["blobs"])
    assert result == recover()(root, [], "2026-09-01T00:00:00.000Z", "2026-09-04T00:00:00.000Z",
                               trusted_heads=[head], imported_at="2026-10-15T12:00:00.000Z")


def test_recovery_rejects_revision_outside_pinned_trusted_ancestry(tmp_path: Path) -> None:
    root = repository(tmp_path)
    trusted = commit_day(root, "2026-09-01", [event("2026-09-01")])
    foreign = commit_day(root, "2026-09-02", [event("2026-09-02")])
    with pytest.raises(ValueError, match="trusted"):
        recover()(root, [foreign], "2026-09-01T00:00:00.000Z", "2026-09-04T00:00:00.000Z",
                  trusted_heads=[trusted])


def test_recovery_rejects_nonregular_historical_blob(tmp_path: Path) -> None:
    root = repository(tmp_path)
    oid = git(root, "hash-object", "-w", "--stdin", payload=b"../../outside.json")
    git(root, "update-index", "--add", "--cacheinfo", "120000", oid,
        "data/history/daily/2026-09-01/events.ndjson")
    git(root, "commit", "-m", "Unsafe historical link")
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="regular"):
        recover()(root, [], "2026-09-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z", trusted_heads=[head])


def test_recovery_rejects_invalid_event_identity_and_partial_day_stays_explicit(tmp_path: Path) -> None:
    root = repository(tmp_path)
    bad = {**event("2026-09-01"), "observedAt": "2026-09-01T13:00:00.000Z"}
    head = commit_day(root, "2026-09-01", [bad])
    with pytest.raises(ValueError, match="event"):
        recover()(root, [head], "2026-09-01T00:00:00.000Z", "2026-09-01T14:00:00.000Z",
                  trusted_heads=[head])
    head = commit_day(root, "2026-09-01", [event("2026-09-01")])
    result = recover()(root, [head], "2026-09-01T00:00:00.000Z", "2026-09-01T14:00:00.000Z",
                       trusted_heads=[head])
    assert result["coverage"]["partialDays"] == ["2026-09-01"]


def test_recovery_checkpoint_resumes_exactly_and_rejects_corruption(tmp_path: Path) -> None:
    module = importlib.import_module("hecavex_radar.history_recovery")
    root = repository(tmp_path)
    head = commit_day(root, "2026-09-01", [event("2026-09-01")])
    output = tmp_path / "recovered"
    args = ["--repository", str(root), "--trusted-head", head, "--start", "2026-09-01T00:00:00.000Z",
            "--end", "2026-09-02T00:00:00.000Z", "--output", str(output)]
    assert module.main(args) == 0
    before = (output / "recovery.json").read_bytes()
    assert module.main(args) == 0
    assert (output / "recovery.json").read_bytes() == before
    (output / "recovery.sha256").write_text("0" * 64 + "  recovery.json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint.*digest"):
        module.main(args)


def test_recovery_refuses_linked_checkpoint_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("hecavex_radar.history_recovery")
    root = repository(tmp_path)
    head = commit_day(root, "2026-09-01", [event("2026-09-01")])
    output = tmp_path / "recovered"
    output.mkdir()
    target = output / "recovery.json"
    target.write_text("do not read this linked target", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError, match="linked checkpoint"):
        module.main(["--repository", str(root), "--trusted-head", head, "--start", "2026-09-01T00:00:00.000Z",
                     "--end", "2026-09-02T00:00:00.000Z", "--output", str(output)])


@pytest.mark.parametrize("budget", ["MAXIMUM_COMMITS", "MAXIMUM_FILE_BYTES"])
def test_recovery_refuses_partial_result_when_a_budget_is_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: str,
) -> None:
    module = importlib.import_module("hecavex_radar.history_recovery")
    root = repository(tmp_path)
    commit_day(root, "2026-09-01", [event("2026-09-01")])
    head = commit_day(root, "2026-09-02", [event("2026-09-02")])
    monkeypatch.setattr(module, budget, 1)
    with pytest.raises(ValueError, match="budget"):
        module.recover_git_history(root, [], "2026-09-01T00:00:00.000Z", "2026-09-03T00:00:00.000Z",
                                   trusted_heads=[head])
