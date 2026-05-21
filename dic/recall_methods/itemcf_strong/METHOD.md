# itemcf_strong

## 方法定位
强标签 ItemCF 召回，基于更可信的 item 共现边提供高精度补充候选。它属于 `custom_dataset_policy`，是重资源方法，当前只做诊断，不可替换 ranking。

## 当前 readiness
- 状态：`DIAGNOSTIC_ONLY`
- index：`INDEX_READY`
- 输出：`DIAGNOSTIC_OUTPUT_READY`
- 仅维持诊断态，不做状态升级或下游链路替换。

## 治理契约
- 只适用 `heavy_cf_eligible`。
- 必须 batch 化、带 guard、带 memory limit。
- builder 覆盖：`source_index_manifest` 以 `train_only` 的 source-positive 用户建边；本轮 `users_scanned=5992`、`users_with_source_items=5000`、`users_used=2133`，`target_user_limit_semantics=source_positive_builder_sequences_limit`。
- profiled 覆盖：`null` / `unprofiled`，没有单独的用户质量 profile 过滤；当前 artifact 是 legacy unfiltered sidecar coverage audit，不把高质量用户索引误当 consumer universe。
- consumer 覆盖：新增独立 `consumer_user_manifest.json` 和 `coverage_audit.json`；本轮 target500 train-only consumer 中 `consumer_users_with_edge_seed_hit=239`、`edge_item_out_of_universe_count=0`。

## 适用用户
- 有强正反馈或高置信行为序列。
- seed item 能命中 strong item-item 边。
- 适合作为高精度补充来源，不适合单独承担覆盖。

## 输入 artifact
- source signature：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`，`row_count=18103384`，`sha256=d47c9a3476f35f0c8bd88947b58f8a3f0ef83383f587d8d0e3102b6dbf1baf07`
- clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`

## 输出 artifact
- readiness contract：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/readiness_contract.json`
- source index manifest：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/source_index_manifest.json`
- resource audit：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/resource_audit.json`
- no-holdout audit：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/no_holdout_audit.json`
- per-source candidate manifest：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/per_source_candidate_manifest.json`
- weak/strong comparison：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/weak_strong_comparison.json`
- edge sidecar：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/itemcf_strong_edges.jsonl`
- consumer user manifest：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/consumer_user_manifest.json`
- coverage audit：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/coverage_audit.json`
- custom dataset manifest：`configs/recall/full_data_pool500/itemcf_strong_custom_dataset_manifest.json`
- recall-only target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/itemcf_strong/manifest.json`

## 资源画像
最近一次 target500 guarded diagnostic：
- `edge_count` / `rows_written`：68432
- `unique_pair_count`：34341
- `unique_item_count`：9939
- `candidate_user_count`：5000
- `users_scanned`：5992
- `users_used`：2133
- `consumer_users_with_edge_seed_hit`：239 / 500
- `edge_item_out_of_universe_count`：0
- `peak_rss_mb`：35.695
- `underfilled_user_coverage`：1.0

## 当前问题
已经从 500 个 source-positive 用户扩大到 5000 个 train-only source-positive 用户建边，并补齐 consumer coverage audit 与 registry custom dataset manifest；但 `status` 仍是 `DIAGNOSTIC_ONLY`，`custom_dataset_policy_satisfied=false`，仍只保留诊断用途。strong 更适合作为高置信补充源，不适合单独承担补量。

## 下一步
与 weak ItemCF 一起比较覆盖和边际贡献：本轮 guarded sidecar 中 strong `rows_written=68432`、target500 consumer seed-hit 用户 239；weak `rows_written=74662`、target500 consumer seed-hit 用户 250，weak 更适合补量，strong 更适合作为高置信补充。若治理上必须满足高质量 custom dataset policy，需要另跑 quality-builder sidecar，并继续用独立 consumer_user_manifest / coverage_audit 校验 pool500 consumer 覆盖。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是围绕 `heavy_cf_eligible` 用户扩展 strong ItemCF 的高置信 item-pair 数据集，重点比较 strong/weak 的精度、覆盖、重复率和资源成本。Agent 必须保留 batch/guard/memory limit，并输出 source index manifest、resource audit 和诊断候选 manifest；不得因为 strong 边更可信就跳过诊断门槛或直接宣称可晋升状态。