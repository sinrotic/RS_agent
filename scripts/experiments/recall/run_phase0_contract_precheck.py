from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json

SCHEMA_VERSION = "phase0_contract_precheck_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "phase0_contract_precheck"
DEFAULT_CLEAN_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_LIGHTWEIGHT_VIEWS_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight"
DEFAULT_BASELINE_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "lightweight_representative_e2e"
DEFAULT_ITEMCF_SIDECAR_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "bounded_itemcf_covisit_sidecar_representative"
DEFAULT_GRAPH_CONFIG = ROOT / "configs" / "recall" / "phase_1_19" / "phase_1_19_graph_walk_seed_deepwalk_full_safe.yaml"
DEFAULT_TWO_TOWER_CONFIG = ROOT / "configs" / "recall" / "phase_1_18" / "phase_1_18_two_tower_seed_pool100_full_safe.yaml"
DEFAULT_RANKING_POOL200_CONFIG = ROOT / "configs" / "ranking" / "phase_1_25" / "phase_1_25_pool200_same_run_baseline_full_safe.yaml"
MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
)
FORBIDDEN_HOLDOUT_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
LIGHTWEIGHT_VIEW_FILES = (
    "manifest.json",
    "stats.json",
    "popular_recall.jsonl",
    "category_recall_items.jsonl",
    "category_top_items.jsonl",
    "semantic_recall_inputs.jsonl",
    "semantic_inverted_index.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Phase 0 recall-method contract precheck artifacts.")
    parser.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    parser.add_argument("--full-lightweight-views-dir", default=str(DEFAULT_LIGHTWEIGHT_VIEWS_DIR))
    parser.add_argument("--lightweight-representative-baseline-dir", default=str(DEFAULT_BASELINE_DIR))
    parser.add_argument("--bounded-itemcf-covisit-sidecar-dir", default=str(DEFAULT_ITEMCF_SIDECAR_DIR))
    parser.add_argument("--graph-config-file", default=str(DEFAULT_GRAPH_CONFIG))
    parser.add_argument("--two-tower-config-file", default=str(DEFAULT_TWO_TOWER_CONFIG))
    parser.add_argument("--ranking-pool200-config-file", default=str(DEFAULT_RANKING_POOL200_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase0_contract_precheck(
    *,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    full_lightweight_views_dir: Path = DEFAULT_LIGHTWEIGHT_VIEWS_DIR,
    lightweight_representative_baseline_dir: Path = DEFAULT_BASELINE_DIR,
    bounded_itemcf_covisit_sidecar_dir: Path = DEFAULT_ITEMCF_SIDECAR_DIR,
    graph_config_file: Path = DEFAULT_GRAPH_CONFIG,
    two_tower_config_file: Path = DEFAULT_TWO_TOWER_CONFIG,
    ranking_pool200_config_file: Path = DEFAULT_RANKING_POOL200_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    run_id = created_at.replace(":", "").replace("+", "Z")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    disk_root = _existing_ancestor(output_dir.parent)
    disk_free_bytes_start = shutil.disk_usage(disk_root).free
    read_files: list[str] = []
    failures: list[str] = []

    clean_dir = clean_dir.resolve()
    full_lightweight_views_dir = full_lightweight_views_dir.resolve()
    lightweight_representative_baseline_dir = lightweight_representative_baseline_dir.resolve()
    bounded_itemcf_covisit_sidecar_dir = bounded_itemcf_covisit_sidecar_dir.resolve()
    graph_config_file = graph_config_file.resolve()
    two_tower_config_file = two_tower_config_file.resolve()
    ranking_pool200_config_file = ranking_pool200_config_file.resolve()

    project_venv_enforced = enforce_venv and _is_project_venv_python()
    if enforce_venv and not project_venv_enforced:
        failures.append(f"Project .venv Python is required, got {sys.executable}")
    if disk_free_bytes_start < min_free_bytes:
        failures.append(f"D disk free bytes below threshold: {disk_free_bytes_start} < {min_free_bytes}")

    no_10k_source = True
    for label, path in {
        "full_clean_dir": clean_dir,
        "full_lightweight_views_dir": full_lightweight_views_dir,
        "lightweight_representative_baseline": lightweight_representative_baseline_dir,
        "bounded_itemcf_covisit_sidecar": bounded_itemcf_covisit_sidecar_dir,
    }.items():
        if _has_forbidden_10k_part(path):
            no_10k_source = False
            failures.append(f"{label} uses forbidden 10k path: {path}")

    full_clean_status = _require_dir(clean_dir, failures, "full_clean_dir")
    full_lightweight_status = _require_dir(full_lightweight_views_dir, failures, "full_lightweight_views_dir")
    baseline_status = _require_dir(lightweight_representative_baseline_dir, failures, "lightweight_representative_baseline")
    sidecar_status = _require_dir(bounded_itemcf_covisit_sidecar_dir, failures, "bounded_itemcf_covisit_sidecar")

    required_clean_files = {
        "user_sequences_train": clean_dir / "user_sequences.train.jsonl",
        "canonical_interactions_train": clean_dir / "canonical_interactions.train.jsonl",
        "canonical_items": clean_dir / "canonical_items.jsonl",
        "manifest": clean_dir / "manifest.json",
        "stats": clean_dir / "stats.json",
    }
    clean_input_records = _resolve_file_records(required_clean_files, failures, read_files)
    lightweight_view_records = _resolve_file_records(
        {name: full_lightweight_views_dir / name for name in LIGHTWEIGHT_VIEW_FILES}, failures, read_files
    )
    baseline_records = _resolve_file_records(
        {
            "manifest": lightweight_representative_baseline_dir / "manifest.json",
            "source_audit": lightweight_representative_baseline_dir / "source_audit.json",
            "candidates": lightweight_representative_baseline_dir / "candidates.jsonl",
        },
        failures,
        read_files,
    )
    sidecar_records = _resolve_file_records(
        {
            "manifest": bounded_itemcf_covisit_sidecar_dir / "manifest.json",
            "source_audit": bounded_itemcf_covisit_sidecar_dir / "source_audit.json",
        },
        failures,
        read_files,
    )
    graph_config = _resolve_config_file(graph_config_file, failures, read_files, "phase4_graph_config_file")
    two_tower_config = _resolve_config_file(two_tower_config_file, failures, read_files, "phase5_two_tower_config_file")
    ranking_pool200_config = _resolve_config_file(ranking_pool200_config_file, failures, read_files, "ranking_pool200_config_file")

    baseline_manifest = _read_optional_json(baseline_records["manifest"].get("path"), read_files)
    sidecar_manifest = _read_optional_json(sidecar_records["manifest"].get("path"), read_files)
    lightweight_manifest = _read_optional_json(lightweight_view_records["manifest.json"].get("path"), read_files)

    recall_promotion_gate = {
        "scope": "recall_candidate_generation_only",
        "status": "PASS" if not failures and baseline_status == "READY" and sidecar_status == "READY" else "BLOCKED_MISSING_ARTIFACT",
        "baseline_sources": baseline_manifest.get("enabled_sources", []),
        "sidecar_schema_version": sidecar_manifest.get("schema_version"),
        "does_not_promote_ranking_input": True,
    }
    ranking_frozen_pool200_gate = {
        "scope": "ranking_frozen_pool200_only",
        "status": "PASS" if ranking_pool200_config.get("status") == "READY" else "BLOCKED_MISSING_ARTIFACT",
        "config_file": ranking_pool200_config.get("path"),
        "config_sha256": ranking_pool200_config.get("sha256"),
        "separate_from_recall_promotion_gate": True,
        "pool500_pool1000_cannot_replace_pool200": True,
    }

    phase2_usercf_inputs = _phase_inputs(
        "phase2_usercf_inputs",
        [clean_input_records["user_sequences_train"], clean_input_records["canonical_interactions_train"]],
    )
    phase3_swing_inputs = _phase_inputs(
        "phase3_swing_inputs",
        [clean_input_records["user_sequences_train"], clean_input_records["canonical_interactions_train"]],
    )
    phase3_sequence_inputs = _phase_inputs(
        "phase3_sequence_inputs",
        [clean_input_records["user_sequences_train"]],
    )
    phase4_mf_inputs = _phase_inputs(
        "phase4_mf_inputs",
        [clean_input_records["canonical_interactions_train"], clean_input_records["canonical_items"]],
    )
    phase5_pool_readiness_inputs = {
        "status": "READY" if baseline_records["candidates"].get("status") == "READY" else "BLOCKED_MISSING_ARTIFACT",
        "frozen_pool200_candidate_source": baseline_records["candidates"],
        "pool500_status": "READINESS_ONLY_NOT_RANKING_INPUT",
        "pool1000_status": "READINESS_ONLY_NOT_RANKING_INPUT",
        "ranking_gate": "Use ranking_frozen_pool200_gate, not recall_promotion_gate.",
    }

    has_scope_drift = not no_10k_source or graph_config.get("status") == "INVALID_SCOPE_DRIFT" or two_tower_config.get("status") == "INVALID_SCOPE_DRIFT" or ranking_pool200_config.get("status") == "INVALID_SCOPE_DRIFT"
    status = "PASS" if not failures else ("INVALID_SCOPE_DRIFT" if has_scope_drift else "BLOCKED_MISSING_ARTIFACT")
    failure_reason = None if not failures else "; ".join(failures)
    resolved_inputs = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_reason": failure_reason,
        "full_clean_dir": {"path": str(clean_dir), "status": full_clean_status, "files": clean_input_records},
        "full_lightweight_views_dir": {
            "path": str(full_lightweight_views_dir),
            "status": full_lightweight_status,
            "files": lightweight_view_records,
            "manifest_mode": lightweight_manifest.get("mode"),
        },
        "lightweight_representative_baseline": {
            "path": str(lightweight_representative_baseline_dir),
            "status": baseline_status,
            "files": baseline_records,
        },
        "bounded_itemcf_covisit_sidecar": {
            "path": str(bounded_itemcf_covisit_sidecar_dir),
            "status": sidecar_status,
            "files": sidecar_records,
        },
        "phase2_usercf_inputs": phase2_usercf_inputs,
        "phase3_swing_inputs": phase3_swing_inputs,
        "phase3_sequence_inputs": phase3_sequence_inputs,
        "phase4_graph_config_file": graph_config.get("path"),
        "phase4_graph_config_hash": graph_config.get("sha256"),
        "phase4_graph_config_status": graph_config.get("status"),
        "phase4_mf_inputs": phase4_mf_inputs,
        "phase5_two_tower_config_file": two_tower_config.get("path"),
        "phase5_two_tower_config_hash": two_tower_config.get("sha256"),
        "phase5_two_tower_config_status": two_tower_config.get("status"),
        "phase5_pool_readiness_inputs": phase5_pool_readiness_inputs,
    }

    holdout_contract = {
        "status": "PASS",
        "candidate_generation_uses_holdout": False,
        "allowed_source_files": [
            "user_sequences.train.jsonl",
            "canonical_interactions.train.jsonl",
            "canonical_items.jsonl",
            *LIGHTWEIGHT_VIEW_FILES,
        ],
        "forbidden_source_files": list(FORBIDDEN_HOLDOUT_FILES),
    }
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "read_files": sorted(set(read_files)),
        "allowed_candidate_generation_inputs": [
            str(clean_dir / "user_sequences.train.jsonl"),
            str(clean_dir / "canonical_interactions.train.jsonl"),
            str(clean_dir / "canonical_items.jsonl"),
            *(str(full_lightweight_views_dir / name) for name in LIGHTWEIGHT_VIEW_FILES),
            str(lightweight_representative_baseline_dir / "manifest.json"),
            str(bounded_itemcf_covisit_sidecar_dir / "manifest.json"),
        ],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_HOLDOUT_FILES],
        "evaluation_only_inputs": [
            str(clean_dir / "canonical_interactions.valid.jsonl"),
            str(clean_dir / "canonical_interactions.test.jsonl"),
        ],
        "train_only": True,
        "no_10k_source": no_10k_source,
        "holdout_contract": holdout_contract,
    }

    disabled_outputs = {
        "execute_phase2_usercf": True,
        "execute_phase3_swing": True,
        "execute_phase3_sequence": True,
        "execute_phase4_graph": True,
        "execute_phase4_mf": True,
        "execute_phase5_two_tower": True,
        "pool500_as_ranking_input": True,
        "pool1000_as_ranking_input": True,
        "valid_test_holdout_candidate_reads": True,
    }
    required_artifacts = {
        "resolved_inputs": str(output_dir / "resolved_inputs.json"),
        "source_audit": str(output_dir / "source_audit.json"),
        "manifest": str(output_dir / "manifest.json"),
    }
    disk_free_bytes_end = shutil.disk_usage(disk_root).free
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "status": status,
        "train_only": True,
        "project_venv_enforced": project_venv_enforced,
        "disk_free_bytes_start": disk_free_bytes_start,
        "disk_free_bytes_end": disk_free_bytes_end,
        "min_free_bytes": min_free_bytes,
        "recall_promotion_gate": recall_promotion_gate,
        "ranking_frozen_pool200_gate": ranking_frozen_pool200_gate,
        "required_artifacts": required_artifacts,
        "disabled_outputs": disabled_outputs,
        "failure_reason": failure_reason,
        "downgrade_action": None if status == "PASS" else "Do not execute downstream phases; resolve blocked inputs first.",
    }

    write_json(output_dir / "resolved_inputs.json", resolved_inputs)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    return current


