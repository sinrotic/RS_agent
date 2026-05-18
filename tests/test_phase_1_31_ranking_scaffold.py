from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.experiment

from rs_core.workflow.ranking_experiments import (
    REQUIRED_CANDIDATE_POOL_SIZE,
    REQUIRED_TOP_K,
    RankingMethodSpec,
    build_blocked_ranking_run_row,
    build_ranking_run_row,
)
from rs_lab.experiments.ranking import run_phase_1_31_ranking_algorithm_scaffold as runner


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
        '{"trace_path":"'
        + str(paths["ranking_stage_trace_path"]).replace("\\", "\\\\")
        + '","summary_path":"'
        + str(paths["ranking_stage_summary_path"]).replace("\\", "\\\\")
        + '","candidate_pool_size":200,"top_k":5,"stage_counts":{"coarse":2,"fine":2,"rerank":2},"pass_through_stage_counts":{"coarse":2,"fine":2,"rerank":2},"total_ranked_items":2,"online_metrics":{},"online_metric_claims":[]}\n',
        encoding="utf-8",
    )
    return {key: str(value) for key, value in paths.items()}


def _executable_row(output_dir: Path, spec: RankingMethodSpec, run_kind: str, run_index: int) -> dict:
    status = {
        "baseline": {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}},
        "diagnostic": {"status": "PARTIAL diagnostic-only", "promotable": False, "diagnostic_only": True, "reasons": ["valid_test_promotion_evidence_missing"], "metric_delta": {}},
    }[run_kind]
    return build_ranking_run_row(
        run_id="phase_1_31_ranking_algorithm_scaffold:test",
        run_index=run_index,
        run_kind=run_kind,
        method_spec=spec,
        config={"strategy_name": spec.method_id, "candidate_pool_size": 200, "top_k": 5},
        frozen_rows=FROZEN_ROWS,
        baseline_frozen_rows=FROZEN_ROWS,
        metrics={"hit_rate_at_k": 0.5, "ndcg_at_k": 0.4, "mrr_at_k": 0.3, "map_at_k": 0.2},
        strict_status=status,
        artifact_paths=_touch_artifacts(output_dir, spec.method_id),
        command_text="pytest-scaffold",
    )


def test_ranking_run_rows_require_frozen_pool200_and_top5_for_executable_methods():
    spec = runner.build_method_specs()[1]

    with pytest.raises(ValueError, match="candidate_pool_size=200"):
        build_ranking_run_row(
            run_id="test",
            run_index=1,
            run_kind="diagnostic",
            method_spec=spec,
            config={"candidate_pool_size": 500, "top_k": 5},
            frozen_rows=FROZEN_ROWS,
        )

    with pytest.raises(ValueError, match="candidate_pool_size=200"):
        build_ranking_run_row(
            run_id="test",
            run_index=1,
            run_kind="diagnostic",
            method_spec=spec,
            config={"candidate_pool_size": 500, "top_k": REQUIRED_TOP_K},
            frozen_rows=FROZEN_ROWS,
        )
    with pytest.raises(ValueError, match="top_k=5"):
        build_ranking_run_row(
            run_id="test",
            run_index=1,
            run_kind="diagnostic",
            method_spec=spec,
            config={"candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": 10},
            frozen_rows=FROZEN_ROWS,
        )

def test_spec_only_blocked_method_enters_registry_with_dependency_gpu_and_recovery_fields():
    spec = RankingMethodSpec(
        method_id="dummy_gpu_method_prepare",
        method_family="neural_gpu_ranker",
        stage_target="fine",
        requires_training=True,
        requires_gpu=True,
        dependency="torch",
        promotion_lane="blocked",
        blocked_recovery_condition="verify dependency and GPU before enabling runner",
    )

    row = build_blocked_ranking_run_row(
        run_id="test",
        run_index=9,
        method_spec=spec,
        dependency_available=False,
        gpu_available=False,
        blocked_reason="runner_not_copied",
    )

    assert "ranking_experiment_registry" not in row
    assert row["status"] == "BLOCKED"
    assert row["dependency_status"] == {"dependency": "torch", "available": False, "status": "missing"}
    assert row["gpu_resource"]["status"] == "blocked-gpu-unavailable"
    assert "dependency_missing_or_unverified" in row["blocked_reason"]
    assert "gpu_required_not_verified" in row["blocked_reason"]
    assert "runner_not_copied" in row["blocked_reason"]
    assert row["blocked_recovery_condition"] == "verify dependency and GPU before enabling runner"
    assert row["method_registry_entry"]["method_id"] == "dummy_gpu_method_prepare"
    assert row["method_registry_entry"]["state"] == "blocked"
    assert row["method_registry_entry"]["gpu_resource"]["dependency_status"] == "missing"


