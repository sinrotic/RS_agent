from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.common.io import write_jsonl
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment

pytestmark = pytest.mark.unit


def test_hybrid_environment_allows_missing_optional_itemcf_strong_sidecar(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    views = tmp_path / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{
        "user_id": "u1",
        "recent_item_sequence": ["seed_audio"],
        "recent_positive_item_sequence": ["seed_audio"],
        "recent_strong_positive_item_sequence": [],
    }])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio"}])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [{"parent_asin": "earbuds_1", "score": 1.0, "category": "Audio"}]}])
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join([
            f"clean_dir: {clean}",
            f"views_dir: {views}",
            f"output_dir: {tmp_path / 'out'}",
            f"report_path: {tmp_path / 'report.md'}",
            "evaluation_mode: public_serving",
            "top_k: 2",
            "candidate_pool_size: 5",
            "popular_fallback_count: 2",
        ]),
        encoding="utf-8",
    )

    env = HybridRecommendationEnvironment.from_config(str(config), limit_users=1)
    session = env.start_session("u1")
    turn = env.converse(session, "prefer Audio")

    assert turn.recommendation.final_items
    assert env.itemcf_strong == {}
