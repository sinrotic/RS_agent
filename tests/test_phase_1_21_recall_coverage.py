from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.experiment

from rs_core.common.io import write_jsonl
from scripts.experiments.recall import phase_1_21_recall_coverage_experiments as phase_1_21


def test_phase_1_21_baseline_and_audit_write_required_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, baseline_path = _write_fixture(tmp_path)
    baseline_output = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    audit_output = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "audit"
    baseline_before = baseline_path.read_bytes()

    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(baseline_output),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    assert baseline_path.read_bytes() == baseline_before
    manifest = json.loads((baseline_output / "manifest.json").read_text(encoding="utf-8"))
    holdout_payload = json.loads((baseline_output / "holdout_user_ids.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "baseline"
    assert manifest["limit_users"] == 2
    assert manifest["users_with_holdout"] == 2
    assert manifest["evaluation_mode"] == "valid_test"
    assert manifest["hit_rate_denominator"] == "users_with_holdout"
    assert manifest["holdout_user_ids_hash"] == _holdout_hash(["u1", "u2"])
    assert manifest["source_contract_version"] == "phase_1_21_source_contract_v1"
    assert manifest["metrics_contract_version"] == "phase_1_21_metrics_contract_v1"
    assert manifest["source_contract"]["candidate_fields"] == ["item_id", "source", "score", "metadata"]
    assert manifest["metrics_contract"]["denominator"] == "users_with_holdout"
    assert manifest["ranking_rerank_disabled_checks"]["include_ranking_v2"] == "not enabled"
    assert "source index construction" in manifest["no_leakage_contract"]
    assert holdout_payload["holdout_user_ids"] == ["u1", "u2"]
    assert (baseline_output / "metrics.json").is_file()
    benchmark_artifact = json.loads((baseline_output / "source_family_observation_benchmarks.json").read_text(encoding="utf-8"))
    assert manifest["source_family_benchmark_contract_version"] == "source_family_observation_benchmark_v1"
    assert manifest["source_family_observation_benchmarks_path"] == str(baseline_output / "source_family_observation_benchmarks.json")
    assert benchmark_artifact["baseline_metrics_path"] == str(baseline_output / "metrics.json")
    benchmark_by_name = {row["display_name"]: row for row in benchmark_artifact["benchmarks"]}
    assert set(benchmark_by_name) == {
        "popular/category",
        "ItemCF/co-visit",
        "semantic/title-category",
        "graph",
        "vector/two-tower",
        "UserCF",
        "Swing",
        "session/transition",
        "implicit SVD MF",
        "ALS MF",
        "BPR MF",
        "LightFM MF",
        "sequence/multi-interest",
    }
    assert benchmark_by_name["popular/category"]["source_group"] == "popular_rule"
    assert benchmark_by_name["ItemCF/co-visit"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["semantic/title-category"]["source_group"] == "content_semantic"
    assert benchmark_by_name["graph"]["source_group"] == "graph"
    assert benchmark_by_name["vector/two-tower"]["source_group"] == "vector_tower"
    assert benchmark_by_name["UserCF"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["Swing"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["session/transition"]["source_group"] == "sequence_interest"
    assert benchmark_by_name["implicit SVD MF"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["ALS MF"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["BPR MF"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["LightFM MF"]["source_group"] == "cf_behavior"
    assert benchmark_by_name["sequence/multi-interest"]["source_group"] == "sequence_interest"
    assert all(row["lane"] == "observation" for row in benchmark_by_name.values())
    assert all(row["scope_contract"] == "recall_only" for row in benchmark_by_name.values())
    assert all(row["artifact_source"].endswith("registry_artifact") for row in benchmark_by_name.values())
    assert benchmark_by_name["vector/two-tower"]["artifact_source"] == "offline_vector_two_tower_registry_artifact"
    assert benchmark_by_name["ItemCF/co-visit"]["config_patch"]["co_visit_fallback_repair_enabled"] is True
    assert benchmark_by_name["semantic/title-category"]["config_patch"]["semantic_title_category_expansion"]["enabled"] is True
    assert benchmark_by_name["vector/two-tower"]["config_patch"]["two_tower_enabled"] is True
    required_status_fields = {
        "execution_status",
        "evidence_level",
        "execution_command",
        "output_dir",
        "metrics_path",
        "metrics_sha256",
        "failure_reason",
        "invalidation_reason",
        "next_action",
    }
    assert all(required_status_fields <= set(row) for row in benchmark_by_name.values())
    assert benchmark_by_name["popular/category"]["execution_status"] == "EXECUTED_PASS"
    assert benchmark_by_name["popular/category"]["evidence_level"] == "same_contract_verified"
    assert benchmark_by_name["popular/category"]["metrics_path"] == str(baseline_output / "metrics.json")
    assert benchmark_by_name["popular/category"]["metrics_sha256"] == hashlib.sha256((baseline_output / "metrics.json").read_bytes()).hexdigest()
    assert benchmark_by_name["popular/category"]["registration_template"]["gate_status"] == "PASS_OBSERVATION_ONLY"
    assert benchmark_by_name["ItemCF/co-visit"]["execution_status"] == "READY_TO_RUN"
    assert benchmark_by_name["semantic/title-category"]["execution_status"] == "READY_TO_RUN"
    assert benchmark_by_name["graph"]["execution_status"] == "READY_TO_RUN"
    assert "configs/recall/phase_1_21/phase_1_21_recall_coverage_graph.yaml" in benchmark_by_name["graph"]["execution_command"]
    assert benchmark_by_name["graph"]["config_patch"]["item_graph_enabled"] is True
    assert benchmark_by_name["graph"]["config_patch"]["graph_walk_seed_enabled"] is False
    assert benchmark_by_name["vector/two-tower"]["execution_status"] == "READY_TO_RUN"
    assert "configs/recall/phase_1_21/phase_1_21_recall_coverage_vector.yaml" in benchmark_by_name["vector/two-tower"]["execution_command"]
    assert benchmark_by_name["UserCF"]["execution_status"] == "READY_TO_RUN"
    assert benchmark_by_name["Swing"]["execution_status"] == "READY_TO_RUN"
    assert benchmark_by_name["session/transition"]["execution_status"] == "READY_TO_RUN"
    assert benchmark_by_name["implicit SVD MF"]["execution_status"] == "READY_TO_RUN"
    for name in ["ALS MF", "BPR MF", "LightFM MF"]:
        assert benchmark_by_name[name]["execution_status"] in {"blocked_missing_dependency", "READY_TO_RUN"}
        assert benchmark_by_name[name]["dependency_gate"]["required_modules"]
        assert "configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml" in benchmark_by_name[name]["execution_command"]
        if benchmark_by_name[name]["execution_status"] == "blocked_missing_dependency":
            assert benchmark_by_name[name]["next_action"] == "defer_until_dependency_available"
            assert benchmark_by_name[name]["dependency_gate"]["missing_modules"]
    assert benchmark_by_name["sequence/multi-interest"]["execution_status"] == "READY_TO_RUN"
    assert all(
        row["registration_template"]["gate_status"] == "INCONCLUSIVE_MISSING_ARTIFACT"
        for name, row in benchmark_by_name.items()
        if name != "popular/category"
    )
    assert all(not row["metrics_path"] and not row["metrics_sha256"] for name, row in benchmark_by_name.items() if name != "popular/category")
    for name, row in benchmark_by_name.items():
        if name == "popular/category":
            continue
        if name in {"ALS MF", "BPR MF", "LightFM MF"} and row["execution_status"] == "blocked_missing_dependency":
            assert row["evidence_level"] == "dependency_gate"
            assert row["invalidation_reason"] == "not_executed_missing_dependency"
        elif name in {"ALS MF", "BPR MF", "LightFM MF"} and row["execution_status"] == "READY_TO_RUN":
            assert row["evidence_level"] in {"needs_rerun", "dependency_gate_passed_needs_rerun"}
        else:
            assert row["evidence_level"] == "needs_rerun"
            assert row["invalidation_reason"] == "not_executed_no_metrics_artifact"
    assert "hit_rate_at_k" in benchmark_artifact["forbidden_metrics"]
    assert "ndcg" in benchmark_artifact["forbidden_metrics"]
    assert "topk_hit_rate" in benchmark_artifact["forbidden_metrics"]
    assert "topk_hit_users" in benchmark_artifact["forbidden_metrics"]
    assert "ranking_gap_pool_has_target" in benchmark_artifact["forbidden_metrics"]
    metrics = json.loads((baseline_output / "metrics.json").read_text(encoding="utf-8"))
    expected_metric_fields = {
        "empty_candidate_users",
        "empty_candidate_rate",
        "user_candidate_coverage_rate",
        "candidate_count_min",
        "candidate_count_p50",
        "candidate_count_p90",
        "candidate_count_max",
        "candidate_hit_rate_at_cutoffs",
        "candidate_recall_at_cutoffs",
        "catalog_candidate_coverage_count",
        "catalog_candidate_coverage_rate",
        "source_user_coverage",
        "source_item_coverage",
        "source_marginal_candidate_hit_users",
        "source_marginal_candidate_hit_rate",
        "source_overlap",
    }
    assert expected_metric_fields <= set(metrics)
    assert 0.0 <= metrics["empty_candidate_rate"] <= 1.0
    assert 0.0 <= metrics["user_candidate_coverage_rate"] <= 1.0
    assert metrics["candidate_count_min"] <= metrics["candidate_count_p50"] <= metrics["candidate_count_p90"] <= metrics["candidate_count_max"]
    assert all(0.0 <= rate <= 1.0 for rate in metrics["candidate_hit_rate_at_cutoffs"].values())
    assert all(0.0 <= rate <= 1.0 for rate in metrics["candidate_recall_at_cutoffs"].values())
    assert metrics["catalog_candidate_coverage_rate"] is None or 0.0 <= metrics["catalog_candidate_coverage_rate"] <= 1.0
    assert "source_pair_jaccard" in metrics["source_overlap"]
    assert (baseline_output / "pool_curve.csv").is_file()
    assert (baseline_output / "source_coverage.csv").is_file()
    assert (baseline_output / "frozen_candidates.jsonl").is_file()
    assert (baseline_output / "frozen_candidate_artifact.json").is_file()
    frozen_evidence = json.loads((baseline_output / "frozen_promotion_evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["frozen_candidates_path"] == str(baseline_output / "frozen_candidates.jsonl")
    assert frozen_evidence["required_artifacts"]["frozen_candidates_path"]["available"] is True
    assert frozen_evidence["required_artifacts"]["source_coverage_path"]["available"] is True
    assert frozen_evidence["required_artifacts"]["pool_curve_path"]["available"] is True
    assert frozen_evidence["gate_status"] == "INCONCLUSIVE_MISSING_ARTIFACT"
    assert "ablation_report_path" in frozen_evidence["missing_required_artifacts"]

    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(audit_output),
            "--mode",
            "audit",
            "--limit-users",
            "2",
            "--holdout-user-ids",
            str(baseline_output / "holdout_user_ids.json"),
        ],
    )

    phase_1_21.main()

    audit_manifest = json.loads((audit_output / "manifest.json").read_text(encoding="utf-8"))
    assert audit_manifest["mode"] == "audit"
    assert audit_manifest["holdout_user_ids_hash"] == manifest["holdout_user_ids_hash"]
    assert audit_manifest["source_contract_version"] == "phase_1_21_source_contract_v1"
    assert audit_manifest["metrics_contract_version"] == "phase_1_21_metrics_contract_v1"
    assert audit_manifest["loaded_baseline_holdout_user_ids_path"] == str(baseline_output / "holdout_user_ids.json")
    assert "diagnostics/evaluation only" in audit_manifest["no_leakage_contract"]
    assert "candidate whitelist construction" in audit_manifest["no_leakage_contract"]
    assert (audit_output / "miss_targets.csv").is_file()
    assert (audit_output / "source_gap_audit.csv").is_file()
    assert (audit_output / "category_gap_summary.csv").is_file()
    assert (audit_output / "popularity_gap_summary.csv").is_file()
    assert (audit_output / "source_opportunity_summary.json").is_file()
    opportunity_summary = json.loads((audit_output / "source_opportunity_summary.json").read_text(encoding="utf-8"))
    assert opportunity_summary["baseline_miss_users"] == 1
    assert opportunity_summary["opportunity_users_on_raw_misses"] == {
        "metadata_neighbor_opportunity_users": 1,
        "co_visit_opportunity_users": 1,
    }
    assert opportunity_summary["opportunity_gate"] == {
        "metadata_neighbor_min_users": 3,
        "co_visit_min_users": 5,
        "metadata_neighbor_gate_pass": False,
        "co_visit_gate_pass": False,
        "stop_loss_no_new_source": True,
        "counting_unit": "raw_stage_miss_users",
    }
    assert "query construction" in opportunity_summary["no_leakage_note"]
    assert "source index construction" in opportunity_summary["no_leakage_note"]

    miss_rows = _read_csv(audit_output / "miss_targets.csv")
    assert len(miss_rows) == 2
    assert {row["target_item"] for row in miss_rows} == {"speaker_1", "keyboard_1"}
    assert all(row["gap_reason"] for row in miss_rows)


def test_phase_1_21_ablation_writes_evidence_and_frozen_checklist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    phase_config = json.loads(config_path.read_text(encoding="utf-8"))
    phase_config.update({
        "co_visit_fallback_repair_enabled": True,
        "co_visit_seed_window": 1,
        "co_visit_per_seed": 2,
        "co_visit_per_user": 2,
        "category_long_tail_enabled": True,
        "category_long_tail_start_rank": 1,
        "category_long_tail_per_user": 2,
        "semantic_title_category_expansion": {"enabled": True, "per_user": 1, "per_seed": 1},
    })
    config_path.write_text(json.dumps(phase_config), encoding="utf-8")
    baseline_output = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    ablation_output = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "ablation"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(baseline_output),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )
    phase_1_21.main()

    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(ablation_output),
            "--mode",
            "ablation",
            "--limit-users",
            "2",
            "--holdout-user-ids",
            str(baseline_output / "holdout_user_ids.json"),
        ],
    )
    phase_1_21.main()

    manifest = json.loads((ablation_output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dedicated_ablation_contract_version"] == phase_1_21.DEDICATED_ABLATION_CONTRACT_VERSION
    assert manifest["frozen_promotion_evidence_contract_version"] == phase_1_21.FROZEN_PROMOTION_EVIDENCE_CONTRACT_VERSION
    ablation_manifest = json.loads(Path(manifest["dedicated_ablation_evidence_manifest_path"]).read_text(encoding="utf-8"))
    frozen_checklist = json.loads(Path(manifest["frozen_promotion_evidence_checklist_path"]).read_text(encoding="utf-8"))

    assert ablation_manifest["promotion_evidence_status"] == "READY_FOR_PROMOTION_REVIEW"
    assert ablation_manifest["missing_required_artifacts"] == []
    assert all(check["available"] for check in ablation_manifest["required_artifacts"].values())
    experiments_by_name = {row["experiment_name"]: row for row in ablation_manifest["experiments"]}
    assert "co_visit_fallback_repair_enabled" not in experiments_by_name["baseline_only"]["config_patch"]
    assert "semantic_title_category_expansion" not in experiments_by_name["baseline_only"]["config_patch"]
    assert experiments_by_name["co_visit_fallback"]["config_patch"]["co_visit_fallback_repair_enabled"] is True
    assert experiments_by_name["semantic_title_category"]["config_patch"]["semantic_title_category_expansion"]["enabled"] is True
    assert frozen_checklist["required_artifacts"]["frozen_candidates"]["available"] is True
    assert frozen_checklist["required_artifacts"]["source_coverage"]["available"] is True
    assert frozen_checklist["required_artifacts"]["pool_curve"]["available"] is True
    assert frozen_checklist["required_artifacts"]["ablation_report"]["available"] is True
    assert frozen_checklist["required_artifacts"]["overlap_report"]["available"] is True
    assert frozen_checklist["required_artifacts"]["fallback_report"]["available"] is True
    assert frozen_checklist["required_artifacts"]["latency_report"]["available"] is True
    assert frozen_checklist["gate_status"] == "READY_FOR_PROMOTION_REVIEW"
    assert frozen_checklist["missing_required_artifacts"] == []
    assert (ablation_output / "latency_report.csv").is_file()


def test_phase_1_21_source_aware_writes_observation_comparison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    phase_config = json.loads(config_path.read_text(encoding="utf-8"))
    phase_config.update({
        "candidate_pool_size": 2,
        "source_aware_experiments": ["score_sorted_all_sources", "source_balanced_fallback_preserving"],
        "semantic_title_category_expansion": {"enabled": True, "per_user": 1, "per_seed": 1},
        "co_visit_fallback_repair_enabled": True,
        "co_visit_seed_window": 1,
        "co_visit_per_seed": 1,
        "co_visit_per_user": 1,
        "usercf_enabled": True,
        "swing_enabled": True,
    })
    config_path.write_text(json.dumps(phase_config), encoding="utf-8")
    baseline_output = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    source_aware_output = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "source-aware"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(baseline_output),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )
    phase_1_21.main()

    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(source_aware_output),
            "--mode",
            "source-aware",
            "--limit-users",
            "2",
            "--holdout-user-ids",
            str(baseline_output / "holdout_user_ids.json"),
        ],
    )
    phase_1_21.main()

    manifest = json.loads((source_aware_output / "manifest.json").read_text(encoding="utf-8"))
    summary_rows = _read_csv(source_aware_output / "summary_metrics.csv")
    assert manifest["mode"] == "source-aware"
    assert manifest["decision_scope"] == "recall_only_observation"
    assert manifest["same_holdout_user_ids_verified"] is True
    assert manifest["experiments"] == ["score_sorted_all_sources", "source_balanced_fallback_preserving"]
    assert {row["experiment_name"] for row in summary_rows} == set(manifest["experiments"])
    balanced_manifest = json.loads((source_aware_output / "source_balanced_fallback_preserving" / "manifest.json").read_text(encoding="utf-8"))
    balanced_features = balanced_manifest["phase_source_features"]
    assert balanced_features["candidate_pool_strategy"] == "balanced_source_budget"
    assert balanced_features["candidate_source_minimums"]["semantic_title_category_expansion"] == 40
    assert (source_aware_output / "baseline_displacement_report.csv").is_file()
    assert (source_aware_output / "source_overlap_matrix.csv").is_file()



def test_phase_1_21_audit_rejects_holdout_hash_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    bad_holdout = tmp_path / "bad_holdout.json"
    bad_holdout.write_text(json.dumps({"holdout_user_ids": ["u1"]}), encoding="utf-8")
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "outputs" / "phase_1_21_recall_coverage" / "audit"),
            "--mode",
            "audit",
            "--limit-users",
            "2",
            "--holdout-user-ids",
            str(bad_holdout),
        ],
    )

    with pytest.raises(ValueError, match="Loaded holdout user ids do not match"):
        phase_1_21.main()


@pytest.mark.parametrize(
    ("config_patch", "expected_fragment"),
    [
        ({"ltr_model": {"enabled": True}}, "ltr_model.enabled=false"),
        ({"ranking_v2": {"enabled": True}}, "ranking_v2.enabled=false"),
        ({"include_ranking_v2": True}, "include_ranking_v2 not enabled"),
        ({"version": "ltr_v2"}, "version !="),
        ({"feature_version": "ranking_v2"}, "feature_version !="),
        ({"item_feature_rerank": {"enabled": True}}, "item_feature_rerank.enabled=false"),
        ({"source_aware_fusion": {"enabled": True}}, "source_aware_fusion.enabled=false"),
    ],
)
def test_phase_1_21_rejects_ranking_route_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch: dict[str, object],
    expected_fragment: str,
):
    config_path, baseline_path = _write_fixture(tmp_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline.update(config_patch)
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    with pytest.raises(ValueError, match="must not enable ranking/rerank routes") as exc_info:
        phase_1_21.main()
    assert expected_fragment in str(exc_info.value)


def test_phase_1_21_rejects_no_leakage_source_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["miss_targets_path"] = "outputs/recall/phase_1_21_recall_coverage/audit/miss_targets.csv"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    with pytest.raises(ValueError, match="no-leakage contract forbids miss_targets_path"):
        phase_1_21.main()


def test_phase_1_21_long_tail_and_metadata_recall_are_default_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    rows = _read_csv(output_dir / "source_coverage.csv")
    sources = {row["source"] for row in rows if row["row_type"] == "source"}
    assert "category_long_tail_recall" not in sources
    assert "metadata_neighbor_recall" not in sources


def test_phase_1_21_long_tail_and_metadata_recall_source_reporting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, baseline_path = _write_fixture(tmp_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline.update({
        "category_long_tail_enabled": True,
        "category_long_tail_start_rank": 2,
        "category_long_tail_per_user": 3,
        "metadata_neighbor_enabled": True,
        "metadata_neighbor_per_user": 3,
        "metadata_neighbor_per_seed": 3,
        "metadata_neighbor_min_token_overlap": 1,
    })
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    rows = _read_csv(output_dir / "source_coverage.csv")
    source_rows = {row["source"]: row for row in rows if row["row_type"] == "source"}
    assert int(source_rows["category_long_tail_recall"]["candidate_count"]) >= 1
    assert int(source_rows["metadata_neighbor_recall"]["candidate_count"]) >= 1
    pairs = {row["pair"] for row in rows if row["row_type"] == "source_pair"}
    assert "itemcf_weak+metadata_neighbor_recall" in pairs
    frozen_rows = [json.loads(line) for line in (output_dir / "frozen_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    metadata_candidates = [
        row
        for row in frozen_rows
        if "metadata_neighbor_recall" in row["sources"]
    ]
    assert metadata_candidates
    assert all(candidate["metadata"]["metadata_neighbor_index_mode"] == "bucketed_train_visible_metadata" for candidate in metadata_candidates)


def test_phase_1_21_metadata_neighbor_skips_missing_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, baseline_path = _write_fixture(tmp_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline.update({
        "metadata_neighbor_enabled": True,
        "metadata_neighbor_per_user": 3,
        "metadata_neighbor_per_seed": 3,
    })
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    rows = _read_csv(output_dir / "source_coverage.csv")
    source_rows = {row["source"]: row for row in rows if row["row_type"] == "source"}
    assert int(source_rows["metadata_neighbor_recall"]["candidate_count"]) >= 1


def test_phase_1_21_co_visit_fallback_repair_default_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    rows = _read_csv(output_dir / "source_coverage.csv")
    sources = {row["source"] for row in rows if row["row_type"] == "source"}
    assert "co_visit_fallback_repair" not in sources


def test_phase_1_21_co_visit_fallback_repair_source_reporting_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, baseline_path = _write_fixture(tmp_path)
    sequences_path = tmp_path / "clean" / "user_sequences.train.jsonl"
    existing = sequences_path.read_text(encoding="utf-8")
    additions = [
        {"user_id": "train_audio_pair", "recent_item_sequence": ["seed_audio", "co_visit_speaker"], "recent_positive_item_sequence": ["seed_audio", "co_visit_speaker"], "recent_strong_positive_item_sequence": [], "sequence_len": 2},
        {"user_id": "train_noise_pair_1", "recent_item_sequence": ["seed_audio", "popular_noise"], "recent_positive_item_sequence": ["seed_audio", "popular_noise"], "recent_strong_positive_item_sequence": [], "sequence_len": 2},
        {"user_id": "train_noise_pair_2", "recent_item_sequence": ["seed_office", "popular_noise"], "recent_positive_item_sequence": ["seed_office", "popular_noise"], "recent_strong_positive_item_sequence": [], "sequence_len": 2},
        {"user_id": "train_noise_pair_3", "recent_item_sequence": ["other_seed", "popular_noise"], "recent_positive_item_sequence": ["other_seed", "popular_noise"], "recent_strong_positive_item_sequence": [], "sequence_len": 2},
    ]
    sequences_path.write_text(existing + "".join(json.dumps(row) + "\n" for row in additions), encoding="utf-8")
    valid_path = tmp_path / "clean" / "canonical_interactions.valid.jsonl"
    valid_path.write_text(valid_path.read_text(encoding="utf-8") + json.dumps({"user_id": "u1", "parent_asin": "co_visit_speaker", "label_binary": 1}) + "\n", encoding="utf-8")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["rank_weights"]["co_visit_fallback_repair"] = 1.0
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.update({
        "co_visit_fallback_repair_enabled": True,
        "co_visit_seed_window": 1,
        "co_visit_per_seed": 5,
        "co_visit_per_user": 5,
        "co_visit_max_item_user_freq": 2,
    })
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    rows = _read_csv(output_dir / "source_coverage.csv")
    source_rows = {row["source"]: row for row in rows if row["row_type"] == "source"}
    benchmark_artifact = json.loads((output_dir / "source_family_observation_benchmarks.json").read_text(encoding="utf-8"))
    benchmark_by_name = {row["display_name"]: row for row in benchmark_artifact["benchmarks"]}
    assert benchmark_by_name["ItemCF/co-visit"]["execution_status"] == "EXECUTED_PASS"
    assert benchmark_by_name["ItemCF/co-visit"]["metrics_path"] == str(output_dir / "metrics.json")
    assert benchmark_by_name["popular/category"]["execution_status"] == "READY_TO_RUN"
    assert int(source_rows["co_visit_fallback_repair"]["candidate_count"]) >= 1
    assert int(source_rows["co_visit_fallback_repair"]["hit_users"]) == 1
    neighbors = phase_1_21._build_co_visit_neighbors([json.loads(line) for line in sequences_path.read_text(encoding="utf-8").splitlines()], config)
    candidates = phase_1_21._co_visit_candidates_for_user({"recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]}, neighbors, config)
    assert "popular_noise" not in {candidate.item_id for candidate in candidates}
    candidate = candidates[0]
    assert candidate.source == "co_visit_fallback_repair"
    assert candidate.metadata["seed_item_id"] == "seed_audio"
    assert candidate.metadata["reason"] == "train_period_co_visit"
    assert candidate.metadata["source_score"] >= 1.0


def test_phase_1_21_co_visit_fallback_repair_skips_empty_neighbors():
    candidates = phase_1_21._co_visit_candidates_for_user(
        {"recent_item_sequence": ["seed_without_neighbors"], "recent_positive_item_sequence": ["seed_without_neighbors"]},
        {},
        {"co_visit_fallback_repair_enabled": True},
    )
    assert candidates == []


def test_phase_1_21_behavior_untried_sources_use_train_sequences_only():
    sequences = [
        {"user_id": "u1", "recent_item_sequence": ["seed_a", "next_a"], "recent_positive_item_sequence": ["seed_a", "next_a"]},
        {"user_id": "u2", "recent_item_sequence": ["seed_a", "next_b"], "recent_positive_item_sequence": ["seed_a", "next_b"]},
        {"user_id": "u3", "recent_item_sequence": ["seed_c", "next_b"], "recent_positive_item_sequence": ["seed_c", "next_b"]},
        {"user_id": "u4", "recent_item_sequence": ["seed_a", "next_c"], "recent_positive_item_sequence": ["seed_a", "next_c"]},
    ]
    config = phase_1_21._behavior_untried_patch()

    usercf = phase_1_21._build_usercf_index(sequences, config)
    swing = phase_1_21._build_swing_index(sequences, config)
    transition = phase_1_21._build_session_transition_index(sequences, config)

    sequence = {"user_id": "u1", "recent_item_sequence": ["seed_a"], "recent_positive_item_sequence": ["seed_a"]}
    usercf_candidates = phase_1_21._usercf_candidates_for_user(sequence, usercf, config)
    swing_candidates = phase_1_21._swing_candidates_for_user(sequence, swing, config)
    transition_candidates = phase_1_21._session_transition_candidates_for_user(sequence, transition, config)

    assert {candidate.source for candidate in usercf_candidates} == {"usercf_recall"}
    assert {candidate.source for candidate in swing_candidates} == {"swing_recall"}
    assert {candidate.source for candidate in transition_candidates} == {"session_transition_recall"}
    assert "next_b" in {candidate.item_id for candidate in usercf_candidates}
    assert "next_b" in {candidate.item_id for candidate in swing_candidates}
    assert "next_a" in {candidate.item_id for candidate in transition_candidates}


def test_phase_1_21_implicit_als_bpr_recall_uses_train_sequences_only():
    if importlib.util.find_spec("implicit") is None:
        pytest.skip("implicit is not installed")
    sequences = [
        {"user_id": "u1", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]},
        {"user_id": "u2", "recent_item_sequence": ["seed_audio", "speaker_a"], "recent_positive_item_sequence": ["seed_audio", "speaker_a"]},
        {"user_id": "u3", "recent_item_sequence": ["seed_office", "keyboard_a"], "recent_positive_item_sequence": ["seed_office", "keyboard_a"]},
    ]
    config = {
        "als_mf_enabled": True,
        "als_mf_factors": 2,
        "als_mf_iterations": 1,
        "als_mf_regularization": 0.01,
        "als_mf_alpha": 1.0,
        "als_mf_per_user": 2,
        "als_mf_min_score": -1.0,
        "bpr_mf_enabled": True,
        "bpr_mf_factors": 2,
        "bpr_mf_iterations": 1,
        "bpr_mf_regularization": 0.01,
        "bpr_mf_learning_rate": 0.01,
        "bpr_mf_per_user": 2,
        "bpr_mf_min_score": -1.0,
    }

    for model_name, expected_source, expected_reason in [
        ("als_mf", "als_mf_recall", "train_implicit_als"),
        ("bpr_mf", "bpr_mf_recall", "train_implicit_bpr"),
    ]:
        index = phase_1_21._build_implicit_mf_index(sequences, config, model_name)
        candidates = phase_1_21._implicit_mf_candidates_for_user(
            {"user_id": "u1", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]},
            index,
            config,
            model_name,
        )

        assert candidates
        assert {candidate.source for candidate in candidates} == {expected_source}
        assert "seed_audio" not in {candidate.item_id for candidate in candidates}
        candidate = candidates[0]
        assert candidate.metadata["reason"] == expected_reason
        assert candidate.metadata["source_rank"] == 1
        assert candidate.metadata["model_name"] == model_name



def test_phase_1_21_lightfm_recall_uses_train_sequences_only():
    if importlib.util.find_spec("lightfm") is None:
        pytest.skip("lightfm is not installed")
    sequences = [
        {"user_id": "u1", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]},
        {"user_id": "u2", "recent_item_sequence": ["seed_audio", "speaker_a"], "recent_positive_item_sequence": ["seed_audio", "speaker_a"]},
        {"user_id": "u3", "recent_item_sequence": ["seed_office", "keyboard_a"], "recent_positive_item_sequence": ["seed_office", "keyboard_a"]},
    ]
    config = {
        "lightfm_enabled": True,
        "lightfm_components": 2,
        "lightfm_epochs": 1,
        "lightfm_loss": "logistic",
        "lightfm_learning_rate": 0.05,
        "lightfm_per_user": 2,
        "lightfm_min_score": -1.0,
    }

    index = phase_1_21._build_lightfm_index(sequences, config)
    candidates = phase_1_21._lightfm_candidates_for_user(
        {"user_id": "u1", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]},
        index,
        config,
    )

    assert candidates
    assert {candidate.source for candidate in candidates} == {"lightfm_recall"}
    assert "seed_audio" not in {candidate.item_id for candidate in candidates}
    candidate = candidates[0]
    assert candidate.metadata["reason"] == "train_lightfm_logistic"
    assert candidate.metadata["source_rank"] == 1
    assert candidate.metadata["model_name"] == "lightfm"


def test_phase_1_21_multi_interest_recall_uses_train_sequences_only():
    sequences = [
        {"user_id": "u1", "recent_item_sequence": ["seed_audio", "speaker_a"], "recent_positive_item_sequence": ["seed_audio", "speaker_a"]},
        {"user_id": "u2", "recent_item_sequence": ["seed_audio", "speaker_b"], "recent_positive_item_sequence": ["seed_audio", "speaker_b"]},
        {"user_id": "u3", "recent_item_sequence": ["seed_office", "keyboard_a"], "recent_positive_item_sequence": ["seed_office", "keyboard_a"]},
    ]
    config = phase_1_21._multi_interest_patch()

    index = phase_1_21._build_multi_interest_index(sequences, config)
    candidates = phase_1_21._multi_interest_candidates_for_user(
        {"user_id": "eval_user", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]},
        index,
        config,
    )

    assert {candidate.source for candidate in candidates} == {"multi_interest_recall"}
    assert [candidate.item_id for candidate in candidates[:2]] == ["speaker_a", "speaker_b"]
    candidate = candidates[0]
    assert candidate.metadata["reason"] == "train_period_multi_interest"
    assert candidate.metadata["seed_item_id"] == "seed_audio"
    assert candidate.metadata["source_rank"] == 1
    assert candidate.metadata["seed_info"]["interest_unit"] == "train_positive_sequence"
    assert candidate.metadata["seed_info"]["session_neighbor_weight"] == 0.25



def test_phase_1_21_semantic_title_category_expansion_default_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = _read_csv(output_dir / "source_coverage.csv")
    sources = {row["source"] for row in rows if row["row_type"] == "source"}
    assert manifest["phase_source_features"] == {}
    assert "semantic_title_category_expansion" not in sources


def test_phase_1_21_semantic_title_category_expansion_reporting_and_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["semantic_title_category_expansion"] = {
        "enabled": True,
        "per_user": 1,
        "per_seed": 1,
        "seed_window": 2,
        "min_title_overlap": 1,
        "weak_categories": ["Office Products"],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = _read_csv(output_dir / "source_coverage.csv")
    source_rows = {row["source"]: row for row in rows if row["row_type"] == "source"}
    benchmark_artifact = json.loads((output_dir / "source_family_observation_benchmarks.json").read_text(encoding="utf-8"))
    benchmark_by_name = {row["display_name"]: row for row in benchmark_artifact["benchmarks"]}
    assert manifest["phase_source_features"]["semantic_title_category_expansion"]["enabled"] is True
    assert benchmark_by_name["semantic/title-category"]["execution_status"] == "EXECUTED_PASS"
    assert benchmark_by_name["semantic/title-category"]["metrics_path"] == str(output_dir / "metrics.json")
    assert benchmark_by_name["popular/category"]["execution_status"] == "READY_TO_RUN"
    assert int(source_rows["semantic_title_category_expansion"]["candidate_count"]) <= 2
    assert int(source_rows["semantic_title_category_expansion"]["hit_users"]) >= 1
    assert manifest["ranking_rerank_disabled_checks"]["ranking_v2.enabled"] is False
    assert manifest["ranking_rerank_disabled_checks"]["include_ranking_v2"] == "not enabled"


def test_phase_1_21_phase_config_can_promote_pool_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path, _ = _write_fixture(tmp_path)
    phase_config = json.loads(config_path.read_text(encoding="utf-8"))
    phase_config["candidate_pool_size"] = 1
    config_path.write_text(json.dumps(phase_config), encoding="utf-8")
    output_dir = tmp_path / "outputs" / "phase_1_21_recall_coverage" / "baseline"
    monkeypatch.setattr(phase_1_21, "DEFAULT_OUTPUT_ROOT", str(tmp_path / "outputs" / "phase_1_21_recall_coverage"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_21_recall_coverage_experiments.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            "baseline",
            "--limit-users",
            "2",
        ],
    )

    phase_1_21.main()

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert manifest["baseline_candidate_pool_size"] == 1
    assert metrics["candidate_count_avg"] <= 1.0


def _write_fixture(root: Path) -> tuple[Path, Path]:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()

    write_jsonl(clean / "user_sequences.train.jsonl", [
        {
            "user_id": "u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
            "recent_strong_positive_item_sequence": [],
            "sequence_len": 1,
        },
        {
            "user_id": "u2",
            "recent_item_sequence": ["seed_office"],
            "recent_positive_item_sequence": ["seed_office"],
            "recent_strong_positive_item_sequence": [],
            "sequence_len": 1,
        },
    ])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [
        {"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1},
        {"user_id": "u2", "parent_asin": "keyboard_1", "label_binary": 1},
    ])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5, "title_clean": "USB charger"},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
        {"parent_asin": "seed_office", "main_category": "Office Products"},
        {"parent_asin": "keyboard_1", "main_category": "Office Products"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [
        {"bucket": "main::Audio", "top_items": [
            {"parent_asin": "speaker_1", "score": 1.0, "category": "Audio", "title_clean": "Bluetooth speaker"},
        ]},
        {"bucket": "main::Office Products", "top_items": []},
    ])
    write_jsonl(views / "semantic_recall_inputs.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio", "title_clean": "portable bluetooth audio seed"},
        {"parent_asin": "speaker_1", "main_category": "Audio", "title_clean": "portable bluetooth speaker"},
        {"parent_asin": "seed_office", "main_category": "Office Products", "title_clean": "wireless office keyboard seed"},
        {"parent_asin": "keyboard_1", "main_category": "Office Products", "title_clean": "wireless office keyboard"},
    ])

    baseline = root / "baseline.yaml"
    baseline.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "evaluation_mode": "valid_test",
        "top_k": 3,
        "candidate_pool_size": 100,
        "popular_fallback_count": 3,
        "rank_weights": {
            "popular": 1.0,
            "itemcf_weak": 1.0,
            "itemcf_strong": 1.0,
            "category": 1.0,
        },
        "ltr_model": {"enabled": False},
        "ranking_v2": {"enabled": False},
        "item_feature_rerank": {"enabled": False},
        "source_aware_fusion": {"enabled": False},
    }), encoding="utf-8")
    config = root / "phase_1_21.yaml"
    config.write_text(json.dumps({
        "baseline_config_path": str(baseline),
        "limit_users": 2,
        "evaluation_mode": "valid_test",
        "hit_rate_denominator": "users_with_holdout",
        "expected_users_with_holdout": 2,
    }), encoding="utf-8")
    return config, baseline


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _holdout_hash(user_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(user_ids)).encode("utf-8")).hexdigest()
