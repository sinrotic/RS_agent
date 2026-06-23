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
    RAG_PARENT_PROFILE_FIELD,
    RAG_STANDARD_FIELDS,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    RagEvidence,
    RagPolicy,
    Small2BigCandidateEvidenceRetriever,
    SQLiteBM25CandidateRetriever,
    SQLiteBM25QueryPlanningRetriever,
    SQLiteBM25Unavailable,
    build_local_vector_index,
    build_query_rag_context_for_planning,
    build_rag_context_for_ranked_candidates,
    build_sqlite_bm25_index,
    evidence_policy_violation_tokens,
    validate_parent_profile_manifest,
    load_local_vector_index,
)
from rs_core.agent_runtime.adapters.rag import RagAgentAdapter
from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.schema import AgentTurn, FeedbackConstraints
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


class FakeVectorBackend:
    def retrieve(self, query: str, candidate_item_ids, max_evidence_per_item: int = 3):  # type: ignore[no-untyped-def]
        return [RagEvidence(str(candidate_item_ids[0]), "title", f"vector-only {query}", "qdrant_vector", score=1.0)]


class FailingVectorBackend:
    def retrieve(self, query: str, candidate_item_ids, max_evidence_per_item: int = 3):  # type: ignore[no-untyped-def]
        raise RuntimeError("dense backend unavailable")


class StaticEvidenceRetriever:
    def __init__(self, evidence: list[RagEvidence]) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, list[str], int]] = []

    def retrieve(self, query: str, candidate_item_ids, max_evidence_per_item: int = 3):  # type: ignore[no-untyped-def]
        candidate_ids = [str(item_id) for item_id in candidate_item_ids]
        self.calls.append((query, candidate_ids, max_evidence_per_item))
        candidate_id_set = set(candidate_ids)
        return [row for row in self.evidence if str(row.item_id) in candidate_id_set]


def _valid_small2big_manifest() -> dict[str, object]:
    return {
        "schema_version": "small2big_parent_profile.v1",
        "train_only": True,
        "no_holdout": True,
        "source_hash": "fixture-source-hash",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "raw_profile_public_projection": True,
    }


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


def test_evidence_rag_facade_small2big_invalid_manifest_file_fails_closed(tmp_path):
    manifest_path = tmp_path / "broken_manifest.json"
    manifest_path.write_text("{not-json", encoding="utf-8")
    ranked_items = [{"parent_asin": "i1", "title": "Titanium camping kettle", "category": "Camping"}]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "max_evidence_per_item": 1,
                "small2big": {"enabled": True, "parent_store_manifest_path": str(manifest_path)},
            }
        },
        "camping kettle",
        ranked_items,
        ranked_items,
    )

    assert context is not None
    assert [row["field"] for row in context["evidence"]] == ["title"]
    assert context["evidence"][0]["metadata"]["small2big"] == {"passed": False, "failure_reason": "missing_manifest"}


def test_evidence_rag_facade_small2big_string_false_stays_disabled():
    ranked_items = [{"parent_asin": "i1", "title": "Titanium camping kettle", "description_text": "Parent context"}]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "max_evidence_per_item": 1,
                "small2big": {"enabled": "false", "manifest": _valid_small2big_manifest()},
            }
        },
        "camping kettle",
        ranked_items,
        ranked_items,
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "in_memory_candidate_card"
    assert context["metadata"]["small2big"] == {"enabled": False}
    assert [row["field"] for row in context["evidence"]] == ["title"]


def test_evidence_rag_facade_small2big_invalid_enabled_fails_closed():
    ranked_items = [{"parent_asin": "i1", "title": "Titanium camping kettle", "description_text": "Parent context"}]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "max_evidence_per_item": 1,
                "small2big": {"enabled": "maybe", "manifest": _valid_small2big_manifest()},
            }
        },
        "camping kettle",
        ranked_items,
        ranked_items,
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "in_memory_candidate_card"
    assert context["metadata"]["small2big"]["enabled"] is False
    assert "Invalid boolean config" in context["metadata"]["small2big"]["error"]
    assert [row["field"] for row in context["evidence"]] == ["title"]


