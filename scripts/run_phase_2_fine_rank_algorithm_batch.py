from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json
from rs_core.recsys.evaluation import (
    build_ranking_feature_contract,
    inspect_ranking_run_artifacts,
    strict_ranking_promotion_status,
)
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ranking_experiments import (
    REQUIRED_CANDIDATE_POOL_SIZE,
    REQUIRED_TOP_K,
    RankingMethodSpec,
    build_blocked_ranking_run_row,
    build_ranking_method_registry_entry_from_spec,
    build_ranking_run_row,
    public_ranking_run_row,
)
from scripts.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS
from scripts.run_phase_1_26_real_ranking_experiments import _not_applicable_feature_contract_gate, _not_applicable_leakage_gate, _read_frozen_rows

_PHASE = "phase_2_fine_rank_algorithm_batch"
_BASELINE_METHOD_ID = "same_run_pool200_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_2_fine_rank_algorithm_batch"
DEFAULT_SEED = 20260513
LTR_STATUS_BOUNDARY = "strict_status_currently_forces_diagnostic_only"
PHYSICAL_PIPELINE_OVERRIDE = {
    "enabled": True,
    "mode": "pass_through",
    "stages": ["coarse", "fine", "rerank"],
    "promotion_claim": "none",
}
RULE_VARIANT_CONFIGS: dict[str, dict[str, Any]] = {
    "normalized_additive_fine_rank_rule": {
        "normalized_additive_ranking": {
            "enabled": True,
            "weights": {
                "source_signal": 0.2,
                "item_feature": 0.2,
                "freshness_quality": 0.1,
                "near_miss_tiebreak_strength": 0.05,
            },
        }
    },
    "source_aware_fine_rank_rule": {
        "source_aware_fusion": {
            "enabled": True,
            "itemcf_multi_source_boost": 0.06,
            "two_tower_itemcf_source_boost": 0.04,
            "semantic_only_penalty": 0.04,
            "popular_only_penalty": 0.06,
        }
    },
    "item_feature_fine_rank_rule": {
        "item_feature_rerank": {
            "enabled": True,
            "weights": {
                "multi_source": 0.06,
                "two_tower_itemcf_source": 0.04,
                "two_tower_semantic_source": 0.04,
                "popular_only": -0.06,
            },
        }
    },
}
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 2 fine-rank algorithm batch on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 2 batch artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in batch artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_2_fine_rank_algorithm_batch(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_2_fine_rank_algorithm_batch(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, seed)
    method_specs = build_method_specs()
    dependency_checks = _dependency_checks(method_specs)
    gpu_check = _gpu_check()

    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, method_specs[0], run_id, command_text)
    rule_rows = _run_rule_variants(output_dir, limit_users, feature_contract, method_specs[1:4], baseline_row, run_id, command_text)
    learned_rows = _diagnostic_ltr_rows(method_specs[4:6], baseline_row, run_id, command_text)
    blocked_rows = _blocked_rows(method_specs[6:], run_id, command_text, dependency_checks, gpu_check)
    runnable_rows = [baseline_row, *rule_rows, *learned_rows]
    runs = [public_ranking_run_row(row) for row in runnable_rows] + blocked_rows
    method_registry = [_method_registry_entry(row) for row in runnable_rows] + [row["method_registry_entry"] for row in blocked_rows]
    ranking_registry = [row["ranking_experiment_registry"] for row in runnable_rows if "ranking_experiment_registry" in row]

    return {
        "phase": _PHASE,
        "run_id": run_id,
        "algorithm_batch": _algorithm_batch_summary(method_specs),
        "stage_assignment_summary": _stage_assignment_summary(method_specs),
        "promotion_boundary": _promotion_boundary(),
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "seed": seed,
        "limit_users": limit_users,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "method_specs": [spec.to_registry_payload() for spec in method_specs],
        "dependency_checks": dependency_checks,
        "gpu_check": gpu_check,
        "artifact_inspection": inspect_ranking_run_artifacts(
            [baseline_row, *rule_rows],
            required_paths=[
                "metrics_path",
                "recommendations_path",
                "ranking_cases_path",
                "ranking_case_summary_path",
                "report_path",
                "frozen_candidates_path",
                "ranking_stage_trace_path",
                "ranking_stage_summary_path",
            ],
        ),
        "method_registry": method_registry,
        "ranking_experiment_registry": ranking_registry,
        "runs": runs,
    }


def build_method_specs() -> list[RankingMethodSpec]:
    return [
        RankingMethodSpec(
            method_id=_BASELINE_METHOD_ID,
            method_family="current_champion_route",
            stage_target="rerank",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="baseline",
            blocked_recovery_condition="baseline route is executable through the frozen pool200 same-run config",
            promotion_eligible=False,
            diagnostic_only=False,
            metadata={"config_path": str(BASELINE_CONFIG), "role": "frozen_pool200_current_champion"},
        ),
        RankingMethodSpec(
            method_id="normalized_additive_fine_rank_rule",
            method_family="rule_based_fine_rank",
            stage_target="fine",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="fine_rank_batch_2",
            blocked_recovery_condition="valid/test promotion evidence is required before challenger promotion",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"algorithm_batch": "batch_2_executable_rule_fine_rank", "config_override": RULE_VARIANT_CONFIGS["normalized_additive_fine_rank_rule"]},
        ),
        RankingMethodSpec(
            method_id="source_aware_fine_rank_rule",
            method_family="rule_based_fine_rank",
            stage_target="fine",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="fine_rank_batch_2",
            blocked_recovery_condition="valid/test promotion evidence is required before challenger promotion",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"algorithm_batch": "batch_2_executable_rule_fine_rank", "config_override": RULE_VARIANT_CONFIGS["source_aware_fine_rank_rule"]},
        ),
        RankingMethodSpec(
            method_id="item_feature_fine_rank_rule",
            method_family="rule_based_fine_rank",
            stage_target="fine",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="fine_rank_batch_2",
            blocked_recovery_condition="valid/test promotion evidence is required before challenger promotion",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"algorithm_batch": "batch_2_executable_rule_fine_rank", "config_override": RULE_VARIANT_CONFIGS["item_feature_fine_rank_rule"]},
        ),
        RankingMethodSpec(
            method_id="pointwise_logistic_ltr_fine_rank_diagnostic",
            method_family="shallow_learned_fine_ranker",
            stage_target="fine",
            requires_training=True,
            requires_gpu=False,
            dependency=None,
            promotion_lane="batch_3_diagnostic_only",
            blocked_recovery_condition="replace LOPO/current strict-status diagnostic evidence with full valid/test adapter evidence",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"algorithm_batch": "batch_3_learned_diagnostic", "ltr_enabled_status_boundary": LTR_STATUS_BOUNDARY, "artifact_pattern": "real_training/*/training_log.json"},
        ),
        RankingMethodSpec(
            method_id="pairwise_or_listwise_ltr_fine_rank_diagnostic",
            method_family="learned_ltr_fine_ranker",
            stage_target="fine",
            requires_training=True,
            requires_gpu=False,
            dependency=None,
            promotion_lane="batch_4_diagnostic_only",
            blocked_recovery_condition="implement full train/valid/test LTR adapter and promotion gates before challenger use",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"algorithm_batch": "batch_4_learned_diagnostic", "ltr_enabled_status_boundary": LTR_STATUS_BOUNDARY, "artifact_pattern": "real_training/*/{metrics.json,model.json,training_log.json}"},
        ),
        RankingMethodSpec(
            method_id="sklearn_gbdt_fine_rank_blocked",
            method_family="tree_gbdt",
            stage_target="fine",
            requires_training=True,
            requires_gpu=False,
            dependency="sklearn",
            promotion_lane="blocked",
            blocked_recovery_condition="sklearn plus a candidate-level GBDT training/inference adapter and valid/test evidence are available",
            metadata={"algorithm_batch": "batch_6_tree_lambdamart_blocked", "deterministic_stand_in": False},
        ),
        RankingMethodSpec(
            method_id="xgboost_lambdamart_fine_rank_blocked",
            method_family="lambdamart",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="xgboost",
            promotion_lane="blocked",
            blocked_recovery_condition="xgboost plus verified GPU, LambdaMART adapter, and valid/test evidence are available",
            metadata={"algorithm_batch": "batch_6_tree_lambdamart_blocked", "deterministic_stand_in": False},
        ),
        RankingMethodSpec(
            method_id="lightgbm_lambdamart_fine_rank_blocked",
            method_family="lambdamart",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="lightgbm",
            promotion_lane="blocked",
            blocked_recovery_condition="lightgbm plus verified GPU, LambdaMART adapter, and valid/test evidence are available",
            metadata={"algorithm_batch": "batch_6_tree_lambdamart_blocked", "deterministic_stand_in": False},
        ),
    ]


