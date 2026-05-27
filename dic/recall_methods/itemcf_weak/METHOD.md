# itemcf_weak

## 方法定位
弱标签 ItemCF 召回，基于较宽松的 item 共现关系提供补充候选。它属于 `custom_dataset_policy`，是重资源方法，当前只做诊断，不可替换 ranking。

## 当前 readiness
- 状态：`DIAGNOSTIC_ONLY`
- index：`INDEX_READY`
- 输出：`DIAGNOSTIC_OUTPUT_READY`
- 仅维持诊断态，不做状态升级或下游链路替换。

## 治理契约
- 适用 `heavy_cf_eligible` 和 `medium_behavior`。
- 必须 batch 化、带 guard、带 memory limit。
- builder 覆盖：`source_index_manifest` 以 `train_only` 的 source-positive 用户建边；本轮 `users_scanned=5713`、`users_with_source_items=5000`、`users_used=2149`，`target_user_limit_semantics=source_positive_builder_sequences_limit`。
- profiled 覆盖：`null` / `unprofiled`，没有单独的用户质量 profile 过滤；当前 artifact 是 legacy unfiltered sidecar coverage audit，不把高质量用户索引误当 consumer universe。
- consumer 覆盖：新增独立 `consumer_user_manifest.json` 和 `coverage_audit.json`；本轮 target500 train-only consumer 中 `consumer_users_with_edge_seed_hit=250`、`edge_item_out_of_universe_count=0`。

## 适用用户
- 有可用近期正反馈序列。
- 历史 item 能命中 item-item 边。
- 适合作为 UserCF / Swing 之外的行为召回补充。

## 输入 artifact
- source signature：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`，`row_count=18103384`，`sha256=d47c9a3476f35f0c8bd88947b58f8a3f0ef83383f587d8d0e3102b6dbf1baf07`
- clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`

## 输出 artifact
- readiness contract：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/readiness_contract.json`
- source index manifest：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/source_index_manifest.json`
- resource audit：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/resource_audit.json`
- no-holdout audit：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/no_holdout_audit.json`
- per-source candidate manifest：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/per_source_candidate_manifest.json`
- weak/strong comparison：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/weak_strong_comparison.json`
- edge sidecar：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/itemcf_weak_edges.jsonl`
- consumer user manifest：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/consumer_user_manifest.json`
- coverage audit：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/coverage_audit.json`
- custom dataset manifest：`configs/recall/full_data_pool500/itemcf_weak_custom_dataset_manifest.json`
- recall-only target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/itemcf_weak/manifest.json`

## 资源画像
最近一次 target500 guarded diagnostic：
- `edge_count` / `rows_written`：74662
- `unique_pair_count`：37466
- `unique_item_count`：10177
- `candidate_user_count`：5000
- `users_scanned`：5713
- `users_used`：2149
- `consumer_users_with_edge_seed_hit`：250 / 500
- `edge_item_out_of_universe_count`：0
- `peak_rss_mb`：35.574
- `underfilled_user_coverage`：1.0

## 当前问题
已经从 500 个 source-positive 用户扩大到 5000 个 train-only source-positive 用户建边，并补齐 consumer coverage audit 与 registry custom dataset manifest；但 `status` 仍是 `DIAGNOSTIC_ONLY`，`custom_dataset_policy_satisfied=false`，仍不能把当前结果写成可晋升状态或下游替换结果。

## 下一步
继续保持 guarded diagnostic；若治理上必须满足高质量 custom dataset policy，需要另跑 quality-builder sidecar，并继续用独立 consumer_user_manifest / coverage_audit 校验 pool500 consumer 覆盖。后续可用更细的 source-positive 用户分层、seed window 与 per-seed 配额分析边际贡献；如果继续扩大 train-only 索引，需要先评估 item shard、外排聚合和资源水位，再决定是否继续扩样。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是围绕 `heavy_cf_eligible_or_medium_behavior` 用户扩展 weak ItemCF 的 item-pair 数据集，评估边数、命中用户数、去重后边际贡献和资源水位。Agent 必须使用 batch/guard/memory limit，输出 source index manifest、resource audit 和诊断候选 manifest；不得把 weak ItemCF 的低阈值广覆盖直接解释为可晋升状态或下游替换权限。

## P2 method_dataset 数据清洗与筛选方案

- 数据来源：只读取 `governance_train_only` 的用户质量、item 质量、train item frequency 与 `user_sequences.train.jsonl`。
- 筛选单位：`user_positive_sequence_to_item_pairs`。先保留用户内正反馈窗口，再生成 item-pair，不单独随机抽 item。
- 适用桶：用户桶 `medium_behavior`、`collaborative_rich`；item 侧使用 `cf_ready`。
- 清洗规则：过滤缺失 `quality_bucket_v2` 的用户、非 `cf_ready` item、过热 item 或对过热 item 做 cap/downweight；保留更宽的弱共现覆盖。
- 规模参数：`max_output_users=300000`、`max_items_per_user=50`、`max_item_user_freq=5000`、`min_pair_support=1`。

