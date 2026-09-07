"""Versioned JSON Schemas for Radar's generated public artifacts."""

from __future__ import annotations

from typing import Final

SCHEMA_BASE: Final = "https://radar.hecavex.com/data/schemas/"
TIMESTAMP_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
HEX20_PATTERN: Final = r"^[a-f0-9]{20}$"
SHA256_PATTERN: Final = r"^[a-f0-9]{64}$"
NONEMPTY_SHA256_PATTERN: Final = (
    r"^(?!e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855$)[a-f0-9]{64}$"
)
DOMAIN_LABEL_PATTERN: Final = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
DOMAIN_SUFFIX_PATTERN: Final = r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})"
DEFANGED_DOMAIN_PATTERN: Final = (
    rf"^(?:{DOMAIN_LABEL_PATTERN}\[\.\])+(?:{DOMAIN_SUFFIX_PATTERN})$"
)
DEFANGED_URL_PATTERN: Final = (
    rf"^hxxps?://(?:{DOMAIN_LABEL_PATTERN}\[\.\])+(?:{DOMAIN_SUFFIX_PATTERN})"
    r"(?::[0-9]{1,5})?(?:/[A-Za-z0-9%:@!$&'()*+,;=._~\[\]/-]*)?$"
)
RAW_DOMAIN_PATTERN: Final = (
    rf"^(?:{DOMAIN_LABEL_PATTERN}\.)+(?:{DOMAIN_SUFFIX_PATTERN})$"
)
UUID_PATTERN: Final = r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
URLSCAN_SCREENSHOT_PATTERN: Final = (
    r"^https://urlscan\.io/screenshots/[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}\.png$"
)
URLSCAN_RESULT_PATTERN: Final = (
    r"^https://urlscan\.io/result/[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}/$"
)
REASON_CODES: Final = (
    "brand-domain-match",
    "brand-title-match",
    "provider-verdict",
    "primary-html-hash-pivot",
    "brand-exact-token",
    "brand-joined-affix",
    "brand-split-token",
    "brand-lookalike-edit",
    "suspicious-context",
    "punycode",
    "different-tld",
    "multiple-hyphens",
    "unicode-confusable",
    "mixed-script",
    "restricted-identifier",
    "hecavex-public-export",
    "manual-review",
    "first-publication",
    "source-status-change",
)
SOURCE_HOMEPAGES: Final = {
    "CertStream": "https://certstream.dev/",
    "URLScan": "https://urlscan.io/",
    "HECAVEX": "https://hecavex.com/",
}


def _base(name: str, title: str) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE}{name}",
        "title": title,
        "type": "object",
    }


def _signal_definition() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
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
            "matchScore",
            "evidenceTier",
            "reviewState",
            "ltRelevance",
            "confidence",
        ],
        "properties": {
            "id": {"type": "string", "pattern": HEX20_PATTERN},
            "url": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2048,
                "pattern": DEFANGED_URL_PATTERN,
            },
            "domain": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
                "pattern": DEFANGED_DOMAIN_PATTERN,
            },
            "firstSeen": {"type": "string", "pattern": TIMESTAMP_PATTERN},
            "lastSeen": {"type": "string", "pattern": TIMESTAMP_PATTERN},
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "uniqueItems": True,
                "items": {"enum": ["CertStream", "URLScan", "HECAVEX"]},
            },
            "status": {"enum": ["active", "suspected", "offline", "mitigated", "unknown"]},
            "brand": {"type": ["string", "null"], "maxLength": 120},
            "country": {"type": ["string", "null"], "maxLength": 80},
            "host": {"type": ["string", "null"], "maxLength": 160},
            "screenshotUrl": {
                "type": ["string", "null"],
                "maxLength": 2048,
                "pattern": URLSCAN_SCREENSHOT_PATTERN,
            },
            "referenceUrl": {
                "type": ["string", "null"],
                "maxLength": 2048,
                "pattern": URLSCAN_RESULT_PATTERN,
            },
            "hashes": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": NONEMPTY_SHA256_PATTERN},
            },
            "brandEvidence": {
                "type": "array",
                "maxItems": 4,
                "uniqueItems": True,
                "items": {"enum": ["domain", "title", "verdict", "primary-html-sha256"]},
            },
            "reasonCodes": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": {"enum": list(REASON_CODES)},
            },
            "discoveredVia": {
                "type": "array",
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "certstream-live",
                        "ct-search-api",
                        "urlscan-public-report",
                        "hecavex-public-export",
                        "hecavex-review",
                    ]
                },
            },
            "corroboratedBy": {
                "type": "array",
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "urlscan-public-report",
                        "urlscan-page-title",
                        "urlscan-provider-verdict",
                        "urlscan-primary-html-sha256",
                        "analyst-review",
                    ]
                },
            },
            "detailAvailable": {"const": True},
            "matchScore": {"type": "integer", "minimum": 0, "maximum": 100},
            "evidenceTier": {"enum": ["name-only", "corroborated", "reviewed"]},
            "reviewState": {
                "enum": [
                    "unreviewed",
                    "needs-review",
                    "confirmed-suspicious",
                    "false-positive",
                    "benign-brand-reference",
                    "inconclusive",
                ]
            },
            "ltRelevance": {
                "enum": [
                    "lithuanian-targeting",
                    "lithuanian-brand-relevance",
                    "global-brand-reference",
                    "unknown",
                ]
            },
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    }


RADAR_SCHEMA: Final[dict[str, object]] = {
    **_base("radar-v2.schema.json", "HECAVEX Radar live snapshot v2"),
    "additionalProperties": False,
    "required": ["schemaVersion", "dataset", "generatedAt", "lastSuccessfulSyncAt", "signals", "sources"],
    "properties": {
        "schemaVersion": {"const": 2},
        "dataset": {"const": "live"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "lastSuccessfulSyncAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "signals": {"type": "array", "maxItems": 25000, "items": {"$ref": "#/$defs/signal"}},
        "sources": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {"$ref": "#/$defs/source"},
        },
    },
    "$defs": {
        "signal": _signal_definition(),
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "homepage", "fetchedAt", "records", "state", "note"],
            "properties": {
                "name": {"enum": ["CertStream", "URLScan", "HECAVEX"]},
                "homepage": {"type": "string", "minLength": 1, "maxLength": 2048},
                "fetchedAt": {"anyOf": [{"type": "null"}, {"type": "string", "pattern": TIMESTAMP_PATTERN}]},
                "records": {"type": "integer", "minimum": 0, "maximum": 25000},
                "state": {"enum": ["healthy", "partial", "skipped"]},
                "note": {"type": ["string", "null"], "maxLength": 240},
            },
            "allOf": [
                {
                    "if": {"properties": {"name": {"const": name}}, "required": ["name"]},
                    "then": {"properties": {"homepage": {"const": homepage}}},
                }
                for name, homepage in SOURCE_HOMEPAGES.items()
            ],
        },
    },
}


RADAR_SHARD_SCHEMA: Final[dict[str, object]] = {
    **_base("radar-shard-v1.schema.json", "HECAVEX Radar signal shard v1"),
    "additionalProperties": False,
    "required": ["schemaVersion", "dataset", "generatedAt", "shard", "signals"],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-signal-shard"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "shard": {"type": "integer", "minimum": 1, "maximum": 9999},
        "signals": {"type": "array", "minItems": 1, "maxItems": 25000, "items": {"$ref": "#/$defs/signal"}},
    },
    "$defs": {"signal": _signal_definition()},
}


RADAR_INDEX_SCHEMA: Final[dict[str, object]] = {
    **_base("radar-index-v1.schema.json", "HECAVEX Radar shard index v1"),
    "additionalProperties": False,
    "required": [
        "schemaVersion",
        "dataset",
        "generatedAt",
        "signalCount",
        "dashboardSignalCount",
        "shards",
    ],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-signal-index"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "signalCount": {"type": "integer", "minimum": 0, "maximum": 25000},
        "dashboardSignalCount": {"type": "integer", "minimum": 0, "maximum": 25000},
        "shards": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["number", "path", "signals", "bytes", "sha256", "firstSignalId", "lastSignalId"],
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "path": {"type": "string", "pattern": "^/data/radar-shards/[0-9]{4}\\.json$"},
                    "signals": {"type": "integer", "minimum": 1},
                    "bytes": {"type": "integer", "minimum": 1, "maximum": 262144},
                    "sha256": {"type": "string", "pattern": SHA256_PATTERN},
                    "firstSignalId": {"type": "string", "pattern": HEX20_PATTERN},
                    "lastSignalId": {"type": "string", "pattern": HEX20_PATTERN},
                },
            },
        },
    },
}


