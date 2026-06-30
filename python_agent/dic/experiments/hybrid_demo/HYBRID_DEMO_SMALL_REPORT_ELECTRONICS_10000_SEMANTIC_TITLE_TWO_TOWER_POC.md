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
    "two_tower": 1.2,
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
    "semantic": 20,
    "two_tower": 10
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
  "two_tower_enabled": true,
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": 30,
  "two_tower_seed_window": 10,
  "two_tower_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ],
  "two_tower_min_overlap": 1,
  "two_tower_recency_decay": 0.85
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
| fallback_rate | 0.088889 |
| candidate_hit_rate_at_pool | 0.086957 |
| candidate_hit_users | 62 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 15.774194 |
| candidate_hit_rank_p50 | 11.0 |
| candidate_hit_rank_p90 | 37.0 |
| candidate_hit_missed_topk_users | 46 |
| ranked_hit_users | 16 |
| recall_at_k | 0.006099 |
| recall_at_pool | 0.035813 |
| ndcg_at_k | 0.006288 |
| mrr_at_k | 0.011547 |
| map_at_k | 0.003446 |
| hit_rate_at_k | 0.02244 |
| popular_only_hit_rate_at_k | 0.008415 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.02244 |
| hybrid_no_itemcf_hit_rate_at_k | 0.02244 |
| category_diversity_avg | 2.430769 |

## Fallback and Source Coverage

- fallback_rate: 0.088889
- recall_source_coverage: `{"category": 13251, "itemcf_strong": 14219, "itemcf_weak": 15064, "popular": 37885, "semantic": 59814, "two_tower": 30527}`
- topk_source_coverage: `{"category": 2633, "itemcf_strong": 971, "itemcf_weak": 991, "popular": 8170, "semantic": 3007, "two_tower": 2232}`
- per_source_candidate_contribution: `{"category": 8, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 11, "semantic": 70, "two_tower": 41}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "semantic": 13, "two_tower": 6}`
- source_overlap: `{"single_source_candidate_count": 65252, "multi_source_candidate_count": 51736, "multi_source_candidate_rate": 0.442233, "source_pair_counts": {"category+itemcf_strong": 197, "category+itemcf_weak": 204, "category+popular": 12160, "category+semantic": 1081, "category+two_tower": 1287, "itemcf_strong+itemcf_weak": 13036, "itemcf_strong+popular": 222, "itemcf_strong+semantic": 111, "itemcf_strong+two_tower": 158, "itemcf_weak+popular": 232, "itemcf_weak+semantic": 111, "itemcf_weak+two_tower": 173, "popular+semantic": 435, "popular+two_tower": 775, "semantic+two_tower": 26067}}`
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
    "candidate_hit_rate_at_pool": 0.086957,
    "hit_rate_at_k": 0.02244,
    "ndcg_at_k": 0.006288,
    "mrr_at_k": 0.011547,
    "candidate_hit_users": 62,
    "candidate_hit_missed_topk_users": 46,
    "candidate_hit_rank_p50": 11.0,
    "candidate_hit_rank_p90": 37.0,
    "fallback_rate": 0.088889,
    "multi_source_candidate_rate": 0.442233,
    "ranking_p95_seconds": 0.000436
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.812542,
  "candidate_generation_p95_seconds": 1.308537,
  "ranking_avg_seconds": 0.000312,
  "ranking_p95_seconds": 0.000436,
  "recommendation_avg_seconds": 0.812877,
  "recommendation_p95_seconds": 1.30891,
  "total_run_seconds": 1906.13907
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.086957
- candidate_hit_users: 62
- ranked_hit_users: 16
- candidate_hit_missed_topk_users: 46
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 15.774194
- candidate_hit_rank_p50: 11.0
- candidate_hit_rank_p90: 37.0
- candidate_hit_source_coverage: `{"category": 8, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 11, "semantic": 70, "two_tower": 41}`

## Ranking Case Summary

- total_hit_cases: 89
- topk_hit_cases: 17
- missed_topk_cases: 72
- semantic_only_items_above_share: 0.478997
- top1_score_gap_avg: 21.883497
- target_source_combinations: `{"category+popular": 5, "itemcf_strong+itemcf_weak": 1, "popular": 2, "semantic": 29, "semantic+two_tower": 28, "two_tower": 7}`
- items_above_source_combinations: `{"semantic": 707, "semantic+two_tower": 365, "popular": 144, "category+popular": 117, "itemcf_strong+itemcf_weak": 63, "two_tower": 21, "itemcf_weak": 18, "category+semantic+two_tower": 8, "category+semantic": 7, "category+popular+two_tower": 6, "category+popular+semantic": 5, "category+popular+semantic+two_tower": 4, "itemcf_strong+itemcf_weak+semantic+two_tower": 3, "category+itemcf_strong+itemcf_weak+popular+semantic+two_tower": 2, "itemcf_strong": 1, "category+itemcf_strong+itemcf_weak+popular": 1, "itemcf_weak+semantic+two_tower": 1, "category+itemcf_weak": 1, "itemcf_strong+itemcf_weak+popular": 1, "category+itemcf_strong+semantic+two_tower": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_11_two_tower_poc_10000_valid_test
- risk_flags: none
- items:
  - B071VDV7NC score=55.547077 sources=category,semantic,two_tower,popular
  - B07MZ6PJW8 score=54.583787 sources=semantic,two_tower
  - B07TJ87YKB score=53.47999 sources=semantic,two_tower
  - B07VVJNG7P score=52.20758 sources=semantic,two_tower
  - B005TUQV0E score=3.181982 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_11_two_tower_poc_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B013EKI2DY score=36.361753 sources=semantic,two_tower,popular
  - B0B23LRBRP score=34.018604 sources=semantic,two_tower
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_11_two_tower_poc_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=3.181982 sources=itemcf_weak,itemcf_strong
