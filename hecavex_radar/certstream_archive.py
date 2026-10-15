"""Bounded, date-partitioned archive for public CertStream candidates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from .brands import normalize_domain
from .certstream import CertificateEvidence, certificate_for_domain, public_certificate_text
from .models import CandidateMatch, CertStreamCandidate, RawSignal, SourceTimeEvidence
from .normalize import legacy_source_time_evidence, resolve_signal_times, validate_source_time_evidence
from .safety import defang_host, refang, stable_id

VILNIUS = ZoneInfo("Europe/Vilnius")
MAXIMUM_ARCHIVE_BYTES = 25 * 1024 * 1024
MAXIMUM_ARCHIVE_RECORDS = 25_000
MAXIMUM_CANDIDATE_LINE_BYTES = 16 * 1024
MAXIMUM_BRAND_CHARACTERS = 120
MAXIMUM_REASON_CHARACTERS = 240
MAXIMUM_REASONS = 12
MAXIMUM_CERTIFICATE_SAN_SAMPLES = 12
MAXIMUM_CERTIFICATE_SAN_COUNT = 500
MAXIMUM_CERTIFICATE_ISSUER_CHARACTERS = 200
MAXIMUM_CERTIFICATE_SERIAL_CHARACTERS = 80
MAXIMUM_DAILY_ATTEMPTS = 256
MAXIMUM_ATTEMPT_ARCHIVE_BYTES = 256 * 1024
MAXIMUM_ATTEMPT_LINE_BYTES = 4 * 1024
CANDIDATE_FIELDS = frozenset(
    {
        "schemaVersion",
        "id",
        "observedAt",
        "indicatorType",
        "domain",
        "registrableDomain",
        "source",
        "brand",
        "confidence",
        "reasons",
    }
)
CANDIDATE_OPTIONAL_FIELDS = frozenset({"certificate", "collectionMethod", "sourceTimeEvidence"})
CANDIDATE_ID = re.compile(r"^[a-f\d]{20}$")
ATTEMPT_ID = re.compile(r"^[a-f\d]{24}$")
UTC_MILLISECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
HEX = re.compile(r"^[0-9a-f]+$")
ATTEMPT_FIELDS = frozenset(
    {
        "schemaVersion",
        "id",
        "collectorStartedAt",
        "endedAt",
        "expectedListeningSeconds",
        "listeningSeconds",
        "messages",
        "dnsNames",
        "matches",
        "newRecords",
        "outcome",
    }
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def vilnius_date(value: datetime) -> str:
    return _aware(value).astimezone(VILNIUS).date().isoformat()


def candidate_from_match(
    match: CandidateMatch,
    observed_at: datetime,
    certificate: CertificateEvidence | None = None,
    collection_method: str = "certstream-live",
    *,
    source_time_evidence: list[SourceTimeEvidence] | None = None,
) -> CertStreamCandidate:
    observed = _aware(observed_at).astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "id": stable_id(match.domain),
        "observedAt": observed,
        "indicatorType": "domain",
        "domain": defang_host(match.domain),
        "registrableDomain": defang_host(match.registrable_domain),
        "source": "CertStream",
        "brand": match.brand,
        "confidence": match.confidence,
        "reasons": list(match.reasons),
        "collectionMethod": collection_method,
    }
    certificate_detail = certificate_for_domain(certificate, match.registrable_domain)
    if certificate_detail is not None:
        payload["certificate"] = certificate_detail
    if source_time_evidence is None:
        source_time_evidence = (
            resolve_signal_times(RawSignal(url=match.domain, source="CertStream"), observed)
            if collection_method == "certstream-live"
            else legacy_source_time_evidence(observed, observed, "CertStream")
        )
    payload["sourceTimeEvidence"] = validate_source_time_evidence(
        source_time_evidence, first_seen=observed, last_seen=observed, source="CertStream",
    )
    candidate = cast(CertStreamCandidate, payload)
    if not _is_candidate(candidate):
        raise ValueError("Candidate match cannot be represented by the public CertStream schema.")
    return candidate


def _bounded_root(value: str | Path) -> Path:
    repository = Path.cwd().resolve()
    root = (repository / value).resolve()
    if root == repository or not root.is_relative_to(repository):
        raise ValueError("CERTSTREAM_ARCHIVE_ROOT must stay inside the repository.")
    return root


def _candidate_path(root: str | Path, day: str) -> Path:
    if not _valid_day(day):
        raise ValueError("Invalid candidate archive date.")
    return _bounded_root(root) / day / "domains.ndjson"


def _attempt_path(root: str | Path, day: str) -> Path:
    if not _valid_day(day):
        raise ValueError("Invalid collection-attempt archive date.")
    return _bounded_root(root) / day / "attempts.ndjson"


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not UTC_MILLISECONDS.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    canonical = parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _bounded_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value.strip() == value
        and value.isprintable()
    )


def _canonical_defanged_domain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = normalize_domain(value.replace("[.]", "."))
    return normalized if normalized is not None and defang_host(normalized) == value else None


def _canonical_defanged_certificate_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    raw = refang(value)
    wildcard = raw.startswith("*.")
    normalized = normalize_domain(raw)
    if normalized is None:
        return None
    expected = f"*[.]{defang_host(normalized)}" if wildcard else defang_host(normalized)
    return normalized if value == expected else None


def _optional_timestamp(value: object) -> datetime | None | bool:
    if value is None:
        return None
    parsed = _timestamp(value)
    return parsed if parsed is not None else False


def _fingerprint(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and HEX.fullmatch(value) is not None


def _optional_fingerprint(value: object, length: int) -> bool:
    return value is None or _fingerprint(value, length)


def _is_certificate(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "countryName",
        "issuer",
        "commonName",
        "notBefore",
        "notAfter",
        "subjectAltNames",
        "subjectAltNameCount",
        "serialNumberHex",
        "fingerprints",
    }:
        return False
    subject_alt_names = value["subjectAltNames"]
    count = value["subjectAltNameCount"]
    fingerprints = value["fingerprints"]
    not_before = _optional_timestamp(value["notBefore"])
    not_after = _optional_timestamp(value["notAfter"])
    valid = not (
        (
            value["countryName"] is not None
            and (
                not isinstance(value["countryName"], str)
                or re.fullmatch(r"[A-Z]{2}", value["countryName"]) is None
            )
        )
        or (
            value["issuer"] is not None
            and public_certificate_text(value["issuer"], MAXIMUM_CERTIFICATE_ISSUER_CHARACTERS)
            != value["issuer"]
        )
        or (
            value["commonName"] is not None
            and _canonical_defanged_certificate_name(value["commonName"]) is None
        )
        or not_before is False
        or not_after is False
        or (
            isinstance(not_before, datetime)
            and isinstance(not_after, datetime)
            and not_after < not_before
        )
        or not isinstance(subject_alt_names, list)
        or len(subject_alt_names) > MAXIMUM_CERTIFICATE_SAN_SAMPLES
        or not all(_canonical_defanged_domain(name) is not None for name in subject_alt_names)
        or len(set(subject_alt_names)) != len(subject_alt_names)
        or type(count) is not int
        or not len(subject_alt_names) <= count <= MAXIMUM_CERTIFICATE_SAN_COUNT
        or (
            value["serialNumberHex"] is not None
            and (
                not isinstance(value["serialNumberHex"], str)
                or not 1 <= len(value["serialNumberHex"]) <= MAXIMUM_CERTIFICATE_SERIAL_CHARACTERS
                or HEX.fullmatch(value["serialNumberHex"]) is None
            )
        )
        or not isinstance(fingerprints, dict)
        or set(fingerprints) != {"md5", "sha1", "sha256"}
        or not _optional_fingerprint(fingerprints["md5"], 32)
        or not _optional_fingerprint(fingerprints["sha1"], 40)
        or not _optional_fingerprint(fingerprints["sha256"], 64)
    )
    if not valid or not isinstance(fingerprints, dict):
        return False
    return any(
        value[field] is not None
        for field in ("countryName", "issuer", "commonName", "notBefore", "notAfter", "serialNumberHex")
    ) or bool(subject_alt_names) or any(fingerprints[field] is not None for field in ("md5", "sha1", "sha256"))


def _certificate_has_only_related_sans(value: object, registrable_domain: str) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("subjectAltNames"), list):
        return False
    for item in value["subjectAltNames"]:
        domain = _canonical_defanged_domain(item)
        if domain is None or not (domain == registrable_domain or domain.endswith(f".{registrable_domain}")):
            return False
    return True


def _is_candidate(value: Any, expected_day: str | None = None) -> bool:
    if (
        not isinstance(value, dict)
        or not CANDIDATE_FIELDS.issubset(value)
        or not set(value).issubset(CANDIDATE_FIELDS | CANDIDATE_OPTIONAL_FIELDS)
    ):
        return False
    observed_at = _timestamp(value["observedAt"])
    domain = _canonical_defanged_domain(value["domain"])
    registrable_domain = _canonical_defanged_domain(value["registrableDomain"])
    reasons = value["reasons"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["indicatorType"] != "domain"
        or value["source"] != "CertStream"
        or observed_at is None
        or domain is None
        or registrable_domain is None
        or not (domain == registrable_domain or domain.endswith(f".{registrable_domain}"))
        or not isinstance(value["id"], str)
        or not CANDIDATE_ID.fullmatch(value["id"])
        or value["id"] != stable_id(domain)
        or not _bounded_text(value["brand"], MAXIMUM_BRAND_CHARACTERS)
        or type(value["confidence"]) is not int
        or not 0 <= value["confidence"] <= 100
        or not isinstance(reasons, list)
        or not 1 <= len(reasons) <= MAXIMUM_REASONS
        or not all(_bounded_text(reason, MAXIMUM_REASON_CHARACTERS) for reason in reasons)
        or value.get("collectionMethod", "certstream-live") not in {"certstream-live", "ct-search-api"}
        or (
            "certificate" in value
            and (
                not _is_certificate(value["certificate"])
                or not _certificate_has_only_related_sans(value["certificate"], registrable_domain)
            )
        )
    ):
        return False
    if "sourceTimeEvidence" in value:
        try:
            validate_source_time_evidence(value["sourceTimeEvidence"], first_seen=value["observedAt"],
                                          last_seen=value["observedAt"], source="CertStream")
        except ValueError:
            return False
    return expected_day is None or vilnius_date(observed_at) == expected_day


def _attempt_identity(value: dict[str, object]) -> str:
    payload = {key: value[key] for key in ATTEMPT_FIELDS if key != "id"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _is_counter(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2_000_000_000


def _is_seconds(value: object) -> bool:
    if type(value) not in {int, float}:
        return False
    return 0 <= float(cast(int | float, value)) <= 86_400


def _is_attempt(value: Any, expected_day: str | None = None) -> bool:
    if not isinstance(value, dict) or set(value) != ATTEMPT_FIELDS:
        return False
    started_at = _timestamp(value["collectorStartedAt"])
    ended_at = _timestamp(value["endedAt"])
    if (
        started_at is None
        or ended_at is None
        or ended_at < started_at
        or value["outcome"] not in {"healthy-empty", "healthy-matches"}
        or not _is_seconds(value["expectedListeningSeconds"])
        or not _is_seconds(value["listeningSeconds"])
        or not all(_is_counter(value[field]) for field in ("messages", "dnsNames", "matches", "newRecords"))
        or value["dnsNames"] < value["matches"]
        or value["matches"] < value["newRecords"]
        or (value["outcome"] == "healthy-empty" and value["matches"] != 0)
        or (value["outcome"] == "healthy-matches" and value["matches"] == 0)
        or not isinstance(value["id"], str)
        or not ATTEMPT_ID.fullmatch(value["id"])
        or value["id"] != _attempt_identity(value)
    ):
        return False
    return expected_day is None or vilnius_date(ended_at) == expected_day


def _archive_bytes(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError(f"Candidate archive exceeds 25 MiB: {path}")
    body = path.read_bytes()
    if len(body) > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError(f"Candidate archive exceeds 25 MiB: {path}")
    return body


def _partition_day(path: Path) -> str | None:
    return path.parent.name if path.name == "domains.ndjson" and _valid_day(path.parent.name) else None


def read_candidate_file(path: Path, maximum: int = MAXIMUM_ARCHIVE_RECORDS) -> list[CertStreamCandidate]:
    try:
        body = _archive_bytes(path)
    except FileNotFoundError:
        return []
    limit = max(0, min(maximum, MAXIMUM_ARCHIVE_RECORDS))
    if limit == 0:
        return []
    expected_day = _partition_day(path)
    records: list[CertStreamCandidate] = []
    for raw_line in body.splitlines():
        if len(raw_line) > MAXIMUM_CANDIDATE_LINE_BYTES:
            continue
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not line.strip():
            continue
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _is_candidate(value, expected_day):
            records.append(value)
        if len(records) >= limit:
            break
    return records


def read_attempt_file(path: Path, maximum: int = MAXIMUM_DAILY_ATTEMPTS) -> list[dict[str, object]]:
    try:
        if path.stat().st_size > MAXIMUM_ATTEMPT_ARCHIVE_BYTES:
            raise ValueError(f"Collection-attempt archive exceeds 256 KiB: {path}")
        body = path.read_bytes()
    except FileNotFoundError:
        return []
    if len(body) > MAXIMUM_ATTEMPT_ARCHIVE_BYTES:
        raise ValueError(f"Collection-attempt archive exceeds 256 KiB: {path}")
    limit = max(0, min(maximum, MAXIMUM_DAILY_ATTEMPTS))
    if limit == 0:
        return []
    expected_day = path.parent.name if path.name == "attempts.ndjson" and _valid_day(path.parent.name) else None
    records: list[dict[str, object]] = []
    for raw_line in body.splitlines():
        if len(raw_line) > MAXIMUM_ATTEMPT_LINE_BYTES:
            continue
        try:
            value: Any = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if _is_attempt(value, expected_day):
            records.append(value)
        if len(records) >= limit:
            break
    return records


def record_successful_attempt(
    root: str | Path,
    *,
    collector_started_at: datetime,
    ended_at: datetime,
    expected_listening_seconds: int,
    listening_seconds: float,
    messages: int,
    dns_names: int,
    matches: int,
    new_records: int,
    outcome: str,
) -> Path:
    """Record one successful sampled window without implying full-day CT coverage."""

    started = _aware(collector_started_at).astimezone(UTC)
    ended = _aware(ended_at).astimezone(UTC)
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "collectorStartedAt": started.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "endedAt": ended.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "expectedListeningSeconds": expected_listening_seconds,
        "listeningSeconds": round(max(0.0, listening_seconds), 3),
        "messages": messages,
        "dnsNames": dns_names,
        "matches": matches,
        "newRecords": new_records,
        "outcome": outcome,
    }
    attempt = {"id": _attempt_identity(payload), **payload}
    day = vilnius_date(ended)
    if not _is_attempt(attempt, day):
        raise ValueError("Refusing to archive invalid CertStream attempt metadata.")

    path = _attempt_path(root, day)
    existing = read_attempt_file(path)
    if any(record["id"] == attempt["id"] for record in existing):
        return path
    if len(existing) >= MAXIMUM_DAILY_ATTEMPTS:
        raise ValueError("Collection-attempt archive reached its daily record limit.")
    records = sorted([*existing, attempt], key=lambda record: (str(record["endedAt"]), str(record["id"])))
    body = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    if len(body.encode("utf-8")) > MAXIMUM_ATTEMPT_ARCHIVE_BYTES:
        raise ValueError("Collection-attempt archive exceeds 256 KiB.")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return path


def _repair_final_line(path: Path, expected_day: str) -> None:
    try:
        body = _archive_bytes(path)
    except FileNotFoundError:
        return
    if not body or body.endswith(b"\n"):
        return

    boundary = body.rfind(b"\n") + 1
    tail = body[boundary:]
    complete = False
    if len(tail) <= MAXIMUM_CANDIDATE_LINE_BYTES:
        try:
            value: Any = json.loads(tail.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        else:
            complete = _is_candidate(value, expected_day)

    if complete:
        if len(body) + 1 > MAXIMUM_ARCHIVE_BYTES:
            raise ValueError(f"Candidate archive exceeds 25 MiB: {path}")
        descriptor = os.open(path, os.O_APPEND | os.O_WRONLY)
        try:
            os.write(descriptor, b"\n")
        finally:
            os.close(descriptor)
        return

    with path.open("r+b") as stream:
        stream.truncate(boundary)


class CandidateArchiveWriter:
    def __init__(self, root: str | Path) -> None:
        self._root = root
        self._known_by_day: dict[str, set[str]] = {}
        self._record_count_by_day: dict[str, int] = {}

    def append(self, records: list[CertStreamCandidate]) -> int:
        groups: dict[str, list[CertStreamCandidate]] = {}
        for record in records:
            if not _is_candidate(record):
                raise ValueError("Refusing to archive an invalid CertStream candidate.")
            observed = _timestamp(record["observedAt"])
            if observed is None:
                raise ValueError("Refusing to archive a candidate with an invalid observedAt timestamp.")
            groups.setdefault(vilnius_date(observed), []).append(record)

        written = 0
        for day, candidates in groups.items():
            path = _candidate_path(self._root, day)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _repair_final_line(path, day)
                known = self._known_by_day.get(day)
                if known is None:
                    existing = read_candidate_file(path, maximum=MAXIMUM_ARCHIVE_RECORDS)
                    known = {
                        f"{candidate['id']}:{candidate.get('collectionMethod', 'certstream-live')}"
                        for candidate in existing
                    }
                    self._known_by_day[day] = known
                    self._record_count_by_day[day] = len(existing)
                existing_records = self._record_count_by_day[day]
                queued: set[str] = set()
                unique: list[CertStreamCandidate] = []
                for candidate in candidates:
                    archive_key = f"{candidate['id']}:{candidate.get('collectionMethod', 'certstream-live')}"
                    if archive_key not in known and archive_key not in queued:
                        queued.add(archive_key)
                        unique.append(candidate)
                if not unique:
                    continue
                existing_size = path.stat().st_size if path.exists() else 0
                remaining_records = max(0, MAXIMUM_ARCHIVE_RECORDS - existing_records)
                if len(unique) > remaining_records:
                    raise ValueError("CertStream candidate archive reached its daily record limit.")
                lines: list[str] = []
                written_ids: list[str] = []
                projected_size = existing_size
                for candidate in unique:
                    line = json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n"
                    line_size = len(line.encode("utf-8"))
                    if line_size > MAXIMUM_CANDIDATE_LINE_BYTES:
                        raise ValueError("CertStream candidate exceeds the maximum NDJSON line size.")
                    if projected_size + line_size > MAXIMUM_ARCHIVE_BYTES:
                        raise ValueError("CertStream candidate archive reached its daily byte limit.")
                    lines.append(line)
                    written_ids.append(
                        f"{candidate['id']}:{candidate.get('collectionMethod', 'certstream-live')}"
                    )
                    projected_size += line_size
                descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as stream:
                    stream.writelines(lines)
                known.update(written_ids)
                self._record_count_by_day[day] += len(lines)
                written += len(lines)
            except OSError:
                raise
        return written


def append_candidates(root: str | Path, records: list[CertStreamCandidate]) -> int:
    return CandidateArchiveWriter(root).append(records)


def read_recent_candidates(
    root: str | Path,
    lookback_days: int,
    now: datetime,
    maximum: int = 25_000,
) -> list[CertStreamCandidate]:
    archive_root = _bounded_root(root)
    try:
        directories = sorted(
            (entry.name for entry in archive_root.iterdir() if entry.is_dir() and _valid_day(entry.name)),
            reverse=True,
        )
    except FileNotFoundError:
        return []
    today = _aware(now).astimezone(VILNIUS).date()
    permitted = {(today - timedelta(days=offset)).isoformat() for offset in range(lookback_days)}
    results: list[CertStreamCandidate] = []
    for day in (value for value in directories if value in permitted):
        remaining = maximum - len(results)
        if remaining <= 0:
            break
        results.extend(read_candidate_file(_candidate_path(root, day), remaining))
    return results


def _valid_day(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
