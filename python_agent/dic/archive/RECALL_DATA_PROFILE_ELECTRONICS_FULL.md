# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-20T08:08:13.722856+00:00
- Canonical interactions: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_electronics_full\canonical_interactions.jsonl`
- Canonical items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_electronics_full\canonical_items.jsonl`
- User sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_electronics_full\user_sequences.jsonl`
- Train user sequences: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_clean_electronics_full\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 43886944
- Exact dedup rows kept: 43408909
- Exact duplicates skipped: 478035
- User-item keep-last rows kept: 43365426
- User-item keep-last removed: 43483
- Frequency filter rows kept: 43365426
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 1609860
- Missing item metadata after filtering: 0
- User sequences written: 18286191
- Train user sequences written: 15193774
- Longest user sequence: 1007
- Longest train user sequence: 942

## 3. Train readiness

- Positive train interactions: 26795784
- Strong positive train interactions: 25042837
- Users with >=2 positive train items: 4837381
- Users with >=2 strong positive train items: 4556602

## 4. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 43365426 | 18286191 | 1609860 |
| train | 34692342 | 15193774 | 1313501 |
| valid | 4336542 | 3133272 | 394302 |
| test | 4336542 | 2932253 | 382852 |

### Split boundaries
- Train rows: 34692342
- Valid rows: 4336542
- Test rows: 4336542
- Small-data all-train threshold: 0
- Small-data all-train applied: False
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 34692342, 'timestamp': 1624989356752, 'user_id': 'AGQ7N45OXLDR3PP7QYDHH7R2S72Q', 'parent_asin': 'B09TSC8SXN'}`
- Valid boundary: `{'row_num': 39028884, 'timestamp': 1655918057058, 'user_id': 'AF2ZMOT7LYJRWW7JIORXEOVLZZPA', 'parent_asin': 'B077YYTPFP'}`
- Test boundary: `{'row_num': 43365426, 'timestamp': 1694625981867, 'user_id': 'AFBTS24P7YOJXTJSGIFRRNYIDLAA', 'parent_asin': 'B09F823P9L'}`

## 5. Recall view stats

### 5.1 Popular recall
- Rows written: 1158601
- Positive train rows used: 26795784
- Recent threshold: 1469658741401

### 5.2 ItemCF recall (weak positives)
- Rows written: 118869568
- Users used: 4837381
- Unique items in graph: 1156103
- Unique item pairs: 59434784

### 5.3 ItemCF recall (strong positives)
- Rows written: 104836430
- Users used: 4556602
- Unique items in graph: 1109721
- Unique item pairs: 52418215

### 5.4 Category and semantic recall
- Category rows written: 1609860
- Category bucket rows: 1243
- Semantic rows written: 1609860

## 6. Output paths

- Popular recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_electronics_full\popular_recall.jsonl`
- Weak ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_electronics_full\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_electronics_full\itemcf_recall_strong.jsonl`
- Category recall items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_electronics_full\category_recall_items.jsonl`
- Category top items: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_electronics_full\category_top_items.jsonl`
- Semantic recall inputs: `D:\sinrotic_code\python_project\summer\RS_agent\data\processed\amazon_2023_recall_views_electronics_full\semantic_recall_inputs.jsonl`
