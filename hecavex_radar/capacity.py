"""Read-only durable-store headroom inventory. Never contacts candidate systems."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from .data_branch import MANIFEST, MAX_FILE, MAX_TOTAL, PUBLICATION, allowed
from .history_partitions import MAXIMUM_PARTS, PART_BYTES, partition_paths, read_document
from .observation_store import (
    INDEX_RELATIVE,
    MAXIMUM_INDEX_BYTES,
    MAXIMUM_PART_BYTES,
    read_observations,
)
from .observation_store import (
    MAXIMUM_PARTS as OBSERVATION_PARTS,
)
from .observation_store import (
    MAXIMUM_TOTAL_BYTES as OBSERVATION_BYTES,
)
from .publication import MAXIMUM_DASHBOARD_BYTES

MAXIMUM_ACTIVE_FILES = 20_000

# Byte caps are per response/partition, not an authorization to discard records.
STORES = (
    ("data/urlscan/search-checkpoints.json", 256 * 1024, "queries", 256,
     "completed cache: 30 days; pending: until resolved"),
    ("data/ct-search/state.json", 128 * 1024, "queries", 128, "durable query cursors"),
    ("data/history/summary.json", 12 * 1024 * 1024, "signals", 25_000, "730 days default"),
    ("public/data/history.json", 512 * 1024, "signals", 5_000, "730 days default; 30 days detail"),
    ("public/data/radar.json", MAXIMUM_DASHBOARD_BYTES, "signals", None, "recent configured snapshot window"),
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
    observation_index = root / INDEX_RELATIVE
    if observation_index.exists():
        observations = read_observations(root)
        document = read_document(observation_index, MAXIMUM_INDEX_BYTES)
        parts = document["partitions"]
        store_bytes = sum(part["bytes"] for part in parts)
        largest = max((part["bytes"] for part in parts), default=0)
        size = observation_index.stat().st_size
        result.append({
            "path": INDEX_RELATIVE.as_posix(), "present": True, "bytes": size,
            "maximumBytes": MAXIMUM_INDEX_BYTES, "headroomBytes": MAXIMUM_INDEX_BYTES - size,
            "records": len(observations), "hostnames": document["hostnameCount"],
            "partitions": len(parts), "maximumPartitions": OBSERVATION_PARTS,
            "partitionBytes": store_bytes, "largestPartitionBytes": largest,
            "maximumPartitionBytes": MAXIMUM_PART_BYTES, "maximumStoreBytes": OBSERVATION_BYTES,
            "storeHeadroomBytes": OBSERVATION_BYTES - store_bytes,
            "retention": "durable normalized facts; no age-based eviction",
        })
    else:
        result.append({"path": INDEX_RELATIVE.as_posix(), "present": False})
    return result


def capacity_report(root: Path, *, warning_percent: int = 80, scope: str = "unspecified") -> dict[str, object]:
    """Measure allowlisted operational files without exporting their contents."""
    if not 0 <= warning_percent <= 100 or root.is_symlink() or root.is_junction():
        raise ValueError("Capacity inventory requires an unlinked root and a 0-100 warning threshold.")
    root = root.resolve(strict=True)
    if any(path.is_symlink() or path.is_junction() for path in (root / "data", root / "public", root / "public/data")):
        raise ValueError("Capacity inventory refuses linked archive roots.")
    stores = inventory(root)
    total = 0
    count = 0
    months: set[str] = set()
    for base in (root / "data", root / "public/data"):
        if not base.exists():
            continue
        for current, directories, filenames in os.walk(base, followlinks=False):
            parent = Path(current)
            if any((parent / name).is_symlink() or (parent / name).is_junction() for name in directories):
                raise ValueError("Capacity inventory refuses linked archive directories.")
            for name in filenames:
                path = parent / name
                if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                    raise ValueError("Capacity inventory refuses linked archive files.")
                if not allowed(path.relative_to(root).as_posix()):
                    continue
                size = path.stat().st_size
                if size > MAX_FILE:
                    raise ValueError("Operational capacity inventory found an oversized blob.")
                total += size
                count += 1
                if total > MAX_TOTAL or count > MAXIMUM_ACTIVE_FILES:
                    raise ValueError("Operational capacity inventory exceeds the data-branch hard limit.")
                for part in path.relative_to(root).parts:
                    if re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?(?:\.json)?", part):
                        months.add(part[:7])
    # Transport metadata lives at repository root and consumes the same byte
    # and file budgets as the data/public trees.
    for name in (MANIFEST, PUBLICATION):
        path = root / name
        if not path.exists():
            continue
        if not path.is_file() or path.is_symlink() or path.is_junction():
            raise ValueError("Capacity inventory refuses linked transport metadata")
        size = path.stat().st_size
        if size > MAX_FILE:
            raise ValueError("Operational capacity inventory found an oversized blob.")
        total += size
        count += 1
        if total > MAX_TOTAL or count > MAXIMUM_ACTIVE_FILES:
            raise ValueError("Operational capacity inventory exceeds the data-branch hard limit.")
    warnings: list[dict[str, object]] = []
    measurements = [("operational-tree", total, MAX_TOTAL, "bytes"),
                    ("operational-files", count, MAXIMUM_ACTIVE_FILES, "files")]
    for store in stores:
        packed = isinstance(store.get("maximumPartitions"), int)
        used, maximum = store.get("bytes"), store.get("maximumBytes")
        if isinstance(used, int) and isinstance(maximum, int):
            measurements.append((str(store["path"]), used, maximum, "bytes"))
        elif not packed:
            used, maximum = store.get("largestPartitionBytes"), store.get("maximumPartitionBytes")
            if isinstance(used, int) and isinstance(maximum, int):
                measurements.append((str(store["path"]), used, maximum, "bytes"))
        # Content-addressed parts normally pack close to their per-response cap.
        # Their validators retain that hard cap; exhaustion warnings use the
        # aggregate store bytes and remaining part slots instead.
        for used_key, maximum_key, label, unit in (("partitionBytes", "maximumStoreBytes", "total", "bytes"),
                                                  ("partitions", "maximumPartitions", "partitions", "partitions")):
            used, maximum = store.get(used_key), store.get(maximum_key)
            if isinstance(used, int) and isinstance(maximum, int):
                measurements.append((str(store["path"]) + "/" + label, used, maximum, unit))
    for measured_path, used, maximum, unit in measurements:
        if used > maximum:
            raise ValueError("Capacity inventory exceeds its declared hard limit")
        if used * 100 >= maximum * warning_percent:
            warning: dict[str, object] = {"path": measured_path, "usagePercent": round(used * 100 / maximum, 2),
                                          "unit": unit, "used": used, "maximum": maximum}
            if unit == "bytes":
                warning.update({"bytes": used, "maximumBytes": maximum})
            warnings.append(warning)
    return {"schemaVersion": 1, "scope": scope, "stores": stores, "activeFiles": count,
            "activeBytes": total, "maximumActiveBytes": MAX_TOTAL, "maximumActiveFiles": MAXIMUM_ACTIVE_FILES,
            "headroomBytes": MAX_TOTAL - total, "headroomFiles": MAXIMUM_ACTIVE_FILES - count,
            "archiveMonths": sorted(months),
            "warningPercent": warning_percent, "warnings": warnings,
            "semantics": "Aggregate active-tree inventory; Git historical objects and deployed HTML are separate."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("unspecified", "ci-fixture", "operational"), default="unspecified")
    parser.add_argument("--warning-percent", type=int, default=80)
    options = parser.parse_args()
    report = capacity_report(Path.cwd(), warning_percent=options.warning_percent, scope=options.scope)
    print(json.dumps(report, indent=2))
    warnings = report["warnings"]
    if not isinstance(warnings, list):
        raise ValueError("Capacity warning inventory has an unsupported contract.")
    for warning in warnings:
        unit = {"bytes": "byte", "files": "file count", "partitions": "partition count"}[warning["unit"]]
        print(f"::warning title=Radar data capacity::{warning['path']} "
              f"uses {warning['usagePercent']}% of its {unit} limit.")


if __name__ == "__main__":
    main()
