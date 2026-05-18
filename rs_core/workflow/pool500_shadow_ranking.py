from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Iterable

from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import MergedCandidate
from rs_core.workflow.pool500_ranking_adapter import adapt_pool500_rows_to_candidates

SCHEMA_VERSION = "pool500_shadow_ranking_evidence_v1"
FULL_POOL500_READY = "FULL_POOL500_READY"
PASS = "PASS"
STOP = "STOP"

DIAGNOSTIC_ONLY_FLAGS = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "ranking_replacement_allowed": False,
    "promotion_allowed": False,
    "pool1000_allowed": False,
    "diagnostic_only": True,
}

FORBIDDEN_FIELDS = {
    "current_ranking_route",
    "candidate_id",
    "candidate_type",
    "promotion_lane",
    "promotion_eligible",
    "lane",
}
FORBIDDEN_RUN_KINDS = {"variant", "challenger", "candidate", "champion"}


def build_pool500_shadow_ranking_evidence(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    shadow_metrics: dict[str, Any],
    source_artifact_gate_result: dict[str, Any] | None = None,
    source_shadow_evidence_validation: dict[str, Any] | None = None,
    source_artifact_gate_decision: str | None = None,
    source_shadow_evidence_decision: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact_decision = source_artifact_gate_decision
    if artifact_decision is None and isinstance(source_artifact_gate_result, dict):
        artifact_decision = source_artifact_gate_result.get("decision")
    shadow_decision = source_shadow_evidence_decision
    if shadow_decision is None and isinstance(source_shadow_evidence_validation, dict):
        shadow_decision = source_shadow_evidence_validation.get("status")
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_method_id": diagnostic_method_id,
        "comparison_group": comparison_group,
        "shadow_metrics": dict(shadow_metrics),
        "source_artifact_gate_decision": artifact_decision,
        "source_shadow_evidence_decision": shadow_decision,
        **DIAGNOSTIC_ONLY_FLAGS,
        "generated_at": generated_at,
    }


def run_pool500_shadow_ranking(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    config: dict[str, Any],
    artifact_gate_result: dict[str, Any],
    recall_shadow_evidence_validation: dict[str, Any] | None = None,
    candidates_by_user: dict[str, list[MergedCandidate]] | None = None,
    rows: Iterable[dict[str, Any]] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    blockers = _preflight_blockers(artifact_gate_result, recall_shadow_evidence_validation)
    adapter_result: dict[str, Any] | None = None
    if candidates_by_user is None:
        if rows is None:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_INPUT_REQUIRED", {"required": "candidates_by_user or rows"}))
            candidates_by_user = {}
        else:
            adapter_result = adapt_pool500_rows_to_candidates(rows)
            candidates_by_user = adapter_result["candidates_by_user"]
            if adapter_result.get("status") != PASS:
                blockers.extend(adapter_result.get("blockers", []))

    if blockers:
        return _stop_result(
            diagnostic_method_id=diagnostic_method_id,
            comparison_group=comparison_group,
            artifact_gate_result=artifact_gate_result,
            recall_shadow_evidence_validation=recall_shadow_evidence_validation,
            blockers=blockers,
            adapter_result=adapter_result,
            top_k=top_k,
        )

    ranking_results: dict[str, list[dict[str, Any]]] = {}
    for user_id in sorted(candidates_by_user):
        ranking = rank_candidates(user_id, candidates_by_user[user_id], config, top_k=top_k)
        ranking_results[user_id] = [_ranking_item_payload(item) for item in ranking.items]

    shadow_metrics = _shadow_metrics(candidates_by_user, ranking_results, top_k)
    evidence = build_pool500_shadow_ranking_evidence(
        diagnostic_method_id=diagnostic_method_id,
        comparison_group=comparison_group,
        shadow_metrics=shadow_metrics,
        source_artifact_gate_result=artifact_gate_result,
        source_shadow_evidence_validation=recall_shadow_evidence_validation,
    )
    validation = validate_pool500_shadow_ranking_evidence(evidence)
    status = PASS if validation["status"] == PASS else STOP
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "decision": status,
        "evidence": evidence,
        "validation": validation,
        "ranking_results": ranking_results if status == PASS else {},
        "adapter_result": _adapter_summary(adapter_result),
        "blockers": validation["blockers"],
        "diagnostics": [],
    }


def validate_pool500_shadow_ranking_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        blockers.append(_blocker("POOL500_SHADOW_RANKING_SCHEMA_VERSION_MISMATCH", {"schema_version": evidence.get("schema_version")}))
    for field, expected in DIAGNOSTIC_ONLY_FLAGS.items():
        if evidence.get(field) is not expected:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_DIAGNOSTIC_FLAG_REQUIRED", {"field": field, "value": evidence.get(field), "required": expected}))
    if not evidence.get("diagnostic_method_id"):
        blockers.append(_blocker("POOL500_SHADOW_RANKING_METHOD_ID_REQUIRED", {"diagnostic_method_id": evidence.get("diagnostic_method_id")}))
    if not evidence.get("comparison_group"):
        blockers.append(_blocker("POOL500_SHADOW_RANKING_COMPARISON_GROUP_REQUIRED", {"comparison_group": evidence.get("comparison_group")}))
    if not isinstance(evidence.get("shadow_metrics"), dict):
        blockers.append(_blocker("POOL500_SHADOW_RANKING_METRICS_REQUIRED", {"shadow_metrics_type": type(evidence.get("shadow_metrics")).__name__}))
    artifact_decision = evidence.get("source_artifact_gate_decision")
    if artifact_decision is not None and artifact_decision != FULL_POOL500_READY:
        blockers.append(_blocker("POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY", {"source_artifact_gate_decision": artifact_decision, "required": FULL_POOL500_READY}))
    shadow_decision = evidence.get("source_shadow_evidence_decision")
    if shadow_decision is not None and shadow_decision != PASS:
        blockers.append(_blocker("POOL500_SOURCE_SHADOW_EVIDENCE_NOT_PASS", {"source_shadow_evidence_decision": shadow_decision, "required": PASS}))
    blockers.extend(_validate_forbidden_semantics(evidence))
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": PASS if not blockers else STOP,
        "status": PASS if not blockers else STOP,
        **DIAGNOSTIC_ONLY_FLAGS,
        "blockers": blockers,
    }


