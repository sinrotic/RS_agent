from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from scripts.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _enforce_project_venv, _existing_ancestor, _file_signature

SCHEMA_VERSION = "pool500_all_methods_custom_index_v1"
DEFAULT_CLEAN_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_SOURCE_POOL500_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "custom_index"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_PATH_PARTS = ("amazon_2023_recall_clean_10000", "amazon_2023_recall_views_10000")
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build representative pool500 custom indexes for all-method recall probes.")
    parser.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    parser.add_argument("--source-pool500-dir", default=str(DEFAULT_SOURCE_POOL500_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def build_pool500_all_methods_custom_index(
    *,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    source_pool500_dir: Path = DEFAULT_SOURCE_POOL500_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()

    clean_dir = clean_dir.resolve()
    source_pool500_dir = source_pool500_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck(clean_dir, source_pool500_dir, output_dir, min_free_bytes, overwrite)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free

    sample = _read_json(source_pool500_dir / "representative_user_sample.json")
    source_manifest = _read_json(source_pool500_dir / "manifest.json")
    user_ids = [str(user_id) for user_id in sample.get("user_ids", [])]
    if len(user_ids) != 500:
        raise ValueError(f"Representative user sample must contain exactly 500 users, got {len(user_ids)}")
    user_id_set = set(user_ids)
    user_to_index = {user_id: index for index, user_id in enumerate(user_ids)}

    sequence_rows = _load_representative_train_sequences(clean_dir / "user_sequences.train.jsonl", user_id_set)
    missing_users = sorted(user_id_set.difference(sequence_rows))
    if missing_users:
        raise ValueError(f"Missing representative users in train sequences: {missing_users[:5]}")

    candidate_path = source_pool500_dir / "pool500_recall_only" / "candidates.jsonl"
    item_counter: Counter[str] = Counter()
    candidate_row_count = 0
    candidate_users: set[str] = set()
    candidate_sources: Counter[str] = Counter()
    for row in iter_jsonl(candidate_path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if not user_id or user_id not in user_id_set or not item_id:
            continue
        candidate_row_count += 1
        candidate_users.add(user_id)
        item_counter[item_id] += 1
        for source in row.get("sources", []) or []:
            candidate_sources[str(source)] += 1

    train_item_counter: Counter[str] = Counter()
    train_event_count = 0
    positive_event_count = 0
    strong_positive_event_count = 0
    sequence_lengths: list[int] = []
    indexed_sequence_path = output_dir / "indexed_train_sequences.jsonl"
    with indexed_sequence_path.open("w", encoding="utf-8") as handle:
        for user_id in user_ids:
            row = sequence_rows[user_id]
            sequence = [str(item_id) for item_id in row.get("recent_item_sequence", []) or [] if item_id]
            positives = [str(item_id) for item_id in row.get("recent_positive_item_sequence", []) or [] if item_id]
            strong_positives = [str(item_id) for item_id in row.get("recent_strong_positive_item_sequence", []) or [] if item_id]
            train_item_counter.update(sequence)
            item_counter.update(sequence)
            train_event_count += len(sequence)
            positive_event_count += len(positives)
            strong_positive_event_count += len(strong_positives)
            sequence_lengths.append(len(sequence))
            record = {
                "user_index": user_to_index[user_id],
                "user_id": user_id,
                "item_ids": sequence,
                "timestamps": row.get("recent_timestamp_sequence", []) or [],
                "positive_item_ids": positives,
                "positive_timestamps": row.get("recent_positive_timestamp_sequence", []) or [],
                "strong_positive_item_ids": strong_positives,
                "strong_positive_timestamps": row.get("recent_strong_positive_timestamp_sequence", []) or [],
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    item_ids = sorted(item_counter)
    item_to_index = {item_id: index for index, item_id in enumerate(item_ids)}
    custom_user_index = {
        "schema_version": SCHEMA_VERSION,
        "user_count": len(user_ids),
        "selection": sample.get("selection"),
        "users": [{"user_index": index, "user_id": user_id} for user_id, index in user_to_index.items()],
    }
    custom_item_index = {
        "schema_version": SCHEMA_VERSION,
        "item_count": len(item_ids),
        "candidate_unique_item_count": len([item_id for item_id, count in item_counter.items() if count > train_item_counter.get(item_id, 0)]),
        "train_unique_item_count": len(train_item_counter),
        "items": [
            {
                "item_index": item_to_index[item_id],
                "item_id": item_id,
                "train_occurrence_count": train_item_counter.get(item_id, 0),
                "pool500_occurrence_count": item_counter[item_id] - train_item_counter.get(item_id, 0),
            }
            for item_id in item_ids
        ],
    }
    representative_sample = {
        **sample,
        "source_representative_sample_path": str(source_pool500_dir / "representative_user_sample.json"),
        "source_manifest_path": str(source_pool500_dir / "manifest.json"),
        "custom_index_output_dir": str(output_dir),
    }

    resolved_inputs = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "clean_dir": {"path": str(clean_dir), "manifest": str(clean_dir / "manifest.json")},
        "source_pool500_dir": {"path": str(source_pool500_dir), "manifest_status": source_manifest.get("status")},
        "train_sequences": str(clean_dir / "user_sequences.train.jsonl"),
        "pool500_candidates": str(candidate_path),
        "representative_user_sample": str(source_pool500_dir / "representative_user_sample.json"),
        "output_dir": str(output_dir),
    }
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_index_build": True,
        "candidate_generation_uses_holdout": False,
        "candidate_generation_read_files": [str(clean_dir / "user_sequences.train.jsonl"), str(candidate_path)],
        "evaluation_only_read_files": [],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "no_10k_source": True,
        "no_full_clean_copy": True,
        "ranking_isolation": {
            "ranking_default_input_modified": False,
            "pool500_as_ranking_input": False,
            "pool1000_generated": False,
        },
        "source_signatures": {
            "train_sequences": _file_signature(clean_dir / "user_sequences.train.jsonl"),
            "source_pool500_manifest": _file_signature(source_pool500_dir / "manifest.json"),
            "source_representative_user_sample": _file_signature(source_pool500_dir / "representative_user_sample.json"),
            "pool500_candidates": _file_signature(candidate_path),
        },
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "min_free_bytes": min_free_bytes,
        "bounded_user_count": len(user_ids),
        "bounded_item_count": len(item_ids),
        "train_event_count": train_event_count,
        "positive_event_count": positive_event_count,
        "strong_positive_event_count": strong_positive_event_count,
        "pool500_candidate_row_count": candidate_row_count,
        "pool500_candidate_user_count": len(candidate_users),
        "candidate_source_counts": dict(sorted(candidate_sources.items())),
    }

    write_json(output_dir / "representative_user_sample.json", representative_sample)
    write_json(output_dir / "custom_user_index.json", custom_user_index)
    write_json(output_dir / "custom_item_index.json", custom_item_index)
    write_json(output_dir / "resolved_inputs.json", resolved_inputs)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "pool500_all_methods_representative_custom_index_recall_only",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "source_pool500_status": source_manifest.get("status"),
        "representative_user_count": len(user_ids),
        "custom_item_count": len(item_ids),
        "indexed_train_sequence_rows": len(user_ids),
        "pool500_candidate_row_count": candidate_row_count,
        "sequence_length_summary": _summary(sequence_lengths),
        "train_only_index_build": True,
        "candidate_generation_uses_holdout": False,
        "disabled_outputs": {
            "pool1000": True,
            "model_training": True,
            "two_tower_training": True,
            "graph_training": True,
            "mf_training": True,
            "ranking": True,
        },
        "required_artifacts": {
            "representative_user_sample": str(output_dir / "representative_user_sample.json"),
            "custom_user_index": str(output_dir / "custom_user_index.json"),
            "custom_item_index": str(output_dir / "custom_item_index.json"),
            "indexed_train_sequences": str(indexed_sequence_path),
            "resolved_inputs": str(output_dir / "resolved_inputs.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "artifact_signatures": {
            "indexed_train_sequences": _file_signature(indexed_sequence_path),
            "custom_user_index": _file_signature(output_dir / "custom_user_index.json"),
            "custom_item_index": _file_signature(output_dir / "custom_item_index.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _precheck(clean_dir: Path, source_pool500_dir: Path, output_dir: Path, min_free_bytes: int, overwrite: bool) -> None:
    for path in (clean_dir, source_pool500_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k path for pool500 custom index: {path}")
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    required = [
        clean_dir / "manifest.json",
        clean_dir / "user_sequences.train.jsonl",
        source_pool500_dir / "manifest.json",
        source_pool500_dir / "representative_user_sample.json",
        source_pool500_dir / "pool500_recall_only" / "candidates.jsonl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(missing))
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_representative_train_sequences(sequence_path: Path, user_id_set: set[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(sequence_path):
        user_id = str(row.get("user_id", ""))
        if user_id in user_id_set:
            rows[user_id] = row
            if len(rows) == len(user_id_set):
                break
    return rows


def _summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "max": 0, "avg": 0.0}
    return {"min": min(values), "max": max(values), "avg": round(sum(values) / len(values), 6)}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    manifest = build_pool500_all_methods_custom_index(
        clean_dir=Path(args.clean_dir),
        source_pool500_dir=Path(args.source_pool500_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(f"Pool500 all-methods custom index status: {manifest['status']}")
    print(f"Output dir: {manifest['output_dir']}")


if __name__ == "__main__":
    main()
