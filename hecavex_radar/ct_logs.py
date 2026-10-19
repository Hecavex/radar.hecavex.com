"""Checkpointed tail polling of public static-ct (tiled) Certificate Transparency logs.

CertStream is a sampled live stream and crt.sh lags by weeks. This collector reads the
logs themselves: it follows the current shards named in Google's CT log list, keeps one
entry-index checkpoint per log and feeds every DNS name through the same matcher and
candidate archive as CertStream. Polling runs outside the shared writer lock and writes a
results file; ``ingest`` merges results into ``data/`` inside the lock.

Only tiled logs are read: their data tiles are cheap, cacheable and need no pagination.
It covers the configured logs only, not every public CT log.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID

from .brands import BrandRegistry, load_brand_registry, score_domain
from .certstream import CertificateEvidence, parse_message
from .certstream_archive import CandidateArchiveWriter, candidate_from_match
from .models import CertStreamCandidate, RawSignal
from .normalize import resolve_signal_times
from .seeds import _compile_brand_prefilter, _may_match_reviewed_brand

LOG_LIST_URL = "https://www.gstatic.com/ct/log_list/v3/log_list.json"
DEFAULT_STATE_PATH = "data/ct-logs/state.json"
DEFAULT_ARCHIVE_ROOT = "data/certstream"
COLLECTION_METHOD = "ct-log-poll"
TILE_WIDTH = 256
USER_AGENT = "hecavex-radar-ct-logs/1.0 (+https://radar.hecavex.com/)"
MAXIMUM_TILE_BYTES = 8 * 1024 * 1024
MAXIMUM_LOG_LIST_BYTES = 4 * 1024 * 1024
MAXIMUM_STATE_BYTES = 256 * 1024
MAXIMUM_NAMES_PER_ENTRY = 500
# Shards are split by certificate expiry; ordinary 90-day issuance lands in the shard
# covering now + ~90 days, so read every shard whose interval overlaps this horizon.
SHARD_HORIZON_DAYS = 100
PREFETCH_TILES = 32
TAIL_SLEEP_SECONDS = 20

Fetcher = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class Shard:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class Entry:
    names: tuple[str, ...]
    timestamp_ms: int
    der: bytes = b""


def fetch(url: str, *, maximum: int = MAXIMUM_TILE_BYTES, tries: int = 4) -> bytes:
    if urlsplit(url).scheme != "https":
        raise ValueError("CT log URLs must use HTTPS.")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})  # noqa: S310 - HTTPS only
    for attempt in range(tries):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - HTTPS only
                body = cast(bytes, response.read(maximum + 1))
                if len(body) > maximum:
                    raise ValueError("CT log response exceeds its size limit.")
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == tries - 1:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            time.sleep(min(60.0, float(retry_after) if retry_after and retry_after.isdigit() else 2.0**attempt))
        except (URLError, TimeoutError):
            if attempt == tries - 1:
                raise
            time.sleep(2.0**attempt)
    raise RuntimeError("unreachable")


def select_shards(log_list: dict[str, Any], prefixes: list[str], now: datetime) -> list[Shard]:
    """Usable or qualified tiled shards of the named logs whose expiry window overlaps the horizon."""
    horizon = now + timedelta(days=SHARD_HORIZON_DAYS)
    shards: list[Shard] = []
    for operator in log_list.get("operators", []):
        for log in operator.get("tiled_logs", []):
            name, url = log.get("description", ""), log.get("monitoring_url", "")
            states = set(log.get("state") or {})
            interval = log.get("temporal_interval") or {}
            try:
                start = datetime.fromisoformat(interval["start_inclusive"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(interval["end_exclusive"].replace("Z", "+00:00"))
            except (KeyError, AttributeError, ValueError):
                continue
            if (
                any(name.startswith(prefix) for prefix in prefixes)
                and states & {"usable", "qualified"}
                and start <= horizon
                and end > now
                and urlsplit(url).scheme == "https"
            ):
                shards.append(Shard(name, url if url.endswith("/") else url + "/"))
    return sorted(shards, key=lambda shard: shard.name)


def parse_checkpoint(text: str) -> int:
    lines = text.split("\n")
    if len(lines) < 3 or not lines[1].isdigit():
        raise ValueError("Not a C2SP checkpoint.")
    return int(lines[1])


def tile_path(index: int) -> str:
    groups = []
    while True:
        groups.append(index % 1000)
        index //= 1000
        if index == 0:
            break
    groups.reverse()
    return "tile/data/" + "/".join([f"x{group:03d}" for group in groups[:-1]] + [f"{groups[-1]:03d}"])


def _name_text(name: x509.Name, oid: x509.ObjectIdentifier) -> str | None:
    values = name.get_attributes_for_oid(oid)
    return values[0].value if values and isinstance(values[0].value, str) else None


def _names(certificate: x509.Certificate) -> tuple[str, ...]:
    try:
        sans = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = sans.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    domains = tuple(dict.fromkeys(name.lower() for name in names[:MAXIMUM_NAMES_PER_ENTRY]))
    common_name = _name_text(certificate.subject, NameOID.COMMON_NAME)
    return domains or ((common_name.lower(),) if common_name else ())


def entry_from_der(der: bytes, timestamp_ms: int) -> Entry:
    try:
        return Entry(_names(x509.load_der_x509_certificate(der)), timestamp_ms, der)
    except Exception:  # untrusted log data: one malformed leaf must not stop the log
        return Entry((), timestamp_ms)


def certificate_evidence(der: bytes) -> CertificateEvidence | None:
    """Build CertStream-shaped leaf fields and let CertStream's own parser bound them (hits only)."""
    try:
        certificate = x509.load_der_x509_certificate(der)
        common_name = _name_text(certificate.subject, NameOID.COMMON_NAME)
        leaf = {
            "all_domains": list(_names(certificate)),
            "subject": {"CN": common_name, "C": _name_text(certificate.subject, NameOID.COUNTRY_NAME)},
            "issuer": {
                "O": _name_text(certificate.issuer, NameOID.ORGANIZATION_NAME),
                "CN": _name_text(certificate.issuer, NameOID.COMMON_NAME),
            },
            "serial_number": format(certificate.serial_number, "x"),
            "not_before": certificate.not_valid_before_utc.timestamp(),
            "not_after": certificate.not_valid_after_utc.timestamp(),
            "fingerprints": {
                "sha256": certificate.fingerprint(hashes.SHA256()).hex(),
                "sha1": certificate.fingerprint(hashes.SHA1()).hex(),  # noqa: S303 - identifier, not security
            },
        }
    except Exception:
        return None
    return parse_message({"message_type": "certificate_update", "data": {"leaf_cert": leaf}}).certificate


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.offset = data, 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise EOFError
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def number(self, size: int) -> int:
        return int.from_bytes(self.take(size), "big")