PIPELINE_HEALTH_SCHEMA: Final[dict[str, object]] = {
    **_base("pipeline-health-v1.schema.json", "HECAVEX Radar rolling pipeline health v1"),
    "$defs": {
        "counter": {"type": "integer", "minimum": 0, "maximum": 2_000_000_000},
        "timestampOrNull": {"type": ["string", "null"], "pattern": TIMESTAMP_PATTERN},
        "sourceStates": {
            "type": "object",
            "additionalProperties": False,
            "required": ["CertStream", "URLScan", "HECAVEX"],
            "properties": {
                name: {"enum": ["healthy", "partial", "skipped"]}
                for name in ("CertStream", "URLScan", "HECAVEX")
            },
        },
        "sourceRecords": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                name: {"$ref": "#/$defs/counter"}
                for name in ("CertStream", "URLScan", "HECAVEX")
            },
        },
        "certstreamSummary": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generatedAt", "lastSuccessAt", "freshness", "latestAttempt"],
            "properties": {
                "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "lastSuccessAt": {"$ref": "#/$defs/timestampOrNull"},
                "freshness": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "referenceAt", "ageSeconds"],
                    "properties": {
                        "status": {"enum": ["current", "stale", "unavailable"]},
                        "referenceAt": {"$ref": "#/$defs/timestampOrNull"},
                        "ageSeconds": {"type": ["number", "null"], "minimum": 0, "maximum": 31_536_000},
                    },
                },
                "latestAttempt": {
                    "anyOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "startedAt", "endedAt", "outcome", "listeningSeconds",
                                "messages", "dnsNames", "matches", "newRecords",
                            ],
                            "properties": {
                                "startedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                                "endedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                                "outcome": {
                                    "enum": ["healthy-empty", "healthy-matches", "no-input", "partial", "failed"]
                                },
                                "listeningSeconds": {"type": "number", "minimum": 0, "maximum": 86_400},
                                "messages": {"$ref": "#/$defs/counter"},
                                "dnsNames": {"$ref": "#/$defs/counter"},
                                "matches": {"$ref": "#/$defs/counter"},
                                "newRecords": {"$ref": "#/$defs/counter"},
                            },
                        },
                    ]
                },
            },
        },
        "urlscanSummary": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generatedAt", "configured", "lastOutcome", "lastAttemptAt", "checkpointCoverage"],
            "properties": {
                "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "configured": {"type": "boolean"},
                "lastOutcome": {"enum": ["skipped-not-configured", "completed", "budget-limited", "failed"]},
                "lastFailureCode": {"enum": [
                    "unknown", "state-capacity", "state-invalid", "provider-rate-limit", "provider-error",
                ]},
                "lastAttemptAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "checkpointCoverage": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["queries", "complete", "partial", "backlog", "oldestBacklogProgressAt"],
                    "properties": {
                        "queries": {"type": "integer", "minimum": 0, "maximum": 256},
                        "complete": {"type": "integer", "minimum": 0, "maximum": 256},
                        "partial": {"type": "integer", "minimum": 0, "maximum": 256},
                        "backlog": {"type": "integer", "minimum": 0, "maximum": 256},
                        "oldestBacklogProgressAt": {"$ref": "#/$defs/timestampOrNull"},
                    },
                },
            },
        },
        "ctSearchSummary": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generatedAt", "latestRun"],
            "properties": {
                "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "provider": {"const": "crt.sh"},
                "providerHealth": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "lastSuccessAt", "lastAttemptAt", "lastFailureCodes", "consecutiveFailures",
                        "degradedSince", "nextAttemptAt",
                    ],
                    "properties": {
                        **{field: {"$ref": "#/$defs/timestampOrNull"} for field in (
                            "lastSuccessAt", "lastAttemptAt", "degradedSince", "nextAttemptAt",
                        )},
                        "consecutiveFailures": {"$ref": "#/$defs/counter"},
                        "lastFailureCodes": {
                            "type": "array", "maxItems": 8, "uniqueItems": True,
                            "items": {"enum": [
                                "provider-timeout", "provider-http", "provider-network", "invalid-response",
                                "validation", "internal",
                            ]},
                        },
                    },
                },
                "latestRun": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "startedAt", "endedAt", "outcome", "queriesAttempted", "queriesCompleted",
                        "queriesBacklogged", "rowsProcessed", "dnsNames", "matches", "newRecords",
                        "failureCodes",
                    ],
                    "properties": {
                        "startedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                        "endedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                        "outcome": {"enum": ["completed", "partial", "failed", "deferred-backoff"]},
                        "failureCodes": {
                            "type": "array",
                            "maxItems": 8,
                            "uniqueItems": True,
                            "items": {
                                "enum": [
                                    "provider-timeout",
                                    "provider-http",
                                    "provider-network",
                                    "invalid-response",
                                    "validation",
                                    "internal",
                                ]
                            },
                        },
                        **{
                            field: {"$ref": "#/$defs/counter"}
                            for field in (
                                "queriesAttempted", "queriesCompleted", "queriesBacklogged", "rowsProcessed",
                                "dnsNames", "matches", "newRecords",
                            )
                        },
                    },
                },
            },
        },
        "domainContextSummary": {
            "type": "object",
            "additionalProperties": False,
            "required": ["generatedAt", "latestRun", "recordCount"],
            "properties": {
                "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "recordCount": {"type": "integer", "minimum": 0, "maximum": 25_000},
                "latestRun": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["startedAt", "endedAt", "outcome", "attempted", "completed"],
                    "properties": {
                        "startedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                        "endedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                        "outcome": {"enum": ["completed", "partial", "failed", "empty"]},
                        "attempted": {"$ref": "#/$defs/counter"},
                        "completed": {"$ref": "#/$defs/counter"},
                    },
                },
            },
        },
        "collectionOutcomes": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                outcome: {"$ref": "#/$defs/counter"}
                for outcome in ("healthy-empty", "healthy-matches", "no-input", "partial", "failed")
            },
        },
        "sourceCounts": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                source: {"$ref": "#/$defs/counter"}
                for source in ("CertStream", "URLScan", "HECAVEX")
            },
        },
    },
    "additionalProperties": False,
    "required": ["schemaVersion", "dataset", "generatedAt", "privacy", "current", "windows"],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-pipeline-health"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "privacy": {"const": "Aggregate counters only; no candidate names or detector payloads."},
        "current": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "publishedSignals", "sourceStates", "sourceRecords", "certstream", "urlscan", "ctSearch",
                "domainContext",
            ],
            "properties": {
                "publishedSignals": {"type": "integer", "minimum": 0, "maximum": 25_000},
                "sourceStates": {"$ref": "#/$defs/sourceStates"},
                "sourceRecords": {"$ref": "#/$defs/sourceRecords"},
                "certstream": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/certstreamSummary"}]},
                "urlscan": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/urlscanSummary"}]},
                "ctSearch": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/ctSearchSummary"}]},
                "domainContext": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/domainContextSummary"}]},
            },
        },
        "windows": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["hours", "from", "to", "collection", "screening", "enrichment", "publication"],
                "properties": {
                    "hours": {"enum": [24, 168]},
                    "from": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                    "to": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                    "collection": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "scheduledSlots", "recordedAttempts", "healthyAttempts", "recordedSchedulePercent",
                            "listeningCoveragePercent", "scheduledListeningCeilingPercent", "expectedListeningSeconds",
                            "listeningSeconds", "messages", "dnsNames", "outcomes",
                        ],
                        "properties": {
                            **{
                                field: {"$ref": "#/$defs/counter"}
                                for field in (
                                    "scheduledSlots", "recordedAttempts", "healthyAttempts",
                                    "expectedListeningSeconds", "messages", "dnsNames",
                                )
                            },
                            "recordedSchedulePercent": {"type": "number", "minimum": 0, "maximum": 100},
                            "listeningCoveragePercent": {"type": "number", "minimum": 0, "maximum": 100},
                            "scheduledListeningCeilingPercent": {"type": "number", "minimum": 0, "maximum": 100},
                            "listeningSeconds": {"type": "number", "minimum": 0, "maximum": 604_800},
                            "outcomes": {"$ref": "#/$defs/collectionOutcomes"},
                        },
                    },
                    "screening": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["matches", "newArchiveRecords", "firstPublications", "bySource"],
                        "properties": {
                            "matches": {"$ref": "#/$defs/counter"},
                            "newArchiveRecords": {"$ref": "#/$defs/counter"},
                            "firstPublications": {"$ref": "#/$defs/counter"},
                            "bySource": {"$ref": "#/$defs/sourceCounts"},
                        },
                    },
                    "enrichment": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "observations", "uniqueSignals", "page", "network", "assessment", "certificate", "dns",
                            "rdap",
                        ],
                        "properties": {
                            field: {"$ref": "#/$defs/counter"}
                            for field in (
                                "observations", "uniqueSignals", "page", "network", "assessment", "certificate",
                                "dns", "rdap",
                            )
                        },
                    },
                    "publication": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["events", "observations", "statusTransitions", "uniqueSignals"],
                        "properties": {
                            field: {"$ref": "#/$defs/counter"}
                            for field in ("events", "observations", "statusTransitions", "uniqueSignals")
                        },
                    },
                },
            },
        },
    },
}


