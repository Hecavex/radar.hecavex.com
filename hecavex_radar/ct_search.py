"""Checkpointed, bounded Certificate Transparency keyword polling.

The live CertStream collector is intentionally sampled.  This module adds a
second, replayable path for reviewed brand terms by keeping a cursor for every
query.  It does not claim complete coverage of every public CT log: crt.sh is a
search index, and its availability and indexing scope remain external limits.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .brands import BrandRegistry, load_brand_registry, normalize_domain, score_domain
from .certstream import CertificateEvidence
from .certstream_archive import CandidateArchiveWriter, candidate_from_match

API_HOST = "crt.sh"
API_ROOT = f"https://{API_HOST}/"
DEFAULT_STATE_PATH = "data/ct-search/state.json"
DEFAULT_ARCHIVE_ROOT = "data/certstream"
MAXIMUM_RESPONSE_BYTES = 20 * 1024 * 1024
MAXIMUM_STATE_BYTES = 128 * 1024
MAXIMUM_QUERIES = 128
MAXIMUM_QUERY_CHARACTERS = 48
MAXIMUM_ROWS_PER_QUERY = 2_000
MAXIMUM_DNS_NAMES_PER_ROW = 500
DEFAULT_REPLAY_ID_WINDOW = 1_000
DEFAULT_REPLAY_ROWS = 50
DEFAULT_PROVIDER_BACKOFF_SECONDS = 5 * 60
MAXIMUM_PROVIDER_BACKOFF_SECONDS = 6 * 60 * 60
STATE_OUTCOMES = frozenset({"completed", "partial", "failed", "deferred-backoff"})
FAILURE_CODES = frozenset(
    {"provider-timeout", "provider-http", "provider-network", "invalid-response", "validation", "internal"}
)
PROVIDER_HEALTH_FIELDS = frozenset(
    {"lastSuccessAt", "lastAttemptAt", "lastFailureCodes", "consecutiveFailures", "degradedSince", "nextAttemptAt"}
)
ROW_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?$")
HEX = re.compile(r"^[a-f\d]+$")
QUERY = re.compile(r"^[a-z\d][a-z\d-]{3,47}$")

JsonRequester = Callable[[str], Any]
FailureCode = Literal[
    "provider-timeout",
    "provider-http",
    "provider-network",
    "invalid-response",
    "validation",
    "internal",
]


class CTSearchRequestError(RuntimeError):
    """A provider failure with a stable code safe for public health output."""

    def __init__(self, code: FailureCode, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class QueryDefinition:
    key: str
    term: str
    brand: str


@dataclass(frozen=True, slots=True)
class ParsedRow:
    identifier: int
    observed_at: datetime
    domains: tuple[str, ...]
    certificate: CertificateEvidence | None


class _SameHostRedirectHandler(HTTPRedirectHandler):
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
            or destination.hostname != API_HOST
            or destination.username is not None
            or destination.password is not None
            or destination.port is not None
        ):
            raise HTTPError(request.full_url, code, "CT search returned an unapproved redirect.", headers, file_pointer)
        return super().redirect_request(request, file_pointer, code, message, headers, destination.geturl())


def _bounded_integer(value: str | None, fallback: int, minimum: int, maximum: int) -> int:
    if not value or not value.strip():
        return fallback
    try:
        parsed = int(value)
    except ValueError:
        return fallback
    return min(maximum, max(minimum, parsed))


def _timestamp(value: datetime) -> str:
    candidate = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return candidate.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40 or not ROW_TIMESTAMP.fullmatch(value.strip()):
        return None
    candidate = value.strip().replace(" ", "T")
    if candidate.endswith("Z"):
        candidate = candidate.removesuffix("Z") + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_path(value: str | Path, *, expected_parent: str) -> Path:
    repository = Path.cwd().resolve()
    target = (repository / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    allowed = (repository / expected_parent).resolve()
    if target == repository or not target.is_relative_to(allowed):
        raise ValueError(f"Path must stay below {expected_parent}.")
    return target


def _query_term(value: str) -> str | None:
    folded = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z\d]+", folded)
    if not tokens:
        return None
    joined = "".join(tokens)
    return joined if QUERY.fullmatch(joined) else None


def build_queries(registry: BrandRegistry) -> list[QueryDefinition]:
    """Choose a bounded set of high-specificity brand terms.

    Very short aliases make an unbounded public CT search both noisy and
    expensive.  The domain matcher still makes the final publication decision.
    """

    definitions: list[QueryDefinition] = []
    owners: dict[str, str] = {}
    for entry in registry.entries:
        candidates = {
            term
            for alias in [entry.brand, *entry.aliases]
            if (term := _query_term(alias)) is not None and len(term) >= 5
        }
        if not candidates:
            continue
        # Prefer the shortest still-specific term so the search catches common
        # affixes such as ``brand-support``. Short brand names fall back to a
        # longer reviewed alias to avoid global four-character searches.
        term = sorted(candidates, key=lambda item: (len(item), item))[0]
        previous = owners.get(term)
        if previous is not None and previous != entry.brand:
            continue
        owners[term] = entry.brand
        definitions.append(QueryDefinition(key=f"brand:{term}", term=term, brand=entry.brand))
    definitions.sort(key=lambda item: item.key)
    return definitions[:MAXIMUM_QUERIES]


def _request_url(term: str) -> str:
    if not QUERY.fullmatch(term):
        raise ValueError("Invalid CT search term.")
    query = urlencode({"q": f"%{term}%", "exclude": "expired", "output": "json"})
    return f"{API_ROOT}?{query}"


def _retry_after_seconds(value: object, *, now: datetime | None = None) -> int | None:
    """Parse a provider Retry-After value into a conservative bounded delay."""

    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        return None
    candidate = value.strip()
    if candidate.isdecimal():
        return min(MAXIMUM_PROVIDER_BACKOFF_SECONDS, int(candidate))
    try:
        retry_at = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = max(0, int((retry_at.astimezone(UTC) - (now or datetime.now(UTC))).total_seconds()))
    return min(MAXIMUM_PROVIDER_BACKOFF_SECONDS, delay)


def request_json(url: str) -> Any:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != API_HOST
        or parsed.path != "/"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise ValueError("CT search requests must stay on https://crt.sh/.")
    opener = build_opener(_SameHostRedirectHandler())
    request = Request(  # noqa: S310 - scheme and host are enforced above
        url,
        headers={"Accept": "application/json", "User-Agent": "hecavex-radar/0.2 (+https://radar.hecavex.com/)"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=45) as response:  # noqa: S310 - scheme and host are enforced above
            content_length = response.headers.get("Content-Length")
            try:
                oversized = content_length is not None and int(content_length) > MAXIMUM_RESPONSE_BYTES
            except ValueError as error:
                raise CTSearchRequestError(
                    "invalid-response", "CT search returned an invalid content length."
                ) from error
            if oversized:
                raise CTSearchRequestError("invalid-response", "CT search response exceeds 20 MiB.")
            body = response.read(MAXIMUM_RESPONSE_BYTES + 1)
    except HTTPError as error:
        retry_after = _retry_after_seconds(error.headers.get("Retry-After") if error.headers else None)
        raise CTSearchRequestError(
            "provider-http",
            f"CT search returned HTTP {error.code}.",
            retry_after_seconds=retry_after,
        ) from error
    except URLError as error:
        code: FailureCode = "provider-timeout" if isinstance(error.reason, TimeoutError) else "provider-network"
        raise CTSearchRequestError(code, "CT search request failed.") from error
    except TimeoutError as error:
        raise CTSearchRequestError("provider-timeout", "CT search request timed out.") from error
    if len(body) > MAXIMUM_RESPONSE_BYTES:
        raise CTSearchRequestError("invalid-response", "CT search response exceeds 20 MiB.")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CTSearchRequestError("invalid-response", "CT search returned invalid JSON.") from error


def _hex(value: object, maximum: int = 80) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower().removeprefix("0x").replace(":", "").replace(" ", "")
    return candidate if 0 < len(candidate) <= maximum and HEX.fullmatch(candidate) else None


def _domains(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or len(value) > 64 * 1024:
        return ()
    domains: list[str] = []
    for raw in value.splitlines()[:MAXIMUM_DNS_NAMES_PER_ROW]:
        normalized = normalize_domain(raw)
        if normalized is not None and normalized not in domains:
            domains.append(normalized)
    return tuple(domains)


def _certificate(value: dict[str, Any], domains: tuple[str, ...]) -> CertificateEvidence | None:
    common_name = value.get("common_name")
    normalized_common = normalize_domain(common_name) if isinstance(common_name, str) else None
    issuer = value.get("issuer_name")
    issuer_text = " ".join(issuer.split())[:200] if isinstance(issuer, str) and issuer.strip() else None
    not_before = _parse_timestamp(value.get("not_before"))
    not_after = _parse_timestamp(value.get("not_after"))
    evidence = CertificateEvidence(
        country_name=None,
        issuer=issuer_text,
        common_name=normalized_common,
        not_before=_timestamp(not_before) if not_before else None,
        not_after=_timestamp(not_after) if not_after else None,
        subject_alt_names=domains,
        serial_number_hex=_hex(value.get("serial_number")),
        md5=None,
        sha1=None,
        sha256=None,
    )
    fields = (issuer_text, normalized_common, not_before, not_after, domains, evidence.serial_number_hex)
    return evidence if any(fields) else None


def parse_row(value: object) -> ParsedRow | None:
    if not isinstance(value, dict):
        return None
    raw_identifier = value.get("id")
    if isinstance(raw_identifier, str) and raw_identifier.isdecimal():
        raw_identifier = int(raw_identifier)
    observed_at = _parse_timestamp(value.get("entry_timestamp"))
    domains = _domains(value.get("name_value"))
    if (
        not isinstance(raw_identifier, int)
        or isinstance(raw_identifier, bool)
        or not 0 < raw_identifier <= 9_223_372_036_854_775_807
        or observed_at is None
        or not domains
    ):
        return None
    return ParsedRow(raw_identifier, observed_at, domains, _certificate(cast(dict[str, Any], value), domains))


def _empty_state(now: datetime) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "dataset": "ct-search-state",
        "provider": "crt.sh",
        "generatedAt": _timestamp(now),
        "queryCursor": 0,
        "queries": {},
        "latestRun": None,
        "providerHealth": {
            "lastSuccessAt": None,
            "lastAttemptAt": None,
            "lastFailureCodes": [],
            "consecutiveFailures": 0,
            "degradedSince": None,
            "nextAttemptAt": None,
        },
    }


def _legacy_provider_health(latest: object) -> dict[str, object]:
    if not isinstance(latest, dict):
        return {
            "lastSuccessAt": None,
            "consecutiveFailures": 0,
            "degradedSince": None,
            "nextAttemptAt": None,
        }
    ended_at = latest.get("endedAt")
    failure_codes = latest.get("failureCodes", [])
    degraded = latest.get("outcome") in {"failed", "partial"} and (
        latest.get("outcome") == "failed" or bool(failure_codes)
    )
    return {
        "lastSuccessAt": None if degraded else ended_at,
        "consecutiveFailures": 1 if degraded else 0,
        "degradedSince": latest.get("startedAt") if degraded else None,
        "nextAttemptAt": None,
    }


def _normalize_state(value: object) -> object:
    if not isinstance(value, dict):
        return value
    legacy_fields = {
        "schemaVersion", "dataset", "provider", "generatedAt", "queryCursor", "queries", "latestRun"
    }
    normalized = dict(value)
    if set(value) == legacy_fields:
        normalized["providerHealth"] = _legacy_provider_health(value.get("latestRun"))
    health = normalized.get("providerHealth")
    if isinstance(health, dict) and set(health) == PROVIDER_HEALTH_FIELDS - {"lastAttemptAt", "lastFailureCodes"}:
        latest = normalized.get("latestRun")
        latest = latest if isinstance(latest, dict) else {}
        queries = normalized.get("queries", {})
        queries = queries if isinstance(queries, dict) else {}
        times = [row.get("lastRunAt") for row in queries.values() if isinstance(row, dict)]
        attempted = latest.get("queriesAttempted", 0)
        if type(attempted) is int and attempted > 0:
            times.append(latest.get("endedAt"))
        normalized["providerHealth"] = {
            **health,
            "lastAttemptAt": max((cast(str, time) for time in times if _parse_timestamp(time)), default=None),
            "lastFailureCodes": latest.get("failureCodes", []),
        }
    return normalized


def _valid_query_state(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "term", "brand", "lastId", "lastEntryAt", "lastRunAt", "lastOutcome"
    }:
        return False
    return (
        isinstance(value["term"], str)
        and QUERY.fullmatch(value["term"]) is not None
        and isinstance(value["brand"], str)
        and 0 < len(value["brand"]) <= 120
        and type(value["lastId"]) is int
        and 0 <= value["lastId"] <= 9_223_372_036_854_775_807
        and (value["lastEntryAt"] is None or _parse_timestamp(value["lastEntryAt"]) is not None)
        and (value["lastRunAt"] is None or _parse_timestamp(value["lastRunAt"]) is not None)
        and value["lastOutcome"] in {None, "completed", "partial", "failed"}
    )


def _valid_provider_health(value: object, generated_at: datetime, latest: object) -> bool:
    if not isinstance(value, dict) or set(value) != PROVIDER_HEALTH_FIELDS:
        return False
    consecutive = value["consecutiveFailures"]
    last_success = _parse_timestamp(value["lastSuccessAt"])
    degraded_since = _parse_timestamp(value["degradedSince"])
    next_attempt = _parse_timestamp(value["nextAttemptAt"])
    last_attempt = _parse_timestamp(value["lastAttemptAt"])
    if (
        type(consecutive) is not int
        or not 0 <= consecutive <= 2_000_000_000
        or (value["lastSuccessAt"] is not None and last_success is None)
        or (value["degradedSince"] is not None and degraded_since is None)
        or (value["nextAttemptAt"] is not None and next_attempt is None)
        or (value["lastAttemptAt"] is not None and last_attempt is None)
        or (last_attempt is not None and last_attempt > generated_at)
        or not isinstance(value["lastFailureCodes"], list)
        or len(value["lastFailureCodes"]) > 8
        or any(not isinstance(code, str) or code not in FAILURE_CODES for code in value["lastFailureCodes"])
        or (last_success is not None and last_success > generated_at)
        or (degraded_since is not None and degraded_since > generated_at)
        or (
            next_attempt is not None
            and next_attempt > generated_at + timedelta(seconds=MAXIMUM_PROVIDER_BACKOFF_SECONDS)
        )
        or (consecutive == 0 and (degraded_since is not None or next_attempt is not None))
        or (consecutive > 0 and degraded_since is None)
    ):
        return False
    if not isinstance(latest, dict):
        return consecutive == 0 and last_success is None
    ended_at = _parse_timestamp(latest.get("endedAt"))
    failure_codes = latest.get("failureCodes", [])
    has_failure = latest.get("outcome") == "failed" or bool(failure_codes)
    if latest.get("outcome") == "deferred-backoff":
        return consecutive > 0 and latest.get("queriesAttempted") == 0 and not failure_codes
    if has_failure:
        return consecutive > 0
    return consecutive == 0 and ended_at is not None and last_success == ended_at


def _valid_state(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "dataset", "provider", "generatedAt", "queryCursor", "queries", "latestRun",
        "providerHealth",
    }:
        return False
    queries = value["queries"]
    latest = value["latestRun"]
    generated_at = _parse_timestamp(value["generatedAt"])
    if (
        value["schemaVersion"] != 1
        or value["dataset"] != "ct-search-state"
        or value["provider"] != "crt.sh"
        or generated_at is None
        or type(value["queryCursor"]) is not int
        or not 0 <= value["queryCursor"] <= MAXIMUM_QUERIES
        or not isinstance(queries, dict)
        or len(queries) > MAXIMUM_QUERIES
        or not all(
            isinstance(key, str) and key.startswith("brand:") and _valid_query_state(item)
            for key, item in queries.items()
        )
        or not _valid_provider_health(value["providerHealth"], generated_at, latest)
    ):
        return False
    if latest is None:
        return True
    latest_fields = {
        "startedAt", "endedAt", "outcome", "queriesAttempted", "queriesCompleted", "rowsProcessed",
        "dnsNames", "matches", "newRecords", "queriesBacklogged",
    }
    failure_codes = latest.get("failureCodes", []) if isinstance(latest, dict) else []
    return (
        isinstance(latest, dict)
        and frozenset(latest) in {frozenset(latest_fields), frozenset({*latest_fields, "failureCodes"})}
        and _parse_timestamp(latest["startedAt"]) is not None
        and _parse_timestamp(latest["endedAt"]) is not None
        and latest["outcome"] in STATE_OUTCOMES
        and isinstance(failure_codes, list)
        and len(failure_codes) <= len(FAILURE_CODES)
        and all(isinstance(code, str) and code in FAILURE_CODES for code in failure_codes)
        and failure_codes == sorted(set(cast(list[str], failure_codes)))
        and all(type(latest[field]) is int and 0 <= latest[field] <= 2_000_000_000 for field in (
            "queriesAttempted", "queriesCompleted", "rowsProcessed", "dnsNames", "matches", "newRecords",
            "queriesBacklogged"
        ))
    )


def read_state(path: str | Path = DEFAULT_STATE_PATH, *, now: datetime | None = None) -> dict[str, Any]:
    target = _safe_path(path, expected_parent="data/ct-search")
    try:
        if target.stat().st_size > MAXIMUM_STATE_BYTES:
            raise ValueError("CT search state exceeds 128 KiB.")
        value: object = _normalize_state(json.loads(target.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return _empty_state(now or datetime.now(UTC))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("CT search state is unreadable.") from error
    if not _valid_state(value):
        raise ValueError("CT search state has an invalid contract.")
    return cast(dict[str, Any], value)


def write_state(value: dict[str, Any], path: str | Path = DEFAULT_STATE_PATH) -> Path:
    if not _valid_state(value):
        raise ValueError("Refusing to write invalid CT search state.")
    target = _safe_path(path, expected_parent="data/ct-search")
    body = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(body.encode("utf-8")) > MAXIMUM_STATE_BYTES:
        raise ValueError("Refusing to write CT search state larger than 128 KiB.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return target


def _failure_code(error: Exception) -> FailureCode:
    if isinstance(error, CTSearchRequestError):
        return error.code
    if isinstance(error, TimeoutError):
        return "provider-timeout"
    if isinstance(error, HTTPError):
        return "provider-http"
    if isinstance(error, URLError):
        return "provider-network"
    if isinstance(error, (UnicodeDecodeError, json.JSONDecodeError)):
        return "invalid-response"
    if isinstance(error, ValueError):
        return "validation"
    return "internal"


def _provider_backoff_seconds(consecutive_failures: int, retry_after_seconds: int | None) -> int:
    exponent = min(6, max(0, consecutive_failures - 1))
    exponential = min(MAXIMUM_PROVIDER_BACKOFF_SECONDS, DEFAULT_PROVIDER_BACKOFF_SECONDS * (1 << exponent))
    requested = retry_after_seconds if retry_after_seconds is not None else 0
    return min(MAXIMUM_PROVIDER_BACKOFF_SECONDS, max(exponential, requested))


def poll(
    requester: JsonRequester = request_json,
    *,
    now: datetime | None = None,
    registry: BrandRegistry | None = None,
    state_path: str | Path = DEFAULT_STATE_PATH,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    queries_per_run: int | None = None,
    rows_per_query: int | None = None,
    bootstrap_days: int | None = None,
    replay_ids: int | None = None,
    replay_rows: int | None = None,
) -> dict[str, Any]:
    started = (now or datetime.now(UTC)).astimezone(UTC)
    registry = registry or load_brand_registry()
    definitions = build_queries(registry)
    state = read_state(state_path, now=started)
    provider_health = cast(dict[str, Any], state["providerHealth"])
    next_attempt_at = _parse_timestamp(provider_health["nextAttemptAt"])
    circuit_open = next_attempt_at is not None and started < next_attempt_at
    query_states = cast(dict[str, dict[str, Any]], state["queries"])
    active_keys = {definition.key for definition in definitions}
    for stale in set(query_states).difference(active_keys):
        del query_states[stale]
    for definition in definitions:
        existing = query_states.get(definition.key)
        if existing is None or existing.get("term") != definition.term or existing.get("brand") != definition.brand:
            query_states[definition.key] = {
                "term": definition.term,
                "brand": definition.brand,
                "lastId": 0,
                "lastEntryAt": None,
                "lastRunAt": None,
                "lastOutcome": None,
            }

    run_query_limit = queries_per_run or _bounded_integer(os.environ.get("CT_SEARCH_QUERIES_PER_RUN"), 6, 1, 24)
    row_limit = rows_per_query or _bounded_integer(
        os.environ.get("CT_SEARCH_ROWS_PER_QUERY"), 500, 1, MAXIMUM_ROWS_PER_QUERY
    )
    initial_days = bootstrap_days if bootstrap_days is not None else _bounded_integer(
        os.environ.get("CT_SEARCH_BOOTSTRAP_DAYS"), 7, 0, 30
    )
    replay_id_window = replay_ids if replay_ids is not None else _bounded_integer(
        os.environ.get("CT_SEARCH_REPLAY_IDS"), DEFAULT_REPLAY_ID_WINDOW, 0, 10_000
    )
    replay_row_count = replay_rows if replay_rows is not None else _bounded_integer(
        os.environ.get("CT_SEARCH_REPLAY_ROWS"), DEFAULT_REPLAY_ROWS, 0, 250
    )
    cursor = state["queryCursor"] % max(1, len(definitions))
    selected = [] if circuit_open else [
        definitions[(cursor + offset) % len(definitions)]
        for offset in range(min(run_query_limit, len(definitions)))
    ]
    writer = CandidateArchiveWriter(archive_root)
    metrics = {
        "queriesAttempted": 0,
        "queriesCompleted": 0,
        "rowsProcessed": 0,
        "dnsNames": 0,
        "matches": 0,
        "newRecords": 0,
        "queriesBacklogged": 0,
    }
    failure_codes: set[FailureCode] = set()
    backlog_keys: list[str] = []
    retry_after_seconds: int | None = None
    cutoff = started - timedelta(days=initial_days)

    for definition in selected:
        query_state = query_states[definition.key]
        metrics["queriesAttempted"] += 1
        try:
            payload = requester(_request_url(definition.term))
            if not isinstance(payload, list):
                raise CTSearchRequestError("invalid-response", "CT search response is not a JSON array.")
            parsed = sorted(
                (row for value in payload if (row := parse_row(value)) is not None),
                key=lambda row: (row.identifier, row.observed_at),
            )
            last_id = cast(int, query_state["lastId"])
            if last_id == 0:
                older = [row.identifier for row in parsed if row.observed_at < cutoff]
                last_id = max(older, default=0)
            new_rows = [row for row in parsed if row.identifier > last_id]
            maximum_replay = min(
                replay_row_count,
                max(0, row_limit - 1) if new_rows else row_limit,
            )
            replay_floor = max(0, last_id - replay_id_window)
            overlap = [row for row in parsed if replay_floor < row.identifier <= last_id]
            overlap = overlap[-maximum_replay:] if maximum_replay else []
            selected_new = new_rows[: row_limit - len(overlap)]
            pending = [*overlap, *selected_new]
            has_backlog = len(selected_new) < len(new_rows)
            highest_processed = last_id
            for row in pending:
                metrics["rowsProcessed"] += 1
                highest_processed = max(highest_processed, row.identifier)
                candidates = []
                for domain in row.domains:
                    metrics["dnsNames"] += 1
                    match = score_domain(domain, registry)
                    if match is None:
                        continue
                    metrics["matches"] += 1
                    candidates.append(
                        candidate_from_match(
                            match,
                            row.observed_at,
                            row.certificate,
                            collection_method="ct-search-api",
                        )
                    )
                if candidates:
                    metrics["newRecords"] += writer.append(candidates)
            query_state.update(
                {
                    "lastId": highest_processed,
                    "lastEntryAt": (
                        _timestamp(selected_new[-1].observed_at)
                        if selected_new
                        else query_state["lastEntryAt"]
                    ),
                    "lastRunAt": _timestamp(started),
                    "lastOutcome": "partial" if has_backlog else "completed",
                }
            )
            metrics["queriesCompleted"] += 1
            if has_backlog:
                metrics["queriesBacklogged"] += 1
                backlog_keys.append(definition.key)
        except Exception as error:
            query_state.update({"lastRunAt": _timestamp(started), "lastOutcome": "failed"})
            code = _failure_code(error)
            failure_codes.add(code)
            if isinstance(error, CTSearchRequestError):
                retry_after_seconds = error.retry_after_seconds
            # One failed provider request trips the run-scoped circuit. This
            # bounds total attempts below the existing queries-per-run budget
            # instead of issuing the remaining queries into a known outage.
            break

    ended = datetime.now(UTC) if now is None else started
    if not circuit_open:
        # Each query retains its own cursor, including failures and backlog.
        # Rotate after the actual bounded attempts so one slow term cannot
        # monopolize every retry. A provider error still stops this run.
        state["queryCursor"] = (cursor + metrics["queriesAttempted"]) % max(1, len(definitions))
    outcome: Literal["completed", "partial", "failed", "deferred-backoff"]
    if circuit_open:
        outcome = "deferred-backoff"
    elif failure_codes:
        outcome = (
            "partial" if metrics["queriesCompleted"] else "failed"
        )
    elif backlog_keys:
        outcome = "partial"
    else:
        outcome = "completed"
    if circuit_open:
        updated_provider_health = provider_health
    elif failure_codes:
        previous_failures = cast(int, provider_health["consecutiveFailures"])
        consecutive_failures = min(2_000_000_000, previous_failures + 1)
        degraded_since = provider_health["degradedSince"] or _timestamp(started)
        backoff_seconds = _provider_backoff_seconds(consecutive_failures, retry_after_seconds)
        updated_provider_health = {
            "lastSuccessAt": provider_health["lastSuccessAt"],
            "lastAttemptAt": _timestamp(ended),
            "lastFailureCodes": sorted(failure_codes),
            "consecutiveFailures": consecutive_failures,
            "degradedSince": degraded_since,
            "nextAttemptAt": _timestamp(ended + timedelta(seconds=backoff_seconds)),
        }
    else:
        updated_provider_health = {
            "lastSuccessAt": _timestamp(ended),
            "lastAttemptAt": _timestamp(ended),
            "lastFailureCodes": [],
            "consecutiveFailures": 0,
            "degradedSince": None,
            "nextAttemptAt": None,
        }
    state.update(
        {
            "generatedAt": _timestamp(ended),
            "providerHealth": updated_provider_health,
            "latestRun": {
                "startedAt": _timestamp(started),
                "endedAt": _timestamp(ended),
                "outcome": outcome,
                "failureCodes": sorted(failure_codes),
                **metrics,
            },
        }
    )
    write_state(state, state_path)
    if failure_codes:
        print("CT search controlled failure codes: " + ", ".join(sorted(failure_codes)), flush=True)
    print(
        f"CT search {outcome}: {metrics['queriesCompleted']}/{metrics['queriesAttempted']} queries, "
        f"{metrics['rowsProcessed']} rows, {metrics['dnsNames']} DNS names, "
        f"{metrics['matches']} matches, {metrics['newRecords']} new records.",
        flush=True,
    )
    return cast(dict[str, Any], state["latestRun"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Poll bounded CT keyword searches with persisted cursors.")
    parser.add_argument("--state", default=os.environ.get("CT_SEARCH_STATE_PATH", DEFAULT_STATE_PATH))
    parser.add_argument("--archive-root", default=os.environ.get("CERTSTREAM_ARCHIVE_ROOT", DEFAULT_ARCHIVE_ROOT))
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        result = poll(state_path=options.state, archive_root=options.archive_root)
    except Exception as error:
        print(f"CT search failed before state publication: {_failure_code(error)}", flush=True)
        return 1
    return 0 if result["outcome"] in {"completed", "partial", "deferred-backoff"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
