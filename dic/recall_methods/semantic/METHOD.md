# semantic

## 方法定位
语义召回来源，用于通过文本或 metadata 相似性补充行为召回覆盖。它属于 `deferred_evidence_policy`：当前重点是补齐证据和缺失 artifact，不允许伪装成 ready。

## 当前 readiness
- 状态：`DEFERRED`
- target500 batch row_count：0
- 当前未作为可用 pool500 source 晋升。

## 治理契约
- 先补齐可审计证据，再谈 ready。
- 不接受老 artifact、holdout、valid、test、clean_10000、LOPO、youtube_dnn 之类作为 readiness 证据（如适用）。
- 未完成 full-clean-safe contract 前，不得标记为 ready。

## 适用用户
- 历史 item 有 title/category/text metadata。
- 行为 CF 覆盖不足但语义相似 item 可扩展。
- 中低行为密度用户和长尾 item 场景。

## 输入 artifact
- semantic recall inputs 或 batch-scoped semantic index。
- item title/category metadata。

## 输出 artifact
- target500 per-source 占位：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/semantic/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：0
- readiness：DEFERRED

## 当前问题
尚未接入 full-clean-safe 的可用 semantic artifact；当前仅保留占位和 gate 边界。

## 下一步
先做 batch-scoped semantic 诊断，验证 metadata 覆盖、去重后贡献和 underfill 改善，再决定是否建设 full semantic sidecar。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是补齐 metadata 覆盖、semantic input manifest、batch-scoped 诊断和 no-holdout 证据，而不是直接进入 final pool500。Agent 必须保持 `deferred_evidence_policy`，先证明 title/category/text 字段可用、去重后有边际贡献且不读取 holdout/valid/test；未完成 full-clean-safe artifact 前不得宣称 READY、ranking input replacement 或 pool1000。
