from __future__ import annotations

import json
import math
import os
import re
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from .brands import (
    BrandRegistry,
    domain_match_brands,
    is_brand_collision,
    is_suppressed_domain,
    load_brand_registry,
    resolve_brand_name,
)
from .domain_context import public_records as load_domain_context
from .hecavex import write_hecavex_candidates
from .history import build_history_events, previous_statuses, update_history
from .models import RadarSignal, RadarSource, RawSignal, SignalStatus, SourceResult
from .normalize import merge_signals, prepare_signal
from .provenance import normalize_reason_codes
from .publication import apply_source_counts, fit_dashboard_signals, publish_supplemental_artifacts
from .review import load_public_review
from .safety import clean_text, parse_and_defang_url, refang, safe_reference_url, safe_screenshot_url, stable_id
from .signal_detail import build_signal_details, load_recent_context_changes, write_signal_details
from .sources import (
    SOURCE_NAMES,
    fetch_hecavex,
    load_certstream,
    load_urlscan,
    skipped_sources,
)
from .stix import write_reviewed_stix_bundle, write_stix_bundle

SIGNAL_STATUSES = {"active", "suspected", "offline", "mitigated", "unknown"}
EVIDENCE_TIERS = {"name-only", "corroborated", "reviewed"}
REVIEW_STATES = {
    "unreviewed",
    "needs-review",
    "confirmed-suspicious",
    "false-positive",
    "benign-brand-reference",
    "inconclusive",
}
LT_RELEVANCE = {
    "lithuanian-targeting",
    "lithuanian-brand-relevance",
    "global-brand-reference",
    "unknown",
}
DISCOVERY_METHODS = {
    "certstream-live",
    "ct-search-api",
    "urlscan-public-report",
    "hecavex-public-export",
    "hecavex-review",
}
CORROBORATION_METHODS = {
    "urlscan-public-report",
    "urlscan-page-title",
    "urlscan-provider-verdict",
    "urlscan-primary-html-sha256",
    "analyst-review",
}
MAXIMUM_RETAINED_SIGNALS = 25_000
MAXIMUM_SNAPSHOT_BYTES = 512 * 1024
UTC_MILLISECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _enabled(value: str | None) -> bool:
    return bool(value and value.strip().lower() == "true")


def _enabled_by_default(value: str | None) -> bool:
    return value is None or _enabled(value)


def _bounded_integer(value: str | None, fallback: int, minimum: int, maximum: int) -> int:
    if not value or not value.strip():
        return fallback
    try:
        parsed = int(value)
    except ValueError:
        return fallback
    return min(maximum, max(minimum, parsed))


def _output_path() -> Path:
    repository = Path.cwd().resolve()
    target = (repository / os.environ.get("RADAR_OUTPUT", "public/data/radar.json")).resolve()
    if target == repository or not target.is_relative_to(repository):
        raise ValueError("RADAR_OUTPUT must stay inside the repository.")
    return target


def _stable_snapshot_view(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    stable = {key: value for key, value in payload.items() if key not in {"generatedAt", "lastSuccessfulSyncAt"}}
    raw_sources = stable.get("sources")
    if isinstance(raw_sources, list):
        stable["sources"] = [
            {key: value for key, value in source.items() if key != "fetchedAt"} if isinstance(source, dict) else source
            for source in raw_sources
        ]
    return stable


def _snapshot_content_unchanged(target: Path, candidate: object) -> bool:
    try:
        if target.stat().st_size > MAXIMUM_SNAPSHOT_BYTES:
            return False
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return _stable_snapshot_view(existing) == _stable_snapshot_view(candidate)


def _preserve_generated_at_if_unchanged(target: Path, candidate: dict[str, object]) -> bool:
    """Keep the material-data timestamp while allowing a successful heartbeat write."""
    if not _snapshot_content_unchanged(target, candidate):
        return False
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    generated_at = existing.get("generatedAt") if isinstance(existing, dict) else None
    if _public_timestamp(generated_at) is None:
        return False
    candidate["generatedAt"] = generated_at
    return True


def _existing_signal_count(target: Path, recent_since: datetime | None = None) -> int | None:
    try:
        if target.stat().st_size > MAXIMUM_SNAPSHOT_BYTES:
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 2
        or payload.get("dataset") != "live"
        or not isinstance(payload.get("signals"), list)
    ):
        return None
    if recent_since is None:
        return len(payload["signals"])
    return sum(
        isinstance(signal, dict)
        and (last_seen := _public_timestamp(signal.get("lastSeen"))) is not None
        and last_seen >= recent_since
        for signal in payload["signals"]
    )


