"""Trusted-source, blob-only operational data transport. Never check out data code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST = "radar-data-manifest.json"
PUBLICATION = "radar-publication.json"
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
SHA = re.compile(r"[a-f0-9]{40}")
WRITERS = {
    "certstream": ("data/certstream/", "public/data/collection-health.json"),
    "ct-search": ("data/certstream/", "data/ct-search/"),
    "urlscan": ("data/urlscan/",),
    "brand-assets": ("data/urlscan/",),
    "domain-context": ("data/enrichment/domain-context.json", "data/history/context/"),
    "passive-context": ("data/enrichment/passive-context.json", "data/history/context/"),
    "snapshot": ("public/data/", "data/history/", "data/coverage/brand-coverage.json",
                 "data/review/review-queue.json"),
}
# CertStream depends on trusted source configuration and its own attempt/archive state.
# Other computed writers conservatively invalidate on any operational input change.
READ_SCOPES = {writer: (("data/certstream/", "public/data/collection-health.json")
                       if writer == "certstream" else ("data/", "public/data/")) for writer in WRITERS}


def allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or any(part in {".", ".."} for part in parts) or "\\" in path or ":" in path:
        return False
    if PurePosixPath(path).is_absolute() or str(PurePosixPath(path)) != path:
        return False
    if path in {MANIFEST, PUBLICATION}:
        return True
    if PurePosixPath(path).suffix not in {".json", ".ndjson", ".xml", ".sha256"}:
        return False
    return path.startswith(("public/data/", "data/certstream/", "data/ct-search/",
                            "data/enrichment/", "data/history/", "data/urlscan/")) or path in {
        "data/coverage/brand-coverage.json", "data/review/review-queue.json",
    }


def git(repository: Path, *args: str, content: bytes | None = None,
        environment: dict[str, str] | None = None) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required")
    return subprocess.run(  # noqa: S603 - fixed executable, no shell or data-branch execution.
        [executable, "-C", str(repository), *args], input=content, capture_output=True,
        check=True, timeout=120, env=environment,
    ).stdout


def revision(value: str) -> str:
    if SHA.fullmatch(value) is None:
        raise ValueError("A full lowercase Git revision is required")
    return value


def head(repository: Path) -> str:
    return revision(git(repository, "rev-parse", "HEAD").decode().strip())


def remote(repository: Path, branch: str) -> str | None:
    rows = git(repository, "ls-remote", "--heads", "origin", f"refs/heads/{branch}").decode().splitlines()
    return revision(rows[0].split()[0]) if rows else None


def source_guard(repository: Path, source: str) -> None:
    if head(repository) != source or remote(repository, "main") != source:
        raise ValueError("Protected source changed; refusing older-source output")


def blobs(repository: Path, selected: str, *, source_tree: bool = False) -> dict[str, bytes]:
    revision(selected)
    result: dict[str, bytes] = {}
    total = 0
    entries: list[tuple[str, bytes, int]] = []
    for row in git(repository, "ls-tree", "-rlz", selected).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if not allowed(path):
            if source_tree:
                continue
            raise ValueError(f"Non-data path in data branch: {path}")
        mode, kind, oid, raw_size = metadata.split()
        if mode != b"100644" or kind != b"blob":
            raise ValueError(f"Data must be a non-executable regular blob: {path}")
        size = int(raw_size)
        total += size
        if size > MAX_FILE or total > MAX_TOTAL or len(entries) >= 20000:
            raise ValueError("Data tree exceeds transport capacity")
        entries.append((path, oid, size))
    batch = git(repository, "cat-file", "--batch", content=b"".join(oid + b"\n" for _, oid, _ in entries))
    cursor = 0
    for path, oid, size in entries:
        end = batch.index(b"\n", cursor)
        if batch[cursor:end] != oid + b" blob " + str(size).encode():
            raise ValueError("Unexpected Git blob batch response")
        cursor = end + 1
        result[path] = batch[cursor:cursor + size]
        cursor += size + 1
    if cursor != len(batch):
        raise ValueError("Unexpected trailing Git blob response")
    return result


def inventory(files: dict[str, bytes]) -> list[dict[str, Any]]:
    return [{"path": path, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            for path, value in sorted(files.items()) if path != MANIFEST]


def encode(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def validate(files: dict[str, bytes]) -> dict[str, Any]:
    manifest = json.loads(files.get(MANIFEST, b"null"))
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("Missing or unsupported data manifest")
    revision(manifest["sourceRevision"])
    if manifest.get("baseDataRevision") is not None:
        revision(manifest["baseDataRevision"])
    if manifest.get("inventory") != inventory(files):
        raise ValueError("Data manifest inventory mismatch")
    if PUBLICATION in files:
        marker = json.loads(files[PUBLICATION])
        if not isinstance(marker, dict) or marker.get("schemaVersion") != 1:
            raise ValueError("Unsupported publication marker")
        revision(marker["sourceRevision"])
        revision(marker["inputDataRevision"])
    return manifest


def safe_target(repository: Path, path: str) -> Path:
    target = repository / path
    if not allowed(path) or not target.resolve().is_relative_to(repository.resolve()):
        raise ValueError("Unsafe data overlay path")
    for parent in (target, *target.parents):
        if parent == repository:
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Links are not permitted in the data overlay")
    return target


def local_files(repository: Path) -> dict[str, bytes]:
    paths = git(repository, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    result = {}
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        path = raw.decode()
        if allowed(path):
            target = safe_target(repository, path)
            if target.is_file():
                if target.stat().st_size > MAX_FILE:
                    raise ValueError("Data file exceeds transport capacity")
                result[path] = target.read_bytes()
    if sum(map(len, result.values())) > MAX_TOTAL:
        raise ValueError("Data inventory exceeds transport capacity")
    return result


def overlay(repository: Path, files: dict[str, bytes]) -> None:
    existing = local_files(repository)
    for path in existing.keys() - files.keys():
        safe_target(repository, path).unlink()
    for path, value in files.items():
        target = safe_target(repository, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)


def commit_data(repository: Path, files: dict[str, bytes], source: str, base: str | None,
                writer: str, message: str) -> str:
    files = dict(files)
    files[MANIFEST] = encode({"schemaVersion": 1, "sourceRevision": source,
        "baseDataRevision": base, "writer": writer,
        "writtenAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inventory": inventory(files)})
    if (len(files) > 20000 or any(len(value) > MAX_FILE for value in files.values())
            or sum(map(len, files.values())) > MAX_TOTAL):
        raise ValueError("Complete data commit exceeds transport capacity")
    with tempfile.TemporaryDirectory(prefix="radar-data-index-") as temporary:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"),
                           GIT_AUTHOR_NAME="github-actions[bot]", GIT_COMMITTER_NAME="github-actions[bot]",
                           GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
                           GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
        git(repository, "read-tree", "--empty", environment=environment)
        records = b""
        for path, value in sorted(files.items()):
            oid = git(repository, "hash-object", "-w", "--stdin", content=value).strip()
            records += b"100644 " + oid + b"\t" + path.encode() + b"\0"
        git(repository, "update-index", "-z", "--index-info", content=records, environment=environment)
        tree = git(repository, "write-tree", environment=environment).decode().strip()
        parents = ["-p", base] if base else []
        return git(repository, "commit-tree", tree, *parents, "-m", message,
                   environment=environment).decode().strip()


def emit(values: dict[str, str], output: Path | None) -> None:
    if output is not None:
        with output.open("a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    print(json.dumps(values, sort_keys=True))


def in_scope(path: str, scope: tuple[str, ...]) -> bool:
    return any(path == prefix or (prefix.endswith("/") and path.startswith(prefix)) for prefix in scope)


def publish(repository: Path, source: str, base: str, writer: str, message: str,
            files: dict[str, bytes]) -> tuple[str, dict[str, bytes]]:
    old = blobs(repository, base)
    validate(old)
    changed = {path for path in old.keys() | files.keys() if old.get(path) != files.get(path)}
    if any(not in_scope(path, WRITERS[writer]) for path in changed):
        raise ValueError("Writer modified paths outside its declared output scope")
    for _attempt in range(4):
        source_guard(repository, source)
        latest = remote(repository, "radar-data")
        if latest is None:
            raise ValueError("Data branch disappeared")
        current = old
        if latest != base:
            git(repository, "fetch", "--no-tags", "origin",
                "+refs/heads/radar-data:refs/remotes/origin/radar-data")
            git(repository, "merge-base", "--is-ancestor", base, latest)
            current = blobs(repository, latest)
            validate(current)
            intervening = {path for path in old.keys() | current.keys()
                           if old.get(path) != current.get(path) and path not in {MANIFEST, PUBLICATION}}
            if any(in_scope(path, READ_SCOPES[writer] + WRITERS[writer]) for path in intervening):
                raise ValueError("Writer inputs changed; refusing stale computed output")
        merged = dict(current)
        for path in changed:
            if path in files:
                merged[path] = files[path]
            else:
                merged.pop(path, None)
        marker = json.loads(merged.get(PUBLICATION, b"{}"))
        needs_publication = writer == "snapshot" and marker.get("sourceRevision") != source
        if not changed and not needs_publication:
            return latest, merged
        if writer == "snapshot":
            cutoff = json.loads(merged["public/data/radar.json"]).get("generatedAt")
            if not isinstance(cutoff, str) or not cutoff.endswith("Z"):
                raise ValueError("Snapshot publication requires a UTC generatedAt")
            datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            merged[PUBLICATION] = encode({"schemaVersion": 1, "sourceRevision": source,
                                        "inputDataRevision": base, "generatedAt": cutoff})
        selected = commit_data(repository, merged, source, latest, writer, message)
        source_guard(repository, source)
        try:
            git(repository, "push", f"--force-with-lease=refs/heads/radar-data:{latest}",
                "origin", f"{selected}:refs/heads/radar-data")
        except subprocess.CalledProcessError:
            if remote(repository, "radar-data") == latest:
                raise
            continue
        return selected, merged
    raise ValueError("Data publication lost four compare-and-swap races")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("materialize", "materialize-fixture", "publish", "bootstrap"))
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--branch", choices=("radar-data",), default="radar-data")
    parser.add_argument("--view", choices=("operational", "publication"), default="operational")
    parser.add_argument("--revision")
    parser.add_argument("--source-revision")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--writer", choices=tuple(WRITERS))
    parser.add_argument("--message", default="data: publish operational state")
    parser.add_argument("--push", action="store_true")
    options = parser.parse_args(argv)
    repository = options.repository.resolve()
    try:
        source = head(repository)
        selected = ""
        files: dict[str, bytes]
        if options.command == "bootstrap":
            source = revision(options.source_revision or "")
            source_guard(repository, source)
            if remote(repository, options.branch) is not None:
                raise ValueError("Bootstrap refuses an existing data branch")
            files = blobs(repository, source, source_tree=True)
            files.pop(PUBLICATION, None)
            files.pop(MANIFEST, None)
            selected = commit_data(repository, files, source, None, "bootstrap",
                                   "data: bootstrap exact source inventory")
            source_guard(repository, source)
            if options.push:
                git(repository, "push", f"--force-with-lease=refs/heads/{options.branch}:",
                    "origin", f"{selected}:refs/heads/{options.branch}")
        elif options.command == "publish":
            if options.state_file is None or options.writer is None:
                raise ValueError("Publish requires state and writer")
            state = json.loads(options.state_file.read_bytes())
            if state.get("kind") != "operational":
                raise ValueError("Only an operational materialization can publish")
            source = revision(state["source_revision"])
            base = revision(state["data_revision"])
            source_guard(repository, source)
            files = local_files(repository)
            selected, files = publish(repository, source, base, options.writer, options.message, files)
        else:
            if options.command == "materialize-fixture":
                selected = revision(options.revision or "")
                files = blobs(repository, selected, source_tree=True)
            else:
                if remote(repository, options.branch) is None:
                    raise ValueError("Data branch missing; bootstrap must follow the exact migration merge")
                git(repository, "fetch", "--no-tags", "origin",
                    f"+refs/heads/{options.branch}:refs/remotes/origin/{options.branch}")
                tip = git(repository, "rev-parse", f"refs/remotes/origin/{options.branch}").decode().strip()
                selected = revision(options.revision) if options.revision else tip
                git(repository, "merge-base", "--is-ancestor", selected, tip)
                if options.view == "publication":
                    selected = git(repository, "log", "-1", "--format=%H", selected, "--", PUBLICATION).decode().strip()
                    revision(selected)
                files = blobs(repository, selected)
                validate(files)
            overlay(repository, files)
            if options.state_file is not None:
                kind = options.view if options.command == "materialize" else "fixture"
                options.state_file.write_bytes(encode({"kind": kind,
                    "source_revision": source, "data_revision": selected}))
        marker = json.loads(files.get(PUBLICATION, b"{}"))
        emit({"source_revision": source, "data_revision": selected,
              "publication_source_revision": marker.get("sourceRevision", "")}, options.github_output)
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"Data transport refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
