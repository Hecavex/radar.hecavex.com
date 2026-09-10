"""Replay pending deployment replacement from the actual workflow policy.

This models the documented workflow concurrency queue, not GitHub's scheduler.
Job eligibility is evaluated only after workflow-level pending admission, where
an ineligible completion could already have displaced a valid pending run.
"""

from pathlib import Path
from typing import Any

import pytest
from test_certstream_relay_events import _admitted, _block

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-pages.yml"


def _event(kind: str, *, eligible: bool = True) -> dict[str, Any]:
    if kind == "repository_dispatch":
        event = {"client_payload": {
            "source_ref": "main", "source_workflow": "Sync radar snapshot",
            "source_conclusion": "success" if eligible else "failure",
        }}
    else:
        event = {"workflow_run": {
            "head_branch": "main", "name": "CI", "conclusion": "success",
            "event": "push" if eligible else "pull_request",
        }}
    return {"event_name": kind, "event": event}


def _drain(
    workflow: str, arrivals: list[dict[str, Any]],
) -> tuple[list[int], list[int], list[int]]:
    """Run 0 already owns both build/deploy; arrivals occur while it builds."""
    policy_text = "\n".join(line for line in workflow.splitlines() if not line.lstrip().startswith("#")) + "\n"
    policy = _block(policy_text, "concurrency", 0)
    assert policy["group"] == "github-pages"
    assert policy["cancel-in-progress"] == "false"
    pending: list[int] = []
    cancelled: list[int] = []
    for number, _event_context in enumerate(arrivals, 1):
        if policy.get("queue") != "max":
            cancelled.extend(pending)
            pending.clear()
        pending.append(number)
    admitted, skipped = [0], []
    for number in pending:
        (admitted if _admitted(workflow, arrivals[number - 1]) else skipped).append(number)
    return admitted, cancelled, skipped


def test_skipped_ci_completion_cannot_replace_valid_pending_snapshot_deploy() -> None:
    workflow = WORKFLOW.read_text()
    # Observed Sep10: active34437296807, pending34437403701, skipped34437562523.
    arrivals = [_event("repository_dispatch"), _event("workflow_run", eligible=False)]
    assert _drain(workflow, arrivals) == ([0, 1], [], [2])
    old_policy = workflow.replace("  queue: max\n", "")
    assert _drain(old_policy, arrivals) == ([0], [1], [2])


@pytest.mark.parametrize("first_kind", ["repository_dispatch", "workflow_run"])
def test_eligible_deployments_survive_later_ineligible_and_eligible_arrivals(first_kind: str) -> None:
    arrivals = [
        _event(first_kind), _event("repository_dispatch", eligible=False),
        _event("workflow_run"), _event("workflow_run", eligible=False),
    ]
    assert _drain(WORKFLOW.read_text(), arrivals) == ([0, 1, 3], [], [2, 4])


def test_workflow_queue_serializes_entire_build_and_deploy_with_revision_guards() -> None:
    workflow = WORKFLOW.read_text()
    # Strip comments only for the shared minimal mapping reader.
    policy_text = "\n".join(line for line in workflow.splitlines() if not line.lstrip().startswith("#")) + "\n"
    assert _block(policy_text, "concurrency", 0) == {
        "group": "github-pages", "cancel-in-progress": "false", "queue": "max",
    }
    assert workflow.index("concurrency:") < workflow.index("jobs:")
    assert "    concurrency:" not in workflow
    assert "    needs: build" in workflow
    assert "if: needs.build.outputs.should_deploy == 'true'" in workflow
    assert workflow.count("python -m hecavex_radar.publication_selection") == 2
    assert 'args+=(--trigger-data "${TRIGGER_DATA_SHA}")' in workflow
    assert '--view operational --revision "${DATA_SHA}"' in workflow
    assert (
        workflow.index("Refuse source or data superseded while building")
        < workflow.index("uses: actions/deploy-pages@")
    )