def _is_project_venv_python() -> bool:
    executable = Path(sys.executable).resolve()
    expected = (ROOT / ".venv").resolve()
    try:
        executable.relative_to(expected)
        return True
    except ValueError:
        return False


def _has_forbidden_10k_part(path: Path) -> bool:
    lowered = str(path).replace("\\", "/").lower()
    return any(part in lowered for part in FORBIDDEN_PATH_PARTS)


def _require_dir(path: Path, failures: list[str], label: str) -> str:
    if _has_forbidden_10k_part(path):
        return "INVALID_SCOPE_DRIFT"
    if not path.is_dir():
        failures.append(f"{label} directory is missing: {path}")
        return "BLOCKED_MISSING_ARTIFACT"
    return "READY"


def _resolve_file_records(paths: dict[str, Path], failures: list[str], read_files: list[str]) -> dict[str, dict[str, Any]]:
    return {name: _file_record(path, failures, read_files, name) for name, path in paths.items()}


def _resolve_config_file(path: Path, failures: list[str], read_files: list[str], label: str) -> dict[str, Any]:
    if path.is_dir():
        failures.append(f"{label} must be a concrete file, got directory: {path}")
        return {"path": str(path), "status": "INVALID_SCOPE_DRIFT", "failure_reason": "directory_not_file"}
    record = _file_record(path, failures, read_files, label)
    if record.get("status") != "READY":
        return record
    config = _read_json_without_audit(path)
    forbidden_values = _forbidden_config_references(config)
    if forbidden_values:
        failures.append(f"{label} config references forbidden 10k paths: {', '.join(forbidden_values)}")
        return {
            **record,
            "status": "INVALID_SCOPE_DRIFT",
            "failure_reason": "config_references_forbidden_10k_path",
            "forbidden_references": forbidden_values,
        }
    return record


