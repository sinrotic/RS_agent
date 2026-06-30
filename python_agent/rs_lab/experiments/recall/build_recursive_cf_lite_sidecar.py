from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "recursive_cf_lite_sidecar_v1"
SOURCE_NAME = "usercf_recall"
SOURCE_VARIANT = "recursive_cf_lite_zhang_pu_2007"
INDEX_SCOPE = "FULL_DERIVED_INDEX"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "manifest.json"
DEFAULT_EVAL_USERS = ROOT / "outputs" / "eval" / "pool500_offline_eval_users_10k" / "users.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_method_sources" / "recent_2y" / "recursive_cf_lite" / "diagnostic_v1"
FORBIDDEN_INPUT_NAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_PATH_TOKENS = {"holdout", "valid", "test", "lopo", "oracle", "eval_label"}
FORBIDDEN_SWITCHES = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a train-only Recursive CF-lite sidecar compatible with usercf_recall route loading.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--target-users", default=str(DEFAULT_EVAL_USERS), help="JSONL users to materialize candidates for; empty means all indexed users.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--sequence-field", default="recent_strong_positive_item_sequence")
    parser.add_argument("--fallback-sequence-field", default="recent_positive_item_sequence")
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--max-item-user-freq", type=int, default=5000)
    parser.add_argument("--similar-users-top-k", type=int, default=80)
    parser.add_argument("--recursive-neighbor-top-k", type=int, default=20)
    parser.add_argument("--second-order-top-k", type=int, default=20)
    parser.add_argument("--candidate-items-per-neighbor", type=int, default=80)
    parser.add_argument("--candidate-top-k-per-user", type=int, default=200)
    parser.add_argument("--max-depth", type=int, choices=(1, 2), default=2)
    parser.add_argument("--recursive-decay", type=float, default=0.6)
    parser.add_argument("--min-similarity", type=float, default=0.0)
    parser.add_argument("--target-user-limit", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=16)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_recursive_cf_lite_sidecar(
    *,
    clean_manifest: Path = DEFAULT_CLEAN_MANIFEST,
    target_users_path: Path | None = DEFAULT_EVAL_USERS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sequence_field: str = "recent_strong_positive_item_sequence",
    fallback_sequence_field: str = "recent_positive_item_sequence",
    max_items_per_user: int = 80,
    max_item_user_freq: int = 5000,
    similar_users_top_k: int = 80,
    recursive_neighbor_top_k: int = 20,
    second_order_top_k: int = 20,
    candidate_items_per_neighbor: int = 80,
    candidate_top_k_per_user: int = 200,
    max_depth: int = 2,
    recursive_decay: float = 0.6,
    min_similarity: float = 0.0,
    target_user_limit: int = 0,
    shard_count: int = 16,
    min_free_bytes: int = 0,
    overwrite: bool = False,
    enforce_venv_check: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv_check:
        enforce_project_venv(ROOT)
    _validate_args(
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        similar_users_top_k=similar_users_top_k,
        recursive_neighbor_top_k=recursive_neighbor_top_k,
        second_order_top_k=second_order_top_k,
        candidate_items_per_neighbor=candidate_items_per_neighbor,
        candidate_top_k_per_user=candidate_top_k_per_user,
        max_depth=max_depth,
        recursive_decay=recursive_decay,
        target_user_limit=target_user_limit,
        shard_count=shard_count,
        min_free_bytes=min_free_bytes,
    )
    clean_manifest = clean_manifest.resolve()
    output_dir = output_dir.resolve()
    target_users_path = target_users_path.resolve() if target_users_path else None
    _precheck_input_path(clean_manifest, "clean_manifest")
    if target_users_path:
        _precheck_eval_user_path(target_users_path)
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    if min_free_bytes and shutil.disk_usage(_existing_ancestor(output_dir.parent)).free < min_free_bytes:
        raise RuntimeError("Free disk bytes below --min-free-bytes")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_payload = read_json(clean_manifest)
    train_sequence_path = _resolve_train_sequence_path(clean_manifest, manifest_payload)
    _precheck_train_path(train_sequence_path)
    target_user_ids = _load_target_user_ids(target_users_path, target_user_limit) if target_users_path else None
    user_items, item_users_raw, load_audit = _load_user_items(
        train_sequence_path,
        sequence_field=sequence_field,
        fallback_sequence_field=fallback_sequence_field,
        max_items_per_user=max_items_per_user,
    )
    if target_user_ids is None:
        target_user_ids = sorted(user_items)
        if target_user_limit:
            target_user_ids = target_user_ids[:target_user_limit]
    else:
        target_user_ids = [user_id for user_id in target_user_ids if user_id in user_items]

    hot_items = {item_id for item_id, users in item_users_raw.items() if len(users) > max_item_user_freq}
    item_users = {item_id: users for item_id, users in item_users_raw.items() if item_id not in hot_items}
    item_weight = {item_id: 1.0 / math.log(2.0 + len(users)) for item_id, users in item_users.items()}
    user_norm = _user_norms(user_items, item_weight)
    shard_paths = [output_dir / f"recursive_cf_lite_shard_{index:05d}.jsonl" for index in range(shard_count)]
    shard_handles = [path.open("w", encoding="utf-8") for path in shard_paths]
    stats = Counter()
    try:
        for user_id in target_user_ids:
            candidates, user_stats = _recursive_candidates_for_user(
                user_id,
                user_items=user_items,
                item_users=item_users,
                item_weight=item_weight,
                user_norm=user_norm,
                similar_users_top_k=similar_users_top_k,
                recursive_neighbor_top_k=recursive_neighbor_top_k,
                second_order_top_k=second_order_top_k,
                candidate_items_per_neighbor=candidate_items_per_neighbor,
                candidate_top_k_per_user=candidate_top_k_per_user,
                max_depth=max_depth,
                recursive_decay=recursive_decay,
                min_similarity=min_similarity,
            )
            stats.update(user_stats)
            if not candidates:
                continue
            shard_id = _stable_shard_id(user_id, shard_count)
            row = {"user_id": user_id, "candidates": candidates}
            shard_handles[shard_id].write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["candidate_user_count"] += 1
            stats["candidate_total_count"] += len(candidates)
    finally:
        for handle in shard_handles:
            handle.close()

    shard_stats = _shard_stats(shard_paths)
    source_signature = _file_signature(train_sequence_path)
    outputs = {
        "candidate_shards": [str(path) for path in shard_paths],
        "source_index_manifest": str(output_dir / "source_index_manifest.json"),
        "resource_audit": str(output_dir / "resource_audit.json"),
        "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
    }
    hard_contract = {
        "source": SOURCE_NAME,
        "source_variant": SOURCE_VARIANT,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
    }
    config = {
        "sequence_field": sequence_field,
        "fallback_sequence_field": fallback_sequence_field,
        "max_items_per_user": max_items_per_user,
        "max_item_user_freq": max_item_user_freq,
        "similar_users_top_k": similar_users_top_k,
        "recursive_neighbor_top_k": recursive_neighbor_top_k,
        "second_order_top_k": second_order_top_k,
        "candidate_items_per_neighbor": candidate_items_per_neighbor,
        "candidate_top_k_per_user": candidate_top_k_per_user,
        "max_depth": max_depth,
        "recursive_decay": recursive_decay,
        "min_similarity": min_similarity,
        "target_user_limit": target_user_limit,
        "shard_count": shard_count,
    }
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **hard_contract,
        "paper_reference": {
            "title": "A recursive prediction algorithm for collaborative filtering recommender systems",
            "authors": ["Jiyong Zhang", "Pearl Pu"],
            "venue": "RecSys 2007",
            "doi": "10.1145/1297231.1297241",
            "implementation_note": "Implicit-feedback Recursive CF-lite: missing neighbor preference is approximated by depth-2 user-neighbor evidence with decay and pruning, not a full rating-matrix RPA reproduction.",
        },
        "config_caps": config,
        "target_user_count": len(target_user_ids),
        "indexed_user_count": load_audit["indexed_user_count"],
        "indexed_item_count": len(item_users_raw),
        "dropped_hot_item_count": len(hot_items),
        "candidate_user_count": int(stats["candidate_user_count"]),
        "candidate_total_count": int(stats["candidate_total_count"]),
        "row_count": int(stats["candidate_user_count"]),
        "underfilled_user_coverage": round(int(stats["candidate_user_count"]) / len(target_user_ids), 6) if target_user_ids else 0.0,
        "recursive_candidate_share": round(int(stats["recursive_candidate_edges"]) / max(1, int(stats["direct_candidate_edges"]) + int(stats["recursive_candidate_edges"])), 6),
        "resolved_paths": {
            "clean_manifest": str(clean_manifest),
            "train_user_sequences_path": str(train_sequence_path),
            "target_users_path": str(target_users_path) if target_users_path else None,
            "output_dir": str(output_dir),
        },
        "outputs": outputs,
        "shards": shard_stats,
        "source_signature": source_signature,
        "runtime_seconds": round(perf_counter() - started, 6),
        "no_oracle": True,
        "eval_only": False,
        "label_backflow_allowed": False,
    }
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "config_caps": config,
        "load_audit": load_audit,
        "stats": dict(stats),
        "shards": shard_stats,
    }
    no_holdout_audit = {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS",
        "allowed_inputs": ["clean_manifest.train_user_sequences_path", "target_users.user_id_for_materialization_only"],
        "forbidden_inputs": sorted(FORBIDDEN_INPUT_NAMES),
        "train_user_sequences_path": str(train_sequence_path),
        "target_users_path": str(target_users_path) if target_users_path else None,
        "labels_used_for_candidate_generation": False,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
    }
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _recursive_candidates_for_user(
    user_id: str,
    *,
    user_items: dict[str, list[str]],
    item_users: dict[str, set[str]],
    item_weight: dict[str, float],
    user_norm: dict[str, float],
    similar_users_top_k: int,
    recursive_neighbor_top_k: int,
    second_order_top_k: int,
    candidate_items_per_neighbor: int,
    candidate_top_k_per_user: int,
    max_depth: int,
    recursive_decay: float,
    min_similarity: float,
) -> tuple[list[dict[str, Any]], Counter]:
    seen_items = set(user_items.get(user_id, []))
    stats: Counter = Counter()
    direct_scores: Counter[str] = Counter()
    recursive_scores: Counter[str] = Counter()
    first_neighbors = _similar_users(
        user_id,
        user_items=user_items,
        item_users=item_users,
        item_weight=item_weight,
        user_norm=user_norm,
        top_k=similar_users_top_k,
        min_similarity=min_similarity,
    )
    stats["first_order_neighbor_links"] += len(first_neighbors)
    for neighbor_id, sim_uv in first_neighbors:
        for item_id in user_items.get(neighbor_id, [])[:candidate_items_per_neighbor]:
            if item_id in seen_items or item_id not in item_weight:
                continue
            direct_scores[item_id] += sim_uv
            stats["direct_candidate_edges"] += 1
    if max_depth >= 2:
        for neighbor_id, sim_uv in first_neighbors[:recursive_neighbor_top_k]:
            second_neighbors = _similar_users(
                neighbor_id,
                user_items=user_items,
                item_users=item_users,
                item_weight=item_weight,
                user_norm=user_norm,
                top_k=second_order_top_k,
                min_similarity=min_similarity,
            )
            stats["second_order_neighbor_links"] += len(second_neighbors)
            for second_neighbor_id, sim_vw in second_neighbors:
                if second_neighbor_id == user_id:
                    continue
                path_weight = recursive_decay * sim_uv * sim_vw
                for item_id in user_items.get(second_neighbor_id, [])[:candidate_items_per_neighbor]:
                    if item_id in seen_items or item_id not in item_weight:
                        continue
                    recursive_scores[item_id] += path_weight
                    stats["recursive_candidate_edges"] += 1
    merged_items = set(direct_scores) | set(recursive_scores)
    ranked = sorted(
        merged_items,
        key=lambda item_id: (-(direct_scores[item_id] + recursive_scores[item_id]), -direct_scores[item_id], item_id),
    )[:candidate_top_k_per_user]
    candidates = []
    for rank, item_id in enumerate(ranked, start=1):
        direct_score = float(direct_scores[item_id])
        recursive_score = float(recursive_scores[item_id])
        total_score = direct_score + recursive_score
        candidates.append(
            {
                "item_id": item_id,
                "rank": rank,
                "score": round(total_score, 10),
                "source": SOURCE_NAME,
                "canonical_source": SOURCE_NAME,
                "source_variant": SOURCE_VARIANT,
                "direct_score": round(direct_score, 10),
                "recursive_score": round(recursive_score, 10),
                "recursive_depth": 2 if recursive_score > 0 else 1,
            }
        )
    return candidates, stats


