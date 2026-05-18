from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    DEFAULT_PHASE0_DIR,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _read_json,
)

SCHEMA_VERSION = "phase4_graph_mf_contract_validation_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "graph_mf_contract_validation"
DEFAULT_MF_CONFIG = ROOT / "configs" / "recall" / "phase_1_21" / "phase_1_21_recall_coverage_mf.yaml"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_PATH_PARTS = ("amazon_2023_recall_clean_10000", "amazon_2023_recall_views_10000")
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
ALLOWED_STATES = {"EXECUTED_PASS_CONTRACT_ONLY", "blocked", "deferred"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Phase 4 graph and MF contracts without training or promotion.")
    parser.add_argument("--phase0-dir", default=str(DEFAULT_PHASE0_DIR))
    parser.add_argument("--mf-config", default=str(DEFAULT_MF_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase4_graph_mf_contract_validation(
    *,
    phase0_dir: Path = DEFAULT_PHASE0_DIR,
    mf_config: Path = DEFAULT_MF_CONFIG,
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
        raise RuntimeError(f"Phase 0 must PASS before Phase 4, got {phase0_manifest.get('status')}")

    graph_config = Path(phase0_resolved["phase4_graph_config_file"]).resolve()
    mf_config = mf_config.resolve()
    graph_config_payload = _read_config(graph_config)
    mf_config_payload = _read_config(mf_config)
    clean_dir = Path(phase0_resolved["full_clean_dir"]["path"]).resolve()
    graph_inputs = [Path(item["path"]).resolve() for item in phase0_resolved["phase3_swing_inputs"]["inputs"]]
    mf_inputs = [Path(item["path"]).resolve() for item in phase0_resolved["phase4_mf_inputs"]["inputs"]]

    failures = []
    for label, path in {"graph_config": graph_config, "mf_config": mf_config}.items():
        if _has_forbidden_path_part(path):
            failures.append(f"{label} path references forbidden 10k source: {path}")
    for label, payload in {"graph_config": graph_config_payload, "mf_config": mf_config_payload}.items():
        forbidden = _forbidden_config_references(payload)
        if forbidden:
            failures.append(f"{label} references forbidden 10k paths: {', '.join(forbidden)}")
    for path in [*graph_inputs, *mf_inputs]:
        if _has_forbidden_path_part(path):
            failures.append(f"input references forbidden 10k source: {path}")
        if path.name in FORBIDDEN_CANDIDATE_FILES:
            failures.append(f"input is forbidden candidate-generation file: {path}")

    graph_contract = {
        "status": "PASS" if not failures else "BLOCKED",
        "config_file": str(graph_config),
        "config_signature": _file_signature(graph_config),
        "config_strategy_name": graph_config_payload.get("strategy_name") or graph_config_payload.get("phase"),
        "graph_walk_seed_enabled": bool(graph_config_payload.get("graph_walk_seed_enabled", False)),
        "training_disabled": True,
        "promotion_disabled": True,
        "ranking_default_input_disabled": True,
        "inputs": [_file_signature(path) for path in graph_inputs],
    }
    mf_contract = {
        "status": "PASS" if not failures else "BLOCKED",
        "config_file": str(mf_config),
        "config_signature": _file_signature(mf_config),
        "enabled_methods": [
            key.removesuffix("_enabled")
            for key, value in sorted(mf_config_payload.items())
            if key.endswith("_enabled") and _as_bool(value)
        ],
        "training_disabled": True,
        "promotion_disabled": True,
        "ranking_default_input_disabled": True,
        "inputs": [_file_signature(path) for path in mf_inputs],
    }
    direct_10k_paths = any(_has_forbidden_path_part(path) for path in [graph_config, mf_config, *graph_inputs, *mf_inputs])
    config_10k_references = bool(_forbidden_config_references(graph_config_payload) or _forbidden_config_references(mf_config_payload))
    status = "EXECUTED_PASS_CONTRACT_ONLY" if not failures else "blocked"
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "graph_contract": graph_contract,
        "mf_contract": mf_contract,
        "contract_only": True,
        "no_model_training_executed": True,
        "candidate_generation_uses_holdout": False,
        "evaluation_only": {"read_files": [], "contract": "Phase 4 validates graph/MF readiness only and does not evaluate against valid/test."},
    }
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "BLOCKED",
        "train_only_candidate_generation": True,
        "contract_only_no_candidate_generation": True,
        "candidate_generation_read_files": [str(graph_config), str(mf_config), *[str(path) for path in graph_inputs], *[str(path) for path in mf_inputs]],
        "evaluation_only_read_files": [],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "candidate_generation_uses_holdout": False,
        "no_10k_source": not direct_10k_paths and not config_10k_references,
        "disabled_outputs": {"graph_walk_training": True, "mf_training": True, "pool500": True, "pool1000": True, "ranking_default_input": True},
    }

    output_dir.mkdir(parents=True)
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "graph_contract_validation.json", graph_contract)
    write_json(output_dir / "mf_contract_validation.json", mf_contract)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_reason": "contract_validation_failed" if failures else None,
        "downgrade_action": "do_not_train_or_promote_graph_mf" if failures else "record_contract_only_do_not_promote",
        "phase0_status": phase0_manifest.get("status"),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - start, 6),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "contract_only": True,
        "no_model_training_executed": True,
        "failures": failures,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "graph_contract_validation": str(output_dir / "graph_contract_validation.json"),
            "mf_contract_validation": str(output_dir / "mf_contract_validation.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _read_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _read_simple_yaml(text)
    return payload if isinstance(payload, dict) else {}


def _read_simple_yaml(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        value = raw_value.strip()
        payload[key.strip()] = _parse_scalar(value)
    return payload


def _parse_scalar(value: str) -> Any:
    if value in {"", "null", "None"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip('"\'')


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


def _has_forbidden_path_part(path: Path) -> bool:
    text = str(path).replace("\\", "/")
    return any(part in text for part in FORBIDDEN_PATH_PARTS)


def _forbidden_config_references(value: Any) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            matches.extend(_forbidden_config_references(child))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_forbidden_config_references(child))
    elif isinstance(value, str) and any(part in value.replace("\\", "/") for part in FORBIDDEN_PATH_PARTS):
        matches.append(value)
    return sorted(set(matches))


def main() -> None:
    args = parse_args()
    manifest = run_phase4_graph_mf_contract_validation(
        phase0_dir=Path(args.phase0_dir),
        mf_config=Path(args.mf_config),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    if manifest["status"] not in ALLOWED_STATES:
        raise RuntimeError(f"Unexpected Phase 4 state: {manifest['status']}")
    print(f"Phase 4 graph/MF contract validation status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
