"""Durable, bounded observation facts, independent of expiring public history.

The index commits a complete content-addressed cohort. Replayed annotations do
not create observations; eligibility and analyst verdicts never erase facts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from importlib import metadata, resources
from pathlib import Path
from typing import TypedDict, cast

import idna

from .brands import EXTRACT, normalize_domain
from .safety import defang_host, stable_id

STORE_VERSION = "radar-observation-store-v1"
IDENTITY_VERSION = f"canonical-hostname-idna-{metadata.version('idna')}-uts46-nontransitional-v1"
INDEX_RELATIVE = Path("data/history/observations/index.json")
MAXIMUM_PART_BYTES = 256 * 1024
MAXIMUM_INDEX_BYTES = 256 * 1024
MAXIMUM_PARTS = 512
MAXIMUM_TOTAL_BYTES = 128 * 1024 * 1024
MAXIMUM_ANNOTATION_BYTES = 16 * 1024
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
PART_PATH = re.compile(r"(?:months/\d{4}-\d{2}|hosts)/[a-f0-9]{64}\.json")
MATCH_KEYS = {"brand", "score", "reasonCodes", "policyVersion", "legacyEventId", "legacyConfidence",
              "status", "previousStatus"}


class ObservationInput(TypedDict):
    domain: str
    sources: list[str]
    sourceObservedAt: str
    sourceTimeProvenance: str
    radarRecordedAt: str | None
    importedAt: str | None
    providerEventId: str | None
    originalMatch: dict[str, object] | None
    assessment: dict[str, object] | None
    provenance: list[dict[str, object]]


class ObservationRecord(TypedDict):
    observationId: str
    hostnameId: str
    domain: str
    domainGroup: str
    sources: list[str]
    sourceObservedAt: str
    sourceTimeProvenances: list[str]
    radarRecordedAt: str | None
    importedAt: str | None
    providerEventId: str | None
    matchAnnotations: list[dict[str, object]]
    assessments: list[dict[str, object]]
    provenance: list[dict[str, object]]


class StoreUpdate(TypedDict):
    addedObservations: int
    addedHostnames: int
    observationCount: int
    hostnameCount: int
    indexSha256: str


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or TIMESTAMP.fullmatch(value) is None:
        raise ValueError("Observation timestamps must be canonical UTC milliseconds.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid observation timestamp.") from error
    if parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ValueError("Noncanonical observation timestamp.")
    return value


def grouping_metadata() -> dict[str, object]:
    snapshot = resources.files("tldextract").joinpath(".tld_set_snapshot").read_bytes()
    return {"method": "private-psl-registrable-domain", "version": f"tldextract-{metadata.version('tldextract')}",
            "privateSuffixes": True, "pslSha256": hashlib.sha256(snapshot).hexdigest()}


def canonical_hostname(value: str) -> dict[str, str]:
    if not isinstance(value, str):
        raise ValueError("Observation hostname must be a string.")
    raw = normalize_domain(value.replace("[.]", "."))
    if raw is None:
        raise ValueError("Observation hostname is not a valid IDNA hostname.")
    domain = defang_host(raw)
    extracted = EXTRACT(raw)
    parent = extracted.top_domain_under_public_suffix or raw
    return {"id": stable_id(domain.lower()), "domain": domain, "domainGroup": defang_host(parent),
            "unicodeDomain": defang_host(idna.decode(raw)), "identityPolicyVersion": IDENTITY_VERSION}


def _strings(value: object, *, allow_empty: bool = False) -> list[str]:
    if (not isinstance(value, list) or (not value and not allow_empty)
            or any(not isinstance(item, str) or not item.strip() or len(item) > 512 for item in value)):
        raise ValueError("Invalid observation string list.")
    return sorted(set(cast(list[str], value)))


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Observation annotation must be an object.")
    try:
        body = encode(value)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("Observation annotation is not finite JSON.") from error
    if len(body) > MAXIMUM_ANNOTATION_BYTES:
        raise ValueError("Observation annotation exceeds its finite budget.")
    # Copy through JSON so caller mutation cannot alter an accepted fact.
    return cast(dict[str, object], json.loads(body))


def _match(value: object) -> dict[str, object]:
    result = _json_object(value)
    if not {"brand", "policyVersion"} <= result.keys() or result.keys() - MATCH_KEYS:
        raise ValueError("Invalid versioned match annotation fields.")
    for key in ("brand", "policyVersion"):
        if not isinstance(result[key], str) or not cast(str, result[key]).strip():
            raise ValueError("Match brand and policy version are required.")
    for key in ("score", "legacyConfidence"):
        score = result.get(key)
        if score is not None and (type(score) is not int or not 0 <= score <= 100):
            raise ValueError("Match scores must be nullable integers from zero to one hundred.")
    if "reasonCodes" in result:
        result["reasonCodes"] = _strings(result["reasonCodes"], allow_empty=True)
    for key in ("legacyEventId", "status", "previousStatus"):
        if result.get(key) is not None and not isinstance(result[key], str):
            raise ValueError("Invalid legacy match annotation.")
    return result


def _assessment(value: object) -> dict[str, object]:
    result = _json_object(value)
    if (set(result) != {"verdict", "assessedAt", "evidenceReferences", "decisionId", "analystConfidence"}
            or not isinstance(result["verdict"], str)
            or result["verdict"] not in {"malicious", "suspicious", "benign", "inconclusive"}):
        raise ValueError("Assessment requires an explicit dated analyst verdict.")
    decision = result["decisionId"]
    confidence = result["analystConfidence"]
    if (not isinstance(decision, str) or re.fullmatch(r"[a-f0-9]{24}", decision) is None
            or (confidence is not None and (type(confidence) is not int or not 0 <= confidence <= 100))):
        raise ValueError("Assessment decision identity or independent confidence is invalid.")
    validate_timestamp(result["assessedAt"])
    result["evidenceReferences"] = _strings(result["evidenceReferences"])
    return result


def observation_identity(domain: str, sources: Sequence[str], source_observed_at: str,
                         provider_event_id: str | None = None) -> str:
    host = canonical_hostname(domain)
    payload = {"hostnameId": host["id"], "sources": sorted(set(sources)),
               "sourceObservedAt": validate_timestamp(source_observed_at), "providerEventId": provider_event_id}
    return hashlib.sha256(encode(payload)).hexdigest()


def _record(value: ObservationInput) -> ObservationRecord:
    if not isinstance(value, dict) or set(value) != set(ObservationInput.__annotations__):
        raise ValueError("Invalid observation input fields.")
    host = canonical_hostname(value["domain"])
    sources = _strings(value["sources"])
    observed = validate_timestamp(value["sourceObservedAt"])
    for key in ("radarRecordedAt", "importedAt"):
        if value[key] is not None:
            validate_timestamp(value[key])
    origin = value["sourceTimeProvenance"]
    if not isinstance(origin, str) or not origin.strip() or len(origin) > 128:
        raise ValueError("Observation time provenance is required.")
    provider = value["providerEventId"]
    if provider is not None and (not isinstance(provider, str) or not provider.strip() or len(provider) > 512):
        raise ValueError("Invalid provider observation identity.")
    if not isinstance(value["provenance"], list):
        raise ValueError("Observation provenance must be a list.")
    return {
        "observationId": observation_identity(host["domain"], sources, observed, provider),
        "hostnameId": host["id"], "domain": host["domain"], "domainGroup": host["domainGroup"],
        "sources": sources, "sourceObservedAt": observed, "sourceTimeProvenances": [origin],
        "radarRecordedAt": value["radarRecordedAt"], "importedAt": value["importedAt"],
        "providerEventId": provider,
        "matchAnnotations": [] if value["originalMatch"] is None else [_match(value["originalMatch"])],
        "assessments": [] if value["assessment"] is None else [_assessment(value["assessment"])],
        "provenance": _unique([_json_object(item) for item in value["provenance"]]),
    }


def _unique(values: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    return [value for _, value in sorted({encode(value): value for value in values}.items())]


def _merge(existing: ObservationRecord, incoming: ObservationRecord) -> ObservationRecord:
    merged = cast(ObservationRecord, {**existing})
    for key in ("matchAnnotations", "assessments", "provenance"):
        merged[key] = _unique([*existing[key], *incoming[key]])
    merged["sourceTimeProvenances"] = sorted(set(existing["sourceTimeProvenances"] + incoming["sourceTimeProvenances"]))
    # Unknown historical recording time must not become the later replay time.
    times = (existing["radarRecordedAt"], incoming["radarRecordedAt"])
    merged["radarRecordedAt"] = None if None in times else min(cast(tuple[str, str], times))
    imported = [value for value in (existing["importedAt"], incoming["importedAt"]) if value is not None]
    merged["importedAt"] = min(imported) if imported else None
    return merged


def _regular(path: Path, root: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Observation path escapes the repository.")
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("Observation store refuses linked paths.")
        if item == root:
            break


def _validate_record(raw: object) -> ObservationRecord:
    if not isinstance(raw, dict) or set(raw) != set(ObservationRecord.__annotations__):
        raise ValueError("Invalid stored observation fields.")
    value = cast(ObservationRecord, raw)
    origins = _strings(value["sourceTimeProvenances"])
    if any(len(origin) > 128 for origin in origins):
        raise ValueError("Observation time provenance exceeds its finite budget.")
    if (not isinstance(value["matchAnnotations"], list) or not isinstance(value["assessments"], list)
            or not isinstance(value["provenance"], list)):
        raise ValueError("Stored observation annotations must be arrays.")
    base = _record({"domain": value["domain"], "sources": value["sources"],
                    "sourceObservedAt": value["sourceObservedAt"], "sourceTimeProvenance": origins[0],
                    "radarRecordedAt": value["radarRecordedAt"], "importedAt": value["importedAt"],
                    "providerEventId": value["providerEventId"], "originalMatch": None,
                    "assessment": None, "provenance": []})
    base["sourceTimeProvenances"] = origins
    base["matchAnnotations"] = _unique([_match(item) for item in value["matchAnnotations"]])
    base["assessments"] = _unique([_assessment(item) for item in value["assessments"]])
    base["provenance"] = _unique([_json_object(item) for item in value["provenance"]])
    if base != value:
        raise ValueError("Stored observation identity, canonical fields or ordering mismatch.")
    return base


def _read(repository: Path) -> tuple[list[ObservationRecord], list[dict[str, str]]]:
    index_path = repository / INDEX_RELATIVE
    _regular(index_path, repository)
    if not index_path.exists():
        return [], []
    if index_path.stat().st_size > MAXIMUM_INDEX_BYTES:
        raise ValueError("Observation index exceeds its finite budget.")
    index = json.loads(index_path.read_bytes())
    keys = {"schemaVersion", "dataset", "updatedAt", "identityPolicyVersion", "grouping", "observationCount",
            "hostnameCount", "partitions"}
    if (not isinstance(index, dict) or set(index) != keys or type(index["schemaVersion"]) is not int
            or index["schemaVersion"] != 1
            or index["dataset"] != STORE_VERSION or index["identityPolicyVersion"] != IDENTITY_VERSION
            or index["grouping"] != grouping_metadata()):
        raise ValueError("Invalid observation store index or identity policy.")
    validate_timestamp(index["updatedAt"])
    for key in ("observationCount", "hostnameCount"):
        if type(index[key]) is not int or index[key] < 0:
            raise ValueError("Invalid observation store count.")
    if not isinstance(index["partitions"], list) or len(index["partitions"]) > MAXIMUM_PARTS:
        raise ValueError("Observation store partition budget exceeded.")
    observations: list[ObservationRecord] = []
    hosts: list[dict[str, str]] = []
    seen: set[str] = set()
    total = 0
    for descriptor in index["partitions"]:
        if not isinstance(descriptor, dict) or set(descriptor) != {"path", "bytes", "sha256", "records", "kind"}:
            raise ValueError("Invalid observation partition descriptor.")
        relative, size, count = descriptor["path"], descriptor["bytes"], descriptor["records"]
        if (not isinstance(relative, str) or PART_PATH.fullmatch(relative) is None or relative in seen
                or type(size) is not int or not 0 < size <= MAXIMUM_PART_BYTES
                or type(count) is not int or count <= 0):
            raise ValueError("Invalid observation partition path or capacity.")
        expected_kind = "hostnames" if relative.startswith("hosts/") else "observations"
        if descriptor["kind"] != expected_kind:
            raise ValueError("Observation partition type mismatch.")
        target = index_path.parent / relative
        _regular(target, repository)
        if not target.is_file() or target.stat().st_size != size:
            raise ValueError("Observation partition is missing or has the wrong size.")
        body = target.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if descriptor["sha256"] != digest or target.stem != digest:
            raise ValueError("Observation partition digest mismatch.")
        rows = json.loads(body)
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError("Observation partition row count mismatch.")
        if expected_kind == "observations":
            for row in rows:
                validated = _validate_record(row)
                if validated["sourceObservedAt"][:7] != relative.split("/")[1]:
                    raise ValueError("Observation is in the wrong source-time month.")
                observations.append(validated)
        else:
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("domain"), str):
                    raise ValueError("Invalid canonical hostname inventory row.")
                canonical = canonical_hostname(row["domain"])
                if row != canonical:
                    raise ValueError("Canonical hostname inventory mismatch.")
                hosts.append(canonical)
        total += len(body)
        if total > MAXIMUM_TOTAL_BYTES:
            raise ValueError("Observation store byte budget exceeded.")
        seen.add(relative)
    if (len(observations) != index["observationCount"] or len(hosts) != index["hostnameCount"]
            or len({row["observationId"] for row in observations}) != len(observations)
            or len({row["id"] for row in hosts}) != len(hosts)):
        raise ValueError("Observation store cohort is incomplete or duplicated.")
    host_ids = {row["id"] for row in hosts}
    if {row["hostnameId"] for row in observations} != host_ids:
        raise ValueError("Observation facts and independent hostname inventory disagree.")
    return sorted(observations, key=lambda row: row["observationId"]), sorted(hosts, key=lambda row: row["id"])


def read_observations(repository: Path) -> list[ObservationRecord]:
    return _read(repository)[0]


def _chunks(rows: Sequence[object]) -> list[bytes]:
    chunks: list[bytes] = []
    current: list[bytes] = []
    size = 3
    for row in rows:
        body = encode(row).rstrip(b"\n")
        if len(body) + 3 > MAXIMUM_PART_BYTES:
            raise ValueError("One durable observation exceeds the bounded partition budget.")
        if current and size + len(body) + 1 > MAXIMUM_PART_BYTES:
            chunks.append(b"[" + b",".join(current) + b"]\n")
            current, size = [], 3
        current.append(body)
        size += len(body) + 1
    if current:
        chunks.append(b"[" + b",".join(current) + b"]\n")
    return chunks


def _atomic(path: Path, body: bytes, repository: Path) -> None:
    _regular(path, repository)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="observation-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def append_observations(repository: Path, observations: Sequence[ObservationInput], *, updated_at: str) -> StoreUpdate:
    validate_timestamp(updated_at)
    existing, old_hosts = _read(repository)
    by_id = {row["observationId"]: row for row in existing}
    for item in observations:
        row = _record(item)
        key = row["observationId"]
        by_id[key] = _merge(by_id[key], row) if key in by_id else row
    rows = sorted(by_id.values(), key=lambda row: row["observationId"])
    hosts = {row["hostnameId"]: canonical_hostname(row["domain"]) for row in rows}
    buckets: dict[str, list[ObservationRecord]] = {}
    for row in rows:
        buckets.setdefault(row["sourceObservedAt"][:7], []).append(row)
    partitions: list[dict[str, object]] = []
    bodies: dict[str, bytes] = {}
    partition_groups: list[tuple[str, str, Sequence[object]]] = [
        (f"months/{month}", "observations", bucket) for month, bucket in sorted(buckets.items())
    ]
    partition_groups.append(("hosts", "hostnames", [hosts[key] for key in sorted(hosts)]))
    for prefix, kind, bucket in partition_groups:
        for body in _chunks(bucket):
            digest = hashlib.sha256(body).hexdigest()
            relative = f"{prefix}/{digest}.json"
            bodies[relative] = body
            partitions.append({"path": relative, "bytes": len(body), "sha256": digest,
                               "records": len(json.loads(body)), "kind": kind})
    index = {"schemaVersion": 1, "dataset": STORE_VERSION, "updatedAt": updated_at,
             "identityPolicyVersion": IDENTITY_VERSION, "grouping": grouping_metadata(),
             "observationCount": len(rows), "hostnameCount": len(hosts), "partitions": partitions}
    index_body = encode(index)
    if (len(partitions) > MAXIMUM_PARTS or sum(map(len, bodies.values())) > MAXIMUM_TOTAL_BYTES
            or len(index_body) > MAXIMUM_INDEX_BYTES):
        raise ValueError("Durable observation store capacity exceeded; no facts were evicted.")
    index_path = repository / INDEX_RELATIVE
    for relative, body in bodies.items():
        target = index_path.parent / relative
        _regular(target, repository)
        if not target.exists() or target.read_bytes() != body:
            _atomic(target, body, repository)
    if not index_path.exists() or index_path.read_bytes() != index_body:
        _atomic(index_path, index_body, repository)
    # Current index retains every fact. Only obsolete generated encodings go;
    # earlier committed versions remain recoverable through Git.
    for folder in (index_path.parent / "months", index_path.parent / "hosts"):
        if not folder.exists():
            continue
        _regular(folder, repository)
        for target in folder.rglob("*.json"):
            relative = target.relative_to(index_path.parent).as_posix()
            if PART_PATH.fullmatch(relative) is not None and relative not in bodies:
                _regular(target, repository)
                target.unlink()
    return {"addedObservations": len(rows) - len(existing), "addedHostnames": len(hosts) - len(old_hosts),
            "observationCount": len(rows), "hostnameCount": len(hosts),
            "indexSha256": hashlib.sha256(index_body).hexdigest()}


def build_public_records(
    observations: Sequence[ObservationRecord], *, as_of: str,
    eligible_matches: Mapping[str, Mapping[str, object]], available_record_ids: Collection[str] = (),
    first_published_at: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    validate_timestamp(as_of)
    grouped: dict[str, list[ObservationRecord]] = {}
    for row in observations:
        if row["sourceObservedAt"] <= as_of and row["hostnameId"] in eligible_matches:
            grouped.setdefault(row["hostnameId"], []).append(row)
    result: list[dict[str, object]] = []
    for hostname_id, facts in sorted(grouped.items()):
        match = eligible_matches[hostname_id]
        annotation = _match({key: match[key] for key in ("brand", "score", "reasonCodes", "policyVersion")})
        assessment = match.get("assessment")
        assessment = None if assessment is None else _assessment(assessment)
        day_last: dict[str, str] = {}
        for fact in facts:
            observed = fact["sourceObservedAt"]
            day_last[observed[:10]] = max(day_last.get(observed[:10], observed), observed)
        recorded = [fact["radarRecordedAt"] for fact in facts]
        first_recorded = None if None in recorded else min(cast(list[str], recorded))
        if first_recorded is not None and first_recorded > as_of:
            first_recorded = None
        published = (first_published_at or {}).get(hostname_id)
        if published is not None:
            validate_timestamp(published)
            if published > as_of or first_recorded is None:
                published = None
        result.append({
            "id": hostname_id, "domain": facts[0]["domain"], "domainGroup": facts[0]["domainGroup"],
            "brand": annotation["brand"], "firstSeen": min(fact["sourceObservedAt"] for fact in facts),
            "lastSeen": max(fact["sourceObservedAt"] for fact in facts), "firstRecordedAt": first_recorded,
            "firstPublishedAt": published, "observedDays": sorted(day_last),
            "observedDayLastSeen": {day: day_last[day] for day in sorted(day_last)},
            "sources": sorted({source for fact in facts for source in fact["sources"]}),
            "match": {key: annotation[key] for key in ("score", "reasonCodes", "policyVersion")},
            "assessment": assessment, "recordAvailable": hostname_id in available_record_ids,
        })
    return result