@lru_cache(maxsize=200000)
def _similar_users_cached(
    user_id: str,
    top_k: int,
    min_similarity: float,
    user_items_id: int,
    item_users_id: int,
    item_weight_id: int,
    user_norm_id: int,
) -> tuple[tuple[str, float], ...]:
    raise RuntimeError("cache key placeholder should be replaced by _similar_users")


def _similar_users(
    user_id: str,
    *,
    user_items: dict[str, list[str]],
    item_users: dict[str, set[str]],
    item_weight: dict[str, float],
    user_norm: dict[str, float],
    top_k: int,
    min_similarity: float,
) -> list[tuple[str, float]]:
    cache = _similar_users.__dict__.setdefault("cache", {})
    cache_key = (user_id, top_k, min_similarity)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    accum: Counter[str] = Counter()
    for item_id in user_items.get(user_id, []):
        weight = item_weight.get(item_id)
        if not weight:
            continue
        weighted = weight * weight
        for neighbor_id in item_users.get(item_id, set()):
            if neighbor_id != user_id:
                accum[neighbor_id] += weighted
    denom_u = user_norm.get(user_id, 0.0)
    rows: list[tuple[str, float]] = []
    for neighbor_id, overlap_score in accum.items():
        denom = denom_u * user_norm.get(neighbor_id, 0.0)
        if denom <= 0:
            continue
        sim = float(overlap_score) / denom
        if sim > min_similarity:
            rows.append((neighbor_id, sim))
    rows.sort(key=lambda row: (-row[1], row[0]))
    result = rows[:top_k]
    if len(cache) < 200000:
        cache[cache_key] = result
    return result


