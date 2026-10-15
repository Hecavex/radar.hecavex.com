from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPMessage
from itertools import islice
from typing import IO, Any, cast
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .brand_assets import read_brand_asset_hunt_state
from .brands import load_brand_registry, score_domain
from .certstream_archive import read_recent_candidates
from .models import RadarSource, RawDomainIntelligence, RawSignal, SourceResult, SourceState
from .normalize import legacy_source_time_evidence, validate_source_time_evidence
from .provenance import reason_codes_from_evidence, reason_codes_from_match
from .safety import refang, safe_feed_url
from .urlscan import read_recent_urlscan, read_recent_urlscan_intelligence, read_urlscan_hunt_state

MAXIMUM_SOURCE_BYTES = 20 * 1024 * 1024
MAXIMUM_HECAVEX_RECORDS = 25_000


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    name: str
    homepage: str


SOURCE_DEFINITIONS = {
    "certstream": SourceDefinition("CertStream", "https://certstream.dev/"),
    "urlscan": SourceDefinition("URLScan", "https://urlscan.io/"),
    "hecavex": SourceDefinition("HECAVEX", "https://hecavex.com/"),
}
SOURCE_NAMES = frozenset(definition.name for definition in SOURCE_DEFINITIONS.values())


def _source(
    definition: SourceDefinition,
    *,
    fetched_at: str | None,
    records: int,
    state: SourceState,
    note: str | None,
) -> RadarSource:
    return {
        "name": definition.name,
        "homepage": definition.homepage,
        "fetchedAt": fetched_at,
        "records": records,
        "state": state,
        "note": note,
    }


def skipped_sources() -> list[RadarSource]:
    return [
        _source(definition, fetched_at=None, records=0, state="skipped", note="Not configured")
        for definition in SOURCE_DEFINITIONS.values()
    ]


class _SameHostRedirectHandler(HTTPRedirectHandler):
    def __init__(self, hostname: str) -> None:
        self._hostname = hostname
        super().__init__()

    def redirect_request(
        self,
        request: Request,
        file_pointer: IO[bytes],
        code: int,
        message: str,
        headers: HTTPMessage,
        new_url: str,
    ) -> Request | None:
        destination = urlsplit(urljoin(request.full_url, new_url))
        if (
            code not in {301, 302, 303, 307, 308}
            or destination.scheme != "https"
            or destination.hostname != self._hostname
            or destination.username is not None
            or destination.password is not None
            or destination.port is not None
        ):
            raise HTTPError(request.full_url, code, "Source returned an unapproved redirect.", headers, file_pointer)
        return super().redirect_request(request, file_pointer, code, message, headers, destination.geturl())


def fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    safe_url = safe_feed_url(url)
    parsed = urlsplit(safe_url)
    if not parsed.hostname or parsed.port is not None:
        raise ValueError("Source URL must use a hostname and the default HTTPS port.")
    opener = build_opener(_SameHostRedirectHandler(parsed.hostname))
    request = Request(safe_url, headers=headers or {}, method="GET")  # noqa: S310 - scheme/host are enforced above
    try:
        with opener.open(request, timeout=45) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAXIMUM_SOURCE_BYTES:
                raise ValueError("Source response exceeds 20 MiB.")
            body = response.read(MAXIMUM_SOURCE_BYTES + 1)
    except HTTPError as error:
        raise ValueError(f"Source request failed with HTTP {error.code}.") from error
    if len(body) > MAXIMUM_SOURCE_BYTES:
        raise ValueError("Source response exceeds 20 MiB.")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Source returned invalid JSON.") from error


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return float(value)
    except OverflowError:
        return None


def _first_number(*values: object) -> float | None:
    return next((number for value in values if (number := _number(value)) is not None), None)


