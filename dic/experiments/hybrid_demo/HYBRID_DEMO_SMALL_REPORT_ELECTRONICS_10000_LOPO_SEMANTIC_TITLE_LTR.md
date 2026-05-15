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
    "recent": 0.3,
    "verified": 0.2,
    "time_decay": 0.2
  },
  "rerank_policy": {},
  "source_aware_fusion": {},
  "item_feature_rerank": {},
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
    "semantic": 20
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
| candidate_hit_rate_at_pool | 0.939219 |
| candidate_hit_users | 1298 |
| candidate_hit_rank_min | 1 |
| candidate_hit_rank_avg | 32.59168 |
| candidate_hit_rank_p50 | 33.0 |
| candidate_hit_rank_p90 | 48.0 |
| candidate_hit_missed_topk_users | 250 |
| ranked_hit_users | 1048 |
| recall_at_k | 0.758321 |
| recall_at_pool | 0.939219 |
| ndcg_at_k | 0.302548 |
| mrr_at_k | 0.163326 |
| map_at_k | 0.163326 |
| hit_rate_at_k | 0.758321 |
| popular_only_hit_rate_at_k | 0.02822 |
| itemcf_only_hit_rate_at_k | 0.869754 |
| hybrid_hit_rate_at_k | 0.758321 |
| hybrid_no_itemcf_hit_rate_at_k | 0.036903 |
| category_diversity_avg | 1.884949 |

## Fallback and Source Coverage

- fallback_rate: 0.0
- recall_source_coverage: `{"category": 8772, "itemcf_strong": 11481, "itemcf_weak": 11959, "popular": 17142, "semantic": 39744}`
- topk_source_coverage: `{"category": 2039, "itemcf_strong": 1323, "itemcf_weak": 1368, "popular": 5142, "semantic": 794}`
- per_source_candidate_contribution: `{"category": 45, "itemcf_strong": 1219, "itemcf_weak": 1292, "popular": 62, "semantic": 64}`
- per_source_topk_contribution: `{"category": 45, "itemcf_strong": 994, "itemcf_weak": 1044, "popular": 61, "semantic": 61}`
- source_overlap: `{"single_source_candidate_count": 49864, "multi_source_candidate_count": 19236, "multi_source_candidate_rate": 0.278379, "source_pair_counts": {"category+itemcf_strong": 186, "category+itemcf_weak": 190, "category+popular": 8211, "category+semantic": 735, "itemcf_strong+itemcf_weak": 10540, "itemcf_strong+popular": 209, "itemcf_strong+semantic": 149, "itemcf_weak+popular": 213, "itemcf_weak+semantic": 154, "popular+semantic": 301}}`
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
    "candidate_hit_rate_at_pool": 0.939219,
    "hit_rate_at_k": 0.758321,
    "ndcg_at_k": 0.302548,
    "mrr_at_k": 0.163326,
    "candidate_hit_users": 1298,
    "candidate_hit_missed_topk_users": 250,
    "candidate_hit_rank_p50": 33.0,
    "candidate_hit_rank_p90": 48.0,
    "fallback_rate": 0.0,
    "multi_source_candidate_rate": 0.278379,
    "ranking_p95_seconds": 0.00136
  }
}
```

## Latency Diagnostics

```json
{
  "candidate_generation_avg_seconds": 0.147991,
  "candidate_generation_p95_seconds": 0.337061,
  "ranking_avg_seconds": 0.001036,
  "ranking_p95_seconds": 0.00136,
  "recommendation_avg_seconds": 0.149049,
  "recommendation_p95_seconds": 0.338162,
  "total_run_seconds": 210.758715
}
```

## Recall Bottleneck Diagnostics

- candidate_hit_rate_at_pool: 0.939219
- candidate_hit_users: 1298
- ranked_hit_users: 1048
- candidate_hit_missed_topk_users: 250
- candidate_hit_rank_min: 1
- candidate_hit_rank_avg: 32.59168
- candidate_hit_rank_p50: 33.0
- candidate_hit_rank_p90: 48.0
- candidate_hit_source_coverage: `{"category": 45, "itemcf_strong": 1219, "itemcf_weak": 1292, "popular": 62, "semantic": 64}`

## Ranking Case Summary

- total_hit_cases: 1298
- topk_hit_cases: 60
- missed_topk_cases: 1238
- semantic_only_items_above_share: 0.634383
- top1_score_gap_avg: 44.358666
- target_source_combinations: `{"category+itemcf_strong+itemcf_weak": 11, "category+itemcf_strong+itemcf_weak+popular": 13, "category+itemcf_strong+itemcf_weak+semantic": 1, "category+itemcf_weak+popular": 1, "itemcf_strong": 1, "itemcf_strong+itemcf_weak": 1092, "itemcf_strong+itemcf_weak+popular": 8, "itemcf_strong+itemcf_weak+semantic": 40, "itemcf_weak": 70, "semantic": 1}`
- items_above_source_combinations: `{"semantic": 25938, "popular": 7995, "category+popular": 5398, "itemcf_strong+itemcf_weak": 763, "category+semantic": 358, "category+popular+semantic": 159, "itemcf_strong+itemcf_weak+semantic": 59, "category+itemcf_strong+itemcf_weak+popular": 57, "itemcf_strong+itemcf_weak+popular": 45, "popular+semantic": 26, "category+itemcf_strong+itemcf_weak": 19, "category+itemcf_weak+popular": 15, "itemcf_weak+semantic": 8, "category+itemcf_strong+itemcf_weak+popular+semantic": 7, "itemcf_weak": 7, "category+itemcf_strong+popular": 7, "itemcf_strong+popular": 7, "itemcf_strong+semantic": 6, "itemcf_weak+popular": 5, "category+itemcf_strong": 3, "category+itemcf_weak": 2, "category+itemcf_weak+popular+semantic": 1, "itemcf_strong": 1, "category+itemcf_strong+semantic": 1}`

## Sample Limitations

- Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact.
- Leave-one-positive-out evaluated 1382 of 2340 input users; 958 users were skipped because they had fewer than 2 positives.

## Recommendation Examples

### User AE25NQAZI3725GZIL5FS52ZIKWKQ

- strategy: phase_1_9_ltr_demo_10000_lopo
- risk_flags: none
- items:
  - B087S2JRXY score=56.216268 sources=category,popular
  - B071VDV7NC score=39.635496 sources=category,semantic,popular
  - B07MZ6PJW8 score=32.32 sources=semantic
  - B07TJ87YKB score=31.58 sources=semantic
  - B09RHJTQTM score=17.474358 sources=itemcf_weak,itemcf_strong

### User AE26ICWKMFJEHDH5VDX4W42H2NMA

- strategy: phase_1_9_ltr_demo_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=58.812087 sources=popular
  - B075X8471B score=51.000504 sources=popular
  - B07KTYJ769 score=48.897348 sources=popular
  - B07GZFM1ZM score=46.471499 sources=popular
  - B00KWR8ME2 score=17.177179 sources=itemcf_weak,itemcf_strong,category

### User AE2CJPQPEGCIDJKZZRYDSVRV46SA

- strategy: phase_1_9_ltr_demo_10000_lopo
- risk_flags: none
- items:
  - B01K8B8YA8 score=58.812087 sources=popular
  - B075X8471B score=51.000504 sources=popular
  - B07KTYJ769 score=48.897348 sources=popular
  - B07GZFM1ZM score=46.471499 sources=popular
  - 993591786X score=15.367181 sources=itemcf_weak,itemcf_strong
