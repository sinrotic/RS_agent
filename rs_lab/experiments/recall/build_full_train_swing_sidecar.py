from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _enforce_project_venv, _existing_ancestor, _file_signature

SCHEMA_VERSION = "full_train_swing_sidecar_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_full_sources" / "swing_recall"
DEFAULT_MIN_FREE_BYTES = 10 * 1024**3
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
    "valid",
    "test",
    "holdout",
)
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a train-only full-clean Swing item-pair sidecar for pool500 recall sources.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--max-item-user-freq", type=int, default=500)
    parser.add_argument("--max-user-items", type=int, default=100)
    parser.add_argument("--min-pair-support", type=int, default=2)
    parser.add_argument("--per-seed-top-k", type=int, default=200)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_full_train_swing_sidecar(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_item_user_freq: int = 500,
    max_user_items: int = 100,
    min_pair_support: int = 2,
    per_seed_top_k: int = 200,
    min_score: float = 0.0,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    _validate_limits(max_item_user_freq, max_user_items, min_pair_support, per_seed_top_k, min_score)
    if enforce_venv:
        _enforce_project_venv()

    clean_manifest_path = clean_manifest_path.resolve()
    output_dir = output_dir.resolve()
    clean_manifest = _read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    _precheck(clean_manifest_path, train_sequences_path, output_dir, min_free_bytes, overwrite)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free

    sequences_by_user, load_audit = _load_train_positive_sequences(train_sequences_path, max_user_items)
    item_users = _build_item_users(sequences_by_user)
    dropped_hot_items = _dropped_hot_items(item_users, max_item_user_freq)
    allowed_item_users = {item_id: users for item_id, users in item_users.items() if item_id not in dropped_hot_items}
    edges, build_audit = _build_swing_edges(
        sequences_by_user=sequences_by_user,
        item_users=allowed_item_users,
        dropped_hot_items=set(dropped_hot_items),
        min_pair_support=min_pair_support,
        per_seed_top_k=per_seed_top_k,
        min_score=min_score,
    )

    edges_path = output_dir / "swing_recall_edges.jsonl"
    write_jsonl(edges_path, edges)

    guard_contract = {
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    no_holdout_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **guard_contract,
        "read_files": [str(train_sequences_path)],
        "forbidden_files_not_read": [str(train_sequences_path.parent / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "valid_test_holdout_usage": "not_read",
        "source_signatures": {
            "clean_manifest": _file_signature(clean_manifest_path),
            "train_user_sequences": _file_signature(train_sequences_path),
        },
    }
    custom_index_selection_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **guard_contract,
        "method": "swing_recall",
        "input_strategy": "clean_manifest.train_user_sequences_path_only",
        "declared_inputs": [str(train_sequences_path)],
        "ranking_input_replacement": False,
        "pool500_recall_source_sidecar": True,
        "pool1000_ready": False,
        "parameters": {
            "max_item_user_freq": max_item_user_freq,
            "max_user_items": max_user_items,
            "min_pair_support": min_pair_support,
            "per_seed_top_k": per_seed_top_k,
            "min_score": min_score,
        },
    }
    dropped_hot_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "max_item_user_freq": max_item_user_freq,
        "dropped_item_count": len(dropped_hot_items),
        "items": [
            {"item_id": item_id, "train_user_freq": len(item_users[item_id])}
            for item_id in dropped_hot_items
        ],
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "disk_free_bytes_start": "excluded_from_canonical_sha",
        "disk_free_bytes_end": "excluded_from_canonical_sha",
        "canonical_sha_excluded_fields": ["disk_free_bytes_start", "disk_free_bytes_end"],
        "min_free_bytes": min_free_bytes,
        "user_count": len(sequences_by_user),
        "item_count_before_hot_drop": len(item_users),
        "item_count_after_hot_drop": len(allowed_item_users),
        "dropped_hot_item_count": len(dropped_hot_items),
        "edge_count": len(edges),
        "shard_audit": _shard_audit(edges),
        "load_audit": load_audit,
        "build_audit": build_audit,
        "no_unbounded_global_pair_counter": True,
    }
    edge_signature = _file_signature(edges_path)
    edge_signature["path"] = "swing_recall_edges.jsonl"
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": "excluded_from_canonical_sha",
        "source": "swing_recall",
        **guard_contract,
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "output_dir": "excluded_from_canonical_sha",
        "runtime_seconds": "excluded_from_canonical_sha",
        "canonical_sha_excluded_fields": ["generated_at", "output_dir", "runtime_seconds"],
        "edge_count": len(edges),
        "seed_count": len({edge["src_item"] for edge in edges}),
        "required_artifacts": {
            "swing_recall_edges": "swing_recall_edges.jsonl",
            "source_index_manifest": "source_index_manifest.json",
            "custom_index_selection_manifest": "custom_index_selection_manifest.json",
            "dropped_hot_items": "dropped_hot_items.json",
            "resource_audit": "resource_audit.json",
            "no_holdout_audit": "no_holdout_audit.json",
        },
        "artifact_signatures": {
            "swing_recall_edges": edge_signature,
        },
    }

    write_json(output_dir / "custom_index_selection_manifest.json", custom_index_selection_manifest)
    write_json(output_dir / "dropped_hot_items.json", dropped_hot_payload)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _validate_limits(max_item_user_freq: int, max_user_items: int, min_pair_support: int, per_seed_top_k: int, min_score: float) -> None:
    for label, value in {
        "max_item_user_freq": max_item_user_freq,
        "max_user_items": max_user_items,
        "min_pair_support": min_pair_support,
        "per_seed_top_k": per_seed_top_k,
    }.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if min_score < 0:
        raise ValueError("min_score must be non-negative")


