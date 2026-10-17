import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/app/build_release_manifest.py"
spec = importlib.util.spec_from_file_location("release_manifest", SCRIPT)
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


def test_source_digest_includes_uncommitted_code_but_excludes_secrets_and_builds(tmp_path):
    source = tmp_path / "java_agent" / "src"
    source.mkdir(parents=True)
    (source / "App.java").write_text("class App {}", encoding="utf-8")
    (source / ".env.json").write_text("secret", encoding="utf-8")
    compiled = tmp_path / "java_agent" / "target"
    compiled.mkdir()
    (compiled / "build.json").write_text("output", encoding="utf-8")
    first = manifest.source_manifest(tmp_path)
    assert list(first) == ["java_agent/src/App.java"]
    (source / "App.java").write_text("class App { int changed; }", encoding="utf-8")
    assert manifest.source_manifest(tmp_path) != first
