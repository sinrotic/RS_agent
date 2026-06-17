from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.diagnose_swing_recent2y_funnel import build_swing_funnel_diagnostic

pytestmark = pytest.mark.unit


def test_swing_funnel_diagnostic_counts_coverage_hot_seed_and_hits(tmp_path: Path) -> None:
    train_path = tmp_path / "user_sequences.train.jsonl"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    valid_path = tmp_path / "swing_valid_in_universe.jsonl"
    test_path = tmp_path / "swing_test_in_universe.jsonl"

    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "seen"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["hot", "seen2"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["solo"]},
        ],
    )
    _write_jsonl(
        source_dir / "swing_recall_edges.jsonl",
        [
            {"src_item": "seed", "dst_item": "target", "score": 2.0, "rank": 1, "source": "swing_recall"},
            {"src_item": "seed", "dst_item": "other", "score": 1.0, "rank": 2, "source": "swing_recall"},
            {"src_item": "solo", "dst_item": "target2", "score": 1.5, "rank": 1, "source": "swing_recall"},
        ],
    )
    (source_dir / "dropped_hot_items.json").write_text(
        json.dumps({"status": "PASS", "items": [{"item_id": "hot", "train_user_freq": 3}]}),
        encoding="utf-8",
    )
    labels = [
        {"user_id": "u1", "item_id": "target", "label": 1},
        {"user_id": "u2", "item_id": "target", "label": 1},
        {"user_id": "u3", "item_id": "target2", "label": 1},
        {"user_id": "u4", "item_id": "other", "label": 1},
    ]
    _write_jsonl(valid_path, labels)
    _write_jsonl(test_path, labels)

    report = build_swing_funnel_diagnostic(
        train_sequences_path=train_path,
        source_dir=source_dir,
        split_label_paths={"valid": valid_path, "test": test_path},
        max_user_items=50,
        per_seed_top_k=100,
        max_k=500,
    )

    valid = report["splits"]["valid"]
    assert report["status"] == "PASS"
    assert report["train_only"] is True
    assert report["governance"]["valid_test_holdout_usage"] == "evaluation_only_metrics_not_candidate_generation"
    assert report["governance"]["uses_valid_for_training_or_graph"] is False
    assert report["source_stats"] == {
        "train_user_count": 3,
        "edge_count": 3,
        "seed_count": 2,
        "dst_item_count": 3,
        "dropped_hot_item_count": 1,
    }
    assert valid["eval_user_count"] == 4
    assert valid["missing_train_sequence_users"] == 1
    assert valid["has_train_sequence_users"] == 3
    assert valid["train_len_ge2_users"] == 2
    assert valid["has_seed_in_graph_users"] == 2
    assert valid["has_hot_dropped_seed_users"] == 1
    assert valid["users_without_graph_seed_but_hot_dropped_seed"] == 1
    assert valid["target_exists_as_any_dst_users"] == 4
    assert valid["generated_candidate_user_count"] == 2
    assert valid["candidate_user_coverage_rate"] == 0.5
    assert valid["hit_user_count_at_500"] == 2
    assert valid["hit_rate_at_500"] == 0.5
    assert valid["recall_at_500"] == 0.5
    assert valid["candidate_count"] == {"avg": 1.0, "p50": 1, "p90": 2, "p99": 2, "max": 2}
    assert valid["user_buckets"]["missing_train_sequence"]["eval_user_count"] == 1
    assert valid["user_buckets"]["cold_or_single_seed"]["hit_user_count_at_500"] == 1
    assert valid["user_buckets"]["light_behavior_2_3"]["has_hot_dropped_seed_users"] == 1


def test_swing_funnel_diagnostic_requires_train_sequence_filename(tmp_path: Path) -> None:
    bad_train_path = tmp_path / "user_sequences.valid.jsonl"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    valid_path = tmp_path / "swing_valid_in_universe.jsonl"
    test_path = tmp_path / "swing_test_in_universe.jsonl"
    _write_jsonl(bad_train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    _write_jsonl(source_dir / "swing_recall_edges.jsonl", [])
    (source_dir / "dropped_hot_items.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    _write_jsonl(valid_path, [{"user_id": "u1", "item_id": "b", "label": 1}])
    _write_jsonl(test_path, [{"user_id": "u1", "item_id": "b", "label": 1}])

    with pytest.raises(ValueError, match="user_sequences.train.jsonl"):
        build_swing_funnel_diagnostic(
            train_sequences_path=bad_train_path,
            source_dir=source_dir,
            split_label_paths={"valid": valid_path, "test": test_path},
        )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
