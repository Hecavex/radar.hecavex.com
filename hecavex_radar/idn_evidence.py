"""Versioned, bounded explanations of current curated IDN candidate matches."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .brands import IDN_VISUAL_PROFILE, BrandRegistry, idn_match_evidence
from .models import RadarSignal
from .public_schemas import IDN_MATCHES_SCHEMA

MAXIMUM_IDN_EVIDENCE_BYTES = 2 * 1024 * 1024
MAXIMUM_IDN_EVIDENCE_RECORDS = 2_500


def build_idn_evidence(
    signals: Sequence[RadarSignal],
    registry: BrandRegistry,
    generated_at: str,
    snapshot_sha256: str,
) -> dict[str, object]:
    """Recompute name resemblance at this release boundary, never historical intent."""
    records: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for signal in signals:
        identifier = signal["id"]
        if identifier in seen_ids:
            raise ValueError("IDN evidence inputs contain a duplicate signal ID.")
        seen_ids.add(identifier)
        if "xn--" not in signal["domain"]:
            continue
        evidence = idn_match_evidence(signal["domain"].replace("[.]", "."), registry)
        if evidence is None:
            continue
        if evidence.get("brand") != signal["brand"]:
            raise ValueError("IDN evidence does not match its published signal brand.")
        records.append({"signalId": identifier, "domain": signal["domain"], **evidence})
        if len(records) > MAXIMUM_IDN_EVIDENCE_RECORDS:
            raise ValueError("IDN evidence exceeds its record budget; refusing truncation.")
    result: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-idn-matches",
        "generatedAt": generated_at,
        "snapshotSha256": snapshot_sha256,
        "profile": IDN_VISUAL_PROFILE,
        "records": sorted(records, key=lambda record: cast(str, record["signalId"])),
    }
    errors = list(Draft202012Validator(IDN_MATCHES_SCHEMA).iter_errors(result))
    if errors:
        raise ValueError(f"IDN evidence does not satisfy its schema: {errors[0].message}")
    if len((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")) > MAXIMUM_IDN_EVIDENCE_BYTES:
        raise ValueError("IDN evidence exceeds its byte budget; refusing truncation.")
    return result


def validate_idn_evidence(
    value: object,
    signals: Sequence[RadarSignal],
    registry: BrandRegistry,
    generated_at: str,
    snapshot_sha256: str,
) -> None:
    """Validate identity, completeness, suppression, PSL role and exact transformations."""
    if list(Draft202012Validator(IDN_MATCHES_SCHEMA).iter_errors(value)):
        raise ValueError("IDN evidence differs from its strict supported schema.")
    expected = build_idn_evidence(signals, registry, generated_at, snapshot_sha256)
    if value != expected:
        raise ValueError("IDN evidence differs from the current publication, registry or visual profile.")
