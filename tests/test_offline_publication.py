"""Exercise the real publisher, not merely schema-check already published fixtures."""

import json
import os
import shutil
import socket
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from hecavex_radar import offline_publication
from hecavex_radar.brands import load_brand_registry, score_domain
from hecavex_radar.certstream_archive import CandidateArchiveWriter, candidate_from_match
from hecavex_radar.offline_publication import regenerate_fixture
from hecavex_radar.public_schemas import PUBLIC_SCHEMAS
from hecavex_radar.publication import validate_publication


def test_fixture_cutoff_uses_observations_not_expiry_and_does_not_advance_on_rebuild(tmp_path: Path) -> None:
    public = tmp_path / "public/data"
    public.mkdir(parents=True)
    snapshot = public / "radar.json"
    snapshot.write_text(json.dumps({"generatedAt": "2026-09-07T12:00:00.000Z"}))
    (public / "context.json").write_text(json.dumps({"observedAt": "2026-09-07T12:01:00.000Z",
                                                    "expiresAt": "2099-01-01T00:00:00.000Z"}))
    cutoff = offline_publication.fixture_cutoff(tmp_path)
    assert cutoff.isoformat() == "2026-09-07T12:01:00+00:00"
    snapshot.write_text(json.dumps({"generatedAt": cutoff.isoformat().replace("+00:00", "Z")}))
    assert offline_publication.fixture_cutoff(tmp_path) == cutoff


def test_real_offline_sync_validates_newly_derived_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    original_schemas = {name: (repository / "public/data/schemas" / name).read_bytes()
                        for name in PUBLIC_SCHEMAS}
    for relative in ("data", "public/data"):
        shutil.copytree(repository / relative, tmp_path / relative)
    monkeypatch.chdir(tmp_path)
    regenerate_fixture(tmp_path)
    trends = json.loads((tmp_path / "public/data/daily-trends.json").read_bytes())
    assert trends["countingMethodVersion"] == 2
    assert trends["reobservationSemantics"].startswith("Version 2:")
    assert all(day["collectorCoverage"]["coverageBounds"]["methodVersion"] == 2
               for day in trends["series"])
    for name, schema in PUBLIC_SCHEMAS.items():
        assert json.loads((tmp_path / "public/data/schemas" / name).read_bytes()) == schema
        assert (repository / "public/data/schemas" / name).read_bytes() == original_schemas[name]


def test_source_ci_regenerates_only_its_fixture_before_publication_validation() -> None:
    repository = Path(__file__).resolve().parents[1]
    workflow = (repository / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert workflow.index("data_branch materialize-fixture") < workflow.index(
        "python -m hecavex_radar.offline_publication") < workflow.index("run: pnpm check")
    deploy = (repository / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "offline_publication" not in deploy
    assert "--publication-source" in deploy


def test_code_free_weekly_export_uses_trusted_registry_and_rejects_tampered_idn_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    trusted_registry = load_brand_registry(repository / "data/brands-lt.json")
    source, extracted = tmp_path / "source", tmp_path / "extracted"
    for relative in ("data", "public/data"):
        shutil.copytree(repository / relative, source / relative)
    monkeypatch.chdir(source)
    cutoff = offline_publication.fixture_cutoff(source)
    match = score_domain("weekly-luminөr.example", trusted_registry)
    assert match is not None
    CandidateArchiveWriter("data/certstream").append([candidate_from_match(match, cutoff)])
    regenerate_fixture(source, cutoff=cutoff)
    idn_path = Path("public/data/idn-matches-v1.json")
    artifact = json.loads(idn_path.read_bytes())
    assert any(record["domain"] == match.domain.replace(".", "[.]") for record in artifact["records"])
    for relative in ("public/data", "data/history/context"):
        if (source / relative).exists():
            shutil.copytree(source / relative, extracted / relative)
    monkeypatch.chdir(extracted)
    assert not (extracted / "hecavex_radar").exists()
    assert not (extracted / "data/brands-lt.json").exists()
    with pytest.raises(FileNotFoundError, match="brands-lt.json"):
        validate_publication(extracted)
    subprocess.run(  # noqa: S603 - the workflow's validation command with a fixed interpreter; no shell or network.
        [sys.executable, "-m", "hecavex_radar.weekly_release", "validate"], cwd=extracted, check=True,
        capture_output=True, text=True,
        env={**os.environ, "GITHUB_WORKSPACE": str(repository), "RELEASE_SOURCE_ROOT": str(extracted),
             "PYTHONPATH": str(repository)},
    )
    # A registry-like file from an untrusted export cannot override source policy.
    untrusted_registry = extracted / "data/brands-lt.json"
    untrusted_registry.parent.mkdir(parents=True, exist_ok=True)
    untrusted_registry.write_text("untrusted registry must not be parsed", encoding="utf-8")
    validate_publication(extracted, trusted_registry=trusted_registry)
    artifact["records"][0]["substitutions"][0]["position"] = 62
    idn_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="IDN evidence differs"):
        validate_publication(extracted, trusted_registry=trusted_registry)


def test_offline_fixture_refuses_dns_even_if_publisher_swallows_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(offline_publication, "fixture_cutoff", lambda _: None)

    def attempt_dns(**kwargs: object) -> None:
        with suppress(AssertionError):
            socket.getaddrinfo("must-not-resolve.invalid", 443)

    monkeypatch.setattr(offline_publication, "synchronize", attempt_dns)
    monkeypatch.setattr(offline_publication, "validate_publication", lambda *args, **kwargs: None)
    with pytest.raises(AssertionError, match="attempted a network connection"):
        regenerate_fixture(tmp_path)


def test_explicit_archival_validation_accepts_legacy_without_weakening_live_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    repository = Path(__file__).resolve().parents[1]
    registry = load_brand_registry(repository / "data/brands-lt.json")
    shutil.copytree(repository / "public/data", tmp_path / "public/data")
    public = tmp_path / "public/data"
    new_schemas = {
        "observed-hostname-v1.schema.json", "observed-hostname-part-v1.schema.json",
        "observed-hostnames-index-v1.schema.json", "period-metrics-v1.schema.json",
    }
    def new_path(value: str) -> bool:
        return (value.startswith("/data/observed-hostnames") or value == "/data/period-metrics-v1.json"
                or value.removeprefix("/data/schemas/") in new_schemas)
    manifest_path = public / "feed-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for artifact in manifest["artifacts"]:
        if new_path(artifact["path"]):
            target = tmp_path / "public" / artifact["path"].removeprefix("/")
            target.unlink()
            target.with_name(target.name + ".sha256").unlink()
    manifest["artifacts"] = [row for row in manifest["artifacts"] if not new_path(row["path"])]
    manifest["counts"]["artifacts"] = len(manifest["artifacts"])
    body = (json.dumps(manifest) + "\n").encode()
    manifest_path.write_bytes(body)
    manifest_path.with_name("feed-manifest.json.sha256").write_text(
        hashlib.sha256(body).hexdigest() + "  feed-manifest.json\n", encoding="ascii",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        validate_publication(tmp_path, trusted_registry=registry)
    validate_publication(tmp_path, trusted_registry=registry, allow_legacy_observations=True)
    # Opt-in cannot disguise an incomplete new cohort as an old archive.
    (public / "observed-hostnames-v1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_publication(tmp_path, trusted_registry=registry, allow_legacy_observations=True)
