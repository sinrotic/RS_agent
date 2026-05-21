# usercf_recall

## 方法定位
基于共享正反馈 item 的用户相似召回。它属于 `custom_dataset_policy`，是重资源方法，当前只用于 pool500 heavy28 侧车诊断，不作为正式 ranking input。

## 当前 readiness
- 状态：`DIAGNOSTIC_ONLY`
- index：`INDEX_READY`
- 输出：`DIAGNOSTIC_OUTPUT_READY`
- 禁止：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`

## 默认 pool500 sidecar artifact
- source index manifest：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/source_index_manifest.json`
- custom index selection manifest：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/custom_index_selection_manifest.json`
- readiness contract：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/readiness_contract.json`
- per-source candidate manifest：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/per_source_candidate_manifest.json`
- resource audit：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/resource_audit.json`
- no-holdout audit：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/no_holdout_audit.json`

## 高质量用户索引数据集
- 输入：`D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_user_quality/heavy_probe_limit5000_train_only/eligible_user_quality_manifest.json`
- 当前策略：`heavy_cf_eligible`
- 质量维度：近期正反馈 item 数、unique item 多样性、共享 item 的邻居连通性、避免纯 hot-item 堆叠
- 不适合：cold-start 用户、低行为用户

## 治理契约
- `source=usercf_recall`
- `source_status=DIAGNOSTIC_ONLY`
- `train_only=true`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `final_pool500_ready_claimed=false`
- 不读取 valid/test/holdout/10k/pool1000

## 资源与效果审计
- `target_user_count=28`
- `indexed_user_count=1386693`
- `candidate_user_count=28`
- `candidate_total_count=5600`
- `peak_rss_mb=1937`
- `underfilled_user_coverage=1.0`
- `marginal_candidate_share=0.4`

## 旧诊断口径
`usercf_recall_target100_guarded` 只代表 v1 的弱参数历史诊断，不是当前交付物，也不能作为 pool500 ready、ranking input replacement 或 pool1000 的依据。

## 当前结论
heavy28 侧车已经证明：在真实 high-quality 用户索引上，UserCF 可以以受控资源产生候选，并对 underfilled heavy 用户形成边际贡献；但这些证据只支持 `DIAGNOSTIC_ONLY` 合同，不授权 READY 晋升、ranking input replacement、pool1000 或 final pool500 ready 声明。

## 下一步
如果要把范围扩大到 heavy28 之外，必须先扩充 eligible profile / high-quality index，再考虑单独做 64/100 用户的受控诊断；在此之前仍然保持 `DIAGNOSTIC_ONLY`，不做 READY、ranking 或 pool1000。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应继续围绕 `heavy_cf_eligible` 用户构建可分批、可恢复、带内存 guard 的 UserCF 诊断数据集，并输出 source index manifest、readiness contract、resource audit 和 per-source candidate manifest。Agent 不应对低行为用户强行跑全用户矩阵，也不得把 `DIAGNOSTIC_ONLY` 产物晋升为 READY、ranking input replacement 或 pool1000 依据。