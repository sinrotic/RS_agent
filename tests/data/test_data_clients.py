from __future__ import annotations

import pytest

from rs_core.data.clients import (
    ArtifactClient,
    CandidatePoolClient,
    DataClient,
    DatasetClient,
    FeatureClient,
    KnowledgeDataClient,
    MemoryDataClient,
)

pytestmark = pytest.mark.unit


def test_data_clients_expose_manifest_and_backend_status_contracts(tmp_path) -> None:
    data_client = DataClient(project_root=tmp_path)
    dataset = DatasetClient(data_client).manifest(
        "recent-window",
        "datasets/recent.jsonl",
        split="window",
        window="recent-3m",
        freshness="daily",
    )
    feature_view = FeatureClient(data_client).feature_view_contract(
        "ranking-features",
        {"price": "float", "category": "string"},
        source="features/ranking.jsonl",
    )
    artifact_client = ArtifactClient(data_client)
    artifact = artifact_client.artifact(
        "deepfm",
        "models/deepfm.json",
        "model",
        checksum="sha256:test",
        metadata={"model_family": "DeepFM"},
    )
    manifest = artifact_client.manifest(
        "ranking-artifacts",
        [artifact],
        current_route="cold_deepfm",
        metadata={"owner": "offline"},
    )
    memory_ref = MemoryDataClient(data_client).session_memory_ref("session-1", backend_status="disabled")
    pool = CandidatePoolClient(data_client).from_item_ids(
        "pool-smoke",
        ["i1", "i1", "i2"],
        source="manual",
        freshness="smoke",
    )

    assert dataset["path"] == str(tmp_path / "datasets" / "recent.jsonl")
    assert dataset["metadata"] == {"window": "recent-3m", "freshness": "daily"}
    assert feature_view == {
        "schema": {"name": "ranking-features", "columns": {"price": "float", "category": "string"}, "version": "v1"},
        "source": "features/ranking.jsonl",
        "client": "FeatureClient",
    }
    assert artifact.metadata == {"model_family": "DeepFM"}
    assert manifest.to_dict()["current_route"] == "cold_deepfm"
    assert manifest.to_dict()["artifacts"][0]["checksum"] == "sha256:test"
    assert memory_ref == {"session_id": "session-1", "backend": "data-client-managed", "backend_status": "disabled"}
    assert pool.item_ids == ["i1", "i2"]
    assert pool.metadata == {"size": 2, "freshness": "smoke"}


def test_knowledge_data_client_declares_local_rag_index_artifact(tmp_path) -> None:
    client = KnowledgeDataClient(DataClient(project_root=tmp_path))

    artifact = client.local_rag_index_artifact(
        "rag-smoke",
        "indexes/rag.sqlite",
        backend="sqlite_bm25",
        metadata={"candidate_scoped": True},
    )

    payload = artifact.to_dict()

    assert payload["artifact_id"] == "rag-smoke"
    assert payload["uri"] == str(tmp_path / "indexes" / "rag.sqlite")
    assert payload["kind"] == "rag_index"
    assert payload["checksum"] == ""
    assert payload["metadata"]["backend"] == "sqlite_bm25"
    assert payload["metadata"]["role"] == "rag_evidence"
    assert payload["metadata"]["candidate_scoped"] is True
    assert payload["metadata"]["adapter_contract"] == {
        "adapter_id": "rag-smoke",
        "backend": "sqlite_bm25",
        "resource_ref": str(tmp_path / "indexes" / "rag.sqlite"),
        "connection_ref": "local_file",
        "read_only": True,
        "metadata": {"role": "rag_evidence", "candidate_scoped": True},
    }


def test_knowledge_data_client_resolves_runtime_local_rag_index_path(tmp_path) -> None:
    client = KnowledgeDataClient(DataClient(project_root=tmp_path))

    artifact = client.local_rag_index_artifact("runtime-rag-bm25", "rag/index.sqlite")

    assert artifact.uri == str(tmp_path / "rag" / "index.sqlite")
    assert artifact.kind == "rag_index"
    assert artifact.metadata["backend"] == "sqlite_bm25"
    assert artifact.metadata["role"] == "rag_evidence"
    assert artifact.metadata["adapter_contract"]["backend"] == "sqlite_bm25"
    assert artifact.metadata["adapter_contract"]["resource_ref"] == str(tmp_path / "rag" / "index.sqlite")


def test_knowledge_data_client_declares_elasticsearch_rag_index_artifact() -> None:
    artifact = KnowledgeDataClient().elasticsearch_rag_index_artifact(
        "rag_bm25",
        metadata={"candidate_scoped": True},
    )

    payload = artifact.to_dict()

    assert payload["artifact_id"] == "rag_bm25"
    assert payload["uri"] == "elasticsearch://rag_bm25"
    assert payload["kind"] == "rag_lexical_index"
    assert payload["checksum"] == ""
    assert payload["metadata"]["backend"] == "elasticsearch_bm25"
    assert payload["metadata"]["role"] == "rag_evidence"
    assert payload["metadata"]["candidate_scoped"] is True
    assert payload["metadata"]["adapter_contract"] == {
        "adapter_id": "rag_bm25",
        "backend": "elasticsearch_bm25",
        "resource_ref": "elasticsearch://rag_bm25",
        "connection_ref": "env:RS_ELASTICSEARCH_*",
        "read_only": True,
        "metadata": {"role": "rag_evidence", "candidate_scoped": True},
    }


    artifact = KnowledgeDataClient().milvus_rag_collection_artifact(
        "rag_chunks",
        metadata={"candidate_scoped": True},
    )

    payload = artifact.to_dict()

    assert payload["artifact_id"] == "rag_chunks"
    assert payload["uri"] == "milvus://rag_chunks"
    assert payload["kind"] == "rag_vector_collection"
    assert payload["checksum"] == ""
    assert payload["metadata"]["backend"] == "milvus"
    assert payload["metadata"]["role"] == "rag_evidence"
    assert payload["metadata"]["candidate_scoped"] is True
    assert payload["metadata"]["adapter_contract"] == {
        "adapter_id": "rag_chunks",
        "backend": "milvus",
        "resource_ref": "milvus://rag_chunks",
        "connection_ref": "env:RS_MILVUS_*",
        "read_only": True,
        "metadata": {"role": "rag_evidence", "candidate_scoped": True},
    }
