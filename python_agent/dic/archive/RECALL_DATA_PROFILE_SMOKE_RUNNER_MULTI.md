# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-20T13:30:18.981137+00:00
- Canonical interactions: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner_multi\canonical_interactions.jsonl`
- Canonical items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner_multi\canonical_items.jsonl`
- User sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner_multi\user_sequences.jsonl`
- Train user sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_smoke_runner_multi\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 56732656
- Exact dedup rows kept: 56124001
- Exact duplicates skipped: 608655
- User-item keep-last rows kept: 56054775
- User-item keep-last removed: 69226
- Frequency filter rows kept: 56054775
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 2320263
- Missing item metadata after filtering: 0
- User sequences written: 21617114
- Train user sequences written: 18103384
- Longest user sequence: 1595
- Longest train user sequence: 1326

## 3. Train readiness

- Positive train interactions: 37760526
- Strong positive train interactions: 35340485
- Users with >=2 positive train items: 6761142
- Users with >=2 strong positive train items: 6400386

## 4. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 56054775 | 21617114 | 2320263 |
| train | 44843821 | 18103384 | 1886402 |
| valid | 5605477 | 3885224 | 581236 |
| test | 5605477 | 3593207 | 566549 |

### Split boundaries
- Train rows: 44843821
- Valid rows: 5605477
- Test rows: 5605477
- Small-data all-train threshold: 3
- Small-data all-train applied: False
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 44843821, 'timestamp': 1626819149306, 'user_id': 'AFO6QBMDP7YOK4GYT2RWQM5IQEWA', 'parent_asin': 'B0C6936NKR'}`
- Valid boundary: `{'row_num': 50449298, 'timestamp': 1657408140329, 'user_id': 'AGD5MF3VYJ54AQP25A73NPJQ4TBQ', 'parent_asin': 'B08ZMS346Y'}`
- Test boundary: `{'row_num': 56054775, 'timestamp': 1694625981867, 'user_id': 'AFBTS24P7YOJXTJSGIFRRNYIDLAA', 'parent_asin': 'B09F823P9L'}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: 1735036
- Positive train rows used: 37760526
- Recent threshold: 1471122575444

### 5.2 ItemCF recall (weak positives)
- Rows written: 203595826
- Users used: 6761142
- Unique items in graph: 1730120
- Unique item pairs: 101797913

### 5.3 ItemCF recall (strong positives)
- Rows written: 180787582
- Users used: 6400386
- Unique items in graph: 1667450
- Unique item pairs: 90393791

### 5.4 Category and semantic recall
- Category rows written: 2320263
- Category bucket rows: 1876
- Semantic rows written: 2320263

## 6. Output paths

- Popular recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner_multi\popular_recall.jsonl`
- Weak ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner_multi\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner_multi\itemcf_recall_strong.jsonl`
- Category recall items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner_multi\category_recall_items.jsonl`
- Category top items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner_multi\category_top_items.jsonl`
- Semantic recall inputs: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_smoke_runner_multi\semantic_recall_inputs.jsonl`
