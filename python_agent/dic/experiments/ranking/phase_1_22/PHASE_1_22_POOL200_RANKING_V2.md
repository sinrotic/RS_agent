# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_10000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_10000",
  "evaluation_mode": "valid_test",
  "top_k": 5,
  "candidate_pool_size": 200,
  "limit_users": 500,
  "rank_weights": {},
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
  "two_tower_text_fields": null,
  "two_tower_min_overlap": null,
  "two_tower_recency_decay": null,
  "two_tower_seed_enabled": false,
  "two_tower_seed_artifact_path": null,
  "two_tower_seed_artifact_name": "two_tower_seed_recall.jsonl",
  "two_tower_seed_manifest_path": null,
  "two_tower_seed_manifest_name": "two_tower_seed_manifest.json",
  "fail_on_missing_sidecar": false,
  "two_tower_seed_per_seed": null,
  "two_tower_seed_per_user": null,
  "two_tower_seed_window": 50,
  "two_tower_seed_recent_positive_window": null,
  "two_tower_seed_recent_strong_window": null,
  "two_tower_seed_recency_decay": null,
  "two_tower_seed_score_floor": null,
  "item_graph_enabled": false,
  "item_graph_artifact_path": null,
  "item_graph_artifact_name": "item_graph_recall.jsonl",
  "item_graph_per_seed": null,
  "item_graph_per_user": null,
  "item_graph_seed_window": null,
  "item_graph_recent_positive_window": null,
  "item_graph_recent_strong_window": null,
  "graph_walk_seed_enabled": false,
  "graph_walk_seed_algorithm": "deepwalk",
  "graph_walk_seed_artifact_path": null,
  "graph_walk_seed_artifact_name": "graph_walk_seed_neighbors.jsonl",
  "graph_walk_seed_manifest_path": null,
  "graph_walk_seed_manifest_name": "graph_walk_seed_manifest.json",
  "graph_walk_seed_per_seed": null,
  "graph_walk_seed_per_user": null,
  "graph_walk_seed_window": null,
  "graph_walk_seed_recent_positive_window": null,
  "graph_walk_seed_recent_strong_window": null,
  "graph_walk_seed_recency_decay": null,
  "graph_walk_seed_score_floor": null,
  "graph_walk_training": {},
  "candidate_source_maximums": {},
  "candidate_pool_strategy": null
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | valid_test |
| users_total | 500 |
| users_with_holdout | 138 |
| users_evaluated | 138 |
| lopo_input_users | None |
| lopo_eligible_users | None |
| lopo_skipped_users_fewer_than_2_positives | None |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 152.272 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.123188 |
| candidate_hit_users | 17 |
| candidate_hit_rank_min | 2 |
| candidate_hit_rank_avg | 36.941176 |
| candidate_hit_rank_p50 | 26.0 |
| candidate_hit_rank_p90 | 68.0 |
| candidate_hit_missed_topk_users | 15 |
| ranked_hit_users | 2 |
| recall_at_k | 0.002657 |
| recall_at_pool | 0.065962 |
| ndcg_at_k | 0.002779 |
| mrr_at_k | 0.006039 |
| map_at_k | 0.001208 |
| hit_rate_at_k | 0.014493 |
| popular_only_hit_rate_at_k | 0.014493 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.014493 |
| hybrid_no_itemcf_hit_rate_at_k | 0.014493 |
| category_diversity_avg | 2.482 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 13593, "category_long_tail_recall": 13257, "itemcf_strong": 4011, "itemcf_weak": 4253, "popular": 24906, "semantic": 13620, "two_tower": 15000}`
- topk_source_coverage: `{"category": 486, "category_long_tail_recall": 13, "itemcf_strong": 195, "itemcf_weak": 204, "popular": 1129, "semantic": 1265, "two_tower": 459}`
- per_source_candidate_contribution: `{"category": 2, "category_long_tail_recall": 2, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 6, "semantic": 13, "two_tower": 2}`
- per_source_topk_contribution: `{"category": 1, "popular": 1, "semantic": 1, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 64229, "multi_source_candidate_count": 11907, "multi_source_candidate_rate": 0.156391, "source_pair_counts": {"category+category_long_tail_recall": 346, "category+itemcf_strong": 27, "category+itemcf_weak": 28, "category+popular": 4906, "category+semantic": 194, "category+two_tower": 416, "category_long_tail_recall+itemcf_strong": 23, "category_long_tail_recall+itemcf_weak": 30, "category_long_tail_recall+semantic": 124, "category_long_tail_recall+two_tower": 135, "itemcf_strong+itemcf_weak": 3408, "itemcf_strong+popular": 41, "itemcf_strong+semantic": 21, "itemcf_strong+two_tower": 56, "itemcf_weak+popular": 46, "itemcf_weak+semantic": 22, "itemcf_weak+two_tower": 61, "popular+semantic": 95, "popular+two_tower": 435, "semantic+two_tower": 2780}}`
- source_diagnostics: `{"users_with_positive_seeds": 454, "users_with_itemcf_seed_hits": 318, "users_with_itemcf_raw_candidates": 318, "itemcf_raw_candidates": 84940, "itemcf_raw_unseen_candidates": 35123, "users_with_item_graph_seed_hits": 0, "users_with_item_graph_raw_candidates": 0, "item_graph_raw_candidates": 0, "item_graph_raw_unseen_candidates": 0, "users_with_two_tower_seed_hits": 0, "users_with_two_tower_seed_raw_candidates": 0, "two_tower_seed_raw_candidates": 0, "two_tower_seed_raw_unseen_candidates": 0, "users_with_graph_walk_seed_hits": 0, "users_with_graph_walk_seed_raw_candidates": 0, "graph_walk_seed_raw_candidates": 0, "graph_walk_seed_raw_unseen_candidates": 0}`

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
    "candidate_pool_size": 200,
    "candidate_hit_rate_at_pool": 0.123188,
    "hit_rate_at_k": 0.014493,
    "ndcg_at_k": 0.002779,
    "mrr_at_k": 0.006039,
    "candidate_hit_users": 17,
    "candidate_hit_missed_topk_users": 15,
    "candidate_hit_rank_p50": 26.0,
    "candidate_hit_rank_p90": 68.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.156391,
    "ranking_p95_seconds": 0.001435,
    "candidate_generation_p95_seconds": 0.363297
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.206002,
  "candidate_generation_p95_seconds": 0.363297,
  "ranking_avg_seconds": 0.000977,
  "ranking_p95_seconds": 0.001435,
  "recommendation_avg_seconds": 0.207016,
  "recommendation_p95_seconds": 0.364415,
  "total_run_seconds": 106.014668
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.123188
- candidate_hit_users: 17
- ranked_hit_users: 2
- candidate_hit_missed_topk_users: 15
- candidate_hit_rank_min: 2
- candidate_hit_rank_avg: 36.941176
- candidate_hit_rank_p50: 26.0
- candidate_hit_rank_p90: 68.0
- candidate_hit_source_coverage: `{"category": 2, "category_long_tail_recall": 2, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 6, "semantic": 13, "two_tower": 2}`

## Ranking Case Summary

- total_hit_cases: 23
- topk_hit_cases: 2
- missed_topk_cases: 21
- semantic_only_items_above_share: 0.417266
- top1_score_gap_avg: 22.981073
- target_source_combinations: `{"category+popular": 1, "category_long_tail_recall": 2, "itemcf_strong+itemcf_weak": 1, "popular": 4, "semantic": 12, "two_tower": 1}`
- items_above_source_combinations: `{"semantic": 406, "popular": 179, "category+popular": 109, "category": 63, "two_tower": 63, "semantic+two_tower": 38, "category_long_tail_recall": 29, "itemcf_strong+itemcf_weak": 26, "itemcf_weak": 15, "itemcf_strong": 13, "popular+two_tower": 10, "category+popular+two_tower": 9, "category+popular+semantic": 3, "popular+semantic": 2, "category+two_tower": 2, "itemcf_weak+popular": 2, "itemcf_strong+itemcf_weak+semantic": 2, "itemcf_weak+two_tower": 1, "category+itemcf_strong+itemcf_weak+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_22_pool200_ranking_v2
- risk_flags: none
- items:
  - B071VDV7NC score=46.0 sources=category,semantic,popular
  - B07MZ6PJW8 score=45.0 sources=semantic
  - B07TJ87YKB score=44.0 sources=semantic
  - B06Y3WCWXN score=43.0 sources=semantic
  - B004GYBR30 score=0.411767 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_22_pool200_ranking_v2
- risk_flags: none
- items:
  - B01K8B8YA8 score=31.0 sources=popular
  - B013EKI2DY score=29.0 sources=semantic,popular
  - B075X8471B score=28.0 sources=popular
  - B0B23LRBRP score=28.0 sources=semantic
  - B00006IBAK score=1.0 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_22_pool200_ranking_v2
- risk_flags: none
- items:
  - B01K8B8YA8 score=31.0 sources=popular
  - B07W3Q9X9B score=29.694227 sources=semantic,two_tower
  - B0B8SDY8F6 score=29.662978 sources=semantic,two_tower
  - B0B42DKNL2 score=29.644007 sources=semantic,two_tower
  - 993591786X score=1.202082 sources=itemcf_weak,itemcf_strong
