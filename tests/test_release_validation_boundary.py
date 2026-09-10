"""Exercise the actual workflow's embedded Python validation command."""
import ast
import textwrap
from pathlib import Path

from hecavex_radar import publication


def test_release_validation_imports_trusted_code_then_anchors_external_data(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    workflow = (repository / ".github/workflows/release-weekly-dataset.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Validate selected publication data with current tooling", 1)[1]
    script = textwrap.dedent(step.split("python - <<'PY'\n", 1)[1].split("\n          PY\n", 1)[0])
    tree = ast.parse(script)
    imported = next(node.lineno for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module == "hecavex_radar.publication")
    changed = next(node.lineno for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "chdir")
    assert imported < changed
    source = tmp_path / "external-selected-data"
    source.mkdir()
    monkeypatch.setenv("RELEASE_SOURCE_ROOT", str(source))
    monkeypatch.chdir(repository)
    calls = []

    def validate(selected, *, validate_stix):
        assert selected == source
        assert Path.cwd() == source
        assert validate_stix is True
        calls.append(selected)

    monkeypatch.setattr(publication, "validate_publication", validate)
    exec(compile(script, "actual-release-workflow-validation", "exec"), {})  # noqa: S102 - trusted source workflow
    assert calls == [source]
