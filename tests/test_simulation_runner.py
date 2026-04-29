import json
from pathlib import Path

from fastapi.testclient import TestClient

from rs_core.common.io import write_jsonl
from rs_core.serving import app as serving_app
from rs_core.serving.service import RecommendationService
from rs_core.simulation import COMMUTER_PRACTICAL, RoleActionType, run_simulation_scene

BLOCKED_PUBLIC_KEYS = {"ranking", "diagnostics", "reward", "reward_evidence", "score"}


def test_run_simulation_scene_returns_safe_scene_contract(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)

    scene = run_simulation_scene(service, COMMUTER_PRACTICAL, max_turns=3, user_id="u1", scene_id="scene-test")

    assert scene["scene_id"] == "scene-test"
    assert scene["role"]["role_id"] == "commuter_practical"
    assert scene["state"]["final_action"] in {action.value for action in RoleActionType}
    assert scene["actions"][0]["type"] == "chat"
    assert "daily commute" in scene["actions"][0]["message"]
    assert scene["session"]["session_id"]
    assert scene["session"]["turn_count"] >= 1
    assert scene["session"]["display_responses"]
    assert scene["state"]["seen_item_ids"]
    _assert_no_blocked_keys(scene)


def test_simulation_scene_endpoint_returns_scene_for_frontend(tmp_path: Path, monkeypatch):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        response = client.post("/simulation/scene", json={"role_id": "commuter_practical", "max_turns": 3, "user_id": "u1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"]["role_id"] == "commuter_practical"
    assert payload["session"]["events"][0]["type"] == "chat"
    assert payload["session"]["display_responses"][0]["schema_version"] == "rs_agent_display_v1"
    _assert_no_blocked_keys(payload)


def test_simulation_scene_endpoint_rejects_unknown_role(tmp_path: Path, monkeypatch):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        response = client.post("/simulation/scene", json={"role_id": "missing_role"})

    assert response.status_code == 422
    assert "Unknown simulation role_id" in response.json()["detail"]


def _assert_no_blocked_keys(value):
    if isinstance(value, dict):
        assert not BLOCKED_PUBLIC_KEYS & set(value)
        for child in value.values():
            _assert_no_blocked_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_keys(child)


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
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker for commute"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
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
            "category": 1.0,
            "feedback_category": 10.0,
            "feedback_keyword": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
    }), encoding="utf-8")
    return config
