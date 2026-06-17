from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_popular_recent2y_source_v1"
DATASET_SCHEMA_VERSION = "pool500_popular_recent2y_method_dataset_v1"
EVAL_SCHEMA_VERSION = "pool500_popular_recent2y_eval_v1"
RECENT_2Y_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
GOVERNANCE_MANIFEST = RECENT_2Y_ROOT / "train_only_governance" / "manifest.json"
DATASET_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_datasets" / "recent_2y" / "popular"
SOURCE_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources" / "recent_2y" / "popular"
FORBIDDEN_TOKENS = ("holdout", "lopo", "oracle", "eval_label", "clean_10000", "pool1000")
EVAL_FORBIDDEN_FOR_BUILD = (*FORBIDDEN_TOKENS, "valid", "test")
DEFAULT_KS = (10, 50, 100, 500)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build recent-2y train-only popular source for pool500 recall.")
    parser.add_argument("--scale-tier", choices=("smoke", "formal"), required=True)
    parser.add_argument("--governance-manifest", default=str(GOVERNANCE_MANIFEST))
    parser.add_argument("--dataset-output-root", default=str(DATASET_OUTPUT_ROOT))
    parser.add_argument("--source-output-root", default=str(SOURCE_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--smoke-top-n", type=int, default=500)
    parser.add_argument("--formal-top-n", type=int, default=0, help="0 means keep all train-frequency items.")
    parser.add_argument("--eval-user-limit", type=int, default=0, help="0 means full eval for formal; smoke defaults to 500.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_popular_recent2y(
    *,
    scale_tier: str,
    governance_manifest_path: Path = GOVERNANCE_MANIFEST,
    dataset_output_root: Path = DATASET_OUTPUT_ROOT,
    source_output_root: Path = SOURCE_OUTPUT_ROOT,
    run_id: str | None = None,
    smoke_top_n: int = 500,
    formal_top_n: int = 0,
    eval_user_limit: int = 0,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    if scale_tier not in {"smoke", "formal"}:
        raise ValueError(f"unsupported scale_tier: {scale_tier}")

    run_id = run_id or f"popular_recent2y_{scale_tier}_v1"
    governance_manifest_path = Path(governance_manifest_path).resolve()
    governance = read_json(governance_manifest_path)
    if governance.get("schema_version") != "train_only_data_governance_v1" or governance.get("train_only") is not True:
        raise ValueError("governance manifest must be train_only_data_governance_v1 and train_only=true")

    artifacts = governance.get("artifacts") if isinstance(governance.get("artifacts"), dict) else {}
    item_frequency_path = _resolve_path(governance_manifest_path, artifacts.get("item_frequency_train"))
    user_quality_path = _resolve_path(governance_manifest_path, artifacts.get("user_quality_profile"))
    if item_frequency_path is None or not item_frequency_path.is_file():
        raise FileNotFoundError(f"missing item_frequency_train: {item_frequency_path}")

    dataset_dir = Path(dataset_output_root).resolve() / scale_tier / run_id
    source_dir = Path(source_output_root).resolve() / scale_tier / run_id
    _prepare_output_dir(dataset_dir, overwrite)
    _prepare_output_dir(source_dir, overwrite)

    source_limit = smoke_top_n if scale_tier == "smoke" else formal_top_n
    purpose = "program_and_schema_validation_only" if scale_tier == "smoke" else "official_method_logic_dataset_under_recent_2y_train_only_governance"
    candidates = _load_popular_rows(item_frequency_path, limit=source_limit)
    if not candidates:
        raise ValueError("popular candidates are empty")

    dataset_rows_path = dataset_dir / "method_dataset_rows.jsonl"
    candidates_path = source_dir / "candidates.jsonl"
    _write_jsonl(dataset_rows_path, candidates)
    _write_jsonl(candidates_path, candidates)

    input_hashes = {
        "governance_manifest_sha256": _sha256_file(governance_manifest_path),
        "item_frequency_train_sha256": _sha256_file(item_frequency_path),
    }
    build_inputs = [governance_manifest_path, item_frequency_path]
    candidate_generation_allowed = scale_tier == "formal"
    no_holdout_audit = _build_no_holdout_audit(build_inputs, candidate_generation_allowed=candidate_generation_allowed)
    resource_audit = {
        "schema_version": "pool500_popular_recent2y_resource_audit_v1",
        "status": "PASS",
        "source": "popular",
        "scale_tier": scale_tier,
        "heavy_job": False,
        "resource_profile": "local_train_only_frequency_sort",
        "input_row_count": _jsonl_row_count(item_frequency_path),
        "candidate_row_count": len(candidates),
        "runtime_seconds_until_resource_audit": round(perf_counter() - started, 6),
        "candidate_generation_allowed": candidate_generation_allowed,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }
    coverage_audit = _build_coverage_audit(candidates, candidate_generation_allowed=candidate_generation_allowed)
    undercoverage_audit = {
        "schema_version": "pool500_popular_recent2y_undercoverage_audit_v1",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "source": "popular",
        "scope": "global_popular_source_has_no_per_user_target_list_until_merge_time",
        "primary_risk": "popular can overfill sparse users but remains weak for personalization and long-tail coverage",
        "candidate_generation_allowed": candidate_generation_allowed,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }

    method_dataset_manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "status": "PASS",
        "source": "popular",
        "scale_tier": scale_tier,
        "run_id": run_id,
        "purpose": purpose,
        "train_only": True,
        "dataset_policy": "recent_2y_train_only_popular_frequency_dataset",
        "output_dir": str(dataset_dir),
        "method_dataset_rows_path": str(dataset_rows_path),
        "row_count": len(candidates),
        "rank_policy": "sort_by_frequency_desc_parent_asin_asc",
        "lineage": _lineage(governance_manifest_path, item_frequency_path, input_hashes),
        "allowed_input_scopes": ["recent_2y_train_only_governance", "item_frequency_train"],
        "forbidden_input_scopes": list(EVAL_FORBIDDEN_FOR_BUILD),
        "candidate_generation_allowed": candidate_generation_allowed,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    write_json(dataset_dir / "method_dataset_manifest.json", method_dataset_manifest)

    eval_limit = eval_user_limit or (500 if scale_tier == "smoke" else 0)
    evaluation_report = _evaluate_popular(
        candidates=candidates,
        governance=governance,
        user_quality_path=user_quality_path,
        max_k=max(DEFAULT_KS),
        eval_user_limit=eval_limit,
        smoke_only=scale_tier == "smoke",
    )

    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if no_holdout_audit["status"] == "PASS" else "BLOCKED",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "popular",
        "canonical_source": "popular",
        "source_status": "READY",
        "scale_tier": scale_tier,
        "run_id": run_id,
        "role": "recent_2y_train_only_popular_fallback_source",
        "train_only": True,
        "output_dir": str(source_dir),
        "method_dataset_manifest_path": str(dataset_dir / "method_dataset_manifest.json"),
        "candidates_path": str(candidates_path),
        "candidate_row_count": len(candidates),
        "unique_item_count": len({row["parent_asin"] for row in candidates}),
        "rank_policy": "sort_by_frequency_desc_parent_asin_asc",
        "lineage": _lineage(governance_manifest_path, item_frequency_path, input_hashes),
        "artifact_sha256": {
            "candidates": _sha256_file(candidates_path),
            "method_dataset_rows": _sha256_file(dataset_rows_path),
        },
        "outputs": {
            "source_index_manifest": str(source_dir / "source_index_manifest.json"),
            "candidates": str(candidates_path),
            "coverage_audit": str(source_dir / "coverage_audit.json"),
            "undercoverage_audit": str(source_dir / "undercoverage_audit.json"),
            "resource_audit": str(source_dir / "resource_audit.json"),
            "no_holdout_audit": str(source_dir / "no_holdout_audit.json"),
            "evaluation_report": str(source_dir / "evaluation_report.json"),
        },
        "audit_statuses": {
            "coverage_audit": coverage_audit["status"],
            "undercoverage_audit": undercoverage_audit["status"],
            "resource_audit": resource_audit["status"],
            "no_holdout_audit": no_holdout_audit["status"],
            "evaluation_report": evaluation_report["status"],
            "method_dataset_manifest": method_dataset_manifest["status"],
        },
        "candidate_generation_allowed": candidate_generation_allowed,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }

    write_json(source_dir / "coverage_audit.json", coverage_audit)
    write_json(source_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(source_dir / "resource_audit.json", resource_audit)
    write_json(source_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(source_dir / "evaluation_report.json", evaluation_report)
    write_json(source_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _load_popular_rows(path: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    raw_rows = []
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "").strip()
        frequency = int(row.get("frequency") or 0)
        if not item_id or frequency <= 0:
            continue
        raw_rows.append(row)
    raw_rows.sort(key=lambda row: (-int(row.get("frequency") or 0), str(row.get("parent_asin") or "")))
    if limit > 0:
        raw_rows = raw_rows[:limit]
    candidates = []
    for rank, row in enumerate(raw_rows, start=1):
        frequency = int(row.get("frequency") or 0)
        item_id = str(row.get("parent_asin") or "")
        category = str(row.get("category") or "UNKNOWN")
        candidates.append(
            {
                "rank": rank,
                "parent_asin": item_id,
                "item_id": item_id,
                "source": "popular",
                "score": float(frequency),
                "frequency": frequency,
                "user_count": int(row.get("user_count") or frequency),
                "category": category,
                "store": row.get("store"),
                "is_long_tail": bool(row.get("is_long_tail")),
                "metadata": {
                    "rank_policy": "sort_by_frequency_desc_parent_asin_asc",
                    "category": category,
                    "store": row.get("store"),
                    "train_frequency": frequency,
                    "is_long_tail": bool(row.get("is_long_tail")),
                },
            }
        )
    return candidates


def _evaluate_popular(
    *,
    candidates: list[dict[str, Any]],
    governance: dict[str, Any],
    user_quality_path: Path | None,
    max_k: int,
    eval_user_limit: int,
    smoke_only: bool,
) -> dict[str, Any]:
    dataset_root = Path(str(governance["lineage"]["input_files"]["clean_manifest"])).parent
    recent_manifest = read_json(dataset_root / "manifest.json")
    split_paths = recent_manifest.get("split_paths") or {}
    valid_path = Path(split_paths["valid"])
    test_path = Path(split_paths["test"])
    train_sequences_path = Path(recent_manifest["train_user_sequences_path"])

    positives_by_user: dict[str, list[str]] = defaultdict(list)
    positives_by_split: dict[str, dict[str, list[str]]] = {"valid": defaultdict(list), "test": defaultdict(list)}
    for split, path in (("valid", valid_path), ("test", test_path)):
        for row in iter_jsonl(path):
            if not row.get("label_binary"):
                continue
            user_id = str(row.get("user_id") or "")
            item_id = str(row.get("parent_asin") or "")
            if not user_id or not item_id:
                continue
            if eval_user_limit and user_id not in positives_by_user and len(positives_by_user) >= eval_user_limit:
                continue
            positives_by_user[user_id].append(item_id)
            positives_by_split[split][user_id].append(item_id)
    eval_users = sorted(positives_by_user)
    eval_user_set = set(eval_users)
    train_seen = _load_train_seen(train_sequences_path, eval_user_set)
    user_buckets = _load_user_buckets(user_quality_path, eval_user_set) if user_quality_path else {}

    top_items = [row["parent_asin"] for row in candidates]
    item_long_tail = {row["parent_asin"]: bool(row.get("is_long_tail")) for row in candidates}
    item_universe = set(top_items)
    ks = [k for k in DEFAULT_KS if k <= max_k]
    overall = _metric_bucket(eval_users, positives_by_user, top_items, train_seen, item_universe, item_long_tail, ks)

    by_split = {
        split: _metric_bucket(sorted(split_users), split_users, top_items, train_seen, item_universe, item_long_tail, ks)
        for split, split_users in positives_by_split.items()
    }
    users_by_bucket: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for user_id, items in positives_by_user.items():
        bucket = user_buckets.get(user_id, "UNKNOWN")
        users_by_bucket[bucket][user_id].extend(items)
    by_user_bucket = {
        bucket: _metric_bucket(sorted(bucket_users), bucket_users, top_items, train_seen, item_universe, item_long_tail, ks)
        for bucket, bucket_users in sorted(users_by_bucket.items())
    }
    candidate_counts = [len(_filtered_candidates(top_items, train_seen.get(user_id, set()), max_k)) for user_id in eval_users]
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "status": "PASS",
        "source": "popular",
        "smoke_only": smoke_only,
        "evaluation_label_use": "metrics_only_not_candidate_generation_or_training",
        "eval_user_limit": eval_user_limit,
        "eval_user_count": len(eval_users),
        "positive_event_count": sum(len(items) for items in positives_by_user.values()),
        "k_values": ks,
        "candidate_count_per_user_at_500": _summary(candidate_counts),
        "overall": overall,
        "by_split": by_split,
        "by_user_quality_bucket": by_user_bucket,
        "read_files": {
            "valid": str(valid_path),
            "test": str(test_path),
            "train_sequences_for_seen_filter_only": str(train_sequences_path),
            "user_quality_for_bucket_only": str(user_quality_path) if user_quality_path else None,
        },
        "candidate_generation_allowed": not smoke_only,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }


def _metric_bucket(
    users: list[str],
    positives_by_user: dict[str, list[str]],
    top_items: list[str],
    train_seen: dict[str, set[str]],
    item_universe: set[str],
    item_long_tail: dict[str, bool],
    ks: list[int],
) -> dict[str, Any]:
    hits = {k: 0 for k in ks}
    users_with_hit = {k: 0 for k in ks}
    positive_count = 0
    in_universe_positive_count = 0
    in_universe_hits = {k: 0 for k in ks}
    long_tail_positive_count = 0
    long_tail_hits = {k: 0 for k in ks}
    for user_id in users:
        positives = positives_by_user.get(user_id, [])
        if not positives:
            continue
        positive_count += len(positives)
        per_user_hit = {k: False for k in ks}
        seen = train_seen.get(user_id, set())
        filtered_by_k = {k: set(_filtered_candidates(top_items, seen, k)) for k in ks}
        for item_id in positives:
            in_universe = item_id in item_universe
            if in_universe:
                in_universe_positive_count += 1
            is_long_tail = item_long_tail.get(item_id, False)
            if is_long_tail:
                long_tail_positive_count += 1
            for k in ks:
                if item_id in filtered_by_k[k]:
                    hits[k] += 1
                    per_user_hit[k] = True
                    if in_universe:
                        in_universe_hits[k] += 1
                    if is_long_tail:
                        long_tail_hits[k] += 1
        for k in ks:
            if per_user_hit[k]:
                users_with_hit[k] += 1
    return {
        "user_count": len(users),
        "positive_event_count": positive_count,
        "in_train_candidate_universe_positive_count": in_universe_positive_count,
        "long_tail_positive_count": long_tail_positive_count,
        "recall_at_k": {str(k): _ratio(hits[k], positive_count) for k in ks},
        "hit_rate_at_k": {str(k): _ratio(users_with_hit[k], len(users)) for k in ks},
        "in_universe_recall_at_k": {str(k): _ratio(in_universe_hits[k], in_universe_positive_count) for k in ks},
        "long_tail_recall_at_k": {str(k): _ratio(long_tail_hits[k], long_tail_positive_count) for k in ks},
    }


def _filtered_candidates(top_items: list[str], seen: set[str], k: int) -> list[str]:
    result = []
    for item_id in top_items:
        if item_id in seen:
            continue
        result.append(item_id)
        if len(result) >= k:
            break
    return result


def _load_train_seen(path: Path, eval_users: set[str]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {user_id: set() for user_id in eval_users}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id not in seen:
            continue
        for item_id in row.get("recent_item_sequence") or []:
            if item_id:
                seen[user_id].add(str(item_id))
    return seen


def _load_user_buckets(path: Path, eval_users: set[str]) -> dict[str, str]:
    buckets = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id in eval_users:
            buckets[user_id] = str(row.get("quality_bucket_v2") or row.get("quality_bucket") or "UNKNOWN")
    return buckets


def _build_coverage_audit(candidates: list[dict[str, Any]], *, candidate_generation_allowed: bool) -> dict[str, Any]:
    categories = Counter(str(row.get("category") or "UNKNOWN") for row in candidates)
    long_tail_count = sum(1 for row in candidates if row.get("is_long_tail"))
    return {
        "schema_version": "pool500_popular_recent2y_coverage_audit_v1",
        "status": "PASS",
        "source": "popular",
        "candidate_row_count": len(candidates),
        "unique_item_count": len({row["parent_asin"] for row in candidates}),
        "category_bucket_count": len(categories),
        "category_bucket_top10": [
            {"category": category, "row_count": count, "share": _ratio(count, len(candidates))}
            for category, count in categories.most_common(10)
        ],
        "long_tail_candidate_count": long_tail_count,
        "long_tail_candidate_share": _ratio(long_tail_count, len(candidates)),
        "recommended_max_source_share": 0.2,
        "candidate_generation_allowed": candidate_generation_allowed,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }


def _build_no_holdout_audit(read_files: list[Path], *, candidate_generation_allowed: bool) -> dict[str, Any]:
    forbidden = _forbidden_matches(read_files, EVAL_FORBIDDEN_FOR_BUILD)
    return {
        "schema_version": "pool500_popular_recent2y_no_holdout_audit_v1",
        "status": "PASS" if not forbidden else "BLOCKED",
        "source": "popular",
        "train_only": True,
        "read_files_for_build": [str(path) for path in read_files],
        "forbidden_inputs": forbidden,
        "uses_valid_for_build": False,
        "uses_test_for_build": False,
        "uses_holdout": False,
        "uses_lopo": False,
        "uses_oracle": False,
        "uses_eval_label": False,
        "candidate_generation_allowed": candidate_generation_allowed,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }


def _lineage(governance_manifest_path: Path, item_frequency_path: Path, input_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "dataset_root": str(RECENT_2Y_ROOT),
        "governance_manifest_path": str(governance_manifest_path),
        "item_frequency_train_path": str(item_frequency_path),
        "input_hashes": input_hashes,
        "train_only": True,
        "forbidden_scopes": list(EVAL_FORBIDDEN_FOR_BUILD),
    }


def _resolve_path(relative_to: Path, value: Any) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    return (relative_to.parent / path).resolve()


def _prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=False)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _jsonl_row_count(path: Path) -> int:
    count = 0
    for _ in iter_jsonl(path):
        count += 1
    return count


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _forbidden_matches(paths: list[Path], tokens: tuple[str, ...]) -> list[str]:
    matches = []
    for path in paths:
        normalized = str(path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part]
        if any(token in parts or f"_{token}_" in normalized or f".{token}." in normalized for token in tokens):
            matches.append(str(path))
    return matches


def _summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "mean": 0.0, "max": 0}
    return {"min": min(values), "p50": median(values), "mean": round(mean(values), 6), "max": max(values)}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def main() -> None:
    args = parse_args()
    manifest = build_popular_recent2y(
        scale_tier=args.scale_tier,
        governance_manifest_path=Path(args.governance_manifest),
        dataset_output_root=Path(args.dataset_output_root),
        source_output_root=Path(args.source_output_root),
        run_id=args.run_id or None,
        smoke_top_n=args.smoke_top_n,
        formal_top_n=args.formal_top_n,
        eval_user_limit=args.eval_user_limit,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"source_index_manifest": manifest["outputs"]["source_index_manifest"], "status": manifest["status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
