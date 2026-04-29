# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics_1000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics_1000",
  "evaluation_mode": "leave_one_positive_out",
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
  },
  "lopo_input_users": 100,
  "lopo_eligible_users": 49,
  "lopo_skipped_users_fewer_than_2_positives": 51
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | leave_one_positive_out |
| users_total | 49 |
| users_with_holdout | 49 |
| users_evaluated | 49 |
| lopo_input_users | 100 |
| lopo_eligible_users | 49 |
| lopo_skipped_users_fewer_than_2_positives | 51 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 49.959184 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.877551 |
| candidate_hit_users | 43 |
| ranked_hit_users | 42 |
| hit_rate_at_k | 0.857143 |
| popular_only_hit_rate_at_k | 0.061224 |
| itemcf_only_hit_rate_at_k | 0.857143 |
| hybrid_hit_rate_at_k | 0.857143 |
| hybrid_no_itemcf_hit_rate_at_k | 0.040816 |
| category_diversity_avg | 1.0 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 144, "itemcf_strong": 83, "itemcf_weak": 79, "popular": 2372}`
- topk_source_coverage: `{"category": 61, "itemcf_strong": 47, "itemcf_weak": 46, "popular": 208}`
- source_diagnostics: `{"users_with_positive_seeds": 49, "users_with_itemcf_seed_hits": 49, "users_with_itemcf_raw_candidates": 49, "itemcf_raw_candidates": 12016, "itemcf_raw_unseen_candidates": 1196}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.877551
- candidate_hit_users: 43
- ranked_hit_users: 42
- candidate_hit_source_coverage: `{"category": 2, "itemcf_strong": 43, "itemcf_weak": 43, "popular": 7}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 49 of 100 input users; 51 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B08HFNNPPJ score=5.6 sources=itemcf_weak,itemcf_strong,category
  - B07KTYJ769 score=5.32948 sources=popular
  - B07456BG8N score=4.674856 sources=popular
  - B075X8471B score=4.358013 sources=popular

### User AE7Y5RLYIKHOZB5NKKOEKYG2SPSQ

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B08XNCHTCY score=5.176019 sources=category,popular
  - B00KC0HVTQ score=5.145465 sources=category,popular
  - B07456BG8N score=4.674856 sources=popular

### User AEAUZK2OLWXD75AWJOCCGGCL3H2A

- strategy: phase_1_5_deterministic_hybrid_demo
- risk_flags: none
- items:
  - B01K8B8YA8 score=7.538137 sources=popular
  - B07KTYJ769 score=5.32948 sources=popular
  - B08XNCHTCY score=5.176019 sources=category,popular
  - B00KC0HVTQ score=5.145465 sources=category,popular
  - B0C8HDXFXN score=4.5 sources=itemcf_weak,itemcf_strong
