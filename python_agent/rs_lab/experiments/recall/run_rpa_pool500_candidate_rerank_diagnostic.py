from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_lab.experiments.recall.run_pool500_offline_eval_baseline import (
    DEFAULT_EVAL_MANIFEST,
    METRIC_KS,
    _load_eval_labels,
    _load_eval_users,
    _load_offline_eval_manifest,
    _parse_metric_ks,
)
from rs_lab.experiments.recall.run_rpa_strict_zhang_pu_2007_sqlite_smoke import RecursivePredictionEngine

SCHEMA_VERSION = "rpa_pool500_candidate_rerank_diagnostic_v1"
DEFAULT_CLEAN_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_BASELINE_MANIFEST = ROOT / "outputs" / "eval" / "rpa_rerank_baseline_100_20260606a" / "baseline_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "eval" / "rpa_rerank_diagnostic_100_20260606a"


@dataclass(frozen=True)
class Config:
    baseline_manifest: Path = DEFAULT_BASELINE_MANIFEST
    clean_root: Path = DEFAULT_CLEAN_ROOT
    output_dir: Path = DEFAULT_OUTPUT_DIR
    run_id: str = "rpa_rerank_diagnostic_100_20260606a"
    strategy: str = "CS"
    k: int = 50
    k_prime: int = 50
    zeta: int = 2
    lambda_weight: float = 0.5
    phi: int = 2
    max_index_users: int = 12000
    max_users_per_item: int = 200
    max_items_per_user: int = 80
    metric_ks: tuple[int, ...] = METRIC_KS
    overwrite: bool = False
    enforce_venv: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnostic RPA-score reranking over an existing pool500 candidate artifact.")
    parser.add_argument("--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST)
    parser.add_argument("--clean-root", type=Path, default=DEFAULT_CLEAN_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default="rpa_rerank_diagnostic_100_20260606a")
    parser.add_argument("--strategy", default="CS")
    parser.add_argument("--k", type=int, default=50)
    parser.add_argument("--k-prime", type=int, default=50)
    parser.add_argument("--zeta", type=int, default=2)
    parser.add_argument("--lambda-weight", type=float, default=0.5)
    parser.add_argument("--phi", type=int, default=2)
    parser.add_argument("--max-index-users", type=int, default=12000)
    parser.add_argument("--max-users-per-item", type=int, default=200)
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--metric-ks", default=",".join(str(k) for k in METRIC_KS))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_diagnostic(
        Config(
            baseline_manifest=args.baseline_manifest,
            clean_root=args.clean_root,
            output_dir=args.output_dir,
            run_id=args.run_id,
            strategy=args.strategy,
            k=args.k,
            k_prime=args.k_prime,
            zeta=args.zeta,
            lambda_weight=args.lambda_weight,
            phi=args.phi,
            max_index_users=args.max_index_users,
            max_users_per_item=args.max_users_per_item,
            max_items_per_user=args.max_items_per_user,
            metric_ks=tuple(_parse_metric_ks(args.metric_ks)),
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["manifest_path"], "comparison": manifest["comparison"]}, ensure_ascii=False, indent=2))


