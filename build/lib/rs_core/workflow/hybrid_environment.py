from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from time import perf_counter
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
from rs_core.common.io import read_json, read_jsonl
from rs_core.display.builder import build_display_record, item_to_display_card, validate_public_display_payload
from rs_core.recsys.rag import RAG_STANDARD_FIELDS
from rs_core.recsys.semantic_description import (
    DEFAULT_DOCUMENT_COUNT,
    SemanticDescriptionRecallEngine,
    retrieve_fixture_results,
    tokens,
)
from rs_core.recsys.types import MergedCandidate
from rs_core.rsagent.tools import (
    AgentToolCall,
    AgentToolExecutionReport,
    AgentToolResult,
    AgenticRecallRequest,
    CategoryConstraint,
    DeepFMRankRequest,
    KeywordConstraint,
    ProductSearchRequest,
    RecallPathPlan,
    UnderstandUserNeedOutput,
    agentic_recall_candidates,
    catalog_constraint_search,
    deepfm_rank_candidates,
    get_agent_tool_spec,
    normalize_agent_tool_calls,
    validate_agent_tool_call,
)
from rs_core.recsys.rag import (
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    build_rag_context_for_ranked_candidates,
)
from rs_core.rsagent.context import ContextBudget, build_context_bundle
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
        item_metadata: dict[str, dict[str, Any]],
        semantic_index: dict[str, dict[str, Any]],
        holdout_records: list[dict[str, Any]],
        inference_client: RerankPolicyClient | None = None,
        semantic_live_engine: SemanticDescriptionRecallEngine | None = None,
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
        self.item_metadata = item_metadata
        self.semantic_index = semantic_index
        self.semantic_live_engine = semantic_live_engine
        self.semantic_live_cache: dict[str, Any] = {}
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
        evaluation_mode = config.get("evaluation_mode")
        evaluation_mode = str(evaluation_mode) if evaluation_mode not in (None, "") else "public_serving"
        if evaluation_mode == "none":
            evaluation_mode = "public_serving"
        if evaluation_mode == "leave_one_positive_out":
            train_sequences, holdout_records, _ = _leave_one_positive_out_sequences(train_sequences)
        elif evaluation_mode not in {"valid_test", "public_serving"}:
            raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode}")
        itemcf_seed_items = _itemcf_seed_items(train_sequences)
        popular = load_popular_candidates(paths["popular"], limit=int(config.get("popular_fallback_count", 50)))
        itemcf_weak = load_itemcf_by_source(paths["itemcf_weak"], "itemcf_weak", itemcf_seed_items)
        itemcf_strong = load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items)
        category_top = load_category_candidates(paths["category_top"])
        item_category = _load_item_category(paths["category_items"])
        item_metadata = _load_item_metadata(paths["category_items"], clean_dir / "canonical_items.jsonl")
        semantic_index = load_semantic_index(paths["semantic"], config.get("semantic_text_fields")) if config.get("semantic_enabled") else {}
        semantic_live_engine = _build_semantic_live_engine(config)
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
            item_metadata,
            semantic_index,
            holdout_records,
            inference_client,
            semantic_live_engine,
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

    def execute_agent_tools(
        self,
        session: AgentSession,
        plan: Any,
        phase: str,
        turn: AgentTurn | None = None,
    ) -> dict[str, Any]:
        calls = [call for call in _planned_tool_calls(plan) if not call.phase or call.phase == phase]
        results = [self._execute_agent_tool_call(session, plan, phase, turn, call) for call in calls]
        summary = {
            "supported": True,
            "phase": phase,
            "requested_count": len(calls),
            "result_count": len(results),
            "executed_count": sum(1 for result in results if result.status == "ok"),
            "skipped_count": sum(1 for result in results if result.status == "skipped"),
            "error_count": sum(1 for result in results if result.status == "error"),
        }
        return AgentToolExecutionReport(phase=phase, results=results, summary=summary).to_dict()

    def _execute_agent_tool_call(
        self,
        session: AgentSession,
        plan: Any,
        phase: str,
        turn: AgentTurn | None,
        call: AgentToolCall,
    ) -> AgentToolResult:
        reason = validate_agent_tool_call(call, str(getattr(plan, "intent", "")), phase)
        if reason is not None:
            return _tool_result(call.name, phase, "skipped", reason=reason)
        spec = get_agent_tool_spec(call.name)
        if spec and spec.requires_candidate_pool and not _turn_candidate_item_ids(_source_turn(session, turn)):
            return _tool_result(call.name, phase, "skipped", reason="empty_candidate_pool")
        try:
            return self._dispatch_agent_tool_call(session, plan, phase, turn, call)
        except Exception as exc:
            return _tool_result(
                call.name,
                phase,
                "error",
                error_type=type(exc).__name__,
                message=str(exc),
            )

    def _dispatch_agent_tool_call(
        self,
        session: AgentSession,
        plan: Any,
        phase: str,
        turn: AgentTurn | None,
        call: AgentToolCall,
    ) -> AgentToolResult:
        if call.name == "get_user_context":
            return _tool_result(call.name, phase, "ok", output=_get_user_context_output(session, call))
        if call.name == "retrieve_candidates":
            semantic_output = self._semantic_live_retrieve_candidates(call, session, turn)
            if semantic_output is not None:
                return _tool_result(call.name, phase, "ok", output=semantic_output)
            online_recommender = getattr(self, "online_recommender", None)
            if online_recommender is not None and online_recommender.readiness().get("complete_pool500_available"):
                sequence = self.sequences_by_user[session.user_id]
                output = online_recommender.tool_retrieve_candidates(
                    sequence,
                    prior_turn_items=session.prior_turn_items(),
                    candidate_pool_size=int(call.arguments.get("limit") or self.config.get("candidate_pool_size", 50)),
                )
                return _tool_result(call.name, phase, "ok", output=output)
            request = _agentic_recall_request_from_call(call, session, turn)
            output = agentic_recall_candidates(request, self._tool_catalog_items(), session.prior_turn_items()).to_dict()
            return _tool_result(call.name, phase, "ok", output=_retrieve_candidates_output(output))
        if call.name == "rank_candidates":
            online_recommender = getattr(self, "online_recommender", None)
            if online_recommender is not None and online_recommender.readiness().get("complete_pool500_available"):
                output = online_recommender.tool_rank_candidates(turn, return_top_k=call.arguments.get("return_top_k"))
                return _tool_result(call.name, phase, "ok", output=output)
            request = _deepfm_rank_request_from_call(call, session, turn)
            output = deepfm_rank_candidates(request).to_dict()
            return _tool_result(call.name, phase, "ok", output=_rank_candidates_output(output))
        if call.name == "get_item_evidence":
            output = _get_item_evidence_output(session, turn, call)
            return _tool_result(call.name, phase, "ok", output=output)
        if call.name == "record_user_feedback":
            output = _record_user_feedback_output(session, call)
            return _tool_result(call.name, phase, "ok", output=output)
        if call.name == "build_recommendation_slate":
            output = _build_recommendation_slate_output(session, turn, call)
            return _tool_result(call.name, phase, "ok", output=output)
        if call.name == "understand_user_need":
            output = UnderstandUserNeedOutput(
                intent=str(getattr(plan, "intent", "")),
                action=str(getattr(plan, "action", "")),
                constraints=session.active_constraints.to_dict(),
                needs_clarification=bool(session.conversation_state.pending_clarification),
                clarification_question=session.conversation_state.pending_clarification or None,
                confidence=1.0,
            ).to_dict()
            return _tool_result(call.name, phase, "ok", output=output)
        if call.name == "catalog_constraint_search":
            request = _product_search_request_from_call(call, session, turn, force_candidate_pool=False)
            output = catalog_constraint_search(request, self._tool_catalog_items(), session.prior_turn_items()).to_dict()
            return _tool_result(call.name, phase, "ok", output=_compact_catalog_output(output))
        if call.name == "agentic_recall_candidates":
            request = _agentic_recall_request_from_call(call, session, turn)
            output = agentic_recall_candidates(request, self._tool_catalog_items(), session.prior_turn_items()).to_dict()
            return _tool_result(call.name, phase, "ok", output=_compact_agentic_recall_output(output))
        if call.name == "deepfm_rank_candidates":
            request = _deepfm_rank_request_from_call(call, session, turn)
            output = deepfm_rank_candidates(request).to_dict()
            return _tool_result(call.name, phase, "ok", output=_compact_deepfm_output(output))
        if call.name == "match_specific_need_in_pool":
            candidate_pool = _turn_candidate_item_ids(turn)
            if not candidate_pool:
                return _tool_result(call.name, phase, "skipped", reason="empty_candidate_pool")
            request = _product_search_request_from_call(call, session, turn, force_candidate_pool=True)
            output = catalog_constraint_search(request, self._tool_catalog_items(), session.prior_turn_items()).to_dict()
            return _tool_result(call.name, phase, "ok", output=_compact_catalog_output(output))
        if call.name == "rerank_for_browsing":
            output = {
                "candidate_count": len(turn.candidates) if turn else 0,
                "ranking_count": len(turn.ranking) if turn else 0,
                "applied": False,
            }
            return _tool_result(call.name, phase, "ok", output=output)
        if call.name == "build_product_reasoning":
            final_items = turn.recommendation.final_items if turn else []
            output = {
                "item_ids": _item_ids(final_items),
                "item_count": len(final_items),
                "has_rag_context": bool(turn and turn.rag_context),
            }
            return _tool_result(call.name, phase, "ok", output=output)
        if call.name == "compose_shopping_response":
            output = {
                "display_item_count": len(turn.recommendation.final_items) if turn else 0,
                "public_builder_required": True,
            }
            return _tool_result(call.name, phase, "ok", output=output)
        return _tool_result(call.name, phase, "skipped", reason="unimplemented_tool")

    def _semantic_live_retrieve_candidates(
        self,
        call: AgentToolCall,
        session: AgentSession,
        turn: AgentTurn | None,
    ) -> dict[str, Any] | None:
        if self.semantic_live_engine is None:
            return None
        query = str(call.arguments.get("query") or getattr(turn, "user_input", "") or "").strip()
        if not query:
            return None
        limit = max(1, int(call.arguments.get("limit", call.arguments.get("top_k", 50)) or 50))
        result = self._run_semantic_live_query(query, limit=limit, exclude_item_ids=session.prior_turn_items())
        if not result.get("candidate_item_ids"):
            return None
        self.semantic_live_cache[session.session_id] = result
        return {
            "candidate_item_ids": result["candidate_item_ids"],
            "candidate_count": len(result["candidate_item_ids"]),
            "retrieval_summary": {
                "target_pool_size": limit,
                "path_count": 1,
            },
            "diagnostics": {"compact": True},
        }

    def _run_semantic_live_query(
        self,
        query: str,
        *,
        limit: int,
        exclude_item_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        if self.semantic_live_engine is None:
            return {"candidate_item_ids": [], "candidates": [], "latency_ms": 0.0}
        exclude_item_ids = exclude_item_ids or set()
        config = self.semantic_live_engine.config
        fixture = _semantic_live_fixture(query)
        started_at = perf_counter()
        results, _ = retrieve_fixture_results(
            fixtures=[fixture],
            semantic_inputs_path=config.semantic_inputs_path,
            inverted_index_path=config.inverted_index_path,
            per_token_limit=config.per_token_limit,
            candidate_limit=config.candidate_limit,
            document_count=config.document_count,
            store=self.semantic_live_engine.store,
        )
        latency_ms = round((perf_counter() - started_at) * 1000, 3)
        rows = results[0].rows if results else []
        candidates: list[MergedCandidate] = []
        candidate_ids: list[str] = []
        for rank, row in enumerate(rows, start=1):
            if row.item_id in exclude_item_ids:
                continue
            metadata = _semantic_live_metadata(row.record, rank, row.details)
            self.item_metadata[row.item_id] = {**metadata, **self.item_metadata.get(row.item_id, {})}
            candidates.append(MergedCandidate(
                item_id=row.item_id,
                sources=["semantic_live"],
                source_scores={"semantic_live": float(row.score)},
                category=str(row.record.get("main_category") or row.record.get("category") or ""),
                metadata=metadata,
            ))
            candidate_ids.append(row.item_id)
            if len(candidates) >= limit:
                break
        return {
            "candidate_item_ids": candidate_ids,
            "candidates": candidates,
            "query": query,
            "latency_ms": latency_ms,
            "candidate_pool_size": len(results[0].candidate_ids) if results else 0,
            "scored_count": len(rows),
            "governance": {
                "label_inputs_role": "not_used",
                "oracle_label_injection": False,
                "ranking_input_replacement_allowed": False,
                "promotion_allowed": False,
            },
        }

    def _tool_catalog_items(self) -> dict[str, dict[str, Any]]:
        return {item_id: {"parent_asin": item_id, **metadata} for item_id, metadata in self.item_metadata.items()}

    def build_recommendation_turn(
        self,
        session: AgentSession,
        user_input: str,
        assistant_response: str,
        merge_user_input: bool,
    ) -> AgentTurn:
        return self._recommendation_step(session, user_input, assistant_response, merge_user_input=merge_user_input)

    def enrich_display_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _enrich_items(items, self.item_metadata)

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
        semantic_live_result = self.semantic_live_cache.pop(session.session_id, None)
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
            extra_candidates=semantic_live_result.get("candidates") if isinstance(semantic_live_result, dict) else None,
        )
        result.ranking.items = _enrich_items(result.ranking.items, self.item_metadata)
        result.decision.final_items = _enrich_items(result.decision.final_items, self.item_metadata)
        candidates = [asdict(candidate) for candidate in result.candidates]
        rag_context = _build_turn_rag_context(self.config, user_input, result.ranking.items, result.decision.final_items)
        diagnostics = dict(result.diagnostics)
        if semantic_live_result:
            diagnostics["semantic_live_retrieval"] = {
                "enabled": True,
                "candidate_count": len(semantic_live_result.get("candidate_item_ids", [])),
                "candidate_pool_size": semantic_live_result.get("candidate_pool_size"),
                "scored_count": semantic_live_result.get("scored_count"),
                "latency_ms": semantic_live_result.get("latency_ms"),
                "governance": semantic_live_result.get("governance", {}),
            }
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


