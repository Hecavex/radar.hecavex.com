"""A complete, digest-bound public hostname cohort with bounded responses."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .brands import normalize_domain
from .observation_schemas import (
    HOSTNAME_INDEX_SCHEMA,
    HOSTNAME_PART_SCHEMA,
    HOSTNAME_RECORD_SCHEMA,
    PERIOD_METRICS_SCHEMA,
)
from .observation_store import canonical_hostname, grouping_metadata
from .period_metrics import build_period_metrics
from .safety import defang_host, stable_id

INDEX = Path("public/data/observed-hostnames-v1.json")
METRICS = Path("public/data/period-metrics-v1.json")
PART_ROOT = Path("public/data/observed-hostnames-parts")
MAX_RESPONSE = 256 * 1024
MAX_ROWS = 25_000
MAX_PARTS = 512
RECORD_VALIDATOR = Draft202012Validator(HOSTNAME_RECORD_SCHEMA)
INDEX_VALIDATOR = Draft202012Validator(HOSTNAME_INDEX_SCHEMA)
PART_VALIDATOR = Draft202012Validator(HOSTNAME_PART_SCHEMA)
METRICS_VALIDATOR = Draft202012Validator(PERIOD_METRICS_SCHEMA)


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _validate(validator: Any, value: object, label: str) -> None:
    errors = list(validator.iter_errors(value))
    if errors:
        raise ValueError(f"{label} violates its versioned schema: {errors[0].message}")


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("Invalid public observation timestamp") from error
    if result.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ValueError("Non-canonical public observation timestamp")
    return result


def validate_records(records: list[dict[str, Any]], as_of: str) -> None:
    if len(records) > MAX_ROWS:
        raise ValueError("Public hostname cardinality exceeds its supported capacity; no rows were omitted")
    cutoff = _time(as_of)
    ids: list[str] = []
    for row in records:
        _validate(RECORD_VALIDATOR, row, "Observed hostname")
        host = normalize_domain(row["domain"].replace("[.]", "."))
        if host is None or defang_host(host) != row["domain"] or stable_id(row["domain"].lower()) != row["id"]:
            raise ValueError("Observed hostname identity is not canonical")
        group = normalize_domain(row["domainGroup"].replace("[.]", "."))
        if (group is None or defang_host(group) != row["domainGroup"]
                or canonical_hostname(row["domain"])["domainGroup"] != row["domainGroup"]):
            raise ValueError("Observed hostname group is not canonical")
        first, last = _time(row["firstSeen"]), _time(row["lastSeen"])
        if first > last or last > cutoff:
            raise ValueError("Observed source boundaries exceed the publication cutoff")
        days = row["observedDays"]
        maxima = row["observedDayLastSeen"]
        if not days or days != sorted(set(days)) or set(maxima) != set(days):
            raise ValueError("Observed UTC day membership is incomplete or duplicated")
        if days[0] != first.date().isoformat() or days[-1] != last.date().isoformat():
            raise ValueError("Observed day membership does not reconcile with source boundaries")
        for day, timestamp in maxima.items():
            parsed = _time(timestamp)
            if parsed.date().isoformat() != day or not first <= parsed <= last:
                raise ValueError("An observation was assigned to the wrong UTC day")
        if maxima[days[-1]] != row["lastSeen"]:
            raise ValueError("Last observed day does not bind lastSeen")
        for clock in ("firstRecordedAt", "firstPublishedAt"):
            if row[clock] is not None and _time(row[clock]) > cutoff:
                raise ValueError("A recording/publication clock exceeds the cutoff")
        if row["firstPublishedAt"] is not None and (
            row["firstRecordedAt"] is None or row["firstPublishedAt"] < row["firstRecordedAt"]
        ):
            raise ValueError("A publication clock requires an earlier tracked recording")
        if row["sources"] != sorted(set(row["sources"])):
            raise ValueError("Observed sources are not canonical")
        ids.append(row["id"])
    if ids != sorted(set(ids)):
        raise ValueError("Public hostname IDs are duplicated or not canonically ordered")


def _safe(repository: Path, relative: Path) -> Path:
    root = repository.resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError("Observation publication path escaped the repository")
    for item in (target, *target.parents):
        if item == root:
            break
        if item.is_symlink() or item.is_junction():
            raise ValueError("Observation publication refuses linked paths")
    return target


def atomic_write(path: Path, body: bytes, maximum: int = MAX_RESPONSE) -> None:
    if len(body) > maximum:
        raise ValueError("Observation response exceeds its supported byte capacity")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def write_observed_hostnames(
    repository: Path, records: list[dict[str, Any]], *, as_of: str,
    coverage: dict[str, Any], policy_versions: dict[str, str], grouping: dict[str, Any],
) -> dict[str, Any]:
    validate_records(records, as_of)
    chunks: list[bytes] = []
    current: list[bytes] = []
    current_size = 3
    for row in records:
        body = encode(row).rstrip(b"\n")
        if len(body) + 3 > MAX_RESPONSE:
            raise ValueError("One public hostname record exceeds the part budget")
        if current and current_size + len(body) + 1 > MAX_RESPONSE:
            chunks.append(b"[" + b",".join(current) + b"]\n")
            current, current_size = [], 3
        current.append(body)
        current_size += len(body) + 1
    if current:
        chunks.append(b"[" + b",".join(current) + b"]\n")
    if len(chunks) > MAX_PARTS:
        raise ValueError("Public hostname parts exceed their finite capacity")
    descriptors: list[dict[str, Any]] = []
    for body in chunks:
        digest = hashlib.sha256(body).hexdigest()
        descriptors.append({
            "path": f"/data/observed-hostnames-parts/{digest}.json", "sha256": digest,
            "bytes": len(body), "records": len(json.loads(body)),
        })
    index = {
        "schemaVersion": 1, "dataset": "radar-observed-hostnames", "generatedAt": as_of, "asOf": as_of,
        "recordCount": len(records), "coverage": coverage, "policyVersions": policy_versions,
        "grouping": grouping, "partitions": descriptors,
    }
    _validate(INDEX_VALIDATOR, index, "Observed hostname index")
    index_bytes = encode(index)
    if len(index_bytes) > MAX_RESPONSE:
        raise ValueError("Observed hostname index exceeds its finite byte budget")
    targets = [_safe(repository, Path("public") / row["path"].removeprefix("/")) for row in descriptors]
    index_path = _safe(repository, INDEX)
    parts_root = _safe(repository, PART_ROOT)
    for target, body in zip(targets, chunks, strict=True):
        atomic_write(target, body)
    atomic_write(index_path, index_bytes)
    # Only obsolete generated siblings, after the complete new index commits.
    retained = {target.name for target in targets}
    if parts_root.exists():
        for path in parts_root.iterdir():
            if re.fullmatch(r"[a-f0-9]{64}\.json(?:\.sha256)?", path.name):
                _safe(repository, path.relative_to(repository.resolve()))
                if path.name.removesuffix(".sha256") not in retained:
                    path.unlink()
    return index


def read_observed_hostnames(repository: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    index_path = _safe(repository, INDEX)
    try:
        if index_path.stat().st_size > MAX_RESPONSE:
            raise ValueError("Observed hostname index exceeds its byte budget")
        index = json.loads(index_path.read_bytes())
        _validate(INDEX_VALIDATOR, index, "Observed hostname index")
        if index["generatedAt"] != index["asOf"]:
            raise ValueError("Observed hostname index has a mixed cutoff")
        records: list[dict[str, Any]] = []
        paths: set[str] = set()
        for descriptor in index["partitions"]:
            relative = descriptor["path"]
            if relative in paths:
                raise ValueError("Observed hostname index repeats a partition")
            paths.add(relative)
            part = _safe(repository, Path("public") / relative.removeprefix("/"))
            if part.stat().st_size != descriptor["bytes"]:
                raise ValueError("Observed hostname partition byte count differs")
            body = part.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if digest != descriptor["sha256"] or part.stem != digest:
                raise ValueError("Observed hostname partition digest differs")
            rows = json.loads(body)
            _validate(PART_VALIDATOR, rows, "Observed hostname partition")
            if len(rows) != descriptor["records"]:
                raise ValueError("Observed hostname partition row count differs")
            records.extend(rows)
            if len(records) > index["recordCount"]:
                raise ValueError("Observed hostname parts exceed their declared total")
        if len(records) != index["recordCount"]:
            raise ValueError("Observed hostname parts are incomplete")
        validate_records(records, index["asOf"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Observed hostname cohort is incomplete or unreadable") from error
    return index, records


def publication_paths(repository: Path) -> list[Path]:
    index, _ = read_observed_hostnames(repository)
    return [repository / INDEX, *[
        repository / "public" / row["path"].removeprefix("/") for row in index["partitions"]
    ]]


def write_period_artifact(repository: Path) -> dict[str, Any]:
    index, records = read_observed_hostnames(repository)
    metrics = build_period_metrics(
        records, as_of=index["asOf"], hostnames_sha256=hashlib.sha256((repository / INDEX).read_bytes()).hexdigest(),
        coverage=index["coverage"], policy_versions=index["policyVersions"],
    )
    _validate(METRICS_VALIDATOR, metrics, "Period metrics")
    atomic_write(_safe(repository, METRICS), encode(metrics))
    return dict(metrics)


def validate_period_artifacts(repository: Path, *, expected_as_of: str) -> tuple[dict[str, Any], dict[str, Any]]:
    index, records = read_observed_hostnames(repository)
    target = _safe(repository, METRICS)
    if target.stat().st_size > MAX_RESPONSE:
        raise ValueError("Period metrics exceed the response budget")
    metrics = json.loads(target.read_bytes())
    _validate(METRICS_VALIDATOR, metrics, "Period metrics")
    if index["asOf"] != expected_as_of or index["grouping"] != grouping_metadata():
        raise ValueError("Observation cohort uses a different cutoff or grouping policy")
    expected = build_period_metrics(
        records, as_of=expected_as_of, hostnames_sha256=hashlib.sha256((repository / INDEX).read_bytes()).hexdigest(),
        coverage=index["coverage"], policy_versions=index["policyVersions"],
    )
    if metrics != expected:
        raise ValueError("Period metrics do not reconcile with the complete digest-bound hostname cohort")
    return index, metrics
