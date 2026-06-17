from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_usercf_raw_vs_filtered_reachability_v1"
SOURCE = "usercf_recall"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "manifest.json"
DEFAULT_METHOD_DATASET_MANIFEST = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_datasets"
    / "recent_2y"
    / "usercf_sciomc_v1"
    / "formal"
    / "usercf_method_dataset"
    / "method_dataset_manifest.json"
)
DEFAULT_SOURCE_INDEX_MANIFEST = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_sources"
    / "recent_2y"
    / SOURCE
    / "usercf_recent_2y_sciomc_formal_v1"
    / "source_index_manifest.json"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_diagnostics"
    / "recent_2y"
    / SOURCE
    / "raw_vs_filtered_reachability_v1"
)
POSITIVE_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")
FORBIDDEN_GENERATION_INPUTS = ("holdout", "valid", "test", "LOPO", "oracle", "eval_label")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose usercf_recall recent-2y raw-vs-filtered reachability. "
            "Train data builds neighbor universes; valid/test labels are evaluation-only."
        )
    )
    parser.add_argument("--clean-manifest", type=Path, default=DEFAULT_CLEAN_MANIFEST)
    parser.add_argument("--method-dataset-manifest", type=Path, default=DEFAULT_METHOD_DATASET_MANIFEST)
    parser.add_argument("--source-index-manifest", type=Path, default=DEFAULT_SOURCE_INDEX_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-user-limit", type=int, default=1000, help="Bounded diagnostic target users; 0 means all method-dataset users.")
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--similar-users-top-k", type=int, default=200)
    parser.add_argument("--candidate-top-k-per-user", type=int, default=500)
    parser.add_argument("--max-raw-item-user-freq", type=int, default=5000)
    parser.add_argument("--max-filtered-item-user-freq", type=int, default=5000)
    parser.add_argument("--label-splits", default="valid,test")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = diagnose_usercf_raw_vs_filtered_reachability(
        clean_manifest_path=args.clean_manifest,
        method_dataset_manifest_path=args.method_dataset_manifest,
        source_index_manifest_path=args.source_index_manifest,
        output_dir=args.output_dir,
        target_user_limit=args.target_user_limit,
        max_items_per_user=args.max_items_per_user,
        similar_users_top_k=args.similar_users_top_k,
        candidate_top_k_per_user=args.candidate_top_k_per_user,
        max_raw_item_user_freq=args.max_raw_item_user_freq,
        max_filtered_item_user_freq=args.max_filtered_item_user_freq,
        label_splits=_split_csv(args.label_splits),
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": report["status"], "report_path": report["report_path"], "metrics": report["metrics"]}, ensure_ascii=False, indent=2))


def diagnose_usercf_raw_vs_filtered_reachability(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    method_dataset_manifest_path: Path = DEFAULT_METHOD_DATASET_MANIFEST,
    source_index_manifest_path: Path = DEFAULT_SOURCE_INDEX_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    target_user_limit: int = 1000,
    max_items_per_user: int = 80,
    similar_users_top_k: int = 200,
    candidate_top_k_per_user: int = 500,
    max_raw_item_user_freq: int = 5000,
    max_filtered_item_user_freq: int = 5000,
    label_splits: Iterable[str] = ("valid", "test"),
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    _validate_positive_caps(
        target_user_limit=target_user_limit,
        max_items_per_user=max_items_per_user,
        similar_users_top_k=similar_users_top_k,
        candidate_top_k_per_user=candidate_top_k_per_user,
        max_raw_item_user_freq=max_raw_item_user_freq,
        max_filtered_item_user_freq=max_filtered_item_user_freq,
    )
    clean_manifest_path = _resolve_path(clean_manifest_path)
    method_dataset_manifest_path = _resolve_path(method_dataset_manifest_path)
    source_index_manifest_path = _resolve_path(source_index_manifest_path)
    output_dir = _resolve_path(output_dir)
    _prepare_output_dir(output_dir, overwrite)

    method_manifest, method_rows_path = _resolve_method_dataset_rows(method_dataset_manifest_path)
    clean_manifest = read_json(clean_manifest_path)
    source_manifest = read_json(source_index_manifest_path)
    source_candidates_path = _resolve_source_candidates_path(source_index_manifest_path, source_manifest)

    filtered_graph = _load_filtered_graph(
        method_rows_path,
        max_items_per_user=max_items_per_user,
        target_user_limit=target_user_limit,
        max_item_user_freq=max_filtered_item_user_freq,
    )
    target_user_ids = filtered_graph["target_user_ids"]
    labels_by_user, label_paths = _load_eval_only_labels(clean_manifest, label_splits, set(target_user_ids))
    raw_graph = _load_raw_train_graph_for_targets(
        clean_manifest,
        target_user_ids,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_raw_item_user_freq,
    )
    final_candidates_by_user = _load_final_candidates(source_candidates_path, set(target_user_ids), candidate_top_k_per_user)

    metrics, per_user_rows = _score_reachability(
        target_user_ids=target_user_ids,
        labels_by_user=labels_by_user,
        raw_user_items=raw_graph["user_items"],
        raw_item_users=raw_graph["item_users"],
        filtered_user_items=filtered_graph["user_items"],
        filtered_item_users=filtered_graph["item_users"],
        final_candidates_by_user=final_candidates_by_user,
        similar_users_top_k=similar_users_top_k,
    )
    sample_path = output_dir / "per_user_sample.jsonl"
    _write_per_user_sample(sample_path, per_user_rows)

    report_path = output_dir / "report.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "diagnostic_scope": "raw_vs_filtered_reachability",
        "readiness": "DIAGNOSTIC_ONLY",
        "promotion_decision": "NO_PROMOTION_DIAGNOSTIC_ONLY",
        "report_path": str(report_path),
        "per_user_sample_path": str(sample_path),
        "inputs": {
            "clean_manifest_path": str(clean_manifest_path),
            "method_dataset_manifest_path": str(method_dataset_manifest_path),
            "method_dataset_rows_path": str(method_rows_path),
            "source_index_manifest_path": str(source_index_manifest_path),
            "source_candidates_path": str(source_candidates_path),
            "label_paths": [str(path) for path in label_paths],
        },
        "config": {
            "target_user_limit": target_user_limit,
            "max_items_per_user": max_items_per_user,
            "similar_users_top_k": similar_users_top_k,
            "candidate_top_k_per_user": candidate_top_k_per_user,
            "max_raw_item_user_freq": max_raw_item_user_freq,
            "max_filtered_item_user_freq": max_filtered_item_user_freq,
            "label_splits": list(label_splits),
        },
        "metrics": metrics,
        "audits": {
            "method_dataset": filtered_graph["audit"],
            "raw_train_graph": raw_graph["audit"],
            "source_candidate_user_count_in_scope": len(final_candidates_by_user),
            "method_manifest_status": method_manifest.get("status"),
            "source_manifest_status": source_manifest.get("status"),
        },
        "governance_evidence": {
            "train_only_candidate_generation": True,
            "eval_scope": "evaluation_only",
            "label_inputs_role": "evaluation_only_not_candidate_generation_inputs",
            "labels_used_for_neighbor_building": False,
            "labels_used_for_candidate_generation": False,
            "forbidden_generation_inputs": list(FORBIDDEN_GENERATION_INPUTS),
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "old_full_data_artifact_reference_only": True,
        },
        "interpretation": _interpret(metrics),
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    write_json(report_path, report)
    return report


def _validate_positive_caps(**values: int) -> None:
    for name, value in values.items():
        if name == "target_user_limit":
            if value < 0:
                raise ValueError("target_user_limit must be non-negative")
            continue
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def _prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory exists and is non-empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _resolve_method_dataset_rows(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    payload = read_json(manifest_path)
    if payload.get("status") != "PASS":
        raise ValueError("method_dataset_manifest.status must be PASS")
    if payload.get("schema_version") != "pool500_method_dataset_v1":
        raise ValueError("method_dataset_manifest.schema_version must be pool500_method_dataset_v1")
    if payload.get("train_only") is not True:
        raise ValueError("method_dataset_manifest.train_only must be true")
    if payload.get("source_method") != "usercf_method_dataset":
        raise ValueError("method_dataset_manifest.source_method must be usercf_method_dataset")
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    if outputs.get("dataset_schema") != "eligible_user_sequence_v1":
        raise ValueError("method_dataset_manifest.outputs.dataset_schema must be eligible_user_sequence_v1")
    rows_path_raw = outputs.get("dataset_rows_path")
    if not rows_path_raw:
        raise ValueError("method_dataset_manifest.outputs.dataset_rows_path is required")
    rows_path = _resolve_path_from(manifest_path.parent, rows_path_raw)
    if rows_path.name != "method_dataset_rows.jsonl":
        raise ValueError(f"method_dataset rows file must be method_dataset_rows.jsonl, got {rows_path.name}")
    if not rows_path.is_file():
        raise FileNotFoundError(rows_path)
    return payload, rows_path


def _resolve_source_candidates_path(source_index_manifest_path: Path, source_manifest: dict[str, Any]) -> Path:
    outputs = source_manifest.get("outputs") if isinstance(source_manifest.get("outputs"), dict) else {}
    candidates_path = outputs.get("candidates") or source_manifest.get("candidates_path") or source_index_manifest_path.parent / "candidates.jsonl"
    path = _resolve_path_from(source_index_manifest_path.parent, candidates_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _load_filtered_graph(path: Path, *, max_items_per_user: int, target_user_limit: int, max_item_user_freq: int) -> dict[str, Any]:
    user_items: dict[str, set[str]] = {}
    item_users_raw: dict[str, set[str]] = defaultdict(set)
    target_user_ids: list[str] = []
    row_count = 0
    rows_with_items = 0
    item_events = 0
    for row in iter_jsonl(path):
        row_count += 1
        user_id = _clean_id(row.get("user_id"))
        raw_items = row.get("eligible_item_sequence")
        if not user_id or not isinstance(raw_items, list):
            continue
        if target_user_limit == 0 or len(target_user_ids) < target_user_limit:
            target_user_ids.append(user_id)
        items = _first_unique_items(raw_items, max_items_per_user)
        item_events += len(items)
        if not items:
            continue
        rows_with_items += 1
        item_set = set(items)
        user_items[user_id] = item_set
        for item_id in item_set:
            item_users_raw[item_id].add(user_id)
    hot_items = {item_id for item_id, users in item_users_raw.items() if len(users) > max_item_user_freq}
    item_users = {item_id: users for item_id, users in item_users_raw.items() if item_id not in hot_items}
    return {
        "user_items": user_items,
        "item_users": item_users,
        "target_user_ids": target_user_ids,
        "audit": {
            "rows_scanned": row_count,
            "rows_with_items": rows_with_items,
            "target_user_count": len(target_user_ids),
            "indexed_user_count": len(user_items),
            "item_event_count": item_events,
            "unique_item_count_before_freq_cap": len(item_users_raw),
            "unique_item_count_after_freq_cap": len(item_users),
            "dropped_item_count_by_freq_cap": len(hot_items),
            "max_item_user_freq": max_item_user_freq,
        },
    }


def _load_raw_train_graph_for_targets(
    clean_manifest: dict[str, Any],
    target_user_ids: list[str],
    *,
    max_items_per_user: int,
    max_item_user_freq: int,
) -> dict[str, Any]:
    train_path_raw = clean_manifest.get("train_user_sequences_path") or clean_manifest.get("user_sequences_train_path")
    if not train_path_raw:
        split_paths = clean_manifest.get("sequence_paths") if isinstance(clean_manifest.get("sequence_paths"), dict) else {}
        train_path_raw = split_paths.get("train")
    if not train_path_raw:
        raise ValueError("clean manifest must provide train_user_sequences_path")
    train_path = _resolve_path(train_path_raw)
    target_set = set(target_user_ids)
    target_items: set[str] = set()
    target_raw_items: dict[str, set[str]] = {}
    first_pass_rows = 0
    for row in iter_jsonl(train_path):
        first_pass_rows += 1
        user_id = _clean_id(row.get("user_id"))
        if user_id not in target_set:
            continue
        items = set(_recent_unique_items(row.get("recent_positive_item_sequence") or [], max_items_per_user))
        target_raw_items[user_id] = items
        target_items.update(items)
        if len(target_raw_items) >= len(target_set):
            break

    user_items: dict[str, set[str]] = {}
    item_users_raw: dict[str, set[str]] = defaultdict(set)
    rows_scanned = 0
    rows_with_overlap = 0
    for row in iter_jsonl(train_path):
        rows_scanned += 1
        user_id = _clean_id(row.get("user_id"))
        raw_items = row.get("recent_positive_item_sequence") or []
        if not user_id or not isinstance(raw_items, list):
            continue
        items = set(_recent_unique_items(raw_items, max_items_per_user))
        if not items:
            continue
        if user_id not in target_set and not (items & target_items):
            continue
        rows_with_overlap += 1
        user_items[user_id] = items
        for item_id in items:
            item_users_raw[item_id].add(user_id)
    for user_id, items in target_raw_items.items():
        if items:
            user_items.setdefault(user_id, items)
            for item_id in items:
                item_users_raw[item_id].add(user_id)
    hot_items = {item_id for item_id, users in item_users_raw.items() if len(users) > max_item_user_freq}
    item_users = {item_id: users for item_id, users in item_users_raw.items() if item_id not in hot_items}
    return {
        "user_items": user_items,
        "item_users": item_users,
        "audit": {
            "train_user_sequences_path": str(train_path),
            "target_user_count": len(target_user_ids),
            "target_users_found_in_train": len(target_raw_items),
            "target_raw_item_count": len(target_items),
            "first_pass_rows_scanned_until_targets_found": first_pass_rows,
            "second_pass_rows_scanned": rows_scanned,
            "rows_with_target_item_overlap_or_target_user": rows_with_overlap,
            "indexed_user_count": len(user_items),
            "unique_item_count_before_freq_cap": len(item_users_raw),
            "unique_item_count_after_freq_cap": len(item_users),
            "dropped_item_count_by_freq_cap": len(hot_items),
            "max_item_user_freq": max_item_user_freq,
        },
    }


def _load_eval_only_labels(clean_manifest: dict[str, Any], label_splits: Iterable[str], target_user_ids: set[str]) -> tuple[dict[str, set[str]], list[Path]]:
    split_paths = clean_manifest.get("split_paths") if isinstance(clean_manifest.get("split_paths"), dict) else {}
    labels_by_user: dict[str, set[str]] = defaultdict(set)
    label_paths: list[Path] = []
    for split in label_splits:
        raw_path = split_paths.get(split)
        if not raw_path:
            continue
        path = _resolve_path(raw_path)
        label_paths.append(path)
        for row in iter_jsonl(path):
            if not _is_positive(row):
                continue
            user_id = _string_value(row, "user_id", "user")
            if not user_id or user_id not in target_user_ids:
                continue
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            if item_id:
                labels_by_user[user_id].add(item_id)
    return dict(labels_by_user), label_paths


def _load_final_candidates(candidates_path: Path, target_user_ids: set[str], candidate_top_k_per_user: int) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in iter_jsonl(candidates_path):
        user_id = _string_value(row, "user_id")
        if not user_id or user_id not in target_user_ids:
            continue
        rank = _int_value(row.get("rank"), candidate_top_k_per_user + 1)
        if rank > candidate_top_k_per_user:
            continue
        item_id = _string_value(row, "item_id", "parent_asin")
        if item_id:
            result[user_id].add(item_id)
    return dict(result)


def _score_reachability(
    *,
    target_user_ids: list[str],
    labels_by_user: dict[str, set[str]],
    raw_user_items: dict[str, set[str]],
    raw_item_users: dict[str, set[str]],
    filtered_user_items: dict[str, set[str]],
    filtered_item_users: dict[str, set[str]],
    final_candidates_by_user: dict[str, set[str]],
    similar_users_top_k: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    per_user_rows: list[dict[str, Any]] = []
    for user_id in target_user_ids:
        labels = labels_by_user.get(user_id, set())
        if not labels:
            continue
        raw_reachable = _neighbor_reachable_items(user_id, raw_user_items, raw_item_users, similar_users_top_k)
        filtered_reachable = _neighbor_reachable_items(user_id, filtered_user_items, filtered_item_users, similar_users_top_k)
        final_candidates = final_candidates_by_user.get(user_id, set())
        raw_hits = labels & raw_reachable
        filtered_hits = labels & filtered_reachable
        final_hits = labels & final_candidates
        label_count = len(labels)
        counts["label_user_count"] += 1
        counts["label_total_count"] += label_count
        counts["raw_neighbor_reachable_label_count"] += len(raw_hits)
        counts["filtered_neighbor_reachable_label_count"] += len(filtered_hits)
        counts["final_candidate_hit_count"] += len(final_hits)
        if raw_hits:
            counts["raw_neighbor_reachable_user_count"] += 1
        if filtered_hits:
            counts["filtered_neighbor_reachable_user_count"] += 1
        if final_hits:
            counts["final_candidate_hit_user_count"] += 1
        per_user_rows.append(
            {
                "user_id": user_id,
                "label_count": label_count,
                "raw_neighbor_reachable_label_count": len(raw_hits),
                "filtered_neighbor_reachable_label_count": len(filtered_hits),
                "final_candidate_hit_count": len(final_hits),
                "raw_neighbor_candidate_count": len(raw_reachable),
                "filtered_neighbor_candidate_count": len(filtered_reachable),
                "final_candidate_count": len(final_candidates),
            }
        )
    label_total = counts["label_total_count"]
    raw_count = counts["raw_neighbor_reachable_label_count"]
    filtered_count = counts["filtered_neighbor_reachable_label_count"]
    final_count = counts["final_candidate_hit_count"]
    metrics: dict[str, Any] = {
        "target_user_count": len(target_user_ids),
        "label_user_count": counts["label_user_count"],
        "label_total_count": label_total,
        "raw_neighbor_reachable_label_count": raw_count,
        "filtered_neighbor_reachable_label_count": filtered_count,
        "final_candidate_hit_count": final_count,
        "raw_neighbor_reachable_user_count": counts["raw_neighbor_reachable_user_count"],
        "filtered_neighbor_reachable_user_count": counts["filtered_neighbor_reachable_user_count"],
        "final_candidate_hit_user_count": counts["final_candidate_hit_user_count"],
        "raw_reachability_rate": _safe_rate(raw_count, label_total),
        "filtered_reachability_rate": _safe_rate(filtered_count, label_total),
        "final_recall_at_k": _safe_rate(final_count, label_total),
        "raw_to_filtered_loss_rate": _loss_rate(raw_count, filtered_count),
        "filtered_to_final_loss_rate": _loss_rate(filtered_count, final_count),
    }
    return metrics, per_user_rows


def _neighbor_reachable_items(
    user_id: str,
    user_items: dict[str, set[str]],
    item_users: dict[str, set[str]],
    similar_users_top_k: int,
) -> set[str]:
    items = user_items.get(user_id, set())
    if not items:
        return set()
    neighbor_scores: Counter[str] = Counter()
    for item_id in items:
        for neighbor_user in item_users.get(item_id, set()):
            if neighbor_user != user_id:
                neighbor_scores[neighbor_user] += 1
    reachable: set[str] = set()
    for neighbor_user, _overlap in sorted(neighbor_scores.items(), key=lambda pair: (-pair[1], pair[0]))[:similar_users_top_k]:
        reachable.update(user_items.get(neighbor_user, set()) - items)
    return reachable


def _write_per_user_sample(path: Path, rows: list[dict[str, Any]], limit: int = 200) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows[:limit]:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _interpret(metrics: dict[str, Any]) -> dict[str, str]:
    raw = float(metrics.get("raw_reachability_rate", 0.0))
    filtered = float(metrics.get("filtered_reachability_rate", 0.0))
    final = float(metrics.get("final_recall_at_k", 0.0))
    if raw > filtered:
        diagnosis = "raw_neighbor_has_more_future_label_reachability_than_filtered_neighbor; item filtering may truncate useful UserCF signal."
    elif raw == 0:
        diagnosis = "raw_neighbor_reachability_is_zero_for_this_scope; UserCF neighbor structure may be weak for future-window labels."
    else:
        diagnosis = "filtered_neighbor_reachability_is_not_lower_than_raw_in_this_scope; investigate final candidate ranking/capping if final recall is lower."
    return {
        "diagnosis": diagnosis,
        "promotion_note": "This diagnostic does not promote usercf_recall. Keep DIAGNOSTIC_ONLY until formal route-gate, source-overlap, popularity, and no-holdout evidence pass.",
        "metric_summary": f"raw={raw:.6f}, filtered={filtered:.6f}, final={final:.6f}",
    }


def _recent_unique_items(raw_items: list[Any], max_items_per_user: int) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in reversed(raw_items[-max_items_per_user:]):
        item_id = _clean_id(item)
        if item_id and item_id not in seen:
            seen.add(item_id)
            items.append(item_id)
    items.reverse()
    return items


def _first_unique_items(raw_items: list[Any], max_items_per_user: int) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        item_id = _clean_id(item)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        items.append(item_id)
        if len(items) >= max_items_per_user:
            break
    return items


def _is_positive(row: dict[str, Any]) -> bool:
    for field in POSITIVE_FIELDS:
        if field not in row:
            continue
        value = row.get(field)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "positive"}:
                return True
            if lowered in {"0", "false", "no", "negative"}:
                return False
    rating = row.get("rating")
    return isinstance(rating, (int, float)) and rating >= 4.0


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _resolve_path(value: Any) -> Path:
    path = Path(str(value).replace("\\", "/"))
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _resolve_path_from(base_dir: Path, value: Any) -> Path:
    path = Path(str(value).replace("\\", "/"))
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _clean_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _string_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        cleaned = _clean_id(value)
        if cleaned:
            return cleaned
    return ""


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _loss_rate(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round(max(0, before - after) / before, 6)


if __name__ == "__main__":
    main()
