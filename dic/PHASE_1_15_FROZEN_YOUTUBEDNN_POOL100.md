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
  "two_tower_artifact_path": "outputs/two_tower_training/youtube_dnn/artifact_manifest.json",
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
| users_total | 2340 |
| users_with_holdout | 713 |
| users_evaluated | 713 |
| lopo_input_users | None |
| lopo_eligible_users | None |
| lopo_skipped_users_fewer_than_2_positives | None |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 97.936752 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.096774 |
| candidate_hit_users | 69 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 23.043478 |
| candidate_hit_rank_p50 | 18.0 |
| candidate_hit_rank_p90 | 55.0 |
| candidate_hit_missed_topk_users | 55 |
| ranked_hit_users | 14 |
| recall_at_k | 0.005515 |
| recall_at_pool | 0.040439 |
| ndcg_at_k | 0.005876 |
| mrr_at_k | 0.012202 |
| map_at_k | 0.00329 |
| hit_rate_at_k | 0.019635 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.019635 |
| hybrid_no_itemcf_hit_rate_at_k | 0.021038 |
| category_diversity_avg | 2.382051 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 22741, "itemcf_strong": 22143, "itemcf_weak": 24024, "popular": 84105, "semantic": 63299, "two_tower": 67406}`
- topk_source_coverage: `{"category": 1959, "itemcf_strong": 1017, "itemcf_weak": 1043, "popular": 8116, "semantic": 3024, "two_tower": 1180}`
- per_source_candidate_contribution: `{"category": 7, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 15, "semantic": 70, "two_tower": 15}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "semantic": 10, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 177166, "multi_source_candidate_count": 52006, "multi_source_candidate_rate": 0.22693, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+popular": 19144, "category+semantic": 897, "category+two_tower": 2027, "itemcf_strong+itemcf_weak": 18907, "itemcf_strong+popular": 230, "itemcf_strong+semantic": 117, "itemcf_strong+two_tower": 326, "itemcf_weak+popular": 241, "itemcf_weak+semantic": 118, "itemcf_weak+two_tower": 327, "popular+semantic": 435, "popular+two_tower": 2182, "semantic+two_tower": 12209}}`
- source_diagnostics: `{"users_with_positive_seeds": 2132, "users_with_itemcf_seed_hits": 1530, "users_with_itemcf_raw_candidates": 1530, "itemcf_raw_candidates": 499363, "itemcf_raw_unseen_candidates": 201803, "users_with_item_graph_seed_hits": 0, "users_with_item_graph_raw_candidates": 0, "item_graph_raw_candidates": 0, "item_graph_raw_unseen_candidates": 0, "users_with_two_tower_seed_hits": 0, "users_with_two_tower_seed_raw_candidates": 0, "two_tower_seed_raw_candidates": 0, "two_tower_seed_raw_unseen_candidates": 0, "users_with_graph_walk_seed_hits": 0, "users_with_graph_walk_seed_raw_candidates": 0, "graph_walk_seed_raw_candidates": 0, "graph_walk_seed_raw_unseen_candidates": 0}`

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
    "hit_rate_at_k": 0.019635,
    "ndcg_at_k": 0.005876,
    "mrr_at_k": 0.012202,
    "candidate_hit_users": 69,
    "candidate_hit_missed_topk_users": 55,
    "candidate_hit_rank_p50": 18.0,
    "candidate_hit_rank_p90": 55.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.22693,
    "ranking_p95_seconds": 0.000871,
    "candidate_generation_p95_seconds": 0.515314
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.20767,
  "candidate_generation_p95_seconds": 0.515314,
  "ranking_avg_seconds": 0.00063,
  "ranking_p95_seconds": 0.000871,
  "recommendation_avg_seconds": 0.208327,
  "recommendation_p95_seconds": 0.515958,
  "total_run_seconds": 492.758191
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.096774
- candidate_hit_users: 69
- ranked_hit_users: 14
- candidate_hit_missed_topk_users: 55
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 23.043478
- candidate_hit_rank_p50: 18.0
- candidate_hit_rank_p90: 55.0
- candidate_hit_source_coverage: `{"category": 7, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 15, "semantic": 70, "two_tower": 15}`

## Ranking Case Summary

- total_hit_cases: 96
- topk_hit_cases: 15
- missed_topk_cases: 81
- semantic_only_items_above_share: 0.562387
- top1_score_gap_avg: 20.790164
- target_source_combinations: `{"category+popular": 4, "itemcf_strong+itemcf_weak": 1, "popular": 7, "semantic": 55, "semantic+two_tower": 4, "two_tower": 10}`
- items_above_source_combinations: `{"semantic": 1244, "popular": 472, "category+popular": 127, "two_tower": 110, "semantic+two_tower": 109, "itemcf_strong+itemcf_weak": 89, "itemcf_strong": 13, "itemcf_weak": 11, "category+semantic": 7, "category+popular+semantic": 5, "popular+two_tower": 5, "popular+semantic": 4, "category+popular+two_tower": 4, "itemcf_strong+itemcf_weak+semantic": 3, "category+two_tower": 2, "category+itemcf_strong+itemcf_weak+popular+semantic": 2, "itemcf_strong+semantic": 2, "category+itemcf_strong+itemcf_weak+popular": 1, "itemcf_weak+semantic+two_tower": 1, "itemcf_strong+itemcf_weak+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_frozen_youtubednn_pool100
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_frozen_youtubednn_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B013EKI2DY score=35.953283 sources=semantic,popular
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_frozen_youtubednn_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
