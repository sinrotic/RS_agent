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
    "two_tower": 1.2,
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  },
  "rerank_policy": {},
  "source_aware_fusion": {},
  "item_feature_rerank": {},
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
  "two_tower_variant": "dssm",
  "two_tower_artifact_path": "outputs/two_tower_training/dssm/artifact_manifest.json",
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": 30,
  "two_tower_seed_window": 10,
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
| candidate_count_avg | 50.0 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.071529 |
| candidate_hit_users | 51 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 14.0 |
| candidate_hit_rank_p50 | 11.0 |
| candidate_hit_rank_p90 | 29.0 |
| candidate_hit_missed_topk_users | 35 |
| ranked_hit_users | 16 |
| recall_at_k | 0.007525 |
| recall_at_pool | 0.029375 |
| ndcg_at_k | 0.006524 |
| mrr_at_k | 0.011244 |
| map_at_k | 0.003518 |
| hit_rate_at_k | 0.02244 |
| popular_only_hit_rate_at_k | 0.004208 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.02244 |
| hybrid_no_itemcf_hit_rate_at_k | 0.023843 |
| category_diversity_avg | 2.389744 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 9530, "itemcf_strong": 14218, "itemcf_weak": 15065, "popular": 30007, "semantic": 57159, "two_tower": 27787}`
- topk_source_coverage: `{"category": 2118, "itemcf_strong": 973, "itemcf_weak": 988, "popular": 7428, "semantic": 3810, "two_tower": 556}`
- per_source_candidate_contribution: `{"category": 3, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 5, "semantic": 64, "two_tower": 4}`
- per_source_topk_contribution: `{"category": 2, "popular": 3, "semantic": 14}`
- source_overlap: `{"single_source_candidate_count": 81790, "multi_source_candidate_count": 35210, "multi_source_candidate_rate": 0.30094, "source_pair_counts": {"category+itemcf_strong": 197, "category+itemcf_weak": 204, "category+popular": 8368, "category+semantic": 1082, "category+two_tower": 953, "itemcf_strong+itemcf_weak": 13038, "itemcf_strong+popular": 222, "itemcf_strong+semantic": 111, "itemcf_strong+two_tower": 117, "itemcf_weak+popular": 232, "itemcf_weak+semantic": 111, "itemcf_weak+two_tower": 118, "popular+semantic": 435, "popular+two_tower": 828, "semantic+two_tower": 12495}}`
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
    "candidate_hit_rate_at_pool": 0.071529,
    "hit_rate_at_k": 0.02244,
    "ndcg_at_k": 0.006524,
    "mrr_at_k": 0.011244,
    "candidate_hit_users": 51,
    "candidate_hit_missed_topk_users": 35,
    "candidate_hit_rank_p50": 11.0,
    "candidate_hit_rank_p90": 29.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.30094,
    "ranking_p95_seconds": 0.00039,
    "candidate_generation_p95_seconds": 0.430508
  },
  "two_tower_strict_promotion_gate": {
    "enabled": true,
    "variant": "dssm",
    "evaluation_mode": "valid_test",
    "promotable": false,
    "decision": "default_off_side_lane_only",
    "checks": {
      "valid_test_mode": true,
      "semantic_title_baseline_present": true,
      "valid_test_metrics_not_below_semantic_title_baseline": {
        "candidate_hit_rate_at_pool": false,
        "recall_at_pool": false,
        "hit_rate_at_k": true
      },
      "candidate_hit_users_not_down": false,
      "paired_lopo_no_regression": false,
      "candidate_generation_p95_within_budget": false,
      "source_contribution_and_overlap_present": true
    },
    "evidence": {
      "current_metrics": {
        "candidate_hit_rate_at_pool": 0.071529,
        "recall_at_pool": 0.029375,
        "hit_rate_at_k": 0.02244,
        "candidate_hit_users": 51
      },
      "semantic_title_baseline_metrics": {
        "candidate_hit_rate_at_pool": 0.084151,
        "recall_at_pool": 0.034086,
        "hit_rate_at_k": 0.019635,
        "candidate_hit_users": 60
      },
      "semantic_title_lopo_baseline_metrics": {
        "candidate_hit_rate_at_pool": 0.939219,
        "recall_at_pool": 0.939219,
        "hit_rate_at_k": 0.755427,
        "candidate_hit_users": 1298
      },
      "paired_valid_test_metrics": {
        "candidate_hit_rate_at_pool": 0.071529,
        "recall_at_pool": 0.029375,
        "hit_rate_at_k": 0.02244,
        "candidate_hit_users": 51
      },
      "paired_lopo_metrics": {
        "candidate_hit_rate_at_pool": 0.938495,
        "recall_at_pool": 0.938495,
        "hit_rate_at_k": 0.762663,
        "candidate_hit_users": 1297
      },
      "evidence_paths": {
        "semantic_title_baseline_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_semantic_title\\metrics.json",
          "exists": true
        },
        "semantic_title_lopo_baseline_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title\\metrics.json",
          "exists": true
        },
        "paired_valid_test_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_semantic_title_two_tower_dssm\\metrics.json",
          "exists": true
        },
        "paired_lopo_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title_two_tower_dssm\\metrics.json",
          "exists": true
        }
      },
      "lopo_checks": {
        "candidate_hit_rate_at_pool": false,
        "recall_at_pool": false,
        "hit_rate_at_k": true
      },
      "candidate_generation_p95_seconds": 0.430508,
      "candidate_generation_p95_seconds_budget": 0.05,
      "two_tower_candidate_contribution": 4,
      "source_overlap": {
        "single_source_candidate_count": 81790,
        "multi_source_candidate_count": 35210,
        "multi_source_candidate_rate": 0.30094,
        "source_pair_counts": {
          "category+itemcf_strong": 197,
          "category+itemcf_weak": 204,
          "category+popular": 8368,
          "category+semantic": 1082,
          "category+two_tower": 953,
          "itemcf_strong+itemcf_weak": 13038,
          "itemcf_strong+popular": 222,
          "itemcf_strong+semantic": 111,
          "itemcf_strong+two_tower": 117,
          "itemcf_weak+popular": 232,
          "itemcf_weak+semantic": 111,
          "itemcf_weak+two_tower": 118,
          "popular+semantic": 435,
          "popular+two_tower": 828,
          "semantic+two_tower": 12495
        }
      }
    }
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.18865,
  "candidate_generation_p95_seconds": 0.430508,
  "ranking_avg_seconds": 0.000279,
  "ranking_p95_seconds": 0.00039,
  "recommendation_avg_seconds": 0.188949,
  "recommendation_p95_seconds": 0.430865,
  "total_run_seconds": 445.981703
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.071529
- candidate_hit_users: 51
- ranked_hit_users: 16
- candidate_hit_missed_topk_users: 35
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 14.0
- candidate_hit_rank_p50: 11.0
- candidate_hit_rank_p90: 29.0
- candidate_hit_source_coverage: `{"category": 3, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 5, "semantic": 64, "two_tower": 4}`

## Ranking Case Summary

- total_hit_cases: 71
- topk_hit_cases: 18
- missed_topk_cases: 53
- semantic_only_items_above_share: 0.667373
- top1_score_gap_avg: 16.936223
- target_source_combinations: `{"category+popular": 1, "itemcf_strong+itemcf_weak": 1, "popular": 1, "semantic": 46, "semantic+two_tower": 3, "two_tower": 1}`
- items_above_source_combinations: `{"semantic": 630, "popular": 145, "semantic+two_tower": 88, "category+popular": 54, "itemcf_strong+itemcf_weak": 7, "category+semantic": 6, "category+popular+semantic": 5, "itemcf_strong+itemcf_weak+semantic": 3, "category+semantic+two_tower": 2, "category+itemcf_strong+itemcf_weak+popular": 1, "itemcf_weak+semantic+two_tower": 1, "itemcf_strong+itemcf_weak+popular": 1, "two_tower": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_12_two_tower_dssm_10000_valid_test
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B005TUQV0E score=3.181982 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_12_two_tower_dssm_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B013EKI2DY score=35.953283 sources=semantic,popular
  - B0B23LRBRP score=34.578289 sources=semantic,two_tower
  - B00006IBAK score=2.25 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_12_two_tower_dssm_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - 993591786X score=3.181982 sources=itemcf_weak,itemcf_strong
