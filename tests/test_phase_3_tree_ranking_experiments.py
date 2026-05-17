from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.experiment, pytest.mark.slow]

from rs_core.workflow.ranking_experiments import (
    REQUIRED_CANDIDATE_POOL_SIZE,
    REQUIRED_TOP_K,
    RankingMethodSpec,
    build_ranking_run_row,
)


@pytest.fixture
def runner():
    return pytest.importorskip("scripts.experiments.ranking.run_phase_3_tree_ranking_experiments")


FROZEN_ROWS = [
    {"user_id": "u1", "candidate_rank": 1, "item_id": "i1"},
    {"user_id": "u1", "candidate_rank": 2, "item_id": "i2"},
]


def _touch_artifacts(output_dir: Path, method_id: str) -> dict[str, str]:
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
    for path in paths.values():
        path.write_text("{}\n", encoding="utf-8")
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


def _baseline_row(output_dir: Path, spec: RankingMethodSpec) -> dict:
    raw_metrics = {
        "hit_rate_at_k": 0.5,
        "ndcg_at_k": 0.4,
        "mrr_at_k": 0.3,
        "map_at_k": 0.2,
        "candidate_hit_missed_topk_users": 1,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "config_summary": {"candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": REQUIRED_TOP_K},
    }
    row = build_ranking_run_row(
        run_id="phase_3_tree_ranking_experiments:test-run",
        run_index=0,
        run_kind="baseline",
        method_spec=spec,
        config={
            "strategy_name": spec.method_id,
            "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
            "top_k": REQUIRED_TOP_K,
        },
        frozen_rows=FROZEN_ROWS,
        metrics=raw_metrics,
        strict_status={
            "status": "BASELINE",
            "promotable": False,
            "diagnostic_only": False,
            "reasons": ["same_run_baseline", "frozen_pool200_boundary"],
            "metric_delta": {},
        },
        artifact_paths=_touch_artifacts(output_dir, spec.method_id),
        command_text="pytest-phase-3",
    )
    row["raw_metrics"] = raw_metrics
    row["frozen_rows"] = FROZEN_ROWS
    return row


