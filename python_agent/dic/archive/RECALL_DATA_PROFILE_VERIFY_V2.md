# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-19T16:11:54.200034+00:00
- Canonical interactions: `data\processed\amazon_2023_recall_clean_verify_v2\canonical_interactions.jsonl`
- Canonical items: `data\processed\amazon_2023_recall_clean_verify_v2\canonical_items.jsonl`
- User sequences: `data\processed\amazon_2023_recall_clean_verify_v2\user_sequences.jsonl`
- Train user sequences: `data\processed\amazon_2023_recall_clean_verify_v2\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 1
- Exact dedup rows kept: 1
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 1
- User-item keep-last removed: 0
- Frequency filter rows kept: 1
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 1
- Missing item metadata after filtering: 0
- User sequences written: 1
- Train user sequences written: 1
- Longest user sequence: 1
- Longest train user sequence: 1

## 3. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 1 | 1 | 1 |
| train | 1 | 1 | 1 |
| valid | 0 | 0 | 0 |
| test | 0 | 0 | 0 |

### Split boundaries
- Train rows: 1
- Valid rows: 0
- Test rows: 0
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 1, 'timestamp': 1658185117948, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B083NRGZMM'}`
- Valid boundary: `None`
- Test boundary: `{'row_num': 1, 'timestamp': 1658185117948, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B083NRGZMM'}`

## 4. Recall view stats

### 4.1 Popular recall
- Rows written: 0
- Positive train rows used: 0
- Recent threshold: 0

### 4.2 ItemCF recall (weak positives)
- Rows written: 0
- Users used: 0
- Unique items in graph: 0
- Unique item pairs: 0

### 4.3 ItemCF recall (strong positives)
- Rows written: 0
- Users used: 0
- Unique items in graph: 0
- Unique item pairs: 0

### 4.4 Category and semantic recall
- Category rows written: 1
- Category bucket rows: 5
- Semantic rows written: 1

## 5. Output paths

- Popular recall: `data\processed\amazon_2023_recall_views_verify_v2\popular_recall.jsonl`
- Weak ItemCF recall: `data\processed\amazon_2023_recall_views_verify_v2\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `data\processed\amazon_2023_recall_views_verify_v2\itemcf_recall_strong.jsonl`
- Category recall items: `data\processed\amazon_2023_recall_views_verify_v2\category_recall_items.jsonl`
- Category top items: `data\processed\amazon_2023_recall_views_verify_v2\category_top_items.jsonl`
- Semantic recall inputs: `data\processed\amazon_2023_recall_views_verify_v2\semantic_recall_inputs.jsonl`
