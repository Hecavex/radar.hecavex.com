import io
import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from hecavex_radar import certstream_cadence
from hecavex_radar.certstream_cadence import relay_decision

NOW = datetime(2026, 9, 7, 14, 50, tzinfo=UTC)


def _ghost() -> dict:
    return {"id": 34132479390, "status": "queued", "conclusion": None, "head_branch": "main",
            "created_at": "2026-09-07T14:21:09Z", "updated_at": "2026-09-07T14:21:09Z"}


def _completed() -> dict:
    return {"id": 34133571031, "status": "completed", "conclusion": "success", "head_branch": "main",
            "created_at": "2026-09-07T14:33:10Z", "updated_at": "2026-09-07T14:41:43Z"}


def test_observed_superseded_zero_job_ghost_allows_one_standard_dispatch() -> None:
    calls = []

    def jobs(identifier: int) -> dict:
        calls.append(identifier)
        return {"total_count": 0, "jobs": []}

    assert relay_decision({"workflow_runs": [_completed(), _ghost()]}, now=NOW, load_jobs=jobs) == "dispatch"
    assert calls == [34132479390]


@pytest.mark.parametrize("patch", [
    {"created_at": "2026-09-07T14:35:00Z", "updated_at": "2026-09-07T14:35:00Z"},
    {"created_at": "2026-09-07T14:30:00Z", "updated_at": "2026-09-07T14:30:00Z"},
    {"status": "in_progress"}, {"status": "waiting"}, {"status": "pending"}, {"status": "unknown"},
    {"created_at": None}, {"updated_at": None}, {"created_at": "invalid"},
    {"created_at": "2026-09-07T14:51:00Z"}, {"updated_at": "2026-09-07T14:51:00Z"},
    {"updated_at": "2026-09-07T14:00:00Z"}, {"id": True},
])
def test_uncertain_recent_or_active_run_still_owns_without_job_lookup(patch: dict) -> None:
    def unexpected_lookup(identifier: int) -> dict:
        raise AssertionError("Ineligible owner must not be reconciled")

    assert relay_decision({"workflow_runs": [_completed(), {**_ghost(), **patch}]},
                          now=NOW, load_jobs=unexpected_lookup) == "active-owner"


@pytest.mark.parametrize("patch", [
    {"status": "in_progress"}, {"updated_at": None}, {"conclusion": None},
    {"head_branch": "other"}, {"created_at": "2026-09-07T14:00:00Z"},
    {"updated_at": "2026-09-07T14:51:00Z"},
])
def test_no_valid_newer_finished_main_run_cannot_release_ghost(patch: dict) -> None:
    assert relay_decision({"workflow_runs": [{**_completed(), **patch}, _ghost()]},
                          now=NOW, load_jobs=lambda _: {"total_count": 0, "jobs": []}) == "active-owner"


@pytest.mark.parametrize("jobs", [
    {"total_count": 1, "jobs": [{"status": "in_progress"}]},
    {"total_count": 1, "jobs": [{"status": "completed"}]},
    {"total_count": 1, "jobs": []}, {"total_count": 0, "jobs": [{}]},
])
def test_any_job_or_conflicting_nonzero_count_retains_owner(jobs: dict) -> None:
    assert relay_decision({"workflow_runs": [_completed(), _ghost()]},
                          now=NOW, load_jobs=lambda _: jobs) == "active-owner"


@pytest.mark.parametrize("jobs", [{}, {"total_count": False, "jobs": []},
                                 {"total_count": -1, "jobs": []}, {"total_count": 0, "jobs": None}])
def test_invalid_jobs_schema_fails_closed(jobs: dict) -> None:
    with pytest.raises(ValueError, match="jobs response"):
        relay_decision({"workflow_runs": [_completed(), _ghost()]}, now=NOW, load_jobs=lambda _: jobs)


def test_fresh_queued_successor_blocks_repeated_dispatch() -> None:
    runs = [_completed(), _ghost()]
    def loader(identifier: int) -> dict:
        return {"total_count": 0, "jobs": []}
    assert relay_decision({"workflow_runs": runs}, now=NOW, load_jobs=loader) == "dispatch"
    successor = {**_ghost(), "id": 34140000000, "created_at": "2026-09-07T14:49:00Z",
                 "updated_at": "2026-09-07T14:49:00Z"}
    assert relay_decision({"workflow_runs": [successor, *runs]}, now=NOW, load_jobs=loader) == "active-owner"


def test_api_failure_exits_without_dispatch_decision(monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["cadence", "--repository", "Hecavex/radar.hecavex.com"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"workflow_runs": [_completed(), _ghost()]})))

    def fail_request(*args: object) -> dict:
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(certstream_cadence, "_github_jobs", fail_request)
    assert certstream_cadence.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "refused" in output.err


def test_job_reconciliation_budget_fails_closed() -> None:
    ghosts = [{**_ghost(), "id": number} for number in range(1, 7)]
    calls = []

    def loader(identifier: int) -> dict:
        calls.append(identifier)
        return {"total_count": 0, "jobs": []}

    assert relay_decision({"workflow_runs": [_completed(), *ghosts]},
                          now=NOW, load_jobs=loader) == "active-owner"
    assert len(calls) == 5


def test_newer_completed_noop_does_not_take_relay_ownership() -> None:
    assert relay_decision({"workflow_runs": [
        {"id": 3, "status": "completed", "conclusion": "success", "head_branch": "main"},
        {"id": 2, "status": "completed", "conclusion": "cancelled", "head_branch": "main"},
        {"id": 1, "status": "completed", "conclusion": "success", "head_branch": "main"},
    ]}) == "dispatch"


def test_active_main_owner_prevents_duplicate_listener_dispatch() -> None:
    for status in ("queued", "in_progress", "waiting", "pending"):
        assert relay_decision({"workflow_runs": [
            {"status": status, "head_branch": "main"},
        ]}) == "active-owner"


def test_nonproduction_branch_cannot_stop_production_relay() -> None:
    assert relay_decision({"workflow_runs": [
        {"status": "queued", "head_branch": "untrusted-branch"},
    ]}) == "dispatch"
