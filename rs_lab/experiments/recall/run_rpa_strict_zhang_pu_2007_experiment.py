from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
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

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "rpa_strict_zhang_pu_2007_experiment_v1"
INDEX_SCHEMA_VERSION = "rpa_strict_rating_index_v1"
PREDICTION_SCHEMA_VERSION = "rpa_strict_prediction_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_EVAL_USER_MANIFEST = ROOT / "outputs" / "eval" / "pool500_offline_eval_users_10k" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "rpa_strict_zhang_pu_2007"
DEFAULT_TARGET_USER_LIMIT = 200
DEFAULT_MAX_INDEX_USERS = 5000
DEFAULT_MAX_USERS_PER_ITEM = 500
DEFAULT_MAX_ITEMS_PER_USER = 80
DEFAULT_MAX_EVAL_PAIRS = 1000
DEFAULT_MAX_RSS_MB = 5120
POSITIVE_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")
FORBIDDEN_TRAIN_PATH_TOKENS = {"holdout", "oracle", "eval_label", "clean_10000", "pool1000"}
STRATEGIES = ("BS", "BS+", "SS", "CS", "CS+")


@dataclass(frozen=True)
class RPAStrictExperimentConfig:
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST
    eval_user_manifest_path: Path = DEFAULT_EVAL_USER_MANIFEST
    output_dir: Path = DEFAULT_OUTPUT_ROOT / "smoke"
    run_id: str = "rpa_strict_zhang_pu_2007_smoke"
    target_user_limit: int = DEFAULT_TARGET_USER_LIMIT
    max_index_users: int = DEFAULT_MAX_INDEX_USERS
    max_users_per_item: int = DEFAULT_MAX_USERS_PER_ITEM
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER
    max_eval_pairs: int = DEFAULT_MAX_EVAL_PAIRS
    k: int = 10
    k_prime: int = 10
    zeta: int = 2
    lambda_weight: float = 0.5
    phi: int = 10
    max_rss_mb: int = DEFAULT_MAX_RSS_MB
    overwrite: bool = False
    enforce_venv: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a paper-faithful Zhang & Pu 2007 Recursive Prediction Algorithm smoke experiment."
    )
    parser.add_argument("--clean-manifest", type=Path, default=DEFAULT_CLEAN_MANIFEST)
    parser.add_argument("--eval-user-manifest", type=Path, default=DEFAULT_EVAL_USER_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "smoke")
    parser.add_argument("--run-id", default="rpa_strict_zhang_pu_2007_smoke")
    parser.add_argument("--target-user-limit", type=int, default=DEFAULT_TARGET_USER_LIMIT)
    parser.add_argument("--max-index-users", type=int, default=DEFAULT_MAX_INDEX_USERS)
    parser.add_argument("--max-users-per-item", type=int, default=DEFAULT_MAX_USERS_PER_ITEM)
    parser.add_argument("--max-items-per-user", type=int, default=DEFAULT_MAX_ITEMS_PER_USER)
    parser.add_argument("--max-eval-pairs", type=int, default=DEFAULT_MAX_EVAL_PAIRS)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--k-prime", type=int, default=10)
    parser.add_argument("--zeta", type=int, default=2)
    parser.add_argument("--lambda-weight", type=float, default=0.5)
    parser.add_argument("--phi", type=int, default=10)
    parser.add_argument("--max-rss-mb", type=int, default=DEFAULT_MAX_RSS_MB)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_rpa_strict_zhang_pu_2007_experiment(
        RPAStrictExperimentConfig(
            clean_manifest_path=args.clean_manifest,
            eval_user_manifest_path=args.eval_user_manifest,
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
            max_rss_mb=args.max_rss_mb,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "manifest_path": manifest["manifest_path"],
                "metrics_path": manifest["outputs"]["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def run_rpa_strict_zhang_pu_2007_experiment(config: RPAStrictExperimentConfig) -> dict[str, Any]:
    started = perf_counter()
    if config.enforce_venv:
        enforce_project_venv(ROOT)
    _validate_config(config)

    output_dir = _resolve_path(config.output_dir)
    _prepare_output_dir(output_dir, config.overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    memory_samples: list[dict[str, Any]] = []
    _sample_memory(memory_samples, "start")
    _enforce_memory(memory_samples, config.max_rss_mb)

    clean_manifest_path = _resolve_path(config.clean_manifest_path)
    eval_user_manifest_path = _resolve_path(config.eval_user_manifest_path)
    clean_manifest = read_json(clean_manifest_path)
    split_paths = clean_manifest.get("split_paths") if isinstance(clean_manifest.get("split_paths"), dict) else {}
    train_path = _resolve_path(split_paths.get("train"))
    valid_path = _resolve_path(split_paths.get("valid"))
    test_path = _resolve_path(split_paths.get("test"))
    _validate_train_path(train_path)

    target_users = _load_target_users(eval_user_manifest_path, config.target_user_limit)
    target_user_set = set(target_users)
    target_ratings, target_seed_items, pass1_stats = _collect_target_train_ratings(
        train_path, target_user_set, config.max_items_per_user
    )
    _sample_memory(memory_samples, "after_target_train_scan")
    _enforce_memory(memory_samples, config.max_rss_mb)

    eval_pairs, _eval_target_items, label_stats = _collect_eval_pairs(
        (valid_path, test_path), target_user_set, config.max_eval_pairs
    )
    _sample_memory(memory_samples, "after_eval_pair_scan")
    _enforce_memory(memory_samples, config.max_rss_mb)

    neighbor_candidate_users, pass2_stats = _collect_neighbor_candidate_users(
        train_path,
        target_seed_items,
        config.max_users_per_item,
        config.max_index_users,
    )
    selected_users = _select_index_users(target_users, neighbor_candidate_users, config.max_index_users)
    selected_user_set = set(selected_users)
    selected_user_set.update(target_user_set)

    ratings_by_user, item_users, pass3_stats = _collect_selected_user_ratings(
        train_path,
        selected_user_set,
        config.max_items_per_user,
    )
    for user_id, ratings in target_ratings.items():
        ratings_by_user.setdefault(user_id, {}).update(ratings)
    _rebuild_item_users(item_users, ratings_by_user)
    _sample_memory(memory_samples, "after_rating_index_build")
    _enforce_memory(memory_samples, config.max_rss_mb)

    predictor = RecursivePredictionEngine(
        ratings_by_user=ratings_by_user,
        item_users=item_users,
        k=config.k,
        k_prime=config.k_prime,
        zeta=config.zeta,
        lambda_weight=config.lambda_weight,
        phi=config.phi,
    )
    predictions_path = output_dir / "rpa_strict_predictions.jsonl"
    metrics = _evaluate_predictions(predictor, eval_pairs, predictions_path)
    _sample_memory(memory_samples, "after_prediction_eval")
    _enforce_memory(memory_samples, config.max_rss_mb)

    index_manifest_path = output_dir / "rpa_strict_index_manifest.json"
    metrics_path = output_dir / "rpa_strict_eval_metrics.json"
    resource_audit_path = output_dir / "resource_audit.json"
    no_oracle_audit_path = output_dir / "no_oracle_audit.json"
    manifest_path = output_dir / "experiment_manifest.json"
    runtime_seconds = round(perf_counter() - started, 6)
    peak_rss_mb = max((int(sample.get("rss_mb") or 0) for sample in memory_samples), default=0)

    index_manifest = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "status": "PASS",
        "run_id": config.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paper_basis": _paper_basis(),
        "local_adaptation": {
            "rating_matrix": "Amazon canonical train split explicit rating field; missing interactions remain missing, not zero",
            "eval_target_pairs": "valid/test positive rows are used only as held-out prediction targets",
            "split_policy": "existing chronological project train/valid/test split, not random 80/20 MovieLens split",
            "bounded_index_policy": "smoke index expands from target users to train users sharing target history/eval items, capped for local resource control",
        },
        "algorithm_parameters": _algorithm_params(config),
        "input_paths": {
            "clean_manifest": str(clean_manifest_path),
            "train_ratings": str(train_path),
            "valid_labels": str(valid_path),
            "test_labels": str(test_path),
            "eval_user_manifest": str(eval_user_manifest_path),
        },
        "target_user_count": len(target_users),
        "index_user_count": len(ratings_by_user),
        "index_item_count": len(item_users),
        "index_rating_count": sum(len(ratings) for ratings in ratings_by_user.values()),
        "eval_pair_count": len(eval_pairs),
        "pass_stats": {
            "target_train_scan": pass1_stats,
            "eval_pair_scan": label_stats,
            "neighbor_candidate_scan": pass2_stats,
            "selected_user_train_scan": pass3_stats,
        },
        "outputs": {
            "predictions": str(predictions_path),
            "metrics": str(metrics_path),
            "resource_audit": str(resource_audit_path),
            "no_oracle_audit": str(no_oracle_audit_path),
            "experiment_manifest": str(manifest_path),
        },
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(index_manifest_path, index_manifest)
    write_json(metrics_path, metrics)
    resource_audit = {
        "status": "PASS",
        "max_rss_mb": config.max_rss_mb,
        "peak_rss_mb": peak_rss_mb,
        "memory_samples": memory_samples,
        "runtime_seconds": runtime_seconds,
    }
    write_json(resource_audit_path, resource_audit)
    no_oracle_audit = {
        "status": "PASS",
        "train_inputs_for_index": [str(train_path)],
        "eval_only_inputs_for_scoring": [str(valid_path), str(test_path), str(eval_user_manifest_path)],
        "labels_role": "evaluation_only_prediction_targets_not_index_or_neighbor_selection",
        "no_label_backflow": True,
        "candidate_generation_allowed": False,
    }
    write_json(no_oracle_audit_path, no_oracle_audit)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "run_id": config.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest_path),
        "index_manifest_path": str(index_manifest_path),
        "outputs": index_manifest["outputs"],
        "metrics_summary": metrics.get("summary", {}),
        "resource_summary": {"peak_rss_mb": peak_rss_mb, "runtime_seconds": runtime_seconds},
        "diagnostic_only": True,
    }
    write_json(manifest_path, manifest)
    return manifest


class RecursivePredictionEngine:
    def __init__(
        self,
        *,
        ratings_by_user: dict[str, dict[str, float]],
        item_users: dict[str, dict[str, float]],
        k: int,
        k_prime: int,
        zeta: int,
        lambda_weight: float,
        phi: int,
    ) -> None:
        self.ratings_by_user = ratings_by_user
        self.item_users = item_users
        self.k = k
        self.k_prime = k_prime
        self.zeta = zeta
        self.lambda_weight = lambda_weight
        self.phi = phi
        self.user_means = {user: _mean(ratings.values()) for user, ratings in ratings_by_user.items() if ratings}
        all_ratings = [rating for ratings in ratings_by_user.values() for rating in ratings.values()]
        self.global_mean = _mean(all_ratings) if all_ratings else 3.0
        self.sim_cache: dict[tuple[str, str], tuple[float, int]] = {}
        self.pred_cache: dict[tuple[str, str, int, str], float] = {}
        self.recursion_fallback_count = 0
        self.empty_denominator_count = 0

    def predict(self, user_id: str, item_id: str, strategy: str) -> float:
        return self._predict(user_id, item_id, 0, strategy, set())

    def _predict(self, user_id: str, item_id: str, level: int, strategy: str, stack: set[tuple[str, str, int, str]]) -> float:
        key = (user_id, item_id, level, strategy)
        if key in self.pred_cache:
            return self.pred_cache[key]
        if key in stack:
            self.recursion_fallback_count += 1
            return self._baseline_prediction(user_id, item_id)
        if level > self.zeta:
            value = self._baseline_prediction(user_id, item_id)
            self.pred_cache[key] = value
            return value

        neighbors = self._select_neighbors(user_id, item_id, strategy)
        alpha = 0.0
        beta = 0.0
        stack.add(key)
        for neighbor_id, similarity, _overlap in neighbors:
            neighbor_ratings = self.ratings_by_user.get(neighbor_id, {})
            if item_id in neighbor_ratings:
                rating = neighbor_ratings[item_id]
                weight = 1.0
            else:
                rating = self._predict(neighbor_id, item_id, level + 1, strategy, stack)
                weight = self.lambda_weight
            alpha += weight * (rating - self._user_mean(neighbor_id)) * similarity
            beta += weight * abs(similarity)
        stack.remove(key)
        if beta <= 0.0:
            self.empty_denominator_count += 1
            value = self._fallback_prediction(user_id, item_id)
        else:
            value = self._user_mean(user_id) + alpha / beta
        value = _clip_rating(value)
        self.pred_cache[key] = value
        return value

    def _baseline_prediction(self, user_id: str, item_id: str) -> float:
        neighbors = self._select_bs_neighbors(user_id, item_id, self.k, min_overlap=0)
        alpha = 0.0
        beta = 0.0
        for neighbor_id, similarity, _overlap in neighbors:
            rating = self.ratings_by_user.get(neighbor_id, {}).get(item_id)
            if rating is None:
                continue
            alpha += (rating - self._user_mean(neighbor_id)) * similarity
            beta += abs(similarity)
        if beta <= 0.0:
            return self._fallback_prediction(user_id, item_id)
        return _clip_rating(self._user_mean(user_id) + alpha / beta)

    def _fallback_prediction(self, user_id: str, item_id: str) -> float:
        item_ratings = self.item_users.get(item_id)
        if item_ratings:
            return _clip_rating(_mean(item_ratings.values()))
        return _clip_rating(self._user_mean(user_id))

    def _select_neighbors(self, user_id: str, item_id: str, strategy: str) -> list[tuple[str, float, int]]:
        if strategy == "BS":
            return self._select_bs_neighbors(user_id, item_id, self.k, min_overlap=0)
        if strategy == "BS+":
            return self._select_bs_neighbors(user_id, item_id, self.k, min_overlap=self.phi)
        if strategy == "SS":
            return self._select_ss_neighbors(user_id, self.k_prime, min_overlap=0)
        if strategy == "CS":
            return self._merge_neighbors(
                self._select_bs_neighbors(user_id, item_id, self.k, min_overlap=0),
                self._select_ss_neighbors(user_id, self.k_prime, min_overlap=0),
            )
        if strategy == "CS+":
            return self._merge_neighbors(
                self._select_bs_neighbors(user_id, item_id, self.k, min_overlap=self.phi),
                self._select_ss_neighbors(user_id, self.k_prime, min_overlap=self.phi),
            )
        raise ValueError(f"Unknown strategy: {strategy}")

    def _select_bs_neighbors(self, user_id: str, item_id: str, limit: int, *, min_overlap: int) -> list[tuple[str, float, int]]:
        candidates = []
        for neighbor_id in self.item_users.get(item_id, {}):
            if neighbor_id == user_id:
                continue
            similarity, overlap = self.similarity(user_id, neighbor_id)
            if overlap < min_overlap or similarity == 0.0:
                continue
            candidates.append((neighbor_id, similarity, overlap))
        return _top_neighbors(candidates, limit)

    def _select_ss_neighbors(self, user_id: str, limit: int, *, min_overlap: int) -> list[tuple[str, float, int]]:
        user_items = self.ratings_by_user.get(user_id, {})
        candidate_users: set[str] = set()
        for item_id in user_items:
            candidate_users.update(self.item_users.get(item_id, {}))
        candidate_users.discard(user_id)
        candidates = []
        for neighbor_id in candidate_users:
            similarity, overlap = self.similarity(user_id, neighbor_id)
            if overlap < min_overlap or similarity == 0.0:
                continue
            candidates.append((neighbor_id, similarity, overlap))
        return _top_neighbors(candidates, limit)

    def _merge_neighbors(
        self, left: list[tuple[str, float, int]], right: list[tuple[str, float, int]]
    ) -> list[tuple[str, float, int]]:
        merged: dict[str, tuple[str, float, int]] = {}
        for row in left + right:
            existing = merged.get(row[0])
            if existing is None or abs(row[1]) > abs(existing[1]):
                merged[row[0]] = row
        return _top_neighbors(list(merged.values()), len(merged))

    def similarity(self, left_user: str, right_user: str) -> tuple[float, int]:
        if left_user == right_user:
            return 1.0, len(self.ratings_by_user.get(left_user, {}))
        key = tuple(sorted((left_user, right_user)))
        cached = self.sim_cache.get(key)
        if cached is not None:
            return cached
        left = self.ratings_by_user.get(left_user, {})
        right = self.ratings_by_user.get(right_user, {})
        common = set(left) & set(right)
        if not common:
            result = (0.0, 0)
            self.sim_cache[key] = result
            return result
        left_mean = self._user_mean(left_user)
        right_mean = self._user_mean(right_user)
        numerator = sum((left[item] - left_mean) * (right[item] - right_mean) for item in common)
        left_norm = math.sqrt(sum((left[item] - left_mean) ** 2 for item in common))
        right_norm = math.sqrt(sum((right[item] - right_mean) ** 2 for item in common))
        if left_norm == 0.0 or right_norm == 0.0:
            result = (0.0, len(common))
        else:
            result = (numerator / (left_norm * right_norm), len(common))
        self.sim_cache[key] = result
        return result

    def _user_mean(self, user_id: str) -> float:
        return self.user_means.get(user_id, self.global_mean)


@dataclass(frozen=True)
class EvalPair:
    user_id: str
    item_id: str
    true_rating: float
    split: str


def _evaluate_predictions(
    predictor: RecursivePredictionEngine, eval_pairs: list[EvalPair], predictions_path: Path
) -> dict[str, Any]:
    rows_by_strategy: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in STRATEGIES}
    with predictions_path.open("w", encoding="utf-8") as handle:
        for pair in eval_pairs:
            for strategy in STRATEGIES:
                predicted = predictor.predict(pair.user_id, pair.item_id, strategy)
                abs_error = abs(pair.true_rating - predicted)
                row = {
                    "schema_version": PREDICTION_SCHEMA_VERSION,
                    "strategy": strategy,
                    "user_id": pair.user_id,
                    "item_id": pair.item_id,
                    "split": pair.split,
                    "true_rating": pair.true_rating,
                    "predicted_rating": round(predicted, 6),
                    "abs_error": round(abs_error, 6),
                }
                rows_by_strategy[strategy].append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    strategy_metrics: dict[str, dict[str, Any]] = {}
    for strategy, rows in rows_by_strategy.items():
        errors = [float(row["abs_error"]) for row in rows]
        strategy_metrics[strategy] = {
            "prediction_count": len(rows),
            "mae": round(_mean(errors), 8) if errors else None,
            "rmse": round(math.sqrt(_mean([err * err for err in errors])), 8) if errors else None,
        }
    baseline_mae = strategy_metrics.get("BS", {}).get("mae")
    for strategy, metrics in strategy_metrics.items():
        mae = metrics.get("mae")
        metrics["mae_delta_vs_bs"] = round(mae - baseline_mae, 8) if mae is not None and baseline_mae is not None else None
    return {
        "schema_version": "rpa_strict_eval_metrics_v1",
        "status": "PASS",
        "metric_contract": "MAE/RMSE on held-out valid/test positive rating rows; labels are evaluation-only",
        "strategies": strategy_metrics,
        "summary": {
            "eval_pair_count": len(eval_pairs),
            "best_strategy_by_mae": min(
                (s for s in STRATEGIES if strategy_metrics[s]["mae"] is not None),
                key=lambda s: strategy_metrics[s]["mae"],
                default=None,
            ),
            "recursive_fallback_count": predictor.recursion_fallback_count,
            "empty_denominator_count": predictor.empty_denominator_count,
            "similarity_cache_size": len(predictor.sim_cache),
            "prediction_cache_size": len(predictor.pred_cache),
        },
    }


def _load_target_users(eval_user_manifest_path: Path, limit: int) -> list[str]:
    payload = read_json(eval_user_manifest_path)
    users = payload.get("users") if isinstance(payload.get("users"), list) else []
    result: list[str] = []
    seen: set[str] = set()
    for row in users:
        if not isinstance(row, dict):
            continue
        user_id = str(row.get("user_id") or "").strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        result.append(user_id)
        if limit and len(result) >= limit:
            break
    if not result:
        raise ValueError(f"No target users found in {eval_user_manifest_path}")
    return result


def _collect_target_train_ratings(
    train_path: Path, target_user_set: set[str], max_items_per_user: int
) -> tuple[dict[str, dict[str, float]], set[str], dict[str, Any]]:
    ratings_by_user: dict[str, dict[str, float]] = defaultdict(dict)
    stats = Counter()
    for row in iter_jsonl(train_path):
        stats["rows_scanned"] += 1
        user_id = _string_value(row, "user_id", "user")
        if user_id not in target_user_set:
            continue
        item_id = _string_value(row, "parent_asin", "item_id", "item")
        rating = _rating_value(row)
        if not item_id or rating is None:
            stats["missing_item_or_rating"] += 1
            continue
        if len(ratings_by_user[user_id]) >= max_items_per_user and item_id not in ratings_by_user[user_id]:
            stats["dropped_max_items_per_user"] += 1
            continue
        ratings_by_user[user_id][item_id] = rating
        stats["target_rating_rows"] += 1
    seed_items = {item_id for ratings in ratings_by_user.values() for item_id in ratings}
    stats["target_users_with_train"] = len(ratings_by_user)
    stats["target_seed_item_count"] = len(seed_items)
    return dict(ratings_by_user), seed_items, dict(stats)


def _collect_eval_pairs(
    label_paths: Iterable[Path], target_user_set: set[str], max_eval_pairs: int
) -> tuple[list[EvalPair], set[str], dict[str, Any]]:
    pairs: list[EvalPair] = []
    target_items: set[str] = set()
    stats = Counter()
    seen_pairs: set[tuple[str, str, str]] = set()
    for path in label_paths:
        split = path.name.split(".")[-2] if "." in path.name else path.stem
        for row in iter_jsonl(path):
            stats[f"{split}_rows_scanned"] += 1
            if not _is_positive(row):
                continue
            user_id = _string_value(row, "user_id", "user")
            if user_id not in target_user_set:
                continue
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            rating = _rating_value(row)
            if not item_id or rating is None:
                stats["missing_item_or_rating"] += 1
                continue
            key = (user_id, item_id, split)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            pairs.append(EvalPair(user_id=user_id, item_id=item_id, true_rating=rating, split=split))
            target_items.add(item_id)
            stats["eval_pairs"] += 1
            if max_eval_pairs and len(pairs) >= max_eval_pairs:
                stats["truncated_by_max_eval_pairs"] = 1
                return pairs, target_items, dict(stats)
    return pairs, target_items, dict(stats)


def _collect_neighbor_candidate_users(
    train_path: Path, anchor_items: set[str], max_users_per_item: int, max_index_users: int
) -> tuple[list[str], dict[str, Any]]:
    item_users: dict[str, list[str]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    stats = Counter()
    for row in iter_jsonl(train_path):
        stats["rows_scanned"] += 1
        item_id = _string_value(row, "parent_asin", "item_id", "item")
        if item_id not in anchor_items:
            continue
        user_id = _string_value(row, "user_id", "user")
        if not user_id:
            continue
        key = (item_id, user_id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        if len(item_users[item_id]) >= max_users_per_item:
            stats["dropped_max_users_per_item"] += 1
            continue
        item_users[item_id].append(user_id)
        stats["neighbor_user_hits"] += 1
    candidate_users: list[str] = []
    seen_users: set[str] = set()
    for item_id in sorted(item_users):
        for user_id in item_users[item_id]:
            if user_id in seen_users:
                continue
            seen_users.add(user_id)
            candidate_users.append(user_id)
            if len(candidate_users) >= max_index_users:
                stats["truncated_by_max_index_users"] = 1
                stats["candidate_user_count"] = len(candidate_users)
                return candidate_users, dict(stats)
    stats["candidate_user_count"] = len(candidate_users)
    return candidate_users, dict(stats)


def _select_index_users(target_users: list[str], candidate_users: list[str], max_index_users: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for user_id in target_users + candidate_users:
        if user_id in seen:
            continue
        seen.add(user_id)
        selected.append(user_id)
        if max_index_users and len(selected) >= max_index_users:
            break
    return selected


def _collect_selected_user_ratings(
    train_path: Path, selected_user_set: set[str], max_items_per_user: int
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, Any]]:
    ratings_by_user: dict[str, dict[str, float]] = defaultdict(dict)
    item_users: dict[str, dict[str, float]] = defaultdict(dict)
    stats = Counter()
    for row in iter_jsonl(train_path):
        stats["rows_scanned"] += 1
        user_id = _string_value(row, "user_id", "user")
        if user_id not in selected_user_set:
            continue
        item_id = _string_value(row, "parent_asin", "item_id", "item")
        rating = _rating_value(row)
        if not item_id or rating is None:
            stats["missing_item_or_rating"] += 1
            continue
        if len(ratings_by_user[user_id]) >= max_items_per_user and item_id not in ratings_by_user[user_id]:
            stats["dropped_max_items_per_user"] += 1
            continue
        ratings_by_user[user_id][item_id] = rating
        item_users[item_id][user_id] = rating
        stats["selected_rating_rows"] += 1
    stats["selected_user_count"] = len(ratings_by_user)
    stats["selected_item_count"] = len(item_users)
    return dict(ratings_by_user), dict(item_users), dict(stats)


def _rebuild_item_users(item_users: dict[str, dict[str, float]], ratings_by_user: dict[str, dict[str, float]]) -> None:
    item_users.clear()
    for user_id, ratings in ratings_by_user.items():
        for item_id, rating in ratings.items():
            item_users.setdefault(item_id, {})[user_id] = rating


def _paper_basis() -> dict[str, Any]:
    return {
        "title": "A recursive prediction algorithm for collaborative filtering recommender systems",
        "authors": ["Jiyong Zhang", "Pearl Pu"],
        "venue": "RecSys 2007",
        "doi": "10.1145/1297231.1297241",
        "algorithm_claim": "Pearson user similarity; BS/BS+/SS/CS/CS+ neighbor strategies; recursive prediction with lambda-weighted estimated neighbor ratings; max recursive level zeta; MAE evaluation on held-out ratings.",
        "access_note": "ACM DOI may be inaccessible; formula details cross-checked against accessible EPFL thesis chapter 'Recursive Collaborative Filtering'.",
    }


def _algorithm_params(config: RPAStrictExperimentConfig) -> dict[str, Any]:
    return {
        "similarity": "Pearson correlation over co-rated train items",
        "prediction_formula": "user_mean + weighted sum((neighbor_rating_or_recursive_prediction - neighbor_mean) * sim) / weighted sum(abs(sim))",
        "neighbor_strategies": list(STRATEGIES),
        "k": config.k,
        "k_prime": config.k_prime,
        "zeta": config.zeta,
        "lambda_weight": config.lambda_weight,
        "phi": config.phi,
        "max_depth_fallback": "conventional BS baseline prediction",
        "empty_neighbor_fallback": "item mean, else user mean, else global mean; engineering completion not explicitly specified in paper",
    }


def _validate_config(config: RPAStrictExperimentConfig) -> None:
    if config.target_user_limit <= 0:
        raise ValueError("target_user_limit must be positive")
    if config.max_index_users < config.target_user_limit:
        raise ValueError("max_index_users must be >= target_user_limit")
    if config.max_rss_mb > 5120:
        raise ValueError("max_rss_mb must be <= 5120 for local memory contract")
    if config.k <= 0 or config.k_prime <= 0:
        raise ValueError("k and k_prime must be positive")
    if not 0.0 <= config.lambda_weight <= 1.0:
        raise ValueError("lambda_weight must be in [0, 1]")
    if config.zeta < 0:
        raise ValueError("zeta must be non-negative")


def _validate_train_path(train_path: Path) -> None:
    raw = str(train_path).replace("\\", "/").lower()
    if any(token in raw for token in FORBIDDEN_TRAIN_PATH_TOKENS):
        raise ValueError(f"forbidden train path for index build: {train_path}")
    if "valid" in raw or "test" in raw:
        raise ValueError(f"train index cannot be built from eval split path: {train_path}")


def _resolve_path(value: Any) -> Path:
    raw_path = str(value).replace("\\", "/")
    repo_marker = f"/{ROOT.name}/"
    if repo_marker in raw_path:
        raw_path = raw_path.split(repo_marker, 1)[1]
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


def _prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"Output directory already exists and is non-empty: {output_dir}")
        shutil.rmtree(output_dir)


def _sample_memory(samples: list[dict[str, Any]], stage: str) -> None:
    rss_mb = None
    status = "unavailable"
    try:
        import psutil  # type: ignore

        rss_mb = int(psutil.Process().memory_info().rss / (1024 * 1024))
        status = "ok"
    except Exception as exc:  # pragma: no cover - psutil availability differs by environment.
        status = f"unavailable:{type(exc).__name__}"
    samples.append({"stage": stage, "rss_mb": rss_mb, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()})


def _enforce_memory(samples: list[dict[str, Any]], max_rss_mb: int) -> None:
    latest = samples[-1] if samples else {}
    rss_mb = latest.get("rss_mb")
    if rss_mb is not None and int(rss_mb) > max_rss_mb:
        raise MemoryError(f"RSS {rss_mb} MB exceeded max_rss_mb={max_rss_mb}")


def _string_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _rating_value(row: dict[str, Any]) -> float | None:
    for key in ("rating", "overall", "score"):
        value = row.get(key)
        if value is None:
            continue
        try:
            rating = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(rating):
            return _clip_rating(rating)
    return None


def _is_positive(row: dict[str, Any]) -> bool:
    for field in POSITIVE_FIELDS:
        if field not in row:
            continue
        value = row.get(field)
        if isinstance(value, bool):
            return value
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return bool(value)
    rating = _rating_value(row)
    return rating is not None and rating >= 4.0


def _top_neighbors(candidates: list[tuple[str, float, int]], limit: int) -> list[tuple[str, float, int]]:
    candidates.sort(key=lambda row: (-abs(row[1]), row[0]))
    return candidates[:limit]


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _clip_rating(value: float) -> float:
    if not math.isfinite(value):
        return 3.0
    return max(1.0, min(5.0, float(value)))


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"path": str(path), "size_bytes": size, "sha256": digest.hexdigest()}


if __name__ == "__main__":
    main()
