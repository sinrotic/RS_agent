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
| candidate_count_avg | 86.43547 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.093969 |
| candidate_hit_users | 67 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 21.283582 |
| candidate_hit_rank_p50 | 18.0 |
| candidate_hit_rank_p90 | 42.0 |
| candidate_hit_missed_topk_users | 52 |
| ranked_hit_users | 15 |
| recall_at_k | 0.007508 |
| recall_at_pool | 0.037814 |
| ndcg_at_k | 0.00721 |
| mrr_at_k | 0.014189 |
| map_at_k | 0.004243 |
| hit_rate_at_k | 0.021038 |
| popular_only_hit_rate_at_k | 0.0 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.021038 |
| hybrid_no_itemcf_hit_rate_at_k | 0.023843 |
| category_diversity_avg | 2.101709 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 52752, "itemcf_strong": 18954, "itemcf_weak": 20333, "popular": 11890, "semantic": 63960, "two_tower": 68238}`
- topk_source_coverage: `{"category": 1141, "itemcf_strong": 992, "itemcf_weak": 1019, "popular": 5206, "semantic": 5540, "two_tower": 1091}`
- per_source_candidate_contribution: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 2, "semantic": 73, "two_tower": 15}`
- per_source_topk_contribution: `{"semantic": 15}`
- source_overlap: `{"single_source_candidate_count": 169384, "multi_source_candidate_count": 32875, "multi_source_candidate_rate": 0.162539, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+popular": 1158, "category+semantic": 899, "category+two_tower": 2173, "itemcf_strong+itemcf_weak": 17044, "itemcf_strong+popular": 12, "itemcf_strong+semantic": 117, "itemcf_strong+two_tower": 326, "itemcf_weak+popular": 13, "itemcf_weak+semantic": 118, "itemcf_weak+two_tower": 327, "popular+semantic": 51, "popular+two_tower": 246, "semantic+two_tower": 12230}}`
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
    "candidate_hit_rate_at_pool": 0.093969,
    "hit_rate_at_k": 0.021038,
    "ndcg_at_k": 0.00721,
    "mrr_at_k": 0.014189,
    "candidate_hit_users": 67,
    "candidate_hit_missed_topk_users": 52,
    "candidate_hit_rank_p50": 18.0,
    "candidate_hit_rank_p90": 42.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.162539,
    "ranking_p95_seconds": 0.000692,
    "candidate_generation_p95_seconds": 0.465336
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.176862,
  "candidate_generation_p95_seconds": 0.465336,
  "ranking_avg_seconds": 0.000454,
  "ranking_p95_seconds": 0.000692,
  "recommendation_avg_seconds": 0.177335,
  "recommendation_p95_seconds": 0.465718,
  "total_run_seconds": 419.076399
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.093969
- candidate_hit_users: 67
- ranked_hit_users: 15
- candidate_hit_missed_topk_users: 52
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 21.283582
- candidate_hit_rank_p50: 18.0
- candidate_hit_rank_p90: 42.0
- candidate_hit_source_coverage: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 2, "semantic": 73, "two_tower": 15}`

## Ranking Case Summary

- total_hit_cases: 95
- topk_hit_cases: 18
- missed_topk_cases: 77
- semantic_only_items_above_share: 0.647949
- top1_score_gap_avg: 17.829672
- target_source_combinations: `{"category": 8, "category+popular": 1, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 1, "popular": 1, "semantic": 51, "semantic+two_tower": 4, "two_tower": 10}`
- items_above_source_combinations: `{"semantic": 1327, "category": 249, "two_tower": 110, "popular": 109, "semantic+two_tower": 101, "itemcf_strong+itemcf_weak": 89, "category+semantic": 15, "category+popular": 13, "itemcf_strong": 10, "itemcf_weak": 10, "category+two_tower": 8, "itemcf_strong+itemcf_weak+semantic": 3, "category+itemcf_strong+itemcf_weak": 1, "itemcf_weak+semantic+two_tower": 1, "itemcf_strong+semantic": 1, "category+itemcf_strong": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_ablation_balanced_budget_caps
- risk_flags: none
- items:
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B07VVJNG7P score=51.6 sources=semantic
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_ablation_balanced_budget_caps
- risk_flags: none
- items:
  - B0B23LRBRP score=33.6 sources=semantic
  - B00P28VN38 score=33.210233 sources=semantic,two_tower
  - B089LMWJJB score=32.4 sources=semantic
  - B09KXJBNGN score=32.4 sources=semantic
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_ablation_balanced_budget_caps
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
