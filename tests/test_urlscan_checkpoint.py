from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from hecavex_radar import urlscan, urlscan_checkpoint
from hecavex_radar.urlscan import (
    _BudgetedRequester,
    _state_for_run,
    _URLScanRateLimitError,
    _validated_hunt_state,
)
from hecavex_radar.urlscan_checkpoint import SearchCheckpointStore, SearchUnavailable, _sort_token

QUERY = "task.visibility:public AND date:>now-7d AND domain:example"


def test_query_custody_never_retires_unclassified_pending_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    query = 'date:>now-7d AND task.visibility:public AND (task.domain.keyword:"candidate.example")'
    store = SearchCheckpointStore.load("data/urlscan/search-checkpoints.json", now=datetime(2026, 9, 10, tzinfo=UTC))
    store.search(query, 100, "unused", _PagedProvider())
    before = copy.deepcopy(store.state)
    report = urlscan_checkpoint.audit_ownership(store.state, [query])
    assert report[0]["queryFamily"] == "exact-domain-batch"
    assert report[0]["ownership"] == "active-in-supplied-plan"
    assert urlscan_checkpoint.audit_ownership(store.state, [])[0]["retired"] is False
    assert store.state == before
    assert "candidate.example" not in json.dumps(store.state)


def test_query_family_recognizes_fixed_builders_only():
    registry = urlscan.load_brand_registry()
    assert urlscan_checkpoint.query_family(urlscan.build_domain_query(registry, 7)) == "domain"
    assert urlscan_checkpoint.query_family(urlscan.build_title_query(registry, 7)) == "title"
    assert urlscan_checkpoint.query_family(urlscan._public_search_query("hash:" + "a" * 64, 7)) == "hash-pivot"
    assert urlscan_checkpoint.query_family(QUERY) == "legacy-unclassified"


def test_byte_retention_preserves_all_pending_cursors_at_supported_query_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    now = datetime(2026, 9, 7, tzinfo=UTC)
    store = SearchCheckpointStore.load("data/urlscan/search-checkpoints.json", now=now)
    store.search(QUERY, 100, "unused", _PagedProvider())
    seed = next(iter(store.state["queries"].values()))
    store.state["queries"] = {}
    for index in range(urlscan_checkpoint.MAXIMUM_QUERIES):
        key = hashlib.sha256(str(index).encode()).hexdigest()
        row = copy.deepcopy(seed)
        row["queryHash"] = key
        row["updatedAt"] = "2026-07-01T00:00:00.000Z"
        store.state["queries"][key] = row
    expected_cursors = {key: row["nextSearchAfter"] for key, row in store.state["queries"].items()}
    path = store.commit()
    assert path.stat().st_size <= urlscan_checkpoint.MAXIMUM_STATE_BYTES
    loaded = SearchCheckpointStore.load(path, now=now)
    assert len(loaded.state["queries"]) == urlscan_checkpoint.MAXIMUM_QUERIES
    assert {key: row["nextSearchAfter"] for key, row in loaded.state["queries"].items()} == expected_cursors
    with pytest.raises(urlscan_checkpoint.CheckpointCapacityError, match="state-capacity"):
        loaded.search(QUERY + "-another", 100, "unused", lambda *_: pytest.fail("capacity preflight precedes network"))
    assert loaded.summary()["backlog"] == urlscan_checkpoint.MAXIMUM_QUERIES


def test_checkpoint_capacity_is_checked_before_archive_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URLSCAN_API_KEY", "test-key")
    monkeypatch.setattr(urlscan, "hunt_urlscan", lambda *_args, **_kwargs: [])
    def fail_preflight(_self: object) -> None:
        raise urlscan_checkpoint.CheckpointCapacityError("state-capacity")
    monkeypatch.setattr(SearchCheckpointStore, "preflight", fail_preflight)
    monkeypatch.setattr(urlscan, "write_urlscan_archive", lambda *_: pytest.fail("must preflight first"))
    assert urlscan.main() == 1
    health = json.loads((tmp_path / "data/urlscan/hunt-state.json").read_text(encoding="utf-8"))
    assert health["lastFailureCode"] == "state-capacity"


def _result(number: int) -> dict[str, object]:
    identifier = f"00000000-0000-0000-0000-{number:012x}"
    return {
        "_id": identifier,
        "sort": [number],
        "task": {"uuid": identifier, "visibility": "public"},
    }


