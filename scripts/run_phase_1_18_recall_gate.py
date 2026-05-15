from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_core.common.io import write_json
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.two_tower_training import build_two_tower_seed_sidecar_from_config

DEFAULT_BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml"
DEFAULT_EXPERIMENT_CONFIG = ROOT / "configs/recall/phase_1_18/phase_1_18_two_tower_seed_pool100.yaml"
DEFAULT_LOPO_CONFIG = ROOT / "configs/recall/phase_1_18/phase_1_18_lopo_two_tower_seed_pool100.yaml"
DEFAULT_OUTPUT = ROOT / "outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.18 same-run recall gate for two_tower_seed.")
    parser.add_argument("--baseline-config", default=str(DEFAULT_BASELINE_CONFIG), help="Frozen recall baseline config.")
    parser.add_argument("--experiment-config", default=str(DEFAULT_EXPERIMENT_CONFIG), help="Phase 1.18 experiment config.")
    parser.add_argument("--lopo-config", default=str(DEFAULT_LOPO_CONFIG), help="Optional LOPO sanity config.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Comparison JSON output path.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional quick-run user limit.")
    parser.add_argument("--skip-sidecar-build", action="store_true", help="Use existing sidecar instead of rebuilding from config.")
    parser.add_argument("--skip-lopo", action="store_true", help="Skip LOPO sanity run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_config = _resolve(args.baseline_config)
    experiment_config = _resolve(args.experiment_config)
    lopo_config = _resolve(args.lopo_config)
    output_path = _resolve(args.output)

    sidecar_manifest = None
    if not args.skip_sidecar_build:
        sidecar_manifest = build_two_tower_seed_sidecar_from_config(experiment_config)

    baseline_result = run_hybrid_demo(baseline_config, limit_users=args.limit_users)
    experiment_result = run_hybrid_demo(experiment_config, limit_users=args.limit_users)
    lopo_result = None if args.skip_lopo else run_hybrid_demo(lopo_config, limit_users=args.limit_users)

    baseline_metrics = baseline_result["metrics"]
    experiment_metrics = experiment_result["metrics"]
    lopo_metrics = lopo_result["metrics"] if lopo_result else None
    comparison = {
        "phase": "1.18",
        "source": "two_tower_seed",
        "baseline": {
            "config_path": str(baseline_config),
            "config_sha256": _sha256_file(baseline_config),
            "metrics_path": baseline_result["metrics_path"],
            "metrics": _recall_metrics(baseline_metrics),
        },
        "experiment": {
            "config_path": str(experiment_config),
            "config_sha256": _sha256_file(experiment_config),
            "metrics_path": experiment_result["metrics_path"],
            "metrics": _recall_metrics(experiment_metrics),
        },
        "lopo_sanity": None if lopo_metrics is None else {
            "config_path": str(lopo_config),
            "config_sha256": _sha256_file(lopo_config),
            "metrics_path": lopo_result["metrics_path"],
            "metrics": _recall_metrics(lopo_metrics),
        },
        "sidecar_manifest": sidecar_manifest or _load_existing_sidecar_manifest(experiment_config),
        "gate": _phase_1_18_gate(baseline_metrics, experiment_metrics, load_config(experiment_config)),
    }
    write_json(output_path, comparison)
    print(f"Phase 1.18 gate comparison written to: {output_path}")
    if not comparison["gate"]["passed"]:
        raise SystemExit(1)


def _phase_1_18_gate(baseline: dict[str, Any], experiment: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    thresholds = dict(config.get("phase_1_18_gate", {}).get("thresholds", {}) or {})
    max_p95 = float(thresholds.get("max_candidate_generation_p95_seconds", 0.543559))
    min_hit_user_lift = int(thresholds.get("min_candidate_hit_users_lift", 1))
    experiment_p95 = _candidate_generation_p95(experiment)
    source_hits = int((experiment.get("candidate_hit_source_coverage") or {}).get("two_tower_seed", 0) or 0)
    checks = {
        "candidate_hit_users_lift": int(experiment.get("candidate_hit_users") or 0) >= int(baseline.get("candidate_hit_users") or 0) + min_hit_user_lift,
        "candidate_hit_rate_at_pool_lift": float(experiment.get("candidate_hit_rate_at_pool") or 0.0) > float(baseline.get("candidate_hit_rate_at_pool") or 0.0),
        "recall_at_pool_lift": float(experiment.get("recall_at_pool") or 0.0) > float(baseline.get("recall_at_pool") or 0.0),
        "fallback_rate_zero": float(experiment.get("fallback_rate") or 0.0) == float(thresholds.get("max_fallback_rate", 0.0)),
        "candidate_generation_p95_budget": experiment_p95 <= max_p95,
        "two_tower_seed_hit_contribution": source_hits > 0,
        "sorting_disabled": _sorting_disabled(config),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "deltas": {
            "candidate_hit_users": int(experiment.get("candidate_hit_users") or 0) - int(baseline.get("candidate_hit_users") or 0),
            "candidate_hit_rate_at_pool": round(float(experiment.get("candidate_hit_rate_at_pool") or 0.0) - float(baseline.get("candidate_hit_rate_at_pool") or 0.0), 6),
            "recall_at_pool": round(float(experiment.get("recall_at_pool") or 0.0) - float(baseline.get("recall_at_pool") or 0.0), 6),
        },
        "thresholds": {
            "min_candidate_hit_users_lift": min_hit_user_lift,
            "max_candidate_generation_p95_seconds": max_p95,
        },
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
        "source_diagnostics": metrics.get("source_diagnostics", {}),
    }


def _candidate_generation_p95(metrics: dict[str, Any]) -> float:
    return float((metrics.get("latency") or {}).get("candidate_generation_p95_seconds") or 0.0)


def _sorting_disabled(config: dict[str, Any]) -> bool:
    return not any(
        bool((config.get(key) or {}).get("enabled"))
        for key in ("ltr_model", "ranking_v2", "item_feature_rerank", "source_aware_fusion")
    )


def _load_existing_sidecar_manifest(config_path: Path) -> dict[str, Any] | None:
    config = load_config(config_path)
    manifest_path = config.get("two_tower_seed_manifest_path") or (config.get("two_tower_seed_sidecar") or {}).get("manifest_path")
    if not manifest_path:
        return None
    resolved = _resolve(manifest_path)
    if not resolved.exists():
        return None
    return json.loads(resolved.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


if __name__ == "__main__":
    main()