def test_evidence_rag_facade_small2big_zero_budget_does_not_expand_context_budget():
    ranked_items = [{"parent_asin": "i1", "title": "Titanium camping kettle", "category": "Camping", "description_text": "Parent context"}]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "max_evidence_per_item": 1,
                "max_evidence_total": 1,
                "small2big": {
                    "enabled": True,
                    "manifest": _valid_small2big_manifest(),
                    "max_parent_profiles_total": 0,
                    "max_parent_profiles_per_item": 0,
                },
            }
        },
        "camping kettle",
        ranked_items,
        ranked_items,
    )

    assert context is not None
    assert [row["field"] for row in context["evidence"]] == ["title"]
    assert context["metadata"]["rag_diagnostics"]["max_evidence_per_item"] == 1
    assert context["metadata"]["rag_diagnostics"]["max_evidence_total"] == 1


def test_evidence_rag_facade_small2big_adds_parent_profile_without_changing_candidates():
    ranked_items = [
        {
            "parent_asin": "i1",
            "title": "Titanium camping kettle",
            "category": "Camping",
            "description_text": "Parent-level description for backpacking water boiling.",
            "features_text": "Lightweight. Folding handle.",
            "target_label": "must not leak",
        },
        {
            "parent_asin": "i2",
            "title": "Desk lamp",
            "category": "Lighting",
            "description_text": "Office light.",
        },
    ]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "max_evidence_per_item": 2,
                "max_evidence_total": 4,
                "max_text_chars": 400,
                "small2big": {
                    "enabled": True,
                    "manifest": _valid_small2big_manifest(),
                    "max_parent_profiles_total": 1,
                    "max_parent_profiles_per_item": 1,
                },
            }
        },
        "camping kettle",
        ranked_items,
        ranked_items[:1],
    )

    assert context is not None
    assert context["candidate_item_ids"] == ["i1", "i2"]
    assert context["metadata"]["retriever"] == "in_memory_candidate_card_small2big"
    assert context["metadata"]["small2big"]["enabled"] is True
    assert context["metadata"]["small2big"]["parent_field"] == RAG_PARENT_PROFILE_FIELD
    parent_rows = [row for row in context["evidence"] if row["field"] == RAG_PARENT_PROFILE_FIELD]
    assert len(parent_rows) == 1
    assert parent_rows[0]["item_id"] == "i1"
    assert "Parent-level description" in parent_rows[0]["text"]
    assert "target_label" not in parent_rows[0]["text"]
    assert parent_rows[0]["metadata"]["promotion_allowed"] is False
    assert parent_rows[0]["metadata"]["requires_parent_context_agent"] is True
    assert {row["item_id"] for row in context["evidence"]} <= {"i1", "i2"}
    assert context["metadata"]["rag_diagnostics"]["max_evidence_total"] == 5



def test_evidence_rag_facade_hybrid_falls_back_to_bm25_when_qdrant_missing(tmp_path):
    db = tmp_path / "rag.sqlite"
    build_sqlite_bm25_index(
        db,
        [
            {"parent_asin": "i1", "title": "Bluetooth audio speaker", "main_category": "Audio"},
            {"parent_asin": "i2", "title": "Desk lamp", "main_category": "Lighting"},
        ],
    )
    ranked_items = [
        {"parent_asin": "i1", "title": "Bluetooth audio speaker", "category": "Audio"},
        {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting"},
    ]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "retriever": "hybrid",
                "index_path": str(db),
                "hybrid": {
                    "qdrant": {
                        "enabled": True,
                        "collection_name": "missing_collection",
                        "candidate_generation_allowed": False,
                        "ranking_input_replacement_allowed": False,
                        "promotion_allowed": False,
                    }
                },
            }
        },
        "bluetooth audio",
        ranked_items,
        ranked_items[:1],
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "hybrid_bm25_fallback"
    assert context["evidence"]
    assert {row["item_id"] for row in context["evidence"]} <= {"i1", "i2"}


