from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qdrant_fakes import install_fake_qdrant
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
SERVING_GOVERNANCE = {
    "promotion_allowed": False,
    "pool1000_allowed": False,
    "ranking_input_replacement_allowed": False,
    "final_pool500_ready_claimed": False,
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


def test_recommend_from_sequence_uses_configured_pool500_context(client: TestClient) -> None:
    response = client.post("/recommend", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
        },
        "complete_pool500": True,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_count"] > 0
    assert payload["items"]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_bad_pool500_artifact_degrades_to_demo_route_without_public_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    bad_pool500 = tmp_path / "bad_pool500_candidates.jsonl"
    write_jsonl(bad_pool500, [
        {
            "user_id": "online-u1",
            "item_id": "bad_internal_item_1",
            "source": "semantic",
            "score": 1.0,
            "metadata": {"label_binary": 1},
        }
    ])
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"pool500_candidates_path": str(bad_pool500), "allowed_sources": ["semantic"], "governance": SERVING_GOVERNANCE}
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recommend", json={
            "user_sequence": {
                "user_id": "online-u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
            },
            "complete_pool500": True,
            "top_k": 2,
        })

    assert response.status_code == 200
    result = response.json()
    assert result["fallback_used"] is True
    assert result["candidate_count"] > 0
    assert result["items"]
    _assert_no_blocked_keys(result)
    _assert_no_blocked_public_terms(result)


def test_recommend_from_sequence_uses_source_indexes_without_pool500_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    payload["rank_weights"].update({
        "itemcf_weak": 1.0,
        "itemcf_strong": 1.0,
        "usercf_recall": 1.0,
        "two_tower": 20.0,
        "co_visit_fallback_repair": 1.0,
    })
    payload.update({
        "itemcf_weak_per_seed": 5,
        "itemcf_strong_per_seed": 5,
        "usercf_per_user": 5,
        "two_tower_per_user": 5,
        "two_tower_min_overlap": 1,
    })
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recommend", json={
            "user_sequence": {
                "user_id": "online-u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
                "recent_strong_positive_item_sequence": ["seed_audio"],
            },
            "complete_pool500": True,
            "top_k": 8,
            "candidate_pool_size": 20,
        })

    assert response.status_code == 200
    result = response.json()
    assert result["candidate_count"] > 0
    assert result["fallback_used"] is False
    item_ids = [item["parent_asin"] for item in result["items"]]
    assert {
        "online_audio_weak_1",
        "online_audio_strong_1",
        "online_audio_user_1",
        "online_audio_model_1",
    }.issubset(item_ids)
    assert "online_audio_visit_1" not in item_ids
    _assert_no_blocked_keys(result)
    _assert_no_blocked_public_terms(result)


def test_co_visit_source_index_is_diagnostic_only_and_does_not_contribute_live_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    payload["rank_weights"].update({"co_visit_fallback_repair": 20.0, "usercf_recall": 1.0})
    payload.update({
        "usercf_per_user": 0,
        "co_visit_per_user": 1,
    })
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recommend", json={
            "user_sequence": {
                "user_id": "online-u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
            },
            "complete_pool500": True,
            "top_k": 5,
            "candidate_pool_size": 20,
        })

    assert response.status_code == 200
    result = response.json()
    item_ids = [item["parent_asin"] for item in result["items"]]
    assert "online_audio_visit_1" not in item_ids
    assert result["candidate_count"] > 0
    internal = service.online_recommender.readiness()["online_source_indexes"]["co_visit_fallback_repair"]
    assert internal["available"] is False
    assert internal["status"] == "diagnostic_only"
    assert internal["candidate_generation_allowed"] is False


