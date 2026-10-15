from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from hecavex_radar import certstream_archive, sources, urlscan
from hecavex_radar.brands import load_brand_registry, score_domain
from hecavex_radar.certstream_archive import CandidateArchiveWriter, candidate_from_match, read_recent_candidates
from hecavex_radar.ct_search import poll, read_state
from hecavex_radar.models import RawSignal
from hecavex_radar.normalize import prepare_signal, resolve_signal_times

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
NOW_TEXT = "2026-10-15T12:00:00.000Z"
DOMAIN = "revolut-login.example"
UUID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def registry_fixture(tmp_path: Path) -> None:
    destination = tmp_path / "data/brands-lt.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes((Path(__file__).resolve().parents[1] / "data/brands-lt.json").read_bytes())


def scan(provider_time: str | None, *, now: datetime = NOW) -> dict[str, Any]:
    summary = {"_id": UUID, "task": {"uuid": UUID, "time": provider_time}, "page": {"url": "https://" + DOMAIN}}
    result = urlscan._signal_from_scan(summary, {}, "https://" + DOMAIN, "Revolut", 80, now,
                                       load_brand_registry(), urlscan._BrandEvidence(True, False, False, False))
    assert result is not None
    return dict(result)


@pytest.mark.parametrize("provider_time,reason", [(None, "missing"), ("invalid-clock", "invalid"),
                                                   ("2027-01-01T00:00:00.000Z", "future")])
def test_urlscan_preserves_explicit_collector_fallback(provider_time: str | None, reason: str) -> None:
    signal = scan(provider_time)
    assert signal["firstSeen"] == signal["lastSeen"] == NOW_TEXT
    evidence = signal.get("sourceTimeEvidence")
    assert evidence is not None, "URLScan must retain explicit provider-time fallback evidence."
    assert [row["boundary"] for row in evidence] == ["firstSeen", "lastSeen"]
    assert all(row["origin"] == "collector-time-fallback" and row["reason"] == reason for row in evidence)
    assert all(row["providerObservedAt"] is None and row["originalProviderTime"] == provider_time for row in evidence)
    assert all(row["collectorTime"] == row["timestamp"] == NOW_TEXT for row in evidence)


def test_urlscan_valid_provider_time_remains_distinct_from_collector() -> None:
    original = "2026-10-15T13:00:00+03:00"
    evidence = scan(original).get("sourceTimeEvidence")
    assert evidence is not None
    assert all(row["providerObservedAt"] == row["timestamp"] == "2026-10-15T10:00:00.000Z" for row in evidence)
    assert all(row["originalProviderTime"] == original and row["collectorTime"] == NOW_TEXT for row in evidence)


def test_urlscan_archive_replay_retains_original_fallback_clock_and_strict_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    signal = scan(None)
    assert urlscan.write_urlscan_archive("data/urlscan", [signal], NOW) == 1
    path = tmp_path / "data/urlscan/2026-10-15/signals.ndjson"
    before = path.read_bytes()
    later = NOW + timedelta(hours=2)
    raw = sources.load_urlscan("2026-10-15T14:00:00.000Z", "data/urlscan", 1).signals[0]
    assert raw.source_time_evidence is not None
    assert all(row["collectorTime"] == NOW_TEXT and row["providerObservedAt"] is None
               for row in resolve_signal_times(raw, "2026-10-15T14:00:00.000Z"))
    prepared = prepare_signal(raw, "2026-10-15T14:00:00.000Z")
    assert prepared is not None and "sourceTimeEvidence" not in prepared
    archived = urlscan.read_recent_urlscan("data/urlscan", 1, later)
    assert urlscan.write_urlscan_archive("data/urlscan", archived, later) == 0
    assert path.read_bytes() == before


def test_urlscan_archive_merge_keeps_provenance_for_both_extreme_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    old = scan("2026-10-15T10:00:00.000Z")
    new = scan(None)
    assert urlscan.write_urlscan_archive("data/urlscan", [old, new], NOW) == 1
    raw = sources.load_urlscan(NOW_TEXT, "data/urlscan", 1).signals[0]
    evidence = resolve_signal_times(raw, NOW_TEXT)
    assert evidence[0]["timestamp"] == "2026-10-15T10:00:00.000Z"
    assert evidence[0]["origin"] == "provider-observation-time"
    assert evidence[1]["timestamp"] == NOW_TEXT and evidence[1]["origin"] == "collector-time-fallback"


def test_urlscan_fresh_same_scan_replay_uses_retained_original_collector_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert urlscan.write_urlscan_archive("data/urlscan", [scan(None)], NOW) == 1
    later = NOW + timedelta(days=1)
    assert urlscan.write_urlscan_archive("data/urlscan", [scan(None, now=later)], later) == 1
    raw = sources.load_urlscan("2026-10-16T12:00:00.000Z", "data/urlscan", 1).signals[0]
    evidence = resolve_signal_times(raw, "2026-10-16T12:00:00.000Z")
    assert raw.first_seen == raw.last_seen == NOW_TEXT
    assert all(row["origin"] == "collector-time-fallback" and row["collectorTime"] == NOW_TEXT
               and row["providerObservedAt"] is None for row in evidence)


