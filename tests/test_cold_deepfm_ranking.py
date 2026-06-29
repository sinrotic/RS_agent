from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.online.ranking.cold_deepfm import (
    COLD_MODEL_TYPE,
    DEEPFM_MODEL_TYPE,
    build_cold_deepfm_training_rows,
    rank_with_cold,
    rank_with_deepfm,
    score_deepfm_model,
    should_apply_cold,
    train_cold_ranker,
    train_deepfm_ranker,
)
from rs_core.common.recsys_types import MergedCandidate
from rs_lab.experiments.ranking.build_cold_deepfm_ranking_training_dataset import (
    build_cold_deepfm_ranking_training_dataset_from_files,
)
from rs_lab.experiments.ranking.build_pool500_cold_deepfm_dataset import build_pool500_cold_deepfm_dataset_from_files
from rs_lab.experiments.ranking.build_pool500_frozen_candidate_eval_dataset import (
    build_pool500_frozen_candidate_eval_dataset_from_files,
    compute_candidate_coverage_gate,
)
from rs_lab.experiments.ranking.run_cold_deepfm_offline_train_eval import run_cold_deepfm_offline_train_eval_from_files
from rs_lab.experiments.ranking.run_pool500_cold_deepfm_chain import run_pool500_cold_deepfm_chain_from_files


def test_build_cold_deepfm_training_rows_joins_labels_and_passes_gates():
    candidates_by_user = {
        "u1": [
            MergedCandidate(item_id="hit", sources=["semantic"], source_scores={"semantic": 0.9}, category="book", metadata={"average_rating": 4.5}),
            MergedCandidate(item_id="miss", sources=["popular"], source_scores={"popular": 0.3}, category="book", metadata={}),
        ]
    }
    label_rows = [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "train"}]

    dataset = build_cold_deepfm_training_rows(candidates_by_user, label_rows)

    assert dataset["status"] == "PASS"
    assert dataset["summary"]["rows"] == 2
    assert dataset["summary"]["positive_rows"] == 1
    assert dataset["summary"]["candidate_positive_coverage"] == 1.0
    assert dataset["feature_contract_gate"]["status"] == "PASS"
    assert dataset["leakage_gate"]["status"] == "PASS"
    assert "candidate" not in dataset["public_rows"][0]


def test_build_cold_deepfm_training_rows_rejects_holdout_or_test_splits():
    candidates_by_user = {
        "u1": [MergedCandidate(item_id="hit", sources=["semantic"], source_scores={"semantic": 0.9})]
    }
    label_rows = [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "holdout"}]

    dataset = build_cold_deepfm_training_rows(candidates_by_user, label_rows)

    assert dataset["status"] == "STOP"
    assert dataset["label_split_gate"]["status"] == "STOP"
    assert dataset["label_split_gate"]["rejected_splits"] == ["holdout"]


def test_build_cold_deepfm_training_rows_ignores_holdout_hit_as_training_label():
    candidates_by_user = {
        "u1": [MergedCandidate(item_id="hit", sources=["semantic"], source_scores={"semantic": 0.9})]
    }
    label_rows = [{"user_id": "u1", "parent_asin": "hit", "holdout_hit": True, "split": "train"}]

    dataset = build_cold_deepfm_training_rows(candidates_by_user, label_rows)

    assert dataset["status"] == "PASS"
    assert dataset["summary"]["positive_rows"] == 0
    assert dataset["summary"]["positive_label_pairs"] == 0


def test_cold_ranker_keeps_positive_in_top_n_with_separable_features():
    rows = [
        {"user_id": "u1", "item_id": "hit", "label": 1, "features": {"score_semantic": 1.0}},
        {"user_id": "u1", "item_id": "miss", "label": 0, "features": {"score_semantic": 0.0}},
        {"user_id": "u2", "item_id": "hit2", "label": 1, "features": {"score_semantic": 1.0}},
        {"user_id": "u2", "item_id": "miss2", "label": 0, "features": {"score_semantic": 0.0}},
    ]

    model = train_cold_ranker(rows, {"epochs": 3, "learning_rate": 0.2})
    ranked = rank_with_cold(rows, model, top_n=1)

    assert model["model_type"] == COLD_MODEL_TYPE
    assert ranked["rows_after"] == 2
    assert ranked["positive_survival_at_top_n"] == 1.0
    assert {user_rows[0]["item_id"] for user_rows in ranked["kept_by_user"].values()} == {"hit", "hit2"}


def test_cold_gate_uses_max_candidate_count_threshold():
    rows = [
        {"user_id": "u1", "item_id": "i1", "label": 0, "features": {"bias": 1.0}},
        {"user_id": "u1", "item_id": "i2", "label": 1, "features": {"bias": 1.0}},
        {"user_id": "u2", "item_id": "i3", "label": 0, "features": {"bias": 1.0}},
    ]

    assert should_apply_cold(rows, 2) is False
    assert should_apply_cold(rows, 1) is True
    assert should_apply_cold(rows, None) is True


def test_ranker_ties_preserve_candidate_rank_before_item_id():
    rows = [
        {"user_id": "u1", "item_id": "z", "label": 0, "features": {"bias": 1.0}, "candidate_rank": 2},
        {"user_id": "u1", "item_id": "a", "label": 1, "features": {"bias": 1.0}, "candidate_rank": 1},
    ]
    model = train_deepfm_ranker(rows, {"epochs": 0})

    ranked = rank_with_deepfm(rows, model, top_k=2)

    assert [row["item_id"] for row in ranked["final_by_user"]["u1"]] == ["a", "z"]


