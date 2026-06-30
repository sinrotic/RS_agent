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
    "item_graph": 1.4,
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
  "two_tower_artifact_path": "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json",
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": 30,
  "two_tower_seed_window": 50,
  "two_tower_text_fields": null,
  "two_tower_min_overlap": null,
  "two_tower_recency_decay": null,
  "item_graph_enabled": true,
  "item_graph_artifact_path": null,
  "item_graph_artifact_name": "item_graph_recall.jsonl",
  "item_graph_per_seed": 20,
  "item_graph_per_user": 30,
  "item_graph_seed_window": 20,
  "item_graph_recent_positive_window": 20,
  "item_graph_recent_strong_window": 20,
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
| candidate_hit_rate_at_pool | 0.970333 |
| candidate_hit_users | 1341 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 71.102908 |
| candidate_hit_rank_p50 | 75.0 |
| candidate_hit_rank_p90 | 81.0 |
| candidate_hit_missed_topk_users | 217 |
| ranked_hit_users | 1124 |
| recall_at_k | 0.813314 |
| recall_at_pool | 0.970333 |
| ndcg_at_k | 0.323505 |
| mrr_at_k | 0.17377 |
| map_at_k | 0.17377 |
| hit_rate_at_k | 0.813314 |
| popular_only_hit_rate_at_k | 0.015919 |
| itemcf_only_hit_rate_at_k | 0.910999 |
| hybrid_hit_rate_at_k | 0.813314 |
| hybrid_no_itemcf_hit_rate_at_k | 0.023878 |
| category_diversity_avg | 2.756151 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 24492, "item_graph": 5343, "itemcf_strong": 11857, "itemcf_weak": 12625, "popular": 66068, "semantic": 41460, "two_tower": 16692}`
- topk_source_coverage: `{"category": 1405, "item_graph": 1362, "itemcf_strong": 1292, "itemcf_weak": 1356, "popular": 4420, "semantic": 1600, "two_tower": 1376}`
- per_source_candidate_contribution: `{"category": 36, "item_graph": 1341, "itemcf_strong": 1225, "itemcf_weak": 1301, "popular": 66, "semantic": 65, "two_tower": 922}`
- per_source_topk_contribution: `{"category": 32, "item_graph": 1124, "itemcf_strong": 1054, "itemcf_weak": 1119, "popular": 59, "semantic": 62, "two_tower": 809}`
- source_overlap: `{"single_source_candidate_count": 104651, "multi_source_candidate_count": 33496, "multi_source_candidate_rate": 0.242466, "source_pair_counts": {"category+item_graph": 293, "category+itemcf_strong": 128, "category+itemcf_weak": 135, "category+popular": 15794, "category+semantic": 570, "category+two_tower": 1321, "item_graph+itemcf_strong": 4059, "item_graph+itemcf_weak": 4447, "item_graph+popular": 642, "item_graph+semantic": 173, "item_graph+two_tower": 1133, "itemcf_strong+itemcf_weak": 10907, "itemcf_strong+popular": 216, "itemcf_strong+semantic": 154, "itemcf_strong+two_tower": 1072, "itemcf_weak+popular": 222, "itemcf_weak+semantic": 160, "itemcf_weak+two_tower": 1115, "popular+semantic": 301, "popular+two_tower": 1860, "semantic+two_tower": 4209}}`
- source_diagnostics: `{"users_with_positive_seeds": 1382, "users_with_itemcf_seed_hits": 1382, "users_with_itemcf_raw_candidates": 1382, "itemcf_raw_candidates": 445846, "itemcf_raw_unseen_candidates": 180148, "users_with_item_graph_seed_hits": 1382, "users_with_item_graph_raw_candidates": 1382, "item_graph_raw_candidates": 51396, "item_graph_raw_unseen_candidates": 22252}`

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
    "candidate_hit_rate_at_pool": 0.970333,
    "hit_rate_at_k": 0.813314,
    "ndcg_at_k": 0.323505,
    "mrr_at_k": 0.17377,
    "candidate_hit_users": 1341,
    "candidate_hit_missed_topk_users": 217,
    "candidate_hit_rank_p50": 75.0,
    "candidate_hit_rank_p90": 81.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.242466,
    "ranking_p95_seconds": 0.000616,
    "candidate_generation_p95_seconds": 0.373816
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.166728,
  "candidate_generation_p95_seconds": 0.373816,
  "ranking_avg_seconds": 0.000462,
  "ranking_p95_seconds": 0.000616,
  "recommendation_avg_seconds": 0.167215,
  "recommendation_p95_seconds": 0.374276,
  "total_run_seconds": 235.189254
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.970333
- candidate_hit_users: 1341
- ranked_hit_users: 1124
- candidate_hit_missed_topk_users: 217
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 71.102908
- candidate_hit_rank_p50: 75.0
- candidate_hit_rank_p90: 81.0
- candidate_hit_source_coverage: `{"category": 36, "item_graph": 1341, "itemcf_strong": 1225, "itemcf_weak": 1301, "popular": 66, "semantic": 65, "two_tower": 922}`

## Ranking Case Summary

- total_hit_cases: 1341
- topk_hit_cases: 66
- missed_topk_cases: 1275
- semantic_only_items_above_share: 0.355283
- top1_score_gap_avg: 46.396568
- target_source_combinations: `{"category+item_graph+itemcf_strong+itemcf_weak": 1, "category+item_graph+itemcf_strong+itemcf_weak+popular": 4, "category+item_graph+itemcf_strong+itemcf_weak+popular+two_tower": 8, "category+item_graph+itemcf_strong+itemcf_weak+semantic+two_tower": 1, "category+item_graph+itemcf_strong+itemcf_weak+two_tower": 9, "category+item_graph+itemcf_weak+popular+two_tower": 1, "category+item_graph+popular": 2, "category+item_graph+two_tower": 1, "item_graph": 9, "item_graph+itemcf_strong+itemcf_weak": 367, "item_graph+itemcf_strong+itemcf_weak+popular": 11, "item_graph+itemcf_strong+itemcf_weak+popular+two_tower": 14, "item_graph+itemcf_strong+itemcf_weak+semantic": 2, "item_graph+itemcf_strong+itemcf_weak+semantic+two_tower": 13, "item_graph+itemcf_strong+itemcf_weak+two_tower": 733, "item_graph+itemcf_strong+two_tower": 2, "item_graph+itemcf_weak": 17, "item_graph+itemcf_weak+popular+two_tower": 1, "item_graph+itemcf_weak+two_tower": 57, "item_graph+popular+two_tower": 2, "item_graph+semantic": 1, "item_graph+semantic+two_tower": 1, "item_graph+two_tower": 18}`
- items_above_source_combinations: `{"popular": 40936, "semantic": 33354, "category+popular": 12998, "semantic+two_tower": 3553, "category+popular+two_tower": 667, "popular+two_tower": 603, "category": 372, "category+semantic": 239, "item_graph+popular": 233, "category+popular+semantic": 115, "category+item_graph+popular": 111, "category+semantic+two_tower": 69, "popular+semantic": 53, "category+popular+semantic+two_tower": 51, "category+two_tower": 47, "category+item_graph+popular+two_tower": 45, "item_graph+semantic": 41, "item_graph+itemcf_strong+itemcf_weak": 36, "itemcf_strong+itemcf_weak+popular": 34, "itemcf_strong+itemcf_weak+semantic": 31, "item_graph+popular+two_tower": 25, "item_graph+itemcf_strong+itemcf_weak+popular": 22, "item_graph+itemcf_strong+itemcf_weak+semantic": 21, "category+itemcf_strong+itemcf_weak+popular": 21, "itemcf_strong+itemcf_weak": 20, "itemcf_strong+two_tower": 12, "category+item_graph+itemcf_strong+itemcf_weak+popular": 11, "itemcf_strong+popular": 10, "category+item_graph+itemcf_strong+itemcf_weak+popular+two_tower": 9, "category+item_graph": 9, "itemcf_strong": 9, "item_graph": 9, "itemcf_strong+itemcf_weak+semantic+two_tower": 8, "category+itemcf_strong+itemcf_weak+popular+two_tower": 7, "category+item_graph+popular+semantic": 7, "itemcf_strong+semantic": 6, "itemcf_weak+popular": 6, "itemcf_weak+semantic": 6, "category+itemcf_weak+popular": 5, "category+item_graph+itemcf_strong+itemcf_weak": 5, "item_graph+itemcf_strong+itemcf_weak+popular+two_tower": 5, "category+item_graph+itemcf_strong+itemcf_weak+popular+semantic": 4, "item_graph+itemcf_strong+itemcf_weak+semantic+two_tower": 4, "item_graph+semantic+two_tower": 4, "popular+semantic+two_tower": 4, "item_graph+popular+semantic": 4, "item_graph+itemcf_weak+popular": 4, "itemcf_strong+itemcf_weak+popular+two_tower": 4, "category+itemcf_strong+itemcf_weak+popular+semantic": 3, "category+item_graph+itemcf_weak+popular+two_tower": 3, "category+itemcf_strong+popular": 3, "item_graph+itemcf_strong+itemcf_weak+two_tower": 3, "category+itemcf_strong+itemcf_weak": 2, "category+item_graph+itemcf_weak+popular": 2, "category+item_graph+itemcf_strong+popular": 2, "category+itemcf_weak+popular+two_tower": 2, "itemcf_weak+semantic+two_tower": 2, "item_graph+popular+semantic+two_tower": 1, "category+itemcf_weak+popular+semantic": 1, "category+item_graph+popular+semantic+two_tower": 1, "itemcf_weak+popular+two_tower": 1, "item_graph+itemcf_strong+semantic": 1, "item_graph+itemcf_weak+semantic": 1, "item_graph+itemcf_weak": 1, "item_graph+itemcf_strong+popular": 1, "itemcf_strong+itemcf_weak+two_tower": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_16_lopo_item_graph_pool100
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B09RHJTQTM score=7.482605 sources=itemcf_weak,itemcf_strong,two_tower,item_graph

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_16_lopo_item_graph_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=8.686228 sources=itemcf_weak,itemcf_strong,category,two_tower,item_graph

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_16_lopo_item_graph_pool100
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B074V5CMYK score=6.288742 sources=itemcf_weak,itemcf_strong,two_tower,item_graph
