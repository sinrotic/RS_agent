# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-27T04:36:26.473750+00:00
- Canonical interactions: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_100\canonical_interactions.jsonl`
- Canonical items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_100\canonical_items.jsonl`
- User sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_100\user_sequences.jsonl`
- Train user sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_100\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 100
- Exact dedup rows kept: 100
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 100
- User-item keep-last removed: 0
- Frequency filter rows kept: 100
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 43
- Missing item metadata after filtering: 57
- User sequences written: 30
- Train user sequences written: 22
- Longest user sequence: 22
- Longest train user sequence: 17

## 3. Train readiness

- Positive train interactions: 72
- Strong positive train interactions: 70
- Users with >=2 positive train items: 12
- Users with >=2 strong positive train items: 11

## 4. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 100 | 30 | 100 |
| train | 80 | 22 | 80 |
| valid | 10 | 7 | 10 |
| test | 10 | 10 | 10 |

### Split boundaries
- Train rows: 80
- Valid rows: 10
- Test rows: 10
- Small-data all-train threshold: 3
- Small-data all-train applied: False
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 80, 'timestamp': 1606084429795, 'user_id': 'AFQLNQNQYFWQZPJQZS6V3NZU4QBQ', 'parent_asin': 'B08BRJ98H3'}`
- Valid boundary: `{'row_num': 90, 'timestamp': 1637522881041, 'user_id': 'AGCI7FAH4GL5FI65HYLKWTMFZ2CQ', 'parent_asin': 'B07CML419K'}`
- Test boundary: `{'row_num': 100, 'timestamp': 1676601581238, 'user_id': 'AG2L7H23R5LLKDKLBEF2Q3L2MVDA', 'parent_asin': 'B07CJYMRWM'}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: 72
- Positive train rows used: 72
- Recent threshold: 1527837214036

### 5.2 ItemCF recall (weak positives)
- Rows written: 490
- Users used: 12
- Unique items in graph: 72
- Unique item pairs: 245

### 5.3 ItemCF recall (strong positives)
- Rows written: 478
- Users used: 11
- Unique items in graph: 70
- Unique item pairs: 239

### 5.4 Category and semantic recall
- Category rows written: 43
- Category bucket rows: 84
- Semantic rows written: 43

## 6. Output paths

- Popular recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_100\popular_recall.jsonl`
- Weak ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_100\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_100\itemcf_recall_strong.jsonl`
- Category recall items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_100\category_recall_items.jsonl`
- Category top items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_100\category_top_items.jsonl`
- Semantic recall inputs: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_100\semantic_recall_inputs.jsonl`
