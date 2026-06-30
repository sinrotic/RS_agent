# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_10000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_10000",
  "evaluation_mode": "valid_test",
  "top_k": 5,
  "candidate_pool_size": 100,
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
  "source_aware_fusion": {
    "enabled": false
  },
  "item_feature_rerank": {
    "enabled": false
  },
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
  "two_tower_variant": "youtube_dnn",
  "two_tower_artifact_path": "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json",
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": 30,
  "two_tower_seed_window": 50,
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
| candidate_count_avg | 81.886325 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.096774 |
| candidate_hit_users | 69 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 22.304348 |
| candidate_hit_rank_p50 | 16.0 |
| candidate_hit_rank_p90 | 49.0 |
| candidate_hit_missed_topk_users | 51 |
| ranked_hit_users | 18 |
| recall_at_k | 0.009343 |
| recall_at_pool | 0.037477 |
| ndcg_at_k | 0.00894 |
| mrr_at_k | 0.016877 |
| map_at_k | 0.005446 |
| hit_rate_at_k | 0.025245 |
| popular_only_hit_rate_at_k | 0.0 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.025245 |
| hybrid_no_itemcf_hit_rate_at_k | 0.026648 |
| category_diversity_avg | 1.72906 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 65274, "itemcf_strong": 15430, "itemcf_weak": 16405, "semantic": 63960, "two_tower": 60160}`
- topk_source_coverage: `{"category": 864, "itemcf_strong": 990, "itemcf_weak": 1018, "semantic": 9528, "two_tower": 4159}`
- per_source_candidate_contribution: `{"category": 13, "itemcf_strong": 1, "itemcf_weak": 1, "semantic": 73, "two_tower": 13}`
- per_source_topk_contribution: `{"semantic": 17, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 162797, "multi_source_candidate_count": 28817, "multi_source_candidate_rate": 0.150391, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+semantic": 899, "category+two_tower": 2173, "itemcf_strong+itemcf_weak": 14036, "itemcf_strong+semantic": 117, "itemcf_strong+two_tower": 326, "itemcf_weak+semantic": 118, "itemcf_weak+two_tower": 327, "semantic+two_tower": 12230}}`
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
    "candidate_pool_size": 100,
    "candidate_hit_rate_at_pool": 0.096774,
    "hit_rate_at_k": 0.025245,
    "ndcg_at_k": 0.00894,
    "mrr_at_k": 0.016877,
    "candidate_hit_users": 69,
    "candidate_hit_missed_topk_users": 51,
    "candidate_hit_rank_p50": 16.0,
    "candidate_hit_rank_p90": 49.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.150391,
    "ranking_p95_seconds": 0.000716,
    "candidate_generation_p95_seconds": 0.503614
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.198851,
  "candidate_generation_p95_seconds": 0.503614,
  "ranking_avg_seconds": 0.000509,
  "ranking_p95_seconds": 0.000716,
  "recommendation_avg_seconds": 0.199386,
  "recommendation_p95_seconds": 0.504324,
  "total_run_seconds": 470.842626
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.096774
- candidate_hit_users: 69
- ranked_hit_users: 18
- candidate_hit_missed_topk_users: 51
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 22.304348
- candidate_hit_rank_p50: 16.0
- candidate_hit_rank_p90: 49.0
- candidate_hit_source_coverage: `{"category": 13, "itemcf_strong": 1, "itemcf_weak": 1, "semantic": 73, "two_tower": 13}`

## Ranking Case Summary

- total_hit_cases: 95
- topk_hit_cases: 21
- missed_topk_cases: 74
- semantic_only_items_above_share: 0.678265
- top1_score_gap_avg: 14.763795
- target_source_combinations: `{"category": 12, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 1, "semantic": 49, "semantic+two_tower": 4, "two_tower": 7}`
- items_above_source_combinations: `{"semantic": 1345, "category": 365, "semantic+two_tower": 109, "two_tower": 61, "itemcf_strong+itemcf_weak": 58, "category+semantic": 15, "itemcf_weak": 11, "category+two_tower": 8, "itemcf_strong": 5, "itemcf_strong+itemcf_weak+semantic": 3, "category+itemcf_strong+itemcf_weak": 1, "itemcf_strong+semantic": 1, "category+itemcf_strong": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_ablation_no_popular
- risk_flags: none
- items:
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B07VVJNG7P score=51.6 sources=semantic
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_ablation_no_popular
- risk_flags: none
- items:
  - B0B23LRBRP score=33.6 sources=semantic
  - B00P28VN38 score=33.210233 sources=semantic,two_tower
  - B089LMWJJB score=32.4 sources=semantic
  - B09KXJBNGN score=32.4 sources=semantic
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_ablation_no_popular
- risk_flags: none
- items:
  - B07W3Q9X9B score=35.633072 sources=semantic,two_tower
  - B0B8SDY8F6 score=35.595574 sources=semantic,two_tower
  - B0B42DKNL2 score=35.572808 sources=semantic,two_tower
  - B09HZWP8V4 score=34.36784 sources=semantic,two_tower
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