def _file_record(path: Path, failures: list[str], read_files: list[str], label: str) -> dict[str, Any]:
    if _has_forbidden_10k_part(path):
        failures.append(f"{label} uses forbidden 10k path: {path}")
        return {"path": str(path), "status": "INVALID_SCOPE_DRIFT", "failure_reason": "forbidden_10k_path"}
    if not path.is_file() or path.stat().st_size == 0:
        failures.append(f"{label} file is missing or empty: {path}")
        return {"path": str(path), "status": "BLOCKED_MISSING_ARTIFACT", "failure_reason": "missing_or_empty"}
    read_files.append(str(path))
    return {
        "path": str(path),
        "status": "READY",
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _read_json_without_audit(path: Path) -> dict[str, Any]:
    try:
        return read_json(path)
    except Exception:
        return {}


def _forbidden_config_references(value: Any) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            matches.extend(_forbidden_config_references(child))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_forbidden_config_references(child))
    elif isinstance(value, str) and _has_forbidden_10k_part(Path(value)):
        matches.append(value)
    return sorted(set(matches))


def _read_optional_json(path_text: Any, read_files: list[str]) -> dict[str, Any]:
    if not path_text:
        return {}
    path = Path(str(path_text))
    if not path.is_file():
        return {}
    read_files.append(str(path))
    try:
        return read_json(path)
    except Exception:
        return {}


def _phase_inputs(label: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    status = "READY" if all(record.get("status") == "READY" for record in records) else "BLOCKED_MISSING_ARTIFACT"
    payload: dict[str, Any] = {"status": status, "inputs": records}
    if status != "READY":
        payload["failure_reason"] = f"{label} has unresolved required train-only inputs"
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    manifest = run_phase0_contract_precheck(
        clean_dir=Path(args.clean_dir),
        full_lightweight_views_dir=Path(args.full_lightweight_views_dir),
        lightweight_representative_baseline_dir=Path(args.lightweight_representative_baseline_dir),
        bounded_itemcf_covisit_sidecar_dir=Path(args.bounded_itemcf_covisit_sidecar_dir),
        graph_config_file=Path(args.graph_config_file),
        two_tower_config_file=Path(args.two_tower_config_file),
        ranking_pool200_config_file=Path(args.ranking_pool200_config_file),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(f"Phase 0 contract precheck status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
