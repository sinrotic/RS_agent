# Java Agent Runtime

`java_agent/rs-service-agent` 是本轮唯一迁移范围内的 Agent Runtime。Python Agent 继续保留其既有职责，不与 Java Runtime 共享或竞争调度事实。

## 结构与配置

- `AgentTemplateProperties`：`rs.agent.templates` 配置入口；默认使用内置 `shopping-assistant` Profile。
- `AgentProfileRegistry`：把配置转换为不可变 `AgentRuntimeProfile`，并在启动时校验默认 Profile、allowlist 与循环上限。
- `AgentCapabilityRegistry`：唯一 Capability 执行入口；首批稳定 ID 是 `recommend`、`rag-explain`、`session-memory`。
- `AgentCapabilityToolUseExecutor`：将模型工具映射为 Capability，在执行前二次检查 Profile 授权。
- `PublicAgentResponseProjector`：唯一 final answer block 投影入口。
- `PublicAgentStreamProjector`：Controller 的公开 SSE 边界；仅向客户端发送 token、answer block、interrupt 和完成事件。
- Trace 只保留 profile/capability/status/error/usage 等安全元数据；Prompt、工具参数、原始 Capability payload 和检索证据不会进入公开流或 Trace data。

`application.yml` 的最小配置如下：

```yaml
rs:
  agent:
    templates:
      default-profile: shopping-assistant
```

完整决策见 [ADR-0009](adr/0009-java-agent-profile-configuration.md)、[ADR-0010](adr/0010-agent-capability-registry.md)、[ADR-0011](adr/0011-profiled-runtime-capability-execution.md)、[ADR-0012](adr/0012-public-agent-response-projection.md)。

## 验证

在 `java_agent` 目录运行：

```powershell
mvn -pl rs-service-agent -am test
```

重点覆盖：Profile/Capability 授权、公开输出投影、公开 SSE 边界、同步聊天与流式聊天、Session 恢复/取消/串行、虚拟线程工具执行和 Trace 安全元数据。

## 推荐服务适配

`AgentRecommendationService` 是 `recommend` Capability 的稳定边界。默认的 `memory` 模式用于本地开发；部署时可将 `rs.agent.recommendation.type` 设置为 `http`，通过 `base-url` 和 `candidates-path` 调用 `rs-service-recommend` 的 Agent 候选接口。HTTP 适配器只映射 Agent 所需的候选条目，不暴露下游原始响应或排序证据。详见 [ADR-0013](adr/0013-agent-recommendation-service-adapter.md)。

当对话请求含有非空查询词时，HTTP 适配器改用 `semantic-recall-path` 并把查询、会话、场景与约束发送给推荐服务；空查询继续使用候选接口。详见 [ADR-0015](adr/0015-query-aware-agent-recommendation.md)。

## 热会话存储

`AgentHotSessionStore` 是 `session-memory` Capability 的存储边界。默认 `rs.agent.session-store.type=memory` 用于本地运行；部署环境可切换为 `redis`，通过 `key-prefix` 隔离会话 key，并以 `ttl` 控制热事件和快照的保存时间。会话事件、压缩快照及其载荷不会进入公开 SSE 或 Trace。详见 [ADR-0014](adr/0014-agent-session-store-adapter.md)。
