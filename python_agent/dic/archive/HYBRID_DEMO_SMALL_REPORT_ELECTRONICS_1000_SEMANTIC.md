# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics_1000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics_1000",
  "evaluation_mode": "valid_test",
  "top_k": 5,
  "candidate_pool_size": 50,
  "limit_users": 100,
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
  "topk_source_minimums": {
    "itemcf": 1
  },
  "candidate_source_minimums": {
    "itemcf": 20,
    "semantic": 20
  },
  "semantic_enabled": true,
  "semantic_per_user": 30,
  "semantic_min_overlap": 2
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | valid_test |
| users_total | 100 |
| users_with_holdout | 30 |
| users_evaluated | 30 |
| lopo_input_users | None |
| lopo_eligible_users | None |
| lopo_skipped_users_fewer_than_2_positives | None |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 50.0 |
| fallback_rate | 0.31 |
| candidate_hit_rate_at_pool | 0.2 |
| candidate_hit_users | 6 |
| candidate_hit_rank_min | 2 |
| candidate_hit_rank_avg | 20.333333 |
| candidate_hit_rank_p50 | 23.0 |
| candidate_hit_missed_topk_users | 5 |
| ranked_hit_users | 1 |
| hit_rate_at_k | 0.033333 |
| popular_only_hit_rate_at_k | 0.033333 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.033333 |
| hybrid_no_itemcf_hit_rate_at_k | 0.033333 |
| category_diversity_avg | 2.23 |

## Fallback and Source Coverage

- fallback_rate: 0.31
- recall_source_coverage: `{"category": 350, "itemcf_strong": 131, "itemcf_weak": 135, "popular": 3070, "semantic": 2010}`
- topk_source_coverage: `{"category": 33, "itemcf_strong": 14, "itemcf_weak": 14, "popular": 219, "semantic": 324}`
- source_diagnostics: `{"users_with_positive_seeds": 90, "users_with_itemcf_seed_hits": 52, "users_with_itemcf_raw_candidates": 52, "itemcf_raw_candidates": 12754, "itemcf_raw_unseen_candidates": 964}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.2
- candidate_hit_users: 6
- ranked_hit_users: 1
- candidate_hit_missed_topk_users: 5
- candidate_hit_rank_min: 2
- candidate_hit_rank_avg: 20.333333
- candidate_hit_rank_p50: 23.0
- candidate_hit_source_coverage: `{"category": 2, "popular": 2, "semantic": 5}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_6_deterministic_semantic_recall_demo
- risk_flags: none
- items:
  - B0020HRE1Y score=80.559368 sources=semantic,popular
  - B0BLCBK97H score=79.2 sources=semantic
  - B004WMSV76 score=69.6 sources=semantic
  - B089T4YVYD score=67.2 sources=semantic
  - B00XI3MMMA score=64.8 sources=semantic

### User AE3Q6AEWP7Y7CH4N6IWEP4YBNP2A

- strategy: phase_1_6_deterministic_semantic_recall_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular

### User AE4KVNO5P6N6SP6CQTZTIDHEAWFQ

- strategy: phase_1_6_deterministic_semantic_recall_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular
