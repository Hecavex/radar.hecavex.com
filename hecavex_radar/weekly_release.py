"""Select, validate, package and annotate one weekly Radar dataset release.

Each subcommand is one step of `.github/workflows/release-weekly-dataset.yml` and reads that step's environment.
Release creation, attestation and publication stay in the workflow. Only standard-library modules are imported at
module level because `select-release` runs before the workflow installs the locked toolchain.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

FULL_SHA = re.compile(r"[0-9a-f]{40}")
RELEASE_WEEK = re.compile(r"[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])")
CORRECTION = re.compile(r"[1-9][0-9]{0,2}")
DIGITS = re.compile(r"[0-9]+")
UNSAFE_ARCHIVE_MEMBER = re.compile(rb"(^/|(^|/)\.\.($|/))")


class Refused(Exception):
    """A release precondition failed; reported as one `::error::` annotation with exit status 1."""


class CommandFailed(Exception):
    """A required command failed; the step exits with that command's status, as `set -e` did."""

    def __init__(self, code: int) -> None:
        super().__init__(f"command exited with status {code}")
        self.code = code


class Runner(Protocol):
    def __call__(self, args: list[str], *, quiet: bool = False) -> tuple[int, str]: ...


def run_command(args: list[str], *, quiet: bool = False) -> tuple[int, str]:
    """Run one git/gh command, capturing stdout; stderr reaches the log unless `quiet` (bash `2>/dev/null`)."""
    executable = shutil.which(args[0]) or args[0]
    completed = subprocess.run(  # noqa: S603 - fixed git/gh argument vectors, no shell.
        [executable, *args[1:]], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL if quiet else None,
        text=True, encoding="utf-8", check=False,
    )
    return completed.returncode, completed.stdout


def _checked(result: tuple[int, str]) -> str:
    code, output = result
    if code != 0:
        raise CommandFailed(code)
    return output.rstrip("\n")  # Bash command substitution drops trailing newlines.


def bash_read(text: str, separators: str, count: int) -> list[str]:
    """Split the first line like `IFS=<whitespace separators> read -r` into `count` fields."""
    fields = re.split(f"[{separators}]+", text.split("\n", 1)[0].strip(separators), maxsplit=count - 1)
    return fields + [""] * (count - len(fields))


def iso_week(manifest_text: str) -> str:
    value = json.loads(manifest_text)["generatedAt"]
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    year, week, _ = parsed.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _json_stream(text: str) -> list[object]:
    """Concatenated JSON documents, as `gh api --paginate` prints and jq reads them."""
    decoder, values, index = json.JSONDecoder(), [], 0
    while remainder := text[index:].lstrip(" \t\n\r"):
        value, index = decoder.raw_decode(text, len(text) - len(remainder))
        values.append(value)
    return values