def _build_semantic_live_engine(config: dict[str, Any]) -> SemanticDescriptionRecallEngine | None:
    semantic_config = config.get("semantic_description_live")
    if not isinstance(semantic_config, dict):
        semantic_config = config.get("semantic_live") if isinstance(config.get("semantic_live"), dict) else {}
    if not semantic_config.get("enabled"):
        return None
    semantic_inputs = _resolve_path(
        semantic_config.get("semantic_inputs_path")
        or "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_recall_inputs.jsonl"
    )
    inverted_index = _resolve_path(
        semantic_config.get("inverted_index_path")
        or "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_inverted_index.jsonl"
    )
    sqlite_value = semantic_config.get("sqlite_index_path")
    sqlite_index = _resolve_path(sqlite_value) if sqlite_value else None
    return SemanticDescriptionRecallEngine.from_paths(
        semantic_inputs_path=semantic_inputs,
        inverted_index_path=inverted_index,
        sqlite_index_path=sqlite_index,
        document_count=int(semantic_config.get("document_count", DEFAULT_DOCUMENT_COUNT) or DEFAULT_DOCUMENT_COUNT),
        per_token_limit=int(semantic_config.get("per_token_limit", 2_000) or 2_000),
        candidate_limit=int(semantic_config.get("candidate_limit", 1_000) or 1_000),
        top_k=int(semantic_config.get("top_k", 50) or 50),
    )


