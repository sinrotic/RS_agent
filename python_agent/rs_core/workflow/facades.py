from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from rs_core.agent.adapters import (
    MemoryAgentAdapter,
    MemoryAgentConfig,
    RagAgentAdapter,
    RagAgentConfig,
    RagAgentInvocation,
    RecommendationShadowAdapter,
)
from rs_core.agent.contracts import AgentSession, AgentTurn
from rs_core.agent.rag import (
    RAG_AGENT_POST_RANKING_STAGE,
    RAG_PARENT_PROFILE_FIELD,
    RAG_STANDARD_FIELDS,
    HybridCandidateRetriever,
    InMemoryCandidateCardRetriever,
    MilvusCandidateRagVectorRetriever,
    RagPolicy,
    SQLiteBM25CandidateRetriever,
    ElasticsearchBM25CandidateRetriever,
    Small2BigCandidateEvidenceRetriever,
    build_rag_context_for_ranked_candidates,
)
from rs_core.agent.runtime import AgentRuntime, AgentRuntimeHost
from rs_core.agent.runtime_core import AgentRuntimeConfig, LoopMode
from rs_core.common.io import read_json
from rs_core.data.adapters import MilvusAdapter
from rs_core.data.clients import DataClient, KnowledgeDataClient
from rs_core.display.builder import item_to_display_card
from rs_core.data.vectorstores.milvus_contracts import DEFAULT_MILVUS_RAG_CHUNK_COLLECTION, MILVUS_RAG_CHUNK_SCHEMA_VERSION
from rs_core.workflow.hybrid_demo import ROOT


class AgentOrchestrationFacade:
    def __init__(self, runtime: AgentRuntime, runtime_config: AgentRuntimeConfig | None = None) -> None:
        self.runtime = runtime
        self.runtime_config = runtime_config or AgentRuntimeConfig()
        self.shadow_adapter = RecommendationShadowAdapter()
        self.memory_shadow_adapter = MemoryAgentAdapter()
        self.rag_shadow_adapter = RagAgentAdapter()

    def run_turn(
        self,
        host: AgentRuntimeHost,
        session: AgentSession,
        user_input: str = "",
        explanation_item_id: str | None = None,
    ) -> AgentTurn:
        if self.runtime_config.loop_mode == LoopMode.GENERIC_ACTIVE:
            raise RuntimeError("agent_runtime.loop_mode=generic_active is not available before active readiness gates pass")
        before_turn_count = len(session.turns)
        turn = self.runtime.run_turn(host, session, user_input, explanation_item_id)
        if self.runtime_config.loop_mode == LoopMode.GENERIC_SHADOW:
            self.shadow_adapter.attach_shadow_report(
                turn,
                before_turn_count=before_turn_count,
                after_turn_count=len(session.turns),
            )
        try:
            memory_agent_config = MemoryAgentConfig.from_dict(self.runtime_config.metadata.get("memory_agent") if isinstance(self.runtime_config.metadata.get("memory_agent"), dict) else None)
        except ValueError as exc:
            turn.diagnostics["memory_agent_shadow"] = {"status": "error", "action": "skip", "errors": [str(exc)], "internal_only": True}
            memory_agent_config = MemoryAgentConfig(enabled=False)
        if memory_agent_config.enabled and memory_agent_config.mode == "shadow":
            try:
                self.memory_shadow_adapter.attach_shadow_report(session, turn, memory_agent_config)
            except Exception as exc:
                turn.diagnostics["memory_agent_shadow"] = {"status": "error", "action": "skip", "errors": [f"{type(exc).__name__}: {exc}"], "internal_only": True}
        elif memory_agent_config.enabled and memory_agent_config.mode != "shadow":
            turn.diagnostics["memory_agent_shadow"] = {"status": "error", "action": "skip", "errors": [f"Unsupported MemoryAgent mode: {memory_agent_config.mode}"], "internal_only": True}
        try:
            rag_agent_config = RagAgentConfig.from_dict(self.runtime_config.metadata.get("rag_agent") if isinstance(self.runtime_config.metadata.get("rag_agent"), dict) else None)
        except ValueError as exc:
            turn.diagnostics["rag_agent_shadow"] = {"status": "error", "action": "skip", "errors": [str(exc)], "candidate_scoped": True}
            return turn
        if rag_agent_config.enabled and rag_agent_config.mode == "shadow" and isinstance(turn.rag_context, dict):
            response = self.rag_shadow_adapter.invoke(
                RagAgentInvocation(
                    description="post-ranking RagAgent evidence support",
                    stage=RAG_AGENT_POST_RANKING_STAGE,
                    prompt_or_task="Compress candidate-scoped RAG evidence for the current recommendation turn.",
                    session_id=session.session_id,
                    turn_index=turn.turn_index,
                    request_id=f"rag-post-{session.session_id}-{turn.turn_index}",
                    payload={"turn": turn},
                ),
                rag_agent_config,
            )
            report = response.shadow_report.to_dict() if response.shadow_report else {"status": response.status, "action": response.action, "candidate_scoped": True}
            turn.diagnostics["rag_agent_shadow"] = report
            if rag_agent_config.attach_support_to_diagnostics and response.support and response.support.used_evidence_count > 0:
                turn.diagnostics["rag_agent_support"] = response.support.to_dict()
        elif rag_agent_config.enabled and rag_agent_config.mode != "shadow":
            turn.diagnostics["rag_agent_shadow"] = {"status": "error", "action": "skip", "errors": [f"Unsupported RagAgent mode: {rag_agent_config.mode}"], "candidate_scoped": True}
        return turn