def _candidate_training_summary(output_dir: Path) -> dict:
    training_dir = output_dir / "candidate_training_data"
    training_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "candidate_rows_path": training_dir / "candidate_rows.jsonl",
        "metrics_path": training_dir / "metrics.json",
        "model_path": training_dir / "model.json",
        "training_config_path": training_dir / "training_config.json",
        "summary_path": training_dir / "candidate_training_data_summary.json",
    }
    paths["candidate_rows_path"].write_text(
        '\n'.join(
            [
                json.dumps({"user_id": "u1", "item_id": "i1", "label": 1, "features": {"score": 1.0}}),
                json.dumps({"user_id": "u1", "item_id": "i2", "label": 0, "features": {"score": 0.1}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for key, path in paths.items():
        if key != "candidate_rows_path":
            path.write_text("{}\n", encoding="utf-8")
    return {
        "schema_version": "phase_3_candidate_training_data_v1",
        "status": "PASS",
        "seed": 7,
        "evaluation_mode": "leave_one_positive_out",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "reasons": ["lopo_training_diagnostic_only", "valid_test_promotion_gate_missing"],
        "row_count": 2,
        "positive_rows": 1,
        "negative_rows": 1,
        "group_count": 1,
        "min_group_size": 2,
        "max_group_size": 2,
        "feature_contract_gate": {"status": "PASS"},
        "leakage_gate": {"status": "PASS"},
        **{key: str(path) for key, path in paths.items()},
    }


def _fake_tree_training(output_dir: Path, rows_path: Path, seed: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "model_path": output_dir / "sklearn_gbdt_model.pkl",
        "metrics_path": output_dir / "metrics.json",
        "training_config_path": output_dir / "training_config.json",
        "training_log_path": output_dir / "training_log.json",
    }
    metrics = {
        "schema_version": "phase_3_tree_training_metrics_v1",
        "model_type": "sklearn_gradient_boosting_classifier",
        "objective": "pointwise_binary_relevance",
        "seed": seed,
        "candidate_rows_path": str(rows_path),
        "promotion_eligible": False,
        "diagnostic_only": True,
        "reasons": [
            "sklearn_gbdt_real_training_complete",
            "tree_serving_adapter_missing",
            "valid_test_promotion_gate_missing",
            "lopo_training_diagnostic_only",
        ],
    }
    for path in paths.values():
        path.write_text(json.dumps(metrics) + "\n", encoding="utf-8")
    return {
        "state": "diagnostic",
        "status": "diagnostic",
        "candidate_rows_path": str(rows_path),
        "metrics": metrics,
        "promotion_eligible": False,
        "diagnostic_only": True,
        "reasons": metrics["reasons"],
        **{key: str(path) for key, path in paths.items()},
    }


def test_phase_3_method_specs_keep_frozen_pool_and_assign_tree_methods_to_fine_stage(runner):
    specs = runner.build_method_specs()
    by_id = {spec.method_id: spec for spec in specs}

    assert runner.REQUIRED_CANDIDATE_POOL_SIZE == REQUIRED_CANDIDATE_POOL_SIZE
    assert runner.REQUIRED_TOP_K == REQUIRED_TOP_K
    assert runner.BASELINE_CONFIG.name == "phase_1_25_pool200_same_run_baseline.yaml"
    assert by_id["same_run_pool200_baseline"].stage_target == "rerank"
    assert by_id["sklearn_gbdt_pointwise_fine_rank_diagnostic"].stage_target == "fine"
    assert by_id["xgboost_lambdamart_fine_rank_blocked"].stage_target == "fine"
    assert by_id["lightgbm_lambdamart_fine_rank_blocked"].stage_target == "fine"

    for spec in specs[1:]:
        assert spec.promotion_eligible is False
        assert spec.metadata["deterministic_stand_in"] is False
    assert by_id["sklearn_gbdt_pointwise_fine_rank_diagnostic"].diagnostic_only is True
    assert by_id["sklearn_gbdt_pointwise_fine_rank_diagnostic"].metadata["diagnostic_boundary"] == runner.TREE_DIAGNOSTIC_BOUNDARY


def test_phase_3_runner_records_sklearn_diagnostic_and_blocks_lambdamart_without_fake_promotion(tmp_path, monkeypatch, runner):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "_gpu_check", lambda: {"available": False, "status": "missing", "checked_by": "pytest", "device": None})
    monkeypatch.setattr(
        runner,
        "_dependency_checks",
        lambda method_specs: {
            spec.method_id: {
                "dependency": spec.dependency,
                "available": True if spec.dependency == "sklearn" else None if spec.dependency is None else False,
                "status": "available" if spec.dependency == "sklearn" else "not_required" if spec.dependency is None else "missing",
                "checked_by": "pytest",
            }
            for spec in method_specs
        },
    )
    monkeypatch.setattr(
        runner,
        "_run_baseline",
        lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _baseline_row(output_dir, method_spec),
    )
    monkeypatch.setattr(runner, "_prepare_candidate_rows", lambda output_dir, limit_users, seed: _candidate_training_summary(output_dir))
    monkeypatch.setattr(runner, "_train_sklearn_gbdt", _fake_tree_training)

    comparison = runner.run_phase_3_tree_ranking_experiments(output_dir=tmp_path, limit_users=2, seed=7)
    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}

    assert comparison["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert comparison["top_k"] == REQUIRED_TOP_K
    assert comparison["promotion_boundary"]["recall_semantics_changed"] is False
    assert comparison["promotion_boundary"]["merge_for_user_changed"] is False
    assert comparison["promotion_boundary"]["no_deterministic_stand_in"] is True
    assert comparison["promotion_boundary"]["online_metrics_forbidden_as_current_offline_evidence"] is True
    assert comparison["promotion_boundary"]["lopo_gate_smoke_stage_trace_training_loss_online_metrics_not_promotion_evidence"] is True

    sklearn_row = runs_by_id["sklearn_gbdt_pointwise_fine_rank_diagnostic"]
    assert sklearn_row["run_kind"] == "diagnostic"
    assert sklearn_row["stage_target"] == "fine"
    assert sklearn_row["lane"] == "diagnostic"
    assert sklearn_row["promotion_eligible"] is False
    assert sklearn_row["diagnostic_only"] is True
    assert sklearn_row["strict_status"]["promotable"] is False
    assert sklearn_row["strict_status"]["diagnostic_only"] is True
    assert "sklearn_gbdt_real_training_complete" in sklearn_row["strict_status"]["reasons"]
    assert runner.TREE_DIAGNOSTIC_BOUNDARY in sklearn_row["strict_status"]["reasons"]
    assert sklearn_row["tree_training"]["promotion_eligible"] is False
    assert sklearn_row["tree_training"]["diagnostic_only"] is True
    assert sklearn_row["adapter_execution"] == "not_run_no_verified_tree_serving_adapter"
    assert sklearn_row["promotion_evidence_claim"] == "none"
    assert sklearn_row["ranking_experiment_registry"]["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert sklearn_row["ranking_experiment_registry"]["top_k"] == REQUIRED_TOP_K
    assert sklearn_row["frozen_candidate_comparison"]["match"] is True

    for method_id in ["xgboost_lambdamart_fine_rank_blocked", "lightgbm_lambdamart_fine_rank_blocked"]:
        row = runs_by_id[method_id]
        assert row["run_kind"] == "blocked"
        assert row["status"] == "BLOCKED"
        assert row["stage_target"] == "fine"
        assert row["promotion_eligible"] is False
        assert row["diagnostic_only"] is False
        assert row["dependency_status"]["status"] == "missing"
        assert row["gpu_resource"]["status"] == "blocked-gpu-unavailable"
        assert "dependency_missing_or_unverified" in row["blocked_reason"]
        assert "gpu_required_not_verified" in row["blocked_reason"]
        assert "lambda_mart_serving_adapter_missing" in row["blocked_reason"]
        assert "valid_test_promotion_gate_missing" in row["blocked_reason"]
        assert "no_deterministic_stand_in" in row["blocked_reason"]
        assert "rank:ndcg" in row["blocked_recovery_condition"] or "lambdarank" in row["blocked_recovery_condition"]

    assert {row["promotion_eligible"] for row in comparison["runs"]} == {False}
    assert all("online" not in row.get("strict_status", {}).get("reasons", []) for row in comparison["runs"])
    assert comparison["training_artifact_inspection"]["status"] == "PASS"


def test_phase_3_sklearn_dependency_or_candidate_gap_returns_blocked_diagnostic_row(tmp_path, runner):
    specs = runner.build_method_specs()
    baseline = _baseline_row(tmp_path, specs[0])
    candidate_rows = _candidate_training_summary(tmp_path) | {"status": "BLOCKED", "candidate_rows_path": None}

    dependency_blocked = runner._run_sklearn_gbdt_diagnostic(
        tmp_path,
        specs[1],
        baseline,
        _candidate_training_summary(tmp_path),
        {"dependency": "sklearn", "available": False, "status": "missing"},
        "test-run",
        "pytest-phase-3",
        7,
    )
    candidate_blocked = runner._run_sklearn_gbdt_diagnostic(
        tmp_path,
        specs[1],
        baseline,
        candidate_rows,
        {"dependency": "sklearn", "available": True, "status": "available"},
        "test-run",
        "pytest-phase-3",
        7,
    )

    assert dependency_blocked["run_kind"] == "blocked"
    assert dependency_blocked["status"] == "BLOCKED"
    assert dependency_blocked["promotion_eligible"] is False
    assert "dependency_missing_or_unverified" in dependency_blocked["blocked_reason"]
    assert "sklearn_dependency_missing_or_unverified" in dependency_blocked["blocked_reason"]
    assert candidate_blocked["run_kind"] == "blocked"
    assert candidate_blocked["status"] == "BLOCKED"
    assert candidate_blocked["promotion_eligible"] is False
    assert "candidate_rows_missing_or_single_class" in candidate_blocked["blocked_reason"]
    assert "candidate_level_tree_training_not_run" in candidate_blocked["blocked_reason"]
