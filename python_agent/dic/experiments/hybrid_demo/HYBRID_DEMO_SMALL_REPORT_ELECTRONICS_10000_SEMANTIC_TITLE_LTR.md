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
    "enabled": true,
    "model_path": "outputs/training/ltr/ltr_training_10000_lopo_semantic_title/ltr_model.json",
    "score_scale": 1.0,
    "features": {
      "include_metadata": true
    }
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
  "semantic_score_mode": "raw",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": [
    "title_clean",
    "main_category",
    "categories_flat"
  ],
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
| fallback_rate | 0.088889 |
| candidate_hit_rate_at_pool | 0.084151 |
| candidate_hit_users | 60 |
| candidate_hit_rank_min | 2 |
| candidate_hit_rank_avg | 17.833333 |
| candidate_hit_rank_p50 | 16.0 |
| candidate_hit_rank_p90 | 36.0 |
| candidate_hit_missed_topk_users | 50 |
| ranked_hit_users | 10 |
| recall_at_k | 0.002009 |
| recall_at_pool | 0.034086 |
| ndcg_at_k | 0.002638 |
| mrr_at_k | 0.005259 |
| map_at_k | 0.001116 |
| hit_rate_at_k | 0.014025 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.014025 |
| hybrid_no_itemcf_hit_rate_at_k | 0.018233 |
| category_diversity_avg | 1.733333 |

## Fallback and Source Coverage

- fallback_rate: 0.088889
- recall_source_coverage: `{"category": 14312, "itemcf_strong": 14218, "itemcf_weak": 15064, "popular": 40003, "semantic": 61539}`
- topk_source_coverage: `{"category": 2782, "itemcf_strong": 991, "itemcf_weak": 1015, "popular": 10068, "semantic": 990}`
- per_source_candidate_contribution: `{"category": 9, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 12, "semantic": 72}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "semantic": 6}`
- source_overlap: `{"single_source_candidate_count": 89681, "multi_source_candidate_count": 27307, "multi_source_candidate_rate": 0.233417, "source_pair_counts": {"category+itemcf_strong": 197, "category+itemcf_weak": 204, "category+popular": 13498, "category+semantic": 1082, "itemcf_strong+itemcf_weak": 13038, "itemcf_strong+popular": 222, "itemcf_strong+semantic": 111, "itemcf_weak+popular": 232, "itemcf_weak+semantic": 111, "popular+semantic": 435}}`
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
    "candidate_hit_rate_at_pool": 0.084151,
    "hit_rate_at_k": 0.014025,
    "ndcg_at_k": 0.002638,
    "mrr_at_k": 0.005259,
    "candidate_hit_users": 60,
    "candidate_hit_missed_topk_users": 50,
    "candidate_hit_rank_p50": 16.0,
    "candidate_hit_rank_p90": 36.0,
    "fallback_rate": 0.088889,
    "multi_source_candidate_rate": 0.233417,
    "ranking_p95_seconds": 0.001287
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.138682,
  "candidate_generation_p95_seconds": 0.388379,
  "ranking_avg_seconds": 0.001019,
  "ranking_p95_seconds": 0.001287,
  "recommendation_avg_seconds": 0.139722,
  "recommendation_p95_seconds": 0.389186,
  "total_run_seconds": 331.926245
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.084151
- candidate_hit_users: 60
- ranked_hit_users: 10
- candidate_hit_missed_topk_users: 50
- candidate_hit_rank_min: 2
- candidate_hit_rank_avg: 17.833333
- candidate_hit_rank_p50: 16.0
- candidate_hit_rank_p90: 36.0
- candidate_hit_source_coverage: `{"category": 9, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 12, "semantic": 72}`

## Ranking Case Summary

- total_hit_cases: 85
- topk_hit_cases: 13
- missed_topk_cases: 72
- semantic_only_items_above_share: 0.600917
- top1_score_gap_avg: 37.200807
- target_source_combinations: `{"category+popular": 4, "itemcf_strong+itemcf_weak": 1, "popular": 1, "semantic": 66}`
- items_above_source_combinations: `{"semantic": 917, "popular": 297, "category+popular": 263, "category+semantic": 14, "category+popular+semantic": 13, "itemcf_strong+itemcf_weak": 7, "itemcf_strong+itemcf_weak+semantic": 6, "itemcf_strong+itemcf_weak+popular": 5, "category+itemcf_strong+itemcf_weak+popular": 2, "category+itemcf_strong+itemcf_weak+popular+semantic": 2}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_9_ltr_demo_10000_valid_test
- risk_flags: none
- items:
  - B087S2JRXY score=56.216268 sources=category,popular
  - B071VDV7NC score=39.635496 sources=category,semantic,popular
  - B07MZ6PJW8 score=32.32 sources=semantic
  - B07TJ87YKB score=31.58 sources=semantic
  - B005TUQV0E score=15.367181 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_9_ltr_demo_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=58.812087 sources=popular
  - B075X8471B score=51.000504 sources=popular
  - B013EKI2DY score=25.763562 sources=semantic,popular
  - B0B23LRBRP score=19.74 sources=semantic
  - B00006IBAK score=13.877179 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_9_ltr_demo_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=58.812087 sources=popular
  - B075X8471B score=51.000504 sources=popular
  - B07KTYJ769 score=48.897348 sources=popular
  - B07GZFM1ZM score=46.471499 sources=popular
  - 993591786X score=15.367181 sources=itemcf_weak,itemcf_strong
