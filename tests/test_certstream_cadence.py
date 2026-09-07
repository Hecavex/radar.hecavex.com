from hecavex_radar.certstream_cadence import relay_decision


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
