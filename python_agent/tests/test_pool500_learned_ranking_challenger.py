from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rs_core.common.recsys_types import MergedCandidate
from rs_lab.experiments.recall.run_pool500_learned_ranking_challenger import _challenger_config, _frozen_candidate_equality, run_pool500_learned_ranking_challenger

pytestmark = pytest.mark.unit


def test_challenger_config_does_not_enable_untrained_lightgbm_model() -> None:
    config = _challenger_config({"model_type": "lightgbm_lambdamart_ltr_v1", "training": {"status": "dependency_unavailable"}})

    assert config["ltr_model"]["enabled"] is False


def test_challenger_config_keeps_underpowered_ltr_out_of_ranking() -> None:
    config = _challenger_config(
        {
            "model_type": "lightgbm_lambdamart_ltr_v1",
            "booster_model": "trained-model-placeholder",
            "training": {"status": "trained", "positive_rows": 1, "positive_users": 1},
        }
    )

    assert config["coarse_ranking"]["source_score_calibration"]["category"]["scale"] == 1.0
    assert config["ltr_model"]["enabled"] is False
    assert config["ltr_model"]["eligibility"]["reason"] == "underpowered_ltr_training_labels"


def _write_json(path: Path, payload: dict[str, object]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _eligible_report(tmp_path: Path, *, label_metric_eligibility: bool = True) -> tuple[Path, str]:
    path = tmp_path / "comparison_report.json"
    digest = _write_json(
        path,
        {
            "schema_version": "pool500_fixed_ranking_comparison_report_v1",
            "label_metric_eligibility": label_metric_eligibility,
            "label_ineligible_reason": None if label_metric_eligibility else "label_insufficient",
            "label_metric_definition_version": "pool500_label_metrics_per_user_mean_v1",
            "promotion_readiness": "not_allowed_in_this_report",
        },
    )
    return path, digest


def _write_gate_inputs(tmp_path: Path) -> tuple[Path, Path]:
    candidates = tmp_path / "pool500_candidates.jsonl"
    labels = tmp_path / "train_labels.jsonl"
    _write_jsonl(
        candidates,
        [
            {"user_id": "u1", "item_id": "i_pos", "source": "itemcf_strong", "score": 1.0, "rank": 1, "metadata": {"category": "cat_a", "recent_pop_score": 0.8}},
            {"user_id": "u1", "item_id": "i_neg", "source": "popular", "score": 0.5, "rank": 2, "metadata": {"category": "cat_b"}},
        ],
    )
    _write_jsonl(labels, [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i_pos", "label_binary": 1, "split": "train"}])
    return candidates, labels


def _blocker_codes(report: dict[str, object]) -> set[str]:
    return {str(blocker["code"]) for blocker in report["blockers"]}  # type: ignore[index]


def test_learned_ranking_challenger_fails_closed_without_report_path_and_hash(tmp_path: Path) -> None:
    report = run_pool500_learned_ranking_challenger(output_dir=tmp_path / "out", enforce_venv=False)

    assert report["would_be_eligible"] is False
    assert report["current_phase_training_enabled"] is False
    assert "agent_ready_ranked_artifact" not in report["output_paths"]
    assert not (tmp_path / "out" / "agent_ready_ranked_artifact.json").exists()
    assert {"POOL500_LEARNED_CHALLENGER_FIXED_REPORT_PATH_REQUIRED", "POOL500_LEARNED_CHALLENGER_FIXED_REPORT_HASH_REQUIRED"} <= _blocker_codes(report)


def test_learned_ranking_challenger_fails_closed_on_report_hash_mismatch(tmp_path: Path) -> None:
    report_path, _digest = _eligible_report(tmp_path)
    candidates, labels = _write_gate_inputs(tmp_path)

    report = run_pool500_learned_ranking_challenger(
        fixed_comparison_report_path=report_path,
        expected_fixed_comparison_report_sha256="0" * 64,
        rule_diagnostics_plateau_evidence=True,
        pool500_candidates_path=candidates,
        train_label_artifact_path=labels,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["would_be_eligible"] is False
    assert "POOL500_LEARNED_CHALLENGER_FIXED_REPORT_HASH_MISMATCH" in _blocker_codes(report)
    assert "agent_ready_ranked_artifact" not in report["output_paths"]


def test_learned_ranking_challenger_requires_label_metric_eligibility(tmp_path: Path) -> None:
    report_path, digest = _eligible_report(tmp_path, label_metric_eligibility=False)
    candidates, labels = _write_gate_inputs(tmp_path)

    report = run_pool500_learned_ranking_challenger(
        fixed_comparison_report_path=report_path,
        expected_fixed_comparison_report_sha256=digest,
        rule_diagnostics_plateau_evidence=True,
        pool500_candidates_path=candidates,
        train_label_artifact_path=labels,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["learned_ranking_gate"]["label_metric_eligibility_gate"]["status"] == "STOP"
    assert report["would_be_eligible"] is False
    assert "POOL500_LEARNED_CHALLENGER_LABEL_METRIC_INELIGIBLE" in _blocker_codes(report)
    assert not (tmp_path / "out" / "agent_ready_ranked_artifact.json").exists()


def test_learned_ranking_challenger_requires_explicit_rule_plateau_evidence(tmp_path: Path) -> None:
    report_path, digest = _eligible_report(tmp_path)
    candidates, labels = _write_gate_inputs(tmp_path)

    report = run_pool500_learned_ranking_challenger(
        fixed_comparison_report_path=report_path,
        expected_fixed_comparison_report_sha256=digest,
        pool500_candidates_path=candidates,
        train_label_artifact_path=labels,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["learned_ranking_gate"]["rule_diagnostics_plateau_gate"]["status"] == "STOP"
    assert report["would_be_eligible"] is False
    assert "POOL500_LEARNED_CHALLENGER_RULE_PLATEAU_EVIDENCE_MISSING" in _blocker_codes(report)


def test_learned_ranking_challenger_all_gates_pass_stays_frozen(tmp_path: Path) -> None:
    report_path, digest = _eligible_report(tmp_path)
    candidates, labels = _write_gate_inputs(tmp_path)

    report = run_pool500_learned_ranking_challenger(
        fixed_comparison_report_path=report_path,
        expected_fixed_comparison_report_sha256=digest,
        rule_diagnostics_plateau_evidence=True,
        pool500_candidates_path=candidates,
        train_label_artifact_path=labels,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["would_be_eligible"] is True
    assert report["current_phase_training_enabled"] is False
    assert report["model"] is None
    assert report["promotion_allowed"] is False
    assert report["promotion_readiness"] == "not_allowed_in_current_phase"
    assert report["learned_ranking_gate"]["feature_contract_gate"]["status"] == "PASS"
    assert report["learned_ranking_gate"]["leakage_gate"]["status"] == "PASS"
    assert report["output_paths"] == {"comparison_json": str(tmp_path / "out" / "comparison.json"), "comparison_md": str(tmp_path / "out" / "comparison.md")}
    assert Path(report["output_paths"]["comparison_json"]).is_file()
    assert Path(report["output_paths"]["comparison_md"]).is_file()
    assert not (tmp_path / "out" / "agent_ready_ranked_artifact.json").exists()


def test_frozen_candidate_equality_allows_different_topk_order_and_membership_when_items_are_frozen() -> None:
    candidates_by_user = {
        "u1": [
            MergedCandidate("a", ["popular"], {"popular": 1.0}),
            MergedCandidate("b", ["semantic"], {"semantic": 1.0}),
            MergedCandidate("c", ["itemcf_strong"], {"itemcf_strong": 1.0}),
        ]
    }
    baseline = {"u1": [{"parent_asin": "a"}, {"parent_asin": "b"}]}
    challenger = {"u1": [{"parent_asin": "c"}, {"parent_asin": "a"}]}

    result = _frozen_candidate_equality([], candidates_by_user, baseline, challenger)

    assert result["status"] == "PASS"
    assert result["baseline_challenger_diff_pair_count"] == 2
    assert result["baseline_extra_pair_count"] == 0
    assert result["challenger_extra_pair_count"] == 0


def test_frozen_candidate_equality_stops_when_challenger_adds_non_frozen_item() -> None:
    candidates_by_user = {"u1": [MergedCandidate("a", ["popular"], {"popular": 1.0})]}
    baseline = {"u1": [{"parent_asin": "a"}]}
    challenger = {"u1": [{"parent_asin": "not_frozen"}]}

    result = _frozen_candidate_equality([], candidates_by_user, baseline, challenger)

    assert result["status"] == "STOP"
    assert result["challenger_extra_pair_count"] == 1
    assert result["mismatches"][0]["challenger_not_in_candidate"] == ["not_frozen"]
