from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_CLEAN_STATS = "./data/processed/amazon_2023_recall_clean/stats.json"
DEFAULT_VIEW_STATS = "./data/processed/amazon_2023_recall_views/stats.json"
DEFAULT_OUTPUT_PATH = "./dic/RECALL_DATA_PROFILE.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a markdown profile for recall clean tables and recall views."
    )
    parser.add_argument(
        "--clean-stats",
        default=DEFAULT_CLEAN_STATS,
        help="stats.json emitted by build_recall_clean_tables.py",
    )
    parser.add_argument(
        "--view-stats",
        default=DEFAULT_VIEW_STATS,
        help="stats.json emitted by build_recall_views.py",
    )
    parser.add_argument(
        "--output-path",
        default=DEFAULT_OUTPUT_PATH,
        help="Markdown report output path.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def render_split_rows(split_summary: dict[str, Any]) -> str:
    rows = ["| Split | Interactions | Distinct Users | Distinct Items |", "| --- | ---: | ---: | ---: |"]
    for split_name in ["all", "train", "valid", "test"]:
        stats = split_summary.get(split_name, {})
        rows.append(
            f"| {split_name} | {stats.get('interaction_count', 0)} | {stats.get('distinct_user_count', 0)} | {stats.get('distinct_item_count', 0)} |"
        )
    return "\n".join(rows)


def build_report(clean_stats: dict[str, Any], view_stats: dict[str, Any]) -> str:
    ingest = clean_stats.get("ingest", {})
    split_summary = clean_stats.get("split_summary", {})
    split_plan = clean_stats.get("split_plan", {})
    train_readiness = clean_stats.get("train_readiness", {})
    outputs = clean_stats.get("outputs", {})
    view_pop = view_stats.get("popular_recall", {})
    view_itemcf = view_stats.get("itemcf_recall", {})
    view_category = view_stats.get("category_recall", {})
    weak_itemcf = view_itemcf.get("weak", {})
    strong_itemcf = view_itemcf.get("strong", {})

    return f"""# Recall Data Profile

## 1. Summary

- Report generated at: {datetime.now(UTC).isoformat()}
- Canonical interactions: `{outputs.get('canonical_interactions_path', '')}`
- Canonical items: `{outputs.get('canonical_items_path', '')}`
- User sequences: `{outputs.get('user_sequences_path', '')}`
- Train user sequences: `{outputs.get('train_user_sequences_path', '')}`

## 2. Canonical table build stats

- Raw reviews seen: {ingest.get('raw_reviews_seen', 0)}
- Exact dedup rows kept: {ingest.get('exact_dedup_rows', 0)}
- Exact duplicates skipped: {ingest.get('exact_duplicates_skipped', 0)}
- User-item keep-last rows kept: {ingest.get('latest_user_item_rows', 0)}
- User-item keep-last removed: {ingest.get('user_item_keep_last_removed', 0)}
- Frequency filter rows kept: {ingest.get('filtered_rows', 0)}
- Frequency filter removed: {ingest.get('frequency_filter_removed', 0)}
- K-core iterations: {ingest.get('kcore_iterations', 0)}
- Final min user interactions: {ingest.get('final_min_user_interaction_count', 0)}
- Final min item interactions: {ingest.get('final_min_item_interaction_count', 0)}
- Canonical items written: {outputs.get('canonical_items_written', 0)}
- Missing item metadata after filtering: {outputs.get('missing_item_metadata', 0)}
- User sequences written: {outputs.get('user_sequence_count', 0)}
- Train user sequences written: {outputs.get('train_user_sequence_count', 0)}
- Longest user sequence: {outputs.get('longest_sequence', 0)}
- Longest train user sequence: {outputs.get('longest_train_sequence', 0)}

## 3. Train readiness

- Positive train interactions: {train_readiness.get('positive_train_interaction_count', 0)}
- Strong positive train interactions: {train_readiness.get('strong_positive_train_interaction_count', 0)}
- Users with >=2 positive train items: {train_readiness.get('users_with_ge2_positive_train_items', 0)}
- Users with >=2 strong positive train items: {train_readiness.get('users_with_ge2_strong_positive_train_items', 0)}

## 4. Split coverage

{render_split_rows(split_summary)}

### Split boundaries
- Train rows: {split_plan.get('train_count', 0)}
- Valid rows: {split_plan.get('valid_count', 0)}
- Test rows: {split_plan.get('test_count', 0)}
- Small-data all-train threshold: {split_plan.get('small_data_all_train_threshold', 0)}
- Small-data all-train applied: {split_plan.get('small_data_all_train_applied', False)}
- Ordering key: `{split_plan.get('order_by', [])}`
- Train boundary: `{split_plan.get('train_boundary', {})}`
- Valid boundary: `{split_plan.get('valid_boundary', {})}`
- Test boundary: `{split_plan.get('test_boundary', {})}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: {view_pop.get('rows_written', 0)}
- Positive train rows used: {view_pop.get('positive_rows_used', 0)}
- Recent threshold: {view_pop.get('recent_threshold', 0)}

### 5.2 ItemCF recall (weak positives)
- Rows written: {weak_itemcf.get('rows_written', 0)}
- Users used: {weak_itemcf.get('users_used', 0)}
- Unique items in graph: {weak_itemcf.get('unique_item_count', 0)}
- Unique item pairs: {weak_itemcf.get('unique_pair_count', 0)}

### 5.3 ItemCF recall (strong positives)
- Rows written: {strong_itemcf.get('rows_written', 0)}
- Users used: {strong_itemcf.get('users_used', 0)}
- Unique items in graph: {strong_itemcf.get('unique_item_count', 0)}
- Unique item pairs: {strong_itemcf.get('unique_pair_count', 0)}

### 5.4 Category and semantic recall
- Category rows written: {view_category.get('category_rows_written', 0)}
- Category bucket rows: {view_category.get('category_bucket_rows', 0)}
- Semantic rows written: {view_category.get('semantic_rows_written', 0)}

## 6. Output paths

- Popular recall: `{view_pop.get('output_path', '')}`
- Weak ItemCF recall: `{weak_itemcf.get('output_path', '')}`
- Strong ItemCF recall: `{strong_itemcf.get('output_path', '')}`
- Category recall items: `{view_category.get('category_items_path', '')}`
- Category top items: `{view_category.get('category_top_path', '')}`
- Semantic recall inputs: `{view_category.get('semantic_path', '')}`
"""


def main() -> None:
    args = parse_args()
    clean_stats_path = Path(args.clean_stats)
    view_stats_path = Path(args.view_stats)
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clean_stats = read_json(clean_stats_path)
    view_stats = read_json(view_stats_path)
    report = build_report(clean_stats, view_stats)
    output_path.write_text(report, encoding="utf-8")
    print(f"Recall report written to: {output_path}")


if __name__ == "__main__":
    main()
