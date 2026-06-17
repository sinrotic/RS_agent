from __future__ import annotations

import argparse
import json
import math
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
SCHEMA_VERSION = "rpa_pool500_per_user_rerank_diagnostic_v1"
DEFAULT_CLEAN_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_BASELINE_MANIFEST = ROOT / "outputs" / "eval" / "rpa_rerank_baseline_1000_20260606a" / "baseline_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "eval" / "rpa_per_user_rerank_diagnostic_1000_20260606a"


@dataclass(frozen=True)
class Config:
    baseline_manifest: Path = DEFAULT_BASELINE_MANIFEST
    clean_root: Path = DEFAULT_CLEAN_ROOT
    output_dir: Path = DEFAULT_OUTPUT_DIR
    run_id: str = "rpa_per_user_rerank_diagnostic_1000_20260606a"
    strategy: str = "CS"
    k: int = 20
    k_prime: int = 20
    zeta: int = 2
    lambda_weight: float = 0.5
    phi: int = 2
    max_users_per_anchor_item: int = 60
    max_users_per_candidate_item: int = 20
    max_neighbors_per_user: int = 1500
    max_items_per_neighbor: int = 80
    eval_user_limit: int = 0
    sparse_similarity_fallback: bool = True
    metric_ks: tuple[int, ...] = METRIC_KS
    overwrite: bool = False
    enforce_venv: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Per-user train-only RPA confidence-gated local rerank diagnostic for pool500 candidates.")
    parser.add_argument("--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST)
    parser.add_argument("--clean-root", type=Path, default=DEFAULT_CLEAN_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default="rpa_per_user_rerank_diagnostic_1000_20260606a")
    parser.add_argument("--strategy", default="CS")
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--k-prime", type=int, default=20)
    parser.add_argument("--zeta", type=int, default=2)
    parser.add_argument("--lambda-weight", type=float, default=0.5)
    parser.add_argument("--phi", type=int, default=2)
    parser.add_argument("--max-users-per-anchor-item", type=int, default=60)
    parser.add_argument("--max-users-per-candidate-item", type=int, default=20)
    parser.add_argument("--max-neighbors-per-user", type=int, default=1500)
    parser.add_argument("--max-items-per-neighbor", type=int, default=80)
    parser.add_argument("--eval-user-limit", type=int, default=0)
    parser.add_argument("--disable-sparse-similarity-fallback", action="store_true")
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
            max_users_per_anchor_item=args.max_users_per_anchor_item,
            max_users_per_candidate_item=args.max_users_per_candidate_item,
            max_neighbors_per_user=args.max_neighbors_per_user,
            max_items_per_neighbor=args.max_items_per_neighbor,
            eval_user_limit=args.eval_user_limit,
            sparse_similarity_fallback=not args.disable_sparse_similarity_fallback,
            metric_ks=tuple(_parse_metric_ks(args.metric_ks)),
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["manifest_path"], "best_delta": manifest["best_delta"]}, ensure_ascii=False, indent=2))


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
    if config.eval_user_limit > 0:
        selected_users = selected_users[: config.eval_user_limit]
    eval_user_ids = [str(user["user_id"]) for user in selected_users]
    labels_by_user = _load_labels_for_selected_users(eval_manifest, selected_users, eval_user_ids)
    candidates_by_user = _load_candidates(candidate_path, eval_user_ids)

    stats = read_json(clean_root / "stats.json")
    train_end_row = int(stats["split_plan"]["train_end_row"])
    con = sqlite3.connect(clean_root / "recall_clean.sqlite")
    con.execute("pragma temp_store=memory")
    con.execute("pragma cache_size=-200000")

    scored_path = output_dir / "scored_candidates.jsonl"
    scored_by_user: dict[str, list[dict[str, Any]]] = {}
    global_stats = Counter()
    try:
        with scored_path.open("w", encoding="utf-8") as handle:
            for user_index, user_id in enumerate(eval_user_ids, start=1):
                user_rows = candidates_by_user[user_id]
                target_ratings = _load_user_ratings(con, user_id, train_end_row, 0)
                if not target_ratings:
                    scored_by_user[user_id] = _fallback_scored_rows(user_rows)
                    global_stats["users_without_train"] += 1
                    continue
                candidate_items = [row["item_id"] for row in user_rows]
                neighbor_users, neighbor_stats = _collect_per_user_neighbors(con, target_ratings, candidate_items, train_end_row, config)
                ratings_by_user = {user_id: target_ratings}
                ratings_by_user.update(_load_ratings_for_users(con, neighbor_users, train_end_row, config.max_items_per_neighbor))
                item_users = _invert_index(ratings_by_user)
                engine = FastResidualEngine(
                    ratings_by_user=ratings_by_user,
                    item_users=item_users,
                    sparse_similarity_fallback=config.sparse_similarity_fallback,
                )
                user_mean = engine.user_mean(user_id)
                scored_rows = []
                for row in user_rows:
                    item_id = row["item_id"]
                    diagnostics = engine.predict(user_id, item_id)
                    rpa_score = diagnostics["score"]
                    residual = rpa_score - user_mean
                    supported = bool(diagnostics["supported"])
                    payload = dict(row["raw"])
                    payload.update({
                        "original_rank": row["rank"],
                        "rpa_score": round(rpa_score, 6),
                        "rpa_residual": round(residual, 6),
                        "rpa_neighbor_count": diagnostics["neighbor_count"],
                        "rpa_explicit_neighbor_count": diagnostics["explicit_neighbor_count"],
                        "rpa_denominator": round(diagnostics["denominator"], 6),
                        "rpa_supported": supported,
                    })
                    scored_rows.append(payload)
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    global_stats["candidate_count"] += 1
                    if supported:
                        global_stats["supported_candidate_count"] += 1
                    if item_id in labels_by_user[user_id]:
                        global_stats["positive_candidate_count"] += 1
                        if supported:
                            global_stats["supported_positive_candidate_count"] += 1
                global_stats.update({f"neighbor_{k}": v for k, v in neighbor_stats.items()})
                global_stats["similarity_cache_size_total"] += len(engine.sim_cache)
                global_stats["prediction_cache_size_total"] += engine.prediction_count
                global_stats["empty_denominator_count_total"] += engine.empty_denominator_count
                scored_by_user[user_id] = scored_rows
                if user_index % 100 == 0:
                    print(json.dumps({"processed_users": user_index, "supported_candidates": global_stats["supported_candidate_count"]}, ensure_ascii=False), flush=True)
    finally:
        con.close()

    strategy_rows = _build_strategy_rows(scored_by_user, eval_user_ids)
    strategy_metrics = {name: _evaluate_rows(rows, eval_user_ids, labels_by_user, config.metric_ks) for name, rows in strategy_rows.items()}
    original = strategy_metrics["original"]
    deltas = {name: _delta(metrics, original) for name, metrics in strategy_metrics.items() if name != "original"}
    best_name = max(deltas, key=lambda name: deltas[name].get("Recall@50", -999), default="")
    metrics_payload = {
        "schema_version": f"{SCHEMA_VERSION}_metrics",
        "status": "PASS",
        "metric_contract": "Final Recall/HitRate after conservative train-only RPA confidence-gated local reranking; labels are evaluation-only.",
        "strategies": strategy_metrics,
        "deltas_vs_original": deltas,
        "best_by_recall_at_50": best_name,
    }
    write_json(output_dir / "metrics.json", metrics_payload)
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
        "parameters": _config_payload(config),
        "coverage": dict(global_stats),
        "supported_candidate_ratio": round(global_stats["supported_candidate_count"] / global_stats["candidate_count"], 6) if global_stats["candidate_count"] else 0.0,
        "supported_positive_candidate_ratio": round(global_stats["supported_positive_candidate_count"] / global_stats["positive_candidate_count"], 6) if global_stats["positive_candidate_count"] else 0.0,
        "outputs": {"scored_candidates": str(scored_path), "metrics": str(output_dir / "metrics.json")},
        "best_delta": deltas.get(best_name, {}),
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


