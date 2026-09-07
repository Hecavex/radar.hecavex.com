from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAXIMUM_JSON_BYTES = 2 * 1024 * 1024
MAXIMUM_HTML_BYTES = 512 * 1024
DEFAULT_BASE_URL = "https://radar.hecavex.com"
DEFAULT_GRACE_MINUTES = 30
DEFAULT_MAXIMUM_SYNC_AGE_MINUTES = 180
ROUTES = (
    ("/", 200, "en", "https://radar.hecavex.com/"),
    ("/lt/", 200, "lt", "https://radar.hecavex.com/lt/"),
    ("/methodology/", 200, "en", "https://radar.hecavex.com/methodology/"),
    ("/lt/metodologija/", 200, "lt", "https://radar.hecavex.com/lt/metodologija/"),
    ("/trends/", 200, "en", "https://radar.hecavex.com/trends/"),
    ("/lt/tendencijos/", 200, "lt", "https://radar.hecavex.com/lt/tendencijos/"),
    ("/radar-live-smoke-not-found", 404, "en", None),
)
ATOMIC_PAIR_FINDING = "The live snapshot and feed manifest do not share one atomic synchronization timestamp."
LIVE_DIGEST_FINDING = "The live radar snapshot digest does not match the live feed manifest."
LIVE_LENGTH_FINDING = "The live radar snapshot byte length does not match the live feed manifest."
CHECKED_IN_DIGEST_FINDING = (
    "The live radar artifact digest differs from the checked-in artifact at the same synchronization timestamp."
)
CHECKED_IN_LENGTH_FINDING = (
    "The live radar artifact byte length differs from the checked-in artifact at the same synchronization timestamp."
)
TRANSITIONAL_PAIR_FINDINGS = frozenset(
    {
        ATOMIC_PAIR_FINDING,
        LIVE_DIGEST_FINDING,
        LIVE_LENGTH_FINDING,
        CHECKED_IN_DIGEST_FINDING,
        CHECKED_IN_LENGTH_FINDING,
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(UTC)
    except ValueError:
        return None
    canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object.")
    return value


def _radar_artifact(manifest: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    return next(
        (
            value
            for value in artifacts
            if isinstance(value, dict) and value.get("path") == "/data/radar.json"
        ),
        None,
    )


def _needs_pair_retry(findings: list[str]) -> bool:
    return any(finding in TRANSITIONAL_PAIR_FINDINGS for finding in findings)


def evaluate_publication(
    expected_manifest: dict[str, Any],
    live_manifest: dict[str, Any],
    live_snapshot_payload: bytes,
    *,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    now: datetime | None = None,
    maximum_sync_age_minutes: int = DEFAULT_MAXIMUM_SYNC_AGE_MINUTES,
) -> list[str]:
    findings: list[str] = []
    expected_generated = _timestamp(expected_manifest.get("generatedAt"))
    live_generated = _timestamp(live_manifest.get("generatedAt"))
    if now is not None and live_generated is not None:
        age = now.astimezone(UTC) - live_generated
        if age > timedelta(minutes=maximum_sync_age_minutes):
            findings.append(
                "The live synchronization is stale in absolute time, even if it matches the repository: "
                f"age={int(age.total_seconds() // 60)} minutes, maximum={maximum_sync_age_minutes} minutes."
            )
        if age < -timedelta(minutes=5):
            findings.append("The live synchronization timestamp is unexpectedly in the future.")
    if expected_generated is None:
        findings.append("The checked-in feed manifest has an invalid generatedAt timestamp.")
    if live_generated is None:
        findings.append("The live feed manifest has an invalid generatedAt timestamp.")
    elif expected_generated is not None and expected_generated - live_generated > timedelta(minutes=grace_minutes):
        findings.append(
            "The live publication is older than the checked-in manifest beyond the propagation grace period: "
            f"live={live_manifest.get('generatedAt')}, expected={expected_manifest.get('generatedAt')}."
        )

    live_snapshot = _json_object(live_snapshot_payload, "Live radar snapshot")
    if live_snapshot.get("schemaVersion") != 2 or live_snapshot.get("dataset") != "live":
        findings.append("The live radar snapshot has an unsupported contract.")
    # ``generatedAt`` records the most recent material data change. A healthy
    # heartbeat-only synchronization advances ``lastSuccessfulSyncAt`` while
    # deliberately preserving that older data timestamp. The manifest is
    # atomic with the successful publication, not necessarily with a change to
    # the candidate set.
    if live_snapshot.get("lastSuccessfulSyncAt") != live_manifest.get("generatedAt"):
        findings.append(ATOMIC_PAIR_FINDING)

    live_radar_artifact = _radar_artifact(live_manifest)
    if live_radar_artifact is None:
        findings.append("The live feed manifest does not inventory /data/radar.json.")
    else:
        digest = hashlib.sha256(live_snapshot_payload).hexdigest()
        if live_radar_artifact.get("sha256") != digest:
            findings.append(LIVE_DIGEST_FINDING)
        if live_radar_artifact.get("bytes") != len(live_snapshot_payload):
            findings.append(LIVE_LENGTH_FINDING)
    if expected_generated is not None and expected_generated == live_generated:
        expected_radar_artifact = _radar_artifact(expected_manifest)
        if expected_radar_artifact is None:
            findings.append("The checked-in feed manifest does not inventory /data/radar.json.")
        elif live_radar_artifact is not None:
            if expected_radar_artifact.get("sha256") != live_radar_artifact.get("sha256"):
                findings.append(CHECKED_IN_DIGEST_FINDING)
            if expected_radar_artifact.get("bytes") != live_radar_artifact.get("bytes"):
                findings.append(CHECKED_IN_LENGTH_FINDING)
    return findings


def _fetch(base_url: str, path: str, maximum_bytes: int, nonce: str) -> tuple[int, bytes]:
    target = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    separator = "&" if "?" in target else "?"
    request = urllib.request.Request(  # noqa: S310 - fixed operator-controlled HTTPS origin
        f"{target}{separator}radar_smoke={urllib.parse.quote(nonce)}",
        headers={
            "Accept": "application/json,text/html;q=0.8",
            "Cache-Control": "no-cache",
            "User-Agent": "HECAVEX-Radar-Live-Smoke/1.0",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=20)  # noqa: S310 - fixed operator-controlled HTTPS origin
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > maximum_bytes:
                    raise ValueError(f"Live response exceeded the {maximum_bytes}-byte declared limit.")
            except ValueError as error:
                raise ValueError("Live response returned an invalid or oversized Content-Length header.") from error
        payload = response.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise ValueError(f"Live response exceeded the {maximum_bytes}-byte read limit.")
        return response.status, payload


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def matches_release_identity(release: dict[str, object], source: str, data: str | None = None) -> bool:
    """Retain legacy source-only checks; dual-revision deployment checks fail closed."""
    if (release.get("schemaVersion") != 1 or release.get("repository") != "Hecavex/radar.hecavex.com"
            or release.get("revision") != source):
        return False
    if "sourceRevision" in release and release["sourceRevision"] != source:
        return False
    return data is None or (release.get("sourceRevision") == source and release.get("dataRevision") == data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the deployed Radar publication against selected data blobs.")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--grace-minutes", type=int, default=DEFAULT_GRACE_MINUTES)
    parser.add_argument("--expected-revision", help="Require this exact deployed build commit after Pages rollout.")
    parser.add_argument("--expected-data-revision", help="Require this exact selected data commit after Pages rollout.")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--github-output", type=Path)
    options = parser.parse_args(argv)
    if not options.base_url.startswith("https://") or not 5 <= options.grace_minutes <= 180:
        print("Live smoke check requires an HTTPS base URL and a 5-180 minute grace period.", file=sys.stderr)
        return 2
    if options.expected_revision and not re.fullmatch(r"[a-f0-9]{40}", options.expected_revision):
        print("Expected release revision must be a full Git commit ID.", file=sys.stderr)
        return 2
    if options.expected_data_revision and (
        not options.expected_revision or not re.fullmatch(r"[a-f0-9]{40}", options.expected_data_revision)
    ):
        print("Expected data revision requires full source and data commit IDs.", file=sys.stderr)
        return 2

    expected_path = options.repository.resolve() / "public" / "data" / "feed-manifest.json"
    expected_payload = expected_path.read_bytes()
    if len(expected_payload) > MAXIMUM_JSON_BYTES:
        print("Checked-in feed manifest exceeded the bounded read limit.", file=sys.stderr)
        return 2
    expected_manifest = _json_object(expected_payload, "Checked-in feed manifest")
    nonce = os.environ.get("GITHUB_RUN_ID", "local")
    findings: list[str] = []
    route_results: list[dict[str, object]] = []
    try:
        if options.expected_revision:
            status, body = _fetch(options.base_url, "/.well-known/hecavex-release.json", 4096, nonce)
            release = _json_object(body, "Live release identity")
            if status != 200 or not matches_release_identity(
                release, options.expected_revision, options.expected_data_revision,
            ):
                findings.append("The live release identity does not match the deployed build revision.")
        for attempt in range(2):
            publication_nonce = f"{nonce}-publication-{attempt + 1}"
            manifest_status, live_manifest_payload = _fetch(
                options.base_url, "/data/feed-manifest.json", MAXIMUM_JSON_BYTES, publication_nonce
            )
            snapshot_status, live_snapshot_payload = _fetch(
                options.base_url, "/data/radar.json", MAXIMUM_JSON_BYTES, publication_nonce
            )
            publication_findings: list[str] = []
            if manifest_status != 200:
                publication_findings.append(f"Live feed manifest returned HTTP {manifest_status}, expected 200.")
            if snapshot_status != 200:
                publication_findings.append(f"Live radar snapshot returned HTTP {snapshot_status}, expected 200.")
            if manifest_status == 200 and snapshot_status == 200:
                live_manifest = _json_object(live_manifest_payload, "Live feed manifest")
                publication_findings.extend(
                    evaluate_publication(
                        expected_manifest,
                        live_manifest,
                        live_snapshot_payload,
                        grace_minutes=options.grace_minutes,
                        now=_now(),
                    )
                )
            if attempt == 0 and _needs_pair_retry(publication_findings):
                continue
            findings.extend(publication_findings)
            break
        for route, expected_status, expected_language, expected_canonical in ROUTES:
            status, payload = _fetch(options.base_url, route, MAXIMUM_HTML_BYTES, nonce)
            route_results.append({"path": route, "status": status, "expectedStatus": expected_status})
            if status != expected_status:
                findings.append(f"Live route {route} returned HTTP {status}, expected {expected_status}.")
            language_marker = f'<html lang="{expected_language}"'.encode()
            if language_marker not in payload:
                findings.append(
                    f"Live route {route} did not expose the expected {expected_language} document language."
                )
            if expected_canonical is not None:
                canonical_marker = f'rel="canonical" href="{expected_canonical}"'.encode()
                if canonical_marker not in payload:
                    findings.append(f"Live route {route} did not expose its exact localized canonical URL.")
                if b'id="main-content"' not in payload:
                    findings.append(f"Live route {route} did not contain the expected primary content landmark.")
            if route == "/radar-live-smoke-not-found" and b"This route has no signal." not in payload:
                findings.append("The live custom 404 response did not contain the expected safe page marker.")
    except (OSError, TimeoutError, ValueError, urllib.error.URLError) as error:
        findings.append(f"Live publication request failed safely: {error}")

    checked_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    report: dict[str, object] = {
        "schemaVersion": 1,
        "dataset": "radar-live-smoke",
        "checkedAt": checked_at,
        "baseUrl": options.base_url,
        "healthy": not findings,
        "findings": findings,
        "routes": route_results,
    }
    if options.json_output is not None:
        _write_report(options.json_output, report)
    markdown = [
        "# Radar live publication health",
        "",
        f"Checked: `{checked_at}`",
        f"Status: **{'healthy' if not findings else 'degraded'}**",
        "",
    ]
    if findings:
        markdown.extend(["## Findings", "", *(f"- {finding}" for finding in findings), ""])
    else:
        markdown.extend(["The live publication matches or is newer than the checked-in atomic snapshot.", ""])
    if options.markdown_output is not None:
        options.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        options.markdown_output.write_text("\n".join(markdown), encoding="utf-8")
    if options.github_output is not None:
        with options.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"unhealthy={'true' if findings else 'false'}\n")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
