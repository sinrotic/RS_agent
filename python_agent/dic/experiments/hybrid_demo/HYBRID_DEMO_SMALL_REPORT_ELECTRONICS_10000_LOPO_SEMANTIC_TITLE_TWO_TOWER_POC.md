# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_10000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_10000",
  "evaluation_mode": "leave_one_positive_out",
  "top_k": 5,
  "candidate_pool_size": 50,
  "limit_users": null,
  "rank_weights": {
    "popular": 1.0,
    "itemcf_weak": 2.0,
    "itemcf_strong": 2.5,
    "category": 0.8,
    "semantic": 1.2,
    "two_tower": 1.2,
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  },
  "rerank_policy": {},
  "source_aware_fusion": {},
  "item_feature_rerank": {},
  "ltr_model": {
    "enabled": false
  },
  "topk_source_minimums": {
    "itemcf": 1
  },
  "candidate_source_minimums": {
    "itemcf": 20,
    "semantic": 20,
    "two_tower": 10
  },
  "semantic_enabled": true,
  "semantic_per_user": 30,
  "semantic_min_overlap": 1,
  "semantic_score_mode": "raw",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ],
  "two_tower_enabled": true,
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": 30,
  "two_tower_seed_window": 10,
  "two_tower_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ],
  "two_tower_min_overlap": 1,
  "two_tower_recency_decay": 0.85,
  "lopo_input_users": 2340,
  "lopo_eligible_users": 1382,
  "lopo_skipped_users_fewer_than_2_positives": 958
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | leave_one_positive_out |
| users_total | 1382 |
| users_with_holdout | 1382 |
| users_evaluated | 1382 |
| lopo_input_users | 2340 |
| lopo_eligible_users | 1382 |
| lopo_skipped_users_fewer_than_2_positives | 958 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 50.0 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.939942 |
| candidate_hit_users | 1299 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 38.297152 |
| candidate_hit_rank_p50 | 42.0 |
| candidate_hit_rank_p90 | 50.0 |
| candidate_hit_missed_topk_users | 252 |
| ranked_hit_users | 1047 |
| recall_at_k | 0.757598 |
| recall_at_pool | 0.939942 |
| ndcg_at_k | 0.299326 |
| mrr_at_k | 0.159298 |
| map_at_k | 0.159298 |
| hit_rate_at_k | 0.757598 |
| popular_only_hit_rate_at_k | 0.024602 |
| itemcf_only_hit_rate_at_k | 0.887844 |
| hybrid_hit_rate_at_k | 0.757598 |
| hybrid_no_itemcf_hit_rate_at_k | 0.025326 |
| category_diversity_avg | 2.353111 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 7915, "itemcf_strong": 11479, "itemcf_weak": 11962, "popular": 15484, "semantic": 38333, "two_tower": 19005}`
- topk_source_coverage: `{"category": 1835, "itemcf_strong": 1306, "itemcf_weak": 1351, "popular": 4145, "semantic": 1863, "two_tower": 1259}`
- per_source_candidate_contribution: `{"category": 45, "itemcf_strong": 1219, "itemcf_weak": 1292, "popular": 62, "semantic": 64, "two_tower": 86}`
- per_source_topk_contribution: `{"category": 43, "itemcf_strong": 990, "itemcf_weak": 1043, "popular": 58, "semantic": 61, "two_tower": 78}`
- source_overlap: `{"single_source_candidate_count": 35698, "multi_source_candidate_count": 33402, "multi_source_candidate_rate": 0.483386, "source_pair_counts": {"category+itemcf_strong": 186, "category+itemcf_weak": 190, "category+popular": 7154, "category+semantic": 734, "category+two_tower": 902, "itemcf_strong+itemcf_weak": 10538, "itemcf_strong+popular": 209, "itemcf_strong+semantic": 149, "itemcf_strong+two_tower": 201, "itemcf_weak+popular": 213, "itemcf_weak+semantic": 154, "itemcf_weak+two_tower": 219, "popular+semantic": 301, "popular+two_tower": 578, "semantic+two_tower": 15422}}`
- source_diagnostics: `{"users_with_positive_seeds": 1382, "users_with_itemcf_seed_hits": 1382, "users_with_itemcf_raw_candidates": 1382, "itemcf_raw_candidates": 445846, "itemcf_raw_unseen_candidates": 180148}`

## Diagnostic Gate

```json
{
  "recall_bottleneck": false,
  "ranking_bottleneck": true,
  "source_merge_bottleneck": false,
  "latency_bottleneck": false,
  "architecture_escalation": false,
  "recommended_next_phase": "phase_1_12_ranking_ltr_gate",
  "evidence": {
    "top_k": 5,
    "candidate_pool_size": 50,
    "candidate_hit_rate_at_pool": 0.939942,
    "hit_rate_at_k": 0.757598,
    "ndcg_at_k": 0.299326,
    "mrr_at_k": 0.159298,
    "candidate_hit_users": 1299,
    "candidate_hit_missed_topk_users": 252,
    "candidate_hit_rank_p50": 42.0,
    "candidate_hit_rank_p90": 50.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.483386,
    "ranking_p95_seconds": 0.00038
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.804706,
  "candidate_generation_p95_seconds": 1.138104,
  "ranking_avg_seconds": 0.00027,
  "ranking_p95_seconds": 0.00038,
  "recommendation_avg_seconds": 0.804996,
  "recommendation_p95_seconds": 1.138356,
  "total_run_seconds": 1115.964141
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.939942
- candidate_hit_users: 1299
- ranked_hit_users: 1047
- candidate_hit_missed_topk_users: 252
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 38.297152
- candidate_hit_rank_p50: 42.0
- candidate_hit_rank_p90: 50.0
- candidate_hit_source_coverage: `{"category": 45, "itemcf_strong": 1219, "itemcf_weak": 1292, "popular": 62, "semantic": 64, "two_tower": 86}`

## Ranking Case Summary

- total_hit_cases: 1299
- topk_hit_cases: 57
- missed_topk_cases: 1242
- semantic_only_items_above_share: 0.415132
- top1_score_gap_avg: 49.683794
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 10, "category+itemcf_strong+itemcf_weak+popular": 17, "category+itemcf_strong+itemcf_weak+popular+two_tower": 2, "category+itemcf_strong+itemcf_weak+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 2, "category+itemcf_weak+popular": 1, "itemcf_strong": 1, "itemcf_strong+itemcf_weak": 1062, "itemcf_strong+itemcf_weak+popular": 18, "itemcf_strong+itemcf_weak+popular+two_tower": 1, "itemcf_strong+itemcf_weak+semantic": 11, "itemcf_strong+itemcf_weak+semantic+two_tower": 12, "itemcf_strong+itemcf_weak+two_tower": 31, "itemcf_weak": 68, "itemcf_weak+popular": 1, "itemcf_weak+two_tower": 2, "semantic": 1, "two_tower": 1}`
- items_above_source_combinations: `{"semantic": 20060, "semantic+two_tower": 13130, "popular": 7456, "category+popular": 5680, "itemcf_strong+itemcf_weak": 702, "category+popular+two_tower": 275, "category+semantic": 227, "category+semantic+two_tower": 189, "category+popular+semantic": 92, "category+two_tower": 77, "category+popular+semantic+two_tower": 74, "popular+two_tower": 55, "category+itemcf_strong+itemcf_weak+popular": 54, "itemcf_strong+itemcf_weak+popular": 47, "itemcf_strong+itemcf_weak+semantic+two_tower": 35, "itemcf_strong+itemcf_weak+semantic": 24, "category+itemcf_strong+itemcf_weak": 23, "popular+semantic+two_tower": 20, "category+itemcf_weak+popular": 13, "itemcf_strong+itemcf_weak+two_tower": 8, "itemcf_strong": 8, "popular+semantic": 8, "itemcf_strong+popular": 8, "itemcf_weak": 7, "category+itemcf_strong+popular": 7, "category+itemcf_strong+itemcf_weak+popular+two_tower": 5, "category+itemcf_strong+itemcf_weak+popular+semantic+two_tower": 5, "itemcf_weak+popular": 5, "category+itemcf_strong": 5, "itemcf_strong+semantic": 4, "itemcf_weak+semantic+two_tower": 4, "itemcf_weak+semantic": 4, "category+itemcf_weak+popular+two_tower": 2, "itemcf_strong+semantic+two_tower": 2, "category+itemcf_weak": 2, "category+itemcf_strong+itemcf_weak+popular+semantic": 2, "category+itemcf_weak+popular+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "category+itemcf_strong+semantic+two_tower": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_11_two_tower_poc_10000_lopo
- risk_flags: none
- items:
  - B071VDV7NC score=55.635044 sources=category,semantic,two_tower,popular
  - B07MZ6PJW8 score=54.686808 sources=semantic,two_tower
  - B07TJ87YKB score=53.599987 sources=semantic,two_tower
  - B07VVJNG7P score=52.314802 sources=semantic,two_tower
  - B09RHJTQTM score=4.5 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_11_two_tower_poc_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=5.75 sources=itemcf_weak,itemcf_strong,category

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_11_two_tower_poc_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=3.181982 sources=itemcf_weak,itemcf_strong
