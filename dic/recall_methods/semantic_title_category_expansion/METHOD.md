# semantic_title_category_expansion

## 方法定位
结合 title overlap 与 category overlap 的语义类目扩展召回。它属于 `deferred_evidence_policy`：重点先补证据与缺失 artifact，不允许把不完整结果包装成 ready。

## 当前 readiness
- 状态：`DEFERRED`
- target500 batch row_count：0
- 当前不可作为正式 pool500 source。

## 治理契约
- 先补齐可审计证据，再谈 ready。
- 不接受老 artifact、holdout、valid、test、clean_10000、LOPO、youtube_dnn 之类作为 readiness 证据（如适用）。
- 未完成 full-clean-safe contract 前，不得标记为 ready。

## 适用用户
- 历史 item 有较完整 title/category。
- 行为召回不足但同类语义扩展可能有效。
- 适合补中尾部候选。

## 输入 artifact
- `scripts/experiments/recall/build_full_semantic_title_category_manifest.py` 相关产物。
- clean item metadata / semantic recall inputs。

## 输出 artifact
- target500 per-source 占位：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/semantic_title_category_expansion/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：0
- readiness：DEFERRED

## 当前问题
当前未接入可用 full artifact；需要先明确 metadata 来源、manifest contract 和资源占用。

## 下一步
优先做小批 batch-scoped semantic title/category manifest，验证是否能降低 underfill，再规划 full-clean-safe artifact。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是构建小批 title/category manifest，验证 metadata 清洗、category overlap、title token overlap、去重后边际贡献和 underfill 改善。Agent 必须保持 `deferred_evidence_policy`，禁止使用 holdout/valid/test/clean_10000/LOPO 等证据；未形成 full-clean-safe source manifest 与 readiness contract 前，不得宣称 READY、ranking input replacement 或 pool1000。
