from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect

from .brands import load_brand_registry, score_domain
from .certstream import parse_message
from .certstream_archive import CandidateArchiveWriter, candidate_from_match, record_successful_attempt
from .collection_health import (
    CollectionMetrics,
    CollectionOutcome,
    begin_attempt,
    complete_attempt,
    read_collection_health,
)
from .models import CertStreamCandidate

MAXIMUM_MESSAGE_BYTES = 1024 * 1024


def _enabled(value: str | None) -> bool:
    return bool(value and value.strip().lower() == "true")


def _bounded_integer(value: str | None, fallback: int, minimum: int, maximum: int) -> int:
    if not value or not value.strip():
        return fallback
    try:
        parsed = int(value)
    except ValueError:
        return fallback
    return min(maximum, max(minimum, parsed))


def _websocket_url(value: str | None, allow_insecure: bool) -> str:
    url = value.strip() if value and value.strip() else "wss://certstream.calidog.io/"
    parsed = urlsplit(url)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "wss" and not (parsed.scheme == "ws" and (local or allow_insecure)):
        raise ValueError(
            "CERTSTREAM_URL must use WSS (set CERTSTREAM_ALLOW_INSECURE_WS=true only for a trusted private network)."
        )
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("CERTSTREAM_URL must not contain credentials.")
    return url