def test_evidence_rag_facade_hybrid_qdrant_small2big_is_candidate_scoped(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "rag.sqlite"
    build_sqlite_bm25_index(
        db,
        [
            {"parent_asin": "i1", "title": "Bluetooth audio speaker", "main_category": "Audio", "features": "portable wireless sound"},
            {"parent_asin": "i2", "title": "Desk lamp", "main_category": "Lighting", "features": "office light"},
        ],
    )
    ranked_items = [
        {"parent_asin": "i1", "title": "Bluetooth audio speaker", "category": "Audio", "description": "Parent speaker profile"},
        {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting", "description": "Parent lamp profile"},
    ]
    monkeypatch.setattr("rs_core.workflow.facades._safe_qdrant_rag_vector_backend", lambda rag_config, hybrid_config: FakeVectorBackend())

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "retriever": "hybrid",
                "index_path": str(db),
                "hybrid": {"qdrant": {"enabled": True, "collection_name": "rag_chunks"}},
                "small2big": {
                    "enabled": True,
                    "manifest": _valid_small2big_manifest(),
                    "max_parent_profiles_total": 2,
                    "max_parent_profiles_per_item": 1,
                },
            }
        },
        "bluetooth audio",
        ranked_items,
        ranked_items[:1],
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "hybrid_qdrant_small2big"
    assert context["metadata"]["small2big"]["enabled"] is True
    parent_rows = [row for row in context["evidence"] if row["field"] == RAG_PARENT_PROFILE_FIELD]
    assert parent_rows
    assert {row["item_id"] for row in context["evidence"]} <= set(context["candidate_item_ids"])
    assert all(row["metadata"].get("candidate_generation_allowed") is False for row in parent_rows)
    assert all(row["metadata"].get("ranking_input_replacement_allowed") is False for row in parent_rows)
    assert all(row["metadata"].get("promotion_allowed") is False for row in parent_rows)


def test_evidence_rag_facade_hybrid_bm25_fallback_small2big_is_explicit(tmp_path):
    db = tmp_path / "rag.sqlite"
    build_sqlite_bm25_index(
        db,
        [
            {"parent_asin": "i1", "title": "Bluetooth audio speaker", "main_category": "Audio", "features": "portable wireless sound"},
            {"parent_asin": "i2", "title": "Desk lamp", "main_category": "Lighting", "features": "office light"},
        ],
    )
    ranked_items = [
        {"parent_asin": "i1", "title": "Bluetooth audio speaker", "category": "Audio", "description": "Parent speaker profile"},
        {"parent_asin": "i2", "title": "Desk lamp", "category": "Lighting", "description": "Parent lamp profile"},
    ]

    context = EvidenceRAGFacade().build_turn_rag_context(
        {
            "rag": {
                "evidence_mode": "explain",
                "retriever": "hybrid",
                "index_path": str(db),
                "hybrid": {"qdrant": {"enabled": True, "collection_name": "missing_collection"}},
                "small2big": {
                    "enabled": True,
                    "manifest": _valid_small2big_manifest(),
                    "max_parent_profiles_total": 2,
                    "max_parent_profiles_per_item": 1,
                },
            }
        },
        "bluetooth audio",
        ranked_items,
        ranked_items[:1],
    )

    assert context is not None
    assert context["metadata"]["retriever"] == "hybrid_bm25_fallback_small2big"
    assert context["metadata"]["small2big"]["enabled"] is True
    assert any(row["field"] == RAG_PARENT_PROFILE_FIELD for row in context["evidence"])


def test_hybrid_retriever_falls_back_to_bm25_when_vector_backend_fails(tmp_path):
    db = tmp_path / "rag.sqlite"
    build_sqlite_bm25_index(
        db,
        [
            {"parent_asin": "i1", "title": "Bluetooth audio speaker", "main_category": "Audio"},
            {"parent_asin": "i2", "title": "Desk lamp", "main_category": "Lighting"},
        ],
    )

    evidence = HybridCandidateRetriever(db, vector_backend=FailingVectorBackend()).retrieve(
        "bluetooth audio",
        ["i1", "i2"],
        max_evidence_per_item=2,
    )

    assert evidence
    assert {row.item_id for row in evidence} <= {"i1", "i2"}
    assert {row.metadata.get("retriever") for row in evidence} == {"hybrid"}
    assert all(row.metadata.get("bm25_rank") is not None for row in evidence)
    assert all(row.metadata.get("vector_score") == 0.0 for row in evidence)


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
    assert RAG_PARENT_PROFILE_FIELD not in RAG_STANDARD_FIELDS


def test_parent_profile_manifest_gate_fails_closed_without_required_training_provenance():
    assert validate_parent_profile_manifest(None) == {"passed": False, "failure_reason": "missing_manifest"}
    assert validate_parent_profile_manifest({**_valid_small2big_manifest(), "no_holdout": False}) == {
        "passed": False,
        "failure_reason": "invalid_no_holdout",
    }
    assert validate_parent_profile_manifest({**_valid_small2big_manifest(), "source_hash": ""}) == {
        "passed": False,
        "failure_reason": "missing_source_hash",
    }
    assert validate_parent_profile_manifest({**_valid_small2big_manifest(), "source_manifest_path": "outputs/holdout/oracle_labels.json"}) == {
        "passed": False,
        "failure_reason": "forbidden_source_manifest_path",
    }
    assert validate_parent_profile_manifest(_valid_small2big_manifest()) == {"passed": True, "failure_reason": None}