def _run_baseline(
    output_dir: Path,
    limit_users: int | None,
    feature_contract: dict[str, Any],
    method_spec: RankingMethodSpec,
    run_id: str,
    command_text: str,
) -> dict[str, Any]:
    variant_output_dir = output_dir / method_spec.method_id
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "export_ranking_stage_artifacts": True,
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "strategy_name": f"{_PHASE}_{method_spec.method_id}",
        },
    )
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(method_spec.method_id, result, metrics)
    row = build_ranking_run_row(
        run_id=f"{_PHASE}:{run_id}",
        run_index=0,
        run_kind="baseline",
        method_spec=method_spec,
        config=_registry_config(metrics, method_spec.method_id),
        frozen_rows=frozen_rows,
        metrics={key: metrics.get(key) for key in METRIC_FIELDS},
        strict_status={"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline", "frozen_pool200_boundary"], "metric_delta": {}},
        artifact_paths=_artifact_paths(variant_output_dir, result, metrics),
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
        command_text=command_text,
    )
    row["raw_metrics"] = metrics
    row["frozen_rows"] = frozen_rows
    return row


def _run_rule_variants(
    output_dir: Path,
    limit_users: int | None,
    feature_contract: dict[str, Any],
    method_specs: list[RankingMethodSpec],
    baseline_row: dict[str, Any],
    run_id: str,
    command_text: str,
) -> list[dict[str, Any]]:
    rows = []
    for offset, spec in enumerate(method_specs, start=1):
        variant_output_dir = output_dir / spec.method_id
        result = run_hybrid_demo(
            BASELINE_CONFIG,
            limit_users=limit_users,
            config_overrides={
                **RULE_VARIANT_CONFIGS[spec.method_id],
                "output_dir": str(variant_output_dir),
                "report_path": str(variant_output_dir / "report.md"),
                "export_frozen_candidates": True,
                "export_ranking_stage_artifacts": True,
                "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
                "strategy_name": f"{_PHASE}_{spec.method_id}",
            },
        )
        metrics = result["metrics"]
        frozen_rows = _read_frozen_rows(spec.method_id, result, metrics)
        status = strict_ranking_promotion_status(
            baseline_row["raw_metrics"],
            metrics,
            build_ranking_run_row(
                run_id=f"{_PHASE}:{run_id}:internal_comparison",
                run_index=offset,
                run_kind="diagnostic",
                method_spec=spec,
                config=_registry_config(metrics, spec.method_id),
                frozen_rows=frozen_rows,
                baseline_frozen_rows=baseline_row["frozen_rows"],
            )["frozen_candidate_comparison"],
            ltr_enabled=False,
        )
        status = status | {
            "status": "INVALID/STOP" if status.get("status") == "INVALID/STOP" else "PARTIAL diagnostic-only",
            "promotable": False,
            "diagnostic_only": True,
            "reasons": sorted(set([*status.get("reasons", []), "batch_2_executable_rule_fine_rank_diagnostic_only", "valid_test_promotion_evidence_missing"])),
        }
        row = build_ranking_run_row(
            run_id=f"{_PHASE}:{run_id}",
            run_index=offset,
            run_kind="diagnostic",
            method_spec=spec,
            config=_registry_config(metrics, spec.method_id),
            frozen_rows=frozen_rows,
            baseline_frozen_rows=baseline_row["frozen_rows"],
            metrics={key: metrics.get(key) for key in METRIC_FIELDS},
            strict_status=status,
            artifact_paths=_artifact_paths(variant_output_dir, result, metrics),
            feature_contract=feature_contract,
            feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
            leakage_gate_summary=_not_applicable_leakage_gate(),
            command_text=command_text,
        )
        row["raw_metrics"] = metrics
        row["frozen_rows"] = frozen_rows
        rows.append(row)
    return rows


