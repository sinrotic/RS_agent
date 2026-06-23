from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rs_core.common.io import write_jsonl
from rs_core.recsys.vectorstores.qdrant_builders import merge_qdrant_config, qdrant_config_from_args, qdrant_config_from_env

pytestmark = pytest.mark.unit


def test_qdrant_config_from_env_parses_connection_fields() -> None:
    config = qdrant_config_from_env(
        {
            "RS_QDRANT_URL": "http://qdrant:6333",
            "RS_QDRANT_PORT": "6334",
            "RS_QDRANT_PREFER_GRPC": "true",
            "RS_QDRANT_PATH": "",
        }
    )

    assert config == {"url": "http://qdrant:6333", "port": 6334, "prefer_grpc": True}


def test_qdrant_config_from_env_rejects_bad_port_and_bool() -> None:
    with pytest.raises(ValueError, match="RS_QDRANT_PORT"):
        qdrant_config_from_env({"RS_QDRANT_PORT": "not-a-port"})
    with pytest.raises(ValueError, match="RS_QDRANT_PREFER_GRPC"):
        qdrant_config_from_env({"RS_QDRANT_PREFER_GRPC": "maybe"})


def test_merge_qdrant_config_keeps_base_when_override_empty() -> None:
    assert merge_qdrant_config({"url": "http://base:6333", "collection_name": "items"}, {"url": "", "path": None}) == {
        "url": "http://base:6333",
        "collection_name": "items",
    }


def test_merge_qdrant_config_replaces_target_kind() -> None:
    assert merge_qdrant_config({"path": "local_qdrant", "collection_name": "items"}, {"url": "http://env:6333"}) == {
        "url": "http://env:6333",
        "collection_name": "items",
    }


def test_cli_args_override_env_qdrant_config() -> None:
    args = SimpleNamespace(
        qdrant_location=None,
        qdrant_path=None,
        qdrant_url="http://cli:6333",
        qdrant_host=None,
        qdrant_port=7333,
        prefer_grpc=True,
    )

    merged = merge_qdrant_config(
        qdrant_config_from_env({"RS_QDRANT_URL": "http://env:6333", "RS_QDRANT_PORT": "6333", "RS_QDRANT_PREFER_GRPC": "false"}),
        qdrant_config_from_args(args),
    )

    assert merged == {"url": "http://cli:6333", "port": 7333, "prefer_grpc": True}


def test_recommendation_service_applies_qdrant_env_to_readiness_without_leaking_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from rs_core.serving.application.recommendation_service import RecommendationService

    config_path = _write_serving_fixture(tmp_path)
    monkeypatch.setenv("RS_QDRANT_URL", "http://secret-qdrant.internal:6333")

    service = RecommendationService(str(config_path), limit_users=1)
    readiness = service.readiness()

    rag = readiness["rag"]
    assert rag["retriever"] == "hybrid"
    assert rag["retrieval_scope"] == "post_ranking_candidate_scoped_rag"
    assert rag["candidate_scoped"] is True
    assert rag["final_rag"] is True
    assert rag["small2big"]["enabled"] is True
    assert rag["small2big"]["parent_profile_enabled"] is True
    assert rag["pre_retrieval_query_support"] == {
        "retriever": "sqlite_bm25_query_planning",
        "retrieval_scope": "query_planning",
        "candidate_scoped": False,
        "final_rag": False,
        "used_for": "semantic_query_hint_only",
    }
    qdrant = rag["qdrant"]
    assert qdrant["target_configured"] is True
    assert qdrant["target_kind"] == "url"
    assert qdrant["collection_name"] == "rag_chunks"
    assert qdrant["fallback_enabled"] is True
    assert "empty_vector_results" in qdrant["fallback_reasons"]
    payload = json.dumps(readiness, ensure_ascii=False)
    assert "secret-qdrant" not in payload
    assert "http://secret-qdrant.internal:6333" not in payload
    assert service.env.config["rag"]["hybrid"]["qdrant"]["url"] == "http://secret-qdrant.internal:6333"
    assert service.env.config["rag"]["qdrant"]["url"] == "http://secret-qdrant.internal:6333"
    assert service.env.config["online_route"]["source_indexes"]["two_tower"]["qdrant"]["url"] == "http://secret-qdrant.internal:6333"
    assert service.env.config["online_retrieval"]["providers"]["two_tower_qdrant"]["qdrant"]["url"] == "http://secret-qdrant.internal:6333"


def _write_serving_fixture(root: Path) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "popular_1", "category": "Audio", "pop_score": 1.0}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [{"parent_asin": "seed", "main_category": "Audio"}])
    write_jsonl(views / "category_top_items.jsonl", [])
    source_manifest = root / "two_tower_source_index_manifest.json"
    source_manifest.write_text(json.dumps({"schema_version": "source_index_manifest_v1", "source": "two_tower", "item_count": 0}), encoding="utf-8")
    config = root / "config.yaml"
    config.write_text(
        json.dumps(
            {
                "clean_dir": str(clean),
                "views_dir": str(views),
                "output_dir": str(root / "out"),
                "report_path": str(root / "report.md"),
                "evaluation_mode": "public_serving",
                "serving_allowed": True,
                "top_k": 3,
                "candidate_pool_size": 10,
                "popular_fallback_count": 3,
                "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0, "category": 1.0},
                "online_route": {
                    "source_indexes": {
                        "two_tower": {
                            "enabled": True,
                            "manifest_path": str(source_manifest),
                            "backend": "qdrant",
                            "qdrant": {"enabled": True, "path": str(root / "local_qdrant"), "collection_name": "two_tower_items"},
                        }
                    },
                    "governance": {"ranking_input_replacement_allowed": False, "pool1000_allowed": False, "promotion_allowed": False, "final_pool500_ready_claimed": False},
                },
                "rag": {
                    "retriever": "hybrid",
                    "fallback_policy": {"enabled": True, "fallback_retriever": "sqlite_bm25"},
                    "hybrid": {"qdrant": {"enabled": True, "path": str(root / "rag_qdrant"), "collection_name": "rag_chunks"}},
                    "qdrant": {"enabled": True, "path": str(root / "rag_qdrant"), "collection_name": "rag_chunks"},
                    "small2big": {
                        "enabled": True,
                        "max_parent_profiles_total": 6,
                        "max_parent_profiles_per_item": 1,
                    },
                },
                "online_retrieval": {
                    "enabled": True,
                    "providers": {
                        "two_tower_qdrant": {
                            "enabled": True,
                            "manifest_path": str(source_manifest),
                            "qdrant": {"enabled": True, "path": str(root / "two_tower_qdrant"), "collection_name": "two_tower_items"},
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return config
