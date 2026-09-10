from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from hecavex_radar import urlscan
from hecavex_radar.urlscan_checkpoint import SearchCheckpointStore

ROW = {
    "task": {"uuid": "00000000-0000-4000-8000-000000000001", "visibility": "public"},
    "sort": [1, "00000000-0000-4000-8000-000000000001"],
}


def _response(payload: object = None, *, timeout: bool = False) -> MagicMock:
    response = MagicMock()
    response.headers = {}
    if timeout:
        response.read.side_effect = TimeoutError("private transport detail")
    else:
        response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


@pytest.mark.parametrize("search_timeout", [False, True])
def test_real_hunt_read_timeout_preserves_publication_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, search_timeout: bool,
) -> None:
    registry = urlscan.load_brand_registry()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URLSCAN_API_KEY", "synthetic-unused")
    monkeypatch.setenv("URLSCAN_ARCHIVE_ROOT", "data/urlscan")
    monkeypatch.setenv("URLSCAN_TITLE_DETAIL_LIMIT", "0")
    monkeypatch.setattr(urlscan, "load_brand_registry", lambda: registry)
    monkeypatch.setattr(urlscan, "_load_hunt_seeds", lambda *_args: [])
    monkeypatch.setattr(urlscan, "_summary_match", lambda *_args: MagicMock())
    prior_at = datetime(2026, 8, 29, tzinfo=UTC)
    store = SearchCheckpointStore.load("data/urlscan/search-checkpoints.json", now=prior_at)
    query = urlscan.build_domain_query(registry, 7)
    store.search(query, 100, "unused", lambda *_args: {"results": [ROW], "total": 200})
    checkpoint = store.commit()
    original_checkpoint = checkpoint.read_bytes()
    prior = urlscan._state_for_run(
        prior_at, configured=True, outcome="completed", search_requests=1,
        result_requests=0, candidate_cursor=0, candidate_count=0,
        selected_candidates=0, last_search_requests=1, last_result_requests=0,
        checkpoint_coverage=store.summary(),
    )
    urlscan.write_urlscan_hunt_state("data/urlscan", prior)
    opener = MagicMock()
    if search_timeout:
        opener.open.return_value = _response(timeout=True)
    else:
        opener.open.side_effect = [
            _response({"results": [ROW], "total": 1}),
            _response({"results": [], "total": 1}),
            _response(timeout=True),
        ]
    monkeypatch.setattr(urlscan, "build_opener", lambda *_args: opener)

    assert urlscan.main() == int(search_timeout)
    state = urlscan.read_urlscan_hunt_state("data/urlscan")
    assert state is not None
    if search_timeout:
        assert state["lastOutcome"] == "failed"
        assert state["lastSuccessAt"] == prior["lastSuccessAt"]
        assert state["checkpointCoverage"] == prior["checkpointCoverage"]
        assert checkpoint.read_bytes() == original_checkpoint
        assert state["lastRunSearchRequests"] == 1
        assert state["lastRunResultRequests"] == 0
    else:
        assert state["lastOutcome"] == "completed"
        assert state["lastSuccessAt"] == state["lastRunAt"]
        assert state["checkpointCoverage"]["backlog"] == 0
        assert checkpoint.read_bytes() != original_checkpoint
        assert state["lastRunSearchRequests"] == 2
        assert state["lastRunResultRequests"] == 1


@pytest.mark.parametrize("status", [401, 403, 429])
def test_optional_detail_keeps_auth_and_rate_limits_fatal(
    monkeypatch: pytest.MonkeyPatch, status: int,
) -> None:
    opener = MagicMock()
    opener.open.side_effect = HTTPError("https://urlscan.io/", status, "synthetic", {}, None)
    monkeypatch.setattr(urlscan, "build_opener", lambda *_args: opener)
    requester = urlscan._BudgetedRequester(
        urlscan._request_json, search_used=0, result_used=0, daily_search_cap=10,
        daily_result_cap=10, run_search_cap=10, run_result_cap=10,
    )
    expected = urlscan._URLScanRateLimitError if status == 429 else urlscan._URLScanAccessError
    with pytest.raises(expected):
        urlscan._safe_detail(ROW, "unused", requester)
    assert requester.run_result_requests == 1
    assert requester.result_used == 1
    assert requester.provider_exhausted is (status == 429)


def test_optional_detail_continues_after_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = MagicMock()
    opener.open.side_effect = [_response(timeout=True), _response(ROW)]
    monkeypatch.setattr(urlscan, "build_opener", lambda *_args: opener)
    requester = urlscan._BudgetedRequester(
        urlscan._request_json, search_used=0, result_used=0, daily_search_cap=10,
        daily_result_cap=10, run_search_cap=10, run_result_cap=10,
    )
    assert urlscan._safe_detail(ROW, "unused", requester) is None
    assert urlscan._safe_detail(ROW, "unused", requester) == (ROW["task"]["uuid"], ROW)
    assert requester.run_result_requests == 2
    assert requester.result_used == 2
