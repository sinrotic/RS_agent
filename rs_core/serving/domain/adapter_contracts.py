from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AdapterConfig:
    name: str
    backend: str
    sync_path: bool
    async_path: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    governance_tags: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("adapter name is required")
        if not self.backend:
            errors.append(f"{self.name}: backend is required")
        if not self.sync_path and not self.async_path:
            errors.append(f"{self.name}: at least one sync_path or async_path is required")
        if any(not tag for tag in self.governance_tags):
            errors.append(f"{self.name}: governance_tags entries must be non-empty")
        return errors


@dataclass(frozen=True)
class AdapterValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeQuery:
    query: str
    top_k: int = 5
    timeout_seconds: float = 10.0
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeResult:
    documents: tuple[dict[str, Any], ...]
    latency_ms: float = 0.0
    degraded: bool = False


@dataclass(frozen=True)
class TaskRef:
    task_id: str
    task_type: str
    status: str


@runtime_checkable
class StoreAdapter(Protocol):
    config: AdapterConfig

    def write_fact(self, fact_type: str, payload: dict[str, Any]) -> str:
        ...

    def read_fact(self, fact_id: str) -> dict[str, Any] | None:
        ...


@runtime_checkable
class CacheAdapter(Protocol):
    config: AdapterConfig

    def get(self, key: str) -> Any | None:
        ...

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        ...

    def delete(self, key: str) -> None:
        ...


@runtime_checkable
class ArtifactAdapter(Protocol):
    config: AdapterConfig

    def exists(self, path_or_uri: str) -> bool:
        ...

    def load_metadata(self, path_or_uri: str) -> dict[str, Any]:
        ...

    def resolve(self, artifact_id: str) -> ArtifactRef | None:
        ...


@runtime_checkable
class KnowledgeAdapter(Protocol):
    config: AdapterConfig

    def query(self, request: KnowledgeQuery) -> KnowledgeResult:
        """Synchronous online RAG query used by the Agent recommendation path."""
        ...

    def request_index_refresh(self, *, reason: str, payload: dict[str, Any] | None = None) -> TaskRef:
        """Asynchronous RAG index build/refresh request; never blocks online query."""
        ...


@runtime_checkable
class TaskAdapter(Protocol):
    config: AdapterConfig

    def enqueue(self, task_type: str, payload: dict[str, Any]) -> TaskRef:
        ...

    def status(self, task_id: str) -> TaskRef | None:
        ...


class MockStoreAdapter:
    def __init__(self, config: AdapterConfig | None = None) -> None:
        self.config = config or AdapterConfig(name="mock_store", backend="memory", sync_path=True, governance_tags=("canonical_facts", "public_safe_projection"))
        self._facts: dict[str, dict[str, Any]] = {}

    def write_fact(self, fact_type: str, payload: dict[str, Any]) -> str:
        fact_id = f"{fact_type}:{len(self._facts) + 1}"
        self._facts[fact_id] = {"fact_type": fact_type, **payload}
        return fact_id

    def read_fact(self, fact_id: str) -> dict[str, Any] | None:
        return self._facts.get(fact_id)


class MockCacheAdapter:
    def __init__(self, config: AdapterConfig | None = None) -> None:
        self.config = config or AdapterConfig(name="mock_cache", backend="memory", sync_path=True)
        self._values: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._values.get(key)

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._values[key] = value

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class MockArtifactAdapter:
    def __init__(self, root: str | Path, config: AdapterConfig | None = None) -> None:
        self.root = Path(root)
        self.config = config or AdapterConfig(name="mock_artifact", backend="local", sync_path=True, governance_tags=("manifest_gate", "provenance_gate"))
        self._refs: dict[str, ArtifactRef] = {}

    def register(self, ref: ArtifactRef) -> None:
        self._refs[ref.artifact_id] = ref

    def exists(self, path_or_uri: str) -> bool:
        path = Path(path_or_uri)
        if not path.is_absolute():
            path = self.root / path
        return path.exists()

    def load_metadata(self, path_or_uri: str) -> dict[str, Any]:
        return {"path": path_or_uri, "exists": self.exists(path_or_uri)}

    def resolve(self, artifact_id: str) -> ArtifactRef | None:
        return self._refs.get(artifact_id)


