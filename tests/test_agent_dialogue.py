from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.io import write_jsonl
from rs_core.rsagent.dialogue import plan_dialogue_turn
from rs_core.rsagent.rollout import session_to_rollout_records
from rs_core.rsagent.schema import AgentSession, DIALOGUE_PLAN_ACTIONS, DIALOGUE_PLAN_INTENTS
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


@pytest.mark.parametrize("user_input", [
    "",
    "For commute, prefer bluetooth and Audio",
    "why?",
    "I want headphones",
    "make it match my living room vibe",
])
def test_dialogue_plan_outputs_are_allowlisted(user_input: str):
    plan = plan_dialogue_turn(user_input, AgentSession(session_id="s1", user_id="u1"))

    assert plan.intent in DIALOGUE_PLAN_INTENTS
    assert plan.action in DIALOGUE_PLAN_ACTIONS


def test_clarification_dialogue_plan_output_is_allowlisted():
    session = AgentSession(session_id="s1", user_id="u1")
    session.conversation_state.pending_clarification = "Do you care more about commute use?"

    plan = plan_dialogue_turn("For commute, prefer bluetooth and Audio", session)

    assert plan.intent in DIALOGUE_PLAN_INTENTS
    assert plan.action in DIALOGUE_PLAN_ACTIONS