def _public_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not UTC_MILLISECONDS.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    canonical = parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _load_existing_snapshot(
    target: Path,
    now: str,
    retention_days: int,
) -> tuple[list[RadarSignal], dict[str, str | None]]:
    try:
        if target.stat().st_size > MAXIMUM_SNAPSHOT_BYTES:
            return [], {}
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return [], {}
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 2
        or payload.get("dataset") != "live"
        or not isinstance(payload.get("signals"), list)
    ):
        return [], {}

    now_value = _public_timestamp(now)
    if now_value is None:
        return [], {}
    cutoff = now_value - timedelta(days=retention_days)
    retained: list[RadarSignal] = []
    for raw in payload["signals"][:MAXIMUM_RETAINED_SIGNALS]:
        if not isinstance(raw, dict):
            continue
        identifier = raw.get("id")
        url = raw.get("url")
        domain = raw.get("domain")
        first_seen = raw.get("firstSeen")
        last_seen = raw.get("lastSeen")
        sources = raw.get("sources")
        status = raw.get("status")
        legacy_score = raw.get("confidence")
        match_score = raw.get("matchScore", legacy_score)
        evidence_tier = raw.get("evidenceTier", "name-only")
        review_state = raw.get("reviewState", "unreviewed")
        lt_relevance = raw.get("ltRelevance", "lithuanian-brand-relevance")
        parsed_url = parse_and_defang_url(refang(url)) if isinstance(url, str) else None
        first_value = _public_timestamp(first_seen)
        last_value = _public_timestamp(last_seen)
        known_sources = (
            sorted({source for source in sources if source in SOURCE_NAMES})
            if isinstance(sources, list) and all(isinstance(source, str) for source in sources)
            else []
        )
        if (
            not isinstance(identifier, str)
            or len(identifier) != 20
            or any(character not in "0123456789abcdef" for character in identifier)
            or not isinstance(url, str)
            or len(url) > 2_048
            or not url.startswith(("hxxp://", "hxxps://"))
            or "?" in url
            or "#" in url
            or "http://" in url.lower()
            or "https://" in url.lower()
            or not isinstance(domain, str)
            or not domain
            or len(domain) > 512
            or parsed_url is None
            or parsed_url.display_url != url
            or parsed_url.display_domain != domain
            or identifier != stable_id(domain.lower())
            or first_value is None
            or last_value is None
            or first_value > last_value
            or last_value < cutoff
            or last_value > now_value + timedelta(minutes=5)
            or not isinstance(sources, list)
            or not 1 <= len(sources) <= 10
            or not all(isinstance(source, str) and 0 < len(source) <= 80 for source in sources)
            or not known_sources
            or status not in SIGNAL_STATUSES
            or isinstance(match_score, bool)
            or not isinstance(match_score, int)
            or not 0 <= match_score <= 100
            or (legacy_score is not None and legacy_score != match_score)
            or evidence_tier not in EVIDENCE_TIERS
            or review_state not in REVIEW_STATES
            or lt_relevance not in LT_RELEVANCE
        ):
            continue

        optional_values = (("brand", 120), ("country", 80), ("host", 160))
        if any(
            value is not None and (not isinstance(value, str) or clean_text(value, maximum) != value)
            for field, maximum in optional_values
            if (value := raw.get(field)) is not None
        ):
            continue
        screenshot = raw.get("screenshotUrl")
        if screenshot is not None and (
            not isinstance(screenshot, str) or safe_screenshot_url(screenshot) != screenshot
        ):
            continue
        reference = raw.get("referenceUrl")
        if reference is not None and safe_reference_url(reference) != reference:
            continue
        hashes = raw.get("hashes", [])
        reason_codes = raw.get("reasonCodes", [])
        discovered_via = raw.get("discoveredVia", [])
        corroborated_by = raw.get("corroboratedBy", [])
        if (
            not isinstance(hashes, list)
            or len(hashes) > 8
            or not all(
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
                for value in hashes
            )
        ):
            continue
        if (
            not isinstance(reason_codes, list)
            or len(reason_codes) > 16
            or reason_codes != normalize_reason_codes(reason_codes)
        ):
            continue
        if (
            not isinstance(discovered_via, list)
            or len(discovered_via) > 5
            or not all(isinstance(method, str) and method in DISCOVERY_METHODS for method in discovered_via)
            or len(discovered_via) != len(set(cast(list[str], discovered_via)))
            or not isinstance(corroborated_by, list)
            or len(corroborated_by) > 5
            or not all(isinstance(method, str) and method in CORROBORATION_METHODS for method in corroborated_by)
            or len(corroborated_by) != len(set(cast(list[str], corroborated_by)))
        ):
            continue
        retained_signal: RadarSignal = {
            "id": stable_id(domain.lower()),
            "url": url,
            "domain": domain,
            "firstSeen": cast(str, first_seen),
            "lastSeen": cast(str, last_seen),
            "sources": known_sources,
            "status": cast(SignalStatus, status),
            "brand": cast(str | None, raw.get("brand")),
            "country": cast(str | None, raw.get("country")),
            "host": cast(str | None, raw.get("host")),
            "screenshotUrl": screenshot,
            "referenceUrl": cast(str | None, reference),
            # Snapshot v1 does not carry hash provenance. Never retain old
            # untyped values across a source outage or schema migration.
            "hashes": [],
            "matchScore": match_score,
            "evidenceTier": cast(Any, evidence_tier),
            "reviewState": cast(Any, review_state),
            "ltRelevance": cast(Any, lt_relevance),
            "confidence": match_score,
        }
        if reason_codes:
            retained_signal["reasonCodes"] = normalize_reason_codes(reason_codes)
        if discovered_via:
            retained_signal["discoveredVia"] = cast(Any, discovered_via)
        if corroborated_by:
            retained_signal["corroboratedBy"] = cast(Any, corroborated_by)
        retained.append(retained_signal)

    source_fetches: dict[str, str | None] = {}
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, list):
        for source in raw_sources:
            if not isinstance(source, dict) or source.get("name") not in SOURCE_NAMES:
                continue
            fetched_at = source.get("fetchedAt")
            if fetched_at is None or _public_timestamp(fetched_at) is not None:
                source_fetches[source["name"]] = cast(str | None, fetched_at)
    return retained, source_fetches


