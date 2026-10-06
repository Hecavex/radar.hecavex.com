from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from hecavex_radar.brands import BrandEntry, BrandRegistry
from hecavex_radar.models import RawSignal
from hecavex_radar.normalize import merge_signals, prepare_signal
from hecavex_radar.review import (
    AssessmentAdmissionSource,
    PublicReviewPolicy,
    _build_admission_source,
    build_public_export,
    load_public_review,
    read_review_events,
    record_review_event,
    review_state,
)
from hecavex_radar.review import main as review_main
from hecavex_radar.safety import defang_host, stable_id
from hecavex_radar.stix import RADAR_IDENTITY_ID, TLP_CLEAR_MARKING_ID, build_reviewed_stix_bundle

ROOT = Path(__file__).resolve().parent
FIXTURE = json.loads((ROOT / "fixtures/semantic-signals.json").read_text(encoding="utf-8"))


def registry() -> BrandRegistry:
    return BrandRegistry(
        scope="test",
        reviewed_at="2026-08-25",
        entries=[
            BrandEntry(
                brand="Vinted",
                last_reviewed_at="2026-08-25",
                aliases=["vinted"],
                fuzzy_aliases=["vinted"],
                excluded_terms=[],
                excluded_domains=[],
                category="marketplace",
                official_domains=["vinted.com", "vinted.lt"],
                sources=["https://www.vinted.com/"],
            )
        ],
    )


def registry_with_alias(alias: str) -> BrandRegistry:
    return BrandRegistry(
        scope="test",
        reviewed_at="2026-08-25",
        entries=[
            BrandEntry(
                brand="Vinted",
                last_reviewed_at="2026-08-25",
                aliases=[alias],
                fuzzy_aliases=[alias],
                excluded_terms=[],
                excluded_domains=[],
                category="marketplace",
                official_domains=["vinted.com", "vinted.lt"],
                sources=["https://www.vinted.com/"],
            )
        ],
    )


def signal(
    source: str = "CertStream",
    *,
    hashes: list[str] | None = None,
    reason_codes: list[str] | None = None,
) -> AssessmentAdmissionSource:
    prepared = prepare_signal(
        RawSignal(
            url=FIXTURE["url"],
            source=source,
            first_seen=FIXTURE["firstSeen"],
            last_seen=FIXTURE["lastSeen"],
            status="suspected",
            brand=FIXTURE["brand"],
            hashes=hashes,
            confidence=96,
            reason_codes=reason_codes
            or ["brand-exact-token", "suspicious-context", "different-tld"],
        ),
        "2026-08-25T12:00:00.000Z",
    )
    if prepared is None:  # pragma: no cover - fixed valid fixture
        raise RuntimeError("Semantic test fixture did not normalize.")
    return prepared


def admission(
    domain: str = FIXTURE["domain"],
    brand: str = FIXTURE["brand"],
    observed_at: str = FIXTURE["firstSeen"],
    sources: list[str] | None = None,
) -> dict[str, object]:
    display_domain = defang_host(domain)
    return _build_admission_source(
        signal_id=stable_id(display_domain.lower()),
        domain=display_domain,
        brand=brand,
        observed_at=observed_at,
        sources=sources or ["CertStream"],
    )


