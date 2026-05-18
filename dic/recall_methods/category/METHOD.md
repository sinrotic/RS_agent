# category

## 方法定位
基于用户历史 item 的类目召回，用于提供稳定覆盖和非个性化弱相关候选。它属于 `default_dataset_policy`，不要求单独建设高质量用户自定义数据集。

## 当前 readiness
- 状态：`READY`
- 可参与诊断合并。
- 仍受整体 route gate 约束，不能单独决定 pool500 晋升，也不能替代 ranking。

## 治理契约
- 仅使用 train-only popularity / category metadata。
- 面向全用户做 fallback 覆盖补齐。
- 不引入 custom dataset，不做 promotion / ranking replacement / pool1000 替换。

## 适用用户
- 有可解析 category 的历史行为。
- 行为不足以支持重 CF 时，可作为主要覆盖来源。
- 适合中低行为密度用户和 fallback 场景。

## 输入 artifact
- lightweight views manifest 中的 category recall / top item 视图。
- item category metadata。

## 输出 artifact
- target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/category/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：30193
- readiness：READY

## 当前问题
覆盖稳定但个性化较弱；当前 underfill 仍为 500/500，说明 category 不能单独撑满 pool500。

## 下一步
继续与用户质量分层结合：冷启动和低行为用户依赖 category，高质量用户应让重召回优先贡献更多候选。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是检查 category fallback 的覆盖、预算占比和与 popular 的重复率，而不是建设定制高质量用户数据集。Agent 必须保持 `default_dataset_policy`，只使用 train-only category metadata / lightweight views，不得把 category 的 READY 状态解释为 pool500 final ready、ranking input replacement 或 pool1000 权限。