def parse_tile(data: bytes) -> list[Entry]:
    """Decode a static-ct data tile (TileLeaf records). A truncated tail keeps the complete entries."""
    reader, entries = _Reader(data), []
    while reader.offset < len(data):
        try:
            timestamp, entry_type = reader.number(8), reader.number(2)
            if entry_type == 0:  # x509_entry
                der = reader.take(reader.number(3))
                reader.take(reader.number(2))  # extensions
            elif entry_type == 1:  # precert_entry: issuer key hash, TBS, extensions, then the full precertificate
                reader.take(32)
                reader.take(reader.number(3))
                reader.take(reader.number(2))
                der = reader.take(reader.number(3))
            else:
                break
            reader.take(reader.number(2))  # chain fingerprints
        except EOFError:
            break
        entries.append(entry_from_der(der, timestamp))
    return entries


def plan_range(last: int | None, size: int, cap: int) -> tuple[int, int, int]:
    """Return (start, end, skipped). A new log starts at its head; a backlog beyond cap keeps the newest."""
    start = size if last is None or last > size else last
    skipped = max(0, size - cap - start)
    return start + skipped, size, skipped


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _candidates(
    entry: Entry, registry: BrandRegistry, prefilter: Any, minimum: int, metrics: dict[str, int]
) -> list[CertStreamCandidate]:
    found: list[CertStreamCandidate] = []
    certificate: CertificateEvidence | None = None
    for domain in entry.names:
        metrics["dnsNames"] += 1
        if not _may_match_reviewed_brand(domain, prefilter):
            continue
        match = score_domain(domain, registry)
        if match is None or match.confidence < minimum:
            continue
        metrics["matches"] += 1
        if certificate is None:
            certificate = certificate_evidence(entry.der)
        collected = _timestamp(datetime.now(UTC))
        logged = _timestamp(datetime.fromtimestamp(entry.timestamp_ms / 1000, UTC))
        evidence = resolve_signal_times(
            RawSignal(url=match.domain, source="CertStream", first_seen=logged, last_seen=logged), collected
        )
        observed = datetime.fromisoformat(evidence[-1]["timestamp"].replace("Z", "+00:00"))
        try:
            found.append(candidate_from_match(
                match, observed, certificate, COLLECTION_METHOD, source_time_evidence=evidence,
            ))
        except ValueError:  # an unrepresentable match must not discard the log's progress
            metrics["unrepresentable"] += 1
    return found