def test_vague_request_triggers_clarification_without_recommendation(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    turn = env.converse(session, "I want something")

    assert turn.recommendation.trigger_reason == "clarification_needed"
    assert turn.ranking == []
    assert turn.diagnostics["conversation_intent"] == "recommend_request"
    assert turn.diagnostics["agent_action"] == "ask_clarifying_question"
    assert "clarification_question" in turn.diagnostics
    assert session.conversation_state.pending_clarification


@pytest.mark.parametrize("user_input", ["I want headphones", "I want TV", "想要耳机"])
def test_concrete_request_recommends_without_blocking_clarification(tmp_path: Path, user_input: str):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    turn = env.converse(session, user_input)

    assert turn.diagnostics["conversation_intent"] == "recommend_request"
    assert turn.diagnostics["agent_action"] == "recommend_items"
    assert turn.ranking
    assert session.conversation_state.pending_clarification == ""


def test_generic_quality_request_still_triggers_clarification(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    turn = env.converse(session, "I want something good")

    assert turn.ranking == []
    assert turn.diagnostics["agent_action"] == "ask_clarifying_question"
    assert session.conversation_state.pending_clarification


def test_clarification_answer_updates_constraints_and_recommends(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    env.converse(session, "I want something")

    turn = env.converse(session, "For commute, prefer bluetooth and Audio, avoid wired")

    assert turn.diagnostics["conversation_intent"] == "clarification_answer"
    assert session.conversation_state.pending_clarification == ""
    assert session.active_constraints.preferred_keywords["bluetooth"] == 1.0
    assert session.active_constraints.preferred_keywords["commute"] == 1.0
    assert session.active_constraints.disliked_keywords["wired"] == 1.0
    assert session.active_constraints.preferred_categories["Audio"] == 1.0
    assert turn.ranking[0]["parent_asin"] == "speaker_1"
    assert turn.diagnostics["boosts_applied"]


def test_pending_clarification_takes_priority_over_why_word(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    env.converse(session, "I want something")

    turn = env.converse(session, "为什么不先按 budget 推荐便宜一点")

    assert turn.diagnostics["conversation_intent"] == "clarification_answer"
    assert turn.diagnostics["clarification_route"] == "pending_clarification_priority"
    assert session.conversation_state.pending_clarification == ""
    assert session.active_constraints.preferred_keywords["cheap"] == 1.0
    assert turn.ranking


def test_bare_why_during_pending_clarification_stays_explanation_request(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    env.converse(session, "I want something")
    pending_question = session.conversation_state.pending_clarification

    turn = env.converse(session, "why?")

    assert turn.diagnostics["conversation_intent"] == "ask_explanation"
    assert turn.diagnostics["agent_action"] == "explain_recommendation"
    assert session.conversation_state.pending_clarification == pending_question
    assert turn.ranking == []


def test_why_request_explains_prior_turn_without_changing_constraints(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    env.converse(session, "I want something")
    env.converse(session, "For commute, prefer bluetooth and Audio")
    constraints_before = session.active_constraints.to_dict()

    turn = env.converse(session, "why?")

    assert session.active_constraints.to_dict() == constraints_before
    assert turn.diagnostics["conversation_intent"] == "ask_explanation"
    assert turn.diagnostics["agent_action"] == "explain_recommendation"
    assert "speaker_1" in turn.assistant_response
    assert turn.ranking == []


def test_why_request_without_prior_recommendation_returns_public_fallback(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    turn = env.converse(session, "为什么推荐？")

    assert turn.assistant_response == "我现在还没有可以解释的最近推荐。你可以先让我推荐一些商品，然后再问为什么推荐其中某一件。"
    assert turn.ranking == []


def test_why_request_for_stale_item_returns_public_fallback(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    env.converse(session, "For commute, prefer bluetooth and Audio")

    turn = env.converse(session, "why? item_id=stale_item_1")

    assert turn.assistant_response == "我只能解释最近一次推荐列表里的商品。"
    assert turn.ranking == []


def test_why_request_targets_latest_recommendation_item_after_dialogue_only_turns(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    env.converse(session, "For commute, prefer bluetooth and Audio")
    env.converse(session, "why? item_id=speaker_1")

    turn = env.converse(session, "why? item_id=speaker_1")

    assert "speaker_1" in turn.assistant_response
    assert turn.assistant_response != "我只能解释最近一次推荐列表里的商品。"
    assert turn.diagnostics["explanation_source_turn"] == 1
    assert turn.ranking == []


def test_show_different_filters_prior_turn_items(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")
    first = env.step(session, "")
    first_items = {item["parent_asin"] for item in first.ranking}

    turn = env.converse(session, "show me something different")

    assert session.active_constraints.filter_prior_turn_items is True
    assert turn.diagnostics["excluded_prior_turn_items"]
    assert not first_items & {item["parent_asin"] for item in turn.ranking}


def test_rag_off_preserves_prior_explanation_output(tmp_path: Path):
    base_env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path / "base")), limit_users=1)
    base_session = base_env.start_session("u1")
    base_env.converse(base_session, "For commute, prefer bluetooth and Audio")
    base_turn = base_env.converse(base_session, "why? item_id=speaker_1")

    off_env = HybridRecommendationEnvironment.from_config(
        str(_write_rag_dialogue_fixture(tmp_path / "off", {"evidence_mode": "off"})),
        limit_users=1,
    )
    off_session = off_env.start_session("u1")
    recommendation_turn = off_env.converse(off_session, "For commute, prefer bluetooth and Audio")
    off_turn = off_env.converse(off_session, "why? item_id=speaker_1")

    assert recommendation_turn.rag_context is None
    assert off_turn.assistant_response == base_turn.assistant_response


def test_rag_shadow_builds_context_without_changing_explanation(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(
        str(_write_rag_dialogue_fixture(tmp_path, {"evidence_mode": "shadow", "max_evidence_per_item": 2})),
        limit_users=1,
    )
    session = env.start_session("u1")
    recommendation_turn = env.converse(session, "For commute, prefer bluetooth and Audio")

    turn = env.converse(session, "why? item_id=speaker_1")

    assert recommendation_turn.rag_context is not None
    assert recommendation_turn.rag_context["metadata"]["evidence_mode"] == "shadow"
    records = session_to_rollout_records(session, env.sequences_by_user[session.user_id])
    assert recommendation_turn.diagnostics["rag"]["kept_evidence_count"] > 0
    assert records[0]["metadata"]["rag_context"] == recommendation_turn.rag_context
    assert "rag_context" not in records[0]["display_response"]
    assert "商品信息显示" not in turn.assistant_response
    assert "consumed_by_explanation" not in recommendation_turn.rag_context["metadata"]


def test_rag_explain_uses_evidence_without_mutating_recommendation_payload(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(
        str(_write_rag_dialogue_fixture(tmp_path, {"evidence_mode": "explain", "max_evidence_per_item": 2})),
        limit_users=1,
    )
    session = env.start_session("u1")
    recommendation_turn = env.converse(session, "For commute, prefer bluetooth and Audio")
    before = deepcopy(
        {
            "candidates": recommendation_turn.candidates,
            "ranking": recommendation_turn.ranking,
            "final_items": recommendation_turn.recommendation.final_items,
        }
    )

    turn = env.converse(session, "why? item_id=speaker_1")

    assert "商品信息显示" in turn.assistant_response
    assert "Audio" in turn.assistant_response
    assert "consumed_by_explanation" not in recommendation_turn.rag_context["metadata"]
    assert "consumed_by_explanation" not in recommendation_turn.diagnostics["rag"]
    assert before == {
        "candidates": recommendation_turn.candidates,
        "ranking": recommendation_turn.ranking,
        "final_items": recommendation_turn.recommendation.final_items,
    }


def test_unsupported_free_text_is_preserved_across_turns_and_rollout(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session("u1")

    env.converse(session, "make it match my living room vibe")
    env.converse(session, "prefer Audio")
    records = session_to_rollout_records(session, env.sequences_by_user[session.user_id])

    assert "make it match my living room vibe" in session.active_constraints.unsupported_free_text
    assert "make it match my living room vibe" in records[-1]["prompt_context"]["feedback_constraints"]["unsupported_free_text"]


def _write_rag_dialogue_fixture(root: Path, rag: dict[str, object]) -> Path:
    config = _write_dialogue_fixture(root)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["rag"] = rag
    config.write_text(json.dumps(payload), encoding="utf-8")
    return config


def _write_dialogue_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
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
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker for commute"}])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [
        {"parent_asin": "earbuds_1", "score": 1.0, "category": "Audio", "title_clean": "Wireless bluetooth earbuds"},
        {"parent_asin": "headset_1", "score": 0.5, "category": "Audio", "title_clean": "Wired headset"},
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
            "feedback_keyword_penalty": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
        "feedback_keyword_penalty": 1.0,
    }), encoding="utf-8")
    return config
