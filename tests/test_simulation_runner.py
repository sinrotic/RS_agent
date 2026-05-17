import pytest

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rs_core.common.io import write_jsonl
from rs_core.serving import app as serving_app
from rs_core.serving.service import RecommendationService
from rs_core.simulation import COMMUTER_PRACTICAL, RoleAction, RoleActionType, run_simulation_batch, run_simulation_scene
from scripts.evaluation.run_agent_evaluation import run_agent_evaluation, write_agent_evaluation_outputs
from scripts.evaluation.run_simulation_evaluation import write_simulation_evaluation_outputs

BLOCKED_PUBLIC_KEYS = {
    "ranking",
    "diagnostics",
    "reward",
    "reward_evidence",
    "score",
    "base_score",
    "agent_boost",
    "final_score",
    "training_samples",
    "tool_events",
    "constraint_filter_events",
    "scorecard",
    "judge_scores",
}
BLOCKED_PUBLIC_TERMS = {
    "agent_boost",
    "base_score",
    "diagnostic",
    "constraint_filter",
    "feedback_source",
    "final_score",
    "hybrid recall",
    "itemcf",
    "rank_weights",
    "ranked highest",
    "ranking",
    "recall source",
    "reward",
    "reward_evidence",
    "scorecard",
    "source",
    "training",
    "training_samples",
}


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
    _assert_public_payload(scene)


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
    _assert_public_payload(payload)


def test_simulation_why_action_uses_public_explanation_path(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    policy = _WhyOncePolicy()

    scene = run_simulation_scene(service, COMMUTER_PRACTICAL, max_turns=2, user_id="u1", policy=policy, scene_id="why-scene")

    assert scene["actions"][1]["type"] == RoleActionType.WHY.value
    assert scene["actions"][1]["action_type"] == "why"
    assert scene["session"]["events"][1]["type"] == "feedback"
    assert scene["session"]["events"][1]["action_type"] == "why"
    explained_item_id = scene["actions"][1]["item_id"]
    assert explained_item_id in scene["session"]["display_responses"][1]["assistant_message"]
    _assert_public_payload(scene)


def test_simulation_scene_endpoint_rejects_unknown_role(tmp_path: Path, monkeypatch):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        response = client.post("/simulation/scene", json={"role_id": "missing_role"})

    assert response.status_code == 422
    assert "Unknown simulation role_id" in response.json()["detail"]


def test_run_simulation_batch_returns_aggregate_metrics(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)

    batch = run_simulation_batch(
        service,
        role_ids=["commuter_practical", "gift_buyer"],
        max_turns=3,
        repeats=2,
        user_id="u1",
        batch_id="batch-test",
    )

    assert batch["batch_id"] == "batch-test"
    assert len(batch["scenes"]) == 4
    assert batch["summary"]["scene_count"] == 4
    assert batch["summary"]["role_count"] == 2
    assert set(batch["summary"]["roles"]) == {"commuter_practical", "gift_buyer"}
    for scene in batch["scenes"]:
        assert scene["metrics"]["turn_count"] == scene["session"]["turn_count"]
        assert scene["metrics"]["action_count"] == len(scene["actions"])
        assert scene["metrics"]["final_action"] in {action.value for action in RoleActionType}
        assert scene["session"]["display_responses"]
    _assert_public_payload(batch)


def test_run_simulation_batch_rejects_unknown_role(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)

    try:
        run_simulation_batch(service, role_ids=["missing_role"], max_turns=2)
    except KeyError as exc:
        assert exc.args[0] == "missing_role"
    else:
        raise AssertionError("expected missing role to raise KeyError")


def test_simulation_batch_endpoint_returns_safe_batch_contract(tmp_path: Path, monkeypatch):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        response = client.post("/simulation/batch", json={
            "role_ids": ["commuter_practical", "gift_buyer"],
            "max_turns": 3,
            "repeats": 1,
            "user_id": "u1",
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["scene_count"] == 2
    assert payload["summary"]["role_count"] == 2
    assert len(payload["scenes"]) == 2
    assert payload["scenes"][0]["metrics"]["turn_count"] >= 1
    _assert_public_payload(payload)


def test_simulation_batch_endpoint_rejects_unknown_role(tmp_path: Path, monkeypatch):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        response = client.post("/simulation/batch", json={"role_ids": ["missing_role"]})

    assert response.status_code == 422
    assert "Unknown simulation role_id: missing_role" in response.json()["detail"]


def test_agent_evaluation_outputs_baseline_and_enhanced_artifacts(tmp_path: Path):
    config = _write_serving_fixture(tmp_path)

    result = run_agent_evaluation(
        config=str(config),
        variants=["baseline", "enhanced_feedback_rerank"],
        limit_users=1,
        roles=["commuter_practical"],
        max_turns=3,
        repeats=1,
        user_id="u1",
        run_id="agent-eval-test",
    )
    paths = write_agent_evaluation_outputs(result, tmp_path / "agent_eval")

    saved = json.loads(paths["evaluation_path"].read_text(encoding="utf-8"))
    scorecard = json.loads(paths["scorecard_path"].read_text(encoding="utf-8"))
    signals = json.loads(paths["training_signals_path"].read_text(encoding="utf-8"))
    report = paths["report_path"].read_text(encoding="utf-8")
    assert saved["schema_version"] == "rs_agent_evaluation_run_v1"
    assert [variant["variant"] for variant in saved["variants"]] == ["baseline", "enhanced_feedback_rerank"]
    assert set(scorecard) == {"baseline", "enhanced_feedback_rerank"}
    assert signals["enhanced_feedback_rerank"]["trajectory_turn_count"] >= 1
    assert "Agent Evaluation Comparison Report" in report
    assert "enhanced_feedback_rerank" in report
    assert saved["variants"][0]["artifacts"][0]["rollouts"]
    _assert_public_payload(saved["variants"][0]["batch"])


def test_simulation_evaluation_outputs_write_json_metrics_and_report(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    batch = run_simulation_batch(
        service,
        role_ids=["commuter_practical"],
        max_turns=3,
        repeats=1,
        user_id="u1",
        batch_id="batch-output-test",
    )

    paths = write_simulation_evaluation_outputs(batch, tmp_path / "eval")

    saved_batch = json.loads(paths["batch_path"].read_text(encoding="utf-8"))
    saved_metrics = json.loads(paths["metrics_path"].read_text(encoding="utf-8"))
    report = paths["report_path"].read_text(encoding="utf-8")
    assert saved_batch["batch_id"] == "batch-output-test"
    assert saved_metrics["summary"]["scene_count"] == 1
    assert "Simulation Evaluation Report" in report
    assert "commuter_practical" in report
    _assert_public_payload(saved_batch)


class _WhyOncePolicy:
    def next_action(self, role, state, display_response):
        state.remember_display(display_response)
        return RoleAction.why(display_response["items"][0]["parent_asin"])


def _assert_public_payload(value):
    _assert_no_blocked_keys(value)
    _assert_no_blocked_public_terms(value)


def _assert_no_blocked_keys(value):
    if isinstance(value, dict):
        assert not BLOCKED_PUBLIC_KEYS & set(value)
        for child in value.values():
            _assert_no_blocked_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_keys(child)


def _assert_no_blocked_public_terms(value):
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
