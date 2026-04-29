from __future__ import annotations

import json
from pathlib import Path

from rs_core.common.io import read_jsonl, write_jsonl
from rs_core.rsagent.rollout import session_to_rollout_records
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


def test_vague_request_triggers_clarification_without_recommendation(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session()

    turn = env.converse(session, "I want headphones")

    assert turn.recommendation.trigger_reason == "clarification_needed"
    assert turn.ranking == []
    assert turn.diagnostics["conversation_intent"] == "recommend_request"
    assert turn.diagnostics["agent_action"] == "ask_clarifying_question"
    assert "clarification_question" in turn.diagnostics
    assert session.conversation_state.pending_clarification


def test_clarification_answer_updates_constraints_and_recommends(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session()
    env.converse(session, "I want headphones")

    turn = env.converse(session, "For commute, prefer bluetooth and Audio, avoid wired")

    assert turn.diagnostics["conversation_intent"] == "clarification_answer"
    assert session.conversation_state.pending_clarification == ""
    assert session.active_constraints.preferred_keywords["bluetooth"] == 1.0
    assert session.active_constraints.preferred_keywords["commute"] == 1.0
    assert session.active_constraints.disliked_keywords["wired"] == 1.0
    assert session.active_constraints.preferred_categories["Audio"] == 1.0
    assert turn.ranking[0]["parent_asin"] == "speaker_1"
    assert turn.diagnostics["boosts_applied"]


def test_why_request_explains_prior_turn_without_changing_constraints(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session()
    env.converse(session, "I want headphones")
    env.converse(session, "For commute, prefer bluetooth and Audio")
    constraints_before = session.active_constraints.to_dict()

    turn = env.converse(session, "why?")

    assert session.active_constraints.to_dict() == constraints_before
    assert turn.diagnostics["conversation_intent"] == "ask_explanation"
    assert turn.diagnostics["agent_action"] == "explain_recommendation"
    assert "speaker_1" in turn.assistant_response
    assert turn.ranking == []


def test_show_different_filters_prior_turn_items(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session()
    first = env.step(session, "")
    first_items = {item["parent_asin"] for item in first.ranking}

    turn = env.converse(session, "show me something different")

    assert session.active_constraints.filter_prior_turn_items is True
    assert turn.diagnostics["excluded_prior_turn_items"]
    assert not first_items & {item["parent_asin"] for item in turn.ranking}


def test_unsupported_free_text_is_preserved_across_turns_and_rollout(tmp_path: Path):
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path)), limit_users=1)
    session = env.start_session()

    env.converse(session, "make it match my living room vibe")
    env.converse(session, "prefer Audio")
    records = session_to_rollout_records(session, env.sequences_by_user[session.user_id])

    assert "make it match my living room vibe" in session.active_constraints.unsupported_free_text
    assert "make it match my living room vibe" in records[-1]["prompt_context"]["feedback_constraints"]["unsupported_free_text"]


def _write_dialogue_fixture(root: Path) -> Path:
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
