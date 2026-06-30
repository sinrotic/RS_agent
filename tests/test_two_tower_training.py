from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

pytestmark = [pytest.mark.experiment, pytest.mark.gpu]

from rs_core.common.io import read_json, read_jsonl, write_json, write_jsonl
from rs_core.online.recall.candidate_merge import load_two_tower_index, two_tower_candidates_for_user
from rs_core.online.recall.vector_index import VectorIndex
from rs_core.offline.training import two_tower
from rs_core.offline.training.two_tower import save_two_tower_artifacts, train_two_tower_model
from rs_core.workflow.two_tower_training import _attach_training_sample_negatives, _compact_training_sequence, build_two_tower_item_vocab, build_two_tower_seed_sidecar, build_two_tower_seed_sidecar_from_config, train_two_tower_recall
import scripts.training.train_two_tower as train_two_tower_cli
import scripts.training.two_tower_DSSM.train_two_tower_dssm as train_two_tower_dssm_cli
from scripts.training.train_two_tower import main as train_two_tower_cli_main
from scripts.training.two_tower_DSSM.train_two_tower_dssm import main as train_two_tower_dssm_cli_main


def _write_training_workflow_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()

    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["audio_seed", "audio_next"], "recent_item_sequence": ["audio_seed", "audio_next"], "negative_item_ids": ["camera_seed"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["camera_seed", "camera_next"], "recent_item_sequence": ["camera_seed", "camera_next"], "negative_item_ids": ["audio_seed"]},
        ],
    )
    write_jsonl(
        clean_dir / "canonical_interactions.train.jsonl",
        [
            {"user_id": "u1", "parent_asin": "audio_seed"},
            {"user_id": "u1", "parent_asin": "audio_next"},
            {"user_id": "u2", "parent_asin": "camera_seed"},
            {"user_id": "u2", "parent_asin": "camera_next"},
        ],
    )
    write_jsonl(clean_dir / "canonical_items.jsonl", _items())
    vocab_manifest_path = tmp_path / "item_vocab" / "two_tower_item_vocab_manifest.json"
    build_two_tower_item_vocab(
        clean_dir / "canonical_interactions.train.jsonl",
        tmp_path / "item_vocab" / "two_tower_item_vocab.jsonl",
        vocab_manifest_path,
        clean_dir / "canonical_items.jsonl",
    )

    config_path = tmp_path / "config.json"
    write_json(
        config_path,
        {
            "clean_dir": str(clean_dir),
            "evaluation_mode": "train_only",
            "two_tower_training": {
                "variant": "youtube_dnn",
                "source_name": "two_tower_youtube_dnn",
                "item_vocab_manifest": str(vocab_manifest_path),
                "min_user_positives": 2,
            },
        },
    )
    user_quality_path = tmp_path / "eligible_user_quality_manifest.json"
    write_json(
        user_quality_path,
        {
            "policy_role": "eligibility_policy_not_recall_source",
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "profiles": [
                {"user_id": "u1", "quality_bucket": "heavy"},
                {"user_id": "u2", "quality_bucket": "medium"},
            ],
        },
    )
    return {"config": config_path, "user_quality": user_quality_path}


def _sequences() -> list[dict]:
    return [
        {"user_id": "u1", "recent_positive_item_sequence": ["audio_seed", "audio_next"], "recent_item_sequence": ["audio_seed", "audio_next"]},
        {"user_id": "u2", "recent_positive_item_sequence": ["camera_seed", "camera_next"], "recent_item_sequence": ["camera_seed", "camera_next"]},
    ]


def _items() -> list[dict]:
    return [
        {"parent_asin": "audio_seed", "title_clean": "wireless earbuds", "main_category": "Audio", "item_quality_token": "item_quality:embedding_ready"},
        {"parent_asin": "audio_next", "title_clean": "bluetooth headphones", "main_category": "Audio", "item_quality_token": "item_quality:embedding_ready"},
        {"parent_asin": "camera_seed", "title_clean": "mirrorless camera", "main_category": "Camera", "item_quality_token": "item_quality:embedding_ready"},
        {"parent_asin": "camera_next", "title_clean": "camera tripod", "main_category": "Camera", "item_quality_token": "item_quality:embedding_ready"},
    ]


def test_two_tower_item_vocab_is_canonical_train_only_and_metadata_does_not_expand(tmp_path: Path):
    train_path = tmp_path / "canonical_interactions.train.jsonl"
    metadata_path = tmp_path / "canonical_items.jsonl"
    vocab_path = tmp_path / "two_tower_item_vocab.jsonl"
    manifest_path = tmp_path / "two_tower_item_vocab_manifest.json"
    write_jsonl(train_path, [{"parent_asin": "train_a"}, {"item_id": "train_b"}, {"parent_asin": "train_a"}])
    write_jsonl(
        metadata_path,
        [
            {"parent_asin": "train_a", "title_clean": "kept metadata"},
            {"parent_asin": "metadata_only", "title_clean": "must not expand"},
        ],
    )

    manifest = build_two_tower_item_vocab(train_path, vocab_path, manifest_path, metadata_path)
    rows = read_jsonl(vocab_path)

    assert {row["parent_asin"] for row in rows} == {"train_a", "train_b"}
    assert {row["item_id"] for row in rows} == {"train_a", "train_b"}
    assert "metadata_only" not in {row["parent_asin"] for row in rows}
    assert manifest["item_count"] == len(rows) == 2
    assert manifest["metadata_join_added_items"] is False
    assert manifest["content_hash"].startswith("sha256:")
    assert read_json(manifest_path) == manifest


def test_two_tower_item_vocab_min_frequency_prunes_train_items_only(tmp_path: Path):
    train_path = tmp_path / "canonical_interactions.train.jsonl"
    metadata_path = tmp_path / "canonical_items.jsonl"
    vocab_path = tmp_path / "two_tower_item_vocab.jsonl"
    manifest_path = tmp_path / "two_tower_item_vocab_manifest.json"
    write_jsonl(train_path, [{"parent_asin": "keep_a"}, {"parent_asin": "keep_a"}, {"parent_asin": "drop_b"}])
    write_jsonl(metadata_path, [{"parent_asin": "keep_a"}, {"parent_asin": "drop_b"}, {"parent_asin": "metadata_only"}])

    manifest = build_two_tower_item_vocab(train_path, vocab_path, manifest_path, metadata_path, min_frequency=2)
    rows = read_jsonl(vocab_path)

    assert [row["parent_asin"] for row in rows] == ["keep_a"]
    assert manifest["item_count"] == 1
    assert manifest["original_item_count"] == 2
    assert manifest["filtered_item_count"] == 1
    assert manifest["min_frequency"] == 2
    assert manifest["metadata_join_added_items"] is False


def test_train_two_tower_recall_rejects_eval_scoped_item_vocab_manifest(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    config = read_json(paths["config"])
    manifest_path = Path(config["two_tower_training"]["item_vocab_manifest"])
    manifest = read_json(manifest_path)
    manifest["source_paths"]["canonical_interactions_train"] = str(tmp_path / "canonical_interactions.valid.jsonl")
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="eval/valid/test/holdout"):
        train_two_tower_recall(
            paths["config"],
            output_dir=tmp_path / "artifacts",
            variant="youtube_dnn",
            config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
        )


