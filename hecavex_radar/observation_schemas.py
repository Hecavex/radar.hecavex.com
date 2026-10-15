"""Versioned public hostname/period contracts, independent of legacy snapshot v2."""

from __future__ import annotations

from typing import Any

BASE = "https://radar.hecavex.com/data/schemas/"
TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
DAY = r"^\d{4}-\d{2}-\d{2}$"
HEX20 = r"^[a-f0-9]{20}$"
HEX64 = r"^[a-f0-9]{64}$"
DOMAIN = r"^[a-z0-9-]+(?:\[\.\][a-z0-9-]+)+$"


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def text(pattern: str | None = None, *, nullable: bool = False, maximum: int = 160) -> dict[str, Any]:
    result: dict[str, Any] = {"type": ["string", "null"] if nullable else "string", "maxLength": maximum}
    if pattern:
        result["pattern"] = pattern
    return result


def dates() -> dict[str, Any]:
    return {"type": "array", "uniqueItems": True, "maxItems": 36600, "items": text(DAY)}


GROUPING_SCHEMA = obj({
    "method": {"const": "private-psl-registrable-domain"},
    "version": {"const": "tldextract-5.4.0"},
    "privateSuffixes": {"const": True}, "pslSha256": text(HEX64),
})
POLICY_VERSIONS_SCHEMA = obj({
    key: text() for key in ("identity", "matching", "review", "metrics", "store")
})
COVERAGE_SCHEMA = obj({
    "availableFrom": text(TIMESTAMP, nullable=True), "recordedFrom": text(TIMESTAMP, nullable=True),
    "publicationRecordedFrom": text(TIMESTAMP, nullable=True),
    "recoveredFrom": text(DAY, nullable=True), "recoveredThrough": text(DAY, nullable=True),
    "recoveredDays": dates(), "missingDays": dates(),
    **{key: {"type": "boolean"} for key in (
        "historyComplete", "collectionComplete", "historicalRecordingTimesComplete",
        "historicalPublicationTimesComplete", "partialCurrentDay",
    )},
    "basis": {"const": "recorded-and-recovered-observation-facts"},
})
ASSESSMENT_SCHEMA = obj({
    "verdict": {"enum": ["malicious", "suspicious", "benign", "inconclusive"]},
    "assessedAt": text(TIMESTAMP),
    "decisionId": text(r"^[a-f0-9]{24}$"),
    "analystConfidence": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
    "evidenceReferences": {
        "type": "array", "minItems": 1, "maxItems": 64, "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 512},
    },
})
HOSTNAME_RECORD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": BASE + "observed-hostname-v1.schema.json",
    "title": "HECAVEX Radar observed hostname v1",
    **obj({
        "id": text(HEX20), "domain": text(DOMAIN, maximum=512), "domainGroup": text(DOMAIN, maximum=512),
        "brand": {"type": "string", "minLength": 1, "maxLength": 120},
        "firstSeen": text(TIMESTAMP), "lastSeen": text(TIMESTAMP),
        "firstRecordedAt": text(TIMESTAMP, nullable=True), "firstPublishedAt": text(TIMESTAMP, nullable=True),
        "observedDays": dates(),
        "observedDayLastSeen": {
            "type": "object", "maxProperties": 36600, "propertyNames": text(DAY),
            "additionalProperties": text(TIMESTAMP),
        },
        "sources": {
            "type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
            "items": {"enum": ["CertStream", "URLScan", "HECAVEX"]},
        },
        "match": obj({
            "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
            "reasonCodes": {
                "type": "array", "uniqueItems": True, "maxItems": 32,
                "items": {"type": "string", "pattern": "^[a-z][a-z0-9-]{1,79}$"},
            },
            "policyVersion": text(),
        }),
        "assessment": {"anyOf": [{"type": "null"}, ASSESSMENT_SCHEMA]},
        "recordAvailable": {"type": "boolean"},
    }),
}
# Additive evidence: older committed v1 cohorts omit it and remain readable.
HOSTNAME_RECORD_SCHEMA["properties"]["sourceTimeProvenances"] = {
    "type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
    "items": {"enum": ["provider-observation-time", "collector-time-fallback", "legacy-normalized-unknown"]},
}
HOSTNAME_PART_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": BASE + "observed-hostname-part-v1.schema.json",
    "title": "HECAVEX Radar observed hostname partition v1",
    "type": "array", "minItems": 1, "maxItems": 25000,
    "items": HOSTNAME_RECORD_SCHEMA,
}
HOSTNAME_INDEX_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": BASE + "observed-hostnames-index-v1.schema.json",
    "title": "HECAVEX Radar complete observed-hostname index v1",
    **obj({
        "schemaVersion": {"const": 1}, "dataset": {"const": "radar-observed-hostnames"},
        "generatedAt": text(TIMESTAMP), "asOf": text(TIMESTAMP),
        "recordCount": {"type": "integer", "minimum": 0, "maximum": 25000},
        "coverage": COVERAGE_SCHEMA, "policyVersions": POLICY_VERSIONS_SCHEMA, "grouping": GROUPING_SCHEMA,
        "partitions": {
            "type": "array", "maxItems": 512,
            "items": obj({
                "path": text(r"^/data/observed-hostnames-parts/[a-f0-9]{64}\.json$", maximum=150),
                "bytes": {"type": "integer", "minimum": 1, "maximum": 262144},
                "sha256": text(HEX64), "records": {"type": "integer", "minimum": 1, "maximum": 25000},
            }),
        },
    }),
}
PERIOD_WINDOW_SCHEMA = obj({
    "key": text(r"^(30d|90d|365d|all|month:\d{4}-\d{2}|year:\d{4})$"),
    "startInclusive": text(TIMESTAMP, nullable=True), "endExclusive": text(TIMESTAMP),
    **{key: {"type": "integer", "minimum": 0, "maximum": 2147483647}
       for key in ("uniqueHostnames", "domainGroups", "candidateDays")},
    **{key: {"type": ["integer", "null"], "minimum": 0, "maximum": 25000}
       for key in ("firstRecordedHostnames", "firstPublishedHostnames")},
    "exactWithinRecordedData": {"const": True}, "completeCollection": {"type": "boolean"},
})
PERIOD_METRICS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": BASE + "period-metrics-v1.schema.json",
    "title": "HECAVEX Radar period-distinct recorded hostname metrics v1",
    **obj({
        "schemaVersion": {"const": 1}, "dataset": {"const": "radar-period-metrics"},
        "generatedAt": text(TIMESTAMP), "asOf": text(TIMESTAMP),
        "timeBasis": {"enum": [
            "source-observation-time", "source-observation-or-explicit-collector-fallback",
        ]}, "identityUnit": {"const": "canonical-hostname"},
        "population": {"const": "public-eligible-recorded-hostnames"}, "hostnamesSha256": text(HEX64),
        "grouping": GROUPING_SCHEMA, "coverage": COVERAGE_SCHEMA, "policyVersions": POLICY_VERSIONS_SCHEMA,
        "windows": {"type": "array", "minItems": 4, "maxItems": 10000, "items": PERIOD_WINDOW_SCHEMA},
    }),
}
