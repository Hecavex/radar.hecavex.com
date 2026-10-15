"""Publication clocks come from successful release receipts, not source firstSeen."""

import importlib
import importlib.util
import json

import pytest


def receipts():
    name = "hecavex_radar.publication_receipts"
    assert importlib.util.find_spec(name) is not None, "actual publication receipt writer is missing"
    return importlib.import_module(name)


def test_receipt_records_only_demonstrably_new_hostnames_and_is_idempotent(tmp_path):
    rows = [
        {"id": "a" * 20, "firstRecordedAt": None, "firstPublishedAt": None},
        {"id": "b" * 20, "firstRecordedAt": "2026-10-15T10:00:00.000Z", "firstPublishedAt": None},
    ]
    kwargs = {
        "source_revision": "1" * 40, "data_revision": "2" * 40, "hostnames_sha256": "3" * 64,
        "published_at": "2026-10-15T12:00:00.000Z",
    }
    receipts().record_publication_receipt(tmp_path, rows, **kwargs)
    before = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes()) for p in tmp_path.rglob("*.json"))
    receipts().record_publication_receipt(tmp_path, rows, **kwargs)
    after = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes()) for p in tmp_path.rglob("*.json"))
    assert before == after
    clocks, activation = receipts().read_publication_clocks(tmp_path, as_of="2026-10-15T13:00:00.000Z")
    assert clocks == {"b" * 20: "2026-10-15T12:00:00.000Z"}
    assert activation == "2026-10-15T12:00:00.000Z"


def test_future_receipts_cannot_backdate_an_earlier_publication(tmp_path):
    receipts().record_publication_receipt(
        tmp_path, [{"id": "b" * 20, "firstRecordedAt": "2026-10-15T10:00:00.000Z", "firstPublishedAt": None}],
        source_revision="1" * 40, data_revision="2" * 40, hostnames_sha256="3" * 64,
        published_at="2026-10-15T12:00:00.000Z",
    )
    clocks, activation = receipts().read_publication_clocks(tmp_path, as_of="2026-10-15T11:00:00.000Z")
    assert clocks == {} and activation is None


def test_receipt_with_mutated_digest_or_unsafe_identity_is_rejected(tmp_path):
    receipts().record_publication_receipt(
        tmp_path, [], source_revision="1" * 40, data_revision="2" * 40, hostnames_sha256="3" * 64,
        published_at="2026-10-15T12:00:00.000Z",
    )
    path = tmp_path / "data/history/publications/activation.json"
    value = json.loads(path.read_bytes())
    value["publishedAt"] = "not-a-timestamp"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        receipts().read_publication_clocks(tmp_path, as_of="2026-10-15T13:00:00.000Z")


def test_cli_rejects_backdated_artifact_before_writing_activation_or_receipts(tmp_path):
    from hecavex_radar.observation_publication import write_observed_hostnames
    from tests.test_observation_publication import metadata

    coverage, policies, grouping = metadata()
    publication = tmp_path / "publication"
    destination = tmp_path / "receipts"
    write_observed_hostnames(publication, [], as_of="2026-10-15T12:00:00.000Z", coverage=coverage,
                             policy_versions=policies, grouping=grouping)
    with pytest.raises(ValueError, match="predates"):
        receipts().main(["--repository", str(destination), "--publication-root", str(publication),
                         "--source-revision", "a" * 40, "--data-revision", "b" * 40,
                         "--published-at", "2026-10-14T12:00:00.000Z"])
    assert not destination.exists()


@pytest.mark.parametrize("budget", ["MAXIMUM_TOTAL_BYTES", "MAXIMUM_MONTH_BYTES"])
def test_receipt_capacity_is_preflighted_before_activation_or_month_writes(tmp_path, monkeypatch, budget):
    monkeypatch.setattr(receipts(), budget, 1)
    with pytest.raises(ValueError, match="capacity|budget"):
        receipts().record_publication_receipt(
            tmp_path, [{"id": "b" * 20, "firstRecordedAt": "2026-10-15T10:00:00.000Z", "firstPublishedAt": None}],
            source_revision="1" * 40, data_revision="2" * 40, hostnames_sha256="3" * 64,
            published_at="2026-10-15T12:00:00.000Z",
        )
    assert not (tmp_path / "data").exists()


