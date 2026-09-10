"""Replay completion races using the actual workflow condition and concurrency scope.

This deliberately uses a small, fail-closed interpreter for the workflow's current
boolean expression rather than adding a YAML/runtime dependency to collector tests.
It models job admission and concurrency, not GitHub's hosted scheduler internals.
"""

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from hecavex_radar.certstream_cadence import relay_decision

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/maintain-certstream-cadence.yml"


def _block(workflow: str, key: str, indent: int) -> dict[str, str]:
    match = re.search(rf"(?m)^{' ' * indent}{key}:\n((?:{' ' * (indent + 2)}[^\n]+\n)+)", workflow)
    if match is None:
        return {}
    return dict(line.strip().split(": ", 1) for line in match[1].splitlines())


def _admitted(workflow: str, context: dict[str, Any]) -> bool:
    match = re.search(r"(?m)^    if: >-\n((?:      [^\n]+\n)+)", workflow)
    assert match is not None
    expression = " ".join(line.strip() for line in match[1].splitlines())
    tree = ast.parse(expression.replace("&&", " and ").replace("||", " or "), mode="eval")

    def value(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return value(node.body)
        if isinstance(node, ast.Name) and node.id == "github":
            return context
        if isinstance(node, ast.Attribute):
            parent = value(node.value)
            return parent.get(node.attr) if isinstance(parent, dict) else None
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BoolOp):
            items = [bool(value(item)) for item in node.values]
            if isinstance(node.op, ast.And):
                return all(items)
            if isinstance(node.op, ast.Or):
                return any(items)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = value(node.left), value(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise AssertionError(f"Unsupported workflow condition node: {type(node).__name__}")

    return bool(value(tree))


def _event(kind: str, conclusion: str = "success", branch: str = "main") -> dict[str, Any]:
    payload = {"source_workflow": "Collect CertStream candidates", "source_ref": branch}
    event = ({"client_payload": payload} if kind == "repository_dispatch" else
             {"workflow_run": {"head_branch": branch, "conclusion": conclusion}})
    return {"ref": "refs/heads/main", "event_name": kind, "event": event}


def _replay(workflow: str, events: list[dict[str, Any]]) -> tuple[list[int], list[int], list[int]]:
    """An admitted job waits six minutes; later events arrive before that wait ends."""
    waiting: list[int] = []
    cancelled: list[int] = []
    skipped: list[int] = []
    global_group = _block(workflow, "concurrency", 0)
    job_group = _block(workflow, "concurrency", 4)
    for number, event in enumerate(events):
        # Reproduces the old workflow-wide cancellation *before* a skipped job.
        if global_group.get("cancel-in-progress") == "true":
            cancelled.extend(waiting)
            waiting.clear()
        if not _admitted(workflow, event):
            skipped.append(number)
            continue
        if job_group.get("cancel-in-progress") == "true":
            cancelled.extend(waiting)
            waiting.clear()
        if waiting and (job_group or global_group).get("queue") != "max" and len(waiting) > 1:
            cancelled.append(waiting.pop())
        waiting.append(number)
    return waiting, cancelled, skipped


def test_successful_collector_completion_does_not_cancel_its_waiting_handoff() -> None:
    workflow = WORKFLOW.read_text()
    events = [_event("repository_dispatch"), _event("workflow_run")]
    assert _replay(workflow, events) == ([0], [], [1])
    # The exact previous policy reproduces Sep 9/10: valid handoff cancelled,
    # successful workflow_run skipped, and no owner left to dispatch a successor.
    previous = "concurrency:\n  group: radar-certstream-cadence\n  cancel-in-progress: true\n" + workflow
    assert _replay(previous, events) == ([], [0], [1])


def test_reverse_completion_order_still_has_one_handoff() -> None:
    assert _replay(WORKFLOW.read_text(), [_event("workflow_run"), _event("repository_dispatch")]) == ([1], [], [0])


def test_eligible_failure_handoffs_remain_queued_and_collector_ownership_deduplicates() -> None:
    workflow = WORKFLOW.read_text()
    events = [_event("repository_dispatch", "failure"), _event("workflow_run", "failure"),
              _event("workflow_dispatch")]
    assert _replay(workflow, events) == ([0, 1, 2], [], [])
    # The first serialized relay can dispatch once; queued handoffs see the
    # child owner and never create a second listener. Existing persisted due
    # claims remain authoritative if that child has already finished.
    assert relay_decision({"workflow_runs": []}) == "dispatch"
    owner = {"workflow_runs": [{"status": "queued", "head_branch": "main"}]}
    assert [relay_decision(owner) for _ in events[1:]] == ["active-owner", "active-owner"]


@pytest.mark.parametrize("kind", ["repository_dispatch", "workflow_run"])
def test_non_main_completion_cannot_claim_relay(kind: str) -> None:
    assert _replay(WORKFLOW.read_text(), [_event(kind, "failure", "untrusted")]) == ([], [], [0])


def test_concurrency_is_inside_admitted_job_and_preserves_wait_single_post_and_due_guard() -> None:
    workflow = WORKFLOW.read_text()
    assert not _block(workflow, "concurrency", 0)
    assert _block(workflow, "concurrency", 4) == {
        "group": "radar-certstream-cadence", "cancel-in-progress": "false", "queue": "max",
    }
    assert workflow.index("  relay:") < workflow.index("    if:") < workflow.index("    concurrency:")
    assert "    environment: radar-certstream-cadence" in workflow
    assert workflow.count("gh api --method POST") == 1
    assert "inputs[cadence_relay]=true" in workflow
    collector = (WORKFLOW.parent / "collect-certstream.yml").read_text()
    assert "group: radar-certstream-writer" in collector
    assert "cancel-in-progress: false" in collector
    assert 'CERTSTREAM_DURATION_SECONDS: "480"' in collector
    assert "collection_health begin-if-due" in collector
    assert "steps.cadence.outputs.due == 'true'" in collector
