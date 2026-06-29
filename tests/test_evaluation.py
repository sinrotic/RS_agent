from __future__ import annotations

import pytest

from rs_core.recsys.evaluation import evaluate, inspect_physical_ranking_pipeline_artifacts

pytestmark = pytest.mark.unit
from rs_core.common.recsys_types import MergedCandidate, RankingResult


def test_evaluate_core_recall_metrics_on_small_sample():
    candidates_by_user = {
        "u1": [
            MergedCandidate("target", ["graph"], {"graph": 3.0}),
            MergedCandidate("shared", ["popular", "semantic"], {"popular": 2.0, "semantic": 2.0}),
            MergedCandidate("semantic_only", ["semantic"], {"semantic": 1.0}),
        ],
        "u2": [],
    }
    rankings_by_user = {
        "u1": RankingResult("u1", [{"parent_asin": "target", "sources": ["graph"], "category": "Audio"}]),
        "u2": RankingResult("u2", []),
    }
    holdout_records = [
        {"user_id": "u1", "parent_asin": "target", "label_binary": 1},
        {"user_id": "u2", "parent_asin": "missing", "label_binary": 1},
    ]

    summary = evaluate(
        candidates_by_user,
        rankings_by_user,
        holdout_records,
        {
            "top_k": 1,
            "candidate_metric_cutoffs": [1, 2, 3, 5],
            "candidate_pool_size": 3,
            "catalog_size": 6,
            "baseline_candidate_hit_users": 0,
            "pool_displacement_risk": "low",
        },
    ).to_dict()

    assert summary["users_total"] == 2
    assert summary["users_evaluated"] == 2
    assert summary["candidate_count_avg"] == 1.5
    assert summary["empty_candidate_users"] == 1
    assert summary["empty_candidate_rate"] == 0.5
    assert summary["user_candidate_coverage_rate"] == 0.5
    assert summary["candidate_count_min"] == 0
    assert summary["candidate_count_p50"] == 1.5
    assert summary["candidate_count_p90"] == 3.0
    assert summary["candidate_count_max"] == 3
    assert summary["candidate_hit_rate_at_cutoffs"] == {"1": 0.5, "2": 0.5, "3": 0.5}
    assert summary["candidate_recall_at_cutoffs"] == {"1": 0.5, "2": 0.5, "3": 0.5}
    assert summary["catalog_candidate_coverage_count"] == 3
    assert summary["catalog_candidate_coverage_rate"] == 0.5
    assert summary["source_user_coverage"] == {"graph": 1, "popular": 1, "semantic": 1}
    assert summary["source_item_coverage"] == {"graph": 1, "popular": 1, "semantic": 2}
    assert summary["source_marginal_candidate_hit_users"] == {"graph": 1}
    assert summary["source_marginal_candidate_hit_rate"] == {"graph": 0.5}
    assert summary["candidate_hit_users"] == 1
    assert summary["candidate_hit_rate_at_pool"] == 0.5
    assert summary["recall_at_pool"] == 0.5
    assert summary["source_overlap"]["source_pair_counts"] == {"popular+semantic": 1}
    assert summary["source_overlap"]["source_pair_jaccard"] == {
        "graph+popular": 0.0,
        "graph+semantic": 0.0,
        "popular+semantic": 0.5,
    }
    assert summary["method_card_diagnostics"] == {
        "schema_version": "recall_method_card_diagnostics_v1",
        "canonical_baseline": "semantic_title_category_expansion",
        "experiment_scope": "fixed_contract_candidate_eval",
        "evidence_level": "same_contract_verified",
        "decision_options": ["promote", "reject", "defer", "fallback", "document_only"],
        "forbidden_promotion_metrics": [
            "hit_rate_at_k",
            "ndcg",
            "mrr",
            "map",
            "topk_hit_rate",
            "topk_hit_users",
            "ranking_gap_pool_has_target",
            "ltr_score",
            "rerank_score",
            "ctr",
            "cvr",
            "gmv",
        ],
        "candidate_pool_size": 3,
        "users_with_holdout": 2,
        "baseline_candidate_hit_users": 0,
        "candidate_hit_users": 1,
        "marginal_candidate_hit_users": 1,
        "source_marginal_candidate_hit_users": {"graph": 1},
        "source_candidate_count_before_cap": 3,
        "source_candidate_count_after_cap": 3,
        "pool_displacement_risk": "low",
        "can_promote": True,
        "decision_hint": "promote",
    }

    conservative_summary = evaluate(
        candidates_by_user,
        rankings_by_user,
        holdout_records,
        {"top_k": 1, "candidate_pool_size": 3},
    ).to_dict()
    assert conservative_summary["method_card_diagnostics"]["pool_displacement_risk"] == "unknown"
    assert conservative_summary["method_card_diagnostics"]["can_promote"] is False
    assert conservative_summary["method_card_diagnostics"]["decision_hint"] == "defer"


def test_physical_artifact_inspection_requires_stage_paths_and_rejects_online_metric_claims(tmp_path):
    trace_path = tmp_path / "ranking_stage_trace.jsonl"
    summary_path = tmp_path / "ranking_stage_summary.json"
    trace_path.write_text("{}\n", encoding="utf-8")
    summary_path.write_text("{}", encoding="utf-8")
    base_summary = {
        "trace_path": str(trace_path),
        "summary_path": str(summary_path),
        "candidate_pool_size": 200,
        "top_k": 5,
        "stage_counts": {"coarse": 4, "fine": 4, "rerank": 4},
        "pass_through_stage_counts": {"coarse": 4, "fine": 4, "rerank": 4},
        "total_ranked_items": 4,
        "online_metrics": {},
        "online_metric_claims": [],
    }

    pass_summary = inspect_physical_ranking_pipeline_artifacts(base_summary)
    missing_stage_path = inspect_physical_ranking_pipeline_artifacts(base_summary | {"trace_path": str(tmp_path / "missing.jsonl")})
    online_claim = inspect_physical_ranking_pipeline_artifacts(base_summary | {"online_metrics": {"ctr": 0.1}})
    pass_through_failure = inspect_physical_ranking_pipeline_artifacts(base_summary | {"stage_counts": {"coarse": 4, "fine": 3, "rerank": 4}})

    assert pass_summary["schema_version"] == "ranking_artifact_inspection_v1"
    assert pass_summary["status"] == "PASS"
    assert missing_stage_path["status"] == "INVALID"
    assert missing_stage_path["missing_artifacts"] == ["trace_path"]
    assert online_claim["status"] == "INVALID"
    assert online_claim["online_metric_claims"] == ["ctr"]
    assert pass_through_failure["status"] == "INVALID"
    assert pass_through_failure["pass_through_stage_failures"] == ["fine"]
