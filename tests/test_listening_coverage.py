from datetime import UTC, datetime, timedelta

import pytest

from hecavex_radar.daily_trends import build_daily_trends
from hecavex_radar.listening_coverage import coverage_bounds

START = datetime(2026, 9, 10, tzinfo=UTC)


def row(begin: float, end: float, listening: float) -> dict[str, object]:
    def stamp(seconds: float) -> str:
        return (START + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"collectorStartedAt": stamp(begin), "endedAt": stamp(end),
            "listeningSeconds": listening, "outcome": "healthy-empty"}


@pytest.mark.parametrize(("rows", "low", "high"), [
    ([row(0, 480, 480), row(0, 480, 480)], 480, 480),
    ([row(0, 480, 480), row(240, 720, 480)], 720, 720),
    ([row(0, 480, 480), row(480, 960, 480)], 960, 960),
    ([row(-240, 240, 480)], 240, 240),
    ([row(86160, 86640, 480)], 240, 240),
    ([row(-240, 240, 240)], 0, 240),
    ([row(0, 600, 480), row(0, 600, 480)], 480, 600),
    ([row(0, 600, 480)], 480, 480),
])
def test_bounds_do_not_invent_connections(rows, low, high):
    result = coverage_bounds(rows, START, START + timedelta(days=1))
    assert result["lowerSeconds"] == low
    assert result["upperSeconds"] == high


def test_missing_invalid_timing_is_unknown_not_precise():
    result = coverage_bounds([{"endedAt": "2026-09-10T01:00:00.000Z", "listeningSeconds": 480}],
                             START, START + timedelta(days=1))
    assert result["precision"] == "unknown"
    assert result["lowerSeconds"] == 0
    assert result["upperSeconds"] == 480


def test_daily_midnight_split_preserves_one_attempt_count():
    result = build_daily_trends([], [row(-240, 240, 480)], [], {},
                                "2026-09-10T12:00:00.000Z", days=2)
    days = result["series"]
    assert [day["collectorCoverage"]["listeningSeconds"] for day in days] == [240, 240]
    assert [day["collectorCoverage"]["recordedAttempts"] for day in days] == [0, 1]


def test_bounds_enclose_every_small_discrete_connection_arrangement():
    # Enumerate real connected seconds, then discard their locations exactly as
    # production telemetry does. Every possible union must remain in the bound.
    for left_mask in range(16):
        for right_mask in range(16):
            left = {second for second in range(4) if left_mask & (1 << second)}
            right = {second + 2 for second in range(4) if right_mask & (1 << second)}
            bounds = coverage_bounds([row(0, 4, len(left)), row(2, 6, len(right))],
                                     START + timedelta(seconds=1), START + timedelta(seconds=5))
            actual = len((left | right) & {1, 2, 3, 4})
            assert bounds["lowerSeconds"] <= actual <= bounds["upperSeconds"]


def test_midnight_end_preserves_worker_total_without_new_day_coverage():
    result = build_daily_trends([], [row(-480, 0, 480)], [], {},
                                "2026-09-10T12:00:00.000Z", days=2)
    coverage = [day["collectorCoverage"] for day in result["series"]]
    assert [day["recordedAttempts"] for day in coverage] == [0, 1]
    assert [day["listeningSeconds"] for day in coverage] == [480, 0]
    assert [day["coverageBounds"]["reportedWorkerSeconds"] for day in coverage] == [0, 480]
