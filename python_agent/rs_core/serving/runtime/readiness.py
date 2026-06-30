from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from rs_core.agent.inference import resolve_inference_policy_config
from rs_core.common.elasticsearch_config import elasticsearch_target_kind, public_elasticsearch_config
from rs_core.serving.runtime.config import PROJECT_ROOT


def _public_candidate_retrieval_readiness(online: dict[str, Any]) -> dict[str, Any]:
    retrieval = online.get("candidate_retrieval") if isinstance(online.get("candidate_retrieval"), dict) else {}
    providers = retrieval.get("providers") if isinstance(retrieval.get("providers"), dict) else {}
    safe_providers = {
        str(name): {
            "enabled": bool(status.get("enabled")),
            "available": bool(status.get("available")),
            "status": str(status.get("status", "unknown")),
            "role": str(status.get("role", "")),
            "backend": str(status.get("backend", "unknown")),
        }
        for name, status in providers.items()
        if isinstance(status, dict)
    }
    return {
        "enabled": bool(retrieval.get("enabled")),
        "available": bool(retrieval.get("available")),
        "status": str(retrieval.get("status", "not_configured")),
        "configured_provider_count": int(retrieval.get("configured_provider_count", len(safe_providers)) or 0),
        "available_provider_count": int(retrieval.get("available_provider_count", 0) or 0),
        "providers": safe_providers,
    }


def _public_online_route_readiness(online: dict[str, Any]) -> dict[str, Any]:
    source_indexes = online.get("online_source_indexes") if isinstance(online.get("online_source_indexes"), dict) else {}
    artifact = online.get("pool500_artifact") if isinstance(online.get("pool500_artifact"), dict) else {}
    return {
        "mode": online.get("mode", "demo-compatible"),
        "session_state": "single_process_in_memory",
        "complete_pool500_available": bool(online.get("complete_pool500_available")),
        "online_source_indexes_available": bool(online.get("online_source_indexes_available")),
        "source_index_available_count": sum(1 for status in source_indexes.values() if isinstance(status, dict) and status.get("available")),
        "source_index_configured_count": len(source_indexes),
        "pool500_artifact": {
            "enabled": bool(artifact.get("enabled")),
            "status": str(artifact.get("status", "not_configured")),
        },
    }


