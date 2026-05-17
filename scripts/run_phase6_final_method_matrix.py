from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json
from scripts.run_phase1_itemcf_covisit_representative_merge_eval import _enforce_project_venv, _existing_ancestor, _file_signature, _read_json

SCHEMA_VERSION = "phase6_final_method_matrix_v1"
DEFAULT_BASE_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR / "final_method_matrix"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
PHASES = [
    {
        "phase": "Phase 0",
        "method_family": "contract_precheck",
        "artifact_dir": "phase0_contract_precheck",
        "decision": "pass_gate",
        "required": ["manifest.json", "source_audit.json", "resolved_inputs.json"],
    },
    {
        "phase": "Phase 1",
        "method_family": "bounded_itemcf_covisit",
        "artifact_dir": "itemcf_covisit_representative_merge_eval",
        "decision": "observation_only_no_lift",
        "required": ["manifest.json", "source_audit.json", "metrics.json", "ablation_vs_lightweight_baseline.json", "candidates.jsonl"],
    },
    {
        "phase": "Phase 2",
        "method_family": "usercf_bounded",
        "artifact_dir": "usercf_bounded_observation",
        "decision": "reject_no_positive_lift",
        "required": ["manifest.json", "source_audit.json", "metrics.json", "ablation_vs_lightweight_baseline.json", "source_overlap_with_itemcf.json", "candidates.jsonl"],
    },
    {
        "phase": "Phase 3",
        "method_family": "swing_sequence_session",
        "artifact_dir": "swing_sequence_session_observation",
        "decision": "observation_only_no_promotion",
        "required": ["manifest.json", "source_audit.json", "metrics.json", "ablation_vs_lightweight_baseline.json", "session_definition_audit.json", "transition_sidecar_manifest.json", "candidates.jsonl"],
    },
    {
        "phase": "Phase 4",
        "method_family": "graph_mf_contract",
        "artifact_dir": "graph_mf_contract_validation",
        "decision": "contract_only_defer_training",
        "required": ["manifest.json", "source_audit.json", "metrics.json", "graph_contract_validation.json", "mf_contract_validation.json"],
    },
    {
        "phase": "Phase 5",
        "method_family": "two_tower_pool_readiness",
        "artifact_dir": "two_tower_pool_readiness",
        "decision": "feasibility_only_defer_training",
        "required": ["manifest.json", "source_audit.json", "metrics.json", "two_tower_feasibility.json", "pool_readiness.json"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build final recall method matrix for Phase 0-5 artifacts.")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase6_final_method_matrix(
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    start = perf_counter()
    if enforce_venv:
        _enforce_project_venv()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below threshold: {disk_free_start} < {min_free_bytes}")
    base_dir = base_dir.resolve()

    rows = []
    failures = []
    for phase in PHASES:
        artifact_dir = base_dir / phase["artifact_dir"]
        manifest_path = artifact_dir / "manifest.json"
        source_audit_path = artifact_dir / "source_audit.json"
        missing = [name for name in phase["required"] if not (artifact_dir / name).exists()]
        manifest = _read_json(manifest_path) if manifest_path.exists() else {}
        source_audit = _read_json(source_audit_path) if source_audit_path.exists() else {}
        required_artifacts = manifest.get("required_artifacts", {})
        artifact_signatures = {
            name: _file_signature(artifact_dir / name)
            for name in phase["required"]
            if (artifact_dir / name).exists()
        }
        if missing:
            failures.append(f"{phase['phase']} missing required artifacts: {', '.join(missing)}")
        candidate_generation_uses_holdout = _candidate_generation_uses_holdout(source_audit)
        train_only_candidate_generation = source_audit.get("train_only_candidate_generation", source_audit.get("train_only"))
        if source_audit and candidate_generation_uses_holdout is not False:
            failures.append(f"{phase['phase']} source audit does not prove holdout exclusion")
        rows.append(
            {
                "phase": phase["phase"],
                "method_family": phase["method_family"],
                "status": manifest.get("status"),
                "decision": phase["decision"],
                "failure_reason": manifest.get("failure_reason"),
                "downgrade_action": manifest.get("downgrade_action"),
                "artifact_dir": str(artifact_dir),
                "required_artifacts_present": not missing,
                "missing_artifacts": missing,
                "candidate_generation_uses_holdout": candidate_generation_uses_holdout,
                "train_only_candidate_generation": train_only_candidate_generation,
                "disabled_outputs": source_audit.get("disabled_outputs", {}),
                "row_count": manifest.get("candidate_row_count"),
                "empty_user_count": manifest.get("empty_user_count"),
                "required_artifacts": required_artifacts,
                "artifact_signatures": artifact_signatures,
            }
        )

    status = "PASS" if not failures else "BLOCKED"
    matrix = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "rows": rows,
        "summary": {
            "phase_count": len(rows),
            "pass_like_count": sum(1 for row in rows if row["status"] in {"PASS", "EXECUTED_PASS_OBSERVATION_ONLY", "EXECUTED_PASS_CONTRACT_ONLY", "EXECUTED_PASS_FEASIBILITY_ONLY"}),
            "rejected_count": sum(1 for row in rows if row["status"] == "rejected"),
            "blocked_count": sum(1 for row in rows if row["status"] in {"blocked", "BLOCKED"}),
            "promotion_count": sum(1 for row in rows if row["status"] == "promotion_candidate"),
        },
        "global_contracts": {
            "valid_test_holdout_candidate_generation_forbidden": True,
            "ranking_frozen_pool200_not_replaced_by_pool500_pool1000": True,
            "two_tower_training_deferred_without_explicit_gpu_approval": True,
            "phase4_graph_mf_training_deferred": True,
        },
        "failures": failures,
    }
    output_dir.mkdir(parents=True)
    write_json(output_dir / "final_method_matrix.json", matrix)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_reason": "final_matrix_validation_failed" if failures else None,
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - start, 6),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "phase_count": len(rows),
        "failures": failures,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "final_method_matrix": str(output_dir / "final_method_matrix.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _candidate_generation_uses_holdout(source_audit: dict[str, Any]) -> Any:
    if "candidate_generation_uses_holdout" in source_audit:
        return source_audit["candidate_generation_uses_holdout"]
    holdout_contract = source_audit.get("holdout_contract")
    if isinstance(holdout_contract, dict) and "candidate_generation_uses_holdout" in holdout_contract:
        return holdout_contract["candidate_generation_uses_holdout"]
    return None


def main() -> None:
    args = parse_args()
    manifest = run_phase6_final_method_matrix(
        base_dir=Path(args.base_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    if manifest["status"] != "PASS":
        raise RuntimeError(f"Phase 6 final matrix failed: {manifest['failures']}")
    print(f"Phase 6 final method matrix status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