MISP_EVENT_SCHEMA: Final[dict[str, object]] = {
    **_base("misp-event-v1.schema.json", "Reviewed-only MISP event"),
    "additionalProperties": False,
    "required": ["Event"],
    "$defs": {
        "tag": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120}},
        },
        "org": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "uuid"],
            "properties": {
                "name": {"const": "HECAVEX"},
                "uuid": {"type": "string", "pattern": UUID_PATTERN},
            },
        },
        "attribute": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "uuid",
                "type",
                "category",
                "to_ids",
                "distribution",
                "value",
                "comment",
                "timestamp",
                "Tag",
            ],
            "properties": {
                "uuid": {"type": "string", "pattern": UUID_PATTERN},
                "type": {"const": "domain"},
                "category": {"const": "Network activity"},
                "to_ids": {"const": False},
                "distribution": {"const": "3"},
                "value": {"type": "string", "pattern": RAW_DOMAIN_PATTERN, "maxLength": 253},
                "comment": {"type": "string", "minLength": 1, "maxLength": 800},
                "timestamp": {"type": "string", "pattern": r"^[0-9]{1,12}$"},
                "deleted": {"const": True},
                "Tag": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {"$ref": "#/$defs/tag"},
                },
            },
        },
    },
    "properties": {
        "Event": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "uuid",
                "info",
                "date",
                "timestamp",
                "analysis",
                "threat_level_id",
                "published",
                "distribution",
                "Orgc",
                "Tag",
                "Attribute",
            ],
            "properties": {
                "uuid": {"type": "string", "pattern": UUID_PATTERN},
                "info": {"const": "HECAVEX Radar analyst-reviewed phishing domains"},
                "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                "timestamp": {"type": "string", "pattern": r"^[0-9]{1,12}$"},
                "analysis": {"const": "2"},
                "threat_level_id": {"const": "2"},
                "published": {"type": "boolean"},
                "distribution": {"const": "3"},
                "Orgc": {"$ref": "#/$defs/org"},
                "Tag": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"$ref": "#/$defs/tag"},
                },
                "Attribute": {
                    "type": "array",
                    "maxItems": 2_500,
                    "items": {"$ref": "#/$defs/attribute"},
                },
            },
        }
    },
}


