from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from hecavex_radar.observation_store import (
    ObservationInput,
    append_observations,
    build_public_records,
    canonical_hostname,
    read_observations,
)


def observation(
    domain: str = "login.swedbank.example", timestamp: str = "2026-09-01T10:00:00.000Z",
) -> ObservationInput:
    return {
        "domain": domain, "sources": ["CertStream"], "sourceObservedAt": timestamp,
        "sourceTimeProvenance": "legacy-history-boundary", "radarRecordedAt": None,
        "importedAt": "2026-10-15T12:00:00.000Z", "providerEventId": None,
        "originalMatch": {"brand": "Swedbank", "policyVersion": "legacy-unknown", "score": None},
        "assessment": None,
        "provenance": [{"commit": "a" * 40, "path": "data/history/daily/2026-09-01.ndjson",
                        "blobOid": "b" * 40, "sha256": "c" * 64, "legacyEventId": "d" * 32}],
    }


def test_hostname_identity_normalizes_idna_but_keeps_subdomains_distinct() -> None:
    unicode_host = canonical_hostname("shop.luminөr.example")
    assert canonical_hostname(unicode_host["domain"]) == unicode_host
    assert unicode_host["domain"].startswith("shop[.]xn--")
    assert canonical_hostname("a.host.blogspot.com")["domainGroup"] == "host[.]blogspot[.]com"
    assert canonical_hostname("a.host.blogspot.com")["id"] != canonical_hostname("b.host.blogspot.com")["id"]


def test_import_is_idempotent_and_annotation_variants_do_not_multiply_facts(tmp_path: Path) -> None:
    original = observation()
    first = append_observations(tmp_path, [original], updated_at="2026-10-15T12:00:00.000Z")
    variant = cast(ObservationInput, {
        **original, "originalMatch": {"brand": "Swedbank", "policyVersion": "later-policy", "score": 90},
        "provenance": [{**original["provenance"][0], "legacyEventId": "e" * 32}],
    })
    second = append_observations(tmp_path, [variant, original], updated_at="2026-10-15T12:01:00.000Z")
    records = read_observations(tmp_path)
    assert first["addedObservations"] == 1
    assert second["addedObservations"] == 0
    assert second["hostnameCount"] == 1
    assert len(records) == 1
    assert len(records[0]["matchAnnotations"]) == 2
    assert len(records[0]["provenance"]) == 2
    assert records[0]["radarRecordedAt"] is None
    assert records[0]["importedAt"] == original["importedAt"]


def test_known_live_recording_clock_does_not_rewrite_unknown_legacy_first_recording(tmp_path: Path) -> None:
    old = observation()
    new = cast(ObservationInput, {**observation(timestamp="2026-10-15T12:00:00.000Z"),
                                 "sourceTimeProvenance": "provider-event-time",
                                 "radarRecordedAt": "2026-10-15T12:00:00.000Z"})
    append_observations(tmp_path, [old, new], updated_at="2026-10-15T12:00:00.000Z")
    selected = canonical_hostname(old["domain"])["id"]
    public = build_public_records(read_observations(tmp_path), as_of="2026-10-15T12:00:00.000Z",
                                  eligible_matches={selected: {"brand": "Swedbank", "score": 90,
                                                               "reasonCodes": [], "policyVersion": "current"}})
    assert public[0]["firstRecordedAt"] is None
    assert public[0]["lastSeen"] == new["sourceObservedAt"]


def test_legacy_host_cannot_gain_a_modern_first_publication_clock_from_receipt_map(tmp_path: Path) -> None:
    append_observations(tmp_path, [observation()], updated_at="2026-10-15T12:00:00.000Z")
    selected = canonical_hostname(observation()["domain"])["id"]
    public = build_public_records(read_observations(tmp_path), as_of="2026-10-15T12:00:00.000Z",
                                  eligible_matches={selected: {"brand": "Swedbank", "score": 90,
                                                               "reasonCodes": [], "policyVersion": "current"}},
                                  first_published_at={selected: "2026-10-15T11:00:00.000Z"})
    assert public[0]["firstRecordedAt"] is None
    assert public[0]["firstPublishedAt"] is None


