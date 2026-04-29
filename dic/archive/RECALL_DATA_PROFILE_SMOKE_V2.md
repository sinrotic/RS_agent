# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-19T16:12:24.857196+00:00
- Canonical interactions: `data\processed\amazon_2023_recall_clean_smoke_v2\canonical_interactions.jsonl`
- Canonical items: `data\processed\amazon_2023_recall_clean_smoke_v2\canonical_items.jsonl`
- User sequences: `data\processed\amazon_2023_recall_clean_smoke_v2\user_sequences.jsonl`
- Train user sequences: `data\processed\amazon_2023_recall_clean_smoke_v2\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 3
- Exact dedup rows kept: 3
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 3
- User-item keep-last removed: 0
- Frequency filter rows kept: 3
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 3
- Final min item interactions: 1
- Canonical items written: 3
- Missing item metadata after filtering: 0
- User sequences written: 1
- Train user sequences written: 1
- Longest user sequence: 3
- Longest train user sequence: 1

## 3. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 3 | 1 | 3 |
| train | 1 | 1 | 1 |
| valid | 1 | 1 | 1 |
| test | 1 | 1 | 1 |

### Split boundaries
- Train rows: 1
- Valid rows: 1
- Test rows: 1
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 1, 'timestamp': 1523093017534, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B01G8JO5F2'}`
- Valid boundary: `{'row_num': 2, 'timestamp': 1592678549731, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B07N69T6TM'}`
- Test boundary: `{'row_num': 3, 'timestamp': 1658185117948, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B083NRGZMM'}`

## 4. Recall view stats

### 4.1 Popular recall
- Rows written: 1
- Positive train rows used: 1
- Recent threshold: 1523093017533

### 4.2 ItemCF recall (weak positives)
- Rows written: 0
- Users used: 0
- Unique items in graph: 1
- Unique item pairs: 0

### 4.3 ItemCF recall (strong positives)
- Rows written: 0
- Users used: 0
- Unique items in graph: 1
- Unique item pairs: 0

### 4.4 Category and semantic recall
- Category rows written: 3
- Category bucket rows: 9
- Semantic rows written: 3

## 5. Output paths

- Popular recall: `data\processed\amazon_2023_recall_views_smoke_v2\popular_recall.jsonl`
- Weak ItemCF recall: `data\processed\amazon_2023_recall_views_smoke_v2\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `data\processed\amazon_2023_recall_views_smoke_v2\itemcf_recall_strong.jsonl`
- Category recall items: `data\processed\amazon_2023_recall_views_smoke_v2\category_recall_items.jsonl`
- Category top items: `data\processed\amazon_2023_recall_views_smoke_v2\category_top_items.jsonl`
- Semantic recall inputs: `data\processed\amazon_2023_recall_views_smoke_v2\semantic_recall_inputs.jsonl`
