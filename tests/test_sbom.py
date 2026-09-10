from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hecavex_radar.sbom import build_sbom, write_sbom

TAG = "radar-data-2026-W35"
COMMIT = "a" * 40


def _fixtures(root: Path) -> dict[str, Path]:
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "hecavex-radar"
version = "0.1.0"
license = "Apache-2.0"
""",
        encoding="utf-8",
    )
    python_lock = root / "runtime.lock"
    python_lock.write_text(
        """attrs==26.1.0 \\
    --hash=sha256:aaaa
idna==3.19 \\
    --hash=sha256:bbbb
""",
        encoding="utf-8",
    )
    package_json = root / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "name": "hecavex-radar",
                "private": True,
                "dependencies": {"react": "19.2.8"},
                "devDependencies": {"@types/node": "26.2.0"},
            }
        ),
        encoding="utf-8",
    )
    pnpm_lock = root / "pnpm-lock.yaml"
    pnpm_lock.write_text(
        """lockfileVersion: '9.0'
packages:
  '@types/node@26.2.0':
    resolution: {integrity: sha512-example}
  react@19.2.8:
    resolution: {integrity: sha512-example}
  scheduler@0.27.0:
    resolution: {integrity: sha512-example}
snapshots:
""",
        encoding="utf-8",
    )
    release_manifest = root / f"{TAG}.manifest.json"
    release_manifest.write_text(
        json.dumps(
            {
                "tag": TAG,
                "sourceCommit": COMMIT,
                "snapshotGeneratedAt": "2026-08-26T10:11:12.345Z",
            }
        ),
        encoding="utf-8",
    )
    archive = root / f"{TAG}.tar.gz"
    archive.write_bytes(b"archive")
    return {
        "pyproject": pyproject,
        "python_lock": python_lock,
        "package_json": package_json,
        "pnpm_lock": pnpm_lock,
        "release_manifest": release_manifest,
        "archive": archive,
    }


def _build(paths: dict[str, Path]) -> dict[str, object]:
    return build_sbom(
        tag=TAG,
        repository="Hecavex/radar.hecavex.com",
        commit=COMMIT,
        release_manifest=paths["release_manifest"],
        files=[paths["archive"], paths["release_manifest"]],
        pyproject_path=paths["pyproject"],
        python_lock=paths["python_lock"],
        package_path=paths["package_json"],
        pnpm_lock=paths["pnpm_lock"],
    )


def test_distinct_data_and_tooling_revisions_keep_dependency_identity(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)
    manifest = json.loads(paths["release_manifest"].read_text(encoding="utf-8"))
    manifest.update(sourceCommit="b" * 40, toolingCommit=COMMIT)
    paths["release_manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    value = _build(paths)
    assert value["documentNamespace"].endswith("/" + COMMIT)
    assert value["packages"][0]["downloadLocation"].endswith("/" + COMMIT)
    assert json.loads(paths["release_manifest"].read_text(encoding="utf-8"))["sourceCommit"] == "b" * 40


@pytest.mark.parametrize("updates", [
    {"sourceCommit": "b" * 40},  # A legacy manifest must still match exactly.
    {"sourceCommit": "b" * 40, "toolingCommit": "c" * 40},
    {"sourceCommit": "bad", "toolingCommit": COMMIT},
    {"sourceCommit": None, "toolingCommit": COMMIT},
    {"sourceCommit": "b" * 40, "toolingCommit": None},
    {"sourceCommit": "b" * 40, "toolingCommit": COMMIT + "\n"},
])
def test_release_identity_mismatch_or_malformed_sha_is_rejected(tmp_path: Path, updates: dict) -> None:
    paths = _fixtures(tmp_path)
    manifest = json.loads(paths["release_manifest"].read_text(encoding="utf-8"))
    manifest.update(updates)
    paths["release_manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        _build(paths)


def test_sbom_covers_release_files_and_both_dependency_ecosystems(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)

    value = _build(paths)

    assert value["spdxVersion"] == "SPDX-2.3"
    assert value["dataLicense"] == "CC0-1.0"
    assert value["creationInfo"]["created"] == "2026-08-26T10:11:12Z"  # type: ignore[index]
    packages = value["packages"]
    assert isinstance(packages, list)
    purls = {
        reference["referenceLocator"]
        for package in packages
        for reference in package.get("externalRefs", [])
    }
    assert "pkg:pypi/attrs@26.1.0" in purls
    assert "pkg:npm/react@19.2.8" in purls
    assert "pkg:npm/%40types/node@26.2.0" in purls
    # Transitive pnpm packages are part of the inventory as well.
    assert "pkg:npm/scheduler@0.27.0" in purls
    assert len({package["SPDXID"] for package in packages}) == len(packages)

    files = value["files"]
    assert isinstance(files, list)
    assert {row["fileName"] for row in files} == {
        f"./{TAG}.tar.gz",
        f"./{TAG}.manifest.json",
    }
    archive = next(row for row in files if row["fileName"].endswith(".tar.gz"))
    assert archive["checksums"] == [
        {"algorithm": "SHA256", "checksumValue": hashlib.sha256(b"archive").hexdigest()}
    ]


def test_sbom_rejects_manifest_dependency_drift(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)
    paths["package_json"].write_text(
        json.dumps({"private": True, "dependencies": {"react": "19.2.9"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not contain the declared exact dependency"):
        _build(paths)


def test_sbom_rejects_ranges_and_conflicting_python_pins(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)
    paths["package_json"].write_text(
        json.dumps({"private": True, "dependencies": {"react": "^19.2.8"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not pinned exactly"):
        _build(paths)

    paths = _fixtures(tmp_path)
    paths["python_lock"].write_text("idna==3.18\nidna==3.19\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting pins"):
        _build(paths)


def test_sbom_output_cannot_escape_release_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _fixtures(tmp_path)
    value = _build(paths)
    monkeypatch.chdir(tmp_path)

    output = write_sbom(value, Path(f"_release/assets/{TAG}.spdx.json"))
    assert json.loads(output.read_text(encoding="utf-8"))["spdxVersion"] == "SPDX-2.3"

    with pytest.raises(ValueError, match="direct JSON child"):
        write_sbom(value, Path("outside.spdx.json"))


def test_repository_locks_produce_a_complete_hybrid_inventory(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    release_manifest = tmp_path / f"{TAG}.manifest.json"
    release_manifest.write_text(
        json.dumps(
            {
                "tag": TAG,
                "sourceCommit": COMMIT,
                "snapshotGeneratedAt": "2026-08-26T10:11:12.000Z",
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / f"{TAG}.tar.gz"
    archive.write_bytes(b"archive")

    value = build_sbom(
        tag=TAG,
        repository="Hecavex/radar.hecavex.com",
        commit=COMMIT,
        release_manifest=release_manifest,
        files=[archive, release_manifest],
        pyproject_path=repository / "pyproject.toml",
        python_lock=repository / "requirements/automation-runtime-py312.lock",
        package_path=repository / "package.json",
        pnpm_lock=repository / "pnpm-lock.yaml",
    )

    packages = value["packages"]
    assert isinstance(packages, list)
    assert len(packages) > 200
    purls = {
        reference["referenceLocator"]
        for package in packages
        for reference in package.get("externalRefs", [])
    }
    assert "pkg:pypi/jsonschema@4.26.0" in purls
    assert "pkg:npm/react@19.2.8" in purls
    assert "pkg:npm/typescript@6.0.3" in purls


def test_weekly_workflow_uploads_checksums_sbom_and_attests_all_assets() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/release-weekly-dataset.yml"
    ).read_text(encoding="utf-8")

    assert 'sha256sum "${archive_name}" "${manifest_name}" "${sbom_name}" > SHA256SUMS' in workflow
    assert '"${RELEASE_TAG}.spdx.json" "${RELEASE_TAG}.tar.gz"' in workflow
    assert "${{ steps.package.outputs.sbom_path }}" in workflow
    assert "${{ steps.package.outputs.checksums_path }}" in workflow
    assert '--commit "${TRUSTED_TOOLING_SHA}"' in workflow
    assert '--commit "${SOURCE_SHA}"' not in workflow
