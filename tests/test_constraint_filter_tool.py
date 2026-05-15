from __future__ import annotations

from rs_core.recsys.candidate_merge import RecallCandidate, merge_candidates
from rs_core.rsagent.constraint_filter import apply_constraint_filter_tool, parse_constraint_filter_input
from rs_core.rsagent.schema import FeedbackConstraints


def test_parse_constraint_filter_extracts_explicit_negative_item_and_category_constraints():
    english = parse_constraint_filter_input("not headphones, please")
    chinese = parse_constraint_filter_input("不要耳机，通勤用")

    assert "headphones" in _negative_constraint_values(english)
    assert "headphones" in _negative_constraint_values(chinese)
    assert "commute" in chinese.preferred_keywords or "commute" in getattr(chinese, "use_cases", {})


def test_parse_constraint_filter_extracts_budget_and_use_case_aliases():
    budget = parse_constraint_filter_input("budget lower, something affordable for commute")
    gift = parse_constraint_filter_input("need a gift for my friend")

    assert (
        "cheap" in budget.preferred_keywords
        or "budget" in budget.preferred_keywords
        or getattr(budget, "max_price", None) is not None
    )
    assert "commute" in budget.preferred_keywords or "commute" in getattr(budget, "use_cases", {})
    assert "gift" in gift.preferred_keywords or "gift" in getattr(gift, "use_cases", {})


def test_constraint_filter_filters_candidates_and_records_bounded_events():
    candidates = merge_candidates([
        RecallCandidate("headphones_1", "popular", 5.0, category="Audio", metadata={"title_clean": "Wireless headphones"}),
        RecallCandidate("wired_1", "popular", 4.0, category="Accessories", metadata={"title_clean": "Wired charging cable"}),
        RecallCandidate("budget_1", "popular", 3.0, category="Accessories", metadata={"title_clean": "Affordable portable charger"}),
    ])

    filtered, diagnostics = apply_constraint_filter_tool(
        candidates,
        FeedbackConstraints(
            disliked_categories={"Audio"},
            disliked_keywords={"wired": 1.0},
            preferred_keywords={"cheap": 1.0},
        ),
        {"constraint_filter": {"enabled": True, "keyword_penalty": 0.5, "keyword_boost": 0.25, "min_candidates": 1}},
    )

    item_ids = [candidate.item_id for candidate in filtered]
    assert "headphones_1" not in item_ids
    assert "wired_1" in item_ids
    by_id = {candidate.item_id: candidate for candidate in filtered}
    assert by_id["wired_1"].source_scores["feedback_keyword_penalty"] == -0.5
    assert by_id["budget_1"].source_scores["feedback_keyword"] == 0.25
    assert diagnostics["constraint_filter_summary"] == {
        "filtered_item_count": 1,
        "penalized_item_count": 1,
        "boosted_item_count": 1,
        "over_filter_protected": False,
    }
    assert diagnostics["constraint_filter_events"] == [
        {
            "type": "constraint_filter",
            "action": "filter",
            "target_item_id": "headphones_1",
            "reason": "disliked_category",
            "item_id": "headphones_1",
            "matched_value": "Audio",
            "configured_value": "Audio",
        },
        {
            "type": "constraint_filter",
            "action": "penalize",
            "target_item_id": "wired_1",
            "reason": "disliked_keyword",
            "matched_value": "wired",
            "configured_value": "wired",
            "delta": -0.5,
        },
        {
            "type": "constraint_filter",
            "action": "boost",
            "target_item_id": "budget_1",
            "reason": "preferred_keyword",
            "matched_value": "cheap",
            "configured_value": "cheap",
            "delta": 0.25,
        },
    ]


def test_constraint_filter_keeps_minimum_candidates_when_constraints_over_filter():
    candidates = merge_candidates([
        RecallCandidate("a", "popular", 2.0, category="Audio"),
        RecallCandidate("b", "popular", 1.0, category="Audio"),
    ])

    filtered, diagnostics = apply_constraint_filter_tool(
        candidates,
        FeedbackConstraints(disliked_categories={"Audio"}),
        {"constraint_filter": {"enabled": True, "min_candidates": 1}},
    )

    assert [candidate.item_id for candidate in filtered] == ["b"]
    assert diagnostics["constraint_filter_summary"]["over_filter_protected"] is True
    assert diagnostics["constraint_filter_events"][-1] == {
        "type": "constraint_filter",
        "action": "protect",
        "target_item_id": "b",
        "reason": "over_filter_restored",
        "item_id": "b",
        "matched_value": "b",
        "configured_value": "min_candidate_protection",
    }


def _negative_constraint_values(constraints: FeedbackConstraints) -> set[str]:
    return {value.lower() for value in constraints.disliked_categories} | set(constraints.disliked_keywords)
