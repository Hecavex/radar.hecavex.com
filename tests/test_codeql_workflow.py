"""Bound the source-only CodeQL contract without a YAML runtime dependency."""

import ast
import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/codeql.yml"


def _guard_accepts(event: str, ref: str, base: str = "", head: str = "", fork: bool = False) -> bool:
    """Evaluate only boolean comparisons from the actual Actions job guard."""
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = text.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
    values = {
        "github.event.pull_request.head.repo.full_name": "fork/repo" if fork else "owner/repo",
        "github.repository": "owner/repo",
        "github.event_name": event,
        "github.base_ref": base,
        "github.head_ref": head,
        "github.ref": ref,
    }
    for key, value in values.items():
        guard = guard.replace(key, repr(value))
    parsed = ast.parse(" ".join(guard.split()).replace("&&", "and").replace("||", "or"), mode="eval")

    def visit(node: ast.AST) -> bool:
        if isinstance(node, ast.BoolOp):
            operands = [visit(value) for value in node.values]
            return all(operands) if isinstance(node.op, ast.And) else any(operands)
        assert isinstance(node, ast.Compare) and len(node.ops) == 1
        assert isinstance(node.left, ast.Constant) and isinstance(node.comparators[0], ast.Constant)
        assert isinstance(node.ops[0], (ast.Eq, ast.NotEq))
        equal = node.left.value == node.comparators[0].value
        return equal if isinstance(node.ops[0], ast.Eq) else not equal

    return visit(parsed.body)


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
def test_non_pr_guard_accepts_only_main(event: str) -> None:
    assert _guard_accepts(event, "refs/heads/main")
    assert not _guard_accepts(event, "refs/heads/radar-data")
    assert not _guard_accepts(event, "refs/heads/feature")
    assert not _guard_accepts(event, "refs/tags/main")


def test_pr_guard_preserves_source_review_boundary() -> None:
    assert _guard_accepts("pull_request", "refs/pull/1/merge", "main", "feature")
    assert not _guard_accepts("pull_request", "refs/pull/1/merge", "main", "radar-data")
    assert not _guard_accepts("pull_request", "refs/pull/1/merge", "radar-data", "feature")
    assert not _guard_accepts("pull_request", "refs/pull/1/merge", "main", "feature", fork=True)


def test_triggers_languages_and_non_executing_analysis_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    events = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.findall(r"^  (\w+):", events, re.MULTILINE) == [
        "push", "pull_request", "schedule", "workflow_dispatch",
    ]
    assert "  push:\n    branches: [main]\n" in events
    assert "  pull_request:\n    branches: [main]\n" in events
    assert 'cron: "37 4 * * 1"' in events
    assert "language: [actions, javascript-typescript, python]" in text
    assert "languages: ${{ matrix.language }}" in text
    assert "category: /language:${{ matrix.language }}" in text
    assert "build-mode: none" in text
    assert "disable-default-queries: false\n            threat-models: []" in text
    assert "persist-credentials: false" in text
    assert not re.search(r"^\s+(run|ref|queries|packs|config-file|paths-ignore):", text, re.MULTILINE)
    assert "data_branch" not in text and "autobuild" not in text
    uses = re.findall(r"uses: ([^\s]+)", text)
    assert len(uses) == 3
    assert [use.split("@")[0] for use in uses] == [
        "actions/checkout", "github/codeql-action/init", "github/codeql-action/analyze",
    ]
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", use) for use in uses)
    assert uses[1].split("@")[1] == uses[2].split("@")[1]
    permissions = text.split("\npermissions:\n", 1)[1].split("\njobs:", 1)[0]
    assert permissions.strip().splitlines() == [
        "actions: read", "  contents: read", "  packages: read", "  security-events: write",
    ]
