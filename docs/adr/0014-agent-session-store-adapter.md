# ADR-0014：Agent 热会话存储采用可配置后端

## 状态

已接受

## 背景

`session-memory` Capability 依赖 `AgentHotSessionStore` 保存会话事件和压缩快照。固定内存实现只能覆盖单 JVM 生命周期，无法支持部署重启后的热会话恢复。

## 决策

- `AgentHotSessionStore` 保持为 Capability 的唯一存储边界；
- `rs.agent.session-store.type=memory`（默认）使用内存实现；
- `type=redis` 使用 Redis List 保存事件、String 保存最新快照；
- 事件 key 与快照 key 都以前缀加 `sessionId` 命名，默认前缀为 `agent:session:`；
- 事件写入和快照写入遵守可配置 TTL；会话内容仅限内部存储，不进入公开 SSE 或 Trace。

## 后果

部署环境可选择 Redis 实现以跨 JVM 保留热会话；本地开发仍保持零外部依赖。Redis 连接或序列化失败沿用 Capability 执行层的受控失败处理。
