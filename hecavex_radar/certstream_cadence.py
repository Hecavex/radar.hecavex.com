"""Conservative relay ownership, independent of completed run ordering.

The collector itself checks the persisted 15-minute claim under its existing
single-writer concurrency group. A completed run is never a promise of another
handoff: it might have been a no-op, cancelled, or failed before finalization.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

COLLECTOR_TIMEOUT = timedelta(minutes=20)
MAX_JOB_RECONCILIATIONS = 5


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _newer_completed(runs: list[Any], created: datetime, now: datetime) -> bool:
    for run in runs:
        if (not isinstance(run, dict) or run.get("head_branch") != "main" or run.get("status") != "completed"
                or run.get("conclusion") not in {"success", "failure", "cancelled", "timed_out", "skipped",
                                                "neutral", "action_required", "stale", "startup_failure"}):
            continue
        started = _timestamp(run.get("created_at"))
        ended = _timestamp(run.get("updated_at"))
        if started is not None and ended is not None and created < started <= ended <= now:
            return True
    return False


def relay_decision(
    payload: dict[str, Any], *, now: datetime | None = None,
    load_jobs: Callable[[int], dict[str, Any]] | None = None,
) -> Literal["active-owner", "dispatch"]:
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list) or len(runs) > 20:
        raise ValueError("Invalid collector run response.")
    now = now or datetime.now(UTC)
    if now.utcoffset() != timedelta(0):
        raise ValueError("Cadence reconciliation requires a UTC clock.")
    reconciliations = 0
    for run in runs:
        if (not isinstance(run, dict) or not isinstance(run.get("status"), str)
                or not isinstance(run.get("head_branch"), str)):
            raise ValueError("Invalid collector run status.")
        if run.get("head_branch") == "main" and run["status"] != "completed":
            created = _timestamp(run.get("created_at"))
            updated = _timestamp(run.get("updated_at"))
            identifier = run.get("id")
            if (run["status"] != "queued" or load_jobs is None or created is None or updated is None
                    or not created <= updated <= now or now - created <= COLLECTOR_TIMEOUT
                    or not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0
                    or not _newer_completed(runs, created, now)
                    or reconciliations >= MAX_JOB_RECONCILIATIONS):
                return "active-owner"
            # Read-only reconciliation, never cancellation. A single fresh response
            # with any job still owns the slot, regardless of job status or age.
            reconciliations += 1
            jobs = load_jobs(identifier)
            if (not isinstance(jobs, dict) or type(jobs.get("total_count")) is not int
                    or jobs["total_count"] < 0 or not isinstance(jobs.get("jobs"), list)):
                raise ValueError("Invalid collector jobs response; refusing dispatch.")
            if jobs["total_count"] != 0 or jobs["jobs"]:
                return "active-owner"
            print(f"Reconciled superseded queued collector {identifier} created {run['created_at']}: zero jobs.",
                  file=sys.stderr)
    return "dispatch"


def _github_jobs(repository: str, identifier: int) -> dict[str, Any]:
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ValueError("Invalid repository for cadence reconciliation.")
    executable = shutil.which("gh")
    if executable is None:
        raise ValueError("GitHub CLI is required for queued-run reconciliation.")
    result = subprocess.run(  # noqa: S603 - fixed executable, validated repository and integer run ID.
        [executable, "api", "--method", "GET", "-H", "Cache-Control: no-cache",
         f"/repos/{repository}/actions/runs/{identifier}/jobs?per_page=1"],
        capture_output=True, check=True, timeout=20,
    )
    if len(result.stdout) > 256 * 1024:
        raise ValueError("Collector jobs response exceeds reconciliation bound.")
    payload: object = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Invalid collector jobs response.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository")
    options = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Invalid collector run response.")
        loader = (lambda identifier: _github_jobs(options.repository, identifier)) if options.repository else None
        print(relay_decision(payload, load_jobs=loader))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Cadence reconciliation refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
