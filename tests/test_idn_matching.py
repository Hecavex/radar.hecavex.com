from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import idna
import pytest

from hecavex_radar import sources
from hecavex_radar.brands import (
    IDN_VISUAL_PROFILE,
    BrandEntry,
    BrandRegistry,
    _domain_hyphen_count,
    domain_match_brands,
    idn_match_evidence,
    load_brand_registry,
    score_domain,
)
from hecavex_radar.certstream_archive import CandidateArchiveWriter, candidate_from_match
from hecavex_radar.normalize import prepare_signal
from hecavex_radar.provenance import reason_codes_from_match
from hecavex_radar.seeds import SeedObservation, build_intelligence_seeds

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry() -> BrandRegistry:
    return load_brand_registry(ROOT / "data" / "brands-lt.json")


@pytest.mark.parametrize(
    ("domain", "brand", "replacement"),
    [
        ("swedbanƙ.example", "Swedbank", "k"),
        ("luminөr.example", "Luminor", "o"),
        ("payѕөra.example", "Paysera", "e"),
        ("ӏuminor.example", "Luminor", "l"),
    ],
)
def test_curated_visual_matches_admit_only_generic_name_evidence(
    registry: BrandRegistry, domain: str, brand: str, replacement: str,
) -> None:
    match = score_domain(domain, registry)
    assert match is not None and match.brand == brand and match.confidence == 95
    codes = reason_codes_from_match(match.reasons)
    assert "brand-domain-match" in codes and "punycode" in codes
    assert not {"brand-exact-token", "unicode-confusable", "mixed-script"}.intersection(codes)
    evidence = idn_match_evidence(domain, registry)
    assert evidence is not None and evidence["brand"] == brand
    assert evidence["substitutions"][0]["replacement"] == replacement
    assert evidence["labelRole"] == "registrable" and evidence["labelIndex"] == 0
    assert score_domain(idna.encode(domain, uts46=True).decode(), registry) == match
    assert idn_match_evidence(idna.encode(domain, uts46=True).decode(), registry) == evidence


def test_trace_keeps_original_positions_and_only_supplemental_mappings(registry: BrandRegistry) -> None:
    evidence = idn_match_evidence("secure-payѕөra.example", registry)
    assert evidence is not None
    assert evidence["matchedLabel"] == "secure-payѕөra"
    assert evidence["substitutions"] == [{"position": 11, "codePoint": "U+04E9", "replacement": "e"}]
    assert IDN_VISUAL_PROFILE == "radar-idn-visual-v1"


def test_curated_candidate_survives_archive_reload_as_unreviewed_name_only(
    registry: BrandRegistry, tmp_path: Path, monkeypatch,
) -> None:
    match = score_domain("luminөr.example", registry)
    assert match is not None
    now = "2026-10-15T12:00:00.000Z"
    candidate = candidate_from_match(match, datetime(2026, 10, 15, 12, tzinfo=UTC))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sources, "load_brand_registry", lambda: registry)
    assert CandidateArchiveWriter("data/certstream").append([candidate]) == 1
    result = sources.load_certstream(now, "data/certstream", 1)
    assert len(result.signals) == 1
    signal = prepare_signal(result.signals[0], now)
    assert signal is not None
    assert (signal["status"], signal["reviewState"], signal["evidenceTier"]) == (
        "suspected", "unreviewed", "name-only",
    )
    assert set(signal["reasonCodes"]) == {"brand-domain-match", "punycode", "different-tld"}
    assert signal["matchScore"] == signal["confidence"] == 95
    seeds = build_intelligence_seeds([SeedObservation(match.domain)], registry)
    assert len(seeds) == 1 and seeds[0].brand == "Luminor"


def test_original_hyphens_and_label_roles(registry: BrandRegistry) -> None:
    match = score_domain("secure-luminөr.example", registry)
    assert match is not None and match.confidence == 100
    assert "multiple hyphens" not in match.reasons
    evidence = idn_match_evidence("luminөr.login.example", registry)
    assert evidence is not None and evidence["labelRole"] == "subdomain"
    assert evidence["labelIndex"] == 0


