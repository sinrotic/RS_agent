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
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  },
  "rerank_policy": {},
  "source_aware_fusion": {},
  "item_feature_rerank": {},
  "ltr_model": {},
  "topk_source_minimums": {
    "itemcf": 1
  },
  "candidate_source_minimums": {},
  "semantic_enabled": false,
  "semantic_per_user": null,
  "semantic_min_overlap": null,
  "semantic_score_mode": "raw",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": null,
  "two_tower_enabled": false,
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": null,
  "two_tower_seed_window": null,
  "two_tower_text_fields": null,
  "two_tower_min_overlap": null,
  "two_tower_recency_decay": null
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
| candidate_count_avg | 49.994872 |
| fallback_rate | 0.091453 |
| candidate_hit_rate_at_pool | 0.032258 |
| candidate_hit_users | 23 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 15.130435 |
| candidate_hit_rank_p50 | 7.0 |
| candidate_hit_rank_p90 | 34.0 |
| candidate_hit_missed_topk_users | 18 |
| ranked_hit_users | 5 |
| recall_at_k | 0.001163 |
| recall_at_pool | 0.010322 |
| ndcg_at_k | 0.00168 |
| mrr_at_k | 0.003904 |
| map_at_k | 0.000836 |
| hit_rate_at_k | 0.007013 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.007013 |
| hybrid_no_itemcf_hit_rate_at_k | 0.007013 |
| category_diversity_avg | 1.924786 |

## Fallback and Source Coverage

- fallback_rate: 0.091453
- recall_source_coverage: `{"category": 31630, "itemcf_strong": 245, "itemcf_weak": 249, "popular": 116499}`
- topk_source_coverage: `{"category": 2708, "itemcf_strong": 172, "itemcf_weak": 174, "popular": 11682}`
- per_source_candidate_contribution: `{"category": 15, "popular": 24}`
- per_source_topk_contribution: `{"category": 4, "popular": 5}`
- source_overlap: `{"single_source_candidate_count": 85711, "multi_source_candidate_count": 31277, "multi_source_candidate_rate": 0.267352, "source_pair_counts": {"category+itemcf_strong": 141, "category+itemcf_weak": 146, "category+popular": 31146, "itemcf_strong+itemcf_weak": 217, "itemcf_strong+popular": 222, "itemcf_weak+popular": 232}}`
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
    "candidate_hit_rate_at_pool": 0.032258,
    "hit_rate_at_k": 0.007013,
    "ndcg_at_k": 0.00168,
    "mrr_at_k": 0.003904,
    "candidate_hit_users": 23,
    "candidate_hit_missed_topk_users": 18,
    "candidate_hit_rank_p50": 7.0,
    "candidate_hit_rank_p90": 34.0,
    "fallback_rate": 0.091453,
    "multi_source_candidate_rate": 0.267352,
    "ranking_p95_seconds": 0.000345
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.00047,
  "candidate_generation_p95_seconds": 0.000637,
  "ranking_avg_seconds": 0.000229,
  "ranking_p95_seconds": 0.000345,
  "recommendation_avg_seconds": 0.000709,
  "recommendation_p95_seconds": 0.000926,
  "total_run_seconds": 4.524739
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.032258
- candidate_hit_users: 23
- ranked_hit_users: 5
- candidate_hit_missed_topk_users: 18
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 15.130435
- candidate_hit_rank_p50: 7.0
- candidate_hit_rank_p90: 34.0
- candidate_hit_source_coverage: `{"category": 15, "popular": 24}`

## Ranking Case Summary

- total_hit_cases: 24
- topk_hit_cases: 5
- missed_topk_cases: 19
- semantic_only_items_above_share: 0.0
- top1_score_gap_avg: 37.101303
- target_source_combinations: `{"category+popular": 11, "popular": 8}`
- items_above_source_combinations: `{"category+popular": 204, "popular": 140, "category+itemcf_strong+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_5_deterministic_hybrid_demo_10000
- risk_flags: none
- items:
  - B087S2JRXY score=51.542975 sources=category,popular
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_5_deterministic_hybrid_demo_10000
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B087S2JRXY score=34.742975 sources=popular

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_5_deterministic_hybrid_demo_10000
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B087S2JRXY score=34.742975 sources=popular