class EvidenceRAGFacade:
    def build_turn_rag_context(
        self,
        config: dict[str, Any],
        query: str,
        ranked_items: list[dict[str, Any]],
        final_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        rag_config = config.get("rag") if isinstance(config.get("rag"), dict) else {}
        mode = str(rag_config.get("evidence_mode", "off"))
        if mode not in {"shadow", "explain"}:
            return None
        max_evidence_per_item = int(rag_config.get("max_evidence_per_item", 3) or 3)
        max_evidence_total = int(rag_config.get("max_evidence_total", 12) or 12)
        max_text_chars = int(rag_config.get("max_text_chars", rag_config.get("max_evidence_text_chars", 180)) or 180)
        fields = _string_list(rag_config.get("fields")) or list(RAG_STANDARD_FIELDS)
        item_cards = _display_safe_item_cards([*ranked_items, *final_items])
        candidate_item_ids = [item_id for item_id in _ranked_item_ids(ranked_items) if item_id in item_cards]
        retriever_name = "in_memory_candidate_card"
        retriever = InMemoryCandidateCardRetriever(item_cards, fields=fields)
        retriever_config = str(rag_config.get("retriever", "")).strip().lower()
        index_path = _rag_index_path(rag_config)
        lexical_backend, lexical_backend_name = _safe_rag_lexical_backend(rag_config)
        hybrid_config = rag_config.get("hybrid") if isinstance(rag_config.get("hybrid"), dict) else {}
        vector_backend, vector_backend_name = _safe_rag_vector_backend(rag_config, hybrid_config) if retriever_config == "hybrid" else (None, "")
        if retriever_config == "hybrid" and (lexical_backend is not None or vector_backend is not None or _has_legacy_sqlite_index(index_path)):
            legacy_index_path = index_path
            retriever = HybridCandidateRetriever(
                legacy_index_path,
                vector_index_path=_rag_vector_index_path(rag_config, legacy_index_path) if legacy_index_path and legacy_index_path.exists() else None,
                bm25_weight=float(hybrid_config.get("bm25_weight", 0.65)),
                vector_weight=float(hybrid_config.get("vector_weight", 0.35)),
                vector_dim=int(hybrid_config.get("vector_dim", 256)),
                vector_top_k_multiplier=int(hybrid_config.get("vector_top_k_multiplier", 4)),
                fusion_method=str(hybrid_config.get("fusion_method", "weighted")),
                rrf_k=int(hybrid_config.get("rrf_k", 60)),
                field_weights=_field_weights(hybrid_config.get("field_weights")),
                vector_backend=vector_backend,
                lexical_backend=lexical_backend,
                lexical_backend_name=lexical_backend_name,
                legacy_sqlite_hashed_vector_fallback_enabled=lexical_backend is None,
            )
            retriever_name = _hybrid_retriever_name(lexical_backend_name, vector_backend_name)
        elif lexical_backend is not None and retriever_config != "in_memory_candidate_card":
            retriever = lexical_backend
            retriever_name = lexical_backend_name
        elif index_path is not None and index_path.exists() and retriever_config != "in_memory_candidate_card":
            retriever = SQLiteBM25CandidateRetriever(index_path)
            retriever_name = "sqlite_bm25_legacy"
        small2big_config = rag_config.get("small2big") if isinstance(rag_config.get("small2big"), dict) else {}
        small2big_metadata: dict[str, Any] = {"enabled": False}
        try:
            small2big_enabled = _bool_config(small2big_config, "enabled", False)
        except ValueError as exc:
            small2big_enabled = False
            small2big_metadata = {"enabled": False, "error": str(exc)}
        if small2big_enabled:
            max_parent_profiles_total = _int_config(small2big_config, "max_parent_profiles_total", 6)
            max_parent_profiles_per_item = _int_config(small2big_config, "max_parent_profiles_per_item", 1)
            parent_records = _candidate_parent_records([*ranked_items, *final_items])
            manifest = _small2big_manifest(small2big_config)
            retriever = Small2BigCandidateEvidenceRetriever(
                retriever,
                parent_records=parent_records,
                parent_fields=_string_list(small2big_config.get("parent_fields")) or None,
                parent_profile_max_chars=_int_config(small2big_config, "parent_profile_max_chars", _int_config(small2big_config, "parent_text_max_chars", 1000)),
                max_parent_profiles_total=max_parent_profiles_total,
                max_parent_profiles_per_item=max_parent_profiles_per_item,
                min_base_evidence_total=_int_config(small2big_config, "min_base_evidence_total", 1),
                base_max_evidence_per_item=max_evidence_per_item,
                manifest=manifest,
            )
            retriever_name = f"{retriever_name}_small2big"
            fields = list(dict.fromkeys([*fields, RAG_PARENT_PROFILE_FIELD]))
            max_evidence_per_item += max(0, max_parent_profiles_per_item)
            max_evidence_total += max(0, max_parent_profiles_total)
            small2big_metadata = {
                "enabled": True,
                "parent_field": RAG_PARENT_PROFILE_FIELD,
                "candidate_scoped": True,
                "candidate_generation_allowed": False,
                "ranking_input_replacement_allowed": False,
                "promotion_allowed": False,
                "direct_recommendation_input_allowed": False,
                "consumer": "parent_context_agent",
            }
        context = build_rag_context_for_ranked_candidates(
            query=query,
            candidate_item_ids=candidate_item_ids,
            retriever=retriever,
            policy=RagPolicy(
                mode=mode,
                max_evidence_per_item=max_evidence_per_item,
                max_evidence_total=max_evidence_total,
                max_text_chars=max_text_chars,
                allowed_fields=fields,
            ),
            metadata={"evidence_mode": mode, "retriever": retriever_name, "small2big": small2big_metadata},
        )
        return context.to_dict()


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _int_config(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if value in (None, ""):
        return default
    return int(value)


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        raise ValueError(f"Invalid boolean config for {key}: {value}")
    return bool(value)


def _rag_index_path(rag_config: dict[str, Any]) -> Path | None:
    value = rag_config.get("index_path") or rag_config.get("bm25_index_path")
    if not value:
        return None
    artifact = KnowledgeDataClient(DataClient(project_root=ROOT)).local_rag_index_artifact(
        "runtime-rag-bm25",
        value,
        backend="sqlite_bm25",
        metadata={"candidate_scoped": True, "consumer": "EvidenceRAGFacade"},
    )
    adapter_contract = artifact.metadata["adapter_contract"]
    return Path(str(adapter_contract["resource_ref"]))


def _field_weights(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    return {str(field): float(weight) for field, weight in value.items()}


def _small2big_manifest(config: dict[str, Any]) -> dict[str, Any] | None:
    manifest_value = config.get("parent_store_manifest") or config.get("parent_store_manifest_path") or config.get("manifest")
    if isinstance(manifest_value, dict):
        return manifest_value
    if manifest_value:
        path = _resolve_path(manifest_value)
        if path.exists():
            try:
                return read_json(path)
            except (OSError, ValueError):
                return None
    return None


def _safe_rag_lexical_backend(rag_config: dict[str, Any]) -> tuple[Any | None, str]:
    fallback = rag_config.get("fallback_policy") if isinstance(rag_config.get("fallback_policy"), dict) else {}
    retriever_name = str(fallback.get("fallback_retriever") or rag_config.get("bm25_backend") or "sqlite_bm25").strip().lower()
    if retriever_name in {"elasticsearch", "es", "es_bm25", "elasticsearch_bm25"}:
        backend = _safe_elasticsearch_bm25_backend(rag_config)
        if backend is not None:
            return backend, "elasticsearch_bm25"
        legacy_path = _rag_legacy_index_path(rag_config)
        if _has_legacy_sqlite_index(legacy_path):
            return SQLiteBM25CandidateRetriever(legacy_path), "sqlite_bm25_legacy"
        return None, "elasticsearch_bm25_unavailable"
    if retriever_name in {"sqlite", "sqlite_bm25"}:
        legacy_path = _rag_legacy_index_path(rag_config)
        if _has_legacy_sqlite_index(legacy_path):
            return SQLiteBM25CandidateRetriever(legacy_path), "sqlite_bm25"
    return None, ""


def _safe_elasticsearch_bm25_backend(rag_config: dict[str, Any]) -> ElasticsearchBM25CandidateRetriever | None:
    elasticsearch_config = _elasticsearch_bm25_config(rag_config)
    if not elasticsearch_config.get("enabled", True):
        return None
    if not _has_elasticsearch_target(elasticsearch_config) or not _has_elasticsearch_index(elasticsearch_config):
        return None
    if importlib.util.find_spec("elasticsearch") is None:
        return None
    return ElasticsearchBM25CandidateRetriever(
        config=elasticsearch_config,
        fields=_string_list(rag_config.get("fields")) or list(RAG_STANDARD_FIELDS),
    )


def _elasticsearch_bm25_config(rag_config: dict[str, Any]) -> dict[str, Any]:
    hybrid = rag_config.get("hybrid") if isinstance(rag_config.get("hybrid"), dict) else {}
    config = hybrid.get("elasticsearch") if isinstance(hybrid.get("elasticsearch"), dict) else rag_config.get("elasticsearch")
    return dict(config) if isinstance(config, dict) else {}


def _has_elasticsearch_target(config: dict[str, Any]) -> bool:
    return any(config.get(key) not in (None, "") for key in ("uri", "url", "hosts"))


def _has_elasticsearch_index(config: dict[str, Any]) -> bool:
    return any(config.get(key) not in (None, "") for key in ("index_name", "index", "alias"))


def _rag_legacy_index_path(rag_config: dict[str, Any]) -> Path | None:
    value = rag_config.get("legacy_bm25_index_path") or rag_config.get("bm25_index_path") or rag_config.get("index_path")
    if not value:
        return None
    artifact = KnowledgeDataClient(DataClient(project_root=ROOT)).local_rag_index_artifact(
        "runtime-rag-bm25-legacy",
        value,
        backend="sqlite_bm25",
        metadata={"candidate_scoped": True, "consumer": "EvidenceRAGFacade"},
    )
    adapter_contract = artifact.metadata["adapter_contract"]
    return Path(str(adapter_contract["resource_ref"]))


def _has_legacy_sqlite_index(index_path: Path | None) -> bool:
    return bool(index_path is not None and index_path.exists())


def _hybrid_retriever_name(lexical_backend_name: str, vector_backend_name: str) -> str:
    lexical = lexical_backend_name or "no_lexical"
    vector = vector_backend_name or "no_vector"
    if lexical in {"sqlite_bm25", "sqlite_bm25_legacy"}:
        if vector == "milvus":
            return "hybrid_milvus"
        if vector == "no_vector":
            return "hybrid_bm25_fallback"
    return f"hybrid_{lexical}_{vector}"


def _safe_rag_vector_backend(rag_config: dict[str, Any], hybrid_config: dict[str, Any]) -> tuple[Any | None, str]:
    milvus_backend = _safe_milvus_rag_vector_backend(rag_config, hybrid_config)
    if milvus_backend is not None:
        return milvus_backend, "milvus"
    return None, ""


def _safe_milvus_rag_vector_backend(rag_config: dict[str, Any], hybrid_config: dict[str, Any]) -> MilvusCandidateRagVectorRetriever | None:
    milvus_config = hybrid_config.get("milvus") or rag_config.get("milvus")
    if not isinstance(milvus_config, dict) or not milvus_config.get("enabled", False):
        return None
    if not _has_milvus_target(milvus_config):
        return None
    try:
        backend = _milvus_rag_vector_backend(rag_config, hybrid_config)
        if backend is None:
            return None
        if hasattr(backend.store.client, "has_collection") and not backend.store.client.has_collection(collection_name=backend.collection_name):
            return None
        return backend
    except Exception:
        if bool(milvus_config.get("required", False)):
            raise
        return None


def _milvus_rag_vector_backend(rag_config: dict[str, Any], hybrid_config: dict[str, Any]) -> MilvusCandidateRagVectorRetriever | None:
    milvus_config = hybrid_config.get("milvus") or rag_config.get("milvus")
    if not isinstance(milvus_config, dict) or not milvus_config.get("enabled", False):
        return None
    collection_name = str(milvus_config.get("collection_name") or DEFAULT_MILVUS_RAG_CHUNK_COLLECTION)
    collection_artifact = KnowledgeDataClient(DataClient(project_root=ROOT)).milvus_rag_collection_artifact(
        collection_name,
        metadata={"candidate_scoped": True, "consumer": "EvidenceRAGFacade"},
    )
    adapter_contract = collection_artifact.metadata["adapter_contract"]
    connection_config = dict(milvus_config)
    if connection_config.get("db_path") and not connection_config.get("uri"):
        connection_config["uri"] = connection_config.get("db_path")
    if connection_config.get("path") and not connection_config.get("uri"):
        connection_config["uri"] = connection_config.get("path")
    store = MilvusAdapter.from_config(connection_config, config_ref=str(adapter_contract["connection_ref"])).build_vector_store()
    return MilvusCandidateRagVectorRetriever(
        store=store,
        collection_name=_milvus_collection_name_from_resource_ref(str(adapter_contract["resource_ref"])),
        embedding_model_name=str(milvus_config.get("embedding_model_name") or rag_config.get("embedding_model_name") or "BAAI/bge-m3"),
        embedding_method=str(milvus_config.get("embedding_method") or "sentence_transformer_dense_v1"),
        query_prefix=str(milvus_config.get("query_prefix") or ""),
        embedding_batch_size=int(milvus_config.get("embedding_batch_size", 32) or 32),
        normalize_embeddings=bool(milvus_config.get("normalize_embeddings", True)),
        top_k_multiplier=int(milvus_config.get("top_k_multiplier", hybrid_config.get("vector_top_k_multiplier", 4)) or 4),
        schema_version=str(milvus_config.get("schema_version") or MILVUS_RAG_CHUNK_SCHEMA_VERSION),
        exclude_holdout=bool(milvus_config.get("exclude_holdout", True)),
    )



def _milvus_collection_name_from_resource_ref(resource_ref: str) -> str:
    prefix = "milvus://"
    return resource_ref[len(prefix):] if resource_ref.startswith(prefix) else resource_ref


def _has_milvus_target(milvus_config: dict[str, Any]) -> bool:
    return any(milvus_config.get(key) not in (None, "") for key in ("uri", "path", "db_path"))


def _rag_vector_index_path(rag_config: dict[str, Any], index_path: Path) -> Path | None:
    value = rag_config.get("vector_index_path")
    if value:
        path = _resolve_path(value)
        return path if path.exists() else None

    manifest_value = rag_config.get("manifest_path") or rag_config.get("index_manifest_path")
    manifest_path = _resolve_path(manifest_value) if manifest_value else index_path.with_suffix(index_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        return None
    manifest = read_json(manifest_path)
    vector_index_path = manifest.get("vector_index_path")
    if not vector_index_path:
        return None
    path = _resolve_path(vector_index_path)
    return path if path.exists() else None


def _display_safe_item_cards(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    for item in items:
        card = item_to_display_card(item)
        if card:
            cards[card.parent_asin] = card.to_dict()
    return cards


def _candidate_parent_records(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = str(item.get("parent_asin") or item.get("item_id") or item.get("asin") or "")
        if item_id and item_id not in records:
            records[item_id] = dict(item)
    return records


def _ranked_item_ids(items: list[dict[str, Any]]) -> list[str]:
    item_ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("parent_asin") or item.get("item_id") or "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)
    return item_ids


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path
