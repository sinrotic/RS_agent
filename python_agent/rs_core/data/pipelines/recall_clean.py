from __future__ import annotations

import json
import sqlite3
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_INPUT_MANIFEST = "./data/processed/amazon_2023_base/manifest.json"
DEFAULT_OUTPUT_DIR = "./data/processed/amazon_2023_recall_clean"
DEFAULT_VALID_RATIO = 0.1
DEFAULT_TEST_RATIO = 0.1
DEFAULT_POSITIVE_RATING_THRESHOLD = 4.0
DEFAULT_MIN_USER_INTERACTIONS = 1
DEFAULT_MIN_ITEM_INTERACTIONS = 1
DEFAULT_SEQUENCE_MAX_LEN = 50


def compact_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False)


def clean_scalar_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def flatten_text_list(value: Any) -> str:
    if not isinstance(value, list):
        return clean_scalar_text(value)
    parts = [clean_scalar_text(item) for item in value]
    return " ".join(part for part in parts if part)


def normalize_categories(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_scalar_text(item) for item in value if clean_scalar_text(item)]


def build_item_text(record: dict[str, Any]) -> str:
    title = clean_scalar_text(record.get("title"))
    categories = " > ".join(normalize_categories(record.get("categories")))
    description = flatten_text_list(record.get("description"))
    features = flatten_text_list(record.get("features"))
    return "\n".join(part for part in [title, categories, description, features] if part)


def ensure_ratio_args(valid_ratio: float, test_ratio: float) -> None:
    if valid_ratio < 0 or test_ratio < 0 or valid_ratio + test_ratio >= 1:
        raise ValueError("valid_ratio and test_ratio must be >= 0 and sum to < 1")


def ensure_positive_args(
    min_user_interactions: int,
    min_item_interactions: int,
    sequence_max_len: int,
    small_data_all_train_threshold: int,
) -> None:
    if min_user_interactions < 1 or min_item_interactions < 1:
        raise ValueError("min interaction thresholds must be >= 1")
    if sequence_max_len < 1:
        raise ValueError("sequence_max_len must be >= 1")
    if small_data_all_train_threshold < 0:
        raise ValueError("small_data_all_train_threshold must be >= 0")


def is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_dataset_path(
    manifest_path: Path,
    configured_path: str | None,
    category: str,
    filename: str,
) -> Path:
    allowed_root = manifest_path.parent.resolve()
    fallback = (manifest_path.parent / category / filename).resolve()
    if fallback.exists() and is_within_root(fallback, allowed_root):
        return fallback
    if configured_path:
        candidate = Path(configured_path)
        if not candidate.is_absolute():
            candidate = manifest_path.parent / candidate
        candidate = candidate.resolve()
        if candidate.exists() and is_within_root(candidate, allowed_root):
            return candidate
        if candidate.exists():
            raise ValueError(f"Configured path escapes dataset root: {candidate}")
    raise FileNotFoundError(f"Could not resolve {filename} for category={category}")


