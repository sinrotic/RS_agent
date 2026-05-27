from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.recsys.candidate_merge import (
    load_category_candidates,
    load_itemcf_by_source,
    load_popular_candidates,
    load_semantic_index,
)
from rs_core.workflow.hybrid_demo import (
    ROOT,
    _ensure_inputs,
    _itemcf_seed_items,
    _leave_one_positive_out_sequences,
    _load_item_category,
    _required_paths,
    recommend_for_user,
)
from rs_core.common.io import read_jsonl
from rs_core.display.builder import item_to_display_card
from rs_core.recsys.rag import (
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    build_rag_context_for_ranked_candidates,
)
from rs_core.rsagent.dialogue import apply_dialogue_plan, plan_dialogue_turn
from rs_core.rsagent.inference_policy import RerankPolicyClient
from rs_core.rsagent.policy import merge_feedback, normalize_feedback_input, parse_feedback
from rs_core.rsagent.runtime import AgentRuntime
from rs_core.rsagent.schema import AgentSession, AgentTurn


class HybridRecommendationEnvironment:
    def __init__(
        self,
        config: dict[str, Any],
        config_path: str | Path,
        train_sequences: list[dict[str, Any]],
        popular: list[Any],
        itemcf_weak: dict[str, list[Any]],
        itemcf_strong: dict[str, list[Any]],
        category_top: dict[str, list[Any]],
        item_category: dict[str, str],
        semantic_index: dict[str, dict[str, Any]],
        holdout_records: list[dict[str, Any]],
        inference_client: RerankPolicyClient | None = None,
    ) -> None:
        self.config = config
        self.config_path = str(config_path)
        self.train_sequences = train_sequences
        self.sequences_by_user = {sequence.get("user_id", ""): sequence for sequence in train_sequences}
        self.popular = popular
        self.itemcf_weak = itemcf_weak
        self.itemcf_strong = itemcf_strong
        self.category_top = category_top
        self.item_category = item_category
        self.semantic_index = semantic_index
        self.holdout_records = holdout_records
        self.inference_client = inference_client
        self.runtime = AgentRuntime()

    @classmethod
    def from_config(
        cls,
        config_path: str | Path,
        limit_users: int | None = None,
        inference_client: RerankPolicyClient | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> HybridRecommendationEnvironment:
        config = load_config(config_path)
        if config_overrides:
            config = _merge_nested(config, config_overrides)
        clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
        views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
        paths = _required_paths(clean_dir, views_dir)
        if config.get("semantic_enabled"):
            paths["semantic"] = views_dir / "semantic_recall_inputs.jsonl"
        _ensure_inputs(paths)
        train_sequences = read_jsonl(paths["sequences"])
        if limit_users is not None:
            train_sequences = train_sequences[:limit_users]
        holdout_records: list[dict[str, Any]] = []
        evaluation_mode = str(config.get("evaluation_mode", "valid_test"))
        if evaluation_mode == "leave_one_positive_out":
            train_sequences, holdout_records, _ = _leave_one_positive_out_sequences(train_sequences)
        elif evaluation_mode != "valid_test":
            raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode}")
        itemcf_seed_items = _itemcf_seed_items(train_sequences)
        popular = load_popular_candidates(paths["popular"], limit=int(config.get("popular_fallback_count", 50)))
        itemcf_weak = load_itemcf_by_source(paths["itemcf_weak"], "itemcf_weak", itemcf_seed_items)
        itemcf_strong = load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items)
        category_top = load_category_candidates(paths["category_top"])
        item_category = _load_item_category(paths["category_items"])
        semantic_index = load_semantic_index(paths["semantic"], config.get("semantic_text_fields")) if config.get("semantic_enabled") else {}
        if evaluation_mode == "valid_test":
            for split_name in ("valid", "test"):
                path = clean_dir / f"canonical_interactions.{split_name}.jsonl"
                if path.exists():
                    holdout_records.extend(read_jsonl(path))
        return cls(
            config,
            config_path,
            train_sequences,
            popular,
            itemcf_weak,
            itemcf_strong,
            category_top,
            item_category,
            semantic_index,
            holdout_records,
            inference_client,
        )

    def list_users(self) -> list[str]:
        return [sequence.get("user_id", "") for sequence in self.train_sequences if sequence.get("user_id")]

    def start_session(self, user_id: str | None = None, session_id: str | None = None) -> AgentSession:
        selected = user_id or self.list_users()[0]
        if selected not in self.sequences_by_user:
            raise ValueError(f"Unknown user_id: {selected}")
        return AgentSession(session_id=session_id or f"agent-{selected}", user_id=selected)

    def step(self, session: AgentSession, user_input: str = "") -> AgentTurn:
        return self._recommendation_step(session, user_input)

    def converse(self, session: AgentSession, user_input: str = "", explanation_item_id: str | None = None) -> AgentTurn:
        user_input = normalize_feedback_input(user_input) if user_input else ""
        return self.runtime.run_turn(self, session, user_input, explanation_item_id)

    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None = None) -> Any:
        return plan_dialogue_turn(user_input, session, explanation_item_id=explanation_item_id)

    def apply_dialogue_plan(self, session: AgentSession, plan: Any) -> Any:
        return apply_dialogue_plan(session, plan)

    def build_recommendation_turn(
        self,
        session: AgentSession,
        user_input: str,
        assistant_response: str,
        merge_user_input: bool,
    ) -> AgentTurn:
        return self._recommendation_step(session, user_input, assistant_response, merge_user_input=merge_user_input)

    def build_dialogue_turn(self, session: AgentSession, user_input: str, assistant_response: str) -> AgentTurn:
        return self._dialogue_only_turn(session, user_input, assistant_response)

    def _recommendation_step(
        self,
        session: AgentSession,
        user_input: str = "",
        assistant_response: str = "",
        merge_user_input: bool = True,
    ) -> AgentTurn:
        if user_input:
            user_input = normalize_feedback_input(user_input)
        parsed = parse_feedback(user_input) if user_input else session.active_constraints
        if user_input and merge_user_input:
            session.active_constraints = merge_feedback(session.active_constraints, parsed)
        sequence = self.sequences_by_user[session.user_id]
        result = recommend_for_user(
            sequence,
            self.popular,
            self.itemcf_weak,
            self.itemcf_strong,
            self.category_top,
            self.item_category,
            self.config,
            semantic_index=self.semantic_index,
            feedback_constraints=session.active_constraints,
            prior_turn_items=session.prior_turn_items(),
            inference_client=self.inference_client,
            turn_index=len(session.turns) + 1,
        )
        candidates = [asdict(candidate) for candidate in result.candidates]
        rag_context = _build_turn_rag_context(self.config, user_input, result.ranking.items, result.decision.final_items)
        diagnostics = dict(result.diagnostics)
        if rag_context is not None:
            diagnostics["rag"] = _rag_diagnostics(rag_context)
        turn = AgentTurn(
            turn_index=len(session.turns) + 1,
            user_input=user_input,
            feedback_constraints=session.active_constraints,
            recommendation=result.decision,
            candidates=candidates,
            ranking=result.ranking.items,
            fallback_used=result.fallback_used,
            diagnostics=diagnostics,
            rag_context=rag_context,
            assistant_response=assistant_response or result.decision.agent_explanation,
        )
        session.turns.append(turn)
        return turn

    def _dialogue_only_turn(self, session: AgentSession, user_input: str, assistant_response: str) -> AgentTurn:
        from rs_core.recsys.types import AgentDecision

        turn = AgentTurn(
            turn_index=len(session.turns) + 1,
            user_input=user_input,
            feedback_constraints=session.active_constraints,
            recommendation=AgentDecision(
                user_id=session.user_id,
                strategy_name=str(self.config.get("strategy_name", "phase_1_5_deterministic_hybrid_demo")),
                trigger_reason="clarification_needed",
                agent_explanation=assistant_response,
                risk_flags=[],
                limitations=["Dialogue-only turn; no new recommendation was produced."],
                final_items=[],
            ),
            candidates=[],
            ranking=[],
            fallback_used=False,
            diagnostics={},
            assistant_response=assistant_response,
        )
        session.turns.append(turn)
        return turn