def test_deepfm_ranker_trains_scores_and_ranks_rows():
    rows = [
        {"user_id": "u1", "item_id": "hit", "label": 1, "features": {"score_semantic": 1.0, "multi_source": 1.0}},
        {"user_id": "u1", "item_id": "miss", "label": 0, "features": {"score_semantic": 0.0, "multi_source": 0.0}},
        {"user_id": "u2", "item_id": "hit2", "label": 1, "features": {"score_semantic": 1.0, "multi_source": 1.0}},
        {"user_id": "u2", "item_id": "miss2", "label": 0, "features": {"score_semantic": 0.0, "multi_source": 0.0}},
    ]

    model = train_deepfm_ranker(rows, {"epochs": 2, "learning_rate": 0.05, "seed": 3})
    score = score_deepfm_model(rows[0]["features"], model)
    ranked = rank_with_deepfm(rows, model, top_k=1)

    assert model["model_type"] == DEEPFM_MODEL_TYPE
    assert model["training"]["status"] == "trained"
    assert math.isfinite(score)
    assert ranked["rows_after"] == 2
    assert ranked["positive_survival_at_top_k"] >= 0.5


def test_pool500_cold_deepfm_file_smoke_writes_diagnostic_report(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    labels_path = tmp_path / "pool500_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
            {"user_id": "u2", "item_id": "hit2", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "toy"}},
            {"user_id": "u2", "item_id": "miss2", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "toy"}},
        ],
    )
    _write_jsonl(
        labels_path,
        [
            {"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "train"},
            {"user_id": "u2", "parent_asin": "hit2", "label_binary": 1, "split": "train"},
        ],
    )

    report = run_pool500_cold_deepfm_chain_from_files(
        pool500_candidates_path=candidates_path,
        label_artifact_path=labels_path,
        output_dir=tmp_path / "out",
        cold_top_n=1,
        deepfm_top_k=1,
        cold_candidate_threshold=1,
        enforce_venv=False,
    )

    assert report["status"] == "PASS"
    assert report["diagnostic_only"] is True
    assert report["ranking_replacement_allowed"] is False
    assert report["ranking_strategy"] == "cold_then_deepfm"
    assert report["training_sample_summary"]["positive_rows"] == 2
    assert report["cold"]["applied"] is True
    assert report["cold"]["positive_survival_at_top_n"] == 1.0
    assert report["label_split_gate"]["status"] == "PASS"
    assert report["final_rankings"]["u1"][0]["sources"] == ["semantic"]
    assert report["final_rankings"]["u1"][0]["category"] == "book"
    assert Path(report["output_paths"]["comparison_json"]).is_file()
    assert Path(report["output_paths"]["comparison_md"]).is_file()


def test_pool500_cold_deepfm_chain_skips_cold_when_candidates_within_threshold(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    labels_path = tmp_path / "pool500_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "train"}])

    report = run_pool500_cold_deepfm_chain_from_files(
        pool500_candidates_path=candidates_path,
        label_artifact_path=labels_path,
        output_dir=tmp_path / "out",
        cold_top_n=1,
        deepfm_top_k=1,
        cold_candidate_threshold=2,
        enforce_venv=False,
    )

    assert report["status"] == "PASS"
    assert report["ranking_strategy"] == "direct_deepfm"
    assert report["cold"]["status"] == "SKIPPED"
    assert report["cold"]["applied"] is False
    assert report["cold"]["rows_after"] == report["cold"]["rows_before"]
    assert report["deepfm"]["status"] == "PASS"


def test_pool500_cold_deepfm_chain_does_not_train_deepfm_when_blocked(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    labels_path = tmp_path / "pool500_labels.jsonl"
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1}])
    _write_jsonl(labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "test"}])

    report = run_pool500_cold_deepfm_chain_from_files(
        pool500_candidates_path=candidates_path,
        label_artifact_path=labels_path,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["status"] == "STOP"
    assert report["deepfm"]["status"] == "STOP"
    assert report["final_rankings"] == {}


def test_pool500_cold_deepfm_dataset_builder_writes_l4_artifacts(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    train_labels_path = tmp_path / "train_labels.jsonl"
    valid_labels_path = tmp_path / "valid_labels.jsonl"
    test_labels_path = tmp_path / "test_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(train_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "train"}])
    _write_jsonl(valid_labels_path, [{"user_id": "u1", "parent_asin": "miss", "label_binary": 1, "split": "valid"}])
    _write_jsonl(test_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "test"}])

    manifest = build_pool500_cold_deepfm_dataset_from_files(
        pool500_candidates_path=candidates_path,
        train_label_artifact_path=train_labels_path,
        valid_label_artifact_path=valid_labels_path,
        test_label_artifact_path=test_labels_path,
        output_dir=tmp_path / "dataset",
        enforce_venv=False,
    )

    assert manifest["status"] == "PASS"
    output_paths = manifest["output_paths"]
    train_rows = [json.loads(line) for line in Path(output_paths["train_rows"]).read_text(encoding="utf-8").splitlines()]
    valid_rows = [json.loads(line) for line in Path(output_paths["valid_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(output_paths["dataset_audit"]).read_text(encoding="utf-8"))
    feature_manifest = json.loads(Path(output_paths["feature_manifest"]).read_text(encoding="utf-8"))

    assert len(train_rows) == 2
    assert train_rows[0]["split"] == "train"
    assert "candidate" not in train_rows[0]
    assert train_rows[0]["sources"] == ["semantic"]
    assert train_rows[0]["category"] == "book"
    assert sum(row["label"] for row in train_rows) == 1
    assert sum(row["label"] for row in valid_rows) == 1
    assert audit["offline_training_only"] is True
    assert audit["ranking_replacement_allowed"] is False
    assert feature_manifest["feature_count"] > 0


def test_pool500_cold_deepfm_dataset_builder_blocks_holdout_training_labels(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    train_labels_path = tmp_path / "train_labels.jsonl"
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}}])
    _write_jsonl(train_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "holdout"}])

    manifest = build_pool500_cold_deepfm_dataset_from_files(
        pool500_candidates_path=candidates_path,
        train_label_artifact_path=train_labels_path,
        output_dir=tmp_path / "dataset",
        enforce_venv=False,
    )

    output_paths = manifest["output_paths"]
    train_rows_text = Path(output_paths["train_rows"]).read_text(encoding="utf-8")
    split_gate = json.loads(Path(output_paths["split_gate"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "STOP"
    assert train_rows_text == ""
    assert split_gate["train"]["rejected_splits"] == ["holdout"]


def test_pool500_cold_deepfm_dataset_builder_ignores_holdout_hit_label_field(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    train_labels_path = tmp_path / "train_labels.jsonl"
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}}])
    _write_jsonl(train_labels_path, [{"user_id": "u1", "parent_asin": "hit", "holdout_hit": True, "split": "train"}])

    manifest = build_pool500_cold_deepfm_dataset_from_files(
        pool500_candidates_path=candidates_path,
        train_label_artifact_path=train_labels_path,
        output_dir=tmp_path / "dataset",
        enforce_venv=False,
    )

    train_rows = [json.loads(line) for line in Path(manifest["output_paths"]["train_rows"]).read_text(encoding="utf-8").splitlines()]

    assert manifest["status"] == "PASS"
    assert train_rows[0]["label"] == 0


