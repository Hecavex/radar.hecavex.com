from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from hecavex_radar import idn_evidence
from hecavex_radar.brands import load_brand_registry, normalize_domain, score_domain
from hecavex_radar.models import RadarSignal
from hecavex_radar.provenance import reason_codes_from_match
from hecavex_radar.public_schemas import IDN_MATCHES_SCHEMA, RADAR_SCHEMA

REPOSITORY = Path(__file__).resolve().parents[1]
NOW = "2026-10-15T12:00:00.000Z"
DIGEST = "a" * 64


def signal_for(value: str) -> RadarSignal:
    registry = load_brand_registry(REPOSITORY / "data/brands-lt.json")
    match = score_domain(value, registry)
    assert match is not None
    domain = normalize_domain(value)
    assert domain is not None
    defanged = domain.replace(".", "[.]")
    return cast(RadarSignal, {
        "id": hashlib.sha256(domain.encode()).hexdigest()[:20],
        "domain": defanged, "url": f"hxxps://{defanged}", "brand": match.brand,
        "firstSeen": NOW, "lastSeen": NOW, "sources": ["CertStream"], "status": "suspected",
        "country": None, "host": None, "screenshotUrl": None, "matchScore": match.confidence,
        "confidence": match.confidence, "evidenceTier": "name-only", "reviewState": "unreviewed",
        "ltRelevance": "lithuanian-brand-relevance", "reasonCodes": reason_codes_from_match(match.reasons),
    })


def test_release_evidence_is_deterministic_and_legacy_signal_schema_is_unchanged() -> None:
    registry = load_brand_registry(REPOSITORY / "data/brands-lt.json")
    signals = [signal_for("swedbanƙ.example"), signal_for("luminөr.example")]
    artifact = idn_evidence.build_idn_evidence(signals, registry, NOW, DIGEST)
    assert artifact == idn_evidence.build_idn_evidence(list(reversed(signals)), registry, NOW, DIGEST)
    Draft202012Validator(IDN_MATCHES_SCHEMA).validate(artifact)
    assert len(artifact["records"]) == 2
    for signal in signals:
        assert "brand-domain-match" in signal["reasonCodes"]
        assert "unicode-confusable" not in signal["reasonCodes"]
        assert "brand-exact-token" not in signal["reasonCodes"]
        assert signal["reviewState"] == "unreviewed"
    sources = [{"name": name, "homepage": homepage, "fetchedAt": NOW, "records": 0,
                "state": "skipped", "note": None} for name, homepage in (
                    ("CertStream", "https://certstream.dev/"), ("URLScan", "https://urlscan.io/"),
                    ("HECAVEX", "https://hecavex.com/"))]
    Draft202012Validator(RADAR_SCHEMA).validate({
        "schemaVersion": 2, "dataset": "live", "generatedAt": NOW,
        "lastSuccessfulSyncAt": NOW, "signals": signals, "sources": sources,
    })
    idn_evidence.validate_idn_evidence(artifact, signals, registry, NOW, DIGEST)


@pytest.mark.parametrize("mutation", ["digest", "time", "brand", "orphan", "position", "replacement",
                                       "role", "duplicate", "omission", "private-field", "boolean-index"])
def test_semantic_tampering_and_stale_or_incomplete_evidence_fail(mutation: str) -> None:
    registry = load_brand_registry(REPOSITORY / "data/brands-lt.json")
    signals = [signal_for("swedbanƙ.example")]
    artifact = deepcopy(idn_evidence.build_idn_evidence(signals, registry, NOW, DIGEST))
    records = cast(list[dict[str, object]], artifact["records"])
    record = records[0]
    substitutions = cast(list[dict[str, object]], record["substitutions"])
    if mutation == "digest":
        artifact["snapshotSha256"] = "b" * 64
    elif mutation == "time":
        artifact["generatedAt"] = "2026-10-14T12:00:00.000Z"
    elif mutation == "brand":
        record["brand"] = "Luminor"
    elif mutation == "orphan":
        record["signalId"] = "b" * 20
    elif mutation == "position":
        substitutions[0]["position"] = 0
    elif mutation == "replacement":
        substitutions[0]["replacement"] = "e"
    elif mutation == "role":
        record["labelRole"] = "subdomain"
    elif mutation == "boolean-index":
        record["labelIndex"] = False
    elif mutation == "duplicate":
        records.append(deepcopy(record))
    elif mutation == "omission":
        records.clear()
    else:
        record["skeleton"] = "private derived comparison"
    with pytest.raises(ValueError, match="IDN evidence differs"):
        idn_evidence.validate_idn_evidence(artifact, signals, registry, NOW, DIGEST)


def test_empty_artifact_and_rollback_do_not_invent_historical_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = load_brand_registry(REPOSITORY / "data/brands-lt.json")
    assert idn_evidence.build_idn_evidence([], registry, NOW, DIGEST)["records"] == []
    signal = signal_for("swedbanƙ.example")
    monkeypatch.setenv("HECAVEX_IDN_VISUAL_MATCHING", "false")
    assert idn_evidence.build_idn_evidence([signal], registry, NOW, DIGEST)["records"] == []


def test_limits_fail_instead_of_truncating(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = load_brand_registry(REPOSITORY / "data/brands-lt.json")
    signals = [signal_for("swedbanƙ.example"), signal_for("luminөr.example")]
    monkeypatch.setattr(idn_evidence, "MAXIMUM_IDN_EVIDENCE_RECORDS", 1)
    with pytest.raises(ValueError, match="record budget"):
        idn_evidence.build_idn_evidence(signals, registry, NOW, DIGEST)
    monkeypatch.setattr(idn_evidence, "MAXIMUM_IDN_EVIDENCE_RECORDS", 2500)
    monkeypatch.setattr(idn_evidence, "MAXIMUM_IDN_EVIDENCE_BYTES", 100)
    with pytest.raises(ValueError, match="byte budget"):
        idn_evidence.build_idn_evidence(signals, registry, NOW, DIGEST)
    with pytest.raises(ValueError, match="duplicate signal"):
        idn_evidence.build_idn_evidence([signals[0], signals[0]], registry, NOW, DIGEST)