def test_train_two_tower_cli_blocks_default_and_explicit_all(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    write_json(config_path, {"clean_dir": str(tmp_path)})

    monkeypatch.setattr(sys, "argv", ["train_two_tower.py", "--config", str(config_path)])
    with pytest.raises(SystemExit, match="variant youtube_dnn"):
        train_two_tower_cli_main()

    monkeypatch.setattr(sys, "argv", ["train_two_tower.py", "--config", str(config_path), "--variant", "all"])
    with pytest.raises(SystemExit, match="variant youtube_dnn"):
        train_two_tower_cli_main()


def test_train_two_tower_cli_maps_v2_overrides(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    write_json(config_path, {"clean_dir": str(tmp_path)})
    captured = {}

    def fake_train_two_tower_recall(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"artifact_manifest_path": "artifact.json", "recall_index_path": "recall.jsonl"}

    monkeypatch.setattr(train_two_tower_cli, "train_two_tower_recall", fake_train_two_tower_recall)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train_two_tower.py",
            "--config",
            str(config_path),
            "--variant",
            "youtube_dnn",
            "--training-sample-path",
            "outputs/recall/pool500_method_datasets/recent_2y/two_tower/formal/two_tower_train_samples.jsonl",
            "--min-user-positives",
            "2",
            "--max-samples-per-user",
            "20",
            "--batch-size",
            "256",
            "--user-history-window",
            "80",
            "--embedding-dim",
            "64",
            "--hidden-dim",
            "128",
            "--learning-rate",
            "0.001",
            "--negative-samples",
            "10",
            "--negative-sampling-power",
            "0.5",
            "--negative-sampling-version",
            "v2",
            "--unique-negatives-per-example",
            "--negative-dedup-max-attempts",
            "7",
            "--sampled-softmax-candidate-mode",
            "batch_shared",
            "--sampled-softmax-correction",
            "logq",
            "--sampled-softmax-logq-epsilon",
            "1e-9",
            "--torch-user-history-weighting",
            "recency_decay",
            "--recency-decay",
            "0.85",
            "--example-age-weighting",
            "decay",
            "--example-age-half-life-days",
            "45",
            "--example-age-min-weight",
            "0.2",
        ],
    )

    train_two_tower_cli_main()

    assert captured["kwargs"]["config_overrides"] == {
        "two_tower_training": {
            "training_sample_path": "outputs/recall/pool500_method_datasets/recent_2y/two_tower/formal/two_tower_train_samples.jsonl",
            "min_user_positives": 2,
            "max_samples_per_user": 20,
            "batch_size": 256,
            "user_history_window": 80,
            "embedding_dim": 64,
            "hidden_dim": 128,
            "learning_rate": 0.001,
            "negative_samples": 10,
            "negative_sampling_power": 0.5,
            "negative_sampling_version": "v2",
            "unique_negatives_per_example": True,
            "negative_dedup_max_attempts": 7,
            "sampled_softmax_candidate_mode": "batch_shared",
            "sampled_softmax_correction": "logq",
            "sampled_softmax_logq_epsilon": 1e-09,
            "torch_user_history_weighting": "recency_decay",
            "recency_decay": 0.85,
            "example_age_weighting": "decay",
            "example_age_half_life_days": 45.0,
            "example_age_min_weight": 0.2,
        }
    }


def test_dssm_cli_passes_score_temperature_override(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    item_vocab_manifest = tmp_path / "two_tower_dssm_item_vocab_manifest.json"
    write_json(config_path, {"two_tower_training": {"variant": "dssm"}})
    write_json(item_vocab_manifest, {"schema_version": "two_tower_item_vocab_v1"})
    captured = {}

    def fake_train_two_tower_recall(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"artifact_manifest_path": "artifact.json", "recall_index_path": "recall.jsonl"}

    monkeypatch.setattr(train_two_tower_dssm_cli, "train_two_tower_recall", fake_train_two_tower_recall)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train_two_tower_dssm.py",
            "--config",
            str(config_path),
            "--item-vocab-manifest",
            str(item_vocab_manifest),
            "--score-temperature",
            "0.1",
        ],
    )

    train_two_tower_dssm_cli_main()

    assert captured["kwargs"]["config_overrides"]["two_tower_training"]["score_temperature"] == 0.1


def test_compact_training_sequence_preserves_train_only_negative_item_ids():
    compact = _compact_training_sequence(
        {
            "user_id": "u1",
            "recent_positive_item_sequence": ["i1", "i2", "i3"],
            "recent_positive_timestamp_sequence": [1000, 2000, 3000],
            "recent_item_sequence": ["i0", "i1", "i2", "i3"],
            "recent_timestamp_sequence": [0, 1000, 2000, 3000],
            "negative_item_ids": ["n1", "", "n2"],
        },
        {"user_history_window": 2},
    )

    assert compact == {
        "user_id": "u1",
        "recent_positive_item_sequence": ["i2", "i3"],
        "recent_positive_timestamp_sequence": [2000, 3000],
        "recent_strong_positive_item_sequence": [],
        "recent_strong_positive_timestamp_sequence": [],
        "recent_item_sequence": ["i2", "i3"],
        "recent_timestamp_sequence": [2000, 3000],
        "negative_item_ids": ["n1", "n2"],
    }


def test_compact_training_sequence_keeps_timestamp_alignment_when_items_are_dropped():
    compact = _compact_training_sequence(
        {
            "user_id": "u1",
            "recent_positive_item_sequence": ["", "i2", "i3"],
            "recent_positive_timestamp_sequence": [1000, 2000, 3000],
            "recent_item_sequence": ["i1", "", "i3"],
            "recent_timestamp_sequence": [1000, 2000, 3000],
        },
        {"user_history_window": 3},
    )

    assert compact["recent_positive_item_sequence"] == ["i2", "i3"]
    assert compact["recent_positive_timestamp_sequence"] == [2000, 3000]
    assert compact["recent_item_sequence"] == ["i1", "i3"]
    assert compact["recent_timestamp_sequence"] == [1000, 3000]


def test_attach_training_sample_negatives_uses_train_only_method_dataset(tmp_path: Path):
    sample_path = tmp_path / "two_tower_train_samples.jsonl"
    write_jsonl(
        sample_path,
        [
            {"user_id": "u1", "negative_item_ids": ["n1", "n2"], "source": "two_tower_method_dataset"},
            {"user_id": "u1", "negative_item_ids": ["n2", "n3"], "source": "two_tower_method_dataset"},
            {"user_id": "u3", "negative_item_ids": ["n4"], "source": "two_tower_method_dataset"},
        ],
    )
    sequences = [{"user_id": "u1", "negative_item_ids": ["existing"]}, {"user_id": "u2"}]

    stats = _attach_training_sample_negatives(sequences, {"training_sample_path": str(sample_path)})

    assert sequences[0]["negative_item_ids"] == ["existing", "n1", "n2", "n3"]
    assert "negative_item_ids" not in sequences[1]
    assert stats["training_sample_negative_users"] == 1
    assert stats["training_sample_negative_items_attached"] == 4


