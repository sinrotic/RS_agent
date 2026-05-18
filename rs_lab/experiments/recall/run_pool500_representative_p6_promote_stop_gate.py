from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_lab.experiments.recall.run_full_lightweight_recall_e2e import MIN_FREE_BYTES
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
)

SCHEMA_VERSION = "pool500_representative_p6_promote_stop_gate_v1"
DEFAULT_P0_P2_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
DEFAULT_P3_P4_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "p3_p4_audit"
DEFAULT_P5_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "p5_method_observations"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "p6_promote_stop_gate"
FORBIDDEN_PATH_MARKERS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
)
FORBIDDEN_TRAINING_FLAGS = ("two_tower_training", "graph_training", "mf_training")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate pool500 representative P6 promote/stop gate.")
    parser.add_argument("--p0-p2-dir", default=str(DEFAULT_P0_P2_DIR))
    parser.add_argument("--p3-p4-dir", default=str(DEFAULT_P3_P4_DIR))
    parser.add_argument("--p5-dir", default=str(DEFAULT_P5_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_representative_p6_promote_stop_gate(
    *,
    p0_p2_dir: Path = DEFAULT_P0_P2_DIR,
    p3_p4_dir: Path = DEFAULT_P3_P4_DIR,
    p5_dir: Path = DEFAULT_P5_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()

    p0_p2_dir = p0_p2_dir.resolve()
    p3_p4_dir = p3_p4_dir.resolve()
    p5_dir = p5_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck(p0_p2_dir, p3_p4_dir, p5_dir, output_dir, min_free_bytes)

    paths = _input_paths(p0_p2_dir, p3_p4_dir, p5_dir)
    artifacts = {name: read_json(path) for name, path in paths.items()}
    rule_results = _rule_results(artifacts)
    decision = "PASS" if all(rule["pass"] for rule in rule_results.values()) else "STOP"
    failed_rules = [name for name, rule in rule_results.items() if not rule["pass"]]
    reasons = [rule_results[name]["reason"] for name in failed_rules]
    if decision == "PASS":
        reasons = [
            "pool500 representative adds same-scope recall-only value at ranks 201-500 while preserving leakage, resource, and ranking isolation gates"
        ]

    promote_stop_gate = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if decision == "PASS" else "FAIL",
        "decision": decision,
        "scope": "representative_pool500_p6_promote_stop_gate_recall_only",
        "p7_allowed": decision == "PASS",
        "p7_allowed_scope": "representative recall-only continuation; not ranking input replacement" if decision == "PASS" else None,
        "reasons": reasons,
        "rule_results": rule_results,
        "decision_inputs": {
            "exclusive_hit_users_201_500": artifacts["comparison"].get("exclusive_hit_users_201_500"),
            "source_attribution_for_exclusive_hits": artifacts["comparison"].get("source_attribution_for_exclusive_hits", {}),
            "delta": artifacts["comparison"].get("delta", {}),
            "duplicate_empty_fallback_comparison": artifacts["comparison"].get("duplicate_empty_fallback_comparison", {}),
            "audit_statuses": {
                "p0_p2_manifest": artifacts["p0_p2_manifest"].get("status"),
                "p3_p4_manifest": artifacts["p3_p4_manifest"].get("status"),
                "p5_manifest": artifacts["p5_manifest"].get("status"),
                "leakage_audit": artifacts["leakage_audit"].get("status"),
                "resource_audit": artifacts["resource_audit"].get("status"),
                "ranking_isolation_audit": artifacts["ranking_isolation_audit"].get("status"),
                "p5_source_audit": artifacts["p5_source_audit"].get("status"),
            },
        },
        "p6_execution_boundary": {
            "no_candidate_generation_executed": True,
            "no_full_pool500_executed": True,
            "no_ranking_executed": True,
            "no_model_training_executed": True,
            "read_only_inputs": {name: str(path) for name, path in paths.items()},
        },
    }

    output_dir.mkdir(parents=True)
    write_json(output_dir / "promote_stop_gate.json", promote_stop_gate)
    write_json(output_dir / "source_audit.json", _source_audit(paths, artifacts))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": promote_stop_gate["status"],
        "decision": decision,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "representative_pool500_p6_promote_stop_gate_recall_only",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "no_candidate_generation_executed": True,
        "no_full_pool500_executed": True,
        "no_ranking_input_modified": True,
        "no_pool1000_generated": True,
        "no_model_training_executed": True,
        "required_artifacts": {
            "promote_stop_gate": str(output_dir / "promote_stop_gate.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "input_signatures": {name: _file_signature(path) for name, path in paths.items()},
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _precheck(p0_p2_dir: Path, p3_p4_dir: Path, p5_dir: Path, output_dir: Path, min_free_bytes: int) -> None:
    for path in (p0_p2_dir, p3_p4_dir, p5_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
            raise ValueError(f"Forbidden pool500 P6 path marker in {path}")
    required = list(_input_paths(p0_p2_dir, p3_p4_dir, p5_dir).values())
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing P6 inputs: {missing}")
    if output_dir.exists() and (output_dir / "manifest.json").exists():
        raise FileExistsError(f"Completed output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _input_paths(p0_p2_dir: Path, p3_p4_dir: Path, p5_dir: Path) -> dict[str, Path]:
    return {
        "p0_p2_manifest": p0_p2_dir / "manifest.json",
        "p0_p2_source_audit": p0_p2_dir / "source_audit.json",
        "comparison": p3_p4_dir / "pool500_vs_pool200_same_scope_comparison.json",
        "leakage_audit": p3_p4_dir / "leakage_audit.json",
        "resource_audit": p3_p4_dir / "resource_audit.json",
        "ranking_isolation_audit": p3_p4_dir / "ranking_isolation_audit.json",
        "p3_p4_manifest": p3_p4_dir / "manifest.json",
        "method_observations": p5_dir / "method_observations.json",
        "method_contribution_201_500": p5_dir / "method_contribution_201_500.json",
        "p5_source_audit": p5_dir / "source_audit.json",
        "p5_manifest": p5_dir / "manifest.json",
    }


def _rule_results(artifacts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    comparison = artifacts["comparison"]
    duplicate_empty_fallback = comparison.get("duplicate_empty_fallback_comparison", {})
    p0_manifest = artifacts["p0_p2_manifest"]
    p0_source_audit = artifacts["p0_p2_source_audit"]
    p5_source_audit = artifacts["p5_source_audit"]
    method_observations = artifacts["method_observations"]
    method_contribution = artifacts["method_contribution_201_500"]
    ranking_isolation = artifacts["ranking_isolation_audit"]

    rule_results = {
        "exclusive_hit_users_201_500_positive": _rule(
            int(comparison.get("exclusive_hit_users_201_500") or 0) > 0,
            f"exclusive_hit_users_201_500={comparison.get('exclusive_hit_users_201_500')}",
        ),
        "source_attribution_explained": _rule(
            _source_attribution_explained(comparison, method_contribution),
            "exclusive 201-500 hits include non-empty source attribution and P5 method contribution repeats it",
        ),
        "recall_side_metric_non_negative_or_added": _rule(
            bool(comparison.get("pool500_adds_recall_side_value")) or _non_negative_delta(comparison),
            f"delta={comparison.get('delta', {})}, pool500_adds_recall_side_value={comparison.get('pool500_adds_recall_side_value')}",
        ),
        "duplicate_empty_fallback_not_worse": _rule(
            _duplicate_empty_fallback_not_worse(duplicate_empty_fallback),
            f"duplicate/empty/fallback comparison={duplicate_empty_fallback}",
        ),
        "leakage_audit_pass": _status_rule(artifacts["leakage_audit"], "leakage_audit"),
        "resource_audit_pass": _status_rule(artifacts["resource_audit"], "resource_audit"),
        "ranking_isolation_audit_pass": _status_rule(ranking_isolation, "ranking_isolation_audit"),
        "no_10k": _rule(
            bool(artifacts["leakage_audit"].get("no_10k")) and bool(p0_source_audit.get("no_10k_source")),
            "P0/P3 audits report no 10k source usage",
        ),
        "no_full_clean_copy": _rule(
            bool(artifacts["leakage_audit"].get("no_full_clean_copy")) and bool(p0_source_audit.get("no_full_clean_copy")),
            "P0/P3 audits report no full clean copy",
        ),
        "no_pool1000": _rule(
            _disabled(p0_manifest, "pool1000") and _disabled(p5_source_audit, "pool1000"),
            "pool1000 remains disabled in P0 and P5 audit contracts",
        ),
        "no_dense_all_user_matrix": _rule(
            _disabled(p5_source_audit, "dense_all_user_matrix"),
            "P5 audit contract disables dense all-user matrix",
        ),
        "no_full_in_memory_global_counter": _rule(
            True,
            "P6 reads compact JSON audits only and does not scan global candidate tables or build global counters",
        ),
        "no_unapproved_training": _rule(
            all(_disabled(p0_manifest, flag) and _disabled(p5_source_audit, flag) for flag in FORBIDDEN_TRAINING_FLAGS)
            and _method_training_deferred(method_observations),
            "two_tower/graph/MF are disabled or deferred contract-only; no training contribution is admitted",
        ),
        "pool500_not_replacing_frozen_pool200_ranking_input": _rule(
            not ranking_isolation.get("pool500_as_ranking_input")
            and not ranking_isolation.get("ranking_default_input_modified")
            and not ranking_isolation.get("frozen_pool200_ranking_baseline_replaced"),
            "ranking isolation audit keeps frozen pool200 ranking input unchanged",
        ),
        "input_manifests_pass": _rule(
            all(artifacts[name].get("status") == "PASS" for name in ("p0_p2_manifest", "p3_p4_manifest", "p5_manifest")),
            "P0-P2, P3-P4, and P5 manifests are PASS",
        ),
    }
    return rule_results


def _rule(passed: bool, reason: str) -> dict[str, Any]:
    return {"pass": bool(passed), "reason": reason}


def _status_rule(artifact: dict[str, Any], name: str) -> dict[str, Any]:
    return _rule(artifact.get("status") == "PASS", f"{name} status={artifact.get('status')}")


def _source_attribution_explained(comparison: dict[str, Any], method_contribution: dict[str, Any]) -> bool:
    attribution = comparison.get("source_attribution_for_exclusive_hits", {})
    contribution_attribution = method_contribution.get("source_attribution_for_exclusive_hits", {})
    details = comparison.get("exclusive_hit_details_201_500", [])
    has_sources = bool(attribution) and attribution == contribution_attribution
    details_explained = all(
        item.get("sources")
        for detail in details
        for item in detail.get("exclusive_hit_items", [])
    )
    return has_sources and details_explained


def _non_negative_delta(comparison: dict[str, Any]) -> bool:
    delta = comparison.get("delta", {})
    return (delta.get("candidate_hit_users") or 0) >= 0 and (delta.get("recall_at_pool") or 0.0) >= 0.0


def _duplicate_empty_fallback_not_worse(comparison: dict[str, Any]) -> bool:
    pool200 = comparison.get("pool200", {})
    pool500 = comparison.get("pool500", {})
    keys = ("duplicate_candidate_rows", "empty_candidate_users", "empty_candidate_rate", "fallback_rate")
    return all((pool500.get(key) or 0) <= (pool200.get(key) or 0) for key in keys)


def _disabled(artifact: dict[str, Any], key: str) -> bool:
    disabled_outputs = artifact.get("disabled_outputs", {})
    return disabled_outputs.get(key) is True


def _method_training_deferred(method_observations: dict[str, Any]) -> bool:
    methods = method_observations.get("methods", {})
    return (
        methods.get("graph", {}).get("no_model_training_executed") is True
        and methods.get("mf", {}).get("no_model_training_executed") is True
        and methods.get("two_tower", {}).get("no_two_tower_training_executed") is True
    )


def _source_audit(paths: dict[str, Path], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "candidate_generation_executed_in_p6": False,
        "full_pool500_executed_in_p6": False,
        "ranking_executed_in_p6": False,
        "model_training_executed_in_p6": False,
        "p6_read_only_inputs": {name: str(path) for name, path in paths.items()},
        "upstream_scopes": {
            "p0_p2": artifacts["p0_p2_manifest"].get("scope"),
            "p3_p4": artifacts["p3_p4_manifest"].get("scope"),
            "p5": artifacts["p5_manifest"].get("scope"),
        },
        "ranking_isolation": artifacts["ranking_isolation_audit"],
        "disabled_outputs": {
            "pool1000": True,
            "graph_training": True,
            "mf_training": True,
            "two_tower_training": True,
            "ranking": True,
            "dense_all_user_matrix": True,
            "full_in_memory_global_counter": True,
        },
        "source_signatures": {name: _file_signature(path) for name, path in paths.items()},
    }


def main() -> None:
    args = parse_args()
    manifest = run_pool500_representative_p6_promote_stop_gate(
        p0_p2_dir=Path(args.p0_p2_dir),
        p3_p4_dir=Path(args.p3_p4_dir),
        p5_dir=Path(args.p5_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "decision": manifest["decision"],
                "manifest_path": manifest["required_artifacts"]["manifest"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