def test_cold_deepfm_ranking_training_builder_writes_positive_rich_schema_and_gates(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {
                "user_id": f"u{index}",
                "parent_asin": f"hit{index}",
                "label_binary": 1,
                "split": "train",
                "event_time": f"2023-03-{(index % 20) + 1:02d}T00:00:00Z",
            }
            for index in range(20)
        ]
        + [
            {"user_id": "catalog", "parent_asin": "neg1", "label_binary": 0, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "catalog", "parent_asin": "neg2", "label_binary": 0, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
        ],
    )

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=1,
        seed=7,
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["ranking_training_dataset"]).read_text(encoding="utf-8").splitlines()]
    gate_report = json.loads(Path(manifest["output_paths"]["gate_report"]).read_text(encoding="utf-8"))
    report = json.loads(Path(manifest["output_paths"]["dataset_report"]).read_text(encoding="utf-8"))
    required_fields = {
        "user_id",
        "item_id",
        "label",
        "label_semantics",
        "split",
        "event_time",
        "label_event_time",
        "negative_sampling_cutoff_time",
        "feature_cutoff_time",
        "event_time_source",
        "label_event_time_source",
        "negative_sampling_strategy",
        "negative_sampling_seed",
        "item_universe_source",
        "feature_version",
        "source_manifest_hash",
    }

    assert manifest["status"] == "PASS"
    assert len(rows) == 40
    expected_features = {
        "score_item_train_positive_count_log1p",
        "score_item_train_positive_user_count_log1p",
        "score_user_train_positive_count_log1p",
        "score_user_train_distinct_item_count_log1p",
        "has_item_train_history",
        "has_user_train_history",
    }

    assert all(required_fields <= set(row) for row in rows)
    assert sum(row["label"] for row in rows) == 20
    assert {row["label_semantics"] for row in rows} == {"observed_positive", "weak_negative"}
    assert all(expected_features <= set(row["features"]) for row in rows)
    assert all(isinstance(value, (int, float)) for row in rows for value in row["features"].values())
    assert all("candidate_rank" not in row and "candidate_sources" not in row for row in rows)
    assert gate_report["feature_gate"]["status"] == "PASS"
    assert set(gate_report["feature_gate"]["feature_names"]) == expected_features
    assert report["feature_policy"]["feature_generation_scope"] == "train_only_interactions"
    assert report["cold_bucket_summary"]["recommended_filter_challenger_order"] == ["warm_user_first", "warm_item_second"]
    assert report["cold_bucket_summary"]["bucket_counts"]
    weak_negative = next(row for row in rows if row["label_semantics"] == "weak_negative")
    assert weak_negative["event_time"] == weak_negative["negative_sampling_cutoff_time"]
    assert weak_negative["label_event_time"] == weak_negative["negative_sampling_cutoff_time"]
    assert gate_report["positive_rich_training_gate"]["status"] == "PASS"
    assert gate_report["weak_negative_gate"]["status"] == "PASS"
    assert gate_report["row_level_time_leakage_gate"]["status"] == "PASS"
    assert report["weak_negative_disclaimer"].startswith("No exposure log")
    assert report["source_manifest_hash"]



def test_cold_deepfm_ranking_training_builder_uses_train_only_prefix_history_features(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "parent_asin": "repeat", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "u2", "parent_asin": "repeat", "label_binary": 1, "split": "train", "event_time": "2023-03-02T00:00:00Z"},
            {"user_id": "u1", "parent_asin": "next", "label_binary": 1, "split": "train", "event_time": "2023-03-03T00:00:00Z"},
        ]
        + [
            {"user_id": f"u{index}", "parent_asin": f"hit{index}", "label_binary": 1, "split": "train", "event_time": f"2023-03-{index + 4:02d}T00:00:00Z"}
            for index in range(17)
        ]
        + [
            {"user_id": "catalog", "parent_asin": "neg_before", "label_binary": 1, "split": "train", "event_time": "2023-03-01T12:00:00Z"},
            {"user_id": "catalog", "parent_asin": "neg_after", "label_binary": 1, "split": "train", "event_time": "2023-04-01T00:00:00Z"},
        ],
    )
    item_universe_path = tmp_path / "item_universe.jsonl"
    _write_jsonl(item_universe_path, [{"parent_asin": "repeat"}, {"parent_asin": "next"}, {"parent_asin": "neg_before"}, {"parent_asin": "neg_after"}])

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        item_universe_path=item_universe_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=3,
        seed=1,
        threshold_override=True,
        override_reason="prefix history fixture",
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["ranking_training_dataset"]).read_text(encoding="utf-8").splitlines()]
    first_repeat = next(row for row in rows if row["user_id"] == "u1" and row["item_id"] == "repeat" and row["label"] == 1)
    second_repeat = next(row for row in rows if row["user_id"] == "u2" and row["item_id"] == "repeat" and row["label"] == 1)
    u1_next = next(row for row in rows if row["user_id"] == "u1" and row["item_id"] == "next" and row["label"] == 1)
    neg_before = next(row for row in rows if row["item_id"] == "neg_before" and row["label"] == 0 and row["event_time"] > "2023-03-01T12:00:00+00:00")
    neg_after = next(row for row in rows if row["item_id"] == "neg_after" and row["label"] == 0 and row["event_time"] < "2023-04-01T00:00:00+00:00")

    assert first_repeat["features"]["has_item_train_history"] == 0.0
    assert second_repeat["features"]["score_item_train_positive_count_log1p"] == pytest.approx(math.log1p(1))
    assert second_repeat["features"]["score_item_train_positive_user_count_log1p"] == pytest.approx(math.log1p(1))
    assert u1_next["features"]["score_user_train_positive_count_log1p"] == pytest.approx(math.log1p(1))
    assert u1_next["features"]["score_user_train_distinct_item_count_log1p"] == pytest.approx(math.log1p(1))
    assert neg_before["features"]["has_item_train_history"] == 1.0
    assert neg_after["features"]["has_item_train_history"] == 0.0


