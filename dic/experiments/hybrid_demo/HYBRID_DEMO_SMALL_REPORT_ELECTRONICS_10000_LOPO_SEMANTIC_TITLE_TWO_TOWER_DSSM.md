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
  "two_tower_variant": "dssm",
  "two_tower_artifact_path": "outputs/training/two_tower/two_tower_training/dssm/artifact_manifest.json",
  "two_tower_artifact_name": "semantic_recall_inputs.jsonl",
  "two_tower_per_user": 30,
  "two_tower_seed_window": 10,
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
| candidate_hit_rate_at_pool | 0.938495 |
| candidate_hit_users | 1297 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 33.276022 |
| candidate_hit_rank_p50 | 38.0 |
| candidate_hit_rank_p90 | 47.0 |
| candidate_hit_missed_topk_users | 243 |
| ranked_hit_users | 1054 |
| recall_at_k | 0.762663 |
| recall_at_pool | 0.938495 |
| ndcg_at_k | 0.303497 |
| mrr_at_k | 0.163193 |
| map_at_k | 0.163193 |
| hit_rate_at_k | 0.762663 |
| popular_only_hit_rate_at_k | 0.030391 |
| itemcf_only_hit_rate_at_k | 0.887844 |
| hybrid_hit_rate_at_k | 0.762663 |
| hybrid_no_itemcf_hit_rate_at_k | 0.027496 |
| category_diversity_avg | 2.353111 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 5009, "itemcf_strong": 11482, "itemcf_weak": 11957, "popular": 10472, "semantic": 36079, "two_tower": 14688}`
- topk_source_coverage: `{"category": 1448, "itemcf_strong": 1307, "itemcf_weak": 1350, "popular": 3555, "semantic": 2491, "two_tower": 329}`
- per_source_candidate_contribution: `{"category": 44, "itemcf_strong": 1219, "itemcf_weak": 1292, "popular": 61, "semantic": 64, "two_tower": 189}`
- per_source_topk_contribution: `{"category": 42, "itemcf_strong": 997, "itemcf_weak": 1051, "popular": 58, "semantic": 61, "two_tower": 175}`
- source_overlap: `{"single_source_candidate_count": 49851, "multi_source_candidate_count": 19249, "multi_source_candidate_rate": 0.278567, "source_pair_counts": {"category+itemcf_strong": 186, "category+itemcf_weak": 190, "category+popular": 4215, "category+semantic": 734, "category+two_tower": 561, "itemcf_strong+itemcf_weak": 10538, "itemcf_strong+popular": 209, "itemcf_strong+semantic": 149, "itemcf_strong+two_tower": 256, "itemcf_weak+popular": 213, "itemcf_weak+semantic": 154, "itemcf_weak+two_tower": 271, "popular+semantic": 301, "popular+two_tower": 604, "semantic+two_tower": 3515}}`
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
    "candidate_hit_rate_at_pool": 0.938495,
    "hit_rate_at_k": 0.762663,
    "ndcg_at_k": 0.303497,
    "mrr_at_k": 0.163193,
    "candidate_hit_users": 1297,
    "candidate_hit_missed_topk_users": 243,
    "candidate_hit_rank_p50": 38.0,
    "candidate_hit_rank_p90": 47.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.278567,
    "ranking_p95_seconds": 0.000387,
    "candidate_generation_p95_seconds": 0.411996
  },
  "two_tower_strict_promotion_gate": {
    "enabled": true,
    "variant": "dssm",
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
      "paired_lopo_no_regression": false,
      "candidate_generation_p95_within_budget": false,
      "source_contribution_and_overlap_present": true
    },
    "evidence": {
      "current_metrics": {
        "candidate_hit_rate_at_pool": 0.938495,
        "recall_at_pool": 0.938495,
        "hit_rate_at_k": 0.762663,
        "candidate_hit_users": 1297
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
        "candidate_hit_rate_at_pool": 0.949349,
        "recall_at_pool": 0.949349,
        "hit_rate_at_k": 0.778582,
        "candidate_hit_users": 1312
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
      "candidate_generation_p95_seconds": 0.411996,
      "candidate_generation_p95_seconds_budget": 0.05,
      "two_tower_candidate_contribution": 189,
      "source_overlap": {
        "single_source_candidate_count": 49851,
        "multi_source_candidate_count": 19249,
        "multi_source_candidate_rate": 0.278567,
        "source_pair_counts": {
          "category+itemcf_strong": 186,
          "category+itemcf_weak": 190,
          "category+popular": 4215,
          "category+semantic": 734,
          "category+two_tower": 561,
          "itemcf_strong+itemcf_weak": 10538,
          "itemcf_strong+popular": 209,
          "itemcf_strong+semantic": 149,
          "itemcf_strong+two_tower": 256,
          "itemcf_weak+popular": 213,
          "itemcf_weak+semantic": 154,
          "itemcf_weak+two_tower": 271,
          "popular+semantic": 301,
          "popular+two_tower": 604,
          "semantic+two_tower": 3515
        }
      }
    }
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.205835,
  "candidate_generation_p95_seconds": 0.411996,
  "ranking_avg_seconds": 0.000281,
  "ranking_p95_seconds": 0.000387,
  "recommendation_avg_seconds": 0.206139,
  "recommendation_p95_seconds": 0.412388,
  "total_run_seconds": 288.140682
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.938495
- candidate_hit_users: 1297
- ranked_hit_users: 1054
- candidate_hit_missed_topk_users: 243
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 33.276022
- candidate_hit_rank_p50: 38.0
- candidate_hit_rank_p90: 47.0
- candidate_hit_source_coverage: `{"category": 44, "itemcf_strong": 1219, "itemcf_weak": 1292, "popular": 61, "semantic": 64, "two_tower": 189}`

## Ranking Case Summary

- total_hit_cases: 1297
- topk_hit_cases: 62
- missed_topk_cases: 1235
- semantic_only_items_above_share: 0.67665
- top1_score_gap_avg: 47.838589
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 11, "category+itemcf_strong+itemcf_weak+popular": 16, "category+itemcf_strong+itemcf_weak+semantic+two_tower": 1, "category+itemcf_strong+itemcf_weak+two_tower": 1, "category+itemcf_weak+popular": 1, "itemcf_strong": 1, "itemcf_strong+itemcf_weak": 935, "itemcf_strong+itemcf_weak+popular": 18, "itemcf_strong+itemcf_weak+semantic": 11, "itemcf_strong+itemcf_weak+semantic+two_tower": 10, "itemcf_strong+itemcf_weak+two_tower": 158, "itemcf_weak": 57, "itemcf_weak+popular": 1, "itemcf_weak+two_tower": 13, "semantic": 1}`
- items_above_source_combinations: `{"semantic": 28240, "popular": 5336, "category+popular": 3234, "semantic+two_tower": 2967, "itemcf_strong+itemcf_weak": 650, "category+semantic": 363, "popular+two_tower": 205, "category+popular+two_tower": 182, "category+popular+semantic": 155, "category+itemcf_strong+itemcf_weak+popular": 58, "itemcf_strong+itemcf_weak+semantic": 53, "category+semantic+two_tower": 52, "itemcf_strong+itemcf_weak+popular": 46, "category+two_tower": 36, "category+itemcf_strong+itemcf_weak": 24, "popular+semantic": 22, "category+itemcf_weak+popular": 13, "two_tower": 10, "category+popular+semantic+two_tower": 9, "itemcf_weak+semantic": 8, "itemcf_strong+popular": 8, "category+itemcf_strong+itemcf_weak+popular+semantic": 7, "itemcf_strong+itemcf_weak+two_tower": 7, "itemcf_weak": 7, "category+itemcf_strong+popular": 7, "itemcf_strong+semantic": 6, "itemcf_strong+itemcf_weak+semantic+two_tower": 6, "popular+semantic+two_tower": 5, "itemcf_weak+popular": 5, "category+itemcf_strong": 5, "category+itemcf_weak+popular+two_tower": 2, "category+itemcf_weak": 2, "category+itemcf_weak+popular+semantic": 1, "itemcf_strong": 1, "category+itemcf_strong+two_tower": 1, "category+itemcf_strong+semantic": 1, "itemcf_strong+itemcf_weak+popular+two_tower": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_12_two_tower_dssm_10000_lopo
- risk_flags: none
- items:
  - B071VDV7NC score=55.048589 sources=category,semantic,popular
  - B07MZ6PJW8 score=54.0 sources=semantic
  - B07TJ87YKB score=52.8 sources=semantic
  - B06Y3WCWXN score=51.6 sources=semantic
  - B09RHJTQTM score=4.5 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_12_two_tower_dssm_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B00KWR8ME2 score=6.728289 sources=itemcf_weak,itemcf_strong,category,two_tower

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_12_two_tower_dssm_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=50.399954 sources=popular
  - B075X8471B score=44.796862 sources=popular
  - B07KTYJ769 score=37.250264 sources=popular
  - B07GZFM1ZM score=35.678481 sources=popular
  - B074V5CMYK score=4.007064 sources=itemcf_weak,itemcf_strong,two_tower