def setup_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_interactions (
            user_id TEXT NOT NULL,
            parent_asin TEXT NOT NULL,
            category TEXT NOT NULL,
            rating REAL,
            timestamp INTEGER NOT NULL,
            verified_purchase INTEGER NOT NULL,
            helpful_vote INTEGER NOT NULL,
            UNIQUE(user_id, parent_asin, timestamp)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_items (
            parent_asin TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            source_categories_json TEXT NOT NULL,
            title_clean TEXT NOT NULL,
            main_category TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            categories_path TEXT NOT NULL,
            description_text TEXT NOT NULL,
            features_text TEXT NOT NULL,
            item_text TEXT NOT NULL,
            average_rating REAL,
            rating_number INTEGER,
            store TEXT NOT NULL
        )
        """
    )
    connection.commit()


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ingest_items(
    connection: sqlite3.Connection,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    raw_seen = 0
    category_conflict_count = 0
    outputs = manifest.get("outputs") or []
    for output in outputs:
        category = output["category"]
        metadata_path = resolve_dataset_path(
            manifest_path,
            output.get("metadata_path"),
            category,
            "metadata.base.jsonl",
        )
        with metadata_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                raw_seen += 1
                record = json.loads(payload)
                parent_asin = clean_scalar_text(record.get("parent_asin"))
                if not parent_asin:
                    continue
                categories = normalize_categories(record.get("categories"))
                title_clean = clean_scalar_text(record.get("title"))
                main_category = clean_scalar_text(record.get("main_category"))
                description_text = flatten_text_list(record.get("description"))
                features_text = flatten_text_list(record.get("features"))
                item_text = build_item_text(record)
                store = clean_scalar_text(record.get("store"))
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO raw_items (
                        parent_asin,
                        category,
                        source_categories_json,
                        title_clean,
                        main_category,
                        categories_json,
                        categories_path,
                        description_text,
                        features_text,
                        item_text,
                        average_rating,
                        rating_number,
                        store
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        parent_asin,
                        category,
                        json.dumps([category], ensure_ascii=False),
                        title_clean,
                        main_category,
                        json.dumps(categories, ensure_ascii=False),
                        " > ".join(categories),
                        description_text,
                        features_text,
                        item_text,
                        record.get("average_rating"),
                        record.get("rating_number"),
                        store,
                    ),
                ).rowcount
                if inserted:
                    continue

                existing = connection.execute(
                    """
                    SELECT category,
                           source_categories_json,
                           title_clean,
                           main_category,
                           description_text,
                           features_text,
                           item_text,
                           average_rating,
                           rating_number,
                           store
                    FROM raw_items
                    WHERE parent_asin = ?
                    """,
                    (parent_asin,),
                ).fetchone()
                source_categories = json.loads(existing["source_categories_json"])
                if category not in source_categories:
                    source_categories.append(category)
                if existing["category"] != category:
                    category_conflict_count += 1
                connection.execute(
                    """
                    UPDATE raw_items
                    SET source_categories_json = ?,
                        title_clean = CASE WHEN title_clean = '' THEN ? ELSE title_clean END,
                        main_category = CASE WHEN main_category = '' THEN ? ELSE main_category END,
                        description_text = CASE WHEN description_text = '' THEN ? ELSE description_text END,
                        features_text = CASE WHEN features_text = '' THEN ? ELSE features_text END,
                        item_text = CASE WHEN item_text = '' THEN ? ELSE item_text END,
                        average_rating = COALESCE(average_rating, ?),
                        rating_number = COALESCE(rating_number, ?),
                        store = CASE WHEN store = '' THEN ? ELSE store END
                    WHERE parent_asin = ?
                    """,
                    (
                        json.dumps(sorted(source_categories), ensure_ascii=False),
                        title_clean,
                        main_category,
                        description_text,
                        features_text,
                        item_text,
                        record.get("average_rating"),
                        record.get("rating_number"),
                        store,
                        parent_asin,
                    ),
                )
    connection.commit()
    return {
        "raw_items_seen": raw_seen,
        "canonical_items_written": connection.execute(
            "SELECT COUNT(*) FROM raw_items"
        ).fetchone()[0],
        "item_category_conflicts": category_conflict_count,
    }


def ingest_interactions(
    connection: sqlite3.Connection,
    manifest_path: Path,
    manifest: dict[str, Any],
    min_timestamp: int,
    max_reviews_per_category: int,
) -> dict[str, Any]:
    raw_seen = 0
    skipped_missing_identity = 0
    skipped_timestamp_filter = 0
    outputs = manifest.get("outputs") or []
    for output in outputs:
        category = output["category"]
        reviews_path = resolve_dataset_path(
            manifest_path,
            output.get("reviews_path"),
            category,
            "reviews.base.jsonl",
        )
        kept_for_category = 0
        with reviews_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                raw_seen += 1
                record = json.loads(payload)
                user_id = clean_scalar_text(record.get("user_id"))
                parent_asin = clean_scalar_text(record.get("parent_asin"))
                timestamp = record.get("timestamp")
                if not user_id or not parent_asin or timestamp is None:
                    skipped_missing_identity += 1
                    continue
                timestamp = int(timestamp)
                if min_timestamp and timestamp < min_timestamp:
                    skipped_timestamp_filter += 1
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO raw_interactions (
                        user_id,
                        parent_asin,
                        category,
                        rating,
                        timestamp,
                        verified_purchase,
                        helpful_vote
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        parent_asin,
                        category,
                        record.get("rating"),
                        timestamp,
                        1 if bool(record.get("verified_purchase", False)) else 0,
                        int(record.get("helpful_vote", 0) or 0),
                    ),
                )
                kept_for_category += 1
                if max_reviews_per_category and kept_for_category >= max_reviews_per_category:
                    break
    connection.commit()
    exact_count = connection.execute("SELECT COUNT(*) FROM raw_interactions").fetchone()[0]
    return {
        "raw_reviews_seen": raw_seen,
        "exact_dedup_rows": exact_count,
        "exact_duplicates_skipped": max(
            0,
            raw_seen - skipped_missing_identity - skipped_timestamp_filter - exact_count,
        ),
        "skipped_missing_identity": skipped_missing_identity,
        "skipped_timestamp_filter": skipped_timestamp_filter,
    }


def build_latest_interactions(connection: sqlite3.Connection) -> int:
    connection.execute("DROP TABLE IF EXISTS latest_interactions")
    connection.execute(
        """
        CREATE TABLE latest_interactions AS
        SELECT r.user_id,
               r.parent_asin,
               r.category,
               r.rating,
               r.timestamp,
               r.verified_purchase,
               r.helpful_vote
        FROM raw_interactions r
        JOIN (
            SELECT user_id, parent_asin, MAX(timestamp) AS max_timestamp
            FROM raw_interactions
            GROUP BY user_id, parent_asin
        ) latest
          ON latest.user_id = r.user_id
         AND latest.parent_asin = r.parent_asin
         AND latest.max_timestamp = r.timestamp
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_latest_user ON latest_interactions(user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_latest_item ON latest_interactions(parent_asin)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_latest_ts ON latest_interactions(timestamp)"
    )
    connection.commit()
    return connection.execute("SELECT COUNT(*) FROM latest_interactions").fetchone()[0]


def build_filtered_interactions(
    connection: sqlite3.Connection,
    min_user_interactions: int,
    min_item_interactions: int,
) -> dict[str, Any]:
    connection.execute("DROP TABLE IF EXISTS filtered_interactions")
    connection.execute(
        """
        CREATE TABLE filtered_interactions AS
        SELECT user_id,
               parent_asin,
               category,
               rating,
               timestamp,
               verified_purchase,
               helpful_vote
        FROM latest_interactions
        """
    )

    iterations = 0
    total_removed = 0
    while True:
        connection.execute("DROP TABLE IF EXISTS low_users")
        connection.execute("DROP TABLE IF EXISTS low_items")
        connection.execute(
            """
            CREATE TEMP TABLE low_users AS
            SELECT user_id
            FROM filtered_interactions
            GROUP BY user_id
            HAVING COUNT(*) < ?
            """,
            (min_user_interactions,),
        )
        connection.execute(
            """
            CREATE TEMP TABLE low_items AS
            SELECT parent_asin
            FROM filtered_interactions
            GROUP BY parent_asin
            HAVING COUNT(*) < ?
            """,
            (min_item_interactions,),
        )
        low_user_count = connection.execute("SELECT COUNT(*) FROM low_users").fetchone()[0]
        low_item_count = connection.execute("SELECT COUNT(*) FROM low_items").fetchone()[0]
        if low_user_count == 0 and low_item_count == 0:
            connection.execute("DROP TABLE low_users")
            connection.execute("DROP TABLE low_items")
            break
        before = connection.execute("SELECT COUNT(*) FROM filtered_interactions").fetchone()[0]
        connection.execute(
            """
            DELETE FROM filtered_interactions
            WHERE user_id IN (SELECT user_id FROM low_users)
               OR parent_asin IN (SELECT parent_asin FROM low_items)
            """
        )
        after = connection.execute("SELECT COUNT(*) FROM filtered_interactions").fetchone()[0]
        total_removed += before - after
        iterations += 1
        connection.execute("DROP TABLE low_users")
        connection.execute("DROP TABLE low_items")
        connection.commit()

    connection.execute("DROP TABLE IF EXISTS stable_user_counts")
    connection.execute("DROP TABLE IF EXISTS stable_item_counts")
    connection.execute(
        """
        CREATE TABLE stable_user_counts AS
        SELECT user_id, COUNT(*) AS interaction_count
        FROM filtered_interactions
        GROUP BY user_id
        """
    )
    connection.execute(
        """
        CREATE TABLE stable_item_counts AS
        SELECT parent_asin, COUNT(*) AS interaction_count
        FROM filtered_interactions
        GROUP BY parent_asin
        """
    )
    connection.execute("DROP TABLE IF EXISTS ranked_interactions")
    connection.execute(
        """
        CREATE TABLE ranked_interactions AS
        SELECT ROW_NUMBER() OVER (ORDER BY f.timestamp, f.user_id, f.parent_asin) AS row_num,
               f.user_id,
               f.parent_asin,
               f.category,
               f.rating,
               f.timestamp,
               f.verified_purchase,
               f.helpful_vote,
               u.interaction_count AS user_interaction_count,
               i.interaction_count AS item_interaction_count
        FROM filtered_interactions f
        JOIN stable_user_counts u ON u.user_id = f.user_id
        JOIN stable_item_counts i ON i.parent_asin = f.parent_asin
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranked_row_num ON ranked_interactions(row_num)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranked_user ON ranked_interactions(user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranked_item ON ranked_interactions(parent_asin)"
    )
    connection.commit()

    filtered_rows = connection.execute("SELECT COUNT(*) FROM filtered_interactions").fetchone()[0]
    min_user_count = connection.execute(
        "SELECT COALESCE(MIN(interaction_count), 0) FROM stable_user_counts"
    ).fetchone()[0]
    min_item_count = connection.execute(
        "SELECT COALESCE(MIN(interaction_count), 0) FROM stable_item_counts"
    ).fetchone()[0]
    return {
        "filtered_rows": filtered_rows,
        "frequency_filter_removed": total_removed,
        "kcore_iterations": iterations,
        "final_min_user_interaction_count": int(min_user_count or 0),
        "final_min_item_interaction_count": int(min_item_count or 0),
    }


def choose_split_counts(
    total_rows: int,
    valid_ratio: float,
    test_ratio: float,
    small_data_all_train_threshold: int,
) -> tuple[int, int, int]:
    if total_rows <= 2:
        return total_rows, 0, 0
    if small_data_all_train_threshold and total_rows <= small_data_all_train_threshold:
        return total_rows, 0, 0
    valid_count = max(1, int(total_rows * valid_ratio))
    test_count = max(1, int(total_rows * test_ratio))
    train_count = total_rows - valid_count - test_count
    if train_count <= 0:
        train_count = max(1, total_rows - 2)
        valid_count = 1 if total_rows >= 2 else 0
        test_count = total_rows - train_count - valid_count
    return train_count, valid_count, test_count


def fetch_ranked_row(connection: sqlite3.Connection, row_num: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT row_num, timestamp, user_id, parent_asin
        FROM ranked_interactions
        WHERE row_num = ?
        """,
        (row_num,),
    ).fetchone()
    if row is None:
        return None
    return {
        "row_num": int(row["row_num"]),
        "timestamp": int(row["timestamp"]),
        "user_id": row["user_id"],
        "parent_asin": row["parent_asin"],
    }


def determine_split_plan(
    connection: sqlite3.Connection,
    valid_ratio: float,
    test_ratio: float,
    small_data_all_train_threshold: int,
) -> dict[str, Any]:
    total_rows = connection.execute("SELECT COUNT(*) FROM ranked_interactions").fetchone()[0]
    if total_rows == 0:
        raise ValueError("No rows left after filtering; cannot build recall tables.")
    train_count, valid_count, test_count = choose_split_counts(
        total_rows,
        valid_ratio,
        test_ratio,
        small_data_all_train_threshold,
    )
    train_end_row = train_count
    valid_end_row = train_count + valid_count
    return {
        "total_rows": total_rows,
        "train_count": train_count,
        "valid_count": valid_count,
        "test_count": test_count,
        "train_end_row": train_end_row,
        "valid_end_row": valid_end_row,
        "train_boundary": fetch_ranked_row(connection, train_end_row),
        "valid_boundary": fetch_ranked_row(connection, valid_end_row) if valid_count else None,
        "test_boundary": fetch_ranked_row(connection, total_rows),
        "order_by": ["timestamp", "user_id", "parent_asin"],
        "small_data_all_train_threshold": small_data_all_train_threshold,
        "small_data_all_train_applied": bool(
            small_data_all_train_threshold and total_rows <= small_data_all_train_threshold
        ),
    }


def assign_split(row_num: int, split_plan: dict[str, Any]) -> str:
    if row_num <= split_plan["train_end_row"]:
        return "train"
    if row_num <= split_plan["valid_end_row"]:
        return "valid"
    return "test"


def label_binary(rating: float | None, threshold: float) -> int:
    if rating is None:
        return 0
    return 1 if float(rating) >= threshold else 0


def label_strength(rating: float | None, verified_purchase: bool, helpful_vote: int) -> float:
    rating_score = 0.0 if rating is None else round(float(rating) / 5.0, 4)
    verified_bonus = 0.2 if verified_purchase else 0.0
    helpful_bonus = min(helpful_vote, 10) / 50.0
    return round(rating_score + verified_bonus + helpful_bonus, 4)


def build_interaction_record(
    row: sqlite3.Row,
    positive_rating_threshold: float,
    split_plan: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "user_id": row["user_id"],
        "parent_asin": row["parent_asin"],
        "category": row["category"],
        "rating": row["rating"],
        "timestamp": int(row["timestamp"]),
        "verified_purchase": bool(row["verified_purchase"]),
        "helpful_vote": int(row["helpful_vote"]),
        "user_interaction_count": int(row["user_interaction_count"]),
        "item_interaction_count": int(row["item_interaction_count"]),
        "row_num": int(row["row_num"]),
    }
    record["label_binary"] = label_binary(record["rating"], positive_rating_threshold)
    record["label_strong"] = int(record["label_binary"] and record["verified_purchase"])
    record["label_strength"] = label_strength(
        record["rating"],
        record["verified_purchase"],
        record["helpful_vote"],
    )
    record["dedup_strategy"] = "exact_then_user_item_keep_last"
    record["split"] = assign_split(record["row_num"], split_plan)
    return record


def write_canonical_interactions(
    connection: sqlite3.Connection,
    output_dir: Path,
    positive_rating_threshold: float,
    split_plan: dict[str, Any],
) -> dict[str, Any]:
    canonical_path = output_dir / "canonical_interactions.jsonl"
    train_path = output_dir / "canonical_interactions.train.jsonl"
    valid_path = output_dir / "canonical_interactions.valid.jsonl"
    test_path = output_dir / "canonical_interactions.test.jsonl"

    split_files = {
        "train": train_path.open("w", encoding="utf-8"),
        "valid": valid_path.open("w", encoding="utf-8"),
        "test": test_path.open("w", encoding="utf-8"),
    }
    split_counts = {"train": 0, "valid": 0, "test": 0}

    with canonical_path.open("w", encoding="utf-8") as canonical_file:
        for row in connection.execute(
            """
            SELECT row_num,
                   user_id,
                   parent_asin,
                   category,
                   rating,
                   timestamp,
                   verified_purchase,
                   helpful_vote,
                   user_interaction_count,
                   item_interaction_count
            FROM ranked_interactions
            ORDER BY row_num
            """
        ):
            record = build_interaction_record(row, positive_rating_threshold, split_plan)
            line = compact_json(record) + "\n"
            canonical_file.write(line)
            split_files[record["split"]].write(line)
            split_counts[record["split"]] += 1

    for handle in split_files.values():
        handle.close()

    return {
        "canonical_interactions_path": str(canonical_path),
        "split_paths": {
            "train": str(train_path),
            "valid": str(valid_path),
            "test": str(test_path),
        },
        "split_counts": split_counts,
    }


def write_canonical_items(connection: sqlite3.Connection, output_dir: Path) -> dict[str, Any]:
    canonical_path = output_dir / "canonical_items.jsonl"
    rows_written = 0
    distinct_filtered_items = connection.execute(
        "SELECT COUNT(DISTINCT parent_asin) FROM filtered_interactions"
    ).fetchone()[0]

    with canonical_path.open("w", encoding="utf-8") as sink:
        for row in connection.execute(
            """
            SELECT i.parent_asin,
                   i.category,
                   i.source_categories_json,
                   i.title_clean,
                   i.main_category,
                   i.categories_json,
                   i.categories_path,
                   i.description_text,
                   i.features_text,
                   i.item_text,
                   i.average_rating,
                   i.rating_number,
                   i.store
            FROM raw_items i
            JOIN (
                SELECT DISTINCT parent_asin
                FROM filtered_interactions
            ) filtered_items
              ON filtered_items.parent_asin = i.parent_asin
            ORDER BY i.parent_asin
            """
        ):
            record = {
                "parent_asin": row["parent_asin"],
                "category": row["category"],
                "source_categories": json.loads(row["source_categories_json"]),
                "title_clean": row["title_clean"],
                "main_category": row["main_category"],
                "categories_flat": json.loads(row["categories_json"]),
                "categories_path": row["categories_path"],
                "description_text": row["description_text"],
                "features_text": row["features_text"],
                "item_text": row["item_text"],
                "average_rating": row["average_rating"],
                "rating_number": row["rating_number"],
                "store": row["store"],
            }
            sink.write(compact_json(record) + "\n")
            rows_written += 1

    return {
        "canonical_items_path": str(canonical_path),
        "canonical_items_written": rows_written,
        "missing_item_metadata": distinct_filtered_items - rows_written,
    }


def empty_sequence_state(sequence_max_len: int) -> dict[str, Any]:
    return {
        "sequence_len": 0,
        "positive_sequence_len": 0,
        "strong_positive_sequence_len": 0,
        "recent_item_sequence": deque(maxlen=sequence_max_len),
        "recent_timestamp_sequence": deque(maxlen=sequence_max_len),
        "recent_positive_item_sequence": deque(maxlen=sequence_max_len),
        "recent_positive_timestamp_sequence": deque(maxlen=sequence_max_len),
        "recent_strong_positive_item_sequence": deque(maxlen=sequence_max_len),
        "recent_strong_positive_timestamp_sequence": deque(maxlen=sequence_max_len),
    }


def update_sequence_state(
    state: dict[str, Any],
    parent_asin: str,
    timestamp: int,
    is_positive: bool,
    is_strong_positive: bool,
) -> None:
    state["sequence_len"] += 1
    state["recent_item_sequence"].append(parent_asin)
    state["recent_timestamp_sequence"].append(timestamp)
    if is_positive:
        state["positive_sequence_len"] += 1
        state["recent_positive_item_sequence"].append(parent_asin)
        state["recent_positive_timestamp_sequence"].append(timestamp)
    if is_strong_positive:
        state["strong_positive_sequence_len"] += 1
        state["recent_strong_positive_item_sequence"].append(parent_asin)
        state["recent_strong_positive_timestamp_sequence"].append(timestamp)


def serialize_sequence(user_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "sequence_len": state["sequence_len"],
        "positive_sequence_len": state["positive_sequence_len"],
        "strong_positive_sequence_len": state["strong_positive_sequence_len"],
        "recent_item_sequence": list(state["recent_item_sequence"]),
        "recent_timestamp_sequence": list(state["recent_timestamp_sequence"]),
        "recent_positive_item_sequence": list(state["recent_positive_item_sequence"]),
        "recent_positive_timestamp_sequence": list(state["recent_positive_timestamp_sequence"]),
        "recent_strong_positive_item_sequence": list(state["recent_strong_positive_item_sequence"]),
        "recent_strong_positive_timestamp_sequence": list(state["recent_strong_positive_timestamp_sequence"]),
    }


def write_user_sequences(
    connection: sqlite3.Connection,
    output_dir: Path,
    sequence_max_len: int,
    positive_rating_threshold: float,
    split_plan: dict[str, Any],
) -> dict[str, Any]:
    all_path = output_dir / "user_sequences.jsonl"
    train_path = output_dir / "user_sequences.train.jsonl"
    user_sequence_count = 0
    train_user_sequence_count = 0
    longest_sequence = 0
    longest_train_sequence = 0
    current_user: str | None = None
    all_state = empty_sequence_state(sequence_max_len)
    train_state = empty_sequence_state(sequence_max_len)

    def flush_user(all_sink: Any, train_sink: Any) -> tuple[int, int, int, int]:
        nonlocal current_user, all_state, train_state
        if current_user is None:
            return 0, 0, 0, 0
        all_written = 0
        train_written = 0
        all_len = 0
        train_len = 0
        if all_state["sequence_len"] > 0:
            all_sink.write(compact_json(serialize_sequence(current_user, all_state)) + "\n")
            all_written = 1
            all_len = int(all_state["sequence_len"])
        if train_state["sequence_len"] > 0:
            train_sink.write(compact_json(serialize_sequence(current_user, train_state)) + "\n")
            train_written = 1
            train_len = int(train_state["sequence_len"])
        current_user = None
        all_state = empty_sequence_state(sequence_max_len)
        train_state = empty_sequence_state(sequence_max_len)
        return all_written, train_written, all_len, train_len

    with all_path.open("w", encoding="utf-8") as all_sink, train_path.open(
        "w", encoding="utf-8"
    ) as train_sink:
        for row in connection.execute(
            """
            SELECT row_num,
                   user_id,
                   parent_asin,
                   rating,
                   timestamp,
                   verified_purchase,
                   helpful_vote
            FROM ranked_interactions
            ORDER BY user_id, row_num
            """
        ):
            if current_user is not None and row["user_id"] != current_user:
                all_written, train_written, all_len, train_len = flush_user(all_sink, train_sink)
                user_sequence_count += all_written
                train_user_sequence_count += train_written
                longest_sequence = max(longest_sequence, all_len)
                longest_train_sequence = max(longest_train_sequence, train_len)
            if current_user is None:
                current_user = row["user_id"]

            timestamp = int(row["timestamp"])
            is_positive = bool(label_binary(row["rating"], positive_rating_threshold))
            is_strong_positive = bool(is_positive and bool(row["verified_purchase"]))
            update_sequence_state(
                all_state,
                row["parent_asin"],
                timestamp,
                is_positive,
                is_strong_positive,
            )
            if assign_split(int(row["row_num"]), split_plan) == "train":
                update_sequence_state(
                    train_state,
                    row["parent_asin"],
                    timestamp,
                    is_positive,
                    is_strong_positive,
                )

        all_written, train_written, all_len, train_len = flush_user(all_sink, train_sink)
        user_sequence_count += all_written
        train_user_sequence_count += train_written
        longest_sequence = max(longest_sequence, all_len)
        longest_train_sequence = max(longest_train_sequence, train_len)

    return {
        "user_sequences_path": str(all_path),
        "train_user_sequences_path": str(train_path),
        "user_sequence_count": user_sequence_count,
        "train_user_sequence_count": train_user_sequence_count,
        "longest_sequence": longest_sequence,
        "longest_train_sequence": longest_train_sequence,
    }


def summarize_split(
    connection: sqlite3.Connection,
    split_name: str,
    split_plan: dict[str, Any],
) -> dict[str, Any]:
    if split_name == "train":
        condition = "row_num <= ?"
        params = (split_plan["train_end_row"],)
    elif split_name == "valid":
        condition = "row_num > ? AND row_num <= ?"
        params = (split_plan["train_end_row"], split_plan["valid_end_row"])
    else:
        condition = "row_num > ?"
        params = (split_plan["valid_end_row"],)
    interaction_count = connection.execute(
        f"SELECT COUNT(*) FROM ranked_interactions WHERE {condition}",
        params,
    ).fetchone()[0]
    distinct_user_count = connection.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM ranked_interactions WHERE {condition}",
        params,
    ).fetchone()[0]
    distinct_item_count = connection.execute(
        f"SELECT COUNT(DISTINCT parent_asin) FROM ranked_interactions WHERE {condition}",
        params,
    ).fetchone()[0]
    return {
        "interaction_count": interaction_count,
        "distinct_user_count": distinct_user_count,
        "distinct_item_count": distinct_item_count,
    }


