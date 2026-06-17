from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.config import load_config
from rs_core.common.engineering_contracts import (
    select_test_paths_by_markers,
    validate_config_contracts,
    validate_engineering_allowlist_contract,
    validate_prd_contract,
    validate_route_registry_contract,
    validate_script_entrypoints,
    validate_test_markers,
)


def test_load_config_preserves_hash_inside_quoted_scalars(tmp_path: Path):
    config = tmp_path / "configs" / "route.yaml"
    config.parent.mkdir()
    config.write_text(
        'workflow_ref: "rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate"\n'
        'workflow_paths: ["rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate"]\n',
        encoding="utf-8",
    )

    loaded = load_config(config)

    assert loaded["workflow_ref"] == "rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate"
    assert loaded["workflow_paths"] == ["rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate"]


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


def test_route_registry_contract_accepts_current_routes(tmp_path: Path):
    registry = _write_valid_registry(tmp_path)

    assert validate_route_registry_contract(tmp_path, registry) == []


def test_route_registry_contract_rejects_invalid_status(tmp_path: Path):
    registry = _write_valid_registry(tmp_path, status="active")

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["route_registry_status"]


def test_route_registry_contract_rejects_missing_required_route(tmp_path: Path):
    registry = _write_valid_registry(tmp_path, omit_ranking=True)

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["route_registry_required_routes"]


def test_route_registry_contract_rejects_missing_online_service_route(tmp_path: Path):
    registry = _write_valid_registry(tmp_path, omit_online_service=True)

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["route_registry_required_routes"]


def test_route_registry_contract_rejects_missing_path(tmp_path: Path):
    registry = _write_valid_registry(tmp_path, extra_config_path="configs/recall/missing.yaml")

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["route_registry_path_exists"]


def test_route_registry_contract_rejects_absolute_path(tmp_path: Path):
    registry = _write_valid_registry(tmp_path, extra_config_path="D:/local/config.yaml")

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["route_registry_relative_path"]


def test_route_registry_contract_rejects_pool500_as_ranking_input(tmp_path: Path):
    registry = _write_valid_registry(tmp_path, ranking_pool500_path="outputs/recall/pool500/manifest.json")

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["pool500_not_ranking_input"]


def test_route_registry_contract_accepts_matching_online_service_artifact_path(tmp_path: Path):
    registry = _write_valid_registry(tmp_path)

    assert validate_route_registry_contract(tmp_path, registry) == []


def test_route_registry_contract_rejects_mismatched_online_service_artifact_path(tmp_path: Path):
    registry = _write_valid_registry(
        tmp_path,
        online_serving_candidates_path="outputs/recall/old_pool500/pool500_candidates.jsonl",
    )

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["online_serving_artifact_path_consistency"]


def test_route_registry_contract_rejects_dual_path_flagged_mismatch(tmp_path: Path):
    registry = _write_valid_registry(
        tmp_path,
        online_serving_candidates_path="outputs/recall/old_pool500/pool500_candidates.jsonl",
        online_service_route_overrides={"dual_path_governance_allowed": True},
    )

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["online_serving_dual_path_governance_forbidden"]


@pytest.mark.parametrize(
    "dual_path_field",
    ["dual_path_governance", "dual_path_governance_allowed", "explicit_dual_path_governance"],
)
def test_route_registry_contract_rejects_dual_path_flagged_matching_path(
    tmp_path: Path,
    dual_path_field: str,
):
    registry = _write_valid_registry(tmp_path, online_service_route_overrides={dual_path_field: True})

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["online_serving_dual_path_governance_forbidden"]


