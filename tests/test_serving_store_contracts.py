from __future__ import annotations

import pytest

from rs_core.serving.store_contracts import (
    FailurePolicy,
    PHASE1A_CONFIG_DEFAULTS,
    RAG_EVIDENCE_CONTRACT,
    TRACE_ID_MAPPING,
    StoreKind,
    assert_safe_wrapper_compatible,
    store_contract_matrix,
)

pytestmark = [pytest.mark.unit, pytest.mark.serving]


def test_store_failure_policy_matrix_matches_phase1a_plan() -> None:
    contracts = {contract.kind: contract for contract in store_contract_matrix()}

    assert contracts[StoreKind.LOCAL_AUDIT].failure_policy == (FailurePolicy.FAIL_OPEN,)
    assert contracts[StoreKind.LOCAL_AUDIT].canonical_source is False
    assert contracts[StoreKind.LOCAL_AUDIT].safe_wrapper_allowed is True

    assert contracts[StoreKind.CANONICAL_FACTS].failure_policy == (FailurePolicy.FAIL_CLOSED,)
    assert contracts[StoreKind.CANONICAL_FACTS].canonical_source is True
    assert contracts[StoreKind.CANONICAL_FACTS].safe_wrapper_allowed is False

    assert contracts[StoreKind.DERIVED_SINK].failure_policy == (FailurePolicy.FAIL_OPEN, FailurePolicy.RETRY)
    assert contracts[StoreKind.DERIVED_SINK].canonical_source is False
    assert contracts[StoreKind.DERIVED_SINK].safe_wrapper_allowed is True
    assert set(contracts) == set(StoreKind)


def test_safe_serving_wrapper_cannot_wrap_strict_canonical_facts_store() -> None:
    assert_safe_wrapper_compatible(StoreKind.LOCAL_AUDIT)
    assert_safe_wrapper_compatible(StoreKind.DERIVED_SINK)

    with pytest.raises(ValueError, match="must not wrap canonical_facts"):
        assert_safe_wrapper_compatible(StoreKind.CANONICAL_FACTS)


def test_trace_id_mapping_covers_phase1a_required_identifiers() -> None:
    assert set(TRACE_ID_MAPPING) == {
        "http_request_id",
        "operation_id",
        "event_id",
        "turn_id",
        "artifact_manifest_id",
    }
    assert TRACE_ID_MAPPING["http_request_id"]["source"] == "X-Request-ID header or generated middleware id"
    assert "/session/start" in TRACE_ID_MAPPING["operation_id"]["endpoints"]
    assert "/chat" in TRACE_ID_MAPPING["turn_id"]["endpoints"]
    assert "/recommend" in TRACE_ID_MAPPING["artifact_manifest_id"]["endpoints"]


def test_phase1a_config_defaults_are_contract_only_and_sqlite_local() -> None:
    assert PHASE1A_CONFIG_DEFAULTS == {
        "STORE_BACKEND": "sqlite_local",
        "EVENT_SOURCE": "jsonl",
        "TRACE_SCHEMA_VERSION": "v1",
        "SERVING_GOVERNANCE_ENFORCEMENT": "strict",
    }


def test_rag_evidence_contract_separates_planning_from_public_explanation() -> None:
    assert "never exported directly" in RAG_EVIDENCE_CONTRACT["PlanningEvidence"]
    assert "candidate-scoped public evidence" in RAG_EVIDENCE_CONTRACT["FinalExplanationEvidence"]
