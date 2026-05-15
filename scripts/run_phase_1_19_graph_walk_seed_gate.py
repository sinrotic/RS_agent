from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_core.common.io import read_json, read_jsonl, write_json
from rs_core.workflow.graph_walk_training import train_graph_walk_seed
from rs_core.workflow.hybrid_demo import run_hybrid_demo

DEFAULT_BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml"
DEFAULT_EXPERIMENT_CONFIG = ROOT / "configs/recall/phase_1_19/phase_1_19_graph_walk_seed_deepwalk.yaml"
DEFAULT_OUTPUT = ROOT / "outputs/recall/phase_1_19_graph_walk_seed_gate/comparison.json"
SOURCE = "graph_walk_seed"
CONFLICTING_SOURCE = "item_graph"
REQUIRED_DIAGNOSTIC_FIELDS = {
    "source_only",
    "without_graph_walk",
    "exclusive_hit_users",
    "displaced_baseline_hit_users",
    "source_overlap",
    "candidate_share",
    "score_distribution",
    "budget",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.19 same-run recall gate for graph_walk_seed DeepWalk.")
    parser.add_argument("--baseline-config", default=str(DEFAULT_BASELINE_CONFIG), help="Frozen Phase 1.15 baseline config.")
    parser.add_argument("--experiment-config", default=str(DEFAULT_EXPERIMENT_CONFIG), help="Phase 1.19 graph_walk_seed config.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Comparison JSON output path.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional quick-run user limit.")
    parser.add_argument("--skip-sidecar-build", action="store_true", help="Use existing graph_walk_seed sidecar instead of rebuilding from config.")
    parser.add_argument("--skip-lopo", action="store_true", help="Skip LOPO sanity run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_config = _resolve(args.baseline_config)
    experiment_config = _resolve(args.experiment_config)
    output_path = _resolve(args.output)
    experiment_config_data = load_config(experiment_config)
    _validate_experiment_config(experiment_config_data)

    run_id = _run_id(experiment_config, args.limit_users)
    enabled_overrides = _enabled_overrides(output_path, run_id, experiment_config_data)
    sidecar_result = None
    if not args.skip_sidecar_build:
        sidecar_result = train_graph_walk_seed(experiment_config, limit_users=args.limit_users)

    baseline_result = run_hybrid_demo(
        baseline_config,
        limit_users=args.limit_users,
        config_overrides=_run_overrides(output_path, "baseline", run_id),
    )
    disabled_result = run_hybrid_demo(
        experiment_config,
        limit_users=args.limit_users,
        config_overrides=_run_overrides(output_path, "graph_walk_disabled", run_id) | {"graph_walk_seed_enabled": False},
    )
    experiment_result = run_hybrid_demo(
        experiment_config,
        limit_users=args.limit_users,
        config_overrides=enabled_overrides,
    )
    source_only_result = run_hybrid_demo(
        experiment_config,
        limit_users=args.limit_users,
        config_overrides=_source_only_overrides(output_path, run_id, experiment_config_data),
    )
    without_graph_walk_result = run_hybrid_demo(
        experiment_config,
        limit_users=args.limit_users,
        config_overrides=enabled_overrides | _run_overrides(output_path, "without_graph_walk", run_id) | {"graph_walk_seed_enabled": False},
    )
    lopo_result = None
    if not args.skip_lopo:
        lopo_result = run_hybrid_demo(
            experiment_config,
            limit_users=args.limit_users,
            config_overrides=enabled_overrides | _run_overrides(output_path, "lopo_sanity", run_id) | {"evaluation_mode": "leave_one_positive_out"},
        )

    baseline_metrics = baseline_result["metrics"]
    disabled_metrics = disabled_result["metrics"]
    experiment_metrics = experiment_result["metrics"]
    source_only_metrics = source_only_result["metrics"]
    without_metrics = without_graph_walk_result["metrics"]
    lopo_metrics = lopo_result["metrics"] if lopo_result else None
    manifest = sidecar_result["manifest"] if sidecar_result else _load_existing_sidecar_manifest(experiment_config_data)
    graph_walk_diagnostics = _graph_walk_diagnostics(
        baseline_result,
        experiment_result,
        source_only_result,
        without_graph_walk_result,
        experiment_config_data,
    )
    comparison = {
        "phase": "1.19",
        "source": SOURCE,
        "algorithm": "deepwalk",
        "run_id": run_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "limit_users": args.limit_users,
        "baseline": _run_summary(baseline_config, baseline_result, baseline_metrics),
        "graph_walk_disabled": _run_summary(experiment_config, disabled_result, disabled_metrics),
        "experiment": _run_summary(experiment_config, experiment_result, experiment_metrics),
        "source_only": _run_summary(experiment_config, source_only_result, source_only_metrics),
        "without_graph_walk": _run_summary(experiment_config, without_graph_walk_result, without_metrics),
        "lopo_sanity": None if lopo_result is None or lopo_metrics is None else _run_summary(experiment_config, lopo_result, lopo_metrics),
        "manifests": {SOURCE: manifest},
        "graph_walk_diagnostics": graph_walk_diagnostics,
        "gate": _phase_1_19_gate(baseline_metrics, disabled_metrics, experiment_metrics, lopo_metrics, experiment_config_data, graph_walk_diagnostics),
    }
    write_json(output_path, comparison)
    print(f"Phase 1.19 gate comparison written to: {output_path}")
    if not comparison["gate"]["passed"]:
        raise SystemExit(1)


def _validate_experiment_config(config: dict[str, Any]) -> None:
    if config.get("graph_walk_seed_enabled"):
        raise ValueError("Phase 1.19 config must keep graph_walk_seed_enabled=false; the gate enables it with overrides")
    if config.get("item_graph_enabled"):
        raise ValueError("Phase 1.19 graph_walk_seed gate requires item_graph_enabled=false to avoid source identity mixing")
    if not _sorting_disabled(config):
        raise ValueError("Phase 1.19 graph_walk_seed gate requires ranking enhancements disabled")


def _enabled_overrides(output_path: Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    return _run_overrides(output_path, "experiment", run_id) | dict(config.get("graph_walk_seed_experiment_pool_strategy", {}) or {}) | {"graph_walk_seed_enabled": True}


def _source_only_overrides(output_path: Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    source_maximum = int((config.get("candidate_source_maximums") or {}).get(SOURCE, 100) or 100)
    return _run_overrides(output_path, "source_only", run_id) | {
        "graph_walk_seed_enabled": True,
        "semantic_enabled": False,
        "two_tower_enabled": False,
        "item_graph_enabled": False,
        "two_tower_seed_enabled": False,
        "itemcf_weak_per_seed": 0,
        "itemcf_strong_per_seed": 0,
        "category_per_user": 0,
        "category_per_bucket": 0,
        "category_max_total_per_user": 0,
        "popular_fallback_count": 0,
        "candidate_source_minimums": {},
        "candidate_source_maximums": {SOURCE: source_maximum},
        "candidate_pool_strategy": "balanced_source_budget",
        "candidate_fill_order": [SOURCE],
    }


def _run_summary(config_path: Path, result: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": Path(result["metrics_path"]).parent.name,
        "config_path": str(config_path),
        "config_sha256": _sha256_file(config_path),
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "metrics": _recall_metrics(metrics),
    }


def _recall_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_hit_users": metrics.get("candidate_hit_users"),
        "candidate_hit_rate_at_pool": metrics.get("candidate_hit_rate_at_pool"),
        "recall_at_pool": metrics.get("recall_at_pool"),
        "hit_rate_at_k": metrics.get("hit_rate_at_k"),
        "fallback_rate": metrics.get("fallback_rate"),
        "candidate_generation_p95_seconds": _candidate_generation_p95(metrics),
        "candidate_hit_source_coverage": metrics.get("candidate_hit_source_coverage", {}),
        "per_source_candidate_contribution": metrics.get("per_source_candidate_contribution", {}),
        "recall_source_coverage": metrics.get("recall_source_coverage", {}),
        "source_overlap": metrics.get("source_overlap", {}),
        "source_diagnostics": metrics.get("source_diagnostics", {}),
    }


def _graph_walk_diagnostics(
    baseline_result: dict[str, Any],
    experiment_result: dict[str, Any],
    source_only_result: dict[str, Any],
    without_graph_walk_result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    baseline_cases = _read_rows(baseline_result["ranking_cases_path"])
    experiment_cases = _read_rows(experiment_result["ranking_cases_path"])
    source_only_cases = _read_rows(source_only_result["ranking_cases_path"])
    without_cases = _read_rows(without_graph_walk_result["ranking_cases_path"])
    experiment_metrics = experiment_result["metrics"]
    source_only_metrics = source_only_result["metrics"]
    without_metrics = without_graph_walk_result["metrics"]
    source_diagnostics = experiment_metrics.get("source_diagnostics") or {}
    source_overlap = experiment_metrics.get("source_overlap") or {}
    recall_coverage = experiment_metrics.get("recall_source_coverage") or {}
    recommendation_rows = _read_rows(experiment_result["recommendations_path"])
    source_pair_counts = source_overlap.get("source_pair_counts") or {}
    graph_walk_candidates = int(recall_coverage.get(SOURCE, 0) or 0)
    total_candidates = sum(int(value or 0) for value in recall_coverage.values())
    baseline_hit_users = {row.get("user_id") for row in baseline_cases if row.get("user_id")}
    experiment_hit_users = {row.get("user_id") for row in experiment_cases if row.get("user_id")}
    without_hit_users = {row.get("user_id") for row in without_cases if row.get("user_id")}
    source_only_hit_users = {row.get("user_id") for row in source_only_cases if row.get("user_id")}
    return {
        "source_only": _recall_metrics(source_only_metrics) | {"hit_user_ids": sorted(source_only_hit_users)},
        "without_graph_walk": _recall_metrics(without_metrics),
        "exclusive_hit_users": sorted(user for user in experiment_hit_users - without_hit_users if user),
        "displaced_baseline_hit_users": sorted(user for user in baseline_hit_users - experiment_hit_users if user),
        "source_overlap": {
            "graph_walk_seed_with_item_graph": int(source_pair_counts.get(f"{CONFLICTING_SOURCE}+{SOURCE}", 0) or source_pair_counts.get(f"{SOURCE}+{CONFLICTING_SOURCE}", 0) or 0),
            "graph_walk_seed_pair_counts": {key: value for key, value in source_pair_counts.items() if SOURCE in key.split("+")},
            "required_sources": _required_source_overlap(source_pair_counts, recall_coverage),
        },
        "candidate_share": {
            "graph_walk_seed_candidates": graph_walk_candidates,
            "total_source_assignments": total_candidates,
            "share": round(graph_walk_candidates / total_candidates, 6) if total_candidates else 0.0,
        },
        "score_distribution": _score_distribution(experiment_cases),
        "budget": {
            "max_candidates_per_user": int((config.get("candidate_source_maximums") or {}).get(SOURCE, 0) or 0),
            "raw_candidates": source_diagnostics.get("graph_walk_seed_raw_candidates"),
            "raw_unseen_candidates": source_diagnostics.get("graph_walk_seed_raw_unseen_candidates"),
            "users_with_seed_hits": source_diagnostics.get("users_with_graph_walk_seed_hits"),
            "users_with_raw_candidates": source_diagnostics.get("users_with_graph_walk_seed_raw_candidates"),
            "max_candidates_per_user_observed": _max_source_candidates_per_user(recommendation_rows, SOURCE),
            "users_exceeding_cap": _users_exceeding_source_cap(recommendation_rows, SOURCE, int((config.get("candidate_source_maximums") or {}).get(SOURCE, 0) or 0)),
        },
    }


def _phase_1_19_gate(
    baseline: dict[str, Any],
    disabled: dict[str, Any],
    experiment: dict[str, Any],
    lopo: dict[str, Any] | None,
    config: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    thresholds = dict((config.get("phase_1_19_gate") or {}).get("thresholds", {}) or {})
    max_p95 = float(thresholds.get("max_candidate_generation_p95_seconds", 0.543559))
    max_fallback = float(thresholds.get("max_fallback_rate", 0.0))
    max_share = float(thresholds.get("max_graph_walk_seed_candidate_share", 0.15))
    checks = {
        "required_diagnostics_present": REQUIRED_DIAGNOSTIC_FIELDS <= diagnostics.keys(),
        "default_off_matches_baseline": _same_recall_metrics(baseline, disabled),
        "source_identity_not_mixed_with_item_graph": int((diagnostics.get("source_overlap") or {}).get("graph_walk_seed_with_item_graph") or 0) == 0,
        "source_cap_not_exceeded": _source_cap_not_exceeded(diagnostics, max_share),
        "sorting_disabled": _sorting_disabled(config),
        "fallback_rate_budget": float(experiment.get("fallback_rate") or 0.0) <= max_fallback,
        "candidate_generation_p95_budget": _candidate_generation_p95(experiment) <= max_p95,
        "candidate_hit_users_lift": int(experiment.get("candidate_hit_users") or 0) >= int(baseline.get("candidate_hit_users") or 0) + 1,
        "candidate_hit_rate_at_pool_lift": float(experiment.get("candidate_hit_rate_at_pool") or 0.0) > float(baseline.get("candidate_hit_rate_at_pool") or 0.0),
        "recall_at_pool_lift": float(experiment.get("recall_at_pool") or 0.0) > float(baseline.get("recall_at_pool") or 0.0),
        "graph_walk_seed_hit_contribution": int((experiment.get("candidate_hit_source_coverage") or {}).get(SOURCE, 0) or 0) > 0,
    }
    if lopo is not None:
        checks["lopo_fallback_rate_budget"] = float(lopo.get("fallback_rate") or 0.0) <= max_fallback
        checks["lopo_candidate_generation_p95_budget"] = _candidate_generation_p95(lopo) <= max_p95
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "deltas": {
            "candidate_hit_users": int(experiment.get("candidate_hit_users") or 0) - int(baseline.get("candidate_hit_users") or 0),
            "candidate_hit_rate_at_pool": round(float(experiment.get("candidate_hit_rate_at_pool") or 0.0) - float(baseline.get("candidate_hit_rate_at_pool") or 0.0), 6),
            "recall_at_pool": round(float(experiment.get("recall_at_pool") or 0.0) - float(baseline.get("recall_at_pool") or 0.0), 6),
        },
        "thresholds": {
            "max_fallback_rate": max_fallback,
            "max_candidate_generation_p95_seconds": max_p95,
            "max_graph_walk_seed_candidate_share": max_share,
        },
    }


def _same_recall_metrics(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ["candidate_hit_users", "candidate_hit_rate_at_pool", "recall_at_pool", "fallback_rate"]
    return all(left.get(key) == right.get(key) for key in keys)


def _source_cap_not_exceeded(diagnostics: dict[str, Any], max_share: float) -> bool:
    budget = diagnostics.get("budget") or {}
    candidate_share = diagnostics.get("candidate_share") or {}
    return not budget.get("users_exceeding_cap") and float(candidate_share.get("share") or 0.0) <= max_share


def _required_source_overlap(source_pair_counts: dict[str, Any], recall_coverage: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    required = ["itemcf_weak", "itemcf_strong", "semantic", "two_tower", "popular", "item_graph"]
    graph_walk_total = int(recall_coverage.get(SOURCE, 0) or 0)
    rows = {}
    for source in required:
        count = int(source_pair_counts.get(f"{source}+{SOURCE}", 0) or source_pair_counts.get(f"{SOURCE}+{source}", 0) or 0)
        rows[source] = {"count": count, "rate": round(count / graph_walk_total, 6) if graph_walk_total else 0.0}
    return rows


def _score_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = sorted(
        float((row.get("target_source_scores") or {}).get(SOURCE) or 0.0)
        for row in rows
        if SOURCE in (row.get("target_source_scores") or {})
    )
    if not scores:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None, "avg": None}
    return {
        "count": len(scores),
        "min": round(scores[0], 6),
        "p50": _percentile(scores, 0.5),
        "p95": _percentile(scores, 0.95),
        "max": round(scores[-1], 6),
        "avg": round(sum(scores) / len(scores), 6),
    }


def _max_source_candidates_per_user(rows: list[dict[str, Any]], source: str) -> int:
    return max((int(((row.get("diagnostics") or {}).get("source_coverage") or {}).get(source, 0) or 0) for row in rows), default=0)


def _users_exceeding_source_cap(rows: list[dict[str, Any]], source: str, cap: int) -> list[dict[str, Any]]:
    if cap <= 0:
        return []
    exceeded = []
    for row in rows:
        count = int(((row.get("diagnostics") or {}).get("source_coverage") or {}).get(source, 0) or 0)
        if count > cap:
            exceeded.append({"user_id": row.get("user_id"), "count": count})
    return exceeded


def _sorting_disabled(config: dict[str, Any]) -> bool:
    return not any(
        bool((config.get(key) or {}).get("enabled"))
        for key in ("ltr_model", "ranking_v2", "item_feature_rerank", "source_aware_fusion")
    )


def _run_overrides(output_path: Path, label: str, run_id: str) -> dict[str, Any]:
    run_dir = output_path.parent / run_id / label
    return {
        "output_dir": str(run_dir),
        "report_path": str(run_dir / "report.md"),
        "strategy_name": f"phase_1_19_gate_{label}_{run_id}",
    }


def _load_existing_sidecar_manifest(config: dict[str, Any]) -> dict[str, Any] | None:
    manifest_path = config.get("graph_walk_seed_manifest_path") or (config.get("graph_walk_training") or {}).get("manifest_path")
    if not manifest_path:
        return None
    resolved = _resolve(manifest_path)
    if not resolved.exists():
        return None
    return read_json(resolved)


def _read_rows(path: str | Path) -> list[dict[str, Any]]:
    resolved = _resolve(path)
    if not resolved.exists():
        return []
    return read_jsonl(resolved)


def _candidate_generation_p95(metrics: dict[str, Any]) -> float:
    return float((metrics.get("latency") or {}).get("candidate_generation_p95_seconds") or 0.0)


def _percentile(values: list[float], percentile: float) -> float:
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return round(values[index], 6)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_id(config_path: Path, limit_users: int | None) -> str:
    seed = f"{datetime.now(UTC).isoformat()}|{config_path}|{limit_users}"
    return "run_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


if __name__ == "__main__":
    main()