@pytest.mark.parametrize(
    ("online_service_route_overrides", "expected_checks"),
    [
        ({"required_output_paths": []}, ["online_serving_required_output_path_shape"]),
        (
            {"required_output_paths": ["outputs/recall/current/pool500_candidates.jsonl", "outputs/recall/other/pool500_candidates.jsonl"]},
            ["online_serving_required_output_path_shape"],
        ),
        ({"required_output_paths": [123]}, ["route_registry_path_value", "online_serving_required_output_path_shape"]),
        ({"config_paths": []}, ["online_serving_config_path_shape"]),
        (
            {"config_paths": ["configs/serving/online_service.yaml", "configs/serving/other.yaml"]},
            ["online_serving_config_path_shape"],
        ),
        ({"config_paths": [123]}, ["route_registry_path_value", "online_serving_config_path_shape"]),
    ],
)
def test_route_registry_contract_requires_single_online_service_artifact_and_config_path(
    tmp_path: Path,
    online_service_route_overrides: dict[str, object],
    expected_checks: list[str],
):
    registry = _write_valid_registry(tmp_path, online_service_route_overrides=online_service_route_overrides)

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == expected_checks


@pytest.mark.parametrize(
    "online_route_overrides",
    [
        {"pool500_candidates_path": None},
        {"pool500_candidates_path": 123},
        {"pool500_candidates_path": ""},
    ],
)
def test_route_registry_contract_requires_online_service_pool500_candidates_path(
    tmp_path: Path,
    online_route_overrides: dict[str, object],
):
    registry = _write_valid_registry(tmp_path, online_route_overrides=online_route_overrides)

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == ["online_serving_pool500_candidates_path_required"]


@pytest.mark.parametrize(
    ("pool500_route_overrides", "expected_check"),
    [
        ({"role": "ranking"}, "pool500_continuation_role"),
        ({"status": "current"}, "pool500_continuation_status"),
        ({"artifact_gate_schema_version": "full_data_pool500_artifact_gate_v4"}, "pool500_v5_artifact_gate_schema"),
        ({"artifact_gate_workflow": "rs_core/workflow/full_data_pool500_route_gate.py"}, "pool500_v5_artifact_gate_workflow"),
        ({"allowed_decisions": ["FULL_POOL500_READY", "STOP", "STOP"]}, "pool500_v5_allowed_decisions"),
        ({"candidate_generation_allowed": True}, "pool500_candidate_generation_not_allowed"),
        ({"ranking_input_replacement_allowed": True}, "pool500_ranking_input_replacement_not_allowed"),
        ({"workflow_paths": ["rs_core/workflow/full_data_pool500_route_gate.py"]}, "pool500_v5_workflow_path_registered"),
        (
            {"required_output_paths": ["outputs/recall/full_data_pool500_batch01_dry_run_verify_worker/manifest.json"]},
            "pool500_dry_run_manifest_not_required_output",
        ),
        ({"shadow_mode": "promotable_candidate"}, "pool500_shadow_mode"),
        ({"full_pool500_ready_semantics": "ranking_input_ready"}, "pool500_full_ready_semantics"),
        ({"public_display_forbidden_fields": ["trace_ref"]}, "pool500_public_display_forbidden_fields"),
    ],
)
def test_route_registry_contract_requires_pool500_v5_governance_fields(
    tmp_path: Path,
    pool500_route_overrides: dict[str, object],
    expected_check: str,
):
    registry = _write_valid_registry(tmp_path, pool500_route_overrides=pool500_route_overrides)

    violations = validate_route_registry_contract(tmp_path, registry)

    assert [violation.check for violation in violations] == [expected_check]


def test_prd_contract_requires_pool500_story(tmp_path: Path):
    prd = tmp_path / "prd.json"
    prd.write_text(json.dumps({"task": "legacy", "stories": []}), encoding="utf-8")

    violations = validate_prd_contract(tmp_path, prd)

    assert [violation.check for violation in violations] == ["prd_pool500_story_required"]


