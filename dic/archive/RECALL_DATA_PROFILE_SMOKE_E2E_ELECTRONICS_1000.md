# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-27T04:52:08.370733+00:00
- Canonical interactions: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_1000\canonical_interactions.jsonl`
- Canonical items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_1000\canonical_items.jsonl`
- User sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_1000\user_sequences.jsonl`
- Train user sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_e2e_electronics_1000\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 1000
- Exact dedup rows kept: 1000
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 996
- User-item keep-last removed: 4
- Frequency filter rows kept: 996
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 525
- Missing item metadata after filtering: 434
- User sequences written: 195
- Train user sequences written: 165
- Longest user sequence: 198
- Longest train user sequence: 155

## 3. Train readiness

- Positive train interactions: 699
- Strong positive train interactions: 621
- Users with >=2 positive train items: 81
- Users with >=2 strong positive train items: 79

## 4. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 996 | 195 | 959 |
| train | 798 | 165 | 771 |
| valid | 99 | 45 | 99 |
| test | 99 | 54 | 98 |

### Split boundaries
- Train rows: 798
- Valid rows: 99
- Test rows: 99
- Small-data all-train threshold: 3
- Small-data all-train applied: False
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 798, 'timestamp': 1631385848791, 'user_id': 'AHEQRHKGEACLR3RSXRQ7TUIXZGSQ', 'parent_asin': 'B08N5821RN'}`
- Valid boundary: `{'row_num': 897, 'timestamp': 1653778081398, 'user_id': 'AFZUK3MTBIBEDQOPAK3OATUOUKLA', 'parent_asin': 'B0C33824RM'}`
- Test boundary: `{'row_num': 996, 'timestamp': 1678797076214, 'user_id': 'AHCPZDDPHJE3G7M6ST5WGRPLXHOA', 'parent_asin': 'B0BFHVDPTG'}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: 676
- Positive train rows used: 699
- Recent threshold: 1537629986157

### 5.2 ItemCF recall (weak positives)
- Rows written: 9802
- Users used: 81
- Unique items in graph: 567
- Unique item pairs: 4901

### 5.3 ItemCF recall (strong positives)
- Rows written: 7218
- Users used: 79
- Unique items in graph: 510
- Unique item pairs: 3609

### 5.4 Category and semantic recall
- Category rows written: 525
- Category bucket rows: 257
- Semantic rows written: 525

## 6. Output paths

- Popular recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_1000\popular_recall.jsonl`
- Weak ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_1000\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_1000\itemcf_recall_strong.jsonl`
- Category recall items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_1000\category_recall_items.jsonl`
- Category top items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_1000\category_top_items.jsonl`
- Semantic recall inputs: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_e2e_electronics_1000\semantic_recall_inputs.jsonl`
