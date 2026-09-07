from __future__ import annotations

import pytest

from hecavex_radar.daily_trends import build_daily_trends
from hecavex_radar.event_feeds import _classify_events
from hecavex_radar.models import RawSignal
from hecavex_radar.normalize import prepare_signal
from hecavex_radar.safety import safe_reference_url, safe_screenshot_url


@pytest.mark.parametrize("port", ["notaport", "65536", "-1", "443"])
def test_invalid_optional_ports_preserve_valid_signal(port: str) -> None:
    identifier = "01234567-89ab-cdef-0123-456789abcdef"
    screenshot = f"https://urlscan.io:{port}/screenshots/{identifier}.png"
    reference = f"https://urlscan.io:{port}/result/{identifier}/"
    assert safe_screenshot_url(screenshot) is None
    assert safe_reference_url(reference) is None
    result = prepare_signal(RawSignal(
        url="https://example.test/", source="HECAVEX",
        screenshot_url=screenshot, reference_url=reference,
    ), "2026-09-07T12:00:00.000Z")
    assert result is not None
    assert result["screenshotUrl"] is None
    assert result["referenceUrl"] is None
    assert result["domain"] == "example[.]test"
    assert safe_screenshot_url(screenshot.replace(f":{port}", "")) is not None
    assert safe_reference_url(reference.replace(f":{port}", "")) is not None


def test_trends_reobservations_match_feed_across_midnight_and_unknown_provenance() -> None:
    def event(number: int, signal_id: str, stamp: str, publication: bool = False) -> dict:
        return {
            "eventId": f"{number:032x}", "signalId": signal_id,
            "eventType": "status-transition" if publication else "observation",
            "observedAt": stamp, "previousStatus": None, "status": "suspected",
            "reasonCodes": ["first-publication"] if publication else [],
            "domain": "example[.]test", "brand": "Example", "sources": ["URLScan"],
        }

    first, unknown, fallback = "a" * 20, "b" * 20, "c" * 20
    events = [
        event(1, first, "2026-09-06T23:58:00.000Z", True),
        event(2, first, "2026-09-06T23:58:00.000Z"),
        event(3, first, "2026-09-06T23:59:00.000Z"),
        event(4, first, "2026-09-07T00:00:00.000Z"),
        event(5, unknown, "2026-09-07T01:00:00.000Z"),
        event(6, fallback, "2026-09-07T02:00:00.000Z"),
    ]
    first_seen = {fallback: "2026-09-05T00:00:00.000Z"}
    trends = build_daily_trends(events, [], [
        {"id": fallback, "firstSeen": first_seen[fallback]},
    ], {}, "2026-09-07T12:00:00.000Z", days=2)
    classified = _classify_events(events, first_seen)
    assert [row["discovery"]["reobservations"] for row in trends["series"]] == [1, 2]
    assert sum(row["discovery"]["reobservations"] for row in trends["series"]) == sum(
        item["type"] == "reobservation" for item in classified
    )
    assert trends["countingMethodVersion"] == 2