def run_diagnostic(config: Config) -> dict[str, Any]:
    started = perf_counter()
    if config.enforce_venv:
        enforce_project_venv(ROOT)
    _validate_config(config)
    baseline_manifest_path = _resolve(config.baseline_manifest)
    clean_root = _resolve(config.clean_root)
    output_dir = _resolve(config.output_dir)
    _prepare_output(output_dir, config.overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_manifest = read_json(baseline_manifest_path)
    candidate_path = Path(str(baseline_manifest["candidate_artifact_path"])).resolve()
    eval_manifest_path = Path(str(baseline_manifest.get("eval_manifest_path") or DEFAULT_EVAL_MANIFEST)).resolve()
    eval_users_path = Path(str(baseline_manifest.get("eval_users_path") or eval_manifest_path.parent / "users.jsonl")).resolve()
    eval_manifest = _load_offline_eval_manifest(eval_manifest_path)
    users = _load_eval_users(eval_manifest, eval_manifest_path, eval_users_path)
    total_user_count = int(baseline_manifest.get("total_user_count") or 0)
    selected_users = users[:total_user_count] if total_user_count else users
    eval_user_ids = [str(user["user_id"]) for user in selected_users]
    labels_by_user = _load_eval_labels(eval_manifest, eval_user_ids)

    candidates_by_user = _load_candidates(candidate_path, eval_user_ids)
    stats = read_json(clean_root / "stats.json")
    train_end_row = int(stats["split_plan"]["train_end_row"])
    sqlite_path = clean_root / "recall_clean.sqlite"

    con = sqlite3.connect(sqlite_path)
    con.execute("pragma temp_store=memory")
    con.execute("pragma cache_size=-200000")
    try:
        target_ratings = _load_train_ratings_for_users(con, eval_user_ids, train_end_row, config.max_items_per_user)
        anchor_items = {item for ratings in target_ratings.values() for item in ratings}
        candidate_items = {row["item_id"] for rows in candidates_by_user.values() for row in rows}
        neighbor_users, neighbor_stats = _load_neighbor_users_for_items(
            con,
            sorted(anchor_items | candidate_items),
            train_end_row,
            config.max_users_per_item,
            config.max_index_users,
        )
        index_users = _merge_limited(eval_user_ids, neighbor_users, config.max_index_users)
        ratings_by_user = _load_train_ratings_for_users(con, index_users, train_end_row, config.max_items_per_user)
        for user_id, ratings in target_ratings.items():
            ratings_by_user.setdefault(user_id, {}).update(ratings)
    finally:
        con.close()

    item_users = _invert_index(ratings_by_user)
    engine = RecursivePredictionEngine(
        ratings_by_user=ratings_by_user,
        item_users=item_users,
        k=config.k,
        k_prime=config.k_prime,
        zeta=config.zeta,
        lambda_weight=config.lambda_weight,
        phi=config.phi,
    )

    scored_rows_path = output_dir / "rpa_scored_candidates.jsonl"
    reranked_path = output_dir / "rpa_reranked_candidates.jsonl"
    original_rows_for_eval: dict[str, list[dict[str, Any]]] = {}
    reranked_rows_for_eval: dict[str, list[dict[str, Any]]] = {}
    score_stats = Counter()
    with scored_rows_path.open("w", encoding="utf-8") as scored_handle, reranked_path.open("w", encoding="utf-8") as rerank_handle:
        for user_id in eval_user_ids:
            rows = candidates_by_user[user_id]
            scored = []
            for row in rows:
                rpa_score = engine.predict(user_id, row["item_id"], config.strategy)
                payload = dict(row["raw"])
                payload["rpa_score"] = round(rpa_score, 6)
                payload["original_rank"] = row["rank"]
                scored.append((rpa_score, row["rank"], float(row.get("score") or 0.0), payload))
                scored_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                score_stats["scored_candidate_count"] += 1
            reranked = sorted(scored, key=lambda item: (-item[0], item[1], -item[2]))
            reranked_payloads = []
            for new_rank, (_rpa_score, _old_rank, _old_score, payload) in enumerate(reranked, start=1):
                out = dict(payload)
                out["rank"] = new_rank
                out["source"] = "rpa_rerank_diagnostic"
                out["sources"] = _merge_sources(out.get("sources"), "rpa_rerank_diagnostic")
                reranked_payloads.append(out)
                rerank_handle.write(json.dumps(out, ensure_ascii=False) + "\n")
            original_rows_for_eval[user_id] = [row["raw"] for row in rows]
            reranked_rows_for_eval[user_id] = reranked_payloads

    original_metrics = _evaluate_rows(original_rows_for_eval, eval_user_ids, labels_by_user, config.metric_ks)
    reranked_metrics = _evaluate_rows(reranked_rows_for_eval, eval_user_ids, labels_by_user, config.metric_ks)
    comparison = {
        metric: round(float(reranked_metrics.get(metric, 0.0)) - float(original_metrics.get(metric, 0.0)), 8)
        for metric in sorted(original_metrics)
        if metric.startswith(("Recall@", "HitRate@"))
    }
    metrics = {
        "schema_version": f"{SCHEMA_VERSION}_metrics",
        "status": "PASS",
        "metric_contract": "Final Recall/HitRate after reranking existing pool500 candidate rows by train-only RPA score; labels are evaluation-only.",
        "original": original_metrics,
        "rpa_reranked": reranked_metrics,
        "delta_rpa_reranked_vs_original": comparison,
    }
    write_json(output_dir / "metrics.json", metrics)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "manifest_path": str(output_dir / "manifest.json"),
        "run_id": config.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(perf_counter() - started, 6),
        "baseline_manifest": str(baseline_manifest_path),
        "candidate_artifact_path": str(candidate_path),
        "train_index_scope": f"ranked_interactions.row_num <= {train_end_row}",
        "eval_label_role": "evaluation_only_not_scoring_inputs",
        "parameters": {
            "strategy": config.strategy,
            "k": config.k,
            "k_prime": config.k_prime,
            "zeta": config.zeta,
            "lambda_weight": config.lambda_weight,
            "phi": config.phi,
            "max_index_users": config.max_index_users,
            "max_users_per_item": config.max_users_per_item,
            "max_items_per_user": config.max_items_per_user,
        },
        "index_stats": {
            "eval_user_count": len(eval_user_ids),
            "target_users_with_train": len(target_ratings),
            "anchor_item_count": len(anchor_items),
            "candidate_item_count": len(candidate_items),
            "neighbor_stats": neighbor_stats,
            "index_user_count": len(ratings_by_user),
            "index_item_count": len(item_users),
            "index_rating_count": sum(len(v) for v in ratings_by_user.values()),
            "similarity_cache_size": len(engine.sim_cache),
            "prediction_cache_size": len(engine.pred_cache),
            "empty_denominator_count": engine.empty_denominator_count,
            "recursive_fallback_count": engine.recursive_fallback_count,
        },
        "outputs": {
            "scored_candidates": str(scored_rows_path),
            "reranked_candidates": str(reranked_path),
            "metrics": str(output_dir / "metrics.json"),
        },
        "comparison": comparison,
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _load_candidates(candidate_path: Path, eval_user_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    wanted = set(eval_user_ids)
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_jsonl(candidate_path):
        user_id = str(row.get("user_id") or "")
        if user_id not in wanted:
            continue
        item_id = str(row.get("item_id") or row.get("parent_asin") or "")
        if not item_id:
            continue
        rank = _int_value(row.get("rank"), len(by_user[user_id]) + 1)
        by_user[user_id].append({"user_id": user_id, "item_id": item_id, "rank": rank, "score": row.get("score"), "raw": dict(row)})
    missing = [user_id for user_id in eval_user_ids if user_id not in by_user]
    if missing:
        raise ValueError(f"candidate rows missing eval users: {missing[:5]}")
    for user_id in eval_user_ids:
        by_user[user_id].sort(key=lambda row: row["rank"])
    return dict(by_user)


def _evaluate_rows(rows_by_user: dict[str, list[dict[str, Any]]], eval_user_ids: list[str], labels_by_user: dict[str, set[str]], metric_ks: tuple[int, ...]) -> dict[str, float]:
    payload: dict[str, float] = {}
    for k in metric_ks:
        recall_sum = 0.0
        hit_sum = 0.0
        for user_id in eval_user_ids:
            labels = labels_by_user[user_id]
            top_items = {str(row.get("item_id") or row.get("parent_asin") or "") for row in rows_by_user[user_id] if _int_value(row.get("rank"), 10**9) <= k}
            hits = top_items & labels
            recall_sum += len(hits) / len(labels) if labels else 0.0
            hit_sum += 1.0 if hits else 0.0
        payload[f"Recall@{k}"] = round(recall_sum / len(eval_user_ids), 6) if eval_user_ids else 0.0
        payload[f"HitRate@{k}"] = round(hit_sum / len(eval_user_ids), 6) if eval_user_ids else 0.0
    return payload


def _load_train_ratings_for_users(con: sqlite3.Connection, users: list[str] | set[str], train_end_row: int, max_items_per_user: int) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    if max_items_per_user > 0:
        query = """
            select parent_asin, rating
            from ranked_interactions
            where user_id = ? and row_num <= ? and rating is not null
            order by timestamp desc, parent_asin
            limit ?
        """
    else:
        query = """
            select parent_asin, rating
            from ranked_interactions
            where user_id = ? and row_num <= ? and rating is not null
            order by timestamp desc, parent_asin
        """
    for user_id in users:
        params: tuple[Any, ...] = (user_id, train_end_row, max_items_per_user) if max_items_per_user > 0 else (user_id, train_end_row)
        ratings = {str(item_id): float(rating) for item_id, rating in con.execute(query, params) if item_id and rating is not None}
        if ratings:
            result[str(user_id)] = ratings
    return result


def _load_neighbor_users_for_items(con: sqlite3.Connection, items: list[str], train_end_row: int, max_users_per_item: int, max_index_users: int) -> tuple[list[str], dict[str, Any]]:
    users = []
    seen = set()
    stats = Counter()
    query = """
        select user_id
        from ranked_interactions
        where parent_asin = ? and row_num <= ?
        order by timestamp desc, user_id
        limit ?
    """
    for item_id in items:
        stats["items_scanned"] += 1
        for (user_id,) in con.execute(query, (item_id, train_end_row, max_users_per_item)):
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            users.append(str(user_id))
            stats["neighbor_users_selected"] += 1
            if len(users) >= max_index_users:
                stats["truncated_by_max_index_users"] = 1
                return users, dict(stats)
    return users, dict(stats)


def _invert_index(ratings_by_user: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    item_users: dict[str, dict[str, float]] = defaultdict(dict)
    for user_id, ratings in ratings_by_user.items():
        for item_id, rating in ratings.items():
            item_users[item_id][user_id] = rating
    return dict(item_users)


def _merge_limited(first: list[str], second: list[str], limit: int) -> list[str]:
    rows = []
    seen = set()
    for user_id in first + second:
        if user_id in seen:
            continue
        seen.add(user_id)
        rows.append(user_id)
        if len(rows) >= limit:
            break
    return rows


def _merge_sources(raw_sources: Any, new_source: str) -> list[str]:
    sources = [str(source) for source in raw_sources] if isinstance(raw_sources, list) else []
    if new_source not in sources:
        sources.insert(0, new_source)
    return sources or [new_source]


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_config(config: Config) -> None:
    if config.strategy not in {"BS", "BS+", "SS", "CS", "CS+"}:
        raise ValueError("strategy must be one of BS, BS+, SS, CS, CS+")
    if config.max_index_users <= 0 or config.max_users_per_item <= 0:
        raise ValueError("max_index_users and max_users_per_item must be positive")
    if not 0.0 <= config.lambda_weight <= 1.0:
        raise ValueError("lambda_weight must be in [0, 1]")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _prepare_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)


if __name__ == "__main__":
    main()