def _jq_raw(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _jq_field(text: str, key: str) -> str:
    """`jq -r '.key'`, yielding what jq printed before any error."""
    lines = []
    try:
        for value in _json_stream(text):
            if not (value is None or isinstance(value, dict)):
                break
            lines.append(_jq_raw(None if value is None else value.get(key)))
    except ValueError:
        pass
    return "\n".join(lines)


def _tsv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    if isinstance(value, bool | int | float):
        return _jq_raw(value)
    raise ValueError("jq @tsv cannot format arrays or objects")


def _existing_release(page_text: str, tag: str) -> str:
    """The release-list jq program: one TSV row for the first release named `tag`, or an empty string."""
    for page in _json_stream(page_text):
        rows = page if isinstance(page, list) else list(page.values()) if isinstance(page, dict) else None
        if rows is None:
            raise ValueError("release page is not iterable")
        for row in rows:
            if row is not None and not isinstance(row, dict):
                raise ValueError("release row is not an object")
            if row is None or row.get("tag_name") != tag:
                continue
            assets = row.get("assets")
            if not isinstance(assets, list) or not all(asset is None or isinstance(asset, dict) for asset in assets):
                raise ValueError("release assets are not a list of objects")
            names = [None if asset is None else asset.get("name") for asset in assets]
            # shortcut: jq would also map over an object or sort/join non-string names; GitHub never sends them.
            if not all(name is None or isinstance(name, str) for name in names):
                raise ValueError("release asset names are not strings")
            joined = ",".join(name or "" for name in sorted(names, key=lambda name: (name is not None, name or "")))
            cells = [row.get("id"), _jq_raw(row.get("draft")), row.get("target_commitish"),
                     _jq_raw(row.get("immutable")), joined]
            return "\t".join(_tsv_cell(cell) for cell in cells)
    return ""


def select_release(
    env: Mapping[str, str], run: Runner = run_command, *, sleep: Callable[[int], object] = time.sleep,
) -> dict[str, str]:
    """Choose and verify the ISO-week tag; returns the step outputs in their original order."""
    repository = env["GITHUB_REPOSITORY"]
    trusted_sha = _checked(run(["git", "rev-parse", "HEAD"]))
    if trusted_sha != env["GITHUB_SHA"]:
        raise Refused("Trusted tooling checkout does not match the triggering main commit.")
    requested_source = env["REQUESTED_SOURCE_SHA"]
    requested_data = env["REQUESTED_DATA_SHA"]
    source_sha = requested_source or env["SELECTED_DATA_SHA"]
    if not FULL_SHA.fullmatch(source_sha):
        raise Refused("Selected data must identify one full commit.")
    if requested_data and source_sha != requested_data:
        raise Refused("data_sha must itself be a coherent publication commit, not an intermediate writer commit.")
    if requested_source:
        if not FULL_SHA.fullmatch(requested_source):
            raise Refused("source_sha must be one full lowercase 40-character commit SHA.")
        compare_status = _checked(run(["gh", "api", f"repos/{repository}/compare/{source_sha}...main",
                                       "--jq", ".status"]))
        if compare_status not in {"ahead", "identical"}:
            raise Refused("source_sha must be an ancestor of the current main branch.")
        if (run(["git", "cat-file", "-e", f"{source_sha}^{{commit}}"], quiet=True)[0] != 0
                or run(["git", "merge-base", "--is-ancestor", source_sha, trusted_sha])[0] != 0):
            raise Refused("source_sha is not available as an ancestor of the trusted tooling commit.")
    manifest_entry = _checked(run(["git", "ls-tree", source_sha, "--", "public/data/feed-manifest.json"]))
    manifest_mode, manifest_type, manifest_object, manifest_path = bash_read(manifest_entry, " \t", 4)
    if (manifest_mode != "100644" or manifest_type != "blob"
            or manifest_path != "public/data/feed-manifest.json"):
        raise Refused("The selected feed manifest is not one regular data blob.")
    manifest_bytes = _checked(run(["git", "cat-file", "-s", manifest_object]))
    if not DIGITS.fullmatch(manifest_bytes) or not 2 <= int(manifest_bytes) <= 262144:
        raise Refused("The selected feed manifest is empty or exceeds 256 KiB.")
    blob_status, blob = run(["git", "cat-file", "blob", manifest_object])
    snapshot_week = iso_week(blob)
    if blob_status != 0:
        raise CommandFailed(blob_status)
    release_week = env["REQUESTED_RELEASE_WEEK"] or snapshot_week
    if not RELEASE_WEEK.fullmatch(release_week):
        raise Refused("release_week must use canonical YYYY-Www syntax.")
    if release_week != snapshot_week:
        raise Refused(f"release_week {release_week} does not match snapshot week {snapshot_week} at {source_sha}.")
    base_tag = f"radar-data-{release_week}"
    tag = base_tag
    release_label = release_week
    correction_revision = env["CORRECTION_REVISION"]
    if correction_revision:
        if not CORRECTION.fullmatch(correction_revision):
            raise Refused("correction_revision must be an integer from 1 to 999.")
        tag = f"{base_tag}-r{correction_revision}"
        release_label = f"{release_week}-r{correction_revision}"
        # Bash kept stdout even when gh failed (`2>/dev/null || true`).
        base_release = run(["gh", "api", f"repos/{repository}/releases/tags/{base_tag}"], quiet=True)[1]
        base_release = base_release.rstrip("\n")
        if (not base_release or _jq_field(base_release, "draft") != "false"
                or _jq_field(base_release, "immutable") != "true"):
            raise Refused(f"A published immutable {base_tag} release is required before a correction.")
    existing: str | None = None
    for api_attempt in range(1, 5):
        status, page = run(["gh", "api", "--paginate", f"repos/{repository}/releases?per_page=100"])
        if status == 0:
            try:
                existing = _existing_release(page, tag)
                break
            except ValueError:
                pass
        sleep(api_attempt)
    if existing is None:
        raise Refused(f"Could not determine whether {tag} already exists after bounded retries.")

    should_release = "true"
    resume_draft = "false"
    if existing:
        _release_id, is_draft, target_commitish, immutable, existing_assets = bash_read(existing, "\t", 5)
        if is_draft == "false":
            if immutable != "true":
                raise Refused(f"{tag} exists but is not immutable. Do not publish another weekly release until "
                              "repository release immutability is enabled.")
            expected_assets = ",".join(sorted(
                ["SHA256SUMS", f"{tag}.manifest.json", f"{tag}.spdx.json", f"{tag}.tar.gz"]))
            if existing_assets != expected_assets:
                raise Refused(f"Immutable {tag} has an unexpected asset inventory: {existing_assets or 'none'}.")
            if not FULL_SHA.fullmatch(target_commitish):
                raise Refused(f"Immutable {tag} does not target one auditable commit SHA.")
            # Existing releases may target legacy main data or the dedicated
            # data branch. Neither target is ever checked out or executed.
            fetch_status, fetch_output = run(["git", "fetch", "--no-tags", "origin", "main", "radar-data"])
            print(fetch_output, end="")
            if fetch_status != 0:
                raise CommandFailed(fetch_status)
            if (run(["git", "merge-base", "--is-ancestor", target_commitish, "origin/main"])[0] != 0
                    and run(["git", "merge-base", "--is-ancestor", target_commitish, "origin/radar-data"])[0] != 0):
                raise Refused(f"Immutable {tag} does not target an approved source/data history.")
            content_status, content = run([
                "gh", "api", f"repos/{repository}/contents/public/data/feed-manifest.json?ref={target_commitish}",
                "--jq", ".content",
            ])
            target_week = iso_week(base64.b64decode(content.replace("\n", ""), validate=True).decode("utf-8"))
            if content_status != 0:
                raise CommandFailed(content_status)
            if target_week != release_week:
                raise Refused(f"Immutable {tag} targets snapshot week {target_week}, not {release_week}.")
            if (requested_source or requested_data) and target_commitish != source_sha:
                raise Refused(f"Immutable {tag} targets {target_commitish}, not requested source {source_sha}.")
            print(f"{tag} is already published and immutable; this run is a no-op.")
            should_release = "false"
        else:
            if target_commitish != source_sha:
                raise Refused(f"Draft {tag} targets {target_commitish}, not {source_sha}. "
                              "Review the interrupted draft manually.")
            resume_draft = "true"

    return {
        "week": release_label,
        "base_tag": base_tag,
        "tag": tag,
        "correction_revision": correction_revision,
        "source_sha": source_sha,
        "trusted_sha": trusted_sha,
        "should_release": should_release,
        "resume_draft": resume_draft,
    }


def validate_release_source(workspace: Path, source_root: Path) -> None:
    """Validate extracted data with current tooling and policy from the trusted workspace."""
    from hecavex_radar import brands, publication

    # Resolve policy from trusted source before entering the code-free
    # data root. An extracted publication never supplies brand rules.
    trusted_registry = brands.load_brand_registry(workspace / "data/brands-lt.json")
    os.chdir(source_root)
    publication.validate_publication(
        source_root, validate_stix=True, trusted_registry=trusted_registry,
        allow_legacy_observations=True,
    )


def build_stage(environ: Mapping[str, str]) -> Path:
    """Copy the canonical public dataset into `_release/stage/<tag>` and write both manifest copies."""
    repository = Path.cwd().resolve()
    source_repository = Path(environ["RELEASE_SOURCE_ROOT"]).resolve(strict=True)
    public_root = source_repository / "public"
    data_root = public_root / "data"
    output_root = repository / "_release"
    tag = environ["RELEASE_TAG"]
    package_root = output_root / "stage" / tag
    assets_root = output_root / "assets"
    maximum_files = 10_000
    maximum_bytes = 128 * 1024 * 1024

    if output_root.parent.resolve() != repository or output_root.name != "_release":
        raise SystemExit("Refusing an unexpected release output path")
    if (
        source_repository.is_symlink()
        or public_root.is_symlink()
        or data_root.is_symlink()
        or not public_root.resolve(strict=True).is_relative_to(source_repository)
    ):
        raise SystemExit("Refusing a symlinked public dataset root")
    if output_root.exists():
        shutil.rmtree(output_root)
    package_root.mkdir(parents=True)
    assets_root.mkdir(parents=True)

    feed_manifest_path = data_root / "feed-manifest.json"
    feed_manifest = json.loads(feed_manifest_path.read_text(encoding="utf-8"))
    snapshot = json.loads((data_root / "radar.json").read_text(encoding="utf-8"))
    index = json.loads((data_root / "radar.index.json").read_text(encoding="utf-8"))
    selected: dict[str, tuple[Path, bytes]] = {}
    selection_totals = {"bytes": 0}

    def select_public_file(raw_path: object, *, expected_bytes: object = None,
                           expected_sha256: object = None) -> None:
        if not isinstance(raw_path, str) or not raw_path.startswith("/data/"):
            raise SystemExit(f"Refusing unsafe public artifact path: {raw_path!r}")
        relative = PurePosixPath(raw_path.removeprefix("/"))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or raw_path != f"/{relative.as_posix()}"
            or relative.as_posix() == "data/collection-health.json"
        ):
            raise SystemExit(f"Refusing excluded or unsafe public artifact path: {raw_path}")
        relative_text = relative.as_posix()
        if relative_text in selected:
            raise SystemExit(f"Duplicate selected public artifact path: {raw_path}")

        source = public_root.joinpath(*relative.parts)
        cursor = public_root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise SystemExit(f"Refusing symlink in public dataset: {relative_text}")
        try:
            resolved = source.resolve(strict=True)
        except OSError as error:
            raise SystemExit(f"Missing selected public artifact: {relative_text}") from error
        if not resolved.is_relative_to(public_root.resolve()) or not source.is_file():
            raise SystemExit(f"Refusing non-file public artifact: {relative_text}")

        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if expected_bytes is not None and (not isinstance(expected_bytes, int) or len(payload) != expected_bytes):
            raise SystemExit(f"Selected artifact byte length drifted: {relative_text}")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or digest != expected_sha256):
            raise SystemExit(f"Selected artifact digest drifted: {relative_text}")
        next_total_bytes = selection_totals["bytes"] + len(payload)
        if len(selected) + 1 > maximum_files or next_total_bytes > maximum_bytes:
            raise SystemExit(
                f"Weekly dataset exceeds release caps while selecting {relative_text}: "
                f"files={len(selected) + 1}/{maximum_files}, "
                f"bytes={next_total_bytes}/{maximum_bytes}"
            )
        selected[relative_text] = (source, payload)
        selection_totals["bytes"] = next_total_bytes

    artifacts = feed_manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise SystemExit("Feed manifest has no canonical artifact list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise SystemExit("Feed manifest contains a non-object artifact row")
        artifact_path = artifact.get("path")
        select_public_file(
            artifact_path,
            expected_bytes=artifact.get("bytes"),
            expected_sha256=artifact.get("sha256"),
        )
        checksum_path = f"{artifact_path}.sha256"
        select_public_file(checksum_path)
        checksum_payload = selected[checksum_path.removeprefix("/")][1]
        expected_checksum = f"{artifact['sha256']}  {PurePosixPath(str(artifact_path)).name}\n".encode("ascii")
        if checksum_payload != expected_checksum:
            raise SystemExit(f"Artifact checksum sidecar drifted: {checksum_path}")

    select_public_file("/data/feed-manifest.json")
    select_public_file("/data/feed-manifest.json.sha256")
    feed_digest = hashlib.sha256(feed_manifest_path.read_bytes()).hexdigest()
    expected_feed_checksum = f"{feed_digest}  feed-manifest.json\n".encode("ascii")
    if selected["data/feed-manifest.json.sha256"][1] != expected_feed_checksum:
        raise SystemExit("Feed-manifest checksum sidecar drifted")

    shards = index.get("shards")
    if not isinstance(shards, list):
        raise SystemExit("Radar index has no shard list")
    for shard in shards:
        if not isinstance(shard, dict):
            raise SystemExit("Radar index contains a non-object shard row")
        select_public_file(
            shard.get("path"),
            expected_bytes=shard.get("bytes"),
            expected_sha256=shard.get("sha256"),
        )

    signals = snapshot.get("signals")
    if not isinstance(signals, list):
        raise SystemExit("Radar snapshot has no signal list")
    for signal in signals:
        if not isinstance(signal, dict):
            raise SystemExit("Radar snapshot contains a non-object signal row")
        if signal.get("detailAvailable") is not True:
            continue
        signal_id = signal.get("id")
        if not isinstance(signal_id, str) or len(signal_id) != 20 or any(
            character not in "0123456789abcdef" for character in signal_id
        ):
            raise SystemExit(f"Refusing invalid detail signal ID: {signal_id!r}")
        select_public_file(f"/data/signals/{signal_id[:2]}/{signal_id}.json")

    actual: set[str] = set()
    for candidate in data_root.rglob("*"):
        if candidate.is_symlink():
            raise SystemExit(f"Refusing symlink in public dataset: {candidate.relative_to(public_root).as_posix()}")
        if candidate.is_file():
            relative_text = candidate.relative_to(public_root).as_posix()
            if relative_text != "data/collection-health.json":
                actual.add(relative_text)
    expected = set(selected)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise SystemExit(
            "Public dataset inventory is not canonical; "
            f"missing={','.join(missing)}; unexpected={','.join(unexpected)}"
        )

    included = []
    for relative_text, (_, payload) in sorted(selected.items()):
        destination = package_root.joinpath(*PurePosixPath(relative_text).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        included.append(
            {
                "path": relative_text,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    release_version = tag.removeprefix("radar-data-")
    release_week = release_version.split("-r", 1)[0]
    release_manifest = {
        "schemaVersion": 1,
        "dataset": "hecavex-radar-weekly-release",
        "releaseWeek": release_week,
        "tag": tag,
        "sourceRepository": environ["GITHUB_REPOSITORY"],
        "sourceCommit": environ["SOURCE_SHA"],
        "toolingCommit": environ["TRUSTED_TOOLING_SHA"],
        "snapshotGeneratedAt": feed_manifest["generatedAt"],
        "archiveRoot": tag,
        "license": "https://github.com/Hecavex/radar.hecavex.com/blob/main/DATA-LICENSE.md",
        "sourceFeedManifest": {
            "path": "data/feed-manifest.json",
            "sha256": feed_digest,
        },
        "excluded": [
            {
                "path": "data/collection-health.json",
                "reason": "This latest-attempt health document changes independently of the atomic snapshot.",
            }
        ],
        "limits": {
            "maximumFiles": maximum_files,
            "maximumBytes": maximum_bytes,
        },
        "files": included,
    }
    manifest_payload = (
        json.dumps(release_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (package_root / "RELEASE-MANIFEST.json").write_bytes(manifest_payload)
    (assets_root / f"{tag}.manifest.json").write_bytes(manifest_payload)
    return package_root


def _tar_gzip(tag: str, output: str) -> int:
    """`tar ... -C _release/stage -cf - <tag> | gzip -n -9 > output` with `pipefail` status."""
    with open(output, "wb") as sink:
        tar = subprocess.Popen(  # noqa: S603 - fixed argument vector, no shell.
            [shutil.which("tar") or "tar", "--sort=name", "--format=gnu", "--mtime=UTC 1970-01-01",
             "--owner=0", "--group=0", "--numeric-owner", "-C", "_release/stage", "-cf", "-", tag],
            stdout=subprocess.PIPE,
        )
        gzip = subprocess.run([shutil.which("gzip") or "gzip", "-n", "-9"],  # noqa: S603
                              stdin=tar.stdout, stdout=sink, check=False)
        if tar.stdout:
            tar.stdout.close()
        return gzip.returncode or tar.wait()


def _require(code: int) -> None:
    if code != 0:
        raise CommandFailed(code)


def package(environ: Mapping[str, str]) -> int:
    """Build the archive, standalone manifest, SPDX SBOM and SHA256SUMS under `_release/assets`."""
    from hecavex_radar import release_context_history, sbom

    tag = environ["RELEASE_TAG"]
    build_stage(environ)
    _require(release_context_history.main(["--tag", tag, "--source-repository", environ["RELEASE_SOURCE_ROOT"]]))

    archive_name = f"{tag}.tar.gz"
    manifest_name = f"{tag}.manifest.json"
    _require(_tar_gzip(tag, f"_release/assets/{archive_name}"))
    _require(_tar_gzip(tag, "_release/reproducibility-check.tar.gz"))
    archive = Path(f"_release/assets/{archive_name}").read_bytes()
    if archive != Path("_release/reproducibility-check.tar.gz").read_bytes():  # `cmp --silent`
        raise CommandFailed(1)
    _require(subprocess.run([shutil.which("gzip") or "gzip", "--test",  # noqa: S603
                             f"_release/assets/{archive_name}"], check=False).returncode)
    listing = subprocess.run([shutil.which("tar") or "tar", "-tzf",  # noqa: S603
                              f"_release/assets/{archive_name}"], stdout=subprocess.PIPE, check=False)
    if any(UNSAFE_ARCHIVE_MEMBER.search(line) for line in listing.stdout.split(b"\n")):
        raise CommandFailed(1)
    _require(listing.returncode)
    sbom_name = f"{tag}.spdx.json"
    _require(sbom.main([
        "--tag", tag,
        "--repository", environ["GITHUB_REPOSITORY"],
        "--commit", environ["TRUSTED_TOOLING_SHA"],
        "--release-manifest", f"_release/assets/{manifest_name}",
        "--file", f"_release/assets/{archive_name}",
        "--file", f"_release/assets/{manifest_name}",
        "--output", f"_release/assets/{sbom_name}",
    ]))
    assets = Path("_release/assets")
    names = (archive_name, manifest_name, sbom_name)
    checksums = "".join(f"{hashlib.sha256((assets / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
    (assets / "SHA256SUMS").write_text(checksums, encoding="ascii", newline="")
    for name in names:  # `sha256sum --check SHA256SUMS`
        print(f"{name}: OK")
    _append_outputs(environ, {
        "archive_path": f"_release/assets/{archive_name}",
        "manifest_path": f"_release/assets/{manifest_name}",
        "sbom_path": f"_release/assets/{sbom_name}",
        "checksums_path": "_release/assets/SHA256SUMS",
    })
    return 0


NOTES = """\
Weekly static export of the public HECAVEX Radar dataset at commit `{source}`.

The archive contains the manifest-declared publication artifacts and checksums, index-declared shards, \
snapshot-declared signal sidecars, and up to 90 validated date partitions of the passive context-change journal as \
one point-in-time package. URLScan-derived journal rows remain excluded unless redistribution is explicitly \
confirmed. The independently replaced `collection-health.json` latest-attempt document is excluded. \
`{tag}.manifest.json` records every packaged dataset and context file and digest plus the selected data commit and \
trusted tooling commit `{tooling}`; the identical in-archive manifest cannot recursively inventory itself. \
`{tag}.spdx.json` is an SPDX 2.3 inventory generated from that trusted tooling commit's pinned Python and pnpm \
repository inputs. `SHA256SUMS` covers the archive, standalone manifest, and SBOM.

Radar publishes sampled research leads, not maliciousness verdicts or comprehensive monitoring. Review the \
[methodology](https://radar.hecavex.com/methodology/) and \
[data terms](https://github.com/Hecavex/radar.hecavex.com/blob/main/DATA-LICENSE.md) before use.

Verify downloads with `sha256sum --check SHA256SUMS`. Verify workflow provenance with \
`gh attestation verify {tag}.tar.gz --repo {repository}`; the manifest, SBOM, and checksum list are attested as \
separate subjects by the same workflow.
"""

CORRECTION_NOTE = """
This immutable correction release supersedes `{base}` for data use. The original release remains available as an \
unmodified audit record.
"""


def write_notes(environ: Mapping[str, str]) -> None:
    """Write `_release/notes.md`; unset values expand to empty strings as in the former unguarded heredoc."""
    notes = NOTES.format(source=environ.get("SOURCE_SHA", ""), tag=environ.get("RELEASE_TAG", ""),
                         tooling=environ.get("TRUSTED_TOOLING_SHA", ""),
                         repository=environ.get("GITHUB_REPOSITORY", ""))
    if environ.get("CORRECTION_REVISION", ""):
        notes += CORRECTION_NOTE.format(base=environ.get("BASE_RELEASE_TAG", ""))
    Path("_release/notes.md").write_text(notes, encoding="utf-8", newline="")


def _append_outputs(environ: Mapping[str, str], outputs: Mapping[str, str]) -> None:
    with open(environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in outputs.items()))


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly Radar dataset release steps.")
    parser.add_argument("step", choices=("select-release", "validate", "package", "notes"))
    step = parser.parse_args(arguments).step
    environ = os.environ
    try:
        if step == "select-release":
            _append_outputs(environ, select_release(environ, run_command))
        elif step == "validate":
            validate_release_source(Path(environ["GITHUB_WORKSPACE"]), Path(environ["RELEASE_SOURCE_ROOT"]))
        elif step == "package":
            return package(environ)
        else:
            write_notes(environ)
    except Refused as error:
        print(f"::error::{error}")
        return 1
    except CommandFailed as error:
        return error.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
