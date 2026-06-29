from __future__ import annotations

import pytest

from rs_core.agent.rag.semantic_description import (
    evaluate_intent,
    evaluate_prepared_intent,
    normalized_text,
    phrase_present,
    prepare_fixture,
    prepare_record,
    record_text,
    score_prepared_record,
    score_record,
    tokens,
)

pytestmark = pytest.mark.unit


def test_semantic_description_text_helpers_preserve_normalization() -> None:
    assert tokens(["Wireless", "mouse-pad", "and", "2.4GHz"]) == ["wireless", "mouse", "pad", "4ghz"]
    assert normalized_text("Wireless mouse, and pack") == "wireless mouse"
    assert phrase_present("wireless ergonomic mouse", "ergonomic mouse")
    assert not phrase_present("wireless ergonomic mouse", "mouse pad")
    assert record_text({"title_clean": "Wireless Mouse", "main_category": "Computers"}, fields=["title_clean"]) == "wireless mouse"


def test_prepared_intent_matches_public_wrapper() -> None:
    fixture = {
        "description": "wireless ergonomic computer mouse for office laptop",
        "core_terms": ["wireless", "mouse"],
        "must_terms": ["mouse"],
        "must_any_groups": [["wireless", "bluetooth"]],
        "intent_phrases": ["wireless mouse", "bluetooth mouse"],
        "category_any": ["electronics", "computers"],
        "negative_phrases": ["mouse pad", "wrist rest"],
    }
    record = {
        "title_clean": "Ergonomic Mouse Pad with Wrist Rest for Computer",
        "main_category": "Office Products",
        "description_text": "mouse pad for laptop office desk",
    }

    assert evaluate_prepared_intent(prepare_fixture(fixture), prepare_record(record)) == evaluate_intent(fixture, record)


def test_prepared_score_matches_public_wrapper() -> None:
    fixture = {
        "description": "baby stroller organizer bag with cup holder",
        "core_terms": ["baby", "stroller"],
        "must_terms": ["stroller"],
        "must_any_groups": [["baby", "infant"], ["organizer", "bag", "holder"]],
        "intent_phrases": ["stroller organizer", "baby stroller"],
        "category_any": ["baby"],
        "negative_phrases": ["desk organizer", "pencil", "office"],
    }
    record = {
        "title_clean": "Universal Baby Stroller Organizer Bag with Cup Holder",
        "main_category": "Baby Products",
        "description_text": "stroller organizer for infant travel",
    }
    doc_freq = {"baby": 5, "stroller": 3, "organizer": 10, "bag": 20, "holder": 30}

    assert score_prepared_record(prepare_fixture(fixture), prepare_record(record), doc_freq, document_count=1000) == score_record(
        fixture,
        record,
        doc_freq,
        document_count=1000,
    )