class MockKnowledgeAdapter:
    def __init__(self, config: AdapterConfig | None = None) -> None:
        self.config = config or AdapterConfig(
            name="mock_knowledge",
            backend="memory",
            sync_path=True,
            async_path=True,
            governance_tags=("online_rag_query", "candidate_scoped_evidence", "query_planning_scope", "no_ranking_replacement"),
        )
        self.refresh_requests: list[TaskRef] = []

    def query(self, request: KnowledgeQuery) -> KnowledgeResult:
        return KnowledgeResult(
            documents=({"text": request.query, "rank": 1, "source": "mock"},),
            latency_ms=0.0,
            degraded=False,
        )

    def request_index_refresh(self, *, reason: str, payload: dict[str, Any] | None = None) -> TaskRef:
        task = TaskRef(task_id=f"knowledge-refresh-{len(self.refresh_requests) + 1}", task_type="rag_index_refresh", status="queued")
        self.refresh_requests.append(task)
        return task


class MockTaskAdapter:
    def __init__(self, config: AdapterConfig | None = None) -> None:
        self.config = config or AdapterConfig(name="mock_task", backend="memory", sync_path=False, async_path=True, governance_tags=("async_worker", "fail_closed"))
        self._tasks: dict[str, TaskRef] = {}

    def enqueue(self, task_type: str, payload: dict[str, Any]) -> TaskRef:
        task = TaskRef(task_id=f"task-{len(self._tasks) + 1}", task_type=task_type, status="queued")
        self._tasks[task.task_id] = task
        return task

    def status(self, task_id: str) -> TaskRef | None:
        return self._tasks.get(task_id)


def validate_adapter_contract(adapter: Any, required_methods: tuple[str, ...]) -> AdapterValidationResult:
    errors: list[str] = []
    config = getattr(adapter, "config", None)
    if not isinstance(config, AdapterConfig):
        errors.append("adapter.config must be an AdapterConfig")
    else:
        errors.extend(config.validate())
    for method in required_methods:
        if not callable(getattr(adapter, method, None)):
            errors.append(f"missing callable method: {method}")
    return AdapterValidationResult(valid=not errors, errors=tuple(errors))


def validate_standard_adapters(
    *,
    store: StoreAdapter,
    cache: CacheAdapter,
    artifact: ArtifactAdapter,
    knowledge: KnowledgeAdapter,
    task: TaskAdapter,
) -> AdapterValidationResult:
    errors: list[str] = []
    checks = (
        validate_adapter_contract(store, ("write_fact", "read_fact")),
        validate_adapter_contract(cache, ("get", "set", "delete")),
        validate_adapter_contract(artifact, ("exists", "load_metadata", "resolve")),
        validate_adapter_contract(knowledge, ("query", "request_index_refresh")),
        validate_adapter_contract(task, ("enqueue", "status")),
    )
    for check in checks:
        errors.extend(check.errors)
    return AdapterValidationResult(valid=not errors, errors=tuple(errors))


__all__ = (
    "AdapterConfig",
    "AdapterValidationResult",
    "ArtifactRef",
    "KnowledgeQuery",
    "KnowledgeResult",
    "TaskRef",
    "StoreAdapter",
    "CacheAdapter",
    "ArtifactAdapter",
    "KnowledgeAdapter",
    "TaskAdapter",
    "MockStoreAdapter",
    "MockCacheAdapter",
    "MockArtifactAdapter",
    "MockKnowledgeAdapter",
    "MockTaskAdapter",
    "validate_adapter_contract",
    "validate_standard_adapters",
)
