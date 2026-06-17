from __future__ import annotations

from pathlib import Path
from typing import Any

from rs_core.common.io import read_json
from rs_core.display.builder import item_to_display_card
from rs_core.recsys.rag import RAG_STANDARD_FIELDS
from rs_core.recsys.rag import (
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    build_rag_context_for_ranked_candidates,
)
from rs_core.rsagent.runtime import AgentRuntime, AgentRuntimeHost
from rs_core.rsagent.schema import AgentSession, AgentTurn
from rs_core.workflow.hybrid_demo import ROOT


class AgentOrchestrationFacade:
    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    def run_turn(
        self,
        host: AgentRuntimeHost,
        session: AgentSession,
        user_input: str = "",
        explanation_item_id: str | None = None,
    ) -> AgentTurn:
        return self.runtime.run_turn(host, session, user_input, explanation_item_id)


class EvidenceRAGFacade:
    def build_turn_rag_context(
        self,
        config: dict[str, Any],
        query: str,
        ranked_items: list[dict[str, Any]],
        final_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        rag_config = config.get("rag") if isinstance(config.get("rag"), dict) else {}
        mode = str(rag_config.get("evidence_mode", "off"))
        if mode not in {"shadow", "explain"}:
            return None
        max_evidence_per_item = int(rag_config.get("max_evidence_per_item", 3) or 3)
        max_evidence_total = int(rag_config.get("max_evidence_total", 12) or 12)
        max_text_chars = int(rag_config.get("max_text_chars", rag_config.get("max_evidence_text_chars", 180)) or 180)
        fields = _string_list(rag_config.get("fields")) or list(RAG_STANDARD_FIELDS)
        item_cards = _display_safe_item_cards([*ranked_items, *final_items])
        candidate_item_ids = [item_id for item_id in _ranked_item_ids(ranked_items) if item_id in item_cards]
        retriever_name = "in_memory_candidate_card"
        retriever = InMemoryCandidateCardRetriever(item_cards, fields=fields)
        retriever_config = str(rag_config.get("retriever", "")).strip().lower()
        index_path = _rag_index_path(rag_config)
        if index_path is not None and index_path.exists() and retriever_config == "hybrid":
            hybrid_config = rag_config.get("hybrid") if isinstance(rag_config.get("hybrid"), dict) else {}
            retriever = HybridCandidateRetriever(
                index_path,
                vector_index_path=_rag_vector_index_path(rag_config, index_path),
                bm25_weight=float(hybrid_config.get("bm25_weight", 0.65)),
                vector_weight=float(hybrid_config.get("vector_weight", 0.35)),
                vector_dim=int(hybrid_config.get("vector_dim", 256)),
                vector_top_k_multiplier=int(hybrid_config.get("vector_top_k_multiplier", 4)),
                fusion_method=str(hybrid_config.get("fusion_method", "weighted")),
                rrf_k=int(hybrid_config.get("rrf_k", 60)),
                field_weights=_field_weights(hybrid_config.get("field_weights")),
            )
            retriever_name = "hybrid"
        elif index_path is not None and index_path.exists() and retriever_config != "in_memory_candidate_card":
            retriever = SQLiteBM25CandidateRetriever(index_path)
            retriever_name = "sqlite_bm25"
        context = build_rag_context_for_ranked_candidates(
            query=query,
            candidate_item_ids=candidate_item_ids,
            retriever=retriever,
            policy=RagPolicy(
                mode=mode,
                max_evidence_per_item=max_evidence_per_item,
                max_evidence_total=max_evidence_total,
                max_text_chars=max_text_chars,
                allowed_fields=fields,
            ),
            metadata={"evidence_mode": mode, "retriever": retriever_name},
        )
        return context.to_dict()


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _rag_index_path(rag_config: dict[str, Any]) -> Path | None:
    value = rag_config.get("index_path") or rag_config.get("bm25_index_path")
    if not value:
        return None
    return _resolve_path(value)


def _field_weights(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    return {str(field): float(weight) for field, weight in value.items()}


def _rag_vector_index_path(rag_config: dict[str, Any], index_path: Path) -> Path | None:
    value = rag_config.get("vector_index_path")
    if value:
        path = _resolve_path(value)
        return path if path.exists() else None

    manifest_value = rag_config.get("manifest_path") or rag_config.get("index_manifest_path")
    manifest_path = _resolve_path(manifest_value) if manifest_value else index_path.with_suffix(index_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        return None
    manifest = read_json(manifest_path)
    vector_index_path = manifest.get("vector_index_path")
    if not vector_index_path:
        return None
    path = _resolve_path(vector_index_path)
    return path if path.exists() else None


def _display_safe_item_cards(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    for item in items:
        card = item_to_display_card(item)
        if card:
            cards[card.parent_asin] = card.to_dict()
    return cards


def _ranked_item_ids(items: list[dict[str, Any]]) -> list[str]:
    item_ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("parent_asin") or item.get("item_id") or "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)
    return item_ids


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path
