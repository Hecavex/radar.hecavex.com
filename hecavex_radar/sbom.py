"""Create a bounded SPDX 2.3 document for a weekly dataset release.

The release job deliberately builds this inventory from the repository's pinned
Python and pnpm inputs. It does not inspect the runner's global environment,
which would make an otherwise reproducible weekly release depend on runner
state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

SPDX_VERSION = "SPDX-2.3"
MAXIMUM_SBOM_BYTES = 2 * 1024 * 1024
MAXIMUM_RELEASE_FILE_BYTES = 256 * 1024 * 1024
MAXIMUM_DEPENDENCIES = 1_000
PINNED_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
PNPM_PACKAGE_KEY = re.compile(r"^  (?:(?:'([^']+)')|([^'\s][^:]*)):\s*$")
SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
SAFE_COMMIT = re.compile(r"^[a-f0-9]{40}$")
SAFE_NPM_NAME = re.compile(r"^(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+$", re.IGNORECASE)

Dependency = tuple[str, str, str, str]


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("SPDX creation time must be a canonical UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("SPDX creation time must be a canonical UTC timestamp.") from error
    canonical_seconds = parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    canonical_milliseconds = parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if value not in {canonical_seconds, canonical_milliseconds}:
        raise ValueError("SPDX creation time is not canonical UTC.")
    # SPDX creationInfo uses whole seconds even though Radar snapshots retain
    # millisecond precision.
    return canonical_seconds


def _sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAXIMUM_RELEASE_FILE_BYTES:
        raise ValueError(f"SPDX input is missing, symlinked, or oversized: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _python_dependencies(lock_path: Path) -> list[Dependency]:
    try:
        body = lock_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("SPDX Python dependency lock is unreadable.") from error
    dependencies: dict[str, str] = {}
    for line in body.splitlines():
        match = PINNED_REQUIREMENT.match(line.strip())
        if not match:
            continue
        name = match.group(1).lower().replace("_", "-")
        version = match.group(2)
        previous = dependencies.setdefault(name, version)
        if previous != version:
            raise ValueError(f"SPDX Python dependency has conflicting pins: {name}")
    if not dependencies:
        raise ValueError("SPDX Python dependency inventory is empty.")
    return [
        ("pypi", name, version, f"pkg:pypi/{quote(name, safe='')}@{quote(version, safe='')}")
        for name, version in sorted(dependencies.items())
    ]


def _npm_purl(name: str, version: str) -> str:
    if name.startswith("@"):
        namespace, package_name = name.split("/", 1)
        path = f"{quote(namespace, safe='')}/{quote(package_name, safe='')}"
    else:
        path = quote(name, safe="")
    return f"pkg:npm/{path}@{quote(version, safe='')}"


def _manifest_npm_pins(package_path: Path) -> dict[str, str]:
    try:
        value: Any = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("SPDX npm package manifest is unreadable.") from error
    if not isinstance(value, dict) or value.get("private") is not True:
        raise ValueError("SPDX npm package manifest must describe the private Radar frontend.")
    dependencies: dict[str, str] = {}
    for section_name in ("dependencies", "devDependencies"):
        section = value.get(section_name, {})
        if not isinstance(section, dict):
            raise ValueError(f"SPDX npm package manifest has an invalid {section_name} section.")
        for raw_name, raw_version in section.items():
            if not isinstance(raw_name, str) or not SAFE_NPM_NAME.fullmatch(raw_name):
                raise ValueError("SPDX npm package manifest contains an invalid package name.")
            if not isinstance(raw_version, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", raw_version):
                raise ValueError(f"SPDX npm dependency is not pinned exactly: {raw_name}")
            previous = dependencies.setdefault(raw_name.lower(), raw_version)
            if previous != raw_version:
                raise ValueError(f"SPDX npm dependency has conflicting pins: {raw_name}")
    if not dependencies:
        raise ValueError("SPDX npm package manifest has no dependencies.")
    return dependencies


def _pnpm_dependencies(lock_path: Path, package_path: Path) -> list[Dependency]:
    direct_pins = _manifest_npm_pins(package_path)
    try:
        lines = lock_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError("SPDX pnpm lock is unreadable.") from error

    in_packages = False
    dependencies: dict[tuple[str, str], None] = {}
    for line in lines:
        if line == "packages:":
            in_packages = True
            continue
        if line == "snapshots:":
            in_packages = False
            break
        if not in_packages:
            continue
        match = PNPM_PACKAGE_KEY.fullmatch(line)
        if not match:
            continue
        key = match.group(1) or match.group(2)
        if "@" not in key:
            raise ValueError(f"SPDX pnpm lock contains an invalid package key: {key}")
        name, version = key.rsplit("@", 1)
        if not name or not version or not SAFE_NPM_NAME.fullmatch(name):
            raise ValueError(f"SPDX pnpm lock contains an invalid package key: {key}")
        dependencies[(name.lower(), version)] = None

    if not dependencies:
        raise ValueError("SPDX pnpm dependency inventory is empty.")
    for name, version in direct_pins.items():
        if (name, version) not in dependencies:
            raise ValueError(f"SPDX pnpm lock does not contain the declared exact dependency: {name}@{version}")
    return [
        ("npm", name, version, _npm_purl(name, version))
        for name, version in sorted(dependencies)
    ]


def _dependencies(*, python_lock: Path, package_path: Path, pnpm_lock: Path) -> list[Dependency]:
    dependencies = _python_dependencies(python_lock) + _pnpm_dependencies(pnpm_lock, package_path)
    if len(dependencies) > MAXIMUM_DEPENDENCIES:
        raise ValueError("SPDX dependency inventory exceeds its cap.")
    return dependencies


def _project_metadata(pyproject_path: Path) -> tuple[str, str, str]:
    try:
        value = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError("SPDX project metadata is unreadable.") from error
    project = value.get("project") if isinstance(value, dict) else None
    if not isinstance(project, dict):
        raise ValueError("SPDX project metadata is missing [project].")
    name = project.get("name")
    version = project.get("version")
    license_value = project.get("license")
    if not all(isinstance(item, str) and item for item in (name, version, license_value)):
        raise ValueError("SPDX project metadata lacks name, version, or license.")
    return str(name), str(version), str(license_value)


def _spdx_id(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", label).strip("-.")
    if not slug:
        raise ValueError("SPDX identifier cannot be empty.")
    if len(slug) > 180:
        suffix = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
        slug = f"{slug[:167]}-{suffix}"
    return f"SPDXRef-{slug}"


def build_sbom(
    *,
    tag: str,
    repository: str,
    commit: str,
    release_manifest: Path,
    files: list[Path],
    pyproject_path: Path = Path("pyproject.toml"),
    python_lock: Path = Path("requirements/automation-runtime-py312.lock"),
    package_path: Path = Path("package.json"),
    pnpm_lock: Path = Path("pnpm-lock.yaml"),
) -> dict[str, object]:
    if not SAFE_TAG.fullmatch(tag) or not SAFE_COMMIT.fullmatch(commit):
        raise ValueError("SPDX tag or source commit is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("SPDX source repository is invalid.")
    try:
        manifest: Any = json.loads(release_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("SPDX release manifest is unreadable.") from error
    if not isinstance(manifest, dict) or manifest.get("tag") != tag:
        raise ValueError("SPDX release manifest does not match the requested release.")
    source_commit = manifest.get("sourceCommit")
    # Dependencies belong to the trusted tooling checkout, not the data-only
    # publication revision. Older manifests legitimately have only one SHA.
    tooling_commit = manifest.get("toolingCommit", source_commit)
    if (not isinstance(source_commit, str) or not SAFE_COMMIT.fullmatch(source_commit)
            or not isinstance(tooling_commit, str) or not SAFE_COMMIT.fullmatch(tooling_commit)
            or tooling_commit != commit):
        raise ValueError("SPDX release manifest does not match the requested release.")
    created = _timestamp(manifest.get("snapshotGeneratedAt"))
    project_name, project_version, project_license = _project_metadata(pyproject_path)
    project_id = _spdx_id(f"Package-project-{project_name}")
    packages: list[dict[str, object]] = [
        {
            "name": project_name,
            "SPDXID": project_id,
            "versionInfo": project_version,
            "downloadLocation": f"https://github.com/{repository}/tree/{commit}",
            "filesAnalyzed": False,
            "licenseConcluded": project_license,
            "licenseDeclared": project_license,
            "copyrightText": "NOASSERTION",
            "primaryPackagePurpose": "APPLICATION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:github/{repository}@{commit}",
                }
            ],
        }
    ]
    relationships: list[dict[str, str]] = [
        {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": project_id}
    ]
    for ecosystem, name, version, purl in _dependencies(
        python_lock=python_lock,
        package_path=package_path,
        pnpm_lock=pnpm_lock,
    ):
        dependency_id = _spdx_id(f"Package-{ecosystem}-{name}-{version}")
        packages.append(
            {
                "name": name,
                "SPDXID": dependency_id,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "primaryPackagePurpose": "LIBRARY",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": purl,
                    }
                ],
                "comment": f"Pinned {ecosystem} dependency recorded from the repository lock inputs.",
            }
        )
        relationships.append(
            {"spdxElementId": project_id, "relationshipType": "DEPENDS_ON", "relatedSpdxElement": dependency_id}
        )
    file_rows: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for path in files:
        name = path.name
        if name in seen_names or not SAFE_ASSET_NAME.fullmatch(name):
            raise ValueError("SPDX release file names must be unique and safe.")
        seen_names.add(name)
        file_id = _spdx_id(f"File-{name}")
        file_rows.append(
            {
                "fileName": f"./{name}",
                "SPDXID": file_id,
                "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(path)}],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {"spdxElementId": project_id, "relationshipType": "GENERATES", "relatedSpdxElement": file_id}
        )
    if not file_rows:
        raise ValueError("SPDX release file inventory is empty.")
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project_name} weekly dataset {tag}",
        "documentNamespace": f"https://radar.hecavex.com/spdx/{quote(tag)}/{commit}",
        "creationInfo": {
            "created": created,
            "creators": [f"Tool: {project_name}-{project_version}"],
            "comment": "Generated deterministically from pinned Python and pnpm repository inputs.",
        },
        "documentDescribes": [project_id],
        "packages": packages,
        "files": file_rows,
        "relationships": relationships,
    }


def write_sbom(value: dict[str, object], output: Path) -> Path:
    repository = Path.cwd().resolve()
    target = output.resolve()
    allowed = (repository / "_release/assets").resolve()
    if not allowed.is_relative_to(repository) or target.parent != allowed or target.suffix != ".json":
        raise ValueError("SPDX output must be a direct JSON child of _release/assets.")
    body = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(body.encode("utf-8")) > MAXIMUM_SBOM_BYTES:
        raise ValueError("SPDX document exceeds 2 MiB.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8", newline="\n")
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a weekly-release SPDX 2.3 JSON SBOM.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-manifest", required=True, type=Path)
    parser.add_argument("--file", action="append", required=True, type=Path, dest="files")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--python-lock", type=Path, default=Path("requirements/automation-runtime-py312.lock"))
    parser.add_argument("--package-json", type=Path, default=Path("package.json"))
    parser.add_argument("--pnpm-lock", type=Path, default=Path("pnpm-lock.yaml"))
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        value = build_sbom(
            tag=options.tag,
            repository=options.repository,
            commit=options.commit,
            release_manifest=options.release_manifest,
            files=options.files,
            pyproject_path=options.pyproject,
            python_lock=options.python_lock,
            package_path=options.package_json,
            pnpm_lock=options.pnpm_lock,
        )
        output = write_sbom(value, options.output)
    except (OSError, ValueError) as error:
        print(f"SPDX generation failed: {error}")
        return 1
    print(f"Wrote SPDX 2.3 JSON SBOM: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