def test_co_visit_transition_graph_repairs_only_underfilled_online_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    co_visit_dir = tmp_path / "source_indexes" / "co_visit_fallback_repair"
    write_jsonl(co_visit_dir / "edges_000.jsonl", [{
        "source": "co_visit_fallback_repair",
        "src_item": "seed_audio",
        "dst_item": "online_audio_visit_1",
        "score": 10.0,
        "category": "Audio",
        "title_clean": "Co visit audio stand",
    }])
    (co_visit_dir / "source_index_manifest.json").write_text(json.dumps({
        "schema_version": "pool500_co_visit_transition_graph_v1.source_index_manifest",
        "source": "co_visit_fallback_repair",
        "source_status": "UNDERFILL_REPAIR_INDEX_READY",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_materialization": "none",
        "underfill_repair_allowed": True,
        "candidate_generation_allowed": False,
        "serving_candidate_source_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "shard_key": "src_item_sha256_mod",
        "shard_count": 1,
        "outputs": {"edges_shards": ["edges_000.jsonl"]},
    }), encoding="utf-8")
    source_indexes["co_visit_fallback_repair"].update({
        "allow_underfill_repair": True,
        "underfill_trigger_count": 20,
        "per_user": 5,
        "per_seed": 5,
        "seed_window": 5,
    })
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    payload["rank_weights"].update({"co_visit_fallback_repair": 20.0})
    payload.update({
        "itemcf_weak_per_seed": 1,
        "itemcf_strong_per_seed": 1,
        "usercf_per_user": 1,
        "two_tower_per_user": 1,
        "two_tower_min_overlap": 1,
    })
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recommend", json={
            "user_sequence": {
                "user_id": "online-u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
                "recent_strong_positive_item_sequence": ["seed_audio"],
            },
            "complete_pool500": True,
            "top_k": 8,
            "candidate_pool_size": 20,
        })

    assert response.status_code == 200
    result = response.json()
    item_ids = [item["parent_asin"] for item in result["items"]]
    assert "online_audio_visit_1" in item_ids
    internal = service.online_recommender.readiness()["online_source_indexes"]["co_visit_fallback_repair"]
    assert internal["available"] is True
    assert internal["status"] == "underfill_repair_index_ready"
    assert internal["underfill_repair_allowed"] is True
    _assert_no_blocked_keys(result)
    _assert_no_blocked_public_terms(result)


def test_missing_co_visit_candidates_path_degrades_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    co_visit_manifest = tmp_path / "source_indexes" / "co_visit_fallback_repair" / "source_index_manifest.json"
    co_visit_payload = json.loads(co_visit_manifest.read_text(encoding="utf-8"))
    co_visit_payload["candidates_path"] = "missing_candidates.jsonl"
    co_visit_manifest.write_text(json.dumps(co_visit_payload), encoding="utf-8")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.get("/ready")

    assert response.status_code == 200
    public = response.json()
    assert public["online_route"]["complete_pool500_available"] is False
    assert public["online_route"]["online_source_indexes_available"] is True
    _assert_ready_no_internal_details(public)
    internal = service.online_recommender.readiness()["online_source_indexes"]["co_visit_fallback_repair"]
    assert internal["available"] is False
    assert internal["status"] == "missing_diagnostic_artifact"
    assert internal["candidate_generation_allowed"] is False



def test_ready_with_source_indexes_is_coarse_and_blocks_large_itemcf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    itemcf_manifest = tmp_path / "source_indexes" / "itemcf_weak" / "source_index_manifest.json"
    itemcf_payload = json.loads(itemcf_manifest.read_text(encoding="utf-8"))
    itemcf_payload["outputs"]["edges_shards"] = [f"shard_{index}.jsonl" for index in range(5)]
    itemcf_manifest.write_text(json.dumps(itemcf_payload), encoding="utf-8")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.get("/ready")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ready"
    assert result["online_route"] == {
        "mode": "online-service",
        "session_state": "single_process_in_memory",
        "complete_pool500_available": False,
        "online_source_indexes_available": True,
        "source_index_available_count": 3,
        "source_index_configured_count": 5,
        "pool500_artifact": {"enabled": False, "status": "not_configured"},
    }
    _assert_ready_no_internal_details(result)
    internal = service.online_recommender.readiness()["online_source_indexes"]
    assert internal["itemcf_weak"]["status"] == "blocked_heavy_scan"
    assert internal["itemcf_weak"]["available"] is False