def summarize_train_readiness(
    connection: sqlite3.Connection,
    split_plan: dict[str, Any],
    positive_rating_threshold: float,
) -> dict[str, Any]:
    train_end_row = split_plan["train_end_row"]
    positive_train_interaction_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM ranked_interactions
        WHERE row_num <= ? AND rating >= ?
        """,
        (train_end_row, positive_rating_threshold),
    ).fetchone()[0]
    strong_positive_train_interaction_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM ranked_interactions
        WHERE row_num <= ? AND rating >= ? AND verified_purchase = 1
        """,
        (train_end_row, positive_rating_threshold),
    ).fetchone()[0]
    users_with_ge2_positive_train_items = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT user_id
            FROM ranked_interactions
            WHERE row_num <= ? AND rating >= ?
            GROUP BY user_id
            HAVING COUNT(DISTINCT parent_asin) >= 2
        )
        """,
        (train_end_row, positive_rating_threshold),
    ).fetchone()[0]
    users_with_ge2_strong_positive_train_items = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT user_id
            FROM ranked_interactions
            WHERE row_num <= ? AND rating >= ? AND verified_purchase = 1
            GROUP BY user_id
            HAVING COUNT(DISTINCT parent_asin) >= 2
        )
        """,
        (train_end_row, positive_rating_threshold),
    ).fetchone()[0]
    return {
        "positive_train_interaction_count": positive_train_interaction_count,
        "strong_positive_train_interaction_count": strong_positive_train_interaction_count,
        "users_with_ge2_positive_train_items": users_with_ge2_positive_train_items,
        "users_with_ge2_strong_positive_train_items": users_with_ge2_strong_positive_train_items,
    }