def _diagnostic_ltr_rows(method_specs: list[RankingMethodSpec], baseline_row: dict[str, Any], run_id: str, command_text: str) -> list[dict[str, Any]]:
    rows = []
    for offset, spec in enumerate(method_specs, start=4):
        status = {
            "status": "PARTIAL diagnostic-only",
            "promotable": False,
            "diagnostic_only": True,
            "reasons": ["learned_ranker_adapter_not_promotable", "valid_test_promotion_evidence_missing", LTR_STATUS_BOUNDARY],
            "metric_delta": {},
        }
        row = build_ranking_run_row(
            run_id=f"{_PHASE}:{run_id}",
            run_index=offset,
            run_kind="diagnostic",
            method_spec=spec,
            config=_registry_config(baseline_row["raw_metrics"], spec.method_id),
            frozen_rows=baseline_row["frozen_rows"],
            baseline_frozen_rows=baseline_row["frozen_rows"],
            metrics={key: baseline_row["raw_metrics"].get(key) for key in METRIC_FIELDS},
            strict_status=status,
            artifact_paths={
                "diagnostic_source_metrics_path": baseline_row.get("metrics_path"),
                "diagnostic_source_frozen_candidates_path": baseline_row.get("frozen_candidates_path"),
                "ltr_enabled_status_boundary": LTR_STATUS_BOUNDARY,
                "adapter_execution": "not_run_no_full_valid_test_adapter",
                "promotion_evidence_claim": "none",
            },
            command_text=command_text,
        )
        row["ltr_enabled_status_boundary"] = LTR_STATUS_BOUNDARY
        row["promotion_eligible"] = False
        row["diagnostic_only"] = True
        rows.append(row)
    return rows


