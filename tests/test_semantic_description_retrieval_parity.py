from __future__ import annotations

import json

import pytest

from rs_core.agent.rag.semantic_description import (
    candidate_ids_for_fixture,
    collect_ordered_unique_candidates,
    diagnose,
    load_query_buckets,
    load_records,
    ordered_unique,
    prioritized_fixture_terms,
    rank_fixture_candidates,
)

pytestmark = pytest.mark.unit


def test_streaming_candidate_collector_matches_raw_extend_order() -> None:
    buckets = {
        "mouse": ["b", "a", "c"],
        "wireless": ["a", "d"],
        "laptop": ["e", "b"],
    }
    token_order = ["mouse", "wireless", "laptop"]
    raw: list[str] = []
    for token in token_order:
        raw.extend(buckets[token])

    assert collect_ordered_unique_candidates(token_order, buckets, 4) == ordered_unique(raw, 4)


def test_candidate_ids_preserve_core_priority_and_sorted_remaining_terms() -> None:
    fixture = {
        "id": "wireless_mouse",
        "description": "wireless ergonomic computer mouse for office laptop",
        "core_terms": ["wireless", "mouse"],
        "must_terms": ["mouse"],
        "must_any_groups": [["wireless", "bluetooth"]],
        "intent_phrases": ["wireless mouse", "bluetooth mouse"],
        "category_any": ["computers"],
        "negative_phrases": ["mouse pad"],
    }
    query_terms = {"wireless", "mouse", "ergonomic", "computer", "laptop", "bluetooth", "computers", "pad"}
    buckets = {
        "wireless": ["core_wireless", "dup"],
        "mouse": ["core_mouse", "dup"],
        "bluetooth": ["non_core_bluetooth"],
        "computer": ["non_core_computer"],
        "computers": ["non_core_computers"],
        "ergonomic": ["non_core_ergonomic"],
        "laptop": ["non_core_laptop"],
        "pad": ["non_core_pad"],
    }

    token_order = prioritized_fixture_terms(fixture, query_terms)

    assert token_order[:2] == ["wireless", "mouse"]
    assert token_order[2:] == sorted(query_terms - {"wireless", "mouse"})
    assert candidate_ids_for_fixture(fixture, query_terms, buckets, candidate_limit=5) == [
        "core_wireless",
        "dup",
        "core_mouse",
        "non_core_bluetooth",
        "non_core_computer",
    ]


def test_rank_fixture_candidates_tie_breaks_by_item_id() -> None:
    fixture = {
        "id": "mouse",
        "description": "wireless mouse",
        "core_terms": ["mouse"],
        "must_terms": ["mouse"],
        "must_any_groups": [["wireless"]],
        "intent_phrases": ["wireless mouse"],
        "category_any": ["computers"],
        "negative_phrases": [],
    }
    records = {
        "b_item": {"parent_asin": "b_item", "title_clean": "Wireless Mouse", "main_category": "Computers"},
        "a_item": {"parent_asin": "a_item", "title_clean": "Wireless Mouse", "main_category": "Computers"},
    }
    rows = rank_fixture_candidates(
        fixture,
        ["b_item", "a_item"],
        records,
        {"wireless": 2, "mouse": 2, "computers": 2},
        document_count=100,
    )

    assert [row.item_id for row in rows] == ["a_item", "b_item"]


def test_diagnose_module_writes_no_label_contract(tmp_path) -> None:
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


def test_query_bucket_and_record_loaders_keep_existing_contract(tmp_path) -> None:
    inverted_index = tmp_path / "semantic_inverted_index.jsonl"
    semantic_inputs = tmp_path / "semantic_recall_inputs.jsonl"
    inverted_index.write_text(
        "\n".join(
            [
                json.dumps({"token": "mouse", "parent_asins": ["a", "b", "c"]}),
                json.dumps({"token": "keyboard", "item_ids": ["k"]}),
                json.dumps({"token": "ignored", "parent_asins": ["x"]}),
            ]
        ),
        encoding="utf-8",
    )
    semantic_inputs.write_text(
        "\n".join(
            [
                json.dumps({"parent_asin": "a", "title_clean": "A"}),
                json.dumps({"item_id": "b", "title_clean": "B"}),
                json.dumps({"parent_asin": "x", "title_clean": "X"}),
            ]
        ),
        encoding="utf-8",
    )

    buckets, doc_freq = load_query_buckets(inverted_index, {"mouse", "keyboard"}, per_token_limit=2)
    records = load_records(semantic_inputs, {"a", "b"})

    assert buckets == {"mouse": ["a", "b"], "keyboard": ["k"]}
    assert doc_freq == {"mouse": 3, "keyboard": 1}
    assert set(records) == {"a", "b"}
