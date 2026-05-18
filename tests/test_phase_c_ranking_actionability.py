from __future__ import annotations

import pytest

pytestmark = pytest.mark.experiment

import json
from pathlib import Path

from rs_core.recsys.evaluation import compare_frozen_candidate_signatures
from rs_core.workflow.ranking_experiments import REQUIRED_CANDIDATE_POOL_SIZE, REQUIRED_TOP_K
from rs_lab.experiments.ranking import run_phase_c_ranking_actionability_diagnostic as runner


BASELINE_FROZEN_ROWS = [
    {"user_id": "u1", "candidate_rank": 1, "item_id": "i1", "sources": ["itemcf"]},
    {"user_id": "u1", "candidate_rank": 2, "item_id": "i2", "sources": ["popular"]},
    {"user_id": "u1", "candidate_rank": 3, "item_id": "i3", "sources": ["semantic"]},
    {"user_id": "u2", "candidate_rank": 1, "item_id": "i4", "sources": ["popular"]},
    {"user_id": "u2", "candidate_rank": 2, "item_id": "i5", "sources": ["itemcf", "semantic"]},
    {"user_id": "u2", "candidate_rank": 3, "item_id": "i6", "sources": ["itemcf", "semantic"]},
]

BASELINE_CASES = [
    {"user_id": "u1", "target_item": "i1", "target_rank": 6},
    {"user_id": "u2", "target_item": "i5", "target_rank": 7},
]

DIAGNOSTIC_CASES = [
    {"user_id": "u1", "target_item": "i1", "target_rank": 4, "target_sources": ["itemcf"]},
    {"user_id": "u2", "target_item": "i5", "target_rank": 8, "target_sources": ["itemcf", "semantic"]},
]

BASELINE_TRACE_ROWS = [
    {"user_id": "u1", "item_id": "i2", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 1, "sources": ["popular"]},
    {"user_id": "u1", "item_id": "i3", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 2, "sources": ["semantic"]},
    {"user_id": "u1", "item_id": "i7", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 3, "sources": ["popular"]},
    {"user_id": "u1", "item_id": "i8", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 4, "sources": ["popular"]},
    {"user_id": "u1", "item_id": "i9", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 5, "sources": ["popular"]},
    {"user_id": "u1", "item_id": "i1", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 6, "sources": ["itemcf"]},
    {"user_id": "u2", "item_id": "i4", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 1, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i9", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 2, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i10", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 3, "sources": ["semantic"]},
    {"user_id": "u2", "item_id": "i11", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 4, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i12", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 5, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i5", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 7, "sources": ["itemcf", "semantic"]},
]

