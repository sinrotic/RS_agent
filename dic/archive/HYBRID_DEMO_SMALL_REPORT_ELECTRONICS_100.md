# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics_100",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics_100",
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
| users_total | 20 |
| users_with_holdout | 6 |
| users_evaluated | 6 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 49.45 |
| fallback_rate | 0.35 |
| hit_rate_at_k | 0.0 |
| popular_only_hit_rate_at_k | 0.0 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.0 |
| hybrid_no_itemcf_hit_rate_at_k | 0.0 |
| category_diversity_avg | 1.0 |

## Fallback and Source Coverage

- fallback_rate: 0.35
- recall_source_coverage: `{"category": 105, "popular": 952}`
- source_diagnostics: `{"users_with_positive_seeds": 18, "users_with_itemcf_seed_hits": 10, "users_with_itemcf_raw_candidates": 10, "itemcf_raw_candidates": 960, "itemcf_raw_unseen_candidates": 0}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AEAUZK2OLWXD75AWJOCCGGCL3H2A

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B07BRHB8C1 score=2.586907 sources=category,popular
  - B07FCZY1ZB score=2.568365 sources=category,popular
  - B01KWY71BO score=2.562165 sources=category,popular
  - B00V3KLZSW score=2.227771 sources=category,popular
  - B00X5C22SS score=2.226002 sources=category,popular

### User AEFKF6R2GUSK2AWPSWRR4ZO36JVQ

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B07BRHB8C1 score=2.586907 sources=category,popular
  - B07FCZY1ZB score=2.568365 sources=category,popular
  - B00V3KLZSW score=2.227771 sources=category,popular
  - B00X5C22SS score=2.226002 sources=category,popular
  - B07BJ8KD6X score=2.212899 sources=category,popular

### User AEM663T6XHZFWLODF4US2RCOCUSA

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B0199HAOAU score=1.795721 sources=popular
  - B002N3MM6W score=1.791606 sources=popular
  - B07BRHB8C1 score=1.786907 sources=popular
  - B0093162RM score=1.785947 sources=popular
  - B07547WSQQ score=1.782171 sources=popular
