from __future__ import annotations

import json
from pathlib import Path

from hecavex_radar.brands import (
    SHORT_ALIAS_MAXIMUM_LENGTH,
    UNICODE_SECURITY_PROFILE,
    _alias_parts,
    load_brand_registry,
    score_domain,
)
from hecavex_radar.provenance import reason_codes_from_match

ROOT = Path(__file__).resolve().parents[1]


def test_versioned_matcher_corpus() -> None:
    corpus = json.loads((ROOT / "data" / "matcher" / "lithuanian-brands-v1.json").read_text(encoding="utf-8"))
    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")

    assert corpus["schemaVersion"] == 1
    assert corpus["unicodeProfile"]["uts46"] == UNICODE_SECURITY_PROFILE["uts46"]
    assert corpus["unicodeProfile"]["uts39"] == UNICODE_SECURITY_PROFILE["uts39"]
    assert len({case["id"] for case in corpus["cases"]}) == len(corpus["cases"])
    for entry in registry.entries:
        cases = [case for case in corpus["cases"] if case.get("brand") == entry.brand]
        assert any(case["expected"]["matched"] for case in cases), entry.brand
        assert any(case["domain"] == entry.official_domains[0] for case in cases), entry.brand
        assert any(
            case["domain"].endswith("-garden.example") and not case["expected"]["matched"] for case in cases
        ), entry.brand

    for case in corpus["cases"]:
        result = score_domain(case["domain"], registry)
        expected = case["expected"]
        if not expected["matched"]:
            assert result is None, case["id"]
            assert expected["rejectionReason"]
            continue
        assert result is not None, case["id"]
        assert result.brand == expected["brand"], case["id"]
        minimum, maximum = expected["scoreBand"]
        assert minimum <= result.confidence <= maximum, case["id"]
        reason_codes = set(reason_codes_from_match(result.reasons))
        assert set(expected["reasonCodes"]) <= reason_codes, (case["id"], result.reasons)


def test_every_brand_has_an_independent_review_date() -> None:
    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")
    assert len(registry.entries) == 46
    assert all(entry.last_reviewed_at for entry in registry.entries)


def test_every_alias_retains_a_boundary_delimited_context_candidate() -> None:
    """Exercise every registry alias through the CertStream matcher contract."""

    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")
    checked: set[tuple[str, str]] = set()
    for entry in registry.entries:
        for alias in entry.aliases:
            parts = _alias_parts(alias)
            domain = f"secure-{'-'.join(parts)}.example"
            result = score_domain(domain, registry)
            assert result is not None, (entry.brand, alias, domain)
            assert result.brand == entry.brand, (entry.brand, alias, result.brand)
            assert result.confidence >= 80, (entry.brand, alias, result.confidence)
            checked.add((entry.brand, alias))

    assert len(checked) == sum(len(entry.aliases) for entry in registry.entries)
    assert {brand for brand, _ in checked} == {entry.brand for entry in registry.entries}


def test_neutral_punycode_decoration_never_replaces_context_for_any_brand() -> None:
    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")
    for entry in registry.entries:
        alias = min(
            entry.aliases,
            key=lambda value: (len(_alias_parts(value)), len("".join(_alias_parts(value))), value.casefold()),
        )
        domain = f"{'-'.join(_alias_parts(alias))}-žalias.example"
        assert score_domain(domain, registry) is None, (entry.brand, alias, domain)


def test_unicode_evidence_is_scoped_to_the_alias_span() -> None:
    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")
    result = score_domain("secure-swedbank-école.example", registry)
    assert result is not None
    codes = set(reason_codes_from_match(result.reasons))
    assert "punycode" in codes
    assert codes.isdisjoint({"unicode-confusable", "mixed-script", "restricted-identifier"})


def test_every_short_alias_requires_a_delimiter_but_keeps_qualified_candidates() -> None:
    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")
    checked = 0
    for entry in registry.entries:
        for alias in entry.aliases:
            parts = _alias_parts(alias)
            compact = "".join(parts)
            if len(compact) > SHORT_ALIAS_MAXIMUM_LENGTH:
                continue
            checked += 1
            assert score_domain(f"secure{compact}.example", registry) is None, (entry.brand, alias)
            result = score_domain(f"secure-{'-'.join(parts)}.example", registry)
            assert result is not None, (entry.brand, alias)
            assert result.brand == entry.brand
            assert result.confidence >= 80

    assert checked > 0


def test_every_reviewed_official_domain_is_suppressed() -> None:
    registry = load_brand_registry(ROOT / "data" / "brands-lt.json")
    for entry in registry.entries:
        for domain in entry.official_domains:
            assert score_domain(domain, registry) is None, (entry.brand, domain)
            assert score_domain(f"login.{domain}", registry) is None, (entry.brand, domain)