def _build_turn_rag_context(
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
    fields = list(rag_config.get("fields", ["title", "category", "description", "summary"]))
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
            bm25_weight=float(hybrid_config.get("bm25_weight", 0.65)),
            vector_weight=float(hybrid_config.get("vector_weight", 0.35)),
            vector_dim=int(hybrid_config.get("vector_dim", 256)),
            vector_top_k_multiplier=int(hybrid_config.get("vector_top_k_multiplier", 4)),
        )
        retriever_name = "hybrid"
    elif index_path is not None and index_path.exists() and retriever_config != "in_memory_candidate_card":
        retriever = SQLiteBM25CandidateRetriever(index_path)
        retriever_name = "sqlite_bm25"
    context = build_rag_context_for_ranked_candidates(
        query=query,
        candidate_item_ids=candidate_item_ids,
        retriever=retriever,
        policy=RagPolicy(mode=mode, max_evidence_per_item=max_evidence_per_item, allowed_fields=fields),
        metadata={"evidence_mode": mode, "retriever": retriever_name},
    )
    return context.to_dict()


def _rag_index_path(rag_config: dict[str, Any]) -> Path | None:
    value = rag_config.get("index_path") or rag_config.get("bm25_index_path")
    if not value:
        return None
    return _resolve_path(value)


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



def _rag_diagnostics(rag_context: dict[str, Any]) -> dict[str, Any]:
    metadata = rag_context.get("metadata") if isinstance(rag_context.get("metadata"), dict) else {}
    diagnostics = metadata.get("rag_diagnostics") if isinstance(metadata.get("rag_diagnostics"), dict) else {}
    return {
        "evidence_mode": metadata.get("evidence_mode"),
        "kept_evidence_count": diagnostics.get("kept_evidence_count", 0),
        "dropped_non_candidate_evidence_count": diagnostics.get("dropped_non_candidate_evidence_count", 0),
        "dropped_policy_violation_count": diagnostics.get("dropped_policy_violation_count", 0),
    }



def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged
