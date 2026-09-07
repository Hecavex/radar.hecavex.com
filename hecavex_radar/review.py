from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .brands import (
    BrandRegistry,
    domain_match_brands,
    load_brand_registry,
    normalize_domain,
    resolve_brand_name,
    score_domain,
)
from .models import LithuanianRelevance, RadarSignal, RawSignal, ReviewState
from .provenance import normalize_reason_codes, reason_codes_from_match
from .public_schemas import RADAR_INDEX_SCHEMA, RADAR_SCHEMA, RADAR_SHARD_SCHEMA
from .safety import defang_host, parse_and_defang_url, refang, stable_id

MAXIMUM_PUBLIC_BYTES = 2 * 1024 * 1024
MAXIMUM_PUBLIC_RECORDS = 2_500
MAXIMUM_NOTE_CHARACTERS = 2_000
UTC_MILLISECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
DECISION_ID = re.compile(r"^[a-f\d]{24}$")
SIGNAL_ID = re.compile(r"^[a-f\d]{20}$")
SHA256 = re.compile(r"^[a-f\d]{64}$")
SHARD_PATH = re.compile(r"^/data/radar-shards/(?P<number>\d{4})\.json$")
MAXIMUM_INDEX_BYTES = 256 * 1024
MAXIMUM_SHARD_BYTES = 256 * 1024
MAXIMUM_HISTORY_BYTES = 512 * 1024
MAXIMUM_ADMISSION_SIGNALS = 25_000
KNOWN_PUBLIC_SOURCES = frozenset({"CertStream", "URLScan", "HECAVEX"})
LOCAL_ACTIONS = frozenset(
    {
        "false-positive",
        "restore",
        "allowlist",
        "unallowlist",
        "add",
        "remove",
        "confirm",
        "correct",
        "retract",
        "inconclusive",
        "dismiss",
    }
)
SUPPRESSION_REASONS = frozenset(
    {
        "legitimate-domain",
        "lexical-collision",
        "official-domain",
        "wrong-brand",
        "insufficient-evidence",
        "reviewed-exclusion",
    }
)
ADD_REASON = "manual-observation"
REVIEW_STATES = frozenset(
    {
        "unreviewed",
        "needs-review",
        "confirmed-suspicious",
        "false-positive",
        "benign-brand-reference",
        "inconclusive",
    }
)
LT_RELEVANCE = frozenset(
    {
        "lithuanian-targeting",
        "lithuanian-brand-relevance",
        "global-brand-reference",
        "unknown",
    }
)
CONFIRMATION_REASONS = frozenset(
    {
        "credential-phishing",
        "brand-impersonation",
        "malicious-redirect",
        "phishing-infrastructure",
        "analyst-confirmed",
    }
)
INCONCLUSIVE_REASONS = frozenset({"insufficient-evidence", "conflicting-evidence", "review-expired"})
RETRACTION_REASONS = frozenset({"incorrect-assessment", "superseded-evidence", "benign-after-review"})
NEGATIVE_ASSESSMENT_REASONS = SUPPRESSION_REASONS
ASSESSMENT_REASONS = (
    CONFIRMATION_REASONS | INCONCLUSIVE_REASONS | RETRACTION_REASONS | NEGATIVE_ASSESSMENT_REASONS
)
EVIDENCE_CODES = frozenset(
    {
        "certificate-transparency",
        "urlscan-page",
        "provider-verdict",
        "screenshot",
        "primary-html-hash",
        "favicon-hash",
        "javascript-hash",
        "certificate",
        "dns",
        "rdap",
        "manual-observation",
    }
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicSuppression(TypedDict):
    id: str
    domain: str
    scope: Literal["exact", "subdomains"]
    brand: str | None
    reasonCode: str


class PublicCandidate(TypedDict):
    id: str
    signalId: str
    url: str
    domain: str
    observedAt: str
    brand: str
    matchScore: int
    confidence: int
    reasonCodes: list[str]


class AssessmentAdmissionSource(TypedDict):
    signalId: str
    domain: str
    brand: str
    observedAt: str
    sources: list[str]
    digest: str


class PublicAssessment(TypedDict):
    id: str
    signalId: str
    domain: str
    brand: str
    reviewState: ReviewState
    dispositionReason: str
    evidenceCodes: list[str]
    ltRelevance: LithuanianRelevance
    reviewedAt: str
    modifiedAt: str
    expiresAt: str | None
    analystConfidence: int | None
    revoked: bool
    admissionSource: AssessmentAdmissionSource


class PublicReviewExport(TypedDict):
    schemaVersion: Literal[3]
    dataset: Literal["radar-review-decisions"]
    generatedAt: str
    suppressions: list[PublicSuppression]
    candidates: list[PublicCandidate]
    assessments: list[PublicAssessment]


@dataclass(frozen=True, slots=True)
class LocalReviewEvent:
    sequence: int
    event_id: str
    recorded_at: str
    action: str
    domain: str
    url: str | None
    brand: str | None
    scope: str | None
    reason_code: str | None
    confidence: int | None
    note: str | None
    review_state: str | None
    evidence_codes: tuple[str, ...]
    expires_at: str | None
    lt_relevance: str | None
    analyst_confidence: int | None
    reviewed_at: str | None
    admission_source: str | None


@dataclass(slots=True)
class LocalReviewState:
    false_positives: dict[str, LocalReviewEvent]
    allowlists: dict[str, LocalReviewEvent]
    candidates: dict[str, LocalReviewEvent]
    assessments: dict[str, LocalReviewEvent]
    assessment_lifecycles: dict[tuple[str, str], LocalReviewEvent]


@dataclass(frozen=True, slots=True)
class PublicReviewPolicy:
    suppressions: tuple[PublicSuppression, ...]
    candidates: tuple[PublicCandidate, ...]
    assessments: tuple[PublicAssessment, ...] = ()

    def suppresses(self, domain: str, brand: str | None) -> bool:
        normalized = normalize_domain(refang(domain))
        if not normalized:
            return True
        for decision in self.suppressions:
            target = normalize_domain(refang(decision["domain"]))
            if target is None:
                continue
            same_domain = normalized == target
            below_domain = decision["scope"] == "subdomains" and normalized.endswith(f".{target}")
            same_brand = decision["brand"] is None or decision["brand"] == brand
            if same_brand and (same_domain or below_domain):
                return True
        return False

    def manual_signals(self) -> list[RawSignal]:
        return [
            RawSignal(
                url=refang(candidate["url"]),
                source="HECAVEX",
                first_seen=candidate["observedAt"],
                last_seen=candidate["observedAt"],
                status="suspected",
                brand=candidate["brand"],
                confidence=float(candidate["confidence"]),
                reason_codes=candidate["reasonCodes"],
                discovered_via=["hecavex-review"],
            )
            for candidate in self.candidates
            if not self.suppresses(candidate["domain"], candidate["brand"])
        ]

    def apply_assessments(self, signals: list[RadarSignal], now: datetime) -> None:
        """Attach sanitized analyst state to rows without changing source status."""

        # The public export retains the terminal version of every lifecycle so a
        # revoked STIX object cannot disappear after a later confirmation.  The
        # dashboard needs only the newest lifecycle for each current signal.
        by_signal: dict[str, PublicAssessment] = {}
        for lifecycle in self.assessments:
            current = by_signal.get(lifecycle["signalId"])
            assessment_order = (lifecycle["modifiedAt"], lifecycle["reviewedAt"], lifecycle["id"])
            current_order = (
                (current["modifiedAt"], current["reviewedAt"], current["id"])
                if current is not None
                else ("", "", "")
            )
            if assessment_order > current_order:
                by_signal[lifecycle["signalId"]] = lifecycle
        for signal in signals:
            selected = by_signal.get(signal["id"])
            if selected is None or selected["domain"] != signal["domain"] or selected["brand"] != signal["brand"]:
                continue
            expires_at = _timestamp(selected["expiresAt"])
            state: ReviewState = selected["reviewState"]
            if selected["revoked"]:
                state = "inconclusive"
            elif state != "inconclusive" and expires_at is not None and expires_at <= now.astimezone(UTC):
                state = "needs-review"
            signal["reviewState"] = state
            signal["evidenceTier"] = "reviewed"
            signal["ltRelevance"] = selected["ltRelevance"]
            methods = signal.get("corroboratedBy", [])
            if "analyst-review" not in methods:
                signal["corroboratedBy"] = [*methods, "analyst-review"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not UTC_MILLISECONDS.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    canonical = parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _admission_body(
    signal_id: str,
    domain: str,
    brand: str,
    observed_at: str,
    sources: list[str],
) -> dict[str, object]:
    return {
        "signalId": signal_id,
        "domain": domain,
        "brand": brand,
        "observedAt": observed_at,
        "sources": sources,
    }


def _admission_digest(body: dict[str, object]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_admission_source(
    *,
    signal_id: str,
    domain: str,
    brand: str,
    observed_at: str,
    sources: list[str],
) -> AssessmentAdmissionSource:
    body = _admission_body(signal_id, domain, brand, observed_at, sources)
    return cast(AssessmentAdmissionSource, {**body, "digest": _admission_digest(body)})


def valid_admission_source(
    value: object,
    *,
    signal_id: str | None = None,
    domain: str | None = None,
    brand: str | None = None,
    reviewed_at: str | None = None,
) -> bool:
    """Validate the self-contained public-observation admission envelope.

    The digest detects accidental mutation. It is deliberately not described
    as a signature or as proof that the observation was malicious.
    """

    fields = {"signalId", "domain", "brand", "observedAt", "sources", "digest"}
    if not isinstance(value, dict) or set(value) != fields:
        return False
    raw_signal_id = value.get("signalId")
    raw_domain = value.get("domain")
    raw_brand = value.get("brand")
    observed_at = value.get("observedAt")
    raw_sources = value.get("sources")
    digest = value.get("digest")
    normalized = normalize_domain(refang(raw_domain)) if isinstance(raw_domain, str) else None
    observed_value = _timestamp(observed_at)
    reviewed_value = _timestamp(reviewed_at) if reviewed_at is not None else None
    sources = (
        cast(list[str], raw_sources)
        if isinstance(raw_sources, list) and all(isinstance(item, str) for item in raw_sources)
        else []
    )
    body = _admission_body(
        raw_signal_id if isinstance(raw_signal_id, str) else "",
        raw_domain if isinstance(raw_domain, str) else "",
        raw_brand if isinstance(raw_brand, str) else "",
        observed_at if isinstance(observed_at, str) else "",
        sources,
    )
    return bool(
        isinstance(raw_signal_id, str)
        and SIGNAL_ID.fullmatch(raw_signal_id)
        and normalized is not None
        and raw_domain == defang_host(normalized)
        and raw_signal_id == stable_id(raw_domain.lower())
        and isinstance(raw_brand, str)
        and 0 < len(raw_brand) <= 120
        and raw_brand.strip() == raw_brand
        and all(character.isprintable() for character in raw_brand)
        and observed_value is not None
        and (reviewed_at is None or (reviewed_value is not None and observed_value <= reviewed_value))
        and 0 < len(sources) <= len(KNOWN_PUBLIC_SOURCES)
        and sources == sorted(set(sources))
        and all(source in KNOWN_PUBLIC_SOURCES for source in sources)
        and isinstance(digest, str)
        and SHA256.fullmatch(digest)
        and digest == _admission_digest(body)
        and (signal_id is None or raw_signal_id == signal_id)
        and (domain is None or raw_domain == domain)
        and (brand is None or raw_brand == brand)
    )


def _serialize_admission_source(value: AssessmentAdmissionSource | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed: object = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("Assessment admission source is invalid JSON.") from error
        canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if canonical != value or not valid_admission_source(parsed):
            raise ValueError("Assessment admission source is invalid or non-canonical.")
        return value
    if not valid_admission_source(value):
        raise ValueError("Assessment admission source is invalid.")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deserialize_admission_source(value: str | None) -> AssessmentAdmissionSource | None:
    if value is None:
        return None
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not valid_admission_source(parsed):
        return None
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return cast(AssessmentAdmissionSource, parsed) if canonical == value else None


def _default_database_path() -> Path:
    configured = os.environ.get("RADAR_REVIEW_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt" and (local_app_data := os.environ.get("LOCALAPPDATA")):
        base = Path(local_app_data)
    elif xdg_data := os.environ.get("XDG_DATA_HOME"):
        base = Path(xdg_data)
    else:
        base = Path.home() / ".local" / "share"
    return (base / "HECAVEX" / "Radar" / "review.sqlite3").resolve()


def _database_path(value: str | Path | None) -> Path:
    target = Path(value).expanduser().resolve() if value is not None else _default_database_path()
    repository = PROJECT_ROOT
    if target == repository or target.is_relative_to(repository):
        raise ValueError("The private review database must be stored outside the Git repository.")
    return target


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_events (
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
    # SQLite has no portable ADD COLUMN IF NOT EXISTS. This bounded migration
    # keeps existing private ledgers readable while preserving their event rows.
    existing_columns = {
        cast(str, row["name"]) for row in connection.execute("PRAGMA table_info(review_events)").fetchall()
    }
    for name, declaration in (
        ("review_state", "TEXT"),
        ("evidence_codes", "TEXT"),
        ("expires_at", "TEXT"),
        ("lt_relevance", "TEXT"),
        ("analyst_confidence", "INTEGER"),
        ("reviewed_at", "TEXT"),
        ("admission_source", "TEXT"),
    ):
        if name not in existing_columns:
            connection.execute(f"ALTER TABLE review_events ADD COLUMN {name} {declaration}")  # noqa: S608
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS review_events_no_update
        BEFORE UPDATE ON review_events
        BEGIN SELECT RAISE(ABORT, 'review_events is append-only'); END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS review_events_no_delete
        BEFORE DELETE ON review_events
        BEGIN SELECT RAISE(ABORT, 'review_events is append-only'); END
        """
    )
    connection.commit()
    with suppress(OSError):
        path.chmod(0o600)
    return connection


def _clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(character for character in value.strip() if character.isprintable())
    return cleaned[:MAXIMUM_NOTE_CHARACTERS] or None


def record_review_event(
    database: str | Path,
    *,
    action: str,
    domain: str,
    url: str | None = None,
    brand: str | None = None,
    scope: str | None = None,
    reason_code: str | None = None,
    confidence: int | None = None,
    note: str | None = None,
    recorded_at: str | None = None,
    review_state: str | None = None,
    evidence_codes: tuple[str, ...] | list[str] = (),
    expires_at: str | None = None,
    lt_relevance: str | None = None,
    analyst_confidence: int | None = None,
    reviewed_at: str | None = None,
    admission_source: AssessmentAdmissionSource | str | None = None,
) -> LocalReviewEvent:
    if action not in LOCAL_ACTIONS:
        raise ValueError("Unknown review action.")
    normalized = normalize_domain(refang(domain))
    timestamp = recorded_at or _now()
    if normalized is None or _timestamp(timestamp) is None:
        raise ValueError("Review action has an invalid domain or timestamp.")
    if scope not in {None, "exact", "subdomains"}:
        raise ValueError("Review scope must be exact or subdomains.")
    if confidence is not None and (type(confidence) is not int or not 0 <= confidence <= 100):
        raise ValueError("Review confidence must be an integer from 0 to 100.")
    canonical_evidence = tuple(sorted(set(evidence_codes)))
    if review_state is not None and review_state not in REVIEW_STATES:
        raise ValueError("Review state is not supported.")
    if any(code not in EVIDENCE_CODES for code in canonical_evidence):
        raise ValueError("Review evidence contains an unsupported code.")
    if expires_at is not None and _timestamp(expires_at) is None:
        raise ValueError("Review expiry must be a canonical UTC timestamp.")
    if lt_relevance is not None and lt_relevance not in LT_RELEVANCE:
        raise ValueError("Lithuanian relevance is not supported.")
    if analyst_confidence is not None and (type(analyst_confidence) is not int or not 0 <= analyst_confidence <= 100):
        raise ValueError("Analyst confidence must be an integer from 0 to 100.")
    if reviewed_at is not None and _timestamp(reviewed_at) is None:
        raise ValueError("Review origin must be a canonical UTC timestamp.")
    canonical_admission = _serialize_admission_source(admission_source)
    parsed_admission = _deserialize_admission_source(canonical_admission)
    if canonical_admission is not None and (
        brand is None
        or reviewed_at is None
        or not valid_admission_source(
            parsed_admission,
            signal_id=stable_id(defang_host(normalized).lower()),
            domain=defang_host(normalized),
            brand=brand,
            reviewed_at=reviewed_at,
        )
    ):
        raise ValueError("Assessment admission source does not match the review event.")
    canonical = json.dumps(
        {
            "recordedAt": timestamp,
            "action": action,
            "domain": normalized,
            "url": url,
            "brand": brand,
            "scope": scope,
            "reasonCode": reason_code,
            "confidence": confidence,
            "reviewState": review_state,
            "evidenceCodes": canonical_evidence,
            "expiresAt": expires_at,
            "ltRelevance": lt_relevance,
            "analystConfidence": analyst_confidence,
            "reviewedAt": reviewed_at,
            "admissionSource": canonical_admission,
            "nonce": secrets.token_hex(8),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    event_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path = _database_path(database)
    with closing(_connect(path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO review_events (
                event_id, recorded_at, action, domain, url, brand, scope, reason_code, confidence, note,
                review_state, evidence_codes, expires_at, lt_relevance, analyst_confidence, reviewed_at,
                admission_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                timestamp,
                action,
                normalized,
                url,
                brand,
                scope,
                reason_code,
                confidence,
                _clean_note(note),
                review_state,
                json.dumps(canonical_evidence, separators=(",", ":")),
                expires_at,
                lt_relevance,
                analyst_confidence,
                reviewed_at,
                canonical_admission,
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("Private review event did not receive a sequence number.")
        sequence = cursor.lastrowid
    return LocalReviewEvent(
        sequence=sequence,
        event_id=event_id,
        recorded_at=timestamp,
        action=action,
        domain=normalized,
        url=url,
        brand=brand,
        scope=scope,
        reason_code=reason_code,
        confidence=confidence,
        note=_clean_note(note),
        review_state=review_state,
        evidence_codes=canonical_evidence,
        expires_at=expires_at,
        lt_relevance=lt_relevance,
        analyst_confidence=analyst_confidence,
        reviewed_at=reviewed_at,
        admission_source=canonical_admission,
    )


def read_review_events(database: str | Path) -> list[LocalReviewEvent]:
    path = _database_path(database)
    if not path.exists():
        return []
    with closing(_connect(path)) as connection, connection:
        rows = connection.execute(
            """
            SELECT sequence, event_id, recorded_at, action, domain, url, brand, scope,
                   reason_code, confidence, note, review_state, evidence_codes,
                   expires_at, lt_relevance, analyst_confidence, reviewed_at, admission_source
            FROM review_events ORDER BY sequence ASC
            """
        ).fetchall()
    events: list[LocalReviewEvent] = []
    for row in rows:
        if row["action"] not in LOCAL_ACTIONS or normalize_domain(row["domain"]) != row["domain"]:
            raise ValueError("Private review database contains an invalid event.")
        try:
            raw_evidence: Any = json.loads(row["evidence_codes"] or "[]")
        except json.JSONDecodeError as error:
            raise ValueError("Private review database contains invalid evidence metadata.") from error
        evidence_codes = (
            tuple(raw_evidence)
            if isinstance(raw_evidence, list) and all(isinstance(item, str) for item in raw_evidence)
            else ()
        )
        if tuple(sorted(set(evidence_codes))) != evidence_codes or any(
            code not in EVIDENCE_CODES for code in evidence_codes
        ):
            raise ValueError("Private review database contains unsupported evidence metadata.")
        admission_source = row["admission_source"]
        if admission_source is not None and _deserialize_admission_source(admission_source) is None:
            raise ValueError("Private review database contains invalid assessment admission metadata.")
        events.append(
            LocalReviewEvent(
                sequence=row["sequence"],
                event_id=row["event_id"],
                recorded_at=row["recorded_at"],
                action=row["action"],
                domain=row["domain"],
                url=row["url"],
                brand=row["brand"],
                scope=row["scope"],
                reason_code=row["reason_code"],
                confidence=row["confidence"],
                note=row["note"],
                review_state=row["review_state"],
                evidence_codes=evidence_codes,
                expires_at=row["expires_at"],
                lt_relevance=row["lt_relevance"],
                analyst_confidence=row["analyst_confidence"],
                reviewed_at=row["reviewed_at"],
                admission_source=admission_source,
            )
        )
    return events


def review_state(events: list[LocalReviewEvent]) -> LocalReviewState:
    state = LocalReviewState(
        false_positives={},
        allowlists={},
        candidates={},
        assessments={},
        assessment_lifecycles={},
    )
    for event in events:
        if event.action == "false-positive":
            state.false_positives[event.domain] = event
        elif event.action == "restore":
            state.false_positives.pop(event.domain, None)
        elif event.action == "allowlist":
            state.allowlists[event.domain] = event
        elif event.action == "unallowlist":
            state.allowlists.pop(event.domain, None)
        elif event.action == "add":
            state.candidates[event.domain] = event
        elif event.action == "remove":
            state.candidates.pop(event.domain, None)
        elif event.action in {"confirm", "correct", "retract", "inconclusive", "dismiss"}:
            lifecycle_key = (event.domain, event.reviewed_at) if event.reviewed_at is not None else None
            previous_lifecycle = (
                state.assessment_lifecycles.get(lifecycle_key) if lifecycle_key is not None else None
            )
            if event.action in {"correct", "retract"} and (
                previous_lifecycle is None or event.admission_source != previous_lifecycle.admission_source
            ):
                raise ValueError("Assessment correction or retraction changed its immutable admission source.")
            state.assessments[event.domain] = event
            if lifecycle_key is not None:
                state.assessment_lifecycles[lifecycle_key] = event
    return state


def _decision_identifier(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _suppression(event: LocalReviewEvent) -> PublicSuppression:
    payload: dict[str, object] = {
        "domain": defang_host(event.domain),
        "scope": cast(Literal["exact", "subdomains"], event.scope or "exact"),
        "brand": event.brand,
        "reasonCode": event.reason_code or "reviewed-exclusion",
    }
    return cast(PublicSuppression, {"id": _decision_identifier(payload), **payload})


def _candidate(event: LocalReviewEvent, registry: BrandRegistry) -> PublicCandidate | None:
    match = score_domain(event.domain, registry)
    if (
        match is None
        or event.brand != match.brand
        or event.url is None
        or event.confidence is None
        or event.confidence > match.confidence
    ):
        return None
    safe_url = parse_and_defang_url(event.url)
    if safe_url is None or safe_url.display_domain != defang_host(event.domain):
        return None
    reasons = normalize_reason_codes(["manual-review", *reason_codes_from_match(match.reasons)])
    payload: dict[str, object] = {
        "signalId": stable_id(safe_url.display_domain.lower()),
        "url": safe_url.display_url,
        "domain": safe_url.display_domain,
        "observedAt": event.recorded_at,
        "brand": match.brand,
        "matchScore": event.confidence,
        "confidence": event.confidence,
        "reasonCodes": reasons,
    }
    return cast(PublicCandidate, {"id": _decision_identifier(payload), **payload})


def _assessment(event: LocalReviewEvent, registry: BrandRegistry) -> PublicAssessment | None:
    # Assessments describe a signal that was actually reviewed.  Its stored
    # brand is part of that dated review record, so later matcher tightening
    # must not make the lifecycle impossible to export.  This is intentionally
    # different from a new manual candidate, which still has to pass
    # ``score_domain`` in ``_candidate`` and in the CLI admission path.
    reviewed_brand = resolve_brand_name(event.brand, registry)
    reviewed_at = _timestamp(event.reviewed_at)
    modified_at = _timestamp(event.recorded_at)
    expires_at = _timestamp(event.expires_at) if event.expires_at is not None else None
    admission = _deserialize_admission_source(event.admission_source)
    if (
        reviewed_brand is None
        or event.brand != reviewed_brand
        or event.review_state not in REVIEW_STATES
        or event.review_state == "unreviewed"
        or event.reason_code not in ASSESSMENT_REASONS
        or event.lt_relevance not in LT_RELEVANCE
        or reviewed_at is None
        or modified_at is None
        or admission is None
        or not valid_admission_source(
            admission,
            signal_id=stable_id(defang_host(event.domain).lower()),
            domain=defang_host(event.domain),
            brand=reviewed_brand,
            reviewed_at=event.reviewed_at,
        )
        or reviewed_at > modified_at
        or (expires_at is not None and expires_at <= reviewed_at)
        or (event.action in {"confirm", "correct", "retract", "dismiss"} and expires_at is None)
        or (event.action in {"confirm", "correct", "retract", "dismiss"} and not event.evidence_codes)
        or (event.action in {"confirm", "correct"} and event.review_state != "confirmed-suspicious")
        or (event.action in {"retract", "inconclusive"} and event.review_state != "inconclusive")
        or (
            event.action == "dismiss"
            and event.review_state not in {"false-positive", "benign-brand-reference"}
        )
        or (event.action == "dismiss" and event.reason_code not in NEGATIVE_ASSESSMENT_REASONS)
    ):
        return None
    signal_id = admission["signalId"]
    identity: dict[str, object] = {
        "signalId": signal_id,
        "domain": defang_host(event.domain),
        "reviewedAt": event.reviewed_at,
    }
    return cast(
        PublicAssessment,
        {
            "id": _decision_identifier(identity),
            "signalId": signal_id,
            "domain": defang_host(event.domain),
            "brand": reviewed_brand,
            "reviewState": cast(ReviewState, event.review_state),
            "dispositionReason": event.reason_code,
            "evidenceCodes": list(event.evidence_codes),
            "ltRelevance": cast(LithuanianRelevance, event.lt_relevance),
            "reviewedAt": cast(str, event.reviewed_at),
            "modifiedAt": event.recorded_at,
            "expiresAt": event.expires_at,
            "analystConfidence": event.analyst_confidence,
            "revoked": event.action == "retract",
            "admissionSource": admission,
        },
    )


def build_public_export(
    state: LocalReviewState,
    registry: BrandRegistry,
    generated_at: str | None = None,
) -> PublicReviewExport:
    timestamp = generated_at or _now()
    timestamp_value = _timestamp(timestamp)
    if timestamp_value is None:
        raise ValueError("Public review export timestamp is invalid.")
    suppression_by_id = {
        suppression["id"]: suppression
        for event in [*state.false_positives.values(), *state.allowlists.values()]
        for suppression in [_suppression(event)]
    }
    suppressions = list(suppression_by_id.values())
    suppressions.sort(key=lambda item: (item["domain"], item["scope"], item["id"]))
    if len(suppressions) > MAXIMUM_PUBLIC_RECORDS:
        raise ValueError("Sanitized review export contains too many suppressions.")
    if not all(_valid_suppression(item, registry) for item in suppressions):
        raise ValueError("A suppression conflicts with current brand evidence.")
    policy = PublicReviewPolicy(tuple(suppressions), ())
    candidates = [
        candidate
        for event in state.candidates.values()
        if (candidate := _candidate(event, registry)) is not None
        and not policy.suppresses(candidate["domain"], candidate["brand"])
    ]
    candidates.sort(key=lambda item: (item["domain"], item["id"]))
    if len(candidates) > MAXIMUM_PUBLIC_RECORDS:
        raise ValueError("Sanitized review export contains too many manual candidates.")
    assessments: list[PublicAssessment] = []
    for event in state.assessment_lifecycles.values():
        assessment = _assessment(event, registry)
        if assessment is None:
            raise ValueError("A private assessment cannot be represented by the sanitized public contract.")
        modified = _timestamp(assessment["modifiedAt"])
        if modified is None or modified > timestamp_value + timedelta(minutes=5):
            raise ValueError("A private assessment is future-dated relative to the public export.")
        assessments.append(assessment)
    assessments.sort(key=lambda item: (item["domain"], item["reviewedAt"], item["id"]))
    if len(assessments) > MAXIMUM_PUBLIC_RECORDS:
        raise ValueError("Sanitized review export contains too many assessments.")
    return {
        "schemaVersion": 3,
        "dataset": "radar-review-decisions",
        "generatedAt": timestamp,
        "suppressions": suppressions,
        "candidates": candidates,
        "assessments": assessments,
    }


def _public_output_path(value: str | Path) -> Path:
    allowed = (PROJECT_ROOT / "data" / "review").resolve()
    requested = Path(value).expanduser()
    target = requested.resolve() if requested.is_absolute() else (PROJECT_ROOT / requested).resolve()
    if target == allowed or not target.is_relative_to(allowed):
        raise ValueError("Sanitized review exports must stay below data/review/.")
    return target


def _atomic_export(path: Path, payload: PublicReviewExport) -> bool:
    stable = {key: value for key, value in payload.items() if key != "generatedAt"}
    try:
        existing: Any = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing = None
    if isinstance(existing, dict) and {key: value for key, value in existing.items() if key != "generatedAt"} == stable:
        return False
    body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(body) > MAXIMUM_PUBLIC_BYTES:
        raise ValueError("Sanitized review export exceeds 2 MiB.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return True


def export_public_review(
    database: str | Path,
    output: str | Path = "data/review/public-decisions.json",
    *,
    registry: BrandRegistry | None = None,
    generated_at: str | None = None,
) -> tuple[Path, PublicReviewExport, bool]:
    state = review_state(read_review_events(database))
    payload = build_public_export(
        state,
        registry or load_brand_registry(PROJECT_ROOT / "data/brands-lt.json"),
        generated_at,
    )
    target = _public_output_path(output)
    changed = _atomic_export(target, payload)
    return target, payload, changed


def _valid_suppression(value: object, registry: BrandRegistry) -> bool:
    if not isinstance(value, dict) or set(value) != {"id", "domain", "scope", "brand", "reasonCode"}:
        return False
    normalized = normalize_domain(refang(value.get("domain", ""))) if isinstance(value.get("domain"), str) else None
    brand = value.get("brand")
    matched_brands = domain_match_brands(normalized, registry) if normalized else frozenset()
    official_brands = (
        frozenset(
            entry.brand
            for entry in registry.entries
            if any(normalized == official or normalized.endswith(f".{official}") for official in entry.official_domains)
        )
        if normalized
        else frozenset()
    )
    evidenced_brands = matched_brands | official_brands
    payload = {key: value[key] for key in ("domain", "scope", "brand", "reasonCode")}
    return bool(
        normalized
        and value["domain"] == defang_host(normalized)
        and value.get("scope") in {"exact", "subdomains"}
        and (brand is None or resolve_brand_name(brand, registry) == brand)
        and len(evidenced_brands) <= 1
        and (brand is None or not evidenced_brands or brand in evidenced_brands)
        and value.get("reasonCode") in SUPPRESSION_REASONS
        and isinstance(value.get("id"), str)
        and DECISION_ID.fullmatch(value["id"])
        and value["id"] == _decision_identifier(payload)
    )


def _valid_candidate(value: object, registry: BrandRegistry, now: datetime) -> bool:
    legacy_fields = {
        "id",
        "signalId",
        "url",
        "domain",
        "observedAt",
        "brand",
        "confidence",
        "reasonCodes",
    }
    current_fields = legacy_fields | {"matchScore"}
    if not isinstance(value, dict) or frozenset(value) not in {frozenset(legacy_fields), frozenset(current_fields)}:
        return False
    safe_url = parse_and_defang_url(refang(value.get("url", ""))) if isinstance(value.get("url"), str) else None
    observed = _timestamp(value.get("observedAt"))
    match = score_domain(refang(value.get("domain", "")), registry) if isinstance(value.get("domain"), str) else None
    reasons = value.get("reasonCodes")
    score = value.get("matchScore", value.get("confidence"))
    fields = tuple(key for key in value if key != "id")
    payload = {key: value[key] for key in fields}
    return bool(
        safe_url
        and safe_url.display_url == value.get("url")
        and safe_url.display_domain == value.get("domain")
        and value.get("signalId") == stable_id(safe_url.display_domain.lower())
        and observed is not None
        and observed <= now.astimezone(UTC) + timedelta(minutes=5)
        and match is not None
        and value.get("brand") == match.brand
        and type(score) is int
        and 0 <= score <= match.confidence
        and value.get("confidence") == score
        and isinstance(reasons, list)
        and "manual-review" in reasons
        and reasons == normalize_reason_codes(reasons)
        and isinstance(value.get("id"), str)
        and DECISION_ID.fullmatch(value["id"])
        and value["id"] == _decision_identifier(payload)
    )


def _valid_assessment(value: object, registry: BrandRegistry, now: datetime) -> bool:
    fields = {
        "id",
        "signalId",
        "domain",
        "brand",
        "reviewState",
        "dispositionReason",
        "evidenceCodes",
        "ltRelevance",
        "reviewedAt",
        "modifiedAt",
        "expiresAt",
        "analystConfidence",
        "revoked",
        "admissionSource",
    }
    if not isinstance(value, dict) or set(value) != fields:
        return False
    domain_value = value.get("domain")
    normalized = normalize_domain(refang(domain_value)) if isinstance(domain_value, str) else None
    brand_value = value.get("brand")
    reviewed_brand = resolve_brand_name(brand_value, registry) if isinstance(brand_value, str) else None
    reviewed_at = _timestamp(value.get("reviewedAt"))
    modified_at = _timestamp(value.get("modifiedAt"))
    expires_at = _timestamp(value.get("expiresAt")) if value.get("expiresAt") is not None else None
    evidence = value.get("evidenceCodes")
    analyst_confidence = value.get("analystConfidence")
    review_state_value = value.get("reviewState")
    disposition_reason = value.get("dispositionReason")
    revoked = value.get("revoked")
    identity = {
        "signalId": value.get("signalId"),
        "domain": value.get("domain"),
        "reviewedAt": value.get("reviewedAt"),
    }
    return bool(
        normalized
        and domain_value == defang_host(normalized)
        and value.get("signalId") == stable_id(domain_value.lower())
        and reviewed_brand is not None
        and brand_value == reviewed_brand
        and valid_admission_source(
            value.get("admissionSource"),
            signal_id=value.get("signalId") if isinstance(value.get("signalId"), str) else None,
            domain=domain_value if isinstance(domain_value, str) else None,
            brand=brand_value if isinstance(brand_value, str) else None,
            reviewed_at=value.get("reviewedAt") if isinstance(value.get("reviewedAt"), str) else None,
        )
        and review_state_value in REVIEW_STATES
        and review_state_value != "unreviewed"
        and disposition_reason in ASSESSMENT_REASONS
        and (
            (review_state_value == "confirmed-suspicious" and disposition_reason in CONFIRMATION_REASONS)
            or (
                review_state_value in {"false-positive", "benign-brand-reference"}
                and disposition_reason in NEGATIVE_ASSESSMENT_REASONS
            )
            or (
                review_state_value == "inconclusive"
                and (
                    (revoked is True and disposition_reason in RETRACTION_REASONS)
                    or (revoked is False and disposition_reason in INCONCLUSIVE_REASONS)
                )
            )
        )
        and isinstance(evidence, list)
        and evidence == sorted(set(evidence))
        and all(isinstance(item, str) and item in EVIDENCE_CODES for item in evidence)
        and (review_state_value == "inconclusive" or bool(evidence))
        and value.get("ltRelevance") in LT_RELEVANCE
        and reviewed_at is not None
        and modified_at is not None
        and reviewed_at <= modified_at <= now.astimezone(UTC) + timedelta(minutes=5)
        and (expires_at is None or expires_at > reviewed_at)
        and (analyst_confidence is None or (type(analyst_confidence) is int and 0 <= analyst_confidence <= 100))
        and type(revoked) is bool
        and (revoked is not True or review_state_value == "inconclusive")
        and (review_state_value == "inconclusive" and revoked is False or expires_at is not None)
        and isinstance(value.get("id"), str)
        and DECISION_ID.fullmatch(value["id"])
        and value["id"] == _decision_identifier(identity)
    )


def load_public_review(
    path: str | Path = "data/review/public-decisions.json",
    *,
    registry: BrandRegistry | None = None,
    now: datetime | None = None,
) -> PublicReviewPolicy:
    target = _public_output_path(path)
    try:
        if target.stat().st_size > MAXIMUM_PUBLIC_BYTES:
            raise ValueError("Sanitized review export exceeds 2 MiB.")
        value: Any = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return PublicReviewPolicy((), ())
    except json.JSONDecodeError as error:
        raise ValueError("Sanitized review export is invalid JSON.") from error
    brand_registry = registry or load_brand_registry(PROJECT_ROOT / "data/brands-lt.json")
    reference = now or datetime.now(UTC)
    schema_version = value.get("schemaVersion") if isinstance(value, dict) else None
    expected_keys = (
        {"schemaVersion", "dataset", "generatedAt", "suppressions", "candidates"}
        if schema_version == 1
        else {"schemaVersion", "dataset", "generatedAt", "suppressions", "candidates", "assessments"}
    )
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or schema_version not in {1, 2, 3}
        or value.get("dataset") != "radar-review-decisions"
        or _timestamp(value.get("generatedAt")) is None
        or not isinstance(value.get("suppressions"), list)
        or not isinstance(value.get("candidates"), list)
        or (schema_version in {2, 3} and not isinstance(value.get("assessments"), list))
        or len(value["suppressions"]) > MAXIMUM_PUBLIC_RECORDS
        or len(value["candidates"]) > MAXIMUM_PUBLIC_RECORDS
        or (schema_version in {2, 3} and len(value["assessments"]) > MAXIMUM_PUBLIC_RECORDS)
        or (schema_version == 2 and bool(value["assessments"]))
        or not all(_valid_suppression(item, brand_registry) for item in value["suppressions"])
        or not all(_valid_candidate(item, brand_registry, reference) for item in value["candidates"])
        or (
            schema_version == 3
            and not all(_valid_assessment(item, brand_registry, reference) for item in value["assessments"])
        )
    ):
        raise ValueError("Sanitized review export does not match a supported schema version.")
    suppressions = cast(tuple[PublicSuppression, ...], tuple(value["suppressions"]))
    candidates = cast(
        tuple[PublicCandidate, ...],
        tuple(
            {**candidate, "matchScore": candidate.get("matchScore", candidate["confidence"])}
            for candidate in value["candidates"]
        ),
    )
    assessments = cast(tuple[PublicAssessment, ...], tuple(value.get("assessments", ())))
    if len({item["id"] for item in suppressions}) != len(suppressions) or len(
        {item["id"] for item in candidates}
    ) != len(candidates):
        raise ValueError("Sanitized review export contains duplicate decisions.")
    if len({item["id"] for item in assessments}) != len(assessments):
        raise ValueError("Sanitized review export contains duplicate assessments.")
    return PublicReviewPolicy(suppressions, candidates, assessments)


def _indicator(value: str) -> tuple[str, str]:
    safe = parse_and_defang_url(value)
    if safe is None:
        raise ValueError("Indicator must contain a valid HTTP(S) URL or domain.")
    normalized = normalize_domain(refang(safe.display_domain))
    if normalized is None:
        raise ValueError("Indicator must contain a valid domain.")
    return normalized, refang(safe.display_url)


def _read_bounded_json(path: Path, maximum_bytes: int) -> object | None:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f"Could not inspect public admission artifact {path.name}.") from error
    if not 0 < size <= maximum_bytes:
        raise ValueError(f"Public admission artifact {path.name} is empty or oversized.")
    try:
        return cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Public admission artifact {path.name} is unreadable or invalid JSON.") from error


def _schema_matches(value: object, schema: dict[str, object]) -> bool:
    return not any(Draft202012Validator(schema).iter_errors(value))


def _complete_current_signals() -> list[dict[str, object]]:
    public_data = (PROJECT_ROOT / "public" / "data").resolve()
    index_path = public_data / "radar.index.json"
    index = _read_bounded_json(index_path, MAXIMUM_INDEX_BYTES)
    if index is None:
        snapshot = _read_bounded_json(public_data / "radar.json", 512 * 1024)
        if snapshot is None:
            return []
        if not _schema_matches(snapshot, RADAR_SCHEMA):
            raise ValueError("The current public Radar snapshot cannot prove assessment admission.")
        return cast(list[dict[str, object]], cast(dict[str, object], snapshot)["signals"])
    if not _schema_matches(index, RADAR_INDEX_SCHEMA):
        raise ValueError("The current public Radar signal index cannot prove assessment admission.")
    typed_index = cast(dict[str, object], index)
    signal_count = cast(int, typed_index["signalCount"])
    raw_shards = cast(list[object], typed_index["shards"])
    if signal_count > MAXIMUM_ADMISSION_SIGNALS or len(raw_shards) > MAXIMUM_ADMISSION_SIGNALS:
        raise ValueError("The current public Radar signal index exceeds the admission boundary.")
    signals: list[dict[str, object]] = []
    seen: set[str] = set()
    for expected_number, raw_row in enumerate(raw_shards, start=1):
        row = cast(dict[str, object], raw_row)
        path_value = cast(str, row["path"])
        path_match = SHARD_PATH.fullmatch(path_value)
        if path_match is None or int(path_match.group("number")) != expected_number or row["number"] != expected_number:
            raise ValueError("The current public Radar signal index contains an unsafe or non-sequential shard.")
        shard_path = (PROJECT_ROOT / "public" / path_value.removeprefix("/")).resolve()
        shard_root = (public_data / "radar-shards").resolve()
        if shard_path.parent != shard_root:
            raise ValueError("The current public Radar signal index contains an unsafe shard path.")
        try:
            body = shard_path.read_bytes()
        except OSError as error:
            raise ValueError("A current public Radar signal shard is unavailable.") from error
        if (
            not body
            or len(body) > MAXIMUM_SHARD_BYTES
            or len(body) != row["bytes"]
            or hashlib.sha256(body).hexdigest() != row["sha256"]
        ):
            raise ValueError("A current public Radar signal shard does not match its index digest.")
        try:
            shard: object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("A current public Radar signal shard is not valid JSON.") from error
        if not _schema_matches(shard, RADAR_SHARD_SCHEMA):
            raise ValueError("A current public Radar signal shard cannot prove assessment admission.")
        typed_shard = cast(dict[str, object], shard)
        shard_signals = cast(list[dict[str, object]], typed_shard["signals"])
        identifiers = [cast(str, signal["id"]) for signal in shard_signals]
        if (
            typed_shard["generatedAt"] != typed_index["generatedAt"]
            or typed_shard["shard"] != expected_number
            or len(shard_signals) != row["signals"]
            or not identifiers
            or identifiers[0] != row["firstSignalId"]
            or identifiers[-1] != row["lastSignalId"]
            or any(identifier in seen for identifier in identifiers)
        ):
            raise ValueError("A current public Radar signal shard conflicts with its index row.")
        signals.extend(shard_signals)
        seen.update(identifiers)
    if len(signals) != signal_count:
        raise ValueError("The current public Radar signal index count is inconsistent.")
    return signals


def _history_signals(registry: BrandRegistry) -> list[dict[str, object]]:
    from .history_partitions import read_document
    try:
        history = read_document(PROJECT_ROOT / "public" / "data" / "history.json", MAXIMUM_HISTORY_BYTES)
    except FileNotFoundError:
        return []
    if (
        not isinstance(history, dict)
        or history.get("schemaVersion") != 1
        or history.get("dataset") != "history"
        or _timestamp(history.get("generatedAt")) is None
        or not isinstance(history.get("signals"), list)
        or len(history["signals"]) > MAXIMUM_ADMISSION_SIGNALS
    ):
        raise ValueError("The bounded public Radar history cannot prove assessment admission.")
    generated = cast(datetime, _timestamp(history["generatedAt"]))
    signals: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in history["signals"]:
        if not isinstance(raw, dict):
            raise ValueError("The bounded public Radar history contains an invalid signal.")
        signal_id = raw.get("id")
        domain = raw.get("domain")
        brand = raw.get("brand")
        first_seen = _timestamp(raw.get("firstSeen"))
        last_seen = _timestamp(raw.get("lastSeen"))
        sources = raw.get("sources")
        normalized = normalize_domain(refang(domain)) if isinstance(domain, str) else None
        canonical_brand = resolve_brand_name(brand, registry) if isinstance(brand, str) else None
        if (
            not isinstance(signal_id, str)
            or not SIGNAL_ID.fullmatch(signal_id)
            or normalized is None
            or domain != defang_host(normalized)
            or signal_id != stable_id(domain.lower())
            or signal_id in seen
            or canonical_brand is None
            or brand != canonical_brand
            or first_seen is None
            or last_seen is None
            or first_seen > last_seen
            or last_seen > generated + timedelta(minutes=5)
            or not isinstance(sources, list)
            or not sources
            or sources != sorted(set(sources))
            or any(not isinstance(source, str) or source not in KNOWN_PUBLIC_SOURCES for source in sources)
        ):
            raise ValueError("The bounded public Radar history contains an invalid signal identity.")
        seen.add(signal_id)
        signals.append(cast(dict[str, object], raw))
    return signals


def _admission_from_signal(
    signal: dict[str, object],
    domain: str,
    registry: BrandRegistry,
    reviewed_at: str,
) -> AssessmentAdmissionSource | None:
    display_domain = signal.get("domain")
    if display_domain != defang_host(domain):
        return None
    signal_id = signal.get("id")
    raw_brand = signal.get("brand")
    canonical_brand = resolve_brand_name(raw_brand, registry) if isinstance(raw_brand, str) else None
    sources = signal.get("sources")
    reviewed_value = _timestamp(reviewed_at)
    first_seen = _timestamp(signal.get("firstSeen"))
    last_seen = _timestamp(signal.get("lastSeen"))
    if (
        reviewed_value is None
        or not isinstance(signal_id, str)
        or not SIGNAL_ID.fullmatch(signal_id)
        or signal_id != stable_id(display_domain.lower())
        or canonical_brand is None
        or raw_brand != canonical_brand
        or not isinstance(sources, list)
        or not sources
        or not all(isinstance(source, str) for source in sources)
        or cast(list[str], sources) != sorted(set(cast(list[str], sources)))
        or any(source not in KNOWN_PUBLIC_SOURCES for source in cast(list[str], sources))
        or first_seen is None
        or last_seen is None
        or first_seen > last_seen
    ):
        raise ValueError("A published Radar observation has invalid assessment-admission metadata.")
    observed = last_seen if last_seen <= reviewed_value else first_seen
    if observed > reviewed_value:
        return None
    observed_at = observed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return _build_admission_source(
        signal_id=signal_id,
        domain=display_domain,
        brand=canonical_brand,
        observed_at=observed_at,
        sources=cast(list[str], sources),
    )


def _assessment_admission(
    domain: str,
    registry: BrandRegistry,
    reviewed_at: str,
) -> AssessmentAdmissionSource | None:
    for signals in (_complete_current_signals(), _history_signals(registry)):
        admissions = [
            admission
            for signal in signals
            if (admission := _admission_from_signal(signal, domain, registry, reviewed_at)) is not None
        ]
        unique = {admission["digest"]: admission for admission in admissions}
        if len(unique) > 1:
            raise ValueError("Published Radar observations conflict for this assessment target.")
        if unique:
            return next(iter(unique.values()))
    return None


def _current_brand(domain: str, registry: BrandRegistry) -> str | None:
    if len(domain_match_brands(domain, registry)) > 1:
        return None
    match = score_domain(domain, registry)
    if match:
        return match.brand
    try:
        payload: Any = json.loads((PROJECT_ROOT / "public/data/radar.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 2
        or payload.get("dataset") != "live"
        or not isinstance(payload.get("signals"), list)
    ):
        return None
    defanged = defang_host(domain)
    brands = {
        signal.get("brand")
        for signal in payload["signals"]
        if isinstance(signal, dict) and signal.get("domain") == defanged and isinstance(signal.get("brand"), str)
    }
    return brands.pop() if len(brands) == 1 else None


def _resolved_requested_brand(value: str | None, inferred: str | None, registry: BrandRegistry) -> str | None:
    if value is None:
        return inferred
    resolved = resolve_brand_name(value, registry)
    if resolved is None or (inferred is not None and resolved != inferred):
        raise ValueError("Requested brand conflicts with current registry evidence.")
    return resolved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hecavex-review",
        description="Maintain the private Radar review ledger and explicitly export sanitized decisions.",
    )
    parser.add_argument("--database", help="Private SQLite path outside the Git repository.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create or verify the empty private append-only review ledger.")

    def decision(name: str, help_text: str, *, reason: bool = True, brand: bool = True) -> argparse.ArgumentParser:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("indicator")
        if brand:
            command.add_argument("--brand")
        if reason:
            command.add_argument("--reason", choices=sorted(SUPPRESSION_REASONS), required=True)
        command.add_argument("--note", help="Private note; never included in the sanitized export.")
        return command

    decision("false-positive", "Suppress one reviewed candidate exactly.")
    decision("restore", "Restore an exact false-positive suppression.", reason=False, brand=False)
    allowlist = decision("allowlist", "Suppress an exact domain or its subtree.")
    allowlist.add_argument("--scope", choices=("exact", "subdomains"), default="exact")
    allowlist.add_argument("--yes", action="store_true", help="Required for a subtree allowlist.")
    decision("unallowlist", "Remove a domain allowlist.", reason=False, brand=False)
    add = decision("add", "Add a currently matching candidate for sanitized export.", reason=False)
    add.add_argument("--confidence", type=int)
    decision("remove", "Remove a locally added candidate.", reason=False, brand=False)

    def assessment(name: str, help_text: str) -> argparse.ArgumentParser:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("indicator")
        command.add_argument("--brand")
        command.add_argument("--note", help="Private note; never included in the sanitized export.")
        return command

    confirm = assessment("confirm", "Confirm a suspicious candidate with bounded analyst evidence.")
    confirm.add_argument("--reason", choices=sorted(CONFIRMATION_REASONS), required=True)
    confirm.add_argument("--evidence", action="append", choices=sorted(EVIDENCE_CODES), required=True)
    confirm.add_argument("--expires-at", required=True, help="Canonical UTC timestamp with milliseconds.")
    confirm.add_argument("--lt-relevance", choices=sorted(LT_RELEVANCE), default="lithuanian-brand-relevance")
    confirm.add_argument("--analyst-confidence", type=int)

    correct = assessment("correct", "Correct metadata for an active confirmed assessment.")
    correct.add_argument("--reason", choices=sorted(CONFIRMATION_REASONS))
    correct.add_argument("--evidence", action="append", choices=sorted(EVIDENCE_CODES))
    correct.add_argument("--expires-at", help="Replacement canonical UTC expiry timestamp.")
    correct.add_argument("--lt-relevance", choices=sorted(LT_RELEVANCE))
    correct.add_argument("--analyst-confidence", type=int)

    retract = assessment("retract", "Revoke a previously confirmed assessment without erasing history.")
    retract.add_argument("--reason", choices=sorted(RETRACTION_REASONS), required=True)

    inconclusive = assessment("inconclusive", "Record a bounded review that did not support confirmation.")
    inconclusive.add_argument("--reason", choices=sorted(INCONCLUSIVE_REASONS), required=True)
    inconclusive.add_argument("--evidence", action="append", choices=sorted(EVIDENCE_CODES))
    inconclusive.add_argument("--lt-relevance", choices=sorted(LT_RELEVANCE), default="unknown")
    dismiss = assessment(
        "dismiss",
        "Record a dated false-positive or benign brand-reference assessment without erasing the candidate history.",
    )
    dismiss.add_argument(
        "--state",
        choices=("false-positive", "benign-brand-reference"),
        required=True,
    )
    dismiss.add_argument("--reason", choices=sorted(NEGATIVE_ASSESSMENT_REASONS), required=True)
    dismiss.add_argument("--evidence", action="append", choices=sorted(EVIDENCE_CODES), required=True)
    dismiss.add_argument("--expires-at", required=True, help="Canonical UTC timestamp with milliseconds.")
    dismiss.add_argument("--lt-relevance", choices=sorted(LT_RELEVANCE), default="unknown")
    dismiss.add_argument("--analyst-confidence", type=int)
    list_command = subparsers.add_parser("list", help="List active local review state without private notes.")
    list_command.add_argument("--events", action="store_true", help="List event metadata instead of active state.")
    export = subparsers.add_parser("export", help="Write sanitized public review state to Git data/review/.")
    export.add_argument("--output", default="data/review/public-decisions.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        database = _database_path(args.database)
        registry = load_brand_registry(PROJECT_ROOT / "data/brands-lt.json")
        if args.command == "init":
            with closing(_connect(database)):
                pass
            print(f"Private review database is ready: {database}")
            return 0
        if args.command == "list":
            events = read_review_events(database)
            if args.events:
                for event in events:
                    print(f"{event.sequence:04d} {event.recorded_at} {event.action:14s} {defang_host(event.domain)}")
            else:
                state = review_state(events)
                for label, values in (
                    ("false-positive", state.false_positives),
                    ("allowlist", state.allowlists),
                    ("candidate", state.candidates),
                    ("assessment", state.assessments),
                ):
                    for event in values.values():
                        print(f"{label:14s} {defang_host(event.domain)} {event.brand or '-'}")
            print(f"Private database: {database}")
            return 0
        if args.command == "export":
            target, payload, changed = export_public_review(database, args.output, registry=registry)
            print(
                f"{'Wrote' if changed else 'Preserved'} {target.relative_to(PROJECT_ROOT)}: "
                f"{len(payload['suppressions'])} suppressions, {len(payload['candidates'])} candidates, "
                f"{len(payload['assessments'])} assessments."
            )
            return 0

        domain, url = _indicator(args.indicator)
        state = review_state(read_review_events(database))
        action = cast(str, args.command)
        if action == "false-positive":
            inferred = _current_brand(domain, registry)
            brand = _resolved_requested_brand(args.brand, inferred, registry)
            if brand is None:
                raise ValueError("False-positive targets must match the registry or current public snapshot.")
            record_review_event(
                database,
                action=action,
                domain=domain,
                brand=brand,
                scope="exact",
                reason_code=args.reason,
                note=args.note,
            )
        elif action == "restore":
            if domain not in state.false_positives:
                raise ValueError("No active exact false-positive decision exists for this domain.")
            record_review_event(database, action=action, domain=domain, note=args.note)
        elif action == "allowlist":
            if args.scope == "subdomains" and not args.yes:
                raise ValueError("A subtree allowlist requires --yes because it can suppress many hosts.")
            inferred = _current_brand(domain, registry)
            brand = _resolved_requested_brand(args.brand, inferred, registry)
            record_review_event(
                database,
                action=action,
                domain=domain,
                brand=brand,
                scope=args.scope,
                reason_code=args.reason,
                note=args.note,
            )
        elif action == "unallowlist":
            if domain not in state.allowlists:
                raise ValueError("No active allowlist exists for this domain.")
            record_review_event(database, action=action, domain=domain, note=args.note)
        elif action == "add":
            match = score_domain(domain, registry)
            if match is None:
                raise ValueError("A manual candidate must independently pass the current public domain matcher.")
            brand = _resolved_requested_brand(args.brand, match.brand, registry)
            requested = match.confidence if args.confidence is None else args.confidence
            if requested < 0:
                raise ValueError("Confidence must be from 0 to 100.")
            confidence = min(match.confidence, requested)
            record_review_event(
                database,
                action=action,
                domain=domain,
                url=url,
                brand=brand,
                reason_code=ADD_REASON,
                confidence=confidence,
                note=args.note,
            )
        elif action == "remove":
            if domain not in state.candidates:
                raise ValueError("No active locally added candidate exists for this domain.")
            record_review_event(database, action=action, domain=domain, note=args.note)
        elif action in {"confirm", "correct", "retract", "inconclusive", "dismiss"}:
            current = state.assessments.get(domain)
            event_time = _now()
            event_value = _timestamp(event_time)
            if event_value is None:  # pragma: no cover - generated internally
                raise ValueError("Could not create a canonical review timestamp.")
            if action in {"correct", "retract"}:
                if current is None:
                    raise ValueError("A correction or retraction requires an existing assessment lifecycle.")
                inferred = resolve_brand_name(current.brand, registry)
                admission = _deserialize_admission_source(current.admission_source)
                if (
                    inferred is None
                    or admission is None
                    or current.reviewed_at is None
                    or not valid_admission_source(
                        admission,
                        signal_id=stable_id(defang_host(domain).lower()),
                        domain=defang_host(domain),
                        brand=inferred,
                        reviewed_at=current.reviewed_at,
                    )
                ):
                    raise ValueError("The existing assessment has no verified immutable admission source.")
                admission_source: AssessmentAdmissionSource | str = cast(str, current.admission_source)
            else:
                admission = _assessment_admission(domain, registry, event_time)
                if admission is None:
                    raise ValueError("Assessment targets must be an exact current or retained public Radar signal.")
                inferred = admission["brand"]
                admission_source = admission
            brand = _resolved_requested_brand(args.brand, inferred, registry)
            current_expiry = _timestamp(current.expires_at) if current and current.expires_at else None
            current_expired = current_expiry is not None and current_expiry <= event_value
            if action == "confirm":
                if (
                    current is not None
                    and current.review_state == "confirmed-suspicious"
                    and current.action != "retract"
                    and not current_expired
                ):
                    raise ValueError("A confirmed assessment already exists; use correct or retract.")
                expires = _timestamp(args.expires_at)
                if expires is None or expires <= event_value:
                    raise ValueError("Confirmation expiry must be a future canonical UTC timestamp.")
                record_review_event(
                    database,
                    action=action,
                    domain=domain,
                    brand=brand,
                    reason_code=args.reason,
                    note=args.note,
                    recorded_at=event_time,
                    review_state="confirmed-suspicious",
                    evidence_codes=args.evidence,
                    expires_at=args.expires_at,
                    lt_relevance=args.lt_relevance,
                    analyst_confidence=args.analyst_confidence,
                    reviewed_at=event_time,
                    admission_source=admission_source,
                )
            elif action == "correct":
                if (
                    current is None
                    or current.review_state != "confirmed-suspicious"
                    or current.action == "retract"
                    or current_expired
                ):
                    raise ValueError("Only an active confirmed assessment can be corrected.")
                if not any(
                    value is not None
                    for value in (
                        args.reason,
                        args.evidence,
                        args.expires_at,
                        args.lt_relevance,
                        args.analyst_confidence,
                    )
                ):
                    raise ValueError("A correction must replace at least one public assessment field.")
                expires_at = args.expires_at or current.expires_at
                expires = _timestamp(expires_at) if expires_at is not None else None
                if expires is None or expires <= event_value:
                    raise ValueError("Corrected expiry must be a future canonical UTC timestamp.")
                record_review_event(
                    database,
                    action=action,
                    domain=domain,
                    brand=brand,
                    reason_code=args.reason or current.reason_code,
                    note=args.note,
                    recorded_at=event_time,
                    review_state="confirmed-suspicious",
                    evidence_codes=args.evidence or current.evidence_codes,
                    expires_at=expires_at,
                    lt_relevance=args.lt_relevance or current.lt_relevance,
                    analyst_confidence=(
                        args.analyst_confidence if args.analyst_confidence is not None else current.analyst_confidence
                    ),
                    reviewed_at=current.reviewed_at,
                    admission_source=admission_source,
                )
            elif action == "retract":
                if current is None or current.review_state != "confirmed-suspicious" or current.action == "retract":
                    raise ValueError("Only an active confirmed assessment can be retracted.")
                record_review_event(
                    database,
                    action=action,
                    domain=domain,
                    brand=brand,
                    reason_code=args.reason,
                    note=args.note,
                    recorded_at=event_time,
                    review_state="inconclusive",
                    evidence_codes=current.evidence_codes,
                    expires_at=current.expires_at,
                    lt_relevance=current.lt_relevance,
                    analyst_confidence=current.analyst_confidence,
                    reviewed_at=current.reviewed_at,
                    admission_source=admission_source,
                )
            elif action == "inconclusive":
                if (
                    current is not None
                    and current.review_state == "confirmed-suspicious"
                    and current.action != "retract"
                ):
                    raise ValueError("Use retract to downgrade an active confirmed assessment.")
                record_review_event(
                    database,
                    action=action,
                    domain=domain,
                    brand=brand,
                    reason_code=args.reason,
                    note=args.note,
                    recorded_at=event_time,
                    review_state="inconclusive",
                    evidence_codes=args.evidence or (),
                    lt_relevance=args.lt_relevance,
                    reviewed_at=event_time,
                    admission_source=admission_source,
                )
            else:
                if (
                    current is not None
                    and current.review_state == "confirmed-suspicious"
                    and current.action != "retract"
                ):
                    raise ValueError("Use retract before recording a negative assessment for a confirmed signal.")
                expires = _timestamp(args.expires_at)
                if expires is None or expires <= event_value:
                    raise ValueError("Negative assessment expiry must be a future canonical UTC timestamp.")
                record_review_event(
                    database,
                    action=action,
                    domain=domain,
                    brand=brand,
                    reason_code=args.reason,
                    note=args.note,
                    recorded_at=event_time,
                    review_state=args.state,
                    evidence_codes=args.evidence,
                    expires_at=args.expires_at,
                    lt_relevance=args.lt_relevance,
                    analyst_confidence=args.analyst_confidence,
                    reviewed_at=event_time,
                    admission_source=admission_source,
                )
        else:
            raise ValueError("Unknown review command.")
        print(f"Recorded {action} for {defang_host(domain)} in private database {database}.")
        print("Run `hecavex-review export` when the sanitized public decisions are ready for review.")
        return 0
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Review failed: {error}", file=sys.stderr)
        return 1


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
