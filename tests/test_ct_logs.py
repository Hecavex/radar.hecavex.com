"""Direct CT log polling: tile parsing, shard selection, checkpoints and the shared archive path.

Synthetic certificates and an in-memory fetcher only; nothing touches the network.
"""
from __future__ import annotations

import datetime as dt
import json
import struct
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

from hecavex_radar import ct_logs
from hecavex_radar.brands import load_brand_registry
from hecavex_radar.certstream_archive import read_candidate_file

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = load_brand_registry(ROOT / "data" / "brands-lt.json")
POISON = ObjectIdentifier("1.3.6.1.4.1.11129.2.4.3")
LOGGED_MS = 1_792_000_000_000  # 2026-10-14T17:46:40Z
KEY = ec.generate_private_key(ec.SECP256R1())


def make_cert(names: list[str], *, precert: bool = False) -> bytes:
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
        .issuer_name(x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Test R1"),
        ]))
        .public_key(KEY.public_key())
        .serial_number(0xABC123)
        .not_valid_before(dt.datetime(2026, 10, 1))
        .not_valid_after(dt.datetime(2027, 1, 1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name) for name in names]), False)
    )
    if precert:
        builder = builder.add_extension(x509.UnrecognizedExtension(POISON, b"\x05\x00"), True)
    return builder.sign(KEY, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def tile_entry(der: bytes, *, precert: bool = False) -> bytes:
    head = struct.pack(">QH", LOGGED_MS, 1 if precert else 0)
    if precert:
        tbs = b"\x00" * 32 + (5).to_bytes(3, "big") + b"tbs!!" + struct.pack(">H", 0)
        body = tbs + len(der).to_bytes(3, "big") + der
    else:
        body = len(der).to_bytes(3, "big") + der + struct.pack(">H", 0)
    return head + body + struct.pack(">H", 32) + b"\x11" * 32


FILLER = tile_entry(make_cert(["ordinary-shop.example"]))
LURE = tile_entry(make_cert(["swedbank-lt-login.example", "cdn.swedbank-lt-login.example"]), precert=True)


def test_tile_path_and_checkpoint() -> None:
    assert ct_logs.tile_path(5) == "tile/data/005"
    assert ct_logs.tile_path(1234) == "tile/data/x001/234"
    assert ct_logs.tile_path(3830461) == "tile/data/x003/x830/461"
    assert ct_logs.parse_checkpoint("log.example/2027h1\n980599223\nabc=\n\n- sig") == 980599223
    with pytest.raises(ValueError):
        ct_logs.parse_checkpoint("not a checkpoint")


def test_tile_decodes_certificates_precertificates_and_keeps_a_truncated_prefix() -> None:
    entries = ct_logs.parse_tile(FILLER + LURE + LURE[:40])
    assert [entry.names for entry in entries] == [
        ("ordinary-shop.example",),
        ("swedbank-lt-login.example", "cdn.swedbank-lt-login.example"),
    ]
    assert entries[1].timestamp_ms == LOGGED_MS
    assert ct_logs.parse_tile(struct.pack(">QH", 1, 0) + b"\x00\x00\x05bad!!\x00\x00\x00\x00")[0].names == ()


def test_shards_follow_the_log_list_interval_and_state() -> None:
    def log(name: str, start: str, end: str, state: str = "usable") -> dict[str, object]:
        return {"description": name, "monitoring_url": f"https://{name.split()[-1].lower()}.example/",
                "state": {state: {}}, "temporal_interval": {"start_inclusive": start, "end_exclusive": end}}

    log_list = {"operators": [{"tiled_logs": [
        log("Test Willow2026h2", "2026-06-17T00:00:00Z", "2026-12-16T00:00:00Z"),
        log("Test Willow2027h1", "2026-12-16T00:00:00Z", "2027-06-17T00:00:00Z"),
        log("Test Willow2027h2", "2027-06-17T00:00:00Z", "2027-12-15T00:00:00Z"),
        log("Test Willow2026h1", "2026-01-01T00:00:00Z", "2026-06-17T00:00:00Z"),
        log("Test Oak2027h1", "2026-12-16T00:00:00Z", "2027-06-17T00:00:00Z", state="retired"),
        log("Other Log2027h1", "2026-12-16T00:00:00Z", "2027-06-17T00:00:00Z"),
    ]}]}
    shards = ct_logs.select_shards(log_list, ["Test Willow", "Test Oak"], dt.datetime(2026, 10, 19, tzinfo=dt.UTC))
    assert [shard.name for shard in shards] == ["Test Willow2026h2", "Test Willow2027h1"]


def test_plan_starts_new_logs_at_the_head_and_caps_backlog_to_the_newest_entries() -> None:
    assert ct_logs.plan_range(None, 1000, 500) == (1000, 1000, 0)
    assert ct_logs.plan_range(900, 1000, 500) == (900, 1000, 0)
    assert ct_logs.plan_range(100, 1000, 500) == (500, 1000, 400)
    assert ct_logs.plan_range(2000, 1000, 500) == (1000, 1000, 0)  # a reset log restarts at its head


def fake_log(tiles: dict[int, bytes], size: int) -> ct_logs.Fetcher:
    def fetcher(url: str) -> bytes:
        if url.endswith("/checkpoint"):
            return f"log.example\n{size}\nroot=\n".encode()
        index = int("".join(part.lstrip("x") for part in url.split("/tile/data/")[1].split("/")))
        return tiles[index]
    return fetcher


def run_poll(fetcher: ct_logs.Fetcher, checkpoints: dict[str, int]) -> dict[str, object]:
    ticks = iter(range(100))
    return ct_logs.poll(
        [ct_logs.Shard("Test Willow2027h1", "https://willow.example/")], checkpoints,
        deadline=6, cap=10_000, registry=REGISTRY, fetcher=fetcher,
        clock=lambda: next(ticks), sleep=lambda _seconds: None,
    )


def test_poll_archives_lures_through_the_certstream_candidate_path(tmp_path: Path, monkeypatch) -> None:
    tiles = {0: FILLER * 256, 1: FILLER * 200 + LURE + FILLER * 55}
    result = run_poll(fake_log(tiles, 600), {"https://willow.example/": 0})  # tile 2 is partial and waits
    record = result["logs"]["https://willow.example/"]
    assert (record["next"], record["treeSize"], record["lag"], record["error"]) == (512, 600, 88, None)
    assert record["entries"] == 512
    candidates = result["candidates"]
    assert {candidate["domain"] for candidate in candidates} == {
        "swedbank-lt-login[.]example", "cdn[.]swedbank-lt-login[.]example",
    }
    candidate = candidates[0]
    assert candidate["source"] == "CertStream"
    assert candidate["collectionMethod"] == "ct-log-poll"
    assert candidate["brand"] == "Swedbank"
    assert candidate["sourceTimeEvidence"][-1]["providerObservedAt"] == "2026-10-14T17:46:40.000Z"
    assert candidate["certificate"]["issuer"] == "O=Test CA, CN=Test R1"

    monkeypatch.chdir(tmp_path)
    state = Path("data/ct-logs/state.json")
    assert ct_logs.ingest([json.loads(json.dumps(result))], state, "data/certstream") == 2
    assert ct_logs.ingest([json.loads(json.dumps(result))], state, "data/certstream") == 0  # replay is idempotent
    stale = json.loads(json.dumps(result))
    stale["logs"]["https://willow.example/"]["next"] = 256
    ct_logs.ingest([stale], state, "data/certstream")
    assert ct_logs.read_state(state)["logs"]["https://willow.example/"]["next"] == 512  # never regresses
    archived = [read_candidate_file(path) for path in Path("data/certstream").rglob("domains.ndjson")]
    assert sum(map(len, archived)) == 2


def test_poll_resumes_mid_tile_and_survives_a_failing_log() -> None:
    tiles = {1: FILLER * 200 + LURE + FILLER * 55}
    result = run_poll(fake_log(tiles, 512), {"https://willow.example/": 300})
    record = result["logs"]["https://willow.example/"]
    assert (record["next"], record["entries"]) == (512, 212)
    assert len(result["candidates"]) == 2

    def broken(url: str) -> bytes:
        raise TimeoutError("unreachable log")

    failed = run_poll(broken, {"https://willow.example/": 300})["logs"]["https://willow.example/"]
    assert failed["next"] == 300 and failed["error"].startswith("TimeoutError")


def test_ingest_keeps_checkpoints_of_logs_never_reached(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    state = Path("data/ct-logs/state.json")
    ct_logs.write_state({"schemaVersion": 1, "generatedAt": None, "logs": {"https://a.example/": {"next": 7}}}, state)
    unreached = {"logs": {"https://a.example/": {"name": "A", "next": None, "error": "TimeoutError: x"},
                          "https://b.example/": {"name": "B", "next": 512}}, "candidates": []}
    ct_logs.ingest([unreached], state, "data/certstream")
    logs = ct_logs.read_state(state)["logs"]
    assert (logs["https://a.example/"]["next"], logs["https://b.example/"]["next"]) == (7, 512)


def test_a_tile_that_does_not_decode_fully_is_counted_and_passed() -> None:
    tiles = {0: FILLER * 255 + bytes(10), 1: FILLER * 256}
    record = run_poll(fake_log(tiles, 512), {"https://willow.example/": 0})["logs"]["https://willow.example/"]
    assert (record["next"], record["badTiles"], record["error"]) == (512, 1, None)


@pytest.mark.parametrize("domain", [
    "swedbank-grazinimas.example", "login.revolut.click", "lumnor-login.example",
    "secureloginrevolut.example", "dpd-trackparcel.example", "revolutt-login.example",
])
def test_prefilter_never_drops_a_name_the_matcher_accepts(domain: str) -> None:
    prefilter = ct_logs._compile_brand_prefilter(REGISTRY)
    assert ct_logs.score_domain(domain, REGISTRY) is not None
    assert ct_logs._may_match_reviewed_brand(domain, prefilter)
