from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json

SCHEMA_VERSION = "bounded_itemcf_covisit_sidecar_v1"
DEFAULT_LIMIT_USERS = 500
MAX_LIMIT_USERS = 1000
DEFAULT_MAX_HISTORY_ITEMS = 50
DEFAULT_MAX_PAIRS_PER_USER = 1000
DEFAULT_TOP_NEIGHBORS_PER_ITEM = 200
DEFAULT_MAX_ITEM_DEGREE = 5000
DEFAULT_SHARD_COUNT = 32
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a small bounded ItemCF/co-visit neighbor sidecar.")
    parser.add_argument("--clean-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--limit-users", type=int, default=DEFAULT_LIMIT_USERS)
    parser.add_argument("--max-history-items", type=int, default=DEFAULT_MAX_HISTORY_ITEMS)
    parser.add_argument("--max-pairs-per-user", type=int, default=DEFAULT_MAX_PAIRS_PER_USER)
    parser.add_argument("--top-neighbors-per-item", type=int, default=DEFAULT_TOP_NEIGHBORS_PER_ITEM)
    parser.add_argument("--max-item-degree", type=int, default=DEFAULT_MAX_ITEM_DEGREE)
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_sidecar_build(
    *,
    clean_dir: Path,
    output_dir: Path,
    limit_users: int = DEFAULT_LIMIT_USERS,
    max_history_items: int = DEFAULT_MAX_HISTORY_ITEMS,
    max_pairs_per_user: int = DEFAULT_MAX_PAIRS_PER_USER,
    top_neighbors_per_item: int = DEFAULT_TOP_NEIGHBORS_PER_ITEM,
    max_item_degree: int = DEFAULT_MAX_ITEM_DEGREE,
    shard_count: int = DEFAULT_SHARD_COUNT,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    _validate_caps(
        limit_users=limit_users,
        max_history_items=max_history_items,
        max_pairs_per_user=max_pairs_per_user,
        top_neighbors_per_item=top_neighbors_per_item,
        max_item_degree=max_item_degree,
        shard_count=shard_count,
        min_free_bytes=min_free_bytes,
    )
    if enforce_venv:
        _enforce_project_venv()

    clean_dir = clean_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck_paths(clean_dir, output_dir)
    disk_free = shutil.disk_usage(output_dir.parent).free
    if disk_free < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {disk_free} < {min_free_bytes}")

    sequence_path = clean_dir / "user_sequences.train.jsonl"
    if not sequence_path.is_file():
        raise FileNotFoundError(sequence_path)

    source_signature = _source_signature(sequence_path)
    sequences, users_scanned = _load_sequences(sequence_path, limit_users, max_history_items)
    build_result = _build_neighbors(
        sequences,
        max_pairs_per_user=max_pairs_per_user,
        top_neighbors_per_item=top_neighbors_per_item,
        max_item_degree=max_item_degree,
    )

    output_dir.mkdir(parents=True)
    shard_stats = _write_neighbor_shards(output_dir, build_result["neighbors_by_item"], shard_count)

    disabled_outputs = {
        "pool500": True,
        "pool1000": True,
        "recall_views": True,
        "full_clean_copy": True,
        "valid_reads": True,
        "test_reads": True,
        "holdout_reads": True,
    }
    safety_flags = {
        "project_venv_enforced": enforce_venv,
        "forbidden_10k_paths_rejected": True,
        "existing_output_dir_rejected": True,
        "output_inside_clean_dir_rejected": True,
        "disk_free_enforced": True,
        "bounded_representative_users_only": True,
        "bounded_pair_counter_only": True,
        "train_only": True,
    }
    common_payload = {
        "schema_version": SCHEMA_VERSION,
        "train_only": True,
        "holdout_contract": {
            "uses_holdout": False,
            "source_file": "user_sequences.train.jsonl",
            "allowed_inputs": ["clean_dir/user_sequences.train.jsonl"],
            "forbidden_inputs": [
                "canonical_interactions.valid.jsonl",
                "canonical_interactions.test.jsonl",
                "holdout files",
            ],
        },
        "resolved_paths": {
            "clean_dir": str(clean_dir),
            "output_dir": str(output_dir),
            "user_sequences_train": str(sequence_path),
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
        },
        "config_caps": {
            "limit_users": limit_users,
            "max_history_items": max_history_items,
            "max_pairs_per_user": max_pairs_per_user,
            "top_neighbors_per_item": top_neighbors_per_item,
            "max_item_degree": max_item_degree,
            "shard_count": shard_count,
            "min_free_bytes": min_free_bytes,
        },
        "source_signature": source_signature,
        "disk_free_bytes": disk_free,
        "users_scanned": users_scanned,
        "sampled_users": len(sequences),
        "processed_users": build_result["processed_users"],
        "pair_updates": build_result["pair_updates"],
        "pairs_dropped_by_cap": build_result["pairs_dropped_by_cap"],
        "hot_items_skipped": build_result["hot_items_skipped"],
        "over_degree_items": build_result["over_degree_items"],
        "shards": shard_stats,
        "safety_flags": safety_flags,
        "disabled_outputs": disabled_outputs,
    }
    manifest = dict(common_payload)
    manifest["outputs"] = {
        "neighbor_shards": [stat["path"] for stat in shard_stats],
        "manifest": str(output_dir / "manifest.json"),
        "source_audit": str(output_dir / "source_audit.json"),
    }
    source_audit = dict(common_payload)
    source_audit["read_files"] = [str(sequence_path)]
    source_audit["write_files"] = manifest["outputs"]

    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "source_audit.json", source_audit)
    return manifest


