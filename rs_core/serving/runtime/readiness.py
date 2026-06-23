from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from rs_core.rsagent.inference_policy import resolve_inference_policy_config
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
    qdrant = _qdrant_config(rag, hybrid)
    fallback = rag.get("fallback_policy") if isinstance(rag.get("fallback_policy"), dict) else {}
    small2big = rag.get("small2big") if isinstance(rag.get("small2big"), dict) else {}
    bm25_path = _project_path(rag.get("bm25_index_path") or rag.get("index_path"))
    manifest_path = _project_path(rag.get("manifest_path") or rag.get("index_manifest_path"))
    qdrant_enabled = bool(qdrant.get("enabled"))
    qdrant_target_configured = _qdrant_target_configured(qdrant)
    dependency_available = _dependency_available("qdrant_client")
    fallback_enabled = bool(fallback.get("enabled", bool(bm25_path)))
    fallback_reasons = []
    if qdrant_enabled and not dependency_available:
        fallback_reasons.append("qdrant_dependency_missing")
    if qdrant_enabled and not qdrant_target_configured:
        fallback_reasons.append("qdrant_target_missing")
    if qdrant_enabled:
        fallback_reasons.append("empty_vector_results")
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
            "retriever": "sqlite_bm25_query_planning",
            "retrieval_scope": "query_planning",
            "candidate_scoped": False,
            "final_rag": False,
            "used_for": "semantic_query_hint_only",
        },
        "qdrant": {
            "enabled": qdrant_enabled,
            "target_configured": qdrant_target_configured,
            "target_kind": _qdrant_target_kind(qdrant),
            "dependency_available": dependency_available,
            "collection_name": str(qdrant.get("collection_name", "")),
            "fallback_enabled": fallback_enabled,
            "fallback_reasons": fallback_reasons,
            "candidate_generation_allowed": bool(qdrant.get("candidate_generation_allowed", rag.get("candidate_generation_allowed"))),
            "ranking_input_replacement_allowed": bool(qdrant.get("ranking_input_replacement_allowed", rag.get("ranking_input_replacement_allowed"))),
            "promotion_allowed": bool(qdrant.get("promotion_allowed", rag.get("promotion_allowed"))),
        },
        "bm25_fallback": {
            "enabled": fallback_enabled,
            "retriever": str(fallback.get("fallback_retriever", "sqlite_bm25")),
            "index_configured": bm25_path is not None,
            "index_exists": bool(bm25_path and bm25_path.exists()),
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
    return {
        "pool500_serving": _manifest_status(_project_path(online_route.get("artifact_manifest_path"))),
        "rag_qdrant": _manifest_status(_project_path(rag.get("manifest_path") or rag.get("index_manifest_path"))),
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


def _qdrant_config(rag: dict[str, Any], hybrid: dict[str, Any]) -> dict[str, Any]:
    hybrid_qdrant = hybrid.get("qdrant")
    if isinstance(hybrid_qdrant, dict):
        return hybrid_qdrant
    rag_qdrant = rag.get("qdrant")
    return rag_qdrant if isinstance(rag_qdrant, dict) else {}


def _qdrant_target_configured(qdrant: dict[str, Any]) -> bool:
    return any(qdrant.get(key) not in (None, "") for key in ("url", "host", "path", "location"))


def _qdrant_target_kind(qdrant: dict[str, Any]) -> str:
    for key in ("url", "host", "path", "location"):
        if qdrant.get(key) not in (None, ""):
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


