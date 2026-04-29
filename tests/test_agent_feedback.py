from __future__ import annotations

from rs_core.recsys.candidate_merge import RecallCandidate, merge_candidates
from rs_core.rsagent.policy import FeedbackConstraints, apply_feedback_to_candidates, parse_feedback
from rs_core.workflow.hybrid_demo import recommend_for_user


def test_parse_feedback_keeps_mixed_positive_and_negative_intents_separate():
    feedback = parse_feedback("I dislike charger_1 and Accessories, prefer Audio and semantic")

    assert feedback.disliked_item_ids == {"charger_1"}
    assert feedback.disliked_categories == {"Accessories"}
    assert feedback.preferred_categories == {"Audio": 1.0}
    assert feedback.preferred_sources == {"semantic": 1.0}


def test_parse_feedback_extracts_keyword_signals():
    feedback = parse_feedback("I prefer bluetooth and long battery for commute, avoid wired")

    assert feedback.preferred_keywords == {"bluetooth": 1.0, "long_battery": 1.0, "commute": 1.0}
    assert feedback.disliked_keywords == {"wired": 1.0}
    assert feedback.preferred_categories == {}
    assert feedback.disliked_categories == set()
    assert feedback.unsupported_free_text == []


def test_recommend_for_user_applies_feedback_exclusion_and_boosts():
    sequence = {"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": [], "recent_strong_positive_item_sequence": []}
    popular = [RecallCandidate("charger_1", "popular", 5.0, category="Accessories")]
    itemcf_weak = {"seed_audio": [RecallCandidate("speaker_1", "itemcf_weak", 2.0, category="Audio")]}
    itemcf_strong = {}
    category_top = {"main::Audio": [RecallCandidate("earbuds_1", "category", 1.0, category="Audio")]}
    item_category = {"seed_audio": "Audio"}
    seeded_sequence = {**sequence, "recent_positive_item_sequence": ["seed_audio"]}
    config = {
        "top_k": 3,
        "candidate_pool_size": 10,
        "popular_fallback_count": 3,
        "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0, "category": 1.0, "feedback_category": 10.0, "feedback_source_itemcf_weak": 10.0},
        "feedback_category_boost": 1.0,
        "feedback_source_boost": 1.0,
    }

    first = recommend_for_user(seeded_sequence, popular, itemcf_weak, itemcf_strong, category_top, item_category, config)
    assert "charger_1" in [item["parent_asin"] for item in first.ranking.items]

    feedback = FeedbackConstraints(
        disliked_item_ids={"charger_1"},
        disliked_categories={"accessories"},
        preferred_categories={"audio": 1.0},
        preferred_sources={"ITEMCF_WEAK": 1.0},
    )
    second = recommend_for_user(
        seeded_sequence,
        popular,
        itemcf_weak,
        itemcf_strong,
        category_top,
        item_category,
        config,
        feedback_constraints=feedback,
    )

    items = [item["parent_asin"] for item in second.ranking.items]
    assert "charger_1" not in items
    assert items[0] == "speaker_1"
    assert second.diagnostics["excluded_items"] == ["charger_1"]
    assert second.diagnostics["preferred_categories"] == {"audio": 1.0}
    assert second.diagnostics["boosts_applied"]["speaker_1"] == ["category:Audio", "source:itemcf_weak"]
    assert second.diagnostics["boost_events"]["speaker_1"] == [
        {"type": "preferred_category", "matched_value": "Audio", "configured_value": "audio", "score_key": "feedback_category", "boost": 1.0},
        {"type": "preferred_source", "matched_value": "itemcf_weak", "configured_value": "ITEMCF_WEAK", "score_key": "feedback_source_itemcf_weak", "boost": 1.0},
    ]
    assert second.diagnostics["filter_events"] == [
        {"item_id": "charger_1", "type": "disliked_item", "matched_value": "charger_1", "configured_value": "charger_1"}
    ]
    assert second.ranking.items[0]["base_score"] == 2.0
    assert second.ranking.items[0]["agent_boost"] == 20.0
    assert second.ranking.items[0]["final_score"] == 22.0
    assert second.ranking.items[0]["score"] == second.ranking.items[0]["final_score"]