def load_certstream(now: str, archive_root: str, lookback_days: int) -> SourceResult:
    candidates = read_recent_candidates(
        archive_root,
        lookback_days,
        datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    registry = load_brand_registry()
    signals: list[RawSignal] = []
    intelligence: list[RawDomainIntelligence] = []
    for candidate in candidates:
        match = score_domain(candidate["domain"].replace("[.]", "."), registry)
        if match is None:
            continue
        signals.append(
            RawSignal(
                url=match.domain,
                first_seen=candidate["observedAt"],
                last_seen=candidate["observedAt"],
                source="CertStream",
                status="suspected",
                brand=match.brand,
                confidence=match.confidence,
                reason_codes=reason_codes_from_match(match.reasons),
                discovered_via=[candidate.get("collectionMethod", "certstream-live")],
                source_time_evidence=(candidate.get("sourceTimeEvidence") or legacy_source_time_evidence(
                    candidate["observedAt"], candidate["observedAt"], "CertStream",
                )),
            )
        )
        certificate = candidate.get("certificate")
        if certificate is not None:
            intelligence.append(
                RawDomainIntelligence(
                    domain=match.domain,
                    source="CertStream",
                    observed_at=candidate["observedAt"],
                    certificate=dict(certificate),
                )
            )
    suffix = "" if lookback_days == 1 else "s"
    suppressed = len(candidates) - len(signals)
    note = f"Open heuristic candidates from the last {lookback_days} day{suffix}"
    if suppressed:
        note += f"; {suppressed} candidate{'s' if suppressed != 1 else ''} no longer passed current registry rules"
    return SourceResult(
        source=_source(
            SOURCE_DEFINITIONS["certstream"],
            fetched_at=now,
            records=len(signals),
            state="healthy",
            note=note,
        ),
        signals=signals,
        intelligence=intelligence,
    )


def load_urlscan(now: str, archive_root: str, lookback_days: int) -> SourceResult:
    observed_at = datetime.fromisoformat(now.replace("Z", "+00:00"))
    archived = read_recent_urlscan(archive_root, lookback_days, observed_at)
    intelligence = read_recent_urlscan_intelligence(archive_root, lookback_days, observed_at)
    hunt_state = read_urlscan_hunt_state(archive_root)
    asset_state = read_brand_asset_hunt_state(archive_root, observed_at)
    signals = [
        RawSignal(
            url=refang(signal["url"]),
            first_seen=signal["firstSeen"],
            last_seen=signal["lastSeen"],
            source="URLScan",
            status=signal["status"],
            brand=signal["brand"],
            country=signal["country"],
            host=signal["host"],
            screenshot_url=signal["screenshotUrl"],
            reference_url=signal.get("referenceUrl"),
            hashes=signal.get("hashes"),
            confidence=signal["confidence"],
            reason_codes=reason_codes_from_evidence(signal.get("brandEvidence", [])),
            discovered_via=["urlscan-public-report"],
            source_time_evidence=(
                validate_source_time_evidence(cast(dict[str, Any], signal)["sourceTimeEvidence"],
                                              first_seen=signal["firstSeen"], last_seen=signal["lastSeen"],
                                              source="URLScan")
                if "sourceTimeEvidence" in signal
                else legacy_source_time_evidence(signal["firstSeen"], signal["lastSeen"], "URLScan")
            ),
        )
        for signal in archived
    ]
    suffix = "" if lookback_days == 1 else "s"
    if hunt_state is None:
        state: SourceState = "partial" if signals else "skipped"
        note = f"Validated passive archive from the last {lookback_days} day{suffix}; hunt state is unavailable"
        fetched_at = None
    else:
        outcome = hunt_state["lastOutcome"]
        fetched_at = hunt_state["lastRunAt"]
        if outcome == "skipped-not-configured":
            state = "skipped"
            note = (
                f"Validated passive archive from the last {lookback_days} day{suffix}; "
                "URLScan API key is not configured"
            )
        elif outcome == "failed":
            state = "partial"
            note = (
                f"Validated passive archive from the last {lookback_days} day{suffix}; the latest passive hunt failed"
            )
        elif outcome == "budget-limited":
            state = "partial"
            note = (
                f"Validated passive archive from the last {lookback_days} day{suffix}; "
                "the latest hunt reached a configured request budget"
            )
        else:
            state = "healthy"
            note = (
                f"Passive public results validated from the last {lookback_days} day{suffix}; "
                "the latest scheduled hunt completed"
            )
    if asset_state is None:
        if state == "healthy":
            state = "partial"
        note += "; official-asset pivot state is unavailable"
    else:
        asset_outcome = asset_state["lastOutcome"]
        if asset_outcome == "completed":
            note += f"; {asset_state['eligibleAssetCount']} stable official asset hashes are pivot-eligible"
        elif asset_outcome == "budget-limited":
            if state == "healthy":
                state = "partial"
            note += "; the latest official-asset pivot reached its request budget"
        elif asset_outcome == "failed":
            if state == "healthy":
                state = "partial"
            note += "; the latest official-asset pivot failed"
        else:
            if state == "healthy":
                state = "partial"
            note += "; the official-asset pivot key is not configured"
    return SourceResult(
        source=_source(
            SOURCE_DEFINITIONS["urlscan"],
            fetched_at=fetched_at,
            records=len(signals),
            state=state,
            note=note,
        ),
        signals=signals,
        intelligence=intelligence,
    )


def _hecavex_signals(payload: Any) -> Iterable[Any]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("signals"), list):
        values = payload["signals"]
    else:
        raise ValueError("HECAVEX export returned an unexpected payload.")
    return islice(values, MAXIMUM_HECAVEX_RECORDS)


