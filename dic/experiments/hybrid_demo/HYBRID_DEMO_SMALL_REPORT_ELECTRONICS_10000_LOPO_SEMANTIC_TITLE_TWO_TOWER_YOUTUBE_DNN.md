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
| candidate_count_avg | 50.0 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.954414 |
| candidate_hit_users | 1319 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 34.783169 |
| candidate_hit_rank_p50 | 39.0 |
| candidate_hit_rank_p90 | 49.0 |
| candidate_hit_missed_topk_users | 229 |
| ranked_hit_users | 1090 |
| recall_at_k | 0.788712 |
| recall_at_pool | 0.954414 |
| ndcg_at_k | 0.31247 |
| mrr_at_k | 0.166932 |
| map_at_k | 0.166932 |
| hit_rate_at_k | 0.788712 |
| popular_only_hit_rate_at_k | 0.026773 |
| itemcf_only_hit_rate_at_k | 0.887844 |
| hybrid_hit_rate_at_k | 0.788712 |
| hybrid_no_itemcf_hit_rate_at_k | 0.02822 |
| category_diversity_avg | 2.722865 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 6752, "itemcf_strong": 11480, "itemcf_weak": 11947, "popular": 12655, "semantic": 36463, "two_tower": 14596}`
- topk_source_coverage: `{"category": 1796, "itemcf_strong": 1306, "itemcf_weak": 1350, "popular": 4029, "semantic": 1984, "two_tower": 1491}`
- per_source_candidate_contribution: `{"category": 47, "itemcf_strong": 1222, "itemcf_weak": 1294, "popular": 64, "semantic": 64, "two_tower": 919}`
- per_source_topk_contribution: `{"category": 43, "itemcf_strong": 1029, "itemcf_weak": 1086, "popular": 59, "semantic": 61, "two_tower": 798}`
- source_overlap: `{"single_source_candidate_count": 47446, "multi_source_candidate_count": 21654, "multi_source_candidate_rate": 0.313372, "source_pair_counts": {"category+itemcf_strong": 186, "category+itemcf_weak": 190, "category+popular": 5743, "category+semantic": 734, "category+two_tower": 1870, "itemcf_strong+itemcf_weak": 10526, "itemcf_strong+popular": 209, "itemcf_strong+semantic": 149, "itemcf_strong+two_tower": 1064, "itemcf_weak+popular": 213, "itemcf_weak+semantic": 154, "itemcf_weak+two_tower": 1105, "popular+semantic": 301, "popular+two_tower": 1703, "semantic+two_tower": 4194}}`
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
    "candidate_pool_size": 50,
    "candidate_hit_rate_at_pool": 0.954414,
    "hit_rate_at_k": 0.788712,
    "ndcg_at_k": 0.31247,
    "mrr_at_k": 0.166932,
    "candidate_hit_users": 1319,
    "candidate_hit_missed_topk_users": 229,
    "candidate_hit_rank_p50": 39.0,
    "candidate_hit_rank_p90": 49.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.313372,
    "ranking_p95_seconds": 0.000405,
    "candidate_generation_p95_seconds": 0.400579
  },
  "two_tower_strict_promotion_gate": {
    "enabled": true,
    "variant": "youtube_dnn",
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
        "candidate_hit_rate_at_pool": 0.954414,
        "recall_at_pool": 0.954414,
        "hit_rate_at_k": 0.788712,
        "candidate_hit_users": 1319
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
        "candidate_hit_rate_at_pool": 0.077139,
        "recall_at_pool": 0.031527,
        "hit_rate_at_k": 0.023843,
        "candidate_hit_users": 55
      },
      "paired_lopo_metrics": {
        "candidate_hit_rate_at_pool": 1.0,
        "recall_at_pool": 1.0,
        "hit_rate_at_k": 0.818182,
        "candidate_hit_users": 22
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
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_semantic_title_two_tower_youtube_dnn\\metrics.json",
          "exists": true
        },
        "paired_lopo_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title_two_tower_youtube_dnn\\metrics.json",
          "exists": true
        }
      },
      "lopo_checks": {
        "candidate_hit_rate_at_pool": true,
        "recall_at_pool": true,
        "hit_rate_at_k": true
      },
      "candidate_generation_p95_seconds": 0.400579,
      "candidate_generation_p95_seconds_budget": 0.05,
      "two_tower_candidate_contribution": 919,
      "source_overlap": {
        "single_source_candidate_count": 47446,
        "multi_source_candidate_count": 21654,
        "multi_source_candidate_rate": 0.313372,
        "source_pair_counts": {
          "category+itemcf_strong": 186,
          "category+itemcf_weak": 190,
          "category+popular": 5743,
          "category+semantic": 734,
          "category+two_tower": 1870,
          "itemcf_strong+itemcf_weak": 10526,
          "itemcf_strong+popular": 209,
          "itemcf_strong+semantic": 149,
          "itemcf_strong+two_tower": 1064,
          "itemcf_weak+popular": 213,
          "itemcf_weak+semantic": 154,
          "itemcf_weak+two_tower": 1105,
          "popular+semantic": 301,
          "popular+two_tower": 1703,
          "semantic+two_tower": 4194
        }
      }
    }
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.200372,
  "candidate_generation_p95_seconds": 0.400579,
  "ranking_avg_seconds": 0.000279,
  "ranking_p95_seconds": 0.000405,
  "recommendation_avg_seconds": 0.200672,
  "recommendation_p95_seconds": 0.400807,
  "total_run_seconds": 280.660962
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.954414
- candidate_hit_users: 1319
- ranked_hit_users: 1090
- candidate_hit_missed_topk_users: 229
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 34.783169
- candidate_hit_rank_p50: 39.0
- candidate_hit_rank_p90: 49.0
- candidate_hit_source_coverage: `{"category": 47, "itemcf_strong": 1222, "itemcf_weak": 1294, "popular": 64, "semantic": 64, "two_tower": 919}`

## Ranking Case Summary

- total_hit_cases: 1319
- topk_hit_cases: 63
- missed_topk_cases: 1256
- semantic_only_items_above_share: 0.640344
- top1_score_gap_avg: 49.189671
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 2, "category+itemcf_strong+itemcf_weak+popular": 5, "category+itemcf_strong+itemcf_weak+popular+two_tower": 12, "category+itemcf_strong+itemcf_weak+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 10, "category+itemcf_weak+popular+two_tower": 1, "category+popular+two_tower": 1, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 363, "itemcf_strong+itemcf_weak+popular": 10, "itemcf_strong+itemcf_weak+popular+two_tower": 7, "itemcf_strong+itemcf_weak+semantic": 1, "itemcf_strong+itemcf_weak+semantic+two_tower": 20, "itemcf_strong+itemcf_weak+two_tower": 732, "itemcf_strong+two_tower": 2, "itemcf_weak": 13, "itemcf_weak+popular+two_tower": 1, "itemcf_weak+two_tower": 57, "popular+two_tower": 1, "semantic+two_tower": 1, "two_tower": 15}`
- items_above_source_combinations: `{"semantic": 28446, "popular": 5944, "category+popular": 3758, "semantic+two_tower": 3503, "category+popular+two_tower": 939, "itemcf_strong+itemcf_weak": 520, "category+semantic": 348, "popular+two_tower": 225, "category+popular+semantic": 137, "category+two_tower": 124, "category+semantic+two_tower": 75, "itemcf_strong+itemcf_weak+semantic": 47, "itemcf_strong+itemcf_weak+popular": 46, "category+itemcf_strong+itemcf_weak+popular": 36, "itemcf_strong": 35, "category+popular+semantic+two_tower": 31, "popular+semantic": 25, "category+itemcf_strong+itemcf_weak": 22, "category+itemcf_strong+itemcf_weak+popular+two_tower": 22, "itemcf_weak": 22, "itemcf_strong+itemcf_weak+two_tower": 15, "itemcf_strong+itemcf_weak+semantic+two_tower": 12, "itemcf_strong+two_tower": 12, "category+itemcf_weak+popular": 10, "itemcf_strong+popular": 8, "category+itemcf_strong+itemcf_weak+popular+semantic": 7, "category+itemcf_strong+popular": 7, "itemcf_weak+semantic": 7, "itemcf_strong+semantic": 6, "category+itemcf_weak+popular+two_tower": 5, "itemcf_weak+popular": 5, "category+itemcf_strong": 5, "popular+semantic+two_tower": 4, "two_tower": 4, "category+itemcf_weak": 3, "itemcf_weak+semantic+two_tower": 2, "category+itemcf_weak+popular+semantic": 1, "category+itemcf_strong+two_tower": 1, "itemcf_weak+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "category+itemcf_strong+semantic": 1, "itemcf_strong+itemcf_weak+popular+two_tower": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_12_two_tower_youtube_dnn_10000_lopo
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B09RHJTQTM score=5.382605 sources=itemcf_weak,itemcf_strong,two_tower

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_12_two_tower_youtube_dnn_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=6.586228 sources=itemcf_weak,itemcf_strong,category,two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_12_two_tower_youtube_dnn_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B074V5CMYK score=4.188742 sources=itemcf_weak,itemcf_strong,two_tower
