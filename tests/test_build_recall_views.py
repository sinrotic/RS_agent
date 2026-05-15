from __future__ import annotations

import hashlib
import json

import pytest

pytestmark = pytest.mark.unit

from scripts.build_recall_views import build_item_graph_view, build_itemcf_edges, build_lightweight_full_safe_views


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path):
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_build_item_graph_view_uses_recency_distance_and_strong_signal(tmp_path):
    sequence_path = tmp_path / "user_sequences.train.jsonl"
    output_dir = tmp_path / "views"
    output_dir.mkdir()
    write_jsonl(
        sequence_path,
        [
            {
                "user_id": "u1",
                "recent_positive_item_sequence": ["a", "b", "c"],
                "recent_strong_positive_item_sequence": ["c"],
            },
            {
                "user_id": "u2",
                "recent_positive_item_sequence": ["a", "c"],
                "recent_strong_positive_item_sequence": [],
            },
        ],
    )

    stats = build_item_graph_view(
        sequence_path,
        output_dir,
        window=2,
        top_k=2,
        min_score=0.0,
        strong_multiplier=2.0,
    )

    rows = read_jsonl(output_dir / "item_graph_recall.jsonl")
    assert stats["rows_written"] == 3
    assert rows == [
        {
            "src_item": "a",
            "dst_item": "c",
            "score": 2.0,
            "cooc_cnt": 2,
            "strong_dst_cnt": 1,
            "src_occurrence_cnt": 2,
            "dst_occurrence_cnt": 2,
            "window": 2,
            "strong_multiplier": 2.0,
        },
        {
            "src_item": "a",
            "dst_item": "b",
            "score": 0.666667,
            "cooc_cnt": 1,
            "strong_dst_cnt": 0,
            "src_occurrence_cnt": 2,
            "dst_occurrence_cnt": 1,
            "window": 2,
            "strong_multiplier": 2.0,
        },
        {
            "src_item": "b",
            "dst_item": "c",
            "score": 2.0,
            "cooc_cnt": 1,
            "strong_dst_cnt": 1,
            "src_occurrence_cnt": 1,
            "dst_occurrence_cnt": 2,
            "window": 2,
            "strong_multiplier": 2.0,
        },
    ]


def test_build_itemcf_edges_uses_recent_unique_items_for_pairs(tmp_path):
    sequence_path = tmp_path / "user_sequences.train.jsonl"
    output_path = tmp_path / "itemcf_recall_weak.jsonl"
    write_jsonl(
        sequence_path,
        [
            {
                "user_id": "u1",
                "recent_positive_item_sequence": ["old", "a", "b", "a", "c"],
            },
            {
                "user_id": "u2",
                "recent_positive_item_sequence": ["a", "b", "b"],
            },
        ],
    )

    stats = build_itemcf_edges(
        sequence_path,
        output_path,
        "recent_positive_item_sequence",
        max_items_per_user=3,
    )

    rows = read_jsonl(output_path)
    assert stats["users_used"] == 2
    assert stats["unique_pair_count"] == 3
    assert {(row["src_item"], row["dst_item"]) for row in rows} == {
        ("a", "b"),
        ("b", "a"),
        ("a", "c"),
        ("c", "a"),
        ("b", "c"),
        ("c", "b"),
    }


def test_lightweight_full_safe_views_skip_heavy_outputs_and_promote_tmp(tmp_path):
    input_dir = tmp_path / "clean"
    input_dir.mkdir()
    (input_dir / "manifest.json").write_text('{"dataset":"unit"}', encoding="utf-8")
    (input_dir / "stats.json").write_text('{"outputs":{}}', encoding="utf-8")
    write_jsonl(
        input_dir / "canonical_interactions.train.jsonl",
        [
            {
                "user_id": "u1",
                "parent_asin": "a",
                "timestamp": 1,
                "label_binary": 1,
                "verified_purchase": True,
                "category": "Electronics",
            },
            {
                "user_id": "u2",
                "parent_asin": "b",
                "timestamp": 2,
                "label_binary": 1,
                "verified_purchase": False,
                "category": "Office Products",
            },
        ],
    )
    write_jsonl(
        input_dir / "canonical_items.jsonl",
        [
            {
                "parent_asin": "a",
                "category": "Electronics",
                "source_categories": ["Electronics"],
                "main_category": "Electronics",
                "categories_flat": ["Audio"],
                "title_clean": "wireless audio adapter",
                "rating_number": 10,
            },
            {
                "parent_asin": "b",
                "category": "Office Products",
                "source_categories": ["Office Products"],
                "main_category": "Office Products",
                "categories_flat": ["Paper"],
                "title_clean": "office paper adapter",
                "rating_number": 5,
            },
        ],
    )

    output_dir = tmp_path / "views"
    manifest, stats = build_lightweight_full_safe_views(
        input_dir=input_dir,
        output_dir=output_dir,
        recent_window_ratio=0.5,
        category_top_k=2,
        min_free_bytes=0,
        max_output_bytes=1024 * 1024,
        semantic_inverted_top_k=1,
    )

    assert output_dir.exists()
    assert not (tmp_path / "views_tmp").exists()
    assert (output_dir / "popular_recall.jsonl").exists()
    assert (output_dir / "category_recall_items.jsonl").exists()
    assert (output_dir / "semantic_recall_inputs.jsonl").exists()
    assert (output_dir / "semantic_inverted_index.jsonl").exists()
    assert not (output_dir / "itemcf_recall_weak.jsonl").exists()
    assert not (output_dir / "itemcf_recall_strong.jsonl").exists()
    assert not (output_dir / "item_graph_recall.jsonl").exists()
    assert manifest["mode"] == "lightweight_full_safe"
    assert set(manifest["skipped_outputs"]) == {
        "itemcf_recall_weak",
        "itemcf_recall_strong",
        "item_graph_recall",
    }
    assert manifest["outputs"]["semantic_inverted_index"] == str(output_dir / "semantic_inverted_index.jsonl")
    assert stats["safety"]["atomic_tmp_dir"] == str(tmp_path / "views_tmp")
    assert stats["safety"]["promoted_output_dir"] == str(output_dir)
    assert stats["safety"]["final_output_size_bytes"] <= 1024 * 1024
    item_signature = stats["source_signature"]["canonical_file_signatures"]["canonical_items.jsonl"]
    train_signature = stats["source_signature"]["canonical_file_signatures"]["canonical_interactions.train.jsonl"]
    assert item_signature["row_count"] == 2
    assert train_signature["row_count"] == 2
    assert item_signature["sha256"] == hashlib.sha256((input_dir / "canonical_items.jsonl").read_bytes()).hexdigest()
    assert train_signature["sha256"] == hashlib.sha256((input_dir / "canonical_interactions.train.jsonl").read_bytes()).hexdigest()
    persisted_stats = json.loads((output_dir / "stats.json").read_text(encoding="utf-8"))
    assert persisted_stats["safety"] == stats["safety"]
    inverted_rows = {row["token"]: row["parent_asins"] for row in read_jsonl(output_dir / "semantic_inverted_index.jsonl")}
    assert inverted_rows["adapter"] == ["a"]