DIAGNOSTIC_TRACE_ROWS = [
    {"user_id": "u1", "item_id": "i2", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 1, "sources": ["popular"]},
    {"user_id": "u1", "item_id": "i3", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 2, "sources": ["semantic"]},
    {"user_id": "u1", "item_id": "i7", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 3, "sources": ["popular"]},
    {"user_id": "u1", "item_id": "i1", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 4, "sources": ["itemcf"]},
    {"user_id": "u1", "item_id": "i8", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 5, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i4", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 1, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i9", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 2, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i10", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 3, "sources": ["semantic"]},
    {"user_id": "u2", "item_id": "i11", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 4, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i12", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 5, "sources": ["popular"]},
    {"user_id": "u2", "item_id": "i5", "input_candidate_count": REQUIRED_CANDIDATE_POOL_SIZE, "final_rank": 8, "sources": ["itemcf", "semantic"]},
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_run_artifacts(output_dir: Path, method_id: str, ranking_cases: list[dict], stage_trace: list[dict]) -> dict[str, str]:
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
    paths["metrics_path"].write_text("{}\n", encoding="utf-8")
    paths["recommendations_path"].write_text("{}\n", encoding="utf-8")
    _write_jsonl(paths["ranking_cases_path"], ranking_cases)
    paths["ranking_case_summary_path"].write_text(json.dumps({"case_count": len(ranking_cases)}) + "\n", encoding="utf-8")
    paths["report_path"].write_text("# phase c fixture\n", encoding="utf-8")
    _write_jsonl(paths["frozen_candidates_path"], BASELINE_FROZEN_ROWS)
    _write_jsonl(paths["ranking_stage_trace_path"], stage_trace)
    paths["ranking_stage_summary_path"].write_text(
        json.dumps(
            {
                "trace_path": str(paths["ranking_stage_trace_path"]),
                "summary_path": str(paths["ranking_stage_summary_path"]),
                "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
                "top_k": REQUIRED_TOP_K,
                "stage_counts": {"coarse": len(stage_trace), "fine": len(stage_trace), "rerank": len(stage_trace)},
                "pass_through_stage_counts": {"coarse": len(stage_trace), "fine": len(stage_trace), "rerank": len(stage_trace)},
                "total_ranked_items": len(stage_trace),
                "online_metrics": {},
                "online_metric_claims": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {key: str(value) for key, value in paths.items()}


def _run_row(output_dir: Path, method_id: str, run_kind: str, ranking_cases: list[dict], stage_trace: list[dict], metrics: dict) -> dict:
    paths = _write_run_artifacts(output_dir, method_id, ranking_cases, stage_trace)
    return {
        "run_id": "phase-c:test-run",
        "run_index": 0 if run_kind == "baseline" else 1,
        "run_kind": run_kind,
        "candidate_id": method_id,
        "candidate_type": "fixture",
        "promotion_eligible": False,
        "diagnostic_only": run_kind != "baseline",
        "status": "BASELINE" if run_kind == "baseline" else "PARTIAL diagnostic-only",
        "strict_status": {
            "status": "BASELINE" if run_kind == "baseline" else "PARTIAL diagnostic-only",
            "promotable": False,
            "diagnostic_only": run_kind != "baseline",
            "reasons": ["same_run_baseline"] if run_kind == "baseline" else ["valid_test_promotion_evidence_missing"],
        },
        "frozen_candidate_comparison": compare_frozen_candidate_signatures(BASELINE_FROZEN_ROWS, BASELINE_FROZEN_ROWS),
        "metrics": metrics,
        **paths,
    }


def _phase_6_fixture(output_dir: Path) -> dict:
    baseline = _run_row(
        output_dir,
        "same_run_pool200_baseline",
        "baseline",
        BASELINE_CASES,
        BASELINE_TRACE_ROWS,
        {"candidate_hit_missed_topk_users": 1, "candidate_hit_rate_at_pool": 0.5, "users_with_holdout": 2, "hit_rate_denominator": "users_with_holdout"},
    )
    diagnostic = _run_row(
        output_dir,
        "industrial_coarse_fine_rerank_chain_diagnostic",
        "diagnostic",
        DIAGNOSTIC_CASES,
        DIAGNOSTIC_TRACE_ROWS,
        {"candidate_hit_missed_topk_users": 1, "candidate_hit_rate_at_pool": 0.5, "users_with_holdout": 2, "hit_rate_denominator": "users_with_holdout"},
    )
    return {
        "phase": "phase_6_industrial_ranking_chain",
        "run_id": "test-run",
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "current_recall_mainline": {"mainline_id": runner.CURRENT_RECALL_MAINLINE_ID, "candidate_pool_strategy": "balanced_source_budget"},
        "artifact_inspection": {"status": "PASS"},
        "promotion_boundary": {"recall_semantics_changed": False},
        "runs": [baseline, diagnostic],
    }


def _run_fixture(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.setattr(runner, "run_phase_6_industrial_ranking_chain", lambda output_dir, limit_users, seed: _phase_6_fixture(output_dir))
    return runner.run_phase_c_ranking_actionability_diagnostic(output_dir=tmp_path, limit_users=2, seed=7)


def test_phase_c_report_schema_status_and_frozen_pool_boundary(tmp_path, monkeypatch):
    report = _run_fixture(tmp_path, monkeypatch)

    assert report["phase"] == "phase_c_ranking_actionability_diagnostic"
    assert report["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert report["top_k"] == REQUIRED_TOP_K
    assert report["actionability_status"]["status"] == "READY_FOR_RANKING_ACTIONABILITY_REVIEW"
    assert report["actionability_status"]["promotion_eligible"] is False
    assert report["actionability_status"]["diagnostic_only"] is True
    assert report["guardrail_status"]["status"] == "PASS"
    assert report["current_recall_mainline"]["mainline_id"] == "source_balanced_pool200_hybrid_recall"
    assert report["current_recall_mainline"]["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert report["current_recall_mainline"]["ranking_scope"] == "ranking_only_on_frozen_candidates_from_current_recall_mainline"
    assert report["promotion_boundary"]["recall_semantics_changed"] is False
    assert report["promotion_boundary"]["merge_for_user_changed"] is False
    assert report["promotion_boundary"]["promotion_eligible"] is False
    assert report["guardrail_status"]["checks"]["candidate_pool_size_200"] is True
    assert report["guardrail_status"]["checks"]["top_k_5"] is True
    assert report["guardrail_status"]["checks"]["current_recall_mainline_fixed"] is True
    assert report["guardrail_status"]["checks"]["frozen_candidates_match"] is True
    assert report["guardrail_status"]["checks"]["diagnostic_not_promotable"] is True
    assert report["guardrail_status"]["checks"]["artifact_inspection_pass"] is True
    assert report["guardrail_status"]["checks"]["online_metric_claims_empty"] is True
    assert Path(report["artifact_paths"]["ranking_actionability_report_path"]).exists()


def test_phase_c_defines_oracle_at_5_and_target_rank_percentile(tmp_path, monkeypatch):
    report = _run_fixture(tmp_path, monkeypatch)
    oracle = report["oracle_at_5"]
    target_rank = report["target_rank_percentile"]

    assert oracle["definition"].startswith("Upper-bound hit_rate@5")
    assert oracle["value"] == 0.5
    assert oracle["source_metric"] == "candidate_hit_rate_at_pool"
    assert target_rank["case_count"] == 2
    assert target_rank["rank_min"] == 4
    assert target_rank["rank_median"] == 6.0
    assert target_rank["rank_p90"] == 8
    assert target_rank["percentile_median"] == 0.03
    assert target_rank["missed_top5_but_hit_top20_users"] == 1


def test_phase_c_reports_source_exposure_and_duplicate_source_balance(tmp_path, monkeypatch):
    report = _run_fixture(tmp_path, monkeypatch)

    assert report["source_exposure"]["candidate_pool_sources"] == {"itemcf": 3, "popular": 2, "semantic": 3}
    assert report["source_exposure"]["topk_sources"] == {"itemcf": 1, "popular": 7, "semantic": 2}
    assert report["source_exposure"]["target_sources"] == {"itemcf": 2, "semantic": 1}
    assert report["duplicate_source_balance"]["candidate_pool"]["multi_source_count"] == 2
    assert report["duplicate_source_balance"]["candidate_pool"]["single_source_count"] == 4
    assert report["duplicate_source_balance"]["candidate_pool"]["multi_source_rate"] == 0.333333
    assert report["duplicate_source_balance"]["candidate_pool"]["source_combinations"]["itemcf+semantic"] == 2


def test_phase_c_reports_win_tie_loss_against_baseline_without_promotion(tmp_path, monkeypatch):
    report = _run_fixture(tmp_path, monkeypatch)

    assert report["win_tie_loss"]["definition"].startswith("win means")
    assert report["win_tie_loss"]["cases_compared"] == 2
    assert report["win_tie_loss"]["win"] == 1
    assert report["win_tie_loss"]["tie"] == 0
    assert report["win_tie_loss"]["loss"] == 1
    assert report["promotion_boundary"]["report_is_current_promotion_evidence"] is False
    assert report["evidence_boundary"]["promotion_claim"] == "none"


def test_phase_c_rejects_online_metric_claims_as_current_evidence(tmp_path, monkeypatch):
    report = _run_fixture(tmp_path, monkeypatch)

    assert report["online_metric_claims"]["accepted"] == []
    assert report["online_metric_claims"]["rejected"] == []
    assert report["evidence_boundary"]["promotion_claim"] == "none"
    assert report["evidence_boundary"]["not_current_promotion_evidence"] == runner.ONLINE_METRIC_NAMES
    assert report["promotion_boundary"]["online_ctr_cvr_gmv_p95_slo_agent_feedback_forbidden_as_current_promotion_evidence"] is True
    assert report["guardrail_status"]["checks"]["online_metric_claims_empty"] is True
    assert "ctr" in report["online_metric_claims"]["forbidden_metric_names"]
