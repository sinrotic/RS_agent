from __future__ import annotations

import pytest

pytestmark = [pytest.mark.experiment, pytest.mark.slow]

import json
from pathlib import Path

from rs_core.workflow.ranking_experiments import REQUIRED_CANDIDATE_POOL_SIZE, REQUIRED_TOP_K, build_ranking_run_row
from scripts import run_phase_5_fine_rank_positive_push as runner


FROZEN_ROWS = [
    {"user_id": "u1", "candidate_rank": 1, "item_id": "i1"},
    {"user_id": "u1", "candidate_rank": 2, "item_id": "i2"},
    {"user_id": "u2", "candidate_rank": 1, "item_id": "i3"},
]

RANKING_CASES = [
    {
        "user_id": "u1",
        "target_item": "i1",
        "target_rank": 6,
        "target_score": 0.61,
        "target_coarse_rank": 42,
        "target_fine_rank": 4,
        "target_fine_score": 0.72,
        "target_final_rank": 6,
        "target_final_score": 0.68,
        "target_score_components": {"fine_rank_score": 0.72, "rerank_score": 0.68},
        "target_score_trace": [{"stage": "fine", "score": 0.72}],
        "target_rank_movement": {"coarse_to_fine": 38, "fine_to_final": -2},
        "top_items": [{"item_id": "i9", "score": 0.9}, {"item_id": "i8", "score": 0.7}],
        "topk_replacement_reason": {"replaced_by": [{"item_id": "i9", "dominant_score_component": "popularity"}]},
        "is_topk_hit": False,
    },
    {
        "user_id": "u2",
        "target_item": "i3",
        "target_rank": 3,
        "target_score": 0.8,
        "target_coarse_rank": 80,
        "target_fine_rank": 3,
        "target_fine_score": 0.82,
        "target_final_rank": 3,
        "target_final_score": 0.81,
        "target_score_components": {"fine_rank_score": 0.82, "rerank_score": 0.81},
        "target_score_trace": [{"stage": "fine", "score": 0.82}],
        "target_rank_movement": {"coarse_to_fine": 77, "fine_to_final": 0},
        "top_items": [{"item_id": "i3", "score": 0.81}, {"item_id": "i7", "score": 0.79}],
        "topk_replacement_reason": {"replaced_by": []},
        "is_topk_hit": True,
    },
]

