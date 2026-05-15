from __future__ import annotations

import json

from scripts.build_recall_views import build_item_graph_view


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