def test_cold_deepfm_ranking_training_builder_negative_sampling_does_not_exclude_future_user_positives(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "parent_asin": "current", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "u1", "parent_asin": "future", "label_binary": 1, "split": "train", "event_time": "2023-04-01T00:00:00Z"},
        ]
        + [
            {"user_id": f"u{index}", "parent_asin": f"hit{index}", "label_binary": 1, "split": "train", "event_time": f"2023-03-{index + 2:02d}T00:00:00Z"}
            for index in range(18)
        ],
    )
    item_universe_path = tmp_path / "item_universe.jsonl"
    _write_jsonl(item_universe_path, [{"parent_asin": "current"}, {"parent_asin": "future"}])

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        item_universe_path=item_universe_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=1,
        seed=1,
        threshold_override=True,
        override_reason="negative sampling prefix fixture",
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["ranking_training_dataset"]).read_text(encoding="utf-8").splitlines()]
    early_future_negative = next(row for row in rows if row["user_id"] == "u1" and row["item_id"] == "future" and row["label"] == 0)
    current_as_negative = [row for row in rows if row["user_id"] == "u1" and row["item_id"] == "current" and row["label"] == 0]

    assert early_future_negative["negative_sampling_cutoff_time"] == "2023-03-01T00:00:00+00:00"
    assert current_as_negative == []


def test_cold_deepfm_ranking_training_builder_accepts_train_positive_event_type(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": f"u{index}", "parent_asin": f"hit{index}", "event_type": "train_positive"}
            for index in range(20)
        ]
        + [{"user_id": "catalog", "parent_asin": "neg", "event_type": "train_negative"}],
    )

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=1,
        max_rows=100,
        fast_source_fingerprint=True,
        enforce_venv=False,
    )

    assert manifest["status"] == "PASS"
    assert manifest["max_rows"] == 100
    assert manifest["fast_source_fingerprint"] is True
    assert manifest["stats"]["positive_rows"] == 20
    assert manifest["stats"]["negative_rows"] == 20



def test_cold_deepfm_ranking_training_builder_records_2y1m3m_eval_only_audit(tmp_path: Path):
    train_path = tmp_path / "canonical_interactions.train.jsonl"
    valid_path = tmp_path / "canonical_interactions.valid.jsonl"
    test_path = tmp_path / "canonical_interactions.test.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": f"u{index}", "parent_asin": f"hit{index}", "label_binary": 1, "split": "train"}
            for index in range(20)
        ]
        + [{"user_id": "catalog", "parent_asin": "neg", "label_binary": 0, "split": "train"}],
    )
    _write_jsonl(valid_path, [{"user_id": "u_valid", "parent_asin": "valid_hit", "label_binary": 1, "split": "valid"}])
    _write_jsonl(test_path, [{"user_id": "u_test", "parent_asin": "test_hit", "label_binary": 1, "split": "test"}])

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        valid_interactions_path=valid_path,
        test_interactions_path=test_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=1,
        max_rows=100,
        fast_source_fingerprint=True,
        enforce_venv=False,
    )

    report = json.loads(Path(manifest["output_paths"]["dataset_report"]).read_text(encoding="utf-8"))
    audit = manifest["dataset_source_audit"]

    assert manifest["status"] == "PASS"
    assert manifest["dataset_id"] == "amazon_2023_recall_recent_2y_1m_3m"
    assert manifest["dataset_window"] == "2y1m3m"
    assert manifest["fast_source_fingerprint"] is True
    assert audit["train_used_for"] == "training"
    assert audit["valid_used_for"] == "evaluation_only"
    assert audit["test_used_for"] == "evaluation_only"
    assert audit["valid_used_for_training"] is False
    assert audit["test_used_for_training"] is False
    assert audit["valid_test_used_for_negative_sampling"] is False
    assert audit["valid_test_used_for_candidate_generation"] is False
    assert report["dataset_source_audit"] == audit
    assert manifest["stats"]["positive_rows"] == 20



def test_cold_deepfm_ranking_training_builder_samples_negatives_without_full_shuffle(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "catalog", "parent_asin": "neg1", "label_binary": 0, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "catalog", "parent_asin": "neg2", "label_binary": 0, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "catalog", "parent_asin": "neg3", "label_binary": 0, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
        ],
    )

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=3,
        threshold_override=True,
        override_reason="sampling fixture",
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["ranking_training_dataset"]).read_text(encoding="utf-8").splitlines()]
    negative_items = [row["item_id"] for row in rows if row["label"] == 0]
    assert len(negative_items) == 3
    assert len(set(negative_items)) == 3
    assert "hit" not in negative_items
    assert "sample_without_full_item_universe_shuffle" in manifest["report"]["exclusion_rules"]



