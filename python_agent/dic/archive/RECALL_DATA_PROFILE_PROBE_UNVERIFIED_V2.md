# Recall Data Profile

## 1. Summary

- Report generated at: 2026-04-19T16:13:11.782084+00:00
- Canonical interactions: `data\processed\amazon_2023_recall_clean_probe_unverified_v2\canonical_interactions.jsonl`
- Canonical items: `data\processed\amazon_2023_recall_clean_probe_unverified_v2\canonical_items.jsonl`
- User sequences: `data\processed\amazon_2023_recall_clean_probe_unverified_v2\user_sequences.jsonl`
- Train user sequences: `data\processed\amazon_2023_recall_clean_probe_unverified_v2\user_sequences.train.jsonl`

## 2. Canonical table build stats

- Raw reviews seen: 27
- Exact dedup rows kept: 27
- Exact duplicates skipped: 0
- User-item keep-last rows kept: 27
- User-item keep-last removed: 0
- Frequency filter rows kept: 27
- Frequency filter removed: 0
- K-core iterations: 0
- Final min user interactions: 1
- Final min item interactions: 1
- Canonical items written: 27
- Missing item metadata after filtering: 0
- User sequences written: 9
- Train user sequences written: 7
- Longest user sequence: 9
- Longest train user sequence: 8

## 3. Split coverage

| Split | Interactions | Distinct Users | Distinct Items |
| --- | ---: | ---: | ---: |
| all | 27 | 9 | 27 |
| train | 23 | 7 | 23 |
| valid | 2 | 2 | 2 |
| test | 2 | 2 | 2 |

### Split boundaries
- Train rows: 23
- Valid rows: 2
- Test rows: 2
- Ordering key: `['timestamp', 'user_id', 'parent_asin']`
- Train boundary: `{'row_num': 23, 'timestamp': 1597714311689, 'user_id': 'AGBFYI2DDIKXC5Y4FARTYDTQBMFQ', 'parent_asin': 'B0199HAOAU'}`
- Valid boundary: `{'row_num': 25, 'timestamp': 1643011912524, 'user_id': 'AFE337D2J37YRU5U6MVTVKNDKWDA', 'parent_asin': 'B0B2DLVCF3'}`
- Test boundary: `{'row_num': 27, 'timestamp': 1676601581238, 'user_id': 'AG2L7H23R5LLKDKLBEF2Q3L2MVDA', 'parent_asin': 'B07CJYMRWM'}`

## 4. Recall view stats

### 4.1 Popular recall
- Rows written: 19
- Positive train rows used: 19
- Recent threshold: 1536227148351

### 4.2 ItemCF recall (weak positives)
- Rows written: 62
- Users used: 3
- Unique items in graph: 19
- Unique item pairs: 31

### 4.3 ItemCF recall (strong positives)
- Rows written: 52
- Users used: 3
- Unique items in graph: 18
- Unique item pairs: 26

### 4.4 Category and semantic recall
- Category rows written: 27
- Category bucket rows: 54
- Semantic rows written: 27

## 5. Output paths

- Popular recall: `data\processed\amazon_2023_recall_views_probe_unverified_v2\popular_recall.jsonl`
- Weak ItemCF recall: `data\processed\amazon_2023_recall_views_probe_unverified_v2\itemcf_recall_weak.jsonl`
- Strong ItemCF recall: `data\processed\amazon_2023_recall_views_probe_unverified_v2\itemcf_recall_strong.jsonl`
- Category recall items: `data\processed\amazon_2023_recall_views_probe_unverified_v2\category_recall_items.jsonl`
- Category top items: `data\processed\amazon_2023_recall_views_probe_unverified_v2\category_top_items.jsonl`
- Semantic recall inputs: `data\processed\amazon_2023_recall_views_probe_unverified_v2\semantic_recall_inputs.jsonl`
