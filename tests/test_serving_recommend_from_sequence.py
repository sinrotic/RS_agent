from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from rs_core.common.io import write_jsonl
from rs_core.serving import app as serving_app
from rs_core.serving.service import RecommendationService

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

BLOCKED_PUBLIC_KEYS = {
    "base_score",
    "coarse_score",
    "diagnostics",
    "final_score",
    "fine_score",
    "ground_truth",
    "label",
    "label_binary",
    "ranking",
    "rerank_score",
    "score",
    "score_trace",
    "source",
    "sources",
    "target_item",
    "training_samples",
}
BLOCKED_PUBLIC_TERMS = {
    "diagnostic",
    "ground_truth",
    "itemcf",
    "label",
    "label_binary",
    "ranking",
    "score_trace",
    "source",
    "target_item",
    "training",
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)
    with TestClient(serving_app.app) as test_client:
        yield test_client


def test_recommend_from_sequence_returns_display_items_without_session(client: TestClient) -> None:
    response = client.post("/recommend", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
        },
        "feedback_text": "prefer bluetooth Audio",
        "top_k": 2,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"]
    assert payload["candidate_count"] > 0
    assert payload["item_count"] == len(payload["items"])
    assert payload["item_count"] <= 2
    assert payload["display"]["schema_version"] == "rs_agent_display_v1"
    assert payload["display"]["session_id"] == payload["request_id"]
    assert payload["display"]["items"] == payload["items"]
    assert payload["items"]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_recommend_from_sequence_respects_top_k(client: TestClient) -> None:
    response = client.post("/recommend", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
        },
        "top_k": 1,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["item_count"] == 1
    assert len(payload["display"]["items"]) == 1


def test_recommend_from_sequence_rejects_oracle_fields(client: TestClient) -> None:
    response = client.post("/recommend", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
            "target_item": "speaker_1",
        },
        "top_k": 1,
    })

    assert response.status_code == 422
    assert "evaluation-only" in str(response.json()["detail"])


def test_recommend_from_sequence_rejects_nested_oracle_fields(client: TestClient) -> None:
    response = client.post("/recommend", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "metadata": {"ground_truth": ["speaker_1"]},
        },
    })

    assert response.status_code == 422
    assert "evaluation-only" in str(response.json()["detail"])


def test_recommend_from_sequence_rejects_complete_pool500_until_online_context_exists(client: TestClient) -> None:
    response = client.post("/recommend", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
        },
        "complete_pool500": True,
    })

    assert response.status_code == 422
    assert "complete_pool500" in response.json()["detail"]


def _assert_no_blocked_keys(value: Any) -> None:
    if isinstance(value, dict):
        assert not BLOCKED_PUBLIC_KEYS & set(value)
        for child in value.values():
            _assert_no_blocked_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_keys(child)


def _assert_no_blocked_public_terms(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _assert_no_blocked_public_terms(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_public_terms(child)
    elif isinstance(value, str):
        lowered = value.lower()
        for term in BLOCKED_PUBLIC_TERMS:
            assert term not in lowered


def _write_serving_fixture(root: Path) -> Path:
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
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5, "title_clean": "Compact wall charger"},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker for commute"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [
        {"src_item": "seed_audio", "dst_item": "headphones_1", "score": 3.0, "category": "Audio", "title_clean": "Wireless headphones for travel"},
    ])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
        {"parent_asin": "headphones_1", "main_category": "Audio"},
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
            "itemcf_strong": 1.0,
            "category": 1.0,
            "feedback_category": 10.0,
            "feedback_keyword": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
    }), encoding="utf-8")
    return config
