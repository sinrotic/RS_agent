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
  "source_aware_fusion": {},
  "item_feature_rerank": {},
  "ltr_model": {
    "enabled": true,
    "model_path": "outputs/ltr_training_phase_1_14_10000_semantic_title_pool100_youtube_dnn_ltr_v2/ltr_model.json",
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
| candidate_count_avg | 97.936752 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.105189 |
| candidate_hit_users | 75 |
| candidate_hit_rank_min | 2 |
| candidate_hit_rank_avg | 63.32 |
| candidate_hit_rank_p50 | 66.0 |
| candidate_hit_rank_p90 | 88.0 |
| candidate_hit_missed_topk_users | 74 |
| ranked_hit_users | 1 |
| recall_at_k | 2.3e-05 |
| recall_at_pool | 0.042043 |
| ndcg_at_k | 0.0003 |
| mrr_at_k | 0.000701 |
| map_at_k | 0.00014 |
| hit_rate_at_k | 0.001403 |
| popular_only_hit_rate_at_k | 0.001403 |
| itemcf_only_hit_rate_at_k | 0.0 |
| hybrid_hit_rate_at_k | 0.001403 |
| hybrid_no_itemcf_hit_rate_at_k | 0.0 |
| category_diversity_avg | 1.338034 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 48115, "itemcf_strong": 14210, "itemcf_weak": 15057, "popular": 113429, "semantic": 63960, "two_tower": 35676}`
- topk_source_coverage: `{"category": 1267, "itemcf_strong": 1881, "itemcf_weak": 1973, "popular": 3, "semantic": 3, "two_tower": 7834}`
- per_source_candidate_contribution: `{"category": 16, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 23, "semantic": 73, "two_tower": 10}`
- per_source_topk_contribution: `{"two_tower": 1}`
- source_overlap: `{"single_source_candidate_count": 171173, "multi_source_candidate_count": 57999, "multi_source_candidate_rate": 0.253081, "source_pair_counts": {"category+itemcf_strong": 197, "category+itemcf_weak": 204, "category+popular": 31123, "category+semantic": 1082, "category+two_tower": 2932, "itemcf_strong+itemcf_weak": 13022, "itemcf_strong+popular": 222, "itemcf_strong+semantic": 111, "itemcf_strong+two_tower": 311, "itemcf_weak+popular": 232, "itemcf_weak+semantic": 111, "itemcf_weak+two_tower": 309, "popular+semantic": 435, "popular+two_tower": 2417, "semantic+two_tower": 12230}}`
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
    "candidate_hit_rate_at_pool": 0.105189,
    "hit_rate_at_k": 0.001403,
    "ndcg_at_k": 0.0003,
    "mrr_at_k": 0.000701,
    "candidate_hit_users": 75,
    "candidate_hit_missed_topk_users": 74,
    "candidate_hit_rank_p50": 66.0,
    "candidate_hit_rank_p90": 88.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.253081,
    "ranking_p95_seconds": 0.002814,
    "candidate_generation_p95_seconds": 0.472091
  },
  "two_tower_strict_promotion_gate": {
    "enabled": true,
    "variant": "youtube_dnn_ranking_v2_ltr_v2",
    "evaluation_mode": "valid_test",
    "promotable": false,
    "decision": "default_off_side_lane_only",
    "checks": {
      "valid_test_mode": true,
      "semantic_title_baseline_present": true,
      "valid_test_metrics_not_below_semantic_title_baseline": {
        "candidate_hit_rate_at_pool": true,
        "recall_at_pool": true,
        "hit_rate_at_k": false
      },
      "candidate_hit_users_not_down": true,
      "paired_lopo_no_regression": false,
      "candidate_generation_p95_within_budget": false,
      "source_contribution_and_overlap_present": true
    },
    "evidence": {
      "current_metrics": {
        "candidate_hit_rate_at_pool": 0.105189,
        "recall_at_pool": 0.042043,
        "hit_rate_at_k": 0.001403,
        "candidate_hit_users": 75
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
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2\\metrics.json",
          "exists": false
        },
        "paired_lopo_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2\\metrics.json",
          "exists": false
        }
      },
      "lopo_checks": {},
      "candidate_generation_p95_seconds": 0.472091,
      "candidate_generation_p95_seconds_budget": 0.05,
      "two_tower_candidate_contribution": 10,
      "source_overlap": {
        "single_source_candidate_count": 171173,
        "multi_source_candidate_count": 57999,
        "multi_source_candidate_rate": 0.253081,
        "source_pair_counts": {
          "category+itemcf_strong": 197,
          "category+itemcf_weak": 204,
          "category+popular": 31123,
          "category+semantic": 1082,
          "category+two_tower": 2932,
          "itemcf_strong+itemcf_weak": 13022,
          "itemcf_strong+popular": 222,
          "itemcf_strong+semantic": 111,
          "itemcf_strong+two_tower": 311,
          "itemcf_weak+popular": 232,
          "itemcf_weak+semantic": 111,
          "itemcf_weak+two_tower": 309,
          "popular+semantic": 435,
          "popular+two_tower": 2417,
          "semantic+two_tower": 12230
        }
      }
    }
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.176291,
  "candidate_generation_p95_seconds": 0.472091,
  "ranking_avg_seconds": 0.0022,
  "ranking_p95_seconds": 0.002814,
  "recommendation_avg_seconds": 0.178518,
  "recommendation_p95_seconds": 0.474773,
  "total_run_seconds": 428.260855
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.105189
- candidate_hit_users: 75
- ranked_hit_users: 1
- candidate_hit_missed_topk_users: 74
- candidate_hit_rank_min: 2
- candidate_hit_rank_avg: 63.32
- candidate_hit_rank_p50: 66.0
- candidate_hit_rank_p90: 88.0
- candidate_hit_source_coverage: `{"category": 16, "itemcf_strong": 1, "itemcf_weak": 1, "popular": 23, "semantic": 73, "two_tower": 10}`

## Ranking Case Summary

- total_hit_cases: 103
- topk_hit_cases: 1
- missed_topk_cases: 102
- semantic_only_items_above_share: 0.245782
- top1_score_gap_avg: 326.790031
- target_source_combinations: `{"category": 1, "category+popular": 14, "category+popular+two_tower": 1, "itemcf_strong+itemcf_weak": 1, "popular": 8, "semantic": 69, "semantic+two_tower": 4, "two_tower": 4}`
- items_above_source_combinations: `{"semantic": 1646, "popular": 1529, "category+popular": 1166, "two_tower": 785, "itemcf_strong+itemcf_weak": 685, "category": 383, "itemcf_weak": 196, "itemcf_strong": 169, "category+two_tower": 39, "itemcf_strong+two_tower": 26, "semantic+two_tower": 22, "category+popular+two_tower": 19, "itemcf_strong+itemcf_weak+two_tower": 11, "category+itemcf_weak": 6, "popular+two_tower": 5, "itemcf_weak+two_tower": 4, "category+itemcf_strong": 2, "itemcf_weak+popular": 1, "category+itemcf_strong+itemcf_weak": 1, "itemcf_strong+popular": 1, "category+itemcf_weak+popular": 1}`

## Sample Limitations

- Hit-rate metrics only include users with held-out positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2_10000_valid_test
- risk_flags: none
- items:
  - B000UCISZW score=-1.1872 sources=two_tower
  - B01LYOG5D1 score=-1.193829 sources=two_tower
  - B078BYWZSF score=-1.195454 sources=two_tower
  - B003YJZBJ4 score=-1.197302 sources=two_tower
  - B005TUQV0E score=-7.463793 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2_10000_valid_test
- risk_flags: none
- items:
  - B002U0KE8Q score=-0.55625 sources=itemcf_strong
  - B00884RNKK score=-0.55625 sources=itemcf_strong
  - B003BUHXK6 score=-0.99375 sources=itemcf_weak
  - B0896VGNF7 score=-1.223176 sources=two_tower
  - B00E1CRC86 score=-1.224355 sources=two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2_10000_valid_test
- risk_flags: none
- items:
  - B0002F67N2 score=-0.9125 sources=category
  - B001U2DPUE score=-0.9125 sources=category
  - B007RBSWAK score=-0.9125 sources=category
  - B00X0G30MQ score=-0.9125 sources=category
  - 993591786X score=-7.463793 sources=itemcf_weak,itemcf_strong
