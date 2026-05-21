from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.recsys.types import MergedCandidate
from rs_lab.experiments.recall.pool500.fallback_completion import (
    Pool500FallbackCompletionConfig,
    build_completion_audit_bundle,
    build_fallback_completion_context,
    complete_pool500_for_user,
)
from rs_lab.experiments.recall.pool500.fallback_completion.segment import segment_for_sequence
from rs_lab.experiments.recall.pool500.fallback_completion.sources import iter_source_candidates
from rs_lab.experiments.recall.pool500.fallback_completion.types import FallbackCompletionContext
from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import UserSegment, classify_user_segment

pytestmark = pytest.mark.unit

CANONICAL_FALLBACK_SOURCES = {"category", "semantic_title_category_expansion", "co_visit_fallback_repair", "popular"}


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_segment_for_sequence_delegates_to_contract_classifier() -> None:
    sequence = {"recent_item_sequence": ["i1", "i2"], "recent_positive_item_sequence": ["i1"]}

    assert segment_for_sequence(sequence) == classify_user_segment(sequence_len=2, positive_sequence_len=1)
    assert segment_for_sequence({"sequence_len": 0, "positive_sequence_len": 0}) == UserSegment.ZERO_HISTORY


def test_iter_source_candidates_and_completion_keep_fallback_metadata_path(tmp_path: Path) -> None:
    config = Pool500FallbackCompletionConfig()
    sequence = {"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}
    context = _build_file_backed_context(tmp_path, [sequence], popular_count=8)

    generated = list(iter_source_candidates(user_id="u1", seed_items=["seed"], context=context, config=config))
    assert generated
    assert {candidate.canonical_source for candidate in generated} <= CANONICAL_FALLBACK_SOURCES
    assert all(candidate.fallback_source.startswith("fallback_") for candidate in generated)

    completion = complete_pool500_for_user(
        sequence=sequence,
        existing_candidates=[],
        context=context,
        config=config,
    )

    assert completion.added_candidates
    first_added = completion.added_candidates[0]
    assert first_added.sources[0] in CANONICAL_FALLBACK_SOURCES
    assert first_added.metadata["fallback_subtype"].startswith("fallback_")
    assert first_added.metadata["fallback_stage"] == config.stage
    assert "fallback_evidence" in first_added.metadata


def test_complete_low_history_user_to_500_with_synthetic_fallback_context() -> None:
    config = Pool500FallbackCompletionConfig()
    sequence = {"user_id": "u1", "recent_item_sequence": ["seed", "seen"], "recent_positive_item_sequence": ["seed"]}
    existing = [MergedCandidate("existing_1", ["category"], {"category": 9.0})]
    context = _synthetic_context(user_id="u1", seed_item="seed")

    result = complete_pool500_for_user(
        sequence=sequence,
        existing_candidates=existing,
        context=context,
        config=config,
    )

    assert len(result.candidates) == 500
    assert result.candidates[0].item_id == "existing_1"
    assert len({candidate.item_id for candidate in result.candidates}) == 500
    assert "seed" not in {candidate.item_id for candidate in result.candidates}
    assert "seen" not in {candidate.item_id for candidate in result.candidates}
    assert _final_sources(result.candidates) <= CANONICAL_FALLBACK_SOURCES
    assert any(candidate.metadata.get("fallback_subtype") for candidate in result.added_candidates)
    assert any(source.startswith("fallback_") for source in result.audit_input["source_mix"])
    assert all(not source.startswith("fallback_") for source in _final_sources(result.candidates))


def test_zero_history_user_fills_from_global_popular_and_audits_high_risk() -> None:
    config = Pool500FallbackCompletionConfig()
    sequence = {"user_id": "cold", "recent_item_sequence": [], "recent_positive_item_sequence": []}
    context = FallbackCompletionContext(
        seed_meta_by_item={},
        seed_keys_by_user={"cold": {"brand": set(), "store": set(), "category": set(), "main_category": set(), "categories_flat": set()}},
        category_recall_index={},
        category_top_index={},
        metadata_neighbor_index={},
        semantic_token_index={},
        global_popular_items=_popular_rows("global", 560, categories=9),
        resource_audit={"heavy_job": False},
    )

    result = complete_pool500_for_user(sequence=sequence, existing_candidates=[], context=context, config=config)
    audit, validation = build_completion_audit_bundle([result.audit_input], config)
    user_audit = audit["per_user"][0]

    assert len(result.candidates) == 500
    assert _final_sources(result.candidates) == {"popular"}
    assert user_audit["completion_status"] == "TARGET_MET"
    assert user_audit["quality_risk_level"] == "HIGH"
    assert user_audit["source_mix"]["fallback_global_diversity_popular"] == 500
    assert validation["valid"] is True


def test_existing_candidates_are_preserved_first_and_capped_at_500() -> None:
    config = Pool500FallbackCompletionConfig()
    sequence = {"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}
    existing = [MergedCandidate(f"existing_{idx}", ["popular"], {"popular": 1.0}) for idx in range(510)]

    result = complete_pool500_for_user(
        sequence=sequence,
        existing_candidates=existing,
        context=_synthetic_context(user_id="u1", seed_item="seed"),
        config=config,
    )

    assert len(result.candidates) == 500
    assert [candidate.item_id for candidate in result.candidates[:3]] == ["existing_0", "existing_1", "existing_2"]
    assert result.candidates[-1].item_id == "existing_499"
    assert result.added_candidates == []


def test_duplicates_and_history_items_are_excluded() -> None:
    config = Pool500FallbackCompletionConfig()
    sequence = {"user_id": "u1", "recent_item_sequence": ["seed", "history_dup"], "recent_positive_item_sequence": ["seed"]}
    existing = [
        MergedCandidate("kept", ["category"], {"category": 1.0}),
        MergedCandidate("kept", ["popular"], {"popular": 0.5}),
        MergedCandidate("history_dup", ["popular"], {"popular": 0.4}),
    ]
    context = _synthetic_context(user_id="u1", seed_item="seed")
    context.category_recall_index["Electronics"].insert(0, {"parent_asin": "kept", "score": 10.0, "category": "Electronics"})
    context.category_recall_index["Electronics"].insert(1, {"parent_asin": "history_dup", "score": 9.0, "category": "Electronics"})

    result = complete_pool500_for_user(sequence=sequence, existing_candidates=existing, context=context, config=config)
    item_ids = [candidate.item_id for candidate in result.candidates]

    assert item_ids.count("kept") == 1
    assert "history_dup" not in item_ids
    assert len(item_ids) == len(set(item_ids))
    assert len(item_ids) == 500


def _build_file_backed_context(tmp_path: Path, sequences: list[dict[str, object]], popular_count: int) -> FallbackCompletionContext:
    clean_dir = tmp_path / "clean"
    views_dir = tmp_path / "views"
    clean_dir.mkdir()
    views_dir.mkdir()
    canonical_items = clean_dir / "canonical_items.jsonl"
    category_recall_items = views_dir / "category_recall_items.jsonl"
    category_top_items = views_dir / "category_top_items.jsonl"
    popular_recall = views_dir / "popular_recall.jsonl"
    semantic_recall_inputs = views_dir / "semantic_recall_inputs.jsonl"

    _write_jsonl(canonical_items, [{"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics", "brand": "Acme"}])
    _write_jsonl(category_recall_items, [{"parent_asin": "category_1", "score": 1.0, "main_category": "Electronics", "brand": "Acme"}])
    _write_jsonl(category_top_items, [{"bucket": "main::Electronics", "top_items": [{"parent_asin": "category_top_1", "score": 0.9}]}])
    _write_jsonl(popular_recall, _popular_rows("popular", popular_count, categories=2))
    _write_jsonl(semantic_recall_inputs, [{"parent_asin": "semantic_1", "title_clean": "gaming keyboard", "main_category": "Electronics"}])

    return build_fallback_completion_context(
        batch_sequences=sequences,
        clean_manifest={"canonical_items_path": str(canonical_items)},
        view_outputs={
            "category_recall_items": str(category_recall_items),
            "category_top_items": str(category_top_items),
            "popular_recall": str(popular_recall),
            "semantic_recall_inputs": str(semantic_recall_inputs),
        },
        config=Pool500FallbackCompletionConfig(),
    )


def _synthetic_context(user_id: str, seed_item: str) -> FallbackCompletionContext:
    seed_keys = {"brand": {"Acme"}, "store": set(), "category": set(), "main_category": {"Electronics"}, "categories_flat": set()}
    return FallbackCompletionContext(
        seed_meta_by_item={seed_item: {"parent_asin": seed_item, "title_clean": "gaming mouse", "main_category": "Electronics", "brand": "Acme"}},
        seed_keys_by_user={user_id: seed_keys},
        category_recall_index={"Electronics": _rows("category", 300, category="Electronics")},
        category_top_index={"Electronics": _rows("category_top", 220, category="Electronics")},
        metadata_neighbor_index={"brand::Acme": _rows("metadata", 200, category="Electronics")},
        semantic_token_index={"gaming": _rows("semantic", 200, category="Electronics")},
        global_popular_items=[*_popular_rows("context", 200, categories=1, category_prefix="Electronics"), *_popular_rows("global", 560, categories=8)],
        resource_audit={"heavy_job": False},
    )


def _rows(prefix: str, count: int, category: str) -> list[dict[str, object]]:
    return [{"parent_asin": f"{prefix}_{idx}", "score": 1.0 / (idx + 1), "category": category, "main_category": category} for idx in range(count)]


def _popular_rows(prefix: str, count: int, categories: int, category_prefix: str = "Popular") -> list[dict[str, object]]:
    return [
        {"parent_asin": f"{prefix}_{idx}", "pop_score": 1.0 / (idx + 1), "category": f"{category_prefix}{idx % categories}" if category_prefix != "Electronics" else "Electronics"}
        for idx in range(count)
    ]


def _final_sources(candidates: list[MergedCandidate]) -> set[str]:
    return {source for candidate in candidates for source in candidate.sources}
