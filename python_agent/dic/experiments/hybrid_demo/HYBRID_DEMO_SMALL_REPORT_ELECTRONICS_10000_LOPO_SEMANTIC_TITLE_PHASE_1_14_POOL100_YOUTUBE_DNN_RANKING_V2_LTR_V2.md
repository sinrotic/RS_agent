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
  "source_aware_fusion": {},
  "item_feature_rerank": {},
  "ltr_model": {
    "enabled": true,
    "model_path": "outputs/training/ltr/ltr_training_phase_1_14_10000_lopo_semantic_title_pool100_youtube_dnn_ltr_v2/ltr_model.json",
    "score_scale": 1.0,
    "features": {
      "version": "ltr_v2",
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
| candidate_hit_rate_at_pool | 0.956585 |
| candidate_hit_users | 1322 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 9.358548 |
| candidate_hit_rank_p50 | 4.0 |
| candidate_hit_rank_p90 | 15.0 |
| candidate_hit_missed_topk_users | 201 |
| ranked_hit_users | 1121 |
| recall_at_k | 0.811143 |
| recall_at_pool | 0.956585 |
| ndcg_at_k | 0.356047 |
| mrr_at_k | 0.213531 |
| map_at_k | 0.213531 |
| hit_rate_at_k | 0.811143 |
| popular_only_hit_rate_at_k | 0.042692 |
| itemcf_only_hit_rate_at_k | 0.862518 |
| hybrid_hit_rate_at_k | 0.811143 |
| hybrid_no_itemcf_hit_rate_at_k | 0.049928 |
| category_diversity_avg | 1.681621 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 31559, "itemcf_strong": 11480, "itemcf_weak": 11947, "popular": 66364, "semantic": 41460, "two_tower": 16756}`
- topk_source_coverage: `{"category": 1087, "itemcf_strong": 1403, "itemcf_weak": 1449, "popular": 5609, "semantic": 43, "two_tower": 1472}`
- per_source_candidate_contribution: `{"category": 49, "itemcf_strong": 1222, "itemcf_weak": 1294, "popular": 66, "semantic": 65, "two_tower": 919}`
- per_source_topk_contribution: `{"category": 43, "itemcf_strong": 1063, "itemcf_weak": 1118, "popular": 59, "semantic": 34, "two_tower": 790}`
- source_overlap: `{"single_source_candidate_count": 99956, "multi_source_candidate_count": 38191, "multi_source_candidate_rate": 0.276452, "source_pair_counts": {"category+itemcf_strong": 186, "category+itemcf_weak": 190, "category+popular": 22148, "category+semantic": 735, "category+two_tower": 2007, "itemcf_strong+itemcf_weak": 10526, "itemcf_strong+popular": 209, "itemcf_strong+semantic": 149, "itemcf_strong+two_tower": 1064, "itemcf_weak+popular": 213, "itemcf_weak+semantic": 154, "itemcf_weak+two_tower": 1105, "popular+semantic": 301, "popular+two_tower": 1860, "semantic+two_tower": 4209}}`
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
    "candidate_hit_rate_at_pool": 0.956585,
    "hit_rate_at_k": 0.811143,
    "ndcg_at_k": 0.356047,
    "mrr_at_k": 0.213531,
    "candidate_hit_users": 1322,
    "candidate_hit_missed_topk_users": 201,
    "candidate_hit_rank_p50": 4.0,
    "candidate_hit_rank_p90": 15.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.276452,
    "ranking_p95_seconds": 0.002839,
    "candidate_generation_p95_seconds": 0.374258
  },
  "two_tower_strict_promotion_gate": {
    "enabled": true,
    "variant": "youtube_dnn_ranking_v2_ltr_v2",
    "evaluation_mode": "leave_one_positive_out",
    "promotable": false,
    "decision": "lopo_sanity_only_no_promotion",
    "checks": {
      "valid_test_mode": false,
      "semantic_title_baseline_present": true,
      "valid_test_metrics_not_below_semantic_title_baseline": {
        "candidate_hit_rate_at_pool": true,
        "recall_at_pool": true,
        "hit_rate_at_k": true
      },
      "candidate_hit_users_not_down": true,
      "paired_lopo_no_regression": true,
      "candidate_generation_p95_within_budget": false,
      "source_contribution_and_overlap_present": true
    },
    "evidence": {
      "current_metrics": {
        "candidate_hit_rate_at_pool": 0.956585,
        "recall_at_pool": 0.956585,
        "hit_rate_at_k": 0.811143,
        "candidate_hit_users": 1322
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
        "candidate_hit_rate_at_pool": 0.105189,
        "recall_at_pool": 0.042043,
        "hit_rate_at_k": 0.001403,
        "candidate_hit_users": 75
      },
      "paired_lopo_metrics": {
        "candidate_hit_rate_at_pool": 0.956585,
        "recall_at_pool": 0.956585,
        "hit_rate_at_k": 0.811143,
        "candidate_hit_users": 1322
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
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2\\metrics.json",
          "exists": true
        },
        "paired_lopo_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2\\metrics.json",
          "exists": true
        }
      },
      "lopo_checks": {
        "candidate_hit_rate_at_pool": true,
        "recall_at_pool": true,
        "hit_rate_at_k": true
      },
      "candidate_generation_p95_seconds": 0.374258,
      "candidate_generation_p95_seconds_budget": 0.05,
      "two_tower_candidate_contribution": 919,
      "source_overlap": {
        "single_source_candidate_count": 99956,
        "multi_source_candidate_count": 38191,
        "multi_source_candidate_rate": 0.276452,
        "source_pair_counts": {
          "category+itemcf_strong": 186,
          "category+itemcf_weak": 190,
          "category+popular": 22148,
          "category+semantic": 735,
          "category+two_tower": 2007,
          "itemcf_strong+itemcf_weak": 10526,
          "itemcf_strong+popular": 209,
          "itemcf_strong+semantic": 149,
          "itemcf_strong+two_tower": 1064,
          "itemcf_weak+popular": 213,
          "itemcf_weak+semantic": 154,
          "itemcf_weak+two_tower": 1105,
          "popular+semantic": 301,
          "popular+two_tower": 1860,
          "semantic+two_tower": 4209
        }
      }
    }
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.177654,
  "candidate_generation_p95_seconds": 0.374258,
  "ranking_avg_seconds": 0.002103,
  "ranking_p95_seconds": 0.002839,
  "recommendation_avg_seconds": 0.179784,
  "recommendation_p95_seconds": 0.376238,
  "total_run_seconds": 257.37522
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.956585
- candidate_hit_users: 1322
- ranked_hit_users: 1121
- candidate_hit_missed_topk_users: 201
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 9.358548
- candidate_hit_rank_p50: 4.0
- candidate_hit_rank_p90: 15.0
- candidate_hit_source_coverage: `{"category": 49, "itemcf_strong": 1222, "itemcf_weak": 1294, "popular": 66, "semantic": 65, "two_tower": 919}`

## Ranking Case Summary

- total_hit_cases: 1322
- topk_hit_cases: 922
- missed_topk_cases: 400
- semantic_only_items_above_share: 0.006051
- top1_score_gap_avg: 132.415364
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak+popular+semantic": 1, "category+itemcf_strong+itemcf_weak+popular+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "category+popular": 2, "category+popular+two_tower": 1, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 119, "itemcf_strong+itemcf_weak+popular": 2, "itemcf_strong+itemcf_weak+semantic": 6, "itemcf_strong+itemcf_weak+semantic+two_tower": 51, "itemcf_strong+itemcf_weak+two_tower": 125, "itemcf_strong+two_tower": 2, "itemcf_weak": 13, "itemcf_weak+two_tower": 56, "semantic": 1, "semantic+two_tower": 2, "two_tower": 15}`
- items_above_source_combinations: `{"popular": 3180, "itemcf_strong+itemcf_weak": 1519, "category+popular": 1393, "category+popular+two_tower": 527, "two_tower": 521, "category": 497, "itemcf_strong": 104, "popular+two_tower": 99, "semantic+two_tower": 95, "itemcf_weak": 67, "semantic": 50, "category+two_tower": 36, "category+itemcf_strong+itemcf_weak+popular": 23, "category+itemcf_strong+itemcf_weak+popular+two_tower": 20, "itemcf_strong+itemcf_weak+popular": 20, "itemcf_strong+itemcf_weak+two_tower": 16, "category+popular+semantic": 16, "category+itemcf_strong+itemcf_weak": 13, "itemcf_strong+two_tower": 13, "itemcf_strong+itemcf_weak+semantic": 7, "itemcf_weak+two_tower": 7, "category+semantic": 6, "category+itemcf_strong": 6, "category+popular+semantic+two_tower": 5, "category+itemcf_weak+popular+two_tower": 4, "category+semantic+two_tower": 4, "category+itemcf_weak+popular": 3, "category+itemcf_strong+popular": 3, "category+itemcf_weak": 3, "itemcf_strong+itemcf_weak+semantic+two_tower": 2, "itemcf_strong+popular": 1, "itemcf_weak+popular": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "itemcf_strong+itemcf_weak+popular+two_tower": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2_10000_lopo
- risk_flags: none
- items:
  - B07KTYJ769 score=66.137148 sources=popular
  - B07GZFM1ZM score=60.025594 sources=popular
  - B07H65KP63 score=57.721495 sources=popular
  - B09RHJTQTM score=48.682191 sources=itemcf_weak,itemcf_strong,two_tower
  - B0791TX5P5 score=44.525422 sources=popular

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2_10000_lopo
- risk_flags: none
- items:
  - B07KTYJ769 score=66.137148 sources=popular
  - B07GZFM1ZM score=60.025594 sources=popular
  - B07H65KP63 score=57.721495 sources=popular
  - B0791TX5P5 score=44.525422 sources=popular
  - B00KWR8ME2 score=37.956279 sources=itemcf_weak,itemcf_strong,category,two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2_10000_lopo
- risk_flags: none
- items:
  - B07KTYJ769 score=66.137148 sources=popular
  - B07GZFM1ZM score=60.025594 sources=popular
  - B07H65KP63 score=57.721495 sources=popular
  - B0791TX5P5 score=44.525422 sources=popular
  - 993591786X score=40.439071 sources=itemcf_weak,itemcf_strong