def _validate_snapshot_size(count: int, target: Path, now: datetime | None = None) -> None:
    if _enabled(os.environ.get("RADAR_ALLOW_SMALL_SNAPSHOT")):
        return
    minimum = _bounded_integer(os.environ.get("RADAR_MIN_SIGNALS"), 0, 0, 25_000)
    retained_percent = _bounded_integer(os.environ.get("RADAR_MIN_RETAINED_PERCENT"), 25, 0, 100)
    guard_days = _bounded_integer(os.environ.get("RADAR_SNAPSHOT_GUARD_DAYS"), 30, 1, 90)
    recent_since = now.astimezone(UTC) - timedelta(days=guard_days) if now is not None else None
    previous = _existing_signal_count(target, recent_since)
    required = max(minimum, math.ceil(previous * retained_percent / 100) if previous is not None else 0)
    if count < required:
        previous_note = f"; previous live snapshot contains {previous}" if previous is not None else ""
        raise RuntimeError(
            f"Refusing to publish {count} signals because at least {required} are required{previous_note}. "
            "Set RADAR_ALLOW_SMALL_SNAPSHOT=true only for an intentional reset."
        )


def _retain_only_unrefreshed_sources(
    signals: list[RadarSignal],
    completed_sources: set[str],
    attempted_sources: set[str] | None = None,
) -> list[RadarSignal]:
    retainable_sources = attempted_sources if attempted_sources is not None else SOURCE_NAMES
    carried: list[RadarSignal] = []
    for signal in signals:
        remaining_sources = [
            source for source in signal["sources"] if source in retainable_sources and source not in completed_sources
        ]
        if remaining_sources:
            retained_signal = cast(RadarSignal, {**signal, "sources": remaining_sources})
            discovery = [
                method
                for method in retained_signal.get("discoveredVia", [])
                if (
                    (method in {"certstream-live", "ct-search-api"} and "CertStream" in remaining_sources)
                    or (method == "urlscan-public-report" and "URLScan" in remaining_sources)
                    or (method in {"hecavex-public-export", "hecavex-review"} and "HECAVEX" in remaining_sources)
                )
            ]
            corroboration = [
                method
                for method in retained_signal.get("corroboratedBy", [])
                if (
                    (method.startswith("urlscan-") and "URLScan" in remaining_sources)
                    or (method == "analyst-review" and "HECAVEX" in remaining_sources)
                )
            ]
            if discovery:
                retained_signal["discoveredVia"] = discovery
            else:
                retained_signal.pop("discoveredVia", None)
            if corroboration:
                retained_signal["corroboratedBy"] = corroboration
            else:
                retained_signal.pop("corroboratedBy", None)
            retained_signal["evidenceTier"] = (
                "reviewed"
                if retained_signal["reviewState"] == "confirmed-suspicious"
                else "corroborated"
                if corroboration
                else "name-only"
            )
            carried.append(retained_signal)
    return carried


