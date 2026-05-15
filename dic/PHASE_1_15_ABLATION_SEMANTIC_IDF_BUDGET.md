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
  "semantic_per_user": 40,
  "semantic_min_overlap": 1,
  "semantic_score_mode": "idf_seed_aware",
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
| candidate_count_avg | 97.593162 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.100982 |
| candidate_hit_users | 72 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 31.791667 |
| candidate_hit_rank_p50 | 27.0 |
| candidate_hit_rank_p90 | 67.0 |
| candidate_hit_missed_topk_users | 68 |
| ranked_hit_users | 4 |
| recall_at_k | 0.000695 |
| recall_at_pool | 0.038765 |
| ndcg_at_k | 0.001425 |
| mrr_at_k | 0.003623 |
| map_at_k | 0.000742 |
| hit_rate_at_k | 0.00561 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.00561 |
| hybrid_no_itemcf_hit_rate_at_k | 0.007013 |
| category_diversity_avg | 1.967094 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 35552, "itemcf_strong": 14802, "itemcf_weak": 15849, "popular": 106428, "semantic": 69941, "two_tower": 39520}`
- topk_source_coverage: `{"category": 1949, "itemcf_strong": 981, "itemcf_weak": 1015, "popular": 10791, "semantic": 271, "two_tower": 803}`
- per_source_candidate_contribution: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 22, "semantic": 69, "two_tower": 9}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 177317, "multi_source_candidate_count": 51051, "multi_source_candidate_rate": 0.223547, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+popular": 23315, "category+semantic": 922, "category+two_tower": 2132, "itemcf_strong+itemcf_weak": 13618, "itemcf_strong+popular": 230, "itemcf_strong+semantic": 162, "itemcf_strong+two_tower": 325, "itemcf_weak+popular": 241, "itemcf_weak+semantic": 174, "itemcf_weak+two_tower": 327, "popular+semantic": 341, "popular+two_tower": 2416, "semantic+two_tower": 12235}}`
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
    "candidate_hit_rate_at_pool": 0.100982,
    "hit_rate_at_k": 0.00561,
    "ndcg_at_k": 0.001425,
    "mrr_at_k": 0.003623,
    "candidate_hit_users": 72,
    "candidate_hit_missed_topk_users": 68,
    "candidate_hit_rank_p50": 27.0,
    "candidate_hit_rank_p90": 67.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.223547,
    "ranking_p95_seconds": 0.000721,
    "candidate_generation_p95_seconds": 0.777899
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.222505,
  "candidate_generation_p95_seconds": 0.777899,
  "ranking_avg_seconds": 0.000511,
  "ranking_p95_seconds": 0.000721,
  "recommendation_avg_seconds": 0.223041,
  "recommendation_p95_seconds": 0.77844,
  "total_run_seconds": 526.765213
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.100982
- candidate_hit_users: 72
- ranked_hit_users: 4
- candidate_hit_missed_topk_users: 68
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 31.791667
- candidate_hit_rank_p50: 27.0
- candidate_hit_rank_p90: 67.0
- candidate_hit_source_coverage: `{"category": 10, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 22, "semantic": 69, "two_tower": 9}`

## Ranking Case Summary

- total_hit_cases: 99
- topk_hit_cases: 5
- missed_topk_cases: 94
- semantic_only_items_above_share: 0.495445
- top1_score_gap_avg: 32.778093
- target_source_combinations: `{"category": 1, "category+popular": 5, "itemcf_strong+itemcf_weak": 1, "popular": 12, "semantic": 67, "semantic+two_tower": 2, "two_tower": 6}`
- items_above_source_combinations: `{"semantic": 1577, "popular": 900, "category+popular": 383, "semantic+two_tower": 116, "itemcf_strong+itemcf_weak": 56, "category": 35, "two_tower": 31, "popular+two_tower": 25, "category+popular+semantic": 14, "category+semantic": 14, "category+popular+two_tower": 6, "itemcf_strong+itemcf_weak+semantic": 6, "itemcf_strong+itemcf_weak+popular": 5, "category+itemcf_strong+itemcf_weak+popular": 2, "category+itemcf_strong+itemcf_weak+popular+semantic": 2, "category+itemcf_strong+popular": 2, "itemcf_strong+popular": 1, "itemcf_strong+semantic": 1, "itemcf_strong+itemcf_weak+two_tower": 1, "category+two_tower": 1, "itemcf_strong": 1, "itemcf_weak": 1, "popular+semantic": 1, "category+popular+semantic+two_tower": 1, "category+semantic+two_tower": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_ablation_semantic_idf_budget
- risk_flags: none
- items:
  - B087S2JRXY score=51.542975 sources=category,popular
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_ablation_semantic_idf_budget
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_ablation_semantic_idf_budget
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
