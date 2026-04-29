# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-19T16:30:09.355052+00:00
- Canonical interactions: `data\processed\amazon_2023_recall_clean_probe_short_v3\canonical_interactions.jsonl`
- Canonical items: `data\processed\amazon_2023_recall_clean_probe_short_v3\canonical_items.jsonl`
- User sequences: `data\processed\amazon_2023_recall_clean_probe_short_v3\user_sequences.jsonl`
- Train user sequences: `data\processed\amazon_2023_recall_clean_probe_short_v3\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 44
- Exact dedup rows kept: 44
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 44
- User-item keep-last removed: 0
- Frequency filter rows kept: 44
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 44
- Missing item metadata after filtering: 0
- User sequences written: 14
- Train user sequences written: 10
- Longest user sequence: 9
- Longest train user sequence: 8

## 3. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 44 | 14 | 44 |
| train | 36 | 10 | 36 |
| valid | 4 | 3 | 4 |
| test | 4 | 4 | 4 |

### Split boundaries
- Train rows: 36
- Valid rows: 4
- Test rows: 4
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 36, 'timestamp': 1601660312073, 'user_id': 'AFTC6ZR5IKNRDG5JCPVNVMU3XV2Q', 'parent_asin': 'B08X4R1T16'}`
- Valid boundary: `{'row_num': 40, 'timestamp': 1638832601151, 'user_id': 'AFTC6ZR5IKNRDG5JCPVNVMU3XV2Q', 'parent_asin': 'B0BNX9QVXZ'}`
- Test boundary: `{'row_num': 44, 'timestamp': 1676601581238, 'user_id': 'AG2L7H23R5LLKDKLBEF2Q3L2MVDA', 'parent_asin': 'B07CJYMRWM'}`

## 4. Recall view stats

### 4.1 Popular recall
- Rows written: 32
- Positive train rows used: 32
- Recent threshold: 1524297919858

### 4.2 ItemCF recall (weak positives)
- Rows written: 118
- Users used: 6
- Unique items in graph: 32
- Unique item pairs: 59

### 4.3 ItemCF recall (strong positives)
- Rows written: 106
- Users used: 5
- Unique items in graph: 30
- Unique item pairs: 53

### 4.4 Category and semantic recall
- Category rows written: 44
- Category bucket rows: 75
- Semantic rows written: 44

## 5. Output paths

- Popular recall: `data\processed\amazon_2023_recall_views_probe_short_v3\popular_recall.jsonl`
- Weak ItemCF recall: `data\processed\amazon_2023_recall_views_probe_short_v3\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `data\processed\amazon_2023_recall_views_probe_short_v3\itemcf_recall_strong.jsonl`
- Category recall items: `data\processed\amazon_2023_recall_views_probe_short_v3\category_recall_items.jsonl`
- Category top items: `data\processed\amazon_2023_recall_views_probe_short_v3\category_top_items.jsonl`
- Semantic recall inputs: `data\processed\amazon_2023_recall_views_probe_short_v3\semantic_recall_inputs.jsonl`