MISP_MANIFEST_SCHEMA: Final[dict[str, object]] = {
    **_base("misp-manifest-v1.schema.json", "Reviewed-only MISP feed manifest"),
    "minProperties": 0,
    "maxProperties": 1,
    "propertyNames": {"pattern": UUID_PATTERN},
    "additionalProperties": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "Orgc",
            "date",
            "info",
            "analysis",
            "threat_level_id",
            "timestamp",
            "integrity:sha256",
        ],
        "properties": {
            "Orgc": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "uuid"],
                "properties": {
                    "name": {"const": "HECAVEX"},
                    "uuid": {"type": "string", "pattern": UUID_PATTERN},
                },
            },
            "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            "info": {"const": "HECAVEX Radar analyst-reviewed phishing domains"},
            "analysis": {"const": "2"},
            "threat_level_id": {"const": "2"},
            "timestamp": {"type": "string", "pattern": r"^[0-9]{1,12}$"},
            "integrity:sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        },
    },
}


MISP_WARNINGLIST_SCHEMA: Final[dict[str, object]] = {
    **_base("misp-warninglist-v1.schema.json", "Reviewed official-domain MISP warning list"),
    "additionalProperties": False,
    "required": ["name", "version", "description", "type", "matching_attributes", "list"],
    "properties": {
        "name": {"const": "HECAVEX reviewed official domains for Lithuania-facing brands"},
        "version": {"type": "integer", "minimum": 20_000_000, "maximum": 99_999_999},
        "description": {"type": "string", "minLength": 1, "maxLength": 500},
        "type": {"const": "hostname"},
        "matching_attributes": {
            "const": ["domain", "hostname", "url", "domain|ip"],
        },
        "list": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10_000,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": RAW_DOMAIN_PATTERN, "maxLength": 253},
        },
    },
}


CHANGES_SCHEMA: Final[dict[str, object]] = {
    **_base("changes-v1.schema.json", "HECAVEX Radar rolling change aggregate v1"),
    "$defs": {
        "counter": {"type": "integer", "minimum": 0, "maximum": 2_000_000_000},
        "countMap": {
            "type": "object",
            "maxProperties": 64,
            "propertyNames": {"type": "string", "minLength": 1, "maxLength": 160},
            "additionalProperties": {"$ref": "#/$defs/counter"},
        },
    },
    "additionalProperties": False,
    "required": ["schemaVersion", "dataset", "generatedAt", "privacy", "windows"],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-change-aggregate"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "privacy": {"const": "Aggregate counters only; signal-level history remains in history.json."},
        "windows": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "hours", "from", "to", "events", "uniqueSignals", "firstPublications", "statusChanges",
                    "observations", "reobservations", "bySource", "byStatus", "byReason", "byBrand",
                ],
                "properties": {
                    "hours": {"enum": [24, 168]},
                    "from": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                    "to": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                    **{
                        field: {"$ref": "#/$defs/counter"}
                        for field in (
                            "events", "uniqueSignals", "firstPublications", "statusChanges", "observations",
                            "reobservations",
                        )
                    },
                    **{
                        field: {"$ref": "#/$defs/countMap"}
                        for field in ("bySource", "byStatus", "byReason", "byBrand")
                    },
                },
            },
        },
    },
}


RELATED_SCHEMA: Final[dict[str, object]] = {
    **_base("related-observations-v1.schema.json", "HECAVEX Radar related observations v1"),
    "additionalProperties": False,
    "required": ["schemaVersion", "dataset", "generatedAt", "semantics", "nodes", "edges", "suppressedEvidence"],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-related-observations"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "semantics": {"type": "string", "minLength": 1, "maxLength": 320},
        "nodes": {
            "type": "array",
            "maxItems": 25000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["signalId", "domain", "clusterId"],
                "properties": {
                    "signalId": {"type": "string", "pattern": HEX20_PATTERN},
                    "domain": {"type": "string", "minLength": 1, "maxLength": 512},
                    "clusterId": {"type": "string", "pattern": "^[a-f0-9]{16}$"},
                },
            },
        },
        "edges": {
            "type": "array",
            "maxItems": 2000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "source", "target", "strength", "evidence"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-f0-9]{20}$"},
                    "source": {"type": "string", "pattern": HEX20_PATTERN},
                    "target": {"type": "string", "pattern": HEX20_PATTERN},
                    "strength": {"enum": ["strong", "corroborated-supporting"]},
                    "evidence": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "value"],
                            "properties": {
                                "type": {
                                    "enum": [
                                        "primary-html-sha256",
                                        "certificate-sha256",
                                        "certificate-san",
                                        "redirect-domain",
                                        "ip-address",
                                        "asn",
                                        "dns-a",
                                        "dns-aaaa",
                                        "dns-cname",
                                        "dns-ns",
                                        "dns-mx",
                                    ]
                                },
                                "value": {"type": "string", "minLength": 1, "maxLength": 512},
                            },
                        },
                    },
                },
            },
        },
        "suppressedEvidence": {
            "type": "object",
            "additionalProperties": False,
            "required": ["highFanoutValues", "temporalPairs", "edgeLimit"],
            "properties": {
                "highFanoutValues": {"type": "integer", "minimum": 0},
                "temporalPairs": {"type": "integer", "minimum": 0},
                "edgeLimit": {"type": "integer", "minimum": 0},
            },
        },
    },
}


