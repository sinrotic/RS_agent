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
| candidate_count_avg | 96.880769 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.106592 |
| candidate_hit_users | 76 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 27.25 |
| candidate_hit_rank_p50 | 21.0 |
| candidate_hit_rank_p90 | 61.0 |
| candidate_hit_missed_topk_users | 64 |
| ranked_hit_users | 12 |
| recall_at_k | 0.005264 |
| recall_at_pool | 0.041354 |
| ndcg_at_k | 0.004386 |
| mrr_at_k | 0.00748 |
| map_at_k | 0.002277 |
| hit_rate_at_k | 0.01683 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.01683 |
| hybrid_no_itemcf_hit_rate_at_k | 0.018233 |
| category_diversity_avg | 2.209402 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"itemcf_strong": 14828, "itemcf_weak": 15865, "popular": 113111, "semantic": 63960, "two_tower": 48198}`
- topk_source_coverage: `{"itemcf_strong": 985, "itemcf_weak": 1014, "popular": 7711, "semantic": 3461, "two_tower": 1208}`
- per_source_candidate_contribution: `{"itemcf_strong": 1, "itemcf_weak": 1, "popular": 22, "semantic": 73, "two_tower": 12}`
- per_source_topk_contribution: `{"popular": 1, "semantic": 11}`
- source_overlap: `{"single_source_candidate_count": 198162, "multi_source_candidate_count": 28539, "multi_source_candidate_rate": 0.125888, "source_pair_counts": {"itemcf_strong+itemcf_weak": 13636, "itemcf_strong+popular": 230, "itemcf_strong+semantic": 117, "itemcf_strong+two_tower": 326, "itemcf_weak+popular": 241, "itemcf_weak+semantic": 118, "itemcf_weak+two_tower": 327, "popular+semantic": 435, "popular+two_tower": 2417, "semantic+two_tower": 12230}}`
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
    "hit_rate_at_k": 0.01683,
    "ndcg_at_k": 0.004386,
    "mrr_at_k": 0.00748,
    "candidate_hit_users": 76,
    "candidate_hit_missed_topk_users": 64,
    "candidate_hit_rank_p50": 21.0,
    "candidate_hit_rank_p90": 61.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.125888,
    "ranking_p95_seconds": 0.000737,
    "candidate_generation_p95_seconds": 0.475504
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.18558,
  "candidate_generation_p95_seconds": 0.475504,
  "ranking_avg_seconds": 0.000555,
  "ranking_p95_seconds": 0.000737,
  "recommendation_avg_seconds": 0.186161,
  "recommendation_p95_seconds": 0.476034,
  "total_run_seconds": 440.408146
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.106592
- candidate_hit_users: 76
- ranked_hit_users: 12
- candidate_hit_missed_topk_users: 64
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 27.25
- candidate_hit_rank_p50: 21.0
- candidate_hit_rank_p90: 61.0
- candidate_hit_source_coverage: `{"itemcf_strong": 1, "itemcf_weak": 1, "popular": 22, "semantic": 73, "two_tower": 12}`

## Ranking Case Summary

- total_hit_cases: 103
- topk_hit_cases: 13
- missed_topk_cases: 90
- semantic_only_items_above_share: 0.580967
- top1_score_gap_avg: 20.138124
- target_source_combinations: `{"itemcf_strong+itemcf_weak": 1, "popular": 20, "popular+two_tower": 1, "semantic": 57, "semantic+two_tower": 4, "two_tower": 7}`
- items_above_source_combinations: `{"semantic": 1514, "popular": 799, "semantic+two_tower": 122, "two_tower": 53, "itemcf_strong+itemcf_weak": 49, "popular+two_tower": 30, "popular+semantic": 15, "itemcf_weak": 10, "itemcf_strong+itemcf_weak+semantic": 3, "itemcf_strong+itemcf_weak+popular": 2, "itemcf_strong": 2, "itemcf_strong+itemcf_weak+popular+semantic": 2, "itemcf_strong+semantic": 2, "itemcf_weak+semantic+two_tower": 1, "popular+semantic+two_tower": 1, "itemcf_strong+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_ablation_no_category
- risk_flags: none
- items:
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B07VVJNG7P score=51.6 sources=semantic
  - B004GYBR30 score=0.936876 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_ablation_no_category
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B013EKI2DY score=35.953283 sources=semantic,popular
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_ablation_no_category
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=2.704684 sources=itemcf_weak,itemcf_strong