class FastResidualEngine:
    def __init__(
        self,
        *,
        ratings_by_user: dict[str, dict[str, float]],
        item_users: dict[str, dict[str, float]],
        sparse_similarity_fallback: bool,
    ) -> None:
        self.ratings_by_user = ratings_by_user
        self.item_users = item_users
        self.sparse_similarity_fallback = sparse_similarity_fallback
        self.user_means = {user_id: _mean(ratings.values()) for user_id, ratings in ratings_by_user.items() if ratings}
        all_ratings = [rating for ratings in ratings_by_user.values() for rating in ratings.values()]
        self.global_mean = _mean(all_ratings) if all_ratings else 3.0
        self.sim_cache: dict[tuple[str, str], tuple[float, int]] = {}
        self.prediction_count = 0
        self.empty_denominator_count = 0

    def predict(self, user_id: str, item_id: str) -> dict[str, Any]:
        self.prediction_count += 1
        alpha = 0.0
        beta = 0.0
        explicit_count = 0
        neighbor_count = 0
        for neighbor_id, rating in self.item_users.get(item_id, {}).items():
            if neighbor_id == user_id:
                continue
            sim, _overlap = self.similarity(user_id, neighbor_id)
            if sim == 0.0:
                continue
            neighbor_count += 1
            explicit_count += 1
            alpha += (rating - self.user_mean(neighbor_id)) * sim
            beta += abs(sim)
        if beta <= 0.0:
            self.empty_denominator_count += 1
            score = self.fallback(user_id, item_id)
            supported = False
        else:
            score = _clip(self.user_mean(user_id) + alpha / beta)
            supported = True
        return {
            "score": score,
            "supported": supported,
            "neighbor_count": neighbor_count,
            "explicit_neighbor_count": explicit_count,
            "denominator": beta,
        }

    def similarity(self, left_user: str, right_user: str) -> tuple[float, int]:
        key = tuple(sorted((left_user, right_user)))
        cached = self.sim_cache.get(key)
        if cached is not None:
            return cached
        left = self.ratings_by_user.get(left_user, {})
        right = self.ratings_by_user.get(right_user, {})
        common = set(left) & set(right)
        if not common:
            result = (0.0, 0)
        elif self.sparse_similarity_fallback and len(common) == 1:
            result = (1.0, 1)
        else:
            left_mean = self.user_mean(left_user)
            right_mean = self.user_mean(right_user)
            numerator = sum((left[item_id] - left_mean) * (right[item_id] - right_mean) for item_id in common)
            left_norm = math.sqrt(sum((left[item_id] - left_mean) ** 2 for item_id in common))
            right_norm = math.sqrt(sum((right[item_id] - right_mean) ** 2 for item_id in common))
            result = (0.0, len(common)) if left_norm == 0.0 or right_norm == 0.0 else (numerator / (left_norm * right_norm), len(common))
        self.sim_cache[key] = result
        return result

    def user_mean(self, user_id: str) -> float:
        return self.user_means.get(user_id, self.global_mean)

    def fallback(self, user_id: str, item_id: str) -> float:
        if item_id in self.item_users and self.item_users[item_id]:
            return _clip(_mean(self.item_users[item_id].values()))
        return _clip(self.user_mean(user_id))