def test_small2big_retriever_fails_closed_to_base_evidence_when_manifest_invalid():
    base = StaticEvidenceRetriever([RagEvidence("i1", "title", "camp kettle", "candidate_card", score=2.0)])
    retriever = Small2BigCandidateEvidenceRetriever(
        base,
        parent_records={"i1": {"parent_asin": "i1", "title": "camp kettle", "description": "full parent profile"}},
        manifest=None,
    )

    evidence = retriever.retrieve("camp kettle", ["i1"], max_evidence_per_item=1)

    assert [(row.item_id, row.field) for row in evidence] == [("i1", "title")]
    assert evidence[0].metadata["small2big"] == {"passed": False, "failure_reason": "missing_manifest"}


def test_small2big_retriever_backfills_parent_profile_for_base_hit_candidate_only():
    base = StaticEvidenceRetriever(
        [
            RagEvidence("i1", "features", "compact titanium camping handle", "candidate_card", score=4.0),
            RagEvidence("i2", "title", "unmatched lamp", "candidate_card", score=1.0),
        ]
    )
    retriever = Small2BigCandidateEvidenceRetriever(
        base,
        parent_records={
            "i1": {
                "parent_asin": "i1",
                "title": "Titanium camp kettle",
                "categories_path": ["Sports", "Camping"],
                "store": "TrailCo",
                "features_text": {"public": "Lightweight body. Folding handle.", "holdout_label": "must not leak"},
                "description_text": {"summary": "Boils water quickly for backpacking.", "full_text": "raw nested full text"},
                "holdout_label": "must not leak",
                "item_text": "raw full text is not allowlisted by default",
            },
            "i3": {"parent_asin": "i3", "title": "outside item"},
        },
        manifest=_valid_small2big_manifest(),
    )

    evidence = retriever.retrieve("camp kettle", ["i1", "i2"], max_evidence_per_item=2)

    parent_rows = [row for row in evidence if row.field == RAG_PARENT_PROFILE_FIELD]
    assert len(parent_rows) == 1
    parent = parent_rows[0]
    assert parent.item_id == "i1"
    assert "Titanium camp kettle" in parent.text
    assert "holdout_label" not in parent.text
    assert "must not leak" not in parent.text
    assert "raw full text" not in parent.text
    assert parent.metadata["candidate_scoped"] is True
    assert parent.metadata["candidate_generation_allowed"] is False
    assert parent.metadata["ranking_input_replacement_allowed"] is False
    assert parent.metadata["promotion_allowed"] is False
    assert parent.metadata["direct_recommendation_input_allowed"] is False
    assert parent.metadata["requires_parent_context_agent"] is True
    assert parent.metadata["parent_projection_fields"] == ["title", "category_path", "store", "features", "description"]
    assert parent.metadata["small2big"]["profile_added_count"] == 1
    assert {row.item_id for row in evidence} <= {"i1", "i2"}


def test_small2big_retriever_respects_zero_parent_budget():
    base = StaticEvidenceRetriever([RagEvidence("i1", "title", "camp kettle", "candidate_card", score=2.0)])
    retriever = Small2BigCandidateEvidenceRetriever(
        base,
        parent_records={"i1": {"parent_asin": "i1", "title": "camp kettle", "description": "full parent profile"}},
        max_parent_profiles_total=0,
        manifest=_valid_small2big_manifest(),
    )

    evidence = retriever.retrieve("camp kettle", ["i1"], max_evidence_per_item=1)

    assert [(row.item_id, row.field) for row in evidence] == [("i1", "title")]
    assert evidence[0].metadata["small2big"]["profile_added_count"] == 0
    assert evidence[0].metadata["small2big"]["max_parent_profiles_total"] == 0


