from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json
from scripts.experiments.recall.pool500.evaluate_method_source_artifact import evaluate_method_source_artifact

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_evaluate_method_source_artifact_uses_eval_labels_only_for_scoring(tmp_path: Path) -> None:
    candidates_path = tmp_path / "source" / "candidates.jsonl"
    source_manifest_path = tmp_path / "source" / "source_index_manifest.json"
    valid_path = tmp_path / "data" / "canonical_interactions.valid.jsonl"
    test_path = tmp_path / "data" / "canonical_interactions.test.jsonl"
    clean_manifest_path = tmp_path / "data" / "manifest.json"
    eligible_manifest_path = tmp_path / "eligible_user_manifest.json"
    output_dir = tmp_path / "eval"

    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit20", "rank": 1, "source": "semantic_title_category_expansion"},
            {"user_id": "u1", "item_id": "miss", "rank": 2, "source": "semantic_title_category_expansion"},
            {"user_id": "u2", "item_id": "hit50", "rank": 30, "source": "semantic_title_category_expansion"},
            {"user_id": "u3", "item_id": "no_label_user", "rank": 1, "source": "semantic_title_category_expansion"},
        ],
    )
    _write_json(
        source_manifest_path,
        {
            "source": "semantic_title_category_expansion",
            "candidates_path": str(candidates_path),
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        },
    )
    _write_jsonl(valid_path, [{"user_id": "u1", "parent_asin": "hit20", "label_binary": 1}])
    _write_jsonl(test_path, [{"user_id": "u2", "parent_asin": "hit50", "label_binary": 1}])
    _write_json(clean_manifest_path, {"split_paths": {"valid": str(valid_path), "test": str(test_path)}})
    _write_json(eligible_manifest_path, {"eligible_user_buckets": {"sequence_sufficient": ["u1"], "fallback_only": ["u2", "u3"]}})

    report = evaluate_method_source_artifact(
        source_index_manifest_path=source_manifest_path,
        clean_manifest_path=clean_manifest_path,
        eligible_user_manifest_path=eligible_manifest_path,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
    )

    metrics = read_json(output_dir / "metrics.json")
    segment_metrics = read_json(output_dir / "segment_metrics.json")
    source_audit = read_json(output_dir / "source_audit.json")

    assert report["eval_scope"] == "evaluation_only"
    assert report["label_inputs_role"] == "evaluation_only_not_candidate_generation_inputs"
    assert report["scored_user_count"] == 2
    assert report["skipped_candidate_user_without_eval_label_count"] == 1
    assert report["no_oracle_label_injection"] is True
    assert metrics["HitRate@20"] == pytest.approx(0.5)
    assert metrics["HitRate@50"] == pytest.approx(1.0)
    assert segment_metrics["sequence_sufficient"]["HitRate@20"] == pytest.approx(1.0)
    assert segment_metrics["fallback_only"]["HitRate@20"] == pytest.approx(0.0)
    assert source_audit["candidate_row_count"] == 4


def test_evaluate_method_source_artifact_scores_label_users_without_candidates_as_zero(tmp_path: Path) -> None:
    candidates_path = tmp_path / "source" / "candidates.jsonl"
    source_manifest_path = tmp_path / "source" / "source_index_manifest.json"
    valid_path = tmp_path / "data" / "canonical_interactions.valid.jsonl"
    clean_manifest_path = tmp_path / "data" / "manifest.json"
    output_dir = tmp_path / "eval"

    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "hit", "rank": 1, "source": "semantic"}])
    _write_json(source_manifest_path, {"source": "semantic", "candidates_path": str(candidates_path)})
    _write_jsonl(valid_path, [
        {"user_id": "u1", "parent_asin": "hit", "label_binary": 1},
        {"user_id": "u2", "parent_asin": "missing_candidate_hit", "label_binary": 1},
    ])
    _write_json(clean_manifest_path, {"split_paths": {"valid": str(valid_path)}})

    report = evaluate_method_source_artifact(
        source_index_manifest_path=source_manifest_path,
        clean_manifest_path=clean_manifest_path,
        output_dir=output_dir,
        label_splits=("valid",),
        metric_ks=(20,),
        overwrite=True,
        enforce_venv=False,
    )

    metrics = read_json(output_dir / "metrics.json")
    assert report["eval_label_user_count"] == 2
    assert report["scored_user_count"] == 2
    assert report["missing_candidate_label_user_count"] == 1
    assert metrics["HitRate@20"] == pytest.approx(0.5)
    assert metrics["Recall@20"] == pytest.approx(0.5)


