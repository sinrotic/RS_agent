# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics",
  "top_k": 5,
  "candidate_pool_size": 50,
  "limit_users": 20,
  "rank_weights": {
    "popular": 1.0,
    "itemcf_weak": 2.0,
    "itemcf_strong": 2.5,
    "category": 0.8,
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  }
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| users_total | 1 |
| users_with_holdout | 0 |
| users_evaluated | 1 |
| hit_rate_denominator | all_demo_users_placeholder |
| candidate_count_avg | 0.0 |
| fallback_rate | 1.0 |
| hit_rate_at_k | 0.0 |
| popular_only_hit_rate_at_k | 0.0 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.0 |
| hybrid_no_itemcf_hit_rate_at_k | 0.0 |
| category_diversity_avg | 0.0 |

## Fallback and Source Coverage

- fallback_rate: 1.0
- recall_source_coverage: `{}`

## Sample Limitations

- No held-out positive valid/test rows were available; hit-rate metrics are reported as 0.0 placeholders.

## Recommendation Examples

### User AFKZENTNBQ7A7V7UXW5JJI6UGRYQ

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: popular_fallback_used, empty_recommendation_list
- items:
