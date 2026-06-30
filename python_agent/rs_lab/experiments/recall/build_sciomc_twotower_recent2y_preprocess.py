from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.workflow.two_tower_training import build_two_tower_item_vocab

SCHEMA_VERSION = "sciomc_twotower_recent2y_preprocess_v1"
DEFAULT_RECENT_WINDOW_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "manifest.json"
DEFAULT_FORMAL_ITEM_VOCAB_MANIFEST = ROOT / "outputs" / "recall" / "pool500_2y_sources" / "two_tower" / "item_vocab" / "two_tower_2y_item_vocab_minfreq1_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "processed" / "amazon_2023_sciomc_twotower_recent2y"
DEFAULT_SMOKE_USERS = 1000
DEFAULT_SEQUENCE_MAX_LEN = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build SciOMC TwoTower smoke/formal dataset packs from existing 2y recent-window data.")
    parser.add_argument("--recent-window-manifest", default=str(DEFAULT_RECENT_WINDOW_MANIFEST))
    parser.add_argument("--formal-item-vocab-manifest", default=str(DEFAULT_FORMAL_ITEM_VOCAB_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--smoke-users", type=int, default=DEFAULT_SMOKE_USERS)
    parser.add_argument("--sequence-max-len", type=int, default=DEFAULT_SEQUENCE_MAX_LEN)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_sciomc_twotower_recent2y_preprocess(
    *,
    recent_window_manifest_path: str | Path = DEFAULT_RECENT_WINDOW_MANIFEST,
    formal_item_vocab_manifest_path: str | Path = DEFAULT_FORMAL_ITEM_VOCAB_MANIFEST,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    smoke_users: int = DEFAULT_SMOKE_USERS,
    sequence_max_len: int = DEFAULT_SEQUENCE_MAX_LEN,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    if smoke_users <= 0:
        raise ValueError("smoke_users must be positive")

    manifest_path = Path(recent_window_manifest_path).resolve()
    output_path = Path(output_dir).resolve()
    formal_vocab_manifest_path = Path(formal_item_vocab_manifest_path).resolve()
    if output_path.exists() and any(output_path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_path}")
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    recent_manifest = _read_json(manifest_path)
    split_paths = _resolve_split_paths(manifest_path, recent_manifest)
    train_sequences_path = _resolve_path(manifest_path, str(recent_manifest["train_user_sequences_path"]))
    canonical_items_path = _resolve_path(manifest_path, str(recent_manifest["canonical_items_path"]))

    formal_dir = output_path / "formal"
    smoke_dir = output_path / "smoke"
    formal_dir.mkdir(parents=True, exist_ok=True)
    smoke_dir.mkdir(parents=True, exist_ok=True)

    smoke_sequence_rows, smoke_user_ids, smoke_sequence_stats = _select_smoke_sequences(train_sequences_path, smoke_users, sequence_max_len)
    smoke_interactions_path = smoke_dir / "canonical_interactions.train.jsonl"
    smoke_interaction_stats = _write_smoke_train_interactions(split_paths["train"], smoke_interactions_path, smoke_user_ids)
    smoke_items_path = smoke_dir / "canonical_items.jsonl"
    _write_smoke_items(canonical_items_path, smoke_items_path, smoke_interaction_stats["item_ids"])
    smoke_sequences_path = smoke_dir / "user_sequences.train.jsonl"
    write_jsonl(smoke_sequences_path, smoke_sequence_rows)

    smoke_vocab_path = smoke_dir / "two_tower_item_vocab_minfreq1.jsonl"
    smoke_vocab_manifest_path = smoke_dir / "two_tower_item_vocab_minfreq1_manifest.json"
    smoke_vocab_manifest = build_two_tower_item_vocab(
        canonical_interactions_train=smoke_interactions_path,
        canonical_items=smoke_items_path,
        output_vocab=smoke_vocab_path,
        output_manifest=smoke_vocab_manifest_path,
        min_frequency=1,
    )

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    common_policy = {
        "methodology": "sciomc_time_split_best_practice",
        "source_dataset": "amazon_2023_recall_recent_2y_1m_3m",
        "split_policy": "global_time_split_half_open_from_existing_2y_manifest",
        "history_policy": "history_before_target_time",
        "formal_sample_count_caps": "none",
        "old_dataset_count_limits_used": False,
        "train_item_universe_only": True,
        "valid_test_used_for_training": False,
        "item_vocab_min_frequency": 1,
    }

    formal_manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_tier": "formal",
        "generated_at": generated_at,
        "source_manifest_path": str(manifest_path),
        "policy": common_policy | {"role": "formal_training_input", "sample_count_caps": "none"},
        "paths": {
            "canonical_interactions_train": str(split_paths["train"]),
            "canonical_interactions_valid": str(split_paths["valid"]),
            "canonical_interactions_test": str(split_paths["test"]),
            "user_sequences_train": str(train_sequences_path),
            "canonical_items_train_only": str(canonical_items_path),
            "item_vocab_manifest": str(formal_vocab_manifest_path),
        },
        "signatures": {
            "recent_window_manifest": _file_signature(manifest_path),
            "train_interactions": _file_signature(split_paths["train"]),
            "valid_interactions": _file_signature(split_paths["valid"]),
            "test_interactions": _file_signature(split_paths["test"]),
            "train_user_sequences": _file_signature(train_sequences_path),
            "train_items": _file_signature(canonical_items_path),
            "item_vocab_manifest": _file_signature(formal_vocab_manifest_path),
        },
    }
    smoke_manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_tier": "smoke",
        "generated_at": generated_at,
        "source_manifest_path": str(manifest_path),
        "policy": common_policy | {
            "role": "smoke_only_not_formal",
            "sample_count_caps": {"smoke_users": smoke_users},
            "selection": "first_train_users_with_min_positive_sequence_len_3_from_existing_2y_train_sequences",
        },
        "paths": {
            "canonical_interactions_train": str(smoke_interactions_path),
            "user_sequences_train": str(smoke_sequences_path),
            "canonical_items_train_only": str(smoke_items_path),
            "item_vocab_manifest": str(smoke_vocab_manifest_path),
        },
        "counts": {
            "selected_user_count": len(smoke_user_ids),
            "train_interaction_count": smoke_interaction_stats["row_count"],
            "train_item_count": len(smoke_interaction_stats["item_ids"]),
            "item_vocab_count": smoke_vocab_manifest["item_count"],
            **smoke_sequence_stats,
        },
        "signatures": {
            "train_interactions": _file_signature(smoke_interactions_path),
            "train_user_sequences": _file_signature(smoke_sequences_path),
            "train_items": _file_signature(smoke_items_path),
            "item_vocab_manifest": _file_signature(smoke_vocab_manifest_path),
        },
    }
    top_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_manifest_path": str(manifest_path),
        "policy": common_policy,
        "tiers": {
            "smoke": str(smoke_dir / "manifest.json"),
            "formal": str(formal_dir / "manifest.json"),
        },
    }
    write_json(formal_dir / "manifest.json", formal_manifest)
    write_json(smoke_dir / "manifest.json", smoke_manifest)
    write_json(output_path / "manifest.json", top_manifest)
    write_json(output_path / "stats.json", {"schema_version": SCHEMA_VERSION, "generated_at": generated_at, "smoke": smoke_manifest["counts"], "formal": {"paths": formal_manifest["paths"]}})
    return {"manifest_path": str(output_path / "manifest.json"), "smoke_manifest_path": str(smoke_dir / "manifest.json"), "formal_manifest_path": str(formal_dir / "manifest.json")}


