"""Transient seed adapters: offline fetcher only; seeds are hints and never published rows."""
from __future__ import annotations

from pathlib import Path

import pytest

from hecavex_radar import seeds
from hecavex_radar.brands import load_brand_registry

REGISTRY = load_brand_registry(Path(__file__).resolve().parents[1] / "data" / "brands-lt.json")
FEEDS = {
    seeds.PHISHDESTROY_URL: b"swedbank-login.example\n",
    seeds.CERTPL_URL: b"",
    seeds.PHISHING_DATABASE_URL: b"# header\ndhl-zustellung.example\nordinary.example\n",
    seeds.HAGEZI_NRD_URL: b"revolut-support.example\nbakery.example\nxn--revolut-login.example\n",
}


def fetch(url: str, headers: dict[str, str], hosts: tuple[str, ...]) -> bytes:
    assert url.startswith("https://") and url.split("/")[2] in hosts
    return FEEDS[url]


def test_phishing_database_and_nrd_seed_the_hunt(monkeypatch: pytest.MonkeyPatch) -> None:
    result = seeds.load_intelligence_seeds(REGISTRY, fetch)
    assert (result.configured, result.completed, result.failed) == (4, 4, 0)
    assert {(seed.domain, seed.brand) for seed in result.seeds} == {
        ("swedbank-login.example", "Swedbank"),
        ("dhl-zustellung.example", "DHL"),
        ("revolut-support.example", "Revolut"),
    }
    monkeypatch.setenv("HAGEZI_NRD_SEED_ENABLED", "false")
    monkeypatch.setenv("PHISHING_DATABASE_SEED_ENABLED", "false")
    assert seeds.load_intelligence_seeds(REGISTRY, fetch).configured == 2


def test_text_feed_row_limit_is_per_feed() -> None:
    body = b"\n".join(b"row%d.example" % index for index in range(10))
    assert len(seeds.parse_text_feed(body, 4)) == 4
    assert len(seeds.parse_text_feed(body)) == 10


@pytest.mark.parametrize("row", ["Swedbank-Login.example", "*.swedbank-login.example", "swedbank-login[.]example"])
def test_ascii_shortcut_keeps_rows_the_full_path_keeps(row: str) -> None:
    prefilter = seeds._compile_brand_prefilter(REGISTRY)
    assert seeds._may_reach_matcher(row, prefilter)