class _PagedProvider:
    def __init__(self) -> None:
        self.starts: list[int] = []

    def __call__(self, url: str, _key: str) -> dict[str, object]:
        query = parse_qs(urlsplit(url).query)
        size = int(query["size"][0])
        after = int(query.get("search_after", ["-1"])[0])
        start = after + 1
        self.starts.append(start)
        return {
            "results": [_result(index) for index in range(start, min(start + size, 250))],
            # URLScan's has_more flag is about its 10k search ceiling, not
            # ordinary page continuation. Pagination must still continue.
            "has_more": False,
            "total": 250,
        }


def test_total_drives_multi_run_backlog_when_has_more_is_false(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = "data/urlscan/search-checkpoints.json"
    provider = _PagedProvider()
    start = datetime(2026, 8, 26, 10, tzinfo=UTC)

    first = SearchCheckpointStore.load(path, now=start)
    assert len(first.search(QUERY, 100, "unused", provider, backlog_pages=1)) == 100
    row = next(iter(first.state["queries"].values()))
    assert row["nextSearchAfter"] == [99]
    assert row["complete"] is False
    first.commit()

    second = SearchCheckpointStore.load(path, now=start + timedelta(hours=1))
    assert len(second.search(QUERY, 100, "unused", provider, backlog_pages=1)) == 200
    row = next(iter(second.state["queries"].values()))
    assert row["nextSearchAfter"] == [199]
    assert row["backlogResultsSeen"] == 200
    assert row["complete"] is False
    second.commit()

    third = SearchCheckpointStore.load(path, now=start + timedelta(hours=2))
    assert len(third.search(QUERY, 100, "unused", provider, backlog_pages=1)) == 150
    row = next(iter(third.state["queries"].values()))
    assert row["nextSearchAfter"] is None
    assert row["backlogResultsSeen"] == 250
    assert row["complete"] is True
    assert provider.starts == [0, 0, 100, 0, 200]


def test_unperformed_search_does_not_mutate_or_complete_checkpoint(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = "data/urlscan/search-checkpoints.json"
    now = datetime(2026, 8, 26, 10, tzinfo=UTC)
    store = SearchCheckpointStore.load(path, now=now)
    store.search(QUERY, 100, "unused", _PagedProvider(), backlog_pages=1)
    store.commit()

    interrupted = SearchCheckpointStore.load(path, now=now + timedelta(hours=1))
    before = copy.deepcopy(interrupted.state)

    def unavailable(_url: str, _key: str) -> object:
        raise SearchUnavailable("budget exhausted")

    assert interrupted.search(QUERY, 100, "unused", unavailable, backlog_pages=1) == []
    assert interrupted.state == before
    assert interrupted.dirty is False


def test_budgeted_requester_uses_explicit_search_exhaustion_signal() -> None:
    requester = _BudgetedRequester(
        lambda _url, _key: pytest.fail("provider must not be called"),
        search_used=1,
        result_used=0,
        daily_search_cap=1,
        daily_result_cap=10,
        run_search_cap=10,
        run_result_cap=10,
    )
    with pytest.raises(SearchUnavailable):
        requester("https://urlscan.io/api/v1/search/?q=test", "unused")
    assert requester.exhausted is True


def test_budgeted_requester_counts_a_provider_attempt_that_fails() -> None:
    def unavailable(_url: str, _key: str) -> object:
        raise RuntimeError("temporary provider failure")

    requester = _BudgetedRequester(
        unavailable,
        search_used=0,
        result_used=0,
        daily_search_cap=10,
        daily_result_cap=10,
        run_search_cap=10,
        run_result_cap=10,
    )

    with pytest.raises(RuntimeError, match="temporary provider failure"):
        requester("https://urlscan.io/api/v1/search/?q=test", "unused")

    assert requester.search_used == 1
    assert requester.run_search_requests == 1


def test_provider_rate_limit_is_not_local_budget_exhaustion() -> None:
    def rate_limited(_url: str, _key: str) -> object:
        raise _URLScanRateLimitError("provider limited")

    requester = _BudgetedRequester(
        rate_limited,
        search_used=0,
        result_used=0,
        daily_search_cap=10,
        daily_result_cap=10,
        run_search_cap=10,
        run_result_cap=10,
    )

    with pytest.raises(_URLScanRateLimitError, match="provider limited"):
        requester("https://urlscan.io/api/v1/search/?q=test", "unused")

    assert requester.search_used == 1
    assert requester.run_search_requests == 1
    assert requester.exhausted is False
    assert requester.provider_exhausted is True

    with pytest.raises(_URLScanRateLimitError, match="not performed"):
        requester("https://urlscan.io/api/v1/search/?q=test", "unused")
    assert requester.search_used == 1


def test_provider_rate_limit_persists_failed_health_without_refreshing_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URLSCAN_ARCHIVE_ROOT", "data/urlscan")
    monkeypatch.setenv("URLSCAN_API_KEY", "test-key")
    prior = _state_for_run(
        datetime(2026, 8, 29, 10, tzinfo=UTC),
        configured=True,
        outcome="completed",
        search_requests=1,
        result_requests=0,
        candidate_cursor=0,
        candidate_count=0,
        selected_candidates=0,
        last_search_requests=1,
        last_result_requests=0,
    )
    urlscan.write_urlscan_hunt_state("data/urlscan", prior)

    def rate_limited(_url: str, _key: str) -> object:
        raise _URLScanRateLimitError("provider limited")

    def hunt(*_args: object, **kwargs: object) -> list[object]:
        requester = kwargs["requester"]
        assert callable(requester)
        requester("https://urlscan.io/api/v1/search/?q=test", "unused")
        return []

    monkeypatch.setattr(urlscan, "_request_json", rate_limited)
    monkeypatch.setattr(urlscan, "hunt_urlscan", hunt)

    assert urlscan.main() == 1
    state = urlscan.read_urlscan_hunt_state("data/urlscan")
    assert state is not None
    assert state["lastOutcome"] == "failed"
    assert state["lastSuccessAt"] == prior["lastSuccessAt"]
    assert state["consecutiveFailures"] == 1
    assert state["degradedSince"] == state["lastRunAt"]
    assert state["lastRunSearchRequests"] == 1


def test_malformed_checkpoint_records_bounded_failure_without_leaking_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URLSCAN_ARCHIVE_ROOT", "data/urlscan")
    monkeypatch.setenv("URLSCAN_API_KEY", "test-key")
    prior = _state_for_run(
        datetime(2026, 8, 29, 10, tzinfo=UTC),
        configured=True,
        outcome="completed",
        search_requests=1,
        result_requests=2,
        candidate_cursor=2,
        candidate_count=4,
        selected_candidates=4,
        last_search_requests=1,
        last_result_requests=2,
    )
    urlscan.write_urlscan_hunt_state("data/urlscan", prior)
    checkpoint = tmp_path / "data/urlscan/search-checkpoints.json"
    checkpoint.write_text('{"private-query":"do-not-log"', encoding="utf-8")

    assert urlscan.main() == 1

    output = capsys.readouterr().out
    assert "malformed or unreadable" in output
    assert "no provider request was made" in output
    assert "failed health state recorded" in output
    assert "private-query" not in output
    assert "do-not-log" not in output
    state = urlscan.read_urlscan_hunt_state("data/urlscan")
    assert state is not None
    assert state["lastOutcome"] == "failed"
    assert state["lastSuccessAt"] == prior["lastSuccessAt"]
    assert state["consecutiveFailures"] == 1
    assert state["candidateCursor"] == 2
    assert state["candidateCount"] == 4
    assert state["checkpointCoverage"] == prior["checkpointCoverage"]
    assert state["lastRunSearchRequests"] == 0
    assert state["lastRunResultRequests"] == 0


def test_missing_checkpoint_bootstraps_instead_of_becoming_malformed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URLSCAN_ARCHIVE_ROOT", "data/urlscan")
    monkeypatch.setenv("URLSCAN_API_KEY", "test-key")
    monkeypatch.setattr(urlscan, "hunt_urlscan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(urlscan, "write_urlscan_archive", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        urlscan,
        "write_urlscan_intelligence_archive",
        lambda *_args, **_kwargs: 0,
    )

    assert urlscan.main() == 0

    state = urlscan.read_urlscan_hunt_state("data/urlscan")
    assert state is not None
    assert state["lastOutcome"] == "completed"
    assert state["consecutiveFailures"] == 0
    assert state["lastSuccessAt"] == state["lastRunAt"]


def test_urlscan_source_health_persists_repeated_failure_duration() -> None:
    first_at = datetime(2026, 8, 26, 10, tzinfo=UTC)
    first = _state_for_run(
        first_at,
        configured=True,
        outcome="failed",
        search_requests=1,
        result_requests=0,
        candidate_cursor=0,
        candidate_count=0,
        selected_candidates=0,
        last_search_requests=1,
        last_result_requests=0,
    )
    second = _state_for_run(
        first_at + timedelta(hours=2),
        configured=True,
        outcome="failed",
        search_requests=2,
        result_requests=0,
        candidate_cursor=0,
        candidate_count=0,
        selected_candidates=0,
        last_search_requests=1,
        last_result_requests=0,
        previous=first,
    )

    assert second["consecutiveFailures"] == 2
    assert second["degradedSince"] == "2026-08-26T10:00:00.000Z"
    assert second["lastSuccessAt"] is None


def test_urlscan_success_resets_persisted_failure_health() -> None:
    failed_at = datetime(2026, 8, 26, 10, tzinfo=UTC)
    failed = _state_for_run(
        failed_at,
        configured=True,
        outcome="failed",
        search_requests=1,
        result_requests=0,
        candidate_cursor=0,
        candidate_count=0,
        selected_candidates=0,
        last_search_requests=1,
        last_result_requests=0,
    )
    recovered_at = failed_at + timedelta(hours=2)
    recovered = _state_for_run(
        recovered_at,
        configured=True,
        outcome="completed",
        search_requests=2,
        result_requests=0,
        candidate_cursor=0,
        candidate_count=0,
        selected_candidates=0,
        last_search_requests=1,
        last_result_requests=0,
        previous=failed,
    )

    assert recovered["consecutiveFailures"] == 0
    assert recovered["degradedSince"] is None
    assert recovered["lastSuccessAt"] == "2026-08-26T12:00:00.000Z"


def test_urlscan_pre_health_state_is_migrated_on_read() -> None:
    current = _state_for_run(
        datetime(2026, 8, 26, 12, tzinfo=UTC),
        configured=True,
        outcome="completed",
        search_requests=1,
        result_requests=1,
        candidate_cursor=0,
        candidate_count=0,
        selected_candidates=0,
        last_search_requests=1,
        last_result_requests=1,
    )
    legacy = {
        key: value
        for key, value in current.items()
        if key not in {"lastSuccessAt", "consecutiveFailures", "degradedSince"}
    }

    migrated = _validated_hunt_state(legacy)

    assert migrated is not None
    assert migrated["lastSuccessAt"] == "2026-08-26T12:00:00.000Z"
    assert migrated["consecutiveFailures"] == 0
    assert migrated["degradedSince"] is None


@pytest.mark.parametrize(
    "token",
    [
        [float("nan")],
        [float("inf")],
        [float("-inf")],
        ["2026-08-26,10:00:00"],
        ["2026-08-26\n10:00:00"],
        ["2026-08-26\t10:00:00"],
    ],
)
def test_search_after_rejects_nonfinite_or_unsafe_components(token: list[object]) -> None:
    assert _sort_token(token) is None


def test_search_after_accepts_conservative_provider_components() -> None:
    assert _sort_token([1724666400000, "2026-08-26T10:00:00.000Z", 1.25]) == [
        1724666400000,
        "2026-08-26T10:00:00.000Z",
        1.25,
    ]


def _directory_symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")


def _file_symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"file symlinks are unavailable: {error}")


def test_checkpoint_rejects_symlinked_repository_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    _directory_symlink_or_skip(linked_root, real_root)
    monkeypatch.setattr(urlscan_checkpoint.os, "getcwd", lambda: str(linked_root))

    with pytest.raises(ValueError, match="repository root"):
        urlscan_checkpoint._bounded_path("data/urlscan/search-checkpoints.json")


def test_checkpoint_rejects_symlinked_allowed_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    external_directory = tmp_path / "outside-urlscan"
    external_directory.mkdir()
    _directory_symlink_or_skip(tmp_path / "data/urlscan", external_directory)

    with pytest.raises(ValueError, match="symlinked path component"):
        SearchCheckpointStore.load("data/urlscan/search-checkpoints.json", now=datetime.now(UTC))


def test_checkpoint_commit_rejects_target_replaced_with_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    store = SearchCheckpointStore.load("data/urlscan/search-checkpoints.json", now=datetime.now(UTC))
    target = tmp_path / "data/urlscan/search-checkpoints.json"
    target.parent.mkdir(parents=True)
    external_file = tmp_path / "outside-checkpoint.json"
    external_file.write_text("do not touch\n", encoding="utf-8")
    _file_symlink_or_skip(target, external_file)

    with pytest.raises(ValueError, match="symlinked path component"):
        store.commit()
    assert external_file.read_text(encoding="utf-8") == "do not touch\n"