def _build_strategy_rows(scored_by_user: dict[str, list[dict[str, Any]]], eval_user_ids: list[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    strategies: dict[str, dict[str, list[dict[str, Any]]]] = {}
    strategies["original"] = {u: _rerank(scored_by_user[u], "original") for u in eval_user_ids}
    strategies["pure_supported_residual"] = {u: _rerank(scored_by_user[u], "pure_supported_residual") for u in eval_user_ids}
    for bucket in (10, 20, 50):
        for alpha in (1.0, 2.0, 5.0):
            name = f"bucket{bucket}_conf_alpha{alpha:g}"
            strategies[name] = {u: _rerank(scored_by_user[u], "bucket_conf", bucket=bucket, alpha=alpha) for u in eval_user_ids}
    return strategies


def _rerank(rows: list[dict[str, Any]], mode: str, *, bucket: int = 20, alpha: float = 1.0) -> list[dict[str, Any]]:
    if mode == "original":
        ordered = sorted(rows, key=lambda r: int(r["original_rank"]))
    elif mode == "pure_supported_residual":
        ordered = sorted(rows, key=lambda r: (not bool(r.get("rpa_supported")), -float(r.get("rpa_residual") or 0.0), int(r["original_rank"])))
    elif mode == "bucket_conf":
        def key(row: dict[str, Any]) -> tuple[float, int]:
            original_rank = int(row["original_rank"])
            bucket_id = (original_rank - 1) // bucket
            if not row.get("rpa_supported"):
                adjusted = float(original_rank)
            else:
                adjusted = float(original_rank) - alpha * float(row.get("rpa_residual") or 0.0)
            return (bucket_id, adjusted, original_rank)  # type: ignore[return-value]
        ordered = sorted(rows, key=key)
    else:
        raise ValueError(mode)
    reranked = []
    for rank, row in enumerate(ordered, start=1):
        out = dict(row)
        out["rank"] = rank
        reranked.append(out)
    return reranked


def _load_labels_for_selected_users(eval_manifest: dict[str, Any], selected_users: list[dict[str, Any]], eval_user_ids: list[str]) -> dict[str, set[str]]:
    labels = {user_id: set() for user_id in eval_user_ids}
    manifest_users = eval_manifest.get("users") if isinstance(eval_manifest.get("users"), list) else []
    rows = selected_users if selected_users else manifest_users
    for row in rows:
        if not isinstance(row, dict):
            continue
        user_id = str(row.get("user_id") or "")
        if user_id not in labels:
            continue
        for item_id in row.get("positive_items_sample") or []:
            if item_id:
                labels[user_id].add(str(item_id))
    if all(labels[user_id] for user_id in eval_user_ids):
        return labels
    file_labels = _load_eval_labels(eval_manifest, eval_user_ids)
    for user_id, item_ids in file_labels.items():
        labels[user_id].update(item_ids)
    return labels


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
        by_user[user_id].append({"user_id": user_id, "item_id": item_id, "rank": rank, "raw": dict(row)})
    missing = [user_id for user_id in eval_user_ids if user_id not in by_user]
    if missing:
        raise ValueError(f"candidate rows missing eval users: {missing[:5]}")
    for user_id in eval_user_ids:
        by_user[user_id].sort(key=lambda row: row["rank"])
    return dict(by_user)


def _collect_per_user_neighbors(con: sqlite3.Connection, target_ratings: dict[str, float], candidate_items: list[str], train_end_row: int, config: Config) -> tuple[list[str], Counter[str]]:
    users = []
    seen = set()
    stats = Counter()
    for item_id, limit, role in [(item, config.max_users_per_anchor_item, "anchor") for item in target_ratings] + [(item, config.max_users_per_candidate_item, "candidate") for item in candidate_items]:
        stats[f"{role}_items_scanned"] += 1
        for (user_id,) in con.execute(
            """
            select user_id
            from ranked_interactions
            where parent_asin = ? and row_num <= ? and rating is not null
            limit ?
            """,
            (item_id, train_end_row, limit),
        ):
            if not user_id or user_id in seen:
                continue
            seen.add(str(user_id))
            users.append(str(user_id))
            stats["neighbor_users_selected"] += 1
            if len(users) >= config.max_neighbors_per_user:
                stats["truncated_by_max_neighbors_per_user"] += 1
                return users, stats
    return users, stats


def _load_user_ratings(con: sqlite3.Connection, user_id: str, train_end_row: int, limit: int) -> dict[str, float]:
    query = """
        select parent_asin, rating
        from ranked_interactions
        where user_id = ? and row_num <= ? and rating is not null
    """
    if limit > 0:
        query += " limit ?"
        rows = con.execute(query, (user_id, train_end_row, limit))
    else:
        rows = con.execute(query, (user_id, train_end_row))
    return {str(item_id): float(rating) for item_id, rating in rows if item_id}


def _load_ratings_for_users(con: sqlite3.Connection, users: list[str], train_end_row: int, limit: int) -> dict[str, dict[str, float]]:
    return {user_id: ratings for user_id in users if (ratings := _load_user_ratings(con, user_id, train_end_row, limit))}


def _invert_index(ratings_by_user: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    item_users: dict[str, dict[str, float]] = defaultdict(dict)
    for user_id, ratings in ratings_by_user.items():
        for item_id, rating in ratings.items():
            item_users[item_id][user_id] = rating
    return dict(item_users)


def _mean(values: Any) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def _clip(value: float) -> float:
    return min(5.0, max(1.0, value))


def _fallback_scored_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row["raw"]) | {"original_rank": row["rank"], "rpa_supported": False, "rpa_score": None, "rpa_residual": 0.0} for row in rows]


def _evaluate_rows(rows_by_user: dict[str, list[dict[str, Any]]], eval_user_ids: list[str], labels_by_user: dict[str, set[str]], metric_ks: tuple[int, ...]) -> dict[str, float]:
    payload = {}
    for k in metric_ks:
        recall_sum = 0.0
        hit_sum = 0.0
        for user_id in eval_user_ids:
            top_items = {str(row.get("item_id") or row.get("parent_asin") or "") for row in rows_by_user[user_id] if _int_value(row.get("rank"), 10**9) <= k}
            hits = top_items & labels_by_user[user_id]
            recall_sum += len(hits) / len(labels_by_user[user_id]) if labels_by_user[user_id] else 0.0
            hit_sum += 1.0 if hits else 0.0
        payload[f"Recall@{k}"] = round(recall_sum / len(eval_user_ids), 6)
        payload[f"HitRate@{k}"] = round(hit_sum / len(eval_user_ids), 6)
    return payload


def _delta(metrics: dict[str, float], original: dict[str, float]) -> dict[str, float]:
    return {key: round(metrics[key] - original[key], 8) for key in sorted(original)}


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_payload(config: Config) -> dict[str, Any]:
    return {
        "baseline_manifest": str(config.baseline_manifest),
        "clean_root": str(config.clean_root),
        "output_dir": str(config.output_dir),
        "run_id": config.run_id,
        "strategy": config.strategy,
        "k": config.k,
        "k_prime": config.k_prime,
        "zeta": config.zeta,
        "lambda_weight": config.lambda_weight,
        "phi": config.phi,
        "max_users_per_anchor_item": config.max_users_per_anchor_item,
        "max_users_per_candidate_item": config.max_users_per_candidate_item,
        "max_neighbors_per_user": config.max_neighbors_per_user,
        "max_items_per_neighbor": config.max_items_per_neighbor,
        "eval_user_limit": config.eval_user_limit,
        "sparse_similarity_fallback": config.sparse_similarity_fallback,
        "metric_ks": list(config.metric_ks),
        "overwrite": config.overwrite,
        "enforce_venv": config.enforce_venv,
    }


def _validate_config(config: Config) -> None:
    if config.strategy not in {"BS", "BS+", "SS", "CS", "CS+"}:
        raise ValueError("strategy must be one of BS, BS+, SS, CS, CS+")
    if min(config.max_users_per_anchor_item, config.max_users_per_candidate_item, config.max_neighbors_per_user) <= 0:
        raise ValueError("neighbor limits must be positive")
    if config.eval_user_limit < 0:
        raise ValueError("eval_user_limit must be non-negative")
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
