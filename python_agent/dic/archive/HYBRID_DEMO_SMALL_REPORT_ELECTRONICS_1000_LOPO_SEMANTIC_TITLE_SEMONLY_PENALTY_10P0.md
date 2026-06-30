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
  "rerank_policy": {
    "enabled": true,
    "semantic_only_penalty": 10.0
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
  "semantic_score_mode": "raw",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ],
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
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 19.978261 |
| candidate_hit_rank_p50 | 18.0 |
| candidate_hit_missed_topk_users | 3 |
| ranked_hit_users | 43 |
| hit_rate_at_k | 0.877551 |
| popular_only_hit_rate_at_k | 0.081633 |
| itemcf_only_hit_rate_at_k | 0.918367 |
| hybrid_hit_rate_at_k | 0.877551 |
| hybrid_no_itemcf_hit_rate_at_k | 0.061224 |
| category_diversity_avg | 1.673469 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 296, "itemcf_strong": 83, "itemcf_weak": 84, "popular": 1369, "semantic": 1050}`
- topk_source_coverage: `{"category": 93, "itemcf_strong": 46, "itemcf_weak": 47, "popular": 83, "semantic": 141}`
- source_diagnostics: `{"users_with_positive_seeds": 49, "users_with_itemcf_seed_hits": 49, "users_with_itemcf_raw_candidates": 49, "itemcf_raw_candidates": 12016, "itemcf_raw_unseen_candidates": 1196}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.938776
- candidate_hit_users: 46
- ranked_hit_users: 43
- candidate_hit_missed_topk_users: 3
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 19.978261
- candidate_hit_rank_p50: 18.0
- candidate_hit_source_coverage: `{"category": 2, "itemcf_strong": 43, "itemcf_weak": 46, "popular": 7, "semantic": 2}`

## Ranking Case Summary

- total_hit_cases: 46
- topk_hit_cases: 15
- missed_topk_cases: 31
- semantic_only_items_above_share: 0.591449
- top1_score_gap_avg: 18.86238
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 1, "itemcf_strong+itemcf_weak": 24, "itemcf_strong+itemcf_weak+popular": 3, "itemcf_weak": 3}`
- items_above_source_combinations: `{"semantic": 498, "category+semantic": 144, "popular": 119, "category+popular": 35, "category+popular+semantic": 20, "popular+semantic": 18, "itemcf_strong+itemcf_weak": 5, "itemcf_strong+itemcf_weak+popular": 2, "itemcf_strong+itemcf_weak+semantic": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 49 of 100 input users; 51 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_7d_title_semantic_only_penalty_10p0
- risk_flags: none
- items:
  - B08HFNNPPJ score=26.0 sources=itemcf_weak,itemcf_strong,category,semantic
  - B08Y1XYLVP score=23.9 sources=category,semantic
  - B08JQCJZQM score=17.6 sources=semantic
  - B0BLCBK97H score=15.2 sources=semantic
  - B07N1H8CGW score=14.3 sources=category,semantic

### User AE7Y5RLYIKHOZB5NKKOEKYG2SPSQ

- strategy: phase_1_7d_title_semantic_only_penalty_10p0
- risk_flags: none
- items:
  - B092F8GG57 score=32.3 sources=category,semantic
  - B08BWN7F7Q score=29.9 sources=category,semantic
  - B08RYY7YB6 score=28.7 sources=category,semantic
  - B01LXFFO8O score=26.3 sources=category,semantic
  - B08F1P3BCC score=2.0 sources=itemcf_weak

### User AEAUZK2OLWXD75AWJOCCGGCL3H2A

- strategy: phase_1_7d_title_semantic_only_penalty_10p0
- risk_flags: none
- items:
  - B00E3W15P0 score=9.2 sources=semantic
  - B01K8B8YA8 score=7.538137 sources=popular
  - B088DJQ2PQ score=6.8 sources=semantic
  - B08XBLP2V8 score=6.8 sources=semantic
  - B0C8HDXFXN score=4.5 sources=itemcf_weak,itemcf_strong
