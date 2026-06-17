from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.common.io import write_jsonl
from rs_core.recsys.pool500_artifacts import load_pool500_artifact_index

pytestmark = pytest.mark.unit


def test_pool500_artifact_loader_indexes_candidates_by_user(tmp_path: Path) -> None:
    path = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(path, [
        {
            "user_id": "u1",
            "item_id": "speaker_1",
            "source": "semantic",
            "sources": ["semantic", "popular"],
            "score": 2.0,
            "rank": 1,
            "metadata": {"category": "Audio", "source_scores": {"semantic": 2.0, "popular": 0.5}},
        },
        {
            "user_id": "u2",
            "item_id": "charger_1",
            "source": "popular",
            "sources": ["popular"],
            "score": 1.0,
            "rank": 1,
            "metadata": {"category": "Accessories"},
        },
    ])

    index = load_pool500_artifact_index(path)

    assert index.row_count == 2
    assert index.user_count == 2
    assert index.source_counts["semantic"] == 1
    assert index.source_counts["popular"] == 2
    candidates = index.candidates_for_user("u1")
    assert [candidate.item_id for candidate in candidates] == ["speaker_1"]
    assert candidates[0].sources == ["semantic", "popular"]
    assert candidates[0].source_scores["semantic"] == 2.0
    assert candidates[0].metadata["pool500_online_artifact"] is True


def test_pool500_artifact_loader_rejects_oracle_fields(tmp_path: Path) -> None:
    path = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(path, [
        {
            "user_id": "u1",
            "item_id": "speaker_1",
            "source": "semantic",
            "score": 2.0,
            "rank": 1,
            "metadata": {"label_binary": 1},
        }
    ])

    with pytest.raises(ValueError, match="evaluation-only"):
        load_pool500_artifact_index(path)


def test_pool500_artifact_loader_rejects_nested_internal_fields(tmp_path: Path) -> None:
    path = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(path, [
        {
            "user_id": "u1",
            "item_id": "speaker_1",
            "source": "usercf_recall",
            "score": 2.0,
            "rank": 1,
            "metadata": {"diagnostics": {"trace": "internal-only"}},
        }
    ])

    with pytest.raises(ValueError, match="internal"):
        load_pool500_artifact_index(path)



def test_pool500_artifact_loader_filters_allowed_sources(tmp_path: Path) -> None:
    path = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(path, [
        {"user_id": "u1", "item_id": "speaker_1", "source": "semantic", "sources": ["semantic"], "score": 2.0, "rank": 1, "metadata": {}},
        {"user_id": "u1", "item_id": "itemcf_weak_1", "source": "itemcf_weak", "sources": ["itemcf_weak"], "score": 4.0, "rank": 1, "metadata": {}},
        {"user_id": "u1", "item_id": "two_tower_1", "source": "two_tower", "sources": ["two_tower"], "score": 5.0, "rank": 1, "metadata": {}},
        {
            "user_id": "u1",
            "item_id": "semantic_title_1",
            "source": "semantic_title_category_expansion",
            "sources": ["semantic_title_category_expansion"],
            "score": 6.0,
            "rank": 1,
            "metadata": {},
        },
        {"user_id": "u1", "item_id": "usercf_1", "source": "usercf_recall", "sources": ["usercf_recall"], "score": 7.0, "rank": 1, "metadata": {}},
        {
            "user_id": "u1",
            "item_id": "co_visit_1",
            "source": "co_visit_fallback_repair",
            "sources": ["co_visit_fallback_repair"],
            "score": 8.0,
            "rank": 1,
            "metadata": {},
        },
    ])

    index = load_pool500_artifact_index(path, allowed_sources={"semantic", "itemcf_weak", "two_tower"})

    assert [candidate.item_id for candidate in index.candidates_for_user("u1")] == ["two_tower_1", "itemcf_weak_1", "speaker_1"]
    assert set(index.source_counts) == {"semantic", "itemcf_weak", "two_tower"}


def test_pool500_artifact_loader_allows_usercf_and_covisit_when_explicitly_allowed(tmp_path: Path) -> None:
    path = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(path, [
        {"user_id": "u1", "item_id": "usercf_1", "source": "usercf_recall", "sources": ["usercf_recall"], "score": 7.0, "rank": 1, "metadata": {}},
        {
            "user_id": "u1",
            "item_id": "co_visit_1",
            "source": "co_visit_fallback_repair",
            "sources": ["co_visit_fallback_repair"],
            "score": 8.0,
            "rank": 1,
            "metadata": {},
        },
    ])

    index = load_pool500_artifact_index(path, allowed_sources={"usercf_recall", "co_visit_fallback_repair"})

    assert [candidate.item_id for candidate in index.candidates_for_user("u1")] == ["co_visit_1", "usercf_1"]
    assert set(index.source_counts) == {"usercf_recall", "co_visit_fallback_repair"}
