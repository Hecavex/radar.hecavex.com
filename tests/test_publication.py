from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from hypothesis import given, settings
from hypothesis import strategies as st
from pytest import MonkeyPatch

from hecavex_radar.models import RadarSignal, RadarSource, SignalDetail
from hecavex_radar.publication import (
    MAXIMUM_SHARD_BYTES,
    _budget_candidate,
    _json_bytes,
    _stix_validation_diagnostics,
    build_change_aggregate,
    build_pipeline_health,
    build_related_observations,
    fit_dashboard_signals,
    write_signal_shards,
)

NOW = "2026-08-25T12:13:16.615Z"


def test_stix_validation_diagnostics_flattens_file_and_object_errors() -> None:
    result = SimpleNamespace(
        fatal="invalid input",
        object_results=(
            SimpleNamespace(errors=("missing schema", "invalid identifier")),
            SimpleNamespace(errors=("unexpected property",)),
        ),
    )

    assert _stix_validation_diagnostics(result) == [
        "invalid input",
        "missing schema",
        "invalid identifier",
        "unexpected property",
    ]


def _signal(number: int, *, body_hash: str | None = None) -> RadarSignal:
    domain = f"login-{number:04d}-{'x' * 40}[.]example"
    signal = cast(
        RadarSignal,
        {
            "id": hashlib.sha256(domain.encode()).hexdigest()[:20],
            "url": f"hxxps://{domain}",
            "domain": domain,
            "firstSeen": NOW,
            "lastSeen": NOW,
            "sources": ["URLScan"],
            "status": "suspected",
            "brand": "Example",
            "country": None,
            "host": None,
            "screenshotUrl": None,
            "referenceUrl": None,
            "hashes": [body_hash] if body_hash else [],
            "reasonCodes": ["brand-domain-match"],
            "matchScore": 90,
            "evidenceTier": "corroborated" if body_hash else "name-only",
            "reviewState": "unreviewed",
            "ltRelevance": "lithuanian-brand-relevance",
            "confidence": 90,
        },
    )
    return signal


def _sources() -> list[RadarSource]:
    return [
        {
            "name": name,
            "homepage": f"https://{name.lower()}.example/",
            "fetchedAt": NOW,
            "records": 0,
            "state": "healthy" if name == "URLScan" else "skipped",
            "note": None,
        }
        for name in ("CertStream", "URLScan", "HECAVEX")
    ]


@given(st.integers(min_value=1, max_value=180), st.integers(min_value=4_000, max_value=80_000))
# This is a deterministic byte-bound property, not a microbenchmark. CPU
# contention in parallel build/test jobs must not replace its actual assertions.
@settings(deadline=None)
def test_dashboard_budget_selects_a_deterministic_prefix(count: int, budget: int) -> None:
    signals = [_signal(number) for number in range(count)]
    try:
        selected = fit_dashboard_signals(signals, _sources(), NOW, maximum_bytes=budget)
    except RuntimeError:
        assert len(_json_bytes(_budget_candidate(signals[:1], _sources(), NOW), pretty=True)) > budget
        return
    assert selected == signals[: len(selected)]
    assert len(_json_bytes(_budget_candidate(selected, _sources(), NOW), pretty=True)) <= budget
    if len(selected) < len(signals):
        next_candidate = _budget_candidate(signals[: len(selected) + 1], _sources(), NOW)
        assert len(_json_bytes(next_candidate, pretty=True)) > budget


