from __future__ import annotations

import pytest

from scripts.experiments.recall.pool500.audit_co_visit_fallback_repair_task import (
    CO_VISIT_CANONICAL_SOURCE,
    CO_VISIT_FALLBACK_SOURCE,
    DIAGNOSTIC_ONLY,
    PASS_GUARDED_FALLBACK_REPAIR,
    STOP,
    build_co_visit_fallback_repair_task_audit,
)

pytestmark = pytest.mark.unit


def _fallback_audit(co_visit_count: int = 7) -> dict[str, object]:
    return {
        "global": {
            "target_user_count": 2,
            "users_with_target_candidates": 2,
            "underfilled_user_count": 0,
            "fallback_source_contribution": {
                "personalized_primary": 993,
                CO_VISIT_FALLBACK_SOURCE: co_visit_count,
            },
            "duplicate_item_per_user_count": 0,
            "per_user_over_target_count": 0,
            "average_fallback_ratio": 0.007,
            "average_popular_ratio": 0.15,
        },
        "per_user": [
            {"user_id": "u1", "completion_status": "TARGET_MET", "source_mix": {CO_VISIT_FALLBACK_SOURCE: co_visit_count}},
            {"user_id": "u2", "completion_status": "TARGET_MET", "source_mix": {}},
        ],
    }


def test_co_visit_fallback_task_gate_passes_underfill_repair_role() -> None:
    audit = build_co_visit_fallback_repair_task_audit(
        fallback_completion_audit=_fallback_audit(),
        fallback_completion_validation={"valid": True},
        underfill_audit={"status": "PASS", "remaining_underfilled_user_count": 0, "users_with_500_candidates": 2},
        source_contribution_audit={"sources": {CO_VISIT_CANONICAL_SOURCE: {"row_count": 7}}},
        source_overlap_audit={"pairwise_user_item_overlap_count": {CO_VISIT_CANONICAL_SOURCE: {"popular": 1}}},
    )

    assert audit["decision"] == PASS_GUARDED_FALLBACK_REPAIR
    assert audit["status"] == "PASS"
    assert audit["source"] == CO_VISIT_CANONICAL_SOURCE
    assert audit["fallback_source"] == CO_VISIT_FALLBACK_SOURCE
    assert audit["primary_acceptance_metric"] == "fallback_underfill_repair_completion"
    assert audit["global"]["co_visit_fallback_added_count"] == 7
    assert audit["promotion_allowed"] is False
    assert audit["ranking_input_replacement_allowed"] is False
    assert audit["pool1000_allowed"] is False
    assert audit["final_pool500_ready_claimed"] is False


def test_co_visit_fallback_task_gate_requires_actual_contribution() -> None:
    audit = build_co_visit_fallback_repair_task_audit(
        fallback_completion_audit=_fallback_audit(co_visit_count=0),
        fallback_completion_validation={"valid": True},
    )

    assert audit["decision"] == DIAGNOSTIC_ONLY
    assert "co_visit_required_for_guarded_merge_but_absent" in audit["diagnostics"]


def test_co_visit_fallback_task_gate_stops_on_contract_or_governance_violation() -> None:
    audit = build_co_visit_fallback_repair_task_audit(
        fallback_completion_audit=_fallback_audit(),
        fallback_completion_validation={"valid": False},
        route_manifest={"promotion_allowed": True},
    )

    assert audit["decision"] == STOP
    assert set(audit["blockers"]) >= {"fallback_completion_validation_invalid", "route_manifest_governance_flag_open"}
