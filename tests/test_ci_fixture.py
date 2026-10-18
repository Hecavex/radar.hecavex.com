import subprocess
from pathlib import Path

import pytest

from tests.ci_fixture import require_ci_fixture


def _repository(tmp_path: Path) -> Path:
    for relative in ("data/x.json", "public/data/radar.json"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text("{}\n", encoding="utf-8")
    for command in (["init", "-q"], ["add", "."],
                    ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "frozen"]):
        subprocess.run(["git", *command], cwd=tmp_path, check=True, capture_output=True)  # noqa: S603, S607
    return tmp_path


def test_unmodified_frozen_copy_skips_locally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception, match="materialize-fixture"):
        require_ci_fixture(_repository(tmp_path))


def test_materialized_fixture_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    repository = _repository(tmp_path)
    (repository / "public/data/radar.json").write_text('{"fixture": true}\n', encoding="utf-8")
    require_ci_fixture(repository)


def test_ci_never_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    require_ci_fixture(_repository(tmp_path))
