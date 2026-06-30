# rs_lab 实验层

`rs_lab` 是推荐系统实验承载层，用于放置尚未沉淀为稳定 core 能力的实验脚本、诊断 batch、资源画像和阶段性 gate 结果。

## 边界

- `rs_lab` 可以承载 recall / ranking 的探索性实验、受控诊断和 sidecar 构建流程。
- `rs_lab` 产物不自动代表生产可用，也不自动代表 `FULL_POOL500_READY`。
- 只有经过治理 gate、测试验证和资源审计的稳定能力，才考虑下沉到 `rs_core`。

## 与 rs_core 的关系

- `rs_core` 保存稳定数据结构、服务接口、候选合并、route gate 和可长期维护的薄抽象。
- `rs_lab` 保存实验实现与运行记录，避免把 `DIAGNOSTIC_ONLY` 或 `DEFERRED` 方法过早固化进 core。

## 当前重点

pool500 召回当前仍处于诊断扩大阶段：target20 / target100 / target500 诊断链路已跑通，但 gate 仍保持 `STOP`，不能替代排序输入。
