# two_tower

## 方法定位
向量召回 / 双塔召回，适合用 embedding 和 ANN 检索补充行为召回。它属于 `deferred_evidence_policy`：当前重点是补证据与缺失 artifact，不允许把旧产物直接当成 ready。

## 当前 readiness
- 状态：`DEFERRED`
- target500 batch row_count：0
- 当前不能复用旧 artifact 作为 full-clean-safe pool500 source。

## 治理契约
- 先补齐可审计证据，再谈 ready。
- 不接受老 artifact、holdout、valid、test、clean_10000、LOPO、youtube_dnn 之类作为 readiness 证据（如适用）。
- 未完成 full-clean-safe contract 前，不得标记为 ready。

## 适用用户
- 有足够 user feature 或行为序列生成 user embedding。
- item embedding 可通过 full-clean-safe 流程构建。
- 适合后续作为语义/行为混合召回补充。

## 输入 artifact
- 待建设：full-clean-safe user/item embedding、ANN index、manifest contract。

## 输出 artifact
- target500 per-source 占位：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/two_tower/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：0
- readiness：DEFERRED

## 当前问题
第一阶段不默认复用旧 YouTubeDNN/two_tower artifact；需要重新建立与当前数据基础匹配的 full-clean-safe 训练与索引合同。

## 下一步
暂不进入本轮主线。等 pool500 行为召回和语义扩展稳定后，再单独规划 GPU / ANN 的 two_tower 路线。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是重新规划 full-clean-safe two_tower 训练/索引链路，包括 item/user embedding、ANN index、model config hash、clean manifest hash、resource/GPU 计划和 no-holdout audit。Agent 必须保持 `deferred_evidence_policy`，不得复用旧 YouTubeDNN、clean_10000、LOPO 或 holdout 产物作为 readiness 证据；未完成新的 source index manifest 与 readiness contract 前，不得宣称 READY、ranking input replacement 或 pool1000。
