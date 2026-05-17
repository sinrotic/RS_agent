from __future__ import annotations

import pytest

pytestmark = pytest.mark.experiment

import json
from pathlib import Path

from rs_core.workflow.ranking_experiments import REQUIRED_CANDIDATE_POOL_SIZE, REQUIRED_TOP_K, build_ranking_run_row
from scripts.experiments.ranking import run_phase_4_stage_shadow_metrics as runner


FROZEN_ROWS = [
    {"user_id": "u1", "candidate_rank": 1, "item_id": "i1"},
    {"user_id": "u1", "candidate_rank": 2, "item_id": "i2"},
    {"user_id": "u2", "candidate_rank": 1, "item_id": "i3"},
]

RANKING_CASES = [
    {"user_id": "u1", "target_item": "i1", "target_rank": 6, "target_coarse_rank": 40, "target_coarse_score": 0.8, "target_final_rank": 6, "target_final_score": 0.7},
    {"user_id": "u2", "target_item": "i3", "target_rank": 12, "target_coarse_rank": 75, "target_coarse_score": 0.5, "target_final_rank": 12, "target_final_score": 0.4},
    {"user_id": "u3", "target_item": "i9", "target_rank": 25, "target_coarse_rank": 125, "target_coarse_score": 0.2, "target_final_rank": 25, "target_final_score": 0.1},
]

STAGE_TRACE_ROWS = [
    {"user_id": "u1", "item_id": "i1", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "coarse_rank": 40, "coarse_score": 0.8, "final_rank": 6, "final_score": 0.7},
    {"user_id": "u2", "item_id": "i3", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "coarse_rank": 75, "coarse_score": 0.5, "final_rank": 12, "final_score": 0.4},
    {"user_id": "u3", "item_id": "i9", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "coarse_rank": 125, "coarse_score": 0.2, "final_rank": 25, "final_score": 0.1},
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
    paths["metrics_path"].write_text(json.dumps({"candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": REQUIRED_TOP_K}) + "\n", encoding="utf-8")
    paths["recommendations_path"].write_text("{}\n", encoding="utf-8")
    _write_jsonl(paths["ranking_cases_path"], RANKING_CASES)
    paths["ranking_case_summary_path"].write_text("{}\n", encoding="utf-8")
    paths["report_path"].write_text("# test\n", encoding="utf-8")
    _write_jsonl(paths["frozen_candidates_path"], FROZEN_ROWS)
    _write_jsonl(paths["ranking_stage_trace_path"], STAGE_TRACE_ROWS)
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
    return {key: str(value) for key, value in paths.items()}


def _baseline_row(output_dir: Path) -> dict:
    spec = runner.build_method_specs()[0]
    raw_metrics = {
        "hit_rate_at_k": 0.2,
        "ndcg_at_k": 0.1,
        "mrr_at_k": 0.05,
        "map_at_k": 0.04,
        "candidate_hit_missed_topk_users": 2,
        "users_with_holdout": 3,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "config_summary": {"candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": REQUIRED_TOP_K},
    }
    row = build_ranking_run_row(
        run_id="phase_4_stage_shadow_metrics:test-run",
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
            "coarse_shadow_diagnostics_path": str(output_dir / spec.method_id / "ranking_stage_summary.json"),
        },
        command_text="pytest-phase-4",
    )
    row["raw_metrics"] = raw_metrics
    row["frozen_rows"] = FROZEN_ROWS
    return row