def _semantic_live_fixture(query: str) -> dict[str, Any]:
    core_terms = _default_semantic_core_terms(query)
    return {
        "id": "agent_live_query",
        "description": query,
        "core_terms": core_terms,
        "must_terms": [],
        "must_any_groups": [core_terms] if core_terms else [],
        "intent_phrases": [" ".join(core_terms)] if core_terms else [],
        "category_any": [],
        "negative_phrases": [],
    }


def _default_semantic_core_terms(query: str) -> list[str]:
    values: list[str] = []
    ignored = {"prefer", "like", "need", "want", "looking", "recommend", "suggest", "show", "please", "more"}
    for token in tokens(query):
        if token in ignored:
            continue
        if token not in values:
            values.append(token)
        if len(values) >= 2:
            break
    return values


def _semantic_live_metadata(record: dict[str, Any], rank: int, details: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "title_clean",
        "title",
        "main_category",
        "category",
        "categories_flat",
        "categories_path",
        "average_rating",
        "rating",
        "rating_number",
        "store",
        "brand",
        "price",
        "image_url",
        "description",
        "description_text",
        "features",
    )
    metadata = {key: record[key] for key in keys if record.get(key) not in (None, "", [])}
    metadata["semantic_live_rank"] = rank
    metadata["semantic_live_required_pass"] = bool(details.get("required_pass"))
    metadata["semantic_live_strict_intent_pass"] = bool(details.get("strict_intent_pass"))
    return metadata


