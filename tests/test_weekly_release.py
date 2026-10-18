"""Weekly dataset release logic, exercised without GitHub or the network."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hecavex_radar import weekly_release

REPOSITORY = Path(__file__).resolve().parents[1]
TRUSTED = "a" * 40
SOURCE = "b" * 40
OTHER = "c" * 40
BLOB = "d" * 40
REPO = "Hecavex/radar.hecavex.com"
MANIFEST = json.dumps({"generatedAt": "2026-10-05T06:00:00Z"})  # ISO 2026-W41
ASSETS = "SHA256SUMS,radar-data-2026-W41.manifest.json,radar-data-2026-W41.spdx.json,radar-data-2026-W41.tar.gz"


class FakeRunner:
    """Answers exact commands; anything unexpected fails the test instead of reaching the network."""

    def __init__(self, answers: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str], *, quiet: bool = False) -> tuple[int, str]:
        key = tuple(args)
        self.calls.append(key)
        assert key in self.answers, f"unexpected command: {key}"
        return self.answers[key]


def releases_page(*releases: dict[str, object]) -> str:
    return json.dumps(list(releases))


def release(tag: str = "radar-data-2026-W41", *, draft: bool = False, target: str = SOURCE,
            immutable: bool = True, assets: str = ASSETS) -> dict[str, object]:
    return {"id": 7, "tag_name": tag, "draft": draft, "target_commitish": target, "immutable": immutable,
            "assets": [{"name": name} for name in reversed(assets.split(","))]}


def base_answers(*, page: str = "[]", manifest: str = MANIFEST, size: str | None = None,
                 entry: str | None = None) -> dict[tuple[str, ...], tuple[int, str]]:
    return {
        ("git", "rev-parse", "HEAD"): (0, TRUSTED + "\n"),
        ("git", "ls-tree", SOURCE, "--", "public/data/feed-manifest.json"):
            (0, entry if entry is not None else f"100644 blob {BLOB}\tpublic/data/feed-manifest.json\n"),
        ("git", "cat-file", "-s", BLOB): (0, (size or str(len(manifest))) + "\n"),
        ("git", "cat-file", "blob", BLOB): (0, manifest),
        ("gh", "api", "--paginate", f"repos/{REPO}/releases?per_page=100"): (0, page),
    }


def env(**overrides: str) -> dict[str, str]:
    value = {"GITHUB_SHA": TRUSTED, "GITHUB_REPOSITORY": REPO, "REQUESTED_RELEASE_WEEK": "",
             "REQUESTED_SOURCE_SHA": "", "REQUESTED_DATA_SHA": "", "SELECTED_DATA_SHA": SOURCE,
             "CORRECTION_REVISION": ""}
    value.update(overrides)
    return value


def select(answers: dict[tuple[str, ...], tuple[int, str]], **overrides: str) -> dict[str, str]:
    return weekly_release.select_release(env(**overrides), FakeRunner(answers), sleep=lambda _: None)


def refused(answers: dict[tuple[str, ...], tuple[int, str]], message: str, **overrides: str) -> None:
    with pytest.raises(weekly_release.Refused, match=message):
        select(answers, **overrides)


# select-release ---------------------------------------------------------------------------------------------------

def test_select_new_weekly_release_from_publication_snapshot() -> None:
    assert select(base_answers()) == {
        "week": "2026-W41", "base_tag": "radar-data-2026-W41", "tag": "radar-data-2026-W41",
        "correction_revision": "", "source_sha": SOURCE, "trusted_sha": TRUSTED,
        "should_release": "true", "resume_draft": "false",
    }


def test_select_correction_requires_published_immutable_base() -> None:
    answers = base_answers()
    lookup = ("gh", "api", f"repos/{REPO}/releases/tags/radar-data-2026-W41")
    answers[lookup] = (0, json.dumps({"draft": False, "immutable": True}))
    outputs = select(answers, CORRECTION_REVISION="2")
    assert (outputs["tag"], outputs["week"], outputs["correction_revision"]) == (
        "radar-data-2026-W41-r2", "2026-W41-r2", "2")
    answers[lookup] = (1, '{"message":"Not Found"}')
    refused(answers, "A published immutable radar-data-2026-W41 release is required", CORRECTION_REVISION="2")
    refused(answers, "correction_revision must be an integer from 1 to 999", CORRECTION_REVISION="01")


def test_select_existing_immutable_release_is_verified_noop(capsys: pytest.CaptureFixture[str]) -> None:
    answers = base_answers(page=releases_page(release()))
    answers[("git", "fetch", "--no-tags", "origin", "main", "radar-data")] = (0, "")
    answers[("git", "merge-base", "--is-ancestor", SOURCE, "origin/main")] = (1, "")
    answers[("git", "merge-base", "--is-ancestor", SOURCE, "origin/radar-data")] = (0, "")
    content = base64.encodebytes(MANIFEST.encode()).decode()
    answers[("gh", "api", f"repos/{REPO}/contents/public/data/feed-manifest.json?ref={SOURCE}", "--jq",
             ".content")] = (0, content)
    outputs = select(answers)
    assert (outputs["should_release"], outputs["resume_draft"]) == ("false", "false")
    assert "radar-data-2026-W41 is already published and immutable; this run is a no-op." in capsys.readouterr().out
    answers[("git", "merge-base", "--is-ancestor", SOURCE, "origin/radar-data")] = (1, "")
    refused(answers, "does not target an approved source/data history")


def test_select_existing_release_refusals() -> None:
    refused(base_answers(page=releases_page(release(immutable=False))), "exists but is not immutable")
    refused(base_answers(page=releases_page(release(assets="SHA256SUMS"))),
            "unexpected asset inventory: SHA256SUMS")
    refused(base_answers(page=releases_page(release(assets=""))), "unexpected asset inventory: none")
    refused(base_answers(page=releases_page(release(target="main"))), "does not target one auditable commit SHA")
    refused(base_answers(page=releases_page(release(draft=True, target=OTHER))),
            f"Draft radar-data-2026-W41 targets {OTHER}, not {SOURCE}")


def test_select_resumes_same_target_draft_across_pages() -> None:
    page = releases_page(release("radar-data-2026-W40")) + "\n" + releases_page(release(draft=True))
    outputs = select(base_answers(page=page))
    assert (outputs["should_release"], outputs["resume_draft"]) == ("true", "true")


def test_select_retries_release_lookup_then_refuses() -> None:
    answers = base_answers()
    answers[("gh", "api", "--paginate", f"repos/{REPO}/releases?per_page=100")] = (1, "")
    sleeps: list[int] = []
    with pytest.raises(weekly_release.Refused, match="after bounded retries"):
        weekly_release.select_release(env(), FakeRunner(answers), sleep=sleeps.append)
    assert sleeps == [1, 2, 3, 4]


def test_select_input_and_snapshot_refusals() -> None:
    refused(base_answers(), "Trusted tooling checkout does not match", GITHUB_SHA=OTHER)
    refused(base_answers(), "Selected data must identify one full commit", SELECTED_DATA_SHA="B" * 40)
    refused(base_answers(), "data_sha must itself be a coherent publication commit", REQUESTED_DATA_SHA=OTHER)
    refused(base_answers(entry=""), "not one regular data blob")
    refused(base_answers(entry=f"120000 blob {BLOB}\tpublic/data/feed-manifest.json"), "not one regular data blob")
    refused(base_answers(size="262145"), "empty or exceeds 256 KiB")
    refused(base_answers(), "canonical YYYY-Www syntax", REQUESTED_RELEASE_WEEK="2026-W54")
    refused(base_answers(), "release_week 2026-W40 does not match snapshot week 2026-W41",
            REQUESTED_RELEASE_WEEK="2026-W40")


def test_select_legacy_source_must_descend_into_main() -> None:
    answers = base_answers()
    compare = ("gh", "api", f"repos/{REPO}/compare/{SOURCE}...main", "--jq", ".status")
    answers[compare] = (0, "behind\n")
    refused(answers, "must be an ancestor of the current main branch", REQUESTED_SOURCE_SHA=SOURCE,
            SELECTED_DATA_SHA="")
    answers[compare] = (0, "ahead\n")
    answers[("git", "cat-file", "-e", f"{SOURCE}^{{commit}}")] = (0, "")
    answers[("git", "merge-base", "--is-ancestor", SOURCE, TRUSTED)] = (0, "")
    assert select(answers, REQUESTED_SOURCE_SHA=SOURCE, SELECTED_DATA_SHA="")["source_sha"] == SOURCE
    answers[compare] = (4, "")
    with pytest.raises(weekly_release.CommandFailed) as failure:
        select(answers, REQUESTED_SOURCE_SHA=SOURCE, SELECTED_DATA_SHA="")
    assert failure.value.code == 4


def test_bash_read_collapses_whitespace_separators_like_bash() -> None:
    assert weekly_release.bash_read("a\t\tb\tc d\t\n", "\t", 3) == ["a", "b", "c d"]
    assert weekly_release.bash_read("", " \t", 2) == ["", ""]


def test_cli_writes_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "out"
    output.write_text("data_revision=x\n", encoding="utf-8")
    monkeypatch.setattr(weekly_release, "run_command", FakeRunner(base_answers()))
    for key, value in env(GITHUB_OUTPUT=str(output)).items():
        monkeypatch.setenv(key, value)
    assert weekly_release.main(["select-release"]) == 0
    assert output.read_text(encoding="utf-8").splitlines()[1:3] == ["week=2026-W41", "base_tag=radar-data-2026-W41"]
    monkeypatch.setenv("GITHUB_SHA", OTHER)
    assert weekly_release.main(["select-release"]) == 1
    assert "::error::Trusted tooling checkout does not match" in capsys.readouterr().out


# validate --------------------------------------------------------------------------------------------------------

def test_validate_loads_trusted_policy_before_entering_data_root(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from hecavex_radar import brands, publication

    workspace, source = tmp_path / "workspace", tmp_path / "source"
    source.mkdir()
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, Path, Path]] = []
    monkeypatch.setattr(brands, "load_brand_registry", lambda path: calls.append(("registry", path, Path.cwd())))

    def validate(selected: Path, **options: object) -> None:
        assert options == {"validate_stix": True, "trusted_registry": None, "allow_legacy_observations": True}
        calls.append(("publication", selected, Path.cwd()))

    monkeypatch.setattr(publication, "validate_publication", validate)
    weekly_release.validate_release_source(workspace, source)
    assert calls == [("registry", workspace / "data/brands-lt.json", tmp_path), ("publication", source, source)]


# package ---------------------------------------------------------------------------------------------------------

def write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def sidecar(path: Path, payload: bytes) -> None:
    write(path.with_name(path.name + ".sha256"), f"{hashlib.sha256(payload).hexdigest()}  {path.name}\n".encode())


def dataset(root: Path) -> Path:
    data = root / "public/data"
    signal_id = "0123456789abcdef0123"
    shard = b'{"shard":1}\n'
    write(data / "shards/radar-0.json", shard)
    write(data / "radar.index.json", json.dumps({"shards": [
        {"path": "/data/shards/radar-0.json", "bytes": len(shard), "sha256": hashlib.sha256(shard).hexdigest()},
    ]}).encode())
    write(data / "radar.json", json.dumps({"signals": [
        {"id": signal_id, "detailAvailable": True}, {"id": "ignored", "detailAvailable": False},
    ]}).encode())
    write(data / f"signals/01/{signal_id}.json", b"{}\n")
    rows = []
    for name in ("radar.json", "radar.index.json"):
        payload = (data / name).read_bytes()
        sidecar(data / name, payload)
        rows.append({"path": f"/data/{name}", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = json.dumps({"generatedAt": "2026-10-05T06:00:00.000Z", "artifacts": rows}).encode()
    write(data / "feed-manifest.json", manifest)
    sidecar(data / "feed-manifest.json", manifest)
    write(data / "collection-health.json", b"{}")
    return data


PACKAGE_ENV = {"RELEASE_TAG": "radar-data-2026-W41", "SOURCE_SHA": SOURCE, "TRUSTED_TOOLING_SHA": TRUSTED,
               "GITHUB_REPOSITORY": REPO}


def stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return weekly_release.build_stage({**PACKAGE_ENV, "RELEASE_SOURCE_ROOT": str(tmp_path / "src")})


def test_build_stage_writes_canonical_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset(tmp_path / "src")
    stage(tmp_path, monkeypatch)
    manifest = json.loads((tmp_path / "_release/assets/radar-data-2026-W41.manifest.json").read_bytes())
    assert manifest == json.loads(
        (tmp_path / "_release/stage/radar-data-2026-W41/RELEASE-MANIFEST.json").read_bytes())
    assert [row["path"] for row in manifest["files"]] == [
        "data/feed-manifest.json", "data/feed-manifest.json.sha256", "data/radar.index.json",
        "data/radar.index.json.sha256", "data/radar.json", "data/radar.json.sha256",
        "data/shards/radar-0.json", "data/signals/01/0123456789abcdef0123.json",
    ]
    assert (manifest["releaseWeek"], manifest["sourceCommit"], manifest["toolingCommit"]) == (
        "2026-W41", SOURCE, TRUSTED)
    assert not (tmp_path / "_release/stage/radar-data-2026-W41/data/collection-health.json").exists()


@pytest.mark.parametrize(("tamper", "message"), [
    (lambda data: write(data / "stray.json", b"{}"), "unexpected=data/stray.json"),
    (lambda data: write(data / "shards/radar-0.json", b"changed"), "byte length drifted: data/shards/radar-0.json"),
    (lambda data: write(data / "radar.json.sha256", b"0  radar.json\n"), "checksum sidecar drifted"),
    (lambda data: write(data / "feed-manifest.json.sha256", b"0\n"), "Feed-manifest checksum sidecar drifted"),
    (lambda data: write(data / "radar.index.json", b'{"shards": [{"path": "/data/../x"}]}'),
     "Selected artifact byte length drifted|excluded or unsafe"),
    (lambda data: write(data / "feed-manifest.json", b'{"artifacts": []}'), "no canonical artifact list"),
])
def test_build_stage_refuses_noncanonical_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                  tamper: object, message: str) -> None:
    data = dataset(tmp_path / "src")
    tamper(data)  # type: ignore[operator]
    with pytest.raises(SystemExit, match=message):
        stage(tmp_path, monkeypatch)


def gnu_tar() -> bool:
    tar = shutil.which("tar")
    if tar is None or shutil.which("gzip") is None:
        return False
    version = subprocess.run([tar, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    return "GNU tar" in version.stdout


@pytest.mark.skipif(not gnu_tar(), reason="GNU tar and gzip are required for the reproducible archive")
def test_package_builds_reproducible_assets_and_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    dataset(tmp_path / "src")
    for name in ("pyproject.toml", "package.json", "pnpm-lock.yaml", "requirements/automation-runtime-py312.lock"):
        write(tmp_path / name, (REPOSITORY / name).read_bytes())
    output = tmp_path / "github-output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED", raising=False)
    assert weekly_release.package({**PACKAGE_ENV, "RELEASE_SOURCE_ROOT": str(tmp_path / "src"),
                                   "GITHUB_OUTPUT": str(output)}) == 0
    assets = tmp_path / "_release/assets"
    names = ["radar-data-2026-W41.tar.gz", "radar-data-2026-W41.manifest.json", "radar-data-2026-W41.spdx.json"]
    assert (assets / "SHA256SUMS").read_text(encoding="ascii") == "".join(
        f"{hashlib.sha256((assets / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
    printed = capsys.readouterr().out
    assert all(f"{name}: OK\n" in printed for name in names)
    assert output.read_text(encoding="utf-8") == (
        "archive_path=_release/assets/radar-data-2026-W41.tar.gz\n"
        "manifest_path=_release/assets/radar-data-2026-W41.manifest.json\n"
        "sbom_path=_release/assets/radar-data-2026-W41.spdx.json\n"
        "checksums_path=_release/assets/SHA256SUMS\n")
    first = (assets / names[0]).read_bytes()
    assert weekly_release.package({**PACKAGE_ENV, "RELEASE_SOURCE_ROOT": str(tmp_path / "src"),
                                   "GITHUB_OUTPUT": str(output)}) == 0
    assert (assets / names[0]).read_bytes() == first


# notes -----------------------------------------------------------------------------------------------------------

def test_notes_name_assets_and_correction_supersession(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "_release").mkdir()
    values = {"RELEASE_TAG": "radar-data-2026-W41", "BASE_RELEASE_TAG": "radar-data-2026-W41",
              "CORRECTION_REVISION": "", "SOURCE_SHA": SOURCE, "TRUSTED_TOOLING_SHA": TRUSTED,
              "GITHUB_REPOSITORY": REPO}
    weekly_release.write_notes(values)
    notes = (tmp_path / "_release/notes.md").read_text(encoding="utf-8")
    assert notes.startswith(f"Weekly static export of the public HECAVEX Radar dataset at commit `{SOURCE}`.\n\n")
    assert f"`gh attestation verify radar-data-2026-W41.tar.gz --repo {REPO}`" in notes
    assert notes.endswith("by the same workflow.\n") and "supersedes" not in notes
    weekly_release.write_notes({**values, "RELEASE_TAG": "radar-data-2026-W41-r1", "CORRECTION_REVISION": "1"})
    notes = (tmp_path / "_release/notes.md").read_text(encoding="utf-8")
    assert notes.endswith("by the same workflow.\n\nThis immutable correction release supersedes "
                          "`radar-data-2026-W41` for data use. The original release remains available as an "
                          "unmodified audit record.\n")
