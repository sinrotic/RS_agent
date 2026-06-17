from __future__ import annotations

import sqlite3
from contextlib import closing

import numpy as np
import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.rag import (
    EvidencePolicyViolation,
    DEFAULT_DENSE_MODEL_NAME,
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    LOCAL_VECTOR_METHOD,
    RAG_STANDARD_FIELDS,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    RagEvidence,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    SQLiteBM25QueryPlanningRetriever,
    SQLiteBM25Unavailable,
    build_local_vector_index,
    build_query_rag_context_for_planning,
    build_rag_context_for_ranked_candidates,
    build_sqlite_bm25_index,
    evidence_policy_violation_tokens,
    load_local_vector_index,
)
from rs_core.workflow.facades import EvidenceRAGFacade


class FakeEmbeddingBackend:
    def encode(self, texts: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        matrix = np.asarray([self._vector(text) for text in texts], dtype=np.float32)
        if normalize:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix = matrix / np.where(norms == 0.0, 1.0, norms)
        return matrix

    def encode_query(self, query: str, *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode([query], normalize=normalize, batch_size=batch_size)[0]

    def encode_passages(self, passages: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode(passages, normalize=normalize, batch_size=batch_size)

    def _vector(self, text: str) -> list[float]:
        value = text.lower()
        return [
            float(any(token in value for token in ("sofa", "couch", "seat", "seating"))),
            float(any(token in value for token in ("lamp", "light", "lighting"))),
            float(any(token in value for token in ("kettle", "hiking", "camping"))),
        ]


def test_evidence_rag_facade_off_mode_does_not_build_context_or_expose_semantics():
    ranked_items = [{"parent_asin": "i1", "title": "Wireless audio headphones", "category": "Audio"}]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {"rag": {"evidence_mode": "off"}},
        "wireless audio",
        ranked_items,
        ranked_items,
    )

    assert context is None


def test_evidence_rag_facade_shadow_and_explain_preserve_candidate_scope_and_boundaries():
    ranked_items = [
        {"parent_asin": "i1", "title": "Wireless audio headphones", "category": "Audio", "description": "Noise cancelling headset."},
        {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting", "description": "Office light."},
    ]
    final_items = [dict(ranked_items[0])]

    shadow = EvidenceRAGFacade().build_turn_rag_context(
        {"rag": {"evidence_mode": "shadow", "max_evidence_per_item": 2, "max_evidence_total": 2}},
        "wireless audio",
        ranked_items,
        final_items,
    )
    explain = EvidenceRAGFacade().build_turn_rag_context(
        {"rag": {"evidence_mode": "explain", "max_evidence_per_item": 2, "max_evidence_total": 2}},
        "wireless audio",
        ranked_items,
        final_items,
    )

    assert shadow is not None
    assert explain is not None
    assert shadow["candidate_item_ids"] == ["i1", "i2"]
    assert explain["candidate_item_ids"] == ["i1", "i2"]
    assert {row["item_id"] for row in shadow["evidence"]} <= {"i1", "i2"}
    assert {row["item_id"] for row in explain["evidence"]} <= {"i1", "i2"}
    assert shadow["metadata"]["evidence_mode"] == "shadow"
    assert explain["metadata"]["evidence_mode"] == "explain"
    for context in (shadow, explain):
        metadata = context["metadata"]
        assert metadata["retriever"] == "in_memory_candidate_card"
        assert metadata["rag_policy"]["enabled"] is True
        assert metadata["rag_diagnostics"]["max_evidence_total"] == 2
        serialized = str(context).lower()
        assert "promotion_allowed" not in serialized
        assert "ranking_replacement_allowed" not in serialized
        assert "public_payload_allowed" not in serialized



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
            "i1": {
                "title": "Wireless headphones",
                "category_path": "Electronics > Audio",
                "description": "Noise cancelling headset for music.",
                "features": "Bluetooth audio.",
                "main_category": "Audio",
            },
            "outside": {"title": "Wireless headphones", "category_path": "Electronics > Audio"},
        }
    )

    context = build_rag_context_for_ranked_candidates(
        query="wireless audio",
        candidate_item_ids=["i1"],
        retriever=retriever,
        policy=RagPolicy(mode="explain", max_evidence_per_item=4),
    )

    assert [row.item_id for row in context.evidence] == ["i1", "i1", "i1", "i1"]
    assert {row.field for row in context.evidence} == {"title", "category_path", "description", "features"}
    assert "main_category" not in {row.field for row in context.evidence}
    assert context.metadata["rag_diagnostics"]["kept_evidence_count"] == 4


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


def test_rag_policy_applies_title_field_quota_before_item_budget():
    context = build_rag_context_for_ranked_candidates(
        query="query",
        candidate_item_ids=["i1"],
        evidence=[
            RagEvidence("i1", "title", "low title", "candidate_card", score=1.0),
            RagEvidence("i1", "description", "description evidence", "candidate_card", score=8.0),
            RagEvidence("i1", "title", "best title", "candidate_card", score=10.0),
            RagEvidence("i1", "features", "features evidence", "candidate_card", score=7.0),
        ],
        policy=RagPolicy(mode="explain", max_evidence_per_item=3),
    )

    assert [row.field for row in context.evidence] == ["title", "description", "features"]
    assert [row.text for row in context.evidence if row.field == "title"] == ["best title"]


    context = build_rag_context_for_ranked_candidates(
        query="query",
        candidate_item_ids=["i1", "i2", "i3"],
        evidence=[
            RagEvidence("i1", "title", "one", "candidate_card", score=3.0),
            RagEvidence("i1", "description", "two", "candidate_card", score=2.0),
            RagEvidence("i2", "title", "three", "candidate_card", score=3.0),
            RagEvidence("i3", "title", "four", "candidate_card", score=3.0),
        ],
        policy=RagPolicy(mode="explain", max_evidence_per_item=2, max_evidence_total=2),
    )

    assert len(context.evidence) == 2
    diagnostics = context.metadata["rag_diagnostics"]
    assert diagnostics["kept_evidence_count"] == 2
    assert diagnostics["dropped_budget_overflow_count"] == 2
    assert diagnostics["max_evidence_total"] == 2


def test_rag_policy_truncates_long_evidence_text_without_mutating_original():
    original = RagEvidence("i1", "description", "x" * 30, "candidate_card", metadata={"artifact_scope": "candidate_internal"})

    context = build_rag_context_for_ranked_candidates(
        query="query",
        candidate_item_ids=["i1"],
        evidence=[original],
        policy=RagPolicy(mode="explain", max_text_chars=10),
    )

    assert original.text == "x" * 30
    assert context.evidence[0].text == "x" * 10 + "..."
    assert context.evidence[0].metadata["text_truncated"] is True
    assert context.evidence[0].metadata["original_text_chars"] == 30
    assert context.metadata["rag_diagnostics"]["truncated_text_count"] == 1


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


def test_sqlite_bm25_index_maps_canonical_fields_and_preserves_chunk_text(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    description = "First sentence describes durable trail cookware. Second sentence mentions compact nesting handles."
    items = [
        {
            "parent_asin": "i1",
            "title_clean": "Trail cook pot",
            "categories_path": ["Sports", "Camping", "Cookware"],
            "description_text": description,
            "features_text": "Titanium body. Nesting handle.",
            "item_text": "Trail cook pot full catalog text mentions compact camping nesting cookware.",
        }
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=[*RAG_STANDARD_FIELDS, "full_text"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    with closing(sqlite3.connect(index_path)) as conn:
        rows = conn.execute(
            "SELECT field, text, metadata_json FROM rag_chunks WHERE item_id = ? ORDER BY field, text",
            ("i1",),
        ).fetchall()

    text_by_field = {field: text for field, text, _ in rows}
    assert text_by_field["description"] == description
    assert text_by_field["features"] == "Titanium body. Nesting handle."
    assert text_by_field["category_path"] == "Sports > Camping > Cookware"
    assert text_by_field["full_text"] == "Trail cook pot full catalog text mentions compact camping nesting cookware."

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve("nesting camping cookware", ["i1"], max_evidence_per_item=4)

    assert {row.field for row in evidence} >= {"category_path", "features"}
    assert "full_text" not in {row.field for row in evidence}
    assert any(row.metadata["source_fields"] == ["categories_path"] for row in evidence if row.field == "category_path")
    assert any(row.metadata["source_fields"] == ["features_text"] for row in evidence if row.field == "features")


def test_default_rag_fields_exclude_noisy_category_aliases():
    assert RAG_STANDARD_FIELDS == ["title", "category_path", "description", "features"]


def test_sqlite_bm25_index_streams_input_without_len(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    items = (
        {"parent_asin": f"i{idx}", "title": f"Wireless audio item {idx}", "category": "Audio"}
        for idx in range(1205)
    )
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "category"], batch_size=100)
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    with closing(sqlite3.connect(index_path)) as conn:
        chunk_count = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        indexed_item_count = conn.execute("SELECT COUNT(DISTINCT item_id) FROM rag_chunks").fetchone()[0]
        item_id_indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list('rag_chunks')").fetchall()
            if str(row[1]).startswith("idx_rag_chunks_item_id")
        }

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve("wireless audio", ["i1204"])
    assert chunk_count == 2410
    assert indexed_item_count == 1205
    assert item_id_indexes == {"idx_rag_chunks_item_id"}
    assert evidence[0].item_id == "i1204"


def test_sqlite_bm25_retriever_filters_default_fields_and_limits_title_quota(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    items = [
        {
            "parent_asin": "i1",
            "title": "Wireless audio headphones",
            "category": "Audio",
            "main_category": "Electronics",
            "category_path": "Electronics > Audio",
            "description": "Wireless audio headset. Wireless music headphones.",
            "features": "Bluetooth audio. Foldable headphones.",
        },
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "category", "main_category", "category_path", "description", "features"], max_chunk_chars=24)
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve(
        "wireless audio headphones bluetooth electronics",
        candidate_item_ids=["i1"],
        max_evidence_per_item=4,
    )

    fields = [row.field for row in evidence]
    assert fields.count("title") <= 1
    assert "category" not in fields
    assert "main_category" not in fields
    assert "description" in fields
    assert "features" in fields


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


def test_sqlite_bm25_query_planning_retriever_searches_catalog_without_candidate_pool(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    items = [
        {"parent_asin": "i1", "title": "Trail cookware pot", "category": "Camping", "description": "Compact nesting handle for hiking."},
        {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting", "description": "Office reading light."},
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "category", "description"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = SQLiteBM25QueryPlanningRetriever(index_path, fields=["title", "description"]).retrieve(
        "compact camping cookware",
        max_evidence_total=3,
        max_evidence_per_item=1,
    )

    assert evidence
    assert {row.item_id for row in evidence} == {"i1"}
    assert len(evidence) <= 3
    assert evidence[0].metadata["retriever"] == "sqlite_bm25_query_planning"
    assert evidence[0].metadata["retrieval_scope"] == "query_planning"
    assert evidence[0].metadata["candidate_generation_allowed"] is False


def test_query_planning_rag_context_filters_policy_and_keeps_non_candidate_evidence():
    context = build_query_rag_context_for_planning(
        query="trail cookware",
        evidence=[
            RagEvidence("i1", "title", "Trail cookware", "catalog", score=4.0),
            RagEvidence("i2", "description", "A" * 80, "catalog", score=3.0),
            RagEvidence("i3", "features", "Filtered by allowed fields", "catalog", score=2.0),
            RagEvidence("i4", "title", "Future label leak", "catalog", score=1.0, metadata={"source_path": "future_label.json"}),
        ],
        policy=RagPolicy(mode="shadow", max_evidence_per_item=1, max_evidence_total=2, max_text_chars=24, allowed_fields=["title", "description"]),
    )

    assert context.candidate_item_ids == []
    assert {row.item_id for row in context.evidence} == {"i1", "i2"}
    assert context.evidence[1].text.endswith("...")
    assert context.metadata["retrieval_scope"] == "query_planning"
    assert context.metadata["candidate_scoped"] is False
    diagnostics = context.metadata["rag_diagnostics"]
    assert diagnostics["dropped_non_candidate_evidence_count"] == 0
    assert diagnostics["dropped_policy_violation_count"] == 1
    assert diagnostics["truncated_text_count"] == 1


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


def test_hybrid_candidate_retriever_filters_default_fields_and_limits_title_quota(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    items = [
        {
            "parent_asin": "i1",
            "title": "Wireless audio headphones",
            "category": "Audio",
            "main_category": "Electronics",
            "category_path": "Electronics > Audio",
            "description": "Wireless music headset for audio calls.",
            "features": "Bluetooth audio support.",
        },
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "category", "main_category", "category_path", "description", "features"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = HybridCandidateRetriever(index_path).retrieve(
        "wireless audio bluetooth electronics",
        candidate_item_ids=["i1"],
        max_evidence_per_item=4,
    )

    fields = [row.field for row in evidence]
    assert fields.count("title") <= 1
    assert "category" not in fields
    assert "main_category" not in fields
    assert "description" in fields
    assert "features" in fields


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
    assert any(row.metadata.get("vector_method") == "hashed_text_vector_v1" for row in evidence)
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
    vector_index_path = tmp_path / "rag.vector.pkl"
    manifest_path = tmp_path / "manifest.json"
    write_jsonl(
        items_path,
        [
            {"parent_asin": "i1", "title": "Wireless headphones", "category": "Audio"},
            {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting"},
        ],
    )

    try:
        source_manifest_path = tmp_path / "source_manifest.json"
        source_manifest_path.write_text("{}", encoding="utf-8")
        manifest = build_rag_bm25_index(
            items_path=items_path,
            index_path=index_path,
            manifest_path=manifest_path,
            fields=["title", "category"],
            vector_index_path=vector_index_path,
            vector_method="tfidf",
            source_manifest_path=source_manifest_path,
        )
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve("wireless audio", ["i1", "i2"])
    vector_index = load_local_vector_index(vector_index_path)

    assert manifest["schema_version"] == "rag_sqlite_bm25_index_v1"
    assert manifest["chunk_count"] == 4
    assert manifest["hybrid_supported"] is True
    assert manifest["hybrid_vector_method"] == LOCAL_VECTOR_METHOD
    assert manifest["embedding_method"] == LOCAL_VECTOR_METHOD
    assert manifest["local_vector_method"] == LOCAL_VECTOR_METHOD
    assert manifest["vector_index_path"] == str(vector_index_path.resolve())
    assert manifest["corpus_scope"] == "product_catalog"
    assert manifest["index_scope"] == "product_catalog"
    assert manifest["retrieval_scope"] == "candidate_item_ids"
    assert manifest["artifact_role"] == "rag_evidence"
    assert manifest["knowledge_base_role"] == "rag_evidence"
    assert manifest["source_manifest_path"] == str(source_manifest_path.resolve())
    assert manifest["item_universe"] == "train_only"
    assert manifest["catalog_snapshot_scope"] == "recent_window_train_catalog"
    assert manifest["text_policy"] == "compact_catalog_source_fields_v1"
    assert manifest["raw_item_text_indexed"] is False
    assert manifest["item_text_compact_source_only"] is True
    assert manifest["dense_granularity"] == "item"
    assert manifest["embedding_dtype"] == "float16"
    assert manifest["fusion_method"] == "rrf"
    assert manifest["candidate_scoped"] is True
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["safety_flags"] == {
        "candidate_scoped": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "raw_item_text_indexed": False,
        "item_text_compact_source_only": True,
    }
    assert vector_index.metadata["local_vector_method"] == LOCAL_VECTOR_METHOD
    assert vector_index.metadata["chunk_count"] == 2
    assert vector_index.metadata["item_level"] is True
    assert vector_index.metadata["storage_dtype"] == "float16"
    assert vector_index.metadata["corpus_scope"] == "product_catalog"
    assert vector_index.metadata["retrieval_scope"] == "candidate_item_ids"
    assert vector_index.metadata["artifact_role"] == "rag_evidence"
    assert vector_index.metadata["knowledge_base_role"] == "rag_evidence"
    assert vector_index.metadata["candidate_generation_allowed"] is False
    assert vector_index.metadata["ranking_input_replacement_allowed"] is False
    assert vector_index.metadata["promotion_allowed"] is False
    assert [chunk.field for chunk in vector_index.chunks] == ["compact_text", "compact_text"]
    assert [chunk.item_id for chunk in vector_index.chunks] == ["i1", "i2"]
    assert evidence[0].item_id == "i1"


def test_rag_bm25_build_script_streams_without_vector_index(tmp_path):
    from rs_core.common.io import write_jsonl
    from scripts.recall.build_rag_bm25_index import build_rag_bm25_index

    items_path = tmp_path / "items.jsonl"
    index_path = tmp_path / "rag.sqlite"
    manifest_path = tmp_path / "manifest.json"
    write_jsonl(
        items_path,
        ({"parent_asin": f"i{idx}", "title": f"Compact camping cup {idx}", "category": "Camping"} for idx in range(1500)),
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

    evidence = SQLiteBM25CandidateRetriever(index_path).retrieve("camping cup", ["i1499"])
    assert manifest["item_row_count"] == 1500
    assert manifest["indexed_item_count"] == 1500
    assert manifest["chunk_count"] == 3000
    assert evidence[0].item_id == "i1499"


def test_hybrid_candidate_retriever_uses_local_vector_index_and_candidate_scope(tmp_path):
    from rs_core.common.io import write_jsonl
    from scripts.recall.build_rag_bm25_index import build_rag_bm25_index

    items_path = tmp_path / "items.jsonl"
    index_path = tmp_path / "rag.sqlite"
    vector_index_path = tmp_path / "rag.vector.pkl"
    write_jsonl(
        items_path,
        [
            {"parent_asin": "i1", "title": "Carbon hiking kettle", "category": "Camping", "description": "Ultralight stove-safe water boiler."},
            {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting", "description": "Adjustable office light."},
            {"parent_asin": "outside", "title": "Carbon hiking kettle", "category": "Camping", "description": "Outside candidate item."},
        ],
    )
    try:
        build_rag_bm25_index(
            items_path=items_path,
            index_path=index_path,
            fields=["title", "category", "description"],
            vector_index_path=vector_index_path,
            vector_method="tfidf",
        )
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    evidence = HybridCandidateRetriever(index_path).retrieve(
        "carbon hiking camping kettle",
        candidate_item_ids=["i1", "i2"],
        max_evidence_per_item=3,
    )

    assert evidence
    assert {row.item_id for row in evidence} <= {"i1", "i2"}
    assert "outside" not in {row.item_id for row in evidence}
    assert any(row.metadata["vector_method"] == LOCAL_VECTOR_METHOD for row in evidence)
    assert all(row.metadata["retriever"] == "hybrid" for row in evidence)


def test_dense_vector_index_uses_embedding_backend_and_candidate_scope(tmp_path):
    vector_index_path = tmp_path / "rag.dense.pkl"
    items = [
        {"parent_asin": "i1", "title": "Modern sofa", "description": "Comfortable couch seating for living room."},
        {"parent_asin": "i2", "title": "Desk lamp", "description": "Adjustable office lighting."},
        {"parent_asin": "outside", "title": "Modern sofa", "description": "Outside candidate couch."},
    ]

    build_local_vector_index(
        vector_index_path,
        items,
        fields=["title", "description"],
        vector_method="dense",
        embedding_model_name=DEFAULT_DENSE_MODEL_NAME,
        embedding_backend=FakeEmbeddingBackend(),
    )
    vector_index = load_local_vector_index(vector_index_path)
    evidence = vector_index.retrieve(
        "couch seating",
        candidate_item_ids=["i1", "i2"],
        max_evidence_per_item=2,
        embedding_backend=FakeEmbeddingBackend(),
    )

    assert vector_index.metadata["local_vector_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD
    assert vector_index.metadata["embedding_model_name"] == DEFAULT_DENSE_MODEL_NAME
    assert vector_index.metadata["corpus_scope"] == "product_catalog"
    assert vector_index.metadata["retrieval_scope"] == "candidate_item_ids"
    assert evidence
    assert {row.item_id for row in evidence} == {"i1"}
    assert "outside" not in {row.item_id for row in evidence}
    assert all(row.metadata["vector_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD for row in evidence)


def test_hybrid_candidate_retriever_uses_dense_vector_index_with_fake_backend(tmp_path):
    index_path = tmp_path / "rag.sqlite"
    vector_index_path = tmp_path / "rag.dense.pkl"
    items = [
        {"parent_asin": "i1", "title": "Modern sofa", "description": "Comfortable couch seating."},
        {"parent_asin": "i2", "title": "Desk lamp", "description": "Adjustable office lighting."},
    ]
    try:
        build_sqlite_bm25_index(index_path, items, fields=["title", "description"])
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")
    build_local_vector_index(
        vector_index_path,
        items,
        fields=["title", "description"],
        vector_method="dense",
        embedding_backend=FakeEmbeddingBackend(),
    )

    evidence = HybridCandidateRetriever(
        index_path,
        vector_index_path=vector_index_path,
        embedding_backend=FakeEmbeddingBackend(),
        fusion_method="rrf",
    ).retrieve("couch seating", ["i1", "i2"], max_evidence_per_item=2)

    assert evidence
    assert {row.item_id for row in evidence} <= {"i1", "i2"}
    assert evidence[0].metadata["retriever"] == "hybrid"
    assert evidence[0].metadata["fusion_method"] == "rrf"
    assert any(row.metadata["vector_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD for row in evidence)


def test_hybrid_rrf_fusion_uses_rank_positions():
    retriever = HybridCandidateRetriever("missing.sqlite", fusion_method="rrf", bm25_weight=0.0, vector_weight=1.0, rrf_k=10)
    bm25_evidence = [
        RagEvidence("i1", "title", "exact title", "catalog_bm25", score=10.0),
        RagEvidence("i2", "title", "second title", "catalog_bm25", score=9.0),
    ]
    vector_evidence = [
        RagEvidence("i2", "title", "second title", "hybrid_vector", score=0.9, metadata={"vector_method": "dense"}),
        RagEvidence("i1", "title", "exact title", "hybrid_vector", score=0.8, metadata={"vector_method": "dense"}),
    ]

    evidence = retriever._fuse(bm25_evidence, vector_evidence, max_evidence_per_item=2)

    assert [(row.item_id, row.text) for row in evidence] == [("i2", "second title"), ("i1", "exact title")]
    assert evidence[0].metadata["fusion_method"] == "rrf"
    assert evidence[0].metadata["vector_rank"] == 1
    assert evidence[0].metadata["vector_rrf"] > evidence[1].metadata["vector_rrf"]


def test_hybrid_weighted_fusion_applies_field_weights():
    retriever = HybridCandidateRetriever("missing.sqlite", fusion_method="weighted", field_weights={"features": 2.0, "title": 0.5})
    bm25_evidence = [
        RagEvidence("i1", "title", "same score title", "catalog_bm25", score=1.0),
        RagEvidence("i1", "features", "same score features", "catalog_bm25", score=1.0),
    ]

    evidence = retriever._fuse(bm25_evidence, [], max_evidence_per_item=2)

    assert [row.field for row in evidence] == ["features", "title"]
    assert evidence[0].metadata["fusion_method"] == "weighted"
    assert evidence[0].metadata["field_weight"] == 2.0
    assert evidence[0].score > evidence[1].score


def test_rag_bm25_build_script_records_dense_vector_manifest(tmp_path):
    from rs_core.common.io import write_jsonl
    from scripts.recall.build_rag_bm25_index import build_rag_bm25_index

    items_path = tmp_path / "items.jsonl"
    index_path = tmp_path / "rag.sqlite"
    vector_index_path = tmp_path / "rag.dense.pkl"
    manifest_path = tmp_path / "manifest.json"
    write_jsonl(
        items_path,
        [
            {"parent_asin": "i1", "title": "Modern sofa", "description": "Comfortable couch seating."},
            {"parent_asin": "i2", "title": "Desk lamp", "description": "Adjustable office lighting."},
        ],
    )

    try:
        manifest = build_rag_bm25_index(
            items_path=items_path,
            index_path=index_path,
            manifest_path=manifest_path,
            fields=["title", "description"],
            vector_index_path=vector_index_path,
            embedding_backend=FakeEmbeddingBackend(),
        )
    except SQLiteBM25Unavailable:
        pytest.skip("SQLite FTS5 is not available")

    vector_index = load_local_vector_index(vector_index_path)
    assert manifest["hybrid_vector_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD
    assert manifest["embedding_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD
    assert manifest["local_vector_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD
    assert manifest["embedding_model_name"] == DEFAULT_DENSE_MODEL_NAME
    assert manifest["corpus_scope"] == "product_catalog"
    assert manifest["retrieval_scope"] == "candidate_item_ids"
    assert manifest["artifact_role"] == "rag_evidence"
    assert manifest["knowledge_base_role"] == "rag_evidence"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["dense_granularity"] == "item"
    assert manifest["embedding_dtype"] == "float16"
    assert manifest["fusion_method"] == "rrf"
    assert manifest["fusion_supported"] == ["weighted", "rrf"]
    assert vector_index.metadata["local_vector_method"] == SENTENCE_TRANSFORMER_VECTOR_METHOD
    assert vector_index.metadata["corpus_scope"] == "product_catalog"
    assert vector_index.metadata["retrieval_scope"] == "candidate_item_ids"
    assert vector_index.metadata["artifact_role"] == "rag_evidence"
    assert vector_index.metadata["candidate_generation_allowed"] is False
