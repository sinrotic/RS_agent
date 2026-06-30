from __future__ import annotations

import argparse
import hashlib
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
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "full_semantic_title_category_expansion_manifest_v1"
SOURCE = "semantic_title_category_expansion"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_semantic_title_category_expansion"
FORBIDDEN_INPUT_FILENAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_PATH_TOKENS = {
    "holdout",
    "pool1000",
    "pool_1000",
    "pool-1000",
    "pool1000_candidates",
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "recall_clean_10k",
    "recall_views_10k",
    "diagnostic_batch",
    "batch01",
    "batch_01",
}
FORBIDDEN_RANKING_KEYS = {
    "ranking_input_replacement_allowed",
    "ranking_default_input_modified",
    "pool500_as_ranking_input",
    "ranking_output_path",
    "ranked_candidates_path",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Declare the full semantic title-category expansion source index manifest.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--lightweight-views-manifest", default=str(DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_full_semantic_title_category_manifest(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)

    clean_manifest_path = clean_manifest_path.resolve()
    lightweight_views_manifest_path = lightweight_views_manifest_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    _reject_ranking_replacement(clean_manifest, "clean_manifest")
    _reject_ranking_replacement(views_manifest, "lightweight_views_manifest")

    canonical_items_path = _resolve_required_manifest_path(clean_manifest_path, clean_manifest, "canonical_items_path")
    outputs = views_manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("Lightweight views manifest must contain an outputs object.")
    semantic_recall_inputs_path = _resolve_required_output_path(lightweight_views_manifest_path, outputs, "semantic_recall_inputs")
    semantic_inverted_index_path = _resolve_required_output_path(lightweight_views_manifest_path, outputs, "semantic_inverted_index")

    declared_inputs = [
        clean_manifest_path,
        lightweight_views_manifest_path,
        canonical_items_path,
        semantic_recall_inputs_path,
        semantic_inverted_index_path,
    ]
    no_holdout_audit = _no_holdout_audit(declared_inputs)
    if no_holdout_audit["status"] != "PASS":
        write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
        raise ValueError("Forbidden semantic manifest input: " + ", ".join(no_holdout_audit["forbidden_inputs"]))

    signatures = {
        "canonical_items": _file_signature(canonical_items_path),
        "semantic_recall_inputs": _file_signature(semantic_recall_inputs_path),
        "semantic_inverted_index": _file_signature(semantic_inverted_index_path),
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "index_scope": "FULL_DERIVED_INDEX",
        "loader_mode": "full_manifest_declared",
        "diagnostic_only": False,
        "diagnostic_batch_rows_promoted_to_full_ready": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "declared_input_paths": [str(path) for path in declared_inputs],
        "source_signatures": signatures,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "index_scope": "FULL_DERIVED_INDEX",
        "canonical_items_path": str(canonical_items_path),
        "semantic_recall_inputs_path": str(semantic_recall_inputs_path),
        "semantic_inverted_index_path": str(semantic_inverted_index_path),
        "canonical_items_sha256": signatures["canonical_items"]["sha256"],
        "semantic_recall_inputs_sha256": signatures["semantic_recall_inputs"]["sha256"],
        "semantic_inverted_index_sha256": signatures["semantic_inverted_index"]["sha256"],
        "loader_mode": "full_manifest_declared",
        "diagnostic_only": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "full_ready_declared": False,
        "ranking_input_replacement_declared": False,
        "output_files": {
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
        },
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    write_json(output_dir / "source_index_manifest.json", manifest)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    return manifest


def _resolve_required_manifest_path(manifest_path: Path, manifest: dict[str, Any], key: str) -> Path:
    value = manifest.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Clean manifest missing required {key}.")
    return _resolve_existing_path(manifest_path, value)


def _resolve_required_output_path(manifest_path: Path, outputs: dict[str, Any], key: str) -> Path:
    value = outputs.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Lightweight views manifest missing required outputs.{key}.")
    return _resolve_existing_path(manifest_path, value)


def _resolve_existing_path(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    candidates = [path] if path.is_absolute() else [ROOT / path, manifest_path.parent / path]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(f"Required manifest input does not exist: {raw_path}")


def _reject_ranking_replacement(payload: dict[str, Any], label: str) -> None:
    stack: list[tuple[str, Any]] = [(label, payload)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key, nested in value.items():
                next_path = f"{path}.{key}"
                if key in FORBIDDEN_RANKING_KEYS and nested:
                    raise ValueError(f"Ranking replacement marker is forbidden in {next_path}.")
                stack.append((next_path, nested))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                stack.append((f"{path}[{index}]", nested))


def _no_holdout_audit(paths: list[Path]) -> dict[str, Any]:
    forbidden_inputs: list[str] = []
    for path in paths:
        normalized = str(path).replace("\\", "/").lower()
        if path.name in FORBIDDEN_INPUT_FILENAMES or any(token in normalized for token in FORBIDDEN_PATH_TOKENS):
            forbidden_inputs.append(str(path))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not forbidden_inputs else "BLOCKED",
        "candidate_generation_uses_holdout": bool(forbidden_inputs),
        "train_only_index_build": not forbidden_inputs,
        "forbidden_inputs": forbidden_inputs,
        "declared_inputs": [str(path) for path in paths],
        "no_10k_source": not any(_contains_token(path, ("10000", "10k")) for path in paths),
        "pool1000_allowed": False,
        "ranking_input_replacement_allowed": False,
    }


def _contains_token(path: Path, tokens: tuple[str, ...]) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(token in normalized for token in tokens)


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            rows += chunk.count(b"\n")
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "row_count": rows if path.suffix == ".jsonl" else None,
        "sha256": digest.hexdigest(),
    }


def main() -> None:
    args = parse_args()
    manifest = build_full_semantic_title_category_manifest(
        clean_manifest_path=Path(args.clean_manifest),
        lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
        output_dir=Path(args.output_dir),
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(f"Semantic title-category manifest status: {manifest['status']}")
    print(f"Output dir: {Path(manifest['output_files']['source_index_manifest']).parent}")


if __name__ == "__main__":
    main()
