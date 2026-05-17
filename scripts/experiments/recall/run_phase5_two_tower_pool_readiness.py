from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json
from scripts.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    DEFAULT_PHASE0_DIR,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _read_json,
)
from scripts.experiments.recall.run_phase4_graph_mf_contract_validation import _forbidden_config_references, _has_forbidden_path_part, _read_config

SCHEMA_VERSION = "phase5_two_tower_pool_readiness_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "two_tower_pool_readiness"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
ALLOWED_STATES = {"EXECUTED_PASS_FEASIBILITY_ONLY", "blocked", "deferred"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Phase 5 two-tower feasibility and pool readiness without training or promotion.")
    parser.add_argument("--phase0-dir", default=str(DEFAULT_PHASE0_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase5_two_tower_pool_readiness(
    *,
    phase0_dir: Path = DEFAULT_PHASE0_DIR,
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

    phase0_dir = phase0_dir.resolve()
    phase0_manifest = _read_json(phase0_dir / "manifest.json")
    phase0_resolved = _read_json(phase0_dir / "resolved_inputs.json")
    if phase0_manifest.get("status") != "PASS":
        raise RuntimeError(f"Phase 0 must PASS before Phase 5, got {phase0_manifest.get('status')}")

    clean_dir = Path(phase0_resolved["full_clean_dir"]["path"]).resolve()
    two_tower_config = Path(phase0_resolved["phase5_two_tower_config_file"]).resolve()
    ranking_pool200_config = Path(phase0_manifest["ranking_frozen_pool200_gate"]["config_file"]).resolve()
    pool_readiness = phase0_resolved["phase5_pool_readiness_inputs"]
    frozen_pool200_candidate_source = Path(pool_readiness["frozen_pool200_candidate_source"]["path"]).resolve()
    config_payload = _read_config(two_tower_config)
    ranking_payload = _read_config(ranking_pool200_config)

    failures = []
    for label, path in {
        "two_tower_config": two_tower_config,
        "ranking_pool200_config": ranking_pool200_config,
        "frozen_pool200_candidate_source": frozen_pool200_candidate_source,
    }.items():
        if _has_forbidden_path_part(path):
            failures.append(f"{label} path references forbidden 10k source: {path}")
        if path.name in FORBIDDEN_CANDIDATE_FILES:
            failures.append(f"{label} is forbidden candidate-generation file: {path}")
    for label, payload in {"two_tower_config": config_payload, "ranking_pool200_config": ranking_payload}.items():
        forbidden = _forbidden_config_references(payload)
        if forbidden:
            failures.append(f"{label} references forbidden 10k paths: {', '.join(forbidden)}")
    if pool_readiness.get("pool500_status") != "READINESS_ONLY_NOT_RANKING_INPUT":
        failures.append("pool500 must remain readiness-only and must not become ranking input")
    if pool_readiness.get("pool1000_status") != "READINESS_ONLY_NOT_RANKING_INPUT":
        failures.append("pool1000 must remain readiness-only and must not become ranking input")
    if not phase0_manifest["ranking_frozen_pool200_gate"].get("separate_from_recall_promotion_gate"):
        failures.append("ranking frozen pool200 gate must remain separate from recall promotion gate")

    direct_10k_paths = any(_has_forbidden_path_part(path) for path in [two_tower_config, ranking_pool200_config, frozen_pool200_candidate_source])
    config_10k_references = bool(_forbidden_config_references(config_payload) or _forbidden_config_references(ranking_payload))
    status = "EXECUTED_PASS_FEASIBILITY_ONLY" if not failures else "blocked"
    two_tower_feasibility = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "BLOCKED",
        "config_file": str(two_tower_config),
        "config_signature": _file_signature(two_tower_config),
        "variant": config_payload.get("two_tower_variant") or config_payload.get("two_tower_training", {}).get("variant"),
        "two_tower_enabled_in_config": bool(config_payload.get("two_tower_enabled", False)),
        "training_default_action": "defer_until_explicit_gpu_training_approval",
        "training_executed": False,
        "promotion_disabled": True,
        "ranking_default_input_disabled": True,
        "artifact_paths_declared": {
            "two_tower_artifact_path": config_payload.get("two_tower_artifact_path"),
            "two_tower_seed_artifact_path": config_payload.get("two_tower_seed_artifact_path"),
            "two_tower_seed_manifest_path": config_payload.get("two_tower_seed_manifest_path"),
        },
    }
    pool_readiness_report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "BLOCKED",
        "ranking_pool200_config": str(ranking_pool200_config),
        "ranking_pool200_config_signature": _file_signature(ranking_pool200_config),
        "frozen_pool200_candidate_source": _file_signature(frozen_pool200_candidate_source),
        "pool500_status": pool_readiness.get("pool500_status"),
        "pool1000_status": pool_readiness.get("pool1000_status"),
        "ranking_gate": pool_readiness.get("ranking_gate"),
        "pool500_pool1000_cannot_replace_pool200": phase0_manifest["ranking_frozen_pool200_gate"].get("pool500_pool1000_cannot_replace_pool200") is True,
        "ranking_frozen_pool200_gate_separate": phase0_manifest["ranking_frozen_pool200_gate"].get("separate_from_recall_promotion_gate") is True,
        "export_frozen_candidates": bool(ranking_payload.get("export_frozen_candidates", False)),
    }
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "feasibility_only": True,
        "no_two_tower_training_executed": True,
        "candidate_generation_uses_holdout": False,
        "two_tower_feasibility": two_tower_feasibility,
        "pool_readiness": pool_readiness_report,
        "evaluation_only": {"read_files": [], "contract": "Phase 5 validates feasibility/readiness only and does not evaluate against valid/test."},
    }
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "BLOCKED",
        "train_only_candidate_generation": True,
        "feasibility_only_no_candidate_generation": True,
        "candidate_generation_read_files": [str(two_tower_config), str(ranking_pool200_config), str(frozen_pool200_candidate_source)],
        "evaluation_only_read_files": [],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "candidate_generation_uses_holdout": False,
        "no_10k_source": not direct_10k_paths and not config_10k_references,
        "disabled_outputs": {"two_tower_training": True, "recall_promotion": True, "pool500_as_ranking_input": True, "pool1000_as_ranking_input": True},
    }

    output_dir.mkdir(parents=True)
    write_json(output_dir / "two_tower_feasibility.json", two_tower_feasibility)
    write_json(output_dir / "pool_readiness.json", pool_readiness_report)
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "source_audit.json", source_audit)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_reason": "feasibility_or_readiness_contract_failed" if failures else None,
        "downgrade_action": "do_not_train_or_promote_two_tower" if failures else "record_feasibility_only_do_not_promote",
        "phase0_status": phase0_manifest.get("status"),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - start, 6),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "feasibility_only": True,
        "no_two_tower_training_executed": True,
        "failures": failures,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "two_tower_feasibility": str(output_dir / "two_tower_feasibility.json"),
            "pool_readiness": str(output_dir / "pool_readiness.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    args = parse_args()
    manifest = run_phase5_two_tower_pool_readiness(
        phase0_dir=Path(args.phase0_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    if manifest["status"] not in ALLOWED_STATES:
        raise RuntimeError(f"Unexpected Phase 5 state: {manifest['status']}")
    print(f"Phase 5 two-tower/pool readiness status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
