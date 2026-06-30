from __future__ import annotations

import json

import pytest

from rs_core.agent.rag.semantic_description import SQLiteSemanticDescriptionStore, build_sqlite_semantic_description_index, diagnose

pytestmark = pytest.mark.unit


def test_sqlite_semantic_description_store_matches_jsonl_backend(tmp_path) -> None:
    semantic_inputs = tmp_path / "semantic_recall_inputs.jsonl"
    inverted_index = tmp_path / "semantic_inverted_index.jsonl"
    index_path = tmp_path / "semantic_description.sqlite"
    manifest_path = tmp_path / "semantic_description.sqlite.manifest.json"
    jsonl_output = tmp_path / "jsonl_out"
    sqlite_output = tmp_path / "sqlite_out"

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
        {
            "parent_asin": "other_keyboard",
            "title_clean": "Mechanical Keyboard",
            "main_category": "Computers",
            "description_text": "keyboard for pc",
        },
    ]
    semantic_inputs.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    buckets = {
        "wireless": ["good_mouse"],
        "mouse": ["good_mouse", "bad_pad"],
        "bluetooth": ["good_mouse"],
        "computer": ["good_mouse", "bad_pad"],
        "laptop": ["good_mouse", "bad_pad"],
        "computers": ["good_mouse", "other_keyboard"],
        "pad": ["bad_pad"],
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

    manifest = build_sqlite_semantic_description_index(
        semantic_inputs_path=semantic_inputs,
        inverted_index_path=inverted_index,
        index_path=index_path,
        manifest_path=manifest_path,
        overwrite=True,
    )
    jsonl_result = diagnose(
        semantic_inputs_path=semantic_inputs,
        inverted_index_path=inverted_index,
        output_dir=jsonl_output,
        fixtures=fixtures,
        per_token_limit=10,
        candidate_limit=10,
        top_k=10,
        document_count=1000,
    )
    sqlite_result = diagnose(
        semantic_inputs_path=semantic_inputs,
        inverted_index_path=inverted_index,
        output_dir=sqlite_output,
        fixtures=fixtures,
        per_token_limit=10,
        candidate_limit=10,
        top_k=10,
        document_count=1000,
        store=SQLiteSemanticDescriptionStore(index_path),
    )

    assert manifest["postings_order_preserved"]
    assert manifest["record_json_preserved"]
    assert manifest["label_inputs_role"] == "not_used"
    assert not manifest["oracle_label_injection"]
    assert _stable_report(jsonl_output / "semantic_description_recall_strict_report.json") == _stable_report(
        sqlite_output / "semantic_description_recall_strict_report.json"
    )
    assert {k: v for k, v in jsonl_result["summary"].items() if k != "created_at"} == {
        k: v for k, v in sqlite_result["summary"].items() if k != "created_at"
    }


def _stable_report(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"].pop("created_at", None)
    return payload
