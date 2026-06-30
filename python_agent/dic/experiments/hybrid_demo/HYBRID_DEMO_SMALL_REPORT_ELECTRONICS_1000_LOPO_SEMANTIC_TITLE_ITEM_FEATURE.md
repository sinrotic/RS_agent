# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_smoke_e2e_electronics_1000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_smoke_e2e_electronics_1000",
  "evaluation_mode": "leave_one_positive_out",
  "top_k": 5,
  "candidate_pool_size": 50,
  "limit_users": 1,
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
  "item_feature_rerank": {
    "enabled": true,
    "weights": {
      "multi_source": 1.0,
      "feedback_category_match": 1.0,
      "feedback_source_match": 1.0,
      "feedback_keyword_match_count": 1.0,
      "feedback_disliked_keyword_match_count": -2.0,
      "popular_only": -0.5,
      "semantic_only": -0.5
    }
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
  "lopo_input_users": 1,
  "lopo_eligible_users": 1,
  "lopo_skipped_users_fewer_than_2_positives": 0
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | leave_one_positive_out |
| users_total | 1 |
| users_with_holdout | 1 |
| users_evaluated | 1 |
| lopo_input_users | 1 |
| lopo_eligible_users | 1 |
| lopo_skipped_users_fewer_than_2_positives | 0 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 50.0 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 1.0 |
| candidate_hit_users | 1 |
| candidate_hit_rank_min | 2 |
| candidate_hit_rank_avg | 2.0 |
| candidate_hit_rank_p50 | 2.0 |
| candidate_hit_missed_topk_users | 0 |
| ranked_hit_users | 1 |
| hit_rate_at_k | 1.0 |
| popular_only_hit_rate_at_k | 0.0 |
| itemcf_only_hit_rate_at_k | 1.0 |
| hybrid_hit_rate_at_k | 1.0 |
| hybrid_no_itemcf_hit_rate_at_k | 0.0 |
| category_diversity_avg | 2.0 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 23, "semantic": 30}`
- topk_source_coverage: `{"category": 2, "itemcf_strong": 1, "itemcf_weak": 1, "semantic": 5}`
- source_diagnostics: `{"users_with_positive_seeds": 1, "users_with_itemcf_seed_hits": 1, "users_with_itemcf_raw_candidates": 1, "itemcf_raw_candidates": 18, "itemcf_raw_unseen_candidates": 6}`

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 1.0
- candidate_hit_users: 1
- ranked_hit_users: 1
- candidate_hit_missed_topk_users: 0
- candidate_hit_rank_min: 2
- candidate_hit_rank_avg: 2.0
- candidate_hit_rank_p50: 2.0
- candidate_hit_source_coverage: `{"category": 1, "itemcf_strong": 1, "itemcf_weak": 1, "semantic": 1}`

## Ranking Case Summary

- total_hit_cases: 1
- topk_hit_cases: 1
- missed_topk_cases: 0
- semantic_only_items_above_share: 0.0
- top1_score_gap_avg: 0.0
- target_source_combinations: `{}`
- items_above_source_combinations: `{}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1 of 1 input users; 0 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE2TA5GQH4JI5RQ4W5H5PQOVYBGA

- strategy: phase_1_8_item_feature_rerank_demo
- risk_flags: none
- items:
  - B08JQCJZQM score=27.1 sources=semantic
  - B08HFNNPPJ score=27.0 sources=itemcf_weak,itemcf_strong,category,semantic
  - B08Y1XYLVP score=24.9 sources=category,semantic
  - B0BLCBK97H score=24.7 sources=semantic
  - B071K5BQPF score=23.5 sources=semantic
