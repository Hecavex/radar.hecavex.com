"""Public timing evidence survives export without breaking archived cohorts."""

import json

import pytest

from hecavex_radar.observation_publication import (
    METRICS,
    read_observed_hostnames,
    validate_period_artifacts,
    write_period_artifact,
)
from tests.test_observation_publication import AS_OF, record, write


def test_collector_fallback_is_preserved_in_complete_public_cohort(tmp_path):
    row = record()
    row["sourceTimeProvenances"] = ["collector-time-fallback", "legacy-normalized-unknown"]
    write(tmp_path, [row])
    assert read_observed_hostnames(tmp_path)[1] == [row]
    write_period_artifact(tmp_path)
    payload = json.loads((tmp_path / METRICS).read_bytes())
    assert payload["timeBasis"] == "source-observation-or-explicit-collector-fallback"
    assert payload["windows"][0]["uniqueHostnames"] == 1
    validate_period_artifacts(tmp_path, expected_as_of=AS_OF)


@pytest.mark.parametrize("origins", [
    [], ["provider-observation-time"] * 2, ["invented-provider-proof"],
    ["legacy-normalized-unknown", "collector-time-fallback"],
])
def test_unsupported_or_ambiguous_public_timing_evidence_cannot_publish(tmp_path, origins):
    row = record()
    row["sourceTimeProvenances"] = origins
    with pytest.raises(ValueError):
        write(tmp_path, [row])


def test_archived_cohort_without_timing_summary_and_old_metrics_remains_valid(tmp_path):
    write(tmp_path, [record()])
    write_period_artifact(tmp_path)
    path = tmp_path / METRICS
    payload = json.loads(path.read_bytes())
    payload["timeBasis"] = "source-observation-time"
    path.write_text(json.dumps(payload), encoding="utf-8")
    validate_period_artifacts(tmp_path, expected_as_of=AS_OF)
    assert "sourceTimeProvenances" not in read_observed_hostnames(tmp_path)[1][0]


def test_unrecognized_time_basis_cannot_pass_recomputed_metrics(tmp_path):
    write(tmp_path, [record()])
    write_period_artifact(tmp_path)
    path = tmp_path / METRICS
    payload = json.loads(path.read_bytes())
    payload["timeBasis"] = "earliest-ever-publication"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_period_artifacts(tmp_path, expected_as_of=AS_OF)


def test_explicit_fallback_cannot_claim_the_older_provider_only_time_basis(tmp_path):
    row = record()
    row["sourceTimeProvenances"] = ["collector-time-fallback"]
    write(tmp_path, [row])
    write_period_artifact(tmp_path)
    path = tmp_path / METRICS
    payload = json.loads(path.read_bytes())
    payload["timeBasis"] = "source-observation-time"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="fallback"):
        validate_period_artifacts(tmp_path, expected_as_of=AS_OF)