def _validate_caps(
    *,
    limit_users: int,
    max_history_items: int,
    max_pairs_per_user: int,
    top_neighbors_per_item: int,
    max_item_degree: int,
    shard_count: int,
    min_free_bytes: int,
) -> None:
    if limit_users <= 0 or limit_users > MAX_LIMIT_USERS:
        raise ValueError(f"--limit-users must be between 1 and {MAX_LIMIT_USERS}")
    positive_caps = {
        "--max-history-items": max_history_items,
        "--max-pairs-per-user": max_pairs_per_user,
        "--top-neighbors-per-item": top_neighbors_per_item,
        "--max-item-degree": max_item_degree,
        "--shard-count": shard_count,
    }
    for name, value in positive_caps.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if min_free_bytes < 0:
        raise ValueError("--min-free-bytes must be non-negative")


def _enforce_project_venv() -> None:
    executable = Path(sys.executable).resolve()
    expected = (ROOT / ".venv").resolve()
    try:
        executable.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError(f"Project .venv Python is required, got {sys.executable}") from exc


def _precheck_paths(clean_dir: Path, output_dir: Path) -> None:
    for path in (clean_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k path is not allowed: {path}")
    if not clean_dir.is_dir():
        raise NotADirectoryError(clean_dir)
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    try:
        output_dir.relative_to(clean_dir)
    except ValueError:
        return
    raise ValueError(f"Output directory must not be inside clean dir: {output_dir}")


def _load_sequences(path: Path, limit_users: int, max_history_items: int) -> tuple[list[list[str]], int]:
    sequences: list[list[str]] = []
    users_scanned = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            users_scanned += 1
            record = json.loads(line)
            items = _history_items(record, max_history_items)
            if items:
                sequences.append(items)
            if users_scanned >= limit_users:
                break
    return sequences, users_scanned


def _history_items(record: dict[str, Any], max_history_items: int) -> list[str]:
    raw_items = record.get("recent_strong_positive_item_sequence") or record.get("recent_positive_item_sequence") or record.get("recent_item_sequence") or []
    if not isinstance(raw_items, list):
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for item in reversed(raw_items[-max_history_items:]):
        item_id = str(item)
        if item_id and item_id not in seen:
            seen.add(item_id)
            deduped.append(item_id)
    deduped.reverse()
    return deduped


def _source_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "row_count": rows,
        "sha256": digest.hexdigest(),
    }


