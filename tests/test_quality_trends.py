from __future__ import annotations

import json
from pathlib import Path

import pytest

from hecavex_radar.daily_trends import build_daily_trends, build_daily_trends_from_repository
from hecavex_radar.quality_metrics import build_quality_metrics

GENERATED_AT = "2026-08-25T12:00:00.000Z"


def _history_signal(
    signal_id: str,
    first_seen: str,
    *,
    sources: list[str] | None = None,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": signal_id,
        "domain": "must-not-appear[.]example",
        "brand": "Example",
        "firstSeen": first_seen,
        "lastSeen": first_seen,
        "observationCount": 1,
        "sources": sources or ["URLScan"],
        "latestStatus": "suspected",
        "reasonCodes": reasons or ["brand-domain-match"],
        "statusTransitions": [],
    }


def _assessment(
    decision_id: str,
    signal_id: str,
    reviewed_at: str,
    *,
    state: str = "confirmed-suspicious",
    revoked: bool = False,
) -> dict[str, object]:
    return {
        "id": decision_id,
        "signalId": signal_id,
        "domain": "private-subject[.]example",
        "brand": "Example",
        "reviewState": state,
        "dispositionReason": "incorrect-assessment" if revoked else "brand-impersonation",
        "evidenceCodes": ["urlscan-page"] if not revoked else [],
        "ltRelevance": "lithuanian-brand-relevance",
        "reviewedAt": reviewed_at,
        "modifiedAt": reviewed_at,
        "expiresAt": "2027-08-25T12:00:00.000Z",
        "analystConfidence": 90,
        "revoked": revoked,
    }


def test_quality_metrics_are_bounded_aggregate_and_do_not_invent_precision() -> None:
    first_id = "a" * 20
    second_id = "b" * 20
    old_id = "c" * 20
    history = {
        "signals": [
            _history_signal(
                first_id,
                "2026-08-24T00:00:00.000Z",
                sources=["URLScan", "CertStream"],
                reasons=["brand-domain-match", "different-tld"],
            ),
            _history_signal(second_id, "2026-08-23T00:00:00.000Z"),
            _history_signal(old_id, "2025-01-01T00:00:00.000Z"),
        ]
    }
    review_export = {
        "assessments": [
            _assessment("1" * 24, first_id, "2026-08-24T12:00:00.000Z"),
            _assessment(
                "2" * 24,
                second_id,
                "2026-08-25T00:00:00.000Z",
                state="inconclusive",
                revoked=True,
            ),
            _assessment("3" * 24, old_id, "2025-01-02T00:00:00.000Z"),
        ],
        "suppressions": [
            {
                "id": "4" * 24,
                "domain": "suppressed-secret[.]example",
                "scope": "exact",
                "brand": "Example",
                "reasonCode": "wrong-brand",
            }
        ],
    }

    result = build_quality_metrics(review_export, history, GENERATED_AT)
    sample = result["reviewSample"]
    assert isinstance(sample, dict)
    assert sample["assessments"] == 2
    assert sample["uniqueSignals"] == 2
    assert sample["outcomes"] == {"confirmed-suspicious": 1, "retracted": 1}
    assert sample["bySource"] == {"URLScan": 2, "CertStream": 1}
    assert sample["byEvidence"] == {"urlscan-page": 1}
    assert sample["byDispositionReason"] == {"brand-impersonation": 1, "incorrect-assessment": 1}
    latency = result["reviewLatencyHours"]
    assert isinstance(latency, dict)
    assert latency["sampleSize"] == 2
    assert latency["median"] == 30.0
    assert latency["minimum"] == 12.0
    assert latency["maximum"] == 48.0
    precision = result["precision"]
    assert isinstance(precision, dict)
    assert precision["available"] is False
    assert precision["estimatePercent"] is None
    exclusions = result["currentExclusions"]
    assert isinstance(exclusions, dict)
    assert exclusions["sampleSize"] == 1
    assert exclusions["byReason"] == {"wrong-brand": 1}

    serialized = json.dumps(result)
    assert first_id not in serialized
    assert "private-subject" not in serialized
    assert "suppressed-secret" not in serialized
    assert "must-not-appear" not in serialized
    assert "prevalence" in str(result["semantics"])


def test_quality_metrics_reject_more_than_one_year() -> None:
    with pytest.raises(ValueError, match="between 1 and 365"):
        build_quality_metrics({}, {}, GENERATED_AT, window_days=366)


def test_quality_metrics_count_dated_negative_outcomes_without_claiming_population_precision() -> None:
    signal_id = "d" * 20
    history = {"signals": [_history_signal(signal_id, "2026-08-24T00:00:00.000Z")]}
    negative = _assessment(
        "5" * 24,
        signal_id,
        "2026-08-24T12:00:00.000Z",
        state="false-positive",
    )
    negative["dispositionReason"] = "lexical-collision"
    negative["evidenceCodes"] = ["rdap"]
    negative["revoked"] = False
    result = build_quality_metrics({"assessments": [negative], "suppressions": []}, history, GENERATED_AT)
    sample = result["reviewSample"]
    assert isinstance(sample, dict)
    assert sample["outcomes"] == {"false-positive": 1}
    precision = result["precision"]
    assert isinstance(precision, dict)
    assert precision["available"] is False
    assert "probability sample" in str(precision["reason"])


