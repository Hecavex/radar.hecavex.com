"""Regenerate an isolated source-CI fixture through the real publisher, without network."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from .publication import validate_publication
from .sync import synchronize

OBSERVATION_TIMES = {"generatedAt", "observedAt", "sourceObservedAt", "firstSeen", "lastSeen",
                     "lastSuccessfulSyncAt", "startedAt", "finishedAt", "completedAt", "updatedAt",
                     "checkedAt", "fetchedAt", "collectedAt", "reviewedAt", "publishedAt"}


def fixture_cutoff(repository: Path) -> datetime:
    """Use retained observation times, never cache expiry or the advancing wall clock."""
    snapshot = json.loads((repository / "public/data/radar.json").read_bytes())
    latest = datetime.fromisoformat(snapshot["generatedAt"].replace("Z", "+00:00"))
    total = 0
    count = 0

    def inspect(value: object) -> None:
        nonlocal latest
        if isinstance(value, dict):
            for key, item in value.items():
                if key in OBSERVATION_TIMES and isinstance(item, str) and item.endswith("Z"):
                    try:
                        candidate = datetime.fromisoformat(item.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    latest = max(latest, candidate)
                elif isinstance(item, (dict, list)):
                    inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    for root in (repository / "data", repository / "public/data"):
        for path in root.rglob("*"):
            if path.suffix not in {".json", ".ndjson"} or not path.is_file():
                continue
            size = path.stat().st_size
            count += 1
            total += size
            if size > 32 * 1024 * 1024 or total > 256 * 1024 * 1024 or count > 20000:
                raise ValueError("Offline fixture exceeds bounded input capacity")
            contents = path.read_text(encoding="utf-8")
            if path.suffix == ".ndjson":
                for line in contents.splitlines():
                    if line.strip():
                        inspect(json.loads(line))
            else:
                inspect(json.loads(contents))
    return latest


def regenerate_fixture(repository: Path, *, cutoff: datetime | None = None) -> None:
    """Only call in a disposable fixture directory; this intentionally writes its data."""
    if repository.resolve() != Path.cwd().resolve():
        raise ValueError("Offline fixture must be the current isolated working directory")
    cutoff = cutoff or fixture_cutoff(repository)
    connections: list[object] = []

    def refuse_network(*args: object, **kwargs: object) -> None:
        connections.append(args)
        raise AssertionError("Offline fixture attempted a network connection")

    settings = {"HECAVEX_ENABLED": "false", "CERTSTREAM_ARCHIVE_ENABLED": "true",
                "URLSCAN_ARCHIVE_ENABLED": "true", "RADAR_RETAIN_EXISTING_SIGNALS": "true",
                "URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED": "false"}
    with ExitStack() as guards:
        guards.enter_context(patch.dict(os.environ, settings))
        for name in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                     "socket.create_connection", "socket.getaddrinfo", "socket.gethostbyname",
                     "socket.gethostbyname_ex"):
            guards.enter_context(patch(name, refuse_network))
        synchronize(sync_time=cutoff)
        validate_publication(repository, validate_stix=True)
    if connections:
        raise AssertionError("Offline fixture attempted a network connection")


if __name__ == "__main__":
    regenerate_fixture(Path.cwd())