def _load_user_items(
    path: Path,
    *,
    sequence_field: str,
    fallback_sequence_field: str,
    max_items_per_user: int,
) -> tuple[dict[str, list[str]], dict[str, set[str]], dict[str, Any]]:
    user_items: dict[str, list[str]] = {}
    item_users: dict[str, set[str]] = defaultdict(set)
    scanned = 0
    fallback_used = 0
    for row in iter_jsonl(path):
        scanned += 1
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        raw_items = row.get(sequence_field)
        if not raw_items and fallback_sequence_field:
            raw_items = row.get(fallback_sequence_field)
            fallback_used += 1
        items = _unique_recent([str(item) for item in (raw_items or []) if item], max_items_per_user)
        if not items:
            continue
        user_items[user_id] = items
        for item_id in items:
            item_users[item_id].add(user_id)
    return user_items, dict(item_users), {"scanned_rows": scanned, "indexed_user_count": len(user_items), "indexed_item_count": len(item_users), "fallback_sequence_rows": fallback_used}


def _user_norms(user_items: dict[str, list[str]], item_weight: dict[str, float]) -> dict[str, float]:
    norms: dict[str, float] = {}
    for user_id, items in user_items.items():
        value = math.sqrt(sum((item_weight.get(item_id, 0.0) ** 2) for item_id in items))
        if value > 0:
            norms[user_id] = value
    return norms


