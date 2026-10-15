"""Exercise the actual workflow's embedded Python validation command."""
import ast
import textwrap
from pathlib import Path

from hecavex_radar import brands, publication


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
    workspace = tmp_path / "trusted-source-workspace"
    registry_path = workspace / "data/brands-lt.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_bytes((repository / "data/brands-lt.json").read_bytes())
    expected_registry = brands.load_brand_registry(registry_path)
    source = tmp_path / "external-selected-data"
    source.mkdir()
    untrusted_registry = source / "data/brands-lt.json"
    untrusted_registry.parent.mkdir()
    untrusted_registry.write_text("exported data must never supply trusted policy", encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.setenv("RELEASE_SOURCE_ROOT", str(source))
    monkeypatch.chdir(repository)
    calls = []

    def load_registry(selected):
        assert selected == registry_path
        assert selected != untrusted_registry
        assert Path.cwd() == repository
        calls.append(("registry", selected))
        return expected_registry

    def validate(selected, *, validate_stix, trusted_registry, allow_legacy_observations):
        assert selected == source
        assert Path.cwd() == source
        assert validate_stix is True
        assert trusted_registry is expected_registry
        assert allow_legacy_observations is True
        calls.append(("publication", selected))

    monkeypatch.setattr(brands, "load_brand_registry", load_registry)
    monkeypatch.setattr(publication, "validate_publication", validate)
    exec(compile(script, "actual-release-workflow-validation", "exec"), {})  # noqa: S102 - trusted source workflow
    assert calls == [("registry", registry_path), ("publication", source)]
