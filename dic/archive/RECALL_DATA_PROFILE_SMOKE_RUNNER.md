# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-20T04:22:08.664889+00:00
- Canonical interactions: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner\canonical_interactions.jsonl`
- Canonical items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner\canonical_items.jsonl`
- User sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner\user_sequences.jsonl`
- Train user sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner\user_sequences.train.jsonl`

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
- Longest train user sequence: 3

## 3. Train readiness

- Positive train interactions: 2
- Strong positive train interactions: 2
- Users with >=2 positive train items: 1
- Users with >=2 strong positive train items: 1

## 4. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 3 | 1 | 3 |
| train | 3 | 1 | 3 |
| valid | 0 | 0 | 0 |
| test | 0 | 0 | 0 |

### Split boundaries
- Train rows: 3
- Valid rows: 0
- Test rows: 0
- Small-data all-train threshold: 3
- Small-data all-train applied: True
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 3, 'timestamp': 1658185117948, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B083NRGZMM'}`
- Valid boundary: `None`
- Test boundary: `{'row_num': 3, 'timestamp': 1658185117948, 'user_id': 'AFKZENTNBQ7A7V7UXW5JJI6UGRYQ', 'parent_asin': 'B083NRGZMM'}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: 2
- Positive train rows used: 2
- Recent threshold: 1631166697865

### 5.2 ItemCF recall (weak positives)
- Rows written: 2
- Users used: 1
- Unique items in graph: 2
- Unique item pairs: 1

### 5.3 ItemCF recall (strong positives)
- Rows written: 2
- Users used: 1
- Unique items in graph: 2
- Unique item pairs: 1

### 5.4 Category and semantic recall
- Category rows written: 3
- Category bucket rows: 9
- Semantic rows written: 3

## 6. Output paths

- Popular recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner\popular_recall.jsonl`
- Weak ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner\itemcf_recall_strong.jsonl`
- Category recall items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner\category_recall_items.jsonl`
- Category top items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner\category_top_items.jsonl`
- Semantic recall inputs: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner\semantic_recall_inputs.jsonl`
