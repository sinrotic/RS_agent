from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.rag import (
    EvidencePolicyViolation,
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    RagEvidence,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    SQLiteBM25Unavailable,
    build_rag_context_for_ranked_candidates,
    build_sqlite_bm25_index,
    evidence_policy_violation_tokens,
)


def test_rag_policy_off_returns_empty_context():
    context = build_rag_context_for_ranked_candidates(
        query="wireless headphones",
        candidate_item_ids=["i1"],
        evidence=[RagEvidence("i1", "title", "Wireless headphones", "candidate_card")],
        policy=RagPolicy(mode="off"),
    )

    assert context.candidate_item_ids == ["i1"]
    assert context.evidence == []
    assert context.metadata["rag_policy"] == {"mode": "off", "enabled": False}


def test_candidate_card_retriever_uses_only_ranked_candidate_items():
    retriever = InMemoryCandidateCardRetriever(
        {
            "i1": {"title": "Wireless headphones", "main_category": "Audio"},
            "outside": {"title": "Wireless headphones", "main_category": "Audio"},
        }
    )

    context = build_rag_context_for_ranked_candidates(
        query="wireless audio",
        candidate_item_ids=["i1"],
        retriever=retriever,
        policy=RagPolicy(mode="explain", max_evidence_per_item=2),
    )

    assert [row.item_id for row in context.evidence] == ["i1", "i1"]
    assert {row.field for row in context.evidence} == {"title", "main_category"}
    assert context.metadata["rag_diagnostics"]["kept_evidence_count"] == 2


def test_rag_context_drops_non_candidate_and_forbidden_provenance_by_default():
    context = build_rag_context_for_ranked_candidates(
        query="query",
        candidate_item_ids=["i1"],
        evidence=[
            RagEvidence("i1", "catalog_label_text", "safe display label", "candidate_card"),
            RagEvidence("i2", "title", "outside", "candidate_card"),
            RagEvidence("i1", "title", "leaky", "offline_eval_label", metadata={"source_path": "holdout/target.json"}),
        ],
        policy=RagPolicy(mode="shadow"),
    )

    assert [(row.item_id, row.field) for row in context.evidence] == [("i1", "catalog_label_text")]
    diagnostics = context.metadata["rag_diagnostics"]
    assert diagnostics["dropped_non_candidate_evidence_count"] == 1
    assert diagnostics["dropped_policy_violation_count"] == 1
    assert diagnostics["policy_violations"][0]["tokens"] == ["eval", "holdout", "label", "target"]


def test_rag_strict_mode_raises_on_forbidden_provenance():
    with pytest.raises(EvidencePolicyViolation):
        build_rag_context_for_ranked_candidates(
            query="query",
            candidate_item_ids=["i1"],
            evidence=[RagEvidence("i1", "title", "leaky", "oracle_source")],
            policy=RagPolicy(mode="explain", strict=True),
        )


def test_provenance_gate_tokenizes_segments_without_field_name_false_positive():
    safe = RagEvidence(
        "i1",
        "display_label",
        "safe label text",
        "candidate-card-v1",
        metadata={"artifact_scope": "candidate_internal"},
    )
    leaky = RagEvidence(
        "i1",
        "title",
        "leaky",
        "candidate_card",
        metadata={"provenance": "diagnostic_label/future_target.json"},
    )

    assert evidence_policy_violation_tokens(safe) == []
    assert evidence_policy_violation_tokens(leaky) == ["diagnostic", "future", "label", "target"]


