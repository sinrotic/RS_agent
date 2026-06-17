from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
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

SCHEMA_VERSION = "rpa_paper_adapted_rating_dataset_v1"
DEFAULT_CLEAN_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "rpa_strict_zhang_pu_2007" / "paper_adapted_formal_v1"
MAX_ALLOWED_RSS_MB = 5120


@dataclass(frozen=True)
class Config:
    clean_root: Path = DEFAULT_CLEAN_ROOT
    output_dir: Path = DEFAULT_OUTPUT_DIR
    run_id: str = "rpa_paper_adapted_formal_v1"
    min_user_ratings: int = 20
    inner_train_ratio: float = 0.8
    split_seed: int = 2007
    max_users: int = 0
    max_ratings_per_user: int = 0
    max_rss_mb: int = 4096
    overwrite: bool = False
    enforce_venv: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a paper-adapted formal rating dataset for strict Zhang & Pu 2007 RPA experiments.")
    parser.add_argument("--clean-root", type=Path, default=DEFAULT_CLEAN_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default="rpa_paper_adapted_formal_v1")
    parser.add_argument("--min-user-ratings", type=int, default=20)
    parser.add_argument("--inner-train-ratio", type=float, default=0.8)
    parser.add_argument("--split-seed", type=int, default=2007)
    parser.add_argument("--max-users", type=int, default=0, help="0 means all eligible train-window users.")
    parser.add_argument("--max-ratings-per-user", type=int, default=0, help="0 means keep all train-window ratings per eligible user.")
    parser.add_argument("--max-rss-mb", type=int, default=4096)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_dataset(
        Config(
            clean_root=args.clean_root,
            output_dir=args.output_dir,
            run_id=args.run_id,
            min_user_ratings=args.min_user_ratings,
            inner_train_ratio=args.inner_train_ratio,
            split_seed=args.split_seed,
            max_users=args.max_users,
            max_ratings_per_user=args.max_ratings_per_user,
            max_rss_mb=args.max_rss_mb,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["manifest_path"], "dataset_stats": manifest["dataset_stats"]}, ensure_ascii=False, indent=2))


def build_dataset(config: Config) -> dict[str, Any]:
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
    source_sqlite = clean_root / "recall_clean.sqlite"
    dataset_sqlite = output_dir / "rpa_paper_adapted_ratings.sqlite"

    memory_samples = []
    _sample_memory(memory_samples, "start")
    counters: Counter[str] = Counter()

    src = sqlite3.connect(source_sqlite)
    src.execute("pragma temp_store=memory")
    src.execute("pragma cache_size=-200000")
    dst = sqlite3.connect(dataset_sqlite)
    try:
        _init_dataset_db(dst)
        _sample_memory(memory_samples, "after_init_output_db")
        candidate_users = _iter_candidate_users(src, config.min_user_ratings)
        query = _user_train_rows_query(config.max_ratings_per_user)
        with dst:
            for user_id in candidate_users:
                rows = list(src.execute(query.sql, query.params(user_id, train_end_row)))
                counters["candidate_user_count"] += 1
                if len(rows) < config.min_user_ratings:
                    counters["dropped_train_rating_lt_min"] += 1
                    continue
                train_rows, eval_rows = _split_user_rows(str(user_id), rows, config.inner_train_ratio, config.split_seed)
                if not train_rows or not eval_rows:
                    counters["dropped_empty_inner_split"] += 1
                    continue
                _insert_rows(dst, "train_ratings", str(user_id), train_rows)
                _insert_rows(dst, "eval_pairs", str(user_id), eval_rows)
                counters["eligible_user_count"] += 1
                counters["train_rating_count"] += len(train_rows)
                counters["eval_pair_count"] += len(eval_rows)
                if config.max_users > 0 and counters["eligible_user_count"] >= config.max_users:
                    counters["truncated_by_max_users"] = 1
                    break
                if counters["eligible_user_count"] % 1000 == 0:
                    _sample_memory(memory_samples, f"after_{counters['eligible_user_count']}_users")
                    _enforce_memory(memory_samples, config.max_rss_mb)
        _create_dataset_indexes(dst)
        _sample_memory(memory_samples, "after_create_indexes")
    finally:
        src.close()
        dst.close()

    _enforce_memory(memory_samples, config.max_rss_mb)
    runtime_seconds = round(perf_counter() - started, 6)
    dataset_stats = dict(counters)
    dataset_stats.update(_dataset_db_stats(dataset_sqlite))

    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}_resource_audit",
        "status": "PASS",
        "max_rss_mb": config.max_rss_mb,
        "max_allowed_rss_mb": MAX_ALLOWED_RSS_MB,
        "peak_rss_mb": max((sample.get("rss_mb") or 0.0) for sample in memory_samples) if memory_samples else None,
        "memory_samples": memory_samples,
        "runtime_seconds": runtime_seconds,
    }
    no_label_audit = {
        "schema_version": f"{SCHEMA_VERSION}_no_label_backflow_audit",
        "status": "PASS",
        "train_window_scope": f"ranked_interactions.row_num <= {train_end_row}",
        "inner_split_scope": "80/20-style deterministic split inside the project train window only",
        "valid_test_rows_used_for_build": False,
        "label_backflow_allowed": False,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "manifest_path": str(output_dir / "manifest.json"),
        "run_id": config.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paper_basis": {
            "title": "A recursive prediction algorithm for collaborative filtering recommender systems",
            "authors": ["Jiyong Zhang", "Pearl Pu"],
            "venue": "RecSys 2007",
            "doi": "10.1145/1297231.1297241",
            "paper_like_parts": [
                "explicit user-item-rating rows",
                "missing ratings remain missing, not zero-filled",
                "minimum user rating count filter",
                "80/20-style rating prediction split",
                "MAE/RMSE rating prediction evaluation",
            ],
        },
        "local_adaptation": {
            "source_data": "Amazon clean full sqlite ranked_interactions",
            "split_policy": "paper_like_80_20_within_project_train_window",
            "train_window_scope": f"row_num <= {train_end_row}",
            "why_not_global_random_split": "Project governance forbids future valid/test rows from entering build inputs.",
            "not_topn_recall_dataset": True,
            "diagnostic_only": True,
        },
        "parameters": {
            "min_user_ratings": config.min_user_ratings,
            "inner_train_ratio": config.inner_train_ratio,
            "split_seed": config.split_seed,
            "max_users": config.max_users,
            "max_ratings_per_user": config.max_ratings_per_user,
            "max_rss_mb": config.max_rss_mb,
        },
        "outputs": {
            "dataset_sqlite": str(dataset_sqlite),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_label_backflow_audit": str(output_dir / "no_label_backflow_audit.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "dataset_stats": dataset_stats,
        "resource_status": "PASS",
        "no_label_backflow_status": "PASS",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_label_backflow_audit.json", no_label_audit)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


class _UserQuery:
    def __init__(self, sql: str, capped: bool) -> None:
        self.sql = sql
        self.capped = capped

    def params(self, user_id: str, train_end_row: int) -> tuple[Any, ...]:
        if self.capped:
            return (user_id, train_end_row, self.limit)
        return (user_id, train_end_row)


def _user_train_rows_query(max_ratings_per_user: int) -> Any:
    if max_ratings_per_user > 0:
        query = _UserQuery(
            """
            select parent_asin, rating, row_num, timestamp
            from ranked_interactions
            where user_id = ? and row_num <= ? and rating is not null
            order by row_num, parent_asin
            limit ?
            """,
            True,
        )
        query.limit = max_ratings_per_user
        return query
    return _UserQuery(
        """
        select parent_asin, rating, row_num, timestamp
        from ranked_interactions
        where user_id = ? and row_num <= ? and rating is not null
        order by row_num, parent_asin
        """,
        False,
    )


def _iter_candidate_users(con: sqlite3.Connection, min_user_ratings: int) -> Any:
    # stable_user_counts is only a superset prefilter; final eligibility is recomputed on train-window rows.
    yield from (row[0] for row in con.execute(
        "select user_id from stable_user_counts where interaction_count >= ? order by user_id",
        (min_user_ratings,),
    ))


def _split_user_rows(user_id: str, rows: list[tuple[str, float, int, int]], train_ratio: float, seed: int) -> tuple[list[tuple[str, float, int, int]], list[tuple[str, float, int, int]]]:
    eval_cutoff = int(round((1.0 - train_ratio) * 10_000))
    train_rows = []
    eval_rows = []
    for item_id, rating, row_num, timestamp in rows:
        bucket = _stable_bucket(user_id, str(item_id), int(row_num), seed)
        target = eval_rows if bucket < eval_cutoff else train_rows
        target.append((str(item_id), float(rating), int(row_num), int(timestamp or 0)))
    if not eval_rows and train_rows:
        eval_rows.append(train_rows.pop())
    if not train_rows and eval_rows:
        train_rows.append(eval_rows.pop(0))
    return train_rows, eval_rows


def _stable_bucket(user_id: str, item_id: str, row_num: int, seed: int) -> int:
    raw = f"{seed}\t{user_id}\t{item_id}\t{row_num}".encode("utf-8")
    return int(hashlib.blake2b(raw, digest_size=8).hexdigest(), 16) % 10_000


def _init_dataset_db(con: sqlite3.Connection) -> None:
    con.execute("pragma journal_mode=wal")
    con.execute("pragma synchronous=normal")
    con.execute("drop table if exists train_ratings")
    con.execute("drop table if exists eval_pairs")
    con.execute("create table train_ratings(user_id text not null, item_id text not null, rating real not null, source_row_num integer not null, timestamp integer)")
    con.execute("create table eval_pairs(user_id text not null, item_id text not null, rating real not null, source_row_num integer not null, timestamp integer)")


def _insert_rows(con: sqlite3.Connection, table: str, user_id: str, rows: list[tuple[str, float, int, int]]) -> None:
    con.executemany(
        f"insert into {table}(user_id, item_id, rating, source_row_num, timestamp) values (?, ?, ?, ?, ?)",
        [(user_id, item_id, rating, row_num, timestamp) for item_id, rating, row_num, timestamp in rows],
    )


def _create_dataset_indexes(con: sqlite3.Connection) -> None:
    con.execute("create index if not exists idx_rpa_train_user on train_ratings(user_id)")
    con.execute("create index if not exists idx_rpa_train_item on train_ratings(item_id)")
    con.execute("create index if not exists idx_rpa_eval_user on eval_pairs(user_id)")
    con.execute("create index if not exists idx_rpa_eval_row on eval_pairs(source_row_num)")


def _dataset_db_stats(path: Path) -> dict[str, Any]:
    con = sqlite3.connect(path)
    try:
        return {
            "train_distinct_users": con.execute("select count(distinct user_id) from train_ratings").fetchone()[0],
            "train_distinct_items": con.execute("select count(distinct item_id) from train_ratings").fetchone()[0],
            "eval_distinct_users": con.execute("select count(distinct user_id) from eval_pairs").fetchone()[0],
            "eval_distinct_items": con.execute("select count(distinct item_id) from eval_pairs").fetchone()[0],
            "sqlite_size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        }
    finally:
        con.close()


def _validate_config(config: Config) -> None:
    if config.min_user_ratings < 2:
        raise ValueError("min_user_ratings must be >= 2")
    if not 0.0 < config.inner_train_ratio < 1.0:
        raise ValueError("inner_train_ratio must be in (0, 1)")
    if config.max_users < 0 or config.max_ratings_per_user < 0:
        raise ValueError("max_users and max_ratings_per_user must be non-negative")
    if config.max_rss_mb <= 0 or config.max_rss_mb > MAX_ALLOWED_RSS_MB:
        raise ValueError(f"max_rss_mb must be in (0, {MAX_ALLOWED_RSS_MB}]")


def _sample_memory(samples: list[dict[str, Any]], stage: str) -> None:
    rss_mb = None
    try:
        import psutil  # type: ignore

        rss_mb = round(psutil.Process().memory_info().rss / 1024 / 1024, 3)
    except Exception:
        rss_mb = None
    samples.append({"stage": stage, "rss_mb": rss_mb, "created_at": datetime.now(timezone.utc).isoformat()})


def _enforce_memory(samples: list[dict[str, Any]], max_rss_mb: int) -> None:
    known = [sample["rss_mb"] for sample in samples if sample.get("rss_mb") is not None]
    if known and max(known) > max_rss_mb:
        raise MemoryError(f"RSS exceeded max_rss_mb={max_rss_mb}: peak={max(known):.3f}")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _prepare_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)


if __name__ == "__main__":
    main()