def test_signal_shards_preserve_order_and_publish_digests(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    signals = [_signal(number) for number in range(900)]
    path, index = write_signal_shards(signals, 500, NOW)
    assert path == (tmp_path / "public/data/radar.index.json").resolve()
    recovered: list[str] = []
    for row in cast(list[dict[str, object]], index["shards"]):
        shard_path = tmp_path / "public" / cast(str, row["path"]).removeprefix("/")
        body = shard_path.read_bytes()
        assert len(body) <= MAXIMUM_SHARD_BYTES
        assert hashlib.sha256(body).hexdigest() == row["sha256"]
        shard = json.loads(body)
        recovered.extend(signal["id"] for signal in shard["signals"])
    assert recovered == [signal["id"] for signal in signals]


def _detail(signal: RadarSignal, ip: str, asn: int, redirect: str | None = None) -> SignalDetail:
    return cast(
        SignalDetail,
        {
            "schemaVersion": 1,
            "dataset": "signal-detail",
            "signalId": signal["id"],
            "domain": signal["domain"],
            "generatedAt": NOW,
            "observations": [
                {
                    "source": "URLScan",
                    "observedAt": NOW,
                    "page": None,
                    "network": {"ipAddress": ip, "asn": asn, "asnDescription": None, "asnRegistry": None},
                    "assessment": (
                        {"urlscanVerdictScore": 0, "urlscanCategories": [], "redirectedToDomain": redirect}
                        if redirect
                        else None
                    ),
                    "certificate": None,
                }
            ],
        },
    )


def test_relationships_require_strong_or_two_supporting_evidence_types() -> None:
    shared_hash = "a" * 64
    first = _signal(1, body_hash=shared_hash)
    second = _signal(2, body_hash=shared_hash)
    third = _signal(3)
    fourth = _signal(4)
    details = {
        first["id"]: _detail(first, "192[.]0[.]2[.]1", 64500),
        second["id"]: _detail(second, "198[.]51[.]100[.]1", 64501),
        third["id"]: _detail(third, "203[.]0[.]113[.]8", 64510, "redirect[.]example"),
        fourth["id"]: _detail(fourth, "203[.]0[.]113[.]8", 64510, "redirect[.]example"),
    }
    artifact = build_related_observations([first, second, third, fourth], details, NOW)
    edges = cast(list[dict[str, object]], artifact["edges"])
    by_pair = {(edge["source"], edge["target"]): edge for edge in edges}
    strong_ids = sorted((first["id"], second["id"]))
    supporting_ids = sorted((third["id"], fourth["id"]))
    strong_pair = (strong_ids[0], strong_ids[1])
    supporting_pair = (supporting_ids[0], supporting_ids[1])
    assert by_pair[strong_pair]["strength"] == "strong"
    assert by_pair[supporting_pair]["strength"] == "corroborated-supporting"
    assert "not campaign" in cast(str, artifact["semantics"]).lower()


def test_dns_context_can_form_a_two_family_infrastructure_association() -> None:
    first = _signal(5)
    second = _signal(6)

    def context_detail(signal: RadarSignal) -> SignalDetail:
        return cast(
            SignalDetail,
            {
                "schemaVersion": 1,
                "dataset": "signal-detail",
                "signalId": signal["id"],
                "domain": signal["domain"],
                "generatedAt": NOW,
                "observations": [],
                "domainContext": {
                    "observedAt": NOW,
                    "dns": {
                        "a": ["192[.]0[.]2[.]50"],
                        "aaaa": [],
                        "cname": [],
                        "ns": ["ns1[.]example[.]net"],
                        "mx": [],
                        "minimumTtl": 300,
                        "queriesCompleted": 5,
                    },
                    "registration": None,
                },
            },
        )

    artifact = build_related_observations(
        [first, second],
        {first["id"]: context_detail(first), second["id"]: context_detail(second)},
        NOW,
    )
    edges = cast(list[dict[str, object]], artifact["edges"])
    assert len(edges) == 1
    evidence = cast(list[dict[str, str]], edges[0]["evidence"])
    assert {item["type"] for item in evidence} == {"dns-a", "dns-ns"}


def test_relationships_do_not_treat_same_registrable_domain_as_independent_infrastructure() -> None:
    shared_hash = "c" * 64
    first = _signal(10, body_hash=shared_hash)
    second = _signal(11, body_hash=shared_hash)
    first["domain"] = "login[.]candidate[.]pages[.]dev"
    first["url"] = "hxxps://login[.]candidate[.]pages[.]dev"
    second["domain"] = "www[.]login[.]candidate[.]pages[.]dev"
    second["url"] = "hxxps://www[.]login[.]candidate[.]pages[.]dev"

    artifact = build_related_observations([first, second], {}, NOW)

    assert artifact["edges"] == []
    assert artifact["nodes"] == []


def test_relation_byte_trimming_recomputes_connected_components(monkeypatch: MonkeyPatch) -> None:
    first = _signal(7, body_hash="a" * 64)
    second = _signal(8, body_hash="a" * 64)
    second["hashes"] = ["a" * 64, "b" * 64]
    third = _signal(9, body_hash="b" * 64)
    signals = [first, second, third]

    complete = build_related_observations(signals, {}, NOW)
    assert len(cast(list[object], complete["edges"])) == 2
    monkeypatch.setattr(
        "hecavex_radar.publication.MAXIMUM_RELATION_BYTES",
        len(_json_bytes(complete, pretty=True)) - 1,
    )
    trimmed = build_related_observations(signals, {}, NOW)
    edges = cast(list[dict[str, object]], trimmed["edges"])
    nodes = cast(list[dict[str, str]], trimmed["nodes"])
    assert len(edges) == 1
    endpoints = {cast(str, edges[0]["source"]), cast(str, edges[0]["target"])}
    assert {node["signalId"] for node in nodes} == endpoints
    expected_cluster = hashlib.sha256("\n".join(sorted(endpoints)).encode()).hexdigest()[:16]
    assert {node["clusterId"] for node in nodes} == {expected_cluster}


def _write_ndjson(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_health_and_changes_publish_only_aggregate_rows(tmp_path: Path) -> None:
    signal = _signal(1)
    event = {
        "schemaVersion": 1,
        "signalId": signal["id"],
        "eventType": "status-transition",
        "observedAt": NOW,
        "domain": signal["domain"],
        "brand": "Example",
        "sources": ["URLScan"],
        "status": "suspected",
        "previousStatus": None,
        "confidence": 90,
        "reasonCodes": ["first-publication"],
        "eventId": "f" * 32,
    }
    _write_ndjson(tmp_path / "data/history/daily/2026-08-25/events.ndjson", [event])
    attempt = {
        "schemaVersion": 1,
        "collectorStartedAt": "2026-08-25T12:00:00.000Z",
        "endedAt": "2026-08-25T12:04:00.000Z",
        "expectedListeningSeconds": 240,
        "listeningSeconds": 240.0,
        "messages": 10,
        "dnsNames": 20,
        "matches": 1,
        "newRecords": 1,
        "outcome": "healthy-matches",
    }
    _write_ndjson(tmp_path / "data/certstream/2026-08-25/attempts.ndjson", [attempt])
    ct_state = {
        "provider": "crt.sh",
        "generatedAt": NOW,
        "latestRun": {
            "startedAt": NOW,
            "endedAt": NOW,
            "outcome": "completed",
            "queriesAttempted": 6,
            "queriesCompleted": 6,
            "rowsProcessed": 20,
            "dnsNames": 30,
            "matches": 2,
            "newRecords": 1,
            "queriesBacklogged": 0,
        },
        "queries": {"must-not-be-public": {"term": "private-candidate"}},
    }
    ct_path = tmp_path / "data/ct-search/state.json"
    ct_path.parent.mkdir(parents=True)
    ct_path.write_text(json.dumps(ct_state), encoding="utf-8")
    context_state = {
        "generatedAt": NOW,
        "latestRun": {
            "startedAt": NOW,
            "endedAt": NOW,
            "outcome": "partial",
            "attempted": 1,
            "completed": 1,
        },
        "records": [{"domain": "must-not-be-public[.]example"}],
    }
    context_path = tmp_path / "data/enrichment/domain-context.json"
    context_path.parent.mkdir(parents=True)
    context_path.write_text(json.dumps(context_state), encoding="utf-8")
    urlscan_state = {
        "generatedAt": NOW,
        "configured": True,
        "lastRunAt": NOW,
        "lastOutcome": "completed",
        "privateQuery": "must-not-be-public.example",
    }
    urlscan_state_path = tmp_path / "data/urlscan/hunt-state.json"
    urlscan_state_path.parent.mkdir(parents=True, exist_ok=True)
    urlscan_state_path.write_text(json.dumps(urlscan_state), encoding="utf-8")
    snapshot = {
        "schemaVersion": 2,
        "dataset": "live",
        "generatedAt": NOW,
        "lastSuccessfulSyncAt": NOW,
        "signals": [signal],
        "sources": _sources(),
    }
    changes = build_change_aggregate(tmp_path, NOW)
    health = build_pipeline_health(tmp_path, snapshot, NOW)
    encoded = json.dumps([changes, health])
    assert signal["domain"] not in encoded
    assert "must-not-be-public" not in encoded
    change_windows = cast(list[dict[str, object]], changes["windows"])
    health_windows = cast(list[dict[str, object]], health["windows"])
    assert change_windows[0]["firstPublications"] == 1
    screening = cast(dict[str, object], health_windows[0]["screening"])
    assert screening["matches"] == 1
    current = cast(dict[str, object], health["current"])
    assert cast(dict[str, object], current["ctSearch"])["provider"] == "crt.sh"
    assert cast(dict[str, object], current["domainContext"])["recordCount"] == 1
    assert current["urlscan"] == {
        "generatedAt": NOW,
        "configured": True,
        "lastOutcome": "completed",
        "lastAttemptAt": NOW,
        "checkpointCoverage": {
            "queries": 0,
            "complete": 0,
            "partial": 0,
            "backlog": 0,
            "oldestBacklogProgressAt": None,
        },
    }
