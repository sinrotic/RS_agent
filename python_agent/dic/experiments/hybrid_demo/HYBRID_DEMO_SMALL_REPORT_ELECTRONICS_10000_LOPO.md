# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_10000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_10000",
  "evaluation_mode": "leave_one_positive_out",
  "top_k": 5,
  "candidate_pool_size": 50,
  "limit_users": null,
  "rank_weights": {
    "popular": 1.0,
    "itemcf_weak": 2.0,
    "itemcf_strong": 2.5,
    "category": 0.8,
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  },
  "rerank_policy": {},
  "source_aware_fusion": {},
  "item_feature_rerank": {},
  "ltr_model": {},
  "topk_source_minimums": {
    "itemcf": 1
  },
  "candidate_source_minimums": {},
  "semantic_enabled": false,
  "semantic_per_user": null,
  "semantic_min_overlap": null,
  "semantic_score_mode": "raw",
  "semantic_category_weight": 2.0,
  "semantic_text_fields": null,
  "two_tower_enabled": false,
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": null,
  "two_tower_seed_window": null,
  "two_tower_text_fields": null,
  "two_tower_min_overlap": null,
  "two_tower_recency_decay": null,
  "lopo_input_users": 2340,
  "lopo_eligible_users": 1382,
  "lopo_skipped_users_fewer_than_2_positives": 958
}
```

## Metrics and Ablation

| Metric | Value |
| --- | --- |
| evaluation_mode | leave_one_positive_out |
| users_total | 1382 |
| users_with_holdout | 1382 |
| users_evaluated | 1382 |
| lopo_input_users | 2340 |
| lopo_eligible_users | 1382 |
| lopo_skipped_users_fewer_than_2_positives | 958 |
| hit_rate_denominator | users_with_holdout |
| candidate_count_avg | 50.0 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.053546 |
| candidate_hit_users | 74 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 15.594595 |
| candidate_hit_rank_p50 | 9.5 |
| candidate_hit_rank_p90 | 43.0 |
| candidate_hit_missed_topk_users | 6 |
| ranked_hit_users | 68 |
| recall_at_k | 0.049204 |
| recall_at_pool | 0.053546 |
| ndcg_at_k | 0.021468 |
| mrr_at_k | 0.012856 |
| map_at_k | 0.012856 |
| hit_rate_at_k | 0.049204 |
| popular_only_hit_rate_at_k | 0.015919 |
| itemcf_only_hit_rate_at_k | 0.04848 |
| hybrid_hit_rate_at_k | 0.049204 |
| hybrid_no_itemcf_hit_rate_at_k | 0.016643 |
| category_diversity_avg | 1.895803 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 22553, "itemcf_strong": 232, "itemcf_weak": 232, "popular": 68711}`
- topk_source_coverage: `{"category": 1982, "itemcf_strong": 179, "itemcf_weak": 180, "popular": 6889}`
- per_source_candidate_contribution: `{"category": 42, "itemcf_strong": 63, "itemcf_weak": 67, "popular": 66}`
- per_source_topk_contribution: `{"category": 38, "itemcf_strong": 61, "itemcf_weak": 65, "popular": 60}`
- source_overlap: `{"single_source_candidate_count": 46812, "multi_source_candidate_count": 22288, "multi_source_candidate_rate": 0.322547, "source_pair_counts": {"category+itemcf_strong": 138, "category+itemcf_weak": 141, "category+popular": 22166, "itemcf_strong+itemcf_weak": 205, "itemcf_strong+popular": 209, "itemcf_weak+popular": 213}}`
- source_diagnostics: `{"users_with_positive_seeds": 1382, "users_with_itemcf_seed_hits": 1382, "users_with_itemcf_raw_candidates": 1382, "itemcf_raw_candidates": 445846, "itemcf_raw_unseen_candidates": 180148}`

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
    "candidate_hit_rate_at_pool": 0.053546,
    "hit_rate_at_k": 0.049204,
    "ndcg_at_k": 0.021468,
    "mrr_at_k": 0.012856,
    "candidate_hit_users": 74,
    "candidate_hit_missed_topk_users": 6,
    "candidate_hit_rank_p50": 9.5,
    "candidate_hit_rank_p90": 43.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.322547,
    "ranking_p95_seconds": 0.000358
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.000546,
  "candidate_generation_p95_seconds": 0.000775,
  "ranking_avg_seconds": 0.000245,
  "ranking_p95_seconds": 0.000358,
  "recommendation_avg_seconds": 0.000803,
  "recommendation_p95_seconds": 0.001087,
  "total_run_seconds": 4.013416
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.053546
- candidate_hit_users: 74
- ranked_hit_users: 68
- candidate_hit_missed_topk_users: 6
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 15.594595
- candidate_hit_rank_p50: 9.5
- candidate_hit_rank_p90: 43.0
- candidate_hit_source_coverage: `{"category": 42, "itemcf_strong": 63, "itemcf_weak": 67, "popular": 66}`

## Ranking Case Summary

- total_hit_cases: 74
- topk_hit_cases: 25
- missed_topk_cases: 49
- semantic_only_items_above_share: 0.0
- top1_score_gap_avg: 39.013127
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 7, "category+itemcf_strong+itemcf_weak+popular": 20, "category+itemcf_weak+popular": 1, "category+popular": 3, "itemcf_strong+itemcf_weak": 1, "itemcf_strong+itemcf_weak+popular": 15, "itemcf_weak+popular": 1, "popular": 1}`
- items_above_source_combinations: `{"popular": 585, "category+popular": 433, "category+itemcf_strong+itemcf_weak+popular": 2, "category": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_5_deterministic_hybrid_demo_10000
- risk_flags: none
- items:
  - B087S2JRXY score=51.542975 sources=category,popular
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_5_deterministic_hybrid_demo_10000
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=5.75 sources=itemcf_weak,itemcf_strong,category

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_5_deterministic_hybrid_demo_10000
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B087S2JRXY score=34.742975 sources=popular
