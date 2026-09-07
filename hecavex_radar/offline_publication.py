"""Regenerate an isolated source-CI fixture through the real publisher, without network."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from .publication import validate_publication
from .sync import synchronize


def regenerate_fixture(repository: Path, *, cutoff: datetime | None = None) -> None:
    """Only call in a disposable fixture directory; this intentionally writes its data."""
    if repository.resolve() != Path.cwd().resolve():
        raise ValueError("Offline fixture must be the current isolated working directory")
    snapshot = json.loads((repository / "public/data/radar.json").read_bytes())
    # The pinned operational tree includes same-day inputs newer than its last
    # snapshot. A fixed next-day cutoff includes them without aging with CI time.
    cutoff = cutoff or datetime.fromisoformat(snapshot["generatedAt"].replace("Z", "+00:00")) + timedelta(days=1)
    connections: list[object] = []

    def refuse_network(*args: object, **kwargs: object) -> None:
        connections.append(args)
        raise AssertionError("Offline fixture attempted a network connection")

    settings = {"HECAVEX_ENABLED": "false", "CERTSTREAM_ARCHIVE_ENABLED": "true",
                "URLSCAN_ARCHIVE_ENABLED": "true", "RADAR_RETAIN_EXISTING_SIGNALS": "true",
                "URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED": "false"}
    with (patch.dict(os.environ, settings), patch("socket.socket.connect", refuse_network),
          patch("socket.create_connection", refuse_network)):
        synchronize(sync_time=cutoff)
        validate_publication(repository, validate_stix=True)
    if connections:
        raise AssertionError("Offline fixture attempted a network connection")


if __name__ == "__main__":
    regenerate_fixture(Path.cwd())