def test_ready_with_qdrant_two_tower_requires_available_vector_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    source_indexes["two_tower"].update({
        "backend": "qdrant",
        "qdrant": {"enabled": True, "collection_name": "missing_two_tower_items"},
    })
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    config.write_text(json.dumps(payload), encoding="utf-8")
    install_fake_qdrant(monkeypatch)
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.get("/ready")

    assert response.status_code == 200
    public = response.json()
    assert public["online_route"]["complete_pool500_available"] is False
    internal = service.online_recommender.readiness()["online_source_indexes"]
    assert internal["two_tower"]["available"] is False
    assert internal["two_tower"]["status"] == "qdrant_unavailable"


def test_recommend_from_sequence_uses_complete_pool500_artifact_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    pool500 = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(pool500, [
        {
            "user_id": "online-u1",
            "item_id": "artifact_speaker_1",
            "source": "semantic",
            "sources": ["semantic"],
            "score": 9.0,
            "rank": 1,
            "metadata": {"category": "Audio", "title_clean": "Artifact bluetooth speaker"},
        },
        {
            "user_id": "online-u1",
            "item_id": "artifact_neighbor_1",
            "source": "itemcf_weak",
            "sources": ["itemcf_weak"],
            "score": 8.0,
            "rank": 2,
            "metadata": {"category": "Audio", "title_clean": "Artifact neighbor speaker"},
        },
        {
            "user_id": "online-u1",
            "item_id": "artifact_embedding_1",
            "source": "two_tower",
            "sources": ["two_tower"],
            "score": 7.0,
            "rank": 3,
            "metadata": {"category": "Audio", "title_clean": "Artifact embedding headphones"},
        },
        {
            "user_id": "online-u1",
            "item_id": "artifact_user_neighbor_1",
            "source": "usercf_recall",
            "sources": ["usercf_recall"],
            "score": 6.0,
            "rank": 4,
            "metadata": {"category": "Audio", "title_clean": "Artifact neighbor earbuds"},
        },
        {
            "user_id": "online-u1",
            "item_id": "artifact_covisit_1",
            "source": "co_visit_fallback_repair",
            "sources": ["co_visit_fallback_repair"],
            "score": 5.0,
            "rank": 5,
            "metadata": {"category": "Audio", "title_clean": "Artifact commute audio stand"},
        },
        {
            "user_id": "online-u1",
            "item_id": "artifact_merged_semantic_legacy",
            "source": "semantic_title_category_expansion",
            "sources": ["semantic_title_category_expansion"],
            "score": 99.0,
            "rank": 1,
            "metadata": {"category": "Audio", "title_clean": "Legacy merged semantic source"},
        },
    ])
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {
        "pool500_candidates_path": str(pool500),
        "allowed_sources": ["semantic", "itemcf_weak", "two_tower", "usercf_recall", "co_visit_fallback_repair"],
        "governance": SERVING_GOVERNANCE,
    }
    payload["rank_weights"]["semantic"] = 1.0
    payload["rank_weights"]["two_tower"] = 1.0
    payload["rank_weights"]["usercf_recall"] = 1.0
    payload["rank_weights"]["co_visit_fallback_repair"] = 1.0
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recommend", json={
            "user_sequence": {
                "user_id": "online-u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
            },
            "complete_pool500": True,
            "top_k": 5,
        })

    assert response.status_code == 200
    result = response.json()
    assert result["candidate_count"] > 0
    item_ids = [item["parent_asin"] for item in result["items"]]
    assert {
        "artifact_speaker_1",
        "artifact_neighbor_1",
        "artifact_embedding_1",
        "artifact_user_neighbor_1",
    }.issubset(item_ids)
    assert "artifact_covisit_1" not in item_ids
    assert "artifact_merged_semantic_legacy" not in item_ids
    _assert_no_blocked_keys(result)
    _assert_no_blocked_public_terms(result)


def test_recall_returns_candidate_contract_without_display_items_or_diagnostics(client: TestClient) -> None:
    response = client.post("/recall", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
        },
    })

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"request_id", "candidate_item_ids", "candidate_count", "retrieval_summary"}
    assert payload["request_id"]
    assert payload["candidate_count"] == len(payload["candidate_item_ids"])
    assert "display" not in payload
    assert "items" not in payload
    assert "diagnostics" not in payload
    assert "ranking" not in payload
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_recall_rejects_oracle_fields(client: TestClient) -> None:
    response = client.post("/recall", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "target_item": "speaker_1",
        },
    })

    assert response.status_code == 422
    assert "evaluation-only" in str(response.json()["detail"])


