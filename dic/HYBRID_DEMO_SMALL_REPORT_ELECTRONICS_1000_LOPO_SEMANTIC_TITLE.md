# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics_1000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics_1000",
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
  ],
  "lopo_input_users": 165,
  "lopo_eligible_users": 81,
  "lopo_skipped_users_fewer_than_2_positives": 84
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | leave_one_positive_out |
| users_total | 81 |
| users_with_holdout | 81 |
| users_evaluated | 81 |
| lopo_input_users | 165 |
| lopo_eligible_users | 81 |
| lopo_skipped_users_fewer_than_2_positives | 84 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 49.975309 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.962963 |
| candidate_hit_users | 78 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 25.128205 |
| candidate_hit_rank_p50 | 34.0 |
| candidate_hit_missed_topk_users | 6 |
| ranked_hit_users | 72 |
| hit_rate_at_k | 0.888889 |
| popular_only_hit_rate_at_k | 0.074074 |
| itemcf_only_hit_rate_at_k | 0.938272 |
| hybrid_hit_rate_at_k | 0.888889 |
| hybrid_no_itemcf_hit_rate_at_k | 0.049383 |
| category_diversity_avg | 1.666667 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 537, "itemcf_strong": 172, "itemcf_weak": 175, "popular": 2193, "semantic": 1770}`
- topk_source_coverage: `{"category": 79, "itemcf_strong": 77, "itemcf_weak": 79, "popular": 121, "semantic": 245}`
- source_diagnostics: `{"users_with_positive_seeds": 81, "users_with_itemcf_seed_hits": 81, "users_with_itemcf_raw_candidates": 81, "itemcf_raw_candidates": 16588, "itemcf_raw_unseen_candidates": 1674}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.962963
- candidate_hit_users: 78
- ranked_hit_users: 72
- candidate_hit_missed_topk_users: 6
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 25.128205
- candidate_hit_rank_p50: 34.0
- candidate_hit_source_coverage: `{"category": 5, "itemcf_strong": 72, "itemcf_weak": 77, "popular": 12, "semantic": 4}`

## Ranking Case Summary

- total_hit_cases: 78
- topk_hit_cases: 25
- missed_topk_cases: 53
- semantic_only_items_above_share: 0.667579
- top1_score_gap_avg: 24.742213
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 3, "itemcf_strong+itemcf_weak": 40, "itemcf_strong+itemcf_weak+popular": 5, "itemcf_weak": 5}`
- items_above_source_combinations: `{"semantic": 1219, "category+semantic": 277, "popular": 190, "category+popular": 68, "category+popular+semantic": 30, "popular+semantic": 28, "itemcf_strong+itemcf_weak": 5, "itemcf_strong+itemcf_weak+semantic": 3, "itemcf_strong+itemcf_weak+popular": 3, "category+itemcf_strong+itemcf_weak+semantic": 2, "category+itemcf_strong+semantic": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 81 of 165 input users; 84 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_7_title_semantic_demo
- risk_flags: none
- items:
  - B08JQCJZQM score=27.6 sources=semantic
  - B08HFNNPPJ score=26.0 sources=itemcf_weak,itemcf_strong,category,semantic
  - B0BLCBK97H score=25.2 sources=semantic
  - B071K5BQPF score=24.0 sources=semantic
  - B09NHSGWPD score=24.0 sources=semantic

### User AE7Y5RLYIKHOZB5NKKOEKYG2SPSQ

- strategy: phase_1_7_title_semantic_demo
- risk_flags: none
- items:
  - B092F8GG57 score=32.3 sources=category,semantic
  - B0C5MCSLKZ score=30.0 sources=semantic
  - B08BWN7F7Q score=29.9 sources=category,semantic
  - B09V28P31X score=28.8 sources=semantic
  - B08F1P3BCC score=2.0 sources=itemcf_weak

### User AEAUZK2OLWXD75AWJOCCGGCL3H2A

- strategy: phase_1_7_title_semantic_demo
- risk_flags: none
- items:
  - B00E3W15P0 score=19.2 sources=semantic
  - B088DJQ2PQ score=16.8 sources=semantic
  - B08XBLP2V8 score=16.8 sources=semantic
  - B09FN58JBR score=16.8 sources=semantic
  - B0C8HDXFXN score=4.5 sources=itemcf_weak,itemcf_strong