def _represented_records(signals: list[RadarSignal], source_name: str) -> int:
    return sum(source_name in signal["sources"] for signal in signals)


def _hostname_from_url(value: str) -> str | None:
    candidate = refang(value)
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        hostname = urlsplit(candidate).hostname
    except ValueError:
        return None
    return hostname


def _scope_raw_signal(raw: RawSignal, registry: BrandRegistry) -> RawSignal | None:
    hostname = _hostname_from_url(raw.url)
    if not hostname or is_suppressed_domain(hostname, registry):
        return None
    matched_brands = domain_match_brands(hostname, registry)
    if len(matched_brands) > 1:
        return None
    declared_brand = resolve_brand_name(raw.brand, registry)
    domain_brand = next(iter(matched_brands), None)
    if declared_brand and domain_brand and declared_brand != domain_brand:
        return None
    brand = declared_brand or domain_brand
    if brand and is_brand_collision(hostname, brand, registry):
        return None
    return replace(raw, brand=brand) if brand else None


def _scope_retained_signal(signal: RadarSignal, registry: BrandRegistry) -> RadarSignal | None:
    hostname = _hostname_from_url(signal["domain"])
    if not hostname or is_suppressed_domain(hostname, registry):
        return None
    matched_brands = domain_match_brands(hostname, registry)
    if len(matched_brands) > 1:
        return None
    declared_brand = resolve_brand_name(signal["brand"], registry)
    domain_brand = next(iter(matched_brands), None)
    if declared_brand and domain_brand and declared_brand != domain_brand:
        return None
    brand = declared_brand or domain_brand
    if brand and is_brand_collision(hostname, brand, registry):
        return None
    return cast(RadarSignal, {**signal, "brand": brand}) if brand else None


def _run_source(label: str, operation: Callable[[], SourceResult]) -> SourceResult | None:
    try:
        result = operation()
        print(f"{label}: {len(result.signals)} records", flush=True)
        return result
    except Exception as error:
        message = str(error).splitlines()[0] if str(error) else type(error).__name__
        print(f"{label}: unavailable ({message})", file=sys.stderr, flush=True)
        return None


