# ADR-0013：Agent 推荐能力采用可配置服务适配器

## 状态

已接受

## 背景

`recommend` 是 Java Agent 的通用 Capability，但早期实现只返回固定内存样例。若 Capability 直接依赖商品推荐业务实现，Agent Runtime 会与推荐服务耦合，测试和本地开发也会失去轻量兜底。

## 决策

- `AgentRecommendationService` 继续作为 Capability 的稳定边界；
- `rs.agent.recommendation.type=memory`（默认）使用内存实现，便于本地运行和隔离下游故障；
- `type=http` 使用 `HttpAgentRecommendationClient` 调用 `rs-service-recommend` 的 `/agent/recommend/candidates`；
- HTTP 响应只映射为 Agent 所需的条目字段，不把推荐服务原始响应、排序证据或底层异常放入公开 SSE/Trace；
- 服务地址和路径均由配置提供，后续可替换为服务发现或其他传输实现而不改变 Capability 合约。

## 后果

Agent Runtime 不需要知道推荐服务的领域 DTO；部署环境可以显式选择真实服务或内存模式。HTTP 模式的网络失败会由现有 Capability 执行层转换为受控失败结果，本地默认行为保持兼容。