def _public_rag_readiness(config: dict[str, Any]) -> dict[str, Any]:
    rag = config.get("rag") if isinstance(config.get("rag"), dict) else {}
    hybrid = rag.get("hybrid") if isinstance(rag.get("hybrid"), dict) else {}
    milvus = _milvus_config(rag, hybrid)
    elasticsearch = _elasticsearch_config(rag, hybrid)
    fallback = rag.get("fallback_policy") if isinstance(rag.get("fallback_policy"), dict) else {}
    small2big = rag.get("small2big") if isinstance(rag.get("small2big"), dict) else {}
    bm25_path = _project_path(rag.get("legacy_bm25_index_path") or rag.get("bm25_index_path") or rag.get("index_path"))
    manifest_path = _project_path(rag.get("manifest_path") or rag.get("index_manifest_path"))
    milvus_enabled = bool(milvus.get("enabled"))
    milvus_target_configured = _milvus_target_configured(milvus)
    milvus_dependency_available = _dependency_available("pymilvus")
    fallback_retriever = str(fallback.get("fallback_retriever", "sqlite_bm25"))
    elasticsearch_selected = fallback_retriever in {"elasticsearch", "es", "es_bm25", "elasticsearch_bm25"}
    elasticsearch_dependency_available = _dependency_available("elasticsearch")
    elasticsearch_target_configured = _elasticsearch_target_configured(elasticsearch)
    elasticsearch_index_configured = _elasticsearch_index_configured(elasticsearch)
    fallback_enabled = bool(fallback.get("enabled", bool(bm25_path) or elasticsearch_selected))
    fallback_reasons = []
    if milvus_enabled and not milvus_dependency_available:
        fallback_reasons.append("milvus_dependency_missing")
    if milvus_enabled and not milvus_target_configured:
        fallback_reasons.append("milvus_target_missing")
    if milvus_enabled:
        fallback_reasons.append("empty_vector_results")
    if elasticsearch_selected and not elasticsearch_dependency_available:
        fallback_reasons.append("elasticsearch_dependency_missing")
    if elasticsearch_selected and not elasticsearch_target_configured:
        fallback_reasons.append("elasticsearch_target_missing")
    if elasticsearch_selected and not elasticsearch_index_configured:
        fallback_reasons.append("elasticsearch_index_missing")
    query_planning = rag.get("query_planning") if isinstance(rag.get("query_planning"), dict) else {}
    query_planning_retriever = str(query_planning.get("retriever") or fallback_retriever)
    if query_planning_retriever in {"elasticsearch", "es", "es_bm25", "elasticsearch_bm25"}:
        query_planning_retriever = "elasticsearch_bm25_query_planning"
    elif query_planning_retriever in {"sqlite", "sqlite_bm25"}:
        query_planning_retriever = "sqlite_bm25_query_planning"
    return {
        "retriever": str(rag.get("retriever", "in_memory_candidate_card")),
        "evidence_mode": str(rag.get("evidence_mode", "off")),
        "retrieval_scope": "post_ranking_candidate_scoped_rag",
        "candidate_scoped": True,
        "final_rag": True,
        "small2big": {
            "enabled": bool(small2big.get("enabled")),
            "parent_profile_enabled": bool(small2big.get("enabled")),
            "max_parent_profiles_total": int(small2big.get("max_parent_profiles_total", 0) or 0),
            "max_parent_profiles_per_item": int(small2big.get("max_parent_profiles_per_item", 0) or 0),
        },
        "pre_retrieval_query_support": {
            "retriever": query_planning_retriever,
            "retrieval_scope": "query_planning",
            "candidate_scoped": False,
            "final_rag": False,
            "used_for": "semantic_query_hint_only",
        },
        "vector_backend": {
            "backend": "milvus" if milvus_enabled else "none",
            "fallback_enabled": fallback_enabled,
            "fallback_reasons": fallback_reasons,
        },
        "milvus": {
            "enabled": milvus_enabled,
            "target_configured": milvus_target_configured,
            "target_kind": _milvus_target_kind(milvus),
            "dependency_available": milvus_dependency_available,
            "collection_name": str(milvus.get("collection_name", "")),
            "fallback_enabled": fallback_enabled,
            "fallback_reasons": fallback_reasons,
            "candidate_generation_allowed": bool(milvus.get("candidate_generation_allowed", rag.get("candidate_generation_allowed"))),
            "ranking_input_replacement_allowed": bool(milvus.get("ranking_input_replacement_allowed", rag.get("ranking_input_replacement_allowed"))),
            "promotion_allowed": bool(milvus.get("promotion_allowed", rag.get("promotion_allowed"))),
        },
        "bm25_fallback": {
            "enabled": fallback_enabled,
            "retriever": fallback_retriever,
            "backend": "elasticsearch" if elasticsearch_selected else "sqlite",
            "target_configured": elasticsearch_target_configured if elasticsearch_selected else bm25_path is not None,
            "target_kind": _elasticsearch_target_kind(elasticsearch) if elasticsearch_selected else "local_file",
            "dependency_available": elasticsearch_dependency_available if elasticsearch_selected else True,
            "index_configured": elasticsearch_index_configured if elasticsearch_selected else bm25_path is not None,
            "index_status": "not_probed_by_readiness" if elasticsearch_selected else ("available" if bm25_path and bm25_path.exists() else "missing"),
            "legacy_retriever": "sqlite_bm25" if bm25_path is not None else "none",
            "legacy_index_configured": bm25_path is not None,
            "legacy_index_exists": bool(bm25_path and bm25_path.exists()),
            "fallback_reasons": fallback_reasons,
        },
        "manifest": _manifest_status(manifest_path),
        "candidate_generation_allowed": bool(rag.get("candidate_generation_allowed")),
        "ranking_input_replacement_allowed": bool(rag.get("ranking_input_replacement_allowed")),
        "promotion_allowed": bool(rag.get("promotion_allowed")),
    }


def _public_artifact_manifest_readiness(config: dict[str, Any]) -> dict[str, Any]:
    online_route = config.get("online_route") if isinstance(config.get("online_route"), dict) else {}
    deepfm_shadow = config.get("deepfm_shadow") if isinstance(config.get("deepfm_shadow"), dict) else {}
    rag = config.get("rag") if isinstance(config.get("rag"), dict) else {}
    hybrid = rag.get("hybrid") if isinstance(rag.get("hybrid"), dict) else {}
    milvus_manifest = rag.get("milvus_manifest_path")
    if not milvus_manifest and _milvus_config(rag, hybrid).get("enabled"):
        milvus_manifest = rag.get("manifest_path") or rag.get("index_manifest_path")
    elasticsearch_manifest = rag.get("elasticsearch_bm25_manifest_path") or rag.get("elasticsearch_manifest_path")
    return {
        "pool500_serving": _manifest_status(_project_path(online_route.get("artifact_manifest_path"))),
        "rag_milvus": _manifest_status(_project_path(milvus_manifest)),
        "rag_elasticsearch_bm25": _manifest_status(_project_path(elasticsearch_manifest)),
        "deepfm_shadow": _manifest_status(_project_path(deepfm_shadow.get("manifest_path"))),
    }


