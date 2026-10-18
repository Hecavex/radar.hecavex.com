"""Exercise the weekly release workflow's validation command."""
import ast
import inspect
import textwrap
from pathlib import Path

from hecavex_radar import brands, publication, weekly_release


def test_release_validation_imports_trusted_code_then_anchors_external_data(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    workflow = (repository / ".github/workflows/release-weekly-dataset.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Validate selected publication data with current tooling", 1)[1]
    assert step.split("- name:", 1)[0].rstrip().endswith("run: python -m hecavex_radar.weekly_release validate")
    tree = ast.parse(textwrap.dedent(inspect.getsource(weekly_release.validate_release_source)))
    imported = next(node.lineno for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module == "hecavex_radar"
                    and {alias.name for alias in node.names} >= {"brands", "publication"})
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
    assert weekly_release.main(["validate"]) == 0
    assert calls == [("registry", registry_path), ("publication", source)]