def test_urlscan_distinct_scan_keeps_new_explicit_collector_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert urlscan.write_urlscan_archive("data/urlscan", [scan(None)], NOW) == 1
    later = NOW + timedelta(days=1)
    fresh = scan(None, now=later)
    fresh["referenceUrl"] = "https://urlscan.io/result/00000000-0000-0000-0000-000000000002/"
    assert urlscan.write_urlscan_archive("data/urlscan", [fresh], later) == 1
    raw = sources.load_urlscan("2026-10-16T12:00:00.000Z", "data/urlscan", 1).signals[0]
    assert raw.last_seen == "2026-10-16T12:00:00.000Z"
    assert resolve_signal_times(raw, "2026-10-16T12:00:00.000Z")[1]["providerObservedAt"] is None


def test_legacy_urlscan_archive_keeps_normalized_origin_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    signal = scan("2026-10-15T10:00:00.000Z")
    legacy = {key: value for key, value in signal.items() if key in urlscan.URLSCAN_ARCHIVE_FIELDS}
    legacy.pop("sourceTimeEvidence", None)
    path = tmp_path / "data/urlscan/2026-10-15/signals.ndjson"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schemaVersion": 2, "hashType": "primary-html-sha256", **legacy}) + "\n",
                    encoding="utf-8")
    raw = sources.load_urlscan(NOW_TEXT, "data/urlscan", 1).signals[0]
    assert raw.source_time_evidence is not None
    assert all(row["origin"] == "legacy-normalized-unknown" and row["collectorTime"] is None
               for row in resolve_signal_times(raw, NOW_TEXT))


def test_hecavex_adapter_does_not_turn_missing_provider_time_into_a_valid_provider_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources, "fetch_json", lambda *_args: [{"domain": DOMAIN, "firstSeen": "invalid-clock"}])
    raw = sources.fetch_hecavex(NOW_TEXT, "https://hecavex.example/feed").signals[0]
    assert raw.last_seen is None
    evidence = resolve_signal_times(raw, NOW_TEXT)
    assert evidence[0]["reason"] == "invalid" and evidence[0]["originalProviderTime"] == "invalid-clock"
    assert evidence[1]["reason"] == "missing"
    assert all(row["origin"] == "collector-time-fallback" for row in evidence)


def test_new_live_ct_archive_proves_actual_collector_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    match = score_domain(DOMAIN, load_brand_registry())
    assert match is not None
    candidate = candidate_from_match(match, NOW)
    assert candidate.get("sourceTimeEvidence") is not None
    CandidateArchiveWriter("data/certstream").append([candidate])
    raw = sources.load_certstream("2026-10-15T14:00:00.000Z", "data/certstream", 1).signals[0]
    evidence = resolve_signal_times(raw, "2026-10-15T14:00:00.000Z")
    assert all(row["origin"] == "collector-time-fallback" and row["collectorTime"] == NOW_TEXT
               and row["providerObservedAt"] is None for row in evidence)


def test_old_ct_archive_does_not_claim_a_verified_provider_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    match = score_domain(DOMAIN, load_brand_registry())
    assert match is not None
    candidate = candidate_from_match(match, NOW, collection_method="ct-search-api")
    candidate.pop("sourceTimeEvidence", None)
    CandidateArchiveWriter("data/certstream").append([candidate])
    raw = sources.load_certstream("2026-10-15T14:00:00.000Z", "data/certstream", 1).signals[0]
    evidence = resolve_signal_times(raw, "2026-10-15T14:00:00.000Z")
    assert all(row["origin"] == "legacy-normalized-unknown" and row["providerObservedAt"] is None
               and row["collectorTime"] is None for row in evidence)


@pytest.mark.parametrize("provider_time,reason", [(None, "missing"), ("invalid-clock", "invalid"),
                                                   ("2027-01-01T00:00:00.000Z", "future")])
def test_ct_search_falls_back_explicitly_without_dropping_valid_hostname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_time: str | None, reason: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = [{"id": 42, "entry_timestamp": provider_time, "name_value": DOMAIN}]
    result = poll(lambda _url: payload, now=NOW, registry=load_brand_registry(), queries_per_run=1)
    assert result["newRecords"] == 1, "An unusable provider clock must not silently discard an otherwise valid CT row."
    candidates = read_recent_candidates("data/certstream", 1, NOW)
    evidence = candidates[0].get("sourceTimeEvidence")
    assert evidence is not None
    assert all(row["origin"] == "collector-time-fallback" and row["reason"] == reason
               and row["originalProviderTime"] == provider_time and row["collectorTime"] == NOW_TEXT
               for row in evidence)
    assert next(iter(read_state()["queries"].values()))["lastEntryAt"] is None