def test_evaluate_method_source_artifact_reports_marginal_metrics_against_baseline(tmp_path: Path) -> None:
    candidates_path = tmp_path / "source" / "candidates.jsonl"
    source_manifest_path = tmp_path / "source" / "source_index_manifest.json"
    baseline_candidates_path = tmp_path / "baseline" / "candidates.jsonl"
    baseline_manifest_path = tmp_path / "baseline" / "source_index_manifest.json"
    valid_path = tmp_path / "data" / "canonical_interactions.valid.jsonl"
    clean_manifest_path = tmp_path / "data" / "manifest.json"
    output_dir = tmp_path / "eval"

    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "shared", "rank": 1},
            {"user_id": "u1", "item_id": "new_hit", "rank": 2},
            {"user_id": "u2", "item_id": "new_miss", "rank": 1},
        ],
    )
    _write_json(source_manifest_path, {"source": "semantic", "candidates_path": str(candidates_path)})
    _write_jsonl(
        baseline_candidates_path,
        [
            {"user_id": "u1", "item_id": "shared", "rank": 1},
            {"user_id": "u2", "item_id": "baseline_only", "rank": 1},
        ],
    )
    _write_json(baseline_manifest_path, {"source": "popular", "candidates_path": str(baseline_candidates_path)})
    _write_jsonl(valid_path, [{"user_id": "u1", "parent_asin": "new_hit", "label_binary": 1}, {"user_id": "u2", "parent_asin": "target", "label_binary": 1}])
    _write_json(clean_manifest_path, {"split_paths": {"valid": str(valid_path)}})

    report = evaluate_method_source_artifact(
        source_index_manifest_path=source_manifest_path,
        baseline_source_index_manifest_paths=[baseline_manifest_path],
        clean_manifest_path=clean_manifest_path,
        output_dir=output_dir,
        label_splits=("valid",),
        metric_ks=(20,),
        overwrite=True,
        enforce_venv=False,
    )

    marginal_metrics = read_json(output_dir / "marginal_metrics.json")
    assert report["baseline_inputs_role"] == "evaluation_only_marginal_comparison_not_candidate_generation_inputs"
    assert report["marginal_metrics_path"] == str(output_dir / "marginal_metrics.json")
    assert marginal_metrics["MarginalCandidateCount@20"] == 2
    assert marginal_metrics["MarginalPositiveHitCount@20"] == 1
    assert marginal_metrics["MarginalHitRate@20"] == pytest.approx(0.5)
    assert marginal_metrics["BaselineComparableUserCount@20"] == 2