def test_receipt_cannot_precede_existing_capture_activation(tmp_path):
    receipts().record_publication_receipt(tmp_path, [], source_revision="1" * 40, data_revision="2" * 40,
                                         hostnames_sha256="3" * 64, published_at="2026-10-15T12:00:00.000Z")
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*.json")}
    with pytest.raises(ValueError, match="activation"):
        receipts().record_publication_receipt(
            tmp_path, [{"id": "b" * 20, "firstRecordedAt": "2026-10-14T10:00:00.000Z", "firstPublishedAt": None}],
            source_revision="1" * 40, data_revision="2" * 40, hostnames_sha256="3" * 64,
            published_at="2026-10-14T12:00:00.000Z",
        )
    assert before == {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*.json")}


def complete_cohort(tmp_path):
    from hecavex_radar.observation_publication import write_observed_hostnames, write_period_artifact
    from hecavex_radar.observation_store import grouping_metadata
    from tests.test_observation_publication import metadata, record

    coverage, policies, _ = metadata()
    write_observed_hostnames(tmp_path, [record()], as_of="2026-10-15T12:00:00.000Z", coverage=coverage,
                             policy_versions=policies, grouping=grouping_metadata())
    write_period_artifact(tmp_path)
    return {"/" + path.relative_to(tmp_path / "public").as_posix(): path.read_bytes()
            for path in (tmp_path / "public/data").rglob("*.json")}


@pytest.mark.parametrize("mismatch", ["index", "part", "metrics"])
def test_served_cohort_must_match_every_verified_byte_before_receipt_write(tmp_path, mismatch):
    local = tmp_path / "publication"
    files = complete_cohort(local)
    target = {"index": "/data/observed-hostnames-v1.json", "metrics": "/data/period-metrics-v1.json"}.get(mismatch)
    target = target or next(path for path in files if "/observed-hostnames-parts/" in path)
    fetched = []

    def fetch(url, maximum_bytes, timeout):
        assert maximum_bytes <= 256 * 1024 and 0 < timeout <= 5
        path = url.removeprefix("https://radar.example")
        fetched.append(path)
        return files[path] + (b" " if path == target else b"")

    with pytest.raises(ValueError, match="served|Served"):
        receipts().verify_served_cohort(local, "https://radar.example", fetch=fetch)
    assert fetched and not (tmp_path / "data/history/publications").exists()


def test_served_cohort_verifies_complete_index_parts_and_metrics_with_injected_fetch(tmp_path):
    files = complete_cohort(tmp_path)
    fetched = []

    def fetch(url, maximum_bytes, timeout):
        assert maximum_bytes <= 256 * 1024 and 0 < timeout <= 5
        path = url.removeprefix("https://radar.example")
        fetched.append(path)
        return files[path]

    receipts().verify_served_cohort(tmp_path, "https://radar.example", fetch=fetch)
    assert set(fetched) == set(files)


def test_cli_mixed_served_metrics_cannot_create_capture_activation(tmp_path, monkeypatch):
    publication = tmp_path / "publication"
    destination = tmp_path / "destination"
    files = complete_cohort(publication)

    def fetch(url, maximum_bytes, timeout):
        path = url.removeprefix("https://radar.example")
        return files[path] + (b" " if path == "/data/period-metrics-v1.json" else b"")

    monkeypatch.setattr(receipts(), "_fetch_served", fetch)
    with pytest.raises(ValueError, match="Served publication cohort"):
        receipts().main(["--repository", str(destination), "--publication-root", str(publication),
                         "--source-revision", "a" * 40, "--data-revision", "b" * 40,
                         "--published-at", "2026-10-15T13:00:00.000Z", "--live-base-url", "https://radar.example"])
    assert not destination.exists()
