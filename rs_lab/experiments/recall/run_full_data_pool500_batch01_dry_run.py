from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.workflow.full_data_pool500_route_gate import (
    CANONICAL_SOURCES,
    DEFAULT_CLEAN_MANIFEST,
    DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    full_data_pool500_route_gate,
)

SCHEMA_VERSION = "full_data_pool500_batch01_dry_run_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_data_pool500_batch01_dry_run"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Batch 0/1 full-data pool500 dry-run inventory and contract artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--lightweight-views-manifest", default=str(DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-venv-check", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run_full_data_pool500_batch01_dry_run(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)

    output_dir = output_dir.resolve()
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_manifest_path = clean_manifest_path.resolve()
    lightweight_views_manifest_path = lightweight_views_manifest_path.resolve()
    clean_manifest = _read_optional_json(clean_manifest_path)
    lightweight_views_manifest = _read_optional_json(lightweight_views_manifest_path)

    batch0_inventory = build_batch0_inventory(clean_manifest_path, lightweight_views_manifest_path, clean_manifest, lightweight_views_manifest)
    batch1_method_contract = build_batch1_method_contract(batch0_inventory)
    batch1_index_manifest = build_batch1_index_manifest(batch0_inventory)
    observed_outputs = {
        "candidate_generation_executed": False,
        "output_paths": [],
        "check_files_exist": False,
    }
    route_gate_audit = full_data_pool500_route_gate(
        method_contract=batch1_method_contract,
        index_manifest=batch1_index_manifest,
        clean_manifest=clean_manifest,
        lightweight_views_manifest=lightweight_views_manifest,
        observed_outputs=observed_outputs,
    )

    required_artifacts = {
        "manifest": str(output_dir / "manifest.json"),
        "batch0_inventory": str(output_dir / "batch0_inventory.json"),
        "batch1_method_contract": str(output_dir / "batch1_method_contract.json"),
        "batch1_index_manifest": str(output_dir / "batch1_index_manifest.json"),
        "route_gate_audit": str(output_dir / "route_gate_audit.json"),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": route_gate_audit["status"],
        "decision": route_gate_audit["decision"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(perf_counter() - started, 6),
        "scope": "batch01_full_data_pool500_dry_run_inventory_contract_only",
        "project_venv_required": enforce_venv,
        "output_dir": str(output_dir),
        "no_candidate_generation_executed": True,
        "no_model_training_executed": True,
        "no_pool1000_artifacts_created": True,
        "no_ranking_input_changes": True,
        "candidate_generation_allowed_by_gate": route_gate_audit["candidate_generation_allowed"],
        "ranking_input_replacement_allowed": route_gate_audit["ranking_input_replacement_allowed"],
        "pool1000_allowed": route_gate_audit["pool1000_allowed"],
        "required_artifacts": required_artifacts,
        "blockers": route_gate_audit["blockers"],
    }

    write_json(output_dir / "batch0_inventory.json", batch0_inventory)
    write_json(output_dir / "batch1_method_contract.json", batch1_method_contract)
    write_json(output_dir / "batch1_index_manifest.json", batch1_index_manifest)
    write_json(output_dir / "route_gate_audit.json", route_gate_audit)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def build_batch0_inventory(
    clean_manifest_path: Path,
    lightweight_views_manifest_path: Path,
    clean_manifest: dict[str, Any],
    lightweight_views_manifest: dict[str, Any],
) -> dict[str, Any]:
    split_paths = clean_manifest.get("split_paths") if isinstance(clean_manifest.get("split_paths"), dict) else {}
    lightweight_outputs = lightweight_views_manifest.get("outputs") if isinstance(lightweight_views_manifest.get("outputs"), dict) else {}
    return {
        "schema_version": f"{SCHEMA_VERSION}.batch0_inventory",
        "batch": 0,
        "role": "full_data_pool500_input_inventory",
        "clean_manifest_path": str(clean_manifest_path),
        "lightweight_views_manifest_path": str(lightweight_views_manifest_path),
        "clean_manifest_status": "READY" if clean_manifest else "MISSING_OR_UNREADABLE",
        "lightweight_views_manifest_status": "READY" if lightweight_views_manifest else "MISSING_OR_UNREADABLE",
        "train_only_inputs": [
            clean_manifest.get("train_user_sequences_path"),
            split_paths.get("train"),
            clean_manifest.get("canonical_items_path"),
            *lightweight_outputs.values(),
        ],
        "evaluation_only_inputs": [split_paths.get("valid"), split_paths.get("test")],
        "lightweight_outputs": lightweight_outputs,
        "candidate_generation_executed": False,
        "model_training_executed": False,
        "ranking_input_changes": False,
    }


def build_batch1_method_contract(batch0_inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.batch1_method_contract",
        "batch": 1,
        "role": "full_data_pool500_method_contract",
        "candidate_pool_size": 500,
        "canonical_sources": sorted(CANONICAL_SOURCES),
        "train_inputs": _compact(batch0_inventory["train_only_inputs"]),
        "evaluation_only_inputs": _compact(batch0_inventory["evaluation_only_inputs"]),
        "pool1000_artifact": False,
        "pool1000_ready": False,
        "pool1000_readiness_peer": False,
        "ranking_input_replacement": False,
        "promote_to_ranking_input": False,
        "legacy_reference_signature_pass_authority": False,
        "candidate_generation_executed": False,
        "model_training_executed": False,
    }


def build_batch1_index_manifest(batch0_inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.batch1_index_manifest",
        "batch": 1,
        "role": "full_data_pool500_index_contract",
        "index_scope": "FULL_DERIVED_INDEX",
        "inputs": _compact(batch0_inventory["train_only_inputs"]),
        "candidate_generation_executed": False,
        "candidate_output_manifest": None,
        "pool1000_artifact": False,
        "pool1000_ready": False,
    }


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _compact(values: list[Any]) -> list[str]:
    return [str(value) for value in values if value]


def main() -> None:
    args = parse_args()
    manifest = run_full_data_pool500_batch01_dry_run(
        clean_manifest_path=Path(args.clean_manifest),
        lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
        output_dir=Path(args.output_dir),
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(json.dumps({"status": manifest["status"], "decision": manifest["decision"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
