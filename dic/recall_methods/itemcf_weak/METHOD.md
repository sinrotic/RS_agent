# itemcf_weak

## 方法定位
弱标签 ItemCF 召回，基于较宽松的 item 共现关系提供补充候选。它属于 `custom_dataset_policy`，是重资源方法，当前只做诊断，不可替换 ranking。

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
- 有可用近期正反馈序列。
- 历史 item 能命中 item-item 边。
- 适合作为 UserCF/Swing 之外的行为召回补充。

## 输入 artifact
- clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- train sequences：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`

## 输出 artifact
- 最新诊断 sidecar：`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/source_index_manifest.json`
- recall-only target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/itemcf_weak/manifest.json`

## 资源画像
最近一次 target500 sidecar：
- edges：6098
- target500 batch row_count：345
- 峰值 RSS：约 38MB

## 当前问题
仍是 target-limited 诊断边集合，覆盖有限；在 target500 batch 中贡献低于 UserCF/Swing，需要继续扩大 item pair 建索引范围。

## 下一步
先按用户质量分层扩大 source-positive 用户样本，再评估是否需要 item shard / 外排聚合来构建 full-train ItemCF。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是围绕 `heavy_cf_eligible_or_medium_behavior` 用户扩展 weak ItemCF 的 item-pair 数据集，评估边数、命中用户数、去重后边际贡献和资源水位。Agent 必须使用 batch/guard/memory limit，输出 source index manifest、resource audit 和诊断候选 manifest；不得把 weak ItemCF 的低阈值广覆盖直接解释为 READY、ranking input replacement 或 pool1000 权限。