def test_prd_contract_rejects_pool500_story_without_shadow_boundaries(tmp_path: Path):
    prd = tmp_path / "prd.json"
    prd.write_text(
        json.dumps(
            {
                "task": "pool500",
                "stories": [
                    {
                        "id": "US-POOL500",
                        "title": "pool500 promotion",
                        "acceptanceCriteria": ["pool500 replaces current ranking route"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    violations = validate_prd_contract(tmp_path, prd)

    assert "prd_pool500_read_only_shadow" in [violation.check for violation in violations]
    assert "prd_pool500_no_candidate_generation" in [violation.check for violation in violations]
    assert "prd_pool500_no_ranking_replacement" in [violation.check for violation in violations]
    assert "prd_pool500_full_ready_semantics" in [violation.check for violation in violations]
    assert "prd_pool500_public_display_forbidden_fields" in [violation.check for violation in violations]


def test_prd_contract_accepts_pool500_shadow_story(tmp_path: Path):
    prd = tmp_path / "prd.json"
    prd.write_text(
        json.dumps(
            {
                "task": "pool500 shadow closure",
                "stories": [
                    {
                        "id": "US-POOL500",
                        "title": "pool500 read-only shadow evidence",
                        "acceptanceCriteria": [
                            "pool500 is read-only shadow evidence with no candidate generation",
                            "pool500 has no current_ranking_route replacement",
                            "FULL_POOL500_READY is recall artifact readiness only",
                            "internal evidence is separate from public display",
                            "public display rejects trace_ref, agent_runtime_trace, diagnostics_path, raw_export_trace_path, ranking_evidence_path",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert validate_prd_contract(tmp_path, prd) == []


def test_engineering_allowlist_contract_requires_lifecycle_fields(tmp_path: Path):
    allowlist = tmp_path / "configs" / "governance" / "engineering_contract_allowlist.yaml"
    allowlist.parent.mkdir(parents=True)
    allowlist.write_text(
        """
        schema_version: engineering_contract_allowlist_v1
        allowlist: [{"check": "workflow_phase_hardcoding", "path": "rs_core/workflow/demo.py", "reason": "Existing warning."}]
        """,
        encoding="utf-8",
    )

    violations = validate_engineering_allowlist_contract(tmp_path, allowlist)

    assert "engineering_allowlist_required_fields" in [violation.check for violation in violations]


def _write_valid_registry(
    tmp_path: Path,
    *,
    status: str = "current",
    omit_ranking: bool = False,
    omit_online_service: bool = False,
    extra_config_path: str | None = None,
    ranking_pool500_path: str | None = None,
    pool500_route_overrides: dict[str, object] | None = None,
    online_service_route_overrides: dict[str, object] | None = None,
    online_route_overrides: dict[str, object] | None = None,
    online_serving_candidates_path: str = "outputs/recall/current/pool500_candidates.jsonl",
) -> Path:
    paths = [
        "configs/recall/current.yaml",
        "configs/ranking/current.yaml",
        "configs/demo/current.yaml",
        "configs/serving/online_service.yaml",
        "rs_core/workflow/current.py",
        "rs_core/workflow/full_data_pool500_route_gate.py",
        "rs_lab/experiments/recall/current.py",
        "outputs/recall/current/manifest.json",
        "outputs/recall/current/pool500_candidates.jsonl",
        "dic/guides/CODEBASE_GOVERNANCE_GUIDE.md",
    ]
    if ranking_pool500_path:
        paths.append(ranking_pool500_path)
    if online_serving_candidates_path:
        paths.append(online_serving_candidates_path)
    if pool500_route_overrides and isinstance(pool500_route_overrides.get("required_output_paths"), list):
        paths.extend(path for path in pool500_route_overrides["required_output_paths"] if isinstance(path, str))
    if online_service_route_overrides:
        for field in ("config_paths", "required_output_paths"):
            override_paths = online_service_route_overrides.get(field)
            if isinstance(override_paths, list):
                paths.extend(path for path in override_paths if isinstance(path, str))
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    config_paths = ["configs/recall/current.yaml"]
    if extra_config_path:
        config_paths.append(extra_config_path)
    online_route = {"pool500_candidates_path": online_serving_candidates_path}
    if online_route_overrides:
        online_route.update(online_route_overrides)
    serving_config = tmp_path / "configs" / "serving" / "online_service.yaml"
    serving_config.write_text(
        json.dumps({"online_route": online_route}, ensure_ascii=False),
        encoding="utf-8",
    )
    registry = tmp_path / "configs" / "governance" / "current_route_registry.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    routes = {
        "current_recall_route": {
            "role": "recall",
            "status": status,
            "authority_refs": ["dic/guides/CODEBASE_GOVERNANCE_GUIDE.md"],
            "config_paths": config_paths,
            "workflow_paths": ["rs_core/workflow/current.py"],
            "script_paths": ["rs_lab/experiments/recall/current.py"],
            "required_output_paths": ["outputs/recall/current/manifest.json"],
            "promotion_gate_ref": "dic/guides/CODEBASE_GOVERNANCE_GUIDE.md#recall-route-promotion",
            "notes": "recall route",
        },
        "current_agent_demo_route": {
            "role": "agent_demo",
            "status": "provisional_current",
            "authority_refs": ["dic/guides/CODEBASE_GOVERNANCE_GUIDE.md"],
            "config_paths": ["configs/demo/current.yaml"],
            "workflow_paths": ["rs_core/workflow/current.py"],
            "script_paths": [],
            "required_output_paths": [],
            "promotion_gate_ref": "dic/guides/CODEBASE_GOVERNANCE_GUIDE.md#agent-demo-route-promotion",
            "notes": "demo route",
        },
        "pool500_recall_continuation_route": {
            "role": "recall",
            "status": "continuation_only",
            "authority_refs": ["dic/guides/CODEBASE_GOVERNANCE_GUIDE.md"],
            "config_paths": ["configs/recall/current.yaml"],
            "workflow_paths": [
                "rs_core/workflow/current.py",
                "rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate",
            ],
            "script_paths": [],
            "required_output_paths": ["outputs/recall/current/manifest.json"],
            "promotion_gate_ref": "dic/guides/CODEBASE_GOVERNANCE_GUIDE.md#recall-route-promotion",
            "artifact_gate_schema_version": "full_data_pool500_artifact_gate_v5",
            "artifact_gate_workflow": "rs_core/workflow/full_data_pool500_route_gate.py#full_data_pool500_artifact_gate",
            "allowed_decisions": ["FULL_POOL500_READY", "DIAGNOSTIC_ONLY_PARTIAL", "STOP"],
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "shadow_mode": "read_only_shadow_evidence",
            "full_pool500_ready_semantics": "recall_artifact_readiness_only",
            "public_display_forbidden_fields": [
                "agent_runtime_trace",
                "diagnostics_path",
                "ranking_evidence_path",
                "raw_export_trace_path",
                "trace_ref",
            ],
            "notes": "pool500 recall only",
        },
    }
    if not omit_online_service:
        routes["current_online_service_route"] = {
            "role": "online_serving",
            "status": "provisional_current",
            "authority_refs": ["dic/guides/CODEBASE_GOVERNANCE_GUIDE.md"],
            "config_paths": ["configs/serving/online_service.yaml"],
            "workflow_paths": ["rs_core/workflow/current.py"],
            "script_paths": [],
            "required_output_paths": ["outputs/recall/current/pool500_candidates.jsonl"],
            "promotion_gate_ref": "dic/guides/CODEBASE_GOVERNANCE_GUIDE.md#agent-demo-route-promotion",
            "candidate_generation_allowed": True,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "promotion_allowed": False,
            "full_pool500_ready_semantics": "recall_artifact_readiness_only",
            "notes": "online route",
        }
    if pool500_route_overrides:
        routes["pool500_recall_continuation_route"].update(pool500_route_overrides)
    if online_service_route_overrides:
        routes["current_online_service_route"].update(online_service_route_overrides)
    if not omit_ranking:
        routes["current_ranking_route"] = {
            "role": "ranking",
            "status": "current",
            "authority_refs": ["dic/guides/CODEBASE_GOVERNANCE_GUIDE.md"],
            "config_paths": ["configs/ranking/current.yaml"],
            "workflow_paths": ["rs_core/workflow/current.py"],
            "script_paths": [],
            "required_output_paths": ["outputs/recall/pool500/manifest.json"] if ranking_pool500_path else [],
            "promotion_gate_ref": "dic/guides/CODEBASE_GOVERNANCE_GUIDE.md#ranking-route-promotion",
            "notes": "ranking route",
        }
    registry.write_text(
        json.dumps({"schema_version": "current_route_registry_v1", "routes": routes}, ensure_ascii=False),
        encoding="utf-8",
    )
    return registry