def test_cold_deepfm_ranking_training_builder_blocks_eval_split_leakage(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "u1", "parent_asin": "future", "label_binary": 1, "split": "test", "event_time": "2023-07-01T00:00:00Z"},
        ],
    )

    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        output_dir=tmp_path / "ranking_training",
        negatives_per_positive=1,
        threshold_override=True,
        override_reason="fixture only",
        enforce_venv=False,
    )

    rows_text = Path(manifest["output_paths"]["ranking_training_dataset"]).read_text(encoding="utf-8")
    gate_report = json.loads(Path(manifest["output_paths"]["gate_report"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "STOP"
    assert rows_text == ""
    assert gate_report["training_split_gate"]["status"] == "STOP"
    assert gate_report["training_split_gate"]["rejected_splits"] == ["test"]
    assert gate_report["row_level_time_leakage_gate"]["valid_test_holdout_used_for_training"] is True



def test_pool500_frozen_candidate_eval_builder_writes_required_schema_and_hashes(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
            {"user_id": "u2", "item_id": "miss2", "source": "popular", "score": 0.1, "rank": 1, "metadata": {"category": "toy"}},
        ],
    )
    _write_jsonl(
        eval_labels_path,
        [
            {"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "test", "label_event_time": "2023-07-01T00:00:00Z"},
            {"user_id": "u2", "parent_asin": "outside", "label_binary": 1, "split": "test", "label_event_time": "2023-07-02T00:00:00Z"},
        ],
    )

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    output_paths = manifest["output_paths"]
    rows = [json.loads(line) for line in Path(output_paths["eval_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(output_paths["dataset_audit"]).read_text(encoding="utf-8"))
    coverage_gate = json.loads(Path(output_paths["coverage_gate"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "PASS"
    assert manifest["ranking_effect_conclusion_allowed"] is False
    assert len(rows) == 3
    hit_row = next(row for row in rows if row["item_id"] == "hit")
    miss_row = next(row for row in rows if row["item_id"] == "miss")
    assert hit_row["label"] == 1
    assert hit_row["label_used_for"] == "evaluation_only"
    assert hit_row["label_event_time"] == "2023-07-01T00:00:00Z"
    assert hit_row["candidate_rank"] == 1
    assert hit_row["candidate_sources"] == ["semantic"]
    assert hit_row["candidate_artifact_sha256"]
    assert hit_row["eval_label_source_sha256"]
    assert miss_row["label"] == 0
    assert miss_row["label_event_time"] is None
    assert hit_row["full_label_denominator"] == 2
    assert hit_row["in_candidate_denominator"] == 1
    assert coverage_gate["status"] == "STOP_FOR_RANKING_EFFECT"
    assert coverage_gate["full_label_denominator"] == 2
    assert coverage_gate["in_candidate_positives"] == 1
    assert audit["label_used_for"] == "evaluation_only"
    assert audit["oracle_injection_gate"]["status"] == "PASS"
    assert audit["recall_window_handoff"]["required"] is True


def test_pool500_frozen_candidate_eval_builder_adds_train_only_history_features(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "u2", "parent_asin": "other_item", "label_binary": 1, "split": "train", "event_time": "2023-03-02T00:00:00Z"},
        ],
    )
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "warm_item", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "future_only", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "future_only", "label_binary": 1, "split": "test", "label_event_time": "2023-07-01T00:00:00Z"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        train_interactions_path=train_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    warm_row = next(row for row in rows if row["item_id"] == "warm_item")
    future_row = next(row for row in rows if row["item_id"] == "future_only")
    expected_features = {
        "score_item_train_positive_count_log1p",
        "score_item_train_positive_user_count_log1p",
        "score_user_train_positive_count_log1p",
        "score_user_train_distinct_item_count_log1p",
        "has_item_train_history",
        "has_user_train_history",
    }

    assert manifest["status"] == "PASS"
    assert all(expected_features <= set(row["features"]) for row in rows)
    assert warm_row["features"]["has_user_train_history"] == 1.0
    assert warm_row["features"]["has_item_train_history"] == 1.0
    assert future_row["label"] == 1
    assert future_row["label_used_for"] == "evaluation_only"
    assert future_row["features"]["has_user_train_history"] == 1.0
    assert future_row["features"]["has_item_train_history"] == 0.0
    assert future_row["features"]["score_item_train_positive_count_log1p"] == 0.0
    assert audit["history_feature_audit"]["status"] == "PASS"
    assert audit["history_feature_audit"]["valid_test_labels_used_for_features"] is False
    assert audit["history_feature_audit"]["eval_label_event_time_used_for_features"] is False


def test_pool500_frozen_candidate_eval_builder_blocks_mixed_split_history_features(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    train_path = tmp_path / "mixed_interactions.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "parent_asin": "future_only", "label_binary": 1, "split": "test", "event_time": "2023-07-01T00:00:00Z"}])
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "future_only", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}}])
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "future_only", "label_binary": 1, "split": "test", "label_event_time": "2023-07-01T00:00:00Z"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        train_interactions_path=train_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "STOP"
    assert audit["history_feature_audit"]["status"] == "STOP"
    assert audit["history_feature_audit"]["valid_test_labels_used_for_features"] is True
    assert audit["history_feature_audit"]["context"]["train_split_gate"]["rejected_splits"] == ["test"]
    assert {blocker["code"] for blocker in audit["blockers"]} == {"EVAL_HISTORY_FEATURE_GATE_NOT_PASS"}


def test_pool500_frozen_candidate_eval_builder_blocks_missing_positive_label_time_for_history_features(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"}])
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "warm_item", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}}])
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "valid"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        train_interactions_path=train_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "STOP"
    assert audit["history_feature_audit"]["status"] == "STOP"
    assert audit["history_feature_audit"]["missing_positive_label_event_time_rows"]


def test_pool500_frozen_candidate_eval_builder_checks_all_positive_label_times_with_history_features(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"}])
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "warm_item", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}}])
    _write_jsonl(
        eval_labels_path,
        [
            {"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "valid", "unix_timestamp": 1688169600},
            {"user_id": "u2", "parent_asin": "outside_candidate_pool", "label_binary": 1, "split": "valid"},
        ],
    )

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        train_interactions_path=train_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8").splitlines()]

    assert manifest["status"] == "STOP"
    assert next(row for row in rows if row["label"] == 1)["label_event_time"] == 1688169600
    assert audit["history_feature_audit"]["status"] == "STOP"
    missing_rows = audit["history_feature_audit"]["missing_positive_label_event_time_rows"]
    assert missing_rows == [{"label_row_index": 2, "user_id": "u2", "item_id": "outside_candidate_pool"}]


def test_pool500_frozen_candidate_eval_builder_blocks_feature_cutoff_after_label_time(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    train_path = tmp_path / "train_interactions.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"}])
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "warm_item", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}}])
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "warm_item", "label_binary": 1, "split": "valid", "label_event_time": "2023-04-01T00:00:00Z"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        train_interactions_path=train_path,
        eval_feature_cutoff_time="2023-07-01T00:00:00Z",
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "STOP"
    assert audit["history_feature_audit"]["status"] == "STOP"
    assert audit["history_feature_audit"]["feature_cutoff_after_label_event_time_rows"]


