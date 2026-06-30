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
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "rpa_strict_zhang_pu_2007_sqlite_smoke_v1"
DEFAULT_CLEAN_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_EVAL_USER_MANIFEST = ROOT / "outputs" / "eval" / "pool500_offline_eval_users_10k" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "rpa_strict_zhang_pu_2007" / "sqlite_smoke"
STRATEGIES = ("BS", "BS+", "SS", "CS", "CS+")


@dataclass(frozen=True)
class Config:
    clean_root: Path = DEFAULT_CLEAN_ROOT
    eval_user_manifest: Path = DEFAULT_EVAL_USER_MANIFEST
    output_dir: Path = DEFAULT_OUTPUT_ROOT
    run_id: str = "rpa_strict_sqlite_smoke"
    target_user_limit: int = 50
    max_index_users: int = 800
    max_users_per_item: int = 120
    max_items_per_user: int = 80
    max_eval_pairs: int = 120
    k: int = 10
    k_prime: int = 10
    zeta: int = 2
    lambda_weight: float = 0.5
    phi: int = 2
    min_eval_rating: float = 3.0
    min_train_unique_items: int = 2
    segments: tuple[str, ...] = ("hot", "warm")
    overwrite: bool = False
    enforce_venv: bool = True


@dataclass(frozen=True)
class EvalPair:
    user_id: str
    item_id: str
    true_rating: float
    row_num: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLite-backed strict Zhang & Pu 2007 RPA smoke experiment.")
    parser.add_argument("--clean-root", type=Path, default=DEFAULT_CLEAN_ROOT)
    parser.add_argument("--eval-user-manifest", type=Path, default=DEFAULT_EVAL_USER_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default="rpa_strict_sqlite_smoke")
    parser.add_argument("--target-user-limit", type=int, default=50)
    parser.add_argument("--max-index-users", type=int, default=800)
    parser.add_argument("--max-users-per-item", type=int, default=120)
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--max-eval-pairs", type=int, default=120)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--k-prime", type=int, default=10)
    parser.add_argument("--zeta", type=int, default=2)
    parser.add_argument("--lambda-weight", type=float, default=0.5)
    parser.add_argument("--phi", type=int, default=2)
    parser.add_argument("--min-eval-rating", type=float, default=3.0)
    parser.add_argument("--min-train-unique-items", type=int, default=2)
    parser.add_argument("--segments", default="hot,warm")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_experiment(
        Config(
            clean_root=args.clean_root,
            eval_user_manifest=args.eval_user_manifest,
            output_dir=args.output_dir,
            run_id=args.run_id,
            target_user_limit=args.target_user_limit,
            max_index_users=args.max_index_users,
            max_users_per_item=args.max_users_per_item,
            max_items_per_user=args.max_items_per_user,
            max_eval_pairs=args.max_eval_pairs,
            k=args.k,
            k_prime=args.k_prime,
            zeta=args.zeta,
            lambda_weight=args.lambda_weight,
            phi=args.phi,
            min_eval_rating=args.min_eval_rating,
            min_train_unique_items=args.min_train_unique_items,
            segments=tuple(part.strip() for part in args.segments.split(",") if part.strip()),
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["manifest_path"], "metrics": manifest["metrics_summary"]}, ensure_ascii=False, indent=2))


