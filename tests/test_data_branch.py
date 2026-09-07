"""Real disposable Git remotes exercise the source/data cutover and publication races."""

import json
from pathlib import Path

import pytest

from hecavex_radar import data_branch as transport


def write(repository: Path, path: str, value: bytes) -> None:
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)


def source_commit(repository: Path, message: str) -> str:
    transport.git(repository, "add", ".")
    transport.git(repository, "commit", "-m", message)
    transport.git(repository, "push", "origin", "HEAD:main")
    return transport.head(repository)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    transport.git(remote, "init", "--bare")
    repository = tmp_path / "source"
    repository.mkdir()
    transport.git(repository, "init", "-b", "main")
    transport.git(repository, "config", "user.name", "Fixture")
    transport.git(repository, "config", "user.email", "fixture@example.invalid")
    transport.git(repository, "remote", "add", "origin", str(remote))
    write(repository, "trusted.py", b"raise RuntimeError('must never execute historical code')\n")
    write(repository, "data/brands-lt.json", b'{"reviewed":true}')
    write(repository, "data/certstream/2026-09-07/domains.ndjson", b'{"domain":"original.invalid"}\n')
    write(repository, "public/data/radar.json", b'{"generatedAt":"2026-09-07T00:00:00Z"}')
    source_commit(repository, "initial source and data")
    return repository


def command(repo: Path, *args: str) -> int:
    return transport.main([args[0], "--repository", str(repo), *args[1:]])


def bootstrap(repo: Path) -> str:
    assert command(repo, "bootstrap", "--source-revision", transport.head(repo), "--push") == 0
    selected = transport.remote(repo, "radar-data")
    assert selected is not None
    return selected


def hydrate(repo: Path, state: Path) -> str:
    assert command(repo, "materialize", "--state-file", str(state)) == 0
    value: str = json.loads(state.read_bytes())["data_revision"]
    return value


def advance_data(repo: Path, base: str, files: dict[str, bytes], writer: str = "snapshot") -> str:
    selected = transport.commit_data(repo, files, transport.head(repo), base, writer, "concurrent fixture")
    transport.git(repo, "push", "origin", f"{selected}:refs/heads/radar-data")
    return selected


def test_missing_branch_fails_closed_without_overlay(repo: Path, tmp_path: Path) -> None:
    before = (repo / "public/data/radar.json").read_bytes()
    assert command(repo, "materialize", "--state-file", str(tmp_path / "state")) == 1
    assert (repo / "public/data/radar.json").read_bytes() == before
    assert not (tmp_path / "state").exists()


def test_bootstrap_exact_postmerge_inventory_retains_late_main_data(repo: Path) -> None:
    old = transport.head(repo)
    write(repo, "data/certstream/2026-09-07/attempts.ndjson", b'{"outcome":"partial"}\n')
    merged = source_commit(repo, "late operational update included by migration merge")
    assert command(repo, "bootstrap", "--source-revision", old, "--push") == 1
    selected = bootstrap(repo)
    files = transport.blobs(repo, selected)
    assert files["data/certstream/2026-09-07/attempts.ndjson"] == b'{"outcome":"partial"}\n'
    assert transport.validate(files)["sourceRevision"] == merged
    assert "trusted.py" not in files and "data/brands-lt.json" not in files
    assert transport.PUBLICATION not in files
    assert command(repo, "bootstrap", "--source-revision", merged, "--push") == 1


def test_collector_preserves_completed_window_across_unrelated_snapshot(repo: Path, tmp_path: Path) -> None:
    bootstrap(repo)
    state = tmp_path / "state"
    base = hydrate(repo, state)
    local = b'{"domain":"original.invalid"}\n{"domain":"new.invalid"}\n'
    write(repo, "data/certstream/2026-09-07/domains.ndjson", local)
    concurrent = transport.blobs(repo, base)
    concurrent["public/data/radar.json"] = b'{"generatedAt":"2026-09-07T01:00:00Z"}'
    concurrent[transport.PUBLICATION] = transport.encode({"schemaVersion": 1,
        "sourceRevision": transport.head(repo), "inputDataRevision": base, "generatedAt": "2026-09-07T01:00:00Z"})
    latest = advance_data(repo, base, concurrent)
    assert command(repo, "publish", "--state-file", str(state), "--writer", "certstream") == 0
    selected = transport.remote(repo, "radar-data")
    assert selected is not None
    result = transport.blobs(repo, selected)
    assert result["data/certstream/2026-09-07/domains.ndjson"] == local
    assert result["public/data/radar.json"] == concurrent["public/data/radar.json"]
    assert result[transport.PUBLICATION] == concurrent[transport.PUBLICATION]
    assert transport.validate(result)["baseDataRevision"] == latest


@pytest.mark.parametrize("writer", ["snapshot", "certstream"])
def test_changed_input_or_same_writer_conflict_refuses(repo: Path, tmp_path: Path, writer: str) -> None:
    bootstrap(repo)
    state = tmp_path / "state"
    base = hydrate(repo, state)
    changed_path = "public/data/radar.json" if writer == "snapshot" else "data/certstream/local.json"
    write(repo, changed_path, b'{"generatedAt":"2026-09-07T01:00:00Z"}')
    concurrent = transport.blobs(repo, base)
    concurrent["data/certstream/2026-09-07/attempts.ndjson"] = b'{"outcome":"partial"}\n'
    latest = advance_data(repo, base, concurrent, "certstream")
    assert command(repo, "publish", "--state-file", str(state), "--writer", writer) == 1
    assert transport.remote(repo, "radar-data") == latest


