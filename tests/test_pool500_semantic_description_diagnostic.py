from __future__ import annotations

import pytest

import json

from scripts.experiments.recall.pool500.diagnose_semantic_description_recall import diagnose, evaluate_intent, score_record

pytestmark = pytest.mark.unit


def test_strict_description_intent_requires_core_type_and_category() -> None:
    fixture = {
        "description": "baby stroller organizer bag with cup holder",
        "core_terms": ["baby", "stroller"],
        "must_terms": ["stroller"],
        "must_any_groups": [["baby", "infant"], ["organizer", "bag", "holder"]],
        "intent_phrases": ["stroller organizer", "baby stroller"],
        "category_any": ["baby"],
        "negative_phrases": ["desk organizer", "pencil", "office"],
    }
    good_record = {
        "title_clean": "Universal Baby Stroller Organizer Bag with Cup Holder",
        "main_category": "Baby Products",
        "description_text": "stroller organizer for infant travel",
    }
    bad_record = {
        "title_clean": "Desk Organizer Pen Cup Pencil Holder",
        "main_category": "Office Products",
        "description_text": "desktop organizer cup holder for office supplies",
    }

    good_intent = evaluate_intent(fixture, good_record)
    bad_intent = evaluate_intent(fixture, bad_record)

    assert good_intent["strict_intent_pass"]
    assert "baby" in good_intent["category_hits"]
    assert not bad_intent["strict_intent_pass"]
    assert "stroller" in bad_intent["missing_must_terms"]
    assert bad_intent["negative_hits"]


def test_strict_description_score_penalizes_wrong_product_type() -> None:
    fixture = {
        "description": "wireless ergonomic computer mouse for office laptop",
        "core_terms": ["wireless", "mouse"],
        "must_terms": ["mouse"],
        "must_any_groups": [["wireless", "bluetooth"]],
        "intent_phrases": ["wireless mouse", "bluetooth mouse"],
        "category_any": ["electronics", "computers"],
        "negative_phrases": ["mouse pad", "wrist rest"],
    }
    doc_freq = {"wireless": 10, "mouse": 10, "ergonomic": 50, "computer": 50, "laptop": 50}
    good_record = {
        "title_clean": "Bluetooth Wireless Mouse for Laptop Computer",
        "main_category": "Computers",
        "description_text": "ergonomic mouse for office laptop",
    }
    bad_record = {
        "title_clean": "Ergonomic Mouse Pad with Wrist Rest for Computer",
        "main_category": "Office Products",
        "description_text": "mouse pad for laptop office desk",
    }

    good_score, good_details = score_record(fixture, good_record, doc_freq, document_count=1000)
    bad_score, bad_details = score_record(fixture, bad_record, doc_freq, document_count=1000)

    assert good_details["strict_intent_pass"]
    assert not bad_details["strict_intent_pass"]
    assert bad_details["negative_hits"] == ["mouse pad", "wrist rest"]
    assert good_score > bad_score


def test_diagnose_writes_no_label_strict_summary_contract(tmp_path) -> None:
    semantic_inputs = tmp_path / "semantic_recall_inputs.jsonl"
    inverted_index = tmp_path / "semantic_inverted_index.jsonl"
    output_dir = tmp_path / "out"
    records = [
        {
            "parent_asin": "good_mouse",
            "title_clean": "Bluetooth Wireless Mouse for Laptop Computer",
            "main_category": "Computers",
            "description_text": "ergonomic mouse for office laptop",
        },
        {
            "parent_asin": "bad_pad",
            "title_clean": "Ergonomic Mouse Pad with Wrist Rest for Computer",
            "main_category": "Office Products",
            "description_text": "mouse pad for laptop office desk",
        },
    ]
    semantic_inputs.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    buckets = {
        "wireless": ["good_mouse"],
        "mouse": ["good_mouse", "bad_pad"],
        "bluetooth": ["good_mouse"],
        "computer": ["good_mouse", "bad_pad"],
        "laptop": ["good_mouse", "bad_pad"],
    }
    inverted_index.write_text(
        "\n".join(json.dumps({"token": token, "parent_asins": item_ids}) for token, item_ids in buckets.items()),
        encoding="utf-8",
    )
    fixtures = [
        {
            "id": "wireless_mouse",
            "description": "wireless ergonomic computer mouse for office laptop",
            "core_terms": ["wireless", "mouse"],
            "must_terms": ["mouse"],
            "must_any_groups": [["wireless", "bluetooth"]],
            "intent_phrases": ["wireless mouse", "bluetooth mouse"],
            "category_any": ["computers"],
            "negative_phrases": ["mouse pad", "wrist rest"],
        }
    ]

    result = diagnose(
        semantic_inputs_path=semantic_inputs,
        inverted_index_path=inverted_index,
        output_dir=output_dir,
        fixtures=fixtures,
        per_token_limit=10,
        candidate_limit=10,
        top_k=10,
        document_count=1000,
    )
    report = json.loads((output_dir / "semantic_description_recall_strict_report.json").read_text(encoding="utf-8"))

    assert result["summary"]["label_inputs_role"] == "not_used"
    assert not result["summary"]["oracle_label_injection"]
    assert report["summary"]["eval_scope"] == "train_metadata_description_diagnostic_only"
    assert report["queries"][0]["top10"][0]["item_id"] == "good_mouse"
    assert report["queries"][0]["top10"][0]["strict_intent_pass"]
