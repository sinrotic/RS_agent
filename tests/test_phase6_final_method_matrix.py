from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_phase6_final_method_matrix import run_phase6_final_method_matrix

pytestmark = pytest.mark.unit


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, content: str = "{}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_phase(base_dir: Path, artifact_dir: str, status: str, required: list[str], source_audit: dict | None = None, extra_manifest: dict | None = None) -> None:
    path = base_dir / artifact_dir
    required_artifacts = {name.removesuffix(".json").removesuffix(".jsonl"): str(path / name) for name in required}
    manifest = {"status": status, "failure_reason": None, "downgrade_action": None, "required_artifacts": required_artifacts, **(extra_manifest or {})}
    write_json(path / "manifest.json", manifest)
    write_json(path / "source_audit.json", source_audit or {"train_only_candidate_generation": True, "candidate_generation_uses_holdout": False})
    for name in required:
        target = path / name
        if target.name in {"manifest.json", "source_audit.json"}:
            continue
        if target.suffix == ".jsonl":
            write_text(target, '{"user_id":"u1","item_id":"i1"}\n')
        else:
            write_json(target, {"status": "PASS"})


def make_fixture(tmp_path: Path) -> Path:
    base_dir = tmp_path / "full_main_route_other_methods"
    make_phase(
        base_dir,
        "phase0_contract_precheck",
        "PASS",
        ["manifest.json", "source_audit.json", "resolved_inputs.json"],
        {"train_only": True, "holdout_contract": {"candidate_generation_uses_holdout": False}},
    )
    make_phase(base_dir, "itemcf_covisit_representative_merge_eval", "EXECUTED_PASS_OBSERVATION_ONLY", ["manifest.json", "source_audit.json", "metrics.json", "ablation_vs_lightweight_baseline.json", "candidates.jsonl"], {"train_only_candidate_generation": True, "candidate_generation_uses_holdout": False}, {"candidate_row_count": 1, "empty_user_count": 0})
    make_phase(base_dir, "usercf_bounded_observation", "rejected", ["manifest.json", "source_audit.json", "metrics.json", "ablation_vs_lightweight_baseline.json", "source_overlap_with_itemcf.json", "candidates.jsonl"], {"train_only_candidate_generation": True, "candidate_generation_uses_holdout": False}, {"candidate_row_count": 1, "empty_user_count": 0})
    make_phase(base_dir, "swing_sequence_session_observation", "EXECUTED_PASS_OBSERVATION_ONLY", ["manifest.json", "source_audit.json", "metrics.json", "ablation_vs_lightweight_baseline.json", "session_definition_audit.json", "transition_sidecar_manifest.json", "candidates.jsonl"], {"train_only_candidate_generation": True, "candidate_generation_uses_holdout": False}, {"candidate_row_count": 1, "empty_user_count": 0})
    make_phase(base_dir, "graph_mf_contract_validation", "EXECUTED_PASS_CONTRACT_ONLY", ["manifest.json", "source_audit.json", "metrics.json", "graph_contract_validation.json", "mf_contract_validation.json"], {"train_only_candidate_generation": True, "candidate_generation_uses_holdout": False})
    make_phase(base_dir, "two_tower_pool_readiness", "EXECUTED_PASS_FEASIBILITY_ONLY", ["manifest.json", "source_audit.json", "metrics.json", "two_tower_feasibility.json", "pool_readiness.json"], {"train_only_candidate_generation": True, "candidate_generation_uses_holdout": False})
    return base_dir


def test_phase6_final_method_matrix_passes_with_phase0_holdout_contract(tmp_path: Path) -> None:
    base_dir = make_fixture(tmp_path)
    output_dir = tmp_path / "final_method_matrix"

    manifest = run_phase6_final_method_matrix(base_dir=base_dir, output_dir=output_dir, min_free_bytes=0, enforce_venv=False)

    matrix = read_json(output_dir / "final_method_matrix.json")
    assert manifest["status"] == "PASS"
    assert matrix["status"] == "PASS"
    assert matrix["summary"] == {"phase_count": 6, "pass_like_count": 5, "rejected_count": 1, "blocked_count": 0, "promotion_count": 0}
    assert matrix["rows"][0]["candidate_generation_uses_holdout"] is False
    assert matrix["rows"][0]["train_only_candidate_generation"] is True
    assert all(row["required_artifacts_present"] for row in matrix["rows"])


def test_phase6_final_method_matrix_blocks_missing_artifact(tmp_path: Path) -> None:
    base_dir = make_fixture(tmp_path)
    (base_dir / "two_tower_pool_readiness" / "pool_readiness.json").unlink()
    output_dir = tmp_path / "final_method_matrix"

    manifest = run_phase6_final_method_matrix(base_dir=base_dir, output_dir=output_dir, min_free_bytes=0, enforce_venv=False)

    matrix = read_json(output_dir / "final_method_matrix.json")
    assert manifest["status"] == "BLOCKED"
    assert matrix["status"] == "BLOCKED"
    assert "Phase 5 missing required artifacts: pool_readiness.json" in manifest["failures"]
