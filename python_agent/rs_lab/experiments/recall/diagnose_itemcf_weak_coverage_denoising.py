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

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_itemcf_weak_coverage_denoising_grid_v1"
SOURCE = "itemcf_weak"
DATA_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_METHOD_DATASET_MANIFEST = ROOT / "outputs" / "recall" / "pool500_itemcf_new_dataset" / "method_datasets_smoke" / SOURCE / "method_dataset_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_method_diagnostics" / "recent_2y" / SOURCE / "weak_coverage_denoising_grid_v1"
DEFAULT_KS = (50, 100, 500)

FORBIDDEN_BUILD_INPUT_TOKENS = ("holdout", "valid", "test", "lopo", "oracle", "eval_label", "clean_10000", "pool1000")


DEFAULT_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "name": "baseline_support1_no_cap",
        "min_pair_support": 1,
        "top_k_per_seed": 0,
        "shrinkage_alpha": 0.0,
        "score_policy": "existing_itemcf_score",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support1_existing_seed200_user500",
        "min_pair_support": 1,
        "top_k_per_seed": 200,
        "shrinkage_alpha": 0.0,
        "score_policy": "existing_itemcf_score",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 500,
    },
    {
        "name": "support1_existing_seed100_user500",
        "min_pair_support": 1,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 0.0,
        "score_policy": "existing_itemcf_score",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 500,
    },
    {
        "name": "support1_existing_seed50_user500",
        "min_pair_support": 1,
        "top_k_per_seed": 50,
        "shrinkage_alpha": 0.0,
        "score_policy": "existing_itemcf_score",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 500,
    },
    {
        "name": "support1_shrink10_seed100_user500",
        "min_pair_support": 1,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 10.0,
        "score_policy": "cosine_shrinkage_from_features",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 500,
    },
    {
        "name": "support1_shrink25_seed100_user500",
        "min_pair_support": 1,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 25.0,
        "score_policy": "cosine_shrinkage_from_features",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 500,
    },
    {
        "name": "support2_no_cap",
        "min_pair_support": 2,
        "top_k_per_seed": 0,
        "shrinkage_alpha": 0.0,
        "score_policy": "existing_itemcf_score",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support3_no_cap",
        "min_pair_support": 3,
        "top_k_per_seed": 0,
        "shrinkage_alpha": 0.0,
        "score_policy": "existing_itemcf_score",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support2_shrink25_seed100",
        "min_pair_support": 2,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 25.0,
        "score_policy": "cosine_shrinkage_from_features",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support2_shrink50_seed100",
        "min_pair_support": 2,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 50.0,
        "score_policy": "cosine_shrinkage_from_features",
        "exclude_hot_dst": False,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support1_bm25idf_shrink25_seed100_hotdst_nonhot",
        "min_pair_support": 1,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 25.0,
        "score_policy": "bm25idf_cosine_shrinkage_from_features",
        "exclude_hot_dst": True,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support2_bm25idf_shrink25_seed100_hotdst_nonhot",
        "min_pair_support": 2,
        "top_k_per_seed": 100,
        "shrinkage_alpha": 25.0,
        "score_policy": "bm25idf_cosine_shrinkage_from_features",
        "exclude_hot_dst": True,
        "per_user_candidate_cap": 0,
    },
    {
        "name": "support1_bm25idf_shrink25_seed50_hotdst_nonhot_user500",
        "min_pair_support": 1,
        "top_k_per_seed": 50,
        "shrinkage_alpha": 25.0,
        "score_policy": "bm25idf_cosine_shrinkage_from_features",
        "exclude_hot_dst": True,
        "per_user_candidate_cap": 500,
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run evaluation-only denoising diagnostics for itemcf_weak weak_coverage method dataset rows.")
    parser.add_argument("--method-dataset-manifest", default=str(DEFAULT_METHOD_DATASET_MANIFEST))
    parser.add_argument("--method-dataset-rows", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--train-sequences", default=str(DATA_ROOT / "user_sequences.train.jsonl"))
    parser.add_argument("--item-frequency-train", default=str(DATA_ROOT / "train_only_governance" / "item_frequency_train.jsonl"))
    parser.add_argument("--item-quality-profile", default=str(DATA_ROOT / "train_only_governance" / "item_quality_profile.jsonl"))
    parser.add_argument("--valid-labels", default=str(DATA_ROOT / "canonical_interactions.valid.jsonl"))
    parser.add_argument("--test-labels", default=str(DATA_ROOT / "canonical_interactions.test.jsonl"))
    parser.add_argument("--eval-user-limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_diagnostics(
        method_dataset_manifest_path=Path(args.method_dataset_manifest),
        method_dataset_rows_path=Path(args.method_dataset_rows) if args.method_dataset_rows else None,
        output_dir=Path(args.output_dir),
        train_sequences_path=Path(args.train_sequences),
        item_frequency_train_path=Path(args.item_frequency_train),
        item_quality_profile_path=Path(args.item_quality_profile),
        eval_label_paths=(Path(args.valid_labels), Path(args.test_labels)),
        eval_user_limit=args.eval_user_limit,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": report["status"], "output": report["outputs"]["evaluation_report"], "best_variant": report["summary"]["best_raw_recall_at_500"]}, ensure_ascii=False, indent=2))


def run_diagnostics(
    *,
    method_dataset_manifest_path: Path = DEFAULT_METHOD_DATASET_MANIFEST,
    method_dataset_rows_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    train_sequences_path: Path = DATA_ROOT / "user_sequences.train.jsonl",
    item_frequency_train_path: Path = DATA_ROOT / "train_only_governance" / "item_frequency_train.jsonl",
    item_quality_profile_path: Path = DATA_ROOT / "train_only_governance" / "item_quality_profile.jsonl",
    eval_label_paths: tuple[Path, Path] = (DATA_ROOT / "canonical_interactions.valid.jsonl", DATA_ROOT / "canonical_interactions.test.jsonl"),
    eval_user_limit: int = 0,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    method_dataset_manifest_path = method_dataset_manifest_path.resolve()
    method_dataset_manifest = _read_json(method_dataset_manifest_path)
    method_dataset_rows_path = (method_dataset_rows_path or _default_rows_path(method_dataset_manifest_path, method_dataset_manifest)).resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and not overwrite:
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _assert_train_only_build_inputs(method_dataset_manifest_path, method_dataset_rows_path, train_sequences_path, item_frequency_train_path, item_quality_profile_path)
    labels, split_label_counts = _load_eval_labels(eval_label_paths)
    train_sequences = _load_train_sequences(train_sequences_path, labels, eval_user_limit)
    eval_seed_items = {item for row in train_sequences.values() for item in row["seed_items"]}
    item_user_counts, item_frequency_counts = _load_item_frequency(item_frequency_train_path)
    hot_items = _load_hot_items(item_quality_profile_path)

    variants = _evaluate_variants_one_pass(
        variants=DEFAULT_VARIANTS,
        rows_path=method_dataset_rows_path,
        eval_seed_items=eval_seed_items,
        train_sequences=train_sequences,
        labels=labels,
        item_user_counts=item_user_counts,
        item_frequency_counts=item_frequency_counts,
        hot_items=hot_items,
        ks=DEFAULT_KS,
    )

    best_raw = max(variants, key=lambda row: row["metrics"].get("raw_recall@500", 0.0)) if variants else None
    best_in_universe = max(variants, key=lambda row: row["metrics"].get("in_universe_recall@500", 0.0)) if variants else None
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "evaluation_only": True,
        "label_usage": "valid/test labels are read only for post-hoc evaluation; not used in method_dataset construction, scoring, filtering, candidate generation, or variant selection inputs",
        "inputs": {
            "method_dataset_manifest": str(method_dataset_manifest_path),
            "method_dataset_rows": str(method_dataset_rows_path),
            "train_sequences": str(train_sequences_path.resolve()),
            "item_frequency_train": str(item_frequency_train_path.resolve()),
            "item_quality_profile": str(item_quality_profile_path.resolve()),
            "eval_label_paths": [str(path.resolve()) for path in eval_label_paths],
        },
        "eval_scope": {
            "eval_users_with_labels": len(labels),
            "evaluated_users_with_train_sequence": len(train_sequences),
            "eval_seed_item_count": len(eval_seed_items),
            "split_label_counts": split_label_counts,
        },
        "variants": variants,
        "summary": {
            "best_raw_recall_at_500": _variant_summary(best_raw),
            "best_in_universe_recall_at_500": _variant_summary(best_in_universe),
            "interpretation": "compare support/shrinkage/BM25-IDF/hot-dst/cap variants without using eval labels for construction; keep DIAGNOSTIC_ONLY until a governed full source and route gate prove marginal value",
        },
        "governance": {
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
        },
        "outputs": {"evaluation_report": str(output_dir / "evaluation_report.json")},
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    _write_json(output_dir / "evaluation_report.json", report)
    return report


def _evaluate_variants_one_pass(
    *,
    variants: tuple[dict[str, Any], ...],
    rows_path: Path,
    eval_seed_items: set[str],
    train_sequences: dict[str, dict[str, Any]],
    labels: dict[str, set[str]],
    item_user_counts: dict[str, int],
    item_frequency_counts: dict[str, int],
    hot_items: set[str],
    ks: tuple[int, ...],
) -> list[dict[str, Any]]:
    adjacency_by_variant: dict[str, dict[str, list[tuple[str, float, int]]]] = {
        variant["name"]: defaultdict(list) for variant in variants
    }
    source_item_union_by_variant: dict[str, set[str]] = {variant["name"]: set() for variant in variants}
    support_counts_by_variant: dict[str, Counter[int]] = {variant["name"]: Counter() for variant in variants}
    kept_counts_by_variant: Counter[str] = Counter()
    edge_rows_scanned = 0

    for row in _iter_jsonl(rows_path):
        edge_rows_scanned += 1
        src = str(row.get("src_item_id") or "")
        dst = str(row.get("dst_item_id") or "")
        if not src or not dst:
            continue
        support = int(row.get("pair_support") or row.get("cooc_cnt") or 0)
        for variant in variants:
            name = str(variant["name"])
            if support < int(variant["min_pair_support"]):
                continue
            if bool(variant["exclude_hot_dst"]) and dst in hot_items:
                continue
            source_item_union_by_variant[name].add(src)
            source_item_union_by_variant[name].add(dst)
            if src not in eval_seed_items:
                continue
            score = _variant_score(row, variant, item_user_counts, item_frequency_counts)
            adjacency_by_variant[name][src].append((dst, score, support))
            support_counts_by_variant[name][support] += 1
            kept_counts_by_variant[name] += 1

    results: list[dict[str, Any]] = []
    for variant in variants:
        name = str(variant["name"])
        adjacency = adjacency_by_variant[name]
        top_k_per_seed = int(variant["top_k_per_seed"])
        for src, edges in list(adjacency.items()):
            ranked = sorted(edges, key=lambda edge: (-edge[1], -edge[2], edge[0]))
            adjacency[src] = ranked[:top_k_per_seed] if top_k_per_seed > 0 else ranked
        eval_result = _evaluate_candidates(
            adjacency=adjacency,
            source_item_union=source_item_union_by_variant[name],
            train_sequences=train_sequences,
            labels=labels,
            ks=ks,
            per_user_candidate_cap=int(variant["per_user_candidate_cap"]),
        )
        results.append(
            {
                "name": name,
                "config": variant,
                "method_dataset": {
                    "edge_rows_scanned": edge_rows_scanned,
                    "edge_rows_kept_for_eval_seed_items": kept_counts_by_variant[name],
                    "source_item_union_count": len(source_item_union_by_variant[name]),
                    "eval_seed_items_with_edges": len(adjacency),
                    "pair_support_counts_for_kept_edges_top10": {
                        str(key): value for key, value in support_counts_by_variant[name].most_common(10)
                    },
                },
                **eval_result,
            }
        )
    return results



def _evaluate_variant(
    *,
    variant: dict[str, Any],
    rows_path: Path,
    eval_seed_items: set[str],
    train_sequences: dict[str, dict[str, Any]],
    labels: dict[str, set[str]],
    item_user_counts: dict[str, int],
    item_frequency_counts: dict[str, int],
    hot_items: set[str],
    ks: tuple[int, ...],
) -> dict[str, Any]:
    adjacency: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    source_item_union: set[str] = set()
    support_counts: Counter[int] = Counter()
    edge_rows_scanned = 0
    edge_rows_kept_for_eval_seed_items = 0
    min_pair_support = int(variant["min_pair_support"])
    exclude_hot_dst = bool(variant["exclude_hot_dst"])
    top_k_per_seed = int(variant["top_k_per_seed"])

    for row in _iter_jsonl(rows_path):
        edge_rows_scanned += 1
        src = str(row.get("src_item_id") or "")
        dst = str(row.get("dst_item_id") or "")
        if not src or not dst:
            continue
        support = int(row.get("pair_support") or row.get("cooc_cnt") or 0)
        if support < min_pair_support:
            continue
        if exclude_hot_dst and dst in hot_items:
            continue
        source_item_union.add(src)
        source_item_union.add(dst)
        if src not in eval_seed_items:
            continue
        score = _variant_score(row, variant, item_user_counts, item_frequency_counts)
        adjacency[src].append((dst, score, support))
        support_counts[support] += 1
        edge_rows_kept_for_eval_seed_items += 1

    for src, edges in list(adjacency.items()):
        ranked = sorted(edges, key=lambda edge: (-edge[1], -edge[2], edge[0]))
        adjacency[src] = ranked[:top_k_per_seed] if top_k_per_seed > 0 else ranked

    eval_result = _evaluate_candidates(
        adjacency=adjacency,
        source_item_union=source_item_union,
        train_sequences=train_sequences,
        labels=labels,
        ks=ks,
        per_user_candidate_cap=int(variant["per_user_candidate_cap"]),
    )
    return {
        "name": variant["name"],
        "config": variant,
        "method_dataset": {
            "edge_rows_scanned": edge_rows_scanned,
            "edge_rows_kept_for_eval_seed_items": edge_rows_kept_for_eval_seed_items,
            "source_item_union_count": len(source_item_union),
            "eval_seed_items_with_edges": len(adjacency),
            "pair_support_counts_for_kept_edges_top10": {str(key): value for key, value in support_counts.most_common(10)},
        },
        **eval_result,
    }


def _variant_score(row: dict[str, Any], variant: dict[str, Any], item_user_counts: dict[str, int], item_frequency_counts: dict[str, int]) -> float:
    score_policy = str(variant["score_policy"])
    if score_policy == "existing_itemcf_score":
        return float(row.get("itemcf_score") or 0.0)
    src = str(row.get("src_item_id") or "")
    dst = str(row.get("dst_item_id") or "")
    support = int(row.get("pair_support") or row.get("cooc_cnt") or 0)
    weighted_cooc = float(row.get("weighted_cooc") or 0.0)
    if score_policy == "bm25idf_cosine_shrinkage_from_features":
        weighted_cooc *= math.sqrt(_bm25idf_weight(src, item_user_counts, item_frequency_counts) * _bm25idf_weight(dst, item_user_counts, item_frequency_counts))
    src_count = int(row.get("src_user_count") or item_user_counts.get(src) or item_frequency_counts.get(src, 0))
    dst_count = int(row.get("dst_user_count") or item_user_counts.get(dst) or item_frequency_counts.get(dst, 0))
    if src_count <= 0 or dst_count <= 0:
        return 0.0
    score = weighted_cooc / math.sqrt(src_count * dst_count)
    shrinkage_alpha = float(variant.get("shrinkage_alpha") or 0.0)
    if shrinkage_alpha > 0:
        score *= support / (support + shrinkage_alpha)
    return round(score, 8)


def _evaluate_candidates(
    *,
    adjacency: dict[str, list[tuple[str, float, int]]],
    source_item_union: set[str],
    train_sequences: dict[str, dict[str, Any]],
    labels: dict[str, set[str]],
    ks: tuple[int, ...],
    per_user_candidate_cap: int,
) -> dict[str, Any]:
    raw_label_total = 0
    in_universe_label_total = 0
    hits = {k: 0 for k in ks}
    in_universe_hits = {k: 0 for k in ks}
    hit_users = {k: 0 for k in ks}
    candidate_counts: list[int] = []
    users_with_seed_hit = 0
    users_with_candidates = 0
    bucket_totals: Counter[str] = Counter()
    bucket_hit_users = {k: Counter() for k in ks}

    for user_id, sequence in train_sequences.items():
        user_labels = labels.get(user_id, set())
        if not user_labels:
            continue
        bucket = _sequence_bucket(len(sequence["seed_items"]))
        bucket_totals[bucket] += 1
        raw_label_total += len(user_labels)
        in_universe_labels = user_labels & source_item_union
        in_universe_label_total += len(in_universe_labels)
        by_item: dict[str, float] = {}
        seed_hit = False
        for seed in sequence["seed_items"]:
            edges = adjacency.get(seed) or []
            if edges:
                seed_hit = True
            for dst, score, _support in edges:
                if dst in sequence["seen_items"] or dst == seed:
                    continue
                if score > by_item.get(dst, -1.0):
                    by_item[dst] = score
        if seed_hit:
            users_with_seed_hit += 1
        ranked = sorted(by_item, key=lambda item: (-by_item[item], item))
        if per_user_candidate_cap > 0:
            ranked = ranked[:per_user_candidate_cap]
        candidate_counts.append(len(ranked))
        if ranked:
            users_with_candidates += 1
        for k in ks:
            top_items = set(ranked[:k])
            hit_count = len(top_items & user_labels)
            hits[k] += hit_count
            in_universe_hits[k] += len(top_items & in_universe_labels)
            if hit_count > 0:
                hit_users[k] += 1
                bucket_hit_users[k][bucket] += 1

    evaluated_user_count = len(train_sequences)
    metrics: dict[str, float | int] = {}
    for k in ks:
        metrics[f"raw_recall@{k}"] = round(hits[k] / raw_label_total, 6) if raw_label_total else 0.0
        metrics[f"raw_hit_user_rate@{k}"] = round(hit_users[k] / evaluated_user_count, 6) if evaluated_user_count else 0.0
        metrics[f"raw_hits@{k}"] = hits[k]
        metrics[f"in_universe_recall@{k}"] = round(in_universe_hits[k] / in_universe_label_total, 6) if in_universe_label_total else 0.0
        metrics[f"in_universe_hits@{k}"] = in_universe_hits[k]
        metrics[f"in_universe_denominator@{k}"] = in_universe_label_total
    return {
        "eval_scope": {
            "evaluated_users_with_train_sequence": evaluated_user_count,
            "raw_label_total": raw_label_total,
            "in_universe_label_total": in_universe_label_total,
            "in_universe_label_ratio": round(in_universe_label_total / raw_label_total, 6) if raw_label_total else 0.0,
        },
        "coverage": {
            "users_with_seed_hit": users_with_seed_hit,
            "seed_hit_user_rate": round(users_with_seed_hit / evaluated_user_count, 6) if evaluated_user_count else 0.0,
            "users_with_candidates": users_with_candidates,
            "candidate_user_rate": round(users_with_candidates / evaluated_user_count, 6) if evaluated_user_count else 0.0,
            "candidate_count_stats": _count_stats(candidate_counts),
            "sequence_bucket_counts": dict(bucket_totals),
        },
        "metrics": metrics,
        "sequence_bucket_hit_user_rate": {
            f"raw_hit_user_rate@{k}": {
                bucket: round(bucket_hit_users[k][bucket] / total, 6) if total else 0.0
                for bucket, total in bucket_totals.items()
            }
            for k in ks
        },
    }


def _load_eval_labels(paths: tuple[Path, Path]) -> tuple[dict[str, set[str]], dict[str, int]]:
    labels: dict[str, set[str]] = defaultdict(set)
    split_counts: dict[str, int] = {}
    for path in paths:
        count = 0
        for row in _iter_jsonl(path):
            user_id = _row_user_id(row)
            item_id = _row_item_id(row)
            if user_id and item_id:
                labels[user_id].add(item_id)
                count += 1
        split_counts[_split_name(path)] = count
    return dict(labels), split_counts


def _load_train_sequences(path: Path, labels: dict[str, set[str]], limit: int) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(path):
        user_id = _row_user_id(row)
        if not user_id or user_id not in labels:
            continue
        seed_items = _unique_in_order(str(item) for item in row.get("recent_positive_item_sequence", []) if item)
        if not seed_items:
            continue
        seen_items = set(seed_items)
        seen_items.update(str(item) for item in row.get("recent_item_sequence", []) if item)
        rows[user_id] = {"seed_items": list(reversed(seed_items)), "seen_items": seen_items}
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def _load_item_frequency(path: Path) -> tuple[dict[str, int], dict[str, int]]:
    user_counts: dict[str, int] = {}
    frequency_counts: dict[str, int] = {}
    for row in _iter_jsonl(path):
        item_id = _row_item_id(row)
        if item_id:
            user_counts[item_id] = int(row.get("user_count") or 0)
            frequency_counts[item_id] = int(row.get("frequency") or 0)
    return user_counts, frequency_counts


def _load_hot_items(path: Path) -> set[str]:
    hot_items: set[str] = set()
    for row in _iter_jsonl(path):
        item_id = _row_item_id(row)
        if item_id and row.get("hotness_bucket") == "hot":
            hot_items.add(item_id)
    return hot_items


def _bm25idf_weight(item_id: str, item_user_counts: dict[str, int], item_frequency_counts: dict[str, int]) -> float:
    user_count = max(item_user_counts.get(item_id) or item_frequency_counts.get(item_id, 0), 1)
    corpus_user_count = max(sum(item_user_counts.values()), 1)
    idf = math.log1p(corpus_user_count / user_count)
    tf = math.log1p(item_frequency_counts.get(item_id, user_count))
    bm25_tf = tf / (tf + 1.2)
    return max(bm25_tf * idf, 1e-6)


def _count_stats(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    return {"min": ordered[0], "p50": _percentile(ordered, 0.5), "p90": _percentile(ordered, 0.9), "max": ordered[-1]}


def _percentile(values: list[int], q: float) -> float:
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    weight = pos - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 6)


def _variant_summary(variant: dict[str, Any] | None) -> dict[str, Any] | None:
    if variant is None:
        return None
    return {
        "name": variant["name"],
        "config": variant["config"],
        "raw_recall@500": variant["metrics"].get("raw_recall@500"),
        "in_universe_recall@500": variant["metrics"].get("in_universe_recall@500"),
        "candidate_user_rate": variant["coverage"].get("candidate_user_rate"),
        "candidate_count_stats": variant["coverage"].get("candidate_count_stats"),
    }


def _sequence_bucket(seed_len: int) -> str:
    if seed_len < 2:
        return "sparse_seq_len_lt2"
    if seed_len < 5:
        return "medium_like_seq_len_2_4"
    return "collab_like_seq_len_gte5"


def _assert_train_only_build_inputs(*paths: Path) -> None:
    for path in paths:
        lowered = str(path).replace("\\", "/").lower()
        if any(token in lowered for token in FORBIDDEN_BUILD_INPUT_TOKENS):
            raise ValueError(f"Forbidden build/input path for diagnostics: {path}")


def _default_rows_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    for key in ("dataset_rows_path", "method_dataset_rows", "rows", "dataset_rows"):
        value = outputs.get(key) or manifest.get(key)
        if value:
            raw_value = str(value).replace("\\", "/")
            if len(raw_value) > 2 and raw_value[1] == ":":
                project_marker = "/outputs/"
                marker_index = raw_value.lower().find(project_marker)
                if marker_index >= 0:
                    return ROOT / raw_value[marker_index + 1 :]
            path = Path(raw_value)
            return path if path.is_absolute() else (ROOT / path)
    return manifest_path.parent / "method_dataset_rows.jsonl"


def _row_user_id(row: dict[str, Any]) -> str:
    return str(row.get("user_id") or row.get("reviewerID") or row.get("reviewer_id") or "")


def _row_item_id(row: dict[str, Any]) -> str:
    return str(row.get("parent_asin") or row.get("item_id") or row.get("asin") or "")


def _split_name(path: Path) -> str:
    name = path.name.lower()
    if "valid" in name:
        return "valid"
    if "test" in name:
        return "test"
    return path.stem


def _unique_in_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
