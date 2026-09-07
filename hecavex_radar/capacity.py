"""Read-only durable-store headroom inventory. Never contacts candidate systems."""

from __future__ import annotations

import json
from pathlib import Path

from .history_partitions import MAXIMUM_PARTS, PART_BYTES, partition_paths, read_document

# Byte caps are per response/partition, not an authorization to discard records.
STORES = (
    ("data/urlscan/search-checkpoints.json", 256 * 1024, "queries", 256,
     "completed cache: 30 days; pending: until resolved"),
    ("data/ct-search/state.json", 128 * 1024, "queries", 128, "durable query cursors"),
    ("data/history/summary.json", 12 * 1024 * 1024, "signals", 25_000, "730 days default"),
    ("public/data/history.json", 512 * 1024, "signals", 5_000, "730 days default; 30 days detail"),
    ("public/data/radar.json", 256 * 1024, "signals", None, "recent configured snapshot window"),
)


def inventory(root: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for relative, maximum, field, rows, retention in STORES:
        path = root / relative
        if not path.exists():
            result.append({"path": relative, "present": False})
            continue
        if path.is_symlink() or path.is_junction() or path.resolve().is_relative_to(root.resolve()) is False:
            raise ValueError("Capacity inventory refuses paths outside the repository.")
        if path.stat().st_size > maximum:
            raise ValueError(f"{relative} exceeds its per-document budget.")
        document = read_document(path, maximum)
        partitions = partition_paths(path) if "history" in relative else []
        count = len(document.get(field, []))
        result.append({
            "path": relative, "present": True, "bytes": path.stat().st_size, "maximumBytes": maximum,
            "headroomBytes": maximum - path.stat().st_size, "records": count, "defaultRecordLimit": rows,
            "retention": retention, "partitions": len(partitions),
            "partitionBytes": sum(part.stat().st_size for part in partitions),
            "maximumPartitionBytes": PART_BYTES if partitions else None,
            "maximumPartitions": MAXIMUM_PARTS if partitions else None,
        })
    for directory, pattern, maximum, count_limit, retention in (
        ("data/certstream", "attempts.ndjson", 256 * 1024, 256, "Vilnius-day partitions"),
        ("data/certstream", "domains.ndjson", 25 * 1024 * 1024, 25_000, "Vilnius-day partitions"),
        ("data/history/daily", "*.ndjson", 8 * 1024 * 1024, 10_000, "30 days default detail"),
    ):
        files = sorted((root / directory).rglob(pattern))
        if any(path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) for path in files):
            raise ValueError("Capacity inventory refuses linked archive paths.")
        largest = max((path.stat().st_size for path in files), default=0)
        if largest > maximum:
            raise ValueError(f"{directory} has an oversized partition.")
        result.append({"path": f"{directory}/**/{pattern}", "partitions": len(files),
                       "largestPartitionBytes": largest, "maximumPartitionBytes": maximum,
                       "headroomBytes": maximum - largest, "recordsPerPartitionLimit": count_limit,
                       "retention": retention})
    return result


def main() -> None:
    print(json.dumps({"schemaVersion": 1, "stores": inventory(Path.cwd())}, indent=2))


if __name__ == "__main__":
    main()