def test_phase_4_shadow_keeps_frozen_pool200_top5_and_does_not_crop_or_mutate_candidates(tmp_path):
    baseline = _baseline_row(tmp_path)
    shadow = runner._build_shadow_row(tmp_path, runner.build_method_specs()[1], baseline, "test-run", "pytest-phase-4")

    assert shadow["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert shadow["top_k"] == REQUIRED_TOP_K
    assert shadow["frozen_candidate_comparison"]["match"] is True
    assert shadow["frozen_candidate_comparison"]["baseline"] == shadow["frozen_candidate_comparison"]["variant"]
    assert shadow["frozen_candidate_comparison"]["baseline"]["hash"] == baseline["frozen_candidate_comparison"]["baseline"]["hash"]
    assert shadow["coarse_shadow_diagnostics"]["does_not_crop_or_mutate_candidates"] is True
    assert shadow["coarse_shadow_diagnostics"]["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert shadow["coarse_shadow_diagnostics"]["top_k"] == REQUIRED_TOP_K
    assert shadow["adapter_execution"] == "not_run_shadow_read_only_diagnostics"


def test_phase_4_weak_metrics_and_coarse_retention_are_diagnostic_only(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "_run_baseline", lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _baseline_row(output_dir))

    comparison = runner.run_phase_4_stage_shadow_metrics(output_dir=tmp_path, limit_users=3, seed=7)
    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}
    shadow = runs_by_id["coarse_shadow_retention_diagnostic"]

    assert comparison["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert comparison["top_k"] == REQUIRED_TOP_K
    assert comparison["weak_metrics"]["diagnostic_only"] is True
    assert comparison["weak_metrics"]["promotion_eligible"] is False
    assert comparison["weak_metrics"]["hit_at_10"] == 1
    assert comparison["weak_metrics"]["hit_at_20"] == 2
    assert comparison["weak_metrics"]["missed_top5_but_hit_top20_users"] == 2
    assert comparison["coarse_shadow_diagnostics"]["diagnostic_only"] is True
    assert comparison["coarse_shadow_diagnostics"]["promotion_eligible"] is False
    assert comparison["coarse_shadow_diagnostics"]["coarse_retention_at_50"] == 0.333333
    assert comparison["coarse_shadow_diagnostics"]["coarse_retention_at_100"] == 0.666667
    assert shadow["promotion_eligible"] is False
    assert shadow["diagnostic_only"] is True
    assert shadow["strict_status"]["promotable"] is False
    assert "weak_metrics_are_diagnostic_only" in shadow["strict_status"]["reasons"]
    assert shadow["promotion_evidence_claim"] == "none"
    assert comparison["artifact_inspection"]["status"] == "PASS"


def test_phase_4_stage_main_lane_matrix_separates_shadow_full_pool_topk_and_future_online():
    matrix = {row["stage"]: row for row in runner._stage_main_lane_matrix()}

    assert matrix["coarse"]["shadow_lane"] == "coarse_shadow_retention_diagnostic"
    assert matrix["coarse"]["candidate_mutation"] is False
    assert {"coarse_retention_at_50", "coarse_retention_at_100"}.issubset(matrix["coarse"]["diagnostics"])
    assert matrix["fine"]["main_lane"] == "existing_fine_rank_full_pool200_scoring"
    assert matrix["fine"]["candidate_scope"] == "full_pool200"
    assert matrix["rerank"]["main_lane"] == "existing_rerank_top5"
    assert matrix["rerank"]["top_k"] == REQUIRED_TOP_K
    assert matrix["future-online"]["main_lane"] == "not_current_offline_evidence"
    assert matrix["future-online"]["promotion_eligible"] is False


def test_phase_4_promotion_boundary_keeps_recall_merge_and_online_metrics_out_of_current_evidence():
    boundary = runner._promotion_boundary()
    specs = {spec.method_id: spec for spec in runner.build_method_specs()}

    assert boundary["frozen_pool200_required"] is True
    assert boundary["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert boundary["top_k"] == REQUIRED_TOP_K
    assert boundary["recall_semantics_changed"] is False
    assert boundary["merge_for_user_changed"] is False
    assert boundary["coarse_shadow_does_not_crop_or_mutate_candidates"] is True
    assert boundary["weak_metrics_diagnostic_only"] is True
    assert boundary["promotion_eligible"] is False
    assert boundary["online_metrics_forbidden_as_current_offline_evidence"] is True
    assert specs["coarse_shadow_retention_diagnostic"].promotion_eligible is False
    assert specs["coarse_shadow_retention_diagnostic"].diagnostic_only is True
    assert specs["coarse_shadow_retention_diagnostic"].metadata["does_not_crop_candidates"] is True