def _preflight_blockers(
    artifact_gate_result: dict[str, Any],
    recall_shadow_evidence_validation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    artifact_decision = artifact_gate_result.get("decision") if isinstance(artifact_gate_result, dict) else None
    artifact_status = artifact_gate_result.get("status") if isinstance(artifact_gate_result, dict) else None
    if artifact_decision != FULL_POOL500_READY or artifact_status not in {None, PASS}:
        blockers.append(_blocker("POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY", {"source_artifact_gate_decision": artifact_decision, "source_artifact_gate_status": artifact_status, "required_decision": FULL_POOL500_READY, "required_status": PASS}))
    if recall_shadow_evidence_validation is not None and recall_shadow_evidence_validation.get("status") != PASS:
        blockers.append(_blocker("POOL500_SOURCE_SHADOW_EVIDENCE_NOT_PASS", {"source_shadow_evidence_decision": recall_shadow_evidence_validation.get("decision"), "source_shadow_evidence_status": recall_shadow_evidence_validation.get("status"), "required": PASS}))
    return blockers


def _stop_result(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    artifact_gate_result: dict[str, Any],
    recall_shadow_evidence_validation: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    adapter_result: dict[str, Any] | None,
    top_k: int,
) -> dict[str, Any]:
    evidence = build_pool500_shadow_ranking_evidence(
        diagnostic_method_id=diagnostic_method_id,
        comparison_group=comparison_group,
        shadow_metrics={"user_count": 0, "top_k": top_k, "stopped_before_ranking": True},
        source_artifact_gate_result=artifact_gate_result,
        source_shadow_evidence_validation=recall_shadow_evidence_validation,
    )
    validation = validate_pool500_shadow_ranking_evidence(evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STOP,
        "decision": STOP,
        "evidence": evidence,
        "validation": validation,
        "ranking_results": {},
        "adapter_result": _adapter_summary(adapter_result),
        "blockers": [*blockers, *validation["blockers"]],
        "diagnostics": [],
    }


def _shadow_metrics(
    candidates_by_user: dict[str, list[MergedCandidate]],
    ranking_results: dict[str, list[dict[str, Any]]],
    top_k: int,
) -> dict[str, Any]:
    pool_sizes = [len(candidates) for candidates in candidates_by_user.values()]
    ranked_items = [item for items in ranking_results.values() for item in items]
    return {
        "user_count": len(candidates_by_user),
        "top_k": top_k,
        "input_pool_size_distribution": _distribution(pool_sizes),
        "underfilled_user_count": sum(1 for size in pool_sizes if size < top_k),
        "stage_trace_coverage": _stage_trace_coverage(ranked_items),
        "topk_source_contribution": dict(sorted(_topk_source_contribution(ranked_items).items())),
    }


def _distribution(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "p50": None, "avg": None, "max": None}
    ordered = sorted(values)
    return {"min": ordered[0], "p50": ordered[len(ordered) // 2], "avg": round(mean(ordered), 6), "max": ordered[-1]}


def _stage_trace_coverage(items: list[dict[str, Any]]) -> dict[str, float]:
    stages = ("coarse", "fine", "rerank")
    if not items:
        return {stage: 0.0 for stage in stages}
    coverage: dict[str, float] = {}
    for stage in stages:
        covered = sum(1 for item in items if any(trace.get("stage") == stage for trace in item.get("score_trace", [])))
        coverage[stage] = round(covered / len(items), 6)
    return coverage


def _topk_source_contribution(items: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        for source in item.get("sources", []):
            counts[str(source)] += 1
    return counts


def _ranking_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "parent_asin",
        "score",
        "base_score",
        "coarse_score",
        "agent_boost",
        "fine_score",
        "rerank_score",
        "final_score",
        "score_trace",
        "sources",
        "category",
        "feature_score",
        "normalized_additive_score",
        "item_features",
        "score_components",
        "ltr_score",
        "rerank_events",
        "coarse_rank",
        "fine_rank",
        "final_rank",
        "rank_movement",
    }
    return {key: item[key] for key in keys if key in item}


def _adapter_summary(adapter_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if adapter_result is None:
        return None
    return {
        "schema_version": adapter_result.get("schema_version"),
        "status": adapter_result.get("status"),
        "decision": adapter_result.get("decision"),
        "candidate_pool_limit": adapter_result.get("candidate_pool_limit"),
        "blockers": adapter_result.get("blockers", []),
        "diagnostics": adapter_result.get("diagnostics", []),
    }


def _validate_forbidden_semantics(payload: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for key, value in _walk(payload):
        leaf = key.rsplit(".", 1)[-1]
        if leaf in FORBIDDEN_FIELDS:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_FORBIDDEN_FIELD", {"field": key, "value": value}))
        if leaf == "run_kind" and str(value) in FORBIDDEN_RUN_KINDS:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_FORBIDDEN_RUN_KIND", {"field": key, "value": value}))
    return blockers


def _walk(payload: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(payload, dict):
        items: list[tuple[str, Any]] = []
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_walk(value, path))
        return items
    if isinstance(payload, list):
        items = []
        for index, value in enumerate(payload):
            items.extend(_walk(value, f"{prefix}[{index}]"))
        return items
    return [(prefix, payload)]


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}
