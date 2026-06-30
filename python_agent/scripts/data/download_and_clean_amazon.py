from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.request import urlopen


DATASET_NAME = "McAuley-Lab/Amazon-Reviews-2023"
DATASET_BASE_URL = f"https://huggingface.co/datasets/{DATASET_NAME}/resolve/main"
DEFAULT_CATEGORIES = ["Electronics", "Office_Products"]
SCHEMA_VERSION = "1.1"
TEXT_BUCKETS = [(0, 0), (1, 19), (20, 99), (100, 499), (500, None)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream Amazon Reviews 2023 and write normalized base datasets."
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=DEFAULT_CATEGORIES,
        help="Amazon category configs, e.g. Electronics Office_Products",
    )
    parser.add_argument(
        "--output-dir",
        default="./data/processed/amazon_2023_base",
        help="Directory used to store normalized base outputs.",
    )
    parser.add_argument(
        "--max-reviews-per-category",
        type=int,
        default=0,
        help="Optional cap on normalized reviews per category. 0 means no cap.",
    )
    parser.add_argument(
        "--metadata-scope",
        choices=("observed-items", "all"),
        default="observed-items",
        help="Whether to keep metadata only for observed parent_asin values or for the full category.",
    )
    return parser.parse_args()


def review_data_url(category: str) -> str:
    return f"{DATASET_BASE_URL}/raw/review_categories/{category}.jsonl"


def metadata_data_url(category: str) -> str:
    return f"{DATASET_BASE_URL}/raw/meta_categories/meta_{category}.jsonl"


def compact_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False)


def iter_remote_jsonl(url: str) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    buffered_parts: list[str] = []

    with urlopen(url) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line and not buffered_parts:
                continue

            buffered_parts.append(line)
            candidate = " ".join(part for part in buffered_parts if part)
            if not candidate:
                buffered_parts.clear()
                continue

            try:
                record, end = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue

            if candidate[end:].strip():
                raise ValueError(f"Unexpected trailing content while reading {url}")
            yield record
            buffered_parts.clear()

    if buffered_parts:
        candidate = " ".join(part for part in buffered_parts if part)
        try:
            record, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            return
        if candidate[end:].strip():
            return
        yield record


def normalized_text(record: dict[str, Any]) -> str:
    return (record.get("text") or "").strip()


def normalized_text_length(record: dict[str, Any]) -> int:
    return len(normalized_text(record))


def bucket_text_length(text_len: int) -> str:
    for lower, upper in TEXT_BUCKETS:
        if upper is None and text_len >= lower:
            return f"{lower}+"
        if upper is not None and lower <= text_len <= upper:
            return f"{lower}-{upper}"
    return "unknown"


def normalize_review_record(category: str, record: dict[str, Any]) -> dict[str, Any] | None:
    user_id = record.get("user_id")
    parent_asin = record.get("parent_asin")
    if not user_id or not parent_asin:
        return None

    text = normalized_text(record)
    return {
        "dataset": DATASET_NAME,
        "category": category,
        "user_id": user_id,
        "parent_asin": parent_asin,
        "asin": record.get("asin"),
        "rating": record.get("rating"),
        "title": record.get("title"),
        "text": text,
        "text_len": len(text),
        "timestamp": record.get("timestamp"),
        "verified_purchase": bool(record.get("verified_purchase", False)),
        "helpful_vote": record.get("helpful_vote", 0),
    }


def normalize_metadata_record(category: str, record: dict[str, Any]) -> dict[str, Any] | None:
    parent_asin = record.get("parent_asin")
    if not parent_asin:
        return None

    return {
        "dataset": DATASET_NAME,
        "category": category,
        "parent_asin": parent_asin,
        "title": record.get("title"),
        "main_category": record.get("main_category"),
        "categories": record.get("categories") or [],
        "description": record.get("description") or [],
        "features": record.get("features") or [],
        "images": record.get("images") or [],
        "price": record.get("price"),
        "average_rating": record.get("average_rating"),
        "rating_number": record.get("rating_number"),
        "store": record.get("store"),
        "details": record.get("details"),
        "bought_together": record.get("bought_together"),
    }


def write_reviews_base_for_category(
    category: str,
    output_dir: Path,
    max_reviews_per_category: int,
) -> dict[str, Any]:
    category_dir = output_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)

    reviews_path = category_dir / "reviews.base.jsonl"
    raw_reviews_seen = 0
    normalized_reviews_kept = 0
    skipped_missing_identity = 0
    unique_users: set[str] = set()
    observed_parent_asins: set[str] = set()
    verified_counts: Counter[str] = Counter()
    text_length_buckets: Counter[str] = Counter()

    with reviews_path.open("w", encoding="utf-8") as sink:
        for record in iter_remote_jsonl(review_data_url(category)):
            raw_reviews_seen += 1
            normalized = normalize_review_record(category, record)
            if normalized is None:
                skipped_missing_identity += 1
                continue

            sink.write(compact_json(normalized) + "\n")
            normalized_reviews_kept += 1
            unique_users.add(normalized["user_id"])
            observed_parent_asins.add(normalized["parent_asin"])
            verified_key = "verified" if normalized["verified_purchase"] else "unverified"
            verified_counts[verified_key] += 1
            text_length_buckets[bucket_text_length(normalized["text_len"])] += 1

            if max_reviews_per_category and normalized_reviews_kept >= max_reviews_per_category:
                break

    return {
        "category": category,
        "reviews_path": str(reviews_path),
        "raw_reviews_seen": raw_reviews_seen,
        "normalized_reviews_kept": normalized_reviews_kept,
        "skipped_missing_identity": skipped_missing_identity,
        "distinct_user_count": len(unique_users),
        "distinct_parent_asin_count": len(observed_parent_asins),
        "verified_counts": dict(verified_counts),
        "text_length_buckets": dict(text_length_buckets),
        "observed_parent_asins": observed_parent_asins,
    }


