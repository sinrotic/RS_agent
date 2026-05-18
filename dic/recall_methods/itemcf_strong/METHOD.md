# itemcf_strong

## 方法定位
强标签 ItemCF 召回，基于更可信的 item 共现边提供高精度补充候选。它属于 `custom_dataset_policy`，是重资源方法，当前只做诊断，不可替换 ranking。

## 当前 readiness
- 状态：`DIAGNOSTIC_ONLY`
- index：`INDEX_READY`
- 输出：`DIAGNOSTIC_OUTPUT_READY`
- 禁止替换 ranking input 或进入 pool1000。

## 治理契约
- 仅对 `heavy_cf_eligible`、必要时少量 `medium_behavior` 用户扩展。
- 必须 batch 化、带 guard、带 memory limit。
- 输出只允许诊断用途，不能替代 ranking。

## 适用用户
- 有强正反馈或高置信行为序列。
- seed item 能命中 strong item-item 边。
- 适合作为高精度补充来源，不适合单独承担覆盖。

## 输入 artifact
- clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- train sequences：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`

## 输出 artifact
- 最新诊断 sidecar：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/source_index_manifest.json`
- recall-only target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/itemcf_strong/manifest.json`

## 资源画像
最近一次 target500 sidecar：
- edges：5636
- target500 batch row_count：330
- 峰值 RSS：约 37MB

## 当前问题
覆盖仍偏低，且不是 full-ready。需要判断 strong 边低覆盖是标签严格导致，还是 target500 样本构建范围不足。

## 下一步
与 weak ItemCF 一起做更大 source-positive shard，比较 weak/strong 的边数、命中用户数和去重后有效贡献。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是围绕 `heavy_cf_eligible` 用户扩展 strong ItemCF 的高置信 item-pair 数据集，重点比较 strong/weak 的精度、覆盖、重复率和资源成本。Agent 必须保留 batch/guard/memory limit，并输出 source index manifest、resource audit 和诊断候选 manifest；不得因为 strong 边更可信就跳过 readiness gate 或宣称 READY、ranking input replacement、pool1000。
