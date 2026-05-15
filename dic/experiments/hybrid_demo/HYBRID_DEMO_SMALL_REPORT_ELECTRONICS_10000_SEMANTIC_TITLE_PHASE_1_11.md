# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_10000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_10000",
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
  "source_aware_fusion": {},
  "item_feature_rerank": {},
  "ltr_model": {
    "enabled": false
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
  "semantic_score_mode": "idf_seed_aware",
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
| users_total | 2340 |
| users_with_holdout | 713 |
| users_evaluated | 713 |
| lopo_input_users | None |
| lopo_eligible_users | None |
| lopo_skipped_users_fewer_than_2_positives | None |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 46.04359 |
| fallback_rate | 0.088889 |
| candidate_hit_rate_at_pool | 0.061711 |
| candidate_hit_users | 44 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 14.727273 |
| candidate_hit_rank_p50 | 11.5 |
| candidate_hit_rank_p90 | 30.0 |
| candidate_hit_missed_topk_users | 31 |
| ranked_hit_users | 13 |
| recall_at_k | 0.006462 |
| recall_at_pool | 0.024854 |
| ndcg_at_k | 0.006376 |
| mrr_at_k | 0.01087 |
| map_at_k | 0.004021 |
| hit_rate_at_k | 0.018233 |
| popular_only_hit_rate_at_k | 0.0 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.018233 |
| hybrid_no_itemcf_hit_rate_at_k | 0.018233 |
| category_diversity_avg | 1.608974 |

## Fallback and Source Coverage

- fallback_rate: 0.088889
- recall_source_coverage: `{"category": 29715, "itemcf_strong": 16473, "itemcf_weak": 17487, "popular": 8415, "semantic": 52403}`
- topk_source_coverage: `{"category": 1828, "itemcf_strong": 1008, "itemcf_weak": 1041, "popular": 4264, "semantic": 5564}`
- per_source_candidate_contribution: `{"category": 6, "itemcf_strong": 1, "itemcf_weak": 1, "semantic": 51}`
- per_source_topk_contribution: `{"category": 1, "semantic": 13}`
- source_overlap: `{"single_source_candidate_count": 91244, "multi_source_candidate_count": 16498, "multi_source_candidate_rate": 0.153125, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+popular": 575, "category+semantic": 793, "itemcf_strong+itemcf_weak": 15073, "itemcf_strong+popular": 3, "itemcf_strong+semantic": 143, "itemcf_weak+popular": 3, "itemcf_weak+semantic": 147, "popular+semantic": 4}}`
- source_diagnostics: `{"users_with_positive_seeds": 2132, "users_with_itemcf_seed_hits": 1530, "users_with_itemcf_raw_candidates": 1530, "itemcf_raw_candidates": 499363, "itemcf_raw_unseen_candidates": 201803}`

## Diagnostic Gate

```json
{
  "recall_bottleneck": true,
  "ranking_bottleneck": true,
  "source_merge_bottleneck": false,
  "latency_bottleneck": false,
  "architecture_escalation": false,
  "recommended_next_phase": "phase_1_11_recall_source_merge",
  "evidence": {
    "top_k": 5,
    "candidate_pool_size": 50,
    "candidate_hit_rate_at_pool": 0.061711,
    "hit_rate_at_k": 0.018233,
    "ndcg_at_k": 0.006376,
    "mrr_at_k": 0.01087,
    "candidate_hit_users": 44,
    "candidate_hit_missed_topk_users": 31,
    "candidate_hit_rank_p50": 11.5,
    "candidate_hit_rank_p90": 30.0,
    "fallback_rate": 0.088889,
    "multi_source_candidate_rate": 0.153125,
    "ranking_p95_seconds": 0.00036
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 1.343513,
  "candidate_generation_p95_seconds": 5.079586,
  "ranking_avg_seconds": 0.000253,
  "ranking_p95_seconds": 0.00036,
  "recommendation_avg_seconds": 1.34378,
  "recommendation_p95_seconds": 5.07992,
  "total_run_seconds": 3147.202248
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.061711
- candidate_hit_users: 44
- ranked_hit_users: 13
- candidate_hit_missed_topk_users: 31
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 14.727273
- candidate_hit_rank_p50: 11.5
- candidate_hit_rank_p90: 30.0
- candidate_hit_source_coverage: `{"category": 6, "itemcf_strong": 1, "itemcf_weak": 1, "semantic": 51}`

## Ranking Case Summary

- total_hit_cases: 58
- topk_hit_cases: 14
- missed_topk_cases: 44
- semantic_only_items_above_share: 0.873037
- top1_score_gap_avg: 6.457807
- target_source_combinations: `{"category": 5, "itemcf_strong+itemcf_weak": 1, "semantic": 38}`
- items_above_source_combinations: `{"semantic": 667, "category": 44, "popular": 23, "category+semantic": 14, "itemcf_strong+itemcf_weak": 7, "itemcf_strong+itemcf_weak+semantic": 3, "category+popular": 2, "category+itemcf_strong+itemcf_weak+semantic": 2, "category+itemcf_strong+itemcf_weak": 1, "itemcf_strong+semantic": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_11_recall_source_merge_demo_10000
- risk_flags: none
- items:
  - B07VVJNG7P score=25.52545 sources=semantic
  - B073XJBJLG score=25.493603 sources=semantic
  - B09BVJ854R score=25.471267 sources=semantic
  - B07MZ6PJW8 score=25.312718 sources=semantic
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_11_recall_source_merge_demo_10000
- risk_flags: none
- items:
  - B00XJPY07M score=19.182542 sources=semantic
  - B0B23LRBRP score=19.030957 sources=semantic
  - B09KXJBNGN score=18.990202 sources=semantic
  - B00P28VN38 score=18.828794 sources=semantic
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_11_recall_source_merge_demo_10000
- risk_flags: none
- items:
  - B00JK4SXY2 score=19.364627 sources=semantic
  - B07H9KRQHL score=19.364627 sources=semantic
  - B08TVR7CQJ score=19.364627 sources=semantic
  - B09BNFN58L score=19.364627 sources=semantic
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