@pytest.mark.parametrize(
    ("domain", "score"),
    [("secure-swedbank.example", 100), ("swedbаnk.example", 95), ("ḓḫl.example", 85)],
)
def test_valid_baseline_scores_remain_identical(registry: BrandRegistry, domain: str, score: int) -> None:
    match = score_domain(domain, registry)
    assert match is not None and match.confidence == score


def test_punycode_payload_hyphens_never_count_as_original_hyphens(registry: BrandRegistry) -> None:
    domain = "secure-ḓḫl.lt"
    encoded = idna.encode(domain, uts46=True).decode()
    assert encoded.removeprefix("xn--").count("-") == 2
    assert _domain_hyphen_count(encoded) == 1
    match = score_domain(domain, registry)
    assert match is not None
    assert "multiple hyphens" not in match.reasons


def test_existing_baseline_winner_has_no_supplemental_admission_trace() -> None:
    registry = _synthetic_registry("iki")
    match = score_domain("ӏki.test", registry)
    assert match is not None and "brand-exact-token" in reason_codes_from_match(match.reasons)
    assert idn_match_evidence("ӏki.test", registry) is None


@pytest.mark.parametrize(
    "domain",
    ["secure-swedbжank.example", "secure-swedbжank-login.example", "swedbank-ƙ.example",
     "ӏuminxr.example", "login.luminxr.example"],
)
def test_unknown_insertions_neutral_decoration_and_inexact_variants_do_not_admit(
    registry: BrandRegistry, domain: str,
) -> None:
    assert score_domain(domain, registry) is None
    assert idn_match_evidence(domain, registry) is None


def test_visual_alias_needs_complete_token_or_existing_same_label_affix(registry: BrandRegistry) -> None:
    assert score_domain("secureluminөr.example", registry) is not None
    assert score_domain("secure-lumi-nөr.example", registry) is not None
    assert score_domain("gardenluminөr.example", registry) is None
    assert score_domain("lumi.nөr.example", registry) is None


def _synthetic_registry(*aliases: str) -> BrandRegistry:
    return BrandRegistry("regression-only", "2026-10-15", [
        BrandEntry(alias, "2026-10-15", [alias], [], [], [], "fixture", [f"{alias}.example"],
                   ["https://fixture.example/"])
        for alias in aliases
    ])


def test_short_alias_never_gets_fuzzy_or_joined_affix_rules() -> None:
    registry = _synthetic_registry("iki")
    match = score_domain("iƙi.test", registry)
    assert match is not None and match.confidence == 85
    assert score_domain("secure-iƙi.test", registry) is not None
    assert score_domain("secureiƙi.test", registry) is None
    assert score_domain("iƙx.test", registry) is None


def test_ambiguous_readings_fail_closed_across_brands() -> None:
    registry = _synthetic_registry("tone", "tene")
    assert domain_match_brands("tөne.test", registry) == frozenset({"tone", "tene"})
    assert score_domain("tөne.test", registry) is None
    assert idn_match_evidence("tөne.test", registry) is None


def test_article_whole_script_example_is_regression_only() -> None:
    registry = _synthetic_registry("apple")
    match = score_domain("аррӏө.test", registry)
    assert match is not None and match.brand == "apple"
    assert idn_match_evidence("аррӏө.test", registry) is not None


def test_rollback_disables_admission_and_trace_together(registry: BrandRegistry, monkeypatch) -> None:
    monkeypatch.setenv("HECAVEX_IDN_VISUAL_MATCHING", "false")
    assert score_domain("luminөr.example", registry) is None
    assert idn_match_evidence("luminөr.example", registry) is None
    assert score_domain("secure-swedbank.example", registry) is not None
    assert score_domain("secure-swedbжank.example", registry) is None


def test_suppression_and_existing_unicode_behavior_remain(registry: BrandRegistry) -> None:
    entry = next(entry for entry in registry.entries if entry.brand == "Luminor")
    encoded = idna.encode("luminөr.example", uts46=True).decode()
    altered = replace(registry, entries=[replace(entry, excluded_domains=[encoded])])
    assert score_domain("luminөr.example", altered) is None
    assert idn_match_evidence("luminөr.example", altered) is None
    assert score_domain("swedbаnk.example", registry) is not None
    assert score_domain("telїa.example", registry) is not None
    assert score_domain("paүsera.example", registry) is not None