def test_stale_source_refuses_even_when_only_source_configuration_changed(repo: Path, tmp_path: Path) -> None:
    base = bootstrap(repo)
    state = tmp_path / "state"
    hydrate(repo, state)
    # A separate source checkout advances main; the old running writer remains at its old HEAD.
    other = tmp_path / "other"
    transport.git(repo, "clone", "--branch", "main", str(tmp_path / "remote.git"), str(other))
    transport.git(other, "config", "user.name", "Fixture")
    transport.git(other, "config", "user.email", "fixture@example.invalid")
    write(other, "data/brands-lt.json", b'{"reviewed":"new"}')
    source_commit(other, "reviewed source change")
    write(repo, "data/certstream/local.json", b"{}")
    assert command(repo, "publish", "--state-file", str(state), "--writer", "certstream") == 1
    assert transport.remote(repo, "radar-data") == base


def test_snapshot_marker_and_publication_selection(repo: Path, tmp_path: Path) -> None:
    bootstrap(repo)
    state = tmp_path / "state"
    base = hydrate(repo, state)
    write(repo, "public/data/radar.json", b'{"generatedAt":"2026-09-07T01:00:00Z"}')
    assert command(repo, "publish", "--state-file", str(state), "--writer", "snapshot") == 0
    published = transport.remote(repo, "radar-data")
    assert published is not None
    files = transport.blobs(repo, published)
    marker = json.loads(files[transport.PUBLICATION])
    assert marker["inputDataRevision"] == base
    assert marker["sourceRevision"] == transport.head(repo)
    files["data/certstream/later.json"] = b"{}"
    latest = advance_data(repo, published, files, "certstream")
    output = tmp_path / "outputs"
    assert command(repo, "materialize", "--view", "publication", "--revision", latest,
                   "--github-output", str(output)) == 0
    assert f"data_revision={published}\n" in output.read_text()
    assert not (repo / "data/certstream/later.json").exists()
    assert (repo / "data/brands-lt.json").exists()


def test_fixture_cannot_publish(repo: Path, tmp_path: Path) -> None:
    bootstrap(repo)
    state = tmp_path / "fixture"
    assert command(repo, "materialize-fixture", "--revision", transport.head(repo), "--state-file", str(state)) == 0
    assert command(repo, "publish", "--state-file", str(state), "--writer", "certstream") == 1


def test_writer_scope_rejects_unrelated_data(repo: Path, tmp_path: Path) -> None:
    base = bootstrap(repo)
    state = tmp_path / "state"
    hydrate(repo, state)
    write(repo, "public/data/radar.json", b"{}")
    assert command(repo, "publish", "--state-file", str(state), "--writer", "certstream") == 1
    assert transport.remote(repo, "radar-data") == base


def test_complete_merged_inventory_capacity_is_checked(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "MAX_TOTAL", 10)
    with pytest.raises(ValueError, match="Complete data commit"):
        transport.commit_data(repo, {"data/certstream/a.json": b"{}"}, transport.head(repo), None, "bootstrap", "cap")


@pytest.mark.parametrize("path", ["../data/x.json", "/public/data/x.json", "public/data/../x.json",
                                  "public/data/x.py", ".github/workflows/a.json", "data/brands-lt.json",
                                  "data/review/public-decisions.json", "public/data/x.json:stream"])
def test_path_boundary(path: str) -> None:
    assert not transport.allowed(path)


def test_manifest_tamper_fails_before_overlay(repo: Path, tmp_path: Path) -> None:
    base = bootstrap(repo)
    files = transport.blobs(repo, base)
    files["public/data/radar.json"] = b"tampered"
    with pytest.raises(ValueError, match="inventory mismatch"):
        transport.validate(files)
    with pytest.raises(ValueError, match="Non-data path"):
        transport.blobs(repo, transport.head(repo))


def test_unreachable_data_revision_refused(repo: Path) -> None:
    bootstrap(repo)
    assert command(repo, "materialize", "--revision", transport.head(repo)) == 1


def test_unchanged_bootstrap_snapshot_still_establishes_publication(repo: Path, tmp_path: Path) -> None:
    bootstrap(repo)
    state = tmp_path / "state"
    hydrate(repo, state)
    assert command(repo, "publish", "--state-file", str(state), "--writer", "snapshot") == 0
    selected = transport.remote(repo, "radar-data")
    assert selected is not None
    assert transport.PUBLICATION in transport.blobs(repo, selected)


def test_all_seven_writers_fail_closed_and_never_push_source() -> None:
    root = Path(__file__).resolve().parents[1]
    writers = {"collect-certstream": "certstream", "sync-radar": "snapshot", "poll-ct-search": "ct-search",
               "hunt-urlscan": "urlscan", "hunt-brand-assets": "brand-assets",
               "enrich-domain-context": "domain-context", "refresh-passive-context": "passive-context"}
    for name, writer in writers.items():
        workflow = (root / f".github/workflows/{name}.yml").read_text()
        assert "if: github.ref == 'refs/heads/main'" in workflow
        assert "hecavex_radar.data_branch materialize" in workflow
        assert "steps.data.outcome == 'success'" in workflow
        assert f"--writer {writer}" in workflow
        assert "HEAD:main" not in workflow and "git rebase" not in workflow


def test_executable_data_blob_refused(repo: Path) -> None:
    path = "public/data/radar.json"
    transport.git(repo, "update-index", "--chmod=+x", path)
    transport.git(repo, "commit", "-m", "invalid executable data")
    with pytest.raises(ValueError, match="non-executable regular blob"):
        transport.blobs(repo, transport.head(repo), source_tree=True)
