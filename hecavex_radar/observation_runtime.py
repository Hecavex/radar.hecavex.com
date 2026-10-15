"""Record accepted source facts and project versioned, policy-eligible hostnames."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .brands import (
    IDN_VISUAL_PROFILE,
    UNICODE_SECURITY_PROFILE,
    BrandRegistry,
    _idn_visual_enabled,
    domain_match_brands,
    is_brand_collision,
    is_suppressed_domain,
    normalize_domain,
    resolve_brand_name,
    score_domain,
)
from .history import KNOWN_STATUSES, _load_summary, read_event_file
from .normalize import legacy_source_time_evidence, validate_source_time_evidence
from .observation_publication import atomic_write, encode
from .observation_store import (
    IDENTITY_VERSION,
    STORE_VERSION,
    ObservationInput,
    append_observations,
    build_public_records,
    grouping_metadata,
    read_observations,
    validate_timestamp,
)
from .period_metrics import METRICS_VERSION
from .provenance import reason_codes_from_match
from .review import PublicReviewPolicy

RUNTIME = Path("data/history/observations/runtime.json")
RECOVERY = Path("data/history/observations/recovery-state.json")
MATCHING_ALGORITHM_VERSION = "radar-domain-matching-v1"
MAXIMUM_RECOVERY_BYTES = 64 * 1024 * 1024


def policy_versions(registry: BrandRegistry, review_export: Mapping[str, object]) -> dict[str, str]:
    semantic_review = {key: value for key, value in review_export.items() if key != "generatedAt"}
    matching = {
        "algorithm": MATCHING_ALGORITHM_VERSION, "registry": asdict(registry),
        "sourceSha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes().replace(
            b"\r\n", b"\n",
        )).hexdigest() for name in ("brands.py", "provenance.py")},
        "unicode": UNICODE_SECURITY_PROFILE, "grouping": grouping_metadata(),
        "idnVisualProfile": IDN_VISUAL_PROFILE, "idnVisualEnabled": _idn_visual_enabled(),
    }
    return {
        "identity": IDENTITY_VERSION, "store": STORE_VERSION, "metrics": METRICS_VERSION,
        "matching": "sha256:" + hashlib.sha256(encode(matching)).hexdigest(),
        "review": "sha256:" + hashlib.sha256(encode(semantic_review)).hexdigest(),
    }


def _read_optional(path: Path, maximum: int = 8 * 1024 * 1024) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.is_symlink() or path.is_junction() or path.stat().st_size > maximum:
        raise ValueError("Observation metadata is linked or exceeds capacity")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Observation metadata must be an object")
    return value


def _source_status(row: Mapping[str, Any]) -> dict[str, object]:
    annotations: dict[str, object] = {}
    for key in ("status", "previousStatus"):
        if key not in row:
            continue
        value = row[key]
        if value is None and key == "previousStatus":
            annotations[key] = None
        elif not isinstance(value, str) or value not in KNOWN_STATUSES:
            raise ValueError("Source status annotation is not a validated operational status")
        else:
            annotations[key] = value
    return annotations


def _legacy_input(row: Mapping[str, Any], timestamp: str, provenance: dict[str, object]) -> ObservationInput:
    match: dict[str, object] = {
        "brand": row["brand"], "score": row.get("matchScore"),
        "reasonCodes": row.get("reasonCodes", []), "policyVersion": "legacy-unknown",
        **_source_status(row),
    }
    if row.get("confidence") is not None:
        match["legacyConfidence"] = row["confidence"]
    if row.get("eventId") is not None:
        match["legacyEventId"] = row["eventId"]
    return {
        "domain": row["domain"], "sources": list(row["sources"]), "sourceObservedAt": timestamp,
        "sourceTimeProvenance": "legacy-source-boundary", "radarRecordedAt": None, "importedAt": None,
        "providerEventId": None, "originalMatch": match, "assessment": None, "provenance": [provenance],
    }


def record_observations(
    repository: Path, prepared: Sequence[Mapping[str, Any]], complete_signals: Sequence[Mapping[str, Any]], *,
    previous_history: Mapping[str, Any] | None, as_of: str, registry: BrandRegistry,
    review_export: Mapping[str, object], legacy_history_root: str | Path | None = None,
) -> None:
    """Capture every validated/scoped row before public review/display selection.

    complete_signals remains a compatibility argument; it cannot gate durable
    facts because current suppression and display limits belong to projections.
    """
    validate_timestamp(as_of)
    root = repository.resolve()
    legacy_root = Path(legacy_history_root) if legacy_history_root is not None else Path("data/history")
    if not legacy_root.is_absolute():
        legacy_root = root / legacy_root
    if not legacy_root.resolve().is_relative_to(root):
        raise ValueError("Legacy history bootstrap must remain inside the repository")
    for path in (legacy_root, *legacy_root.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Legacy history bootstrap refuses linked paths")
        if path == root:
            break
    runtime_path = root / RUNTIME
    metadata = _read_optional(runtime_path)
    if not metadata:
        metadata = {"schemaVersion": 1, "dataset": "radar-observation-capture", "recordedFrom": as_of}
    else:
        validate_timestamp(metadata.get("recordedFrom"))
    incoming: list[ObservationInput] = []
    existing_facts = read_observations(root)
    known_ids = {fact["hostnameId"] for fact in existing_facts}
    first_capture = not runtime_path.exists()
    history = previous_history or {}
    for row in history.get("signals", []):
        if first_capture or row["id"] not in known_ids:
            for timestamp in dict.fromkeys((row["firstSeen"], row["lastSeen"])):
                incoming.append(_legacy_input(row, timestamp, {
                    "kind": "retained-public-boundary", "signalId": row["id"],
                }))
    if first_capture:
        summary_path = legacy_root / "summary.json"
        summary = _load_summary(summary_path, as_of)
        summary_digest = hashlib.sha256(summary_path.read_bytes()).hexdigest() if summary_path.exists() else None
        for row in summary["signals"]:
            for timestamp in dict.fromkeys((row["firstSeen"], row["lastSeen"])):
                incoming.append(_legacy_input(row, timestamp, {
                    "kind": "retained-summary-boundary", "signalId": row["id"],
                    "path": summary_path.relative_to(root).as_posix(), "sha256": summary_digest,
                }))
        daily_root = legacy_root / "daily"
        if daily_root.is_symlink() or daily_root.is_junction():
            raise ValueError("Observation bootstrap refuses linked history")
        for path in sorted(daily_root.glob("????-??-??/events.ndjson")):
            events = read_event_file(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            for event in events:
                if event["eventType"] == "observation":
                    incoming.append(_legacy_input(event, event["observedAt"], {
                        "kind": "retained-daily-event", "path": path.relative_to(root).as_posix(), "sha256": digest,
                    }))
    versions = policy_versions(registry, review_export)
    for row in prepared:
        evidence = row.get("_sourceTimeEvidence")
        if evidence is None:
            # Old callers and already normalized archives cannot establish
            # whether a historical boundary was provider time or a fallback.
            evidence = legacy_source_time_evidence(row["firstSeen"], row["lastSeen"], ",".join(row["sources"]))
        else:
            if len(row["sources"]) != 1:
                raise ValueError("Captured source time provenance requires one original source")
            evidence = validate_source_time_evidence(evidence, first_seen=row["firstSeen"],
                                                     last_seen=row["lastSeen"], source=row["sources"][0])
        for boundary in evidence:
            if boundary["collectorTime"] is not None and boundary["collectorTime"] > as_of:
                raise ValueError("Source time provenance collector receipt exceeds capture asOf")
            timestamp = boundary["timestamp"]
            item = _legacy_input(row, timestamp, {
                "kind": "accepted-live-source", "signalId": row["id"], "policyVersion": versions["matching"],
                **boundary,
            })
            item["sourceTimeProvenance"] = boundary["origin"]
            item["radarRecordedAt"] = as_of
            item["originalMatch"] = {
                "brand": row["brand"], "score": row.get("matchScore"),
                "reasonCodes": row.get("reasonCodes", []), "policyVersion": versions["matching"],
                **_source_status(row),
            }
            incoming.append(item)
    append_observations(root, incoming, updated_at=as_of)
    atomic_write(runtime_path, encode(metadata))


def _assessment(row: Mapping[str, Any], as_of: str) -> dict[str, object]:
    state = row["reviewState"]
    expired = isinstance(row.get("expiresAt"), str) and row["expiresAt"] <= as_of
    if row.get("revoked") or expired or state == "inconclusive":
        verdict = "inconclusive"
    elif state == "confirmed-suspicious":
        verdict = "suspicious"
    elif state in {"false-positive", "benign-brand-reference"}:
        verdict = "benign"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict, "assessedAt": row["reviewedAt"], "decisionId": row["id"],
        "analystConfidence": row.get("analystConfidence"),
        "evidenceReferences": sorted([
            "review-decision:" + row["id"],
            *["evidence-code:" + code for code in row.get("evidenceCodes", [])],
        ]),
    }


def public_record_inputs(
    repository: Path, *, as_of: str, registry: BrandRegistry, review_export: Mapping[str, Any],
    available_record_ids: Collection[str],
) -> tuple[list[dict[str, Any]], dict[str, object], dict[str, str]]:
    validate_timestamp(as_of)
    observations = read_observations(repository)
    versions = policy_versions(registry, review_export)
    policy = PublicReviewPolicy(
        tuple(review_export.get("suppressions", [])), tuple(review_export.get("candidates", [])),
        tuple(review_export.get("assessments", [])),
    )
    assessments: dict[str, Mapping[str, Any]] = {}
    for decision in review_export.get("assessments", []):
        existing = assessments.get(decision["signalId"])
        if existing is None or (decision["modifiedAt"], decision["id"]) > (existing["modifiedAt"], existing["id"]):
            assessments[decision["signalId"]] = decision
    annotations: dict[str, list[dict[str, object]]] = {}
    domains: dict[str, str] = {}
    for fact in observations:
        if fact["sourceObservedAt"] <= as_of:
            domains[fact["hostnameId"]] = fact["domain"]
            annotations.setdefault(fact["hostnameId"], []).extend(fact["matchAnnotations"])
    matches: dict[str, Mapping[str, object]] = {}
    for hostname_id, domain in sorted(domains.items()):
        normalized = normalize_domain(domain.replace("[.]", "."))
        if normalized is None or is_suppressed_domain(normalized, registry):
            continue
        scored = score_domain(normalized, registry)
        brands = domain_match_brands(normalized, registry)
        if len(brands) > 1:
            continue
        for annotation in reversed(annotations.get(hostname_id, [])):
            brand = annotation.get("brand")
            reasons = cast(list[str], annotation.get("reasonCodes", []))
            off_domain = bool({"brand-title-match", "provider-verdict", "hecavex-public-export"}.intersection(reasons))
            if (not isinstance(brand, str) or resolve_brand_name(brand, registry) != brand
                    or is_brand_collision(normalized, brand, registry)
                    or (scored is not None and scored.brand != brand)
                    or (scored is None and not off_domain) or policy.suppresses(domain, brand)):
                continue
            decision = assessments.get(hostname_id)
            assessment = None
            if decision is not None and decision["domain"] == domain and decision["brand"] == brand:
                assessment = _assessment(decision, as_of)
            matches[hostname_id] = {
                "brand": brand, "score": scored.confidence if scored else annotation.get("score"),
                "reasonCodes": sorted(reason_codes_from_match(scored.reasons)) if scored else sorted(set(reasons)),
                "policyVersion": versions["matching"] if scored else annotation["policyVersion"],
                "assessment": assessment,
            }
            break
    from .publication_receipts import read_publication_clocks

    published, publication_from = read_publication_clocks(repository, as_of=as_of)
    records = build_public_records(
        observations, as_of=as_of, eligible_matches=matches,
        available_record_ids=available_record_ids, first_published_at=published,
    )
    runtime = _read_optional(repository / RUNTIME)
    recovery = _read_optional(repository / RECOVERY)
    recovered_days = sorted(set(recovery.get("recoveredDays", [])))
    missing_days = sorted(set(recovery.get("missingDays", [])))
    coverage: dict[str, object] = {
        "availableFrom": min((cast(str, row["firstSeen"]) for row in records), default=None),
        "recordedFrom": runtime.get("recordedFrom"), "publicationRecordedFrom": publication_from,
        "recoveredFrom": recovered_days[0] if recovered_days else None,
        "recoveredThrough": recovered_days[-1] if recovered_days else None,
        "recoveredDays": recovered_days, "missingDays": missing_days, "historyComplete": False,
        "collectionComplete": False, "historicalRecordingTimesComplete": False,
        "historicalPublicationTimesComplete": False,
        "basis": "recorded-and-recovered-observation-facts", "partialCurrentDay": True,
    }
    return cast(list[dict[str, Any]], records), coverage, versions


def import_recovery_bundle(repository: Path, bundle_path: Path, *, imported_at: str) -> dict[str, int]:
    validate_timestamp(imported_at)
    if (not bundle_path.is_file() or bundle_path.stat().st_size > MAXIMUM_RECOVERY_BYTES
            or any(path.is_symlink() or path.is_junction() for path in (bundle_path, *bundle_path.parents))):
        raise ValueError("Recovery bundle is linked or exceeds capacity")
    body = bundle_path.read_bytes()
    checksum = bundle_path.with_suffix(".sha256")
    if not checksum.is_file() or checksum.is_symlink() or checksum.is_junction() or checksum.stat().st_size > 256:
        raise ValueError("Recovery checksum is missing, linked or exceeds capacity")
    expected = hashlib.sha256(body).hexdigest() + "  " + bundle_path.name + "\n"
    if checksum.read_text(encoding="ascii") != expected:
        raise ValueError("Recovery bundle digest does not match")
    bundle = json.loads(body)
    if (not isinstance(bundle, dict) or type(bundle.get("schemaVersion")) is not int
            or bundle.get("schemaVersion") != 1 or bundle.get("dataset") != "radar-history-recovery"):
        raise ValueError("Unsupported recovery bundle")
    reconciliation = bundle.get("reconciliation")
    if (not isinstance(reconciliation, dict) or reconciliation.get("required") is not False
            or reconciliation.get("transitionOnlyBoundaries") != []):
        raise ValueError("Recovery reconciliation must complete before facts can be imported")
    observations = bundle.get("observations")
    if not isinstance(observations, list) or any(not isinstance(item, dict) for item in observations):
        raise ValueError("Recovery bundle has no observation facts")
    # Bundle generation time is not the actual import time. The store preserves
    # the earliest accepted import clock on subsequent idempotent replay.
    incoming = [cast(ObservationInput, {**item, "importedAt": imported_at}) for item in observations]
    days = bundle.get("coverage", {}).get("availablePartitionDays", [])
    missing = bundle.get("coverage", {}).get("missingDays", [])
    state = {
        "schemaVersion": 1, "dataset": "radar-observation-recovery-state",
        "importedAt": imported_at, "bundleSha256": hashlib.sha256(body).hexdigest(),
        "trustedHeads": bundle["trustedHeads"], "window": bundle["window"],
        "recoveredDays": sorted(set(days)), "missingDays": sorted(set(missing)),
        "reconciliation": reconciliation,
    }
    state_body = encode(state)
    if len(state_body) > 8 * 1024 * 1024:
        raise ValueError("Recovery metadata exceeds its finite byte budget")
    update = append_observations(repository, incoming, updated_at=imported_at)
    atomic_write(repository / RECOVERY, state_body, 8 * 1024 * 1024)
    return {"observations": update["observationCount"], "hostnames": update["hostnameCount"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--import-bundle", type=Path, required=True)
    parser.add_argument("--imported-at",
                        default=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    options = parser.parse_args(argv)
    result = import_recovery_bundle(options.repository.resolve(), options.import_bundle,
                                    imported_at=options.imported_at)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