def test_attach_training_sample_negatives_rejects_non_train_sample_path(tmp_path: Path):
    sample_path = tmp_path / "two_tower_train_samples.valid.jsonl"
    sample_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="eval/valid/test/holdout"):
        _attach_training_sample_negatives([], {"training_sample_path": str(sample_path)})


def test_compact_inputs_emit_progress_and_keep_train_only_contract(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    events = []

    result = train_two_tower_recall(
        paths["config"],
        output_dir=tmp_path / "artifacts",
        variant="youtube_dnn",
        config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
        compact_inputs=True,
        progress_callback=lambda event, payload: events.append((event, payload)),
    )

    manifest = read_json(result["artifact_manifest_path"])
    assert manifest["metrics"]["compact_inputs"] is True
    assert manifest["metrics"]["split_scope"] == "train_only"
    assert manifest["metrics"]["leakage_checks"] == {"train_inputs_only": True, "eval_paths_rejected": True}
    event_names = [event for event, _ in events]
    assert "load_item_records_complete" in event_names
    assert "load_training_sequences_complete" in event_names
    assert "training_rows_complete" in event_names
    assert "item_feature_rows_complete" in event_names
    assert "first_batch_devices" in event_names


def test_torch_example_batches_stream_without_materializing_full_examples():
    rows = [
        {"user_id": "u1", "positive_items": ["i1", "i2", "i3"]},
        {"user_id": "u2", "positive_items": ["i2", "missing", "i4"]},
    ]
    item_to_idx = {"i1": 0, "i2": 1, "i3": 2, "i4": 3}

    batches = list(two_tower._torch_example_batches(rows, item_to_idx, 2))

    assert two_tower._torch_example_count(rows, item_to_idx) == 3
    assert [len(batch) for batch in batches] == [2, 1]
    assert batches[0][0] == ([0], 1, {0, 1, 2}, [], 1.0)
    assert batches[0][1] == ([0, 1], 2, {0, 1, 2}, [], 1.0)
    assert batches[1][0] == ([1], 3, {1, 3}, [], 1.0)
    assert all(len(batch) <= 2 for batch in batches)


def test_torch_example_batches_caps_per_user_and_keeps_temporal_history():
    rows = [{"user_id": "u1", "positive_items": ["i1", "i2", "i3", "i4", "i5"]}]
    item_to_idx = {"i1": 0, "i2": 1, "i3": 2, "i4": 3, "i5": 4}

    batches = list(two_tower._torch_example_batches(rows, item_to_idx, batch_size=10, max_samples_per_user=2))

    assert two_tower._torch_example_count(rows, item_to_idx, max_samples_per_user=2) == 2
    assert batches == [[([0, 1, 2], 3, {0, 1, 2, 3, 4}, [], 1.0), ([0, 1, 2, 3], 4, {0, 1, 2, 3, 4}, [], 1.0)]]


def test_sequence_item_events_sort_cross_key_timestamps_before_training_rows():
    config = two_tower._normalized_config(
        {
            "sequence_keys": ["recent_positive_item_sequence", "recent_strong_positive_item_sequence"],
            "user_history_window": 10,
        }
    )

    events = two_tower._sequence_item_events(
        {
            "recent_positive_item_sequence": ["late_positive"],
            "recent_positive_timestamp_sequence": [30],
            "recent_strong_positive_item_sequence": ["early_strong", "middle_strong"],
            "recent_strong_positive_timestamp_sequence": [10, 20],
        },
        config,
    )

    assert [event["item"] for event in events] == ["early_strong", "middle_strong", "late_positive"]


def test_negative_indices_use_popularity_power_distribution():
    item_frequencies = Counter({0: 100, 1: 1, 2: 1})
    sampler = two_tower._negative_sampling_distribution(item_frequencies, item_count=3, power=0.75)

    negatives = two_tower._negative_indices(3, positives={1}, count=50, rng=two_tower.random.Random(20260509), sampling_distribution=sampler)

    assert set(negatives) <= {0, 2}
    assert negatives.count(0) > negatives.count(2)


def test_negative_indices_v2_unique_and_explicit_filtering():
    stats = {"negative_examples": 0, "negative_samples_requested_total": 0, "negative_samples_effective_total": 0}

    negatives = two_tower._negative_indices(
        item_count=5,
        positives={0, 1},
        count=3,
        rng=two_tower.random.Random(20260604),
        explicit_negatives=[1, 2, 2, 3],
        unique=True,
        explicit_negative_weight=1.0,
        stats=stats,
    )

    assert negatives == [2, 3, 4]
    assert set(negatives).isdisjoint({0, 1})
    assert len(negatives) == len(set(negatives))
    assert stats["positive_negative_collision_blocked_count"] == 1
    assert stats["explicit_negative_used_count"] == 2
    assert stats["negative_samples_effective_total"] == 3


def test_negative_indices_v2_small_universe_does_not_loop():
    negatives = two_tower._negative_indices(
        item_count=3,
        positives={0, 1},
        count=5,
        rng=two_tower.random.Random(20260604),
        unique=True,
        max_attempts=1,
    )

    assert negatives == [2]


def test_torch_user_examples_keep_explicit_negative_indices():
    row = {"user_id": "u1", "positive_items": ["i1", "i2", "i3"], "explicit_negative_items": ["i4", "i2", "missing", "i4"]}
    item_to_idx = {"i1": 0, "i2": 1, "i3": 2, "i4": 3}

    examples = two_tower._torch_user_examples(row, item_to_idx, max_samples_per_user=5)

    assert examples == [([0], 1, {0, 1, 2}, [3], 1.0), ([0, 1], 2, {0, 1, 2}, [3], 1.0)]


def test_negative_items_fallback_supports_unique_explicit_and_stats():
    stats = {"negative_examples": 0, "negative_samples_requested_total": 0, "negative_samples_effective_total": 0}

    negatives = two_tower._negative_items(
        ["i0", "i1", "i2", "i3", "i4"],
        positives={"i0", "i1"},
        count=3,
        rng=two_tower.random.Random(20260604),
        explicit_negatives=["i1", "i2", "i2", "i3"],
        unique=True,
        explicit_negative_weight=1.0,
        stats=stats,
    )

    assert negatives == ["i2", "i3", "i4"]
    assert set(negatives).isdisjoint({"i0", "i1"})
    assert len(negatives) == len(set(negatives))
    assert stats["positive_negative_collision_blocked_count"] == 1
    assert stats["negative_duplicate_avoided_count"] == 1
    assert stats["explicit_negative_used_count"] == 2
    assert stats["negative_samples_effective_total"] == 3


def test_history_weights_support_recency_decay_direction():
    config = {"torch_user_history_weighting": "recency_decay", "recency_decay": 0.5}

    assert two_tower._history_weights(history_len=3, padding_len=2, config=config) == [0.25, 0.5, 1.0, 0.0, 0.0]
    assert two_tower._history_weights(history_len=3, padding_len=1, config={"torch_user_history_weighting": "uniform"}) == [1.0, 1.0, 1.0, 0.0]


def test_example_age_weighting_uses_newest_train_timestamp_as_reference():
    rows = [
        {"user_id": "u1", "positive_items": ["i1", "i2"], "positive_timestamps_ms": [1, 86_400_001]},
        {"user_id": "u2", "positive_items": ["i3"], "positive_timestamps_ms": [None]},
    ]

    stats = two_tower._attach_example_age_weights(
        rows,
        {"example_age_weighting": "decay", "example_age_half_life_days": 1.0, "example_age_min_weight": 0.2},
    )

    assert rows[0]["positive_sample_weights"] == [0.5, 1.0]
    assert rows[1]["positive_sample_weights"] == [1.0]
    assert stats["reference_timestamp_ms"] == 86_400_001
    assert stats["missing_timestamp_count"] == 1
    assert stats["weight_stats"]["min"] == 0.5


def test_torch_user_examples_keep_example_age_weights_by_positive_offset():
    row = {"user_id": "u1", "positive_items": ["i1", "i2", "i3"], "positive_sample_weights": [0.25, 0.5, 1.0]}
    item_to_idx = {"i1": 0, "i2": 1, "i3": 2}

    examples = two_tower._torch_user_examples(row, item_to_idx, max_samples_per_user=5)

    assert examples == [([0], 1, {0, 1, 2}, [], 0.5), ([0, 1], 2, {0, 1, 2}, [], 1.0)]


def test_sampled_softmax_logq_values_follow_effective_sample_count():
    sampler = ([1.0, 3.0, 6.0], 6.0)

    logq = two_tower._sampled_softmax_logq_values([0, 1, 2], sampler, item_count=3, epsilon=1e-12, sample_count=3)

    assert logq == [round(two_tower.math.log(3 / 6), 8), round(two_tower.math.log(6 / 6), 8), round(two_tower.math.log(9 / 6), 8)]


def test_normalized_config_defaults_to_per_example_candidate_mode():
    config = two_tower._normalized_config({})

    assert config["sampled_softmax_candidate_mode"] == "per_example"
    assert config["score_temperature"] == 1.0


def test_normalized_config_accepts_score_temperature():
    config = two_tower._normalized_config({"score_temperature": 0.1})

    assert config["score_temperature"] == 0.1


def test_normalized_config_accepts_dynamic_negative_sampling():
    config = two_tower._normalized_config(
        {
            "dynamic_negative_sampling": True,
            "dynamic_same_category_popular_ratio": 0.5,
            "dynamic_same_category_tail_ratio": 0.25,
            "dynamic_global_random_ratio": 0.25,
        }
    )

    assert config["dynamic_negative_sampling"] is True
    assert config["dynamic_negative_sampling_mode"] == "same_category_popular_tail_global_train_only"
    assert config["dynamic_negative_resample_each_epoch"] is True
    assert config["dynamic_same_category_popular_ratio"] == 0.5
    assert config["dynamic_same_category_tail_ratio"] == 0.25
    assert config["dynamic_global_random_ratio"] == 0.25


def test_invalid_score_temperature_is_rejected():
    for value in (0, -0.1, float("nan")):
        with pytest.raises(ValueError, match="score_temperature"):
            train_two_tower_model(_sequences(), _items(), {"variant": "youtube_dnn", "embedding_dim": 8, "epochs": 1, "score_temperature": value})


def test_adjust_sampled_softmax_logits_applies_temperature_before_logq():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")

    logits = torch.tensor([[0.2, 0.4]], dtype=torch.float32)
    logq = torch.tensor([[0.1, 0.3]], dtype=torch.float32)

    adjusted = two_tower._adjust_sampled_softmax_logits(logits, logq, {"score_temperature": 0.1, "sampled_softmax_correction": "logq"})

    assert adjusted.detach().cpu().tolist()[0] == pytest.approx([1.9, 3.7])


def test_invalid_sampled_softmax_candidate_mode_is_rejected():
    with pytest.raises(ValueError, match="sampled_softmax_candidate_mode"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": "youtube_dnn", "embedding_dim": 8, "epochs": 1, "sampled_softmax_candidate_mode": "bad_mode"},
        )


def test_invalid_sampled_softmax_correction_is_rejected():
    with pytest.raises(ValueError, match="sampled_softmax_correction"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": "youtube_dnn", "embedding_dim": 8, "epochs": 1, "sampled_softmax_correction": "log_q"},
        )


def test_dynamic_negative_sampling_rejects_logq_and_batch_shared():
    with pytest.raises(ValueError, match="dynamic_negative_sampling"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": "dssm", "embedding_dim": 8, "epochs": 1, "dynamic_negative_sampling": True, "sampled_softmax_correction": "logq"},
        )
    with pytest.raises(ValueError, match="dynamic_negative_sampling"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": "dssm", "embedding_dim": 8, "epochs": 1, "dynamic_negative_sampling": True, "sampled_softmax_candidate_mode": "batch_shared"},
        )


def test_dynamic_negative_sampling_rejects_disabled_resampling_flag():
    with pytest.raises(ValueError, match="dynamic_negative_resample_each_epoch=false"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": "dssm", "embedding_dim": 8, "epochs": 1, "dynamic_negative_sampling": True, "dynamic_negative_resample_each_epoch": False},
        )


def test_dynamic_negative_indices_resample_and_exclude_positives():
    item_by_id = {item["parent_asin"]: item for item in _items()}
    item_ids = sorted(item_by_id)
    item_to_idx = {item_id: index for index, item_id in enumerate(item_ids)}
    frequencies = Counter({item_to_idx["audio_seed"]: 10, item_to_idx["camera_seed"]: 5, item_to_idx["camera_next"]: 1, item_to_idx["audio_next"]: 1})
    sampler = two_tower._dynamic_negative_sampler(item_by_id, item_ids, frequencies)
    positive_index = item_to_idx["audio_seed"]
    positives = {item_to_idx["audio_seed"], item_to_idx["audio_next"]}
    config = two_tower._normalized_config({"dynamic_negative_sampling": True, "negative_samples": 2})

    first = two_tower._dynamic_negative_indices(positive_index, positives, 2, two_tower.random.Random(7), sampler, unique=True, config=config)
    second = two_tower._dynamic_negative_indices(positive_index, positives, 2, two_tower.random.Random(8), sampler, unique=True, config=config)

    assert first
    assert second
    assert not set(first) & positives
    assert not set(second) & positives
    assert set(first) <= set(range(len(item_ids)))
    assert len(first) == len(second) == 2


def test_dynamic_negative_sampling_draws_from_large_category_pool_without_materializing_full_pool():
    pools = {"audio": list(range(10000))}
    selected = two_tower._draw_from_category_pools(
        ["audio"],
        pools,
        3,
        two_tower.random.Random(20260608),
        unique=True,
        blocked={0, 1},
        selected=set(),
    )

    assert len(selected) == 3
    assert not set(selected) & {0, 1}
    assert all(index in pools["audio"] for index in selected)


def test_dynamic_negative_training_records_component_counts():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")

    result = train_two_tower_model(
        _sequences(),
        _items(),
        {
            "variant": "dssm",
            "embedding_dim": 8,
            "epochs": 1,
            "negative_samples": 2,
            "dynamic_negative_sampling": True,
            "unique_negatives_per_example": True,
        },
    )

    negative_sampling = result["train_metrics"]["negative_sampling"]
    assert negative_sampling["dynamic_negative_sampling"] is True
    assert negative_sampling["dynamic_negative_used_count"] > 0
    assert sum(negative_sampling["dynamic_negative_component_counts"].values()) == negative_sampling["dynamic_negative_used_count"]
    assert result["model"]["negative_sampling_version"] == "v1"


def test_torch_batch_tensors_masks_padded_candidates():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")

    tensors = two_tower._torch_batch_tensors(
        torch,
        [([0], 1, {0, 1, 2}, [], 1.0), ([1], 2, {1, 2}, [], 1.0)],
        item_count=4,
        config={
            "negative_samples": 2,
            "unique_negatives_per_example": True,
            "use_explicit_negative_item_ids": False,
            "explicit_negative_weight": 0.0,
            "negative_dedup_max_attempts": 5,
            "sampled_softmax_correction": "none",
            "torch_user_history_weighting": "uniform",
        },
        rng=two_tower.random.Random(20260604),
        device=torch.device("cpu"),
    )

    assert tensors is not None
    candidate_mask = tensors[-1].detach().cpu().tolist()
    assert candidate_mask[0] == [1.0, 1.0, 0.0]
    assert candidate_mask[1] == [1.0, 1.0, 1.0]


def test_batch_shared_candidates_are_shared_and_targets_follow_positive_positions():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")

    tensors = two_tower._torch_batch_tensors(
        torch,
        [([0], 1, {0, 1, 3}, [], 1.0), ([2], 3, {2, 3}, [], 1.0)],
        item_count=6,
        config={
            "negative_samples": 2,
            "sampled_softmax_candidate_mode": "batch_shared",
            "sampled_softmax_correction": "none",
            "negative_dedup_max_attempts": 5,
            "torch_user_history_weighting": "uniform",
        },
        rng=two_tower.random.Random(20260604),
        device=torch.device("cpu"),
    )

    assert tensors is not None
    candidate_tensor = tensors[2].detach().cpu().tolist()
    target_tensor = tensors[3].detach().cpu().tolist()
    candidate_mask = tensors[-1].detach().cpu().tolist()
    assert candidate_tensor[0] == candidate_tensor[1]
    assert candidate_tensor[0][:2] == [1, 3]
    assert target_tensor == [0, 1]
    assert any(target != 0 for target in target_tensor)
    assert candidate_mask[0][0] == 1.0
    assert candidate_mask[1][1] == 1.0


def test_batch_shared_masks_known_positive_collisions_per_row():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")

    tensors = two_tower._torch_batch_tensors(
        torch,
        [([0], 1, {0, 1, 3}, [], 1.0), ([2], 3, {2, 3}, [], 1.0)],
        item_count=6,
        config={
            "negative_samples": 1,
            "sampled_softmax_candidate_mode": "batch_shared",
            "sampled_softmax_correction": "none",
            "negative_dedup_max_attempts": 5,
            "torch_user_history_weighting": "uniform",
        },
        rng=two_tower.random.Random(20260604),
        device=torch.device("cpu"),
    )

    assert tensors is not None
    candidate_mask = tensors[-1].detach().cpu().tolist()
    assert candidate_mask[0][0] == 1.0
    assert candidate_mask[0][1] == 0.0
    assert candidate_mask[1][0] == 1.0
    assert candidate_mask[1][1] == 1.0


def test_batch_shared_logq_shape_and_stats_use_shared_negative_count():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")
    stats = two_tower._negative_sampling_stats([])

    tensors = two_tower._torch_batch_tensors(
        torch,
        [([0], 1, {0, 1, 3}, [], 1.0), ([2], 3, {2, 3}, [], 1.0)],
        item_count=6,
        config={
            "negative_samples": 2,
            "sampled_softmax_candidate_mode": "batch_shared",
            "sampled_softmax_correction": "logq",
            "sampled_softmax_logq_epsilon": 1e-12,
            "negative_dedup_max_attempts": 5,
            "torch_user_history_weighting": "uniform",
        },
        rng=two_tower.random.Random(20260604),
        device=torch.device("cpu"),
        stats=stats,
    )

    assert tensors is not None
    candidate_tensor = tensors[2]
    logq_tensor = tensors[5]
    assert list(logq_tensor.shape) == list(candidate_tensor.shape)
    assert stats["batch_shared_candidate_batches"] == 1
    assert stats["batch_shared_positive_candidates"] == 2
    assert stats["batch_shared_negative_candidates"] == 2
    assert stats["sampled_softmax_corrected_examples"] == 2
    assert stats["sampled_softmax_corrected_candidates"] == 8


def test_logq_rejects_explicit_negative_mixture():
    with pytest.raises(ValueError, match="explicit negative mixtures"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {
                "variant": "youtube_dnn",
                "embedding_dim": 8,
                "epochs": 1,
                "negative_samples": 1,
                "sampled_softmax_correction": "logq",
                "use_explicit_negative_item_ids": True,
                "explicit_negative_weight": 0.5,
            },
        )


def test_fallback_rejects_pytorch_only_weighting(monkeypatch):
    monkeypatch.setattr(two_tower, "_import_torch", lambda: None)

    with pytest.raises(ValueError, match="example_age_weighting requires the PyTorch backend"):
        train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": "youtube_dnn", "embedding_dim": 8, "epochs": 1, "negative_samples": 1, "example_age_weighting": "decay"},
        )


