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
    "semantic": 20
  },
  "semantic_enabled": true,
  "semantic_per_user": 30,
  "semantic_min_overlap": 1,
  "semantic_score_mode": "idf_seed_aware",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ],
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
| candidate_count_avg | 49.698987 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.941389 |
| candidate_hit_users | 1301 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 36.006149 |
| candidate_hit_rank_p50 | 35.0 |
| candidate_hit_rank_p90 | 49.0 |
| candidate_hit_missed_topk_users | 205 |
| ranked_hit_users | 1096 |
| recall_at_k | 0.793054 |
| recall_at_pool | 0.941389 |
| ndcg_at_k | 0.320614 |
| mrr_at_k | 0.176435 |
| map_at_k | 0.176435 |
| hit_rate_at_k | 0.793054 |
| popular_only_hit_rate_at_k | 0.002894 |
| itemcf_only_hit_rate_at_k | 0.901592 |
| hybrid_hit_rate_at_k | 0.793054 |
| hybrid_no_itemcf_hit_rate_at_k | 0.016643 |
| category_diversity_avg | 1.404486 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 17175, "itemcf_strong": 13277, "itemcf_weak": 14003, "popular": 2686, "semantic": 34732}`
- topk_source_coverage: `{"category": 1219, "itemcf_strong": 1317, "itemcf_weak": 1376, "popular": 1204, "semantic": 3840}`
- per_source_candidate_contribution: `{"category": 34, "itemcf_strong": 1218, "itemcf_weak": 1291, "popular": 7, "semantic": 61}`
- per_source_topk_contribution: `{"category": 31, "itemcf_strong": 1033, "itemcf_weak": 1093, "popular": 7, "semantic": 57}`
- source_overlap: `{"single_source_candidate_count": 55777, "multi_source_candidate_count": 12907, "multi_source_candidate_rate": 0.187919, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 135, "category+popular": 166, "category+semantic": 522, "itemcf_strong+itemcf_weak": 12180, "itemcf_strong+popular": 6, "itemcf_strong+semantic": 165, "itemcf_weak+popular": 8, "itemcf_weak+semantic": 170, "popular+semantic": 2}}`
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
    "candidate_hit_rate_at_pool": 0.941389,
    "hit_rate_at_k": 0.793054,
    "ndcg_at_k": 0.320614,
    "mrr_at_k": 0.176435,
    "candidate_hit_users": 1301,
    "candidate_hit_missed_topk_users": 205,
    "candidate_hit_rank_p50": 35.0,
    "candidate_hit_rank_p90": 49.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.187919,
    "ranking_p95_seconds": 0.000376
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 1.773876,
  "candidate_generation_p95_seconds": 5.64523,
  "ranking_avg_seconds": 0.000286,
  "ranking_p95_seconds": 0.000376,
  "recommendation_avg_seconds": 1.774177,
  "recommendation_p95_seconds": 5.645512,
  "total_run_seconds": 2454.688611
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.941389
- candidate_hit_users: 1301
- ranked_hit_users: 1096
- candidate_hit_missed_topk_users: 205
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 36.006149
- candidate_hit_rank_p50: 35.0
- candidate_hit_rank_p90: 49.0
- candidate_hit_source_coverage: `{"category": 34, "itemcf_strong": 1218, "itemcf_weak": 1291, "popular": 7, "semantic": 61}`

## Ranking Case Summary

- total_hit_cases: 1301
- topk_hit_cases: 48
- missed_topk_cases: 1253
- semantic_only_items_above_share: 0.673114
- top1_score_gap_avg: 25.22443
- target_source_combinations: `{"category": 1, "category+itemcf_strong+itemcf_weak": 24, "category+itemcf_strong+itemcf_weak+popular": 1, "category+itemcf_weak": 1, "itemcf_strong": 2, "itemcf_strong+itemcf_weak": 1127, "itemcf_strong+itemcf_weak+semantic": 21, "itemcf_weak": 72, "itemcf_weak+popular": 1, "semantic": 3}`
- items_above_source_combinations: `{"semantic": 30626, "category": 11118, "popular": 2433, "itemcf_strong+itemcf_weak": 495, "category+semantic": 435, "category+popular": 163, "itemcf_strong+itemcf_weak+semantic": 77, "category+itemcf_strong+itemcf_weak": 63, "itemcf_weak": 34, "category+itemcf_weak": 12, "itemcf_weak+semantic": 11, "itemcf_strong": 10, "category+itemcf_strong+itemcf_weak+semantic": 9, "category+itemcf_strong": 6, "itemcf_strong+semantic": 2, "category+popular+semantic": 2, "category+itemcf_weak+semantic": 1, "category+itemcf_strong+semantic": 1, "itemcf_strong+itemcf_weak+popular": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_11_recall_source_merge_demo_10000_lopo
- risk_flags: none
- items:
  - B07VVJNG7P score=25.52545 sources=semantic
  - B073XJBJLG score=25.493603 sources=semantic
  - B09BVJ854R score=25.471267 sources=semantic
  - B07MZ6PJW8 score=25.312718 sources=semantic
  - B09RHJTQTM score=4.5 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_11_recall_source_merge_demo_10000_lopo
- risk_flags: none
- items:
  - B07QPTYSPP score=17.694154 sources=semantic
  - B07Q74L1TR score=17.568796 sources=semantic
  - B0BSK363WC score=17.363402 sources=semantic
  - B081TZ8TBM score=17.178769 sources=semantic
  - B00KWR8ME2 score=5.75 sources=itemcf_weak,itemcf_strong,category

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_11_recall_source_merge_demo_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=3.181982 sources=itemcf_weak,itemcf_strong
