from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

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
    QueryRagOutput,
    RecallPathPlan,
    UnderstandUserNeedOutput,
    agentic_recall_candidates,
    build_agent_tool_planner_system_prompt,
    catalog_constraint_search,
    deepfm_rank_candidates,
    get_agent_tool_spec,
    normalize_agent_tool_calls,
    validate_agent_tool_call,
    validate_rank_candidates_arguments,
)
from rs_core.recsys.rag import (
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    SQLiteBM25QueryPlanningRetriever,
    build_query_rag_context_for_planning,
    build_rag_context_for_ranked_candidates,
)
from rs_core.rsagent.context import ContextBudget, build_context_bundle
from rs_core.rsagent.dialogue import apply_dialogue_plan, plan_dialogue_turn
from rs_core.rsagent.inference_policy import RerankPolicyClient
from rs_core.rsagent.policy import merge_feedback, normalize_feedback_input, parse_feedback
from rs_core.rsagent.runtime import AgentRuntime
from rs_core.rsagent.schema import AgentSession, AgentTurn
from rs_core.workflow.facades import AgentOrchestrationFacade, EvidenceRAGFacade


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
        self.holdout_records = holdout_records
        self.inference_client = inference_client
        self.tool_planner_system_prompt = build_agent_tool_planner_system_prompt()
        self.tool_planner_contract_sha = sha256(self.tool_planner_system_prompt.encode("utf-8")).hexdigest()
        self.runtime = AgentRuntime()
        self.agent_orchestration_facade = AgentOrchestrationFacade(self.runtime)
        self.evidence_rag_facade = EvidenceRAGFacade()

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
        itemcf_strong = load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items) if paths["itemcf_strong"].exists() else {}
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
        selected_session_id = session_id or str(uuid4())
        selected = str(user_id).strip() if user_id else f"guest-{selected_session_id}"
        if selected not in self.sequences_by_user:
            self.sequences_by_user[selected] = _cold_start_sequence(selected)
        return AgentSession(session_id=selected_session_id, user_id=selected)

    def step(self, session: AgentSession, user_input: str = "") -> AgentTurn:
        return self.converse(session, user_input)

    def converse(self, session: AgentSession, user_input: str = "", explanation_item_id: str | None = None) -> AgentTurn:
        user_input = normalize_feedback_input(user_input) if user_input else ""
        return self.agent_orchestration_facade.run_turn(self, session, user_input, explanation_item_id)

    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None = None) -> Any:
        plan = plan_dialogue_turn(user_input, session, explanation_item_id=explanation_item_id)
        plan.diagnostics["_tool_planner_contract"] = {
            "sha256": self.tool_planner_contract_sha,
            "prompt_length": len(self.tool_planner_system_prompt),
        }
        return plan

    def apply_dialogue_plan(self, session: AgentSession, plan: Any) -> Any:
        return apply_dialogue_plan(session, plan)

    def execute_agent_tools(
        self,
        session: AgentSession,
        plan: Any,
        phase: str,
        turn: AgentTurn | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls = [call for call in _planned_tool_calls(plan) if not call.phase or call.phase == phase]
        active_tool_context = tool_context if tool_context is not None else {}
        results: list[AgentToolResult] = []
        for call in calls:
            results.append(self._execute_agent_tool_call(session, plan, phase, turn, call, active_tool_context))
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
        tool_context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        active_tool_context = tool_context if tool_context is not None else {}
        reason = validate_agent_tool_call(call, str(getattr(plan, "intent", "")), phase)
        if reason is not None:
            return _tool_result(call.name, phase, "skipped", reason=reason)
        if call.name == "rank_candidates":
            validation = validate_rank_candidates_arguments(call.arguments)
            if not validation.valid:
                return _tool_result(call.name, phase, "skipped", reason=validation.reason)
            call = AgentToolCall(
                name=call.name,
                arguments=validation.normalized_arguments,
                phase=call.phase,
                call_id=call.call_id,
            )
        spec = get_agent_tool_spec(call.name)
        pool_turn = turn if call.name == "rank_candidates" else _source_turn(session, turn)
        turn_candidate_ids = _turn_candidate_item_ids(pool_turn)
        if spec and spec.requires_candidate_pool and not turn_candidate_ids:
            return _tool_result(call.name, phase, "skipped", reason="empty_candidate_pool")
        if call.name == "rank_candidates" and not _rank_candidates_explicit_ids_match_turn(call.arguments, turn_candidate_ids):
            return _tool_result(call.name, phase, "skipped", reason="rank_candidates_candidate_pool_mismatch")
        if call.name == "rank_candidates" and _rank_candidates_explicit_filter_ids(call.arguments):
            online_recommender = getattr(self, "online_recommender", None)
            if online_recommender is not None and _online_recommender_available(online_recommender):
                return _tool_result(call.name, phase, "skipped", reason="rank_candidates_explicit_ids_unsupported_online")
        try:
            result = self._dispatch_agent_tool_call(session, plan, phase, turn, call, active_tool_context)
            if call.name == "query_rag" and result.status == "ok":
                active_tool_context["query_rag"] = result.output
            return result
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
        tool_context: dict[str, Any],
    ) -> AgentToolResult:
        if get_agent_tool_spec(call.name) is None:
            return _tool_result(call.name, phase, "skipped", reason="unknown_tool")
        if call.name == "get_user_context":
            return _tool_result(call.name, phase, "ok", output=_get_user_context_output(session, call))
        if call.name == "query_rag":
            return _tool_result(call.name, phase, "ok", output=_query_rag_output(self.config, call))
        if call.name == "retrieve_candidates":
            normalized_policy = _normalize_retrieve_policy(call.arguments, self.config)
            call = AgentToolCall(name=call.name, arguments=normalized_policy, phase=call.phase, call_id=call.call_id)
            semantic_output = self._semantic_live_retrieve_candidates(call, session, turn, tool_context)
            if semantic_output is not None:
                semantic_output = _attach_retrieve_route_decisions(semantic_output, call, session, self.sequences_by_user.get(session.user_id, {}), "semantic_live")
                _store_retrieve_candidates_tool_context(tool_context, semantic_output)
                return _tool_result(call.name, phase, "ok", output=_public_retrieve_candidates_output(semantic_output))
            online_recommender = getattr(self, "online_recommender", None)
            if online_recommender is not None and _online_recommender_available(online_recommender):
                sequence = self.sequences_by_user[session.user_id]
                output = online_recommender.tool_retrieve_candidates(
                    sequence,
                    prior_turn_items=session.prior_turn_items(),
                    candidate_pool_size=_retrieve_target_pool_size(call.arguments, self.config),
                    retrieve_policy=normalized_policy,
                )
                output = _attach_retrieve_route_decisions(output, call, session, sequence, "online_backend")
                _store_retrieve_candidates_tool_context(tool_context, output)
                return _tool_result(call.name, phase, "ok", output=_public_retrieve_candidates_output(output))
            request = _agentic_recall_request_from_call(call, session, turn)
            output = agentic_recall_candidates(request, self._tool_catalog_items(), session.prior_turn_items()).to_dict()
            internal_output = _retrieve_candidates_internal_output(output)
            internal_output = _attach_retrieve_route_decisions(internal_output, call, session, self.sequences_by_user.get(session.user_id, {}), "agentic_fallback")
            _store_retrieve_candidates_tool_context(tool_context, internal_output)
            return _tool_result(call.name, phase, "ok", output=_public_retrieve_candidates_output(internal_output))
        if call.name == "rank_candidates":
            online_recommender = getattr(self, "online_recommender", None)
            if online_recommender is not None and _online_recommender_available(online_recommender):
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
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self.semantic_live_engine is None:
            return None
        semantic_mode = _semantic_mode_from_arguments(call.arguments)
        if semantic_mode == "off":
            return None
        query = _semantic_live_query_for_call(
            call.arguments,
            user_input=str(getattr(turn, "user_input", "") or ""),
            sequence=self.sequences_by_user.get(session.user_id, {}),
            item_metadata=self.item_metadata,
            item_category=self.item_category,
            semantic_mode=semantic_mode,
            query_rag_context=(tool_context or {}).get("query_rag"),
        )
        if not query:
            return None
        limit = max(1, int(call.arguments.get("limit", call.arguments.get("top_k", 50)) or 50))
        result = self._run_semantic_live_query(query, limit=limit, exclude_item_ids=session.prior_turn_items())
        result["semantic_mode"] = semantic_mode if semantic_mode != "auto" else ("hybrid_query_history" if call.arguments.get("query") and call.arguments.get("use_history_profile", True) else "auto")
        if not result.get("candidate_item_ids"):
            return None
        return {
            "candidate_item_ids": result["candidate_item_ids"],
            "candidate_count": len(result["candidate_item_ids"]),
            "candidates": result.get("candidates", []),
            "retrieval_summary": {
                "target_pool_size": limit,
                "path_count": 1,
            },
            "diagnostics": {
                "compact": True,
                "candidate_pool_size": result.get("candidate_pool_size"),
                "scored_count": result.get("scored_count"),
                "latency_ms": result.get("latency_ms"),
                "semantic_mode": result.get("semantic_mode"),
                "governance": result.get("governance", {}),
            },
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
        tool_context: dict[str, Any] | None = None,
    ) -> AgentTurn:
        return self._recommendation_step(
            session,
            user_input,
            assistant_response,
            merge_user_input=merge_user_input,
            tool_context=tool_context,
        )

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
        tool_context: dict[str, Any] | None = None,
    ) -> AgentTurn:
        if user_input:
            user_input = normalize_feedback_input(user_input)
        parsed = parse_feedback(user_input) if user_input else session.active_constraints
        if user_input and merge_user_input:
            session.active_constraints = merge_feedback(session.active_constraints, parsed)
        sequence = self.sequences_by_user[session.user_id]
        retrieved_candidates = _retrieve_candidates_from_tool_context(tool_context)
        retrieval_diagnostics = _retrieve_candidates_diagnostics_from_tool_context(tool_context)
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
            extra_candidates=retrieved_candidates or None,
        )
        result.ranking.items = _enrich_items(result.ranking.items, self.item_metadata)
        result.decision.final_items = _enrich_items(result.decision.final_items, self.item_metadata)
        candidates = [asdict(candidate) for candidate in result.candidates]
        rag_context = self.evidence_rag_facade.build_turn_rag_context(
            self.config,
            user_input,
            result.ranking.items,
            result.decision.final_items,
        )
        diagnostics = dict(result.diagnostics)
        if retrieval_diagnostics:
            diagnostics["retrieve_candidates"] = retrieval_diagnostics
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