def write_manifest(output_dir: Path, payload: dict[str, Any]) -> Path:
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def write_stats(output_dir: Path, payload: dict[str, Any]) -> Path:
    stats_path = output_dir / "stats.json"
    stats_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats_path

def build_recall_clean_tables(
    input_manifest: str | Path = DEFAULT_INPUT_MANIFEST,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    positive_rating_threshold: float = DEFAULT_POSITIVE_RATING_THRESHOLD,
    min_user_interactions: int = DEFAULT_MIN_USER_INTERACTIONS,
    min_item_interactions: int = DEFAULT_MIN_ITEM_INTERACTIONS,
    valid_ratio: float = DEFAULT_VALID_RATIO,
    test_ratio: float = DEFAULT_TEST_RATIO,
    min_timestamp: int = 0,
    max_reviews_per_category: int = 0,
    sequence_max_len: int = DEFAULT_SEQUENCE_MAX_LEN,
    small_data_all_train_threshold: int = 0,
    overwrite: bool = False,
) -> dict[str, Any]:
    ensure_ratio_args(valid_ratio, test_ratio)
    ensure_positive_args(
        min_user_interactions,
        min_item_interactions,
        sequence_max_len,
        small_data_all_train_threshold,
    )

    manifest_path = Path(input_manifest)
    manifest = load_manifest(manifest_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    sqlite_path = output_path / "recall_clean.sqlite"
    if sqlite_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing database: {sqlite_path}. Use --overwrite to replace it."
            )
        sqlite_path.unlink()

    connection = sqlite3.connect(sqlite_path)
    connection.row_factory = sqlite3.Row
    try:
        setup_database(connection)
        item_stats = ingest_items(connection, manifest_path, manifest)
        interaction_stats = ingest_interactions(
            connection,
            manifest_path,
            manifest,
            min_timestamp,
            max_reviews_per_category,
        )
        latest_count = build_latest_interactions(connection)
        filter_stats = build_filtered_interactions(
            connection,
            min_user_interactions,
            min_item_interactions,
        )
        split_plan = determine_split_plan(
            connection,
            valid_ratio,
            test_ratio,
            small_data_all_train_threshold,
        )
        interaction_outputs = write_canonical_interactions(
            connection,
            output_path,
            positive_rating_threshold,
            split_plan,
        )
        item_outputs = write_canonical_items(connection, output_path)
        sequence_outputs = write_user_sequences(
            connection,
            output_path,
            sequence_max_len,
            positive_rating_threshold,
            split_plan,
        )

        split_summary = {
            split_name: summarize_split(connection, split_name, split_plan)
            for split_name in ("train", "valid", "test")
        }
        split_summary["all"] = {
            "interaction_count": filter_stats["filtered_rows"],
            "distinct_user_count": connection.execute(
                "SELECT COUNT(DISTINCT user_id) FROM ranked_interactions"
            ).fetchone()[0],
            "distinct_item_count": connection.execute(
                "SELECT COUNT(DISTINCT parent_asin) FROM ranked_interactions"
            ).fetchone()[0],
        }

        train_readiness = summarize_train_readiness(
            connection,
            split_plan,
            positive_rating_threshold,
        )

        manifest_payload = {
            "dataset": manifest.get("dataset"),
            "schema_version": "1.1",
            "generated_at": datetime.now(UTC).isoformat(),
            "source_manifest": str(manifest_path),
            "output_dir": str(output_path),
            "canonical_interactions_path": interaction_outputs["canonical_interactions_path"],
            "canonical_items_path": item_outputs["canonical_items_path"],
            "user_sequences_path": sequence_outputs["user_sequences_path"],
            "train_user_sequences_path": sequence_outputs["train_user_sequences_path"],
            "split_paths": interaction_outputs["split_paths"],
            "sqlite_path": str(sqlite_path),
        }
        stats_payload = {
            "dataset": manifest.get("dataset"),
            "schema_version": "1.1",
            "generated_at": datetime.now(UTC).isoformat(),
            "config": {
                "positive_rating_threshold": positive_rating_threshold,
                "min_user_interactions": min_user_interactions,
                "min_item_interactions": min_item_interactions,
                "valid_ratio": valid_ratio,
                "test_ratio": test_ratio,
                "min_timestamp": min_timestamp,
                "max_reviews_per_category": max_reviews_per_category,
                "sequence_max_len": sequence_max_len,
                "small_data_all_train_threshold": small_data_all_train_threshold,
            },
            "ingest": {
                **item_stats,
                **interaction_stats,
                "latest_user_item_rows": latest_count,
                "user_item_keep_last_removed": interaction_stats["exact_dedup_rows"] - latest_count,
                **filter_stats,
            },
            "split_plan": split_plan,
            "split_summary": split_summary,
            "train_readiness": train_readiness,
            "outputs": {
                **interaction_outputs,
                **item_outputs,
                **sequence_outputs,
            },
        }

        manifest_output = write_manifest(output_path, manifest_payload)
        stats_output = write_stats(output_path, stats_payload)
        return {
            "canonical_interactions_path": interaction_outputs["canonical_interactions_path"],
            "canonical_items_path": item_outputs["canonical_items_path"],
            "user_sequences_path": sequence_outputs["user_sequences_path"],
            "train_user_sequences_path": sequence_outputs["train_user_sequences_path"],
            "manifest_path": str(manifest_output),
            "stats_path": str(stats_output),
            "manifest": manifest_payload,
            "stats": stats_payload,
        }
    finally:
        connection.close()