def _unique_recent(items: Iterable[str], max_items: int) -> list[str]:
    recent = []
    seen = set()
    for item_id in reversed(list(items)):
        if item_id in seen:
            continue
        seen.add(item_id)
        recent.append(item_id)
        if len(recent) >= max_items:
            break
    return list(reversed(recent))


def _load_target_user_ids(path: Path, limit: int) -> list[str]:
    users = []
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id:
            users.append(user_id)
        if limit and len(users) >= limit:
            break
    return users


def _resolve_train_sequence_path(clean_manifest: Path, payload: dict[str, Any]) -> Path:
    for key in ("train_user_sequences_path", "user_sequences_train_path"):
        value = payload.get(key)
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else (clean_manifest.parent / path).resolve()
    sequences = payload.get("user_sequences") if isinstance(payload.get("user_sequences"), dict) else {}
    value = sequences.get("train")
    if value:
        path = Path(str(value))
        return path if path.is_absolute() else (clean_manifest.parent / path).resolve()
    return (clean_manifest.parent / "user_sequences.train.jsonl").resolve()


def _validate_args(**values: Any) -> None:
    for key, value in values.items():
        if key == "recursive_decay":
            if not (0.0 <= float(value) <= 1.0):
                raise ValueError("--recursive-decay must be in [0, 1]")
            continue
        if key in {"target_user_limit", "min_free_bytes"}:
            if int(value) < 0:
                raise ValueError(f"--{key.replace('_', '-')} must be non-negative")
            continue
        if int(value) <= 0:
            raise ValueError(f"--{key.replace('_', '-')} must be positive")


