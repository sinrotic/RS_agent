from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.serving]

from rs_core.common.io import write_jsonl
from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.reward import build_reward_evidence
from rs_core.rsagent.runtime import RUNTIME_TRACE_STEP_ORDER, AgentRuntime
from rs_core.rsagent.schema import INTENT_RECOMMEND_REQUEST, AgentSession, AgentTurn, FeedbackConstraints
from rs_core.rsagent.tools import AgentToolCall
from rs_core.workflow.facades import AgentOrchestrationFacade
from rs_core.workflow.hybrid_environment import (
    HybridRecommendationEnvironment,
    _deepfm_rank_request_from_call,
    _product_search_request_from_call,
    _rank_candidates_output,
    _semantic_live_query_for_call,
)
from rs_core.workflow.online_recommendation import OnlinePool500Recommender, _rank_return_top_k


def test_agent_orchestration_facade_delegates_to_runtime_host_seam():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = _turn_with_items(session.active_constraints, [{"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]}])
    host = _StaticHost(turn)
    facade = AgentOrchestrationFacade(host.runtime)

    result = facade.run_turn(host, session, "prefer Audio", explanation_item_id="ok_1")

    assert result is turn
    assert host.plan_calls == 1
    assert host.plan_inputs == [("prefer Audio", "s1", "ok_1")]
    assert host.build_recommendation_calls == 1


def test_environment_anonymous_sessions_get_independent_cold_start_identity(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)

    first = env.start_session()
    second = env.start_session()

    assert first.session_id != second.session_id
    assert first.user_id == f"guest-{first.session_id}"
    assert second.user_id == f"guest-{second.session_id}"
    assert first.user_id != second.user_id
    assert env.sequences_by_user[first.user_id] == _empty_sequence(first.user_id)
    assert env.sequences_by_user[second.user_id] == _empty_sequence(second.user_id)


def test_converse_delegates_through_agent_orchestration_facade(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    calls: list[tuple[object, AgentSession, str, str | None]] = []
    original_run_turn = env.agent_orchestration_facade.run_turn

    def spy_run_turn(host: object, active_session: AgentSession, user_input: str = "", explanation_item_id: str | None = None) -> AgentTurn:
        calls.append((host, active_session, user_input, explanation_item_id))
        return original_run_turn(host, active_session, user_input, explanation_item_id)

    env.agent_orchestration_facade.run_turn = spy_run_turn  # type: ignore[method-assign]

    turn = env.converse(session, "For commute, prefer bluetooth and Audio", explanation_item_id="speaker_1")

    assert calls == [(env, session, "For commute, prefer bluetooth and Audio", "speaker_1")]
    assert turn.diagnostics["agent_runtime_trace"]
    assert session.turns[-1] is turn
    assert turn.recommendation.final_items[0]["parent_asin"] == "speaker_1"


def test_converse_attaches_ordered_runtime_trace_and_summary(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    turn = env.converse(session, "For commute, prefer bluetooth and Audio")

    trace = turn.diagnostics["agent_runtime_trace"]
    assert [step["name"] for step in trace] == RUNTIME_TRACE_STEP_ORDER
    assert turn.diagnostics["memory_snapshot"]["conversation_state"]
    assert turn.diagnostics["tool_result_budget"]["retained"] > 0
    assert turn.diagnostics["stop_check_result"]["checked"] is True
    assert session.runtime_trace[-1]["steps"] == RUNTIME_TRACE_STEP_ORDER
    assert session.session_summary["shown_item_ids"][0] == "speaker_1"
    assert "speaker_1" in session.session_summary["shown_item_ids"]
    assert session.session_summary["preferred_categories"] == {"Audio": 1.0}
    assert session.session_summary["recent_action"] == "revise_recommendation"


def test_runtime_summary_default_current_goal_uses_dialogue_contract():
    session = AgentSession(session_id="s1", user_id="u1")

    summary = AgentRuntime()._compact_session(session)

    assert summary["current_goal"] == INTENT_RECOMMEND_REQUEST


def test_memory_prefetch_changes_after_prior_turn_and_feedback(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    first = env.converse(session, "For commute, prefer bluetooth and Audio")
    second = env.converse(session, "show me something different")
    third = env.converse(session, "why?")

    first_memory = first.diagnostics["memory_snapshot"]
    second_memory = second.diagnostics["memory_snapshot"]
    third_memory = third.diagnostics["memory_snapshot"]

    assert first_memory["prior_turn_count"] == 0
    assert second_memory["prior_turn_count"] == 1
    assert second_memory["recent_turns"][0]["item_ids"][0] == "speaker_1"
    assert "speaker_1" in second_memory["recent_turns"][0]["item_ids"]
    assert third_memory["prior_turn_count"] == 2
    assert third_memory["active_constraints"]["filter_prior_turn_items"] is True


def test_budget_does_not_truncate_existing_top_level_diagnostics(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    turn = env.converse(session, "For commute, prefer bluetooth and Audio")

    assert "boost_events" in turn.diagnostics
    assert turn.diagnostics["boost_events"]
    assert isinstance(turn.diagnostics["boost_events"], dict)
    assert "_truncated" not in json.dumps(turn.diagnostics["boost_events"])
    assert turn.diagnostics["tool_result_budget"]["retained"] > 0


def test_stop_check_repairs_disliked_final_items_without_mutating_constraints():
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints.disliked_item_ids.add("bad_1")
    turn = _turn_with_items(session.active_constraints, [
        {"parent_asin": "bad_1", "category": "Audio", "sources": ["popular"]},
        {"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]},
    ])
    before = session.active_constraints.to_dict()

    repaired = _StaticHost(turn)
    result = repaired.runtime.run_turn(repaired, session, "avoid bad_1")

    assert [item["parent_asin"] for item in result.recommendation.final_items] == ["ok_1"]
    assert [item["parent_asin"] for item in result.ranking] == ["ok_1"]
    assert session.active_constraints.to_dict() == before
    assert result.diagnostics["stop_check_result"]["repaired"] is True
    assert result.diagnostics["stop_check_result"]["constraints_unchanged"] is True
    evidence = build_reward_evidence(result, set())
    assert evidence.feedback_constraints_satisfied["disliked_item_ids"] is True


def test_stop_check_does_not_call_recommendation_callback_twice():
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints.disliked_categories.add("Audio")
    turn = _turn_with_items(session.active_constraints, [{"parent_asin": "bad_1", "category": "Audio", "sources": ["popular"]}])
    host = _StaticHost(turn)

    host.runtime.run_turn(host, session, "avoid Audio")

    assert host.build_recommendation_calls == 1
    assert host.plan_calls == 1
    assert session.active_constraints.disliked_categories == {"Audio"}


def test_runtime_executes_host_tools_and_attaches_internal_diagnostics():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = _turn_with_items(session.active_constraints, [{"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]}])
    host = _ToolHost(turn)

    result = host.runtime.run_turn(host, session, "prefer Audio")

    assert host.executed_phases == ["pre_recommendation", "post_recommendation"]
    assert result.diagnostics["agent_tool_summary"]["result_count"] == 2
    assert [event["tool_name"] for event in result.diagnostics["agent_tool_events"]] == ["fake_pre", "fake_post"]
    assert [step["name"] for step in result.diagnostics["agent_runtime_trace"]] == RUNTIME_TRACE_STEP_ORDER


def test_agent_turn_to_dict_omits_hidden_rag_context_by_default():
    turn = _turn_with_items(FeedbackConstraints(), [{"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]}])
    turn.rag_context = {"evidence": [{"text": "internal evidence", "source": "sqlite_bm25"}]}

    payload = turn.to_dict()

    assert "rag_context" not in payload


def test_semantic_live_query_consumes_query_rag_hint():
    query = _semantic_live_query_for_call(
        {"query": "commute speaker", "semantic_mode": "hybrid_query_history"},
        user_input="",
        sequence={"recent_positive_item_sequence": []},
        item_metadata={},
        item_category={},
        semantic_mode="hybrid_query_history",
        query_rag_context={"semantic_query_hint": "commute speaker portable bluetooth"},
    )

    assert query == "commute speaker portable bluetooth"


def test_runtime_passes_single_turn_tool_context_between_phases():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = _turn_with_items(session.active_constraints, [{"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]}])
    host = _ToolContextHost(turn)

    host.runtime.run_turn(host, session, "prefer Audio")

    assert host.pre_context_seen == {"query_rag": {"semantic_query_hint": "portable bluetooth commute"}}
    assert host.build_context_seen == host.pre_context_seen
    assert host.post_context_seen == host.pre_context_seen


def test_retrieve_candidates_tool_context_feeds_recommendation_without_public_candidate_payload(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    tool_context = {
        "retrieve_candidates": {
            "candidate_item_ids": ["tool_1"],
            "candidate_count": 1,
            "candidates": [{
                "item_id": "tool_1",
                "source": "semantic_live",
                "source_score": 999.0,
                "category": "Audio",
                "title": "Tool-context candidate",
            }],
            "retrieval_summary": {"target_pool_size": 1, "path_count": 1},
            "diagnostics": {"compact": True, "route": "unit"},
        }
    }

    turn = env.build_recommendation_turn(session, "prefer Audio", "updated", False, tool_context=tool_context)

    assert turn.recommendation.final_items[0]["parent_asin"] == "tool_1"
    assert "tool_1" in [candidate["item_id"] for candidate in turn.candidates]
    assert turn.diagnostics["retrieve_candidates"]["source"] == "tool_context"
    assert "candidates" not in turn.diagnostics["retrieve_candidates"]



def test_rank_candidates_request_uses_turn_pool_and_filters_without_leaking_fields():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = _turn_with_items(session.active_constraints, [
        {"parent_asin": "ok_1", "rank": 1, "deepfm_score": 9, "label": 1, "valid": True, "test": True},
        {"parent_asin": "ok_2", "rank": 2},
    ])

    request = _deepfm_rank_request_from_call(
        AgentToolCall(
            name="rank_candidates",
            arguments={
                "candidate_item_ids": ["ok_1"],
                "candidates": [{"item_id": "forged", "deepfm_score": 999}],
                "return_top_k": 1,
            },
        ),
        session,
        turn,
    )

    assert [candidate["item_id"] for candidate in request.candidates] == ["ok_1"]
    assert request.return_top_k == 1
    assert "deepfm_score" not in request.candidates[0]["item_features"]
    assert "label" not in request.candidates[0]["item_features"]
    assert "valid" not in request.candidates[0]["item_features"]
    assert "test" not in request.candidates[0]["item_features"]


def test_rank_candidates_execution_skips_explicit_pool_mismatch(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    turn = _turn_with_items(session.active_constraints, [{"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]}])

    result = env._execute_agent_tool_call(
        session,
        _Plan(),
        "post_recommendation",
        turn,
        AgentToolCall(name="rank_candidates", arguments={"candidate_item_ids": ["ok_1", "forged"]}),
    )

    assert result.status == "skipped"
    assert result.reason == "rank_candidates_candidate_pool_mismatch"


def test_rank_candidates_execution_skips_explicit_pool_subset(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    turn = _turn_with_items(session.active_constraints, [
        {"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]},
        {"parent_asin": "ok_2", "category": "Audio", "sources": ["popular"]},
    ])

    result = env._execute_agent_tool_call(
        session,
        _Plan(),
        "post_recommendation",
        turn,
        AgentToolCall(name="rank_candidates", arguments={"candidate_item_ids": ["ok_1"]}),
    )

    assert result.status == "skipped"
    assert result.reason == "rank_candidates_candidate_pool_mismatch"



def test_rank_candidates_execution_does_not_reuse_prior_turn_pool(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    session.turns.append(_turn_with_items(session.active_constraints, [{"parent_asin": "prior_1", "category": "Audio", "sources": ["popular"]}]))

    result = env._execute_agent_tool_call(
        session,
        _Plan(),
        "post_recommendation",
        None,
        AgentToolCall(name="rank_candidates", arguments={"candidate_item_ids": ["prior_1"]}),
    )

    assert result.status == "skipped"
    assert result.reason == "empty_candidate_pool"


def test_deepfm_candidates_from_turn_dedupes_stably_without_leaking_fields():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = _turn_with_items(session.active_constraints, [
        {"parent_asin": "ok_1", "rank": 1, "deepfm_score": 9, "label": 1},
        {"parent_asin": "ok_2", "rank": 2},
        {"parent_asin": "ok_1", "rank": 3, "deepfm_score": 99},
    ])

    request = _deepfm_rank_request_from_call(AgentToolCall(name="rank_candidates"), session, turn)

    assert [candidate["item_id"] for candidate in request.candidates] == ["ok_1", "ok_2"]
    assert request.candidates[0]["source_rank"] == 1
    assert request.candidates[1]["source_rank"] == 2
    assert "deepfm_score" not in json.dumps(request.candidates, ensure_ascii=False)
    assert "label" not in json.dumps(request.candidates, ensure_ascii=False)


def test_rank_candidates_compact_output_has_internal_governance_without_scores():
    output = _rank_candidates_output({
        "ranked_items": [{"item_id": "ok_1", "deepfm_score": 999.0}],
        "feature_rows": [{"item_id": "ok_1"}],
        "diagnostics": {"ranker": "deepfm_contract_deterministic_fallback", "candidate_count": 3, "return_top_k": 1, "returned_count": 1},
    })
    payload = json.dumps(output, ensure_ascii=False)

    assert output["ranking_summary"]["schema_version"] == "rank_candidates_output_v1"
    assert output["ranking_summary"]["route"] == "deterministic_fallback"
    assert output["ranking_summary"]["governance"] == {
        "internal_only": True,
        "public_payload_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "diagnostic_only": True,
    }
    assert output["diagnostics"]["reason"] == "fallback_rank_candidates_compact"
    assert "feature_rows" not in payload
    assert "deepfm_score" not in payload


def test_online_rank_explicit_ids_skip_when_facade_cannot_rerank(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    env.online_recommender = _OnlineRankOnlyRecommender()
    session = env.start_session("u1")
    turn = _turn_with_items(session.active_constraints, [{"parent_asin": "ok_1", "category": "Audio", "sources": ["popular"]}])

    result = env._execute_agent_tool_call(
        session,
        _Plan(),
        "post_recommendation",
        turn,
        AgentToolCall(name="rank_candidates", arguments={"candidate_item_ids": ["ok_1"]}),
    )

    assert result.status == "skipped"
    assert result.reason == "rank_candidates_explicit_ids_unsupported_online"



def test_online_rank_facade_reports_existing_snapshot_without_reranking():
    turn = SimpleNamespace(
        candidates=[{"parent_asin": "ok_1"}, {"parent_asin": "ok_2"}],
        ranking=[{"parent_asin": "ok_1"}, {"parent_asin": "ok_2"}],
    )

    output = OnlinePool500Recommender.tool_rank_candidates(SimpleNamespace(), turn, return_top_k=1)

    assert output["ranked_item_ids"] == ["ok_1"]
    assert output["ranking_summary"]["schema_version"] == "rank_candidates_output_v1"
    assert output["ranking_summary"]["ranker"] == "online_route_facade"
    assert output["ranking_summary"]["route"] == "online_route_facade"
    assert output["ranking_summary"]["has_ranking_snapshot"] is True
    assert output["ranking_summary"]["governance"]["public_payload_allowed"] is False
    assert output["ranking_summary"]["governance"]["ranking_replacement_allowed"] is False
    assert output["diagnostics"] == {
        "compact": True,
        "internal_only": True,
        "public_payload_allowed": False,
        "route": "online_route_facade",
        "reason": "uses_existing_turn_ranking_snapshot",
        "truncated": True,
    }


@pytest.mark.parametrize(("value", "expected"), [(None, 20), (True, 20), ("bad", 20), (0, 1), (-3, 1), (999, 500), ("2", 2)])
def test_online_rank_return_top_k_clamps_invalid_values(value, expected):
    assert _rank_return_top_k(value) == expected


def test_tool_request_builder_keeps_string_arguments_as_scalar_values():
    request = _product_search_request_from_call(
        AgentToolCall(
            name="catalog_constraint_search",
            arguments={
                "keywords": "bluetooth",
                "required": "wireless",
                "disliked": "wired",
                "categories": "Audio",
                "not_categories": "Office",
            },
        ),
        AgentSession(session_id="s1", user_id="u1"),
        None,
        force_candidate_pool=False,
    )

    assert request.keywords
    assert request.keywords.keywords == ["bluetooth"]
    assert request.keywords.required == ["wireless"]
    assert request.keywords.disliked == ["wired"]
    assert request.category
    assert request.category.categories == ["Audio"]
    assert request.category.not_categories == ["Office"]


def test_runtime_boundary_source_restrictions():
    runtime_source = Path("rs_core/rsagent/runtime.py").read_text(encoding="utf-8")
    converse_source = inspect.getsource(HybridRecommendationEnvironment.converse)

    assert "recommend_for_user" not in runtime_source
    assert "load_popular" not in runtime_source
    assert "load_itemcf" not in runtime_source
    assert "candidate_merge" not in runtime_source
    assert "plan_dialogue_turn" not in converse_source
    assert "apply_dialogue_plan" not in converse_source
    assert "_recommendation_step" not in converse_source
    assert "_dialogue_only_turn" not in converse_source


def test_public_chat_feedback_and_export_do_not_expose_runtime_trace(tmp_path: Path):
    from rs_core.serving.service import RecommendationService

    service = RecommendationService(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session_id = service.start_session("u1")

    chat = service.chat(session_id, "For commute, prefer bluetooth and Audio")
    feedback = service.feedback(session_id, "why", item_id="speaker_1")
    export = service.export_session(session_id)

    public_payload = json.dumps([chat.display, feedback.display, export["display_responses"]])
    for term in ("agent_runtime_trace", "context_bundle", "session_summary", "user_profile", "memory_snapshot", "rag_context"):
        assert term not in public_payload


def test_context_bundle_preserves_summary_profile_and_archive_contract(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    env.converse(session, "For commute, prefer bluetooth and Audio")
    env.converse(session, "show me something different")

    summary = session.session_summary
    assert summary["current_goal"] == "preference_feedback"
    assert summary["preferred_categories"] == {"Audio": 1.0}
    assert summary["user_profile"]["preferred_keywords"]["bluetooth"] == 1.0
    assert summary["archived_turn_count"] == 2
    assert session.user_profile.preferred_categories == {"Audio": 1.0}
    assert len(session.archived_turn_summaries) == 2
    archived = session.archived_turn_summaries[0].to_dict()
    assert archived["item_ids"] == ["speaker_1", "earbuds_1", "charger_1"]
    assert "diagnostics" not in archived
    assert "rag_context" not in archived


class _Plan:
    intent = "preference_feedback"
    action = "revise_recommendation"
    assistant_response = "updated"
    should_recommend = True
    diagnostics: dict[str, object] = {}


class _OnlineRankOnlyRecommender:
    def readiness(self) -> dict[str, object]:
        return {"complete_pool500_available": True}


class _ToolHost:
    def __init__(self, turn: AgentTurn) -> None:
        from rs_core.rsagent.runtime import AgentRuntime

        self.runtime = AgentRuntime()
        self.turn = turn
        self.executed_phases: list[str] = []

    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None) -> _Plan:
        return _Plan()

    def apply_dialogue_plan(self, session: AgentSession, plan: _Plan) -> FeedbackConstraints:
        return session.active_constraints

    def build_recommendation_turn(self, session: AgentSession, user_input: str, assistant_response: str, merge_user_input: bool) -> AgentTurn:
        session.turns.append(self.turn)
        return self.turn

    def build_dialogue_turn(self, session: AgentSession, user_input: str, assistant_response: str) -> AgentTurn:
        raise AssertionError("dialogue branch should not be used")

    def execute_agent_tools(self, session: AgentSession, plan: _Plan, phase: str, turn: AgentTurn | None = None) -> dict[str, object]:
        self.executed_phases.append(phase)
        name = "fake_pre" if phase == "pre_recommendation" else "fake_post"
        return {
            "phase": phase,
            "results": [{"name": name, "phase": phase, "status": "ok", "event": {"tool_name": name, "status": "ok"}}],
            "summary": {"supported": True, "result_count": 1},
        }


class _ToolContextHost(_ToolHost):
    def __init__(self, turn: AgentTurn) -> None:
        super().__init__(turn)
        self.pre_context_seen: dict[str, object] | None = None
        self.build_context_seen: dict[str, object] | None = None
        self.post_context_seen: dict[str, object] | None = None

    def execute_agent_tools(
        self,
        session: AgentSession,
        plan: _Plan,
        phase: str,
        turn: AgentTurn | None = None,
        tool_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.executed_phases.append(phase)
        active_context = tool_context if tool_context is not None else {}
        if phase == "pre_recommendation":
            active_context["query_rag"] = {"semantic_query_hint": "portable bluetooth commute"}
            self.pre_context_seen = dict(active_context)
            name = "fake_pre"
        else:
            self.post_context_seen = dict(active_context)
            name = "fake_post"
        return {
            "phase": phase,
            "results": [{"name": name, "phase": phase, "status": "ok", "event": {"tool_name": name, "status": "ok"}}],
            "summary": {"supported": True, "result_count": 1},
        }

    def build_recommendation_turn(
        self,
        session: AgentSession,
        user_input: str,
        assistant_response: str,
        merge_user_input: bool,
        tool_context: dict[str, object] | None = None,
    ) -> AgentTurn:
        self.build_context_seen = dict(tool_context or {})
        session.turns.append(self.turn)
        return self.turn


class _StaticHost:
    def __init__(self, turn: AgentTurn) -> None:
        from rs_core.rsagent.runtime import AgentRuntime

        self.runtime = AgentRuntime()
        self.turn = turn
        self.plan_calls = 0
        self.plan_inputs: list[tuple[str, str, str | None]] = []
        self.build_recommendation_calls = 0

    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None) -> _Plan:
        self.plan_calls += 1
        self.plan_inputs.append((user_input, session.session_id, explanation_item_id))
        return _Plan()

    def apply_dialogue_plan(self, session: AgentSession, plan: _Plan) -> FeedbackConstraints:
        return session.active_constraints

    def build_recommendation_turn(self, session: AgentSession, user_input: str, assistant_response: str, merge_user_input: bool) -> AgentTurn:
        self.build_recommendation_calls += 1
        session.turns.append(self.turn)
        return self.turn

    def build_dialogue_turn(self, session: AgentSession, user_input: str, assistant_response: str) -> AgentTurn:
        raise AssertionError("dialogue branch should not be used")


def _empty_sequence(user_id: str) -> dict[str, object]:
    return {
        "user_id": user_id,
        "recent_item_sequence": [],
        "recent_positive_item_sequence": [],
        "recent_strong_positive_item_sequence": [],
    }


def _turn_with_items(constraints: FeedbackConstraints, items: list[dict[str, object]]) -> AgentTurn:
    decision = AgentDecision(
        user_id="u1",
        strategy_name="demo",
        trigger_reason="ranked_hybrid_candidates_available",
        agent_explanation="Uses popular source only.",
        risk_flags=[],
        limitations=[],
        final_items=[dict(item) for item in items],
    )
    return AgentTurn(
        turn_index=1,
        user_input="",
        feedback_constraints=constraints,
        recommendation=decision,
        candidates=[],
        ranking=[dict(item) for item in items],
        fallback_used=False,
        diagnostics={},
    )


def _write_runtime_fixture(root: Path) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{
        "user_id": "u1",
        "recent_item_sequence": ["seed_audio"],
        "recent_positive_item_sequence": ["seed_audio"],
        "recent_strong_positive_item_sequence": [],
    }])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5},
        {"parent_asin": "case_1", "category": "Accessories", "pop_score": 4},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker for commute"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [
        {"parent_asin": "earbuds_1", "score": 1.0, "category": "Audio", "title_clean": "Wireless bluetooth earbuds"},
    ]}])
    config = root / "config.yaml"
    config.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(root / "out"),
        "report_path": str(root / "report.md"),
        "top_k": 3,
        "candidate_pool_size": 10,
        "popular_fallback_count": 3,
        "rank_weights": {
            "popular": 1.0,
            "itemcf_weak": 1.0,
            "category": 1.0,
            "feedback_category": 10.0,
            "feedback_keyword": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
    }), encoding="utf-8")
    return config