## P2 method_dataset 特征与打分口径

- builder 新增 `weighted_cooc`、`supporting_user_count`、`score_policy`、`itemcf_score_formula`、`active_user_penalty_policy`。
- `itemcf_score = round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)`。
- `active_user_penalty_policy` 是效果导向抑制超活跃用户和长序列随机共现，不是流程优化。
- 这里记录的是 `method_dataset` / diagnostic evidence，不是 source/candidate/ranking/promotion 替换口径。

### 规模档位

| 档位 | max_output_users | max_items_per_user | max_item_user_freq | min_pair_support |
| --- | ---: | ---: | ---: | ---: |
| smoke | 1000 | 50 | 5000 | 1 |
| diagnostic | 50000 | 50 | 5000 | 1 |
| local_formal | 300000 | 50 | 5000 | 1 |

- 泄漏边界：不读取 valid/test/holdout/LOPO/eval_label/oracle，不用诊断命中结果反向筛边，不声明 READY、promotion、ranking input replacement 或 pool1000。
- 维护检查：weak 的 `min_pair_support` 与 `max_item_user_freq` 应宽于 strong；修改后同步检查 registry、builder manifest、测试中的 `itemcf_weak_edges_v1`。

## P2 smoke / diagnostic / formal method_dataset 构建验证（2026-05-25）

- smoke 构建命令：`.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_method_dataset --governance-manifest outputs/recall/data_governance/train_only_v1_smoke/manifest.json --source-method itemcf_weak --scale-tier smoke --output-root outputs/recall/pool500_method_datasets/itemcf_weighted_smoke_v1 --overwrite`
- smoke 输出目录：`outputs/recall/pool500_method_datasets/itemcf_weighted_smoke_v1/itemcf_weak/`；`status=PASS`，但 `row_count=0`、`unique_pair_count=0`，只能证明链路和 audit 边界，不能证明覆盖提升。
- strict diagnostic 输出目录：`outputs/recall/pool500_method_datasets/itemcf_weighted_diagnostic_v1/itemcf_weak/`；`row_count=94`、`unique_pair_count=47`、`edge_count=94`、`user_count=32`、`item_count=69`，audit PASS。
- strict local_formal 输出目录：`outputs/recall/pool500_method_datasets/itemcf_weighted_formal_v1/itemcf_weak/`；`row_count=53540`、`unique_pair_count=26770`、`edge_count=53540`、`user_count=15535`、`item_count=33493`、`weighted_cooc_sum_after_topk=41082.97339`，audit PASS。
- strict local_formal 按三级规模体系执行，但由于 `cf_ready + non-over_hot + max_item_user_freq=5000` 过滤较重，边数只有约 5.35 万；主要 drop 包括 `user_bucket_not_allowed=17629532`、`insufficient_pair_items=458317`、`item_over_hot=866844`、`item_not_cf_ready=1208170`。
- coverage formal 另存为 `outputs/recall/pool500_method_datasets/itemcf_weighted_coverage_formal_v1/itemcf_weak/`，不是替换 strict 口径；显式使用 `weak_coverage` profile：`max_output_users=120000`、`max_items_per_user=80`、`max_item_user_freq=20000`、`top_k_per_seed=200`、用户桶扩到 `medium_behavior/sequence_sufficient/collaborative_rich`、item 桶扩到 `cf_ready/embedding_ready`，over-hot 只在 user frequency cap 下放行。
- coverage formal 规模：`row_count=5640872`、`unique_pair_count=3091726`、`directed_edge_count_after_topk=5640872`、`edge_seed_count=239995`、`user_count=120000`、`item_count=239995`、`max_edges_per_seed_after_topk=200`、`weighted_cooc_sum_after_topk=2153105.673601`、`score_mismatch_count=0`、`missing_field_counts={}`。
- dropped reason：coverage formal 仍保留 train-only 与质量边界，主要为 `user_bucket_not_allowed=14350420`、`max_output_users_exceeded=3632226`、`insufficient_pair_items=738`、`item_quality_bucket_not_allowed=1208170`、`item_user_freq_over_cap=32`。
- 特征摘要：`weighted_cooc`、`supporting_user_count`、`score_policy=weighted_cooc_cosine_normalized_v1`、`active_user_penalty_policy=round(1 / log1p(filtered_sequence_len), 6)` 已进入 builder；`itemcf_score = round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)`；排序策略为 `source_method + src_item_id` 内按 `itemcf_score desc, cooc_cnt desc, dst_item_id asc`。
- 边界说明：这些输出仍是 `method_dataset` / diagnostic evidence，不是 source index、candidate、ranking input、promotion 或 final pool500 ready；audit validator 使用 method manifest 的 `upstream_governance_manifest_path`，不硬编码 default governance。