def test_pool500_frozen_candidate_eval_builder_accepts_diagnostic_repair_sources_with_score_fallback(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {
                "user_id": "u1",
                "item_id": "hit",
                "source": "cold_start_category_sibling",
                "source_scores": {"cold_start_category_sibling": 0.7},
                "rank": 1,
                "metadata": {"category": "book"},
            },
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "valid"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))

    assert manifest["status"] == "PASS"
    assert rows[0]["candidate_sources"] == ["cold_start_category_sibling"]
    assert audit["source_manifest"]["adapter_score_fallback_allowed"] is True
    assert "cold_start_category_sibling" in audit["source_manifest"]["adapter_extra_allowed_sources"]
    assert audit["adapter_summary"]["diagnostic_count"] >= 1
    assert audit["adapter_diagnostic_summary"]["score_fallback_counts_by_reason"] == {"source_scores": 1}
    assert audit["adapter_diagnostic_summary"]["score_fallback_counts_by_source"] == {"cold_start_category_sibling": 1}
    assert audit["adapter_diagnostic_summary"]["score_fallback_sample_rows"][0]["row_missing_score"] is True


def test_candidate_coverage_gate_passes_mechanical_thresholds():
    candidates_by_user = {}
    label_by_pair = {}
    for index in range(500):
        user_id = f"u{index}"
        item_id = f"hit{index}"
        candidates_by_user[user_id] = [MergedCandidate(item_id=item_id, sources=["semantic"], source_scores={"semantic": 1.0})]
        label_by_pair[(user_id, item_id)] = {"split": "test", "label_event_time": "2023-07-01"}

    gate = compute_candidate_coverage_gate(candidates_by_user, label_by_pair)

    assert gate["status"] == "PASS"
    assert gate["user_gate_threshold"] == 100
    assert gate["positive_gate_threshold"] == 500
    assert gate["in_candidate_positive_users"] == 500
    assert gate["in_candidate_positives"] == 500


def test_pool500_frozen_candidate_eval_builder_supports_bounded_preflight_read(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
            {"user_id": "u2", "item_id": "hit2", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "valid"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        max_candidate_users=1,
        fast_source_fingerprint=True,
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    assert audit["source_manifest"]["candidate_rows_read"] == 2
    assert audit["source_manifest"]["max_candidate_users"] == 1
    assert audit["source_manifest"]["fingerprint_mode"] == "path_size_mtime"
    assert audit["dataset_summary"]["users"] == 1



def test_pool500_frozen_candidate_eval_builder_filters_eval_labels_by_user_allowlist(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    allowlist_path = tmp_path / "eval_users.txt"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u2", "item_id": "outside", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(
        eval_labels_path,
        [
            {"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "test"},
            {"user_id": "u2", "parent_asin": "outside", "label_binary": 1, "split": "test"},
        ],
    )
    allowlist_path.write_text("u1\n", encoding="utf-8")

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        eval_user_allowlist_path=allowlist_path,
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))

    assert {row["user_id"] for row in rows if row["label"] == 1} == {"u1"}
    assert rows[0]["full_label_denominator"] == 1
    assert audit["alignment_audit"]["eval_user_allowlist_enabled"] is True
    assert audit["alignment_audit"]["eval_label_rows_filtered_by_allowlist"] == 1
    assert audit["alignment_audit"]["label_injection_allowed"] is False
    assert audit["oracle_injection_gate"]["status"] == "PASS"


def test_pool500_frozen_candidate_eval_builder_stream_filters_candidates_from_eval_labels(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "noise1", "item_id": "n1", "source": "popular", "score": 0.1, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "noise2", "item_id": "n2", "source": "popular", "score": 0.1, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "valid"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        candidate_users_from_eval_labels=True,
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))

    assert [row["user_id"] for row in rows] == ["u1", "u1"]
    assert sum(row["label"] for row in rows) == 1
    assert audit["source_manifest"]["candidate_rows_read"] == 2
    assert audit["source_manifest"]["candidate_rows_filtered_by_user"] == 2
    assert audit["alignment_audit"]["candidate_users_from_eval_labels"] is True
    assert audit["alignment_audit"]["label_source_used_for_candidate_generation"] is False


def test_pool500_frozen_candidate_eval_builder_blocks_candidate_label_fields(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [{"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}, "label": 1}],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "test"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    rows_text = Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8")

    assert manifest["status"] == "STOP"
    assert rows_text
    assert audit["oracle_injection_gate"]["status"] == "STOP"
    assert audit["oracle_injection_gate"]["candidate_rows_with_forbidden_label_fields"][0]["forbidden_label_fields"] == ["label"]


def test_pool500_frozen_candidate_eval_builder_blocks_candidate_time_label_aliases(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}, "event_time": "2023-07-01T00:00:00Z"},
            {"user_id": "u1", "item_id": "miss", "source": "semantic", "score": 0.5, "rank": 2, "metadata": {"category": "book"}, "unix_timestamp": 1688169600},
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "hit", "label_binary": 1, "split": "test", "label_event_time": "2023-07-01T00:00:00Z"}])

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    forbidden_rows = audit["oracle_injection_gate"]["candidate_rows_with_forbidden_label_fields"]

    assert manifest["status"] == "STOP"
    assert audit["oracle_injection_gate"]["status"] == "STOP"
    assert forbidden_rows[0]["forbidden_label_fields"] == ["event_time"]
    assert forbidden_rows[1]["forbidden_label_fields"] == ["unix_timestamp"]


