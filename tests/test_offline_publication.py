"""Exercise the real publisher, not merely schema-check already published fixtures."""

import json
import shutil
from pathlib import Path

import pytest

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