def _public_deepfm_shadow_readiness(config: dict[str, Any]) -> dict[str, Any]:
    shadow = config.get("deepfm_shadow") if isinstance(config.get("deepfm_shadow"), dict) else {}
    return {
        "enabled": bool(shadow.get("enabled")),
        "mode": str(shadow.get("mode", "")),
        "diagnostic_only": bool(shadow.get("diagnostic_only", True)),
        "affect_ranking": bool(shadow.get("affect_ranking")),
        "score_scale": float(shadow.get("score_scale", 0.0) or 0.0),
        "public_payload_allowed": bool(shadow.get("public_payload_allowed")),
        "ranking_input_replacement_allowed": bool(shadow.get("ranking_input_replacement_allowed")),
        "promotion_allowed": bool(shadow.get("promotion_allowed")),
        "manifest": _manifest_status(_project_path(shadow.get("manifest_path"))),
    }


def _public_agent_provider_readiness(config: dict[str, Any]) -> dict[str, Any]:
    policy = resolve_inference_policy_config(config)
    provider = str(policy.get("provider", "disabled"))
    enabled = bool(policy.get("enabled")) and provider != "disabled"
    openai_config = policy.get("openai_compatible") if isinstance(policy.get("openai_compatible"), dict) else {}
    base_env = str(openai_config.get("api_base_env", "RS_AGENT_OPENAI_COMPATIBLE_BASE_URL"))
    model_env = str(openai_config.get("model_env", "RS_AGENT_OPENAI_COMPATIBLE_MODEL"))
    endpoint_configured = provider == "openai_compatible" and bool(openai_config.get("base_url") or os.environ.get(base_env))
    model_configured = provider == "openai_compatible" and bool(openai_config.get("model") or os.environ.get(model_env))
    probe_enabled = bool(openai_config.get("probe_enabled", False))
    base = {
        "enabled": enabled,
        "provider": provider if enabled else "disabled",
        "available_providers": list(policy.get("available_providers", ["disabled", "openai_compatible", "local_transformers"])),
        "default_disabled": not enabled,
        "local_model_load_allowed_by_default": bool(policy.get("local_transformers", {}).get("enabled")) if isinstance(policy.get("local_transformers"), dict) else provider in {"qwen_local", "local_transformers"} and enabled,
        "vllm_started_by_serving": False,
    }
    if not enabled:
        return base
    return base | {
        "configured": enabled and (provider != "openai_compatible" or (endpoint_configured and model_configured)),
        "endpoint_configured": bool(endpoint_configured),
        "model_configured": bool(model_configured) if provider == "openai_compatible" else bool(policy.get("model", {}).get("model_id")),
        "probe_enabled": probe_enabled,
        "probe_status": "not_run_by_readiness",
        "fallback_policy": "raise_when_strict_else_keep_original_candidates",
    }


def _milvus_config(rag: dict[str, Any], hybrid: dict[str, Any]) -> dict[str, Any]:
    hybrid_milvus = hybrid.get("milvus")
    if isinstance(hybrid_milvus, dict):
        return hybrid_milvus
    rag_milvus = rag.get("milvus")
    return rag_milvus if isinstance(rag_milvus, dict) else {}


def _elasticsearch_config(rag: dict[str, Any], hybrid: dict[str, Any]) -> dict[str, Any]:
    hybrid_elasticsearch = hybrid.get("elasticsearch")
    if isinstance(hybrid_elasticsearch, dict):
        return hybrid_elasticsearch
    rag_elasticsearch = rag.get("elasticsearch")
    return rag_elasticsearch if isinstance(rag_elasticsearch, dict) else {}


def _elasticsearch_target_configured(elasticsearch: dict[str, Any]) -> bool:
    return bool(public_elasticsearch_config(elasticsearch)["target_configured"])


def _elasticsearch_index_configured(elasticsearch: dict[str, Any]) -> bool:
    return bool(public_elasticsearch_config(elasticsearch)["index_configured"])


def _elasticsearch_target_kind(elasticsearch: dict[str, Any]) -> str:
    return elasticsearch_target_kind(elasticsearch)


def _milvus_target_configured(milvus: dict[str, Any]) -> bool:
    return any(milvus.get(key) not in (None, "") for key in ("uri", "path", "db_path"))


def _milvus_target_kind(milvus: dict[str, Any]) -> str:
    for key in ("uri", "path", "db_path"):
        if milvus.get(key) not in (None, ""):
            return key
    return "none"


def _dependency_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _manifest_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"configured": False, "exists": False, "status": "not_configured"}
    exists = path.exists()
    return {"configured": True, "exists": exists, "status": "available" if exists else "missing"}


def _project_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path
