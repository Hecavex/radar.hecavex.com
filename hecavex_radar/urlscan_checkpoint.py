"""Bounded URLScan search pagination checkpoints.

The checkpoint stores provider sort cursors and public scan identifiers only.
It deliberately stores a digest of each query rather than the query text so
candidate and brand terms are not copied into operational state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

SEARCH_ENDPOINT = "https://urlscan.io/api/v1/search/"
MAXIMUM_STATE_BYTES = 256 * 1024
MAXIMUM_QUERIES = 256
MAXIMUM_RECENT_IDS = 100
MAXIMUM_RESULTS_PER_CALL = 1_000
MAXIMUM_CURSOR_PARTS = 4
STATE_RETENTION = timedelta(days=30)
CURSOR_TEXT = re.compile(r"^[A-Za-z0-9._:+/@=-]{1,160}$")

JsonRequester = Callable[[str, str], Any]


class SearchUnavailable(RuntimeError):
    """Signal that a search was not performed and must not advance state."""


class CheckpointCapacityError(RuntimeError):
    """Durable unresolved work cannot fit without losing continuation state."""


def _state_body(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if _timestamp(parsed) == value else None


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def query_family(query: str) -> str:
    """Classify only our fixed builders; never persist query terms or URLs."""
    if "AND (hash:" in query:
        return "hash-pivot"
    if 'task.domain.keyword:"' in query:
        return "exact-domain-batch"
    if "task.domain.keyword:(" in query:
        return "domain"
    if "page.title.keyword:(" in query:
        return "title"
    return "legacy-unclassified"


def audit_ownership(state: dict[str, Any], planned_queries: list[str]) -> list[dict[str, object]]:
    """Read-only custody report. Absence from a plan NEVER retires unresolved work."""
    if not _valid_state(_migrate_state(state)):
        raise ValueError("Invalid checkpoint state.")
    plan = {_query_hash(query): query_family(query) for query in planned_queries}
    result = []
    for key, row in sorted(state["queries"].items()):
        if not row["backlogPending"]:
            continue
        result.append({"queryHash": key, "queryFamily": plan.get(key, row.get("queryFamily", "legacy-unclassified")),
                       "ownership": "active-in-supplied-plan" if key in plan else "unresolved-not-in-supplied-plan",
                       "lastProgressAt": row.get("lastProgressAt", row["updatedAt"]),
                       "backlogResultsSeen": row["backlogResultsSeen"],
                       "retired": False})
    return result


def _sort_token(value: object) -> list[str | int | float] | None:
    if not isinstance(value, list) or not 1 <= len(value) <= MAXIMUM_CURSOR_PARTS:
        return None
    parts: list[str | int | float] = []
    for part in value:
        if isinstance(part, bool) or not isinstance(part, (str, int, float)):
            return None
        if isinstance(part, float) and not math.isfinite(part):
            return None
        if isinstance(part, str) and not CURSOR_TEXT.fullmatch(part):
            return None
        parts.append(part)
    return parts


def _scan_id(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    task = value.get("task")
    candidate = value.get("_id")
    if not isinstance(candidate, str) and isinstance(task, dict):
        candidate = task.get("uuid")
    if not isinstance(candidate, str) or not 8 <= len(candidate) <= 80:
        return None
    if any(character not in "0123456789abcdefABCDEF-" for character in candidate):
        return None
    return candidate.lower()


def _public_result(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    task = value.get("task")
    if not isinstance(task, dict) or task.get("visibility") != "public":
        return None
    return cast(dict[str, Any], value)


def _unique_results(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in values:
        identifier = _scan_id(row) or hashlib.sha256(
            json.dumps(row, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if identifier in seen:
            continue
        seen.add(identifier)
        unique.append(row)
        if len(unique) >= MAXIMUM_RESULTS_PER_CALL:
            break
    return unique


def _valid_checkpoint(value: object) -> bool:
    if not isinstance(value, dict) or set(value) - {"queryFamily"} != {
        "queryHash",
        "updatedAt",
        "lastProgressAt",
        "complete",
        "backlogPending",
        "providerTruncated",
        "nextSearchAfter",
        "newestSort",
        "providerTotal",
        "backlogResultsSeen",
        "pagesFetched",
        "resultsObserved",
        "overlapResults",
        "recentIds",
    }:
        return False
    recent = value["recentIds"]
    total = value["providerTotal"]
    return (
        isinstance(value.get("queryFamily", "legacy-unclassified"), str)
        and value.get("queryFamily", "legacy-unclassified") in {
            "domain", "title", "exact-domain-batch", "hash-pivot", "legacy-unclassified"
        }
        and
        isinstance(value["queryHash"], str)
        and len(value["queryHash"]) == 64
        and all(character in "0123456789abcdef" for character in value["queryHash"])
        and _parse_timestamp(value["updatedAt"]) is not None
        and _parse_timestamp(value["lastProgressAt"]) is not None
        and type(value["complete"]) is bool
        and type(value["backlogPending"]) is bool
        and type(value["providerTruncated"]) is bool
        and (value["nextSearchAfter"] is None or _sort_token(value["nextSearchAfter"]) is not None)
        and (value["newestSort"] is None or _sort_token(value["newestSort"]) is not None)
        and (total is None or (type(total) is int and 0 <= total <= 2_000_000_000))
        and all(
            type(value[field]) is int and 0 <= value[field] <= 2_000_000_000
            for field in ("backlogResultsSeen", "pagesFetched", "resultsObserved", "overlapResults")
        )
        and isinstance(recent, list)
        and len(recent) <= MAXIMUM_RECENT_IDS
        and len(recent) == len(set(recent))
        and all(isinstance(identifier, str) and 8 <= len(identifier) <= 80 for identifier in recent)
        and value["backlogPending"] == (value["nextSearchAfter"] is not None)
    )


def _empty_state(now: datetime) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "dataset": "urlscan-search-checkpoints",
        "generatedAt": _timestamp(now),
        "queries": {},
    }


def _migrate_state(value: object) -> object:
    """Add progress timestamps to the original v1 checkpoint contract."""

    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        return value
    queries = value.get("queries")
    if not isinstance(queries, dict):
        return value
    migrated = dict(value)
    migrated_queries: dict[object, object] = {}
    for key, raw in queries.items():
        if isinstance(raw, dict) and "lastProgressAt" not in raw and isinstance(raw.get("updatedAt"), str):
            row = dict(raw)
            row["lastProgressAt"] = raw["updatedAt"]
            migrated_queries[key] = row
        else:
            migrated_queries[key] = raw
    migrated["queries"] = migrated_queries
    return migrated


def _valid_state(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "dataset", "generatedAt", "queries"}:
        return False
    queries = value["queries"]
    return (
        value["schemaVersion"] == 1
        and value["dataset"] == "urlscan-search-checkpoints"
        and _parse_timestamp(value["generatedAt"]) is not None
        and isinstance(queries, dict)
        and len(queries) <= MAXIMUM_QUERIES
        and all(
            key == checkpoint.get("queryHash") and _valid_checkpoint(checkpoint)
            for key, checkpoint in queries.items()
        )
    )


def _is_linklike(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _reject_symlink_components(target: Path, repository: Path) -> None:
    if _is_linklike(repository):
        raise ValueError("URLScan checkpoints refuse a symlinked repository root.")
    if not target.is_relative_to(repository):
        raise ValueError("URLScan checkpoint path escapes the repository.")
    current = repository
    for part in target.relative_to(repository).parts:
        current /= part
        if _is_linklike(current):
            raise ValueError(f"URLScan checkpoints refuse symlinked path component {current.name}.")


def _bounded_path(value: str | Path) -> Path:
    repository = Path(os.path.abspath(Path.cwd()))
    raw = Path(value)
    target = Path(os.path.abspath(repository / raw if not raw.is_absolute() else raw))
    expected = Path(os.path.abspath(repository / "data/urlscan/search-checkpoints.json"))
    if target != expected:
        raise ValueError("URLScan checkpoint state must be data/urlscan/search-checkpoints.json.")
    _reject_symlink_components(target, repository)
    return target


def _page(
    query: str,
    size: int,
    api_key: str,
    requester: JsonRequester,
    search_after: list[str | int | float] | None = None,
) -> tuple[list[dict[str, Any]], bool | None, int | None, list[str | int | float] | None]:
    parameters: dict[str, object] = {"q": query, "size": size, "datasource": "scans"}
    if search_after is not None:
        parameters["search_after"] = ",".join(str(part) for part in search_after)
    payload = requester(f"{SEARCH_ENDPOINT}?{urlencode(parameters)}", api_key)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("URLScan search returned an unexpected payload.")
    results = [result for raw in payload["results"] if (result := _public_result(raw)) is not None]
    has_more = payload.get("has_more") if type(payload.get("has_more")) is bool else None
    total_value = payload.get("total")
    total = total_value if type(total_value) is int and 0 <= total_value <= 2_000_000_000 else None
    next_token = _sort_token(results[-1].get("sort")) if results else None
    return results, has_more, total, next_token


class SearchCheckpointStore:
    """Collect checkpoint updates in memory and commit after archival succeeds."""

    def __init__(self, path: str | Path, state: dict[str, Any], now: datetime) -> None:
        self.path = _bounded_path(path)
        self.state = state
        self.now = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
        self.dirty = False

    @classmethod
    def load(cls, path: str | Path, *, now: datetime) -> SearchCheckpointStore:
        target = _bounded_path(path)
        try:
            if target.stat().st_size > MAXIMUM_STATE_BYTES:
                raise ValueError("URLScan checkpoint state exceeds 256 KiB.")
            value: object = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = _empty_state(now)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("URLScan checkpoint state is unreadable.") from error
        value = _migrate_state(value)
        if not _valid_state(value):
            raise ValueError("URLScan checkpoint state has an invalid contract.")
        state = cast(dict[str, Any], value)
        cutoff = now.astimezone(UTC) - STATE_RETENTION
        queries = cast(dict[str, dict[str, Any]], state["queries"])
        state["queries"] = {
            key: row
            for key, row in queries.items()
            if not row["complete"]
            or ((updated := _parse_timestamp(row["updatedAt"])) is not None and updated >= cutoff)
        }
        return cls(target, state, now)

    def _fit_capacity(self, *, reserve_bytes: int = 0, protected_key: str | None = None) -> None:
        """Trim replay hints, then completed caches, never unresolved cursors.

        Recent IDs are overlap optimizations, not progress checkpoints. Keep
        their newest ID where possible. Losing a hint can cause bounded replay,
        but cannot mark an unprocessed provider page complete.
        """
        queries = cast(dict[str, dict[str, Any]], self.state["queries"])
        ordered = sorted(queries.values(), key=lambda row: (row["updatedAt"], row["queryHash"]))
        def fits() -> bool:
            return (
                len(queries) <= MAXIMUM_QUERIES
                and len(_state_body(self.state).encode("utf-8")) + reserve_bytes <= MAXIMUM_STATE_BYTES
            )
        if fits():
            return
        for row in ordered:
            if len(row["recentIds"]) > 1:
                row["recentIds"] = row["recentIds"][:1]
                self.dirty = True
                if fits():
                    return
        for row in ordered:
            if row["complete"] and row["queryHash"] != protected_key:
                del queries[row["queryHash"]]
                self.dirty = True
                if fits():
                    return
        raise CheckpointCapacityError(
            "state-capacity: unresolved URLScan checkpoints fill the bounded store; "
            "continuation cursors were preserved."
        )

    def preflight(self) -> None:
        """Check final serialization before an archive write can succeed."""
        self._fit_capacity()
        if not _valid_state(self.state):
            raise ValueError("Refusing to write invalid URLScan checkpoint state.")

    def search(
        self,
        query: str,
        size: int,
        api_key: str,
        requester: JsonRequester,
        *,
        backlog_pages: int = 1,
    ) -> list[dict[str, Any]]:
        if "task.visibility:public" not in query:
            raise ValueError("URLScan searches must be restricted to public scans.")
        page_size = min(MAXIMUM_RESULTS_PER_CALL, max(1, size))
        key = _query_hash(query)
        # Reserve room for bounded sort cursors and metadata before spending
        # provider budget. Replay hints can subsequently be compacted to fit.
        self._fit_capacity(reserve_bytes=4096, protected_key=key)
        queries = cast(dict[str, dict[str, Any]], self.state["queries"])
        if key not in queries and len(queries) == MAXIMUM_QUERIES:
            completed = sorted(
                (row for row in queries.values() if row["complete"]),
                key=lambda row: (row["updatedAt"], row["queryHash"]),
            )
            if not completed:
                raise CheckpointCapacityError("state-capacity: all URLScan query slots contain unresolved work.")
            del queries[completed[0]["queryHash"]]
            self.dirty = True
        previous = queries.get(key)
        previous_ids = set(cast(list[str], previous.get("recentIds", []))) if previous else set()
        try:
            first, first_more, total, first_cursor = _page(query, page_size, api_key, requester)
        except SearchUnavailable:
            # An exhausted local/provider budget is not an empty provider page.
            # Preserve the checkpoint so a later run can resume the backlog.
            return []
        combined = list(first)
        first_ids = [identifier for row in first if (identifier := _scan_id(row)) is not None]
        overlap = len(previous_ids.intersection(first_ids))
        pages_fetched = 1

        backlog = _sort_token(previous.get("nextSearchAfter")) if previous else None
        backlog_cursor = backlog
        backlog_seen = cast(int, previous.get("backlogResultsSeen", 0)) if previous else 0
        provider_truncated = bool(previous.get("providerTruncated", False)) if previous else False
        for _ in range(min(max(0, backlog_pages), 4)):
            if backlog_cursor is None:
                break
            try:
                page_results, backlog_more, page_total, next_cursor = _page(
                    query,
                    page_size,
                    api_key,
                    requester,
                    backlog_cursor,
                )
            except SearchUnavailable:
                # The fresh page remains usable for this run, but interrupted
                # backlog work must not move or clear the durable cursor.
                return _unique_results(combined)
            combined.extend(page_results)
            pages_fetched += 1
            backlog_seen += len(page_results)
            provider_truncated = provider_truncated or backlog_more is True
            exhausted_known_total = page_total is not None and backlog_seen >= page_total and backlog_more is not True
            exhausted_short_page = len(page_results) < page_size and backlog_more is not True
            if exhausted_known_total or exhausted_short_page:
                backlog_cursor = None
                break
            if next_cursor is not None and next_cursor != backlog_cursor:
                backlog_cursor = next_cursor
                continue
            # A full page without a usable next cursor is incomplete. Preserve
            # the previous cursor instead of falsely declaring coverage.
            break

        next_backlog = backlog_cursor if backlog is not None else None
        first_needs_continuation = (
            first_cursor is not None
            and (
                (len(first) >= page_size and total is None)
                or (total is not None and total > len(first))
                or first_more is True
            )
        )
        if backlog is None and first_needs_continuation and (previous is None or overlap == 0):
            next_backlog = first_cursor
            backlog_seen = len(first)
            provider_truncated = first_more is True
        elif backlog is None and overlap > 0:
            backlog_seen = len(first)
            provider_truncated = first_more is True
        complete = next_backlog is None and not provider_truncated and (
            overlap > 0
            or (
                previous is None
                and not first_needs_continuation
                and (total is None or total <= len(first))
                and first_more is not True
            )
        )
        newest_sort = _sort_token(first[0].get("sort")) if first else (
            _sort_token(previous.get("newestSort")) if previous else None
        )
        previous_recent = cast(list[str], previous.get("recentIds", [])) if previous else []
        recent_ids = list(dict.fromkeys([*first_ids, *previous_recent]))[:MAXIMUM_RECENT_IDS]
        unique = _unique_results(combined)
        previous_cursor = _sort_token(previous.get("nextSearchAfter")) if previous else None
        previous_seen = cast(int, previous.get("backlogResultsSeen", 0)) if previous else 0
        progressed = previous is None or next_backlog != previous_cursor or backlog_seen > previous_seen
        if progressed:
            last_progress_at = _timestamp(self.now)
        elif previous is not None:
            last_progress_at = cast(str, previous.get("lastProgressAt", previous["updatedAt"]))
        else:  # Defensive invariant: a new checkpoint always counts as progress.
            raise RuntimeError("URLScan checkpoint progress state is inconsistent.")
        queries[key] = {
            "queryHash": key,
            "queryFamily": query_family(query),
            "updatedAt": _timestamp(self.now),
            "lastProgressAt": last_progress_at,
            "complete": complete,
            "backlogPending": next_backlog is not None,
            "providerTruncated": provider_truncated,
            "nextSearchAfter": next_backlog,
            "newestSort": newest_sort,
            "providerTotal": total,
            "backlogResultsSeen": backlog_seen,
            "pagesFetched": pages_fetched,
            "resultsObserved": len(unique),
            "overlapResults": overlap,
            "recentIds": recent_ids,
        }
        self.state["generatedAt"] = _timestamp(self.now)
        self.dirty = True
        self._fit_capacity(protected_key=key)
        return unique

    def summary(self) -> dict[str, object]:
        """Return aggregate coverage state without query terms or identifiers."""

        queries = cast(dict[str, dict[str, Any]], self.state["queries"])
        rows = list(queries.values())
        backlogs = [row for row in rows if row["backlogPending"] is True]
        progress = sorted(cast(str, row["lastProgressAt"]) for row in backlogs)
        complete = sum(row["complete"] is True for row in rows)
        return {
            "queries": len(rows),
            "complete": complete,
            "partial": len(rows) - complete,
            "backlog": len(backlogs),
            "oldestBacklogProgressAt": progress[0] if progress else None,
        }

    def commit(self) -> Path:
        self.preflight()
        body = _state_body(self.state)
        target = _bounded_path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = _bounded_path(target)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            _bounded_path(target)
            os.replace(temporary, target)
        except Exception:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
        self.dirty = False
        return target