def _blocked_rows(
    method_specs: list[RankingMethodSpec],
    run_id: str,
    command_text: str,
    dependency_checks: dict[str, dict[str, Any]],
    gpu_check: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for offset, spec in enumerate(method_specs, start=6):
        dependency_available = dependency_checks.get(spec.method_id, {}).get("available")
        gpu_available = gpu_check["available"] if spec.requires_gpu else None
        rows.append(
            build_blocked_ranking_run_row(
                run_id=f"{_PHASE}:{run_id}",
                run_index=offset,
                method_spec=spec,
                dependency_available=dependency_available,
                gpu_available=gpu_available,
                blocked_reason=["batch_6_tree_lambdamart_adapter_missing", "no_deterministic_stand_in", "valid_test_promotion_evidence_missing"],
                command_text=command_text,
            )
        )
    return rows


def _artifact_paths(variant_output_dir: Path, result: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(variant_output_dir),
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "ranking_stage_trace_path": result.get("ranking_stage_trace_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("trace"),
        "ranking_stage_summary_path": result.get("ranking_stage_summary_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("summary"),
        "frozen_candidates_exported": True,
        "ranking_stage_artifacts_exported": True,
        "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
    }


def _method_registry_entry(row: dict[str, Any]) -> dict[str, Any]:
    method_payload = {key: value for key, value in row["method_spec"].items() if key != "schema_version"}
    return build_ranking_method_registry_entry_from_spec(
        RankingMethodSpec(**method_payload),
        run_kind=str(row["run_kind"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_METHOD_ID if row["run_kind"] == "baseline" else None,
        challenger_of=_BASELINE_METHOD_ID if row["run_kind"] != "baseline" else None,
        dependency_status="not_required",
    )


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or REQUIRED_CANDIDATE_POOL_SIZE
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or REQUIRED_TOP_K
    config["physical_ranking_pipeline"] = PHYSICAL_PIPELINE_OVERRIDE
    config["export_ranking_stage_artifacts"] = True
    return config


def _dependency_checks(method_specs: list[RankingMethodSpec]) -> dict[str, dict[str, Any]]:
    checks = {}
    for spec in method_specs:
        if spec.dependency is None:
            checks[spec.method_id] = {"dependency": None, "available": None, "status": "not_required", "checked_by": "not_required"}
        else:
            available = importlib.util.find_spec(spec.dependency) is not None
            checks[spec.method_id] = {"dependency": spec.dependency, "available": available, "status": "available" if available else "missing", "checked_by": "importlib.util.find_spec"}
    return checks


def _gpu_check() -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"available": False, "status": "missing", "checked_by": "shutil.which:nvidia-smi", "device": None}
    try:
        completed = subprocess.run([nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "status": "unverified", "checked_by": "nvidia-smi", "device": None}
    devices = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return {"available": completed.returncode == 0 and bool(devices), "status": "available" if completed.returncode == 0 and devices else "unavailable", "checked_by": "nvidia-smi", "device": devices[0] if devices else None}


def _algorithm_batch_summary(method_specs: list[RankingMethodSpec]) -> dict[str, Any]:
    return {
        "batch_2_executable_rule_fine_rank": [spec.method_id for spec in method_specs if spec.metadata.get("algorithm_batch") == "batch_2_executable_rule_fine_rank"],
        "batch_3_4_learned_diagnostic_only": [spec.method_id for spec in method_specs if str(spec.metadata.get("algorithm_batch", "")).startswith(("batch_3", "batch_4"))],
        "batch_6_tree_lambdamart_blocked": [spec.method_id for spec in method_specs if spec.metadata.get("algorithm_batch") == "batch_6_tree_lambdamart_blocked"],
    }


def _stage_assignment_summary(method_specs: list[RankingMethodSpec]) -> dict[str, Any]:
    summary: dict[str, list[str]] = {"coarse": [], "fine": [], "rerank": []}
    for spec in method_specs:
        summary[spec.stage_target].append(spec.method_id)
    return summary


def _promotion_boundary() -> dict[str, Any]:
    return {
        "frozen_pool200_required": True,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "recall_semantics_changed": False,
        "learned_ltr_diagnostic_only": True,
        "lopo_gate_smoke_stage_trace_training_loss_online_metrics_not_promotion_evidence": True,
        "online_metrics_forbidden_as_current_offline_evidence": True,
        "gpu_neural_sequence_online_routes_blocked": True,
        "tree_lambdamart_no_deterministic_stand_in": True,
    }


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_2_fine_rank_algorithm_batch.py", "--output-dir", str(output_dir), "--seed", str(seed)]
    if limit_users is not None:
        parts.extend(["--limit-users", str(limit_users)])
    return " ".join(parts)


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 2 Fine-Rank Algorithm Batch",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Seed: `{comparison['seed']}`",
        "- Scope: frozen pool200 / top_k=5; recall semantics are unchanged.",
        "- Promotion boundary: learned/LTR diagnostic-only; tree/GBDT/LambdaMART blocked without dependencies and adapters; online/GPU/neural/sequence routes are not promotion evidence here.",
        "",
        "## Runs",
        "",
        "| method | kind | family | stage | lane | status | promotion_eligible | diagnostic_only | blocked_reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison["runs"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["candidate_id"]),
                    str(row["run_kind"]),
                    str(row["candidate_type"]),
                    str(row["stage_target"]),
                    str(row["lane"]),
                    str(row["status"]),
                    str(row["promotion_eligible"]),
                    str(row["diagnostic_only"]),
                    ", ".join(row.get("blocked_reason", [])),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Stage assignment", ""])
    for stage, methods in comparison["stage_assignment_summary"].items():
        lines.append(f"- `{stage}`: {', '.join(methods) if methods else 'none'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
