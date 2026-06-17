from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rs_core.recsys.evaluation import (
    build_ranking_experiment_registry_entry,
    build_ranking_gpu_resource_summary,
    build_ranking_method_registry_entry,
    compare_frozen_candidate_signatures,
)

RANKING_METHOD_SPEC_SCHEMA_VERSION = "ranking_method_spec_v1"
RANKING_EXPERIMENT_RUN_ROW_SCHEMA_VERSION = "ranking_experiment_run_row_v1"
REQUIRED_CANDIDATE_POOL_SIZE = 200
REQUIRED_TOP_K = 5
RankingRunKind = Literal["baseline", "variant", "diagnostic", "blocked"]
RankingStageTarget = Literal["coarse", "fine", "rerank"]


@dataclass(frozen=True)
class RankingMethodSpec:
    method_id: str
    method_family: str
    stage_target: RankingStageTarget
    requires_training: bool
    requires_gpu: bool
    dependency: str | None
    promotion_lane: str
    blocked_recovery_condition: str
    promotion_eligible: bool = False
    diagnostic_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_registry_payload(self) -> dict[str, Any]:
        return {
            "schema_version": RANKING_METHOD_SPEC_SCHEMA_VERSION,
            "method_id": self.method_id,
            "method_family": self.method_family,
            "stage_target": self.stage_target,
            "requires_training": self.requires_training,
            "requires_gpu": self.requires_gpu,
            "dependency": self.dependency,
            "promotion_lane": self.promotion_lane,
            "blocked_recovery_condition": self.blocked_recovery_condition,
            "promotion_eligible": self.promotion_eligible,
            "diagnostic_only": self.diagnostic_only,
            "metadata": dict(self.metadata),
        }


def build_ranking_run_row(
    *,
    run_id: str,
    run_index: int,
    run_kind: RankingRunKind,
    method_spec: RankingMethodSpec,
    config: dict[str, Any],
    frozen_rows: list[dict[str, Any]],
    baseline_frozen_rows: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    strict_status: dict[str, Any] | None = None,
    artifact_paths: dict[str, Any] | None = None,
    feature_contract: dict[str, Any] | None = None,
    feature_contract_gate_summary: dict[str, Any] | None = None,
    leakage_gate_summary: dict[str, Any] | None = None,
    command_text: str | None = None,
) -> dict[str, Any]:
    if run_kind == "blocked":
        raise ValueError("Use build_blocked_ranking_run_row for blocked methods.")
    _validate_frozen_pool_config(config)
    status = strict_status or _default_status(run_kind)
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{run_id}:{method_spec.method_id}",
        config=_registry_config(config, method_spec.method_id),
        frozen_rows=frozen_rows,
        metrics=metrics or {},
        status=status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    baseline_rows = baseline_frozen_rows if baseline_frozen_rows is not None else frozen_rows
    artifacts = dict(artifact_paths or {})
    return {
        "schema_version": RANKING_EXPERIMENT_RUN_ROW_SCHEMA_VERSION,
        "run_id": run_id,
        "run_index": run_index,
        "run_kind": run_kind,
        "candidate_id": method_spec.method_id,
        "candidate_type": method_spec.method_family,
        "method_spec": method_spec.to_registry_payload(),
        "stage_target": method_spec.stage_target,
        "lane": _lane_for_run_kind(run_kind, method_spec),
        "promotion_eligible": _promotion_eligible_for_run_kind(run_kind, method_spec),
        "diagnostic_only": _diagnostic_only_for_run_kind(run_kind, method_spec),
        "status": status.get("status"),
        "strict_status": status,
        "ranking_experiment_registry": registry_entry,
        "frozen_candidate_comparison": compare_frozen_candidate_signatures(baseline_rows, frozen_rows),
        "candidate_pool_size": registry_entry.get("candidate_pool_size"),
        "top_k": registry_entry.get("top_k"),
        "command_text": command_text,
        "metrics": metrics or {},
        **artifacts,
    }


def build_blocked_ranking_run_row(
    *,
    run_id: str,
    run_index: int,
    method_spec: RankingMethodSpec,
    dependency_available: bool | None,
    gpu_available: bool | None = None,
    blocked_reason: str | list[str] | None = None,
    command_text: str | None = None,
) -> dict[str, Any]:
    reasons = _blocked_reasons(method_spec, dependency_available, gpu_available, blocked_reason)
    dependency_status = _dependency_status(method_spec.dependency, dependency_available)
    gpu_resource = build_ranking_gpu_resource_summary(
        gpu_required=method_spec.requires_gpu,
        gpu_available=gpu_available,
        dependency_status=dependency_status["status"],
    )
    method_registry_entry = build_ranking_method_registry_entry(
        method_id=method_spec.method_id,
        method_family=method_spec.method_family,
        lane="blocked",
        state="blocked",
        promotion_eligible=False,
        diagnostic_only=False,
        reasons=reasons,
        gpu_resource=gpu_resource,
    )
    return {
        "schema_version": RANKING_EXPERIMENT_RUN_ROW_SCHEMA_VERSION,
        "run_id": run_id,
        "run_index": run_index,
        "run_kind": "blocked",
        "candidate_id": method_spec.method_id,
        "candidate_type": method_spec.method_family,
        "method_spec": method_spec.to_registry_payload(),
        "stage_target": method_spec.stage_target,
        "lane": "blocked",
        "promotion_eligible": False,
        "diagnostic_only": False,
        "status": "BLOCKED",
        "strict_status": {"status": "BLOCKED", "promotable": False, "diagnostic_only": False, "reasons": reasons},
        "dependency_status": dependency_status,
        "gpu_resource": gpu_resource,
        "blocked_reason": reasons,
        "blocked_recovery_condition": method_spec.blocked_recovery_condition,
        "method_registry_entry": method_registry_entry,
        "command_text": command_text,
    }