def synchronize(*, sync_time: datetime | None = None) -> Path:
    sync_time = sync_time or datetime.now(UTC)
    now = sync_time.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    target = _output_path()
    registry = load_brand_registry()
    review_path = os.environ.get("RADAR_REVIEW_DECISIONS_PATH", "").strip() or "data/review/public-decisions.json"
    review_policy = load_public_review(
        review_path,
        registry=registry,
        now=datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    results: list[SourceResult] = []
    source_states = skipped_sources()
    attempted_sources: set[str] = set()

    if _enabled_by_default(os.environ.get("CERTSTREAM_ARCHIVE_ENABLED")):
        attempted_sources.add("CertStream")
        lookback_days = _bounded_integer(os.environ.get("RADAR_CT_LOOKBACK_DAYS"), 7, 1, 90)
        archive_root = os.environ.get("CERTSTREAM_ARCHIVE_ROOT", "").strip() or "data/certstream"
        result = _run_source("CertStream", lambda: load_certstream(now, archive_root, lookback_days))
        if result:
            results.append(result)

    if _enabled_by_default(os.environ.get("URLSCAN_ARCHIVE_ENABLED")):
        attempted_sources.add("URLScan")
        lookback_days = _bounded_integer(os.environ.get("RADAR_URLSCAN_LOOKBACK_DAYS"), 30, 1, 90)
        archive_root = os.environ.get("URLSCAN_ARCHIVE_ROOT", "").strip() or "data/urlscan"
        result = _run_source("URLScan", lambda: load_urlscan(now, archive_root, lookback_days))
        if result:
            results.append(result)

    hecavex_url = os.environ.get("HECAVEX_FEED_URL", "").strip()
    if _enabled(os.environ.get("HECAVEX_ENABLED")):
        if not hecavex_url:
            raise RuntimeError("HECAVEX_FEED_URL is required when HECAVEX_ENABLED=true.")
        attempted_sources.add("HECAVEX")
        result = _run_source(
            "HECAVEX",
            lambda: fetch_hecavex(now, hecavex_url, os.environ.get("HECAVEX_FEED_TOKEN")),
        )
        if result:
            results.append(result)

    manual_signals = review_policy.manual_signals()
    if manual_signals:
        existing_hecavex = next((result for result in results if result.source["name"] == "HECAVEX"), None)
        if existing_hecavex:
            existing_hecavex.signals.extend(manual_signals)
            existing_hecavex.source["note"] = "Configured HECAVEX source and sanitized review export"
        else:
            attempted_sources.add("HECAVEX")
            results.append(
                SourceResult(
                    source={
                        "name": "HECAVEX",
                        "homepage": "https://hecavex.com/",
                        "fetchedAt": now,
                        "records": len(manual_signals),
                        "state": "healthy",
                        "note": "Sanitized local review export",
                    },
                    signals=manual_signals,
                )
            )

    if not results:
        raise RuntimeError("No source completed. Configure at least one source before running the synchronizer.")

    retained: list[RadarSignal] = []
    previous_source_fetches: dict[str, str | None] = {}
    if _enabled(os.environ.get("RADAR_RETAIN_EXISTING_SIGNALS")):
        retention_days = _bounded_integer(os.environ.get("RADAR_RETAIN_DAYS"), 7, 1, 90)
        retained, previous_source_fetches = _load_existing_snapshot(
            target,
            now,
            retention_days,
        )
        retained = [scoped for signal in retained if (scoped := _scope_retained_signal(signal, registry))]
        retained = [signal for signal in retained if not review_policy.suppresses(signal["domain"], signal["brand"])]
        print(f"Existing snapshot: retained {len(retained)} recent signals", flush=True)

    prepared: list[RadarSignal] = []
    for result in results:
        original_records = len(result.signals)
        accepted_records = 0
        for raw_signal in result.signals:
            scoped_signal = _scope_raw_signal(raw_signal, registry)
            if scoped_signal is None:
                continue
            raw_signal = scoped_signal
            signal = prepare_signal(raw_signal, now)
            if signal and not review_policy.suppresses(signal["domain"], signal["brand"]):
                prepared.append(signal)
                accepted_records += 1
        excluded = original_records - accepted_records
        result.source["records"] = accepted_records
        if excluded:
            scope_note = f"{excluded} non-registry target{'s' if excluded != 1 else ''} excluded"
            result.source["note"] = f"{result.source['note']}; {scope_note}" if result.source["note"] else scope_note

    sources: list[RadarSource] = []
    for source in source_states:
        completed = next((result for result in results if result.source["name"] == source["name"]), None)
        if completed:
            sources.append(completed.source)
        elif source["name"] in attempted_sources:
            sources.append(
                {
                    **source,
                    "fetchedAt": now,
                    "state": "partial",
                    "note": "Unavailable during this sync",
                }
            )
        else:
            sources.append(source)

    completed_sources = {result.source["name"] for result in results}
    retained = _retain_only_unrefreshed_sources(retained, completed_sources, attempted_sources)
    maximum = _bounded_integer(os.environ.get("RADAR_MAX_SIGNALS"), 2500, 1, 25_000)
    complete_merged = merge_signals(prepared + retained, maximum)
    review_policy.apply_assessments(
        complete_merged,
        datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    for source in sources:
        if source["name"] in completed_sources:
            continue
        carried = sum(source["name"] in signal["sources"] for signal in complete_merged)
        if carried:
            previous_note = source["note"]
            source["records"] = carried
            source["state"] = "partial"
            source["fetchedAt"] = previous_source_fetches.get(source["name"])
            source["note"] = (
                f"{previous_note}; {carried} recent records retained"
                if previous_note
                else f"Not refreshed; {carried} recent records retained"
            )
    for source in sources:
        source["records"] = _represented_records(complete_merged, source["name"])
    merged = fit_dashboard_signals(complete_merged, sources, now)
    apply_source_counts(merged, sources)
    if len(merged) < len(complete_merged):
        print(
            f"Dashboard byte budget selected {len(merged)} of {len(complete_merged)} signals; "
            "the complete ordered set remains available through radar.index.json.",
            flush=True,
        )
    intelligence = [item for result in results for item in result.intelligence]
    detail_root = os.environ.get("RADAR_DETAIL_ROOT", "").strip() or "public/data/signals"
    domain_context_path = os.environ.get("DOMAIN_CONTEXT_PATH", "").strip() or "data/enrichment/domain-context.json"
    domain_context = load_domain_context(domain_context_path, now=sync_time)
    context_journal_root = os.environ.get("PASSIVE_CONTEXT_JOURNAL", "").strip() or "data/history/context"
    context_changes = load_recent_context_changes(
        context_journal_root,
        now,
        retention_days=_bounded_integer(os.environ.get("PASSIVE_CONTEXT_JOURNAL_DAYS"), 60, 30, 90),
        allow_urlscan_redistribution=(
            os.environ.get("URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED", "").strip().lower() == "true"
        ),
    )
    details = build_signal_details(merged, intelligence, now, domain_context, context_changes)
    detail_ids = write_signal_details(detail_root, details)
    for signal in merged:
        if signal["id"] in detail_ids:
            signal["detailAvailable"] = True
    _validate_snapshot_size(
        len(merged),
        target,
        datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    history_root = os.environ.get("RADAR_HISTORY_ROOT", "").strip() or "data/history"
    history_output = os.environ.get("RADAR_HISTORY_OUTPUT", "").strip() or "public/data/history.json"
    history_detail_days = _bounded_integer(os.environ.get("RADAR_HISTORY_DETAIL_DAYS"), 30, 7, 90)
    history_summary_days = _bounded_integer(os.environ.get("RADAR_HISTORY_SUMMARY_DAYS"), 730, 30, 3_650)
    history_maximum = _bounded_integer(os.environ.get("RADAR_HISTORY_MAX_SIGNALS"), 5_000, 1, 25_000)
    history_events = build_history_events(prepared, merged, previous_statuses(history_output))
    history_path = update_history(
        root=history_root,
        output=history_output,
        events=history_events,
        now=datetime.fromisoformat(now.replace("Z", "+00:00")),
        registry=registry,
        is_suppressed=lambda domain, brand: review_policy.suppresses(domain, brand),
        detail_days=history_detail_days,
        summary_days=history_summary_days,
        maximum_signals=history_maximum,
    )
    print(f"Updated bounded public history at {history_path.relative_to(Path.cwd())}.", flush=True)
    try:
        from .history import read_public_history
        history_value: object = read_public_history(history_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The freshly written public history could not be reloaded safely.") from error
    if not isinstance(history_value, dict):
        raise ValueError("The freshly written public history is not a JSON object.")
    review_export: dict[str, object] = {
        "schemaVersion": 3,
        "dataset": "radar-review-decisions",
        "generatedAt": now,
        "suppressions": list(review_policy.suppressions),
        "candidates": list(review_policy.candidates),
        "assessments": list(review_policy.assessments),
    }
    candidate_output = os.environ.get("HECAVEX_CANDIDATE_OUTPUT", "").strip()
    if candidate_output:
        candidate_path = write_hecavex_candidates(
            candidate_output,
            merged,
            datetime.fromisoformat(now.replace("Z", "+00:00")),
        )
        print(
            f"Prepared defanged HECAVEX candidate handoff at {candidate_path.relative_to(Path.cwd())}.",
            flush=True,
        )
    snapshot = {
        "schemaVersion": 2,
        "dataset": "live",
        "generatedAt": now,
        "lastSuccessfulSyncAt": now,
        "signals": merged,
        "sources": sources,
    }
    content_unchanged = _preserve_generated_at_if_unchanged(target, snapshot)
    temporary = target.with_name(f"{target.name}.tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if len(body.encode("utf-8")) > MAXIMUM_SNAPSHOT_BYTES:
        raise RuntimeError("Refusing to publish a dashboard snapshot larger than 512 KiB.")
    try:
        temporary.write_text(body, encoding="utf-8", newline="\n")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if content_unchanged:
        print(
            "Snapshot data unchanged; recorded the successful sync and refreshed source check times.",
            flush=True,
        )
    else:
        print(f"Published {len(merged)} defanged signals to {target.relative_to(Path.cwd())}.", flush=True)
    stix_output = os.environ.get("RADAR_STIX_OUTPUT", "").strip() or "public/data/radar.stix.json"
    stix_target = (Path.cwd().resolve() / stix_output).resolve()
    if stix_target == target:
        raise ValueError("RADAR_STIX_OUTPUT must not replace the dashboard snapshot.")
    stix_path = write_stix_bundle(snapshot, stix_output)
    print(
        f"Published an observational STIX 2.1 bundle to {stix_path.relative_to(Path.cwd())}.",
        flush=True,
    )
    reviewed_stix_output = (
        os.environ.get("RADAR_REVIEWED_STIX_OUTPUT", "").strip() or "public/data/radar-reviewed.stix.json"
    )
    reviewed_stix_target = (Path.cwd().resolve() / reviewed_stix_output).resolve()
    if reviewed_stix_target in {target, stix_target}:
        raise ValueError("RADAR_REVIEWED_STIX_OUTPUT must be a separate publication file.")
    reviewed_stix_path = write_reviewed_stix_bundle(
        review_policy.assessments,
        now,
        reviewed_stix_output,
        history_value,
    )
    print(
        f"Published analyst-reviewed STIX 2.1 indicators to {reviewed_stix_path.relative_to(Path.cwd())}.",
        flush=True,
    )
    supplemental_paths = publish_supplemental_artifacts(
        snapshot,
        complete_merged,
        details,
        history=history_value,
        review_export=review_export,
        misp_enabled=_enabled(os.environ.get("RADAR_MISP_FEED_ENABLED")),
    )
    print(
        f"Published {len(supplemental_paths)} schema, integrity, health, change, shard, and relationship artifacts.",
        flush=True,
    )
    print(f"Published {len(detail_ids)} bounded signal-detail sidecars.", flush=True)
    return target


def main() -> int:
    try:
        synchronize()
        return 0
    except Exception as error:
        print(f"Sync failed: {error}", file=sys.stderr)
        return 1


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
