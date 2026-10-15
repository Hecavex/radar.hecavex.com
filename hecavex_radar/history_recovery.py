"""Restore bounded legacy facts from pinned Git blobs, never historical code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .history import _is_event

SHA = re.compile(r"[a-f0-9]{40}")
DAILY = re.compile(r"data/history/daily/(\d{4}-\d{2}-\d{2})/events\.ndjson")
MAXIMUM_COMMITS = 16_384
MAXIMUM_BLOBS = 20_000
MAXIMUM_FILE_BYTES = 8 * 1024 * 1024
MAXIMUM_TOTAL_BYTES = 192 * 1024 * 1024
MAXIMUM_METADATA_BYTES = 16 * 1024 * 1024
MAXIMUM_EVENTS = 500_000


def _git(repository: Path, *arguments: str, payload: bytes | None = None,
         maximum: int = MAXIMUM_METADATA_BYTES) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required for history recovery.")
    environment = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    # A file-backed input avoids pipe deadlock while the bounded output reader
    # stops an oversized stream before allocating the complete Git response.
    with tempfile.TemporaryFile() as request, tempfile.TemporaryFile() as errors:
        request.write(payload or b"")
        request.seek(0)
        with subprocess.Popen(  # noqa: S603 - fixed trusted Git; no shell or historical code.
            [executable, "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(repository), *arguments],
            stdin=request, stdout=subprocess.PIPE, stderr=errors, env=environment,
        ) as process:
            if process.stdout is None:
                raise ValueError("Git recovery did not open its bounded output stream.")
            result = process.stdout.read(maximum + 1)
            if len(result) > maximum:
                process.kill()
                raise ValueError("Git recovery metadata or payload exceeds its bounded read budget.")
            code = process.wait(timeout=120)
        if code:
            errors.seek(0)
            raise ValueError("Trusted Git recovery read failed: " + errors.read(4096).decode(errors="replace"))
    return result


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not value.endswith("Z") or parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError) as error:
        raise ValueError("Recovery timestamps must be canonical UTC milliseconds.") from error


def _revision(repository: Path, value: str) -> str:
    if SHA.fullmatch(value) is None:
        raise ValueError("Recovery requires full lowercase trusted commit SHAs.")
    _git(repository, "cat-file", "-e", value + "^{commit}")
    return value


def _path_day(path: str) -> str:
    match = DAILY.fullmatch(path)
    if match is None:
        raise ValueError("Recovery encountered an unsafe daily history path.")
    day = match[1]
    if datetime.fromisoformat(day).date().isoformat() != day:
        raise ValueError("Recovery encountered a noncanonical daily history date.")
    return day


def _discover(repository: Path, heads: Sequence[str]) -> list[tuple[str, str, str]]:
    """Enumerate every unique historical blob, including pre-compaction versions."""
    raw = _git(repository, "log", "--full-history", "-m", "--format=%H", "--raw", "-z",
               "--no-abbrev", "--no-renames", "--no-ext-diff", "--no-textconv",
               f"--max-count={MAXIMUM_COMMITS + 1}", *heads, "--", "data/history/daily")
    tokens = raw.split(b"\0")
    entries: list[tuple[str, str, str]] = []
    commits: set[str] = set()
    current = ""
    index = 0
    while index < len(tokens):
        token = tokens[index].strip()
        index += 1
        if not token:
            continue
        text = token.decode("ascii")
        if SHA.fullmatch(text):
            current = text
            commits.add(current)
            if len(commits) > MAXIMUM_COMMITS:
                raise ValueError("History discovery exceeded its commit budget; refusing partial recovery.")
            continue
        if not text.startswith(":") or not current or index >= len(tokens):
            raise ValueError("Git recovery returned malformed historical metadata.")
        fields = text[1:].split()
        if len(fields) != 5:
            raise ValueError("Git recovery returned malformed historical metadata.")
        _, mode, _, oid, operation = fields
        path = tokens[index].decode("ascii")
        index += 1
        _path_day(path)
        if operation == "D":
            continue
        if mode != "100644" or SHA.fullmatch(oid) is None:
            raise ValueError("Recovery accepts regular, non-executable Git blobs only.")
        entries.append((current, path, oid))
        if len(entries) > MAXIMUM_BLOBS:
            raise ValueError("History discovery exceeded its blob budget; refusing partial recovery.")
    return entries


def _selected(repository: Path, revisions: Sequence[str]) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    for revision in revisions:
        listing = _git(repository, "ls-tree", "-rlz", "--full-tree", revision, "--", "data/history/daily")
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, oid, _ = metadata.decode("ascii").split()
            path = raw_path.decode("ascii")
            _path_day(path)
            if mode != "100644" or kind != "blob" or SHA.fullmatch(oid) is None:
                raise ValueError("Recovery accepts regular, non-executable Git blobs only.")
            result.append((revision, path, oid))
            if len(result) > MAXIMUM_BLOBS:
                raise ValueError("Selected history exceeds its blob budget.")
    return result


def _bodies(repository: Path, entries: Sequence[tuple[str, str, str]]) -> dict[str, bytes]:
    identifiers = sorted({entry[2] for entry in entries})
    if not identifiers:
        return {}
    request = ("\n".join(identifiers) + "\n").encode()
    metadata = _git(repository, "cat-file", "--batch-check", payload=request).splitlines()
    total = 0
    sizes: dict[str, int] = {}
    for expected, row in zip(identifiers, metadata, strict=True):
        fields = row.decode("ascii").split()
        if len(fields) != 3 or fields[:2] != [expected, "blob"]:
            raise ValueError("Recovery requires regular Git blob objects.")
        size = int(fields[2])
        total += size
        if size > MAXIMUM_FILE_BYTES or total > MAXIMUM_TOTAL_BYTES:
            raise ValueError("Recovery archive exceeds its file or aggregate byte budget.")
        sizes[expected] = size
    raw = _git(repository, "cat-file", "--batch", payload=request,
               maximum=MAXIMUM_TOTAL_BYTES + MAXIMUM_METADATA_BYTES)
    offset = 0
    result: dict[str, bytes] = {}
    for oid in identifiers:
        end = raw.index(b"\n", offset)
        if raw[offset:end].decode("ascii") != f"{oid} blob {sizes[oid]}":
            raise ValueError("Recovery blob header changed between bounded reads.")
        offset = end + 1
        result[oid] = raw[offset:offset + sizes[oid]]
        offset += sizes[oid]
        if raw[offset:offset + 1] != b"\n":
            raise ValueError("Recovery blob length is inconsistent.")
        offset += 1
    if offset != len(raw):
        raise ValueError("Recovery Git stream has unexpected trailing bytes.")
    return result


def recover_git_history(
    repository: Path, revisions: Sequence[str], start: str, end: str, *,
    trusted_heads: Sequence[str], imported_at: str | None = None,
) -> dict[str, Any]:
    """Recover accepted source boundaries; absent data and publication clocks stay unknown."""
    if repository.is_symlink() or repository.is_junction() or not repository.is_dir():
        raise ValueError("Recovery requires an unlinked trusted source repository.")
    first, last = _time(start), _time(end)
    if first >= last or last - first > timedelta(days=3660):
        raise ValueError("Recovery requires a bounded increasing UTC window.")
    if imported_at is not None:
        _time(imported_at)
    if not trusted_heads or len(trusted_heads) > 8 or len(revisions) > 128:
        raise ValueError("Recovery requires a bounded pinned trusted-head inventory.")
    heads = sorted({_revision(repository, value) for value in trusted_heads})
    selected = sorted({_revision(repository, value) for value in revisions})
    for revision in selected:
        trusted = False
        for head in heads:
            try:
                _git(repository, "merge-base", "--is-ancestor", revision, head)
                trusted = True
                break
            except ValueError:
                continue
        if not trusted:
            raise ValueError("Selected history is outside pinned trusted ancestry.")
    entries = _selected(repository, selected) if selected else _discover(repository, heads)
    final_day = (last - timedelta(microseconds=1)).date().isoformat()
    entries = [entry for entry in entries if first.date().isoformat() <= _path_day(entry[1]) <= final_day]
    # One exact citation per repeated blob/path is sufficient; every annotation variant remains distinct below.
    representatives: dict[tuple[str, str], str] = {}
    for commit, path, oid in entries:
        key = (path, oid)
        representatives[key] = min(representatives.get(key, commit), commit)
    entries = sorted((commit, path, oid) for (path, oid), commit in representatives.items())
    bodies = _bodies(repository, entries)
    blobs: list[dict[str, Any]] = []
    variants: dict[str, dict[str, Any]] = {}
    available_days: set[str] = set()
    processed = 0
    for commit, path, oid in entries:
        day = _path_day(path)
        available_days.add(day)
        body = bodies[oid]
        reference = {"commit": commit, "path": path, "blobOid": oid,
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        blobs.append(reference)
        lines = body.splitlines()
        if len(lines) > 10_000:
            raise ValueError("Recovery event partition exceeds its row budget.")
        for line in lines:
            if not line.strip():
                continue
            processed += 1
            if processed > MAXIMUM_EVENTS:
                raise ValueError("Recovery exceeded its decoded-event budget.")
            event = json.loads(line)
            if not _is_event(event, day):
                raise ValueError("Recovery encountered an invalid legacy event or event identity.")
            if not first <= _time(event["observedAt"]) < last:
                continue
            event_key = json.dumps(event, sort_keys=True, separators=(",", ":"))
            provenance = {**reference, "legacyEventId": event["eventId"], "eventType": event["eventType"]}
            candidate = {"event": event, "provenance": [provenance]}
            if (event_key not in variants
                    or json.dumps(candidate, sort_keys=True) < json.dumps(variants[event_key], sort_keys=True)):
                variants[event_key] = candidate
    legacy = [variants[key] for key in sorted(variants)]
    observations: list[dict[str, Any]] = []
    identities: set[tuple[str, tuple[str, ...], str]] = set()
    observed_days: set[tuple[str, str]] = set()
    for item in legacy:
        event = item["event"]
        if event["eventType"] != "observation":
            continue
        identities.add((event["domain"], tuple(event["sources"]), event["observedAt"]))
        observed_days.add((event["signalId"], event["observedAt"][:10]))
        observations.append({
            "domain": event["domain"], "sources": event["sources"], "sourceObservedAt": event["observedAt"],
            "sourceTimeProvenance": "legacy-history-boundary", "radarRecordedAt": None,
            "importedAt": imported_at, "providerEventId": None, "assessment": None,
            "originalMatch": {"brand": event["brand"], "score": None, "reasonCodes": event["reasonCodes"],
                              "policyVersion": "legacy-unknown", "legacyEventId": event["eventId"],
                              "legacyConfidence": event["confidence"], "status": event["status"],
                              "previousStatus": event["previousStatus"]},
            "provenance": item["provenance"],
        })
    unresolved = [item for item in legacy if item["event"]["eventType"] == "status-transition"
                  and (item["event"]["domain"], tuple(item["event"]["sources"]),
                       item["event"]["observedAt"]) not in identities]
    days: list[str] = []
    current = first.date()
    while datetime.combine(current, datetime.min.time(), tzinfo=UTC) < last:
        days.append(current.isoformat())
        current += timedelta(days=1)
    partial = [day for day in days if first > _time(day + "T00:00:00.000Z")
               or last < _time(day + "T00:00:00.000Z") + timedelta(days=1)]
    return {"schemaVersion": 1, "dataset": "radar-history-recovery", "trustedHeads": heads,
            "selectedRevisions": selected, "discovery": "selected-snapshots" if selected else "trusted-git-history",
            "window": {"startInclusive": start, "endExclusive": end}, "importedAt": imported_at,
            "blobs": blobs, "observations": observations, "observationCount": len(identities),
            "uniqueHostnames": len({key[0] for key in identities}), "candidateDays": len(observed_days),
            "legacyEvents": legacy, "legacyEventCount": len({item["event"]["eventId"] for item in legacy}),
            "coverage": {"availablePartitionDays": sorted(available_days),
                         "missingDays": sorted(set(days) - available_days), "partialDays": partial,
                         "completeCollection": False,
                         "scope": "Preserved eligible legacy source-boundary events; "
                                  "no inferred day membership or clocks."},
            "reconciliation": {"required": bool(unresolved), "transitionOnlyBoundaries": unresolved}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--trusted-head", action="append", required=True)
    parser.add_argument("--revision", action="append", default=[])
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--imported-at")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(argv)
    output = options.output.absolute()
    if output.resolve().is_relative_to(options.repository.resolve()) or any(
        path.is_symlink() or path.is_junction() for path in (output, *output.parents)
    ):
        raise ValueError("Recovery output must be an unlinked isolated directory outside the source repository.")
    target = output / "recovery.json"
    checksum = output / "recovery.sha256"
    temporary = output / "recovery.tmp"
    for path in (target, checksum, temporary):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Recovery refuses a linked checkpoint or temporary output.")
    existing: bytes | None = None
    if target.exists():
        if not target.is_file() or target.stat().st_size > MAXIMUM_TOTAL_BYTES:
            raise ValueError("Recovery checkpoint exceeds its regular-file read budget.")
        existing = target.read_bytes()
        if (not checksum.is_file() or checksum.stat().st_size > 256
                or checksum.read_text(encoding="utf-8") != hashlib.sha256(existing).hexdigest() + "  recovery.json\n"):
            raise ValueError("Recovery checkpoint digest is missing or inconsistent.")
    imported_at = options.imported_at
    if imported_at is None and existing is not None:
        document = json.loads(existing)
        if not isinstance(document, dict):
            raise ValueError("Recovery checkpoint has an unsupported contract.")
        imported_at = document.get("importedAt")
    imported_at = imported_at or datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    result = recover_git_history(options.repository, options.revision, options.start, options.end,
                                 trusted_heads=options.trusted_head, imported_at=imported_at)
    body = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(body) > MAXIMUM_TOTAL_BYTES:
        raise ValueError("Recovery bundle exceeds its output budget.")
    output.mkdir(parents=True, exist_ok=True)
    if existing is not None and existing != body:
        raise ValueError("Existing recovery checkpoint differs; refusing to overwrite recovered evidence.")
    digest = hashlib.sha256(body).hexdigest()
    if existing is None:
        temporary.write_bytes(body)
        temporary.replace(target)
        checksum.write_text(digest + "  recovery.json\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "sha256": digest, "blobs": len(result["blobs"]),
                      "observations": result["observationCount"], "uniqueHostnames": result["uniqueHostnames"],
                      "candidateDays": result["candidateDays"],
                      "reconciliationRequired": result["reconciliation"]["required"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
