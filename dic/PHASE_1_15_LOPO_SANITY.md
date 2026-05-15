# Hybrid Demo Small Report

## Config Summary

```json
{
  "clean_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_clean_10000",
  "views_dir": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\processed\\amazon_2023_recall_views_10000",
  "evaluation_mode": "leave_one_positive_out",
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
| candidate_count_avg | 99.96165 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.959479 |
| candidate_hit_users | 1326 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 74.888386 |
| candidate_hit_rank_p50 | 81.0 |
| candidate_hit_rank_p90 | 87.0 |
| candidate_hit_missed_topk_users | 223 |
| ranked_hit_users | 1103 |
| recall_at_k | 0.798119 |
| recall_at_pool | 0.959479 |
| ndcg_at_k | 0.315763 |
| mrr_at_k | 0.168415 |
| map_at_k | 0.168415 |
| hit_rate_at_k | 0.798119 |
| popular_only_hit_rate_at_k | 0.015919 |
| itemcf_only_hit_rate_at_k | 0.910999 |
| hybrid_hit_rate_at_k | 0.798119 |
| hybrid_no_itemcf_hit_rate_at_k | 0.023878 |
| category_diversity_avg | 2.758321 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 24475, "itemcf_strong": 11953, "itemcf_weak": 12630, "popular": 66089, "semantic": 41460, "two_tower": 16757}`
- topk_source_coverage: `{"category": 1411, "itemcf_strong": 1292, "itemcf_weak": 1356, "popular": 4417, "semantic": 1603, "two_tower": 1375}`
- per_source_candidate_contribution: `{"category": 36, "itemcf_strong": 1224, "itemcf_weak": 1298, "popular": 66, "semantic": 65, "two_tower": 919}`
- per_source_topk_contribution: `{"category": 32, "itemcf_strong": 1032, "itemcf_weak": 1099, "popular": 58, "semantic": 60, "two_tower": 801}`
- source_overlap: `{"single_source_candidate_count": 105614, "multi_source_candidate_count": 32533, "multi_source_candidate_rate": 0.235496, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 135, "category+popular": 15794, "category+semantic": 570, "category+two_tower": 1321, "itemcf_strong+itemcf_weak": 11011, "itemcf_strong+popular": 216, "itemcf_strong+semantic": 154, "itemcf_strong+two_tower": 1071, "itemcf_weak+popular": 222, "itemcf_weak+semantic": 160, "itemcf_weak+two_tower": 1115, "popular+semantic": 301, "popular+two_tower": 1860, "semantic+two_tower": 4209}}`
- source_diagnostics: `{"users_with_positive_seeds": 1382, "users_with_itemcf_seed_hits": 1382, "users_with_itemcf_raw_candidates": 1382, "itemcf_raw_candidates": 445846, "itemcf_raw_unseen_candidates": 180148}`

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
    "candidate_hit_rate_at_pool": 0.959479,
    "hit_rate_at_k": 0.798119,
    "ndcg_at_k": 0.315763,
    "mrr_at_k": 0.168415,
    "candidate_hit_users": 1326,
    "candidate_hit_missed_topk_users": 223,
    "candidate_hit_rank_p50": 81.0,
    "candidate_hit_rank_p90": 87.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.235496,
    "ranking_p95_seconds": 0.000737,
    "candidate_generation_p95_seconds": 0.39457
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.190127,
  "candidate_generation_p95_seconds": 0.39457,
  "ranking_avg_seconds": 0.000535,
  "ranking_p95_seconds": 0.000737,
  "recommendation_avg_seconds": 0.190689,
  "recommendation_p95_seconds": 0.395155,
  "total_run_seconds": 267.860021
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.959479
- candidate_hit_users: 1326
- ranked_hit_users: 1103
- candidate_hit_missed_topk_users: 223
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 74.888386
- candidate_hit_rank_p50: 81.0
- candidate_hit_rank_p90: 87.0
- candidate_hit_source_coverage: `{"category": 36, "itemcf_strong": 1224, "itemcf_weak": 1298, "popular": 66, "semantic": 65, "two_tower": 919}`

## Ranking Case Summary

- total_hit_cases: 1326
- topk_hit_cases: 59
- missed_topk_cases: 1267
- semantic_only_items_above_share: 0.338679
- top1_score_gap_avg: 48.011573
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 1, "category+itemcf_strong+itemcf_weak+popular": 4, "category+itemcf_strong+itemcf_weak+popular+two_tower": 8, "category+itemcf_strong+itemcf_weak+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 9, "category+itemcf_weak+popular+two_tower": 1, "category+popular": 2, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 366, "itemcf_strong+itemcf_weak+popular": 11, "itemcf_strong+itemcf_weak+popular+two_tower": 14, "itemcf_strong+itemcf_weak+semantic": 2, "itemcf_strong+itemcf_weak+semantic+two_tower": 19, "itemcf_strong+itemcf_weak+two_tower": 733, "itemcf_strong+two_tower": 2, "itemcf_weak": 15, "itemcf_weak+popular+two_tower": 2, "itemcf_weak+two_tower": 57, "popular+two_tower": 2, "semantic": 1, "semantic+two_tower": 1, "two_tower": 15}`
- items_above_source_combinations: `{"popular": 43374, "semantic": 33138, "category+popular": 13037, "semantic+two_tower": 3527, "category": 2253, "category+popular+two_tower": 636, "popular+two_tower": 626, "itemcf_strong+itemcf_weak": 295, "category+semantic": 236, "category+two_tower": 116, "category+popular+semantic": 110, "category+semantic+two_tower": 68, "itemcf_strong+itemcf_weak+popular": 58, "popular+semantic": 53, "itemcf_strong+itemcf_weak+semantic": 52, "itemcf_strong": 35, "category+itemcf_strong+itemcf_weak+popular": 33, "category+popular+semantic+two_tower": 31, "itemcf_strong+itemcf_weak+two_tower": 18, "category+itemcf_strong+itemcf_weak": 16, "category+itemcf_strong+itemcf_weak+popular+two_tower": 16, "itemcf_strong+itemcf_weak+semantic+two_tower": 12, "itemcf_strong+two_tower": 12, "itemcf_strong+popular": 11, "itemcf_weak+popular": 10, "itemcf_weak": 10, "itemcf_strong+itemcf_weak+popular+two_tower": 9, "itemcf_strong+semantic": 7, "category+itemcf_weak+popular": 7, "category+itemcf_strong+itemcf_weak+popular+semantic": 7, "itemcf_weak+semantic": 7, "category+itemcf_weak+popular+two_tower": 5, "category+itemcf_strong+popular": 5, "popular+semantic+two_tower": 4, "two_tower": 4, "itemcf_weak+semantic+two_tower": 2, "category+itemcf_weak+popular+semantic": 1, "itemcf_weak+popular+two_tower": 1, "itemcf_weak+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "category+itemcf_strong": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_15_lopo_sanity
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B09RHJTQTM score=5.382605 sources=itemcf_weak,itemcf_strong,two_tower

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_15_lopo_sanity
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=6.586228 sources=itemcf_weak,itemcf_strong,category,two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_15_lopo_sanity
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B074V5CMYK score=4.188742 sources=itemcf_weak,itemcf_strong,two_tower
