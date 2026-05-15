from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.serving]

from rs_core.common.io import write_jsonl
from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.reward import build_reward_evidence
from rs_core.rsagent.runtime import RUNTIME_TRACE_STEP_ORDER
from rs_core.rsagent.schema import AgentSession, AgentTurn, FeedbackConstraints
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


def test_converse_attaches_ordered_runtime_trace_and_summary(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session()

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


def test_memory_prefetch_changes_after_prior_turn_and_feedback(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_runtime_fixture(tmp_path)), limit_users=1)
    session = env.start_session()
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
    session = env.start_session()

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

    assert "agent_runtime_trace" not in json.dumps(chat.display)
    assert "agent_runtime_trace" not in json.dumps(feedback.display)
    assert "agent_runtime_trace" not in json.dumps(export["display_responses"])


class _Plan:
    intent = "preference_feedback"
    action = "revise_recommendation"
    assistant_response = "updated"
    should_recommend = True
    diagnostics: dict[str, object] = {}


class _StaticHost:
    def __init__(self, turn: AgentTurn) -> None:
        from rs_core.rsagent.runtime import AgentRuntime

        self.runtime = AgentRuntime()
        self.turn = turn
        self.plan_calls = 0
        self.build_recommendation_calls = 0

    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None) -> _Plan:
        self.plan_calls += 1
        return _Plan()

    def apply_dialogue_plan(self, session: AgentSession, plan: _Plan) -> FeedbackConstraints:
        return session.active_constraints

    def build_recommendation_turn(self, session: AgentSession, user_input: str, assistant_response: str, merge_user_input: bool) -> AgentTurn:
        self.build_recommendation_calls += 1
        session.turns.append(self.turn)
        return self.turn

    def build_dialogue_turn(self, session: AgentSession, user_input: str, assistant_response: str) -> AgentTurn:
        raise AssertionError("dialogue branch should not be used")


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
