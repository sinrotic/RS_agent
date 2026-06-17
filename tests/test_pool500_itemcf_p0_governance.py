from __future__ import annotations

import pytest

pytestmark = pytest.mark.experiment

from rs_lab.experiments.recall.pool500.governance.itemcf_p0_contracts import (
    build_per_source_metric_contract,
    build_pool_ranking_freeze_assertions,
    is_forbidden_itemcf_input,
    validate_in_universe_denominator_report,
    validate_per_source_metric_contract,
    validate_pool_ranking_freeze_assertions,
    validate_remote_provenance_bundle,
    validate_stage_gate_verifier_checklist,
    validate_success_criteria,
    validate_test_attempt_ledger_record,
)


def _blocker_codes(result: dict[str, object]) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}  # type: ignore[index]


def _valid_in_universe_report() -> dict[str, object]:
    return {
        "schema_version": "in_universe_denominator.v1",
        "evaluation_only": True,
        "evaluation_only_boundary": "只用于评估 denominator 与命中统计，不得作为训练、建边、候选生成或 rerank 输入",
        "universe_source": "train_item_universe_manifest.json",
        "train_item_set_hash": "train-item-set-sha",
        "label_split": "test",
        "label_total_count": 10,
        "label_in_universe_count": 8,
        "label_out_of_universe_count": 2,
        "label_in_universe_ratio": 0.8,
        "metrics_by_k": {
            "500": {
                "hit_in_universe@500": 4,
                "recall_in_universe@500": 0.5,
                "raw_hit@500": 4,
                "raw_recall@500": 0.4,
            }
        },
        "source_breakdown": {"itemcf_weak": {}, "itemcf_strong": {}},
    }


def _valid_success_criteria() -> dict[str, object]:
    criteria = {
        "schema_version": "itemcf_success_criteria.v1",
        "frozen_before_test": True,
        "baseline_config_hash": "baseline-config-sha",
        "chosen_config_hash": "chosen-config-sha",
        "primary_k": 500,
        "threshold_derivation": {"source": "valid-only", "approved_by_verifier": True},
        "minimum_pass_conditions": {
            "weak_min_in_universe_recall@500": 0.1,
            "strong_min_in_universe_recall@500": 0.08,
            "combined_min_in_universe_recall@500": 0.16,
            "max_underfilled_user_rate": 0.0,
            "max_duplicate_user_item_rate": 0.0,
            "max_source_budget_violation_rate": 0.0,
        },
    }
    criteria["success_criteria_hash"] = validate_success_criteria(criteria)["success_criteria_hash"]
    return criteria


def _valid_stage_gate_checklist() -> dict[str, object]:
    return {
        "schema_version": "pool500_stage_gate_verifier_checklist.v1",
        "stage": "P3",
        "artifact_paths": {
            "input_gate_audit": "outputs/recall/pool500_itemcf_new_dataset/evaluation/input_gate_audit.json",
            "per_source_metric_contract": "outputs/recall/pool500_itemcf_new_dataset/evaluation/per_source_metric_contract.json",
            "in_universe_denominator_report": "outputs/recall/pool500_itemcf_new_dataset/evaluation/in_universe_denominator_report.json",
        },
        "checks": {
            "artifact_paths_check": True,
            "required_fields_check": True,
            "hash_check": True,
            "forbidden_input_check": True,
            "route_ranking_isolation_check": True,
            "underfill_duplication_source_budget_check": True,
            "remote_provenance_check": True,
        },
        "pass_fail": "PASS",
        "verifier": "verifier-p0",
    }


def _valid_test_attempt_ledger_record() -> dict[str, object]:
    return {
        "schema_version": "itemcf_test_attempt_ledger.v1",
        "attempt_id": "test-final-001",
        "timestamp": "2026-06-02T00:00:00Z",
        "chosen_config_hash": "chosen-config-sha",
        "success_criteria_hash": "success-criteria-sha",
        "reason_for_attempt": "frozen test-final-only run",
        "test_split_hash": "test-split-sha",
        "metrics_path": "outputs/recall/pool500_itemcf_new_dataset/evaluation/final_test_report.json",
        "pass_fail": "PASS",
        "whether_test_result_informed_next_cycle": False,
    }


def _valid_remote_provenance() -> dict[str, object]:
    return {
        "schema_version": "itemcf_remote_provenance_bundle.v1",
        "command": "python scripts/experiments/recall/pool500/run_pool500_method_source.py --source itemcf_weak",
        "env": {"python_executable": "/workspace/RS_agent/.venv/bin/python"},
        "git_commit": "abc123",
        "git_dirty": False,
        "input_manifest_hash": "input-manifest-sha",
        "method_dataset_hash": "method-dataset-sha",
        "hostname": "authorized-remote-server",
        "resource_audit": {"peak_rss": 1024, "disk_usage": 2048, "runtime_seconds": 30.5, "shard_count": 4},
        "output_artifact_hashes": {"source_index_manifest": "source-index-sha", "candidates": "candidates-sha"},
        "local_revalidation": {
            "manifest_gate": "PASS",
            "hash_signature": "PASS",
            "route_gate_smoke": "PASS",
            "per_source_evaluation_smoke": "PASS",
        },
    }


def test_forbidden_valid_test_holdout_oracle_and_all_items_inputs_are_blocked_for_itemcf_generation() -> None:
    forbidden_paths = [
        "data/processed/full/canonical_interactions.valid.jsonl",
        "data/processed/full/canonical_interactions.test.jsonl",
        "data/processed/full/holdout.jsonl",
        "outputs/recall/oracle/diagnostic_candidates.jsonl",
        "data/processed/full/canonical_items.all.jsonl",
    ]

    assert all(is_forbidden_itemcf_input(path) for path in forbidden_paths)
    assert not is_forbidden_itemcf_input("data/processed/full/user_sequences.train.jsonl")