async def _receive_or_stop(websocket: ClientConnection, stop: asyncio.Event, timeout: float) -> str | bytes | None:
    receive_task = asyncio.create_task(websocket.recv())
    stop_task = asyncio.create_task(stop.wait())
    done, pending = await asyncio.wait({receive_task, stop_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if not done:
        await asyncio.gather(*pending, return_exceptions=True)
        raise TimeoutError
    if stop_task in done and stop_task.result():
        receive_task.cancel()
        await asyncio.gather(receive_task, return_exceptions=True)
        return None
    stop_task.cancel()
    await asyncio.gather(stop_task, return_exceptions=True)
    return receive_task.result()


async def collect(metrics: CollectionMetrics | None = None) -> int:
    metrics = metrics or CollectionMetrics()
    registry = load_brand_registry()
    url = _websocket_url(os.environ.get("CERTSTREAM_URL"), _enabled(os.environ.get("CERTSTREAM_ALLOW_INSECURE_WS")))
    duration_seconds = _bounded_integer(os.environ.get("CERTSTREAM_DURATION_SECONDS"), 480, 0, 86_400)
    flush_seconds = _bounded_integer(os.environ.get("CERTSTREAM_FLUSH_SECONDS"), 15, 5, 300)
    idle_seconds = _bounded_integer(os.environ.get("CERTSTREAM_IDLE_SECONDS"), 90, 30, 600)
    minimum_confidence = _bounded_integer(os.environ.get("CERTSTREAM_MIN_CONFIDENCE"), 80, 1, 100)
    require_messages = _enabled(os.environ.get("CERTSTREAM_REQUIRE_MESSAGES"))
    archive_root = os.environ.get("CERTSTREAM_ARCHIVE_ROOT", "").strip() or "data/certstream"
    writer = CandidateArchiveWriter(archive_root)
    pending: dict[str, CertStreamCandidate] = {}
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_arguments: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    for interrupt in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(interrupt, stop.set)
        except NotImplementedError:
            signal.signal(interrupt, request_stop)

    retry_seconds = 1.0
    started = time.monotonic()
    metrics.collector_started_at = datetime.now(UTC)
    deadline = started + duration_seconds if duration_seconds else float("inf")
    last_flush = started
    last_stats = started

    def flush() -> None:
        nonlocal last_flush
        batch = list(pending.values())
        pending.clear()
        try:
            metrics.new_records += writer.append(batch)
            last_flush = time.monotonic()
        except Exception:
            pending.update((candidate["id"], candidate) for candidate in batch)
            raise

    mode = "continuous" if duration_seconds == 0 else f"{duration_seconds}s bounded"
    print(f"CertStream collector started with {len(registry.entries)} public brand entries ({mode} mode).", flush=True)

    while not stop.is_set() and time.monotonic() < deadline:
        metrics.connection_attempts += 1
        try:
            async with connect(
                url,
                open_timeout=15,
                max_size=MAXIMUM_MESSAGE_BYTES,
                ping_interval=30,
                ping_timeout=20,
                close_timeout=10,
            ) as websocket:
                connected_at = time.monotonic()
                metrics.connections += 1
                retry_seconds = 1.0
                print("CertStream connection established.", flush=True)
                try:
                    while not stop.is_set() and time.monotonic() < deadline:
                        remaining = deadline - time.monotonic()
                        timeout = min(float(idle_seconds), remaining)
                        try:
                            raw = await _receive_or_stop(websocket, stop, timeout)
                        except TimeoutError:
                            if time.monotonic() >= deadline:
                                break
                            print(
                                f"CertStream connection was idle for {idle_seconds}s; reconnecting.",
                                file=sys.stderr,
                                flush=True,
                            )
                            break
                        if raw is None:
                            break
                        body = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
                        if len(body.encode("utf-8")) > MAXIMUM_MESSAGE_BYTES:
                            continue
                        try:
                            payload: Any = json.loads(body)
                        except json.JSONDecodeError:
                            continue
                        metrics.messages += 1
                        observed_at = datetime.now(UTC)
                        parsed_message = parse_message(payload)
                        for candidate_domain in parsed_message.domains:
                            metrics.dns_names += 1
                            match = score_domain(candidate_domain, registry)
                            if not match or match.confidence < minimum_confidence:
                                continue
                            metrics.matches += 1
                            candidate = candidate_from_match(
                                match, observed_at, parsed_message.certificate, collection_method="certstream-live",
                            )
                            existing = pending.get(candidate["id"])
                            candidate_payload = cast(dict[str, object], candidate)
                            existing_payload = cast(dict[str, object], existing) if existing is not None else None
                            if existing_payload is None or (
                                "certificate" in candidate_payload and "certificate" not in existing_payload
                            ):
                                pending[candidate["id"]] = candidate
                        current = time.monotonic()
                        if len(pending) >= 5_000 or current - last_flush >= flush_seconds:
                            flush()
                        if current - last_stats >= 60:
                            print(
                                f"CertStream: {metrics.messages} messages, {metrics.dns_names} domains checked, "
                                f"{metrics.matches} candidates matched, {metrics.new_records} new records saved.",
                                flush=True,
                            )
                            last_stats = current
                finally:
                    metrics.listening_seconds += max(0.0, min(time.monotonic(), deadline) - connected_at)
        except Exception as error:
            metrics.connection_errors += 1
            message = str(error).splitlines()[0] if str(error) else type(error).__name__
            print(f"CertStream connection unavailable: {message}", file=sys.stderr, flush=True)

        if stop.is_set() or time.monotonic() >= deadline:
            break
        wait_seconds = min(retry_seconds, max(0.0, deadline - time.monotonic()))
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=wait_seconds)
        retry_seconds = min(30.0, retry_seconds * 2)

    metrics.interrupted = stop.is_set()
    metrics.completed_window = duration_seconds > 0 and time.monotonic() >= deadline
    flush()
    print(
        f"CertStream collector stopped: {metrics.messages} messages, {metrics.dns_names} domains checked, "
        f"{metrics.matches} candidates matched, {metrics.new_records} new records saved, "
        f"{metrics.listening_seconds:.3f}s listening.",
        flush=True,
    )
    if require_messages and metrics.dns_names == 0:
        raise RuntimeError("The CertStream endpoint produced no certificate domains during the collection window.")
    return metrics.new_records


def _collection_outcome(metrics: CollectionMetrics, duration_seconds: int, failed: bool = False) -> CollectionOutcome:
    if metrics.connections == 0:
        return "failed"
    if metrics.dns_names == 0:
        return "no-input"
    minimum_healthy_listening = duration_seconds * 0.9 if duration_seconds else float("inf")
    if (
        failed
        or metrics.interrupted
        or not metrics.completed_window
        or metrics.listening_seconds < minimum_healthy_listening
    ):
        return "partial"
    return "healthy-matches" if metrics.matches else "healthy-empty"


def main() -> int:
    metrics = CollectionMetrics()
    health_path = os.environ.get("CERTSTREAM_HEALTH_PATH", "").strip() or None
    duration_seconds = _bounded_integer(os.environ.get("CERTSTREAM_DURATION_SECONDS"), 480, 0, 86_400)
    if health_path:
        try:
            current = read_collection_health(health_path, allow_running=True)
            if current is None or current["latestAttempt"] is None or current["latestAttempt"]["outcome"] is not None:
                begin_attempt(health_path)
        except Exception as error:
            print(f"CertStream collector failed to initialize public health metadata: {error}", file=sys.stderr)
            return 1
    try:
        asyncio.run(collect(metrics))
        outcome = _collection_outcome(metrics, duration_seconds)
        ended_at = datetime.now(UTC)
        if outcome in {"healthy-empty", "healthy-matches"}:
            if metrics.collector_started_at is None:
                raise RuntimeError("A successful CertStream attempt is missing its collector start time.")
            archive_root = os.environ.get("CERTSTREAM_ARCHIVE_ROOT", "").strip() or "data/certstream"
            record_successful_attempt(
                archive_root,
                collector_started_at=metrics.collector_started_at,
                ended_at=ended_at,
                expected_listening_seconds=duration_seconds,
                listening_seconds=metrics.listening_seconds,
                messages=metrics.messages,
                dns_names=metrics.dns_names,
                matches=metrics.matches,
                new_records=metrics.new_records,
                outcome=outcome,
            )
        if health_path:
            complete_attempt(metrics, outcome, health_path, now=ended_at)
        if outcome in {"partial", "failed"}:
            print(f"CertStream collector ended with a {outcome} outcome.", file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        metrics.interrupted = True
        if health_path:
            with suppress(Exception):
                complete_attempt(metrics, _collection_outcome(metrics, duration_seconds, failed=True), health_path)
        return 130
    except Exception as error:
        if health_path:
            try:
                complete_attempt(metrics, _collection_outcome(metrics, duration_seconds, failed=True), health_path)
            except Exception as health_error:
                print(f"CertStream health finalization failed: {health_error}", file=sys.stderr)
        print(f"CertStream collector failed: {error}", file=sys.stderr)
        return 1


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