def _select_smoke_sequences(path: Path, smoke_users: int, sequence_max_len: int) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    user_ids: set[str] = set()
    scanned = 0
    for row in iter_jsonl(path):
        scanned += 1
        positives = list(row.get("recent_positive_item_sequence") or [])
        positive_times = list(row.get("recent_positive_timestamp_sequence") or [])
        if len(positives) < 3 or len(positive_times) != len(positives):
            continue
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        compact = dict(row)
        for key in ("recent_item_sequence", "recent_timestamp_sequence", "recent_positive_item_sequence", "recent_positive_timestamp_sequence", "recent_strong_positive_item_sequence", "recent_strong_positive_timestamp_sequence"):
            values = list(compact.get(key) or [])
            compact[key] = values[-sequence_max_len:]
        rows.append(compact)
        user_ids.add(user_id)
        if len(rows) >= smoke_users:
            break
    if not rows:
        raise ValueError("smoke selection produced no users")
    return rows, user_ids, {"source_sequence_rows_scanned": scanned, "smoke_user_sequence_count": len(rows)}


def _write_smoke_train_interactions(source_path: Path, output_path: Path, user_ids: set[str]) -> dict[str, Any]:
    rows = 0
    item_ids: set[str] = set()
    with output_path.open("w", encoding="utf-8") as handle:
        for row in iter_jsonl(source_path):
            if str(row.get("user_id") or "") not in user_ids:
                continue
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if item_id:
                item_ids.add(item_id)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows += 1
    if rows == 0:
        raise ValueError("smoke train interactions produced no rows")
    return {"row_count": rows, "item_ids": item_ids}


def _write_smoke_items(source_path: Path, output_path: Path, item_ids: set[str]) -> None:
    written = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in iter_jsonl(source_path):
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if item_id not in item_ids:
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
    if written != len(item_ids):
        raise ValueError(f"smoke canonical_items metadata missing items: written={written}, expected={len(item_ids)}")


def _resolve_split_paths(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    split_paths = manifest.get("split_paths")
    if not isinstance(split_paths, dict):
        split_paths = manifest.get("outputs", {}).get("split_paths")
    if not isinstance(split_paths, dict):
        raise ValueError("recent-window manifest must declare split_paths")
    return {split: _resolve_path(manifest_path, str(split_paths[split])) for split in ("train", "valid", "test")}


def _resolve_path(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest_path.parent / path).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {"path": str(path), "size_bytes": path.stat().st_size, "row_count": rows, "sha256": digest.hexdigest()}


def main() -> None:
    args = parse_args()
    outputs = build_sciomc_twotower_recent2y_preprocess(
        recent_window_manifest_path=args.recent_window_manifest,
        formal_item_vocab_manifest_path=args.formal_item_vocab_manifest,
        output_dir=args.output_dir,
        smoke_users=args.smoke_users,
        sequence_max_len=args.sequence_max_len,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
