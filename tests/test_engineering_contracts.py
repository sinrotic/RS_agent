from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.engineering_contracts import select_test_paths_by_markers, validate_config_contracts, validate_script_entrypoints, validate_test_markers


def test_config_contract_rejects_tracked_tmp_config_and_personal_absolute_path(tmp_path: Path):
    config = tmp_path / "configs" / "_tmp_search.yaml"
    config.parent.mkdir()
    config.write_text('output_dir: "D:/Users/local/outputs"\ntop_k: 3\n', encoding="utf-8")

    violations = validate_config_contracts(tmp_path, [config])

    assert {violation.check for violation in violations} == {
        "temporary_config_not_tracked",
        "no_personal_absolute_paths",
    }


def test_config_contract_accepts_relative_project_paths(tmp_path: Path):
    config = tmp_path / "configs" / "phase_1_99_demo.yaml"
    config.parent.mkdir()
    config.write_text("clean_dir: data/processed/clean\noutput_dir: outputs/hybrid_demo/demo\n", encoding="utf-8")

    assert validate_config_contracts(tmp_path, [config]) == []


def test_config_contract_reports_loader_errors(tmp_path: Path):
    config = tmp_path / "configs" / "phase_1_99_bad.yaml"
    config.parent.mkdir()
    config.write_text("items:\n  - a\n", encoding="utf-8")

    violations = validate_config_contracts(tmp_path, [config])

    assert [violation.check for violation in violations] == ["config_loadable"]


def test_script_entrypoint_contract_requires_main_guard(tmp_path: Path):
    script = tmp_path / "scripts" / "run_demo.py"
    script.parent.mkdir()
    script.write_text("print('runs at import time')\n", encoding="utf-8")

    violations = validate_script_entrypoints(tmp_path, [script])

    assert [violation.check for violation in violations] == ["script_main_guard"]


def test_script_entrypoint_contract_accepts_guarded_script(tmp_path: Path):
    script = tmp_path / "scripts" / "run_demo.py"
    script.parent.mkdir()
    script.write_text("def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")

    assert validate_script_entrypoints(tmp_path, [script]) == []


def test_test_marker_contract_requires_file_level_marker(tmp_path: Path):
    test_file = tmp_path / "tests" / "test_demo.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_demo():\n    pass\n", encoding="utf-8")

    violations = validate_test_markers(tmp_path, [test_file])

    assert [violation.check for violation in violations] == ["test_file_marker_required"]


def test_test_marker_contract_accepts_registered_marker_lists(tmp_path: Path):
    test_file = tmp_path / "tests" / "test_demo.py"
    test_file.parent.mkdir()
    test_file.write_text(
        "import pytest\n\npytestmark = [pytest.mark.unit, pytest.mark.serving]\n\ndef test_demo():\n    pass\n",
        encoding="utf-8",
    )

    assert validate_test_markers(tmp_path, [test_file]) == []


def test_test_marker_contract_rejects_unregistered_marker(tmp_path: Path):
    test_file = tmp_path / "tests" / "test_demo.py"
    test_file.parent.mkdir()
    test_file.write_text("import pytest\n\npytestmark = pytest.mark.custom\n", encoding="utf-8")

    violations = validate_test_markers(tmp_path, [test_file])

    assert [violation.check for violation in violations] == ["test_file_marker_registered"]


def test_select_test_paths_by_markers_uses_file_level_markers_without_importing(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    unit_test = tests_dir / "test_unit.py"
    experiment_test = tests_dir / "test_experiment.py"
    unit_test.write_text("import pytest\nraise RuntimeError('should not import')\npytestmark = pytest.mark.unit\n", encoding="utf-8")
    experiment_test.write_text("import pytest\npytestmark = pytest.mark.experiment\n", encoding="utf-8")

    selected = select_test_paths_by_markers(
        tmp_path,
        [unit_test, experiment_test],
        {"unit", "smoke"},
    )

    assert selected == ["tests/test_unit.py"]
