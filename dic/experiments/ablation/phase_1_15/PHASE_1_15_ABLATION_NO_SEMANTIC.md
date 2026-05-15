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
    "two_tower": 10
  },
  "semantic_enabled": false,
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
| candidate_count_avg | 95.17265 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.050491 |
| candidate_hit_users | 36 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 38.055556 |
| candidate_hit_rank_p50 | 28.5 |
| candidate_hit_rank_p90 | 92.0 |
| candidate_hit_missed_topk_users | 32 |
| ranked_hit_users | 4 |
| recall_at_k | 0.000695 |
| recall_at_pool | 0.01843 |
| ndcg_at_k | 0.001425 |
| mrr_at_k | 0.003623 |
| map_at_k | 0.000742 |
| hit_rate_at_k | 0.00561 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.00561 |
| hybrid_no_itemcf_hit_rate_at_k | 0.007013 |
| category_diversity_avg | 1.902137 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 62594, "itemcf_strong": 15127, "itemcf_weak": 16173, "popular": 116512, "two_tower": 53287}`
- topk_source_coverage: `{"category": 1877, "itemcf_strong": 987, "itemcf_weak": 1019, "popular": 10814, "two_tower": 795}`
- per_source_candidate_contribution: `{"category": 12, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 24, "two_tower": 11}`
- per_source_topk_contribution: `{"category": 3, "popular": 4, "two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 183739, "multi_source_candidate_count": 38965, "multi_source_candidate_rate": 0.174963, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 141, "category+popular": 23318, "category+two_tower": 2173, "itemcf_strong+itemcf_weak": 13882, "itemcf_strong+popular": 230, "itemcf_strong+two_tower": 326, "itemcf_weak+popular": 241, "itemcf_weak+two_tower": 327, "popular+two_tower": 2417}}`
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
    "candidate_hit_rate_at_pool": 0.050491,
    "hit_rate_at_k": 0.00561,
    "ndcg_at_k": 0.001425,
    "mrr_at_k": 0.003623,
    "candidate_hit_users": 36,
    "candidate_hit_missed_topk_users": 32,
    "candidate_hit_rank_p50": 28.5,
    "candidate_hit_rank_p90": 92.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.174963,
    "ranking_p95_seconds": 0.000736,
    "candidate_generation_p95_seconds": 0.067493
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.062776,
  "candidate_generation_p95_seconds": 0.067493,
  "ranking_avg_seconds": 0.000599,
  "ranking_p95_seconds": 0.000736,
  "recommendation_avg_seconds": 0.063405,
  "recommendation_p95_seconds": 0.068162,
  "total_run_seconds": 152.793571
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.050491
- candidate_hit_users: 36
- ranked_hit_users: 4
- candidate_hit_missed_topk_users: 32
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 38.055556
- candidate_hit_rank_p50: 28.5
- candidate_hit_rank_p90: 92.0
- candidate_hit_source_coverage: `{"category": 12, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 24, "two_tower": 11}`

## Ranking Case Summary

- total_hit_cases: 38
- topk_hit_cases: 5
- missed_topk_cases: 33
- semantic_only_items_above_share: 0.0
- top1_score_gap_avg: 39.403786
- target_source_combinations: `{"category": 3, "category+popular": 5, "itemcf_strong+itemcf_weak": 1, "popular": 14, "two_tower": 10}`
- items_above_source_combinations: `{"popular": 803, "category": 232, "category+popular": 218, "two_tower": 81, "itemcf_strong+itemcf_weak": 70, "popular+two_tower": 19, "itemcf_weak": 10, "category+two_tower": 2, "itemcf_strong": 2, "category+itemcf_strong+itemcf_weak+popular": 1, "itemcf_strong+itemcf_weak+two_tower": 1, "category+popular+two_tower": 1, "category+itemcf_strong+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_ablation_no_semantic
- risk_flags: none
- items:
  - B087S2JRXY score=51.542975 sources=category,popular
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_ablation_no_semantic
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_ablation_no_semantic
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
