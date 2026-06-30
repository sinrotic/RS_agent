from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.experiment

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative"
MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_GENERATION_FILE_NAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_required_artifacts_exist(manifest: dict[str, Any]) -> None:
    for path in manifest["required_artifacts"].values():
        assert Path(path).is_file(), path


def assert_candidate_generation_did_not_read_holdout(source_audit: dict[str, Any]) -> None:
    uses_holdout = source_audit.get(
        "candidate_generation_uses_holdout",
        source_audit.get("candidate_generation_uses_valid_test_holdout"),
    )
    assert uses_holdout is False
    generation_file_names = {
        Path(path).name for path in source_audit.get("candidate_generation_read_files", [])
    }
    assert generation_file_names.isdisjoint(FORBIDDEN_GENERATION_FILE_NAMES)
    if "forbidden_candidate_generation_inputs" in source_audit:
        forbidden_file_names = {
            Path(path).name for path in source_audit["forbidden_candidate_generation_inputs"]
        }
        assert forbidden_file_names == FORBIDDEN_GENERATION_FILE_NAMES


def test_all_method_stage_manifests_pass_and_require_project_venv() -> None:
    expected_statuses = {
        "custom_index": "PASS",
        "lightweight_cf_methods": "PASS",
        "sequence_session_methods": "EXECUTED_PASS_OBSERVATION_ONLY",
        "heavy_indexed_probes": "PASS",
        "final_gate": "PASS",
    }

    for stage, expected_status in expected_statuses.items():
        manifest = read_json(BASE_DIR / stage / "manifest.json")
        assert manifest["status"] == expected_status
        assert manifest["project_venv_required"] is True
        assert_required_artifacts_exist(manifest)


def test_source_audits_keep_candidate_generation_train_only() -> None:
    stage_names = [
        "custom_index",
        "lightweight_cf_methods",
        "sequence_session_methods",
        "heavy_indexed_probes",
    ]

    for stage_name in stage_names:
        source_audit = read_json(BASE_DIR / stage_name / "source_audit.json")
        assert source_audit["status"] == "PASS"
        assert_candidate_generation_did_not_read_holdout(source_audit)
        assert source_audit["no_10k_source"] is True
        assert source_audit["no_full_clean_copy"] is True

    final_source = read_json(BASE_DIR / "final_gate" / "source_audit.json")
    assert final_source["status"] == "PASS"
    assert final_source["candidate_generation_executed_in_final_gate"] is False
    assert final_source["ranking_executed_in_final_gate"] is False
    assert final_source["model_training_executed_in_final_gate"] is False
    assert final_source["evaluation_only_holdout_reads_upstream"]["lightweight_cf"]["contract"] == (
        "valid/test are read only after candidate generation for metrics"
    )


def test_pool500_does_not_replace_frozen_pool200_ranking_or_pool1000() -> None:
    custom_source = read_json(BASE_DIR / "custom_index" / "source_audit.json")
    lightweight_source = read_json(BASE_DIR / "lightweight_cf_methods" / "source_audit.json")
    final_source = read_json(BASE_DIR / "final_gate" / "source_audit.json")
    final_manifest = read_json(BASE_DIR / "final_gate" / "manifest.json")
    promote_stop_gate = read_json(BASE_DIR / "final_gate" / "promote_stop_gate.json")

    assert custom_source["ranking_isolation"] == {
        "ranking_default_input_modified": False,
        "pool500_as_ranking_input": False,
        "pool1000_generated": False,
    }
    assert lightweight_source["disabled_outputs"]["ranking_default_input_modified"] is False
    assert final_source["disabled_outputs"] == {
        "pool1000": True,
        "ranking": True,
        "ranking_default_input_modified": False,
        "graph_training": True,
        "mf_training": True,
        "two_tower_training": True,
    }
    assert final_manifest["no_pool1000_generated"] is True
    assert final_manifest["no_ranking_input_modified"] is True
    assert promote_stop_gate["decision"] == "CONTINUATION_ONLY"
    assert promote_stop_gate["full_pool500_continuation_allowed"] is True
    assert promote_stop_gate["ranking_input_replacement_allowed"] is False
    assert promote_stop_gate["heavy_model_training_allowed_by_this_gate"] is False
    assert promote_stop_gate["pool1000_allowed"] is False


def test_bounded_cf_and_heavy_methods_stay_within_probe_boundaries() -> None:
    lightweight_manifest = read_json(BASE_DIR / "lightweight_cf_methods" / "manifest.json")
    lightweight_source = read_json(BASE_DIR / "lightweight_cf_methods" / "source_audit.json")
    heavy_manifest = read_json(BASE_DIR / "heavy_indexed_probes" / "manifest.json")
    final_resource = read_json(BASE_DIR / "final_gate" / "resource_audit.json")
    final_matrix = read_json(BASE_DIR / "final_gate" / "final_method_matrix.json")

    assert lightweight_manifest["no_dense_user_user_matrix"] is True
    assert lightweight_manifest["full_global_cooccurrence_counter"] is False
    assert lightweight_source["bounded_usercf"]["no_dense_user_user_matrix"] is True
    assert lightweight_source["bounded_itemcf_covisit"]["full_global_cooccurrence_counter"] is False

    assert heavy_manifest["candidate_generation_executed"] is False
    assert heavy_manifest["no_model_training_executed"] is True
    assert heavy_manifest["no_full_graph_mf_two_tower_training"] is True
    assert heavy_manifest["ranking_input_modified"] is False
    assert heavy_manifest["pool1000_generated"] is False
    assert final_resource["heavy_probe_boundaries"] == {
        "candidate_generation_executed": False,
        "no_model_training_executed": True,
        "no_full_graph_mf_two_tower_training": True,
        "pool1000_generated": False,
    }

    for method_name in ("graph_probe", "mf_probe", "two_tower_probe"):
        method = final_matrix["methods"][method_name]
        assert method["status"] == "PASS_FEASIBILITY_PROBE_ONLY"
        assert method["candidate_generation_executed_upstream"] is False
        assert method["candidate_generation_executed_in_final_gate"] is False
        assert method["model_training_executed"] is False
        assert method["probe_type"].endswith("no_training")


def test_resource_gate_stays_bounded_and_above_50_gib() -> None:
    resource_files = [
        BASE_DIR / "custom_index" / "resource_audit.json",
        BASE_DIR / "lightweight_cf_methods" / "resource_audit.json",
        BASE_DIR / "sequence_session_methods" / "resource_audit.json",
        BASE_DIR / "heavy_indexed_probes" / "resource_audit.json",
    ]

    for resource_path in resource_files:
        resource_audit = read_json(resource_path)
        assert resource_audit["status"] == "PASS"
        assert resource_audit["min_free_bytes"] >= MIN_FREE_BYTES
        assert resource_audit["disk_free_bytes_start"] >= MIN_FREE_BYTES
        assert resource_audit["disk_free_bytes_end"] >= MIN_FREE_BYTES

    final_resource = read_json(BASE_DIR / "final_gate" / "resource_audit.json")
    assert final_resource["status"] == "PASS"
    assert final_resource["bounded_user_count"] == 500
    assert final_resource["bounded_item_count"] == 10739
    assert final_resource["no_dense_user_user_matrix"] is True
    assert final_resource["no_full_global_cooccurrence_counter"] is True
