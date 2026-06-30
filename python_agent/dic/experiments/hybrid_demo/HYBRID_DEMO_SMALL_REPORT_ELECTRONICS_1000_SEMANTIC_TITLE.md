# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics_1000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics_1000",
  "evaluation_mode": "valid_test",
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
  "semantic_score_mode": "raw",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ]
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | valid_test |
| users_total | 165 |
| users_with_holdout | 46 |
| users_evaluated | 46 |
| lopo_input_users | None |
| lopo_eligible_users | None |
| lopo_skipped_users_fewer_than_2_positives | None |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 49.993939 |
| fallback_rate | 0.315152 |
| candidate_hit_rate_at_pool | 0.152174 |
| candidate_hit_users | 7 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 12.285714 |
| candidate_hit_rank_p50 | 12.0 |
| candidate_hit_missed_topk_users | 5 |
| ranked_hit_users | 2 |
| hit_rate_at_k | 0.043478 |
| popular_only_hit_rate_at_k | 0.021739 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.043478 |
| hybrid_no_itemcf_hit_rate_at_k | 0.043478 |
| category_diversity_avg | 1.581818 |

## Fallback and Source Coverage

- fallback_rate: 0.315152
- recall_source_coverage: `{"category": 1013, "itemcf_strong": 228, "itemcf_weak": 232, "popular": 4862, "semantic": 3330}`
- topk_source_coverage: `{"category": 192, "itemcf_strong": 24, "itemcf_weak": 24, "popular": 352, "semantic": 535}`
- source_diagnostics: `{"users_with_positive_seeds": 151, "users_with_itemcf_seed_hits": 84, "users_with_itemcf_raw_candidates": 84, "itemcf_raw_candidates": 17845, "itemcf_raw_unseen_candidates": 1351}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.152174
- candidate_hit_users: 7
- ranked_hit_users: 2
- candidate_hit_missed_topk_users: 5
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 12.285714
- candidate_hit_rank_p50: 12.0
- candidate_hit_source_coverage: `{"category": 3, "popular": 2, "semantic": 9}`

## Ranking Case Summary

- total_hit_cases: 11
- topk_hit_cases: 2
- missed_topk_cases: 9
- semantic_only_items_above_share: 0.711864
- top1_score_gap_avg: 12.144742
- target_source_combinations: `{"category+popular": 2, "category+semantic": 1, "semantic": 6}`
- items_above_source_combinations: `{"semantic": 126, "category+semantic": 44, "category+popular": 6, "category+itemcf_strong+itemcf_weak": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_7_title_semantic_demo
- risk_flags: none
- items:
  - B0BLCBK97H score=30.0 sources=semantic
  - B08JQCJZQM score=28.8 sources=semantic
  - B0B2JJV92T score=27.6 sources=semantic
  - B071K5BQPF score=26.4 sources=semantic
  - B09NHSGWPD score=24.0 sources=semantic

### User AE3Q6AEWP7Y7CH4N6IWEP4YBNP2A

- strategy: phase_1_7_title_semantic_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular

### User AE4KVNO5P6N6SP6CQTZTIDHEAWFQ

- strategy: phase_1_7_title_semantic_demo
- risk_flags: popular_fallback_used
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular
  - B08XNCHTCY score=3.576019 sources=popular
