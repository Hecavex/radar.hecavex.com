"""Conservative relay ownership, independent of completed run ordering.

The collector itself checks the persisted 15-minute claim under its existing
single-writer concurrency group. A completed run is never a promise of another
handoff: it might have been a no-op, cancelled, or failed before finalization.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Literal


def relay_decision(payload: dict[str, Any]) -> Literal["active-owner", "dispatch"]:
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("Invalid collector run response.")
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("status"), str):
            raise ValueError("Invalid collector run status.")
        if run.get("head_branch") == "main" and run["status"] != "completed":
            return "active-owner"
    return "dispatch"


if __name__ == "__main__":
    print(relay_decision(json.load(sys.stdin)))
