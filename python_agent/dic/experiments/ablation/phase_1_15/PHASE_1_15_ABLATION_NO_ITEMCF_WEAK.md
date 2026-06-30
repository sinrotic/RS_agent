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
| candidate_count_avg | 97.926496 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.106592 |
| candidate_hit_users | 76 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 26.460526 |
| candidate_hit_rank_p50 | 20.5 |
| candidate_hit_rank_p90 | 62.0 |
| candidate_hit_missed_topk_users | 62 |
| ranked_hit_users | 14 |
| recall_at_k | 0.005515 |
| recall_at_pool | 0.042219 |
| ndcg_at_k | 0.004959 |
| mrr_at_k | 0.009046 |
| map_at_k | 0.002519 |
| hit_rate_at_k | 0.019635 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.019635 |
| hybrid_no_itemcf_hit_rate_at_k | 0.021038 |
| category_diversity_avg | 2.434188 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 40200, "itemcf_strong": 15545, "popular": 113637, "semantic": 63960, "two_tower": 35776}`
- topk_source_coverage: `{"category": 2100, "itemcf_strong": 1023, "popular": 8471, "semantic": 2722, "two_tower": 1205}`
- per_source_candidate_contribution: `{"category": 10, "itemcf_strong": 1, "popular": 24, "semantic": 73, "two_tower": 10}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "semantic": 10, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 191303, "multi_source_candidate_count": 37845, "multi_source_candidate_rate": 0.165155, "source_pair_counts": {"category+itemcf_strong": 128, "category+popular": 23318, "category+semantic": 899, "category+two_tower": 2153, "itemcf_strong+popular": 230, "itemcf_strong+semantic": 117, "itemcf_strong+two_tower": 326, "popular+semantic": 435, "popular+two_tower": 2417, "semantic+two_tower": 12230}}`
- source_diagnostics: `{"users_with_positive_seeds": 2132, "users_with_itemcf_seed_hits": 1530, "users_with_itemcf_raw_candidates": 1530, "itemcf_raw_candidates": 499363, "itemcf_raw_unseen_candidates": 201803}`

## Diagnostic Gate

```json
{
  "recall_bottleneck": false,
  "ranking_bottleneck": true,
  "source_merge_bottleneck": false,
  "latency_bottleneck": false,
  "architecture_escalation": false,
  "recommended_next_phase": "phase_1_12_ranking_ltr_gate",
  "evidence": {
    "top_k": 5,
    "candidate_pool_size": 100,
    "candidate_hit_rate_at_pool": 0.106592,
    "hit_rate_at_k": 0.019635,
    "ndcg_at_k": 0.004959,
    "mrr_at_k": 0.009046,
    "candidate_hit_users": 76,
    "candidate_hit_missed_topk_users": 62,
    "candidate_hit_rank_p50": 20.5,
    "candidate_hit_rank_p90": 62.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.165155,
    "ranking_p95_seconds": 0.000765,
    "candidate_generation_p95_seconds": 0.5131
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.195736,
  "candidate_generation_p95_seconds": 0.5131,
  "ranking_avg_seconds": 0.000596,
  "ranking_p95_seconds": 0.000765,
  "recommendation_avg_seconds": 0.196361,
  "recommendation_p95_seconds": 0.513642,
  "total_run_seconds": 464.341061
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.106592
- candidate_hit_users: 76
- ranked_hit_users: 14
- candidate_hit_missed_topk_users: 62
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 26.460526
- candidate_hit_rank_p50: 20.5
- candidate_hit_rank_p90: 62.0
- candidate_hit_source_coverage: `{"category": 10, "itemcf_strong": 1, "popular": 24, "semantic": 73, "two_tower": 10}`

## Ranking Case Summary

- total_hit_cases: 104
- topk_hit_cases: 15
- missed_topk_cases: 89
- semantic_only_items_above_share: 0.556245
- top1_score_gap_avg: 21.73147
- target_source_combinations: `{"category": 1, "category+popular": 6, "itemcf_strong": 1, "popular": 14, "semantic": 58, "semantic+two_tower": 4, "two_tower": 5}`
- items_above_source_combinations: `{"semantic": 1434, "popular": 661, "category+popular": 204, "semantic+two_tower": 127, "itemcf_strong": 45, "two_tower": 27, "popular+two_tower": 22, "category": 15, "category+popular+two_tower": 9, "category+popular+semantic": 8, "category+semantic": 8, "itemcf_strong+semantic": 5, "popular+semantic": 5, "category+itemcf_strong+popular": 2, "category+itemcf_strong+popular+semantic": 2, "category+two_tower": 1, "itemcf_strong+popular": 1, "category+popular+semantic+two_tower": 1, "category+semantic+two_tower": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_ablation_no_itemcf_weak
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B004GYBR30 score=0.566706 sources=itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_ablation_no_itemcf_weak
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B013EKI2DY score=35.953283 sources=semantic,popular
  - B00006IBAK score=1.25 sources=itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_ablation_no_itemcf_weak
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=1.502602 sources=itemcf_strong