def _build_neighbors(
    sequences: list[list[str]],
    *,
    max_pairs_per_user: int,
    top_neighbors_per_item: int,
    max_item_degree: int,
) -> dict[str, Any]:
    item_degree = Counter(item for sequence in sequences for item in set(sequence))
    over_degree_items = sorted(item for item, degree in item_degree.items() if degree > max_item_degree)
    over_degree_set = set(over_degree_items)
    pair_count: Counter[tuple[str, str]] = Counter()
    pair_updates = 0
    pairs_dropped_by_cap = 0
    hot_items_skipped = 0
    processed_users = 0

    for sequence in sequences:
        filtered = []
        for item in sequence:
            if item in over_degree_set:
                hot_items_skipped += 1
            else:
                filtered.append(item)
        if len(filtered) < 2:
            continue
        processed_users += 1
        kept_for_user = 0
        for left, right in combinations(filtered, 2):
            if kept_for_user >= max_pairs_per_user:
                pairs_dropped_by_cap += 1
                continue
            kept_for_user += 1
            pair_updates += 1
            pair_count[(left, right) if left <= right else (right, left)] += 1

    neighbor_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for (left, right), cooc_cnt in pair_count.items():
        denominator = math.sqrt(item_degree[left] * item_degree[right])
        score = 0.0 if denominator == 0 else round(cooc_cnt / denominator, 6)
        neighbor_rows[left].append({"item_id": right, "score": score, "cooc_cnt": cooc_cnt})
        neighbor_rows[right].append({"item_id": left, "score": score, "cooc_cnt": cooc_cnt})

    neighbors_by_item: dict[str, list[dict[str, Any]]] = {}
    for item_id, neighbors in neighbor_rows.items():
        neighbors_by_item[item_id] = sorted(
            neighbors,
            key=lambda row: (-row["score"], -row["cooc_cnt"], row["item_id"]),
        )[:top_neighbors_per_item]

    return {
        "neighbors_by_item": neighbors_by_item,
        "processed_users": processed_users,
        "pair_updates": pair_updates,
        "pairs_dropped_by_cap": pairs_dropped_by_cap,
        "hot_items_skipped": hot_items_skipped,
        "over_degree_items": over_degree_items,
    }


def _write_neighbor_shards(output_dir: Path, neighbors_by_item: dict[str, list[dict[str, Any]]], shard_count: int) -> list[dict[str, Any]]:
    shard_paths = [output_dir / f"neighbors_shard_{index:05d}.jsonl" for index in range(shard_count)]
    handles = [path.open("w", encoding="utf-8") for path in shard_paths]
    row_counts = [0 for _ in shard_paths]
    try:
        for src_item in sorted(neighbors_by_item):
            shard_index = _stable_shard(src_item, shard_count)
            record = {"src_item": src_item, "neighbors": neighbors_by_item[src_item]}
            handles[shard_index].write(json.dumps(record, ensure_ascii=False) + "\n")
            row_counts[shard_index] += 1
    finally:
        for handle in handles:
            handle.close()

    stats = []
    for index, path in enumerate(shard_paths):
        stats.append(
            {
                "shard_index": index,
                "path": str(path),
                "rows": row_counts[index],
                "bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    return stats


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_shard(value: str, shard_count: int) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % shard_count


def main() -> None:
    args = parse_args()
    manifest = run_sidecar_build(
        clean_dir=Path(args.clean_dir),
        output_dir=Path(args.output_dir),
        limit_users=args.limit_users,
        max_history_items=args.max_history_items,
        max_pairs_per_user=args.max_pairs_per_user,
        top_neighbors_per_item=args.top_neighbors_per_item,
        max_item_degree=args.max_item_degree,
        shard_count=args.shard_count,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(f"Sidecar manifest written to: {manifest['resolved_paths']['manifest']}")
    print(f"Processed users: {manifest['processed_users']}")
    print(f"Pair updates: {manifest['pair_updates']}")


if __name__ == "__main__":
    main()
