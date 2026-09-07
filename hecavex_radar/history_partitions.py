"""Content-addressed bounded history partitions, with no silent row eviction."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

PART_BYTES = 256 * 1024
MAXIMUM_PARTS = 512
MAXIMUM_ROWS = 25_000
FORMAT = "hecavex-history-partitions-v1"


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _prune_unreferenced(parts_root: Path, retained: set[str]) -> None:
    """Only generated, content-addressed siblings, after atomic index commit.

    Git preserves earlier committed versions. Unexpected files are never removed.
    """
    if not parts_root.exists():
        return
    if parts_root.is_symlink() or parts_root.is_junction():
        raise ValueError("Refuse cleanup through a linked history directory.")
    resolved = parts_root.resolve(strict=True)
    for target in parts_root.iterdir():
        if not re.fullmatch(r"[a-f0-9]{64}\.json(?:\.sha256)?", target.name):
            continue
        base_name = target.name.removesuffix(".sha256")
        if base_name in retained:
            continue
        if target.is_symlink() or target.is_junction() or target.resolve().parent != resolved:
            raise ValueError("Refuse cleanup of a linked history partition.")
        if target.is_file():
            target.unlink()


def read_document(path: Path, maximum: int) -> dict[str, Any]:
    if path.is_symlink() or path.is_junction() or path.stat().st_size > maximum:
        raise ValueError("History document is oversized or linked.")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("History document must be an object.")
    if "partitionFormat" not in value:
        return value
    if value.get("partitionFormat") != FORMAT or value.get("schemaVersion") != 2:
        raise ValueError("Unknown history partition format.")
    rows = value.get("signalCount")
    parts = value.get("partitions")
    if type(rows) is not int or not 0 <= rows <= MAXIMUM_ROWS or value.get("signals") != []:
        raise ValueError("Invalid history partition count or embedded rows.")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAXIMUM_PARTS:
        raise ValueError("Invalid history partition inventory.")
    signals: list[object] = []
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, dict) or set(part) != {"path", "bytes", "sha256", "signals"}:
            raise ValueError("Invalid history partition descriptor.")
        relative = part["path"]
        pattern = rf"{re.escape(path.stem)}-parts/[a-f0-9]{{64}}\.json"
        if not isinstance(relative, str) or not re.fullmatch(pattern, relative):
            raise ValueError("History partition path is not allowlisted.")
        target = path.parent / relative
        if not target.exists():
            raise ValueError("A declared history partition is missing. History is incomplete.")
        if target.parent.is_symlink() or target.parent.is_junction() or target.is_symlink() or target.is_junction():
            raise ValueError("History partitions refuse linked paths.")
        size = part["bytes"]
        count = part["signals"]
        if type(size) is not int or not 0 < size <= PART_BYTES or target.stat().st_size != size:
            raise ValueError("History partition byte count mismatch.")
        if type(count) is not int or not 0 < count <= MAXIMUM_ROWS or relative in seen:
            raise ValueError("History partition row count or duplicate path.")
        body = target.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if part["sha256"] != digest or target.stem != digest:
            raise ValueError("History partition digest mismatch.")
        chunk = json.loads(body)
        if not isinstance(chunk, list) or len(chunk) != count:
            raise ValueError("History partition content count mismatch.")
        signals.extend(chunk)
        seen.add(relative)
        if len(signals) > rows:
            raise ValueError("History partitions exceed declared total.")
    if len(signals) != rows:
        raise ValueError("History partition completeness mismatch.")
    return {**{key: item for key, item in value.items() if key not in {
        "partitionFormat", "partitions", "signalCount",
    }}, "schemaVersion": 1, "signals": signals}


def write_document(
    path: Path, payload: dict[str, Any], maximum: int,
    atomic_write: Callable[[Path, bytes, int], None],
) -> None:
    if path.is_symlink() or path.is_junction() or path.parent.is_symlink() or path.parent.is_junction():
        raise ValueError("History writer refuses linked paths.")
    parts_root = path.parent / f"{path.stem}-parts"
    if parts_root.is_symlink() or parts_root.is_junction():
        raise ValueError("History writer refuses a linked partition directory.")
    body = encode(payload)
    if len(body) <= maximum:
        atomic_write(path, body, maximum)
        _prune_unreferenced(parts_root, set())
        return
    signals = payload["signals"]
    if not isinstance(signals, list) or len(signals) > MAXIMUM_ROWS:
        raise ValueError("History growth exceeds supported row cardinality.")
    chunks: list[bytes] = []
    current: list[bytes] = []
    size = 3
    for row in signals:
        encoded = encode(row).rstrip(b"\n")
        if len(encoded) + 3 > PART_BYTES:
            raise ValueError("One history row exceeds the bounded partition size.")
        if current and size + len(encoded) + 1 > PART_BYTES:
            chunks.append(b"[" + b",".join(current) + b"]\n")
            current, size = [], 3
        current.append(encoded)
        size += len(encoded) + 1
    if current:
        chunks.append(b"[" + b",".join(current) + b"]\n")
    if len(chunks) > MAXIMUM_PARTS:
        raise ValueError("History growth exceeds the finite partition budget.")
    descriptors = []
    for chunk in chunks:
        digest = hashlib.sha256(chunk).hexdigest()
        descriptors.append({
            "path": f"{path.stem}-parts/{digest}.json", "sha256": digest,
            "bytes": len(chunk), "signals": len(json.loads(chunk)),
        })
    index = {
        **payload, "schemaVersion": 2, "signals": [], "partitionFormat": FORMAT,
        "signalCount": len(signals), "partitions": descriptors,
    }
    index_body = encode(index)
    if len(index_body) > maximum:
        raise ValueError("History partition index exceeds its finite document budget.")
    # Validate all capacity before touching files. Content addressing prevents
    # a failed write from invalidating a previously published index.
    for descriptor, chunk in zip(descriptors, chunks, strict=True):
        target = path.parent / str(descriptor["path"])
        if target.is_symlink() or target.is_junction():
            raise ValueError("History writer refuses linked partitions.")
        atomic_write(target, chunk, PART_BYTES)
    atomic_write(path, index_body, maximum)
    _prune_unreferenced(parts_root, {Path(str(row["path"])).name for row in descriptors})


def partition_paths(path: Path) -> list[Path]:
    """Return only the currently referenced, already validated partition set."""
    read_document(path, 12 * 1024 * 1024)
    raw = json.loads(path.read_bytes())
    return [path.parent / row["path"] for row in raw.get("partitions", [])]