def test_evaluate_method_source_artifact_expands_category_index_only_manifest(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "category_all_eligible"
    artifact_dir.mkdir()
    method_manifest_path = artifact_dir / "method_dataset_manifest.json"
    source_manifest_path = artifact_dir / "source_index_manifest.json"
    eligible_users_path = artifact_dir / "eligible_users.jsonl"
    profile_path = artifact_dir / "user_category_profile.jsonl"
    top_items_path = artifact_dir / "category_top_items_index.jsonl"
    train_sequences_path = artifact_dir / "train_user_sequences.jsonl"
    coverage_path = artifact_dir / "coverage_audit.json"
    resource_path = artifact_dir / "resource_audit.json"
    valid_path = tmp_path / "data" / "canonical_interactions.valid.jsonl"
    clean_manifest_path = tmp_path / "data" / "manifest.json"
    output_dir = tmp_path / "eval"

    _write_jsonl(eligible_users_path, [{"user_id": "u1", "quality_bucket": "medium_behavior", "sequence_len": 1, "positive_count": 1, "unique_item_count": 1}])
    _write_jsonl(profile_path, [{"user_id": "u1", "top_profile_buckets": [{"bucket": "main::Books", "weight": 1.0, "rank": 1}]}])
    _write_jsonl(train_sequences_path, [{"user_id": "u1", "recent_item_sequence": ["seen_item"], "recent_positive_item_sequence": ["seen_item"]}])
    _write_jsonl(top_items_path, [{"bucket": "main::Books", "top_items": [{"parent_asin": "seen_item", "score": 100}, {"parent_asin": "target", "score": 90}]}])
    _write_json(coverage_path, {"fallback_usage": {"fallback_buckets": ["main::Books"]}})
    _write_json(resource_path, {"config": {"per_user": 3, "category_bucket_cap_per_user": 3, "fallback_bucket_count": 1}})
    _write_json(method_manifest_path, {"source": "category", "candidate_materialization": "none", "input_lineage": {"train_user_sequences_path": str(train_sequences_path)}})
    _write_json(source_manifest_path, {
        "source": "category",
        "canonical_source": "category",
        "candidate_materialization": "none",
        "candidates_path": None,
        "method_dataset_manifest_path": str(method_manifest_path),
        "eligible_users_path": str(eligible_users_path),
        "user_category_profile_path": str(profile_path),
        "category_top_items_index_path": str(top_items_path),
        "outputs": {
            "method_dataset_manifest": str(method_manifest_path),
            "eligible_users": str(eligible_users_path),
            "user_category_profile": str(profile_path),
            "category_top_items_index": str(top_items_path),
            "coverage_audit": str(coverage_path),
            "resource_audit": str(resource_path),
        },
    })
    _write_jsonl(valid_path, [{"user_id": "u1", "parent_asin": "target", "label_binary": 1}])
    _write_json(clean_manifest_path, {"split_paths": {"valid": str(valid_path)}})

    report = evaluate_method_source_artifact(
        source_index_manifest_path=source_manifest_path,
        clean_manifest_path=clean_manifest_path,
        output_dir=output_dir,
        label_splits=("valid",),
        metric_ks=(20,),
        overwrite=True,
        enforce_venv=False,
    )

    metrics = read_json(output_dir / "metrics.json")
    assert report["candidate_artifact_path"] is None
    assert report["candidate_user_count"] == 1
    assert metrics["HitRate@20"] == pytest.approx(1.0)


def test_evaluate_method_source_artifact_loads_recent2y_bucket_profile(tmp_path: Path) -> None:
    candidates_path = tmp_path / "source" / "candidates.jsonl"
    source_manifest_path = tmp_path / "source" / "source_index_manifest.json"
    valid_path = tmp_path / "data" / "canonical_interactions.valid.jsonl"
    clean_manifest_path = tmp_path / "data" / "manifest.json"
    eligible_manifest_path = tmp_path / "eligible_user_manifest.json"
    profile_path = tmp_path / "governance" / "user_quality_profile.jsonl"
    output_dir = tmp_path / "eval"

    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "rank": 1, "source": "co_visit_fallback_repair"},
            {"user_id": "u2", "item_id": "miss", "rank": 1, "source": "co_visit_fallback_repair"},
        ],
    )
    _write_json(source_manifest_path, {"source": "co_visit_fallback_repair", "candidates_path": str(candidates_path)})
    _write_jsonl(valid_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1}, {"user_id": "u2", "parent_asin": "hit2", "label_binary": 1}])
    _write_json(clean_manifest_path, {"split_paths": {"valid": str(valid_path)}})
    _write_jsonl(profile_path, [{"user_id": "u1", "quality_bucket_v2": "fallback_only"}, {"user_id": "u2", "quality_bucket_v2": "sequence_sufficient"}])
    _write_json(
        eligible_manifest_path,
        {
            "eligible_user_buckets": ["fallback_only", "sequence_sufficient"],
            "eligible_user_ids": ["u1", "u2"],
            "user_quality_profile_path": str(profile_path),
        },
    )

    evaluate_method_source_artifact(
        source_index_manifest_path=source_manifest_path,
        clean_manifest_path=clean_manifest_path,
        eligible_user_manifest_path=eligible_manifest_path,
        output_dir=output_dir,
        label_splits=("valid",),
        metric_ks=(20,),
        overwrite=True,
        enforce_venv=False,
    )

    segment_metrics = read_json(output_dir / "segment_metrics.json")
    assert segment_metrics["fallback_only"]["HitRate@20"] == pytest.approx(1.0)
    assert segment_metrics["sequence_sufficient"]["HitRate@20"] == pytest.approx(0.0)
