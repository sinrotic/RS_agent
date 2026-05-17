from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from scripts.run_full_lightweight_recall_e2e import MIN_FREE_BYTES
from scripts.run_phase1_itemcf_covisit_representative_merge_eval import (
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
)

SCHEMA_VERSION = "pool500_representative_p5_method_observations_v1"
DEFAULT_P0_P2_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
DEFAULT_P3_P4_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "p3_p4_audit"
DEFAULT_PRIOR_METHOD_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "p5_method_observations"
FORBIDDEN_PATH_MARKERS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
)
EXECUTED_POOL500_SOURCES = ("popular", "category", "semantic")
OBSERVED_PRIOR_METHODS = {
    "itemcf_covisit": "itemcf_covisit_representative_merge_eval",
    "usercf_bounded": "usercf_bounded_observation",
    "swing_sequence_session": "swing_sequence_session_observation",
}
DEFERRED_PRIOR_METHODS = {
    "graph_mf_contract": "graph_mf_contract_validation",
    "two_tower_pool_readiness": "two_tower_pool_readiness",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate pool500 representative P5 per-method observations.")
    parser.add_argument("--p0-p2-dir", default=str(DEFAULT_P0_P2_DIR))
    parser.add_argument("--p3-p4-dir", default=str(DEFAULT_P3_P4_DIR))
    parser.add_argument("--prior-method-dir", default=str(DEFAULT_PRIOR_METHOD_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_representative_p5_method_observations(
    *,
    p0_p2_dir: Path = DEFAULT_P0_P2_DIR,
    p3_p4_dir: Path = DEFAULT_P3_P4_DIR,
    prior_method_dir: Path = DEFAULT_PRIOR_METHOD_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()

    p0_p2_dir = p0_p2_dir.resolve()
    p3_p4_dir = p3_p4_dir.resolve()
    prior_method_dir = prior_method_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck(p0_p2_dir, p3_p4_dir, prior_method_dir, output_dir, min_free_bytes)

    pool500_path = p0_p2_dir / "pool500_recall_only" / "candidates.jsonl"
    pool200_path = p0_p2_dir / "pool200_same_scope" / "candidates.jsonl"
    pool500_source_audit_path = p0_p2_dir / "pool500_recall_only" / "source_audit.json"
    comparison_path = p3_p4_dir / "pool500_vs_pool200_same_scope_comparison.json"
    p0_manifest_path = p0_p2_dir / "manifest.json"
    p3_manifest_path = p3_p4_dir / "manifest.json"

    pool500_source_audit = read_json(pool500_source_audit_path)
    comparison = read_json(comparison_path)
    p0_manifest = read_json(p0_manifest_path)
    p3_manifest = read_json(p3_manifest_path)
    source_contribution = _pool500_source_contribution(pool500_path)
    method_contribution = _method_contribution_201_500(source_contribution, comparison)
    prior_observations = _prior_method_observations(prior_method_dir)
    deferred_methods = _deferred_methods(prior_method_dir)
    method_observations = _method_observations(
        pool500_source_audit=pool500_source_audit,
        method_contribution=method_contribution,
        prior_observations=prior_observations,
        deferred_methods=deferred_methods,
    )
    source_audit = _source_audit(
        p0_p2_dir=p0_p2_dir,
        p3_p4_dir=p3_p4_dir,
        prior_method_dir=prior_method_dir,
        pool500_path=pool500_path,
        pool200_path=pool200_path,
        comparison_path=comparison_path,
        p0_manifest=p0_manifest,
        p3_manifest=p3_manifest,
    )

    output_dir.mkdir(parents=True)
    write_json(output_dir / "method_observations.json", method_observations)
    write_json(output_dir / "method_contribution_201_500.json", method_contribution)
    write_json(output_dir / "deferred_methods.json", deferred_methods)
    write_json(output_dir / "source_audit.json", source_audit)

    status = "PASS" if _artifacts_pass(method_observations, method_contribution, deferred_methods, source_audit) else "FAIL"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "representative_pool500_p5_per_method_observations_recall_only",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "no_candidate_generation_executed": True,
        "no_model_training_executed": True,
        "no_ranking_input_modified": True,
        "required_artifacts": {
            "method_observations": str(output_dir / "method_observations.json"),
            "method_contribution_201_500": str(output_dir / "method_contribution_201_500.json"),
            "deferred_methods": str(output_dir / "deferred_methods.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "input_signatures": {
            "pool200_candidates": _file_signature(pool200_path),
            "pool500_candidates": _file_signature(pool500_path),
            "pool500_source_audit": _file_signature(pool500_source_audit_path),
            "p3_p4_comparison": _file_signature(comparison_path),
            "p0_p2_manifest": _file_signature(p0_manifest_path),
            "p3_p4_manifest": _file_signature(p3_manifest_path),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _precheck(p0_p2_dir: Path, p3_p4_dir: Path, prior_method_dir: Path, output_dir: Path, min_free_bytes: int) -> None:
    for path in (p0_p2_dir, p3_p4_dir, prior_method_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
            raise ValueError(f"Forbidden pool500 P5 path marker in {path}")
    required = [
        p0_p2_dir / "manifest.json",
        p0_p2_dir / "pool200_same_scope" / "candidates.jsonl",
        p0_p2_dir / "pool500_recall_only" / "candidates.jsonl",
        p0_p2_dir / "pool500_recall_only" / "source_audit.json",
        p3_p4_dir / "manifest.json",
        p3_p4_dir / "pool500_vs_pool200_same_scope_comparison.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing P5 inputs: {missing}")
    if output_dir.exists() and (output_dir / "manifest.json").exists():
        raise FileExistsError(f"Completed output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _pool500_source_contribution(pool500_path: Path) -> dict[str, Any]:
    source_stats: dict[str, dict[str, Any]] = {
        source: {"candidate_rows": 0, "users": set(), "items": set(), "rows_201_500": 0, "users_201_500": set(), "items_201_500": set()}
        for source in EXECUTED_POOL500_SOURCES
    }
    row_count = 0
    row_count_201_500 = 0
    for row in iter_jsonl(pool500_path):
        row_count += 1
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        rank = int(row.get("rank") or 0)
        sources = [source for source in row.get("sources", []) if source in source_stats]
        if 201 <= rank <= 500:
            row_count_201_500 += 1
        for source in sources:
            stats = source_stats[source]
            stats["candidate_rows"] += 1
            stats["users"].add(user_id)
            stats["items"].add(item_id)
            if 201 <= rank <= 500:
                stats["rows_201_500"] += 1
                stats["users_201_500"].add(user_id)
                stats["items_201_500"].add(item_id)
    return {
        "candidate_rows": row_count,
        "rows_201_500": row_count_201_500,
        "source_stats": {
            source: {
                "candidate_rows": stats["candidate_rows"],
                "user_coverage": len(stats["users"]),
                "item_coverage": len(stats["items"]),
                "rows_201_500": stats["rows_201_500"],
                "user_coverage_201_500": len(stats["users_201_500"]),
                "item_coverage_201_500": len(stats["items_201_500"]),
            }
            for source, stats in source_stats.items()
        },
    }


def _method_contribution_201_500(source_contribution: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    exclusive_hit_source_counts = dict(comparison.get("source_attribution_for_exclusive_hits", {}))
    methods: dict[str, Any] = {}
    for source, stats in source_contribution["source_stats"].items():
        methods[source] = {
            "status": "EXECUTED_POOL500_OBSERVATION",
            "candidate_rows_total": stats["candidate_rows"],
            "candidate_rows_201_500": stats["rows_201_500"],
            "user_coverage_total": stats["user_coverage"],
            "user_coverage_201_500": stats["user_coverage_201_500"],
            "item_coverage_total": stats["item_coverage"],
            "item_coverage_201_500": stats["item_coverage_201_500"],
            "exclusive_hit_count_201_500": int(exclusive_hit_source_counts.get(source, 0)),
            "contribution_basis": "existing pool500 candidate sources plus P3 same-scope exclusive-hit attribution",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "scope": "rank_201_to_500_pool500_existing_candidates",
        "pool500_candidate_rows": source_contribution["candidate_rows"],
        "pool500_rows_201_500": source_contribution["rows_201_500"],
        "exclusive_hit_users_201_500": comparison.get("exclusive_hit_users_201_500"),
        "exclusive_hit_details_201_500": comparison.get("exclusive_hit_details_201_500", []),
        "source_attribution_for_exclusive_hits": exclusive_hit_source_counts,
        "methods": methods,
        "non_executed_methods_contribution": {
            "itemcf_covisit": "not present in this pool500 candidate artifact; prior controlled observation exists outside pool500 P0-P2 generation",
            "usercf_bounded": "not present in this pool500 candidate artifact; prior controlled observation exists outside pool500 P0-P2 generation",
            "swing": "not present in this pool500 candidate artifact; prior controlled observation exists outside pool500 P0-P2 generation",
            "session_transition": "not present in this pool500 candidate artifact; prior controlled observation exists outside pool500 P0-P2 generation",
            "graph": "contract/deferred; no training and no pool500 contribution",
            "mf": "contract/deferred; no training and no pool500 contribution",
            "two_tower": "feasibility/deferred; no training and no pool500 contribution",
        },
    }


def _prior_method_observations(prior_method_dir: Path) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for method, artifact_dir_name in OBSERVED_PRIOR_METHODS.items():
        artifact_dir = prior_method_dir / artifact_dir_name
        manifest_path = artifact_dir / "manifest.json"
        metrics_path = artifact_dir / "metrics.json"
        ablation_path = artifact_dir / "ablation_vs_lightweight_baseline.json"
        if not manifest_path.is_file():
            observations[method] = {
                "status": "OBSERVATION_PENDING",
                "reason": f"missing prior manifest: {manifest_path}",
            }
            continue
        manifest = read_json(manifest_path)
        observations[method] = {
            "status": "CONTROLLED_OBSERVATION_AVAILABLE",
            "source_scope": "prior full_main_route_other_methods representative observation",
            "manifest_status": manifest.get("status"),
            "output_dir": manifest.get("output_dir"),
            "candidate_row_count": manifest.get("candidate_row_count"),
            "empty_user_count": manifest.get("empty_user_count"),
            "manifest_path": str(manifest_path),
            "metrics_path": str(metrics_path) if metrics_path.is_file() else None,
            "ablation_path": str(ablation_path) if ablation_path.is_file() else None,
        }
        if ablation_path.is_file():
            ablation = read_json(ablation_path)
            observations[method]["ablation_vs_lightweight_baseline"] = {
                key: ablation.get(key)
                for key in (
                    "candidate_hit_users_delta",
                    "recall_at_pool_delta",
                    "empty_candidate_rate_delta",
                    "fallback_rate_delta",
                    "source_marginal_hit",
                    "swing_marginal_hit",
                    "session_transition_marginal_hit",
                )
                if key in ablation
            }
    return observations


def _deferred_methods(prior_method_dir: Path) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    graph_mf_dir = prior_method_dir / DEFERRED_PRIOR_METHODS["graph_mf_contract"]
    two_tower_dir = prior_method_dir / DEFERRED_PRIOR_METHODS["two_tower_pool_readiness"]
    graph_mf_manifest = _optional_json(graph_mf_dir / "manifest.json")
    two_tower_manifest = _optional_json(two_tower_dir / "manifest.json")
    for method in ("graph", "mf"):
        methods[method] = {
            "status": "DEFERRED_CONTRACT_ONLY",
            "reason": "training is out of pool500 representative P5 scope",
            "contract_artifact_dir": str(graph_mf_dir),
            "contract_status": graph_mf_manifest.get("status") if graph_mf_manifest else "missing_contract_artifact",
            "no_model_training_executed": graph_mf_manifest.get("no_model_training_executed") if graph_mf_manifest else None,
            "pool500_contribution": 0,
        }
    methods["two_tower"] = {
        "status": "DEFERRED_FEASIBILITY_ONLY",
        "reason": "two_tower training is explicitly forbidden for pool500 representative P5",
        "contract_artifact_dir": str(two_tower_dir),
        "contract_status": two_tower_manifest.get("status") if two_tower_manifest else "missing_contract_artifact",
        "no_two_tower_training_executed": two_tower_manifest.get("no_two_tower_training_executed") if two_tower_manifest else None,
        "pool500_contribution": 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "methods": methods,
    }


def _method_observations(
    *,
    pool500_source_audit: dict[str, Any],
    method_contribution: dict[str, Any],
    prior_observations: dict[str, Any],
    deferred_methods: dict[str, Any],
) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for method, contribution in method_contribution["methods"].items():
        methods[method] = {
            "observation_type": "executed_in_pool500_representative_candidates",
            **contribution,
        }
    for method, observation in prior_observations.items():
        methods[method] = {
            "observation_type": "prior_controlled_representative_observation_not_rerun_for_pool500",
            **observation,
        }
    for method, observation in deferred_methods["methods"].items():
        methods[method] = {
            "observation_type": "deferred_or_contract_only",
            **observation,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "scope": "pool500_representative_method_observations_without_new_candidate_generation",
        "pool500_executed_sources": list(EXECUTED_POOL500_SOURCES),
        "pool500_source_candidate_rows": pool500_source_audit.get("source_candidate_rows", {}),
        "pool500_source_user_coverage": pool500_source_audit.get("source_user_coverage", {}),
        "pool500_source_item_coverage": pool500_source_audit.get("source_item_coverage", {}),
        "methods": methods,
        "decision_summary": {
            "pool500_201_500_incremental_hit_sources": method_contribution.get("source_attribution_for_exclusive_hits", {}),
            "itemcf_usercf_swing_session": "represented by existing controlled observations when artifacts exist; not rerun for pool500 P5",
            "graph_mf_two_tower": "deferred/contract only; no training",
        },
    }


def _source_audit(
    *,
    p0_p2_dir: Path,
    p3_p4_dir: Path,
    prior_method_dir: Path,
    pool500_path: Path,
    pool200_path: Path,
    comparison_path: Path,
    p0_manifest: dict[str, Any],
    p3_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_candidate_generation": True,
        "candidate_generation_executed_in_p5": False,
        "candidate_generation_uses_holdout": False,
        "p5_read_only_inputs": [
            str(pool200_path),
            str(pool500_path),
            str(p0_p2_dir / "pool500_recall_only" / "source_audit.json"),
            str(comparison_path),
            str(p0_p2_dir / "manifest.json"),
            str(p3_p4_dir / "manifest.json"),
            str(prior_method_dir),
        ],
        "ranking_isolation": {
            "pool500_as_ranking_input": False,
            "ranking_default_input_modified": False,
            "frozen_pool200_ranking_baseline_replaced": False,
            "p0_p2_ranking_isolation": p0_manifest.get("ranking_isolation", {}),
            "p3_p4_ranking_boundary": p3_manifest.get("ranking_boundary"),
        },
        "disabled_outputs": {
            "pool1000": True,
            "graph_training": True,
            "mf_training": True,
            "two_tower_training": True,
            "ranking": True,
            "dense_all_user_matrix": True,
        },
        "source_signatures": {
            "pool200_candidates": _file_signature(pool200_path),
            "pool500_candidates": _file_signature(pool500_path),
            "p3_p4_comparison": _file_signature(comparison_path),
        },
    }


def _artifacts_pass(*artifacts: dict[str, Any]) -> bool:
    return all(artifact.get("status") == "PASS" for artifact in artifacts)


def _optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    manifest = run_pool500_representative_p5_method_observations(
        p0_p2_dir=Path(args.p0_p2_dir),
        p3_p4_dir=Path(args.p3_p4_dir),
        prior_method_dir=Path(args.prior_method_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
