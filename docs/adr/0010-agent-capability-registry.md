# ADR-0010：Java Agent Capability Registry

## 状态

已接受（2026-08-08）。

## 决策

Java Agent 以 `AgentCapability` 作为可执行能力边界；每项能力必须提供稳定 ID、说明、输入 Schema、`replaySafe` 和 `publicVisible` 元数据。`AgentCapabilityRegistry` 是 Runtime 调用 Adapter 的唯一入口。

执行前 Registry 同时校验：请求 Profile 与运行时 Profile 一致、Capability 已显式注册、Capability 在 Template allowlist 中、Capability 为 replay-safe。任一条件不满足均返回带错误码的结构化失败，且不执行 Adapter。Adapter 异常同样转换为结构化失败，供现有工具循环记录并继续处理。

首批稳定 ID 为 `recommend`、`rag-explain`、`session-memory`：

- `recommend` 仅调用 `AgentRecommendationService`；
- `rag-explain` 仅调用现有 `AgentDelegateService` 的 `rag_agent` 路由；
- `session-memory` 仅调用 `AgentHotSessionStore` 的只读入口。

Adapter 不直接访问 Elasticsearch、Milvus 或数据库。首版只允许 replay-safe Capability；输出投影和 Model Tool 到 Capability 的路由绑定留给后续 Runtime 集成票据处理。

## 后果

新增或替换业务能力时，只需提供 Adapter 并显式注册，不应把基础设施细节带入 Agent Loop。Template allowlist 与 Registry 的双重校验使模型生成的工具请求不能绕过能力授权。
