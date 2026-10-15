"""Exercise the complete new public record cohort, including code-free exports."""

import hashlib
import importlib
import importlib.util
import json
from copy import deepcopy

import pytest

from hecavex_radar.safety import stable_id

AS_OF = "2026-10-15T12:00:00.000Z"


def module():
    name = "hecavex_radar.observation_publication"
    assert importlib.util.find_spec(name) is not None, "durable public cohort publisher is missing"
    return importlib.import_module(name)


def metadata():
    coverage = {
        "availableFrom": "2026-09-01T10:00:00.000Z", "recordedFrom": None, "publicationRecordedFrom": None,
        "recoveredFrom": "2026-09-01", "recoveredThrough": "2026-09-01",
        "recoveredDays": ["2026-09-01"], "missingDays": [], "historyComplete": False,
        "collectionComplete": False, "historicalRecordingTimesComplete": False,
        "historicalPublicationTimesComplete": False,
        "basis": "recorded-and-recovered-observation-facts", "partialCurrentDay": True,
    }
    policies = {key: "legacy-unknown" for key in ("identity", "matching", "review", "metrics", "store")}
    from hecavex_radar.observation_store import grouping_metadata
    grouping = grouping_metadata()
    return coverage, policies, grouping


def record(number=1):
    domain = f"host-{number}[.]example[.]com"
    return {
        "id": stable_id(domain), "domain": domain, "domainGroup": "example[.]com", "brand": "Example",
        "firstSeen": "2026-09-01T10:00:00.000Z", "lastSeen": "2026-10-15T11:00:00.000Z",
        "firstRecordedAt": None, "firstPublishedAt": None,
        "observedDays": ["2026-09-01", "2026-10-15"],
        "observedDayLastSeen": {
            "2026-09-01": "2026-09-01T10:00:00.000Z", "2026-10-15": "2026-10-15T11:00:00.000Z",
        },
        "sources": ["CertStream"],
        "match": {"score": None, "reasonCodes": [], "policyVersion": "legacy-unknown"},
        "assessment": None, "recordAvailable": False,
    }


def write(repository, rows):
    coverage, policies, grouping = metadata()
    return module().write_observed_hostnames(
        repository, sorted(rows, key=lambda row: row["id"]), as_of=AS_OF,
        coverage=coverage, policy_versions=policies, grouping=grouping,
    )


def test_index_is_not_an_empty_record_collection_and_parts_are_digest_bound(tmp_path):
    index = write(tmp_path, [record()])
    assert "records" not in index and "signals" not in index
    assert index["recordCount"] == 1
    assert len(index["partitions"]) == 1
    descriptor = index["partitions"][0]
    part = tmp_path / "public" / descriptor["path"].removeprefix("/")
    assert hashlib.sha256(part.read_bytes()).hexdigest() == descriptor["sha256"]
    loaded_index, rows = module().read_observed_hostnames(tmp_path)
    assert loaded_index == index and rows == [record()]


def test_complete_large_cohort_and_missing_or_tampered_parts_fail_closed(tmp_path):
    rows = [record(number) for number in range(1200)]
    index = write(tmp_path, rows)
    assert len(index["partitions"]) > 1
    assert len(module().read_observed_hostnames(tmp_path)[1]) == len(rows)
    part = tmp_path / "public" / index["partitions"][0]["path"].removeprefix("/")
    original = part.read_bytes()
    part.write_bytes(original.replace(b"Example", b"Tampered", 1))
    with pytest.raises(ValueError):
        module().read_observed_hostnames(tmp_path)
    part.unlink()
    with pytest.raises(ValueError):
        module().read_observed_hostnames(tmp_path)


def test_duplicate_identity_or_invented_day_membership_is_rejected_before_write(tmp_path):
    with pytest.raises(ValueError):
        write(tmp_path, [record(), record()])
    invalid = deepcopy(record())
    invalid["observedDayLastSeen"]["2026-09-01"] = "2026-09-02T10:00:00.000Z"
    with pytest.raises(ValueError):
        write(tmp_path, [invalid])
    assert not (tmp_path / "public/data/observed-hostnames-v1.json").exists()


def test_zero_recorded_population_has_explicit_zero_index(tmp_path):
    index = write(tmp_path, [])
    assert index["recordCount"] == 0 and index["partitions"] == []
    assert module().read_observed_hostnames(tmp_path) == (index, [])


def test_wrong_private_suffix_group_is_rejected(tmp_path):
    row = record()
    row["domainGroup"] = "other[.]com"
    with pytest.raises(ValueError, match="group"):
        write(tmp_path, [row])


@pytest.mark.parametrize("recorded", [None, "2026-10-15T11:30:00.000Z"])
def test_publication_clock_requires_an_earlier_tracked_recording(tmp_path, recorded):
    row = record()
    row["firstRecordedAt"] = recorded
    row["firstPublishedAt"] = "2026-10-15T11:00:00.000Z"
    with pytest.raises(ValueError, match="publication clock"):
        write(tmp_path, [row])


def test_period_artifact_is_recomputed_from_complete_cohort(tmp_path):
    write(tmp_path, [record()])
    publication = module()
    assert hasattr(publication, "write_period_artifact"), "period artifact integration is missing"
    publication.write_period_artifact(tmp_path)
    publication.validate_period_artifacts(tmp_path, expected_as_of=AS_OF)
    path = tmp_path / "public/data/period-metrics-v1.json"
    metrics = json.loads(path.read_bytes())
    metrics["windows"][0]["uniqueHostnames"] += 1
    path.write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(ValueError, match="reconcile"):
        publication.validate_period_artifacts(tmp_path, expected_as_of=AS_OF)


def test_record_schema_separates_match_from_explicit_assessment(tmp_path):
    invalid = deepcopy(record())
    invalid["assessment"] = {
        "verdict": "malicious", "assessedAt": None, "evidenceReferences": [],
        "decisionId": "a" * 24, "analystConfidence": 80,
    }
    with pytest.raises(ValueError):
        write(tmp_path, [invalid])
    index = write(tmp_path, [record()])
    assert json.loads((tmp_path / "public/data/observed-hostnames-v1.json").read_bytes()) == index


def test_explicit_suspicious_assessment_keeps_analyst_confidence_independent(tmp_path):
    row = record()
    row["match"]["score"] = 25
    row["assessment"] = {
        "verdict": "suspicious", "assessedAt": "2026-10-15T10:00:00.000Z",
        "evidenceReferences": ["review-decision:" + "a" * 24],
        "decisionId": "a" * 24, "analystConfidence": 80,
    }
    write(tmp_path, [row])
    loaded = module().read_observed_hostnames(tmp_path)[1][0]
    assert loaded["match"]["score"] == 25
    assert loaded["assessment"]["analystConfidence"] == 80
    assert loaded["assessment"]["verdict"] == "suspicious"