def build_ranking_method_registry_entry_from_spec(
    method_spec: RankingMethodSpec,
    *,
    run_kind: RankingRunKind,
    state: str | None = None,
    reasons: list[str] | None = None,
    champion_id: str | None = None,
    challenger_of: str | None = None,
    gpu_available: bool | None = None,
    dependency_status: str = "not_checked",
) -> dict[str, Any]:
    lane = "blocked" if run_kind == "blocked" else _lane_for_run_kind(run_kind, method_spec)
    return build_ranking_method_registry_entry(
        method_id=method_spec.method_id,
        method_family=method_spec.method_family,
        lane=lane,
        state=state or _method_state_for_run_kind(run_kind),
        promotion_eligible=_promotion_eligible_for_run_kind(run_kind, method_spec),
        diagnostic_only=_diagnostic_only_for_run_kind(run_kind, method_spec),
        reasons=reasons or [],
        champion_id=champion_id,
        challenger_of=challenger_of,
        gpu_resource=build_ranking_gpu_resource_summary(
            gpu_required=method_spec.requires_gpu,
            gpu_available=gpu_available,
            dependency_status=dependency_status,
        ),
    )


def public_ranking_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}


def _validate_frozen_pool_config(config: dict[str, Any]) -> None:
    candidate_pool_size = config.get("candidate_pool_size", (config.get("config_summary") or {}).get("candidate_pool_size"))
    top_k = config.get("top_k", (config.get("config_summary") or {}).get("top_k"))
    if candidate_pool_size != REQUIRED_CANDIDATE_POOL_SIZE:
        raise ValueError(f"ranking experiments require candidate_pool_size={REQUIRED_CANDIDATE_POOL_SIZE}")
    if top_k != REQUIRED_TOP_K:
        raise ValueError(f"ranking experiments require top_k={REQUIRED_TOP_K}")

def _registry_config(config: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    registry_config = dict(config.get("config_summary", {}) or {})
    registry_config.update(config)
    registry_config["strategy_name"] = config.get("strategy_name", strategy_name)
    registry_config["candidate_pool_size"] = REQUIRED_CANDIDATE_POOL_SIZE
    registry_config["top_k"] = REQUIRED_TOP_K
    return registry_config

def _default_status(run_kind: RankingRunKind) -> dict[str, Any]:
    if run_kind == "baseline":
        return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}
    if run_kind == "variant":
        return {"status": "CANDIDATE", "promotable": False, "diagnostic_only": False, "reasons": [], "metric_delta": {}}
    return {"status": "PARTIAL diagnostic-only", "promotable": False, "diagnostic_only": True, "reasons": ["diagnostic_only_evidence"], "metric_delta": {}}


def _lane_for_run_kind(run_kind: RankingRunKind, method_spec: RankingMethodSpec) -> str:
    if run_kind == "baseline":
        return "baseline"
    if run_kind == "diagnostic":
        return "diagnostic"
    return method_spec.promotion_lane


def _promotion_eligible_for_run_kind(run_kind: RankingRunKind, method_spec: RankingMethodSpec) -> bool:
    return run_kind == "variant" and method_spec.promotion_eligible


def _diagnostic_only_for_run_kind(run_kind: RankingRunKind, method_spec: RankingMethodSpec) -> bool:
    return run_kind == "diagnostic" or (run_kind == "variant" and method_spec.diagnostic_only)


def _method_state_for_run_kind(run_kind: RankingRunKind) -> str:
    if run_kind == "baseline":
        return "champion"
    if run_kind == "variant":
        return "candidate"
    if run_kind == "blocked":
        return "blocked"
    return "diagnostic"


def _blocked_reasons(
    method_spec: RankingMethodSpec,
    dependency_available: bool | None,
    gpu_available: bool | None,
    blocked_reason: str | list[str] | None,
) -> list[str]:
    reasons: list[str] = []
    if method_spec.dependency and dependency_available is not True:
        reasons.append("dependency_missing_or_unverified")
    if method_spec.requires_gpu and gpu_available is not True:
        reasons.append("gpu_required_not_verified")
    if isinstance(blocked_reason, str):
        reasons.append(blocked_reason)
    elif blocked_reason:
        reasons.extend(str(reason) for reason in blocked_reason)
    if not reasons:
        reasons.append("method_precondition_not_satisfied")
    return sorted(set(reasons))


def _dependency_status(dependency: str | None, dependency_available: bool | None) -> dict[str, Any]:
    if dependency is None:
        status = "not_required"
    elif dependency_available is True:
        status = "available"
    elif dependency_available is False:
        status = "missing"
    else:
        status = "not_checked"
    return {"dependency": dependency, "available": dependency_available, "status": status}
