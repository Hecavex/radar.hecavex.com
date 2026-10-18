"""Bounded public health metadata for the sampled CertStream collector."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

CollectionOutcome = Literal["healthy-empty", "healthy-matches", "no-input", "partial", "failed"]
ScheduleStatus = Literal["scheduled", "delayed", "relayed", "manual", "unknown"]
CollectionTrigger = Literal["schedule", "cadence-relay", "manual", "unknown"]

MAXIMUM_HEALTH_BYTES = 32 * 1024
MAXIMUM_COUNTER = 2_000_000_000
DEFAULT_HEALTH_PATH = "public/data/collection-health.json"
DEFAULT_EXPECTED_INTERVAL_SECONDS = 15 * 60
DEFAULT_STALE_AFTER_SECONDS = 45 * 60
DEFAULT_DELAY_THRESHOLD_SECONDS = 5 * 60
DEFAULT_DUE_TOLERANCE_SECONDS = 5 * 60
DEFAULT_SCHEDULE_MINUTES = (8, 23, 38, 53)
OUTCOMES = frozenset({"healthy-empty", "healthy-matches", "no-input", "partial", "failed"})
SCHEDULE_STATUSES = frozenset({"scheduled", "delayed", "relayed", "manual", "unknown"})
TRIGGERS = frozenset({"schedule", "cadence-relay", "manual", "unknown"})
AUTOMATED_TRIGGERS = frozenset({"schedule", "cadence-relay"})
FRESHNESS_STATUSES = frozenset({"current", "stale", "unavailable"})


@dataclass(slots=True)
class CollectionMetrics:
    """Counters collected without retaining certificate names or candidate content."""

    collector_started_at: datetime | None = None
    listening_seconds: float = 0.0
    messages: int = 0
    dns_names: int = 0
    matches: int = 0
    new_records: int = 0
    connection_attempts: int = 0
    connections: int = 0
    connection_errors: int = 0
    completed_window: bool = False
    interrupted: bool = False


def _enabled_integer(value: str | None, fallback: int, minimum: int, maximum: int) -> int:
    if not value or not value.strip():
        return fallback
    try:
        parsed = int(value)
    except ValueError:
        return fallback
    return min(maximum, max(minimum, parsed))


def _utc(value: datetime | None = None) -> datetime:
    candidate = value or datetime.now(UTC)
    return candidate.astimezone(UTC) if candidate.tzinfo is not None else candidate.replace(tzinfo=UTC)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if _timestamp(parsed) == value else None


def _bounded_path(value: str | Path | None = None) -> Path:
    repository = Path.cwd().resolve()
    configured = value or os.environ.get("CERTSTREAM_HEALTH_PATH", "").strip() or DEFAULT_HEALTH_PATH
    target = (repository / configured).resolve()
    if target == repository or not target.is_relative_to(repository):
        raise ValueError("CERTSTREAM_HEALTH_PATH must stay inside the repository.")
    return target


def _trigger(value: str | None) -> CollectionTrigger:
    normalized = (value or "").strip().lower()
    if normalized in AUTOMATED_TRIGGERS:
        return cast(CollectionTrigger, normalized)
    if normalized in {"manual", "workflow_dispatch"}:
        return "manual"
    return "unknown"


def _schedule_minutes(value: str | None) -> tuple[int, ...]:
    if not value or not value.strip():
        return DEFAULT_SCHEDULE_MINUTES
    minutes: set[int] = set()
    for item in value.split(",")[:12]:
        try:
            minute = int(item.strip())
        except ValueError:
            continue
        if 0 <= minute <= 59:
            minutes.add(minute)
    return tuple(sorted(minutes)) or DEFAULT_SCHEDULE_MINUTES


def _scheduled_slot(started_at: datetime, minutes: tuple[int, ...]) -> datetime:
    current = _utc(started_at).replace(second=0, microsecond=0)
    candidates = [current.replace(minute=minute) for minute in minutes if minute <= current.minute]
    if candidates:
        return max(candidates)
    previous_hour = current - timedelta(hours=1)
    return previous_hour.replace(minute=max(minutes))


def _schedule(
    started_at: datetime,
    trigger: CollectionTrigger,
) -> tuple[str | None, ScheduleStatus, int | None]:
    if trigger == "manual":
        return None, "manual", None
    if trigger == "cadence-relay":
        return None, "relayed", None
    if trigger != "schedule":
        return None, "unknown", None
    scheduled_for = _scheduled_slot(started_at, _schedule_minutes(os.environ.get("CERTSTREAM_SCHEDULE_MINUTES")))
    delay_seconds = max(0, int((_utc(started_at) - scheduled_for).total_seconds()))
    threshold = _enabled_integer(
        os.environ.get("CERTSTREAM_DELAY_THRESHOLD_SECONDS"),
        DEFAULT_DELAY_THRESHOLD_SECONDS,
        0,
        3_600,
    )
    status: ScheduleStatus = "delayed" if delay_seconds > threshold else "scheduled"
    return _timestamp(scheduled_for), status, delay_seconds


def _freshness(last_success: str | None, at: datetime, stale_after_seconds: int) -> dict[str, object]:
    reference = _parse_timestamp(last_success)
    if reference is None:
        return {"status": "unavailable", "referenceAt": None, "ageSeconds": None}
    age_seconds = max(0, int((_utc(at) - reference).total_seconds()))
    return {
        "status": "current" if age_seconds <= stale_after_seconds else "stale",
        "referenceAt": _timestamp(reference),
        "ageSeconds": age_seconds,
    }


def _valid_counter(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAXIMUM_COUNTER


def _valid_seconds(value: object, maximum: int = 86_400) -> bool:
    return type(value) in {int, float} and 0 <= cast(float, value) <= maximum


def _valid_summary(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 240 and value.strip() == value and value.isprintable()


def _valid_attempt(value: object, allow_running: bool) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "startedAt",
        "collectorStartedAt",
        "endedAt",
        "trigger",
        "scheduledFor",
        "scheduleStatus",
        "delaySeconds",
        "expectedListeningSeconds",
        "listeningSeconds",
        "messages",
        "dnsNames",
        "matches",
        "newRecords",
        "connectionAttempts",
        "connections",
        "outcome",
        "summary",
    }:
        return False
    started_at = _parse_timestamp(value["startedAt"])
    collector_started_at = _parse_timestamp(value["collectorStartedAt"])
    ended_at = _parse_timestamp(value["endedAt"])
    scheduled_for = _parse_timestamp(value["scheduledFor"])
    outcome = value["outcome"]
    if (
        started_at is None
        or (value["collectorStartedAt"] is not None and collector_started_at is None)
        or value["trigger"] not in TRIGGERS
        or value["scheduleStatus"] not in SCHEDULE_STATUSES
        or not _valid_seconds(value["expectedListeningSeconds"])
        or not _valid_seconds(value["listeningSeconds"])
        or not all(
            _valid_counter(value[field])
            for field in ("messages", "dnsNames", "matches", "newRecords", "connectionAttempts", "connections")
        )
        or cast(int, value["dnsNames"]) < cast(int, value["matches"])
        or cast(int, value["connectionAttempts"]) < cast(int, value["connections"])
        or not _valid_summary(value["summary"])
    ):
        return False
    if collector_started_at is not None and collector_started_at < started_at:
        return False
    if collector_started_at is not None and ended_at is not None and collector_started_at > ended_at:
        return False
    expected_statuses = {
        "schedule": {"scheduled", "delayed"},
        "cadence-relay": {"relayed"},
        "manual": {"manual"},
        "unknown": {"unknown"},
    }
    if value["scheduleStatus"] not in expected_statuses[value["trigger"]]:
        return False
    if value["scheduleStatus"] in {"scheduled", "delayed"}:
        if (
            value["trigger"] != "schedule"
            or scheduled_for is None
            or scheduled_for > started_at
            or not _valid_counter(value["delaySeconds"])
            or value["delaySeconds"] != int((started_at - scheduled_for).total_seconds())
        ):
            return False
    elif value["scheduleStatus"] == "relayed":
        if (
            value["trigger"] != "cadence-relay"
            or value["scheduledFor"] is not None
            or value["delaySeconds"] is not None
        ):
            return False
    elif (
        value["scheduledFor"] is not None
        or value["delaySeconds"] is not None
        or (value["scheduleStatus"] == "manual") != (value["trigger"] == "manual")
    ):
        return False
    if outcome is None:
        return allow_running and ended_at is None
    if outcome not in OUTCOMES or ended_at is None or ended_at < started_at:
        return False
    if value["newRecords"] > value["matches"]:
        return False
    if outcome in {"healthy-empty", "healthy-matches", "partial"} and (
        value["connections"] == 0 or value["dnsNames"] == 0
    ):
        return False
    if outcome == "healthy-empty" and value["matches"] != 0:
        return False
    if outcome == "healthy-matches" and value["matches"] == 0:
        return False
    connections = cast(int, value["connections"])
    dns_names = cast(int, value["dnsNames"])
    return outcome != "no-input" or (connections > 0 and dns_names == 0)


def is_collection_health(value: object, allow_running: bool = False) -> bool:
    """Validate the deliberately small public health artifact."""

    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "dataset",
        "generatedAt",
        "expectedIntervalSeconds",
        "staleAfterSeconds",
        "lastSuccessAt",
        "freshness",
        "latestAttempt",
    }:
        return False
    generated_at = _parse_timestamp(value["generatedAt"])
    last_success_at = _parse_timestamp(value["lastSuccessAt"])
    freshness = value["freshness"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["dataset"] != "certstream-collection-health"
        or generated_at is None
        or not _valid_counter(value["expectedIntervalSeconds"])
        or value["expectedIntervalSeconds"] == 0
        or not _valid_counter(value["staleAfterSeconds"])
        or value["staleAfterSeconds"] == 0
        or (value["lastSuccessAt"] is not None and last_success_at is None)
        or not isinstance(freshness, dict)
        or set(freshness) != {"status", "referenceAt", "ageSeconds"}
        or freshness["status"] not in FRESHNESS_STATUSES
        or freshness["referenceAt"] != value["lastSuccessAt"]
        or (
            value["latestAttempt"] is not None
            and not _valid_attempt(value["latestAttempt"], allow_running)
        )
    ):
        return False
    if value["latestAttempt"] is None and last_success_at is not None:
        return False
    if last_success_at is None:
        return freshness["status"] == "unavailable" and freshness["ageSeconds"] is None
    if last_success_at > generated_at or not _valid_counter(freshness["ageSeconds"]):
        return False
    if freshness["ageSeconds"] != int((generated_at - last_success_at).total_seconds()):
        return False
    latest = value["latestAttempt"]
    latest_started = _parse_timestamp(latest["startedAt"]) if latest is not None else None
    expected_freshness = "current" if freshness["ageSeconds"] <= value["staleAfterSeconds"] else "stale"
    if latest is not None and latest["outcome"] is None:
        return (
            allow_running
            and latest_started is not None
            and latest_started <= generated_at
            and last_success_at <= latest_started
            and freshness["status"] == expected_freshness
        )
    latest_ended = _parse_timestamp(latest["endedAt"]) if latest is not None else None
    if (
        latest is None
        or latest_ended is None
        or latest_started is None
        or latest_ended > generated_at
        or freshness["status"] != expected_freshness
    ):
        return False
    if latest["outcome"] in {"healthy-empty", "healthy-matches"}:
        return latest_ended == last_success_at
    return last_success_at <= latest_started


def read_collection_health(path: str | Path | None = None, allow_running: bool = False) -> dict[str, Any] | None:
    target = _bounded_path(path)
    try:
        if target.stat().st_size > MAXIMUM_HEALTH_BYTES:
            raise ValueError("Collection-health artifact exceeds 32 KiB.")
        value: object = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Collection-health artifact is not readable JSON.") from error
    if not is_collection_health(value, allow_running=allow_running):
        raise ValueError("Collection-health artifact does not match schema version 1.")
    return cast(dict[str, Any], value)


def _write_collection_health(
    value: dict[str, Any],
    path: str | Path | None = None,
    allow_running: bool = False,
) -> Path:
    if not is_collection_health(value, allow_running=allow_running):
        raise ValueError("Refusing to write invalid collection-health metadata.")
    target = _bounded_path(path)
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if len(body.encode("utf-8")) > MAXIMUM_HEALTH_BYTES:
        raise ValueError("Refusing to write collection-health metadata larger than 32 KiB.")
    temporary = target.with_name(f"{target.name}.tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(body, encoding="utf-8", newline="\n")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def begin_attempt(
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
    trigger_value: str | None = None,
) -> Path:
    """Replace the latest attempt with a running record while preserving last success."""

    started_at = _utc(now)
    existing = read_collection_health(path, allow_running=True)
    last_success = existing["lastSuccessAt"] if existing else None
    expected_interval = _enabled_integer(
        os.environ.get("CERTSTREAM_EXPECTED_INTERVAL_SECONDS"),
        DEFAULT_EXPECTED_INTERVAL_SECONDS,
        60,
        86_400,
    )
    stale_after = _enabled_integer(
        os.environ.get("CERTSTREAM_STALE_AFTER_SECONDS"),
        DEFAULT_STALE_AFTER_SECONDS,
        expected_interval,
        7 * 86_400,
    )
    expected_listening = _enabled_integer(os.environ.get("CERTSTREAM_DURATION_SECONDS"), 480, 0, 86_400)
    trigger = _trigger(trigger_value if trigger_value is not None else os.environ.get("CERTSTREAM_TRIGGER"))
    scheduled_for, schedule_status, delay_seconds = _schedule(started_at, trigger)
    artifact: dict[str, Any] = {
        "schemaVersion": 1,
        "dataset": "certstream-collection-health",
        "generatedAt": _timestamp(started_at),
        "expectedIntervalSeconds": expected_interval,
        "staleAfterSeconds": stale_after,
        "lastSuccessAt": last_success,
        "freshness": _freshness(last_success, started_at, stale_after),
        "latestAttempt": {
            "startedAt": _timestamp(started_at),
            "collectorStartedAt": None,
            "endedAt": None,
            "trigger": trigger,
            "scheduledFor": scheduled_for,
            "scheduleStatus": schedule_status,
            "delaySeconds": delay_seconds,
            "expectedListeningSeconds": expected_listening,
            "listeningSeconds": 0.0,
            "messages": 0,
            "dnsNames": 0,
            "matches": 0,
            "newRecords": 0,
            "connectionAttempts": 0,
            "connections": 0,
            "outcome": None,
            "summary": "Collection attempt in progress.",
        },
    }
    return _write_collection_health(artifact, path, allow_running=True)


def _due_wait_seconds(
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
    trigger_value: str | None = None,
) -> float | None:
    """Return seconds until an automated invocation is due, or ``None`` when it is too early.

    A small tolerance lets a queued worker wait out normal scheduler jitter. It
    does not move the due boundary: automated attempts still require the full
    declared interval between persisted starts.
    """

    trigger = _trigger(trigger_value if trigger_value is not None else os.environ.get("CERTSTREAM_TRIGGER"))
    if trigger == "manual":
        return 0.0
    existing = read_collection_health(path, allow_running=True)
    if existing is None or existing["latestAttempt"] is None:
        return 0.0
    latest_started = _parse_timestamp(existing["latestAttempt"]["startedAt"])
    if latest_started is None:
        return 0.0
    expected_interval = cast(int, existing["expectedIntervalSeconds"])
    tolerance = _enabled_integer(
        os.environ.get("CERTSTREAM_DUE_TOLERANCE_SECONDS"),
        DEFAULT_DUE_TOLERANCE_SECONDS,
        0,
        min(300, expected_interval - 1),
    )
    remaining = expected_interval - (_utc(now) - latest_started).total_seconds()
    if remaining <= 0:
        return 0.0
    return remaining if remaining <= tolerance else None


def attempt_is_due(
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
    trigger_value: str | None = None,
) -> bool:
    """Return whether an invocation may start immediately without an early wait."""

    return _due_wait_seconds(path, now=now, trigger_value=trigger_value) == 0.0


def begin_attempt_if_due(
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
    trigger_value: str | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> tuple[bool, Path]:
    """Wait through bounded jitter, re-check persisted timing, then initialize when due."""

    target = _bounded_path(path)
    checked_at = _utc(now)
    wait_seconds = _due_wait_seconds(path, now=checked_at, trigger_value=trigger_value)
    if wait_seconds is None:
        return False, target
    if wait_seconds > 0:
        (sleeper or time.sleep)(wait_seconds)
        checked_at = checked_at + timedelta(seconds=wait_seconds) if now is not None else _utc()
    # A native cron and a completion relay can both have been queued. Re-read
    # after the wait so a newer persisted claim wins instead of being replaced.
    if not attempt_is_due(path, now=checked_at, trigger_value=trigger_value):
        return False, target
    begin_attempt(path, now=checked_at, trigger_value=trigger_value)
    return True, target


def _metrics_fields(metrics: CollectionMetrics, listening_seconds: float | None = None) -> dict[str, object]:
    observed_listening = listening_seconds if listening_seconds is not None else metrics.listening_seconds
    return {
        "collectorStartedAt": _timestamp(metrics.collector_started_at) if metrics.collector_started_at else None,
        "listeningSeconds": round(max(0.0, observed_listening), 3),
        "messages": metrics.messages,
        "dnsNames": metrics.dns_names,
        "matches": metrics.matches,
        "newRecords": metrics.new_records,
        "connectionAttempts": metrics.connection_attempts,
        "connections": metrics.connections,
    }


def _summary(outcome: CollectionOutcome) -> str:
    return {
        "healthy-empty": "Input was processed successfully; no candidate matched the publication heuristic.",
        "healthy-matches": "Input was processed successfully and one or more candidates matched.",
        "no-input": "A source connection opened, but no certificate DNS names were received.",
        "partial": "The collector processed only part of its expected listening window.",
        "failed": "The collector could not establish or complete a usable listening window.",
    }[outcome]


def complete_attempt(
    metrics: CollectionMetrics,
    outcome: CollectionOutcome,
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> Path:
    if outcome not in OUTCOMES:
        raise ValueError("Unsupported CertStream collection outcome.")
    artifact = read_collection_health(path, allow_running=True)
    if artifact is None or artifact["latestAttempt"] is None:
        begin_attempt(path, now=metrics.collector_started_at or now)
        artifact = read_collection_health(path, allow_running=True)
    if artifact is None or artifact["latestAttempt"] is None or artifact["latestAttempt"]["outcome"] is not None:
        raise ValueError("No running CertStream collection attempt is available to complete.")
    ended_at = _utc(now)
    artifact["generatedAt"] = _timestamp(ended_at)
    artifact["latestAttempt"].update(_metrics_fields(metrics))
    artifact["latestAttempt"].update(
        {
            "endedAt": _timestamp(ended_at),
            "outcome": outcome,
            "summary": _summary(outcome),
        }
    )
    if outcome in {"healthy-empty", "healthy-matches"}:
        artifact["lastSuccessAt"] = _timestamp(ended_at)
    artifact["freshness"] = _freshness(
        artifact["lastSuccessAt"],
        ended_at,
        artifact["staleAfterSeconds"],
    )
    return _write_collection_health(artifact, path)


def finalize_workflow(path: str | Path | None = None, *, now: datetime | None = None) -> Path:
    """Close an attempt left running because an Actions setup or collector step failed."""

    artifact = read_collection_health(path, allow_running=True)
    if artifact is None or artifact["latestAttempt"] is None:
        begin_attempt(path, now=now)
        artifact = read_collection_health(path, allow_running=True)
    if artifact is None:
        raise RuntimeError("Collection-health initialization failed.")
    attempt = artifact["latestAttempt"]
    if attempt is None:
        raise RuntimeError("Collection-health attempt initialization failed.")
    if attempt["outcome"] is not None:
        return _bounded_path(path)

    metrics = CollectionMetrics(
        collector_started_at=_parse_timestamp(attempt["collectorStartedAt"]),
        listening_seconds=float(attempt["listeningSeconds"]),
        messages=attempt["messages"],
        dns_names=attempt["dnsNames"],
        matches=attempt["matches"],
        new_records=attempt["newRecords"],
        connection_attempts=attempt["connectionAttempts"],
        connections=attempt["connections"],
    )
    install_outcome = os.environ.get("CERTSTREAM_INSTALL_OUTCOME", "success")
    prepare_outcome = os.environ.get("CERTSTREAM_PREPARE_OUTCOME", "success")
    if install_outcome != "success" or prepare_outcome != "success" or metrics.connections == 0:
        outcome: CollectionOutcome = "failed"
    elif metrics.dns_names == 0:
        outcome = "no-input"
    else:
        outcome = "partial"
    return complete_attempt(metrics, outcome, path, now=now)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain bounded public CertStream collection-health metadata.")
    parser.add_argument("action", choices=("begin", "begin-if-due", "finalize"))
    return parser


def main(arguments: list[str] | None = None) -> int:
    action = _parser().parse_args(arguments).action
    try:
        due = True
        if action == "begin":
            target = begin_attempt()
        elif action == "begin-if-due":
            due, target = begin_attempt_if_due()
        else:
            target = finalize_workflow()
    except Exception as error:
        print(f"Collection-health update failed: {error}", file=sys.stderr)
        return 1
    if action == "begin-if-due":
        github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
        if github_output:
            with Path(github_output).open("a", encoding="utf-8") as output:
                output.write(f"due={'true' if due else 'false'}\n")
        if not due:
            print("A recent persisted CertStream attempt already owns this cadence window.", flush=True)
            return 0
    print(f"Updated {target.relative_to(Path.cwd())}.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