def _event(
    event_id: str,
    signal_id: str,
    observed_at: str,
    *,
    event_type: str = "observation",
    previous_status: str | None = None,
    brand: str = "Revolut",
) -> dict[str, object]:
    return {
        "eventId": event_id,
        "signalId": signal_id,
        "eventType": event_type,
        "observedAt": observed_at,
        "domain": "never-publish-this[.]example",
        "brand": brand,
        "sources": ["URLScan"],
        "status": "suspected",
        "previousStatus": previous_status,
        "confidence": 90,
        "reasonCodes": ["brand-domain-match", "first-publication"]
        if event_type == "status-transition" and previous_status is None
        else ["brand-domain-match"],
    }


def _attempt(ended_at: str, outcome: str, listening_seconds: float) -> dict[str, object]:
    return {
        "endedAt": ended_at,
        "outcome": outcome,
        "listeningSeconds": listening_seconds,
    }


def _pipeline_health() -> dict[str, object]:
    return {
        "windows": [
            {
                "hours": 24,
                "collection": {
                    "scheduledSlots": 96,
                    "scheduledListeningCeilingPercent": 26.67,
                },
            }
        ]
    }


def test_daily_trends_put_collector_coverage_beside_discovery_counts() -> None:
    first_id = "a" * 20
    second_id = "b" * 20
    events = [
        _event("1" * 32, first_id, "2026-08-24T01:00:00.000Z"),
        _event("2" * 32, first_id, "2026-08-24T02:00:00.000Z"),
        _event(
            "3" * 32,
            first_id,
            "2026-08-24T02:00:00.000Z",
            event_type="status-transition",
        ),
        _event("4" * 32, second_id, "2026-08-25T10:00:00.000Z", brand="unsafe.example"),
    ]
    attempts = [
        _attempt("2026-08-24T01:04:00.000Z", "healthy-empty", 240.0),
        _attempt("2026-08-24T02:04:00.000Z", "failed", 240.0),
        _attempt("2026-08-25T10:04:00.000Z", "healthy-matches", 120.0),
    ]
    inventory = [
        {"id": first_id, "evidenceTier": "corroborated", "domain": "secret-one[.]example"},
        {"id": second_id, "evidenceTier": "name-only", "domain": "secret-two[.]example"},
    ]

    result = build_daily_trends(events, attempts, inventory, _pipeline_health(), GENERATED_AT, days=2)
    assert result["from"] == "2026-08-24"
    assert result["to"] == "2026-08-25"
    assert result["collectorSchedule"] == {
        "expectedIntervalSeconds": 900,
        "expectedListeningSeconds": 240,
        "derivedFrom": "pipeline-health-24h-window",
    }
    series = result["series"]
    assert isinstance(series, list)
    assert [row["date"] for row in series] == ["2026-08-24", "2026-08-25"]
    first = series[0]
    discovery = first["discovery"]
    coverage = first["collectorCoverage"]
    assert discovery["events"] == 3
    assert discovery["uniqueSignals"] == 1
    assert discovery["observations"] == 2
    # The retained first-publication transition is at 02:00: the paired
    # observation is not a reobservation, and the earlier event cannot be one.
    assert discovery["reobservations"] == 0
    assert discovery["firstPublications"] == 1
    assert discovery["byBrand"] == {"Revolut": 1}
    assert discovery["byEvidenceTier"] == {"corroborated": 1}
    assert coverage["scheduledSlots"] == 96
    assert coverage["recordedAttempts"] == 2
    assert coverage["healthyAttempts"] == 1
    # Legacy records without collectorStartedAt cannot locate connected time.
    assert coverage["listeningSeconds"] == 0.0
    assert coverage["coverageBounds"]["upperSeconds"] == 480.0
    assert coverage["coverageBounds"]["reportedWorkerSeconds"] == 480.0
    assert series[1]["partialDay"] is True
    assert series[1]["collectorCoverage"]["windowSeconds"] == 43_200
    assert series[1]["discovery"]["byBrand"] == {}

    serialized = json.dumps(result)
    assert first_id not in serialized
    assert "never-publish-this" not in serialized
    assert "secret-one" not in serialized
    assert "not a measure" in str(result["semantics"])


def test_daily_trends_repository_reader_is_bounded_to_requested_dates(tmp_path: Path) -> None:
    event = _event("1" * 32, "a" * 20, "2026-08-25T10:00:00.000Z")
    attempt = _attempt("2026-08-25T10:04:00.000Z", "healthy-empty", 240.0)
    event_path = tmp_path / "data/history/daily/2026-08-25/events.ndjson"
    attempt_path = tmp_path / "data/certstream/2026-08-25/attempts.ndjson"
    event_path.parent.mkdir(parents=True)
    attempt_path.parent.mkdir(parents=True)
    event_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    attempt_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    # An older row is outside the requested single-day window and is never read.
    ignored = tmp_path / "data/history/daily/2026-08-22/events.ndjson"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("not-json\n", encoding="utf-8")

    result = build_daily_trends_from_repository(
        tmp_path,
        [{"id": "a" * 20, "evidenceTier": "corroborated"}],
        _pipeline_health(),
        GENERATED_AT,
        days=1,
    )
    series = result["series"]
    assert isinstance(series, list)
    assert series[0]["discovery"]["events"] == 1
    assert series[0]["collectorCoverage"]["recordedAttempts"] == 1


def test_daily_trends_reject_more_than_one_year() -> None:
    with pytest.raises(ValueError, match="between 1 and 365"):
        build_daily_trends([], [], [], {}, GENERATED_AT, days=366)
