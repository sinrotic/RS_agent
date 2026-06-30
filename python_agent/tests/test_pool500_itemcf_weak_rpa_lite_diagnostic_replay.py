from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_lab.experiments.recall.pool500.methods.itemcf_weak.rpa_lite_diagnostic_replay import (
    materialize_rpa_lite_diagnostic_replay,
)

pytestmark = pytest.mark.unit


def test_materialize_rpa_lite_diagnostic_replay_writes_governed_artifacts(tmp_path: Path) -> None:
    dataset_root = _write_dataset_fixture(tmp_path)
    report_path = _write_report_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "rpa_lite_diagnostic_replay_v1"

    manifest = materialize_rpa_lite_diagnostic_replay(
        evaluation_report_path=report_path,
        output_dir=output_dir,
        dataset_root=dataset_root,
        overwrite=True,
        enforce_venv=False,
    )

    required_outputs = {
        "rpa_lite_replay_manifest.json",
        "governance_audit.json",
        "no_eval_label_selection_audit.json",
        "resource_audit.json",
        "coverage_audit.json",
    }
    assert required_outputs <= {path.name for path in output_dir.iterdir()}
    assert (output_dir / "posthoc_eval" / "evaluation_report.json").is_file()

    assert manifest["source"] == "itemcf_weak"
    assert manifest["source_status"] == "DIAGNOSTIC_ONLY"
    assert manifest["diagnostic_only"] is True
    assert manifest["evaluation_only"] is True
    assert manifest["artifact_type"] == "diagnostic_replay_artifact"
    assert manifest["candidate_artifact_written"] is False
    assert manifest["ready_source_artifact"] is False
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert manifest["algorithm"]["predeclared_primary_variant"] == "rpa_iuf_sparse_medium_p100_user500_sharded10gb"
    assert manifest["algorithm"]["observed_best_status"] == "diagnostic_observed_best_not_promotion_rule"
    evidence_schema = manifest["diagnostic_replay_evidence_schema"]
    assert evidence_schema["candidate_artifact_written"] is False
    assert "path_support" in evidence_schema["required_fields_if_candidate_replay_is_materialized"]
    assert "sum_user_similarity" in evidence_schema["required_fields_if_candidate_replay_is_materialized"]
    assert manifest["posthoc_metrics"]["raw_recall@500"] == 0.026407
    assert manifest["posthoc_metrics"]["sparse_hit_user_rate@500"] == 0.02473
    assert manifest["comparison"]["raw_recall_lift_vs_augcf_lite_v3"] == 0.0017

    no_eval = read_json(output_dir / "no_eval_label_selection_audit.json")
    assert no_eval["status"] == "PASS"
    assert no_eval["build_stage_valid_files_opened"] is False
    assert no_eval["build_stage_test_files_opened"] is False
    assert no_eval["scoring_rule_selection"]["eval_label_used_for_selection"] is False
    assert no_eval["posthoc_eval"]["eval_label_used_for_posthoc_metrics_only"] is True

    governance = read_json(output_dir / "governance_audit.json")
    assert governance["train_only"] is True
    assert governance["eval_labels_used_for_candidate_generation"] is False
    assert governance["eval_labels_used_for_scoring_rule_selection"] is False
    assert governance["input_signatures"]["train_user_sequences"]["exists"] is True


def test_materialize_rpa_lite_diagnostic_replay_rejects_forbidden_output_path(tmp_path: Path) -> None:
    dataset_root = _write_dataset_fixture(tmp_path)
    report_path = _write_report_fixture(tmp_path)

    with pytest.raises(ValueError, match="Forbidden output path"):
        materialize_rpa_lite_diagnostic_replay(
            evaluation_report_path=report_path,
            output_dir=tmp_path / "pool1000" / "rpa_lite",
            dataset_root=dataset_root,
            overwrite=True,
            enforce_venv=False,
        )


def test_materialize_rpa_lite_diagnostic_replay_rejects_promoted_report(tmp_path: Path) -> None:
    dataset_root = _write_dataset_fixture(tmp_path)
    report_path = _write_report_fixture(tmp_path, candidate_generation_allowed=True)

    with pytest.raises(ValueError, match="candidate generation"):
        materialize_rpa_lite_diagnostic_replay(
            evaluation_report_path=report_path,
            output_dir=tmp_path / "outputs" / "rpa_lite",
            dataset_root=dataset_root,
            overwrite=True,
            enforce_venv=False,
        )


def _write_dataset_fixture(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "clean"
    governance_root = dataset_root / "train_only_governance"
    governance_root.mkdir(parents=True)
    write_jsonl(dataset_root / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_positive_item_sequence": ["a"]}])
    write_json(governance_root / "manifest.json", {"schema_version": "fixture_governance_v1"})
    write_jsonl(governance_root / "item_frequency_train.jsonl", [{"parent_asin": "a", "user_count": 1}])
    write_jsonl(governance_root / "item_quality_profile.jsonl", [{"parent_asin": "a", "quality_bucket_v2": "cf_ready"}])
    write_jsonl(dataset_root / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "b", "label_binary": 1}])
    write_jsonl(dataset_root / "canonical_interactions.test.jsonl", [{"user_id": "u1", "parent_asin": "c", "label_binary": 1}])
    return dataset_root


def _write_report_fixture(tmp_path: Path, *, candidate_generation_allowed: bool = False) -> Path:
    report = {
        "schema_version": "pool500_itemcf_weak_rpa_lite_local_10gb_sharded_v1",
        "status": "PASS",
        "source": "itemcf_weak",
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "evaluation_only": True,
        "candidate_generation_allowed": candidate_generation_allowed,
        "promotion_allowed": False,
        "candidate_artifact_written": False,
        "shard_mod": 20,
        "completed_shards": 20,
        "local_memory_limit_gb_per_shard": 10.0,
        "peak_observed_rss_gb_max": 6.8637,
        "runtime_seconds_total_sum": 13863.520166,
        "config": {"candidate_score_limit": 500, "candidate_idf_power": 0.5},
        "baselines": {
            "augcf_lite_v3_sideinfo_category_boost_v1": {
                "raw_recall@500": 0.024707,
                "sparse_hit_user_rate@500": 0.018064,
            }
        },
        "eval_scope": {
            "train_only_target_users_total": 5147753,
            "evaluated_target_users_with_labels_total": 41605,
        },
        "summary": {
            "best_raw_recall_at_500": {
                "name": "rpa_iuf_sparse_medium_p100_user500_sharded10gb",
                "raw_recall@500": 0.026407,
                "in_universe_recall@500": 0.050346,
                "raw_hit_user_rate@500": 0.032857,
                "candidate_user_rate": 0.928158,
                "candidate_count_stats": {"min": 0, "p50": 100.0, "p90": 100.0, "max": 100},
                "sequence_bucket_hit_user_rate@500": {
                    "sparse_seq_len_lt2": 0.02473,
                    "medium_like_seq_len_2_4": 0.053875,
                },
            }
        },
    }
    path = tmp_path / "evaluation_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
