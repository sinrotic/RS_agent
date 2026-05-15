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
    "two_tower_seed": 1.2,
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
  "two_tower_seed_enabled": true,
  "two_tower_seed_artifact_path": "outputs/two_tower_training/youtube_dnn/two_tower_seed_neighbors.jsonl",
  "two_tower_seed_artifact_name": "two_tower_seed_recall.jsonl",
  "two_tower_seed_manifest_path": "outputs/two_tower_training/youtube_dnn/two_tower_seed_manifest.json",
  "two_tower_seed_manifest_name": "two_tower_seed_manifest.json",
  "fail_on_missing_sidecar": true,
  "two_tower_seed_per_seed": 20,
  "two_tower_seed_per_user": 30,
  "two_tower_seed_window": 20,
  "two_tower_seed_recent_positive_window": 20,
  "two_tower_seed_recent_strong_window": 20,
  "two_tower_seed_recency_decay": 0.85,
  "two_tower_seed_score_floor": 0.0,
  "item_graph_enabled": false,
  "item_graph_artifact_path": null,
  "item_graph_artifact_name": "item_graph_recall.jsonl",
  "item_graph_per_seed": null,
  "item_graph_per_user": null,
  "item_graph_seed_window": null,
  "item_graph_recent_positive_window": null,
  "item_graph_recent_strong_window": null
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
| candidate_count_avg | 97.946581 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.105189 |
| candidate_hit_users | 75 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 25.48 |
| candidate_hit_rank_p50 | 20.0 |
| candidate_hit_rank_p90 | 61.0 |
| candidate_hit_missed_topk_users | 61 |
| ranked_hit_users | 14 |
| recall_at_k | 0.005515 |
| recall_at_pool | 0.041066 |
| ndcg_at_k | 0.004959 |
| mrr_at_k | 0.009046 |
| map_at_k | 0.002519 |
| hit_rate_at_k | 0.019635 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.019635 |
| hybrid_no_itemcf_hit_rate_at_k | 0.021038 |
| category_diversity_avg | 2.438462 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 39179, "itemcf_strong": 14802, "itemcf_weak": 15836, "popular": 113077, "semantic": 63960, "two_tower": 35334, "two_tower_seed": 22814}`
- topk_source_coverage: `{"category": 2104, "itemcf_strong": 980, "itemcf_weak": 1012, "popular": 8370, "semantic": 2803, "two_tower": 1310, "two_tower_seed": 1007}`
- per_source_candidate_contribution: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 24, "semantic": 73, "two_tower": 11, "two_tower_seed": 8}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "semantic": 10, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 164961, "multi_source_candidate_count": 64234, "multi_source_candidate_rate": 0.280259, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+popular": 23318, "category+semantic": 899, "category+two_tower": 2160, "category+two_tower_seed": 966, "itemcf_strong+itemcf_weak": 13606, "itemcf_strong+popular": 230, "itemcf_strong+semantic": 117, "itemcf_strong+two_tower": 325, "itemcf_strong+two_tower_seed": 213, "itemcf_weak+popular": 241, "itemcf_weak+semantic": 118, "itemcf_weak+two_tower": 327, "itemcf_weak+two_tower_seed": 246, "popular+semantic": 435, "popular+two_tower": 2417, "popular+two_tower_seed": 683, "semantic+two_tower": 12230, "semantic+two_tower_seed": 12482, "two_tower+two_tower_seed": 17270}}`
- source_diagnostics: `{"users_with_positive_seeds": 2132, "users_with_itemcf_seed_hits": 1530, "users_with_itemcf_raw_candidates": 1530, "itemcf_raw_candidates": 499363, "itemcf_raw_unseen_candidates": 201803, "users_with_item_graph_seed_hits": 0, "users_with_item_graph_raw_candidates": 0, "item_graph_raw_candidates": 0, "item_graph_raw_unseen_candidates": 0, "users_with_two_tower_seed_hits": 2132, "users_with_two_tower_seed_raw_candidates": 2132, "two_tower_seed_raw_candidates": 1132700, "two_tower_seed_raw_unseen_candidates": 1119839}`

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
    "candidate_hit_rate_at_pool": 0.105189,
    "hit_rate_at_k": 0.019635,
    "ndcg_at_k": 0.004959,
    "mrr_at_k": 0.009046,
    "candidate_hit_users": 75,
    "candidate_hit_missed_topk_users": 61,
    "candidate_hit_rank_p50": 20.0,
    "candidate_hit_rank_p90": 61.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.280259,
    "ranking_p95_seconds": 0.000717,
    "candidate_generation_p95_seconds": 0.45225
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.155202,
  "candidate_generation_p95_seconds": 0.45225,
  "ranking_avg_seconds": 0.000483,
  "ranking_p95_seconds": 0.000717,
  "recommendation_avg_seconds": 0.15571,
  "recommendation_p95_seconds": 0.452823,
  "total_run_seconds": 371.616225
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.105189
- candidate_hit_users: 75
- ranked_hit_users: 14
- candidate_hit_missed_topk_users: 61
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 25.48
- candidate_hit_rank_p50: 20.0
- candidate_hit_rank_p90: 61.0
- candidate_hit_source_coverage: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 24, "semantic": 73, "two_tower": 11, "two_tower_seed": 8}`

## Ranking Case Summary

- total_hit_cases: 105
- topk_hit_cases: 14
- missed_topk_cases: 91
- semantic_only_items_above_share: 0.507925
- top1_score_gap_avg: 21.811368
- target_source_combinations: `{"category": 1, "category+popular": 6, "itemcf_strong+itemcf_weak": 1, "popular": 14, "semantic": 55, "semantic+two_tower": 2, "semantic+two_tower+two_tower_seed": 2, "semantic+two_tower_seed": 4, "two_tower": 4, "two_tower+two_tower_seed": 2}`
- items_above_source_combinations: `{"semantic": 1346, "popular": 696, "category+popular": 203, "semantic+two_tower_seed": 112, "semantic+two_tower+two_tower_seed": 73, "semantic+two_tower": 60, "itemcf_strong+itemcf_weak": 46, "popular+two_tower": 22, "two_tower": 20, "category": 15, "category+popular+two_tower": 9, "two_tower+two_tower_seed": 9, "category+popular+semantic": 8, "category+semantic": 8, "popular+semantic": 5, "itemcf_strong+itemcf_weak+semantic+two_tower_seed": 2, "category+itemcf_strong+itemcf_weak+popular+semantic": 2, "itemcf_strong+semantic": 2, "category+itemcf_strong+itemcf_weak+popular": 1, "category+two_tower_seed": 1, "category+semantic+two_tower_seed": 1, "itemcf_weak+semantic+two_tower+two_tower_seed": 1, "category+two_tower": 1, "itemcf_strong": 1, "itemcf_weak": 1, "itemcf_strong+itemcf_weak+popular": 1, "itemcf_strong+itemcf_weak+semantic": 1, "category+popular+semantic+two_tower": 1, "category+semantic+two_tower+two_tower_seed": 1, "category+itemcf_strong+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_18_two_tower_seed_pool100
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_18_two_tower_seed_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B013EKI2DY score=35.953283 sources=semantic,popular
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_18_two_tower_seed_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B0B8SDY8F6 score=36.498877 sources=semantic,two_tower,two_tower_seed
  - B07F5K8Z6Y score=3.685187 sources=itemcf_weak,itemcf_strong,two_tower_seed