EVENTS_SCHEMA: Final[dict[str, object]] = {
    **_base("events-v1.schema.json", "HECAVEX Radar event stream v1"),
    "$defs": {
        "event": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id", "type", "occurredAt", "signalId", "signalPath", "domain", "brand",
                "status", "previousStatus", "sources",
            ],
            "properties": {
                "id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                "type": {
                    "enum": ["first-publication", "reobservation", "status-change", "retraction"]
                },
                "occurredAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "signalId": {"type": "string", "pattern": HEX20_PATTERN},
                "signalPath": {"type": "string", "pattern": "^/signals/[a-f0-9]{20}/$"},
                "domain": {"type": "string", "pattern": DEFANGED_DOMAIN_PATTERN, "maxLength": 512},
                "brand": {"type": "string", "minLength": 1, "maxLength": 120},
                "status": {
                    "enum": ["active", "suspected", "offline", "mitigated", "unknown", "retracted"]
                },
                "previousStatus": {
                    "type": ["string", "null"],
                    "enum": ["active", "suspected", "offline", "mitigated", "unknown", None],
                },
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {"enum": ["CertStream", "URLScan", "HECAVEX"]},
                },
            },
        }
    },
    "additionalProperties": False,
    "required": [
        "schemaVersion", "dataset", "generatedAt", "window", "totalAvailable", "truncated", "events"
    ],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-events"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "window": {
            "type": "object",
            "additionalProperties": False,
            "required": ["days", "from", "to"],
            "properties": {
                "days": {"const": 30},
                "from": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "to": {"type": "string", "pattern": TIMESTAMP_PATTERN},
            },
        },
        "totalAvailable": {"type": "integer", "minimum": 0, "maximum": 50_000},
        "truncated": {"type": "boolean"},
        "events": {"type": "array", "maxItems": 1_000, "items": {"$ref": "#/$defs/event"}},
    },
}


JSON_FEED_SCHEMA: Final[dict[str, object]] = {
    **_base("json-feed-v1.schema.json", "HECAVEX Radar JSON Feed 1.1 profile"),
    "additionalProperties": True,
    "required": ["version", "title", "items"],
    "properties": {
        "version": {"const": "https://jsonfeed.org/version/1.1"},
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "home_page_url": {
            "type": "string",
            "pattern": r"^https://radar\.hecavex\.com/[A-Za-z0-9_./-]*$",
        },
        "feed_url": {
            "type": "string",
            "pattern": r"^https://radar\.hecavex\.com/data/[A-Za-z0-9_./-]+$",
        },
        "language": {"const": "en"},
        "items": {
            "type": "array",
            "maxItems": 1_000,
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["id", "url", "title", "content_text", "date_published", "tags"],
                "properties": {
                    "id": {"type": "string", "pattern": "^urn:hecavex-radar:event:[a-f0-9]{32}$"},
                    "url": {
                        "type": "string",
                        "pattern": r"^https://radar\.hecavex\.com/signals/[a-f0-9]{20}/$",
                    },
                    "title": {"type": "string", "minLength": 1, "maxLength": 700},
                    "content_text": {"type": "string", "minLength": 1, "maxLength": 1_500},
                    "date_published": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                    "tags": {
                        "type": "array", "minItems": 2, "maxItems": 2,
                        "items": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                },
            },
        },
    },
}


BRAND_FEEDS_SCHEMA: Final[dict[str, object]] = {
    **_base("brand-feeds-v1.schema.json", "HECAVEX Radar per-brand feed directory v1"),
    "additionalProperties": False,
    "required": ["schemaVersion", "dataset", "generatedAt", "semantics", "brands"],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-brand-feeds"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "semantics": {"type": "string", "minLength": 1, "maxLength": 400},
        "brands": {
            "type": "array",
            "maxItems": 128,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["brand", "slug", "eventCount", "atom", "rss", "jsonFeed"],
                "properties": {
                    "brand": {"type": "string", "minLength": 1, "maxLength": 120},
                    "slug": {"type": "string", "pattern": "^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"},
                    "eventCount": {"type": "integer", "minimum": 0, "maximum": 1_000},
                    "atom": {"type": "string", "pattern": "^/data/brands/[a-z0-9-]+/events\\.atom\\.xml$"},
                    "rss": {"type": "string", "pattern": "^/data/brands/[a-z0-9-]+/events\\.rss\\.xml$"},
                    "jsonFeed": {"type": "string", "pattern": "^/data/brands/[a-z0-9-]+/events\\.feed\\.json$"},
                },
            },
        },
    },
}


