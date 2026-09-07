"""Evaluate repository-backed Radar health without publishing sensitive inputs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

MAXIMUM_JSON_BYTES: Final[int] = 4 * 1024 * 1024
CURRENT_SNAPSHOT_VERSION: Final[int] = 2
MAXIMUM_CLOCK_SKEW_SECONDS: Final[int] = 5 * 60
CT_FAILURE_CODES: Final[frozenset[str]] = frozenset(
    {"provider-timeout", "provider-http", "provider-network", "invalid-response", "validation", "internal"}
)


@dataclass(frozen=True, slots=True)
class HealthFinding:
    code: str
    source: str
    summary: str
    observed: str


def _utc(value: datetime | None = None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate.astimezone(UTC) if candidate.tzinfo is not None else candidate.replace(tzinfo=UTC)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(UTC) if _timestamp(parsed) == value else None


def _read_object(repository: Path, relative: str) -> dict[str, Any] | None:
    root = repository.resolve()
    target = (root / relative).resolve()
    if target == root or not target.is_relative_to(root):
        return None
    try:
        if target.stat().st_size > MAXIMUM_JSON_BYTES:
            return None
        value: object = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _age_seconds(value: object, now: datetime) -> int | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    difference = int((_utc(now) - parsed).total_seconds())
    return None if difference < -MAXIMUM_CLOCK_SKEW_SECONDS else max(0, difference)


def _append_missing(findings: list[HealthFinding], source: str, path: str) -> None:
    findings.append(
        HealthFinding(
            code="health-artifact-unavailable",
            source=source,
            summary="A required aggregate health artifact is missing, malformed, or oversized.",
            observed=path,
        )
    )


def _evaluate_snapshot(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    snapshot = _read_object(repository, "public/data/radar.json")
    if snapshot is None:
        _append_missing(findings, "publication", "public/data/radar.json")
        return
    if (
        snapshot.get("schemaVersion") != CURRENT_SNAPSHOT_VERSION
        or snapshot.get("dataset") != "live"
        or not isinstance(snapshot.get("signals"), list)
        or not isinstance(snapshot.get("sources"), list)
    ):
        findings.append(
            HealthFinding(
                code="snapshot-contract-incompatible",
                source="publication",
                summary="The checked-in live snapshot does not match the current consumer contract.",
                observed=f"expected schema {CURRENT_SNAPSHOT_VERSION}",
            )
        )
        return
    age = _age_seconds(snapshot.get("lastSuccessfulSyncAt"), now)
    if age is None:
        findings.append(
            HealthFinding(
                code="snapshot-timestamp-invalid",
                source="publication",
                summary="The live snapshot has no canonical successful-sync timestamp.",
                observed="lastSuccessfulSyncAt invalid",
            )
        )
    elif age > 3 * 60 * 60:
        findings.append(
            HealthFinding(
                code="snapshot-stale",
                source="publication",
                summary="The hourly public snapshot has not recorded a successful sync within three hours.",
                observed=f"age {age // 60} minutes",
            )
        )


def _evaluate_certstream(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    health = _read_object(repository, "public/data/collection-health.json")
    if health is None:
        _append_missing(findings, "CertStream", "public/data/collection-health.json")
        return
    stale_after = health.get("staleAfterSeconds")
    threshold = stale_after if type(stale_after) is int and 900 <= stale_after <= 86_400 else 2_700
    age = _age_seconds(health.get("lastSuccessAt"), now)
    if age is None or age > threshold:
        findings.append(
            HealthFinding(
                code="certstream-stale",
                source="CertStream",
                summary="The sampled CertStream collector is beyond its declared freshness threshold.",
                observed="no valid success" if age is None else f"age {age // 60} minutes; threshold {threshold // 60}",
            )
        )
    latest = health.get("latestAttempt")
    if isinstance(latest, dict) and latest.get("outcome") in {"failed", "partial", "no-input"}:
        attempt_age = _age_seconds(latest.get("endedAt"), now)
        if attempt_age is None or attempt_age > threshold:
            findings.append(
                HealthFinding(
                    code="certstream-degraded",
                    source="CertStream",
                    summary="The latest persisted CertStream attempt remains degraded beyond one freshness window.",
                    observed=f"outcome {latest.get('outcome')}",
                )
            )


def _evaluate_urlscan(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    state = _read_object(repository, "data/urlscan/hunt-state.json")
    if state is None:
        _append_missing(findings, "URLScan", "data/urlscan/hunt-state.json")
        return
    if state.get("configured") is not True:
        return
    attempt_age = _age_seconds(state.get("lastRunAt"), now)
    consecutive = state.get("consecutiveFailures")
    degraded_age = _age_seconds(state.get("degradedSince"), now)
    success_age = _age_seconds(state.get("lastSuccessAt"), now)
    has_persisted_health = any(
        field in state for field in ("lastSuccessAt", "consecutiveFailures", "degradedSince")
    )
    persisted_health_valid = (
        type(consecutive) is int
        and 0 <= consecutive <= 2_000_000_000
        and (
            (consecutive == 0 and state.get("degradedSince") is None)
            or (consecutive > 0 and degraded_age is not None)
        )
    )
    freshness_age = (
        success_age if success_age is not None else degraded_age
    ) if has_persisted_health and persisted_health_valid else attempt_age
    if freshness_age is None or freshness_age > 6 * 60 * 60:
        findings.append(
            HealthFinding(
                code="urlscan-stale",
                source="URLScan",
                summary="The two-hour URLScan hunt has no valid successful run within six hours.",
                observed=(
                    "no valid success"
                    if freshness_age is None
                    else f"successful-source age {freshness_age // 60} minutes"
                ),
            )
        )
    persistent_failure = (
        not persisted_health_valid
        or cast(int, consecutive) >= 2
        or degraded_age is None
        or degraded_age > 3 * 60 * 60
    ) if has_persisted_health else (attempt_age is None or attempt_age > 3 * 60 * 60)
    if state.get("lastOutcome") == "failed" and persistent_failure:
        findings.append(
            HealthFinding(
                code="urlscan-failed",
                source="URLScan",
                summary="The latest URLScan hunt remains failed after the next scheduled opportunity.",
                observed=(
                    f"{consecutive} consecutive failed runs; degraded "
                    f"{degraded_age // 60 if degraded_age is not None else 'unknown'} minutes"
                    if has_persisted_health and persisted_health_valid
                    else "latest outcome failed; persistent health unavailable"
                ),
            )
        )
    coverage = state.get("checkpointCoverage")
    if isinstance(coverage, dict):
        backlog = coverage.get("backlog")
        oldest_age = _age_seconds(coverage.get("oldestBacklogProgressAt"), now)
        if type(backlog) is int and backlog > 0 and (oldest_age is None or oldest_age > 24 * 60 * 60):
            findings.append(
                HealthFinding(
                    code="urlscan-backlog-stalled",
                    source="URLScan",
                    summary="Checkpointed URLScan search backlog has not made progress within 24 hours.",
                    observed=(
                        f"{backlog} aggregate backlog queries; no valid progress timestamp"
                        if oldest_age is None
                        else f"{backlog} aggregate backlog queries; oldest progress {oldest_age // 3600} hours ago"
                    ),
                )
            )


def _evaluate_ct_search(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    state = _read_object(repository, "data/ct-search/state.json")
    if state is None:
        _append_missing(findings, "crt.sh", "data/ct-search/state.json")
        return
    latest = state.get("latestRun")
    if not isinstance(latest, dict):
        findings.append(
            HealthFinding(
                code="ct-search-state-invalid",
                source="crt.sh",
                summary="The checkpointed CT state has no valid latest-run summary.",
                observed="latestRun unavailable",
            )
        )
        return
    raw_codes = latest.get("failureCodes", [])
    codes = raw_codes if isinstance(raw_codes, list) else []
    if (
        raw_codes is not None
        and (
            not isinstance(raw_codes, list)
            or any(not isinstance(code, str) or code not in CT_FAILURE_CODES for code in raw_codes)
            or raw_codes != sorted(set(cast(list[str], raw_codes)))
        )
    ):
        findings.append(
            HealthFinding(
                code="ct-search-failure-code-invalid",
                source="crt.sh",
                summary="The CT state contains an uncontrolled failure classification.",
                observed="failureCodes invalid",
            )
        )
        codes = []
    attempt_age = _age_seconds(latest.get("endedAt"), now)
    provider_health = state.get("providerHealth")
    has_provider_health = isinstance(provider_health, dict)
    consecutive: object = None
    degraded_age: int | None = None
    success_age: int | None = None
    persisted_health_valid = False
    if isinstance(provider_health, dict):
        consecutive = provider_health.get("consecutiveFailures")
        degraded_age = _age_seconds(provider_health.get("degradedSince"), now)
        success_age = _age_seconds(provider_health.get("lastSuccessAt"), now)
        persisted_health_valid = (
            type(consecutive) is int
            and 0 <= consecutive <= 2_000_000_000
            and (
                (consecutive == 0 and provider_health.get("degradedSince") is None)
                or (consecutive > 0 and degraded_age is not None)
            )
        )
    freshness_age = (
        success_age if success_age is not None else degraded_age
    ) if persisted_health_valid else attempt_age
    if freshness_age is None or freshness_age > 3 * 60 * 60:
        findings.append(
            HealthFinding(
                code="ct-search-stale",
                source="crt.sh",
                summary="The hourly checkpointed CT search has no valid successful provider run within three hours.",
                observed=(
                    "no valid success"
                    if freshness_age is None
                    else f"successful-provider age {freshness_age // 60} minutes"
                ),
            )
        )
    outcome = latest.get("outcome")
    if persisted_health_valid:
        failure_count = cast(int, consecutive)
        persistent_failure = failure_count > 0 and (
            failure_count >= 2 or degraded_age is None or degraded_age > 90 * 60
        )
    elif has_provider_health:
        persistent_failure = True
    else:
        persistent_failure = attempt_age is None or attempt_age > 90 * 60
    if outcome in {"failed", "partial", "deferred-backoff"} and persistent_failure:
        suffix = ",".join(cast(list[str], codes)) if codes else "unclassified-legacy"
        findings.append(
            HealthFinding(
                code="ct-search-degraded",
                source="crt.sh",
                summary="The checkpointed CT search remains degraded after another scheduled opportunity.",
                observed=(
                    f"outcome {outcome}; {consecutive} consecutive provider failures; "
                    f"degraded {degraded_age // 60 if degraded_age is not None else 'unknown'} minutes; "
                    f"failure codes {suffix}"
                    if persisted_health_valid
                    else f"outcome {outcome}; failure codes {suffix}"
                ),
            )
        )


def _evaluate_domain_context(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    state = _read_object(repository, "data/enrichment/domain-context.json")
    if state is None:
        _append_missing(findings, "DNS/RDAP", "data/enrichment/domain-context.json")
        return
    latest = state.get("latestRun")
    if not isinstance(latest, dict):
        _append_missing(findings, "DNS/RDAP", "data/enrichment/domain-context.json#latestRun")
        return
    age = _age_seconds(latest.get("endedAt"), now)
    if age is None or age > 12 * 60 * 60:
        findings.append(
            HealthFinding(
                code="domain-context-stale",
                source="DNS/RDAP",
                summary="The six-hour passive domain-context refresh has no valid run within twelve hours.",
                observed="no valid attempt" if age is None else f"age {age // 60} minutes",
            )
        )
    if latest.get("outcome") == "failed" and (age is None or age > 7 * 60 * 60):
        findings.append(
            HealthFinding(
                code="domain-context-failed",
                source="DNS/RDAP",
                summary="The latest passive domain-context refresh remains failed after another scheduled slot.",
                observed="latest outcome failed",
            )
        )


def _evaluate_passive_context(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    state = _read_object(repository, "data/enrichment/passive-context.json")
    if state is None:
        _append_missing(findings, "Temporal context", "data/enrichment/passive-context.json")
        return
    latest = state.get("latestRun")
    if not isinstance(latest, dict):
        _append_missing(findings, "Temporal context", "data/enrichment/passive-context.json#latestRun")
        return
    age = _age_seconds(latest.get("endedAt"), now)
    if age is None or age > 12 * 60 * 60:
        findings.append(
            HealthFinding(
                code="passive-context-stale",
                source="Temporal context",
                summary="The six-hour temporal passive-context refresh has no valid run within twelve hours.",
                observed="no valid attempt" if age is None else f"age {age // 60} minutes",
            )
        )
    if latest.get("outcome") == "failed" and (age is None or age > 7 * 60 * 60):
        findings.append(
            HealthFinding(
                code="passive-context-failed",
                source="Temporal context",
                summary="The temporal passive-context refresh remains failed after another scheduled slot.",
                observed="latest outcome failed",
            )
        )


def _evaluate_schedule(repository: Path, now: datetime, findings: list[HealthFinding]) -> None:
    health = _read_object(repository, "public/data/pipeline-health.json")
    if health is None:
        _append_missing(findings, "pipeline", "public/data/pipeline-health.json")
        return
    health_age = _age_seconds(health.get("generatedAt"), now)
    if health_age is None:
        findings.append(
            HealthFinding(
                code="pipeline-health-timestamp-invalid",
                source="pipeline",
                summary="The aggregate pipeline-health artifact has no canonical generation timestamp.",
                observed="generatedAt invalid",
            )
        )
        return
    if health_age > 6 * 60 * 60:
        findings.append(
            HealthFinding(
                code="pipeline-health-stale",
                source="pipeline",
                summary="The aggregate pipeline-health artifact is older than six hours.",
                observed=f"age {health_age // 60} minutes",
            )
        )
        return
    windows = health.get("windows")
    if not isinstance(windows, list):
        return
    window = next((item for item in windows if isinstance(item, dict) and item.get("hours") == 24), None)
    collection = window.get("collection") if isinstance(window, dict) else None
    if not isinstance(collection, dict):
        return
    scheduled = collection.get("scheduledSlots")
    recorded = collection.get("recordedAttempts")
    if type(scheduled) is int and type(recorded) is int and scheduled >= 24 and recorded * 2 < scheduled:
        findings.append(
            HealthFinding(
                code="certstream-schedule-gap",
                source="GitHub Actions",
                summary=(
                    "Fewer than half of the declared CertStream schedule slots are represented in the 24-hour record."
                ),
                observed=f"{recorded} of {scheduled} slots recorded",
            )
        )


def evaluate(repository: Path, *, now: datetime | None = None) -> dict[str, object]:
    evaluated_at = _utc(now)
    findings: list[HealthFinding] = []
    _evaluate_snapshot(repository, evaluated_at, findings)
    _evaluate_certstream(repository, evaluated_at, findings)
    _evaluate_urlscan(repository, evaluated_at, findings)
    _evaluate_ct_search(repository, evaluated_at, findings)
    _evaluate_domain_context(repository, evaluated_at, findings)
    _evaluate_passive_context(repository, evaluated_at, findings)
    _evaluate_schedule(repository, evaluated_at, findings)
    ordered = sorted(findings, key=lambda item: (item.source, item.code, item.observed))
    return {
        "schemaVersion": 1,
        "dataset": "radar-health-evaluation",
        "evaluatedAt": _timestamp(evaluated_at),
        "healthy": not ordered,
        "findings": [asdict(item) for item in ordered],
    }


def markdown(report: dict[str, object]) -> str:
    evaluated_at = report.get("evaluatedAt")
    findings = report.get("findings")
    rows = cast(list[dict[str, str]], findings) if isinstance(findings, list) else []
    lines = [
        "## Radar pipeline health",
        "",
        f"Automated aggregate evaluation at `{evaluated_at}`.",
        "",
    ]
    if not rows:
        lines.extend(["All configured repository-backed health checks passed.", ""])
    else:
        lines.extend(
            [
                "This issue is updated in place until every finding recovers.",
                "",
                "| Source | Failure code | Observation |",
                "| --- | --- | --- |",
                *[
                    f"| {row['source']} | `{row['code']}` | {row['summary']} {row['observed']} |"
                    for row in rows
                ],
                "",
            ]
        )
    lines.append(
        "Only controlled failure codes and aggregate counters are included. "
        "Candidate data and raw exceptions are omitted."
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate aggregate GitHub-backed Radar pipeline health.")
    parser.add_argument("--repository", default=".")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    parser.add_argument("--github-output")
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    report = evaluate(Path(options.repository))
    Path(options.json_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(options.markdown_output).write_text(markdown(report), encoding="utf-8")
    if options.github_output:
        with Path(options.github_output).open("a", encoding="utf-8") as output:
            output.write(f"unhealthy={'false' if report['healthy'] else 'true'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
