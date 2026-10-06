import copy
import hashlib
from pathlib import Path

import pytest

from hecavex_radar.consumer_example import compare, load_publication
from hecavex_radar.ranking_evaluation import evaluate, freeze


def cohort():
    return freeze({"schemaVersion": 2, "generatedAt": "2026-09-10T00:00:00.000Z", "signals": [
        {"id": digit * 20, "matchScore": score, "brand": "Example", "evidenceTier": "name-only",
         "sources": ["CertStream"], "lastSeen": "2026-09-09T00:00:00.000Z"}
        for digit, score in [("a", 100), ("b", 90), ("c", 80)]]}, "a" * 40, "b" * 40)


def test_no_labels_is_not_precision():
    result = evaluate(cohort(), [])
    assert result["gate"] == "human-review-required"
    assert result["ranked"]["positiveAmongResolvedPercent"] is None
    assert result["ranked"]["unreviewed"] == 3


def test_inconclusives_and_missing_stay_in_denominator():
    decisions = [{"signalId": digit * 20, "outcome": outcome, "reviewMethod": "human",
                  "reviewedAt": "2026-09-11T00:00:00.000Z", "evidenceReference": "synthetic test only"}
                 for digit, outcome in [("a", "confirmed-suspicious"), ("b", "inconclusive")]]
    result = evaluate(cohort(), decisions)
    assert result["ranked"]["positiveAmongResolvedPercent"] == 100
    assert result["ranked"]["positiveLowerBoundPercent"] == 33.33
    assert result["populationPrecisionAvailable"] is False
    decisions[0]["reviewMethod"] = "AI-assisted"
    with pytest.raises(ValueError, match="human"):
        evaluate(cohort(), decisions)


def test_cohort_tampering_rejected():
    value = cohort()
    value["rows"][0]["matchScore"] = 0
    with pytest.raises(ValueError, match="modified"):
        evaluate(value, [])


def test_existing_complete_publication_can_be_imported_read_only():
    root = Path(__file__).resolve().parents[1] / "public/data"
    digest = hashlib.sha256((root / "feed-manifest.json").read_bytes()).hexdigest()
    publication = load_publication(root, digest)
    assert len(publication["signals"]) > 0
    assert len(publication["history"]) >= len(publication["signals"])
    with pytest.raises(ValueError, match="identity"):
        load_publication(root, "0" * 64)


def test_disappearance_is_unknown_and_reviewed_expiry_separate():
    before = {"manifestSha256": "a" * 64, "signals": {"a": {"lastSeen": "2026-09-01T00:00:00.000Z"}},
              "history": {"a": {}}, "indicators": []}
    after = copy.deepcopy(before)
    after["signals"] = {}
    after["indicators"] = [{"id": "indicator-example", "valid_from": "2026-09-01T00:00:00.000Z",
                            "valid_until": "2026-09-05T00:00:00.000Z"}]
    result = compare(before, after, "2026-09-10T00:00:00.000Z")
    assert "reason-unknown" in result["changes"][0]["change"]
    assert result["reviewedIndicators"][0]["state"] == "expired"
    after["indicators"][0]["revoked"] = True
    assert compare(before, after, "2026-09-10T00:00:00.000Z")["reviewedIndicators"][0]["state"] == "revoked"