QUALITY_METRICS_SCHEMA: Final[dict[str, object]] = {
    **_base("quality-metrics-v1.schema.json", "HECAVEX Radar public quality metrics v1"),
    "$defs": {
        "count": {"type": "integer", "minimum": 0, "maximum": 2_000_000_000},
        "countMap": {
            "type": "object", "maxProperties": 64,
            "additionalProperties": {"$ref": "#/$defs/count"},
        },
        "metric": {"type": ["number", "null"], "minimum": 0},
    },
    "additionalProperties": False,
    "required": [
        "schemaVersion", "dataset", "generatedAt", "window", "semantics", "reviewSample",
        "reviewCoverage", "reviewLatencyHours", "currentExclusions", "precision", "privacy",
    ],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-quality-metrics"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "window": {
            "type": "object", "additionalProperties": False, "required": ["days", "from", "to"],
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 365},
                "from": {"type": "string", "pattern": TIMESTAMP_PATTERN},
                "to": {"type": "string", "pattern": TIMESTAMP_PATTERN},
            },
        },
        "semantics": {"type": "string", "minLength": 1, "maxLength": 500},
        "reviewSample": {
            "type": "object", "additionalProperties": False,
            "required": [
                "assessments", "uniqueSignals", "outcomes", "byBrand", "bySource",
                "sourceLinkedAssessments", "byEvidence", "byDispositionReason", "byDetectionReason",
            ],
            "properties": {
                "assessments": {"$ref": "#/$defs/count"},
                "uniqueSignals": {"$ref": "#/$defs/count"},
                "sourceLinkedAssessments": {"$ref": "#/$defs/count"},
                **{
                    name: {"$ref": "#/$defs/countMap"}
                    for name in (
                        "outcomes", "byBrand", "bySource", "byEvidence", "byDispositionReason",
                        "byDetectionReason",
                    )
                },
            },
        },
        "reviewCoverage": {
            "type": "object", "additionalProperties": False,
            "required": ["eligiblePublishedSignals", "assessedSignals", "percent", "scope"],
            "properties": {
                "eligiblePublishedSignals": {"$ref": "#/$defs/count"},
                "assessedSignals": {"$ref": "#/$defs/count"},
                "percent": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
                "scope": {"type": "string", "minLength": 1, "maxLength": 400},
            },
        },
        "reviewLatencyHours": {
            "type": "object", "additionalProperties": False,
            "required": ["sampleSize", "median", "p90", "minimum", "maximum", "scope"],
            "properties": {
                "sampleSize": {"$ref": "#/$defs/count"},
                **{name: {"$ref": "#/$defs/metric"} for name in ("median", "p90", "minimum", "maximum")},
                "scope": {"type": "string", "minLength": 1, "maxLength": 400},
            },
        },
        "currentExclusions": {
            "type": "object", "additionalProperties": False,
            "required": ["sampleSize", "exact", "subdomainPolicies", "byReason", "scope"],
            "properties": {
                "sampleSize": {"$ref": "#/$defs/count"}, "exact": {"$ref": "#/$defs/count"},
                "subdomainPolicies": {"$ref": "#/$defs/count"},
                "byReason": {"$ref": "#/$defs/countMap"},
                "scope": {"type": "string", "minLength": 1, "maxLength": 400},
            },
        },
        "precision": {
            "type": "object", "additionalProperties": False,
            "required": ["available", "sampleSize", "estimatePercent", "reason"],
            "properties": {
                "available": {"const": False}, "sampleSize": {"const": 0},
                "estimatePercent": {"type": "null"},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
        },
        "privacy": {"type": "string", "minLength": 1, "maxLength": 400},
    },
}


DAILY_TRENDS_SCHEMA: Final[dict[str, object]] = {
    **_base("daily-trends-v1.schema.json", "HECAVEX Radar coverage-aware daily trends v1"),
    "$defs": {
        "count": {"type": "integer", "minimum": 0, "maximum": 2_000_000_000},
        "countMap": {"type": "object", "maxProperties": 64, "additionalProperties": {"$ref": "#/$defs/count"}},
        "percent": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
    },
    "additionalProperties": False,
    "required": [
        "schemaVersion", "dataset", "generatedAt", "retentionDays", "from", "to", "semantics",
        "facetSemantics", "seriesSemantics", "omittedZeroDays", "collectorSchedule", "series", "privacy",
    ],
    "properties": {
        "schemaVersion": {"const": 1}, "dataset": {"const": "radar-daily-trends"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "retentionDays": {"type": "integer", "minimum": 1, "maximum": 365},
        "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"},
        **{
            name: {"type": "string", "minLength": 1, "maxLength": 600}
            for name in ("semantics", "facetSemantics", "seriesSemantics", "privacy")
        },
        "omittedZeroDays": {"type": "integer", "minimum": 0, "maximum": 365},
        "collectorSchedule": {
            "type": "object", "additionalProperties": False,
            "required": ["expectedIntervalSeconds", "expectedListeningSeconds", "derivedFrom"],
            "properties": {
                "expectedIntervalSeconds": {"type": "integer", "minimum": 60, "maximum": 86_400},
                "expectedListeningSeconds": {"type": "integer", "minimum": 0, "maximum": 86_400},
                "derivedFrom": {"enum": ["pipeline-health-24h-window", "documented-default"]},
            },
        },
        "series": {
            "type": "array", "maxItems": 365,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["date", "partialDay", "collectorCoverage", "discovery"],
                "properties": {
                    "date": {"type": "string", "format": "date"}, "partialDay": {"type": "boolean"},
                    "collectorCoverage": {
                        "type": "object", "additionalProperties": False,
                        "required": [
                            "windowSeconds", "scheduledSlots", "recordedAttempts", "healthyAttempts",
                            "recordedSchedulePercent", "listeningCoveragePercent",
                            "scheduledListeningCeilingPercent", "listeningSeconds", "outcomes",
                        ],
                        "properties": {
                            **{
                                name: {"$ref": "#/$defs/count"}
                                for name in ("windowSeconds", "scheduledSlots", "recordedAttempts", "healthyAttempts")
                            },
                            **{
                                name: {"$ref": "#/$defs/percent"}
                                for name in (
                                    "recordedSchedulePercent", "listeningCoveragePercent",
                                    "scheduledListeningCeilingPercent",
                                )
                            },
                            "listeningSeconds": {"type": "number", "minimum": 0, "maximum": 86_400},
                            "outcomes": {"$ref": "#/$defs/countMap"},
                        },
                    },
                    "discovery": {
                        "type": "object", "additionalProperties": False,
                        "required": [
                            "events", "uniqueSignals", "observations", "reobservations", "firstPublications",
                            "statusChanges", "facetSampleSize", "evidenceClassifiedSignals", "byBrand", "bySource",
                            "byEvidenceTier", "byReason",
                        ],
                        "properties": {
                            **{
                                name: {"$ref": "#/$defs/count"}
                                for name in (
                                    "events", "uniqueSignals", "observations", "reobservations",
                                    "firstPublications", "statusChanges", "facetSampleSize",
                                    "evidenceClassifiedSignals",
                                )
                            },
                            **{
                                name: {"$ref": "#/$defs/countMap"}
                                for name in ("byBrand", "bySource", "byEvidenceTier", "byReason")
                            },
                        },
                    },
                },
            },
        },
    },
}