def test_phase_1_31_runner_contract_records_executable_diagnostic_and_blocked_methods(tmp_path, monkeypatch):
    specs = runner.build_method_specs()
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run")
    monkeypatch.setattr(runner, "_gpu_check", lambda: {"available": False, "status": "missing", "checked_by": "pytest", "device": None})
    monkeypatch.setattr(
        runner,
        "_dependency_checks",
        lambda method_specs: {
            spec.method_id: {
                "dependency": spec.dependency,
                "available": None if spec.dependency is None else False,
                "status": "not_required" if spec.dependency is None else "missing",
                "checked_by": "pytest",
            }
            for spec in method_specs
        },
    )
    monkeypatch.setattr(runner, "_run_baseline", lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _executable_row(output_dir, method_spec, "baseline", 0))
    monkeypatch.setattr(runner, "_run_rule_variant", lambda output_dir, limit_users, feature_contract, method_spec, baseline_row, run_id, command_text: _executable_row(output_dir, method_spec, "diagnostic", 1))
    monkeypatch.setattr(runner, "_run_ltr_variant", lambda output_dir, limit_users, feature_contract, method_spec, baseline_row, run_id, command_text, seed: _executable_row(output_dir, method_spec, "diagnostic", 2))

    comparison = runner.run_phase_1_31_ranking_algorithm_scaffold(output_dir=tmp_path, limit_users=2, seed=7)

    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}
    registry_by_id = {row["method_id"]: row for row in comparison["method_registry"]}

    assert comparison["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert comparison["top_k"] == REQUIRED_TOP_K
    assert comparison["promotion_policy"]["lo_po_gate_smoke_stage_trace_not_promotion_evidence"] is True
    assert comparison["promotion_policy"]["online_metrics_forbidden_as_current_offline_evidence"] is True
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["physical_pipeline_inspection"]["status"] == "PASS"
    assert set(runs_by_id) == {spec.method_id for spec in specs}
    assert runs_by_id["same_run_baseline"]["run_kind"] == "baseline"
    assert runs_by_id["normalized_additive_source_aware_rule_rerank"]["run_kind"] == "diagnostic"
    assert runs_by_id["pointwise_logistic_fine_ranker_lopo"]["run_kind"] == "diagnostic"
    assert runs_by_id["normalized_additive_source_aware_rule_rerank"]["promotion_eligible"] is False
    assert runs_by_id["pointwise_logistic_fine_ranker_lopo"]["diagnostic_only"] is True
    assert registry_by_id["same_run_baseline"]["state"] == "champion"
    assert registry_by_id["normalized_additive_source_aware_rule_rerank"]["state"] == "diagnostic"
    assert registry_by_id["pointwise_logistic_fine_ranker_lopo"]["state"] == "diagnostic"
    for method_id in ["sklearn_gbdt_fine_ranker_prepare", "xgboost_lambdamart_fine_ranker_prepare", "lightgbm_lambdamart_fine_ranker_prepare"]:
        assert runs_by_id[method_id]["run_kind"] == "blocked"
        assert registry_by_id[method_id]["state"] == "blocked"
        assert runs_by_id[method_id]["dependency_status"]["status"] == "missing"
        assert runs_by_id[method_id]["blocked_recovery_condition"]
    for method_id in ["xgboost_lambdamart_fine_ranker_prepare", "lightgbm_lambdamart_fine_ranker_prepare"]:
        assert runs_by_id[method_id]["gpu_resource"]["status"] == "blocked-gpu-unavailable"
        assert "gpu_required_not_verified" in runs_by_id[method_id]["blocked_reason"]


def test_lopo_gate_smoke_stage_trace_and_online_metrics_do_not_create_promotion_evidence(tmp_path):
    spec = runner.build_method_specs()[2]
    row = _executable_row(tmp_path, spec, "diagnostic", 2)
    row["strict_status"] = row["strict_status"] | {
        "reasons": [
            "lopo_training_diagnostic_only",
            "feature_contract_gate_passed",
            "smoke_run_only",
            "stage_trace_artifacts_present",
        ]
    }

    assert row["promotion_eligible"] is False
    assert row["diagnostic_only"] is True
    assert row["ranking_experiment_registry"]["status"]["promotable"] is False
    assert row["ranking_experiment_registry"]["status"]["diagnostic_only"] is True
