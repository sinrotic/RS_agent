from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class FailurePolicy(str, Enum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"
    RETRY = "retry"


class StoreKind(str, Enum):
    LOCAL_AUDIT = "local_audit"
    CANONICAL_FACTS = "canonical_facts"
    DERIVED_SINK = "derived_sink"


@dataclass(frozen=True)
class StoreContract:
    kind: StoreKind
    responsibility: str
    failure_policy: tuple[FailurePolicy, ...]
    canonical_source: bool
    safe_wrapper_allowed: bool


STORE_CONTRACTS: Final[dict[StoreKind, StoreContract]] = {
    StoreKind.LOCAL_AUDIT: StoreContract(
        kind=StoreKind.LOCAL_AUDIT,
        responsibility="SQLite/JSONL local audit records and public replay support",
        failure_policy=(FailurePolicy.FAIL_OPEN,),
        canonical_source=False,
        safe_wrapper_allowed=True,
    ),
    StoreKind.CANONICAL_FACTS: StoreContract(
        kind=StoreKind.CANONICAL_FACTS,
        responsibility="MySQL structured facts for sessions, turns, feedback, request summaries, and outbox events",
        failure_policy=(FailurePolicy.FAIL_CLOSED,),
        canonical_source=True,
        safe_wrapper_allowed=False,
    ),
    StoreKind.DERIVED_SINK: StoreContract(
        kind=StoreKind.DERIVED_SINK,
        responsibility="Derived audit, analytics, metrics, and dashboard sinks",
        failure_policy=(FailurePolicy.FAIL_OPEN, FailurePolicy.RETRY),
        canonical_source=False,
        safe_wrapper_allowed=True,
    ),
}

TRACE_ID_MAPPING: Final[dict[str, dict[str, str]]] = {
    "http_request_id": {
        "scope": "HTTP boundary",
        "source": "X-Request-ID header or generated middleware id",
        "endpoints": "all FastAPI endpoints",
    },
    "operation_id": {
        "scope": "ServingOperationUnitOfWork root id",
        "source": "created once per mutating serving operation before facts commit",
        "endpoints": "/session/start, /chat, /feedback, /session/end",
    },
    "event_id": {
        "scope": "business event or outbox row id",
        "source": "created when a canonical event is persisted",
        "endpoints": "mutating endpoints and derived sinks",
    },
    "turn_id": {
        "scope": "session turn identity",
        "source": "session_id + turn_index stable composite identity",
        "endpoints": "/chat, /feedback, GET /session/{session_id}",
    },
    "artifact_manifest_id": {
        "scope": "offline artifact lineage",
        "source": "route registry or artifact manifest reference",
        "endpoints": "/recommend, /recall, readiness checks",
    },
}

PHASE1A_CONFIG_DEFAULTS: Final[dict[str, str]] = {
    "STORE_BACKEND": "sqlite_local",
    "EVENT_SOURCE": "jsonl",
    "TRACE_SCHEMA_VERSION": "v1",
    "SERVING_GOVERNANCE_ENFORCEMENT": "strict",
}

RAG_EVIDENCE_CONTRACT: Final[dict[str, str]] = {
    "PlanningEvidence": "internal retrieval and ranking support; never exported directly in public explanations",
    "FinalExplanationEvidence": "candidate-scoped public evidence only, after forbidden provenance filtering",
}


def assert_safe_wrapper_compatible(store_kind: StoreKind | str) -> None:
    kind = StoreKind(store_kind)
    contract = STORE_CONTRACTS[kind]
    if not contract.safe_wrapper_allowed:
        raise ValueError(f"SafeServingPersistenceStore must not wrap {kind.value}")


def store_contract_matrix() -> list[StoreContract]:
    return [STORE_CONTRACTS[kind] for kind in StoreKind]
