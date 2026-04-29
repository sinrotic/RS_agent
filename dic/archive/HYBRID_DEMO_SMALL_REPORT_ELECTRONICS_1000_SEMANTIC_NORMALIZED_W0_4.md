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
    "semantic": 0.4,
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
  "semantic_min_overlap": 2,
  "semantic_score_mode": "normalized",
  "semantic_category_weight": 2.0
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
| candidate_hit_rank_min | 7 |
| candidate_hit_rank_avg | 13.666667 |
| candidate_hit_rank_p50 | 10.5 |
| candidate_hit_missed_topk_users | 6 |
| ranked_hit_users | 0 |
| hit_rate_at_k | 0.0 |
| popular_only_hit_rate_at_k | 0.033333 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.0 |
| hybrid_no_itemcf_hit_rate_at_k | 0.0 |
| category_diversity_avg | 1.78 |

## Fallback and Source Coverage

- fallback_rate: 0.31
- recall_source_coverage: `{"category": 512, "itemcf_strong": 131, "itemcf_weak": 135, "popular": 2944, "semantic": 2010}`
- topk_source_coverage: `{"category": 122, "itemcf_strong": 15, "itemcf_weak": 15, "popular": 238, "semantic": 310}`
- source_diagnostics: `{"users_with_positive_seeds": 90, "users_with_itemcf_seed_hits": 52, "users_with_itemcf_raw_candidates": 52, "itemcf_raw_candidates": 12754, "itemcf_raw_unseen_candidates": 964}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.2
- candidate_hit_users: 6
- ranked_hit_users: 0
- candidate_hit_missed_topk_users: 6
- candidate_hit_rank_min: 7
- candidate_hit_rank_avg: 13.666667
- candidate_hit_rank_p50: 10.5
- candidate_hit_source_coverage: `{"category": 3, "popular": 2, "semantic": 8}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_7_normalized_semantic_demo
- risk_flags: none
- items:
  - B0BLCBK97H score=11.272727 sources=semantic
  - B089T4YVYD score=11.049808 sources=semantic
  - B071K5BQPF score=10.825397 sources=semantic
  - B08Y1XYLVP score=10.409734 sources=category,semantic
  - B08JQCJZQM score=9.151515 sources=semantic

### User AE3Q6AEWP7Y7CH4N6IWEP4YBNP2A

- strategy: phase_1_7_normalized_semantic_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular

### User AE4KVNO5P6N6SP6CQTZTIDHEAWFQ

- strategy: phase_1_7_normalized_semantic_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular
