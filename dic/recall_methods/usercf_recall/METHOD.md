# usercf_recall

## 方法定位
基于共享正反馈 item 的用户相似召回。它属于 `custom_dataset_policy`，是重资源方法，当前只用于 pool500 重召回诊断，不作为正式 ranking input。

## 当前 readiness
- 状态：`DIAGNOSTIC_ONLY`
- index：`INDEX_READY`
- 输出：`DIAGNOSTIC_OUTPUT_READY`
- 禁止：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`

## 治理契约
- 仅对 `heavy_cf_eligible`、必要时少量 `medium_behavior` 用户扩大样本。
- 必须 batch 化、带 guard、带 memory limit。
- 产物只允许诊断用途，不能替换 ranking，也不能进入 pool1000。

## 适用用户
- 近期正反馈 item 数足够多。
- unique item 有一定多样性。
- 共享 item 能连接到足够邻居用户。
- 不适合极冷启动或只有热门 item 堆叠的用户。

## 输入 artifact
- clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- train sequences：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`

## 输出 artifact
- heavy-only 空诊断 sidecar：`outputs/recall/pool500_sidecar_fix/usercf_recall_guarded_diagnostic_heavy_empty/source_index_manifest.json`
- medium20 降级诊断 sidecar：`outputs/recall/pool500_sidecar_fix/usercf_recall_guarded_diagnostic_medium20/source_index_manifest.json`
- readiness：对应目录下 `readiness_contract.json`
- resource audit：对应目录下 `resource_audit.json`
- per-source candidate manifest：对应目录下 `per_source_candidate_manifest.json`

## 资源画像
最近一次 guarded diagnostic：
- heavy-only：`target_user_count=0`、`indexed_user_count=0`、`candidate_total_count=0`、`peak_rss_mb=31`，确认不会在 eligible 为空时回退全量用户矩阵。
- medium20 降级诊断：`target_user_count=20`、`indexed_user_count=311896`、`candidate_user_count=20`、`candidate_total_count=2000`、`row_count=20`、`peak_rss_mb=552`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.2`。
- guard：按 target batch 写 checkpoint，输出 memory samples、resource audit、no-holdout audit、readiness contract 和 per-source candidate manifest；状态仍为 `DIAGNOSTIC_ONLY`。

## 当前问题
当前 target500 user_quality manifest 中 `heavy_cf_eligible=0`，UserCF 对主策略没有 heavy 用户可诊断。medium20 只用于降级观测，不能标记为 full-ready，也不能作为 ranking input replacement 或 pool1000 依据。

## 下一步
先扩大或重建 user_quality 分层样本以获得真实 `heavy_cf_eligible` 用户，再在相同 guarded/batched/recoverable 流程下评估 UserCF 对 underfill 的边际改善。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是围绕 `heavy_cf_eligible` 用户构建可分批、可恢复、带内存 guard 的 UserCF 诊断数据集，并输出 user quality manifest、source index manifest、readiness contract、resource audit 和 per-source candidate manifest。Agent 不应对低行为用户强行跑全用户矩阵，也不得把 `DIAGNOSTIC_ONLY` 产物晋升为 READY、ranking input replacement 或 pool1000 依据。
