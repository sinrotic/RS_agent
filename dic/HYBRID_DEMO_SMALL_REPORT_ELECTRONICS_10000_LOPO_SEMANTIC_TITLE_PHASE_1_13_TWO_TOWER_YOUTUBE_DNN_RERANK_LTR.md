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
    "model_path": "outputs/ltr_training_10000_lopo_semantic_title/ltr_model.json",
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
| candidate_count_avg | 50.0 |
| fallback_rate | 0.0 |
| candidate_hit_rate_at_pool | 0.954414 |
| candidate_hit_users | 1319 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 6.802881 |
| candidate_hit_rank_p50 | 7.0 |
| candidate_hit_rank_p90 | 9.0 |
| candidate_hit_missed_topk_users | 138 |
| ranked_hit_users | 1181 |
| recall_at_k | 0.854559 |
| recall_at_pool | 0.954414 |
| ndcg_at_k | 0.40016 |
| mrr_at_k | 0.258418 |
| map_at_k | 0.258418 |
| hit_rate_at_k | 0.854559 |
| popular_only_hit_rate_at_k | 0.034732 |
| itemcf_only_hit_rate_at_k | 0.871925 |
| hybrid_hit_rate_at_k | 0.854559 |
| hybrid_no_itemcf_hit_rate_at_k | 0.04631 |
| category_diversity_avg | 2.325615 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 6752, "itemcf_strong": 11480, "itemcf_weak": 11947, "popular": 12655, "semantic": 36463, "two_tower": 14596}`
- topk_source_coverage: `{"category": 1875, "itemcf_strong": 2009, "itemcf_weak": 2052, "popular": 4663, "semantic": 626, "two_tower": 1767}`
- per_source_candidate_contribution: `{"category": 47, "itemcf_strong": 1222, "itemcf_weak": 1294, "popular": 64, "semantic": 64, "two_tower": 919}`
- per_source_topk_contribution: `{"category": 46, "itemcf_strong": 1112, "itemcf_weak": 1175, "popular": 63, "semantic": 62, "two_tower": 868}`
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
    "hit_rate_at_k": 0.854559,
    "ndcg_at_k": 0.40016,
    "mrr_at_k": 0.258418,
    "candidate_hit_users": 1319,
    "candidate_hit_missed_topk_users": 138,
    "candidate_hit_rank_p50": 7.0,
    "candidate_hit_rank_p90": 9.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.313372,
    "ranking_p95_seconds": 0.001003,
    "candidate_generation_p95_seconds": 0.334506
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
        "hit_rate_at_k": 0.854559,
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
        "hit_rate_at_k": 0.012623,
        "candidate_hit_users": 55
      },
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
          "exists": true
        },
        "paired_lopo_metrics_path": {
          "path": "D:\\sinrotic_code\\python_project\\summer\\RS_agent\\outputs\\hybrid_demo_small_electronics_10000_lopo_semantic_title_phase_1_13_two_tower_youtube_dnn_rerank_ltr\\metrics.json",
          "exists": false
        }
      },
      "lopo_checks": {
        "candidate_hit_rate_at_pool": true,
        "recall_at_pool": true,
        "hit_rate_at_k": true
      },
      "candidate_generation_p95_seconds": 0.334506,
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
  "candidate_generation_avg_seconds": 0.163312,
  "candidate_generation_p95_seconds": 0.334506,
  "ranking_avg_seconds": 0.000772,
  "ranking_p95_seconds": 0.001003,
  "recommendation_avg_seconds": 0.164101,
  "recommendation_p95_seconds": 0.335246,
  "total_run_seconds": 231.255291
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.954414
- candidate_hit_users: 1319
- ranked_hit_users: 1181
- candidate_hit_missed_topk_users: 138
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 6.802881
- candidate_hit_rank_p50: 7.0
- candidate_hit_rank_p90: 9.0
- candidate_hit_source_coverage: `{"category": 47, "itemcf_strong": 1222, "itemcf_weak": 1294, "popular": 64, "semantic": 64, "two_tower": 919}`

## Ranking Case Summary

- total_hit_cases: 1319
- topk_hit_cases: 486
- missed_topk_cases: 833
- semantic_only_items_above_share: 0.087798
- top1_score_gap_avg: 28.166361
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak+popular+two_tower": 3, "category+itemcf_strong+itemcf_weak+two_tower": 7, "category+two_tower": 1, "itemcf_strong+itemcf_weak": 235, "itemcf_strong+itemcf_weak+popular": 4, "itemcf_strong+itemcf_weak+popular+two_tower": 1, "itemcf_strong+itemcf_weak+semantic": 1, "itemcf_strong+itemcf_weak+semantic+two_tower": 1, "itemcf_strong+itemcf_weak+two_tower": 507, "itemcf_strong+two_tower": 1, "itemcf_weak": 13, "itemcf_weak+two_tower": 42, "popular+two_tower": 1, "semantic+two_tower": 1, "two_tower": 15}`
- items_above_source_combinations: `{"popular": 3568, "category+popular": 961, "semantic": 590, "itemcf_strong+itemcf_weak": 461, "category+popular+two_tower": 445, "semantic+two_tower": 210, "category+popular+semantic": 77, "itemcf_strong": 56, "itemcf_strong+itemcf_weak+two_tower": 39, "category+semantic": 39, "itemcf_weak": 37, "popular+two_tower": 32, "itemcf_strong+itemcf_weak+semantic": 26, "category+itemcf_strong+itemcf_weak+popular": 24, "itemcf_strong+itemcf_weak+popular": 23, "category+itemcf_strong+itemcf_weak+popular+two_tower": 20, "category+popular+semantic+two_tower": 19, "itemcf_strong+two_tower": 12, "popular+semantic": 10, "itemcf_strong+itemcf_weak+semantic+two_tower": 9, "category+two_tower": 8, "category+itemcf_weak+popular": 6, "category+itemcf_strong+itemcf_weak": 6, "category+itemcf_strong+itemcf_weak+popular+semantic": 5, "category+itemcf_weak+popular+two_tower": 5, "category+semantic+two_tower": 5, "two_tower": 4, "itemcf_weak+two_tower": 4, "popular+semantic+two_tower": 3, "itemcf_weak+semantic": 3, "itemcf_strong+semantic": 2, "category+itemcf_weak": 2, "itemcf_weak+semantic+two_tower": 2, "itemcf_strong+popular": 1, "category+itemcf_strong+popular": 1, "itemcf_weak+popular": 1, "category+itemcf_strong": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "category+itemcf_strong+semantic": 1, "itemcf_strong+itemcf_weak+popular+two_tower": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_13_two_tower_youtube_dnn_rerank_ltr_10000_lopo
- risk_flags: none
- items:
  - B087S2JRXY score=56.716268 sources=category,popular
  - B071VDV7NC score=40.135496 sources=category,semantic,popular
  - B09RHJTQTM score=35.956962 sources=itemcf_weak,itemcf_strong,two_tower
  - B005TUQV0E score=27.867181 sources=itemcf_weak,itemcf_strong
  - B00DS4BLLW score=27.867181 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_13_two_tower_youtube_dnn_rerank_ltr_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=56.312087 sources=popular
  - B075X8471B score=48.500504 sources=popular
  - B07KTYJ769 score=46.397348 sources=popular
  - B07GZFM1ZM score=43.971499 sources=popular
  - B00KWR8ME2 score=35.613407 sources=itemcf_weak,itemcf_strong,category,two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_13_two_tower_youtube_dnn_rerank_ltr_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=56.312087 sources=popular
  - B075X8471B score=48.500504 sources=popular
  - B07KTYJ769 score=46.397348 sources=popular
  - B07GZFM1ZM score=43.971499 sources=popular
  - B074V5CMYK score=33.973941 sources=itemcf_weak,itemcf_strong,two_tower