def test_dssm_fallback_explicit_negatives_take_precedence_when_configured(monkeypatch):
    monkeypatch.setattr(two_tower, "_import_torch", lambda: None)

    result = train_two_tower_model(
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["audio_seed", "audio_next"], "recent_item_sequence": ["audio_seed", "audio_next"], "negative_item_ids": ["camera_seed"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["camera_seed", "camera_next"], "recent_item_sequence": ["camera_seed", "camera_next"], "negative_item_ids": ["audio_seed"]},
        ],
        _items(),
        {
            "variant": "dssm",
            "embedding_dim": 8,
            "epochs": 1,
            "negative_samples": 1,
            "use_explicit_negative_item_ids": True,
            "explicit_negative_weight": 1.0,
        },
    )

    negative_sampling = result["train_metrics"]["negative_sampling"]
    assert negative_sampling["explicit_negative_used_count"] > 0
    assert negative_sampling["negative_samples_effective_avg"] > 0


def test_training_records_active_side_feature_fields():
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {
            "variant": "dssm",
            "embedding_dim": 8,
            "epochs": 1,
            "negative_samples": 1,
            "score_temperature": 0.2,
            "side_feature_fields": ["item_quality_token"],
        },
    )

    metrics = result["train_metrics"]
    assert metrics["text_fields"] == two_tower.DEFAULT_TEXT_FIELDS
    assert metrics["side_feature_fields_active"] == ["item_quality_token"]
    assert metrics["training_backend"]["side_feature_fields_active"] == ["item_quality_token"]
    assert metrics["score_mode"] == "cosine"
    assert metrics["embedding_normalization"] == "l2"
    assert metrics["score_temperature"] == 0.2
    assert metrics["logit_scale"] == 5.0
    assert result["model"]["side_feature_fields"] == ["item_quality_token"]
    assert result["model"]["side_feature_fields_active"] == ["item_quality_token"]
    assert result["model"]["score_mode"] == "cosine"
    assert result["model"]["embedding_normalization"] == "l2"
    assert result["model"]["score_temperature"] == 0.2
    assert result["model"]["logit_scale"] == 5.0


def test_side_feature_tokens_are_atomic_field_value_tokens():
    tokens = two_tower._side_feature_tokens(
        {"item_quality_token": "item_quality:embedding_ready", "item_pop_bucket_token": ["item_pop:rank_000001_000100"]},
        ["item_quality_token", "item_pop_bucket_token"],
    )

    assert tokens == [
        "item_quality_token=item_quality:embedding_ready",
        "item_pop_bucket_token=item_pop:rank_000001_000100",
    ]
    assert "item_quality" not in tokens
    assert "embedding_ready" not in tokens


def test_training_records_accumulation_and_mixed_precision_contract():
    result = train_two_tower_model(
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["audio_seed", "audio_next"], "recent_item_sequence": ["audio_seed", "audio_next"], "negative_item_ids": ["camera_seed", "audio_seed"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["camera_seed", "camera_next"], "recent_item_sequence": ["camera_seed", "camera_next"], "negative_item_ids": ["audio_next"]},
        ],
        _items(),
        {
            "variant": "youtube_dnn",
            "source_name": "two_tower_youtube_dnn",
            "embedding_dim": 8,
            "epochs": 1,
            "negative_samples": 2,
            "negative_sampling_version": "v2",
            "unique_negatives_per_example": True,
            "use_explicit_negative_item_ids": True,
            "explicit_negative_weight": 0.5,
            "torch_user_history_weighting": "recency_decay",
            "recency_decay": 0.85,
            "sampled_softmax_correction": "none",
            "sampled_softmax_logq_epsilon": 1e-9,
            "batch_size": 2,
            "gradient_accumulation_steps": 3,
            "mixed_precision": True,
        },
    )

    metrics = result["train_metrics"]
    backend = metrics["training_backend"]
    assert metrics["gradient_accumulation_steps"] == 3
    assert metrics["effective_batch_size"] == 6
    assert metrics["mixed_precision"] is True
    assert metrics["text_fields"] == two_tower.DEFAULT_TEXT_FIELDS
    assert metrics["side_feature_fields_active"] == []
    assert backend["text_fields"] == two_tower.DEFAULT_TEXT_FIELDS
    assert backend["side_feature_fields_active"] == []
    assert metrics["negative_sampling_version"] == "v2"
    assert metrics["unique_negatives_per_example"] is True
    assert metrics["use_explicit_negative_item_ids"] is True
    assert metrics["explicit_negative_weight"] == 0.5
    assert metrics["torch_user_history_weighting"] == "recency_decay"
    assert metrics["recency_decay"] == 0.85
    assert metrics["example_age_weighting"] == "none"
    assert metrics["example_age"]["applied_to_loss"] == (backend["name"] == "pytorch")
    assert metrics["sampled_softmax_candidate_mode"] == "per_example"
    assert metrics["negative_samples_interpretation"] == "per_example"
    assert metrics["sampled_softmax_correction"] == "none"
    assert metrics["negative_sampling"]["sampled_softmax_candidate_mode"] == "per_example"
    assert metrics["negative_sampling"]["negative_samples_interpretation"] == "per_example"
    assert metrics["negative_sampling"]["sampled_softmax_correction"] == "none"
    assert metrics["negative_sampling"]["sampled_softmax_corrected_examples"] == 0
    assert metrics["negative_sampling"]["rows_with_explicit_negative_items"] == 2
    assert metrics["negative_sampling"]["explicit_negative_used_count"] > 0
    assert metrics["negative_sampling"]["negative_samples_effective_avg"] > 0
    assert backend["gradient_accumulation_steps"] == 3
    assert backend["effective_batch_size"] == 6
    assert backend["mixed_precision_requested"] is True
    assert result["model"]["gradient_accumulation_steps"] == 3
    assert result["model"]["effective_batch_size"] == 6
    assert result["model"]["negative_sampling_version"] == "v2"
    assert result["model"]["sampled_softmax_candidate_mode"] == "per_example"
    assert result["model"]["negative_samples_interpretation"] == "per_example"
    assert result["model"]["unique_negatives_per_example"] is True
    assert result["model"]["use_explicit_negative_item_ids"] is True
    assert result["model"]["torch_user_history_weighting"] == "recency_decay"
    assert result["model"]["text_fields"] == two_tower.DEFAULT_TEXT_FIELDS
    assert result["model"]["side_feature_fields"] == []
    assert result["model"]["side_feature_fields_active"] == []
    if two_tower._import_torch() is not None:
        assert "optimizer_steps" in backend
    else:
        assert backend["mixed_precision_enabled"] is False



def test_batch_shared_training_records_metrics_and_model_payload():
    torch = two_tower._import_torch()
    if torch is None:
        pytest.skip("PyTorch backend is not available")

    result = train_two_tower_model(
        _sequences(),
        _items(),
        {
            "variant": "youtube_dnn",
            "source_name": "two_tower_youtube_dnn",
            "embedding_dim": 8,
            "epochs": 1,
            "negative_samples": 1,
            "sampled_softmax_candidate_mode": "batch_shared",
            "batch_size": 2,
        },
    )

    metrics = result["train_metrics"]
    negative_sampling = metrics["negative_sampling"]
    assert metrics["sampled_softmax_candidate_mode"] == "batch_shared"
    assert metrics["negative_samples_interpretation"] == "batch_level_shared"
    assert negative_sampling["sampled_softmax_candidate_mode"] == "batch_shared"
    assert negative_sampling["negative_samples_interpretation"] == "batch_level_shared"
    assert negative_sampling["batch_shared_candidate_batches"] > 0
    assert result["model"]["sampled_softmax_candidate_mode"] == "batch_shared"
    assert result["model"]["negative_samples_interpretation"] == "batch_level_shared"


def test_cuda_device_name_handles_invalid_visible_device():
    class FakeCuda:
        @staticmethod
        def current_device() -> int:
            return 0

        @staticmethod
        def get_device_name(index: int) -> str:
            raise AssertionError("Invalid device id")

    class FakeTorch:
        cuda = FakeCuda()

    class FakeDevice:
        type = "cuda"
        index = None

    assert two_tower._cuda_device_name(FakeTorch(), FakeDevice()) == ""



def test_two_tower_artifacts_write_complete_default_off_contract(tmp_path: Path):
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "dssm", "source_name": "two_tower_dssm", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )

    contract = save_two_tower_artifacts(result, tmp_path)
    manifest = json.loads(Path(contract["artifact_manifest"]).read_text(encoding="utf-8"))

    assert set(contract) == {
        "train_config",
        "model",
        "item_embeddings",
        "user_embeddings",
        "item_id_map",
        "user_id_map",
        "train_metrics",
        "recall_index",
        "artifact_manifest",
    }
    assert manifest["artifact_type"] == "two_tower_training_artifacts_v1"
    assert manifest["variant"] == "dssm"
    assert manifest["source_name"] == "two_tower_dssm"
    assert manifest["default_enabled"] is False
    assert manifest["contract"] == contract
    assert all(Path(path).exists() for path in contract.values())

    model = json.loads(Path(contract["model"]).read_text(encoding="utf-8"))
    metrics = json.loads(Path(contract["train_metrics"]).read_text(encoding="utf-8"))
    recall_rows = read_jsonl(contract["recall_index"])

    assert model["model_type"] == "dssm_two_tower_v1"
    assert model["default_enabled"] is False
    assert model["training_backend"] == metrics["training_backend"]
    assert "model_parameters" in model
    assert metrics["variant"] == "dssm"
    if two_tower._import_torch() is not None:
        assert metrics["training_backend"]["name"] == "pytorch"
        assert metrics["training_backend"]["torch_available"] is True
        assert metrics["training_backend"]["batch_training"] is True
        assert metrics["batch_size"] == 512
        assert metrics["training_seconds"] > 0
        assert "peak_cuda_memory_mb" in metrics
        assert metrics["loss_history"]
    else:
        assert metrics["training_backend"]["name"] == "python_fallback_vector_updates"
        assert metrics["training_backend"]["torch_available"] is False
        assert metrics["training_backend"]["negative_sampling"] == {"strategy": "popularity_power", "power": 0.75, "item_frequency_count": 4}
        assert metrics["loss_history"] == []
    assert metrics["users_with_training_rows"] == 2
    assert len(recall_rows) == 4
    assert {row["parent_asin"] for row in recall_rows} == {"audio_seed", "audio_next", "camera_seed", "camera_next"}


def test_two_tower_variants_keep_model_type_and_source_isolated(tmp_path: Path):
    variants = {
        "dssm": "two_tower_dssm",
        "youtube_dnn": "two_tower_youtube_dnn",
    }

    manifests = {}
    for variant, source_name in variants.items():
        result = train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": variant, "source_name": source_name, "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
        )
        contract = save_two_tower_artifacts(result, tmp_path / variant)
        manifests[variant] = json.loads(Path(contract["artifact_manifest"]).read_text(encoding="utf-8"))

    assert manifests["dssm"]["source_name"] == "two_tower_dssm"
    assert manifests["youtube_dnn"]["source_name"] == "two_tower_youtube_dnn"
    assert manifests["dssm"]["contract"]["artifact_manifest"] != manifests["youtube_dnn"]["contract"]["artifact_manifest"]

    dssm_model = json.loads(Path(manifests["dssm"]["contract"]["model"]).read_text(encoding="utf-8"))
    youtube_model = json.loads(Path(manifests["youtube_dnn"]["contract"]["model"]).read_text(encoding="utf-8"))
    assert dssm_model["model_type"] == "dssm_two_tower_v1"
    assert youtube_model["model_type"] == "youtube_dnn_two_tower_v1"
    if two_tower._import_torch() is not None:
        assert dssm_model["training_backend"]["name"] == "pytorch"
        assert youtube_model["training_backend"]["name"] == "pytorch"
        assert dssm_model["training_backend"]["model_class"] != youtube_model["training_backend"]["model_class"]
    else:
        assert dssm_model["training_backend"]["name"] == "python_fallback_vector_updates"
        assert youtube_model["training_backend"]["name"] == "python_fallback_vector_updates"
    assert dssm_model["source_name"] != youtube_model["source_name"]


def test_backend_config_cannot_bypass_torch_when_torch_is_available():
    torch_module = two_tower._import_torch()
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "dssm", "source_name": "two_tower_dssm", "backend": "python_fallback", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )

    backend = result["train_metrics"]["training_backend"]
    if torch_module is not None:
        assert backend["name"] == "pytorch"
        assert backend["torch_available"] is True
    else:
        assert backend["name"] == "python_fallback_vector_updates"
        assert backend["torch_available"] is False
        assert backend["negative_sampling"]["strategy"] == "popularity_power"
        assert backend["negative_sampling"]["power"] == 0.75
        assert backend["negative_sampling"]["item_frequency_count"] == 4
    assert result["model"]["training_backend"] == backend


def test_python_backend_is_labeled_as_no_torch_fallback(monkeypatch):
    monkeypatch.setattr(two_tower, "_import_torch", lambda: None)

    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "dssm", "source_name": "two_tower_dssm", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )

    backend = result["train_metrics"]["training_backend"]
    assert backend["name"] == "python_fallback_vector_updates"
    assert backend["torch_available"] is False
    assert backend["negative_sampling"]["strategy"] == "popularity_power"
    assert backend["negative_sampling"]["power"] == 0.75
    assert backend["negative_sampling"]["item_frequency_count"] == 4
    assert result["model"]["training_backend"] == backend



def test_saved_two_tower_manifest_loads_as_vector_index_with_model_metadata(tmp_path: Path):
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )
    contract = save_two_tower_artifacts(result, tmp_path)
    model = read_json(contract["model"])
    zero_matrix = [[0.0] * 8 for _ in range(8)]
    model["model_parameters"] = {
        "user_tower.0.weight": zero_matrix,
        "user_tower.0.bias": [0.0] * 8,
        "user_tower.2.weight": zero_matrix,
        "user_tower.2.bias": [0.0] * 8,
    }
    write_json(contract["model"], model)
    recall_rows = read_jsonl(contract["recall_index"])
    audio_seed_row = next(row for row in recall_rows if row["parent_asin"] == "audio_seed")
    audio_neighbor_row = dict(audio_seed_row)
    audio_neighbor_row["parent_asin"] = "audio_neighbor"
    audio_neighbor_row["item_id"] = "audio_neighbor"
    write_jsonl(contract["recall_index"], recall_rows + [audio_neighbor_row])

    index = load_two_tower_index(contract["artifact_manifest"])
    assert isinstance(index, VectorIndex)
    assert index.source_name == "two_tower_youtube_dnn"
    assert index.model_metadata["variant"] == "youtube_dnn"
    assert index.model_metadata["model_type"] == "youtube_dnn_two_tower_v1"
    assert index.model_metadata["model_parameters"]["user_tower.0.weight"] == zero_matrix

    sequence = {"user_id": "u1", "recent_item_sequence": ["audio_seed"], "recent_positive_item_sequence": ["audio_seed"]}
    candidates = two_tower_candidates_for_user(sequence, index, {"two_tower_enabled": True, "two_tower_per_user": 3})

    assert candidates
    assert candidates[0].item_id == "audio_neighbor"
    assert "audio_seed" not in {candidate.item_id for candidate in candidates}
    assert {candidate.metadata["two_tower_source_name"] for candidate in candidates} == {"two_tower_youtube_dnn"}
    assert {candidate.metadata["two_tower_model_type"] for candidate in candidates} == {"youtube_dnn_two_tower_v1"}


def test_train_two_tower_recall_filters_user_quality_policy(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    output_dir = tmp_path / "artifacts"

    result = train_two_tower_recall(
        paths["config"],
        output_dir=output_dir,
        variant="youtube_dnn",
        config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
        user_quality_manifest=paths["user_quality"],
        user_quality_bucket="heavy",
    )

    metrics = read_json(result["train_metrics_path"])
    user_embeddings = read_jsonl(result["user_embeddings_path"])
    assert metrics["training_input_users"] == 1
    assert metrics["split_scope"] == "train_only"
    assert metrics["leakage_checks"] == {"train_inputs_only": True, "eval_paths_rejected": True}
    assert metrics["item_vocab_size"] == 4
    assert Path(metrics["item_vocab_manifest_path"]).name == "two_tower_item_vocab_manifest.json"
    assert metrics["user_quality_selected_user_count"] == 1
    assert metrics["user_quality_matched_user_count"] == 1
    assert metrics["user_quality_bucket"] == "heavy"
    assert {row["user_id"] for row in user_embeddings} == {"u1"}


def test_train_two_tower_recall_rejects_user_quality_as_source(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    policy = read_json(paths["user_quality"])
    policy["policy_role"] = "recall_source"
    write_json(paths["user_quality"], policy)

    with pytest.raises(ValueError, match="eligibility policy"):
        train_two_tower_recall(
            paths["config"],
            output_dir=tmp_path / "artifacts",
            variant="youtube_dnn",
            config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
            user_quality_manifest=paths["user_quality"],
        )


def test_two_tower_seed_sidecar_schema_manifest_and_deterministic_sort(tmp_path: Path):
    embeddings_path = tmp_path / "item_embeddings.jsonl"
    sidecar_path = tmp_path / "two_tower_seed_neighbors.jsonl"
    manifest_path = tmp_path / "two_tower_seed_manifest.json"
    rows = [
        {"item_id": "b", "embedding": [1.0, 0.0], "embedding_norm": 1.0, "main_category": "", "category": "", "title_clean": ""},
        {"item_id": "a", "embedding": [1.0, 0.0], "embedding_norm": 1.0, "main_category": "", "category": "", "title_clean": ""},
        {"item_id": "c", "embedding": [0.0, 1.0], "embedding_norm": 1.0, "main_category": "", "category": "", "title_clean": ""},
    ]
    embeddings_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    manifest = build_two_tower_seed_sidecar(embeddings_path, sidecar_path, manifest_path, neighbor_k=2)
    sidecar_rows = read_jsonl(sidecar_path)
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert sidecar_rows == [
        {"item_id": "a", "neighbors": [{"item_id": "b", "score": 1.0, "rank": 1}, {"item_id": "c", "score": 0.0, "rank": 2}]},
        {"item_id": "b", "neighbors": [{"item_id": "a", "score": 1.0, "rank": 1}, {"item_id": "c", "score": 0.0, "rank": 2}]},
        {"item_id": "c", "neighbors": [{"item_id": "a", "score": 0.0, "rank": 1}, {"item_id": "b", "score": 0.0, "rank": 2}]},
    ]
    assert set(manifest) == {
        "phase",
        "source",
        "created_at",
        "embedding_input_path",
        "sidecar_path",
        "item_count",
        "neighbor_k",
        "similarity",
        "deterministic_sort",
        "embedding_sha256",
        "sidecar_sha256",
        "config_sha256",
        "schema_version",
    }
    assert saved_manifest == manifest
    assert manifest["phase"] == "1.18"
    assert manifest["source"] == "two_tower_seed"
    assert manifest["item_count"] == 3
    assert manifest["neighbor_k"] == 2
    assert manifest["similarity"] == "cosine"
    assert manifest["deterministic_sort"] == "score_desc_item_id_asc"
    assert manifest["schema_version"] == "two_tower_seed_neighbors_v1"
    assert manifest["embedding_sha256"]
    assert manifest["sidecar_sha256"]


def test_two_tower_seed_sidecar_fails_closed_for_empty_duplicate_and_schema(tmp_path: Path):
    sidecar_path = tmp_path / "neighbors.jsonl"
    manifest_path = tmp_path / "manifest.json"
    empty_path = tmp_path / "empty.jsonl"
    empty_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty two_tower_seed embedding input"):
        build_two_tower_seed_sidecar(empty_path, sidecar_path, manifest_path, neighbor_k=1)

    duplicate_path = tmp_path / "duplicate.jsonl"
    duplicate_path.write_text(
        json.dumps({"item_id": "a", "embedding": [1.0]}) + "\n" + json.dumps({"item_id": "a", "embedding": [1.0]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate two_tower_seed source item_id"):
        build_two_tower_seed_sidecar(duplicate_path, sidecar_path, manifest_path, neighbor_k=1)

    schema_path = tmp_path / "schema.jsonl"
    schema_path.write_text(json.dumps({"item_id": "a", "embedding": [1.0], "unexpected": True}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema mismatch"):
        build_two_tower_seed_sidecar(schema_path, sidecar_path, manifest_path, neighbor_k=1)

    valid_input_path = tmp_path / "valid_input.jsonl"
    valid_input_path.write_text(json.dumps({"item_id": "a", "embedding": [1.0]}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="paths must be distinct"):
        build_two_tower_seed_sidecar(valid_input_path, valid_input_path, manifest_path, neighbor_k=1)
    with pytest.raises(ValueError, match="paths must be distinct"):
        build_two_tower_seed_sidecar(valid_input_path, sidecar_path, sidecar_path, neighbor_k=1)


def test_two_tower_seed_sidecar_cleanup_is_scoped_to_configured_outputs(tmp_path: Path):
    embeddings_path = tmp_path / "item_embeddings.jsonl"
    sidecar_path = tmp_path / "neighbors.jsonl"
    manifest_path = tmp_path / "manifest.json"
    untouched_path = tmp_path / "frozen_config.yaml"
    embeddings_path.write_text(
        json.dumps({"item_id": "a", "embedding": [1.0, 0.0]}) + "\n" + json.dumps({"item_id": "b", "embedding": [0.0, 1.0]}) + "\n",
        encoding="utf-8",
    )
    sidecar_path.write_text("stale sidecar", encoding="utf-8")
    manifest_path.write_text("stale manifest", encoding="utf-8")
    untouched_path.write_text("must stay", encoding="utf-8")

    build_two_tower_seed_sidecar(embeddings_path, sidecar_path, manifest_path, neighbor_k=1)

    assert read_jsonl(sidecar_path) == [{"item_id": "a", "neighbors": [{"item_id": "b", "score": 0.0, "rank": 1}]}, {"item_id": "b", "neighbors": [{"item_id": "a", "score": 0.0, "rank": 1}]}]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["sidecar_path"] == str(sidecar_path)
    assert untouched_path.read_text(encoding="utf-8") == "must stay"


def test_two_tower_seed_sidecar_builds_from_config(tmp_path: Path):
    embeddings_path = tmp_path / "item_embeddings.jsonl"
    sidecar_path = tmp_path / "neighbors.jsonl"
    manifest_path = tmp_path / "manifest.json"
    config_path = tmp_path / "config.yaml"
    embeddings_path.write_text(
        json.dumps({"item_id": "a", "embedding": [1.0, 0.0]}) + "\n" + json.dumps({"item_id": "b", "embedding": [1.0, 0.0]}) + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        f'two_tower_seed_sidecar:\n  embedding_input_path: "{embeddings_path}"\n  sidecar_path: "{sidecar_path}"\n  manifest_path: "{manifest_path}"\n  neighbor_k: 1\n',
        encoding="utf-8",
    )

    manifest = build_two_tower_seed_sidecar_from_config(config_path)

    assert manifest["config_sha256"]
    assert read_jsonl(sidecar_path) == [{"item_id": "a", "neighbors": [{"item_id": "b", "score": 1.0, "rank": 1}]}, {"item_id": "b", "neighbors": [{"item_id": "a", "score": 1.0, "rank": 1}]}]