def _get_user_context_output(session: AgentSession, call: AgentToolCall) -> dict[str, Any]:
    limit = int(call.arguments.get("include_recent_turns", 3) or 3)
    budget = ContextBudget(recent_turns=max(0, limit))
    bundle = build_context_bundle(session, budget)
    include_constraints = call.arguments.get("include_constraints", True) is not False
    return {
        "session_id": bundle.session_id,
        "user_id": bundle.user_id,
        "turn_count": bundle.turn_count,
        "current_goal": bundle.current_goal,
        "latest_intent": bundle.latest_intent,
        "latest_action": bundle.latest_action,
        "pending_clarification": bundle.pending_clarification,
        "active_constraints": bundle.active_constraints if include_constraints else {},
        "shown_item_ids": bundle.shown_item_ids,
        "liked_item_ids": bundle.user_profile.get("liked_item_ids", []),
        "disliked_item_ids": bundle.user_profile.get("disliked_item_ids", []),
        "recent_turns": bundle.recent_turns,
        "user_profile": bundle.user_profile,
        "archived_turn_summaries": bundle.archived_turn_summaries,
        "diagnostics": {"compact": True, "context_budget": bundle.diagnostics.get("budget", {})},
    }


def _retrieve_candidates_output(output: dict[str, Any]) -> dict[str, Any]:
    candidates = output.get("candidates", []) if isinstance(output.get("candidates"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    return {
        "candidate_item_ids": [str(candidate.get("item_id")) for candidate in candidates if candidate.get("item_id")],
        "candidate_count": len(candidates),
        "retrieval_summary": {
            "target_pool_size": diagnostics.get("target_pool_size"),
            "path_count": diagnostics.get("path_count"),
        },
        "diagnostics": {"compact": True},
    }


def _rank_candidates_output(output: dict[str, Any]) -> dict[str, Any]:
    ranked_items = output.get("ranked_items", []) if isinstance(output.get("ranked_items"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    return {
        "ranked_item_ids": [str(item.get("item_id")) for item in ranked_items if item.get("item_id")],
        "ranked_item_count": len(ranked_items),
        "ranking_summary": {
            "ranker": diagnostics.get("ranker"),
            "candidate_count": diagnostics.get("candidate_count", 0),
            "return_top_k": diagnostics.get("return_top_k"),
        },
        "diagnostics": {"compact": True},
    }


def _get_item_evidence_output(session: AgentSession, turn: AgentTurn | None, call: AgentToolCall) -> dict[str, Any]:
    source_turn = _source_turn(session, turn)
    requested_ids = _string_list(call.arguments.get("item_ids"))
    if not requested_ids:
        requested_ids = _turn_final_item_ids(source_turn) or _turn_candidate_item_ids(source_turn)
    max_per_item = max(1, int(call.arguments.get("max_evidence_per_item", 3) or 3))
    max_total = max(1, int(call.arguments.get("max_evidence_total", 12) or 12))
    max_text_chars = max(1, int(call.arguments.get("max_text_chars", call.arguments.get("max_evidence_text_chars", 180)) or 180))
    evidence = _rag_evidence_by_item(source_turn, requested_ids, max_per_item, max_total, max_text_chars)
    used_rag_context = bool(evidence)
    if not evidence:
        evidence = _display_card_evidence_by_item(source_turn, requested_ids, max_per_item, max_total, max_text_chars)
    evidence_count = sum(len(rows) for rows in evidence.values())
    return {
        "evidence": evidence,
        "item_count": len(evidence),
        "evidence_count": evidence_count,
        "diagnostics": {
            "compact": True,
            "source_turn_index": source_turn.turn_index if source_turn else None,
            "used_rag_context": used_rag_context,
            "budget": {
                "max_evidence_per_item": max_per_item,
                "max_evidence_total": max_total,
                "max_text_chars": max_text_chars,
                "retained_evidence_count": evidence_count,
            },
        },
    }


def _record_user_feedback_output(session: AgentSession, call: AgentToolCall) -> dict[str, Any]:
    feedback_text = normalize_feedback_input(str(call.arguments.get("feedback_text") or call.arguments.get("comment") or ""))
    action_type = str(call.arguments.get("action_type") or "").strip().lower()
    item_id = str(call.arguments.get("item_id") or "").strip()
    parts = [feedback_text]
    if item_id and action_type in {"like", "dislike"}:
        prefix = "like this item" if action_type == "like" else "dislike"
        parts.append(f"{prefix} item_id={item_id}")
    parsed = parse_feedback("; ".join(part for part in parts if part))
    before = session.active_constraints.to_dict()
    session.active_constraints = merge_feedback(session.active_constraints, parsed)
    return {
        "applied": session.active_constraints.to_dict() != before,
        "active_constraints": session.active_constraints.to_dict(),
        "feedback_event": {
            "action_type": action_type,
            "item_id": item_id or None,
            "parsed_event_count": len(parsed.item_feedback_events),
        },
        "diagnostics": {"compact": True},
    }


def _build_recommendation_slate_output(session: AgentSession, turn: AgentTurn | None, call: AgentToolCall) -> dict[str, Any]:
    source_turn = _source_turn(session, turn)
    if source_turn is None:
        return {"display": {}, "item_count": 0, "diagnostics": {"compact": True, "reason": "missing_turn"}}
    display = build_display_record(source_turn, session)
    max_items = call.arguments.get("max_items")
    if max_items is not None:
        display = {**display, "items": display.get("items", [])[: max(0, int(max_items))]}
    if call.arguments.get("include_items", True) is False:
        display = {**display, "items": []}
    display = validate_public_display_payload(display)
    return {
        "display": display,
        "item_count": len(display.get("items", [])),
        "diagnostics": {"compact": True, "public_safe": True},
    }


def _source_turn(session: AgentSession, turn: AgentTurn | None) -> AgentTurn | None:
    if turn and turn.recommendation.final_items:
        return turn
    for prior_turn in reversed(session.turns):
        if prior_turn.recommendation.final_items:
            return prior_turn
    return turn


def _turn_final_item_ids(turn: AgentTurn | None) -> list[str]:
    return _item_ids(turn.recommendation.final_items) if turn else []


def _rag_evidence_by_item(
    turn: AgentTurn | None,
    item_ids: list[str],
    max_per_item: int,
    max_total: int,
    max_text_chars: int,
) -> dict[str, list[dict[str, Any]]]:
    if not turn or not isinstance(turn.rag_context, dict):
        return {}
    allowed_ids = set(item_ids)
    evidence_by_item: dict[str, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids}
    retained = 0
    for row in turn.rag_context.get("evidence", []) or []:
        if retained >= max_total:
            break
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id") or "")
        if not item_id or (allowed_ids and item_id not in allowed_ids):
            continue
        bucket = evidence_by_item.setdefault(item_id, [])
        if len(bucket) >= max_per_item:
            continue
        bucket.append({
            "field": row.get("field"),
            "text": _truncate_text(row.get("text"), max_text_chars),
        })
        retained += 1
    return {item_id: rows for item_id, rows in evidence_by_item.items() if rows}


def _display_card_evidence_by_item(
    turn: AgentTurn | None,
    item_ids: list[str],
    max_per_item: int,
    max_total: int,
    max_text_chars: int,
) -> dict[str, list[dict[str, Any]]]:
    if turn is None:
        return {}
    cards = _display_safe_item_cards([*turn.recommendation.final_items, *turn.ranking])
    evidence: dict[str, list[dict[str, Any]]] = {}
    retained = 0
    for item_id in item_ids:
        if retained >= max_total:
            break
        card = cards.get(item_id)
        if not card:
            continue
        rows = []
        for field in ("title", "category", "store", "summary", "features", "description"):
            if retained >= max_total:
                break
            value = card.get(field)
            if value in (None, "", []):
                continue
            text = "; ".join(value) if isinstance(value, list) else str(value)
            rows.append({"field": field, "text": _truncate_text(text, max_text_chars)})
            retained += 1
            if len(rows) >= max_per_item:
                break
        if rows:
            evidence[item_id] = rows
    return evidence


def _planned_tool_calls(plan: Any) -> list[AgentToolCall]:
    calls = normalize_agent_tool_calls(getattr(plan, "tool_calls", []))
    diagnostics = getattr(plan, "diagnostics", {})
    if isinstance(diagnostics, dict):
        calls.extend(normalize_agent_tool_calls(diagnostics.get("tool_calls")))
        calls.extend(normalize_agent_tool_calls(diagnostics.get("requested_tools")))
    return calls


def _tool_result(
    name: str,
    phase: str,
    status: str,
    *,
    output: dict[str, Any] | None = None,
    reason: str = "",
    error_type: str = "",
    message: str = "",
) -> AgentToolResult:
    event = {
        "tool_name": name,
        "phase": phase,
        "status": status,
    }
    if reason:
        event["reason"] = reason
    return AgentToolResult(
        name=name,
        phase=phase,
        status=status,
        output=output or {},
        event=event,
        reason=reason,
        error_type=error_type,
        message=message[:240] if message else "",
    )


def _product_search_request_from_call(
    call: AgentToolCall,
    session: AgentSession,
    turn: AgentTurn | None,
    *,
    force_candidate_pool: bool,
) -> ProductSearchRequest:
    arguments = call.arguments
    constraints = session.active_constraints
    candidate_pool = _turn_candidate_item_ids(turn) if force_candidate_pool else _string_list(arguments.get("candidate_pool"))
    keywords = _string_list(arguments.get("keywords"))
    keywords.extend(constraints.preferred_keywords)
    required = _string_list(arguments.get("required"))
    disliked = _string_list(arguments.get("disliked"))
    disliked.extend(constraints.disliked_keywords)
    categories = _string_list(arguments.get("categories"))
    categories.extend(constraints.preferred_categories)
    not_categories = _string_list(arguments.get("not_categories"))
    not_categories.extend(constraints.disliked_categories)
    limit = int(arguments.get("limit", 10) or 10)
    return ProductSearchRequest(
        query=str(arguments.get("query") or getattr(turn, "user_input", "") or ""),
        keywords=KeywordConstraint(keywords=keywords, required=required, preferred=keywords, disliked=disliked),
        category=CategoryConstraint(categories=categories, not_categories=not_categories),
        limit=max(1, min(limit, 50)),
        candidate_pool=candidate_pool,
        reference_item_id=str(arguments.get("reference_item_id") or "") or None,
        similar_to_item_id=str(arguments.get("similar_to_item_id") or "") or None,
        target_item_id=str(arguments.get("target_item_id") or "") or None,
        exclude_seen_items=bool(arguments.get("exclude_seen_items", True)),
    )


def _agentic_recall_request_from_call(call: AgentToolCall, session: AgentSession, turn: AgentTurn | None) -> AgenticRecallRequest:
    arguments = call.arguments
    paths = [_recall_path_from_dict(path) for path in arguments.get("paths", []) if isinstance(path, dict)]
    if not paths:
        paths = [RecallPathPlan(
            name="constraint_catalog_search",
            limit=int(arguments.get("limit", 50) or 50),
            top_k=int(arguments.get("top_k", arguments.get("limit", 50)) or 50),
            query=str(arguments.get("query") or getattr(turn, "user_input", "") or ""),
            rules=_rules_from_active_constraints(session),
            reason="default_agentic_recall_from_session_constraints",
        )]
    return AgenticRecallRequest(
        user_id=session.user_id,
        session_id=session.session_id,
        target_pool_size=int(arguments.get("target_pool_size", 100) or 100),
        global_rules=dict(arguments.get("global_rules")) if isinstance(arguments.get("global_rules"), dict) else {"exclude_seen_items": True, "dedupe_by_parent_asin": True},
        paths=paths,
        ranking_context=dict(arguments.get("ranking_context")) if isinstance(arguments.get("ranking_context"), dict) else {"query": getattr(turn, "user_input", "") or ""},
    )


def _recall_path_from_dict(value: dict[str, Any]) -> RecallPathPlan:
    return RecallPathPlan(
        name=str(value.get("name") or value.get("path") or "constraint_catalog_search"),
        limit=int(value.get("limit", 50) or 50),
        top_k=int(value.get("top_k", value.get("limit", 50)) or 50),
        query=str(value.get("query") or ""),
        rules=list(value.get("rules")) if isinstance(value.get("rules"), list) else [],
        sources=_string_list(value.get("sources")),
        source_budgets={str(key): int(item) for key, item in value.get("source_budgets", {}).items()} if isinstance(value.get("source_budgets"), dict) else {},
        candidate_pool=_string_list(value.get("candidate_pool")),
        reference_item_id=str(value.get("reference_item_id") or "") or None,
        similar_to_item_id=str(value.get("similar_to_item_id") or "") or None,
        target_item_id=str(value.get("target_item_id") or "") or None,
        reason=str(value.get("reason") or ""),
    )


def _rules_from_active_constraints(session: AgentSession) -> list[dict[str, Any]]:
    constraints = session.active_constraints
    rules: list[dict[str, Any]] = []
    if constraints.preferred_categories:
        rules.append({"field": "category", "op": "in", "values": sorted(constraints.preferred_categories)})
    if constraints.preferred_keywords:
        rules.append({"field": "keyword", "op": "preferred", "values": sorted(constraints.preferred_keywords)})
    if constraints.disliked_keywords:
        rules.append({"field": "keyword", "op": "disliked", "values": sorted(constraints.disliked_keywords)})
    return rules


def _deepfm_rank_request_from_call(call: AgentToolCall, session: AgentSession, turn: AgentTurn | None) -> DeepFMRankRequest:
    arguments = call.arguments
    candidates = arguments.get("candidates") if isinstance(arguments.get("candidates"), list) else _deepfm_candidates_from_turn(turn)
    return DeepFMRankRequest(
        user_id=session.user_id,
        session_id=session.session_id,
        return_top_k=int(arguments.get("return_top_k", 20) or 20),
        ranking_context=dict(arguments.get("ranking_context")) if isinstance(arguments.get("ranking_context"), dict) else {"query": getattr(turn, "user_input", "") or ""},
        candidates=[candidate for candidate in candidates if isinstance(candidate, dict)],
    )


def _deepfm_candidates_from_turn(turn: AgentTurn | None) -> list[dict[str, Any]]:
    if turn is None:
        return []
    candidates = []
    for source_rank, item in enumerate([*turn.ranking, *turn.recommendation.final_items], start=1):
        item_id = str(item.get("parent_asin") or item.get("item_id") or "")
        if not item_id:
            continue
        candidates.append({
            "item_id": item_id,
            "acquisition_path": ",".join(str(source) for source in item.get("sources", [])) if isinstance(item.get("sources"), list) else str(item.get("source") or "hybrid_ranking"),
            "source_rank": source_rank,
            "source_score": float(item.get("score") or item.get("rank_score") or 1.0 / source_rank),
            "item_features": dict(item),
        })
    return candidates


def _truncate_text(value: Any, max_chars: int) -> str:
    text = "" if value in (None, "") else str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _turn_candidate_item_ids(turn: AgentTurn | None) -> list[str]:
    if turn is None:
        return []
    return list(dict.fromkeys([
        *_item_ids(turn.candidates),
        *_item_ids(turn.ranking),
        *_item_ids(turn.recommendation.final_items),
    ]))


def _item_ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("parent_asin") or item.get("item_id") or item.get("dst_item")) for item in items if item.get("parent_asin") or item.get("item_id") or item.get("dst_item")]


def _compact_catalog_output(output: dict[str, Any]) -> dict[str, Any]:
    matched_items = output.get("matched_items", []) if isinstance(output.get("matched_items"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    return {
        "matched_item_ids": _item_ids(matched_items),
        "matched_item_count": len(matched_items),
        "candidate_item_count": diagnostics.get("candidate_item_count", 0),
        "catalog_item_count": diagnostics.get("catalog_item_count", 0),
        "relaxation_level": diagnostics.get("relaxation_level"),
    }


def _compact_agentic_recall_output(output: dict[str, Any]) -> dict[str, Any]:
    candidates = output.get("candidates", []) if isinstance(output.get("candidates"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    return {
        "candidate_item_ids": [str(candidate.get("item_id")) for candidate in candidates if candidate.get("item_id")],
        "candidate_count": len(candidates),
        "target_pool_size": diagnostics.get("target_pool_size"),
        "path_count": diagnostics.get("path_count"),
    }


def _compact_deepfm_output(output: dict[str, Any]) -> dict[str, Any]:
    ranked_items = output.get("ranked_items", []) if isinstance(output.get("ranked_items"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    return {
        "ranked_item_ids": [str(item.get("item_id")) for item in ranked_items if item.get("item_id")],
        "ranked_item_count": len(ranked_items),
        "ranker": diagnostics.get("ranker"),
        "candidate_count": diagnostics.get("candidate_count", 0),
        "return_top_k": diagnostics.get("return_top_k"),
    }


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
    max_evidence_total = int(rag_config.get("max_evidence_total", 12) or 12)
    max_text_chars = int(rag_config.get("max_text_chars", rag_config.get("max_evidence_text_chars", 180)) or 180)
    fields = list(rag_config.get("fields", RAG_STANDARD_FIELDS))
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



def _load_item_metadata(category_items_path: Path, canonical_items_path: Path) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for path in (category_items_path, canonical_items_path):
        if not path.exists():
            continue
        for row in read_jsonl(path):
            item_id = str(row.get("parent_asin") or "")
            if not item_id:
                continue
            metadata[item_id] = {**metadata.get(item_id, {}), **_display_metadata(row)}
    return metadata



def _display_metadata(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "title_clean",
        "title",
        "main_category",
        "category",
        "categories_flat",
        "categories_path",
        "average_rating",
        "rating",
        "rating_number",
        "store",
        "price",
        "image_url",
    )
    return {key: row[key] for key in keys if row.get(key) not in (None, "", [])}



def _enrich_items(items: list[dict[str, Any]], item_metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_items: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("parent_asin") or item.get("item_id") or "")
        metadata = item_metadata.get(item_id, {})
        if not metadata:
            enriched_items.append(item)
            continue
        enriched = dict(item)
        existing_metadata = enriched.get("metadata") if isinstance(enriched.get("metadata"), dict) else {}
        enriched["metadata"] = {**metadata, **existing_metadata}
        enriched_items.append(enriched)
    return enriched_items



def _rag_diagnostics(rag_context: dict[str, Any]) -> dict[str, Any]:
    metadata = rag_context.get("metadata") if isinstance(rag_context.get("metadata"), dict) else {}
    diagnostics = metadata.get("rag_diagnostics") if isinstance(metadata.get("rag_diagnostics"), dict) else {}
    return {
        "evidence_mode": metadata.get("evidence_mode"),
        "kept_evidence_count": diagnostics.get("kept_evidence_count", 0),
        "dropped_non_candidate_evidence_count": diagnostics.get("dropped_non_candidate_evidence_count", 0),
        "dropped_policy_violation_count": diagnostics.get("dropped_policy_violation_count", 0),
        "dropped_budget_overflow_count": diagnostics.get("dropped_budget_overflow_count", 0),
        "truncated_text_count": diagnostics.get("truncated_text_count", 0),
        "max_evidence_per_item": diagnostics.get("max_evidence_per_item"),
        "max_evidence_total": diagnostics.get("max_evidence_total"),
        "max_text_chars": diagnostics.get("max_text_chars"),
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
