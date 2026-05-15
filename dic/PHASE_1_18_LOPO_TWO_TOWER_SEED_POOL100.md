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
  "item_graph_recent_strong_window": null,
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
| candidate_count_avg | 99.965991 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.957308 |
| candidate_hit_users | 1323 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 74.802721 |
| candidate_hit_rank_p50 | 81.0 |
| candidate_hit_rank_p90 | 87.0 |
| candidate_hit_missed_topk_users | 222 |
| ranked_hit_users | 1101 |
| recall_at_k | 0.796671 |
| recall_at_pool | 0.957308 |
| ndcg_at_k | 0.315901 |
| mrr_at_k | 0.169042 |
| map_at_k | 0.169042 |
| hit_rate_at_k | 0.796671 |
| popular_only_hit_rate_at_k | 0.015919 |
| itemcf_only_hit_rate_at_k | 0.910999 |
| hybrid_hit_rate_at_k | 0.796671 |
| hybrid_no_itemcf_hit_rate_at_k | 0.023878 |
| category_diversity_avg | 2.771346 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 24412, "itemcf_strong": 11950, "itemcf_weak": 12625, "popular": 66067, "semantic": 41460, "two_tower": 16142, "two_tower_seed": 12778}`
- topk_source_coverage: `{"category": 1410, "itemcf_strong": 1294, "itemcf_weak": 1358, "popular": 4390, "semantic": 1629, "two_tower": 1399, "two_tower_seed": 627}`
- per_source_candidate_contribution: `{"category": 36, "itemcf_strong": 1224, "itemcf_weak": 1298, "popular": 66, "semantic": 65, "two_tower": 916, "two_tower_seed": 184}`
- per_source_topk_contribution: `{"category": 32, "itemcf_strong": 1030, "itemcf_weak": 1097, "popular": 58, "semantic": 61, "two_tower": 804, "two_tower_seed": 158}`
- source_overlap: `{"single_source_candidate_count": 96922, "multi_source_candidate_count": 41231, "multi_source_candidate_rate": 0.298444, "source_pair_counts": {"category+itemcf_strong": 128, "category+itemcf_weak": 135, "category+popular": 15794, "category+semantic": 570, "category+two_tower": 1320, "category+two_tower_seed": 658, "itemcf_strong+itemcf_weak": 11003, "itemcf_strong+popular": 216, "itemcf_strong+semantic": 154, "itemcf_strong+two_tower": 1071, "itemcf_strong+two_tower_seed": 338, "itemcf_weak+popular": 222, "itemcf_weak+semantic": 160, "itemcf_weak+two_tower": 1115, "itemcf_weak+two_tower_seed": 357, "popular+semantic": 301, "popular+two_tower": 1860, "popular+two_tower_seed": 475, "semantic+two_tower": 4209, "semantic+two_tower_seed": 7233, "two_tower+two_tower_seed": 7114}}`
- source_diagnostics: `{"users_with_positive_seeds": 1382, "users_with_itemcf_seed_hits": 1382, "users_with_itemcf_raw_candidates": 1382, "itemcf_raw_candidates": 445846, "itemcf_raw_unseen_candidates": 180148, "users_with_item_graph_seed_hits": 0, "users_with_item_graph_raw_candidates": 0, "item_graph_raw_candidates": 0, "item_graph_raw_unseen_candidates": 0, "users_with_two_tower_seed_hits": 1382, "users_with_two_tower_seed_raw_candidates": 1382, "two_tower_seed_raw_candidates": 919500, "two_tower_seed_raw_unseen_candidates": 908652}`

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
    "candidate_hit_rate_at_pool": 0.957308,
    "hit_rate_at_k": 0.796671,
    "ndcg_at_k": 0.315901,
    "mrr_at_k": 0.169042,
    "candidate_hit_users": 1323,
    "candidate_hit_missed_topk_users": 222,
    "candidate_hit_rank_p50": 81.0,
    "candidate_hit_rank_p90": 87.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.298444,
    "ranking_p95_seconds": 0.000712,
    "candidate_generation_p95_seconds": 0.433345
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.163562,
  "candidate_generation_p95_seconds": 0.433345,
  "ranking_avg_seconds": 0.000487,
  "ranking_p95_seconds": 0.000712,
  "recommendation_avg_seconds": 0.164076,
  "recommendation_p95_seconds": 0.433804,
  "total_run_seconds": 233.302407
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.957308
- candidate_hit_users: 1323
- ranked_hit_users: 1101
- candidate_hit_missed_topk_users: 222
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 74.802721
- candidate_hit_rank_p50: 81.0
- candidate_hit_rank_p90: 87.0
- candidate_hit_source_coverage: `{"category": 36, "itemcf_strong": 1224, "itemcf_weak": 1298, "popular": 66, "semantic": 65, "two_tower": 916, "two_tower_seed": 184}`

## Ranking Case Summary

- total_hit_cases: 1323
- topk_hit_cases: 62
- missed_topk_cases: 1261
- semantic_only_items_above_share: 0.295178
- top1_score_gap_avg: 47.997292
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 1, "category+itemcf_strong+itemcf_weak+popular": 3, "category+itemcf_strong+itemcf_weak+popular+two_tower": 7, "category+itemcf_strong+itemcf_weak+popular+two_tower+two_tower_seed": 1, "category+itemcf_strong+itemcf_weak+popular+two_tower_seed": 1, "category+itemcf_strong+itemcf_weak+semantic+two_tower+two_tower_seed": 1, "category+itemcf_strong+itemcf_weak+two_tower": 8, "category+itemcf_strong+itemcf_weak+two_tower+two_tower_seed": 1, "category+itemcf_weak+popular+two_tower": 1, "category+popular": 2, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 357, "itemcf_strong+itemcf_weak+popular": 11, "itemcf_strong+itemcf_weak+popular+two_tower": 14, "itemcf_strong+itemcf_weak+semantic": 2, "itemcf_strong+itemcf_weak+semantic+two_tower": 3, "itemcf_strong+itemcf_weak+semantic+two_tower+two_tower_seed": 13, "itemcf_strong+itemcf_weak+two_tower": 624, "itemcf_strong+itemcf_weak+two_tower+two_tower_seed": 109, "itemcf_strong+itemcf_weak+two_tower_seed": 9, "itemcf_strong+two_tower": 2, "itemcf_weak": 14, "itemcf_weak+popular+two_tower": 2, "itemcf_weak+two_tower": 50, "itemcf_weak+two_tower+two_tower_seed": 7, "itemcf_weak+two_tower_seed": 1, "popular+two_tower": 2, "semantic+two_tower+two_tower_seed": 1, "semantic+two_tower_seed": 1, "two_tower": 11, "two_tower+two_tower_seed": 1}`
- items_above_source_combinations: `{"popular": 43216, "semantic": 28781, "category+popular": 12925, "semantic+two_tower_seed": 4271, "category": 2158, "semantic+two_tower+two_tower_seed": 2154, "semantic+two_tower": 1359, "popular+two_tower": 611, "category+popular+two_tower": 455, "itemcf_strong+itemcf_weak": 260, "category+semantic": 196, "category+popular+two_tower+two_tower_seed": 181, "category+popular+semantic": 100, "category+two_tower": 94, "category+popular+two_tower_seed": 83, "itemcf_strong+itemcf_weak+popular": 57, "popular+semantic": 52, "two_tower+two_tower_seed": 52, "category+semantic+two_tower+two_tower_seed": 47, "category+semantic+two_tower_seed": 39, "itemcf_strong+itemcf_weak+semantic": 32, "category+itemcf_strong+itemcf_weak+popular": 32, "category+two_tower+two_tower_seed": 25, "category+semantic+two_tower": 21, "itemcf_strong": 21, "itemcf_strong+itemcf_weak+semantic+two_tower_seed": 20, "category+two_tower_seed": 17, "category+popular+semantic+two_tower": 17, "itemcf_strong+itemcf_weak+two_tower+two_tower_seed": 15, "category+popular+semantic+two_tower+two_tower_seed": 14, "itemcf_strong+itemcf_weak+two_tower_seed": 13, "popular+two_tower_seed": 12, "category+itemcf_strong+itemcf_weak": 12, "itemcf_strong+popular": 11, "category+popular+semantic+two_tower_seed": 10, "itemcf_weak+popular": 10, "itemcf_strong+itemcf_weak+two_tower": 10, "itemcf_weak": 10, "popular+two_tower+two_tower_seed": 9, "itemcf_strong+itemcf_weak+semantic+two_tower+two_tower_seed": 9, "itemcf_strong+itemcf_weak+popular+two_tower": 9, "itemcf_strong+two_tower": 9, "category+itemcf_strong+itemcf_weak+popular+two_tower+two_tower_seed": 8, "category+itemcf_strong+itemcf_weak+popular+two_tower": 8, "category+itemcf_strong+itemcf_weak+popular+semantic": 7, "category+itemcf_weak+popular": 6, "category+itemcf_strong+popular": 5, "itemcf_strong+semantic": 5, "category+itemcf_weak+popular+two_tower": 4, "itemcf_weak+semantic": 4, "itemcf_strong+itemcf_weak+semantic+two_tower": 3, "itemcf_weak+semantic+two_tower_seed": 3, "itemcf_strong+two_tower+two_tower_seed": 3, "popular+semantic+two_tower": 2, "itemcf_strong+semantic+two_tower_seed": 2, "category+itemcf_strong+itemcf_weak+two_tower_seed": 2, "two_tower": 2, "category+itemcf_weak+popular+semantic+two_tower_seed": 1, "itemcf_weak+popular+two_tower": 1, "popular+semantic+two_tower+two_tower_seed": 1, "category+itemcf_weak+popular+two_tower+two_tower_seed": 1, "itemcf_weak+two_tower+two_tower_seed": 1, "itemcf_weak+semantic+two_tower+two_tower_seed": 1, "category+itemcf_weak+popular+two_tower_seed": 1, "itemcf_weak+semantic+two_tower": 1, "itemcf_strong+itemcf_weak+popular+two_tower_seed": 1, "category+itemcf_strong+itemcf_weak+two_tower+two_tower_seed": 1, "category+itemcf_strong": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_18_lopo_two_tower_seed_pool100
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B09RHJTQTM score=5.382605 sources=itemcf_weak,itemcf_strong,two_tower

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_18_lopo_two_tower_seed_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=6.586228 sources=itemcf_weak,itemcf_strong,category,two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_18_lopo_two_tower_seed_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B074V5CMYK score=4.188742 sources=itemcf_weak,itemcf_strong,two_tower
