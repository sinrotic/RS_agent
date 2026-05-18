# popular

## 方法定位
热门兜底召回，用于保证基础覆盖。它属于 `default_dataset_policy`，不要求单独建设高质量用户自定义数据集。

## 当前 readiness
- 状态：`READY`
- 可参与诊断合并。
- 受整体 route gate 约束，不能替代 ranking，也不能直接作为 pool1000 晋升依据。

## 治理契约
- 仅使用 train-only popularity / metadata 统计。
- 面向全用户做 fallback 覆盖补齐。
- 不引入 custom dataset，不做 promotion / ranking replacement / pool1000 替换。

## 适用用户
- 冷启动用户。
- 行为稀疏或所有重召回无命中的用户。
- 作为候选池尾部补齐来源。

## 输入 artifact
- lightweight views manifest 中的 popular recall 视图。

## 输出 artifact
- target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/popular/manifest.json`

## 资源画像
最近一次 target500 batch：
- row_count：81289
- readiness：READY

## 当前问题
贡献最大但个性化最低；如果 popular 占比过高，说明其他召回方法覆盖不足。

## 下一步
继续作为兜底保留，同时用 source budget 和用户质量分层限制其在高质量用户上的占比。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是控制 popular fallback 的预算占比、重复率和长尾挤占风险，而不是建设定制高质量用户数据集。Agent 必须保持 `default_dataset_policy`，只使用 train-only popularity / metadata 统计，不得把 popular 兜底覆盖解释为 pool500 final ready、ranking input replacement 或 pool1000 权限。
