from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.elasticsearch_config import elasticsearch_config_from_env, public_elasticsearch_config
from rs_core.common.milvus_config import milvus_config_from_args, milvus_config_from_env, merge_milvus_config


def test_milvus_config_from_env_parses_connection_fields() -> None:
    config = milvus_config_from_env(
        {
            "RS_MILVUS_URI": "http://localhost:19530",
            "RS_MILVUS_TOKEN": "secret",
            "RS_MILVUS_DB_NAME": "default",
            "RS_MILVUS_TIMEOUT": "30",
        }
    )

    assert config == {"uri": "http://localhost:19530", "token": "secret", "db_name": "default", "timeout": 30}


def test_milvus_config_from_args_ignores_empty_values() -> None:
    args = SimpleNamespace(milvus_uri="outputs/local/milvus.db", milvus_token="", milvus_db_name=None, milvus_timeout=None)

    assert milvus_config_from_args(args) == {"uri": "outputs/local/milvus.db"}


def test_merge_milvus_config_keeps_base_when_override_empty() -> None:
    merged = merge_milvus_config({"uri": "base.db", "token": "keep"}, {"uri": "", "timeout": 10})

    assert merged == {"uri": "base.db", "token": "keep", "timeout": 10}


def test_milvus_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        milvus_config_from_env({"RS_MILVUS_TIMEOUT": "0"})


def test_elasticsearch_config_from_env_and_public_summary_are_secret_safe() -> None:
    config = elasticsearch_config_from_env(
        {
            "RS_ELASTICSEARCH_URI": "http://secret-host:9200",
            "RS_ELASTICSEARCH_INDEX": "rag-index",
            "RS_ELASTICSEARCH_API_KEY": "secret-key",
            "RS_ELASTICSEARCH_TIMEOUT": "10",
        }
    )

    assert config == {"uri": "http://secret-host:9200", "index_name": "rag-index", "api_key": "secret-key", "timeout": 10}
    public = public_elasticsearch_config(config)
    assert public == {"enabled": True, "target_configured": True, "target_kind": "uri", "index_configured": True, "has_auth": True}
    assert "secret-host" not in str(public)
    assert "secret-key" not in str(public)


def test_milvus_env_overrides_serving_rag_without_leaking_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from rs_core.serving.runtime.config import _milvus_env_overrides
    from rs_core.serving.runtime.readiness import _public_rag_readiness

    config = {
        "rag": {
            "retriever": "hybrid",
            "fallback_policy": {"enabled": True, "fallback_retriever": "sqlite_bm25"},
            "hybrid": {
                "milvus": {
                    "enabled": True,
                    "uri": "base.db",
                    "collection_name": "rag_milvus",
                    "candidate_generation_allowed": False,
                    "ranking_input_replacement_allowed": False,
                    "promotion_allowed": False,
                }
            },
        }
    }
    monkeypatch.setenv("RS_MILVUS_URI", "outputs/local/milvus/secret-target.db")
    monkeypatch.setenv("RS_MILVUS_TOKEN", "secret-token")

    overrides = _milvus_env_overrides(config)

    assert overrides["rag"]["hybrid"]["milvus"]["uri"] == "outputs/local/milvus/secret-target.db"
    assert overrides["rag"]["hybrid"]["milvus"]["token"] == "secret-token"
    readiness = _public_rag_readiness(config | {"rag": config["rag"] | {"hybrid": overrides["rag"]["hybrid"]}})
    assert readiness["vector_backend"]["backend"] == "milvus"
    assert readiness["milvus"]["target_configured"] is True
    assert readiness["milvus"]["target_kind"] == "uri"
    assert readiness["milvus"]["collection_name"] == "rag_milvus"
    assert readiness["milvus"]["candidate_generation_allowed"] is False
    assert readiness["milvus"]["ranking_input_replacement_allowed"] is False
    assert readiness["milvus"]["promotion_allowed"] is False
    assert "secret-target" not in str(readiness)
    assert "secret-token" not in str(readiness)


def test_elasticsearch_env_overrides_serving_rag_without_leaking_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from rs_core.serving.runtime.config import _elasticsearch_env_overrides
    from rs_core.serving.runtime.readiness import _public_rag_readiness

    config = {
        "rag": {
            "retriever": "hybrid",
            "fallback_policy": {"enabled": True, "fallback_retriever": "elasticsearch_bm25"},
            "hybrid": {
                "elasticsearch": {
                    "enabled": True,
                    "uri": "http://base:9200",
                    "index_name": "rag-index",
                }
            },
        }
    }
    monkeypatch.setenv("RS_ELASTICSEARCH_URI", "http://secret-host:9200")
    monkeypatch.setenv("RS_ELASTICSEARCH_INDEX", "rag-secret-index")
    monkeypatch.setenv("RS_ELASTICSEARCH_API_KEY", "secret-es-token")

    overrides = _elasticsearch_env_overrides(config)

    assert overrides["rag"]["hybrid"]["elasticsearch"]["uri"] == "http://secret-host:9200"
    readiness = _public_rag_readiness(config | {"rag": config["rag"] | {"hybrid": overrides["rag"]["hybrid"]}})
    assert readiness["bm25_fallback"]["backend"] == "elasticsearch"
    assert readiness["bm25_fallback"]["target_configured"] is True
    assert readiness["bm25_fallback"]["target_kind"] == "uri"
    assert readiness["bm25_fallback"]["index_configured"] is True
    assert readiness["pre_retrieval_query_support"]["retriever"] == "elasticsearch_bm25_query_planning"
    assert "secret-host" not in str(readiness)
    assert "secret-es-token" not in str(readiness)