def _semantic_live_query_for_call(
    arguments: dict[str, Any],
    *,
    user_input: str,
    sequence: dict[str, Any],
    item_metadata: dict[str, dict[str, Any]],
    item_category: dict[str, str],
    semantic_mode: str,
    query_rag_context: Any = None,
) -> str:
    normalized = _normalize_retrieve_policy(arguments)
    mode = semantic_mode if semantic_mode in {"auto", "query_intent", "history_profile", "hybrid_query_history"} else "auto"
    explicit_query = _semantic_live_explicit_query_with_rag_hint(normalized, user_input, query_rag_context)
    reference_query = _semantic_live_reference_query(normalized.get("reference_item_id"), item_metadata, item_category)
    use_history = normalized.get("use_history_profile", True) is not False
    history_query = _semantic_live_history_query(sequence, item_metadata, item_category) if use_history else ""
    if mode == "query_intent":
        return " ".join(part for part in (explicit_query, reference_query) if part).strip()
    if mode == "history_profile":
        return " ".join(part for part in (reference_query, history_query) if part).strip()
    if mode == "hybrid_query_history":
        return " ".join(part for part in (explicit_query, reference_query, history_query) if part).strip()
    if explicit_query or reference_query or history_query:
        return " ".join(part for part in (explicit_query, reference_query, history_query) if part).strip()
    return ""


