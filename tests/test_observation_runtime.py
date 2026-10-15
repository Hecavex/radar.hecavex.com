"""Live recording must preserve legacy uncertainty and complete published cohorts."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from hecavex_radar.brands import load_brand_registry
from hecavex_radar.observation_store import append_observations, read_observations
from hecavex_radar.provenance import reason_codes_from_match
from hecavex_radar.safety import stable_id

AS_OF = "2026-10-15T12:00:00.000Z"


def runtime():
    name = "hecavex_radar.observation_runtime"
    assert importlib.util.find_spec(name) is not None, "live durable-observation integration is missing"
    return importlib.import_module(name)


def registry():
    return load_brand_registry(Path(__file__).resolve().parents[1] / "data/brands-lt.json")


def row(domain="luminor-login[.]example", first="2026-09-01T10:00:00.000Z", last=AS_OF):
    return {
        "id": stable_id(domain), "domain": domain, "brand": "Luminor",
        "firstSeen": first, "lastSeen": last, "sources": ["CertStream"],
        "confidence": 70, "matchScore": 70, "reasonCodes": ["brand-domain-match"],
        "status": "suspected",
    }


def test_seeded_legacy_host_reobservation_does_not_invent_its_first_recording_clock(tmp_path):
    old = row(last="2026-09-02T10:00:00.000Z")
    runtime().record_observations(
        tmp_path, [row()], [row()], previous_history={"signals": [old]},
        as_of=AS_OF, registry=registry(), review_export={},
    )
    facts = read_observations(tmp_path)
    assert any(item["radarRecordedAt"] is None for item in facts)
    records, coverage, _ = runtime().public_record_inputs(
        tmp_path, as_of=AS_OF, registry=registry(), review_export={}, available_record_ids=(),
    )
    assert records[0]["firstRecordedAt"] is None
    assert records[0]["firstPublishedAt"] is None
    assert coverage["historicalRecordingTimesComplete"] is False


def test_new_hostname_records_radar_time_and_repeat_sync_does_not_create_new_facts(tmp_path):
    current = row(first=AS_OF)
    runtime().record_observations(
        tmp_path, [current], [current], previous_history={"signals": []},
        as_of=AS_OF, registry=registry(), review_export={},
    )
    before = read_observations(tmp_path)
    runtime().record_observations(
        tmp_path, [current], [current], previous_history={"signals": []},
        as_of=AS_OF, registry=registry(), review_export={},
    )
    assert read_observations(tmp_path) == before
    records, _, _ = runtime().public_record_inputs(
        tmp_path, as_of=AS_OF, registry=registry(), review_export={}, available_record_ids=(),
    )
    assert records[0]["firstRecordedAt"] == AS_OF


def test_full_accepted_set_is_archived_even_when_only_one_row_is_in_dashboard(tmp_path):
    first, second = row(first=AS_OF), row("seb-login[.]example", first=AS_OF)
    second["brand"] = "SEB"
    runtime().record_observations(
        tmp_path, [first, second], [first, second], previous_history={"signals": []},
        as_of=AS_OF, registry=registry(), review_export={},
    )
    assert {fact["hostnameId"] for fact in read_observations(tmp_path)} == {first["id"], second["id"]}


def test_eligibility_correction_keeps_archived_observation_facts(tmp_path):
    current = row(first=AS_OF)
    runtime().record_observations(
        tmp_path, [current], [current], previous_history={"signals": []},
        as_of=AS_OF, registry=registry(), review_export={},
    )
    before = read_observations(tmp_path)
    suppressions = {"suppressions": [{"domain": current["domain"], "brand": "Luminor", "scope": "exact"}]}
    records, _, _ = runtime().public_record_inputs(
        tmp_path, as_of=AS_OF, registry=registry(), review_export=suppressions, available_record_ids=(),
    )
    assert records == [] and read_observations(tmp_path) == before


def test_migration_activation_is_not_backdated_by_later_offline_replay(tmp_path):
    current = row(first=AS_OF)
    runtime().record_observations(
        tmp_path, [current], [current], previous_history={"signals": []},
        as_of=AS_OF, registry=registry(), review_export={},
    )
    marker = tmp_path / "data/history/observations/runtime.json"
    assert json.loads(marker.read_bytes())["recordedFrom"] == AS_OF


def test_matching_policy_changes_with_effective_idn_rollback(monkeypatch):
    monkeypatch.setenv("HECAVEX_IDN_VISUAL_MATCHING", "true")
    enabled = runtime().policy_versions(registry(), {})["matching"]
    monkeypatch.setenv("HECAVEX_IDN_VISUAL_MATCHING", "false")
    disabled = runtime().policy_versions(registry(), {})["matching"]
    assert enabled != disabled


def test_source_status_variants_preserve_annotations_without_new_fact_or_maliciousness(tmp_path):
    first = {**row(first=AS_OF), "sources": ["HECAVEX"], "previousStatus": None}
    second = {**first, "status": "active", "previousStatus": "suspected"}
    for current in (first, second):
        runtime().record_observations(tmp_path, [current], [current], previous_history={"signals": []},
                                      as_of=AS_OF, registry=registry(), review_export={})
    facts = read_observations(tmp_path)
    assert len(facts) == 1
    assert len(facts[0]["matchAnnotations"]) == 2
    assert {annotation.get("status") for annotation in facts[0]["matchAnnotations"]} == {"suspected", "active"}
    assert {annotation.get("previousStatus") for annotation in facts[0]["matchAnnotations"]} == {None, "suspected"}
    assert facts[0]["assessments"] == []
    records, _, _ = runtime().public_record_inputs(tmp_path, as_of=AS_OF, registry=registry(),
                                                 review_export={}, available_record_ids=())
    assert records[0]["assessment"] is None
    assert "status" not in records[0] and "status" not in records[0]["match"]


@pytest.mark.parametrize("setting,replacement", [
    ("MATCHING_ALGORITHM_VERSION", "radar-domain-matching-next"),
    ("IDN_VISUAL_PROFILE", "radar-idn-visual-next"),
    ("UNICODE_SECURITY_PROFILE", {"uts46": "next-idna-profile", "uts39": "next-confusable-profile"}),
])
def test_matching_policy_versions_algorithm_and_unicode_profiles(monkeypatch, setting, replacement):
    before = runtime().policy_versions(registry(), {})["matching"]
    monkeypatch.setattr(runtime(), setting, replacement)
    assert runtime().policy_versions(registry(), {})["matching"] != before


def test_validated_suppressed_source_fact_is_archived_before_public_selection(tmp_path):
    current = row(first=AS_OF)
    suppressions = {"suppressions": [{"domain": current["domain"], "brand": "Luminor", "scope": "exact"}]}
    runtime().record_observations(tmp_path, [current], [], previous_history={"signals": []},
                                  as_of=AS_OF, registry=registry(), review_export=suppressions)
    assert len(read_observations(tmp_path)) == 1
    records, _, _ = runtime().public_record_inputs(tmp_path, as_of=AS_OF, registry=registry(),
                                                 review_export=suppressions, available_record_ids=())
    assert records == []


def archived_input(domain, reasons, *, policy="old-rule"):
    return {
        "domain": domain, "sources": ["CertStream"], "sourceObservedAt": AS_OF,
        "sourceTimeProvenance": "legacy-history-boundary", "radarRecordedAt": None,
        "importedAt": AS_OF, "providerEventId": None,
        "originalMatch": {"brand": "Luminor", "score": 20, "reasonCodes": reasons, "policyVersion": policy},
        "assessment": None, "provenance": [{"kind": "reserved-domain-regression"}],
    }


def test_current_match_uses_current_reason_codes_instead_of_archived_exact_claim(tmp_path):
    from hecavex_radar.brands import score_domain

    domain = "luminөr-login.example"
    append_observations(tmp_path, [archived_input(domain, ["brand-exact-token"])], updated_at=AS_OF)
    records, _, policies = runtime().public_record_inputs(tmp_path, as_of=AS_OF, registry=registry(),
                                                        review_export={}, available_record_ids=())
    current = score_domain(domain, registry())
    assert current is not None
    assert records[0]["match"]["reasonCodes"] == sorted(reason_codes_from_match(current.reasons))
    assert "brand-exact-token" not in records[0]["match"]["reasonCodes"]
    assert records[0]["match"]["policyVersion"] == policies["matching"]


def test_historical_off_domain_evidence_retains_its_original_match_policy(tmp_path):
    append_observations(tmp_path, [archived_input("reserved-newsroom.example", ["brand-title-match"])],
                        updated_at=AS_OF)
    records, _, _ = runtime().public_record_inputs(tmp_path, as_of=AS_OF, registry=registry(),
                                                 review_export={}, available_record_ids=())
    assert records[0]["match"] == {"score": 20, "reasonCodes": ["brand-title-match"], "policyVersion": "old-rule"}


def recovery_bundle(tmp_path, *, unresolved=False):
    target = tmp_path / "recovery.json"
    document = {
        "schemaVersion": 1, "dataset": "radar-history-recovery", "trustedHeads": ["a" * 40],
        "window": {"startInclusive": "2026-10-01T00:00:00.000Z", "endExclusive": "2026-11-01T00:00:00.000Z"},
        "observations": [archived_input("luminor-login.example", ["brand-domain-match"])],
        "coverage": {"availablePartitionDays": ["2026-10-15"], "missingDays": ["2026-10-14"]},
        "reconciliation": {"required": unresolved, "transitionOnlyBoundaries": ["unresolved"] if unresolved else []},
    }
    body = json.dumps(document).encode()
    target.write_bytes(body)
    target.with_suffix(".sha256").write_text(hashlib.sha256(body).hexdigest() + "  recovery.json\n", encoding="ascii")
    return target


def test_real_recovery_checksum_and_day_keys_import_into_runtime_coverage(tmp_path):
    bundle = recovery_bundle(tmp_path)
    destination = tmp_path / "destination"
    imported_at = "2026-10-16T12:00:00.000Z"
    runtime().import_recovery_bundle(destination, bundle, imported_at=imported_at)
    facts = read_observations(destination)
    assert facts[0]["radarRecordedAt"] is None and facts[0]["importedAt"] == imported_at
    _, coverage, _ = runtime().public_record_inputs(destination, as_of=imported_at, registry=registry(),
                                                   review_export={}, available_record_ids=())
    assert coverage["recoveredDays"] == ["2026-10-15"]
    assert coverage["recoveredFrom"] == "2026-10-15"
    assert coverage["missingDays"] == ["2026-10-14"]
    assert coverage["recordedFrom"] is None


def test_unresolved_recovery_cannot_write_facts_or_metadata(tmp_path):
    destination = tmp_path / "destination"
    with pytest.raises(ValueError, match="reconciliation"):
        runtime().import_recovery_bundle(destination, recovery_bundle(tmp_path, unresolved=True), imported_at=AS_OF)
    assert not destination.exists()


@pytest.mark.parametrize("legacy_root", ["data/history", "custom/legacy-history"])
def test_first_capture_keeps_raw_summary_boundaries_independent_of_public_eligibility(tmp_path, legacy_root):
    from hecavex_radar.history import _atomic_write
    from hecavex_radar.history_partitions import write_document

    public = row(first="2026-09-01T10:00:00.000Z")
    raw_only = row("retained-only[.]example", first="2026-05-22T10:00:00.000Z",
                   last="2026-09-02T10:00:00.000Z")
    raw_only["brand"] = "Retired brand"
    earlier = {**public, "firstSeen": "2026-05-22T09:00:00.000Z"}
    summaries = [{
        "id": item["id"], "domain": item["domain"], "brand": item["brand"],
        "firstSeen": item["firstSeen"], "lastSeen": item["lastSeen"], "observationCount": 2,
        "sources": item["sources"], "latestStatus": "suspected", "statusObservedAt": item["lastSeen"],
        "reasonCodes": ["brand-domain-match"], "statusTransitions": [], "recentEventIds": [],
    } for item in (raw_only, earlier)]
    write_document(tmp_path / legacy_root / "summary.json", {
        "schemaVersion": 1, "dataset": "radar-history-summary", "generatedAt": AS_OF,
        "compactedThrough": "2026-09-15", "signals": summaries,
    }, 12 * 1024 * 1024, _atomic_write)
    runtime().record_observations(tmp_path, [], [], previous_history={"signals": [public]},
                                  as_of=AS_OF, registry=registry(), review_export={}, legacy_history_root=legacy_root)
    facts = read_observations(tmp_path)
    assert {fact["hostnameId"] for fact in facts} == {raw_only["id"], public["id"]}
    assert {fact["sourceObservedAt"] for fact in facts if fact["hostnameId"] == public["id"]} == {
        earlier["firstSeen"], public["firstSeen"], public["lastSeen"],
    }
    assert all(fact["radarRecordedAt"] is None for fact in facts)
    assert all(fact["sourceObservedAt"][:7] != "2026-06" for fact in facts)
