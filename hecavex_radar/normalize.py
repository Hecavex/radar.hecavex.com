from __future__ import annotations

import hashlib
import ipaddress
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlsplit

from .models import (
    CorroborationMethod,
    DiscoveryMethod,
    EvidenceTier,
    RadarSignal,
    RawSignal,
    SignalStatus,
    SourceTimeEvidence,
)
from .provenance import normalize_reason_codes
from .safety import (
    clean_text,
    defang_domains_in_text,
    defang_host,
    parse_and_defang_url,
    refang,
    safe_reference_url,
    safe_screenshot_url,
    stable_id,
)

IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
IPV6_CANDIDATE = re.compile(r"(?<![\da-f:])\[?[\da-f:]*:[\da-f:]+\]?(?![\da-f:])", re.IGNORECASE)
SHA256 = re.compile(r"^[a-f\d]{64}$", re.IGNORECASE)
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
DISCOVERY_METHODS: frozenset[DiscoveryMethod] = frozenset(
    {
        "certstream-live",
        "ct-search-api",
        "ct-log-poll",
        "urlscan-public-report",
        "hecavex-public-export",
        "hecavex-review",
    }
)
CORROBORATION_METHODS: frozenset[CorroborationMethod] = frozenset(
    {
        "urlscan-public-report",
        "urlscan-page-title",
        "urlscan-provider-verdict",
        "urlscan-primary-html-sha256",
        "analyst-review",
    }
)