def _semantic_live_explicit_query_with_rag_hint(
    arguments: dict[str, Any],
    user_input: str,
    query_rag_context: Any,
) -> str:
    explicit_query = str(arguments.get("query") or user_input or "").strip()
    if not isinstance(query_rag_context, dict):
        return explicit_query
    retrieval_hints = query_rag_context.get("retrieval_hints") if isinstance(query_rag_context.get("retrieval_hints"), dict) else {}
    semantic_hint = str(query_rag_context.get("semantic_query_hint") or retrieval_hints.get("semantic_query") or "").strip()
    if semantic_hint:
        if explicit_query and explicit_query.lower() not in semantic_hint.lower():
            return " ".join((explicit_query, semantic_hint)).strip()
        return semantic_hint
    suggested_terms = _string_list(query_rag_context.get("suggested_query_terms") or retrieval_hints.get("suggested_query_terms"))
    if not suggested_terms:
        return explicit_query
    existing_tokens = set(tokens(explicit_query))
    fresh_terms = [term for term in suggested_terms if tokens(term) and not set(tokens(term)) <= existing_tokens]
    return " ".join([explicit_query, *fresh_terms]).strip()


def _semantic_live_reference_query(reference_item_id: Any, item_metadata: dict[str, dict[str, Any]], item_category: dict[str, str]) -> str:
    item_id = str(reference_item_id or "").strip()
    if not item_id:
        return ""
    metadata = item_metadata.get(item_id, {})
    values = [
        metadata.get("title_clean") or metadata.get("title"),
        metadata.get("main_category") or metadata.get("category") or item_category.get(item_id),
        metadata.get("categories_flat"),
        metadata.get("description_text") or metadata.get("description"),
    ]
    terms: list[str] = []
    for value in values:
        for token in tokens(" ".join(str(part) for part in value) if isinstance(value, list) else str(value or "")):
            if token not in terms:
                terms.append(token)
            if len(terms) >= 8:
                return " ".join(terms)
    return " ".join(terms)



def _semantic_live_history_query(
    sequence: dict[str, Any],
    item_metadata: dict[str, dict[str, Any]],
    item_category: dict[str, str],
) -> str:
    seed_items = []
    for key in ("recent_positive_item_sequence", "recent_strong_positive_item_sequence", "recent_item_sequence"):
        for item_id in reversed(sequence.get(key, [])[-8:]):
            item_id = str(item_id or "")
            if item_id and item_id not in seed_items:
                seed_items.append(item_id)
    terms: list[str] = []
    for item_id in seed_items[:5]:
        metadata = item_metadata.get(item_id, {})
        values = [
            metadata.get("title_clean") or metadata.get("title"),
            metadata.get("main_category") or metadata.get("category") or item_category.get(item_id),
            metadata.get("categories_flat"),
            metadata.get("description_text") or metadata.get("description"),
        ]
        for value in values:
            for token in tokens(" ".join(str(part) for part in value) if isinstance(value, list) else str(value or "")):
                if token not in terms:
                    terms.append(token)
                if len(terms) >= 12:
                    return " ".join(terms)
    return " ".join(terms)


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


