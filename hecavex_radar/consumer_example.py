"""Offline, integrity-first snapshot comparison. Never emits a blocklist or a benign verdict."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .history_partitions import read_document
from .listening_coverage import stamp


def load_publication(root: Path, expected_manifest: str) -> dict[str, Any]:
    if root.is_symlink() or root.is_junction() or (root / "feed-manifest.json").is_symlink():
        raise ValueError("Linked publication or manifest rejected.")
    root = root.resolve()
    manifest_path = root / "feed-manifest.json"
    if manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Oversized manifest.")
    body = manifest_path.read_bytes()
    if len(body) > 2 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != expected_manifest:
        raise ValueError("Manifest identity mismatch.")
    manifest = json.loads(body)
    if (manifest.get("schemaVersion") != 1 or not isinstance(manifest.get("artifacts"), list)
            or not 1 <= len(manifest["artifacts"]) <= 10000):
        raise ValueError("Unsupported or unbounded manifest.")
    verified: dict[str, bytes] = {}
    total = 0
    def verify_item(item: dict[str, Any]) -> None:
        nonlocal total
        path = item["path"]
        relative = PurePosixPath(path.removeprefix("/data/"))
        if not path.startswith("/data/") or relative.is_absolute() or ".." in relative.parts or "\\" in path:
            raise ValueError("Unsafe artifact path.")
        target = root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(root) or any(
            part.is_symlink() or part.is_junction() for part in [target, *target.parents] if part != root.parent
        ):
            raise ValueError("Link-like artifact rejected.")
        if path in verified or target.stat().st_size != item["bytes"] or item["bytes"] > 16 * 1024 * 1024:
            raise ValueError("Invalid artifact size or duplicate.")
        payload = target.read_bytes()
        total += len(payload)
        if total > 256 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ValueError("Artifact integrity mismatch.")
        verified[path] = payload
    for item in manifest["artifacts"]:
        verify_item(item)

    def document(path: str) -> Any:
        if path not in verified:
            raise ValueError(f"Missing manifest artifact: {path}")
        return json.loads(verified[path])

    snapshot = document("/data/radar.json")
    if snapshot.get("schemaVersion") != 2 or stamp(snapshot.get("generatedAt")) is None:
        raise ValueError("Unsupported snapshot or timestamp.")
    index = document("/data/radar.index.json")
    signals: list[dict[str, Any]] = []
    for shard in index["shards"]:
        path = shard["path"]
        if path not in verified:
            # The manifest binds the index; its descriptors bind every shard.
            verify_item(shard)
        shard_payload = verified.get(path)
        if shard_payload is None or hashlib.sha256(shard_payload).hexdigest() != shard["sha256"]:
            raise ValueError("Missing or altered complete-snapshot shard.")
        shard_rows = json.loads(shard_payload)["signals"]
        if len(shard_rows) != shard["signals"]:
            raise ValueError("Shard row count mismatch.")
        signals.extend(shard_rows)
    if len(signals) != manifest["counts"]["completeSignals"] or len({row["id"] for row in signals}) != len(signals):
        raise ValueError("Incomplete or duplicate signal scope.")
    if index.get("signalCount") != len(signals):
        raise ValueError("Complete index count mismatch.")
    history = read_document(root / "history.json", 12 * 1024 * 1024)
    # Partition reader verifies each embedded digest; additionally require every
    # partition in the publication manifest before exposing history.
    raw_history = document("/data/history.json")
    for part in raw_history.get("partitions", []):
        if "/data/" + part["path"] not in verified:
            raise ValueError("History partition outside manifest.")
    indicators = document("/data/radar-reviewed.stix.json")["objects"]
    return {"manifestSha256": expected_manifest, "generatedAt": snapshot["generatedAt"],
            "signals": {row["id"]: row for row in signals},
            "history": {row["id"]: row for row in history["signals"]},
            "indicators": [row for row in indicators if row.get("type") == "indicator"]}


def compare(before: dict[str, Any], after: dict[str, Any], as_of: str) -> dict[str, Any]:
    now = stamp(as_of)
    if now is None:
        raise ValueError("An explicit canonical as-of time is required.")
    old, new = before["signals"], after["signals"]
    changes = []
    for identifier in sorted(old.keys() | new.keys()):
        if identifier not in new:
            state = "not-in-current-snapshot; reason-unknown; not-a-benign-or-offline-verdict"
        elif identifier not in old:
            state = "added-to-current-snapshot"
        elif old[identifier] == new[identifier]:
            continue
        elif old[identifier].get("lastSeen") != new[identifier].get("lastSeen"):
            state = "observation-boundary-changed; not-continuous-liveness"
        else:
            state = "metadata-or-policy-interpretation-changed"
        changes.append({"signalId": identifier, "change": state,
                        "retainedInHistory": identifier in after["history"],
                        "timestampQuality": "published-normalized; original-vs-fallback-unspecified"})
    indicator_states = []
    for indicator in after["indicators"]:
        expiry = stamp(indicator.get("valid_until"))
        begins = stamp(indicator.get("valid_from"))
        state = ("revoked" if indicator.get("revoked") is True else "invalid-or-unknown"
                 if expiry is None or begins is None or expiry <= begins else "expired" if expiry <= now
                 else "not-yet-valid" if begins > now
                 else "within-reviewed-validity; independent-action-review-required")
        indicator_states.append({"id": indicator["id"], "state": state})
    return {"schemaVersion": 1, "beforeManifest": before["manifestSha256"],
            "afterManifest": after["manifestSha256"], "asOf": as_of,
            "changes": changes, "reviewedIndicators": indicator_states,
            "boundary": "Missing provenance and disappearance remain unknown. No resolution, browsing or blocking."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--before-manifest", required=True)
    parser.add_argument("--after-manifest", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    print(json.dumps(compare(load_publication(args.before, args.before_manifest),
                             load_publication(args.after, args.after_manifest), args.as_of), indent=2))


if __name__ == "__main__":
    main()