def _parse_date(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return fallback


def _date_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_time(value: object) -> str:
    if not isinstance(value, str) or not value or _parse_date(value, "") != value:
        raise ValueError("Invalid source time provenance timestamp.")
    return value


def validate_source_time_evidence(
    value: object, *, first_seen: str, last_seen: str, source: str,
) -> list[SourceTimeEvidence]:
    """Validate internal archival evidence without promoting legacy clocks."""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Source time provenance requires both boundaries.")
    fields = set(SourceTimeEvidence.__annotations__)
    result: list[SourceTimeEvidence] = []
    for item, boundary, timestamp in zip(value, ("firstSeen", "lastSeen"), (first_seen, last_seen), strict=True):
        if (not isinstance(item, dict) or set(item) != fields or item["boundary"] != boundary
                or item["source"] != source or item["timestamp"] != timestamp):
            raise ValueError("Source time provenance boundary mismatch.")
        _canonical_time(timestamp)
        original, provider, collector = item["originalProviderTime"], item["providerObservedAt"], item["collectorTime"]
        if original is not None and (not isinstance(original, str) or len(original) > 256):
            raise ValueError("Source time provenance original value exceeds its finite budget.")
        truncated, digest = item["originalProviderTimeTruncated"], item["originalProviderTimeSha256"]
        if (type(truncated) is not bool
                or (original is None and (truncated or digest is not None))
                or (original is not None and (not isinstance(digest, str) or SHA256.fullmatch(digest) is None
                    or (truncated and len(original) != 256)
                    or (not truncated and digest != hashlib.sha256(original.encode("utf-8")).hexdigest())))):
            raise ValueError("Source time provenance original value digest or truncation is invalid.")
        if provider is not None:
            _canonical_time(provider)
        if collector is not None:
            _canonical_time(collector)
        origin, reason = item["origin"], item["reason"]
        reasons = {None, "missing", "invalid", "future", "after-last-seen", "legacy-normalized-unknown"}
        if (not isinstance(origin, str) or (reason is not None and not isinstance(reason, str))
                or reason not in reasons):
            raise ValueError("Invalid source time provenance fallback reason.")
        if origin == "provider-observation-time":
            valid = provider == timestamp and collector is not None and reason != "legacy-normalized-unknown"
            if reason is None:
                valid = valid and original is not None and _parse_date(original, "") == provider
        elif origin == "collector-time-fallback":
            valid = provider is None and collector == timestamp and reason in {
                "missing", "invalid", "future", "after-last-seen",
            }
        elif origin == "legacy-normalized-unknown":
            valid = provider is None and collector is None and original is None and reason == origin
        else:
            valid = False
        if not valid:
            raise ValueError("Source time provenance origin contradicts its clocks.")
        parsed_original = _parse_date(original, "")
        if ((reason == "missing" and original not in {None, ""})
                or (reason == "invalid" and (not original or (parsed_original and not truncated)))
                or (reason == "future" and (not parsed_original or collector is None
                    or _date_value(parsed_original) <= _date_value(collector) + timedelta(minutes=5)))
                or (reason == "after-last-seen" and (not parsed_original or parsed_original <= timestamp))):
            raise ValueError("Source time provenance fallback reason contradicts its original value.")
        if origin == "provider-observation-time" and reason is not None:
            last = value[1]
            if (boundary != "firstSeen" or not isinstance(last, dict) or provider != last.get("providerObservedAt")
                    or timestamp != last.get("timestamp") or last.get("origin") != "provider-observation-time"):
                raise ValueError("Source time provenance fallback does not reference the known last provider boundary.")
        if (provider is not None and collector is not None
                and _date_value(provider) > _date_value(collector) + timedelta(minutes=5)):
            raise ValueError("Source time provenance provider clock is implausibly future-dated.")
        result.append(cast(SourceTimeEvidence, dict(item)))
    if first_seen > last_seen:
        raise ValueError("Source time provenance boundaries are reversed.")
    return result


def legacy_source_time_evidence(first_seen: str, last_seen: str, source: str) -> list[SourceTimeEvidence]:
    return validate_source_time_evidence([
        {"timestamp": timestamp, "providerObservedAt": None, "originalProviderTime": None, "collectorTime": None,
         "originalProviderTimeTruncated": False, "originalProviderTimeSha256": None,
         "source": source, "boundary": boundary, "reason": "legacy-normalized-unknown",
         "origin": "legacy-normalized-unknown"}
        for boundary, timestamp in (("firstSeen", first_seen), ("lastSeen", last_seen))
    ], first_seen=first_seen, last_seen=last_seen, source=source)


def resolve_signal_times(raw: RawSignal, now: str) -> list[SourceTimeEvidence]:
    """Keep the effective compatibility clock and its actual origin separate.

    Missing/invalid provider values use collector time explicitly. A missing or
    contradictory first boundary may reference a valid last provider boundary.
    Archived evidence retains the original collector time on every replay.
    """
    source = clean_text(raw.source, 80) or ""
    if raw.source_time_evidence is not None:
        return validate_source_time_evidence(raw.source_time_evidence,
                                             first_seen=raw.first_seen or "", last_seen=raw.last_seen or "",
                                             source=source)
    _canonical_time(now)
    limit = _date_value(now) + timedelta(minutes=5)

    def resolve(value: str | None, boundary: str, fallback: SourceTimeEvidence | None = None) -> SourceTimeEvidence:
        parsed = _parse_date(value, "")
        reason = ("missing" if not value else "invalid" if not parsed
                  else "future" if _date_value(parsed) > limit else None)
        if reason is None and fallback is not None and parsed > fallback["timestamp"]:
            reason = "after-last-seen"
        provider = parsed if reason is None else fallback["providerObservedAt"] if fallback is not None else None
        timestamp = parsed if reason is None else fallback["timestamp"] if fallback is not None else now
        return {
            "timestamp": timestamp, "providerObservedAt": provider,
            "originalProviderTime": value[:256] if value is not None else None,
            "originalProviderTimeTruncated": value is not None and len(value) > 256,
            "originalProviderTimeSha256": (
                hashlib.sha256(value.encode("utf-8")).hexdigest() if value is not None else None
            ),
            "collectorTime": now, "source": source, "boundary": boundary, "reason": reason,
            "origin": "provider-observation-time" if provider is not None else "collector-time-fallback",
        }

    last = resolve(raw.last_seen, "lastSeen")
    first = resolve(raw.first_seen, "firstSeen", last)
    return validate_source_time_evidence([first, last], first_seen=first["timestamp"],
                                         last_seen=last["timestamp"], source=source)


def _map_status(value: str | None) -> SignalStatus:
    normalized = value.strip().lower() if value else ""
    if normalized in {"active", "confirmed", "live", "online", "verified"}:
        return "active"
    if normalized in {"potential", "pending", "suspected"}:
        return "suspected"
    if normalized in {"down", "inactive", "offline"}:
        return "offline"
    if normalized in {"mitigated", "removed", "takedown"}:
        return "mitigated"
    return "unknown"


def _confidence(value: float | None) -> int:
    if value is None or not math.isfinite(value):
        return 50
    return math.floor(min(100.0, max(0.0, value)) + 0.5)


def _safe_host(value: str | None) -> str | None:
    cleaned = clean_text(value, 160)
    if not cleaned:
        return None

    def defang_ipv6(match: re.Match[str]) -> str:
        candidate = match.group(0).removeprefix("[").removesuffix("]")
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return match.group(0)
        return defang_host(candidate) if address.version == 6 else match.group(0)

    ipv4_defanged = IPV4.sub(lambda match: defang_host(match.group(1)), cleaned)
    return defang_domains_in_text(IPV6_CANDIDATE.sub(defang_ipv6, ipv4_defanged))


def _safe_hashes(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return list(
        dict.fromkeys(value.lower() for value in values if SHA256.fullmatch(value) and value.lower() != EMPTY_SHA256)
    )[:8]


def _discovery_methods(values: object, source: str) -> list[DiscoveryMethod]:
    methods: list[DiscoveryMethod] = []
    if isinstance(values, (list, tuple)):
        for value in values:
            if value in DISCOVERY_METHODS and value not in methods:
                methods.append(value)
    if not methods:
        fallback: dict[str, DiscoveryMethod] = {
            "CertStream": "certstream-live",
            "URLScan": "urlscan-public-report",
            "HECAVEX": "hecavex-public-export",
        }
        if source in fallback:
            methods.append(fallback[source])
    return methods


def _corroboration_methods(values: object, reasons: Sequence[str]) -> list[CorroborationMethod]:
    methods: list[CorroborationMethod] = []
    if isinstance(values, (list, tuple)):
        for value in values:
            if value in CORROBORATION_METHODS and value not in methods:
                methods.append(value)
    inferred: tuple[tuple[str, CorroborationMethod], ...] = (
        ("brand-title-match", "urlscan-page-title"),
        ("provider-verdict", "urlscan-provider-verdict"),
        ("primary-html-hash-pivot", "urlscan-primary-html-sha256"),
    )
    for reason, method in inferred:
        if reason in reasons and method not in methods:
            methods.append(method)
    return methods


def _evidence_tier(signal: RadarSignal) -> EvidenceTier:
    """Describe evidence strength without turning it into a verdict.

    A second source, a bounded provider assessment/title match, or a proven
    cross-observation hash pivot is corroboration. A hash captured in the same
    provider observation is context, not independent evidence. Analyst review
    is applied later by the private review policy because it is not source
    evidence.
    """

    evidence = set(signal.get("brandEvidence", []))
    reasons = set(signal.get("reasonCodes", []))
    corroboration = set(signal.get("corroboratedBy", []))
    if (
        len(signal["sources"]) > 1
        or "title" in evidence
        or "verdict" in evidence
        or "primary-html-sha256" in evidence
        or bool(
            corroboration.intersection(
                {
                    "urlscan-page-title",
                    "urlscan-provider-verdict",
                    "urlscan-primary-html-sha256",
                }
            )
        )
        or "brand-title-match" in reasons
        or "provider-verdict" in reasons
        or "primary-html-hash-pivot" in reasons
    ):
        return "corroborated"
    return "name-only"


def prepare_signal(raw: RawSignal, now: str) -> RadarSignal | None:
    safe_url = parse_and_defang_url(raw.url)
    source = clean_text(raw.source, 80)
    if not safe_url or not source:
        return None
    first_time, last_time = resolve_signal_times(raw, now)
    first_seen, last_seen = first_time["timestamp"], last_time["timestamp"]
    score = _confidence(raw.confidence)
    reason_codes = normalize_reason_codes(raw.reason_codes)
    signal: RadarSignal = {
        # One public row represents one observed host. This correlates CT names,
        # URLScan paths, and HECAVEX observations without duplicating schemes or paths.
        "id": stable_id(safe_url.display_domain.lower()),
        "url": safe_url.display_url,
        "domain": safe_url.display_domain,
        "firstSeen": first_seen,
        "lastSeen": last_seen,
        "sources": [source],
        "status": _map_status(raw.status),
        "brand": clean_text(raw.brand, 120),
        "country": clean_text(raw.country, 80),
        "host": _safe_host(raw.host),
        "screenshotUrl": safe_screenshot_url(raw.screenshot_url),
        "referenceUrl": safe_reference_url(raw.reference_url),
        "hashes": _safe_hashes(raw.hashes),
        "matchScore": score,
        "evidenceTier": "name-only",
        "reviewState": "needs-review" if raw.reason_codes and "manual-review" in raw.reason_codes else "unreviewed",
        "ltRelevance": "lithuanian-brand-relevance",
        # Deprecated snapshot alias retained while external consumers move to
        # matchScore. It must always equal matchScore.
        "confidence": score,
    }
    discovered_via = _discovery_methods(raw.discovered_via, source)
    corroborated_by = _corroboration_methods(raw.corroborated_by, reason_codes)
    if discovered_via:
        signal["discoveredVia"] = discovered_via
    if corroborated_by:
        signal["corroboratedBy"] = corroborated_by
    if reason_codes:
        signal["reasonCodes"] = reason_codes
    signal["evidenceTier"] = _evidence_tier(signal)
    return signal


STATUS_PRIORITY: dict[SignalStatus, int] = {
    "active": 5,
    "suspected": 4,
    "unknown": 3,
    "offline": 2,
    "mitigated": 1,
}


def _url_specificity(value: str) -> tuple[int, int, int]:
    try:
        parsed = urlsplit(refang(value))
    except ValueError:
        return (0, 0, 0)
    path = parsed.path if parsed.path != "/" else ""
    return (int(bool(path)), len(path), int(parsed.scheme == "https"))


def merge_signals(signals: list[RadarSignal], maximum: int) -> list[RadarSignal]:
    merged: dict[str, RadarSignal] = {}
    conflicted_ids: set[str] = set()
    for signal in signals:
        if signal["id"] in conflicted_ids:
            continue
        current = merged.get(signal["id"])
        if current is None:
            merged[signal["id"]] = signal.copy()
            continue
        current_brand = current["brand"]
        signal_brand = signal["brand"]
        if current_brand and signal_brand and current_brand != signal_brand:
            merged.pop(signal["id"], None)
            conflicted_ids.add(signal["id"])
            continue
        current_last_seen = _date_value(current["lastSeen"])
        signal_last_seen = _date_value(signal["lastSeen"])
        signal_is_newer = signal_last_seen > current_last_seen
        same_observation_time = signal_last_seen == current_last_seen
        current["firstSeen"] = min(current["firstSeen"], signal["firstSeen"], key=_date_value)
        current["lastSeen"] = max(current["lastSeen"], signal["lastSeen"], key=_date_value)
        current["sources"] = sorted(set(current["sources"] + signal["sources"]))
        if _url_specificity(signal["url"]) > _url_specificity(current["url"]):
            current["url"] = signal["url"]
        if signal_is_newer or (
            same_observation_time and STATUS_PRIORITY[signal["status"]] > STATUS_PRIORITY[current["status"]]
        ):
            current["status"] = signal["status"]
        current["brand"] = current_brand or signal_brand
        if signal_is_newer:
            current["country"] = signal["country"] or current["country"]
            current["host"] = signal["host"] or current["host"]
            current["screenshotUrl"] = signal["screenshotUrl"] or current["screenshotUrl"]
        else:
            current["country"] = current["country"] or signal["country"]
            current["host"] = current["host"] or signal["host"]
            current["screenshotUrl"] = current["screenshotUrl"] or signal["screenshotUrl"]
        current_reference = current.get("referenceUrl")
        signal_reference = signal.get("referenceUrl")
        current["referenceUrl"] = (
            signal_reference or current_reference if signal_is_newer else current_reference or signal_reference
        )
        current["hashes"] = list(dict.fromkeys(current.get("hashes", []) + signal.get("hashes", [])))[:8]
        evidence = current.get("brandEvidence", []) + signal.get("brandEvidence", [])
        if evidence:
            current["brandEvidence"] = list(dict.fromkeys(evidence))
        reason_codes = current.get("reasonCodes", []) + signal.get("reasonCodes", [])
        if reason_codes:
            current["reasonCodes"] = normalize_reason_codes(reason_codes)
        discovered_via = current.get("discoveredVia", []) + signal.get("discoveredVia", [])
        if discovered_via:
            current["discoveredVia"] = list(dict.fromkeys(discovered_via))
        corroborated_by = current.get("corroboratedBy", []) + signal.get("corroboratedBy", [])
        if "URLScan" in current["sources"] and len(current["sources"]) > 1:
            corroborated_by.append("urlscan-public-report")
        if corroborated_by:
            current["corroboratedBy"] = list(dict.fromkeys(corroborated_by))
        current["matchScore"] = max(current["matchScore"], signal["matchScore"])
        current["confidence"] = current["matchScore"]
        if signal["reviewState"] == "needs-review":
            current["reviewState"] = "needs-review"
        current["evidenceTier"] = _evidence_tier(current)

    for signal in merged.values():
        signal["evidenceTier"] = _evidence_tier(signal)
        signal["confidence"] = signal["matchScore"]

    ordered = sorted(
        merged.values(),
        key=lambda signal: (
            -_date_value(signal["lastSeen"]).timestamp(),
            -_date_value(signal["firstSeen"]).timestamp(),
            signal["id"],
        ),
    )
    return ordered[:maximum]
