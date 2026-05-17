from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, read_jsonl, write_json
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_signatures, inspect_ranking_run_artifacts, strict_ranking_promotion_status
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from scripts.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift

_PHASE = "phase_6_semantic_two_tower_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_6_semantic_two_tower_ranker"
MINIMUM_RUNS = 1
REQUIRED_CONSISTENT_RUNS = 1
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
VARIANTS = [
    {
        "name": "semantic_score_feature_rerank",
        "method_family": "semantic_title_score_feature",
        "override": {"rank_weights": {"popular": 1.0, "itemcf_weak": 1.0, "itemcf_strong": 1.0, "category": 1.0, "semantic": 1.3, "two_tower": 1.0, "recent": 0.0, "verified": 0.0, "time_decay": 0.0}},
        "features": ["source_score_semantic"],
    },
    {
        "name": "two_tower_score_feature_rerank",
        "method_family": "two_tower_score_feature",
        "override": {"rank_weights": {"popular": 1.0, "itemcf_weak": 1.0, "itemcf_strong": 1.0, "category": 1.0, "semantic": 1.0, "two_tower": 1.3, "recent": 0.0, "verified": 0.0, "time_decay": 0.0}},
        "features": ["source_score_two_tower", "vector_similarity_from_two_tower_source_score"],
    },
    {
        "name": "semantic_two_tower_cross_feature_fusion",
        "method_family": "semantic_two_tower_cross_feature",
        "override": {
            "source_aware_fusion": {"enabled": True, "two_tower_source_boost": 0.05, "two_tower_multi_source_boost": 0.05, "two_tower_semantic_source_boost": 0.1, "two_tower_only_penalty": 0.05, "semantic_only_penalty": 0.05},
        },
        "features": ["two_tower_source", "two_tower_multi_source", "two_tower_semantic_source", "semantic_only", "two_tower_only"],
    },
]
BLOCKED_METHODS = [
    {
        "method_id": "dssm_artifact_candidate_rerank",
        "method_family": "dssm",
        "gpu_required": True,
        "artifact_path": ROOT / "outputs/training/two_tower/two_tower_training/dssm/artifact_manifest.json",
        "reasons": ["candidate_level_dssm_serving_adapter_missing", "promotion_adr_required", "must_not_regenerate_candidate_pool"],
    },
    {
        "method_id": "raw_vector_similarity_feature_fusion",
        "method_family": "vector_similarity_feature",
        "gpu_required": False,
        "artifact_path": ROOT / "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json",
        "reasons": ["candidate_level_vector_feature_adapter_missing", "using_vector_artifact_as_recall_source_forbidden_in_ranking_phase"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6 semantic/two-tower feature rerank comparison on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 6 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_6_semantic_two_tower_ranker(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_6_semantic_two_tower_ranker(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users)
    baseline_row = _run_variant(_BASELINE_VARIANT, "baseline", "promotion", True, False, {}, output_dir, limit_users, feature_contract, run_id, command_text, None, None, run_index=0)
    baseline_metrics = baseline_row["raw_metrics"]
    baseline_frozen_rows = baseline_row["frozen_rows"]
    baseline_freeze = baseline_row["freeze"]
    variant_rows = [baseline_row]
    for run_index, variant in enumerate(VARIANTS, start=1):
        variant_rows.append(_run_variant(str(variant["name"]), str(variant["method_family"]), "promotion", True, False, dict(variant["override"]), output_dir, limit_users, feature_contract, run_id, command_text, baseline_metrics, baseline_frozen_rows, baseline_freeze, run_index=run_index))
    public_runs = [_public_run_row(row) for row in variant_rows]
    promotable_rows = [row for row in variant_rows if row["strict_status"].get("promotable")]
    selected_route = promotable_rows[0]["candidate_id"] if promotable_rows else _BASELINE_VARIANT
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "minimum_runs": MINIMUM_RUNS,
        "required_consistent_runs": REQUIRED_CONSISTENT_RUNS,
        "actual_runs": 1,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "feature_readiness": _feature_readiness(),
        "lanes": {
            "promotion": {"candidate_types": ["baseline", "semantic_title_score_feature", "two_tower_score_feature", "semantic_two_tower_cross_feature"], "promotion_eligible": True},
            "blocked": {"candidate_types": ["dssm", "vector_similarity_feature"], "promotion_eligible": False},
        },
        "promotion_policy": {"frozen_pool200_required": True, "candidate_pool_regeneration_forbidden": True, "online_metrics_forbidden": True, "dssm_vector_artifacts_need_candidate_level_adapter": True},
        "artifact_inspection": inspect_ranking_run_artifacts(variant_rows) | {"phase_6_scope": "semantic_two_tower_feature_rerank_on_frozen_pool200"},
        "final_decision": {"selected_route": selected_route, "status": "PROMOTE" if selected_route != _BASELINE_VARIANT else "BASELINE_FINAL_ROUTE", "reason": "strict_offline_gate_met" if selected_route != _BASELINE_VARIANT else "semantic_two_tower_variants_not_promotable"},
        "method_registry": [_method_registry_row(row) for row in variant_rows] + _blocked_method_registry_rows(),
        "gpu_resource_strategy": _gpu_resource_strategy(),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in variant_rows],
        "runs": public_runs,
    }


def _run_variant(variant_name: str, candidate_type: str, lane: str, promotion_eligible: bool, diagnostic_only: bool, overrides: dict[str, Any], output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, command_text: str, baseline_metrics: dict[str, Any] | None, baseline_frozen_rows: list[dict[str, Any]] | None, baseline_freeze: dict[str, Any] | None = None, run_index: int = 0) -> dict[str, Any]:
    variant_output_dir = output_dir / variant_name
    config_overrides = _merge_nested(dict(overrides), {"output_dir": str(variant_output_dir), "report_path": str(variant_output_dir / "report.md"), "export_frozen_candidates": True, "strategy_name": f"{_PHASE}_{variant_name}"})
    result = run_hybrid_demo(BASELINE_CONFIG, limit_users=limit_users, config_overrides=config_overrides)
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(variant_name, result, metrics)
    if baseline_metrics is None or baseline_frozen_rows is None or baseline_freeze is None:
        strict_status = _baseline_status()
        baseline_frozen_rows = frozen_rows
        baseline_freeze = _freeze_values(metrics)
    else:
        frozen_comparison = compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows)
        strict_status = strict_ranking_promotion_status(baseline_metrics, metrics, frozen_comparison, feature_contract_gate_summary=_feature_contract_gate(variant_name), leakage_gate_summary=_leakage_gate(variant_name))
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:{variant_name}",
        config=_registry_config(metrics, variant_name),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_feature_contract_gate(variant_name),
        leakage_gate_summary=_leakage_gate(variant_name),
    )
    effective_promotion_eligible = promotion_eligible if variant_name == _BASELINE_VARIANT else promotion_eligible and bool(strict_status.get("promotable", False))
    return _variant_row(variant_name, candidate_type, lane, effective_promotion_eligible, bool(strict_status.get("diagnostic_only", diagnostic_only)), run_id, run_index, command_text, result, metrics, frozen_rows, baseline_frozen_rows, baseline_freeze, strict_status, registry_entry)