def test_rag_agent_support_filters_parent_profile_from_direct_evidence_text():
    turn = AgentTurn(
        turn_index=1,
        user_input="camping kettle",
        feedback_constraints=FeedbackConstraints(),
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="test",
            trigger_reason="test",
            agent_explanation="test",
            risk_flags=[],
            limitations=[],
            final_items=[],
        ),
        candidates=[],
        ranking=[],
        fallback_used=False,
        diagnostics={},
        rag_context={
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "title", "text": "Camping kettle", "metadata": {}},
                {
                    "item_id": "i1",
                    "field": RAG_PARENT_PROFILE_FIELD,
                    "text": "Parent profile should be handled by dedicated agent",
                    "metadata": {"requires_parent_context_agent": True, "direct_recommendation_input_allowed": False},
                },
            ]
        },
    )

    RagAgentAdapter().attach_shadow_report(turn)

    support = turn.diagnostics["rag_agent_support"]
    assert support["item_support"]["i1"] == [
        {"field": "title", "summary": "Camping kettle", "evidence_hint": "candidate-scoped title"},
        {
            "field": RAG_PARENT_PROFILE_FIELD,
            "summary": "商品级画像可用字段: parent_profile",
            "evidence_hint": "small2big parent profile compressed; raw text withheld",
        },
    ]
    assert "Parent profile should be handled by dedicated agent" not in str(support)


def test_small2big_context_policy_preserves_base_chunks_with_parent_budget_extension():
    base = StaticEvidenceRetriever(
        [
            RagEvidence("i1", "features", "backpacking kettle", "candidate_card", score=5.0),
            RagEvidence("i1", "description", "compact camping boil kit", "candidate_card", score=4.0),
        ]
    )
    retriever = Small2BigCandidateEvidenceRetriever(
        base,
        parent_records={"i1": {"parent_asin": "i1", "title": "Kettle", "description_text": "x" * 120}},
        parent_profile_max_chars=80,
        max_parent_profiles_total=1,
        base_max_evidence_per_item=2,
        manifest=_valid_small2big_manifest(),
    )

    context = build_rag_context_for_ranked_candidates(
        query="camping kettle",
        candidate_item_ids=["i1"],
        retriever=retriever,
        policy=RagPolicy(
            mode="explain",
            max_evidence_per_item=3,
            max_evidence_total=3,
            max_text_chars=30,
            allowed_fields=[*RAG_STANDARD_FIELDS, RAG_PARENT_PROFILE_FIELD],
        ),
    )

    assert [row.field for row in context.evidence].count(RAG_PARENT_PROFILE_FIELD) == 1
    assert {"features", "description"} <= {row.field for row in context.evidence}
    parent = next(row for row in context.evidence if row.field == RAG_PARENT_PROFILE_FIELD)
    assert parent.metadata["text_truncated"] is True
    assert context.metadata["rag_diagnostics"]["truncated_text_count"] == 1


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


def test_hybrid_candidate_retriever_uses_vector_backend_when_bm25_missing(tmp_path):
    evidence = HybridCandidateRetriever(
        tmp_path / "missing.sqlite",
        vector_backend=FakeVectorBackend(),
    ).retrieve("sofa", candidate_item_ids=["i1"], max_evidence_per_item=1)

    assert [(row.item_id, row.field, row.text, row.source) for row in evidence] == [("i1", "title", "vector-only sofa", "qdrant_vector")]
    assert evidence[0].metadata["retriever"] == "hybrid"
    assert evidence[0].metadata["vector_method"] == LOCAL_VECTOR_METHOD



def test_hybrid_candidate_retriever_uses_local_vector_index_when_bm25_missing(tmp_path):
    vector_index_path = tmp_path / "rag.vector.pkl"
    build_local_vector_index(
        vector_index_path,
        [{"parent_asin": "i1", "title": "soft red sofa seat"}],
        fields=["title"],
        vector_method="tfidf",
    )

    evidence = HybridCandidateRetriever(
        tmp_path / "missing.sqlite",
        vector_index_path=vector_index_path,
    ).retrieve("sofa", candidate_item_ids=["i1"], max_evidence_per_item=1)

    assert evidence
    assert [(row.item_id, row.field) for row in evidence] == [("i1", "title")]
    assert evidence[0].metadata["retriever"] == "hybrid"
    assert evidence[0].metadata["vector_method"] == LOCAL_VECTOR_METHOD



def test_hybrid_candidate_retriever_uses_vector_backend_when_bm25_invalid(tmp_path):
    index_path = tmp_path / "broken.sqlite"
    index_path.write_text("not sqlite", encoding="utf-8")

    evidence = HybridCandidateRetriever(
        index_path,
        vector_backend=FakeVectorBackend(),
    ).retrieve("sofa", candidate_item_ids=["i1"], max_evidence_per_item=1)

    assert [(row.item_id, row.field, row.text) for row in evidence] == [("i1", "title", "vector-only sofa")]
    assert evidence[0].metadata["retriever"] == "hybrid"



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
    assert context["metadata"]["retriever"] == "hybrid_bm25_fallback"
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