def _resolve_train_sequences_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path") or manifest.get("outputs", {}).get("train_user_sequences_path")
    if not raw_path:
        raise ValueError("Clean manifest must declare train_user_sequences_path")
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (clean_manifest_path.parent / path).resolve()


def _precheck(clean_manifest_path: Path, train_sequences_path: Path, output_dir: Path, min_free_bytes: int, overwrite: bool) -> None:
    for path in (clean_manifest_path, train_sequences_path, output_dir):
        lowered_parts = {part.lower() for part in path.parts}
        lowered_path = str(path).replace("\\", "/").lower()
        forbidden_dataset_parts = {"amazon_2023_recall_clean_10000", "amazon_2023_recall_views_10000", "pool1000"}
        forbidden_input_files = set(FORBIDDEN_CANDIDATE_FILES) if path != output_dir else set()
        if lowered_parts & forbidden_dataset_parts or path.name.lower() in forbidden_input_files or "/holdout/" in lowered_path:
            raise ValueError(f"Forbidden input/output path for full-train Swing sidecar: {path}")
    if train_sequences_path.name != "user_sequences.train.jsonl":
        raise ValueError(f"Swing sidecar must read user_sequences.train.jsonl, got: {train_sequences_path}")
    missing = [str(path) for path in (clean_manifest_path, train_sequences_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(missing))
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"Free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_train_positive_sequences(path: Path, max_user_items: int) -> tuple[dict[str, list[str]], dict[str, Any]]:
    sequences_by_user: dict[str, list[str]] = {}
    raw_user_count = 0
    raw_positive_count = 0
    retained_positive_count = 0
    truncated_user_count = 0
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        raw_items = [str(item_id) for item_id in row.get("recent_positive_item_sequence", []) or [] if item_id]
        if len(raw_items) < 2:
            continue
        raw_user_count += 1
        raw_positive_count += len(raw_items)
        items = list(dict.fromkeys(raw_items[-max_user_items:]))
        if len(raw_items) > max_user_items:
            truncated_user_count += 1
        if len(items) < 2:
            continue
        sequences_by_user[user_id] = items
        retained_positive_count += len(items)
    return sequences_by_user, {
        "raw_user_count_with_two_positive_items": raw_user_count,
        "retained_user_count": len(sequences_by_user),
        "raw_positive_item_count": raw_positive_count,
        "retained_positive_item_count": retained_positive_count,
        "truncated_user_count_by_max_user_items": truncated_user_count,
    }


def _build_item_users(sequences_by_user: dict[str, list[str]]) -> dict[str, set[str]]:
    item_users: dict[str, set[str]] = defaultdict(set)
    for user_id, items in sequences_by_user.items():
        for item_id in items:
            item_users[item_id].add(user_id)
    return dict(item_users)


def _dropped_hot_items(item_users: dict[str, set[str]], max_item_user_freq: int) -> list[str]:
    return sorted(item_id for item_id, users in item_users.items() if len(users) > max_item_user_freq)


def _build_swing_edges(
    *,
    sequences_by_user: dict[str, list[str]],
    item_users: dict[str, set[str]],
    dropped_hot_items: set[str],
    min_pair_support: int,
    per_seed_top_k: int,
    min_score: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    user_item_sets = {
        user_id: {item_id for item_id in items if item_id not in dropped_hot_items}
        for user_id, items in sequences_by_user.items()
    }
    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    pair_support: dict[str, Counter[str]] = defaultdict(Counter)
    pair_update_count = 0
    alpha = 1.0
    for left_item in sorted(item_users):
        related: Counter[str] = Counter()
        for user_id in sorted(item_users[left_item]):
            for right_item in user_item_sets.get(user_id, set()):
                if right_item == left_item:
                    continue
                related[right_item] += 1
                pair_update_count += 1
        for right_item, co_count in related.items():
            if co_count < min_pair_support:
                continue
            common_users = item_users[left_item] & item_users.get(right_item, set())
            denom = alpha + sum(1.0 / max(1, len(user_item_sets[user_id])) for user_id in common_users)
            score = float(co_count) / denom if denom else 0.0
            if score >= min_score:
                pair_scores[left_item][right_item] = score
                pair_support[left_item][right_item] = co_count

    edges: list[dict[str, Any]] = []
    for src_item in sorted(pair_scores):
        ranked = sorted(pair_scores[src_item].items(), key=lambda item: (-float(item[1]), item[0]))[:per_seed_top_k]
        for rank, (dst_item, score) in enumerate(ranked, start=1):
            edges.append(
                {
                    "src_item": src_item,
                    "dst_item": dst_item,
                    "score": round(float(score), 6),
                    "rank": rank,
                    "source": "swing_recall",
                }
            )
    return edges, {
        "pair_update_count": pair_update_count,
        "supported_pair_count": sum(len(scores) for scores in pair_scores.values()),
        "min_pair_support": min_pair_support,
        "per_seed_top_k": per_seed_top_k,
        "min_score": min_score,
    }


def _shard_audit(edges: list[dict[str, Any]]) -> dict[str, Any]:
    shard_counts: Counter[str] = Counter(str(edge["src_item"])[:2] or "__" for edge in edges)
    return {
        "strategy": "src_item_prefix_2_audit_only",
        "shard_count": len(shard_counts),
        "max_edges_per_shard": max(shard_counts.values()) if shard_counts else 0,
        "shards": dict(sorted(shard_counts.items())),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    manifest = build_full_train_swing_sidecar(
        clean_manifest_path=Path(args.clean_manifest),
        output_dir=Path(args.output_dir),
        max_item_user_freq=args.max_item_user_freq,
        max_user_items=args.max_user_items,
        min_pair_support=args.min_pair_support,
        per_seed_top_k=args.per_seed_top_k,
        min_score=args.min_score,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(f"Full-train Swing sidecar status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['source_index_manifest']}")


if __name__ == "__main__":
    main()