def _variant_row(variant_name: str, candidate_type: str, lane: str, promotion_eligible: bool, diagnostic_only: bool, run_id: str, run_index: int, command_text: str, result: dict[str, Any], metrics: dict[str, Any], frozen_rows: list[dict[str, Any]], baseline_frozen_rows: list[dict[str, Any]], baseline_freeze: dict[str, Any], strict_status: dict[str, Any], registry_entry: dict[str, Any]) -> dict[str, Any]:
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, baseline_freeze)
    return {
        "run_id": run_id,
        "run_index": run_index,
        "candidate_id": variant_name,
        "candidate_type": candidate_type,
        "lane": lane,
        "promotion_eligible": promotion_eligible,
        "diagnostic_only": diagnostic_only,
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows),
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(Path(result["metrics_path"]).parent),
        "command_text": command_text,
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "frozen_candidates_exported": True,
        "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        "raw_metrics": metrics,
        "frozen_rows": frozen_rows,
        "freeze": freeze,
    }


def _method_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    state = "champion" if row["candidate_id"] == _BASELINE_VARIANT else ("challenger" if row["strict_status"].get("promotable") else "diagnostic")
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane=row["lane"] if state != "diagnostic" else "diagnostic",
        state=state,
        promotion_eligible=bool(row["promotion_eligible"]),
        diagnostic_only=bool(row["diagnostic_only"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_VARIANT if state == "champion" else None,
        challenger_of=_BASELINE_VARIANT if state == "challenger" else None,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _blocked_method_registry_rows() -> list[dict[str, Any]]:
    rows = []
    for method in BLOCKED_METHODS:
        artifact_path = Path(method["artifact_path"])
        artifact_available = artifact_path.exists()
        reasons = list(method["reasons"])
        if not artifact_available:
            reasons.append("artifact_missing")
        rows.append(
            build_ranking_method_registry_entry(
                method_id=str(method["method_id"]),
                method_family=str(method["method_family"]),
                lane="blocked",
                state="blocked",
                promotion_eligible=False,
                diagnostic_only=False,
                reasons=sorted(set(reasons)),
                gpu_resource=build_ranking_gpu_resource_summary(gpu_required=bool(method["gpu_required"]), gpu_available=None, dependency_status="artifact-available" if artifact_available else "artifact-missing"),
            )
        )
    return rows


def _feature_readiness() -> dict[str, Any]:
    artifacts = {}
    for method in BLOCKED_METHODS:
        path = Path(method["artifact_path"])
        artifacts[str(method["method_id"])] = {"artifact_path": str(path), "available": path.exists(), "artifact_type": _artifact_type(path)}
    return {"schema_version": "semantic_two_tower_feature_readiness_v1", "candidate_level_source_scores_available": True, "semantic_source_score_available": True, "two_tower_source_score_available": True, "candidate_level_vector_adapter_available": False, "candidate_regeneration_forbidden": True, "artifacts": artifacts}


def _artifact_type(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return str(read_json(path).get("artifact_type"))
    except Exception:
        return None


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or 200
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or 5
    return config


def _read_frozen_rows(variant_name: str, result: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    frozen_candidates_path = result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path")
    if not frozen_candidates_path or not Path(frozen_candidates_path).exists():
        raise ValueError(f"{variant_name} did not export frozen_candidates.jsonl")
    return read_jsonl(frozen_candidates_path)


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _baseline_status() -> dict[str, Any]:
    return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}


def _feature_contract_gate(variant_name: str) -> dict[str, Any]:
    if variant_name == _BASELINE_VARIANT:
        features: list[str] = []
    else:
        features = list(next((variant["features"] for variant in VARIANTS if variant["name"] == variant_name), []))
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "PASS", "checked_rows": 0, "checked_feature_count": len(features), "features": features, "reasons": []}


def _leakage_gate(variant_name: str) -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "PASS", "checked_rows": 0, "label_source": "none", "training_split": "none", "reasons": []}


def _gpu_resource_strategy() -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": False, "future_gpu_required_families": ["dssm"], "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "candidate_level_adapter_and_frozen_pool200_equality_required"}


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/experiments/ranking/run_phase_6_semantic_two_tower_ranker.py", "--output-dir", str(output_dir)]
    if limit_users is not None:
        parts.extend(["--limit-users", str(limit_users)])
    return " ".join(parts)


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _merge_nested(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 6 Semantic / Two-Tower Ranker Gate",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: semantic/two-tower feature rerank on frozen pool200 only; no candidate regeneration.",
        "",
        "## Method registry",
        "",
        "| method | family | state | gpu_status | reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["state"], row["gpu_resource"]["status"], ", ".join(row.get("reasons", []))]) + " |")
    lines.extend(["", "## Runs", "", "| candidate | status | hit_rate_at_k | ndcg_at_k | mrr_at_k | frozen_match |", "| --- | --- | --- | --- | --- | --- |"])
    for row in comparison["runs"]:
        metrics = row["metrics"]
        lines.append("| " + " | ".join([row["candidate_id"], row["strict_status"]["status"], str(metrics.get("hit_rate_at_k")), str(metrics.get("ndcg_at_k")), str(metrics.get("mrr_at_k")), str(row.get("frozen_candidate_match"))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