def test_cold_deepfm_offline_train_eval_uses_separate_inputs_and_refuses_low_coverage_effect_claims(tmp_path: Path):
    train_interactions_path = tmp_path / "train_interactions.jsonl"
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    _write_jsonl(
        train_interactions_path,
        [
            {
                "user_id": f"u{index}",
                "parent_asin": f"hit{index}",
                "label_binary": 1,
                "split": "train",
                "event_time": f"2023-03-{(index % 20) + 1:02d}T00:00:00Z",
            }
            for index in range(20)
        ],
    )
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "hit1", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {"category": "book"}},
            {"user_id": "u1", "item_id": "miss", "source": "popular", "score": 0.1, "rank": 2, "metadata": {"category": "book"}},
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "hit1", "label_binary": 1, "split": "test"}])
    train_manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_interactions_path,
        output_dir=tmp_path / "train_dataset",
        negatives_per_positive=1,
        enforce_venv=False,
    )
    eval_manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    report = run_cold_deepfm_offline_train_eval_from_files(
        train_dataset_path=Path(train_manifest["output_paths"]["ranking_training_dataset"]),
        eval_dataset_path=Path(eval_manifest["output_paths"]["eval_rows"]),
        output_dir=tmp_path / "offline_eval",
        cold_top_n=2,
        deepfm_top_k=1,
        enforce_venv=False,
    )

    assert report["status"] == "PASS"
    assert report["separate_train_eval_inputs"] is True
    assert report["source_gates"]["candidate_coverage_gate"]["status"] == "STOP_FOR_RANKING_EFFECT"
    assert report["ranking_effect_conclusion_allowed"] is False
    assert report["ranking_effect_conclusion_refused"] is True
    assert report["ranking_effect_refusal"]["status"] == "STOP_FOR_RANKING_EFFECT"
    assert report["train_summary"]["positive_rows"] == 20
    assert report["train_summary"]["feature_names"] != ["bias"]
    assert "score_item_train_positive_count_log1p" in report["train_summary"]["feature_names"]
    assert report["eval_summary"]["positive_rows"] == 1
    assert report["evaluation_metrics"]["metric_scope"] == "frozen_candidate_rows_only"
    assert Path(report["output_paths"]["report"]).is_file()
    assert Path(report["output_paths"]["manifest"]).is_file()
    assert Path(report["output_paths"]["cold_model"]).is_file()
    assert Path(report["output_paths"]["deepfm_model"]).is_file()
    assert Path(report["output_paths"]["metrics"]).is_file()
    assert Path(report["output_paths"]["comparison"]).is_file()
    assert Path(report["output_paths"]["final_rankings"]).is_file()


def test_cold_deepfm_offline_train_eval_infers_stop_gate_from_eval_denominators(tmp_path: Path):
    train_path = tmp_path / "ranking_training_dataset.jsonl"
    eval_path = tmp_path / "eval_rows.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": f"u{index}", "item_id": f"hit{index}", "label": 1, "features": {"bias": 1.0}}
            for index in range(20)
        ]
        + [
            {"user_id": f"u{index}", "item_id": f"neg{index}", "label": 0, "features": {"bias": 0.0}}
            for index in range(20)
        ],
    )
    _write_jsonl(
        eval_path,
        [
            {
                "user_id": "u1",
                "item_id": "hit1",
                "label": 1,
                "candidate_rank": 1,
                "candidate_sources": ["semantic"],
                "full_label_denominator": 3,
                "in_candidate_denominator": 1,
            },
            {
                "user_id": "u1",
                "item_id": "miss",
                "label": 0,
                "candidate_rank": 2,
                "candidate_sources": ["popular"],
                "full_label_denominator": 3,
                "in_candidate_denominator": 1,
            },
        ],
    )

    report = run_cold_deepfm_offline_train_eval_from_files(
        train_dataset_path=train_path,
        eval_dataset_path=eval_path,
        output_dir=tmp_path / "offline_eval",
        cold_top_n=2,
        deepfm_top_k=1,
        enforce_venv=False,
    )

    gate = report["source_gates"]["candidate_coverage_gate"]
    assert gate["status"] == "STOP_FOR_RANKING_EFFECT"
    assert gate["inferred_from_eval_row_denominators"] is True
    assert report["ranking_effect_conclusion_allowed"] is False
    assert report["ranking_effect_refusal"]["inferred_from_eval_row_denominators"] is True



def test_cold_deepfm_runner_missing_coverage_sidecar_never_allows_ranking_effect(tmp_path: Path):
    train_path = tmp_path / "ranking_training_dataset.jsonl"
    eval_path = tmp_path / "eval_rows.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "item_id": "hit", "label": 1, "features": {"bias": 1.0}},
            {"user_id": "u1", "item_id": "neg", "label": 0, "features": {"bias": 0.0}},
        ],
    )
    _write_jsonl(
        eval_path,
        [
            {
                "user_id": "u1",
                "item_id": "hit",
                "label": 1,
                "candidate_rank": 1,
                "candidate_sources": ["semantic"],
                "full_label_denominator": 1,
                "in_candidate_denominator": 1,
            }
        ],
    )

    report = run_cold_deepfm_offline_train_eval_from_files(
        train_dataset_path=train_path,
        eval_dataset_path=eval_path,
        output_dir=tmp_path / "offline_eval",
        cold_top_n=2,
        deepfm_top_k=1,
        enforce_venv=False,
    )

    gate = report["source_gates"]["candidate_coverage_gate"]
    assert gate["status"] == "STOP_FOR_RANKING_EFFECT"
    assert gate["coverage_gate_sidecar_missing"] is True
    assert report["ranking_effect_conclusion_allowed"] is False
    assert report["ranking_effect_conclusion_refused"] is True



