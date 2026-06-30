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

from rs_core.common.io import read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_lab.experiments.recall.run_rpa_strict_zhang_pu_2007_sqlite_smoke import (
    EvalPair,
    RecursivePredictionEngine,
    _evaluate,
    _invert_index,
)

SCHEMA_VERSION = "rpa_strict_zhang_pu_2007_paper_dataset_experiment_v1"
DEFAULT_DATASET_MANIFEST = ROOT / "outputs" / "recall" / "rpa_strict_zhang_pu_2007" / "paper_adapted_formal_v1" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "rpa_strict_zhang_pu_2007" / "paper_adapted_formal_experiment_v1"


@dataclass(frozen=True)
class Config:
    rating_dataset_manifest: Path = DEFAULT_DATASET_MANIFEST
    output_dir: Path = DEFAULT_OUTPUT_ROOT
    run_id: str = "rpa_paper_adapted_formal_experiment_v1"
    target_user_limit: int = 2000
    max_index_users: int = 12000
    max_users_per_item: int = 400
    max_items_per_user: int = 80
    max_eval_pairs: int = 5000
    k: int = 20
    k_prime: int = 20
    zeta: int = 2
    lambda_weight: float = 0.5
    phi: int = 2
    overwrite: bool = False
    enforce_venv: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strict Zhang & Pu 2007 RPA on a paper-adapted rating dataset.")
    parser.add_argument("--rating-dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default="rpa_paper_adapted_formal_experiment_v1")
    parser.add_argument("--target-user-limit", type=int, default=2000)
    parser.add_argument("--max-index-users", type=int, default=12000)
    parser.add_argument("--max-users-per-item", type=int, default=400)
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--max-eval-pairs", type=int, default=5000)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--k-prime", type=int, default=20)
    parser.add_argument("--zeta", type=int, default=2)
    parser.add_argument("--lambda-weight", type=float, default=0.5)
    parser.add_argument("--phi", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_experiment(
        Config(
            rating_dataset_manifest=args.rating_dataset_manifest,
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
    dataset_manifest_path = _resolve(config.rating_dataset_manifest)
    dataset_manifest = read_json(dataset_manifest_path)
    dataset_sqlite = _resolve(Path(dataset_manifest["outputs"]["dataset_sqlite"]))
    output_dir = _resolve(config.output_dir)
    _prepare_output(output_dir, config.overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(dataset_sqlite)
    con.execute("pragma temp_store=memory")
    con.execute("pragma cache_size=-200000")
    try:
        target_users = _load_target_users(con, config.target_user_limit)
        target_ratings = _load_train_ratings_for_users(con, target_users, config.max_items_per_user)
        anchor_items = {item for ratings in target_ratings.values() for item in ratings}
        neighbor_users, neighbor_stats = _load_neighbor_users_for_items(con, sorted(anchor_items), config.max_users_per_item, config.max_index_users)
        index_users = _merge_limited(target_users, neighbor_users, config.max_index_users)
        ratings_by_user = _load_train_ratings_for_users(con, index_users, config.max_items_per_user)
        for user_id, ratings in target_ratings.items():
            ratings_by_user.setdefault(user_id, {}).update(ratings)
        item_users = _invert_index(ratings_by_user)
        eval_pairs = _load_eval_pairs(con, target_users, config.max_eval_pairs)
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
    metrics["metric_contract"] = "MAE/RMSE on deterministic inner 20% rating rows from the project train window; labels are evaluation-only within this paper-adapted dataset"
    runtime_seconds = round(perf_counter() - started, 6)

    index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "run_id": config.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rating_dataset_manifest": str(dataset_manifest_path),
        "paper_basis": dataset_manifest.get("paper_basis", {}),
        "local_adaptation": {
            "dataset_policy": "paper-like 80/20 split inside project train window",
            "train_source": "train_ratings table from paper-adapted dataset sqlite",
            "eval_source": "eval_pairs table from paper-adapted dataset sqlite",
            "valid_test_rows_used_for_build": False,
            "not_candidate_generation": True,
        },
        "parameters": {
            "target_user_limit": config.target_user_limit,
            "max_index_users": config.max_index_users,
            "max_users_per_item": config.max_users_per_item,
            "max_items_per_user": config.max_items_per_user,
            "max_eval_pairs": config.max_eval_pairs,
            "k": config.k,
            "k_prime": config.k_prime,
            "zeta": config.zeta,
            "lambda_weight": config.lambda_weight,
            "phi": config.phi,
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


def _load_target_users(con: sqlite3.Connection, limit: int) -> list[str]:
    rows = con.execute(
        """
        select e.user_id
        from eval_pairs e
        join train_ratings t on t.user_id = e.user_id
        group by e.user_id
        order by min(e.source_row_num), e.user_id
        limit ?
        """,
        (limit,),
    )
    return [str(row[0]) for row in rows]


def _load_train_ratings_for_users(con: sqlite3.Connection, users: list[str] | set[str], max_items_per_user: int) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    if max_items_per_user > 0:
        query = """
            select item_id, rating
            from train_ratings
            where user_id = ?
            order by source_row_num, item_id
            limit ?
        """
    else:
        query = """
            select item_id, rating
            from train_ratings
            where user_id = ?
            order by source_row_num, item_id
        """
    for user_id in users:
        params: tuple[Any, ...] = (user_id, max_items_per_user) if max_items_per_user > 0 else (user_id,)
        ratings = {str(item_id): float(rating) for item_id, rating in con.execute(query, params) if item_id and rating is not None}
        if ratings:
            result[str(user_id)] = ratings
    return result


def _load_neighbor_users_for_items(con: sqlite3.Connection, items: list[str], max_users_per_item: int, max_index_users: int) -> tuple[list[str], dict[str, Any]]:
    users = []
    seen = set()
    stats = Counter()
    query = """
        select user_id
        from train_ratings
        where item_id = ?
        order by source_row_num, user_id
        limit ?
    """
    for item_id in items:
        stats["anchor_items_scanned"] += 1
        for (user_id,) in con.execute(query, (item_id, max_users_per_item)):
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            users.append(str(user_id))
            stats["neighbor_users_selected"] += 1
            if len(users) >= max_index_users:
                stats["truncated_by_max_index_users"] = 1
                return users, dict(stats)
    return users, dict(stats)


def _load_eval_pairs(con: sqlite3.Connection, users: list[str], max_eval_pairs: int) -> list[EvalPair]:
    pairs = []
    seen = set()
    query = """
        select source_row_num, item_id, rating
        from eval_pairs
        where user_id = ?
        order by source_row_num, item_id
    """
    for user_id in users:
        for row_num, item_id, rating in con.execute(query, (user_id,)):
            key = (user_id, item_id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(EvalPair(str(user_id), str(item_id), float(rating), int(row_num)))
            if len(pairs) >= max_eval_pairs:
                return pairs
    return pairs


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


if __name__ == "__main__":
    main()
