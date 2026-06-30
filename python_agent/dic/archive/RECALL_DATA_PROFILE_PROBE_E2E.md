# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-20T04:32:14.206581+00:00
- Canonical interactions: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_probe_e2e\canonical_interactions.jsonl`
- Canonical items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_probe_e2e\canonical_items.jsonl`
- User sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_probe_e2e\user_sequences.jsonl`
- Train user sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_probe_e2e\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 20
- Exact dedup rows kept: 20
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 20
- User-item keep-last removed: 0
- Frequency filter rows kept: 20
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 20
- Missing item metadata after filtering: 0
- User sequences written: 7
- Train user sequences written: 6
- Longest user sequence: 9
- Longest train user sequence: 8

## 3. Train readiness

- Positive train interactions: 15
- Strong positive train interactions: 15
- Users with >=2 positive train items: 2
- Users with >=2 strong positive train items: 2

## 4. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 20 | 7 | 20 |
| train | 16 | 6 | 16 |
| valid | 2 | 2 | 2 |
| test | 2 | 2 | 2 |

### Split boundaries
- Train rows: 16
- Valid rows: 2
- Test rows: 2
- Small-data all-train threshold: 3
- Small-data all-train applied: False
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 16, 'timestamp': 1565130879386, 'user_id': 'AGCI7FAH4GL5FI65HYLKWTMFZ2CQ', 'parent_asin': 'B07BHHB5RH'}`
- Valid boundary: `{'row_num': 18, 'timestamp': 1637522881041, 'user_id': 'AGCI7FAH4GL5FI65HYLKWTMFZ2CQ', 'parent_asin': 'B07CML419K'}`
- Test boundary: `{'row_num': 20, 'timestamp': 1676601581238, 'user_id': 'AG2L7H23R5LLKDKLBEF2Q3L2MVDA', 'parent_asin': 'B07CJYMRWM'}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: 15
- Positive train rows used: 15
- Recent threshold: 1510160402508

### 5.2 ItemCF recall (weak positives)
- Rows written: 54
- Users used: 2
- Unique items in graph: 15
- Unique item pairs: 27

### 5.3 ItemCF recall (strong positives)
- Rows written: 54
- Users used: 2
- Unique items in graph: 15
- Unique item pairs: 27

### 5.4 Category and semantic recall
- Category rows written: 20
- Category bucket rows: 41
- Semantic rows written: 20

## 6. Output paths

- Popular recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_probe_e2e\popular_recall.jsonl`
- Weak ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_probe_e2e\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_probe_e2e\itemcf_recall_strong.jsonl`
- Category recall items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_probe_e2e\category_recall_items.jsonl`
- Category top items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_probe_e2e\category_top_items.jsonl`
- Semantic recall inputs: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_probe_e2e\semantic_recall_inputs.jsonl`
