"""Provider timestamp absence must survive normalization and durable capture."""

from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hecavex_radar import normalize
from hecavex_radar.brands import load_brand_registry
from hecavex_radar.models import RawSignal
from hecavex_radar.observation_runtime import public_record_inputs, record_observations
from hecavex_radar.observation_store import read_observations
from hecavex_radar.period_metrics import build_period_metrics
from hecavex_radar.public_schemas import RADAR_SCHEMA

NOW = "2026-10-15T12:00:00.000Z"
LATER = "2026-10-16T12:00:00.000Z"


@pytest.mark.parametrize(("value", "reason"), [
    (None, "missing"), ("invalid-provider-clock", "invalid"),
    ("2026-12-01T00:00:00.000Z", "future"),
])
def test_fallback_clock_is_explicit_and_replay_does_not_invent_another_day(tmp_path, value, reason):
    raw = RawSignal(url="https://luminor-login.example/", source="HECAVEX", brand="Luminor",
                    first_seen=value, last_seen=value, confidence=80)
    public = normalize.prepare_signal(raw, NOW)
    assert public is not None
    evidence = normalize.resolve_signal_times(raw, NOW)
    assert {item["origin"] for item in evidence} == {"collector-time-fallback"}
    assert {item["providerObservedAt"] for item in evidence} == {None}
    assert {item["originalProviderTime"] for item in evidence} == {value}
    assert {item["reason"] for item in evidence} == {reason}
    assert {item["collectorTime"] for item in evidence} == {NOW}
    # Internal evidence is attached only to the capture copy, never snapshot v2.
    Draft202012Validator(RADAR_SCHEMA["$defs"]["signal"]).validate(public)
    assert "sourceTimeEvidence" not in public and "_sourceTimeEvidence" not in public
    registry = load_brand_registry(Path(__file__).resolve().parents[1] / "data/brands-lt.json")
    captured = {**public, "_sourceTimeEvidence": evidence}
    record_observations(tmp_path, [captured], [public], previous_history=None,
                        as_of=NOW, registry=registry, review_export={})
    facts = read_observations(tmp_path)
    assert len(facts) == 1
    assert facts[0]["sourceTimeProvenances"] == ["collector-time-fallback"]
    assert {item["originalProviderTime"] for item in facts[0]["provenance"]} == {value}
    replay = replace(raw, first_seen=public["firstSeen"], last_seen=public["lastSeen"],
                     source_time_evidence=evidence)
    assert normalize.resolve_signal_times(replay, LATER) == evidence
    record_observations(tmp_path, [captured], [public], previous_history=None,
                        as_of=LATER, registry=registry, review_export={})
    assert read_observations(tmp_path) == facts
    records, coverage, versions = public_record_inputs(
        tmp_path, as_of=LATER, registry=registry, review_export={}, available_record_ids=(),
    )
    assert records[0]["sourceTimeProvenances"] == ["collector-time-fallback"]
    assert records[0]["observedDays"] == ["2026-10-15"]
    metrics = build_period_metrics(records, as_of=LATER, hostnames_sha256="a" * 64,
                                   coverage=coverage, policy_versions=versions)
    assert metrics["timeBasis"] == "source-observation-or-explicit-collector-fallback"
    assert metrics["windows"][0]["uniqueHostnames"] == 1
    assert metrics["windows"][0]["candidateDays"] == 1
    with pytest.raises(ValueError, match="time basis"):
        build_period_metrics(records, as_of=LATER, hostnames_sha256="a" * 64,
                             coverage=coverage, policy_versions=versions, time_basis="source-observation-time")


def test_missing_first_boundary_can_reference_a_known_last_provider_time():
    raw = RawSignal(url="https://reserved.example/", source="HECAVEX",
                    last_seen="2026-10-01T10:00:00Z")
    evidence = normalize.resolve_signal_times(raw, NOW)
    first, last = evidence
    assert first["reason"] == "missing"
    assert first["originalProviderTime"] is None
    assert first["providerObservedAt"] == last["providerObservedAt"] == "2026-10-01T10:00:00.000Z"
    assert first["origin"] == last["origin"] == "provider-observation-time"


def test_invalid_archival_clock_claim_cannot_be_relabelled_as_verified_provider_time():
    raw = RawSignal(url="https://reserved.example/", source="HECAVEX")
    evidence = normalize.resolve_signal_times(raw, NOW)
    evidence[0]["origin"] = "provider-observation-time"
    with pytest.raises(ValueError, match="provenance"):
        normalize.resolve_signal_times(replace(raw, first_seen=NOW, last_seen=NOW,
                                              source_time_evidence=evidence), LATER)


def test_legacy_normalized_boundaries_remain_unknown():
    evidence = normalize.legacy_source_time_evidence(NOW, NOW, "URLScan")
    assert {item["origin"] for item in evidence} == {"legacy-normalized-unknown"}
    assert {item["providerObservedAt"] for item in evidence} == {None}
    assert {item["collectorTime"] for item in evidence} == {None}


def test_original_provider_timestamp_has_a_finite_archive_budget():
    raw = RawSignal(url="https://reserved.example/", source="HECAVEX", last_seen="x" * 1000)
    evidence = normalize.resolve_signal_times(raw, NOW)
    assert evidence[-1]["originalProviderTime"] == "x" * 256
    assert evidence[-1]["originalProviderTimeTruncated"] is True
    assert len(evidence[-1]["originalProviderTimeSha256"]) == 64


