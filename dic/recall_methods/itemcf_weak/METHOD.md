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