MANIFEST_SCHEMA: Final[dict[str, object]] = {
    **_base("feed-manifest-v1.schema.json", "HECAVEX Radar feed manifest v1"),
    "additionalProperties": False,
    "required": [
        "schemaVersion",
        "dataset",
        "generatedAt",
        "generator",
        "sourceFetchedAt",
        "counts",
        "artifacts",
    ],
    "properties": {
        "schemaVersion": {"const": 1},
        "dataset": {"const": "radar-feed-manifest"},
        "generatedAt": {"type": "string", "pattern": TIMESTAMP_PATTERN},
        "generator": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "version", "revision"],
            "properties": {
                "name": {"const": "hecavex-radar"},
                "version": {"type": "string", "minLength": 1, "maxLength": 40},
                "revision": {"type": ["string", "null"], "pattern": "^[a-f0-9]{40}$"},
            },
        },
        "sourceFetchedAt": {
            "type": "object",
            "additionalProperties": False,
            "required": ["CertStream", "URLScan", "HECAVEX"],
            "properties": {
                name: {
                    "anyOf": [
                        {"type": "null"},
                        {"type": "string", "pattern": TIMESTAMP_PATTERN},
                    ]
                }
                for name in ("CertStream", "URLScan", "HECAVEX")
            },
        },
        "counts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["completeSignals", "dashboardSignals", "dashboardOmitted", "artifacts"],
            "properties": {
                field: {"type": "integer", "minimum": 0, "maximum": 25_000}
                for field in ("completeSignals", "dashboardSignals", "dashboardOmitted", "artifacts")
            },
        },
        "artifacts": {
            "type": "array",
            "minItems": 1,
            "maxItems": 512,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "mediaType", "schema", "bytes", "sha256"],
                "properties": {
                    "path": {
                        "type": "string",
                        "pattern": "^/data/[A-Za-z0-9_-][A-Za-z0-9._-]*(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)*$",
                    },
                    "mediaType": {
                        "enum": [
                            "application/json", "application/stix+json", "application/feed+json",
                            "application/atom+xml", "application/rss+xml",
                        ]
                    },
                    "schema": {"type": ["string", "null"], "maxLength": 2048},
                    "bytes": {"type": "integer", "minimum": 1},
                    "sha256": {"type": "string", "pattern": SHA256_PATTERN},
                },
            },
        },
    },
}


PUBLIC_SCHEMAS: Final[dict[str, dict[str, object]]] = {
    "radar-v2.schema.json": RADAR_SCHEMA,
    "radar-shard-v1.schema.json": RADAR_SHARD_SCHEMA,
    "radar-index-v1.schema.json": RADAR_INDEX_SCHEMA,
    "pipeline-health-v1.schema.json": PIPELINE_HEALTH_SCHEMA,
    "changes-v1.schema.json": CHANGES_SCHEMA,
    "related-observations-v1.schema.json": RELATED_SCHEMA,
    "events-v1.schema.json": EVENTS_SCHEMA,
    "json-feed-v1.schema.json": JSON_FEED_SCHEMA,
    "brand-feeds-v1.schema.json": BRAND_FEEDS_SCHEMA,
    "quality-metrics-v1.schema.json": QUALITY_METRICS_SCHEMA,
    "daily-trends-v1.schema.json": DAILY_TRENDS_SCHEMA,
    "misp-event-v1.schema.json": MISP_EVENT_SCHEMA,
    "misp-manifest-v1.schema.json": MISP_MANIFEST_SCHEMA,
    "misp-warninglist-v1.schema.json": MISP_WARNINGLIST_SCHEMA,
    "feed-manifest-v1.schema.json": MANIFEST_SCHEMA,
}
