# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-19T14:25:22.419051+00:00
- Canonical interactions: `data\processed\amazon_2023_recall_clean_smoke\canonical_interactions.jsonl`
- Canonical items: `data\processed\amazon_2023_recall_clean_smoke\canonical_items.jsonl`
- User sequences: `data\processed\amazon_2023_recall_clean_smoke\user_sequences.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 3
- Exact dedup rows kept: 3
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 3
- User-item keep-last removed: 0
- Frequency filter rows kept: 3
- Frequency filter removed: 0
- Canonical items written: 3
- Missing item metadata after filtering: 0
- User sequences written: 1
- Longest user sequence: 3

## 3. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 3 | 1 | 3 |
| train | 1 | 1 | 1 |
| valid | 1 | 1 | 1 |
| test | 1 | 1 | 1 |

## 4. Recall view stats

### 4.1 Popular recall
- Rows written: 1
- Positive train rows used: 1
- Recent threshold: 1523093017534

### 4.2 ItemCF recall
- Rows written: 0
- Users used: 0
- Unique items in graph: 1
- Unique item pairs: 0

### 4.3 Category and semantic recall
- Category rows written: 3
- Category bucket rows: 9
- Semantic rows written: 3

## 5. Output paths

- Popular recall: `data\processed\amazon_2023_recall_views_smoke\popular_recall.jsonl`
- ItemCF recall: `data\processed\amazon_2023_recall_views_smoke\itemcf_recall.jsonl`
- Category recall items: `data\processed\amazon_2023_recall_views_smoke\category_recall_items.jsonl`
- Category top items: `data\processed\amazon_2023_recall_views_smoke\category_top_items.jsonl`
- Semantic recall inputs: `data\processed\amazon_2023_recall_views_smoke\semantic_recall_inputs.jsonl`