def test_per_source_metric_contract_requires_itemcf_weak_and_strong_metrics_separately() -> None:
    audit = validate_per_source_metric_contract(build_per_source_metric_contract())

    assert audit["status"] == "PASS"


def test_per_source_metric_contract_rejects_missing_itemcf_strong_breakdown() -> None:
    contract = build_per_source_metric_contract(["itemcf_weak"])

    audit = validate_per_source_metric_contract(contract)

    assert audit["status"] == "BLOCKED"
    assert "ITEMCF_PER_SOURCE_METRICS_MISSING" in _blocker_codes(audit)


def test_per_source_metric_contract_rejects_missing_required_metric_keys() -> None:
    contract = build_per_source_metric_contract()
    contract["sources"]["itemcf_weak"]["required_metrics"] = ["candidate_count"]  # type: ignore[index]

    audit = validate_per_source_metric_contract(contract)

    assert audit["status"] == "BLOCKED"
    assert "PER_SOURCE_METRIC_KEYS_MISSING" in _blocker_codes(audit)


def test_in_universe_denominator_report_is_evaluation_only_and_contains_raw_denominator_fields() -> None:
    audit = validate_in_universe_denominator_report(_valid_in_universe_report())

    assert audit["status"] == "PASS"


def test_in_universe_denominator_report_rejects_training_usage_boundary_change() -> None:
    report = _valid_in_universe_report()
    report["evaluation_only"] = False

    audit = validate_in_universe_denominator_report(report)

    assert audit["status"] == "BLOCKED"
    assert "IN_UNIVERSE_EVALUATION_ONLY_REQUIRED" in _blocker_codes(audit)


def test_in_universe_denominator_report_requires_raw_and_in_universe_metrics_by_k() -> None:
    report = _valid_in_universe_report()
    report["metrics_by_k"] = {"500": {"raw_hit@500": 4}}

    audit = validate_in_universe_denominator_report(report)

    assert audit["status"] == "BLOCKED"
    assert "IN_UNIVERSE_METRICS_BY_K_FIELD_MISSING" in _blocker_codes(audit)


def test_success_criteria_freeze_requires_hashes_before_test_final() -> None:
    audit = validate_success_criteria(_valid_success_criteria())

    assert audit["status"] == "PASS"
    assert audit["success_criteria_hash"]


def test_success_criteria_freeze_rejects_unfrozen_criteria() -> None:
    criteria = _valid_success_criteria()
    criteria["frozen_before_test"] = False

    audit = validate_success_criteria(criteria)

    assert audit["status"] == "BLOCKED"
    assert "SUCCESS_CRITERIA_MUST_BE_FROZEN_BEFORE_TEST" in _blocker_codes(audit)


def test_test_attempt_ledger_allows_one_frozen_test_final_record() -> None:
    audit = validate_test_attempt_ledger_record(_valid_test_attempt_ledger_record())

    assert audit["status"] == "PASS"


def test_test_attempt_ledger_rejects_test_tuning_after_final_attempt() -> None:
    record = _valid_test_attempt_ledger_record()
    record["whether_test_result_informed_next_cycle"] = True

    audit = validate_test_attempt_ledger_record(record)

    assert audit["status"] == "BLOCKED"
    assert "TEST_RESULT_MUST_NOT_INFORM_NEXT_CYCLE" in _blocker_codes(audit)


def test_stage_gate_checklist_blocks_progression_when_required_checks_are_missing() -> None:
    checklist = _valid_stage_gate_checklist()
    checklist["checks"]["route_ranking_isolation_check"] = False  # type: ignore[index]
    checklist["pass_fail"] = "BLOCKED"

    audit = validate_stage_gate_verifier_checklist(checklist)

    assert audit["status"] == "BLOCKED"
    assert "STAGE_GATE_CHECKS_FAILED" in _blocker_codes(audit)


def test_remote_provenance_requires_command_environment_hashes_resources_and_local_revalidation() -> None:
    audit = validate_remote_provenance_bundle(_valid_remote_provenance())

    assert audit["status"] == "PASS"


def test_remote_provenance_rejects_missing_local_revalidation() -> None:
    provenance = _valid_remote_provenance()
    provenance["local_revalidation"] = {"manifest_gate": "PASS"}

    audit = validate_remote_provenance_bundle(provenance)

    assert audit["status"] == "BLOCKED"
    assert "REMOTE_LOCAL_REVALIDATION_PASS_REQUIRED" in _blocker_codes(audit)


def test_stage_gate_rejects_underfill_duplicate_or_source_budget_hard_failures() -> None:
    checklist = _valid_stage_gate_checklist()
    checklist["checks"]["underfill_duplication_source_budget_check"] = False  # type: ignore[index]
    checklist["pass_fail"] = "BLOCKED"

    audit = validate_stage_gate_verifier_checklist(checklist)

    assert audit["status"] == "BLOCKED"
    assert "STAGE_GATE_CHECKS_FAILED" in _blocker_codes(audit)


def test_pool200_and_ranking_freeze_allows_source_artifact_only_itemcf_changes() -> None:
    audit = validate_pool_ranking_freeze_assertions(build_pool_ranking_freeze_assertions())

    assert audit["status"] == "PASS"


def test_pool200_and_ranking_freeze_rejects_candidate_fill_order_changes() -> None:
    freeze = build_pool_ranking_freeze_assertions(candidate_fill_order_changed=True)

    audit = validate_pool_ranking_freeze_assertions(freeze)

    assert audit["status"] == "BLOCKED"
    assert "POOL200_RANKING_FREEZE_VIOLATED" in _blocker_codes(audit)