def _cold_start_sequence(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "recent_item_sequence": [],
        "recent_positive_item_sequence": [],
        "recent_strong_positive_item_sequence": [],
    }


def _query_rag_output(config: dict[str, Any], call: AgentToolCall) -> dict[str, Any]:
    arguments = call.arguments
    query = str(arguments.get("query") or "").strip()
    rag_config = config.get("rag") if isinstance(config.get("rag"), dict) else {}
    fields = _string_list(arguments.get("fields")) or _string_list(rag_config.get("fields")) or list(RAG_STANDARD_FIELDS)
    max_evidence_total = max(1, min(int(arguments.get("max_evidence_total", 8) or 8), 20))
    max_text_chars = max(40, min(int(arguments.get("max_text_chars", 220) or 220), 500))
    index_path = _rag_index_path(rag_config)
    if not query or index_path is None or not index_path.exists():
        return QueryRagOutput(
            query=query,
            retrieval_hints=_query_rag_boundaries(applied=False),
            diagnostics={"compact": True, "reason": "missing_query_or_index"},
        ).to_dict()

    retriever = SQLiteBM25QueryPlanningRetriever(index_path, fields=fields)
    context = build_query_rag_context_for_planning(
        query=query,
        retriever=retriever,
        policy=RagPolicy(
            mode="shadow",
            max_evidence_per_item=1,
            max_evidence_total=max_evidence_total,
            max_text_chars=max_text_chars,
            allowed_fields=fields,
        ),
        metadata={"retriever": "sqlite_bm25_query_planning"},
    )
    evidence = context.evidence
    suggested_terms = _query_rag_suggested_terms(query, evidence)
    semantic_query_hint = " ".join(part for part in [query, " ".join(suggested_terms)] if part).strip()
    return QueryRagOutput(
        query=query,
        query_rewrite=semantic_query_hint,
        semantic_query_hint=semantic_query_hint,
        suggested_query_terms=suggested_terms,
        retrieval_hints={
            **_query_rag_boundaries(applied=bool(evidence)),
            "semantic_query": semantic_query_hint,
            "suggested_query_terms": suggested_terms,
        },
        diagnostics={
            "compact": True,
            "evidence_count": len(evidence),
            "retrieval_scope": "query_planning",
            "candidate_scoped": False,
        },
    ).to_dict()


def _query_rag_boundaries(*, applied: bool) -> dict[str, Any]:
    return {
        "applied": applied,
        "retrieval_scope": "query_planning",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "public_payload_allowed": False,
    }


def _query_rag_suggested_terms(query: str, evidence: list[Any]) -> list[str]:
    existing = set(tokens(query))
    blocked = existing | {"and", "with", "for", "the", "item", "product", "recommend"}
    terms: list[str] = []
    for row in evidence:
        for token in tokens(f"{row.field} {row.text}"):
            if token in blocked or token in terms or len(token) < 3:
                continue
            terms.append(token)
            if len(terms) >= 8:
                return terms
    return terms