@pytest.mark.parametrize("field,value", [
    ("source", "HECAVEX"), ("timestamp", "2026-10-15T11:00:00.000Z"),
    ("providerObservedAt", NOW_TEXT), ("boundary", "lastSeen"), ("reason", None),
])
def test_archive_rejects_contradictory_time_metadata(field: str, value: object) -> None:
    payload = urlscan._archive_payload(scan(None))
    payload["sourceTimeEvidence"][0][field] = value
    assert urlscan._archive_signal(payload) is None
    match = score_domain(DOMAIN, load_brand_registry())
    assert match is not None
    candidate = candidate_from_match(match, NOW)
    candidate["sourceTimeEvidence"][0][field] = value  # type: ignore[literal-required]
    assert not certstream_archive._is_candidate(candidate)


def test_urlscan_aggregate_cap_fails_before_replacing_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    signal = scan(None)
    assert urlscan.write_urlscan_archive("data/urlscan", [signal], NOW) == 1
    path = tmp_path / "data/urlscan/2026-10-15/signals.ndjson"
    before = path.read_bytes()
    monkeypatch.setattr(urlscan, "MAXIMUM_ARCHIVE_BYTES", len(before) - 1)
    with pytest.raises(ValueError, match="exceeds 20 MiB"):
        urlscan.write_urlscan_archive("data/urlscan", [signal], NOW)
    assert path.read_bytes() == before


def test_ct_time_evidence_retains_original_line_limit_and_fails_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    match = score_domain(DOMAIN, load_brand_registry())
    assert match is not None
    candidate = candidate_from_match(match, NOW)
    line_bytes = len((json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    assert line_bytes < certstream_archive.MAXIMUM_CANDIDATE_LINE_BYTES == 16 * 1024
    monkeypatch.setattr(certstream_archive, "MAXIMUM_CANDIDATE_LINE_BYTES", line_bytes - 1)
    with pytest.raises(ValueError, match="maximum NDJSON line size"):
        CandidateArchiveWriter("data/certstream").append([candidate])
    assert not (tmp_path / "data/certstream/2026-10-15/domains.ndjson").exists()
    monkeypatch.setattr(certstream_archive, "MAXIMUM_CANDIDATE_LINE_BYTES", line_bytes)
    assert CandidateArchiveWriter("data/certstream").append([candidate]) == 1
    path = tmp_path / "data/certstream/2026-10-15/domains.ndjson"
    before = path.read_bytes()
    later = copy.deepcopy(candidate)
    later["sourceTimeEvidence"] = resolve_signal_times(
        RawSignal(url=DOMAIN, source="CertStream", first_seen="x" * 256, last_seen="x" * 256), NOW_TEXT,
    )
    later["collectionMethod"] = "ct-search-api"
    with pytest.raises(ValueError, match="maximum NDJSON line size"):
        CandidateArchiveWriter("data/certstream").append([later])
    assert path.read_bytes() == before


def test_ct_existing_maximum_field_payload_is_not_silently_dropped_when_evidence_exceeds_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    match = score_domain(DOMAIN, load_brand_registry())
    assert match is not None
    candidate: dict[str, Any] = dict(candidate_from_match(match, NOW))
    original = "\U0001f600" * 256
    candidate["sourceTimeEvidence"] = resolve_signal_times(
        RawSignal(url=DOMAIN, source="CertStream", first_seen=original, last_seen=original), NOW_TEXT,
    )
    candidate["brand"] = "\U0001f600" * certstream_archive.MAXIMUM_BRAND_CHARACTERS
    candidate["reasons"] = [str(index) + "\U0001f600" * 238 for index in range(12)]
    names = [f"{index}.{'a' * 63}.{'b' * 63}.{'c' * 63}.{DOMAIN}".replace(".", "[.]")
             for index in range(12)]
    candidate["certificate"] = {
        "countryName": "LT", "issuer": "I" * 200, "commonName": None,
        "notBefore": None, "notAfter": None, "subjectAltNames": names, "subjectAltNameCount": 500,
        "serialNumberHex": "a" * 80, "fingerprints": {"md5": "a" * 32, "sha1": "b" * 40, "sha256": "c" * 64},
    }

    def encoded_size(value: dict[str, Any]) -> int:
        return len((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())

    legacy = {key: value for key, value in candidate.items() if key != "sourceTimeEvidence"}
    assert certstream_archive._is_candidate(candidate)
    assert encoded_size(legacy) <= 16 * 1024 < encoded_size(candidate)
    with pytest.raises(ValueError, match="maximum NDJSON line size"):
        CandidateArchiveWriter("data/certstream").append([candidate])  # type: ignore[list-item]
    assert not (tmp_path / "data/certstream/2026-10-15/domains.ndjson").exists()
    assert candidate["sourceTimeEvidence"][0]["originalProviderTime"] == original
