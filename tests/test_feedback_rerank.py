from __future__ import annotations

from rs_core.recsys.candidate_merge import RecallCandidate, merge_candidates
from rs_core.rsagent.feedback_rerank import apply_feedback_rerank
from rs_core.rsagent.policy import FeedbackConstraints
from rs_core.recsys.ranking import rank_candidates


def test_feedback_rerank_filters_disliked_item_and_demotes_itemcf_neighbors():
    candidates = merge_candidates([
        RecallCandidate("bad", "popular", 4.0),
        RecallCandidate("neighbor", "popular", 3.0),
        RecallCandidate("other", "popular", 2.0),
    ])
    itemcf_strong = {"bad": [RecallCandidate("neighbor", "itemcf_strong", 0.8)]}

    reranked, diagnostics = apply_feedback_rerank(
        candidates,
        FeedbackConstraints(disliked_item_ids={"bad"}),
        {},
        itemcf_strong,
        {"feedback_rerank": {"enabled": True, "negative_similarity_demote": 0.5}},
        turn_index=2,
    )

    assert [candidate.item_id for candidate in reranked] == ["neighbor", "other"]
    by_id = {candidate.item_id: candidate for candidate in reranked}
    assert by_id["neighbor"].source_scores["feedback_rerank"] == -0.4
    assert diagnostics["feedback_rerank_summary"]["filtered_item_count"] == 1
    assert diagnostics["feedback_rerank_summary"]["demoted_item_count"] == 1
    assert diagnostics["feedback_rerank_events"] == [
        {
            "type": "feedback_rerank",
            "action": "filter",
            "target_item_id": "bad",
            "source_item_id": "bad",
            "reason": "explicit_dislike",
            "turn_index": 2,
        },
        {
            "type": "feedback_rerank",
            "action": "demote",
            "target_item_id": "neighbor",
            "source_item_id": "bad",
            "reason": "itemcf_similarity_propagation",
            "similarity_source": "itemcf_strong",
            "similarity_score": 0.8,
            "delta": -0.4,
            "turn_index": 2,
        },
    ]


def test_feedback_rerank_boosts_liked_itemcf_neighbors_and_ranking_records_event():
    candidates = merge_candidates([
        RecallCandidate("neighbor", "popular", 1.0),
        RecallCandidate("other", "popular", 1.1),
    ])
    itemcf_weak = {"liked": [RecallCandidate("neighbor", "itemcf_weak", 0.9)]}
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "feedback_rerank": 1.0},
        "feedback_rerank": {"enabled": True, "positive_similarity_boost": 0.5, "similarity_sources": ["itemcf_weak"]},
    }

    reranked, diagnostics = apply_feedback_rerank(
        candidates,
        FeedbackConstraints(liked_item_ids={"liked"}),
        itemcf_weak,
        {},
        config,
        turn_index=2,
    )
    ranking = rank_candidates("u1", reranked, config)

    assert diagnostics["feedback_rerank_summary"]["boosted_item_count"] == 1
    assert ranking.items[0]["parent_asin"] == "neighbor"
    assert ranking.items[0]["agent_boost"] == 0.45
    assert ranking.items[0]["rerank_events"] == [
        {
            "type": "feedback_rerank",
            "action": "boost",
            "target_item_id": "neighbor",
            "source_item_id": "liked",
            "reason": "liked_item_anchor",
            "similarity_source": "itemcf_weak",
            "similarity_score": 0.9,
            "delta": 0.45,
            "turn_index": 2,
        }
    ]


def test_feedback_rerank_disabled_keeps_candidates_unchanged():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])

    reranked, diagnostics = apply_feedback_rerank(
        candidates,
        FeedbackConstraints(disliked_item_ids={"a"}),
        {},
        {"a": [RecallCandidate("b", "itemcf_strong", 1.0)]},
        {"feedback_rerank": {"enabled": False}},
    )

    assert reranked == candidates
    assert diagnostics == {"feedback_rerank_events": [], "feedback_rerank_summary": {}}


def test_feedback_rerank_preserves_constraint_filter_restored_candidate():
    candidates = merge_candidates([RecallCandidate("bad", "popular", 1.0)])
    candidates[0].metadata["constraint_filter_restored"] = True

    reranked, diagnostics = apply_feedback_rerank(
        candidates,
        FeedbackConstraints(disliked_item_ids={"bad"}),
        {},
        {},
        {"feedback_rerank": {"enabled": True, "negative_similarity_demote": 0.5}},
        turn_index=2,
    )

    assert [candidate.item_id for candidate in reranked] == ["bad"]
    assert diagnostics["feedback_rerank_summary"]["filtered_item_count"] == 0