def write_signal_projection(root: Path, signals: list[dict[str, object]]) -> None:
    generated_at = "2026-08-25T11:00:00.000Z"
    public_data = root / "public/data"
    shard_root = public_data / "radar-shards"
    shard_root.mkdir(parents=True)
    shards: list[dict[str, object]] = []
    if signals:
        shard = {
            "schemaVersion": 1,
            "dataset": "radar-signal-shard",
            "generatedAt": generated_at,
            "shard": 1,
            "signals": signals,
        }
        body = (json.dumps(shard, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        (shard_root / "0001.json").write_bytes(body)
        shards.append(
            {
                "number": 1,
                "path": "/data/radar-shards/0001.json",
                "signals": len(signals),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "firstSignalId": signals[0]["id"],
                "lastSignalId": signals[-1]["id"],
            }
        )
    index = {
        "schemaVersion": 1,
        "dataset": "radar-signal-index",
        "generatedAt": generated_at,
        "signalCount": len(signals),
        "dashboardSignalCount": 0,
        "shards": shards,
    }
    (public_data / "radar.index.json").write_text(json.dumps(index), encoding="utf-8")


class SemanticSignalTests(unittest.TestCase):
    def test_new_fields_do_not_turn_match_score_into_a_verdict(self) -> None:
        prepared = signal()
        self.assertEqual(prepared["matchScore"], 96)
        self.assertEqual(prepared["confidence"], prepared["matchScore"])
        self.assertEqual(prepared["evidenceTier"], "name-only")
        self.assertEqual(prepared["reviewState"], "unreviewed")
        self.assertEqual(prepared["ltRelevance"], "lithuanian-brand-relevance")

    def test_second_source_is_corroboration_not_confirmation(self) -> None:
        merged = merge_signals([signal("CertStream"), signal("URLScan")], 10)
        self.assertEqual(merged[0]["evidenceTier"], "corroborated")
        self.assertEqual(merged[0]["reviewState"], "unreviewed")

    def test_same_observation_hash_is_context_not_corroboration(self) -> None:
        prepared = signal("URLScan", hashes=["a" * 64])
        self.assertEqual(prepared["hashes"], ["a" * 64])
        self.assertEqual(prepared["evidenceTier"], "name-only")
        self.assertNotIn("corroboratedBy", prepared)

    def test_explicit_cross_observation_hash_pivot_is_corroboration(self) -> None:
        prepared = signal(
            "URLScan",
            hashes=["a" * 64],
            reason_codes=["brand-domain-match", "primary-html-hash-pivot"],
        )
        self.assertEqual(prepared["evidenceTier"], "corroborated")
        self.assertEqual(prepared["corroboratedBy"], ["urlscan-primary-html-sha256"])


class ReviewLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "review.sqlite3"

    def _confirm(self) -> None:
        record_review_event(
            self.database,
            action="confirm",
            admission_source=admission(),
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="credential-phishing",
            recorded_at="2026-08-25T12:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="confirmed-suspicious",
            evidence_codes=["certificate-transparency", "urlscan-page"],
            expires_at="2026-09-25T12:00:00.000Z",
            lt_relevance="lithuanian-targeting",
            analyst_confidence=85,
            note="Private and never exported",
        )

    def test_legacy_sqlite_table_adds_nullable_admission_column_without_rewriting_rows(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                CREATE TABLE review_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    url TEXT,
                    brand TEXT,
                    scope TEXT,
                    reason_code TEXT,
                    confidence INTEGER,
                    note TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO review_events (
                    event_id, recorded_at, action, domain, url, brand, reason_code, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "a" * 64,
                    "2026-08-25T12:00:00.000Z",
                    "add",
                    FIXTURE["domain"],
                    FIXTURE["url"],
                    FIXTURE["brand"],
                    "manual-observation",
                    95,
                ),
            )
            connection.commit()

        events = read_review_events(self.database)

        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].admission_source)
        with closing(sqlite3.connect(self.database)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(review_events)")}
        self.assertIn("admission_source", columns)

    def test_append_only_ledger_exports_bounded_positive_assessment(self) -> None:
        self._confirm()
        events = read_review_events(self.database)
        exported = build_public_export(
            review_state(events),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )
        self.assertEqual(exported["schemaVersion"], 3)
        self.assertEqual(exported["assessments"][0]["reviewState"], "confirmed-suspicious")
        self.assertEqual(exported["assessments"][0]["analystConfidence"], 85)
        self.assertNotIn("note", exported["assessments"][0])

        with closing(sqlite3.connect(self.database)) as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE review_events SET action = 'retract'")

    def test_programmatic_first_assessment_without_admission_cannot_publish(self) -> None:
        record_review_event(
            self.database,
            action="confirm",
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="credential-phishing",
            recorded_at="2026-08-25T12:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="confirmed-suspicious",
            evidence_codes=["certificate-transparency"],
            expires_at="2026-09-25T12:00:00.000Z",
            lt_relevance="lithuanian-targeting",
        )

        with self.assertRaisesRegex(ValueError, "cannot be represented"):
            build_public_export(
                review_state(read_review_events(self.database)),
                registry(),
                "2026-08-25T12:01:00.000Z",
            )

    def test_reviewed_stix_rejects_assessment_without_admission(self) -> None:
        self._confirm()
        assessment = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )["assessments"][0]
        unadmitted = dict(assessment)
        unadmitted.pop("admissionSource")

        with self.assertRaisesRegex(ValueError, "admission provenance"):
            build_reviewed_stix_bundle([unadmitted], "2026-08-25T12:01:00.000Z")

    def test_programmatic_correction_without_admission_does_not_inherit_it(self) -> None:
        self._confirm()
        record_review_event(
            self.database,
            action="correct",
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="brand-impersonation",
            recorded_at="2026-08-25T13:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="confirmed-suspicious",
            evidence_codes=["certificate-transparency", "urlscan-page"],
            expires_at="2026-10-25T12:00:00.000Z",
            lt_relevance="lithuanian-targeting",
        )

        events = read_review_events(self.database)
        self.assertIsNotNone(events[0].admission_source)
        self.assertIsNone(events[1].admission_source)
        with self.assertRaisesRegex(ValueError, "immutable admission"):
            build_public_export(review_state(events), registry(), "2026-08-25T13:01:00.000Z")

    def test_dated_negative_assessment_is_exported_without_creating_a_stix_indicator(self) -> None:
        record_review_event(
            self.database,
            action="dismiss",
            admission_source=admission(),
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="lexical-collision",
            recorded_at="2026-08-25T12:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="false-positive",
            evidence_codes=["certificate-transparency", "rdap"],
            expires_at="2026-09-25T12:00:00.000Z",
            lt_relevance="global-brand-reference",
            analyst_confidence=95,
        )
        exported = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )
        assessment = exported["assessments"][0]
        self.assertEqual(assessment["reviewState"], "false-positive")
        self.assertEqual(assessment["dispositionReason"], "lexical-collision")
        self.assertFalse(assessment["revoked"])

        prepared = signal()
        PublicReviewPolicy((), (), (assessment,)).apply_assessments(
            [prepared], datetime(2026, 8, 25, 12, 1, tzinfo=UTC)
        )
        self.assertEqual(prepared["reviewState"], "false-positive")
        self.assertEqual(prepared["evidenceTier"], "reviewed")
        bundle = build_reviewed_stix_bundle(exported["assessments"], "2026-08-25T12:01:00.000Z")
        self.assertFalse(any(item["type"] == "indicator" for item in bundle["objects"]))

        expired = signal()
        PublicReviewPolicy((), (), (assessment,)).apply_assessments(
            [expired], datetime(2026, 9, 26, tzinfo=UTC)
        )
        self.assertEqual(expired["reviewState"], "needs-review")

    def test_non_lexical_urlscan_dismissal_keeps_its_reviewed_brand(self) -> None:
        domain = "wardrobe-account.pages.dev"
        record_review_event(
            self.database,
            action="dismiss",
            admission_source=admission(
                domain=domain,
                observed_at="2026-08-25T10:00:00.000Z",
                sources=["URLScan"],
            ),
            domain=domain,
            brand="Vinted",
            reason_code="reviewed-exclusion",
            recorded_at="2026-08-25T12:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="benign-brand-reference",
            evidence_codes=["screenshot", "urlscan-page"],
            expires_at="2026-09-25T12:00:00.000Z",
            lt_relevance="global-brand-reference",
            analyst_confidence=90,
        )

        exported = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )

        self.assertEqual(exported["assessments"][0]["domain"], "wardrobe-account[.]pages[.]dev")
        self.assertEqual(exported["assessments"][0]["brand"], "Vinted")
        self.assertEqual(exported["assessments"][0]["reviewState"], "benign-brand-reference")

    def test_matcher_tightening_does_not_erase_historical_assessment(self) -> None:
        domain = "wardrobe-login.example"
        record_review_event(
            self.database,
            action="dismiss",
            admission_source=admission(domain=domain),
            domain=domain,
            brand="Vinted",
            reason_code="lexical-collision",
            recorded_at="2026-08-25T12:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="false-positive",
            evidence_codes=["certificate-transparency", "urlscan-page"],
            expires_at="2026-09-25T12:00:00.000Z",
            lt_relevance="global-brand-reference",
            analyst_confidence=95,
        )
        exported = build_public_export(
            review_state(read_review_events(self.database)),
            registry_with_alias("wardrobe"),
            "2026-08-25T12:01:00.000Z",
        )

        with tempfile.TemporaryDirectory() as temporary, patch(
            "hecavex_radar.review.PROJECT_ROOT", Path(temporary)
        ):
            target = Path(temporary) / "data" / "review" / "public-decisions.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(exported), encoding="utf-8")
            policy = load_public_review(
                "data/review/public-decisions.json",
                registry=registry_with_alias("secondhand-market"),
                now=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
            )

        self.assertEqual(len(policy.assessments), 1)
        self.assertEqual(policy.assessments[0]["brand"], "Vinted")
        self.assertEqual(policy.assessments[0]["signalId"], exported["assessments"][0]["signalId"])

    def test_v2_migration_accepts_only_an_empty_assessment_collection(self) -> None:
        self._confirm()
        exported = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )
        exported["schemaVersion"] = 2  # type: ignore[typeddict-item]
        exported["assessments"][0].pop("admissionSource")
        with tempfile.TemporaryDirectory() as temporary, patch(
            "hecavex_radar.review.PROJECT_ROOT", Path(temporary)
        ):
            target = Path(temporary) / "data/review/public-decisions.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(exported), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "supported schema"):
                load_public_review(
                    "data/review/public-decisions.json",
                    registry=registry(),
                    now=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
                )

            exported["assessments"] = []
            target.write_text(json.dumps(exported), encoding="utf-8")
            policy = load_public_review(
                "data/review/public-decisions.json",
                registry=registry(),
                now=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
            )

        self.assertEqual(policy.assessments, ())

    def test_new_non_matching_manual_candidate_is_rejected(self) -> None:
        result = review_main(
            [
                "--database",
                str(self.database),
                "add",
                "https://neutral-history-only.invalid/login",
                "--brand",
                "Vinted",
            ]
        )

        self.assertEqual(result, 1)
        self.assertEqual(read_review_events(self.database), [])

    def test_new_non_matching_assessment_cannot_bypass_admission_with_explicit_brand(self) -> None:
        result = review_main(
            [
                "--database",
                str(self.database),
                "dismiss",
                "https://neutral-history-only.invalid/login",
                "--brand",
                "Vinted",
                "--state",
                "false-positive",
                "--reason",
                "lexical-collision",
                "--evidence",
                "urlscan-page",
                "--expires-at",
                "2099-09-25T12:00:00.000Z",
            ]
        )

        self.assertEqual(result, 1)
        self.assertEqual(read_review_events(self.database), [])

    def test_matcher_match_without_a_published_observation_cannot_be_assessed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "hecavex_radar.review.PROJECT_ROOT", Path(temporary)
        ), patch("hecavex_radar.review.load_brand_registry", return_value=registry()):
            result = review_main(
                [
                    "--database",
                    str(self.database),
                    "dismiss",
                    FIXTURE["domain"],
                    "--brand",
                    "Vinted",
                    "--state",
                    "false-positive",
                    "--reason",
                    "lexical-collision",
                    "--evidence",
                    "certificate-transparency",
                    "--expires-at",
                    "2099-09-25T12:00:00.000Z",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(read_review_events(self.database), [])

    def test_cli_admits_exact_signal_from_complete_shard_not_dashboard_prefix(self) -> None:
        domain = "wardrobe-account.pages.dev"
        projected = signal("URLScan")
        projected.update(
            {
                "id": stable_id(defang_host(domain).lower()),
                "url": "hxxps://wardrobe-account[.]pages[.]dev",
                "domain": defang_host(domain),
                "firstSeen": "2026-08-25T10:00:00.000Z",
                "lastSeen": "2026-08-25T10:05:00.000Z",
                "sources": ["URLScan"],
                "brand": "Vinted",
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_signal_projection(root, [projected])
            with patch("hecavex_radar.review.PROJECT_ROOT", root), patch(
                "hecavex_radar.review.load_brand_registry", return_value=registry()
            ):
                result = review_main(
                    [
                        "--database",
                        str(self.database),
                        "dismiss",
                        domain,
                        "--brand",
                        "Vinted",
                        "--state",
                        "benign-brand-reference",
                        "--reason",
                        "reviewed-exclusion",
                        "--evidence",
                        "urlscan-page",
                        "--expires-at",
                        "2099-09-25T12:00:00.000Z",
                    ]
                )

        self.assertEqual(result, 0)
        event = read_review_events(self.database)[0]
        source = json.loads(event.admission_source or "null")
        self.assertEqual(source["signalId"], projected["id"])
        self.assertEqual(source["domain"], projected["domain"])
        self.assertEqual(source["sources"], ["URLScan"])

    def test_cli_correction_copies_original_admission_bytes_without_public_lookup(self) -> None:
        self._confirm()
        original = read_review_events(self.database)[0].admission_source
        with tempfile.TemporaryDirectory() as temporary, patch(
            "hecavex_radar.review.PROJECT_ROOT", Path(temporary)
        ), patch("hecavex_radar.review.load_brand_registry", return_value=registry()), patch(
            "hecavex_radar.review._now", return_value="2026-08-26T12:00:00.000Z"
        ):
            result = review_main(
                [
                    "--database",
                    str(self.database),
                    "correct",
                    FIXTURE["domain"],
                    "--reason",
                    "brand-impersonation",
                    "--expires-at",
                    "2099-09-25T12:00:00.000Z",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(read_review_events(self.database)[1].admission_source, original)

    def test_cli_can_admit_an_exact_retained_history_signal(self) -> None:
        domain = "wardrobe-history.example"
        display_domain = defang_host(domain)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_signal_projection(root, [])
            history = {
                "schemaVersion": 1,
                "dataset": "history",
                "generatedAt": "2026-08-25T11:00:00.000Z",
                "signals": [
                    {
                        "id": stable_id(display_domain.lower()),
                        "domain": display_domain,
                        "brand": "Vinted",
                        "firstSeen": "2026-08-24T10:00:00.000Z",
                        "lastSeen": "2026-08-25T10:00:00.000Z",
                        "sources": ["CertStream", "URLScan"],
                    }
                ],
            }
            (root / "public/data/history.json").write_text(json.dumps(history), encoding="utf-8")
            with patch("hecavex_radar.review.PROJECT_ROOT", root), patch(
                "hecavex_radar.review.load_brand_registry", return_value=registry()
            ):
                result = review_main(
                    [
                        "--database",
                        str(self.database),
                        "inconclusive",
                        domain,
                        "--brand",
                        "Vinted",
                        "--reason",
                        "insufficient-evidence",
                    ]
                )

        self.assertEqual(result, 0)
        source = json.loads(read_review_events(self.database)[0].admission_source or "null")
        self.assertEqual(source["observedAt"], "2026-08-25T10:00:00.000Z")
        self.assertEqual(source["sources"], ["CertStream", "URLScan"])

    def test_expired_confirmation_returns_to_needs_review(self) -> None:
        self._confirm()
        assessment = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-09-26T12:00:00.000Z",
        )["assessments"][0]
        prepared = signal()
        PublicReviewPolicy((), (), (assessment,)).apply_assessments([prepared], datetime(2026, 9, 26, tzinfo=UTC))
        self.assertEqual(prepared["reviewState"], "needs-review")
        self.assertEqual(prepared["evidenceTier"], "reviewed")
        self.assertEqual(prepared["ltRelevance"], "lithuanian-targeting")

    def test_correction_keeps_indicator_identity_and_retraction_revokes(self) -> None:
        self._confirm()
        confirmed = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )["assessments"][0]
        first_bundle = build_reviewed_stix_bundle([confirmed], "2026-08-25T12:01:00.000Z")
        first_indicator = next(item for item in first_bundle["objects"] if item["type"] == "indicator")

        record_review_event(
            self.database,
            action="correct",
            admission_source=admission(),
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="brand-impersonation",
            recorded_at="2026-08-25T13:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="confirmed-suspicious",
            evidence_codes=["certificate-transparency", "screenshot", "urlscan-page"],
            expires_at="2026-10-25T12:00:00.000Z",
            lt_relevance="lithuanian-targeting",
            analyst_confidence=90,
        )
        corrected = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T13:01:00.000Z",
        )["assessments"][0]
        second_bundle = build_reviewed_stix_bundle([corrected], "2026-08-25T13:01:00.000Z")
        second_indicator = next(item for item in second_bundle["objects"] if item["type"] == "indicator")
        self.assertEqual(first_indicator["id"], second_indicator["id"])
        self.assertEqual(second_indicator["modified"], "2026-08-25T13:00:00.000Z")
        self.assertEqual(second_indicator["created_by_ref"], RADAR_IDENTITY_ID)
        self.assertEqual(second_indicator["object_marking_refs"], [TLP_CLEAR_MARKING_ID])
        events_after_correction = read_review_events(self.database)
        self.assertEqual(events_after_correction[0].admission_source, events_after_correction[1].admission_source)

        record_review_event(
            self.database,
            action="retract",
            admission_source=admission(),
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="incorrect-assessment",
            recorded_at="2026-08-25T14:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="inconclusive",
            evidence_codes=["certificate-transparency", "screenshot", "urlscan-page"],
            expires_at="2026-10-25T12:00:00.000Z",
            lt_relevance="lithuanian-targeting",
            analyst_confidence=90,
        )
        retracted = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T14:01:00.000Z",
        )["assessments"][0]
        third_bundle = build_reviewed_stix_bundle([retracted], "2026-08-25T14:01:00.000Z")
        third_indicator = next(item for item in third_bundle["objects"] if item["type"] == "indicator")
        self.assertEqual(first_indicator["id"], third_indicator["id"])
        self.assertTrue(third_indicator["revoked"])
        events_after_retraction = read_review_events(self.database)
        self.assertEqual(events_after_retraction[0].admission_source, events_after_retraction[2].admission_source)

    def test_fresh_confirmation_preserves_revoked_indicator_lifecycle(self) -> None:
        self._confirm()
        record_review_event(
            self.database,
            action="retract",
            admission_source=admission(),
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="incorrect-assessment",
            recorded_at="2026-08-25T14:00:00.000Z",
            reviewed_at="2026-08-25T12:00:00.000Z",
            review_state="inconclusive",
            evidence_codes=["certificate-transparency", "urlscan-page"],
            expires_at="2026-09-25T12:00:00.000Z",
            lt_relevance="lithuanian-targeting",
            analyst_confidence=85,
        )
        record_review_event(
            self.database,
            action="confirm",
            admission_source=admission(),
            domain=FIXTURE["domain"],
            brand=FIXTURE["brand"],
            reason_code="credential-phishing",
            recorded_at="2026-08-26T09:00:00.000Z",
            reviewed_at="2026-08-26T09:00:00.000Z",
            review_state="confirmed-suspicious",
            evidence_codes=["certificate-transparency", "screenshot"],
            expires_at="2026-09-26T09:00:00.000Z",
            lt_relevance="lithuanian-targeting",
            analyst_confidence=90,
        )

        exported = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-26T09:01:00.000Z",
        )
        self.assertEqual(len(exported["assessments"]), 2)
        self.assertNotEqual(exported["assessments"][0]["id"], exported["assessments"][1]["id"])

        bundle = build_reviewed_stix_bundle(exported["assessments"], "2026-08-26T09:01:00.000Z")
        indicators = [item for item in bundle["objects"] if item["type"] == "indicator"]
        self.assertEqual(len(indicators), 2)
        indicators_by_created = {item["created"]: item for item in indicators}
        self.assertTrue(indicators_by_created["2026-08-25T12:00:00.000Z"]["revoked"])
        self.assertFalse(indicators_by_created["2026-08-26T09:00:00.000Z"]["revoked"])

        prepared = signal()
        PublicReviewPolicy((), (), tuple(exported["assessments"])).apply_assessments(
            [prepared], datetime(2026, 8, 26, 9, 1, tzinfo=UTC)
        )
        self.assertEqual(prepared["reviewState"], "confirmed-suspicious")
        self.assertEqual(prepared["ltRelevance"], "lithuanian-targeting")

    def test_reviewed_indicator_has_a_public_history_sighting_when_available(self) -> None:
        self._confirm()
        assessment = build_public_export(
            review_state(read_review_events(self.database)),
            registry(),
            "2026-08-25T12:01:00.000Z",
        )["assessments"][0]
        history_signal = signal()
        history = {
            "signals": [
                {
                    "id": history_signal["id"],
                    "domain": history_signal["domain"],
                    "firstSeen": "2026-08-25T10:00:00.000Z",
                    "lastSeen": "2026-08-25T10:05:00.000Z",
                    "observationCount": 3,
                }
            ]
        }

        bundle = build_reviewed_stix_bundle(
            [assessment],
            "2026-08-25T12:01:00.000Z",
            history,
        )
        indicator = next(item for item in bundle["objects"] if item["type"] == "indicator")
        sighting = next(item for item in bundle["objects"] if item["type"] == "sighting")
        self.assertEqual(sighting["sighting_of_ref"], indicator["id"])
        self.assertEqual(sighting["first_seen"], "2026-08-25T10:00:00.000Z")
        self.assertEqual(sighting["last_seen"], "2026-08-25T10:05:00.000Z")
        self.assertEqual(sighting["count"], 3)
        self.assertEqual(sighting["created_by_ref"], RADAR_IDENTITY_ID)


if __name__ == "__main__":
    unittest.main()
