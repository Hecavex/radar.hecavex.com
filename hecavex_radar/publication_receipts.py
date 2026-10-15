"""Append verified Pages-publication facts without inventing legacy clocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from .observation_publication import (
    INDEX,
    MAX_PARTS,
    MAX_RESPONSE,
    METRICS,
    atomic_write,
    encode,
    read_observed_hostnames,
    validate_period_artifacts,
)
from .observation_store import validate_timestamp

ROOT = Path("data/history/publications")
MAXIMUM_MONTH_BYTES = 8 * 1024 * 1024
MAXIMUM_TOTAL_BYTES = 32 * 1024 * 1024
SHA40 = re.compile(r"[a-f0-9]{40}")
SHA64 = re.compile(r"[a-f0-9]{64}")
HOST_ID = re.compile(r"[a-f0-9]{20}")
MAXIMUM_VERIFY_SECONDS = 60.0
MAXIMUM_REQUEST_SECONDS = 5.0
MAXIMUM_COHORT_BYTES = (MAX_PARTS + 2) * MAX_RESPONSE
ServedFetcher = Callable[[str, int, float], bytes]


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.is_junction() or path.stat().st_size > MAXIMUM_MONTH_BYTES:
        raise ValueError("Publication receipts refuse linked or oversized data")
    value = json.loads(path.read_bytes())
    if (not isinstance(value, dict) or type(value.get("schemaVersion")) is not int
            or value.get("schemaVersion") != 1):
        raise ValueError("Publication receipt metadata is invalid")
    return value


def _safe_root(repository: Path) -> Path:
    target = repository.resolve() / ROOT
    for parent in (target, *target.parents):
        if parent == repository.resolve():
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Publication receipt path is linked")
    return target


def _identifier(row: Mapping[str, object]) -> str:
    return hashlib.sha256(encode({key: value for key, value in row.items() if key != "id"})).hexdigest()


def _validate_receipt(row: object) -> dict[str, Any]:
    keys = {"id", "sourceRevision", "dataRevision", "hostnamesSha256", "publishedAt", "hostnameIds"}
    if not isinstance(row, dict) or set(row) != keys:
        raise ValueError("Invalid publication receipt fields")
    validate_timestamp(row["publishedAt"])
    if any(not isinstance(row[key], str) or SHA40.fullmatch(row[key]) is None
           for key in ("sourceRevision", "dataRevision")):
        raise ValueError("Publication receipt revisions must be full Git identities")
    if not isinstance(row["hostnamesSha256"], str) or SHA64.fullmatch(row["hostnamesSha256"]) is None:
        raise ValueError("Publication receipt lacks its exact hostname index digest")
    ids = row["hostnameIds"]
    if (not isinstance(ids, list) or len(ids) > 25000 or ids != sorted(set(ids))
            or any(not isinstance(value, str) or HOST_ID.fullmatch(value) is None for value in ids)
            or row["id"] != _identifier(row)):
        raise ValueError("Publication receipt identities or digest are invalid")
    return row


def read_publication_clocks(repository: Path, *, as_of: str) -> tuple[dict[str, str], str | None]:
    validate_timestamp(as_of)
    root = _safe_root(repository)
    activation: str | None = None
    capture_start: str | None = None
    activation_path = root / "activation.json"
    if activation_path.exists():
        metadata = _read(activation_path)
        if set(metadata) != {"schemaVersion", "dataset", "publishedAt"} or (
            metadata["dataset"] != "radar-publication-capture"
        ):
            raise ValueError("Invalid publication-capture activation")
        value = validate_timestamp(metadata["publishedAt"])
        capture_start = value
        if value <= as_of:
            activation = value
    clocks: dict[str, str] = {}
    total = activation_path.stat().st_size if activation_path.exists() else 0
    if total > MAXIMUM_TOTAL_BYTES:
        raise ValueError("Publication receipt archive exceeds capacity")
    seen: set[str] = set()
    for path in sorted(root.glob("????-??.json")):
        total += path.stat().st_size
        if total > MAXIMUM_TOTAL_BYTES:
            raise ValueError("Publication receipt archive exceeds capacity")
        metadata = _read(path)
        if set(metadata) != {"schemaVersion", "dataset", "receipts"} or (
            metadata["dataset"] != "radar-publication-receipts" or not isinstance(metadata["receipts"], list)
        ):
            raise ValueError("Invalid monthly publication receipt archive")
        for raw in metadata["receipts"]:
            row = _validate_receipt(raw)
            if capture_start is None or row["publishedAt"] < capture_start:
                raise ValueError("Publication receipt precedes or lacks capture activation")
            if row["publishedAt"][:7] != path.stem or row["id"] in seen:
                raise ValueError("Publication receipt month or uniqueness is invalid")
            seen.add(row["id"])
            if row["publishedAt"] <= as_of:
                for hostname_id in row["hostnameIds"]:
                    clocks[hostname_id] = min(clocks.get(hostname_id, row["publishedAt"]), row["publishedAt"])
    return clocks, activation


def record_publication_receipt(
    repository: Path, records: Sequence[Mapping[str, Any]], *,
    source_revision: str, data_revision: str, hostnames_sha256: str, published_at: str,
) -> dict[str, object]:
    validate_timestamp(published_at)
    root = _safe_root(repository)
    clocks, _ = read_publication_clocks(repository, as_of=published_at)
    ids = []
    for record in records:
        hostname_id = record["id"]
        recorded_at = record.get("firstRecordedAt")
        if recorded_at is not None:
            validate_timestamp(recorded_at)
            if recorded_at > published_at:
                raise ValueError("A hostname cannot be published before its tracked recording")
            if record.get("firstPublishedAt") is None and hostname_id not in clocks:
                ids.append(hostname_id)
    row = {
        "sourceRevision": source_revision, "dataRevision": data_revision, "hostnamesSha256": hostnames_sha256,
        "publishedAt": published_at, "hostnameIds": sorted(set(ids)),
    }
    receipt = _validate_receipt({**row, "id": _identifier(row)})
    activation_path = root / "activation.json"
    activation_body = encode({"schemaVersion": 1, "dataset": "radar-publication-capture", "publishedAt": published_at})
    if activation_path.exists():
        activation_body = activation_path.read_bytes()
        if _read(activation_path)["publishedAt"] > published_at:
            raise ValueError("Publication receipt cannot precede capture activation")
    month = root / (published_at[:7] + ".json")
    metadata: dict[str, Any] = _read(month) if month.exists() else {
        "schemaVersion": 1, "dataset": "radar-publication-receipts", "receipts": [],
    }
    by_id = {_validate_receipt(item)["id"]: item for item in metadata["receipts"]}
    if ids:
        by_id[receipt["id"]] = receipt
    metadata["receipts"] = sorted(by_id.values(), key=lambda item: (item["publishedAt"], item["id"]))
    month_body = encode(metadata)
    total = len(activation_body) + sum(path.stat().st_size for path in root.glob("????-??.json"))
    if ids:
        total += len(month_body) - (month.stat().st_size if month.exists() else 0)
    if (len(activation_body) > MAXIMUM_MONTH_BYTES or (ids and len(month_body) > MAXIMUM_MONTH_BYTES)
            or total > MAXIMUM_TOTAL_BYTES):
        raise ValueError("Publication receipt archive exceeds capacity before writing")
    # Preflight the complete state before either mutation. No hourly empty
    # receipts: activate capture once, then append only new tracked identities.
    if ids:
        atomic_write(month, month_body, MAXIMUM_MONTH_BYTES)
    if not activation_path.exists():
        atomic_write(activation_path, activation_body)
    read_publication_clocks(repository, as_of=published_at)
    if not ids:
        return {"recordedHostnames": 0, "publicationRecordedFrom": json.loads(activation_body)["publishedAt"]}
    return {"recordedHostnames": len(ids), "receiptId": receipt["id"]}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _fetch_served(url: str, maximum_bytes: int, timeout: float) -> bytes:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Served publication requests require HTTPS")
    # The origin and every fixed artifact path are validated by verify_served_cohort.
    request = urllib.request.Request(  # noqa: S310 - HTTPS only; redirects explicitly disabled.
        url, headers={"User-Agent": "HECAVEX-Radar-Publication-Receipt/1",
                      "Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Served publication artifact has an unsuccessful response")
            deadline = monotonic() + timeout
            chunks: list[bytes] = []
            received = 0
            while received <= maximum_bytes:
                if monotonic() >= deadline:
                    raise ValueError("Served publication response exceeded its time budget")
                chunk = response.read1(min(64 * 1024, maximum_bytes + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
            body = b"".join(chunks)
    except (OSError, urllib.error.URLError) as error:
        raise ValueError("Served publication artifact could not be fetched") from error
    if len(body) > maximum_bytes:
        raise ValueError("Served publication artifact exceeds its response budget")
    return bytes(body)


def verify_served_cohort(publication_root: Path, base_url: str, *, fetch: ServedFetcher | None = None) -> None:
    """Verify exact served index, all parts and recomputed metrics before capture."""
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Served publication base must be an HTTPS origin")
    index, _ = read_observed_hostnames(publication_root)
    _, metrics = validate_period_artifacts(publication_root, expected_as_of=index["asOf"])
    expected: dict[str, bytes] = {}
    for path in (INDEX, *[Path("public") / item["path"].removeprefix("/") for item in index["partitions"]], METRICS):
        body = (publication_root / path).read_bytes()
        if len(body) > MAX_RESPONSE:
            raise ValueError("Local verified publication exceeds its response budget")
        expected["/" + path.relative_to("public").as_posix()] = body
    if (hashlib.sha256(expected["/data/observed-hostnames-v1.json"]).hexdigest() != metrics["hostnamesSha256"]
            or json.loads(expected["/data/period-metrics-v1.json"]) != metrics):
        raise ValueError("Local verified publication changed during cohort validation")
    for descriptor in index["partitions"]:
        body = expected[descriptor["path"]]
        if len(body) != descriptor["bytes"] or hashlib.sha256(body).hexdigest() != descriptor["sha256"]:
            raise ValueError("Local verified publication part changed during cohort validation")
    reader = fetch or _fetch_served
    deadline = monotonic() + MAXIMUM_VERIFY_SECONDS
    total = 0
    for path, expected_body in expected.items():
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ValueError("Served publication verification exceeded its time budget")
        served = reader(base_url.rstrip("/") + path, MAX_RESPONSE, min(MAXIMUM_REQUEST_SECONDS, remaining))
        if not isinstance(served, bytes):
            raise ValueError("Served publication fetcher must return bounded bytes")
        total += len(served)
        if (len(served) > MAX_RESPONSE or total > MAXIMUM_COHORT_BYTES
                or monotonic() > deadline):
            raise ValueError("Served publication verification exceeded its byte or time budget")
        if (len(served) != len(expected_body)
                or hashlib.sha256(served).digest() != hashlib.sha256(expected_body).digest()):
            raise ValueError("Served publication cohort differs from the exact verified artifact")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--data-revision", required=True)
    parser.add_argument("--live-base-url")
    parser.add_argument("--published-at",
                        default=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    options = parser.parse_args(argv)
    index, records = read_observed_hostnames(options.publication_root.resolve())
    validate_timestamp(options.published_at)
    if index["asOf"] > options.published_at:
        raise ValueError("Publication receipt predates the published artifact")
    if options.live_base_url:
        verify_served_cohort(options.publication_root.resolve(), options.live_base_url)
    result = record_publication_receipt(
        options.repository.resolve(), records, source_revision=options.source_revision,
        data_revision=options.data_revision,
        hostnames_sha256=hashlib.sha256((options.publication_root / INDEX).read_bytes()).hexdigest(),
        published_at=options.published_at,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
