from __future__ import annotations

import pytest

pytestmark = [pytest.mark.experiment, pytest.mark.slow]

import json
from pathlib import Path

from rs_core.workflow.ranking_experiments import REQUIRED_CANDIDATE_POOL_SIZE, REQUIRED_TOP_K
from scripts import run_phase_6_industrial_ranking_chain as runner


FROZEN_ROWS = [
    {"user_id": "u1", "candidate_rank": 1, "item_id": "i1"},
    {"user_id": "u1", "candidate_rank": 2, "item_id": "i2"},
    {"user_id": "u2", "candidate_rank": 1, "item_id": "i3"},
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _fake_hybrid_result(config_path: Path, limit_users: int | None, config_overrides: dict) -> dict:
    output_dir = Path(config_overrides["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics_path": output_dir / "metrics.json",
        "recommendations_path": output_dir / "recommendations.jsonl",
        "ranking_cases_path": output_dir / "ranking_cases.jsonl",
        "ranking_case_summary_path": output_dir / "ranking_case_summary.json",
        "report_path": output_dir / "report.md",
        "frozen_candidates_path": output_dir / "frozen_candidates.jsonl",
        "ranking_stage_trace_path": output_dir / "ranking_stage_trace.jsonl",
        "ranking_stage_summary_path": output_dir / "ranking_stage_summary.json",
    }
    metrics = {
        "hit_rate_at_k": 0.5,
        "ndcg_at_k": 0.4,
        "mrr_at_k": 0.3,
        "map_at_k": 0.2,
        "candidate_hit_missed_topk_users": 1,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "users_with_holdout": 2,
        "frozen_candidates_path": str(paths["frozen_candidates_path"]),
        "ranking_stage_artifact_paths": {"trace": str(paths["ranking_stage_trace_path"]), "summary": str(paths["ranking_stage_summary_path"])},
        "config_summary": {
            "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
            "top_k": REQUIRED_TOP_K,
            "rank_weights": config_overrides.get("rank_weights", {}),
            "normalized_additive_ranking": config_overrides.get("normalized_additive_ranking", {"enabled": False}),
            "source_aware_fusion": config_overrides.get("source_aware_fusion", {"enabled": False}),
            "item_feature_rerank": config_overrides.get("item_feature_rerank", {"enabled": False}),
            "topk_source_minimums": config_overrides.get("topk_source_minimums", {}),
            "ltr_model": config_overrides.get("ltr_model", {"enabled": False}),
            "pool200_fixed_baseline": {
                "fixed_recall_config_path": "configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml",
                "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
            },
        },
    }
    paths["metrics_path"].write_text(json.dumps(metrics) + "\n", encoding="utf-8")
    paths["recommendations_path"].write_text("{}\n", encoding="utf-8")
    paths["ranking_cases_path"].write_text("{}\n", encoding="utf-8")
    paths["ranking_case_summary_path"].write_text(json.dumps({"case_count": 0}) + "\n", encoding="utf-8")
    paths["report_path"].write_text("# phase 6 smoke\n", encoding="utf-8")
    _write_jsonl(paths["frozen_candidates_path"], FROZEN_ROWS)
    _write_jsonl(paths["ranking_stage_trace_path"], [{"stage": "coarse"}, {"stage": "fine"}, {"stage": "rerank"}])
    paths["ranking_stage_summary_path"].write_text(
        json.dumps(
            {
                "trace_path": str(paths["ranking_stage_trace_path"]),
                "summary_path": str(paths["ranking_stage_summary_path"]),
                "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
                "top_k": REQUIRED_TOP_K,
                "stage_counts": {"coarse": 3, "fine": 3, "rerank": 3},
                "pass_through_stage_counts": {"coarse": 3, "fine": 3, "rerank": 3},
                "total_ranked_items": 3,
                "online_metrics": {},
                "online_metric_claims": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {key: str(value) for key, value in paths.items()} | {"metrics": metrics}


def test_phase_6_method_specs_place_industrial_algorithms_across_all_ranking_stages():
    specs = {spec.method_id: spec for spec in runner.build_method_specs()}
    industrial = specs["industrial_coarse_fine_rerank_chain_diagnostic"]
    stage_algorithms = industrial.metadata["stage_algorithms"]

    assert stage_algorithms["coarse_rank"]["algorithm"] == "source_weighted_metadata_prefilter_score"
    assert stage_algorithms["coarse_rank"]["execution"] == "shadow_pass_through_no_crop"
    assert stage_algorithms["fine_rank"]["algorithm"] == "normalized_additive_plus_source_aware_item_feature_scoring"
    assert stage_algorithms["fine_rank"]["execution"] == "full_pool200_scoring"
    assert stage_algorithms["rerank"]["algorithm"] == "topk_source_minimums_stable_tiebreak_local_constraint"
    assert stage_algorithms["rerank"]["execution"] == "top5_local_adjustment_only"
    assert industrial.promotion_eligible is False
    assert industrial.diagnostic_only is True
    assert industrial.metadata["does_not_crop_candidates"] is True


def test_phase_6_industrial_chain_smoke_keeps_frozen_pool_and_diagnostic_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "run_hybrid_demo", _fake_hybrid_result)

    comparison = runner.run_phase_6_industrial_ranking_chain(output_dir=tmp_path, limit_users=2, seed=7)
    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}
    industrial = runs_by_id["industrial_coarse_fine_rerank_chain_diagnostic"]

    assert comparison["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert comparison["top_k"] == REQUIRED_TOP_K
    assert comparison["current_recall_mainline"] == {
        "mainline_id": "source_balanced_pool200_hybrid_recall",
        "config_path": str(runner.CURRENT_RECALL_MAINLINE_CONFIG),
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "candidate_pool_strategy": "balanced_source_budget",
        "role": "fixed_phase_1_source_balanced_pool200_hybrid_recall_input_for_ranking",
        "ranking_scope": "ranking_only_on_frozen_candidates_from_current_recall_mainline",
    }
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert all(row["status"] == "PASS" for row in comparison["artifact_inspection"]["inspected_runs"])
    assert comparison["promotion_boundary"]["recall_semantics_changed"] is False
    assert comparison["promotion_boundary"]["merge_for_user_changed"] is False
    assert comparison["promotion_boundary"]["real_coarse_pool_shrink"] is False
    assert comparison["promotion_boundary"]["coarse_rank_shadow_pass_through_only"] is True
    assert comparison["promotion_boundary"]["fine_rank_full_pool200_scoring"] is True
    assert comparison["promotion_boundary"]["rerank_top5_local_constraint_only"] is True
    assert comparison["promotion_boundary"]["industrial_chain_diagnostic_only"] is True
    assert comparison["promotion_boundary"]["promotion_eligible"] is False
    assert comparison["final_decision"]["status"] == "DIAGNOSTIC_DEFAULT_CHAIN_READY"
    assert industrial["run_kind"] == "diagnostic"
    assert industrial["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert industrial["top_k"] == REQUIRED_TOP_K
    assert industrial["promotion_eligible"] is False
    assert industrial["diagnostic_only"] is True
    assert industrial["strict_status"]["promotable"] is False
    assert industrial["strict_status"]["diagnostic_only"] is True
    assert industrial["frozen_candidate_comparison"]["match"] is True
    assert industrial["adapter_execution"] == "industrial_rule_chain_run_on_frozen_pool200"
    assert industrial["promotion_evidence_claim"] == "none"
    assert industrial["fixed_recall_config_path"] == str(runner.CURRENT_RECALL_MAINLINE_CONFIG)
    assert industrial["current_recall_mainline_id"] == "source_balanced_pool200_hybrid_recall"
    assert "industrial_chain_diagnostic_only" in industrial["strict_status"]["reasons"]


def test_phase_6_config_enables_practical_rule_chain_but_not_ltr_or_online_promotion():
    config = runner.INDUSTRIAL_CHAIN_CONFIG
    boundary = runner._promotion_boundary()

    assert config["rank_weights"]["itemcf"] > config["rank_weights"]["popular"]
    assert config["normalized_additive_ranking"]["enabled"] is True
    assert config["source_aware_fusion"]["enabled"] is True
    assert config["item_feature_rerank"]["enabled"] is True
    assert config["topk_source_minimums"] == {"itemcf": 1}
    assert config["ltr_model"]["enabled"] is False
    assert boundary["recall_mainline_id"] == "source_balanced_pool200_hybrid_recall"
    assert boundary["fixed_recall_config_path"].endswith("phase_1_21_recall_coverage_pool200_experimental.yaml")
    assert boundary["online_metrics_forbidden_as_current_offline_evidence"] is True
    assert boundary["promotion_success"] is False
    assert boundary["promotion_eligible"] is False


def test_phase_6_future_tree_neural_and_online_routes_are_blocked_not_promoted(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "run_hybrid_demo", _fake_hybrid_result)

    comparison = runner.run_phase_6_industrial_ranking_chain(output_dir=tmp_path, limit_users=2, seed=7)
    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}

    for method_id in ["gbdt_lambdamart_fine_rank_future_challenger_blocked", "neural_sequence_agent_online_future_route_blocked"]:
        row = runs_by_id[method_id]
        assert row["run_kind"] == "blocked"
        assert row["promotion_eligible"] is False
        assert row["status"] == "BLOCKED"
        assert "future_route_not_current_offline_evidence" in row["blocked_reason"]
        assert "valid_test_promotion_evidence_missing" in row["blocked_reason"]
