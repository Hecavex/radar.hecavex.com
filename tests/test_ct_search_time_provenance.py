"""CT row identity pins fallback receipt time across bounded overlap replay."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hecavex_radar import ct_search
from hecavex_radar.certstream_archive import read_recent_candidates
from tests.test_ct_search import _registry

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
NOW_TEXT = "2026-10-15T12:00:00.000Z"
DOMAIN = "swedbank-login.example"


def poll(payload, now=NOW, **kwargs):
    return ct_search.poll(lambda _url: payload, now=now, registry=_registry(), queries_per_run=1, **kwargs)


@pytest.mark.parametrize(("provider", "reason"), [
    (None, "missing"), ("invalid-clock", "invalid"), ("2026-10-16T11:00:00.000Z", "future"),
])
def test_unchanged_invalid_provider_row_keeps_first_collector_day_on_later_replay(
    tmp_path, monkeypatch, provider, reason,
):
    monkeypatch.chdir(tmp_path)
    payload = [{"id": 42, "entry_timestamp": provider, "name_value": DOMAIN}]
    assert poll(payload)["newRecords"] == 1
    first = read_recent_candidates("data/certstream", 2, NOW)[0]
    assert {item["reason"] for item in first["sourceTimeEvidence"]} == {reason}
    # The future value becomes plausible on day two. Same provider row still
    # denotes the original accepted fallback receipt, not another observation.
    assert poll(payload, NOW + timedelta(days=1))["newRecords"] == 0
    archived = read_recent_candidates("data/certstream", 2, NOW + timedelta(days=1))
    assert archived == [first]
    assert first["observedAt"] == NOW_TEXT
    assert {item["providerObservedAt"] for item in first["sourceTimeEvidence"]} == {None}
    assert ct_search.read_state()["fallbackClocks"] == {"42": NOW_TEXT}
    assert next(iter(ct_search.read_state()["queries"].values()))["lastEntryAt"] is None


def test_valid_provider_boundary_retains_raw_clock_and_separate_receipt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = "2026-10-15T13:00:00+03:00"
    assert poll([{"id": 43, "entry_timestamp": original, "name_value": DOMAIN}])["newRecords"] == 1
    candidate = read_recent_candidates("data/certstream", 1, NOW)[0]
    assert candidate["observedAt"] == "2026-10-15T10:00:00.000Z"
    assert {item["origin"] for item in candidate["sourceTimeEvidence"]} == {"provider-observation-time"}
    assert {item["originalProviderTime"] for item in candidate["sourceTimeEvidence"]} == {original}
    assert {item["collectorTime"] for item in candidate["sourceTimeEvidence"]} == {NOW_TEXT}
    assert ct_search.read_state()["fallbackClocks"] == {}
    assert next(iter(ct_search.read_state()["queries"].values()))["lastEntryAt"] == candidate["observedAt"]


def test_valid_provider_checkpoint_advances_when_no_hostname_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = poll([{"id": 43, "entry_timestamp": "2026-10-15T10:00:00.000Z",
                    "name_value": "unrelated-reserved.example"}])
    assert result["newRecords"] == 0
    assert next(iter(ct_search.read_state()["queries"].values()))["lastEntryAt"] == "2026-10-15T10:00:00.000Z"
    assert ct_search.read_state()["fallbackClocks"] == {}


def test_bootstrap_does_not_skip_undated_rows_behind_known_old_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = [{"id": 100, "entry_timestamp": "2026-01-01T00:00:00Z", "name_value": DOMAIN},
               {"id": 1, "entry_timestamp": None, "name_value": DOMAIN}]
    assert poll(payload, replay_ids=0, replay_rows=0)["newRecords"] == 1
    assert read_recent_candidates("data/certstream", 1, NOW)[0]["observedAt"] == NOW_TEXT


def test_fallback_capacity_failure_precedes_every_archive_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    poll([])
    state_path = tmp_path / "data/ct-search/state.json"
    before = state_path.read_bytes()
    monkeypatch.setattr(ct_search, "MAXIMUM_STATE_BYTES", len(before) + 10)
    payload = [{"id": number, "entry_timestamp": None, "name_value": DOMAIN} for number in (42, 43)]
    with pytest.raises(ValueError, match="state|capacity"):
        poll(payload, NOW + timedelta(days=1))
    assert state_path.read_bytes() == before
    assert list((tmp_path / "data/certstream").rglob("domains.ndjson")) == []


def test_old_state_without_fallback_cache_is_compatible_and_future_cache_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    poll([])
    state_path = Path("data/ct-search/state.json")
    old = json.loads(state_path.read_bytes())
    old.pop("fallbackClocks", None)
    state_path.write_text(json.dumps(old), encoding="utf-8")
    assert poll([{"id": 42, "entry_timestamp": None, "name_value": DOMAIN}])["newRecords"] == 1
    state = ct_search.read_state()
    state["fallbackClocks"]["42"] = "2027-01-01T00:00:00.000Z"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="contract"):
        ct_search.read_state()


def test_untrusted_missing_provider_identity_cannot_create_a_fallback_cache_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = [{"id": value, "entry_timestamp": None, "name_value": DOMAIN} for value in (None, True, -1, "x")]
    assert poll(payload)["rowsProcessed"] == 0
    assert ct_search.read_state()["fallbackClocks"] == {}
