from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hecavex_radar import publication_selection
from hecavex_radar.live_smoke import matches_release_identity

SOURCE = "a" * 40
DATA = "b" * 40
OLD = "c" * 40


@pytest.mark.parametrize("source,data,publication,expected", [
    (SOURCE, DATA, OLD, SOURCE),
    (SOURCE, DATA, SOURCE, OLD),
    (SOURCE, "", SOURCE, SOURCE),
    (SOURCE, DATA, "", SOURCE),
    ("main", DATA, SOURCE, SOURCE),
])
def test_stale_or_missing_selection_fails_closed(source: str, data: str, publication: str, expected: str) -> None:
    with pytest.raises(ValueError):
        publication_selection.validate_selection(source, data, publication, expected)


def test_current_selection_retains_distinct_source_and_data() -> None:
    publication_selection.validate_selection(SOURCE, DATA, SOURCE, SOURCE)


@pytest.mark.parametrize("remote_source,remote_data", [(OLD, DATA), (SOURCE, OLD), (SOURCE, "")])
def test_source_or_data_advancing_during_build_refuses_deploy(
    monkeypatch: pytest.MonkeyPatch, remote_source: str, remote_data: str,
) -> None:
    monkeypatch.setattr(publication_selection, "_git", lambda *args:
        f"{remote_source}\trefs/heads/main\n{remote_data}\trefs/heads/radar-data")
    with pytest.raises(ValueError, match="advanced"):
        publication_selection.verify_current(Path.cwd(), SOURCE, DATA)


def test_completion_data_must_be_an_ancestor_of_selected_data(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def git(repository: Path, *args: str) -> str:
        del repository
        calls.append(args)
        if args[0] == "ls-remote":
            return f"{SOURCE}\trefs/heads/main\n{DATA}\trefs/heads/radar-data"
        raise subprocess.CalledProcessError(1, "git merge-base")

    monkeypatch.setattr(publication_selection, "_git", git)
    with pytest.raises(subprocess.CalledProcessError):
        publication_selection.verify_current(Path.cwd(), SOURCE, DATA, OLD)
    assert calls[-1] == ("merge-base", "--is-ancestor", OLD, DATA)


def test_missing_writer_data_never_deploys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication_selection, "_git", lambda *args:
        f"{SOURCE}\trefs/heads/main\n{DATA}\trefs/heads/radar-data")
    with pytest.raises(ValueError, match="writer completion"):
        publication_selection.verify_current(Path.cwd(), SOURCE, DATA, "")


def test_real_offline_git_accepts_newer_health_data_but_rejects_newer_source(tmp_path: Path) -> None:
    executable = shutil.which("git")
    assert executable is not None
    repository = tmp_path / "source"
    repository.mkdir()
    remote = tmp_path / "remote.git"

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - controlled local Git fixture, no shell or network.
            [executable, "-C", str(repository), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "Synthetic test")
    git("config", "user.email", "synthetic@example.invalid")
    git("init", "--bare", str(remote))
    git("remote", "add", "origin", str(remote))
    (repository / "source.txt").write_text("trusted code fixture", encoding="utf-8")
    git("add", "source.txt")
    git("commit", "-m", "source")
    source = git("rev-parse", "HEAD")
    git("push", "origin", "main")
    git("switch", "-c", "radar-data")
    (repository / "health.json").write_text('{"status":"healthy"}', encoding="utf-8")
    git("add", "health.json")
    git("commit", "-m", "publication")
    initial_data = git("rev-parse", "HEAD")
    (repository / "health.json").write_text('{"status":"degraded"}', encoding="utf-8")
    git("commit", "-am", "failure health")
    data = git("rev-parse", "HEAD")
    git("push", "origin", "radar-data")
    git("switch", "main")
    publication_selection.verify_current(repository, source, data, initial_data)
    git("commit", "--allow-empty", "-m", "new source")
    git("push", "origin", "main")
    with pytest.raises(ValueError, match="advanced"):
        publication_selection.verify_current(repository, source, data, initial_data)


def test_dual_revision_live_identity_rejects_selected_data_drift() -> None:
    release: dict[str, object] = {
        "schemaVersion": 1, "repository": "Hecavex/radar.hecavex.com",
        "revision": SOURCE, "sourceRevision": SOURCE, "dataRevision": DATA,
    }
    assert matches_release_identity(release, SOURCE, DATA)
    assert not matches_release_identity(release, SOURCE, OLD)
    assert not matches_release_identity(release, OLD, DATA)
    del release["sourceRevision"]
    assert not matches_release_identity(release, SOURCE, DATA)
    assert matches_release_identity(release, SOURCE)


def test_readers_keep_trusted_tooling_separate_from_selected_data() -> None:
    root = Path(__file__).resolve().parents[1]
    workflows = root / ".github" / "workflows"
    deploy = (workflows / "deploy-pages.yml").read_text(encoding="utf-8")
    assert "--view operational" in deploy
    assert "--trigger-data" in deploy
    assert "publication_source_revision" in deploy
    assert "--expected-data-revision" in deploy
    assert deploy.index("Refuse source or data superseded") < deploy.index("- name: Deploy to GitHub Pages")
    for name in ("deploy-pages", "release-weekly-dataset", "verify-live-publication",
                 "evaluate-pipeline-health", "analyst-provider-check"):
        value = (workflows / f"{name}.yml").read_text(encoding="utf-8")
        assert "hecavex_radar.data_branch materialize" in value
        assert "ref: radar-data" not in value
    weekly = (workflows / "release-weekly-dataset.yml").read_text(encoding="utf-8")
    assert "--view publication" in weekly
    assert "Legacy backfill" in weekly and "inputs.data_sha" in weekly
    assert "source_sha or data_sha, never both" in weekly
    assert "hecavex_radar.release_source" in weekly
    assert 'ref: ${{ inputs.data_sha' not in weekly
    for name in ("verify-live-publication", "evaluate-pipeline-health"):
        value = (workflows / f"{name}.yml").read_text(encoding="utf-8")
        assert "continue-on-error: true" in value
        assert "unhealthy=true" in value
