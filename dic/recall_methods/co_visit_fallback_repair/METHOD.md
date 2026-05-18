# co_visit_fallback_repair

## 方法定位
共访 fallback 修复源，用于补行为召回的连接缺口。它属于 `deferred_evidence_policy`，当前重点是补证据与缺失 artifact，不允许伪装成 ready。

## 当前 readiness
- 状态：`DEFERRED`
- target500 batch row_count：0

## 治理契约
- 先补齐可审计证据，再谈 ready。
- 不接受老 artifact、holdout、valid、test、clean_10000、LOPO、youtube_dnn 之类作为 readiness 证据（如适用）。
- 未完成 full-clean-safe contract 前，不得标记为 ready。

## 适用用户
- 有可形成 co-visit 关系的近期行为。
- CF 边不足但局部共访邻接可用。
- 适合作为 fallback repair，而不是主召回。

## 输入 artifact
- co-visit 或 metadata neighbor 相关索引。
- train-only 行为数据。

## 输出 artifact
- target500 per-source 占位：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/co_visit_fallback_repair/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：0
- readiness：DEFERRED

## 当前问题
当前没有可晋升 artifact，仍只是 source registry 中的 deferred 来源。

## 下一步
先在用户质量分层中识别“CF 弱连接但有 co-visit 迹象”的用户，再决定是否建设轻量 fallback repair sidecar。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是识别 CF 弱连接但具备 co-visit 迹象的用户，验证 fallback repair 是否能补 underfill，而不是把它作为主召回源。Agent 必须保持 `deferred_evidence_policy`，产出 train-only co-visit input、触发条件、repair boundary、resource audit 和诊断 manifest；未通过 source gate 前不得宣称 READY、ranking input replacement 或 pool1000。