def _normalize_retrieve_policy(arguments: dict[str, Any] | None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(arguments) if isinstance(arguments, dict) else {}
    route_policy = raw.get("route_policy") if isinstance(raw.get("route_policy"), dict) else {}
    retrieval_mode = str(raw.get("retrieval_mode") or _legacy_retrieval_mode(raw, route_policy) or "auto").strip().lower()
    if retrieval_mode not in {"auto", "specific_need", "personalized_feed", "broad_browse", "similar_to_item", "reference_with_constraints"}:
        retrieval_mode = "auto"
    profile_usage = str(raw.get("profile_usage") or _legacy_profile_usage(raw) or "balanced").strip().lower()
    if profile_usage not in {"none", "light", "balanced", "strong"}:
        profile_usage = "balanced"
    expansion_policy = str(raw.get("expansion_policy") or "balanced").strip().lower()
    if expansion_policy not in {"none", "narrow", "balanced", "broad"}:
        expansion_policy = "balanced"
    semantic_mode = _semantic_mode_from_policy(raw, route_policy, retrieval_mode, profile_usage)
    use_history_profile = profile_usage != "none" and raw.get("use_history_profile", True) is not False
    use_behavioral_recall = raw.get("use_behavioral_recall", True) is not False
    normalized = {
        **raw,
        "retrieval_mode": retrieval_mode,
        "profile_usage": profile_usage,
        "expansion_policy": expansion_policy,
        "reference_item_id": str(raw.get("reference_item_id") or raw.get("similar_to_item_id") or raw.get("target_item_id") or "").strip() or None,
        "target_pool_size": _retrieve_target_pool_size(raw, config or {}),
        "semantic_mode": semantic_mode,
        "use_history_profile": use_history_profile,
        "use_behavioral_recall": use_behavioral_recall,
        "provider_policy": {
            "semantic_mode": semantic_mode,
            "traditional": "off" if retrieval_mode == "specific_need" and not use_behavioral_recall else "auto",
            "reference": "prefer" if retrieval_mode in {"similar_to_item", "reference_with_constraints"} else "auto",
            "fallback": str(route_policy.get("fallback") or "auto").strip().lower(),
        },
    }
    return normalized



def _legacy_retrieval_mode(raw: dict[str, Any], route_policy: dict[str, Any]) -> str:
    if raw.get("reference_item_id") or raw.get("similar_to_item_id") or raw.get("target_item_id") or route_policy.get("similar_item") == "prefer":
        return "similar_to_item"
    if str(raw.get("query") or "").strip():
        return "specific_need"
    if raw.get("use_history_profile", True) is not False:
        return "personalized_feed"
    return "broad_browse"



def _legacy_profile_usage(raw: dict[str, Any]) -> str:
    if raw.get("use_history_profile") is False:
        return "none"
    profile_policy = raw.get("profile_policy") if isinstance(raw.get("profile_policy"), dict) else {}
    weight = str(profile_policy.get("history_weight") or "").strip().lower()
    return weight if weight in {"light", "balanced", "strong"} else "balanced"



def _semantic_mode_from_policy(raw: dict[str, Any], route_policy: dict[str, Any], retrieval_mode: str, profile_usage: str) -> str:
    semantic = str(raw.get("semantic_mode") or route_policy.get("semantic") or "").strip().lower()
    if semantic in {"off", "auto", "query_intent", "history_profile", "hybrid_query_history"}:
        return semantic
    if retrieval_mode in {"specific_need", "reference_with_constraints"}:
        return "hybrid_query_history" if profile_usage != "none" else "query_intent"
    if retrieval_mode == "similar_to_item":
        return "hybrid_query_history"
    if retrieval_mode == "broad_browse":
        return "history_profile" if profile_usage != "none" else "auto"
    return "auto"



def _retrieve_candidates_internal_output(output: dict[str, Any]) -> dict[str, Any]:
    candidates = output.get("candidates", []) if isinstance(output.get("candidates"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    return {
        "candidate_item_ids": [str(candidate.get("item_id")) for candidate in candidates if candidate.get("item_id")],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "retrieval_summary": {
            "target_pool_size": diagnostics.get("target_pool_size"),
            "path_count": diagnostics.get("path_count"),
        },
        "diagnostics": {"compact": True},
    }


def _attach_retrieve_route_decisions(
    output: dict[str, Any],
    call: AgentToolCall,
    session: AgentSession,
    sequence: dict[str, Any],
    selected_route: str,
) -> dict[str, Any]:
    candidate_count = int(output.get("candidate_count") or len(_string_list(output.get("candidate_item_ids"))))
    target_pool_size = _retrieve_target_pool_size(call.arguments, {})
    summary = dict(output.get("retrieval_summary")) if isinstance(output.get("retrieval_summary"), dict) else {}
    normalized_policy = _normalize_retrieve_policy(call.arguments)
    summary["schema_version"] = "retrieve_candidates_output_v3"
    summary.setdefault("target_pool_size", target_pool_size)
    summary["retrieval_mode"] = normalized_policy["retrieval_mode"]
    summary["profile_usage"] = normalized_policy["profile_usage"]
    summary["expansion_policy"] = normalized_policy["expansion_policy"]
    summary["returned_count"] = candidate_count
    summary["underfill"] = candidate_count < int(summary.get("target_pool_size") or target_pool_size or 0)
    route_decisions = _retrieve_route_decisions(normalized_policy, session, sequence, selected_route, candidate_count)
    summary["route_count"] = sum(1 for decision in route_decisions if decision.get("status") == "used")
    summary.setdefault("path_count", summary.get("route_count"))
    return {**output, "retrieval_summary": summary, "route_decisions": route_decisions}


def _retrieve_target_pool_size(arguments: dict[str, Any], config: dict[str, Any]) -> int:
    value = arguments.get("target_pool_size", arguments.get("limit", config.get("candidate_pool_size", 50)))
    try:
        return max(1, min(int(value or 50), 500))
    except (TypeError, ValueError):
        return 50


def _semantic_mode_from_arguments(arguments: dict[str, Any]) -> str:
    normalized = _normalize_retrieve_policy(arguments)
    provider_policy = normalized.get("provider_policy") if isinstance(normalized.get("provider_policy"), dict) else {}
    semantic = str(provider_policy.get("semantic_mode") or "auto").strip().lower()
    return semantic if semantic in {"off", "auto", "query_intent", "history_profile", "hybrid_query_history"} else "auto"


def _route_policy_value(arguments: dict[str, Any], key: str, default: str = "auto") -> str:
    route_policy = arguments.get("route_policy") if isinstance(arguments.get("route_policy"), dict) else {}
    return str(route_policy.get(key) or default).strip().lower()


def _retrieve_route_decisions(
    arguments: dict[str, Any],
    session: AgentSession,
    sequence: dict[str, Any],
    selected_route: str,
    candidate_count: int,
) -> list[dict[str, Any]]:
    recent_items = len(_string_list(sequence.get("recent_item_sequence"))) or len(session.user_profile.liked_item_ids)
    positive_items = len(_string_list(sequence.get("recent_positive_item_sequence"))) or len(session.user_profile.liked_item_ids)
    provider_policy = arguments.get("provider_policy") if isinstance(arguments.get("provider_policy"), dict) else {}
    query_available = bool(str(arguments.get("query") or "").strip())
    reference_available = bool(arguments.get("reference_item_id"))
    profile_enabled = arguments.get("profile_usage") != "none" and arguments.get("use_history_profile", True) is not False
    backend_enabled = arguments.get("use_behavioral_recall", True) is not False
    fallback_policy = str(provider_policy.get("fallback") or "auto").strip().lower()
    return [
        _route_decision(
            "semantic_intent",
            selected_route == "semantic_live",
            provider_policy.get("semantic_mode") != "off" and (query_available or reference_available or profile_enabled),
            "used business intent text" if selected_route == "semantic_live" else "available from query, reference item, or profile text",
            candidate_count if selected_route == "semantic_live" else 0,
        ),
        _route_decision(
            "profile_context",
            backend_enabled and selected_route in {"online_backend", "agentic_fallback"},
            profile_enabled and recent_items >= 1,
            "uses recent preference context when available",
            0,
        ),
        _route_decision(
            "reference_context",
            selected_route in {"semantic_live", "online_backend", "agentic_fallback"} and reference_available,
            reference_available,
            "uses the reference item as a similarity anchor",
            candidate_count if selected_route == "semantic_live" and reference_available else 0,
        ),
        _route_decision(
            "backend_recall",
            selected_route == "online_backend" and backend_enabled,
            backend_enabled and (recent_items >= 1 or positive_items >= 1),
            "backend may expand candidates from eligible user context",
            candidate_count if selected_route == "online_backend" else 0,
        ),
        _route_decision(
            "fallback_safety",
            selected_route in {"online_backend", "agentic_fallback"} and fallback_policy != "off",
            fallback_policy != "off",
            "keeps acquisition safe for cold start or underfilled pools",
            candidate_count if selected_route in {"online_backend", "agentic_fallback"} else 0,
        ),
    ]


def _route_decision(route: str, used: bool, eligible: bool, reason: str, returned_count: int) -> dict[str, Any]:
    status = "used" if used else "skipped" if not eligible else "available"
    return {"route": route, "status": status, "reason": reason, "eligible": eligible, "returned_count": int(returned_count or 0)}


def _compact_route_decisions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    decisions = []
    for item in value:
        if not isinstance(item, dict):
            continue
        decisions.append({
            "route": str(item.get("route") or ""),
            "status": str(item.get("status") or ""),
            "reason": str(item.get("reason") or "")[:160],
            "eligible": bool(item.get("eligible")),
            "returned_count": int(item.get("returned_count") or 0),
        })
    return decisions


def _public_retrieve_candidates_output(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_item_ids": _string_list(output.get("candidate_item_ids")),
        "candidate_count": int(output.get("candidate_count") or 0),
        "retrieval_summary": dict(output.get("retrieval_summary")) if isinstance(output.get("retrieval_summary"), dict) else {},
        "route_decisions": _compact_route_decisions(output.get("route_decisions")),
        "diagnostics": {"compact": True, "internal_only": True, "public_payload_allowed": False},
    }


def _store_retrieve_candidates_tool_context(tool_context: dict[str, Any], output: dict[str, Any]) -> None:
    candidates = _merged_candidates_from_retrieve_output(output)
    diagnostics = output.get("diagnostics") if isinstance(output.get("diagnostics"), dict) else {}
    tool_context["retrieve_candidates"] = {
        "candidate_item_ids": _string_list(output.get("candidate_item_ids")),
        "candidate_count": int(output.get("candidate_count") or len(candidates)),
        "candidates": candidates,
        "retrieval_summary": dict(output.get("retrieval_summary")) if isinstance(output.get("retrieval_summary"), dict) else {},
        "route_decisions": _compact_route_decisions(output.get("route_decisions")),
        "diagnostics": diagnostics,
    }


def _retrieve_candidates_from_tool_context(tool_context: dict[str, Any] | None) -> list[MergedCandidate]:
    if not isinstance(tool_context, dict):
        return []
    payload = tool_context.get("retrieve_candidates")
    if not isinstance(payload, dict):
        return []
    return _merged_candidates_from_retrieve_output(payload)


def _retrieve_candidates_diagnostics_from_tool_context(tool_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(tool_context, dict):
        return {}
    payload = tool_context.get("retrieve_candidates")
    if not isinstance(payload, dict):
        return {}
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    return {
        "enabled": True,
        "source": "tool_context",
        "candidate_count": int(payload.get("candidate_count") or 0),
        "candidate_item_count": len(_string_list(payload.get("candidate_item_ids"))),
        "retrieval_summary": dict(payload.get("retrieval_summary")) if isinstance(payload.get("retrieval_summary"), dict) else {},
        "route_decisions": _compact_route_decisions(payload.get("route_decisions")),
        "diagnostics": diagnostics,
    }


def _merged_candidates_from_retrieve_output(output: dict[str, Any]) -> list[MergedCandidate]:
    raw_candidates = output.get("candidates") if isinstance(output.get("candidates"), list) else []
    candidates: list[MergedCandidate] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_candidates, start=1):
        candidate = _merged_candidate_from_tool_item(item, index)
        if candidate is None or candidate.item_id in seen:
            continue
        seen.add(candidate.item_id)
        candidates.append(candidate)
    return candidates


def _merged_candidate_from_tool_item(item: Any, index: int) -> MergedCandidate | None:
    if isinstance(item, MergedCandidate):
        return item
    if not isinstance(item, dict):
        return None
    item_id = _rank_candidate_id_from_dict(item)
    if not item_id:
        return None
    sources = _string_list(item.get("sources")) or _string_list(item.get("source")) or ["retrieve_candidates"]
    source_scores = item.get("source_scores") if isinstance(item.get("source_scores"), dict) else {}
    if not source_scores:
        score = _safe_float(item.get("score") or item.get("source_score") or item.get("rank_score"), 1.0 / index)
        source_scores = {sources[0]: score}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if not metadata:
        metadata = {key: item[key] for key in (
            "parent_asin",
            "item_id",
            "asin",
            "title_clean",
            "title",
            "main_category",
            "category",
            "brand",
            "store",
            "price",
            "rating",
            "average_rating",
            "rating_number",
            "features",
            "features_text",
            "description",
            "description_text",
            "target_conditioned_catalog_text",
        ) if item.get(key) not in (None, "", [])}
        metadata.setdefault("item_id", item_id)
        metadata.setdefault("parent_asin", item_id)
    return MergedCandidate(
        item_id=item_id,
        sources=sources,
        source_scores={str(source): _safe_float(score, 0.0) for source, score in source_scores.items()},
        category=str(item.get("category") or item.get("main_category") or metadata.get("category") or metadata.get("main_category") or ""),
        metadata=dict(metadata),
    )


def _rank_candidates_output(output: dict[str, Any]) -> dict[str, Any]:
    ranked_items = output.get("ranked_items", []) if isinstance(output.get("ranked_items"), list) else []
    diagnostics = output.get("diagnostics", {}) if isinstance(output.get("diagnostics"), dict) else {}
    ranked_item_ids = [str(item.get("item_id")) for item in ranked_items if item.get("item_id")]
    governance = _rank_candidates_output_governance()
    return {
        "ranked_item_ids": ranked_item_ids,
        "ranked_item_count": len(ranked_item_ids),
        "ranking_summary": {
            "schema_version": "rank_candidates_output_v1",
            "ranker": diagnostics.get("ranker"),
            "route": diagnostics.get("route") or "deterministic_fallback",
            "candidate_count": diagnostics.get("candidate_count", 0),
            "ranked_item_count": len(ranked_item_ids),
            "return_top_k": diagnostics.get("return_top_k"),
            "has_ranking_snapshot": bool(diagnostics.get("has_ranking_snapshot", False)),
            "governance": governance,
        },
        "diagnostics": {
            "compact": True,
            "internal_only": True,
            "public_payload_allowed": False,
            "reason": diagnostics.get("reason") or "fallback_rank_candidates_compact",
            "returned_count": diagnostics.get("returned_count", len(ranked_item_ids)),
            "truncated": bool(diagnostics.get("return_top_k") and diagnostics.get("candidate_count", 0) > diagnostics.get("return_top_k", 0)),
        },
    }


def _rank_candidates_output_governance() -> dict[str, Any]:
    return {
        "internal_only": True,
        "public_payload_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "diagnostic_only": True,
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


def _online_recommender_available(online_recommender: Any) -> bool:
    readiness = online_recommender.readiness()
    return bool(readiness.get("complete_pool500_available") or readiness.get("online_source_indexes_available"))


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
    arguments = _normalize_retrieve_policy(call.arguments)
    paths = [_recall_path_from_dict(path) for path in arguments.get("paths", []) if isinstance(path, dict)]
    if not paths:
        query = str(arguments.get("query") or getattr(turn, "user_input", "") or "")
        reference_item_id = str(arguments.get("reference_item_id") or "").strip() or None
        mode = str(arguments.get("retrieval_mode") or "auto")
        path_name = "similar_item_search" if mode == "similar_to_item" else "cheaper_alternative_search" if mode == "reference_with_constraints" else "constraint_catalog_search"
        paths = [RecallPathPlan(
            name=path_name,
            limit=int(arguments.get("limit", arguments.get("target_pool_size", 50)) or 50),
            top_k=int(arguments.get("top_k", arguments.get("limit", arguments.get("target_pool_size", 50))) or 50),
            query=query,
            rules=_rules_from_active_constraints(session),
            reference_item_id=reference_item_id,
            similar_to_item_id=reference_item_id if mode == "similar_to_item" else None,
            target_item_id=reference_item_id if mode in {"similar_to_item", "reference_with_constraints"} else None,
            reason=f"business_mode:{mode}",
        )]
    return AgenticRecallRequest(
        user_id=session.user_id,
        session_id=session.session_id,
        target_pool_size=int(arguments.get("target_pool_size", 100) or 100),
        global_rules=dict(arguments.get("global_rules")) if isinstance(arguments.get("global_rules"), dict) else {"exclude_seen_items": True, "dedupe_by_parent_asin": True},
        paths=paths,
        ranking_context=dict(arguments.get("ranking_context")) if isinstance(arguments.get("ranking_context"), dict) else {"query": getattr(turn, "user_input", "") or "", "retrieval_mode": arguments.get("retrieval_mode")},
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
    candidates = _deepfm_candidates_from_turn(turn)
    filter_ids = set(_rank_candidates_explicit_filter_ids(arguments))
    if filter_ids:
        candidates = [candidate for candidate in candidates if candidate.get("item_id") in filter_ids]
    return DeepFMRankRequest(
        user_id=session.user_id,
        session_id=session.session_id,
        return_top_k=int(arguments.get("return_top_k", 20) or 20),
        ranking_context=dict(arguments.get("ranking_context")) if isinstance(arguments.get("ranking_context"), dict) else {"query": getattr(turn, "user_input", "") or ""},
        candidates=candidates,
    )


def _deepfm_candidates_from_turn(turn: AgentTurn | None) -> list[dict[str, Any]]:
    if turn is None:
        return []
    candidates = []
    seen: set[str] = set()
    source_items = [*(turn.candidates or []), *(turn.ranking or []), *(turn.recommendation.final_items or [])]
    for item in source_items:
        if not isinstance(item, dict):
            continue
        item_id = _rank_candidate_id_from_dict(item)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        source_rank = len(candidates) + 1
        candidates.append({
            "item_id": item_id,
            "acquisition_path": ",".join(str(source) for source in item.get("sources", [])) if isinstance(item.get("sources"), list) else str(item.get("source") or item.get("acquisition_path") or "hybrid_turn_pool"),
            "source_rank": int(item.get("source_rank") or item.get("rank") or source_rank),
            "source_score": _safe_float(item.get("score") or item.get("rank_score") or item.get("source_score"), 1.0 / source_rank),
            "item_features": _safe_deepfm_item_features(item, item_id),
        })
    return candidates


def _rank_candidates_explicit_ids_match_turn(arguments: dict[str, Any], turn_candidate_ids: list[str]) -> bool:
    explicit_ids = _rank_candidates_explicit_filter_ids(arguments)
    return not explicit_ids or set(explicit_ids) == set(turn_candidate_ids)


def _rank_candidates_explicit_filter_ids(arguments: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for item_id in _string_list(arguments.get("candidate_item_ids")):
        if item_id not in ids:
            ids.append(item_id)
    candidates = arguments.get("candidates") if isinstance(arguments.get("candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        item_id = _rank_candidate_id_from_dict(candidate)
        if item_id and item_id not in ids:
            ids.append(item_id)
    return ids


def _rank_candidate_id_from_dict(item: dict[str, Any]) -> str:
    item_features = item.get("item_features") if isinstance(item.get("item_features"), dict) else {}
    return str(
        item.get("item_id")
        or item.get("parent_asin")
        or item.get("asin")
        or item.get("dst_item")
        or item_features.get("item_id")
        or item_features.get("parent_asin")
        or ""
    ).strip()


def _safe_deepfm_item_features(item: dict[str, Any], item_id: str) -> dict[str, Any]:
    source = item.get("item_features") if isinstance(item.get("item_features"), dict) else item
    allowed = (
        "parent_asin",
        "item_id",
        "asin",
        "title_clean",
        "title",
        "main_category",
        "category",
        "brand",
        "store",
        "price",
        "rating",
        "average_rating",
        "rating_number",
        "features",
        "features_text",
        "description",
        "description_text",
        "target_conditioned_catalog_text",
    )
    blocked = {"feature_rows", "deepfm_score", "label", "valid", "test", "label_binary", "split"}
    features = {key: source[key] for key in allowed if key not in blocked and source.get(key) not in (None, "", [])}
    features.setdefault("item_id", item_id)
    features.setdefault("parent_asin", item_id)
    return features


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
