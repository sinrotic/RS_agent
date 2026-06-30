from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.workflow.pool500_route_gate import (
    DEFAULT_BASELINE_CONFIG,
    DEFAULT_MAIN_ROUTE_DIR,
    DEFAULT_PHASE_CONFIG,
    EXPECTED_SOURCES,
    build_continuation_final_gate,
    build_route_precheck,
    build_route_signature,
)

pytestmark = pytest.mark.experiment

ROOT = Path(__file__).resolve().parents[1]


def test_p7_route_signature_uses_section_24_authority_and_required_sources() -> None:
    signature = build_route_signature(DEFAULT_MAIN_ROUTE_DIR, DEFAULT_PHASE_CONFIG, DEFAULT_BASELINE_CONFIG)

    assert signature["schema_version"] == "full_pool500_route_signature_gate"
    assert "RECALL_METHODS_EXPERIMENT_LOG.md#24" in signature["route_authority"]
    assert set(signature["pool200_route"]["source_set"]) == EXPECTED_SOURCES
    assert signature["pool200_route"]["missing_expected_sources"] == []
    assert signature["pool200_route"]["unexpected_sources"] == []
    assert signature["pool200_route"]["candidate_pool_size"] == 200
    assert signature["intended_pool500_route"]["candidate_pool_size"] == 500


def test_p7_route_signature_enforces_balanced_source_budget_and_itemcf_alias() -> None:
    signature = build_route_signature(DEFAULT_MAIN_ROUTE_DIR, DEFAULT_PHASE_CONFIG, DEFAULT_BASELINE_CONFIG)
    strategy = signature["strategy_audit"]

    assert strategy["actual_strategy"] == "balanced_source_budget"
    assert strategy["actual_fill_order"] == [
        "semantic_title_category_expansion",
        "co_visit_fallback_repair",
        "usercf_recall",
        "swing_recall",
        "itemcf",
        "category",
        "popular",
    ]
    assert set(strategy["itemcf_alias_expansion"]) == {"itemcf_weak", "itemcf_strong"}


def test_p7_route_precheck_hard_blocks_stale_two_tower_artifact_contract() -> None:
    signature = build_route_signature(DEFAULT_MAIN_ROUTE_DIR, DEFAULT_PHASE_CONFIG, DEFAULT_BASELINE_CONFIG)
    signature["two_tower_audit"] = {
        **signature["two_tower_audit"],
        "manifest_contract_missing_paths": ["train_config"],
    }
    precheck = build_route_precheck(signature)

    assert precheck["schema_version"] == "P7_ROUTE_PRECHECK"
    assert precheck["decision"] == "STOP"
    assert precheck["full_pool500_recall_only_continuation_allowed"] is False
    assert precheck["ranking_input_replacement_allowed"] is False
    assert precheck["pool1000_allowed"] is False
    blocker_codes = {blocker["code"] for blocker in precheck["blockers"]}
    assert "BLOCKED_TWO_TOWER_ARTIFACT" in blocker_codes
    assert "BLOCKED_ITEMCF_ALIAS_EXPANSION" not in blocker_codes


def test_p7_route_contract_audit_records_canonical_paths_and_hashes() -> None:
    signature = build_route_signature(DEFAULT_MAIN_ROUTE_DIR, DEFAULT_PHASE_CONFIG, DEFAULT_BASELINE_CONFIG)
    contract = signature["route_contract_audit"]

    assert contract["checks"]["top_k"] is True
    assert contract["checks"]["evaluation_mode"] is True
    assert contract["checks"]["limit_users"] is True
    assert contract["checks"]["users_with_holdout"] is True
    assert contract["checks"]["holdout_user_ids_hash"] is True
    assert contract["checks"]["ranking_rerank_disabled_checks"] is True
    for key in ("baseline_config", "phase_1_21_config"):
        assert contract["checks"][key]["exists"] is True
        assert contract["checks"][key]["sha256"]
        assert str(ROOT) in contract["checks"][key]["canonical_path"]


def test_p7_continuation_final_gate_is_diagnostic_only_without_full_quality_audit() -> None:
    precheck = {
        "status": "PASS",
        "blockers": [],
    }
    final_gate = build_continuation_final_gate(route_precheck=precheck)

    assert final_gate["decision"] == "DIAGNOSTIC_ONLY"
    assert final_gate["full_pool500_recall_only_continuation_allowed"] is False
    assert final_gate["ranking_input_replacement_allowed"] is False
    assert final_gate["decision_matrix"]["PASS_CONTINUATION"]


def test_p7_continuation_final_gate_blocks_missing_candidate_quality_fields() -> None:
    precheck = {
        "status": "PASS",
        "blockers": [],
    }
    quality_path = ROOT / "outputs" / "recall" / "p7_full_pool500_main_route_continuation" / "route_authority" / "route_authority_audit.json"
    final_gate = build_continuation_final_gate(route_precheck=precheck, candidate_quality_audit_path=quality_path)

    assert final_gate["decision"] == "STOP"
    blocker_codes = {blocker["code"] for blocker in final_gate["blockers"]}
    assert "BLOCKED_MISSING_CANDIDATE_QUALITY_AUDIT_FIELD" in blocker_codes
    assert final_gate["ranking_input_replacement_allowed"] is False


def test_p7_continuation_final_gate_can_pass_recall_only_with_quality_audit(tmp_path: Path) -> None:
    precheck = {
        "status": "PASS",
        "blockers": [],
    }
    quality_path = tmp_path / "candidate_quality.json"
    quality_path.write_text(
        """
        {
          "empty_candidate_users_pool500": 0,
          "empty_candidate_rate_pool500": 0.0,
          "fallback_rate_pool500": 0.0,
          "fallback_error_count_pool500": 0,
          "duplicate_user_item_rows_pool500": 0
        }
        """,
        encoding="utf-8",
    )
    final_gate = build_continuation_final_gate(route_precheck=precheck, candidate_quality_audit_path=quality_path)

    assert final_gate["decision"] == "PASS_CONTINUATION"
    assert final_gate["full_pool500_recall_only_continuation_allowed"] is True
    assert final_gate["ranking_input_replacement_allowed"] is False
    assert final_gate["pool1000_allowed"] is False
    assert final_gate["heavy_model_training_allowed_by_this_gate"] is False