def test_keyword_boost_and_penalty_use_candidate_metadata():
    candidates = merge_candidates([
        RecallCandidate("match", "semantic", 1.0, category="Audio", metadata={"title_clean": "Bluetooth headphones", "description_text": "Long battery life for commute"}),
        RecallCandidate("penalized", "semantic", 5.0, category="Audio", metadata={"title_clean": "Wired cable headphones"}),
        RecallCandidate("plain", "popular", 3.0, category="Audio"),
    ])
    filtered, diagnostics = apply_feedback_to_candidates(
        candidates,
        FeedbackConstraints(preferred_keywords={"bluetooth": 1.0, "long_battery": 1.0}, disliked_keywords={"wired": 1.0}),
        {"feedback_keyword_boost": 1.0, "feedback_keyword_penalty": 1.0},
    )

    by_id = {candidate.item_id: candidate for candidate in filtered}
    assert "feedback_keyword" in by_id["match"].sources
    assert by_id["match"].source_scores["feedback_keyword"] == 1.0
    assert "feedback_keyword_penalty" in by_id["penalized"].sources
    assert by_id["penalized"].source_scores["feedback_keyword_penalty"] == -1.0
    assert by_id["plain"].sources == ["popular"]
    assert diagnostics["preferred_keywords"] == {"bluetooth": 1.0, "long_battery": 1.0}
    assert diagnostics["disliked_keywords"] == {"wired": 1.0}
    assert [event["type"] for event in diagnostics["boost_events"]["match"]] == ["preferred_keyword", "preferred_keyword"]
    assert diagnostics["boost_events"]["penalized"] == [
        {
            "type": "disliked_keyword",
            "matched_value": "wired",
            "configured_value": "wired",
            "matched_alias": "wired",
            "score_key": "feedback_keyword_penalty",
            "boost": -1.0,
            "metadata_fields": ["title_clean"],
        }
    ]


def test_keyword_score_contribution_is_agent_boost():
    sequence = {"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": ["seed"], "recent_strong_positive_item_sequence": []}
    popular = []
    itemcf_weak = {"seed": [RecallCandidate("headphones", "itemcf_weak", 2.0, category="Audio", metadata={"title_clean": "Bluetooth headphones"})]}
    config = {
        "top_k": 1,
        "candidate_pool_size": 10,
        "rank_weights": {"itemcf_weak": 1.0, "feedback_keyword": 10.0},
        "feedback_keyword_boost": 1.0,
    }

    result = recommend_for_user(
        sequence,
        popular,
        itemcf_weak,
        {},
        {},
        {"seed": "Audio"},
        config,
        feedback_constraints=FeedbackConstraints(preferred_keywords={"bluetooth": 1.0}),
    )

    item = result.ranking.items[0]
    assert item["parent_asin"] == "headphones"
    assert item["base_score"] == 2.0
    assert item["agent_boost"] == 10.0
    assert item["final_score"] == 12.0
    assert item["score"] == item["final_score"]


def test_parse_feedback_recognizes_show_different_as_prior_turn_filter():
    feedback = parse_feedback("show me something different")

    assert feedback.filter_prior_turn_items is True



def test_prior_turn_filter_excludes_repeated_items():
    candidates = merge_candidates([RecallCandidate("a", "popular", 2.0), RecallCandidate("b", "popular", 1.0)])
    filtered, diagnostics = apply_feedback_to_candidates(
        candidates,
        FeedbackConstraints(filter_prior_turn_items=True),
        {},
        prior_turn_items={"a"},
    )

    assert [candidate.item_id for candidate in filtered] == ["b"]
    assert diagnostics["prior_turn_items"] == ["a"]
    assert diagnostics["excluded_prior_turn_items"] == ["a"]
    assert diagnostics["filter_events"] == [
        {"item_id": "a", "type": "prior_turn_item", "matched_value": "a", "configured_value": "a"}
    ]
