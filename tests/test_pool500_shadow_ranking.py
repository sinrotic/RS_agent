from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

import rs_core.workflow.pool500_shadow_ranking as pool500_shadow_ranking
from rs_core.recsys.types import MergedCandidate
from rs_core.workflow.pool500_shadow_ranking import (
    FULL_POOL500_READY,
    PASS,
    SCHEMA_VERSION,
    STOP,
    build_pool500_shadow_ranking_evidence,
    run_pool500_shadow_ranking,
    validate_pool500_shadow_ranking_evidence,
)


def _evidence(**overrides: object) -> dict[str, object]:
    evidence = build_pool500_shadow_ranking_evidence(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        shadow_metrics={"ndcg_at_20_delta": 0.01, "coverage_delta": 0.0},
        source_artifact_gate_result={"decision": FULL_POOL500_READY},
        source_shadow_evidence_validation={"status": PASS},
    )
    evidence.update(overrides)
    return evidence


def _blocker_codes(result: dict[str, object]) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}  # type: ignore[index]


def test_pool500_shadow_ranking_evidence_is_diagnostic_only_contract() -> None:
    evidence = _evidence()
    validation = validate_pool500_shadow_ranking_evidence(evidence)

    assert evidence["schema_version"] == SCHEMA_VERSION
    assert evidence["diagnostic_method_id"] == "pool500_shadow_ranker_metrics_v1"
    assert evidence["comparison_group"] == "current_pool200_ranking_baseline"
    assert isinstance(evidence["shadow_metrics"], dict)
    assert evidence["candidate_generation_allowed"] is False
    assert evidence["ranking_input_replacement_allowed"] is False
    assert evidence["ranking_replacement_allowed"] is False
    assert evidence["promotion_allowed"] is False
    assert evidence["pool1000_allowed"] is False
    assert evidence["diagnostic_only"] is True
    assert validation["status"] == PASS
    assert validation["blockers"] == []


@pytest.mark.parametrize(
    "field",
    [
        "candidate_generation_allowed",
        "ranking_input_replacement_allowed",
        "ranking_replacement_allowed",
        "promotion_allowed",
        "pool1000_allowed",
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_truthy_forbidden_flags(field: str) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(**{field: True}))

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_DIAGNOSTIC_FLAG_REQUIRED" in _blocker_codes(validation)
    assert validation[field] is False


@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"current_ranking_route": "pool500"},
        {"candidate_id": "pool500-v1"},
        {"candidate_type": "replacement"},
        {"promotion_lane": "ranking"},
        {"promotion_eligible": True},
        {"lane": "champion"},
        {"run_kind": "variant"},
        {"shadow_metrics": {"run_kind": "variant"}},
        {"shadow_metrics": {"nested": {"run_kind": "challenger"}}},
        {"shadow_metrics": {"run_kind": "candidate"}},
        {"shadow_metrics": {"run_kind": "champion"}},
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_promotion_route_semantics(forbidden_payload: dict[str, object]) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(**forbidden_payload))

    assert validation["decision"] == STOP
    assert _blocker_codes(validation) & {
        "POOL500_SHADOW_RANKING_FORBIDDEN_FIELD",
        "POOL500_SHADOW_RANKING_FORBIDDEN_RUN_KIND",
    }


def test_pool500_shadow_ranking_evidence_validates_source_gate_linkage_when_supplied() -> None:
    artifact_validation = validate_pool500_shadow_ranking_evidence(_evidence(source_artifact_gate_decision="DIAGNOSTIC_ONLY_PARTIAL"))
    shadow_validation = validate_pool500_shadow_ranking_evidence(_evidence(source_shadow_evidence_decision=STOP))

    assert artifact_validation["decision"] == STOP
    assert "POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY" in _blocker_codes(artifact_validation)
    assert shadow_validation["decision"] == STOP
    assert "POOL500_SOURCE_SHADOW_EVIDENCE_NOT_PASS" in _blocker_codes(shadow_validation)


def test_pool500_shadow_runner_ranks_candidates_and_emits_diagnostic_evidence() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        candidates_by_user={
            "u1": [
                MergedCandidate("i1", ["popular"], {"popular": 0.2}, "cat"),
                MergedCandidate("i2", ["semantic"], {"semantic": 0.5}, "cat"),
            ],
        },
        config={"rank_weights": {"popular": 1.0, "semantic": 1.0}},
        artifact_gate_result={"decision": FULL_POOL500_READY, "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
        top_k=1,
    )

    assert result["status"] == PASS
    assert result["evidence"]["diagnostic_only"] is True
    assert result["evidence"]["shadow_metrics"]["user_count"] == 1
    assert result["evidence"]["shadow_metrics"]["top_k"] == 1
    assert result["ranking_results"]["u1"][0]["parent_asin"] == "i2"
    top_item = result["ranking_results"]["u1"][0]
    score_trace = top_item["score_trace"]
    assert [stage["stage"] for stage in score_trace] == ["coarse", "fine", "rerank"]
    assert top_item["final_rank"] == 1
    assert top_item["rank_movement"] == {"coarse_to_fine": 0, "fine_to_final": 0, "coarse_to_final": 0}
    assert result["evidence"]["shadow_metrics"]["stage_trace_coverage"] == {"coarse": 1.0, "fine": 1.0, "rerank": 1.0}


def test_pool500_shadow_runner_rows_adapter_path_preserves_score_trace() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        rows=[
            {"user_id": "u1", "item_id": "i1", "source": "popular_recall", "score": 0.2, "rank": 2, "metadata": {"category": "cat"}},
            {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.5, "rank": 1, "metadata": {"category": "cat"}},
        ],
        config={"rank_weights": {"popular": 1.0, "semantic": 1.0}},
        artifact_gate_result={"decision": FULL_POOL500_READY, "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
        top_k=2,
    )

    assert result["status"] == PASS
    assert result["adapter_result"]["status"] == PASS
    score_traces = [item["score_trace"] for item in result["ranking_results"]["u1"]]
    assert score_traces
    assert all([stage["stage"] for stage in trace] == ["coarse", "fine", "rerank"] for trace in score_traces)
    assert result["evidence"]["shadow_metrics"]["stage_trace_coverage"] == {"coarse": 1.0, "fine": 1.0, "rerank": 1.0}


def test_pool500_shadow_runner_does_not_use_pool200_ranking_run_row() -> None:
    source = inspect.getsource(pool500_shadow_ranking)

    assert "build_ranking_run_row" not in source


def test_pool500_shadow_runner_stops_before_ranking_when_preflight_fails() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        candidates_by_user={"u1": [MergedCandidate("i1", ["popular"], {"popular": 1.0})]},
        config={},
        artifact_gate_result={"decision": "DIAGNOSTIC_ONLY_PARTIAL", "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
    )

    assert result["status"] == STOP
    assert result["ranking_results"] == {}
    assert result["evidence"]["shadow_metrics"]["stopped_before_ranking"] is True
    assert "POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY" in _blocker_codes(result)
