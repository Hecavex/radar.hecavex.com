"""Offline evaluation mechanics; never generates reviews or a population precision claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .listening_coverage import stamp

OUTCOMES = {"confirmed-suspicious", "false-positive", "benign-brand-reference", "inconclusive"}


def freeze(snapshot: Mapping[str, Any], source: str, data: str) -> dict[str, Any]:
    if not all(re.fullmatch(r"[a-f0-9]{40}", sha) for sha in (source, data)):
        raise ValueError("Exact source and data revisions are required.")
    if snapshot.get("schemaVersion") != 2 or stamp(snapshot.get("generatedAt")) is None:
        raise ValueError("A version-2 published snapshot with a canonical cutoff is required.")
    signals = snapshot.get("signals")
    if not isinstance(signals, list) or len(signals) > 25000:
        raise ValueError("Invalid bounded cohort.")
    rows = []
    for row in signals:
        if (not isinstance(row, dict) or not re.fullmatch(r"[a-f0-9]{20}", str(row.get("id", "")))
                or type(row.get("matchScore")) is not int or not 0 <= row["matchScore"] <= 100
                or stamp(row.get("lastSeen")) is None):
            raise ValueError("Invalid cohort row.")
        brand = row.get("brand")
        sources = row.get("sources")
        if (brand is not None and (not isinstance(brand, str) or len(brand) > 80
                                  or any(ord(char) < 32 or char in "<>" for char in brand))):
            raise ValueError("Invalid brand facet.")
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 3
                or any(source not in ("CertStream", "URLScan", "HECAVEX") for source in sources)
                or row.get("evidenceTier") not in ("name-only", "corroborated", "reviewed")):
            raise ValueError("Invalid source/evidence facet.")
        rows.append({key: row.get(key) for key in
                     ("id", "matchScore", "brand", "sources", "evidenceTier", "reasonCodes", "lastSeen")})
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate cohort ID.")
    body = {"sourceRevision": source, "dataRevision": data, "cutoff": snapshot["generatedAt"], "rows": rows}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schemaVersion": 1, "protocol": "frozen-current-cohort-v1", **body, "cohortSha256": digest}


def evaluate(cohort: Mapping[str, Any], decisions: list[dict[str, Any]], k: int = 20) -> dict[str, Any]:
    body = {key: cohort[key] for key in ("sourceRevision", "dataRevision", "cutoff", "rows")}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != cohort.get("cohortSha256"):
        raise ValueError("The frozen cohort was modified.")
    rows = cohort["rows"]
    if not 1 <= k <= 25000:
        raise ValueError("k is out of bounds.")
    cutoff = stamp(cohort.get("cutoff"))
    if cutoff is None:
        raise ValueError("Missing frozen cutoff.")
    ids = {row["id"] for row in rows}
    labels: dict[str, str] = {}
    for decision in decisions:
        reviewed = stamp(decision.get("reviewedAt"))
        identifier = decision.get("signalId")
        if (not isinstance(identifier, str) or identifier not in ids or identifier in labels
                or decision.get("reviewMethod") != "human"
                or reviewed is None or reviewed < cutoff or decision.get("outcome") not in OUTCOMES
                or not isinstance(decision.get("evidenceReference"), str) or not decision["evidenceReference"].strip()):
            raise ValueError("Require unique, evidence-backed human dispositions after the frozen cutoff.")
        labels[identifier] = decision["outcome"]

    def summary(selected: list[dict[str, Any]]) -> dict[str, Any]:
        counts = {outcome: sum(labels.get(row["id"]) == outcome for row in selected) for outcome in sorted(OUTCOMES)}
        positive = counts["confirmed-suspicious"]
        resolved = len(selected) - counts["inconclusive"] - sum(row["id"] not in labels for row in selected)
        return {"eligible": len(selected), "unreviewed": sum(row["id"] not in labels for row in selected),
                "outcomes": counts, "resolved": resolved,
                "positiveAmongResolvedPercent": round(100 * positive / resolved, 2) if resolved else None,
                "positiveLowerBoundPercent": round(100 * positive / len(selected), 2) if selected else None}

    ranked = sorted(rows, key=lambda row: (-row["matchScore"], row["id"]))[:k]
    chronological = sorted(rows, key=lambda row: (row["lastSeen"], row["id"]), reverse=True)[:k]
    deterministic = sorted(rows, key=lambda row: hashlib.sha256(
        (cohort["cohortSha256"] + row["id"]).encode()).hexdigest())[:k]
    groups = {str(brand): [row for row in deterministic + rows if row["brand"] == brand]
              for brand in sorted({row["brand"] for row in rows}, key=str)}
    stratified: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    while len(stratified) < min(k, len(rows)):
        for group in groups.values():
            next_row = next((row for row in group if row["id"] not in selected_ids), None)
            if next_row is not None and len(stratified) < k:
                stratified.append(next_row)
                selected_ids.add(next_row["id"])
    facets: dict[str, Any] = {}
    for field in ("brand", "evidenceTier", "matchScore"):
        facets[field] = {str(value): summary([row for row in rows if row[field] == value])
                         for value in sorted({row[field] for row in rows}, key=str)}
    facets["source"] = {source: summary([row for row in rows if source in (row["sources"] or [])])
                        for source in sorted({source for row in rows for source in (row["sources"] or [])})}
    return {"schemaVersion": 1, "cohortSha256": cohort["cohortSha256"], "k": k,
            "scope": "Frozen cohort only; resolved-subset yield is not population precision or calibrated probability.",
            "populationPrecisionAvailable": False, "humanAssessmentCount": len(labels),
            "ranked": summary(ranked), "chronological": summary(chronological),
            "deterministicBaseline": summary(deterministic), "stratifiedBaseline": summary(stratified),
            "facets": facets,
            "gate": "human-review-required" if not labels else "sample-conditional-only"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    frozen = commands.add_parser("freeze")
    frozen.add_argument("snapshot", type=Path)
    frozen.add_argument("--source", required=True)
    frozen.add_argument("--data", required=True)
    measured = commands.add_parser("evaluate")
    measured.add_argument("cohort", type=Path)
    measured.add_argument("decisions", type=Path)
    measured.add_argument("--k", type=int, default=20)
    options = parser.parse_args()
    if options.command == "freeze":
        result = freeze(json.loads(options.snapshot.read_text(encoding="utf-8")), options.source, options.data)
    else:
        result = evaluate(json.loads(options.cohort.read_text(encoding="utf-8")),
                          json.loads(options.decisions.read_text(encoding="utf-8")), options.k)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
