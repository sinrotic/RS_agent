from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_label_coverage_diagnostic_v1"
DEFAULT_OUTPUT_NAME = "pool500_label_coverage_report.json"
TOP_K_BUCKETS = (20, 50, 100, 500)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose pool500 candidate coverage against valid/test positive labels without changing recall or ranking inputs.")
    parser.add_argument("--pool500-candidates", required=True)
    parser.add_argument("--label", action="append", required=True, help="canonical_interactions.valid/test JSONL label input; repeat for valid and test.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def diagnose_pool500_label_coverage(
    *,
    pool500_candidates_path: Path,
    label_paths: Iterable[Path],
    output_dir: Path,
    output_name: str = DEFAULT_OUTPUT_NAME,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    pool500_candidates_path = pool500_candidates_path.resolve()
    label_paths = [path.resolve() for path in label_paths]
    output_dir = output_dir.resolve()
    output_path = output_dir / output_name
    _precheck(pool500_candidates_path, label_paths, output_path, overwrite)

    candidate_index, candidate_summary = _load_candidate_index(pool500_candidates_path)
    label_summary = _scan_labels(label_paths, candidate_index)
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool500_candidates_path": str(pool500_candidates_path),
        "label_paths": [str(path) for path in label_paths],
        "output_path": str(output_path),
        "candidate": candidate_summary,
        "labels": label_summary,
        "diagnostic_only": True,
        "label_inputs_role": "evaluation_only_valid_test_labels_not_recall_generation_inputs",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_path, report)
    return report


def _precheck(pool500_candidates_path: Path, label_paths: list[Path], output_path: Path, overwrite: bool) -> None:
    if not pool500_candidates_path.is_file():
        raise FileNotFoundError(f"pool500 candidate path does not exist or is not a file: {pool500_candidates_path}")
    if not label_paths:
        raise ValueError("At least one label path is required")
    for path in label_paths:
        if not path.is_file():
            raise FileNotFoundError(f"label path does not exist or is not a file: {path}")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}")


def _load_candidate_index(path: Path) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    by_user: dict[str, dict[str, int]] = defaultdict(dict)
    candidate_items: set[str] = set()
    source_counts: Counter[str] = Counter()
    row_count = 0
    skipped_missing_key_count = 0
    duplicate_user_item_count = 0
    max_rank_by_user: Counter[str] = Counter()
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        row_count += 1
        user_id = _string_value(row, "user_id", "user")
        item_id = _string_value(row, "parent_asin", "item_id", "item")
        if not user_id or not item_id:
            skipped_missing_key_count += 1
            continue
        rank = _rank_value(row, row_number)
        existing_rank = by_user[user_id].get(item_id)
        if existing_rank is None:
            by_user[user_id][item_id] = rank
        else:
            duplicate_user_item_count += 1
            if rank < existing_rank:
                by_user[user_id][item_id] = rank
        candidate_items.add(item_id)
        max_rank_by_user[user_id] = max(max_rank_by_user[user_id], rank)
        source = _string_value(row, "source", "canonical_source") or "unknown"
        source_counts[source] += 1
    if not by_user:
        raise ValueError(f"Candidate file has no usable rows: {path}")
    return dict(by_user), {
        "row_count": row_count,
        "candidate_users": len(by_user),
        "candidate_items": len(candidate_items),
        "candidate_user_item_pairs": sum(len(items) for items in by_user.values()),
        "skipped_missing_key_count": skipped_missing_key_count,
        "duplicate_user_item_count": duplicate_user_item_count,
        "source_counts": dict(sorted(source_counts.items())),
        "max_rank_distribution": dict(sorted(Counter(max_rank_by_user.values()).items())),
    }


def _scan_labels(label_paths: list[Path], candidate_index: dict[str, dict[str, int]]) -> dict[str, Any]:
    label_users: set[str] = set()
    positive_users: set[str] = set()
    overlap_users: set[str] = set()
    seen_positive_pairs: set[tuple[str, str]] = set()
    hit_distribution = {f"top_{top_k}": 0 for top_k in TOP_K_BUCKETS}
    missing_reason_counts: Counter[str] = Counter()
    label_source_counts: Counter[str] = Counter()
    row_count = 0
    usable_join_key_row_count = 0
    positive_count = 0
    skipped_missing_key_count = 0
    skipped_non_positive_count = 0
    positive_overlap_count = 0

    for label_path in label_paths:
        for row in iter_jsonl(label_path):
            row_count += 1
            label_source_counts[_label_source(label_path, row)] += 1
            user_id = _string_value(row, "user_id", "user")
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            if not user_id or not item_id:
                skipped_missing_key_count += 1
                continue
            usable_join_key_row_count += 1
            label_users.add(user_id)
            if user_id in candidate_index:
                overlap_users.add(user_id)
            if not _is_positive_label(row):
                skipped_non_positive_count += 1
                continue
            pair = (user_id, item_id)
            if pair in seen_positive_pairs:
                continue
            seen_positive_pairs.add(pair)
            positive_count += 1
            positive_users.add(user_id)
            user_candidates = candidate_index.get(user_id)
            if user_candidates is None:
                missing_reason_counts["user_missing"] += 1
                continue
            rank = user_candidates.get(item_id)
            if rank is None:
                missing_reason_counts["item_not_in_candidate"] += 1
                continue
            positive_overlap_count += 1
            missing_reason_counts["hit"] += 1
            for top_k in TOP_K_BUCKETS:
                if rank <= top_k:
                    hit_distribution[f"top_{top_k}"] += 1

    return {
        "row_count": row_count,
        "usable_join_key_row_count": usable_join_key_row_count,
        "label_users": len(label_users),
        "label_positive_users": len(positive_users),
        "label_positives": positive_count,
        "overlap_users": len(overlap_users),
        "positive_overlap_count": positive_overlap_count,
        "positive_coverage": _safe_ratio(positive_overlap_count, positive_count),
        "user_coverage": _safe_ratio(len(overlap_users), len(label_users)),
        "hit_distribution": hit_distribution,
        "missing_reason_counts": dict(sorted(missing_reason_counts.items())),
        "label_source_counts": dict(sorted(label_source_counts.items())),
        "skipped_missing_key_count": skipped_missing_key_count,
        "skipped_non_positive_count": skipped_non_positive_count,
        "positive_dedup_key": "user_id,parent_asin",
    }


def _string_value(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value) != "":
            return str(value)
    return ""


def _rank_value(row: dict[str, Any], fallback: int) -> int:
    value = row.get("rank")
    if value is None:
        return fallback
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return fallback
    return rank if rank > 0 else fallback


def _is_positive_label(row: dict[str, Any]) -> bool:
    if "label_binary" in row:
        return int(row.get("label_binary") or 0) == 1
    if "label" in row:
        return int(row.get("label") or 0) == 1
    return True


def _label_source(path: Path, row: dict[str, Any]) -> str:
    split = _string_value(row, "split")
    if split:
        return split
    name = path.name
    if ".valid" in name or name.startswith("valid"):
        return "valid"
    if ".test" in name or name.startswith("test"):
        return "test"
    return name


def _safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def main() -> None:
    args = parse_args()
    report = diagnose_pool500_label_coverage(
        pool500_candidates_path=Path(args.pool500_candidates),
        label_paths=[Path(path) for path in args.label],
        output_dir=Path(args.output_dir),
        output_name=args.output_name,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