STAGE_TRACE_ROWS = [
    {
        "user_id": "u1",
        "item_id": "i1",
        "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE,
        "coarse_rank": 42,
        "coarse_score": 0.4,
        "fine_rank": 4,
        "fine_score": 0.72,
        "final_rank": 6,
        "final_score": 0.68,
    },
    {
        "user_id": "u2",
        "item_id": "i3",
        "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE,
        "coarse_rank": 80,
        "coarse_score": 0.3,
        "fine_rank": 3,
        "fine_score": 0.82,
        "final_rank": 3,
        "final_score": 0.81,
    },
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _touch_baseline_artifacts(output_dir: Path, method_id: str) -> dict[str, str]:
    method_dir = output_dir / method_id
    method_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics_path": method_dir / "metrics.json",
        "recommendations_path": method_dir / "recommendations.jsonl",
        "ranking_cases_path": method_dir / "ranking_cases.jsonl",
        "ranking_case_summary_path": method_dir / "ranking_case_summary.json",
        "report_path": method_dir / "report.md",
        "frozen_candidates_path": method_dir / "frozen_candidates.jsonl",
        "ranking_stage_trace_path": method_dir / "ranking_stage_trace.jsonl",
        "ranking_stage_summary_path": method_dir / "ranking_stage_summary.json",
    }
    paths["metrics_path"].write_text(
        json.dumps(
            {
                "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
                "top_k": REQUIRED_TOP_K,
                "users_with_holdout": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paths["recommendations_path"].write_text("{}\n", encoding="utf-8")
    _write_jsonl(paths["ranking_cases_path"], RANKING_CASES)
    paths["ranking_case_summary_path"].write_text(json.dumps({"case_count": len(RANKING_CASES)}) + "\n", encoding="utf-8")
    paths["report_path"].write_text("# phase 5 smoke\n", encoding="utf-8")
    _write_jsonl(paths["frozen_candidates_path"], FROZEN_ROWS)
    _write_jsonl(paths["ranking_stage_trace_path"], STAGE_TRACE_ROWS)
    paths["ranking_stage_summary_path"].write_text(
        json.dumps(
            {
                "trace_path": str(paths["ranking_stage_trace_path"]),
                "summary_path": str(paths["ranking_stage_summary_path"]),
                "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
                "top_k": REQUIRED_TOP_K,
                "stage_counts": {"coarse": 2, "fine": 2, "rerank": 2},
                "pass_through_stage_counts": {"coarse": 2, "fine": 2, "rerank": 2},
                "total_ranked_items": 2,
                "online_metrics": {},
                "online_metric_claims": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {key: str(value) for key, value in paths.items()}


def _baseline_row(output_dir: Path) -> dict:
    spec = runner.build_method_specs()[0]
    raw_metrics = {
        "hit_rate_at_k": 0.5,
        "ndcg_at_k": 0.4,
        "mrr_at_k": 0.3,
        "map_at_k": 0.2,
        "candidate_hit_missed_topk_users": 1,
        "users_with_holdout": 2,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "config_summary": {"candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": REQUIRED_TOP_K},
    }
    row = build_ranking_run_row(
        run_id="phase_5_fine_rank_positive_push:test-run",
        run_index=0,
        run_kind="baseline",
        method_spec=spec,
        config={"strategy_name": spec.method_id, "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": REQUIRED_TOP_K},
        frozen_rows=FROZEN_ROWS,
        metrics=raw_metrics,
        strict_status={"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline", "frozen_pool200_boundary"], "metric_delta": {}},
        artifact_paths=_touch_baseline_artifacts(output_dir, spec.method_id)
        | {
            "weak_metrics_path": str(output_dir / spec.method_id / "metrics.json"),
            "fine_rank_case_diagnostics_path": str(output_dir / spec.method_id / "ranking_case_summary.json"),
            "score_gap_diagnostics_path": str(output_dir / spec.method_id / "ranking_case_summary.json"),
            "rank_movement_diagnostics_path": str(output_dir / spec.method_id / "ranking_stage_summary.json"),
            "gates_path": str(output_dir / spec.method_id / "metrics.json"),
        },
        command_text="pytest-phase-5",
    )
    row["raw_metrics"] = raw_metrics
    row["frozen_rows"] = FROZEN_ROWS
    return row


def test_phase_5_frozen_gate_keeps_pool200_top5_and_read_only_recall_boundary(tmp_path):
    baseline = _baseline_row(tmp_path)
    fine_rank = runner._build_fine_rank_diagnostic_row(tmp_path, runner.build_method_specs()[1], baseline, "test-run", "pytest-phase-5")

    assert fine_rank["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert fine_rank["top_k"] == REQUIRED_TOP_K
    assert fine_rank["frozen_candidate_comparison"]["match"] is True
    assert fine_rank["frozen_gate"]["status"] == "PASS"
    assert fine_rank["frozen_gate"]["recall_semantics_changed"] is False
    assert fine_rank["frozen_gate"]["merge_for_user_changed"] is False
    assert fine_rank["frozen_gate"]["real_coarse_pool_shrink"] is False
    assert "fine_rank_diagnostics_read_only" in fine_rank["frozen_gate"]["reasons"]


def test_phase_5_case_diagnostic_success_is_separate_from_promotion_success(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "_run_baseline", lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _baseline_row(output_dir))

    comparison = runner.run_phase_5_fine_rank_positive_push(output_dir=tmp_path, limit_users=2, seed=7)
    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}
    fine_rank = runs_by_id["fine_rank_positive_push_diagnostic"]

    assert comparison["case_diagnostic_success"] is True
    assert comparison["promotion_success"] is False
    assert fine_rank["case_diagnostic_success"] is True
    assert fine_rank["promotion_success"] is False
    assert fine_rank["diagnostic_only"] is True
    assert fine_rank["promotion_eligible"] is False
    assert fine_rank["strict_status"]["promotable"] is False
    assert "valid_test_promotion_evidence_missing" in fine_rank["strict_status"]["reasons"]


def test_phase_5_weak_metrics_are_supporting_diagnostic_only(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "_run_baseline", lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _baseline_row(output_dir))

    comparison = runner.run_phase_5_fine_rank_positive_push(output_dir=tmp_path, limit_users=2, seed=7)
    weak_metrics = comparison["weak_metrics"]

    assert weak_metrics["diagnostic_only"] is True
    assert weak_metrics["promotion_eligible"] is False
    assert weak_metrics["hit_at_10"] >= 1
    assert comparison["fine_rank_case_diagnostics"]["diagnostic_only"] is True
    assert comparison["score_gap_diagnostics"]["promotion_eligible"] is False
    assert comparison["rank_movement_diagnostics"]["promotion_eligible"] is False
    assert comparison["promotion_boundary"]["weak_metrics_diagnostic_only"] is True
    assert comparison["promotion_boundary"]["target_rank_and_percentile_supporting_only"] is True


def test_phase_5_coarse_stage_is_shadow_only_and_never_real_pool_shrink():
    matrix = {row["stage"]: row for row in runner._stage_main_lane_matrix()}
    boundary = runner._promotion_boundary()
    fine_spec = runner.build_method_specs()[1]

    assert matrix["coarse"]["shadow_lane"] == "coarse_shadow_diagnostics_only"
    assert matrix["coarse"]["main_lane"] == "pass_through_pool200"
    assert matrix["coarse"]["candidate_scope"] == "full_pool200"
    assert matrix["coarse"]["candidate_mutation"] is False
    assert matrix["coarse"]["real_pool_shrink"] is False
    assert fine_spec.metadata["coarse_stage_shadow_only"] is True
    assert fine_spec.metadata["does_not_crop_candidates"] is True
    assert boundary["coarse_shadow_does_not_crop_or_mutate_candidates"] is True
    assert boundary["real_coarse_pool_shrink_forbidden"] is True


def test_phase_5_feature_leakage_and_online_gates_block_current_promotion(tmp_path):
    fine_rank = runner._build_fine_rank_diagnostic_row(tmp_path, runner.build_method_specs()[1], _baseline_row(tmp_path), "test-run", "pytest-phase-5")

    assert fine_rank["feature_gate"]["status"] == "PASS"
    assert fine_rank["feature_gate"]["allowed_feature_families_only"] is True
    assert fine_rank["feature_gate"]["new_training_features_added"] is False
    assert fine_rank["leakage_gate"]["status"] == "PASS"
    assert fine_rank["leakage_gate"]["uses_holdout_target_as_feature"] is False
    assert fine_rank["leakage_gate"]["uses_future_interaction_features"] is False
    assert fine_rank["online_gate"]["status"] == "NOT_CURRENT_EVIDENCE"
    assert fine_rank["online_gate"]["promotion_eligible"] is False
    assert "CTR" in fine_rank["online_gate"]["forbidden_as_current_promotion_evidence"]


def test_phase_5_c_and_b_lanes_are_not_promotion_candidates():
    specs = {spec.method_id: spec for spec in runner.build_method_specs()}
    boundary = runner._promotion_boundary()

    assert boundary["blocked_promotions"] == ["c_rescue_promotion", "b_ltr_promotion"]
    assert boundary["promotion_success"] is False
    assert boundary["promotion_eligible"] is False
    assert specs["fine_rank_positive_push_diagnostic"].promotion_eligible is False
    assert specs["fine_rank_positive_push_diagnostic"].diagnostic_only is True
    assert specs["fine_rank_positive_push_diagnostic"].metadata["blocked_promotions"] == ["c_rescue_promotion", "b_ltr_promotion"]


def test_phase_5_runner_smoke_artifact_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "_run_baseline", lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _baseline_row(output_dir))

    comparison = runner.run_phase_5_fine_rank_positive_push(output_dir=tmp_path, limit_users=2, seed=7)
    fine_rank = {row["candidate_id"]: row for row in comparison["runs"]}["fine_rank_positive_push_diagnostic"]
    required_paths = [
        "metrics_path",
        "recommendations_path",
        "ranking_cases_path",
        "ranking_case_summary_path",
        "report_path",
        "frozen_candidates_path",
        "ranking_stage_trace_path",
        "ranking_stage_summary_path",
        "weak_metrics_path",
        "fine_rank_case_diagnostics_path",
        "score_gap_diagnostics_path",
        "rank_movement_diagnostics_path",
        "gates_path",
    ]

    assert comparison["phase"] == "phase_5_fine_rank_positive_push"
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["seed"] == 7
    assert comparison["limit_users"] == 2
    assert comparison["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert comparison["top_k"] == REQUIRED_TOP_K
    for key in required_paths:
        assert fine_rank[key]
        assert Path(fine_rank[key]).exists()
    assert fine_rank["adapter_execution"] == "not_run_read_only_fine_rank_diagnostics"
    assert fine_rank["promotion_evidence_claim"] == "none"
    assert fine_rank["diagnostic_source_metrics_path"] == fine_rank["metrics_path"]
    assert fine_rank["diagnostic_source_stage_trace_path"] == fine_rank["ranking_stage_trace_path"]
