# ADR-0011：Profile 驱动的 Runtime Capability 执行

## 状态

已接受（2026-08-08）。

## 决策

Java Agent Runtime 将模型侧的工具名映射到稳定的 Capability ID。模型工具 schema 只暴露当前服务端默认 Profile 允许的 Capability；执行阶段再由 `AgentCapabilityToolUseExecutor` 通过 `AgentCapabilityRegistry` 复核授权。两层检查共同防止模型输出、过期 tool schema 或调用方构造的事件绕过 Profile allowlist。

首批映射如下：

- 所有 `recommend_*` 路由到 `recommend`；
- `rag_support` 和 `rag_evidence_search` 路由到 `rag-explain`；
- `session_memory` 路由到 `session-memory`。

没有 Capability 映射的内部工具（例如 `load_skill`、`call_agent`、`emit_final_answer`）仍可交给原有执行器，但必须已经在 Runtime 工具注册表中启用。其他未知工具直接以 `TOOL_NOT_REGISTERED` 返回，不能进入任何业务调用。

Agent Loop 每轮从服务端默认 Profile 获取最大循环次数，并把 profile id、模型引用、系统提示词引用、Capability allowlist 和公开输出块 allowlist 写入受控 Runtime context。`emit_final_answer` 仅接受 Profile 允许的 block 类型。

## 后果

- Profile 选择仍由服务端配置决定，用户请求无法切换 Profile；
- 新增模型工具时，必须显式决定它是内部工具还是 Capability 映射，并补充测试；
- `modelRef` 目前是 Runtime 选择元数据；实际模型提供商仍沿用现有 Spring AI 配置，动态多模型路由属于后续票据；
- 推荐、RAG 和会话读取继续复用既有 Java 服务边界，不把数据源实现带入 Agent Loop。
