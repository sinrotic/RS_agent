# swing_recall

## 方法定位
基于 Swing 共现思想的 item-item 召回，用于补充行为相似 item。它属于 `guarded_ready_policy`：可以视为 READY，但必须绑定已审计的 sidecar / manifest，并受 stoploss 与预算护栏约束。

## 当前 readiness
- 状态：`READY`
- index：`INDEX_READY`
- 输出：`FULL_OUTPUT_READY`
- 单个 source READY 不代表 pool500 全链路 ready。

## 治理契约
- 必须保留 audited sidecar / manifest 证据链。
- 必须受 resource budget、stoploss、route gate 约束。
- 若后续证据证明需要更细分数据集，可再引入 custom dataset；当前不默认要求。

## 适用用户
- 有近期正反馈 seed item。
- seed item 能命中 Swing 边。
- 适合中高行为密度用户的行为扩展。

## 输入 artifact
- clean train 行为数据。
- Swing full-derived index。

## 输出 artifact
- 最新可用 sidecar：`outputs/recall/pool500_sidecar_fix/swing_recall_v2/source_index_manifest.json`
- recall-only target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/swing_recall/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：3668
- readiness：READY / FULL_OUTPUT_READY

## 当前问题
单源可用，但整体 pool500 仍因 UserCF/ItemCF diagnostic、semantic/co_visit/two_tower deferred、underfill 而 STOP。

## 下一步
继续作为稳定行为召回来源，同时观察用户质量分层后的覆盖贡献和与 ItemCF 的重复率。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是验证 audited sidecar 的覆盖、去重后边际贡献、与 ItemCF/UserCF 的重复率以及 stoploss/budget guard，而不是默认重建定制数据集。Agent 必须保持 `guarded_ready_policy`，若要扩大或重建 Swing sidecar，需单独产出 source index manifest、resource audit 和 no-holdout 证据；READY 只表示该 source 当前可作为受控诊断来源，不授权 ranking replacement 或 pool1000。