def _precheck_input_path(path: Path, label: str) -> None:
    lowered = str(path).replace("\\", "/").lower()
    tokens = {token for token in lowered.replace("-", "_").replace(".", "_").split("/") if token}
    if tokens & FORBIDDEN_PATH_TOKENS:
        raise ValueError(f"Forbidden holdout/valid/test/LOPO/oracle/eval path is not allowed for {label}: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)


def _precheck_eval_user_path(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.name != "users.jsonl":
        raise ValueError(f"target users must be users.jsonl, got {path.name}")


def _precheck_train_path(path: Path) -> None:
    _precheck_input_path(path, "train_sequence_path")
    if path.name in FORBIDDEN_INPUT_NAMES or path.name != "user_sequences.train.jsonl":
        raise ValueError(f"Recursive CF-lite must read user_sequences.train.jsonl, got {path.name}")


def _stable_shard_id(value: str, shard_count: int) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16) % shard_count


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"path": str(path), "size_bytes": size, "sha256": digest.hexdigest()}


def _shard_stats(paths: list[Path]) -> list[dict[str, Any]]:
    stats = []
    for path in paths:
        row_count = 0
        candidate_count = 0
        for row in iter_jsonl(path):
            row_count += 1
            candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
            candidate_count += len(candidates)
        stats.append({"path": str(path), "row_count": row_count, "candidate_count": candidate_count})
    return stats


def _existing_ancestor(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        current = current.parent
    return current


def main() -> None:
    args = parse_args()
    manifest = build_recursive_cf_lite_sidecar(
        clean_manifest=Path(args.clean_manifest),
        target_users_path=Path(args.target_users) if args.target_users else None,
        output_dir=Path(args.output_dir),
        sequence_field=args.sequence_field,
        fallback_sequence_field=args.fallback_sequence_field,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        similar_users_top_k=args.similar_users_top_k,
        recursive_neighbor_top_k=args.recursive_neighbor_top_k,
        second_order_top_k=args.second_order_top_k,
        candidate_items_per_neighbor=args.candidate_items_per_neighbor,
        candidate_top_k_per_user=args.candidate_top_k_per_user,
        max_depth=args.max_depth,
        recursive_decay=args.recursive_decay,
        min_similarity=args.min_similarity,
        target_user_limit=args.target_user_limit,
        shard_count=args.shard_count,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv_check=not args.skip_venv_check,
    )
    print(json.dumps({"status": "PASS", "source_index_manifest": manifest["outputs"]["source_index_manifest"], "candidate_total_count": manifest["candidate_total_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
