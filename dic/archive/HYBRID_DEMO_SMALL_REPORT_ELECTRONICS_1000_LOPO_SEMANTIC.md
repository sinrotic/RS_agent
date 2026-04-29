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
    "semantic": 1.2,
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
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
  "semantic_min_overlap": 2,
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
| candidate_hit_rate_at_pool | 0.938776 |
| candidate_hit_users | 46 |
| candidate_hit_rank_min | 2 |
| candidate_hit_rank_avg | 25.543478 |
| candidate_hit_rank_p50 | 34.0 |
| candidate_hit_missed_topk_users | 2 |
| ranked_hit_users | 44 |
| hit_rate_at_k | 0.897959 |
| popular_only_hit_rate_at_k | 0.081633 |
| itemcf_only_hit_rate_at_k | 0.918367 |
| hybrid_hit_rate_at_k | 0.897959 |
| hybrid_no_itemcf_hit_rate_at_k | 0.020408 |
| category_diversity_avg | 2.265306 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 178, "itemcf_strong": 83, "itemcf_weak": 84, "popular": 1440, "semantic": 1050}`
- topk_source_coverage: `{"category": 8, "itemcf_strong": 46, "itemcf_weak": 47, "popular": 89, "semantic": 144}`
- source_diagnostics: `{"users_with_positive_seeds": 49, "users_with_itemcf_seed_hits": 49, "users_with_itemcf_raw_candidates": 49, "itemcf_raw_candidates": 12016, "itemcf_raw_unseen_candidates": 1196}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.938776
- candidate_hit_users: 46
- ranked_hit_users: 44
- candidate_hit_missed_topk_users: 2
- candidate_hit_rank_min: 2
- candidate_hit_rank_avg: 25.543478
- candidate_hit_rank_p50: 34.0
- candidate_hit_source_coverage: `{"category": 2, "itemcf_strong": 43, "itemcf_weak": 46, "popular": 7, "semantic": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 49 of 100 input users; 51 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_6_deterministic_semantic_recall_demo
- risk_flags: none
- items:
  - B0020HRE1Y score=67.359368 sources=semantic,popular
  - B001Q9F0BS score=59.937461 sources=semantic,popular
  - B004WMSV76 score=57.6 sources=semantic
  - B09NHSGWPD score=56.4 sources=semantic
  - B08HFNNPPJ score=5.6 sources=itemcf_weak,itemcf_strong,category

### User AE7Y5RLYIKHOZB5NKKOEKYG2SPSQ

- strategy: phase_1_6_deterministic_semantic_recall_demo
- risk_flags: none
- items:
  - B0020HRE1Y score=122.559368 sources=semantic,popular
  - B0032AN4N0 score=117.6 sources=semantic
  - B00XI3MMMA score=117.6 sources=semantic
  - B003UT2C4U score=116.4 sources=semantic
  - B08F1P3BCC score=2.0 sources=itemcf_weak

### User AEAUZK2OLWXD75AWJOCCGGCL3H2A

- strategy: phase_1_6_deterministic_semantic_recall_demo
- risk_flags: none
- items:
  - B00E3W15P0 score=57.6 sources=semantic
  - B0020HRE1Y score=40.959368 sources=semantic,popular
  - B00XI3MMMA score=40.8 sources=semantic
  - B09LYWCHJX score=37.2 sources=semantic
  - B0C8HDXFXN score=4.5 sources=itemcf_weak,itemcf_strong