def write_metadata_base_for_category(
    category: str,
    output_dir: Path,
    metadata_scope: str,
    observed_parent_asins: set[str],
) -> dict[str, Any]:
    category_dir = output_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = category_dir / "metadata.base.jsonl"
    raw_metadata_seen = 0
    normalized_metadata_kept = 0
    skipped_missing_parent_asin = 0

    with metadata_path.open("w", encoding="utf-8") as sink:
        for record in iter_remote_jsonl(metadata_data_url(category)):
            raw_metadata_seen += 1
            normalized = normalize_metadata_record(category, record)
            if normalized is None:
                skipped_missing_parent_asin += 1
                continue
            if metadata_scope == "observed-items" and normalized["parent_asin"] not in observed_parent_asins:
                continue

            sink.write(compact_json(normalized) + "\n")
            normalized_metadata_kept += 1

    return {
        "category": category,
        "metadata_path": str(metadata_path),
        "raw_metadata_seen": raw_metadata_seen,
        "normalized_metadata_kept": normalized_metadata_kept,
        "skipped_missing_parent_asin": skipped_missing_parent_asin,
        "metadata_scope": metadata_scope,
    }


def write_manifest(output_dir: Path, categories: list[str], summaries: list[dict[str, Any]]) -> Path:
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": DATASET_NAME,
                "schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "categories": categories,
                "outputs": [
                    {
                        "category": summary["category"],
                        "reviews_path": summary["reviews_path"],
                        "metadata_path": summary["metadata_path"],
                    }
                    for summary in summaries
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def write_stats(output_dir: Path, summaries: list[dict[str, Any]]) -> Path:
    stats_path = output_dir / "stats.json"

    total_verified = 0
    total_unverified = 0
    total_raw_reviews_seen = 0
    total_normalized_reviews_kept = 0
    total_raw_metadata_seen = 0
    total_normalized_metadata_kept = 0
    text_bucket_totals: Counter[str] = Counter()

    for summary in summaries:
        total_raw_reviews_seen += summary["raw_reviews_seen"]
        total_normalized_reviews_kept += summary["normalized_reviews_kept"]
        total_raw_metadata_seen += summary["raw_metadata_seen"]
        total_normalized_metadata_kept += summary["normalized_metadata_kept"]
        total_verified += summary["verified_counts"].get("verified", 0)
        total_unverified += summary["verified_counts"].get("unverified", 0)
        text_bucket_totals.update(summary["text_length_buckets"])

    stats_path.write_text(
        json.dumps(
            {
                "dataset": DATASET_NAME,
                "schema_version": SCHEMA_VERSION,
                "category_stats": summaries,
                "totals": {
                    "raw_reviews_seen": total_raw_reviews_seen,
                    "normalized_reviews_kept": total_normalized_reviews_kept,
                    "raw_metadata_seen": total_raw_metadata_seen,
                    "normalized_metadata_kept": total_normalized_metadata_kept,
                    "verified_counts": {
                        "verified": total_verified,
                        "unverified": total_unverified,
                    },
                    "text_length_buckets": dict(text_bucket_totals),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        )
    return stats_path


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []

    for category in args.categories:
        review_summary = write_reviews_base_for_category(
            category=category,
            output_dir=output_dir,
            max_reviews_per_category=args.max_reviews_per_category,
        )
        metadata_summary = write_metadata_base_for_category(
            category=category,
            output_dir=output_dir,
            metadata_scope=args.metadata_scope,
            observed_parent_asins=review_summary["observed_parent_asins"],
        )

        merged_summary = {
            "category": category,
            "raw_reviews_seen": review_summary["raw_reviews_seen"],
            "normalized_reviews_kept": review_summary["normalized_reviews_kept"],
            "skipped_missing_identity": review_summary["skipped_missing_identity"],
            "distinct_user_count": review_summary["distinct_user_count"],
            "distinct_parent_asin_count": review_summary["distinct_parent_asin_count"],
            "verified_counts": review_summary["verified_counts"],
            "text_length_buckets": review_summary["text_length_buckets"],
            "raw_metadata_seen": metadata_summary["raw_metadata_seen"],
            "normalized_metadata_kept": metadata_summary["normalized_metadata_kept"],
            "skipped_missing_parent_asin": metadata_summary["skipped_missing_parent_asin"],
            "metadata_scope": metadata_summary["metadata_scope"],
            "reviews_path": review_summary["reviews_path"],
            "metadata_path": metadata_summary["metadata_path"],
        }
        summaries.append(merged_summary)

        print(
            f"[{category}] reviews={merged_summary['normalized_reviews_kept']} "
            f"users={merged_summary['distinct_user_count']} "
            f"items={merged_summary['distinct_parent_asin_count']} "
            f"metadata={merged_summary['normalized_metadata_kept']}"
        )

    manifest_path = write_manifest(output_dir, args.categories, summaries)
    stats_path = write_stats(output_dir, summaries)
    print(f"Manifest written to: {manifest_path}")
    print(f"Stats written to: {stats_path}")


if __name__ == "__main__":
    main()