def run_experiment(config: Config) -> dict[str, Any]:
    started = perf_counter()
    if config.enforce_venv:
        enforce_project_venv(ROOT)
    _validate_config(config)
    clean_root = _resolve(config.clean_root)
    output_dir = _resolve(config.output_dir)
    _prepare_output(output_dir, config.overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = read_json(clean_root / "stats.json")
    train_end_row = int(stats["split_plan"]["train_end_row"])
    sqlite_path = clean_root / "recall_clean.sqlite"
    target_users = _load_target_users(
        _resolve(config.eval_user_manifest),
        config.target_user_limit,
        min_train_unique_items=config.min_train_unique_items,
        allowed_segments=set(config.segments),
    )

    con = sqlite3.connect(sqlite_path)
    con.execute("pragma temp_store=memory")
    con.execute("pragma cache_size=-200000")
    try:
        target_ratings = _load_train_ratings_for_users(con, target_users, train_end_row, config.max_items_per_user)
        anchor_items = {item for ratings in target_ratings.values() for item in ratings}
        neighbor_users, neighbor_stats = _load_neighbor_users_for_items(
            con, sorted(anchor_items), train_end_row, config.max_users_per_item, config.max_index_users
        )
        index_users = _merge_limited(target_users, neighbor_users, config.max_index_users)
        ratings_by_user = _load_train_ratings_for_users(con, index_users, train_end_row, config.max_items_per_user)
        for user_id, ratings in target_ratings.items():
            ratings_by_user.setdefault(user_id, {}).update(ratings)
        item_users = _invert_index(ratings_by_user)
        eval_pairs = _load_eval_pairs(con, target_users, train_end_row, config.max_eval_pairs, config.min_eval_rating)
    finally:
        con.close()

    predictor = RecursivePredictionEngine(
        ratings_by_user=ratings_by_user,
        item_users=item_users,
        k=config.k,
        k_prime=config.k_prime,
        zeta=config.zeta,
        lambda_weight=config.lambda_weight,
        phi=config.phi,
    )
    predictions_path = output_dir / "predictions.jsonl"
    metrics = _evaluate(predictor, eval_pairs, predictions_path)
    runtime_seconds = round(perf_counter() - started, 6)

    index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "run_id": config.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paper_basis": {
            "title": "A recursive prediction algorithm for collaborative filtering recommender systems",
            "authors": ["Jiyong Zhang", "Pearl Pu"],
            "venue": "RecSys 2007",
            "doi": "10.1145/1297231.1297241",
            "strict_parts": [
                "Pearson user similarity on co-rated observed train items",
                "BS/BS+/SS/CS/CS+ neighbor selection",
                "recursive prediction of missing neighbor rating for target item",
                "lambda-weighted recursively estimated ratings",
                "max recursive level zeta, fallback to BS",
                "MAE/RMSE evaluation on held-out rating targets",
            ],
        },
        "local_adaptation": {
            "data": "Amazon clean full sqlite ranked_interactions",
            "train_index_scope": f"row_num <= {train_end_row}",
            "eval_scope": f"row_num > {train_end_row} and rating >= {config.min_eval_rating}; evaluation only",
            "no_label_backflow": "Index users are expanded only from target users' train anchor items; valid/test target item ids are not used for index construction.",
            "not_candidate_generation": "This is rating-prediction diagnostic, not pool500 candidate generation or route replacement.",
        },
        "parameters": {
            "k": config.k,
            "k_prime": config.k_prime,
            "zeta": config.zeta,
            "lambda_weight": config.lambda_weight,
            "phi": config.phi,
            "target_user_limit": config.target_user_limit,
            "max_index_users": config.max_index_users,
            "max_users_per_item": config.max_users_per_item,
            "max_items_per_user": config.max_items_per_user,
            "max_eval_pairs": config.max_eval_pairs,
        },
        "index_stats": {
            "target_user_count": len(target_users),
            "target_users_with_train": len(target_ratings),
            "anchor_item_count": len(anchor_items),
            "neighbor_stats": neighbor_stats,
            "index_user_count": len(ratings_by_user),
            "index_item_count": len(item_users),
            "index_rating_count": sum(len(v) for v in ratings_by_user.values()),
            "eval_pair_count": len(eval_pairs),
        },
        "outputs": {
            "predictions": str(predictions_path),
            "metrics": str(output_dir / "metrics.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(output_dir / "index_manifest.json", index_manifest)
    write_json(output_dir / "metrics.json", metrics)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "manifest_path": str(output_dir / "manifest.json"),
        "index_manifest_path": str(output_dir / "index_manifest.json"),
        "metrics_summary": metrics["summary"],
        "runtime_seconds": runtime_seconds,
        "outputs": index_manifest["outputs"],
        "diagnostic_only": True,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


class RecursivePredictionEngine:
    def __init__(self, *, ratings_by_user: dict[str, dict[str, float]], item_users: dict[str, dict[str, float]], k: int, k_prime: int, zeta: int, lambda_weight: float, phi: int) -> None:
        self.ratings_by_user = ratings_by_user
        self.item_users = item_users
        self.k = k
        self.k_prime = k_prime
        self.zeta = zeta
        self.lambda_weight = lambda_weight
        self.phi = phi
        self.user_means = {u: _mean(r.values()) for u, r in ratings_by_user.items() if r}
        all_ratings = [v for r in ratings_by_user.values() for v in r.values()]
        self.global_mean = _mean(all_ratings) if all_ratings else 3.0
        self.sim_cache: dict[tuple[str, str], tuple[float, int]] = {}
        self.pred_cache: dict[tuple[str, str, int, str], float] = {}
        self.empty_denominator_count = 0
        self.recursive_fallback_count = 0

    def predict(self, user_id: str, item_id: str, strategy: str) -> float:
        return self._predict(user_id, item_id, 0, strategy, set())

    def _predict(self, user_id: str, item_id: str, level: int, strategy: str, stack: set[tuple[str, str, int, str]]) -> float:
        key = (user_id, item_id, level, strategy)
        if key in self.pred_cache:
            return self.pred_cache[key]
        if key in stack:
            self.recursive_fallback_count += 1
            return self._baseline(user_id, item_id)
        if level >= self.zeta:
            value = self._baseline(user_id, item_id)
            self.pred_cache[key] = value
            return value
        neighbors = self._select_neighbors(user_id, item_id, strategy)
        alpha = 0.0
        beta = 0.0
        stack.add(key)
        for neighbor_id, sim, _overlap in neighbors:
            if item_id in self.ratings_by_user.get(neighbor_id, {}):
                rating = self.ratings_by_user[neighbor_id][item_id]
                weight = 1.0
            else:
                rating = self._predict(neighbor_id, item_id, level + 1, strategy, stack)
                weight = self.lambda_weight
            alpha += weight * (rating - self._user_mean(neighbor_id)) * sim
            beta += weight * abs(sim)
        stack.remove(key)
        if beta <= 0.0:
            self.empty_denominator_count += 1
            value = self._fallback(user_id, item_id)
        else:
            value = self._user_mean(user_id) + alpha / beta
        value = _clip(value)
        self.pred_cache[key] = value
        return value

    def _baseline(self, user_id: str, item_id: str) -> float:
        neighbors = self._bs_neighbors(user_id, item_id, self.k, 0)
        alpha = 0.0
        beta = 0.0
        for neighbor_id, sim, _overlap in neighbors:
            rating = self.ratings_by_user.get(neighbor_id, {}).get(item_id)
            if rating is None:
                continue
            alpha += (rating - self._user_mean(neighbor_id)) * sim
            beta += abs(sim)
        if beta <= 0.0:
            return self._fallback(user_id, item_id)
        return _clip(self._user_mean(user_id) + alpha / beta)

    def _fallback(self, user_id: str, item_id: str) -> float:
        if item_id in self.item_users and self.item_users[item_id]:
            return _clip(_mean(self.item_users[item_id].values()))
        return _clip(self._user_mean(user_id))

    def _select_neighbors(self, user_id: str, item_id: str, strategy: str) -> list[tuple[str, float, int]]:
        if strategy == "BS":
            return self._bs_neighbors(user_id, item_id, self.k, 0)
        if strategy == "BS+":
            return self._bs_neighbors(user_id, item_id, self.k, self.phi)
        if strategy == "SS":
            return self._ss_neighbors(user_id, self.k_prime, 0)
        if strategy == "CS":
            return _merge(self._bs_neighbors(user_id, item_id, self.k, 0), self._ss_neighbors(user_id, self.k_prime, 0))
        if strategy == "CS+":
            return _merge(self._bs_neighbors(user_id, item_id, self.k, self.phi), self._ss_neighbors(user_id, self.k_prime, self.phi))
        raise ValueError(strategy)

    def _bs_neighbors(self, user_id: str, item_id: str, limit: int, min_overlap: int) -> list[tuple[str, float, int]]:
        rows = []
        for neighbor_id in self.item_users.get(item_id, {}):
            if neighbor_id == user_id:
                continue
            sim, overlap = self.similarity(user_id, neighbor_id)
            if sim != 0.0 and overlap >= min_overlap:
                rows.append((neighbor_id, sim, overlap))
        return _top(rows, limit)

    def _ss_neighbors(self, user_id: str, limit: int, min_overlap: int) -> list[tuple[str, float, int]]:
        candidate_users = set()
        for item_id in self.ratings_by_user.get(user_id, {}):
            candidate_users.update(self.item_users.get(item_id, {}))
        candidate_users.discard(user_id)
        rows = []
        for neighbor_id in candidate_users:
            sim, overlap = self.similarity(user_id, neighbor_id)
            if sim != 0.0 and overlap >= min_overlap:
                rows.append((neighbor_id, sim, overlap))
        return _top(rows, limit)

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
        else:
            left_mean = self._user_mean(left_user)
            right_mean = self._user_mean(right_user)
            numerator = sum((left[i] - left_mean) * (right[i] - right_mean) for i in common)
            left_norm = math.sqrt(sum((left[i] - left_mean) ** 2 for i in common))
            right_norm = math.sqrt(sum((right[i] - right_mean) ** 2 for i in common))
            result = (0.0, len(common)) if left_norm == 0.0 or right_norm == 0.0 else (numerator / (left_norm * right_norm), len(common))
        self.sim_cache[key] = result
        return result

    def _user_mean(self, user_id: str) -> float:
        return self.user_means.get(user_id, self.global_mean)


def _load_target_users(
    path: Path,
    limit: int,
    *,
    min_train_unique_items: int,
    allowed_segments: set[str],
) -> list[str]:
    payload = read_json(path)
    rows = payload.get("users") if isinstance(payload.get("users"), list) else []
    users = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        user_id = str(row.get("user_id") or "").strip()
        segment = str(row.get("segment") or "").strip()
        train_unique = int(row.get("train_unique_item_count") or row.get("train_recent_sequence_length") or 0)
        if allowed_segments and segment not in allowed_segments:
            continue
        if train_unique < min_train_unique_items:
            continue
        if user_id and user_id not in seen:
            seen.add(user_id)
            users.append(user_id)
            if len(users) >= limit:
                break
    if not users:
        raise ValueError(f"No users found in {path} for segments={sorted(allowed_segments)} and min_train_unique_items={min_train_unique_items}")
    return users


def _load_train_ratings_for_users(con: sqlite3.Connection, users: list[str] | set[str], train_end_row: int, max_items_per_user: int) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    query = """
        select parent_asin, rating
        from ranked_interactions
        where user_id = ? and row_num <= ?
        order by timestamp desc, parent_asin
        limit ?
    """
    for user_id in users:
        ratings = {}
        for item_id, rating in con.execute(query, (user_id, train_end_row, max_items_per_user)):
            if item_id and rating is not None:
                ratings[str(item_id)] = _clip(float(rating))
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
        stats["anchor_items_scanned"] += 1
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


def _load_eval_pairs(con: sqlite3.Connection, users: list[str], train_end_row: int, max_eval_pairs: int, min_rating: float) -> list[EvalPair]:
    pairs = []
    query = """
        select row_num, parent_asin, rating
        from ranked_interactions
        where user_id = ? and row_num > ? and rating >= ?
        order by row_num, parent_asin
    """
    seen = set()
    for user_id in users:
        for row_num, item_id, rating in con.execute(query, (user_id, train_end_row, min_rating)):
            key = (user_id, item_id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(EvalPair(str(user_id), str(item_id), _clip(float(rating)), int(row_num)))
            if len(pairs) >= max_eval_pairs:
                return pairs
    return pairs


def _invert_index(ratings_by_user: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    item_users: dict[str, dict[str, float]] = defaultdict(dict)
    for user_id, ratings in ratings_by_user.items():
        for item_id, rating in ratings.items():
            item_users[item_id][user_id] = rating
    return dict(item_users)


def _evaluate(engine: RecursivePredictionEngine, pairs: list[EvalPair], predictions_path: Path) -> dict[str, Any]:
    by_strategy: dict[str, list[float]] = {strategy: [] for strategy in STRATEGIES}
    with predictions_path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            for strategy in STRATEGIES:
                pred = engine.predict(pair.user_id, pair.item_id, strategy)
                err = abs(pair.true_rating - pred)
                by_strategy[strategy].append(err)
                handle.write(json.dumps({
                    "strategy": strategy,
                    "user_id": pair.user_id,
                    "item_id": pair.item_id,
                    "row_num": pair.row_num,
                    "true_rating": pair.true_rating,
                    "predicted_rating": round(pred, 6),
                    "abs_error": round(err, 6),
                }, ensure_ascii=False) + "\n")
    strategies = {}
    for strategy, errors in by_strategy.items():
        strategies[strategy] = {
            "prediction_count": len(errors),
            "mae": round(_mean(errors), 8) if errors else None,
            "rmse": round(math.sqrt(_mean([e * e for e in errors])), 8) if errors else None,
        }
    bs = strategies["BS"]["mae"]
    for strategy, metrics in strategies.items():
        mae = metrics["mae"]
        metrics["mae_delta_vs_bs"] = round(mae - bs, 8) if mae is not None and bs is not None else None
    best = min((s for s in STRATEGIES if strategies[s]["mae"] is not None), key=lambda s: strategies[s]["mae"], default=None)
    return {
        "schema_version": "rpa_strict_sqlite_smoke_metrics_v1",
        "status": "PASS",
        "metric_contract": "MAE/RMSE on held-out positive rating rows; labels are evaluation-only",
        "strategies": strategies,
        "summary": {
            "eval_pair_count": len(pairs),
            "best_strategy_by_mae": best,
            "recursive_fallback_count": engine.recursive_fallback_count,
            "empty_denominator_count": engine.empty_denominator_count,
            "similarity_cache_size": len(engine.sim_cache),
            "prediction_cache_size": len(engine.pred_cache),
        },
    }


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


def _merge(left: list[tuple[str, float, int]], right: list[tuple[str, float, int]]) -> list[tuple[str, float, int]]:
    merged = {row[0]: row for row in left}
    for row in right:
        old = merged.get(row[0])
        if old is None or abs(row[1]) > abs(old[1]):
            merged[row[0]] = row
    return _top(list(merged.values()), len(merged))


def _top(rows: list[tuple[str, float, int]], limit: int) -> list[tuple[str, float, int]]:
    rows.sort(key=lambda row: (-abs(row[1]), row[0]))
    return rows[:limit]


def _validate_config(config: Config) -> None:
    if config.target_user_limit <= 0 or config.max_index_users <= 0:
        raise ValueError("target_user_limit and max_index_users must be positive")
    if config.max_index_users < config.target_user_limit:
        raise ValueError("max_index_users must be >= target_user_limit")
    if not 0.0 <= config.lambda_weight <= 1.0:
        raise ValueError("lambda_weight must be in [0, 1]")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _prepare_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def _clip(value: float) -> float:
    return max(1.0, min(5.0, float(value))) if math.isfinite(value) else 3.0


if __name__ == "__main__":
    main()