def _primary_html_hashes(value: dict[str, Any]) -> list[str] | None:
    hashes = value.get("hashes")
    if value.get("hashType") != "primary-html-sha256" or not isinstance(hashes, list):
        return None
    return [digest for digest in hashes if isinstance(digest, str)]


def _provider_time(value: dict[str, Any], primary: str, alternate: str) -> str | None:
    # Preserve the raw provider string, including invalid/empty values, until
    # the shared clock resolver records the actual fallback reason.
    primary_value = value.get(primary)
    raw = primary_value if isinstance(primary_value, str) else value.get(alternate)
    return raw if isinstance(raw, str) else None


def fetch_hecavex(now: str, source_url: str, token: str | None = None) -> SourceResult:
    headers = {"Accept": "application/json", "User-Agent": "hecavex-radar/0.1"}
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    payload = fetch_json(source_url, headers)
    signals: list[RawSignal] = []
    for value in _hecavex_signals(payload):
        if not isinstance(value, dict):
            continue
        url = _string(value.get("url")) or _string(value.get("indicator")) or _string(value.get("domain"))
        if not url:
            continue
        signals.append(
            RawSignal(
                url=url,
                first_seen=_provider_time(value, "firstSeen", "first_seen"),
                last_seen=_provider_time(value, "lastSeen", "last_seen"),
                source="HECAVEX",
                status=_string(value.get("status")),
                brand=_string(value.get("brand"))
                or _string(value.get("brandTargeted"))
                or _string(value.get("brand_targeted")),
                country=_string(value.get("country")),
                host=_string(value.get("host")) or _string(value.get("hosting")),
                screenshot_url=_string(value.get("screenshotUrl")) or _string(value.get("screenshot_url")),
                reference_url=_string(value.get("referenceUrl")) or _string(value.get("reference_url")),
                hashes=_primary_html_hashes(value),
                confidence=_first_number(
                    value.get("confidence"), value.get("confidenceScore"), value.get("confidence_score")
                ),
                reason_codes=["hecavex-public-export"],
                discovered_via=["hecavex-public-export"],
            )
        )
    return SourceResult(
        source=_source(
            SOURCE_DEFINITIONS["hecavex"],
            fetched_at=now,
            records=len(signals),
            state="healthy",
            note="Configured HECAVEX source",
        ),
        signals=signals,
    )