def test_cold_deepfm_screening_user_first_and_item_first_differ(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    rows = [
        {"user_id": "u1", "parent_asin": "a", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
        {"user_id": "u1", "parent_asin": "b", "label_binary": 1, "split": "train", "event_time": "2023-03-02T00:00:00Z"},
        {"user_id": "u2", "parent_asin": "a", "label_binary": 1, "split": "train", "event_time": "2023-03-03T00:00:00Z"},
        {"user_id": "u2", "parent_asin": "d", "label_binary": 1, "split": "train", "event_time": "2023-03-04T00:00:00Z"},
        {"user_id": "u3", "parent_asin": "c", "label_binary": 1, "split": "train", "event_time": "2023-03-05T00:00:00Z"},
        {"user_id": "u4", "parent_asin": "c", "label_binary": 1, "split": "train", "event_time": "2023-03-06T00:00:00Z"},
    ]
    _write_jsonl(train_path, rows)

    user_first = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        output_dir=tmp_path / "user_first",
        negatives_per_positive=0,
        screening_policy="user_first",
        threshold_override=True,
        override_reason="screening fixture",
        enforce_venv=False,
    )
    item_first = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=train_path,
        output_dir=tmp_path / "item_first",
        negatives_per_positive=0,
        screening_policy="item_first",
        threshold_override=True,
        override_reason="screening fixture",
        enforce_venv=False,
    )

    user_audit = json.loads(Path(user_first["output_paths"]["screening_audit"]).read_text(encoding="utf-8"))
    item_audit = json.loads(Path(item_first["output_paths"]["screening_audit"]).read_text(encoding="utf-8"))
    assert user_audit["eligible_items"] == ["a"]
    assert item_audit["eligible_items"] == ["a", "c"]
    assert user_audit["order"] != item_audit["order"]


def test_pool500_eval_feature_contract_filters_candidates_without_label_injection(tmp_path: Path):
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    contract_path = tmp_path / "feature_contract.json"
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "keep", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {}},
            {"user_id": "u1", "item_id": "drop_item", "source": "popular", "score": 0.5, "rank": 2, "metadata": {}},
            {"user_id": "drop_user", "item_id": "keep", "source": "semantic", "score": 0.8, "rank": 1, "metadata": {}},
        ],
    )
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "drop_item", "label_binary": 1, "split": "test"}])
    contract_path.write_text(
        json.dumps(
            {
                "feature_names": ["score_item_train_positive_count_log1p"],
                "feature_version": "cold_deepfm_training_features_v2",
                "screening_policy": "user_first",
                "thresholds": {"min_user_train_positive_count": 2, "min_item_train_positive_user_count": 2},
                "eligible_users": ["u1"],
                "eligible_items": ["keep"],
                "feature_contract_hash": "fixture",
            }
        ),
        encoding="utf-8",
    )

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        feature_contract_path=contract_path,
        screening_policy="user_first",
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in Path(manifest["output_paths"]["eval_rows"]).read_text(encoding="utf-8").splitlines()]
    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    assert [row["item_id"] for row in rows] == ["keep"]
    assert sum(row["label"] for row in rows) == 0
    assert audit["screening_audit"]["candidate_rows_after"] == 1
    assert audit["feature_contract_gate"]["status"] == "PASS"
    assert audit["candidate_label_injection_allowed"] is False


def test_cold_deepfm_runner_contract_mismatch_stops_training(tmp_path: Path):
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    contract_path = tmp_path / "feature_contract.json"
    _write_jsonl(train_path, [{"user_id": "u1", "item_id": "i1", "label": 1, "feature_version": "v1", "features": {"f": 1.0}}])
    _write_jsonl(eval_path, [{"user_id": "u1", "item_id": "i1", "label": 1, "feature_version": "v1", "features": {"f": 1.0}, "full_label_denominator": 1, "in_candidate_denominator": 1}])
    contract_path.write_text(json.dumps({"feature_names": ["f"], "feature_version": "v1", "screening_policy": "user_first"}), encoding="utf-8")

    report = run_cold_deepfm_offline_train_eval_from_files(
        train_dataset_path=train_path,
        eval_dataset_path=eval_path,
        output_dir=tmp_path / "offline_eval",
        feature_contract_path=contract_path,
        expected_screening_policy="item_first",
        enforce_venv=False,
    )

    assert report["status"] == "STOP"
    assert report["feature_contract_gate"]["status"] == "STOP"
    assert report["deepfm"]["status"] == "STOP"
    assert {blocker["code"] for blocker in report["blockers"]} == {"FEATURE_CONTRACT_GATE_NOT_PASS"}


def test_pool500_eval_feature_contract_invalid_threshold_type_stops_without_crash(tmp_path: Path):
    train_path = tmp_path / "train_interactions.jsonl"
    candidates_path = tmp_path / "pool500_candidates.jsonl"
    eval_labels_path = tmp_path / "eval_labels.jsonl"
    contract_path = tmp_path / "feature_contract.json"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "parent_asin": "keep", "label_binary": 1, "split": "train", "event_time": "2023-03-01T00:00:00Z"},
            {"user_id": "u1", "parent_asin": "keep2", "label_binary": 1, "split": "train", "event_time": "2023-03-02T00:00:00Z"},
        ],
    )
    _write_jsonl(candidates_path, [{"user_id": "u1", "item_id": "keep", "source": "semantic", "score": 1.0, "rank": 1, "metadata": {}}])
    _write_jsonl(eval_labels_path, [{"user_id": "u1", "parent_asin": "keep", "label_binary": 1, "split": "valid"}])
    contract_path.write_text(
        json.dumps(
            {
                "feature_names": ["score_item_train_positive_count_log1p"],
                "feature_version": "cold_deepfm_training_features_v2",
                "screening_policy": "user_first",
                "thresholds": {"min_user_train_positive_count": "bad", "min_item_train_positive_user_count": 2},
                "eligible_users": ["u1"],
                "eligible_items": ["keep"],
                "feature_contract_hash": "fixture",
            }
        ),
        encoding="utf-8",
    )

    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=candidates_path,
        eval_label_artifact_path=eval_labels_path,
        train_interactions_path=train_path,
        feature_contract_path=contract_path,
        screening_policy="user_first",
        output_dir=tmp_path / "eval_dataset",
        enforce_venv=False,
    )

    audit = json.loads(Path(manifest["output_paths"]["dataset_audit"]).read_text(encoding="utf-8"))
    assert manifest["status"] == "STOP"
    assert audit["feature_contract_gate"]["status"] == "STOP"
    assert "invalid_screening_threshold_type" in audit["feature_contract_gate"]["reasons"]
    assert "invalid_screening_threshold_type" in audit["history_feature_audit"]["context"]["threshold_gate_reasons"]
    assert {blocker["code"] for blocker in audit["blockers"]} == {"FEATURE_CONTRACT_GATE_NOT_PASS", "EVAL_HISTORY_FEATURE_GATE_NOT_PASS"}



def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
