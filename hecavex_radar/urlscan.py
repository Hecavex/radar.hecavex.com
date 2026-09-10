from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from .brands import (
    BrandRegistry,
    _canonical,
    is_brand_collision,
    is_suppressed_domain,
    load_brand_registry,
    match_brand_text,
    normalize_domain,
    resolve_brand_name,
    score_domain,
)
from .certstream_archive import read_recent_candidates, vilnius_date
from .models import BrandEvidence, CandidateMatch, RadarSignal, RawDomainIntelligence, RawSignal
from .normalize import merge_signals, prepare_signal
from .safety import parse_and_defang_url, refang, safe_reference_url, safe_screenshot_url, stable_id
from .seeds import IntelligenceSeed, load_intelligence_seeds
from .signal_detail import archive_record, raw_from_archive_record
from .urlscan_checkpoint import CheckpointCapacityError, SearchCheckpointStore, SearchUnavailable

API_ROOT = "https://urlscan.io"
SEARCH_ENDPOINT = f"{API_ROOT}/api/v1/search/"
RESULT_ENDPOINT = f"{API_ROOT}/api/v1/result"
SHA256 = re.compile(r"^[a-f\d]{64}$", re.IGNORECASE)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
UTC_MILLISECOND_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
BRAND_EVIDENCE_VALUES: frozenset[BrandEvidence] = frozenset({"domain", "title", "verdict", "primary-html-sha256"})
URLSCAN_ARCHIVE_FIELDS = frozenset(
    {
        "schemaVersion",
        "hashType",
        "brandEvidence",
        "id",
        "url",
        "domain",
        "firstSeen",
        "lastSeen",
        "sources",
        "status",
        "brand",
        "country",
        "host",
        "screenshotUrl",
        "referenceUrl",
        "hashes",
        "confidence",
    }
)
MAXIMUM_RESPONSE_BYTES = 20 * 1024 * 1024
MAXIMUM_DAILY_RECORDS = 2_500
MAXIMUM_ARCHIVE_BYTES = 20 * 1024 * 1024
MAXIMUM_ARCHIVE_OBSERVATION_AGE = timedelta(days=91)
MAXIMUM_TIMESTAMP_FUTURE_SKEW = timedelta(minutes=5)
MAXIMUM_HUNT_STATE_BYTES = 32 * 1024
MAXIMUM_RADAR_SNAPSHOT_BYTES = 512 * 1024
PROVIDER_DAILY_SEARCH_LIMIT = 1_000
PROVIDER_DAILY_RESULT_LIMIT = 10_000
PROVIDER_MINUTE_LIMIT = 120
HUNT_STATE_FIELDS = frozenset(
    {
        "schemaVersion",
        "dataset",
        "generatedAt",
        "configured",
        "budgetDay",
        "searchRequests",
        "resultRequests",
        "candidateCursor",
        "candidateCount",
        "selectedCandidates",
        "lastRunAt",
        "lastOutcome",
        "lastFailureCode",
        "lastSuccessAt",
        "consecutiveFailures",
        "degradedSince",
        "lastRunSearchRequests",
        "lastRunResultRequests",
        "checkpointCoverage",
    }
)
PRE_HEALTH_HUNT_STATE_FIELDS = HUNT_STATE_FIELDS - {
    "lastSuccessAt", "consecutiveFailures", "degradedSince", "lastFailureCode"
}
LEGACY_HUNT_STATE_FIELDS = PRE_HEALTH_HUNT_STATE_FIELDS - {"checkpointCoverage"}
HUNT_OUTCOMES = frozenset({"skipped-not-configured", "completed", "budget-limited", "failed"})
VILNIUS = ZoneInfo("Europe/Vilnius")

JsonRequester = Callable[[str, str], Any]


@dataclass(frozen=True, slots=True)
class _HuntSeed:
    domain: str
    brand: str
    confidence: int


@dataclass(slots=True)
class _HuntProgress:
    candidate_cursor: int = 0
    candidate_count: int = 0
    selected_candidates: int = 0


class _BudgetedRequester:
    """Keep one scheduled run inside conservative passive API request budgets."""

    def __init__(
        self,
        requester: JsonRequester,
        *,
        search_used: int,
        result_used: int,
        daily_search_cap: int,
        daily_result_cap: int,
        run_search_cap: int,
        run_result_cap: int,
    ) -> None:
        self._requester = requester
        self.search_used = search_used
        self.result_used = result_used
        self.daily_search_cap = daily_search_cap
        self.daily_result_cap = daily_result_cap
        self.run_search_cap = run_search_cap
        self.run_result_cap = run_result_cap
        self.run_search_requests = 0
        self.run_result_requests = 0
        self.exhausted = False
        self.provider_exhausted = False

    @staticmethod
    def _kind(url: str) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "urlscan.io"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.fragment
        ):
            raise ValueError("URLScan requests must stay on https://urlscan.io.")
        if parsed.path == "/api/v1/search/":
            return "search"
        if re.fullmatch(r"/api/v1/result/[0-9a-f-]{36}/", parsed.path, re.IGNORECASE):
            identifier = parsed.path.split("/")[4]
            if UUID.fullmatch(identifier) and not parsed.query:
                return "result"
        raise ValueError("Only passive URLScan search and result retrieval are allowed.")

    def __call__(self, url: str, api_key: str) -> Any:
        kind = self._kind(url)
        if self.provider_exhausted:
            raise _URLScanRateLimitError(
                "URLScan request was not performed after provider rate limiting."
            )
        if kind == "search":
            if self.search_used >= self.daily_search_cap or self.run_search_requests >= self.run_search_cap:
                self.exhausted = True
                raise SearchUnavailable("URLScan search was not performed after budget exhaustion.")
        elif self.result_used >= self.daily_result_cap or self.run_result_requests >= self.run_result_cap:
            self.exhausted = True
            return {}

        # URLScan quotas count an attempted HTTP request, not only a response
        # that our parser accepts. Reserve the local budget before sending so
        # transient HTTP, transport, and validation failures cannot make a run
        # under-report or exceed its configured allowance.
        self._count(kind)
        try:
            payload = self._requester(url, api_key)
        except _URLScanRateLimitError:
            # A local cap is a controlled, successful partial run. A provider
            # rate-limit response is different: the provider did not permit
            # the bounded work to finish, so the run must remain degraded and
            # must not refresh lastSuccessAt or advance a search checkpoint.
            self.provider_exhausted = True
            raise
        return payload

    def _count(self, kind: str) -> None:
        if kind == "search":
            self.search_used += 1
            self.run_search_requests += 1
        else:
            self.result_used += 1
            self.run_result_requests += 1


@dataclass(frozen=True, slots=True)
class _ScanVerdict:
    malicious: bool
    phishing: bool
    score: int


@dataclass(frozen=True, slots=True)
class _BrandEvidence:
    domain: bool
    title: bool
    verdict: bool
    conflicting: bool

    @property
    def any(self) -> bool:
        return self.domain or self.title or self.verdict

    @property
    def labels(self) -> list[BrandEvidence]:
        labels: list[BrandEvidence] = []
        if self.domain:
            labels.append("domain")
        if self.title:
            labels.append("title")
        if self.verdict:
            labels.append("verdict")
        return labels


class _URLScanFatalError(RuntimeError):
    pass


class _URLScanRateLimitError(_URLScanFatalError):
    pass


class _URLScanAccessError(_URLScanFatalError):
    pass


def _bounded(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() == "true"


class _UrlscanRedirectHandler(HTTPRedirectHandler):
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
            or destination.hostname != "urlscan.io"
            or destination.username is not None
            or destination.password is not None
            or destination.port is not None
        ):
            raise HTTPError(
                request.full_url,
                code,
                "URLScan returned an unapproved redirect.",
                headers,
                file_pointer,
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            destination.geturl(),
        )


def _rate_limit_headers_exhausted(headers: HTTPMessage) -> bool:
    """Recognize a zero remaining value without relying on one header layout."""
    for name, value in headers.items():
        lowered = name.lower()
        if lowered.startswith("x-rate-limit") and "remaining" in lowered:
            numbers = [int(number) for number in re.findall(r"(?<!\d)\d+(?!\d)", value)]
            if numbers and 0 in numbers:
                return True
    return False


