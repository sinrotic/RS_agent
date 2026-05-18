# rs_lab 治理规则

## 实验晋升原则

实验方法从 `rs_lab` 下沉到 `rs_core` 前，必须同时满足：

1. readiness 为 `READY`，而不是 `DIAGNOSTIC_ONLY` 或 `DEFERRED`。
2. focused tests 和相关回归测试通过。
3. route gate 允许进入目标链路。
4. 资源画像稳定，重任务有内存 guard 或分批策略。
5. artifact contract 清晰，不混用诊断产物和正式产物。

## 禁止事项

- 不允许把诊断产物标记为 `FULL_POOL500_READY`。
- 不允许用 `DIAGNOSTIC_ONLY` source 替代 ranking input。
- 不允许在 pool500 未 ready 时直接扩大到 pool1000。
- 不允许未受控运行 UserCF / ItemCF 等重矩阵任务。

## 推荐流程

1. 在 `rs_lab` 中做 batch-scoped 诊断。
2. 记录 source manifest、readiness contract 和 resource audit。
3. 通过治理 registry 汇总方法状态。
4. 只有状态稳定后，再在 `rs_core` 建立或扩展正式实现。
