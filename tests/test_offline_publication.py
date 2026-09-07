"""Exercise the real publisher, not merely schema-check already published fixtures."""

import json
import shutil
import socket
from contextlib import suppress
from pathlib import Path

import pytest

from hecavex_radar import offline_publication
from hecavex_radar.offline_publication import regenerate_fixture


def test_real_offline_sync_validates_newly_derived_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    for relative in ("data", "public/data"):
        shutil.copytree(repository / relative, tmp_path / relative)
    monkeypatch.chdir(tmp_path)
    regenerate_fixture(tmp_path)
    trends = json.loads((tmp_path / "public/data/daily-trends.json").read_bytes())
    assert trends["countingMethodVersion"] == 2
    assert trends["reobservationSemantics"].startswith("Version 2:")


def test_offline_fixture_refuses_dns_even_if_publisher_swallows_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(offline_publication, "fixture_cutoff", lambda _: None)

    def attempt_dns(**kwargs: object) -> None:
        with suppress(AssertionError):
            socket.getaddrinfo("must-not-resolve.invalid", 443)

    monkeypatch.setattr(offline_publication, "synchronize", attempt_dns)
    monkeypatch.setattr(offline_publication, "validate_publication", lambda *args, **kwargs: None)
    with pytest.raises(AssertionError, match="attempted a network connection"):
        regenerate_fixture(tmp_path)