def test_capacity_failure_preserves_previously_committed_fact_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hecavex_radar.observation_store as store

    append_observations(tmp_path, [observation()], updated_at="2026-10-15T12:00:00.000Z")
    index_path = tmp_path / "data/history/observations/index.json"
    before = index_path.read_bytes()
    existing_bytes = sum(row["bytes"] for row in json.loads(before)["partitions"])
    monkeypatch.setattr(store, "MAXIMUM_TOTAL_BYTES", existing_bytes + 100)
    with pytest.raises(ValueError, match="capacity exceeded"):
        append_observations(tmp_path, [observation("other.swedbank.example")],
                            updated_at="2026-10-15T12:00:01.000Z")
    assert index_path.read_bytes() == before
    assert len(read_observations(tmp_path)) == 1


def test_explicit_suspicious_assessment_preserves_independent_analyst_confidence(tmp_path: Path) -> None:
    reviewed = cast(ObservationInput, {**observation(), "assessment": {
        "verdict": "suspicious", "assessedAt": "2026-10-15T11:00:00.000Z",
        "evidenceReferences": ["review:evidence-1"], "decisionId": "a" * 24, "analystConfidence": 65,
    }})
    append_observations(tmp_path, [reviewed], updated_at="2026-10-15T12:00:00.000Z")
    fact = read_observations(tmp_path)[0]
    assert fact["assessments"] == [reviewed["assessment"]]
    assert fact["matchAnnotations"][0]["score"] is None


@pytest.mark.parametrize("assessment", [
    {"verdict": "active", "assessedAt": "2026-10-15T11:00:00.000Z", "evidenceReferences": ["reference"],
     "decisionId": "a" * 24, "analystConfidence": 65},
    {"verdict": "malicious", "assessedAt": "2026-10-15T11:00:00.000Z", "evidenceReferences": ["reference"],
     "decisionId": "a" * 24, "analystConfidence": 101},
])
def test_operational_status_or_invalid_confidence_is_not_an_analyst_assessment(
    tmp_path: Path, assessment: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Assessment"):
        append_observations(tmp_path, [cast(ObservationInput, {**observation(), "assessment": assessment})],
                            updated_at="2026-10-15T12:00:00.000Z")


def test_public_projection_preserves_exact_days_unknown_clocks_and_suppressed_facts(tmp_path: Path) -> None:
    observations = [observation(timestamp="2024-01-01T08:00:00.000Z"),
                    observation(timestamp="2026-03-01T09:00:00.000Z"),
                    observation("other.swedbank.example", "2026-03-01T09:00:00.000Z")]
    append_observations(tmp_path, observations, updated_at="2026-10-15T12:00:00.000Z")
    facts = read_observations(tmp_path)
    selected = canonical_hostname(observations[0]["domain"])["id"]
    matches: dict[str, dict[str, object]] = {selected: {
        "brand": "Swedbank", "score": 90, "reasonCodes": ["brand-domain-match"],
        "policyVersion": "current-policy", "assessment": None,
    }}
    public = build_public_records(facts, as_of="2026-10-15T12:00:00.000Z", eligible_matches=matches)
    assert len(public) == 1
    assert public[0]["observedDays"] == ["2024-01-01", "2026-03-01"]
    assert public[0]["observedDayLastSeen"] == {
        "2024-01-01": "2024-01-01T08:00:00.000Z", "2026-03-01": "2026-03-01T09:00:00.000Z",
    }
    assert public[0]["firstRecordedAt"] is None
    assert public[0]["firstPublishedAt"] is None
    assert public[0]["recordAvailable"] is False
    assert len(read_observations(tmp_path)) == 3


@pytest.mark.parametrize("damage", ["missing", "digest", "escape", "count"])
def test_store_fails_closed_on_missing_or_tampered_part(tmp_path: Path, damage: str) -> None:
    append_observations(tmp_path, [observation()], updated_at="2026-10-15T12:00:00.000Z")
    index_path = tmp_path / "data/history/observations/index.json"
    index = json.loads(index_path.read_bytes())
    descriptor = index["partitions"][0]
    part = index_path.parent / descriptor["path"]
    if damage == "missing":
        part.unlink()
    elif damage == "digest":
        part.write_bytes(b"x" * part.stat().st_size)
    elif damage == "escape":
        descriptor["path"] = "../outside.json"
    else:
        index["observationCount"] += 1
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError):
        read_observations(tmp_path)