def test_sqlite_bm25_retriever_limits_scope_to_candidate_items(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    items = [
        {"parent_asin": "i1", "title": "Wireless audio headphones", "category": "Audio", "description": "Noise cancelling headset."},
        {"parent_asin": "i2", "title": "Wireless audio speaker", "category": "Audio", "description": "Portable speaker."},
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "category", "description"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve(
        "wireless audio headphones",
        candidate_item_ids=["i1"],
        max_evidence_per_item=2,
    )

    assert evidence
    assert {row.item_id for row in evidence} == {"i1"}
    assert evidence[0].metadata["retriever"] == "sqlite_bm25"


def test_hybrid_rag_context_uses_sqlite_bm25_when_index_path_exists(tmp_path):
    from rs_core.workflow.hybrid_environment import _build_turn_rag_context

    index_path = tmp_path / "rag.sqlite"
    ranked_items = [
        {
            "parent_asin": "i1",
            "title": "Wireless audio headphones",
            "category": "Audio",
            "description": "Noise cancelling headset for music.",
        }
    ]
    try:
        build_sqlite_bm25_index(index_path, ranked_items, fields=["title", "category", "description", "summary"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    context = _build_turn_rag_context(
        {"rag": {"evidence_mode": "explain", "index_path": str(index_path), "fields": ["title", "category", "description", "summary"]}},
        "wireless audio",
        ranked_items,
        [],
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "sqlite_bm25"
    assert context["metadata"]["rag_diagnostics"]["kept_evidence_count"] >= 1
    assert {row["item_id"] for row in context["evidence"]} == {"i1"}


def test_hybrid_candidate_retriever_fuses_bm25_and_vector_scores(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    items = [
        {"parent_asin": "i1", "title": "Wireless headphones", "category": "Audio", "description": "Noise cancelling headset for music."},
        {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting", "description": "Adjustable office light."},
        {"parent_asin": "outside", "title": "Wireless headphones", "category": "Audio"},
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "category", "description"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = HybridCandidateRetriever(index_path).retrieve(
        "wireless audio music",
        candidate_item_ids=["i1", "i2"],
        max_evidence_per_item=2,
    )

    assert evidence
    assert {row.item_id for row in evidence} <= {"i1", "i2"}
    assert "outside" not in {row.item_id for row in evidence}
    assert evidence[0].metadata["retriever"] == "hybrid"
    assert "bm25_norm" in evidence[0].metadata
    assert "vector_norm" in evidence[0].metadata
    assert "hybrid_score" in evidence[0].metadata


def test_hybrid_rag_context_selects_hybrid_retriever_from_config(tmp_path):
    from rs_core.workflow.hybrid_environment import _build_turn_rag_context

    index_path = tmp_path / "rag.sqlite"
    ranked_items = [
        {
            "parent_asin": "i1",
            "title": "Wireless audio headphones",
            "category": "Audio",
            "description": "Noise cancelling headset for music.",
        }
    ]
    try:
        build_sqlite_bm25_index(index_path, ranked_items, fields=["title", "category", "description", "summary"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    context = _build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "retriever": "hybrid",
                "index_path": str(index_path),
                "fields": ["title", "category", "description", "summary"],
                "hybrid": {"bm25_weight": 0.6, "vector_weight": 0.4, "vector_dim": 128},
            }
        },
        "wireless audio music",
        ranked_items,
        [],
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "hybrid"
    assert context["metadata"]["rag_diagnostics"]["kept_evidence_count"] >= 1
    assert context["evidence"][0]["metadata"]["retriever"] == "hybrid"


def test_rag_bm25_build_script_outputs_usable_index(tmp_path):
    from rs_core.common.io import write_jsonl
    from scripts.recall.build_rag_bm25_index import build_rag_bm25_index

    items_path = tmp_path / "items.jsonl"
    index_path = tmp_path / "rag.sqlite"
    manifest_path = tmp_path / "manifest.json"
    write_jsonl(
        items_path,
        [
            {"parent_asin": "i1", "title": "Wireless headphones", "category": "Audio"},
            {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting"},
        ],
    )

    try:
        manifest = build_rag_bm25_index(
            items_path=items_path,
            index_path=index_path,
            manifest_path=manifest_path,
            fields=["title", "category"],
        )
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve("wireless audio", ["i1", "i2"])

    assert manifest["schema_version"] == "rag_sqlite_bm25_index_v1"
    assert manifest["chunk_count"] == 4
    assert manifest["hybrid_supported"] is True
    assert manifest["hybrid_vector_method"] == "hashed_text_vector_v1"
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert evidence[0].item_id == "i1"