def _request_json(url: str, api_key: str) -> Any:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "urlscan.io"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise ValueError("URLScan requests must stay on https://urlscan.io.")
    request = Request(  # noqa: S310 - URL is checked against the fixed HTTPS origin above
        url,
        headers={"Accept": "application/json", "api-key": api_key, "User-Agent": "hecavex-radar/0.1"},
    )
    opener = build_opener(_UrlscanRedirectHandler())
    try:
        with opener.open(  # noqa: S310 - initial URL and redirects use one fixed HTTPS origin
            request,
            timeout=45,
        ) as response:
            body = response.read(MAXIMUM_RESPONSE_BYTES + 1)
            rate_limit_exhausted = _rate_limit_headers_exhausted(response.headers)
    except HTTPError as error:
        if error.code == 429:
            raise _URLScanRateLimitError("URLScan rate limit reached (HTTP 429).") from error
        if error.code in {401, 403}:
            raise _URLScanAccessError(
                f"URLScan API authentication or authorization failed (HTTP {error.code})."
            ) from error
        raise RuntimeError(f"URLScan returned HTTP {error.code}.") from error
    except URLError as error:
        raise RuntimeError("URLScan request failed.") from error
    except TimeoutError as error:
        # Body reads can raise a bare socket timeout rather than URLError.
        # Keep optional result retrieval on the existing transient-error path;
        # search failures still abort without advancing durable checkpoints.
        raise RuntimeError("URLScan request timed out.") from error
    if len(body) > MAXIMUM_RESPONSE_BYTES:
        raise ValueError("URLScan response exceeds 20 MiB.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("URLScan returned invalid JSON.") from error
    if rate_limit_exhausted:
        raise _URLScanRateLimitError("URLScan response reported an exhausted request window.")
    return payload


def _dictionary(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _search_terms(registry: BrandRegistry) -> list[str]:
    terms: set[str] = set()
    for entry in registry.entries:
        for alias in entry.aliases:
            term = _canonical(alias)
            if 5 <= len(term) <= 40:
                terms.add(term)
        for domain in entry.official_domains:
            label = domain.split(".", 1)[0]
            term = _canonical(label)
            if 5 <= len(term) <= 40:
                terms.add(term)
    return sorted(terms)


def _public_search_query(expression: str, lookback_days: int) -> str:
    return f"date:>now-{lookback_days}d AND task.visibility:public AND ({expression})"


def build_domain_query(registry: BrandRegistry, lookback_days: int) -> str:
    alternatives = " OR ".join(f"*{term}*" for term in _search_terms(registry))
    return _public_search_query(
        f"task.domain.keyword:({alternatives}) OR page.domain.keyword:({alternatives})",
        lookback_days,
    )


def build_title_query(registry: BrandRegistry, lookback_days: int) -> str:
    alternatives = " OR ".join(f"*{term}*" for term in _search_terms(registry))
    return _public_search_query(f"page.title.keyword:({alternatives})", lookback_days)


def build_exact_domain_query(domains: list[str], lookback_days: int) -> str:
    normalized = list(dict.fromkeys(domain for value in domains if (domain := normalize_domain(value)) is not None))
    if not normalized:
        raise ValueError("An exact-domain URLScan query requires at least one valid domain.")
    alternatives = " OR ".join(
        clause
        for domain in normalized
        for clause in (f'task.domain.keyword:"{domain}"', f'page.domain.keyword:"{domain}"')
    )
    return _public_search_query(alternatives, lookback_days)


def _is_public_scan(value: dict[str, Any]) -> bool:
    return _dictionary(value.get("task")).get("visibility") == "public"


def _search(
    query: str,
    size: int,
    api_key: str,
    requester: JsonRequester,
    checkpoints: SearchCheckpointStore | None = None,
) -> list[dict[str, Any]]:
    if "task.visibility:public" not in query:
        raise ValueError("URLScan searches must be restricted to public scans.")
    if checkpoints is not None:
        backlog_pages = _bounded(os.environ.get("URLSCAN_BACKLOG_PAGES_PER_SEARCH"), 1, 0, 4)
        return checkpoints.search(
            query,
            size,
            api_key,
            requester,
            backlog_pages=backlog_pages,
        )
    url = f"{SEARCH_ENDPOINT}?{urlencode({'q': query, 'size': size, 'datasource': 'scans'})}"
    try:
        payload = requester(url, api_key)
    except SearchUnavailable:
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("URLScan search returned an unexpected payload.")
    return [
        cast(dict[str, Any], item) for item in payload["results"] if isinstance(item, dict) and _is_public_scan(item)
    ]


def _scan_uuid(result: dict[str, Any]) -> str | None:
    task = _dictionary(result.get("task"))
    candidate = _string(result.get("_id")) or _string(task.get("uuid"))
    return candidate.lower() if candidate and UUID.fullmatch(candidate) else None


def _result_detail(uuid: str, api_key: str, requester: JsonRequester) -> dict[str, Any]:
    payload = requester(f"{RESULT_ENDPOINT}/{uuid}/", api_key)
    if not isinstance(payload, dict):
        raise ValueError("URLScan result returned an unexpected payload.")
    return cast(dict[str, Any], payload)


def _result_urls(result: dict[str, Any]) -> list[str]:
    task = _dictionary(result.get("task"))
    page = _dictionary(result.get("page"))
    values = [_string(task.get("url")), _string(page.get("url"))]
    return list(dict.fromkeys(value for value in values if value))


def _page_url(result: dict[str, Any]) -> str | None:
    return _string(_dictionary(result.get("page")).get("url")) or _string(_dictionary(result.get("task")).get("url"))


def _candidate_scan_url(
    summary: dict[str, Any],
    detail: dict[str, Any],
    registry: BrandRegistry,
) -> str | None:
    """Prefer the submitted non-official URL over a redirected final page."""
    values = [
        _string(_dictionary(detail.get("task")).get("url")),
        _string(_dictionary(summary.get("task")).get("url")),
        _string(_dictionary(detail.get("page")).get("url")),
        _string(_dictionary(summary.get("page")).get("url")),
    ]
    return next(
        (
            value
            for value in values
            if value
            and (hostname := _hostname(value)) is not None
            and not _official(hostname, registry)
        ),
        None,
    )


def _hostname(value: str) -> str | None:
    candidate = refang(value)
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        return urlsplit(candidate).hostname
    except ValueError:
        return None


def _official(domain: str, registry: BrandRegistry) -> bool:
    return is_suppressed_domain(domain, registry)


def _verdict(detail: dict[str, Any]) -> _ScanVerdict:
    verdicts = _dictionary(detail.get("verdicts"))
    urlscan = _dictionary(verdicts.get("urlscan"))
    score_value = urlscan.get("score")
    score = score_value if isinstance(score_value, int) and not isinstance(score_value, bool) else 0
    categories_value = urlscan.get("categories")
    phishing = isinstance(categories_value, list) and any(
        isinstance(value, str) and value.strip().lower() == "phishing" for value in categories_value
    )
    malicious = urlscan.get("malicious") is True or score > 0 or phishing
    return _ScanVerdict(
        malicious=malicious,
        phishing=phishing,
        score=max(-100, min(100, score)),
    )


def _verdict_brand(detail: dict[str, Any], registry: BrandRegistry) -> str | None:
    urlscan = _dictionary(_dictionary(detail.get("verdicts")).get("urlscan"))
    brands = urlscan.get("brands")
    if not isinstance(brands, list):
        return None
    matched_brands: set[str] = set()
    for value in brands:
        if not isinstance(value, dict):
            continue
        name = _string(value.get("name"))
        matched = match_brand_text(name, registry)
        if matched:
            matched_brands.add(matched)
    return matched_brands.pop() if len(matched_brands) == 1 else None


def _primary_hashes(detail: dict[str, Any], registry: BrandRegistry) -> list[str]:
    page_url = _string(_dictionary(detail.get("page")).get("url"))
    page_host = _hostname(page_url) if page_url else None
    if not page_url or not page_host or _official(page_host, registry):
        return []
    requests = _dictionary(detail.get("data")).get("requests")
    if not isinstance(requests, list):
        return []
    matches: list[str] = []
    for value in requests:
        item = _dictionary(value)
        request_container = _dictionary(item.get("request"))
        request = _dictionary(request_container.get("request"))
        response = _dictionary(item.get("response"))
        metadata = _dictionary(response.get("response"))
        response_url = _string(metadata.get("url")) or _string(request.get("url"))
        digest = _string(response.get("hash"))
        mime = (_string(metadata.get("mimeType")) or "").lower()
        resource_type = (
            _string(item.get("type")) or _string(request_container.get("type")) or _string(request.get("type"))
        )
        status_value = metadata.get("status")
        if not isinstance(status_value, int) or isinstance(status_value, bool):
            status_value = response.get("status")
        status = status_value if isinstance(status_value, int) and not isinstance(status_value, bool) else 0
        size_value = metadata.get("encodedDataLength") or metadata.get("dataLength") or response.get("size")
        size = size_value if isinstance(size_value, int) and not isinstance(size_value, bool) else 0
        if (
            response_url == page_url
            and 200 <= status < 300
            and digest
            and SHA256.fullmatch(digest)
            and digest.lower() != EMPTY_SHA256
            and "html" in mime
            and (resource_type is None or resource_type.lower() == "document")
            and size >= 512
        ):
            matches.append(digest.lower())
    return list(dict.fromkeys(matches))[:2]


def _primary_certificate_sha256(detail: dict[str, Any]) -> str | None:
    """Return a bounded certificate identifier only for the primary document response."""

    page_url = _string(_dictionary(detail.get("page")).get("url"))
    requests = _dictionary(detail.get("data")).get("requests")
    if not page_url or not isinstance(requests, list):
        return None
    for value in requests:
        item = _dictionary(value)
        request_container = _dictionary(item.get("request"))
        request = _dictionary(request_container.get("request"))
        response = _dictionary(item.get("response"))
        metadata = _dictionary(response.get("response"))
        response_url = _string(metadata.get("url")) or _string(request.get("url"))
        resource_type = (
            _string(item.get("type"))
            or _string(request_container.get("type"))
            or _string(request.get("type"))
        )
        if response_url != page_url or (resource_type and resource_type.lower() != "document"):
            continue
        security = _dictionary(response.get("securityDetails")) or _dictionary(metadata.get("securityDetails"))
        raw = _string(security.get("certificateId")) or _string(security.get("sha256"))
        compact = re.sub(r"[\s:]", "", raw).lower() if raw else ""
        return compact if SHA256.fullmatch(compact) and compact != EMPTY_SHA256 else None
    return None


def _host_summary(page: dict[str, Any]) -> str | None:
    values = [_string(page.get("asn")), _string(page.get("asnname")), _string(page.get("ip"))]
    present = [value for value in values if value]
    return " · ".join(present) if present else None


def _http_status(value: object) -> int | None:
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599 else None


def _asn_context(detail: dict[str, Any], page: dict[str, Any]) -> tuple[object, object]:
    page_ip = _string(page.get("ip"))
    processor = _dictionary(_dictionary(detail.get("meta")).get("processors"))
    values = _dictionary(processor.get("asn")).get("data")
    if not isinstance(values, list):
        return (page.get("asnname"), None)
    for raw in values:
        item = _dictionary(raw)
        if page_ip and _string(item.get("ip")) not in {None, page_ip}:
            continue
        description = item.get("description") or item.get("name") or page.get("asnname")
        registry = item.get("registrar") or item.get("registry")
        return (description, registry)
    return (page.get("asnname"), None)


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _tls_not_after(valid_from: object, valid_days: object) -> str | None:
    if not isinstance(valid_from, str):
        return None
    try:
        parsed = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or not isinstance(valid_days, int)
        or isinstance(valid_days, bool)
        or not 0 <= valid_days <= 4_000
    ):
        return None
    return _timestamp(parsed + timedelta(days=valid_days))


def _intelligence_from_scan(
    summary: dict[str, Any],
    detail: dict[str, Any],
    matched_url: str,
    observed_at: str,
) -> RawDomainIntelligence | None:
    domain = _hostname(matched_url)
    if domain is None:
        return None
    page = {**_dictionary(summary.get("page")), **_dictionary(detail.get("page"))}
    page_domain = _hostname(_string(page.get("url")) or "")
    same_page_host = page_domain == domain
    description, registry = _asn_context(detail, page)
    urlscan_verdict = _dictionary(_dictionary(detail.get("verdicts")).get("urlscan"))
    raw_categories = urlscan_verdict.get("categories")
    categories = (
        [value for value in raw_categories if isinstance(value, str)] if isinstance(raw_categories, list) else []
    )
    valid_from = _string(page.get("tlsValidFrom"))
    certificate_sha256 = _primary_certificate_sha256(detail)
    return RawDomainIntelligence(
        domain=domain,
        source="URLScan",
        observed_at=observed_at,
        page={"title": page.get("title"), "httpStatus": _http_status(page.get("status"))} if same_page_host else None,
        network=(
            {
                "ipAddress": page.get("ip"),
                "asn": page.get("asn"),
                "asnDescription": description,
                "asnRegistry": registry,
            }
            if same_page_host
            else None
        ),
        assessment={
            "urlscanVerdictScore": urlscan_verdict.get("score"),
            "urlscanCategories": categories,
            "redirectedToDomain": page_domain if page_domain and page_domain != domain else None,
        },
        certificate=(
            {
                "issuer": page.get("tlsIssuer"),
                "notBefore": valid_from,
                "notAfter": _tls_not_after(valid_from, page.get("tlsValidDays")),
                "fingerprints": {"sha256": certificate_sha256},
            }
            if same_page_host
            else None
        ),
    )


def _signal_from_scan(
    summary: dict[str, Any],
    detail: dict[str, Any],
    matched_url: str,
    brand: str,
    base_confidence: int,
    now: datetime,
    registry: BrandRegistry,
    brand_evidence: _BrandEvidence,
    primary_hash_pivot: bool = False,
    intelligence_sink: list[RawDomainIntelligence] | None = None,
) -> RadarSignal | None:
    uuid = _scan_uuid(summary) or _scan_uuid(detail)
    if not uuid:
        return None
    page = {**_dictionary(summary.get("page")), **_dictionary(detail.get("page"))}
    task = {**_dictionary(summary.get("task")), **_dictionary(detail.get("task"))}
    matched_domain = _hostname(matched_url)
    page_domain = _hostname(_string(page.get("url")) or "")
    same_page_host = matched_domain is not None and page_domain == matched_domain
    verdict = _verdict(detail)
    confidence = base_confidence
    if verdict.phishing:
        confidence = max(confidence, min(99, 95 + max(0, verdict.score) // 25))
    elif verdict.malicious:
        confidence = max(confidence, min(90, 80 + max(0, verdict.score)))
    observed_at = _string(task.get("time")) or _timestamp(now)
    hashes = _primary_hashes(detail, registry)
    signal = prepare_signal(
        RawSignal(
            url=matched_url,
            first_seen=observed_at,
            last_seen=observed_at,
            source="URLScan",
            status="suspected",
            brand=brand,
            # URLScan's page object describes the final destination. When a
            # submitted candidate redirects elsewhere, do not attribute that
            # destination's network or screenshot evidence to the candidate.
            country=_string(page.get("country")) if same_page_host else None,
            host=_host_summary(page) if same_page_host else None,
            screenshot_url=f"{API_ROOT}/screenshots/{uuid}.png" if same_page_host else None,
            reference_url=f"{API_ROOT}/result/{uuid}/",
            hashes=hashes,
            confidence=confidence,
        ),
        _timestamp(now),
    )
    if signal is None:
        return None
    signal["brandEvidence"] = brand_evidence.labels
    if primary_hash_pivot:
        signal["brandEvidence"].append("primary-html-sha256")
    intelligence = _intelligence_from_scan(summary, detail, matched_url, observed_at)
    if intelligence is not None and intelligence_sink is not None:
        intelligence_sink.append(intelligence)
    return signal


def _summary_match(result: dict[str, Any], registry: BrandRegistry, minimum_confidence: int) -> CandidateMatch | None:
    matches: list[CandidateMatch] = []
    for value in _result_urls(result):
        hostname = _hostname(value)
        match = score_domain(hostname, registry) if hostname else None
        if match and match.confidence >= minimum_confidence:
            matches.append(match)
    if len({match.brand for match in matches}) != 1:
        return None
    return max(matches, key=lambda match: match.confidence)


def _matched_url(result: dict[str, Any], match: CandidateMatch) -> str:
    return next(
        (value for value in _result_urls(result) if (hostname := _hostname(value)) and hostname == match.domain),
        match.domain,
    )


def _safe_detail(result: dict[str, Any], api_key: str, requester: JsonRequester) -> tuple[str, dict[str, Any]] | None:
    uuid = _scan_uuid(result)
    if not uuid or not _is_public_scan(result):
        return None
    try:
        detail = _result_detail(uuid, api_key, requester)
    except _URLScanFatalError:
        raise
    except (RuntimeError, ValueError):
        return None
    return (uuid, detail) if _is_public_scan(detail) else None


def _title(result: dict[str, Any], detail: dict[str, Any]) -> str | None:
    return _string(_dictionary(detail.get("page")).get("title")) or _string(
        _dictionary(result.get("page")).get("title")
    )


def _brand_evidence(
    result: dict[str, Any],
    detail: dict[str, Any],
    brand: str,
    registry: BrandRegistry,
    *,
    matched_url: str | None = None,
) -> _BrandEvidence:
    candidate_urls = [matched_url] if matched_url is not None else [*_result_urls(result), *_result_urls(detail)]
    domain_brands = {
        match.brand
        for value in candidate_urls
        if (hostname := _hostname(value)) is not None and (match := score_domain(hostname, registry)) is not None
    }
    title_brand = match_brand_text(_title(result, detail), registry)
    verdict_brand = _verdict_brand(detail, registry)
    observed_brands = set(domain_brands)
    if title_brand:
        observed_brands.add(title_brand)
    if verdict_brand:
        observed_brands.add(verdict_brand)
    return _BrandEvidence(
        domain=brand in domain_brands,
        title=title_brand == brand,
        verdict=verdict_brand == brand,
        conflicting=any(observed != brand for observed in observed_brands),
    )


def _merge_hunt_seeds(seeds: list[_HuntSeed], maximum: int) -> list[_HuntSeed]:
    combined: dict[tuple[str, str], _HuntSeed] = {}
    brands_by_domain: dict[str, set[str]] = {}
    for seed in seeds:
        domain = normalize_domain(seed.domain)
        if not domain:
            continue
        brands_by_domain.setdefault(domain, set()).add(seed.brand)
        key = (domain, seed.brand)
        current = combined.get(key)
        if current is None:
            combined[key] = _HuntSeed(
                domain=domain,
                brand=seed.brand,
                confidence=seed.confidence,
            )
            continue
        combined[key] = _HuntSeed(
            domain=domain,
            brand=seed.brand,
            confidence=max(current.confidence, seed.confidence),
        )
    unambiguous = [seed for seed in combined.values() if len(brands_by_domain.get(seed.domain, set())) == 1]
    return sorted(unambiguous, key=lambda seed: (-seed.confidence, seed.domain, seed.brand))[:maximum]


def _within_rolling_window(value: object, now: datetime, lookback_days: int) -> bool:
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        return False
    reference = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(UTC)
    observed_utc = observed.astimezone(UTC)
    return reference - timedelta(days=lookback_days) <= observed_utc <= (reference + MAXIMUM_TIMESTAMP_FUTURE_SKEW)


def _repository_file(value: str | Path, variable: str) -> Path:
    repository = Path.cwd().resolve()
    target = (repository / value).resolve()
    if target == repository or not target.is_relative_to(repository):
        raise ValueError(f"{variable} must stay inside the repository.")
    return target


def _load_radar_snapshot_seeds(
    registry: BrandRegistry,
    now: datetime,
    lookback_days: int,
) -> list[_HuntSeed]:
    if not _enabled("URLSCAN_RADAR_SEEDS_ENABLED", default=True):
        return []
    path_value = os.environ.get("URLSCAN_RADAR_SNAPSHOT", "").strip() or "public/data/radar.json"
    path = _repository_file(path_value, "URLSCAN_RADAR_SNAPSHOT")
    try:
        if path.stat().st_size > MAXIMUM_RADAR_SNAPSHOT_BYTES:
            raise ValueError("Radar snapshot exceeds 512 KiB.")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ValueError("Radar snapshot contains invalid JSON.") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 2
        or payload.get("dataset") != "live"
        or not isinstance(payload.get("signals"), list)
    ):
        raise ValueError("Radar snapshot has an unexpected contract.")

    minimum = _bounded(os.environ.get("URLSCAN_MIN_CONFIDENCE"), 80, 50, 100)
    limit = _bounded(os.environ.get("URLSCAN_RADAR_SEED_LIMIT"), 250, 0, 1_000)
    seeds: list[_HuntSeed] = []
    for value in payload["signals"]:
        if len(seeds) >= limit:
            break
        if not isinstance(value, dict) or not _within_rolling_window(value.get("lastSeen"), now, lookback_days):
            continue
        domain_value = value.get("domain")
        brand_value = value.get("brand")
        confidence = value.get("confidence")
        domain = normalize_domain(refang(domain_value)) if isinstance(domain_value, str) else None
        brand = resolve_brand_name(brand_value, registry) if isinstance(brand_value, str) else None
        if (
            not domain
            or not brand
            or isinstance(confidence, bool)
            or not isinstance(confidence, int)
            or confidence < minimum
            or is_suppressed_domain(domain, registry)
            or is_brand_collision(domain, brand, registry)
        ):
            continue
        current_match = score_domain(domain, registry)
        if current_match is not None and current_match.brand != brand:
            continue
        seeds.append(_HuntSeed(domain=domain, brand=brand, confidence=confidence))
    return seeds


def _load_hunt_seeds(registry: BrandRegistry, now: datetime) -> list[_HuntSeed]:
    seeds: list[_HuntSeed] = []
    lookback = _bounded(os.environ.get("URLSCAN_LOOKBACK_DAYS"), 7, 1, 90)
    seeds.extend(_load_radar_snapshot_seeds(registry, now, lookback))
    if _enabled("URLSCAN_CT_SEEDS_ENABLED", default=True):
        ct_lookback = _bounded(os.environ.get("URLSCAN_CT_LOOKBACK_DAYS"), lookback, 1, 90)
        limit = _bounded(os.environ.get("URLSCAN_CT_SEED_LIMIT"), 100, 0, 1_000)
        minimum = _bounded(os.environ.get("URLSCAN_CT_SEED_MIN_CONFIDENCE"), 80, 50, 100)
        archive_root = os.environ.get("URLSCAN_CT_ARCHIVE_ROOT", "").strip() or "data/certstream"
        candidates = read_recent_candidates(archive_root, ct_lookback, now, maximum=max(1, limit)) if limit else []
        for candidate in candidates:
            if not _within_rolling_window(candidate.get("observedAt"), now, ct_lookback):
                continue
            domain = normalize_domain(refang(candidate["domain"]))
            match = score_domain(domain, registry) if domain else None
            if match and match.confidence >= minimum:
                seeds.append(
                    _HuntSeed(
                        domain=match.domain,
                        brand=match.brand,
                        confidence=match.confidence,
                    )
                )

    if _enabled("URLSCAN_INTELLIGENCE_SEEDS_ENABLED", default=True):
        intelligence = load_intelligence_seeds(registry)
        seeds.extend(
            _HuntSeed(
                domain=seed.domain,
                brand=seed.brand,
                confidence=seed.confidence,
            )
            for seed in intelligence.seeds
            if isinstance(seed, IntelligenceSeed)
        )

    maximum = _bounded(os.environ.get("URLSCAN_EXACT_SEED_LIMIT"), 250, 0, 1_000)
    return _merge_hunt_seeds(seeds, maximum)


def _rotating_seed_window(
    seeds: list[_HuntSeed],
    cursor: int,
    shards: int,
    maximum: int,
) -> tuple[list[_HuntSeed], int]:
    if not seeds or maximum <= 0:
        return [], 0
    start = max(0, cursor) % len(seeds)
    per_shard = max(1, (len(seeds) + max(1, shards) - 1) // max(1, shards))
    count = min(len(seeds), maximum, per_shard)
    selected = [seeds[(start + offset) % len(seeds)] for offset in range(count)]
    return selected, (start + count) % len(seeds)


def _seed_for_result(result: dict[str, Any], seeds_by_domain: dict[str, _HuntSeed]) -> _HuntSeed | None:
    matches = {
        seed
        for value in _result_urls(result)
        if (hostname := _hostname(value)) is not None and (seed := seeds_by_domain.get(hostname)) is not None
    }
    brands = {seed.brand for seed in matches}
    if len(brands) != 1:
        return None
    return max(matches, key=lambda seed: (seed.confidence, seed.domain))


def _seed_url(summary: dict[str, Any], detail: dict[str, Any], seed: _HuntSeed) -> str | None:
    task_values = [
        _string(_dictionary(detail.get("task")).get("url")),
        _string(_dictionary(summary.get("task")).get("url")),
    ]
    page_values = [
        _string(_dictionary(detail.get("page")).get("url")),
        _string(_dictionary(summary.get("page")).get("url")),
    ]
    return next(
        (value for value in [*task_values, *page_values] if value and _hostname(value) == seed.domain),
        None,
    )


def _chunks(values: list[_HuntSeed], size: int) -> list[list[_HuntSeed]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def hunt_urlscan(
    api_key: str,
    now: datetime,
    requester: JsonRequester = _request_json,
    registry: BrandRegistry | None = None,
    *,
    seed_cursor: int | None = None,
    seed_rotation_shards: int = 1,
    seeds_per_run: int = 1_000,
    progress: _HuntProgress | None = None,
    intelligence_sink: list[RawDomainIntelligence] | None = None,
    search_checkpoints: SearchCheckpointStore | None = None,
) -> list[RadarSignal]:
    """Passively hunt existing URLScan results for reviewed Lithuanian targets."""
    if not api_key.strip():
        raise ValueError("URLSCAN_API_KEY is required.")
    brand_registry = registry or load_brand_registry()
    lookback = _bounded(os.environ.get("URLSCAN_LOOKBACK_DAYS"), 7, 1, 90)
    minimum = _bounded(os.environ.get("URLSCAN_MIN_CONFIDENCE"), 80, 50, 100)
    search_limit = _bounded(os.environ.get("URLSCAN_SEARCH_LIMIT"), 100, 1, 1_000)
    detail_limit = _bounded(os.environ.get("URLSCAN_DETAIL_LIMIT"), 30, 1, 200)
    title_limit = _bounded(os.environ.get("URLSCAN_TITLE_DETAIL_LIMIT"), 10, 0, 100)
    pivot_limit = _bounded(os.environ.get("URLSCAN_HASH_PIVOT_LIMIT"), 3, 0, 20)
    pivot_results = _bounded(os.environ.get("URLSCAN_HASH_RESULT_LIMIT"), 10, 1, 100)
    pivot_detail_limit = _bounded(os.environ.get("URLSCAN_HASH_DETAIL_LIMIT"), 30, 0, 200)
    seed_batch_size = _bounded(os.environ.get("URLSCAN_SEED_BATCH_SIZE"), 20, 1, 50)
    seed_search_limit = _bounded(os.environ.get("URLSCAN_SEED_SEARCH_LIMIT"), 50, 1, 200)
    seed_detail_limit = _bounded(os.environ.get("URLSCAN_SEED_DETAIL_LIMIT"), 30, 0, 200)
    maximum = _bounded(os.environ.get("URLSCAN_MAX_SIGNALS"), 500, 1, MAXIMUM_DAILY_RECORDS)

    signals: list[RadarSignal] = []
    processed: set[str] = set()
    hash_seeds: list[tuple[str, str]] = []
    all_exact_seeds = _load_hunt_seeds(brand_registry, now)
    if seed_cursor is None:
        exact_seeds = all_exact_seeds
        rotation_start = 0
    else:
        exact_seeds, _next_cursor = _rotating_seed_window(
            all_exact_seeds,
            seed_cursor,
            seed_rotation_shards,
            seeds_per_run,
        )
        rotation_start = max(0, seed_cursor) % len(all_exact_seeds) if all_exact_seeds else 0
    if progress is not None:
        progress.candidate_count = len(all_exact_seeds)
        progress.selected_candidates = len(exact_seeds)
        progress.candidate_cursor = rotation_start
    seed_details = 0
    queried_seed_count = 0

    for batch in _chunks(exact_seeds, seed_batch_size):
        if seed_details >= seed_detail_limit:
            break
        seeds_by_domain = {seed.domain: seed for seed in batch}
        query = build_exact_domain_query(list(seeds_by_domain), lookback)
        requests_before = getattr(requester, "run_search_requests", None)
        search_results = _search(query, seed_search_limit, api_key, requester, search_checkpoints)
        requests_after = getattr(requester, "run_search_requests", None)
        request_performed = requests_before is None or requests_after is None or requests_after > requests_before
        if request_performed and seed_cursor is not None:
            queried_seed_count += len(batch)
            if progress is not None and all_exact_seeds:
                progress.candidate_cursor = (rotation_start + queried_seed_count) % len(all_exact_seeds)
        for result in search_results:
            if seed_details >= seed_detail_limit:
                break
            uuid = _scan_uuid(result)
            seed = _seed_for_result(result, seeds_by_domain)
            if not uuid or uuid in processed or not seed or _official(seed.domain, brand_registry):
                continue
            fetched = _safe_detail(result, api_key, requester)
            if not fetched:
                continue
            processed.add(uuid)
            seed_details += 1
            _, detail = fetched
            matched_url = _seed_url(result, detail, seed)
            if not matched_url:
                continue
            evidence = _brand_evidence(
                result,
                detail,
                seed.brand,
                brand_registry,
                matched_url=matched_url,
            )
            if evidence.conflicting or not evidence.any:
                continue
            signal = _signal_from_scan(
                result,
                detail,
                matched_url,
                seed.brand,
                seed.confidence,
                now,
                brand_registry,
                evidence,
                intelligence_sink=intelligence_sink,
            )
            if signal:
                signals.append(signal)
                if evidence.title or evidence.verdict:
                    hash_seeds.extend((seed.brand, digest) for digest in _primary_hashes(detail, brand_registry))

    detail_count = 0

    for result in _search(
        build_domain_query(brand_registry, lookback),
        search_limit,
        api_key,
        requester,
        search_checkpoints,
    ):
        if detail_count >= detail_limit:
            break
        uuid = _scan_uuid(result)
        match = _summary_match(result, brand_registry, minimum)
        if not uuid or uuid in processed or not match:
            continue
        fetched = _safe_detail(result, api_key, requester)
        if not fetched:
            continue
        processed.add(uuid)
        detail_count += 1
        _, detail = fetched
        matched_url = _matched_url(result, match)
        evidence = _brand_evidence(
            result,
            detail,
            match.brand,
            brand_registry,
            matched_url=matched_url,
        )
        if evidence.conflicting or not evidence.domain:
            continue
        signal = _signal_from_scan(
            result,
            detail,
            matched_url,
            match.brand,
            match.confidence,
            now,
            brand_registry,
            evidence,
            intelligence_sink=intelligence_sink,
        )
        if signal:
            signals.append(signal)
            if evidence.title or evidence.verdict:
                hash_seeds.extend((match.brand, digest) for digest in _primary_hashes(detail, brand_registry))

    title_details = 0
    if title_limit:
        for result in _search(
            build_title_query(brand_registry, lookback),
            search_limit,
            api_key,
            requester,
            search_checkpoints,
        ):
            if title_details >= title_limit:
                break
            uuid = _scan_uuid(result)
            summary_page = _dictionary(result.get("page"))
            candidate_url = _candidate_scan_url(result, {}, brand_registry)
            hostname = _hostname(candidate_url or "")
            brand = match_brand_text(_string(summary_page.get("title")), brand_registry)
            if not uuid or uuid in processed or not hostname or not brand:
                continue
            fetched = _safe_detail(result, api_key, requester)
            if not fetched:
                continue
            processed.add(uuid)
            title_details += 1
            _, detail = fetched
            matched_url = _candidate_scan_url(result, detail, brand_registry)
            if matched_url is None:
                continue
            evidence = _brand_evidence(
                result,
                detail,
                brand,
                brand_registry,
                matched_url=matched_url,
            )
            verdict = _verdict(detail)
            if evidence.conflicting or not evidence.title or (not evidence.verdict and not verdict.phishing):
                continue
            signal = _signal_from_scan(
                result,
                detail,
                matched_url,
                brand,
                92,
                now,
                brand_registry,
                evidence,
                intelligence_sink=intelligence_sink,
            )
            if signal:
                signals.append(signal)
                hash_seeds.extend((brand, digest) for digest in _primary_hashes(detail, brand_registry))

    unique_seeds = list(dict.fromkeys(hash_seeds))[:pivot_limit]
    pivot_details = 0
    for brand, digest in unique_seeds:
        if pivot_details >= pivot_detail_limit:
            break
        query = _public_search_query(f"hash:{digest}", lookback)
        for result in _search(query, pivot_results, api_key, requester, search_checkpoints):
            if pivot_details >= pivot_detail_limit:
                break
            uuid = _scan_uuid(result)
            if not uuid or uuid in processed:
                continue
            candidate_url = _candidate_scan_url(result, {}, brand_registry)
            if candidate_url is None:
                continue
            fetched = _safe_detail(result, api_key, requester)
            if not fetched:
                continue
            processed.add(uuid)
            pivot_details += 1
            _, detail = fetched
            matched_url = _candidate_scan_url(result, detail, brand_registry)
            if matched_url is None:
                continue
            primary_hashes = _primary_hashes(detail, brand_registry)
            evidence = _brand_evidence(
                result,
                detail,
                brand,
                brand_registry,
                matched_url=matched_url,
            )
            if digest not in primary_hashes or evidence.conflicting or not evidence.any:
                continue
            signal = _signal_from_scan(
                result,
                detail,
                matched_url,
                brand,
                94,
                now,
                brand_registry,
                evidence,
                primary_hash_pivot=True,
                intelligence_sink=intelligence_sink,
            )
            if signal:
                signals.append(signal)

    return merge_signals(signals, maximum)


def _bounded_archive_root(value: str | Path) -> Path:
    repository = Path.cwd().resolve()
    root = (repository / value).resolve()
    if root == repository or not root.is_relative_to(repository):
        raise ValueError("URLSCAN_ARCHIVE_ROOT must stay inside the repository.")
    return root


def _valid_day(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _archive_path(root: str | Path, day: str) -> Path:
    if not _valid_day(day):
        raise ValueError("Invalid URLScan archive date.")
    return _bounded_archive_root(root) / day / "signals.ndjson"


def _intelligence_archive_path(root: str | Path, day: str) -> Path:
    if not _valid_day(day):
        raise ValueError("Invalid URLScan intelligence archive date.")
    return _bounded_archive_root(root) / day / "intelligence.ndjson"


def _archive_signal(
    value: Any,
    *,
    partition_day: date | None = None,
    reference_time: datetime | None = None,
) -> RadarSignal | None:
    if (
        not isinstance(value, dict)
        or not set(value).issubset(URLSCAN_ARCHIVE_FIELDS)
        or value.get("schemaVersion") != 2
        or value.get("hashType") != "primary-html-sha256"
    ):
        return None
    required_strings = ("id", "url", "domain", "firstSeen", "lastSeen")
    if not all(isinstance(value.get(field), str) for field in required_strings):
        return None
    identifier = value["id"]
    url = value["url"]
    domain = value["domain"]
    sources = value.get("sources")
    hashes = value.get("hashes", [])
    brand_evidence = value.get("brandEvidence")
    reference = value.get("referenceUrl")
    screenshot = value.get("screenshotUrl")
    confidence = value.get("confidence")
    parsed_url = parse_and_defang_url(url)
    if (
        not re.fullmatch(r"[a-f\d]{20}", identifier)
        or identifier != stable_id(domain.lower())
        or not url.startswith(("hxxp://", "hxxps://"))
        or "?" in url
        or "#" in url
        or parsed_url is None
        or parsed_url.display_url != url
        or parsed_url.display_domain != domain
        or sources != ["URLScan"]
        or value.get("status") != "suspected"
        or isinstance(confidence, bool)
        or not isinstance(confidence, int)
        or not 0 <= confidence <= 100
        or not isinstance(hashes, list)
        or len(hashes) > 8
        or not all(
            isinstance(digest, str) and digest == digest.lower() and digest != EMPTY_SHA256 and SHA256.fullmatch(digest)
            for digest in hashes
        )
        or not isinstance(brand_evidence, list)
        or not 1 <= len(brand_evidence) <= len(BRAND_EVIDENCE_VALUES)
        or not all(isinstance(label, str) and label in BRAND_EVIDENCE_VALUES for label in brand_evidence)
        or len(set(brand_evidence)) != len(brand_evidence)
        or not {"domain", "title", "verdict"}.intersection(brand_evidence)
        or safe_reference_url(reference) != reference
        or safe_screenshot_url(screenshot) != screenshot
    ):
        return None
    if any(
        value.get(field) is not None and not isinstance(value.get(field), str) for field in ("brand", "country", "host")
    ):
        return None
    try:
        first_seen = datetime.fromisoformat(value["firstSeen"].replace("Z", "+00:00"))
        last_seen = datetime.fromisoformat(value["lastSeen"].replace("Z", "+00:00"))
    except ValueError:
        return None
    if (
        not UTC_MILLISECOND_TIMESTAMP.fullmatch(value["firstSeen"])
        or not UTC_MILLISECOND_TIMESTAMP.fullmatch(value["lastSeen"])
        or first_seen.tzinfo is None
        or last_seen.tzinfo is None
        or _timestamp(first_seen) != value["firstSeen"]
        or _timestamp(last_seen) != value["lastSeen"]
        or first_seen > last_seen
    ):
        return None
    first_seen_utc = first_seen.astimezone(UTC)
    last_seen_utc = last_seen.astimezone(UTC)
    if reference_time is not None:
        reference_utc = (
            reference_time if reference_time.tzinfo is not None else reference_time.replace(tzinfo=UTC)
        ).astimezone(UTC)
        if last_seen_utc > reference_utc + MAXIMUM_TIMESTAMP_FUTURE_SKEW:
            return None
    if partition_day is not None:
        partition_start = datetime.combine(partition_day, datetime.min.time(), tzinfo=VILNIUS)
        partition_end = partition_start + timedelta(days=1)
        if (
            first_seen_utc < partition_start.astimezone(UTC) - MAXIMUM_ARCHIVE_OBSERVATION_AGE
            or last_seen_utc > partition_end.astimezone(UTC) + MAXIMUM_TIMESTAMP_FUTURE_SKEW
        ):
            return None
    return cast(
        RadarSignal,
        {
            "id": stable_id(domain.lower()),
            "url": url,
            "domain": domain,
            "firstSeen": value["firstSeen"],
            "lastSeen": value["lastSeen"],
            "sources": ["URLScan"],
            "status": "suspected",
            "brand": value.get("brand"),
            "country": value.get("country"),
            "host": value.get("host"),
            "screenshotUrl": screenshot,
            "referenceUrl": reference,
            "hashes": hashes,
            "brandEvidence": [cast(BrandEvidence, label) for label in brand_evidence],
            "matchScore": confidence,
            "evidenceTier": (
                "corroborated"
                if {"title", "verdict", "primary-html-sha256"}.intersection(brand_evidence)
                else "name-only"
            ),
            "reviewState": "unreviewed",
            "ltRelevance": "lithuanian-brand-relevance",
            "confidence": confidence,
        },
    )


def read_urlscan_file(
    path: Path,
    maximum: int = MAXIMUM_DAILY_RECORDS,
    *,
    now: datetime | None = None,
    reviewer: Callable[[RadarSignal], bool] | None = None,
) -> list[RadarSignal]:
    try:
        if path.stat().st_size > MAXIMUM_ARCHIVE_BYTES:
            raise ValueError(f"URLScan archive exceeds 20 MiB: {path.relative_to(Path.cwd())}")
        body = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    partition_day = date.fromisoformat(path.parent.name) if _valid_day(path.parent.name) else None
    records: list[RadarSignal] = []
    for line in body.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        signal = _archive_signal(value, partition_day=partition_day, reference_time=now)
        if signal and (reviewer is None or reviewer(signal)):
            records.append(signal)
        if len(records) >= maximum:
            break
    return records


def _reviewed_archive_signal(signal: RadarSignal, registry: BrandRegistry) -> bool:
    hostname = _hostname(signal["domain"])
    brand = resolve_brand_name(signal["brand"], registry)
    if (
        not hostname
        or not brand
        or is_suppressed_domain(hostname, registry)
        or is_brand_collision(hostname, brand, registry)
    ):
        return False
    current_match = score_domain(hostname, registry)
    if current_match is not None:
        return current_match.brand == brand
    evidence = set(signal.get("brandEvidence", []))
    return bool(evidence.intersection({"title", "verdict"}))


def write_urlscan_archive(
    root: str | Path,
    signals: list[RadarSignal],
    now: datetime,
    registry: BrandRegistry | None = None,
) -> int:
    path = _archive_path(root, vilnius_date(now))
    brand_registry = registry or load_brand_registry()
    archived = read_urlscan_file(path, now=now)
    if not signals and not archived and not path.exists():
        return 0
    existing = [signal for signal in archived if _reviewed_archive_signal(signal, brand_registry)]
    partition_day = date.fromisoformat(path.parent.name)
    signals = [
        validated
        for signal in signals
        if (
            validated := _archive_signal(
                {"schemaVersion": 2, "hashType": "primary-html-sha256", **signal},
                partition_day=partition_day,
                reference_time=now,
            )
        )
        is not None
        and _reviewed_archive_signal(validated, brand_registry)
    ]
    existing_ids = {signal["id"] for signal in existing}
    merged = merge_signals(existing + signals, MAXIMUM_DAILY_RECORDS)
    lines = [
        json.dumps(
            {"schemaVersion": 2, "hashType": "primary-html-sha256", **signal},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for signal in merged
    ]
    body = "\n".join(lines) + ("\n" if lines else "")
    if len(body.encode("utf-8")) > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError("URLScan archive exceeds 20 MiB.")
    try:
        if path.read_text(encoding="utf-8") == body:
            return 0
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return sum(signal["id"] not in existing_ids for signal in signals)


def _read_urlscan_intelligence_file(
    path: Path,
    now: datetime,
    maximum: int = MAXIMUM_DAILY_RECORDS,
) -> list[RawDomainIntelligence]:
    try:
        if path.stat().st_size > MAXIMUM_ARCHIVE_BYTES:
            raise ValueError(f"URLScan intelligence archive exceeds 20 MiB: {path.relative_to(Path.cwd())}")
        body = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    now_value = _timestamp(now)
    records: list[RawDomainIntelligence] = []
    for line in body.splitlines():
        if len(line.encode("utf-8")) > 16 * 1024:
            continue
        try:
            value: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw = raw_from_archive_record(value, now_value)
        if raw is not None:
            records.append(raw)
        if len(records) >= max(0, min(maximum, MAXIMUM_DAILY_RECORDS)):
            break
    return records


def write_urlscan_intelligence_archive(
    root: str | Path,
    intelligence: list[RawDomainIntelligence],
    now: datetime,
) -> int:
    path = _intelligence_archive_path(root, vilnius_date(now))
    now_value = _timestamp(now)
    existing = _read_urlscan_intelligence_file(path, now) if path.exists() else []
    records: dict[tuple[str, str], dict[str, object]] = {}
    existing_keys: set[tuple[str, str]] = set()
    for raw in [*existing, *intelligence]:
        record = archive_record(raw, now_value)
        if record is None:
            continue
        observation = cast(dict[str, Any], record["observation"])
        key = (cast(str, record["signalId"]), cast(str, observation["source"]))
        if raw in existing:
            existing_keys.add(key)
        current = records.get(key)
        current_observation = cast(dict[str, Any], current["observation"]) if current else None
        if current_observation is None or cast(str, observation["observedAt"]) > cast(
            str, current_observation["observedAt"]
        ):
            records[key] = record
    ordered = sorted(
        records.values(),
        key=lambda record: (
            cast(str, cast(dict[str, Any], record["observation"])["observedAt"]),
            cast(str, record["signalId"]),
        ),
        reverse=True,
    )[:MAXIMUM_DAILY_RECORDS]
    body = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in ordered)
    if len(body.encode("utf-8")) > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError("URLScan intelligence archive exceeds 20 MiB.")
    try:
        if path.read_text(encoding="utf-8") == body:
            return 0
    except FileNotFoundError:
        pass
    if not body and not path.exists():
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    written_keys = {
        (cast(str, record["signalId"]), cast(str, cast(dict[str, Any], record["observation"])["source"]))
        for record in ordered
    }
    return sum(key not in existing_keys for key in written_keys)


def read_recent_urlscan_intelligence(
    root: str | Path,
    lookback_days: int,
    now: datetime,
    maximum: int = MAXIMUM_DAILY_RECORDS,
) -> list[RawDomainIntelligence]:
    archive_root = _bounded_archive_root(root)
    try:
        directories = sorted(
            (entry.name for entry in archive_root.iterdir() if entry.is_dir() and _valid_day(entry.name)),
            reverse=True,
        )
    except FileNotFoundError:
        return []
    today = date.fromisoformat(vilnius_date(now))
    permitted = {(today - timedelta(days=offset)).isoformat() for offset in range(lookback_days)}
    newest: dict[tuple[str, str], RawDomainIntelligence] = {}
    for day in (value for value in directories if value in permitted):
        remaining = maximum - len(newest)
        if remaining <= 0:
            break
        for raw in _read_urlscan_intelligence_file(_intelligence_archive_path(root, day), now, remaining):
            key = (raw.domain, raw.source)
            current = newest.get(key)
            if current is None or (raw.observed_at or "") > (current.observed_at or ""):
                newest[key] = raw
    return list(newest.values())[:maximum]


def read_recent_urlscan(
    root: str | Path,
    lookback_days: int,
    now: datetime,
    maximum: int = MAXIMUM_DAILY_RECORDS,
    registry: BrandRegistry | None = None,
) -> list[RadarSignal]:
    archive_root = _bounded_archive_root(root)
    try:
        directories = sorted(
            (entry.name for entry in archive_root.iterdir() if entry.is_dir() and _valid_day(entry.name)),
            reverse=True,
        )
    except FileNotFoundError:
        return []
    today = date.fromisoformat(vilnius_date(now))
    permitted = {(today - timedelta(days=offset)).isoformat() for offset in range(lookback_days)}
    brand_registry = registry or load_brand_registry()

    def reviewer(signal: RadarSignal) -> bool:
        return _reviewed_archive_signal(signal, brand_registry)

    records: list[RadarSignal] = []
    for day in (value for value in directories if value in permitted):
        remaining = maximum - len(records)
        if remaining <= 0:
            break
        records.extend(
            read_urlscan_file(
                _archive_path(root, day),
                remaining,
                now=now,
                reviewer=reviewer,
            )
        )
    return merge_signals(records, maximum)


def _hunt_state_path(root: str | Path) -> Path:
    return _bounded_archive_root(root) / "hunt-state.json"


def _validated_hunt_state(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    failure_code = value.get("lastFailureCode", "unknown" if value.get("lastOutcome") == "failed" else None)
    value = {key: item for key, item in value.items() if key != "lastFailureCode"}
    if set(value) == LEGACY_HUNT_STATE_FIELDS:
        value = {
            **value,
            "checkpointCoverage": {
                "queries": 0,
                "complete": 0,
                "partial": 0,
                "backlog": 0,
                "oldestBacklogProgressAt": None,
            },
        }
    if set(value) == PRE_HEALTH_HUNT_STATE_FIELDS:
        failed = value.get("lastOutcome") == "failed"
        value = {
            **value,
            "lastSuccessAt": None if failed or value.get("configured") is not True else value.get("lastRunAt"),
            "consecutiveFailures": 1 if failed else 0,
            "degradedSince": value.get("lastRunAt") if failed else None,
        }
    if set(value) != HUNT_STATE_FIELDS - {"lastFailureCode"}:
        return None
    value["lastFailureCode"] = failure_code
    allowed_failure_codes = {
        None, "unknown", "state-capacity", "state-invalid", "provider-rate-limit", "provider-error",
    }
    if failure_code not in allowed_failure_codes:
        return None
    if (value.get("lastOutcome") == "failed") != (failure_code is not None):
        return None
    integers = (
        "searchRequests",
        "resultRequests",
        "candidateCursor",
        "candidateCount",
        "selectedCandidates",
        "lastRunSearchRequests",
        "lastRunResultRequests",
        "consecutiveFailures",
    )
    if (
        value.get("schemaVersion") != 1
        or value.get("dataset") != "urlscan-hunt-state"
        or not isinstance(value.get("configured"), bool)
        or value.get("lastOutcome") not in HUNT_OUTCOMES
        or not all(isinstance(value.get(field), int) and not isinstance(value.get(field), bool) for field in integers)
    ):
        return None
    generated = value.get("generatedAt")
    last_run = value.get("lastRunAt")
    last_success = value.get("lastSuccessAt")
    degraded_since = value.get("degradedSince")
    budget_day = value.get("budgetDay")
    if (
        not isinstance(generated, str)
        or not UTC_MILLISECOND_TIMESTAMP.fullmatch(generated)
        or not isinstance(last_run, str)
        or not UTC_MILLISECOND_TIMESTAMP.fullmatch(last_run)
        or (last_success is not None and (
            not isinstance(last_success, str) or not UTC_MILLISECOND_TIMESTAMP.fullmatch(last_success)
        ))
        or (degraded_since is not None and (
            not isinstance(degraded_since, str) or not UTC_MILLISECOND_TIMESTAMP.fullmatch(degraded_since)
        ))
        or not isinstance(budget_day, str)
        or not _valid_day(budget_day)
    ):
        return None
    try:
        if _timestamp(datetime.fromisoformat(generated.replace("Z", "+00:00"))) != generated:
            return None
        if _timestamp(datetime.fromisoformat(last_run.replace("Z", "+00:00"))) != last_run:
            return None
        if last_success is not None and (
            _timestamp(datetime.fromisoformat(last_success.replace("Z", "+00:00"))) != last_success
        ):
            return None
        if degraded_since is not None and (
            _timestamp(datetime.fromisoformat(degraded_since.replace("Z", "+00:00"))) != degraded_since
        ):
            return None
    except ValueError:
        return None
    search_requests = value["searchRequests"]
    result_requests = value["resultRequests"]
    candidate_cursor = value["candidateCursor"]
    candidate_count = value["candidateCount"]
    selected = value["selectedCandidates"]
    last_search = value["lastRunSearchRequests"]
    last_result = value["lastRunResultRequests"]
    configured = value["configured"]
    outcome = value["lastOutcome"]
    consecutive_failures = value["consecutiveFailures"]
    coverage = value["checkpointCoverage"]
    if (
        not 0 <= search_requests <= PROVIDER_DAILY_SEARCH_LIMIT
        or not 0 <= result_requests <= PROVIDER_DAILY_RESULT_LIMIT
        or not 0 <= candidate_count <= 1_000
        or not 0 <= selected <= candidate_count
        or (candidate_count == 0 and candidate_cursor != 0)
        or (candidate_count > 0 and not 0 <= candidate_cursor < candidate_count)
        or not 0 <= last_search <= PROVIDER_MINUTE_LIMIT
        or not 0 <= last_result <= PROVIDER_MINUTE_LIMIT
        or (outcome == "skipped-not-configured") != (configured is False)
        or not 0 <= consecutive_failures <= 2_000_000_000
        or generated != last_run
        or datetime.fromisoformat(generated.replace("Z", "+00:00")).date().isoformat() != budget_day
    ):
        return None
    if outcome == "failed":
        if consecutive_failures == 0 or degraded_since is None:
            return None
        if datetime.fromisoformat(degraded_since.replace("Z", "+00:00")) > datetime.fromisoformat(
            last_run.replace("Z", "+00:00")
        ):
            return None
    elif consecutive_failures != 0 or degraded_since is not None:
        return None
    if configured and outcome != "failed" and last_success != last_run:
        return None
    if not configured and last_success is not None:
        return None
    if (
        last_success is not None
        and datetime.fromisoformat(last_success.replace("Z", "+00:00"))
        > datetime.fromisoformat(last_run.replace("Z", "+00:00"))
    ):
        return None
    if not isinstance(coverage, dict) or set(coverage) != {
        "queries",
        "complete",
        "partial",
        "backlog",
        "oldestBacklogProgressAt",
    }:
        return None
    coverage_counts = [coverage.get(field) for field in ("queries", "complete", "partial", "backlog")]
    if (
        not all(type(item) is int and 0 <= item <= 256 for item in coverage_counts)
        or coverage["complete"] + coverage["partial"] != coverage["queries"]
        or coverage["backlog"] > coverage["partial"]
    ):
        return None
    oldest_progress = coverage["oldestBacklogProgressAt"]
    if (coverage["backlog"] == 0) != (oldest_progress is None):
        return None
    if oldest_progress is not None:
        if not isinstance(oldest_progress, str) or not UTC_MILLISECOND_TIMESTAMP.fullmatch(oldest_progress):
            return None
        try:
            if _timestamp(datetime.fromisoformat(oldest_progress.replace("Z", "+00:00"))) != oldest_progress:
                return None
        except ValueError:
            return None
    return cast(dict[str, Any], value)


def read_urlscan_hunt_state(root: str | Path) -> dict[str, Any] | None:
    path = _hunt_state_path(root)
    try:
        if path.stat().st_size > MAXIMUM_HUNT_STATE_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return _validated_hunt_state(payload)


def write_urlscan_hunt_state(root: str | Path, state: dict[str, Any]) -> None:
    validated = _validated_hunt_state(state)
    if validated is None:
        raise ValueError("URLScan hunt state has an invalid contract.")
    path = _hunt_state_path(root)
    body = json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
    if len(body.encode("utf-8")) > MAXIMUM_HUNT_STATE_BYTES:
        raise ValueError("URLScan hunt state exceeds 32 KiB.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _write_hunt_state_if_changed(
    root: str | Path,
    previous: dict[str, Any] | None,
    state: dict[str, Any],
) -> bool:
    stable_fields = HUNT_STATE_FIELDS - {"generatedAt", "lastRunAt"}
    if previous is not None and all(previous[field] == state[field] for field in stable_fields):
        return False
    write_urlscan_hunt_state(root, state)
    return True


def _state_for_run(
    now: datetime,
    *,
    configured: bool,
    outcome: str,
    search_requests: int,
    result_requests: int,
    candidate_cursor: int,
    candidate_count: int,
    selected_candidates: int,
    last_search_requests: int,
    last_result_requests: int,
    checkpoint_coverage: dict[str, object] | None = None,
    previous: dict[str, Any] | None = None,
    failure_code: str = "unknown",
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    if outcome == "failed":
        last_success_at = previous.get("lastSuccessAt") if previous else None
        consecutive_failures = min(
            2_000_000_000,
            (cast(int, previous["consecutiveFailures"]) if previous else 0) + 1,
        )
        degraded_since = previous.get("degradedSince") if previous else None
        degraded_since = degraded_since or timestamp
    elif configured:
        last_success_at = timestamp
        consecutive_failures = 0
        degraded_since = None
    else:
        last_success_at = None
        consecutive_failures = 0
        degraded_since = None
    state = {
        "schemaVersion": 1,
        "dataset": "urlscan-hunt-state",
        "generatedAt": timestamp,
        "configured": configured,
        "budgetDay": now.astimezone(UTC).date().isoformat(),
        "searchRequests": search_requests,
        "resultRequests": result_requests,
        "candidateCursor": candidate_cursor,
        "candidateCount": candidate_count,
        "selectedCandidates": selected_candidates,
        "lastRunAt": timestamp,
        "lastOutcome": outcome,
        "lastFailureCode": failure_code if outcome == "failed" else None,
        "lastSuccessAt": last_success_at,
        "consecutiveFailures": consecutive_failures,
        "degradedSince": degraded_since,
        "lastRunSearchRequests": last_search_requests,
        "lastRunResultRequests": last_result_requests,
        "checkpointCoverage": checkpoint_coverage
        or {
            "queries": 0,
            "complete": 0,
            "partial": 0,
            "backlog": 0,
            "oldestBacklogProgressAt": None,
        },
    }
    if _validated_hunt_state(state) is None:
        raise ValueError("URLScan hunt state could not be constructed safely.")
    return state


def main() -> int:
    now = datetime.now(UTC)
    root = os.environ.get("URLSCAN_ARCHIVE_ROOT", "").strip() or "data/urlscan"
    previous = read_urlscan_hunt_state(root)
    api_key = os.environ.get("URLSCAN_API_KEY", "").strip()
    budget_day = now.date().isoformat()
    same_day = previous is not None and previous["budgetDay"] == budget_day
    if same_day and previous is not None:
        search_used = cast(int, previous["searchRequests"])
        result_used = cast(int, previous["resultRequests"])
    else:
        search_used = 0
        result_used = 0
    previous_cursor = cast(int, previous["candidateCursor"]) if previous else 0
    previous_count = cast(int, previous["candidateCount"]) if previous else 0
    try:
        checkpoints = SearchCheckpointStore.load(
            _bounded_archive_root(root) / "search-checkpoints.json",
            now=now,
        )
    except Exception:
        # A missing checkpoint is a valid first-run bootstrap and is handled
        # by SearchCheckpointStore.load. Reaching this branch means existing
        # state is malformed or unreadable. Do not print the exception: a
        # future provider implementation could include a private query in it.
        recorded = False
        if previous is not None and api_key:
            try:
                recorded = _write_hunt_state_if_changed(
                    root,
                    previous,
                    _state_for_run(
                        now,
                        configured=True,
                        outcome="failed",
                        failure_code="state-invalid",
                        search_requests=search_used,
                        result_requests=result_used,
                        candidate_cursor=previous_cursor if previous_count else 0,
                        candidate_count=previous_count,
                        selected_candidates=0,
                        last_search_requests=0,
                        last_result_requests=0,
                        checkpoint_coverage=cast(
                            dict[str, object], previous["checkpointCoverage"]
                        ),
                        previous=previous,
                    ),
                )
            except Exception:
                print("URLScan checkpoint failure state could not be recorded safely.")
        suffix = "failed health state recorded" if recorded else "no safe prior state available"
        print(
            "URLScan checkpoint state is malformed or unreadable; "
            f"no provider request was made; {suffix}."
        )
        return 1
    initial_checkpoint_coverage = checkpoints.summary()
    if not api_key:
        try:
            changed = _write_hunt_state_if_changed(
                root,
                previous,
                _state_for_run(
                    now,
                    configured=False,
                    outcome="skipped-not-configured",
                    search_requests=search_used,
                    result_requests=result_used,
                    candidate_cursor=previous_cursor,
                    candidate_count=previous_count,
                    selected_candidates=0,
                    last_search_requests=0,
                    last_result_requests=0,
                    checkpoint_coverage=initial_checkpoint_coverage,
                    previous=previous,
                ),
            )
            print(
                "URLScan hunt skipped successfully: URLSCAN_API_KEY is not configured; "
                "no URLScan request was made; independently qualifying CertStream "
                f"candidates remain eligible; state {'updated' if changed else 'unchanged'}."
            )
            return 0
        except Exception as error:
            message = str(error).splitlines()[0] if str(error) else type(error).__name__
            print(f"URLScan skip state failed: {message}")
            return 1

    daily_search_cap = _bounded(os.environ.get("URLSCAN_DAILY_SEARCH_CAP"), 900, 1, PROVIDER_DAILY_SEARCH_LIMIT)
    daily_result_cap = _bounded(os.environ.get("URLSCAN_DAILY_RESULT_CAP"), 8_000, 1, PROVIDER_DAILY_RESULT_LIMIT)
    run_search_cap = _bounded(os.environ.get("URLSCAN_RUN_SEARCH_CAP"), 25, 1, PROVIDER_MINUTE_LIMIT - 20)
    run_result_cap = _bounded(os.environ.get("URLSCAN_RUN_RESULT_CAP"), 100, 1, PROVIDER_MINUTE_LIMIT - 20)
    requester = _BudgetedRequester(
        _request_json,
        search_used=search_used,
        result_used=result_used,
        daily_search_cap=daily_search_cap,
        daily_result_cap=daily_result_cap,
        run_search_cap=run_search_cap,
        run_result_cap=run_result_cap,
    )
    shards = _bounded(os.environ.get("URLSCAN_SEED_ROTATION_SHARDS"), 1, 1, 48)
    seeds_per_run = _bounded(os.environ.get("URLSCAN_SEEDS_PER_RUN"), 250, 1, 250)
    progress = _HuntProgress(candidate_cursor=previous_cursor)
    intelligence: list[RawDomainIntelligence] = []
    try:
        signals = hunt_urlscan(
            api_key,
            now,
            requester=requester,
            seed_cursor=previous_cursor,
            seed_rotation_shards=shards,
            seeds_per_run=seeds_per_run,
            progress=progress,
            intelligence_sink=intelligence,
            search_checkpoints=checkpoints,
        )
        checkpoints.preflight()
        added = write_urlscan_archive(root, signals, now)
        detail_added = write_urlscan_intelligence_archive(root, intelligence, now)
        if checkpoints.dirty:
            checkpoints.commit()
        outcome = "budget-limited" if requester.exhausted else "completed"
        _write_hunt_state_if_changed(
            root,
            previous,
            _state_for_run(
                now,
                configured=True,
                outcome=outcome,
                search_requests=requester.search_used,
                result_requests=requester.result_used,
                candidate_cursor=progress.candidate_cursor,
                candidate_count=progress.candidate_count,
                selected_candidates=progress.selected_candidates,
                last_search_requests=requester.run_search_requests,
                last_result_requests=requester.run_result_requests,
                checkpoint_coverage=checkpoints.summary(),
                previous=previous,
            ),
        )
        print(
            f"URLScan: {len(signals)} reviewed signals; {added} new signal and "
            f"{detail_added} new detail archive records; "
            f"{requester.run_search_requests} search and {requester.run_result_requests} "
            f"result requests; outcome {outcome}."
        )
        return 0
    except Exception as error:
        try:
            _write_hunt_state_if_changed(
                root,
                previous,
                _state_for_run(
                    now,
                    configured=True,
                    outcome="failed",
                    failure_code=(
                        "state-capacity" if isinstance(error, CheckpointCapacityError)
                        else "provider-rate-limit" if isinstance(error, _URLScanRateLimitError)
                        else "provider-error"
                    ),
                    search_requests=requester.search_used,
                    result_requests=requester.result_used,
                    candidate_cursor=previous_cursor if previous_count else 0,
                    candidate_count=previous_count,
                    selected_candidates=0,
                    last_search_requests=requester.run_search_requests,
                    last_result_requests=requester.run_result_requests,
                    checkpoint_coverage=initial_checkpoint_coverage,
                    previous=previous,
                ),
            )
        except Exception as state_error:
            state_message = str(state_error).splitlines()[0] if str(state_error) else type(state_error).__name__
            print(f"URLScan failure state could not be recorded: {state_message}")
        message = str(error).splitlines()[0] if str(error) else type(error).__name__
        print(f"URLScan hunt failed: {message}")
        return 1


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
