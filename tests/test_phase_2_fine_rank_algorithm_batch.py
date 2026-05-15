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
    return pytest.importorskip("scripts.run_phase_2_fine_rank_algorithm_batch")


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
                "stage_counts": {"coarse": 2, "fine": 2},
                "pass_through_stage_counts": {"coarse": 2, "fine": 2},
                "total_ranked_items": 2,
                "online_metrics": {},
                "online_metric_claims": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {key: str(value) for key, value in paths.items()}


def _executable_row(output_dir: Path, spec: RankingMethodSpec, run_kind: str, run_index: int) -> dict:
    strict_status = {
        "baseline": {
            "status": "BASELINE",
            "promotable": False,
            "diagnostic_only": False,
            "reasons": ["same_run_baseline"],
            "metric_delta": {},
        },
        "diagnostic": {
            "status": "PARTIAL diagnostic-only",
            "promotable": False,
            "diagnostic_only": True,
            "reasons": [
                "lopo_training_diagnostic_only",
                "phase_2_valid_test_promotion_split_missing",
                "learned_ranker_boundary_diagnostic_only",
            ],
            "metric_delta": {},
        },
    }[run_kind]
    row = build_ranking_run_row(
        run_id="phase_2_fine_rank_algorithm_batch:test",
        run_index=run_index,
        run_kind=run_kind,
        method_spec=spec,
        config={
            "strategy_name": spec.method_id,
            "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
            "top_k": REQUIRED_TOP_K,
        },
        frozen_rows=FROZEN_ROWS,
        baseline_frozen_rows=FROZEN_ROWS,
        metrics={"hit_rate_at_k": 0.5, "ndcg_at_k": 0.4, "mrr_at_k": 0.3, "map_at_k": 0.2},
        strict_status=strict_status,
        artifact_paths=_touch_artifacts(output_dir, spec.method_id),
        command_text="pytest-fine-rank-batch",
    )
    row["raw_metrics"] = {
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "config_summary": {"candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE, "top_k": REQUIRED_TOP_K},
    }
    row["frozen_rows"] = FROZEN_ROWS
    return row


def test_batch_2_4_executable_methods_target_fine_stage_and_fixed_pool_topk(runner):
    specs = runner.build_method_specs()
    batch_specs = [spec for spec in specs if str(spec.metadata.get("algorithm_batch", "")).startswith(("batch_2", "batch_3", "batch_4"))]

    assert batch_specs
    assert all(spec.stage_target == "fine" for spec in batch_specs)
    assert all("rerank" not in spec.method_id for spec in batch_specs)
    assert all("rerank" not in spec.method_family for spec in batch_specs)
    assert runner.REQUIRED_CANDIDATE_POOL_SIZE == REQUIRED_CANDIDATE_POOL_SIZE
    assert runner.REQUIRED_TOP_K == REQUIRED_TOP_K


def test_learned_ltr_specs_are_diagnostic_only_and_explicitly_not_promotion_candidates(runner):
    learned_specs = [
        spec
        for spec in runner.build_method_specs()
        if spec.promotion_lane != "blocked"
        and (spec.requires_training or "ltr" in spec.method_id or "logistic" in spec.method_id or "perceptron" in spec.method_id)
    ]

    assert learned_specs
    for spec in learned_specs:
        assert spec.stage_target == "fine"
        assert spec.diagnostic_only is True
        assert spec.promotion_eligible is False
        assert "diagnostic" in spec.promotion_lane
        boundary_text = " ".join(
            str(value)
            for value in [
                spec.blocked_recovery_condition,
                *spec.metadata.values(),
            ]
        ).lower()
        assert "diagnostic" in boundary_text
        assert "valid/test" in boundary_text or "promotion" in boundary_text


def test_fine_rank_batch_runner_records_diagnostics_blockers_and_no_rerank_or_online_promotion(tmp_path, monkeypatch, runner):
    monkeypatch.setattr(runner, "_run_id", lambda: "test-run", raising=False)
    monkeypatch.setattr(
        runner,
        "_gpu_check",
        lambda: {"available": False, "status": "missing", "checked_by": "pytest", "device": None},
        raising=False,
    )
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
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "_run_baseline",
        lambda output_dir, limit_users, feature_contract, method_spec, run_id, command_text: _executable_row(
            output_dir, method_spec, "baseline", 0
        ),
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "_run_rule_variants",
        lambda output_dir, limit_users, feature_contract, method_specs, baseline_row, run_id, command_text: [
            _executable_row(output_dir, spec, "diagnostic", index) for index, spec in enumerate(method_specs, start=1)
        ],
    )

    comparison = runner.run_phase_2_fine_rank_algorithm_batch(output_dir=tmp_path, limit_users=2, seed=7)
    runs_by_id = {row["candidate_id"]: row for row in comparison["runs"]}

    assert comparison["candidate_pool_size"] == REQUIRED_CANDIDATE_POOL_SIZE
    assert comparison["top_k"] == REQUIRED_TOP_K
    assert comparison["promotion_boundary"]["lopo_gate_smoke_stage_trace_training_loss_online_metrics_not_promotion_evidence"] is True
    non_baseline_rows = [row for row in comparison["runs"] if row["run_kind"] != "baseline"]
    assert all(row["stage_target"] == "fine" for row in non_baseline_rows)
    assert all("rerank" not in row["candidate_id"] and row.get("stage_target") != "rerank" for row in non_baseline_rows)

    learned_rows = [
        row
        for row in comparison["runs"]
        if row["run_kind"] == "diagnostic" and ("ltr" in row["candidate_id"] or "logistic" in row["candidate_id"] or "perceptron" in row["candidate_id"])
    ]
    assert learned_rows
    for row in learned_rows:
        assert row["diagnostic_only"] is True
        assert row["promotion_eligible"] is False
        assert row["strict_status"]["promotable"] is False
        assert row["strict_status"]["diagnostic_only"] is True
        assert any("diagnostic" in reason for reason in row["strict_status"]["reasons"])
        assert any("promotion" in reason for reason in row["strict_status"]["reasons"])

    blocked_ids = [method_id for method_id in runs_by_id if "gbdt" in method_id or "lambdamart" in method_id]
    assert blocked_ids
    for method_id in blocked_ids:
        row = runs_by_id[method_id]
        assert row["run_kind"] == "blocked"
        assert row["status"] == "BLOCKED"
        assert row["blocked_recovery_condition"]
        assert row["dependency_status"]["status"] in {"missing", "not_checked"}
        assert "dependency_missing_or_unverified" in row["blocked_reason"]
        assert row["gpu_resource"]["status"] in {"blocked-gpu-unavailable", "not_required", "unknown"}
        if "lambdamart" in method_id:
            assert "gpu_required_not_verified" in row["blocked_reason"]
            assert row["gpu_resource"]["status"] == "blocked-gpu-unavailable"

    assert comparison["promotion_boundary"]["lopo_gate_smoke_stage_trace_training_loss_online_metrics_not_promotion_evidence"] is True