def test_recall_rejects_nested_oracle_fields(client: TestClient) -> None:
    response = client.post("/recall", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "metadata": {"ground_truth": ["speaker_1"]},
        },
    })

    assert response.status_code == 422
    assert "evaluation-only" in str(response.json()["detail"])


def test_recall_rejects_training_samples_field(client: TestClient) -> None:
    response = client.post("/recall", json={
        "user_sequence": {
            "user_id": "online-u1",
            "recent_item_sequence": ["seed_audio"],
            "training_samples": [{"item_id": "speaker_1"}],
        },
    })

    assert response.status_code == 422
    assert "evaluation-only" in str(response.json()["detail"])



def test_recall_uses_source_indexes_without_pool500_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    source_indexes = _write_source_index_fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"source_indexes": source_indexes, "governance": SERVING_GOVERNANCE}
    payload.update({
        "itemcf_weak_per_seed": 5,
        "itemcf_strong_per_seed": 5,
        "usercf_per_user": 5,
        "two_tower_per_user": 5,
        "two_tower_min_overlap": 1,
    })
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recall", json={
            "user_sequence": {
                "user_id": "online-u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
                "recent_strong_positive_item_sequence": ["seed_audio"],
            },
            "candidate_pool_size": 20,
        })

    assert response.status_code == 200
    payload = response.json()
    assert {
        "online_audio_weak_1",
        "online_audio_strong_1",
        "online_audio_user_1",
        "online_audio_model_1",
    }.issubset(set(payload["candidate_item_ids"]))
    assert "online_audio_visit_1" not in payload["candidate_item_ids"]
    assert payload["candidate_count"] == len(payload["candidate_item_ids"])
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_recall_pool500_artifact_respects_allowed_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    pool500 = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(pool500, [
        {
            "user_id": "online-u1",
            "item_id": "artifact_semantic_1",
            "source": "semantic",
            "sources": ["semantic"],
            "score": 10.0,
            "metadata": {"category": "Audio"},
        },
        {
            "user_id": "online-u1",
            "item_id": "artifact_itemcf_1",
            "source": "itemcf_weak",
            "sources": ["itemcf_weak"],
            "score": 20.0,
            "metadata": {"category": "Audio"},
        },
    ])
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {
        "pool500_candidates_path": str(pool500),
        "allowed_sources": ["semantic"],
        "governance": SERVING_GOVERNANCE,
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recall", json={
            "user_id": "online-u1",
            "user_sequence": {"recent_item_sequence": ["seed_audio"]},
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_item_ids"] == ["artifact_semantic_1"]
    assert "artifact_itemcf_1" not in payload["candidate_item_ids"]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_recall_applies_candidate_pool_size_and_seen_item_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_serving_fixture(tmp_path)
    pool500 = tmp_path / "pool500_candidates.jsonl"
    write_jsonl(pool500, [
        {
            "user_id": "online-u1",
            "item_id": "already_seen_recent",
            "source": "semantic",
            "score": 100.0,
            "metadata": {"category": "Audio"},
        },
        {
            "user_id": "online-u1",
            "item_id": "already_seen_prior",
            "source": "semantic",
            "score": 90.0,
            "metadata": {"category": "Audio"},
        },
        {
            "user_id": "online-u1",
            "item_id": "candidate_kept_1",
            "source": "semantic",
            "score": 80.0,
            "metadata": {"category": "Audio"},
        },
        {
            "user_id": "online-u1",
            "item_id": "candidate_kept_2",
            "source": "semantic",
            "score": 70.0,
            "metadata": {"category": "Audio"},
        },
    ])
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["online_route"] = {"pool500_candidates_path": str(pool500), "allowed_sources": ["semantic"], "governance": SERVING_GOVERNANCE}
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/recall", json={
            "user_id": "online-u1",
            "user_sequence": {"recent_item_sequence": ["already_seen_recent"]},
            "prior_turn_items": ["already_seen_prior"],
            "candidate_pool_size": 1,
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_item_ids"] == ["candidate_kept_1"]
    assert payload["candidate_count"] == 1
    assert payload["retrieval_summary"]["target_pool_size"] == 1
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


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


def _assert_ready_no_internal_details(value: Any) -> None:
    serialized = json.dumps(value).lower()
    blocked_terms = {
        "manifest_path",
        "source_index_manifest",
        "candidates_path",
        "config_path",
        "source_counts",
        "itemcf_weak",
        "itemcf_strong",
        "two_tower",
        "usercf_recall",
        "co_visit_fallback_repair",
        "/",
        "\\\\",
    }
    for term in blocked_terms:
        assert term not in serialized


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


def _write_source_index_fixture(root: Path) -> dict[str, dict[str, Any]]:
    source_root = root / "source_indexes"
    source_root.mkdir()

    itemcf_weak_dir = source_root / "itemcf_weak"
    itemcf_weak_dir.mkdir()
    write_jsonl(itemcf_weak_dir / "edges.jsonl", [
        {"src_item": "seed_audio", "dst_item": "online_audio_weak_1", "score": 9.0, "category": "Audio", "title_clean": "Bluetooth travel speaker"},
    ])
    (itemcf_weak_dir / "source_index_manifest.json").write_text(json.dumps({
        "source": "itemcf_weak",
        "train_only": True,
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "outputs": {"edges_path": "edges.jsonl"},
    }), encoding="utf-8")

    itemcf_strong_dir = source_root / "itemcf_strong"
    itemcf_strong_dir.mkdir()
    write_jsonl(itemcf_strong_dir / "edges.jsonl", [
        {"src_item": "seed_audio", "dst_item": "online_audio_strong_1", "score": 8.0, "category": "Audio", "title_clean": "Noise cancelling headphones"},
    ])
    (itemcf_strong_dir / "source_index_manifest.json").write_text(json.dumps({
        "source": "itemcf_strong",
        "train_only": True,
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "outputs": {"edges_path": "edges.jsonl"},
    }), encoding="utf-8")

    usercf_dir = source_root / "usercf_recall"
    usercf_dir.mkdir()
    write_jsonl(usercf_dir / "candidates.jsonl", [{
        "user_id": "online-u1",
        "candidates": [
            {"item_id": "online_audio_user_1", "score": 7.0, "rank": 1, "category": "Audio", "title_clean": "User neighbor earbuds"},
        ],
    }])
    (usercf_dir / "source_index_manifest.json").write_text(json.dumps({
        "source": "usercf_recall",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "source_status": "POOL500_RECALL_ONLY_SUPPLEMENTAL_READY",
        "diagnostic_only": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "outputs": {"candidates": "candidates.jsonl"},
    }), encoding="utf-8")

    two_tower_path = source_root / "two_tower_index.jsonl"
    write_jsonl(two_tower_path, [
        {"parent_asin": "seed_audio", "title_clean": "wireless audio seed", "main_category": "Audio"},
        {"parent_asin": "online_audio_model_1", "title_clean": "wireless audio model headphones", "main_category": "Audio"},
    ])

    co_visit_dir = source_root / "co_visit_fallback_repair"
    co_visit_dir.mkdir()
    write_jsonl(co_visit_dir / "candidates.jsonl", [{
        "user_id": "online-u1",
        "item_id": "online_audio_visit_1",
        "source": "co_visit_fallback_repair",
        "score": 6.0,
        "rank": 1,
        "metadata": {"category": "Audio", "title_clean": "Co visit audio stand"},
    }])
    (co_visit_dir / "source_index_manifest.json").write_text(json.dumps({
        "source": "co_visit_fallback_repair",
        "train_only": True,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "complete_co_visit_graph_claimed": False,
        "candidates_path": "candidates.jsonl",
    }), encoding="utf-8")

    return {
        "itemcf_weak": {"enabled": True, "manifest_path": str(itemcf_weak_dir / "source_index_manifest.json")},
        "itemcf_strong": {"enabled": True, "manifest_path": str(itemcf_strong_dir / "source_index_manifest.json")},
        "usercf_recall": {"enabled": True, "manifest_path": str(usercf_dir / "source_index_manifest.json")},
        "two_tower": {"enabled": True, "manifest_path": str(two_tower_path)},
        "co_visit_fallback_repair": {"enabled": True, "manifest_path": str(co_visit_dir / "source_index_manifest.json")},
    }
