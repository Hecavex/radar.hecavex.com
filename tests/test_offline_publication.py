"""Exercise the real publisher, not merely schema-check already published fixtures."""

import json
import shutil
import socket
from contextlib import suppress
from pathlib import Path

import pytest

from hecavex_radar import offline_publication
from hecavex_radar.offline_publication import regenerate_fixture


def test_fixture_cutoff_uses_observations_not_expiry_and_does_not_advance_on_rebuild(tmp_path: Path) -> None:
    public = tmp_path / "public/data"
    public.mkdir(parents=True)
    snapshot = public / "radar.json"
    snapshot.write_text(json.dumps({"generatedAt": "2026-09-07T12:00:00.000Z"}))
    (public / "context.json").write_text(json.dumps({"observedAt": "2026-09-07T12:01:00.000Z",
                                                    "expiresAt": "2099-01-01T00:00:00.000Z"}))
    cutoff = offline_publication.fixture_cutoff(tmp_path)
    assert cutoff.isoformat() == "2026-09-07T12:01:00+00:00"
    snapshot.write_text(json.dumps({"generatedAt": cutoff.isoformat().replace("+00:00", "Z")}))
    assert offline_publication.fixture_cutoff(tmp_path) == cutoff


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
