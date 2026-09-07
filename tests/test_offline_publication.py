"""Exercise the real publisher, not merely schema-check already published fixtures."""

import json
import shutil
import socket
from pathlib import Path

import pytest

from hecavex_radar.publication import validate_publication
from hecavex_radar.sync import synchronize


def test_real_offline_sync_validates_newly_derived_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    for relative in ("data", "public/data"):
        shutil.copytree(repository / relative, tmp_path / relative)
    connections: list[object] = []

    def refuse_network(*args: object, **kwargs: object) -> None:
        connections.append(args)
        raise AssertionError("Offline publication must not contact external infrastructure")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HECAVEX_ENABLED", "false")
    monkeypatch.setenv("CERTSTREAM_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("URLSCAN_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("RADAR_RETAIN_EXISTING_SIGNALS", "true")
    monkeypatch.setenv("URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED", "false")
    synchronize()
    validate_publication(tmp_path, validate_stix=True)
    trends = json.loads((tmp_path / "public/data/daily-trends.json").read_bytes())
    assert trends["countingMethodVersion"] == 2
    assert trends["reobservationSemantics"].startswith("Version 2:")
    assert not connections
