from __future__ import annotations

from pathlib import Path

import pytest

from hecavex_radar.observation_store import (
    append_observations,
    build_public_records,
    canonical_hostname,
    read_observations,
)
from hecavex_radar.period_metrics import build_period_metrics
from tests.test_observation_store import observation


def coverage() -> dict[str, object]:
    return {
        "availableFrom": "2026-01-01T00:00:00.000Z", "recordedFrom": None, "publicationRecordedFrom": None,
        "recoveredFrom": "2026-01-01", "recoveredThrough": "2026-10-15",
        "recoveredDays": ["2026-01-01", "2026-03-01"], "missingDays": ["2026-02-01"],
        "historyComplete": False, "collectionComplete": False,
        "historicalRecordingTimesComplete": False, "historicalPublicationTimesComplete": False,
        "basis": "recorded-and-recovered-observation-facts", "partialCurrentDay": True,
    }


POLICIES = {"identity": "identity-v1", "matching": "matching-v1", "review": "review-v1",
            "metrics": "radar-period-metrics-v1", "store": "radar-observation-store-v1"}
AS_OF = "2026-10-15T12:00:00.000Z"


def public_records(tmp_path: Path, facts: list[tuple[str, str]]) -> list[dict[str, object]]:
    inputs = [observation(domain, timestamp) for domain, timestamp in facts]
    append_observations(tmp_path, inputs, updated_at=AS_OF)
    matches = {canonical_hostname(domain)["id"]: {"brand": "Swedbank", "score": None, "reasonCodes": [],
                                                   "policyVersion": "legacy-unknown", "assessment": None}
               for domain, _ in facts}
    return build_public_records(read_observations(tmp_path), as_of=AS_OF, eligible_matches=matches)


def windows(records: list[dict[str, object]], supplied_coverage: dict[str, object] | None = None) -> dict[str, object]:
    payload = build_period_metrics(records, as_of=AS_OF, hostnames_sha256="a" * 64,
                                   coverage=coverage() if supplied_coverage is None else supplied_coverage,
                                   policy_versions=POLICIES)
    return {window["key"]: window for window in payload["windows"]}


def test_repeated_host_days_count_once_and_subdomains_group_independently(tmp_path: Path) -> None:
    facts = [("one.swedbank.example.com", f"2026-09-{day:02d}T10:00:00.000Z") for day in range(20, 31)]
    facts += [("one.swedbank.example.com", f"2026-10-{day:02d}T10:00:00.000Z") for day in range(1, 10)]
    facts += [("two.swedbank.example.com", "2026-10-15T12:00:00.000Z")]
    selected = windows(public_records(tmp_path, facts))["30d"]
    assert selected["uniqueHostnames"] == 2
    assert selected["domainGroups"] == 1
    assert selected["candidateDays"] == 21
    assert selected["endExclusive"] == "2026-10-15T12:00:00.001Z"
    assert selected["firstRecordedHostnames"] is None
    assert selected["firstPublishedHostnames"] is None


def test_first_last_do_not_invent_membership_in_intermediate_month(tmp_path: Path) -> None:
    facts = [("swedbank.example", "2026-01-01T10:00:00.000Z"),
             ("swedbank.example", "2026-03-01T10:00:00.000Z")]
    selected = windows(public_records(tmp_path, facts))
    assert selected["month:2026-02"]["uniqueHostnames"] == 0
    assert selected["month:2026-02"]["candidateDays"] == 0
    assert selected["all"]["uniqueHostnames"] == 1
    assert selected["all"]["candidateDays"] == 2
    assert selected["all"]["startInclusive"] is None
    assert selected["month:2026-02"]["completeCollection"] is False


def test_partial_lower_day_and_exact_as_of_are_included_correctly(tmp_path: Path) -> None:
    facts = [("early.swedbank.example", "2026-09-15T11:59:59.999Z"),
             ("edge.swedbank.example", "2026-09-15T12:00:00.000Z"),
             ("repeat.swedbank.example", "2026-09-15T11:00:00.000Z"),
             ("repeat.swedbank.example", "2026-10-15T12:00:00.000Z"),
             ("future.swedbank.example", "2026-10-15T12:00:00.001Z")]
    selected = windows(public_records(tmp_path, facts))["30d"]
    assert selected["startInclusive"] == "2026-09-15T12:00:00.000Z"
    assert selected["uniqueHostnames"] == 2
    assert selected["candidateDays"] == 2


def test_known_clock_counts_are_distinct_from_source_time_membership(tmp_path: Path) -> None:
    records = public_records(tmp_path, [("swedbank.example", "2026-01-01T10:00:00.000Z")])
    records[0]["firstRecordedAt"] = "2026-10-01T00:00:00.000Z"
    records[0]["firstPublishedAt"] = "2026-10-02T00:00:00.000Z"
    complete = {**coverage(), "historicalRecordingTimesComplete": True, "historicalPublicationTimesComplete": True}
    selected = windows(records, complete)["30d"]
    assert selected["uniqueHostnames"] == 0
    assert selected["firstRecordedHostnames"] == 1
    assert selected["firstPublishedHostnames"] == 1


def test_empty_recorded_population_is_known_zero_but_coverage_is_not_invented() -> None:
    selected = windows([])["all"]
    assert selected["uniqueHostnames"] == 0
    assert selected["candidateDays"] == 0
    assert selected["exactWithinRecordedData"] is True
    assert selected["completeCollection"] is False


def test_post_activation_clock_windows_are_exact_without_inventing_earlier_clocks(tmp_path: Path) -> None:
    records = public_records(tmp_path, [("swedbank.example", "2026-01-01T10:00:00.000Z"),
                                        ("new.swedbank.example", "2026-10-01T10:00:00.000Z")])
    new = next(record for record in records if record["domain"].startswith("new[.]"))
    new["firstRecordedAt"] = "2026-10-01T12:00:00.000Z"
    new["firstPublishedAt"] = "2026-10-02T00:00:00.000Z"
    activated = {**coverage(), "recordedFrom": "2026-09-01T00:00:00.000Z",
                 "publicationRecordedFrom": "2026-09-20T00:00:00.000Z"}
    selected = windows(records, activated)
    assert selected["30d"]["firstRecordedHostnames"] == 1
    assert selected["90d"]["firstRecordedHostnames"] is None
    assert selected["30d"]["firstPublishedHostnames"] is None
    assert selected["all"]["firstRecordedHostnames"] is None


def test_incomplete_or_incoherent_membership_and_coverage_cannot_publish_metrics(tmp_path: Path) -> None:
    records = public_records(tmp_path, [("swedbank.example", "2026-01-01T10:00:00.000Z")])
    records[0]["observedDays"] = ["2026-01-01", "2026-02-01"]
    with pytest.raises(ValueError, match="membership"):
        windows(records)
    with pytest.raises(ValueError, match="coverage fields"):
        windows([], {key: value for key, value in coverage().items() if key != "publicationRecordedFrom"})


def test_complete_clock_claim_cannot_turn_unknown_historical_clocks_into_zero(tmp_path: Path) -> None:
    records = public_records(tmp_path, [("swedbank.example", "2026-01-01T10:00:00.000Z")])
    with pytest.raises(ValueError, match="clock completeness"):
        windows(records, {**coverage(), "historicalRecordingTimesComplete": True})
