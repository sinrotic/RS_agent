from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.recsys.types import RecallCandidate, MergedCandidate

EXPECTED_VIEW_FILES = {
    "manifest": "manifest.json",
    "stats": "stats.json",
    "popular_recall": "popular_recall.jsonl",
    "category_recall_items": "category_recall_items.jsonl",
    "category_top_items": "category_top_items.jsonl",
    "semantic_recall_inputs": "semantic_recall_inputs.jsonl",
    "semantic_inverted_index": "semantic_inverted_index.jsonl",
}
DISABLED_SOURCES = [
    "itemcf_weak",
    "itemcf_strong",
    "item_graph",
    "graph_walk_seed",
    "two_tower",
    "two_tower_seed",
    "usercf_recall",
    "swing_recall",
    "session_transition_recall",
    "implicit_svd_recall",
    "als_mf_recall",
    "bpr_mf_recall",
    "lightfm_recall",
    "multi_interest_recall",
    "pool500",
    "pool1000",
]
ENABLED_SOURCES = ["popular", "category", "semantic"]
MIN_FREE_BYTES = 50 * 1024**3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded representative E2E candidate pass from full lightweight recall views."
    )
    parser.add_argument("--clean-dir", default="data/processed/amazon_2023_recall_clean_full")
    parser.add_argument("--views-dir", default="data/processed/amazon_2023_recall_views_full_lightweight")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--limit-users", type=int, default=500)
    parser.add_argument("--mode", choices=["baseline"], default="baseline")
    parser.add_argument("--candidate-pool-size", type=int, default=200)
    parser.add_argument("--popular-per-user", type=int, default=80)
    parser.add_argument("--category-per-user", type=int, default=80)
    parser.add_argument("--category-per-bucket", type=int, default=40)
    parser.add_argument("--semantic-per-user", type=int, default=40)
    parser.add_argument("--semantic-seed-window", type=int, default=10)
    parser.add_argument("--semantic-min-overlap", type=int, default=1)
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_representative_e2e(
    *,
    clean_dir: Path,
    views_dir: Path,
    output_dir: Path,
    limit_users: int,
    mode: str = "baseline",
    candidate_pool_size: int = 200,
    popular_per_user: int = 80,
    category_per_user: int = 80,
    category_per_bucket: int = 40,
    semantic_per_user: int = 40,
    semantic_seed_window: int = 10,
    semantic_min_overlap: int = 1,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if mode != "baseline":
        raise ValueError("Only --mode baseline is allowed for this runner")
    if limit_users <= 0 or limit_users > 1000:
        raise ValueError("--limit-users must be between 1 and 1000")
    if enforce_venv and ".venv" not in str(Path(sys.executable).resolve()):
        raise RuntimeError(f"Project .venv Python is required, got {sys.executable}")

    clean_dir = clean_dir.resolve()
    views_dir = views_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck_paths(clean_dir, views_dir, output_dir, min_free_bytes)

    sequence_path = clean_dir / "user_sequences.train.jsonl"
    sequences = _load_representative_sequences(sequence_path, limit_users)
    seed_items = _seed_items(sequences, semantic_seed_window)

    view_paths = {name: views_dir / rel_path for name, rel_path in EXPECTED_VIEW_FILES.items()}
    manifest_in = read_json(view_paths["manifest"])
    stats_in = read_json(view_paths["stats"])

    popular, popular_sig = _load_popular_with_signature(
        view_paths["popular_recall"], popular_per_user
    )
    category_top, category_top_sig = _load_category_top_with_signature(view_paths["category_top_items"])
    seed_category_records, category_items_sig = _load_seed_records_with_signature(
        view_paths["category_recall_items"], seed_items
    )
    seed_semantic_records, semantic_inputs_sig = _load_seed_records_with_signature(
        view_paths["semantic_recall_inputs"], seed_items
    )
    semantic_candidates_by_user, semantic_inverted_sig = _semantic_candidates_by_user(
        view_paths["semantic_inverted_index"],
        sequences,
        seed_semantic_records,
        semantic_seed_window,
        semantic_min_overlap,
        semantic_per_user,
    )
    small_artifact_signatures = {
        "manifest": _file_signature(view_paths["manifest"]),
        "stats": _file_signature(view_paths["stats"]),
    }
    source_artifact_signatures = {
        **small_artifact_signatures,
        "popular_recall": popular_sig,
        "category_recall_items": category_items_sig,
        "category_top_items": category_top_sig,
        "semantic_recall_inputs": semantic_inputs_sig,
        "semantic_inverted_index": semantic_inverted_sig,
    }

    config = {
        "mode": mode,
        "limit_users": limit_users,
        "candidate_pool_size": candidate_pool_size,
        "popular_per_user": popular_per_user,
        "category_per_user": category_per_user,
        "category_per_bucket": category_per_bucket,
        "semantic_per_user": semantic_per_user,
        "semantic_seed_window": semantic_seed_window,
        "semantic_min_overlap": semantic_min_overlap,
    }
    candidate_rows: list[dict[str, Any]] = []
    per_user_rows: list[dict[str, Any]] = []
    source_candidate_rows: Counter[str] = Counter()
    source_user_coverage: Counter[str] = Counter()
    source_items: dict[str, set[str]] = defaultdict(set)
    pair_overlap: Counter[str] = Counter()
    candidate_counts: list[int] = []

    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        seen_items = set(str(item) for item in sequence.get("recent_item_sequence", []))
        category_candidates = _category_candidates_for_user(
            sequence,
            category_top,
            seed_category_records,
            category_per_bucket,
            category_per_user,
        )
        semantic_candidates = semantic_candidates_by_user.get(user_id, [])
        raw = [*semantic_candidates, *category_candidates, *popular]
        merged = _merge_preserve_order(raw, seen_items)[:candidate_pool_size]
        candidate_counts.append(len(merged))
        user_sources = set()
        for rank, candidate in enumerate(merged, start=1):
            for source in candidate.sources:
                source_candidate_rows[source] += 1
                source_items[source].add(candidate.item_id)
                user_sources.add(source)
            for pair in _source_pairs(candidate.sources):
                pair_overlap[pair] += 1
            candidate_rows.append(
                {
                    "user_id": user_id,
                    "rank": rank,
                    "item_id": candidate.item_id,
                    "sources": candidate.sources,
                    "source_scores": candidate.source_scores,
                    "category": candidate.category,
                }
            )
        for source in user_sources:
            source_user_coverage[source] += 1
        per_user_rows.append(
            {
                "user_id": user_id,
                "candidate_count": len(merged),
                "sources": sorted(user_sources),
                "recent_item_count": len(seen_items),
            }
        )

    output_dir.mkdir(parents=True)
    candidates_path = output_dir / "candidates.jsonl"
    per_user_path = output_dir / "per_user_source_audit.jsonl"
    source_audit_path = output_dir / "source_audit.json"
    manifest_path = output_dir / "manifest.json"

    audit = {
        "schema_version": "full_lightweight_representative_source_audit_v1",
        "user_count": len(sequences),
        "candidate_row_count": len(candidate_rows),
        "empty_candidate_users": sum(1 for count in candidate_counts if count == 0),
        "empty_candidate_rate": _safe_div(sum(1 for count in candidate_counts if count == 0), len(candidate_counts)),
        "candidate_count_distribution": _distribution(candidate_counts),
        "source_candidate_rows": dict(sorted(source_candidate_rows.items())),
        "source_user_coverage": dict(sorted(source_user_coverage.items())),
        "source_item_coverage": {source: len(items) for source, items in sorted(source_items.items())},
        "source_pair_overlap": dict(sorted(pair_overlap.items())),
    }
    manifest = {
        "schema_version": "full_lightweight_representative_e2e_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "train_only": True,
        "holdout_contract": "No valid/test/holdout target file is read for candidate generation.",
        "resolved_clean_dir": str(clean_dir),
        "resolved_views_dir": str(views_dir),
        "resolved_sequence_path": str(sequence_path.resolve()),
        "output_dir": str(output_dir),
        "enabled_sources": ENABLED_SOURCES,
        "disabled_sources": DISABLED_SOURCES,
        "config": config,
        "input_lightweight_manifest_mode": manifest_in.get("mode"),
        "input_lightweight_skipped_outputs": manifest_in.get("skipped_outputs", []),
        "input_lightweight_source_signature": manifest_in.get("source_signature", {}),
        "input_lightweight_stats_safety": stats_in.get("safety", {}),
        "source_artifact_signatures": source_artifact_signatures,
        "outputs": {
            "candidates": str(candidates_path),
            "per_user_source_audit": str(per_user_path),
            "source_audit": str(source_audit_path),
        },
        "summary": audit,
        "runtime_seconds": round(perf_counter() - started, 6),
    }

    write_jsonl(candidates_path, candidate_rows)
    write_jsonl(per_user_path, per_user_rows)
    write_json(source_audit_path, audit)
    write_json(manifest_path, manifest)
    return manifest


def _precheck_paths(clean_dir: Path, views_dir: Path, output_dir: Path, min_free_bytes: int) -> None:
    if "amazon_2023_recall_views_10000" in str(views_dir):
        raise ValueError("10k recall views cannot be used as this runner's source")
    if "amazon_2023_recall_clean_10000" in str(clean_dir):
        raise ValueError("10k clean data cannot be used as this runner's source")
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    if _is_relative_to(output_dir, clean_dir) or _is_relative_to(output_dir, views_dir):
        raise ValueError("Output directory must not be inside clean_dir or views_dir")
    if not (clean_dir / "user_sequences.train.jsonl").is_file():
        raise FileNotFoundError(clean_dir / "user_sequences.train.jsonl")
    missing = [str(views_dir / rel_path) for rel_path in EXPECTED_VIEW_FILES.values() if not (views_dir / rel_path).is_file() or (views_dir / rel_path).stat().st_size == 0]
    if missing:
        raise FileNotFoundError("Missing or empty full lightweight view files: " + ", ".join(missing))
    disk_root = _existing_ancestor(output_dir.parent)
    free_bytes = shutil.disk_usage(disk_root).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"Insufficient free disk space: {free_bytes} < {min_free_bytes}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    return current


def _load_representative_sequences(path: Path, limit_users: int) -> list[dict[str, Any]]:
    rows = []
    for row in iter_jsonl(path):
        if row.get("user_id"):
            rows.append(row)
        if len(rows) >= limit_users:
            break
    if not rows:
        raise ValueError(f"No representative users found in {path}")
    return rows


def _seed_items(sequences: list[dict[str, Any]], window: int) -> set[str]:
    items = set()
    for sequence in sequences:
        for item in sequence.get("recent_positive_item_sequence", [])[-window:]:
            items.add(str(item))
    return items


def _load_popular_with_signature(path: Path, limit: int) -> tuple[list[RecallCandidate], dict[str, Any]]:
    digest = hashlib.sha256()
    rows = 0
    candidates: list[RecallCandidate] = []
    with path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            if raw_line.strip():
                rows += 1
                if len(candidates) < limit:
                    row = json.loads(raw_line)
                    candidates.append(
                        RecallCandidate(
                            item_id=str(row.get("parent_asin", "")),
                            source="popular",
                            score=float(row.get("pop_score", 0.0) or 0.0),
                            category=str(row.get("category", "")),
                            metadata={"source_rank": rows},
                        )
                    )
    return [candidate for candidate in candidates if candidate.item_id], _signature_payload(path, rows, digest)


def _load_category_top_with_signature(path: Path) -> tuple[dict[str, list[RecallCandidate]], dict[str, Any]]:
    digest = hashlib.sha256()
    rows = 0
    by_bucket: dict[str, list[RecallCandidate]] = {}
    with path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            rows += 1
            row = json.loads(raw_line)
            bucket = str(row.get("bucket", ""))
            by_bucket[bucket] = [
                RecallCandidate(
                    item_id=str(item.get("parent_asin", "")),
                    source="category",
                    score=float(item.get("score", 0.0) or 0.0),
                    metadata={"bucket": bucket, "source_rank": index},
                )
                for index, item in enumerate(row.get("top_items", []), start=1)
                if item.get("parent_asin")
            ]
    return by_bucket, _signature_payload(path, rows, digest)


def _load_seed_records_with_signature(path: Path, seed_items: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    digest = hashlib.sha256()
    rows = 0
    records: dict[str, dict[str, Any]] = {}
    with path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            rows += 1
            row = json.loads(raw_line)
            item_id = str(row.get("parent_asin", ""))
            if item_id in seed_items:
                records[item_id] = row
    return records, _signature_payload(path, rows, digest)


def _semantic_candidates_by_user(
    path: Path,
    sequences: list[dict[str, Any]],
    seed_records: dict[str, dict[str, Any]],
    seed_window: int,
    min_overlap: int,
    per_user: int,
) -> tuple[dict[str, list[RecallCandidate]], dict[str, Any]]:
    user_tokens: dict[str, set[str]] = {}
    token_to_users: dict[str, set[str]] = defaultdict(set)
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        tokens: set[str] = set()
        for item_id in list(dict.fromkeys(reversed(sequence.get("recent_positive_item_sequence", [])[-seed_window:]))):
            record = seed_records.get(str(item_id))
            if record:
                tokens.update(_semantic_tokens(record))
        user_tokens[user_id] = tokens
        for token in tokens:
            token_to_users[token].add(user_id)

    candidate_scores: dict[str, Counter[str]] = {str(sequence.get("user_id", "")): Counter() for sequence in sequences}
    seen_by_user = {
        str(sequence.get("user_id", "")): set(str(item) for item in sequence.get("recent_item_sequence", []))
        for sequence in sequences
    }
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            rows += 1
            row = json.loads(raw_line)
            token = str(row.get("token", ""))
            users = token_to_users.get(token)
            if not users:
                continue
            parent_asins = [str(item) for item in row.get("parent_asins", [])]
            for user_id in users:
                seen = seen_by_user[user_id]
                for item_id in parent_asins:
                    if item_id and item_id not in seen:
                        candidate_scores[user_id][item_id] += 1

    by_user = {}
    for user_id, scores in candidate_scores.items():
        rows_for_user = []
        for item_id, overlap in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
            if overlap < min_overlap:
                continue
            rows_for_user.append(
                RecallCandidate(
                    item_id=item_id,
                    source="semantic",
                    score=float(overlap),
                    metadata={"semantic_token_overlap": overlap},
                )
            )
            if len(rows_for_user) >= per_user:
                break
        by_user[user_id] = rows_for_user
    return by_user, _signature_payload(path, rows, digest)


def _category_candidates_for_user(
    sequence: dict[str, Any],
    category_top: dict[str, list[RecallCandidate]],
    seed_records: dict[str, dict[str, Any]],
    per_bucket: int,
    per_user: int,
) -> list[RecallCandidate]:
    buckets = []
    for item_id in reversed(sequence.get("recent_positive_item_sequence", [])):
        record = seed_records.get(str(item_id))
        if not record:
            continue
        for bucket in _category_buckets(record):
            if bucket not in buckets:
                buckets.append(bucket)
    rows: list[RecallCandidate] = []
    for bucket in buckets:
        rows.extend(category_top.get(bucket, [])[:per_bucket])
        if len(rows) >= per_user:
            return rows[:per_user]
    return rows[:per_user]


def _category_buckets(record: dict[str, Any]) -> list[str]:
    values = [record.get("main_category"), record.get("category")]
    values.extend(record.get("source_categories", []) or [])
    values.extend(record.get("categories_flat", []) or [])
    buckets = []
    for value in values:
        text = str(value).strip()
        if text and f"main::{text}" not in buckets:
            buckets.append(f"main::{text}")
    return buckets


def _semantic_tokens(row: dict[str, Any]) -> set[str]:
    fields = ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"]
    text_parts: list[str] = []
    for field in fields:
        value = row.get(field, "")
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        else:
            text_parts.append(str(value))
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(text_parts).lower()) if len(token) >= 3}


