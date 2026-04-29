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
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  },
  "topk_source_minimums": {
    "itemcf": 1
  }
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | valid_test |
| users_total | 100 |
| users_with_holdout | 30 |
| users_evaluated | 30 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 50.0 |
| fallback_rate | 0.31 |
| candidate_hit_rate_at_pool | 0.066667 |
| candidate_hit_users | 2 |
| ranked_hit_users | 1 |
| hit_rate_at_k | 0.033333 |
| popular_only_hit_rate_at_k | 0.033333 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.033333 |
| hybrid_no_itemcf_hit_rate_at_k | 0.033333 |
| category_diversity_avg | 1.0 |

## Fallback and Source Coverage

- fallback_rate: 0.31
- recall_source_coverage: `{"category": 253, "itemcf_strong": 95, "itemcf_weak": 92, "popular": 4902}`
- topk_source_coverage: `{"category": 135, "itemcf_strong": 14, "itemcf_weak": 13, "popular": 491}`
- source_diagnostics: `{"users_with_positive_seeds": 90, "users_with_itemcf_seed_hits": 52, "users_with_itemcf_raw_candidates": 52, "itemcf_raw_candidates": 12754, "itemcf_raw_unseen_candidates": 964}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.066667
- candidate_hit_users: 2
- ranked_hit_users: 1
- candidate_hit_source_coverage: `{"category": 2, "popular": 2}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular

### User AE3Q6AEWP7Y7CH4N6IWEP4YBNP2A

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular

### User AE4KVNO5P6N6SP6CQTZTIDHEAWFQ

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular
