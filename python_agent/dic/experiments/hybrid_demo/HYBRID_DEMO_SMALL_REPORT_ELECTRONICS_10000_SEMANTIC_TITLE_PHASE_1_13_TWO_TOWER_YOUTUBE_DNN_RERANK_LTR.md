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
  "source_aware_fusion": {
    "enabled": true,
    "itemcf_source_boost": 8.0,
    "itemcf_multi_source_boost": 4.0,
    "two_tower_source_boost": 0.5,
    "two_tower_multi_source_boost": 1.0,
    "two_tower_itemcf_source_boost": 2.0,
    "two_tower_semantic_source_boost": 1.0,
    "two_tower_only_penalty": 1.0,
    "semantic_only_penalty": 4.0,
    "popular_only_penalty": 2.0
  },
  "item_feature_rerank": {
    "enabled": true,
    "weights": {
      "multi_source": 0.5,
      "two_tower_source": 0.2,
      "two_tower_multi_source": 0.6,
      "two_tower_itemcf_source": 0.8,
      "two_tower_semantic_source": 0.4,
      "two_tower_only": -0.4,
      "semantic_only": -0.5,
      "popular_only": -0.5
    }
  },
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
| candidate_hit_rate_at_pool | 0.077139 |
| candidate_hit_users | 55 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 21.272727 |
| candidate_hit_rank_p50 | 19.0 |
| candidate_hit_rank_p90 | 43.0 |
| candidate_hit_missed_topk_users | 46 |
| ranked_hit_users | 9 |
| recall_at_k | 0.001323 |
| recall_at_pool | 0.031527 |
| ndcg_at_k | 0.002515 |
| mrr_at_k | 0.00561 |
| map_at_k | 0.00114 |
| hit_rate_at_k | 0.012623 |
| popular_only_hit_rate_at_k | 0.007013 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.012623 |
| hybrid_no_itemcf_hit_rate_at_k | 0.02244 |
| category_diversity_avg | 1.692735 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 11356, "itemcf_strong": 14210, "itemcf_weak": 15057, "popular": 31819, "semantic": 57346, "two_tower": 26917}`
- topk_source_coverage: `{"category": 2571, "itemcf_strong": 1834, "itemcf_weak": 1842, "popular": 9442, "semantic": 848, "two_tower": 1349}`
- per_source_candidate_contribution: `{"category": 6, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 8, "semantic": 64, "two_tower": 9}`
- per_source_topk_contribution: `{"category": 4, "popular": 5, "semantic": 4, "two_tower": 2}`
- source_overlap: `{"single_source_candidate_count": 80425, "multi_source_candidate_count": 36575, "multi_source_candidate_rate": 0.312607, "source_pair_counts": {"category+itemcf_strong": 197, "category+itemcf_weak": 204, "category+popular": 9936, "category+semantic": 1081, "category+two_tower": 2665, "itemcf_strong+itemcf_weak": 13022, "itemcf_strong+popular": 222, "itemcf_strong+semantic": 111, "itemcf_strong+two_tower": 311, "itemcf_weak+popular": 232, "itemcf_weak+semantic": 111, "itemcf_weak+two_tower": 309, "popular+semantic": 435, "popular+two_tower": 2212, "semantic+two_tower": 12174}}`
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
    "candidate_hit_rate_at_pool": 0.077139,
    "hit_rate_at_k": 0.012623,
    "ndcg_at_k": 0.002515,
    "mrr_at_k": 0.00561,
    "candidate_hit_users": 55,
    "candidate_hit_missed_topk_users": 46,
    "candidate_hit_rank_p50": 19.0,
    "candidate_hit_rank_p90": 43.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.312607,
    "ranking_p95_seconds": 0.00106,
    "candidate_generation_p95_seconds": 0.374855
  },
  "two_tower_strict_promotion_gate": {
    "enabled": true,
    "variant": "youtube_dnn",
    "evaluation_mode": "valid_test",
    "promotable": false,
    "decision": "default_off_side_lane_only",
    "checks": {
      "valid_test_mode": true,
      "semantic_title_baseline_present": true,
      "valid_test_metrics_not_below_semantic_title_baseline": {
        "candidate_hit_rate_at_pool": false,
        "recall_at_pool": false,
        "hit_rate_at_k": false
      },
      "candidate_hit_users_not_down": false,
      "paired_lopo_no_regression": false,
      "candidate_generation_p95_within_budget": false,
      "source_contribution_and_overlap_present": true
    },
    "evidence": {
      "current_metrics": {
        "candidate_hit_rate_at_pool": 0.077139,
        "recall_at_pool": 0.031527,
        "hit_rate_at_k": 0.012623,
        "candidate_hit_users": 55
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
      "paired_valid_test_metrics": {},
      "paired_lopo_metrics": {},
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
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_semantic_title_phase_1_13_two_tower_youtube_dnn_rerank_ltr\\metrics.json",
          "exists": false
        },
        "paired_lopo_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title_phase_1_13_two_tower_youtube_dnn_rerank_ltr\\metrics.json",
          "exists": false
        }
      },
      "lopo_checks": {},
      "candidate_generation_p95_seconds": 0.374855,
      "candidate_generation_p95_seconds_budget": 0.05,
      "two_tower_candidate_contribution": 9,
      "source_overlap": {
        "single_source_candidate_count": 80425,
        "multi_source_candidate_count": 36575,
        "multi_source_candidate_rate": 0.312607,
        "source_pair_counts": {
          "category+itemcf_strong": 197,
          "category+itemcf_weak": 204,
          "category+popular": 9936,
          "category+semantic": 1081,
          "category+two_tower": 2665,
          "itemcf_strong+itemcf_weak": 13022,
          "itemcf_strong+popular": 222,
          "itemcf_strong+semantic": 111,
          "itemcf_strong+two_tower": 311,
          "itemcf_weak+popular": 232,
          "itemcf_weak+semantic": 111,
          "itemcf_weak+two_tower": 309,
          "popular+semantic": 435,
          "popular+two_tower": 2212,
          "semantic+two_tower": 12174
        }
      }
    }
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.157451,
  "candidate_generation_p95_seconds": 0.374855,
  "ranking_avg_seconds": 0.000787,
  "ranking_p95_seconds": 0.00106,
  "recommendation_avg_seconds": 0.158256,
  "recommendation_p95_seconds": 0.375606,
  "total_run_seconds": 374.899587
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.077139
- candidate_hit_users: 55
- ranked_hit_users: 9
- candidate_hit_missed_topk_users: 46
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 21.272727
- candidate_hit_rank_p50: 19.0
- candidate_hit_rank_p90: 43.0
- candidate_hit_source_coverage: `{"category": 6, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 8, "semantic": 64, "two_tower": 9}`

## Ranking Case Summary

- total_hit_cases: 77
- topk_hit_cases: 9
- missed_topk_cases: 68
- semantic_only_items_above_share: 0.383966
- top1_score_gap_avg: 40.505512
- target_source_combinations: `{"category+popular": 2, "itemcf_strong+itemcf_weak": 1, "popular": 1, "semantic": 57, "semantic+two_tower": 3, "two_tower": 4}`
- items_above_source_combinations: `{"semantic": 637, "itemcf_strong+itemcf_weak": 384, "popular": 204, "category+popular": 176, "semantic+two_tower": 129, "category+popular+two_tower": 22, "itemcf_strong+two_tower": 22, "two_tower": 17, "itemcf_weak": 11, "itemcf_strong+itemcf_weak+two_tower": 9, "category+semantic": 8, "category+popular+semantic": 7, "itemcf_strong+itemcf_weak+semantic": 6, "itemcf_strong+itemcf_weak+popular": 5, "category+itemcf_weak": 4, "popular+two_tower": 3, "category+semantic+two_tower": 2, "category+itemcf_strong+itemcf_weak+popular": 2, "category+itemcf_strong+itemcf_weak+popular+semantic": 2, "category+two_tower": 2, "itemcf_weak+semantic+two_tower": 1, "itemcf_weak+popular": 1, "category+itemcf_strong+popular": 1, "category+itemcf_strong+itemcf_weak": 1, "itemcf_strong+popular": 1, "category+itemcf_strong": 1, "itemcf_strong": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_13_two_tower_youtube_dnn_rerank_ltr_10000_valid_test
- risk_flags: none
- items:
  - B071VDV7NC score=40.135496 sources=category,semantic,popular
  - B005TUQV0E score=27.867181 sources=itemcf_weak,itemcf_strong
  - B00DS4BLLW score=27.867181 sources=itemcf_weak,itemcf_strong
  - B0122TWDH4 score=27.867181 sources=itemcf_weak,itemcf_strong
  - B01DN8TG46 score=27.867181 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_13_two_tower_youtube_dnn_rerank_ltr_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=56.312087 sources=popular
  - B00006IBAK score=26.377179 sources=itemcf_weak,itemcf_strong
  - B00006IEJC score=26.377179 sources=itemcf_weak,itemcf_strong
  - B001UXFT70 score=26.377179 sources=itemcf_weak,itemcf_strong
  - B002GYWHSQ score=26.377179 sources=itemcf_weak,itemcf_strong

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_13_two_tower_youtube_dnn_rerank_ltr_10000_valid_test
- risk_flags: none
- items:
  - B01K8B8YA8 score=56.312087 sources=popular
  - B075X8471B score=48.500504 sources=popular
  - B07KTYJ769 score=46.397348 sources=popular
  - B07GZFM1ZM score=43.971499 sources=popular
  - 993591786X score=27.867181 sources=itemcf_weak,itemcf_strong