def _merge_preserve_order(candidates: Iterable[RecallCandidate], seen_items: set[str]) -> list[MergedCandidate]:
    merged: dict[str, MergedCandidate] = {}
    for candidate in candidates:
        if not candidate.item_id or candidate.item_id in seen_items:
            continue
        current = merged.get(candidate.item_id)
        if current is None:
            current = MergedCandidate(
                item_id=candidate.item_id,
                sources=[],
                source_scores={},
                category=candidate.category,
                metadata=dict(candidate.metadata),
            )
            merged[candidate.item_id] = current
        if candidate.source not in current.sources:
            current.sources.append(candidate.source)
        current.source_scores[candidate.source] = max(
            float(current.source_scores.get(candidate.source, 0.0)), candidate.score
        )
        if not current.category:
            current.category = candidate.category
        current.metadata.update({k: v for k, v in candidate.metadata.items() if k not in current.metadata})
    return list(merged.values())


def _source_pairs(sources: list[str]) -> list[str]:
    rows = []
    ordered = sorted(set(sources))
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            rows.append(f"{left}+{right}")
    return rows


def _distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p50": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "max": ordered[-1],
        "avg": round(sum(ordered) / len(ordered), 6),
    }


def _percentile(ordered: list[int], q: float) -> int:
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[index]


def _safe_div(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            if raw_line.strip():
                rows += 1
    return _signature_payload(path, rows, digest)


def _signature_payload(path: Path, rows: int, digest: hashlib._Hash) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "row_count": rows,
        "sha256": digest.hexdigest(),
    }


def main() -> None:
    args = parse_args()
    manifest = run_representative_e2e(
        clean_dir=Path(args.clean_dir),
        views_dir=Path(args.views_dir),
        output_dir=Path(args.output_dir),
        limit_users=args.limit_users,
        mode=args.mode,
        candidate_pool_size=args.candidate_pool_size,
        popular_per_user=args.popular_per_user,
        category_per_user=args.category_per_user,
        category_per_bucket=args.category_per_bucket,
        semantic_per_user=args.semantic_per_user,
        semantic_seed_window=args.semantic_seed_window,
        semantic_min_overlap=args.semantic_min_overlap,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(f"Representative full-lightweight candidates written to: {manifest['output_dir']}")
    print(f"Manifest written to: {Path(manifest['output_dir']) / 'manifest.json'}")
    print(f"Candidate rows: {manifest['summary']['candidate_row_count']}")


if __name__ == "__main__":
    main()