def test_truncated_invalid_raw_time_cannot_become_a_verified_parseable_prefix():
    original = "2026-10-01T10:00:00." + "1" * 300 + "INVALID"
    evidence = normalize.resolve_signal_times(RawSignal(url="https://reserved.example/", source="HECAVEX",
                                                        last_seen=original), NOW)
    assert evidence[-1]["reason"] == "invalid"
    assert evidence[-1]["providerObservedAt"] is None
    assert evidence[-1]["originalProviderTimeTruncated"] is True


def test_repeated_valid_provider_fact_retains_first_collector_receipt_without_unbounded_variants(tmp_path):
    raw = RawSignal(url="https://luminor-login.example/", source="HECAVEX", brand="Luminor",
                    first_seen="2026-10-01T10:00:00.000Z", last_seen="2026-10-01T10:00:00.000Z")
    registry = load_brand_registry(Path(__file__).resolve().parents[1] / "data/brands-lt.json")
    public = normalize.prepare_signal(raw, NOW)
    assert public is not None
    for stamp in (NOW, LATER):
        captured = {**public, "_sourceTimeEvidence": normalize.resolve_signal_times(raw, stamp)}
        record_observations(tmp_path, [captured], [public], previous_history=None,
                            as_of=stamp, registry=registry, review_export={})
    facts = read_observations(tmp_path)
    assert len(facts) == 1 and len(facts[0]["provenance"]) == 2
    assert {item["collectorTime"] for item in facts[0]["provenance"]} == {NOW}
    assert facts[0]["radarRecordedAt"] == NOW


def test_old_normalization_label_is_not_retroactively_called_verified_provider_time(tmp_path):
    from hecavex_radar.observation_store import append_observations, build_public_records, canonical_hostname
    from tests.test_observation_store import observation

    fact = observation("luminor-login.example", NOW)
    fact["sourceTimeProvenance"] = "normalized-provider-boundary"
    append_observations(tmp_path, [fact], updated_at=NOW)
    records = build_public_records(read_observations(tmp_path), as_of=NOW, eligible_matches={
        canonical_hostname(fact["domain"])["id"]: {
            "brand": "Luminor", "score": None, "reasonCodes": [], "policyVersion": "legacy-unknown",
        },
    })
    assert records[0]["sourceTimeProvenances"] == ["legacy-normalized-unknown"]


def test_future_collector_receipt_is_rejected_before_capture_writes(tmp_path):
    raw = RawSignal(url="https://luminor-login.example/", source="HECAVEX", brand="Luminor")
    public = normalize.prepare_signal(raw, LATER)
    assert public is not None
    capture = {**public, "_sourceTimeEvidence": normalize.resolve_signal_times(raw, LATER)}
    registry = load_brand_registry(Path(__file__).resolve().parents[1] / "data/brands-lt.json")
    with pytest.raises(ValueError, match="collector"):
        record_observations(tmp_path, [capture], [public], previous_history=None,
                            as_of=NOW, registry=registry, review_export={})
    assert not list(tmp_path.rglob("*.json"))


def test_empty_or_untyped_archived_clocks_fail_validation():
    evidence = normalize.resolve_signal_times(RawSignal(url="https://reserved.example/", source="HECAVEX"), NOW)
    for field, value in (("collectorTime", ""), ("reason", []), ("origin", [])):
        malformed = [dict(item) for item in evidence]
        malformed[0][field] = value
        with pytest.raises(ValueError, match="provenance"):
            normalize.validate_source_time_evidence(malformed, first_seen=NOW, last_seen=NOW, source="HECAVEX")


def test_archive_cannot_forge_a_fallback_reason_or_an_unrelated_provider_boundary():
    raw = RawSignal(url="https://reserved.example/", source="HECAVEX", last_seen="invalid-clock")
    evidence = normalize.resolve_signal_times(raw, NOW)
    evidence[1]["reason"] = "missing"
    with pytest.raises(ValueError, match="provenance"):
        normalize.validate_source_time_evidence(evidence, first_seen=NOW, last_seen=NOW, source="HECAVEX")
    raw.last_seen = "2026-10-01T10:00:00.000Z"
    evidence = normalize.resolve_signal_times(raw, NOW)
    evidence[0]["timestamp"] = evidence[0]["providerObservedAt"] = "2026-09-01T10:00:00.000Z"
    with pytest.raises(ValueError, match="provenance"):
        normalize.validate_source_time_evidence(evidence, first_seen="2026-09-01T10:00:00.000Z",
                                                last_seen=raw.last_seen, source="HECAVEX")


def test_old_metrics_time_basis_can_be_recomputed_without_rewriting_archive():
    from tests.test_period_metrics import POLICIES, coverage

    metrics = build_period_metrics([], as_of=NOW, hostnames_sha256="a" * 64,
                                   coverage=coverage(), policy_versions=POLICIES,
                                   time_basis="source-observation-time")
    assert metrics["timeBasis"] == "source-observation-time"
    with pytest.raises(ValueError, match="time basis"):
        build_period_metrics([], as_of=NOW, hostnames_sha256="a" * 64,
                             coverage=coverage(), policy_versions=POLICIES, time_basis="invented")