def poll(
    shards: list[Shard],
    checkpoints: dict[str, int],
    *,
    deadline: float,
    cap: int,
    registry: BrandRegistry,
    minimum_confidence: int = 80,
    fetcher: Fetcher = fetch,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Tail every shard round-robin until the deadline; checkpoints advance only past whole parsed tiles."""
    prefilter = _compile_brand_prefilter(registry)
    candidates: list[CertStreamCandidate] = []
    logs: dict[str, dict[str, Any]] = {}
    planned: set[str] = set()
    for shard in shards:
        logs[shard.url] = {"name": shard.name, "next": checkpoints.get(shard.url), "treeSize": None,
                           "skipped": 0, "entries": 0, "dnsNames": 0, "matches": 0, "unrepresentable": 0,
                           "error": None}
    with ThreadPoolExecutor(8) as pool:
        while clock() < deadline:
            progressed = False
            for shard in shards:
                record = logs[shard.url]
                if clock() >= deadline:
                    break
                try:
                    size = parse_checkpoint(fetcher(shard.url + "checkpoint").decode("utf-8"))
                    if shard.url not in planned:
                        start, _end, skipped = plan_range(record["next"], size, cap)
                        record["skipped"] += skipped
                        record["next"] = start
                        planned.add(shard.url)
                    record["treeSize"] = size
                    first, last = record["next"] // TILE_WIDTH, size // TILE_WIDTH  # full tiles only
                    batch = list(range(first, min(last, first + PREFETCH_TILES)))
                    urls = [shard.url + tile_path(index) for index in batch]
                    for index, raw in zip(batch, pool.map(fetcher, urls), strict=True):
                        entries = parse_tile(raw)
                        if len(entries) != TILE_WIDTH:
                            raise ValueError(f"Full tile {index} decoded {len(entries)} entries.")
                        for entry in entries[record["next"] - index * TILE_WIDTH :]:
                            record["entries"] += 1
                            candidates.extend(_candidates(entry, registry, prefilter, minimum_confidence, record))
                        record["next"] = (index + 1) * TILE_WIDTH
                        progressed = True
                        if clock() >= deadline:
                            break
                    record["error"] = None
                except Exception as error:  # one failing log must not stop the others; retry next round
                    record["error"] = f"{type(error).__name__}: {str(error)[:160]}"
            if not progressed:
                sleep(min(TAIL_SLEEP_SECONDS, max(0.0, deadline - clock())))
    for record in logs.values():
        if record["next"] is not None and record["treeSize"] is not None:
            record["lag"] = record["treeSize"] - record["next"]
    return {"logs": logs, "candidates": candidates}


def read_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"schemaVersion": 1, "generatedAt": None, "logs": {}}
    body = target.read_bytes()
    if len(body) > MAXIMUM_STATE_BYTES:
        raise ValueError("CT log state exceeds its size limit.")
    state = json.loads(body)
    logs = state.get("logs") if isinstance(state, dict) else None
    if state.get("schemaVersion") != 1 or not isinstance(logs, dict) or not all(
        isinstance(url, str) and urlsplit(url).scheme == "https" and isinstance(value, dict)
        and type(value.get("next")) is int and value["next"] >= 0
        for url, value in logs.items()
    ):
        raise ValueError("CT log state is invalid.")
    return cast(dict[str, Any], state)


def write_state(state: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    body = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(body) > MAXIMUM_STATE_BYTES:
        raise ValueError("CT log state exceeds its size limit.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        stream.write(body)
    os.replace(stream.name, target)


def ingest(results: list[dict[str, Any]], state_path: str | Path, archive_root: str | Path) -> int:
    """Archive candidates first, then advance checkpoints, so a failed write only causes a replay."""
    state = read_state(state_path)
    candidates = [candidate for result in results for candidate in result["candidates"]]
    written = CandidateArchiveWriter(archive_root).append(candidates)
    now = _timestamp(datetime.now(UTC))
    for result in results:
        for url, record in result["logs"].items():
            if urlsplit(url).scheme != "https" or type(record.get("next")) is not int or record["next"] < 0:
                raise ValueError("CT log result is invalid.")
            previous = state["logs"].get(url, {})
            state["logs"][url] = {
                "name": str(record.get("name"))[:120],
                "next": max(record["next"], previous.get("next", 0)),
                "treeSize": record.get("treeSize"),
                "lag": record.get("lag"),
                "skippedTotal": previous.get("skippedTotal", 0) + int(record.get("skipped") or 0),
                "lastRunAt": now,
                "lastError": record.get("error"),
            }
    state["generatedAt"] = now
    write_state(state, state_path)
    return written


def _bounded(value: str | None, fallback: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(value))) if value else fallback
    except ValueError:
        return fallback


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    poll_command = commands.add_parser("poll", help="Tail the shards of one named log and write a results file.")
    poll_command.add_argument("--log", required=True, help="Log name prefix, e.g. 'Google PlumbersArms'.")
    poll_command.add_argument("--out", type=Path, required=True)
    poll_command.add_argument("--state", default=os.environ.get("CT_LOGS_STATE_PATH", DEFAULT_STATE_PATH))
    poll_command.add_argument("--log-list", type=Path, help="Use a saved log list instead of fetching it.")
    ingest_command = commands.add_parser("ingest", help="Merge results files into the archive and checkpoints.")
    ingest_command.add_argument("results", type=Path, nargs="+")
    ingest_command.add_argument("--state", default=os.environ.get("CT_LOGS_STATE_PATH", DEFAULT_STATE_PATH))
    ingest_command.add_argument(
        "--archive-root", default=os.environ.get("CERTSTREAM_ARCHIVE_ROOT", DEFAULT_ARCHIVE_ROOT)
    )
    options = parser.parse_args(arguments)

    if options.command == "ingest":
        results = [json.loads(path.read_text(encoding="utf-8")) for path in options.results]
        written = ingest(results, options.state, options.archive_root)
        print(f"CT logs: archived {written} new candidates from {len(results)} result files.", flush=True)
        return 0

    log_list = json.loads(
        options.log_list.read_bytes() if options.log_list else fetch(LOG_LIST_URL, maximum=MAXIMUM_LOG_LIST_BYTES)
    )
    shards = select_shards(log_list, [options.log], datetime.now(UTC))
    if not shards:
        print(f"CT logs: no current shard matches {options.log!r}.", file=sys.stderr, flush=True)
        return 1
    state = read_state(options.state)
    seconds = _bounded(os.environ.get("CT_LOGS_DEADLINE_SECONDS"), 2400, 30, 3 * 3600)
    result = poll(
        shards,
        {url: value["next"] for url, value in state["logs"].items()},
        deadline=time.monotonic() + seconds,
        cap=_bounded(os.environ.get("CT_LOGS_CAP_PER_LOG"), 2_000_000, 1, 50_000_000),
        registry=load_brand_registry(),
        minimum_confidence=_bounded(os.environ.get("CERTSTREAM_MIN_CONFIDENCE"), 80, 1, 100),
    )
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    for record in result["logs"].values():
        print(f"CT logs {record['name']}: {record['entries']} entries, {record['dnsNames']} names, "
              f"{record['matches']} matches, lag {record.get('lag')}, skipped {record['skipped']}, "
              f"error {record['error']}", flush=True)
    return 0 if any(record["error"] is None for record in result["logs"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
