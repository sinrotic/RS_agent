# Agent Chat Wire Contract Design

**状态：** 已批准（2026-07-13）

## 目标

修复 Java 前端与 `rs-service-agent` 的同步聊天接口契约漂移，使真实模式下的 `POST /api/agent/chat` 使用一套可由 Java 与 TypeScript 共同验证的 JSON 契约。

本切片只解决请求、响应和前端映射，不改变 Agent 推荐逻辑，不接入新的 Session、Recommend、RAG、Catalog 或远程部署行为。

## 当前问题

前端目前发送：

```json
{
  "sessionId": "sess_001",
  "message": "想要一个通勤背包"
}
```

Java 后端要求 `session_id`、`profile_user_id` 和 `user_message`；后端响应使用 `request_id`、`assistant_message` 和 `recommended_items`，前端却直接按 `requestId`、`assistantMessage` 和 `items` 读取。TypeScript 类型检查无法发现运行时 JSON 字段不匹配。

## 设计决策

### 1. Wire 与 UI 模型分离

- HTTP JSON 一律使用 `snake_case`。
- React 组件内部继续使用 `camelCase`。
- `agentClient` 不再把后端 JSON 强制断言为页面类型。
- 新建纯函数负责构建 wire request 和映射 wire response。

这样，后端字段变化只影响契约层，不直接扩散到页面组件。

### 2. Canonical Request

`POST /api/agent/chat`

```json
{
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "user_message": "想要一个通勤背包",
  "limit": 5,
  "context": {
    "scene": "agent_chat"
  }
}
```

字段规则：

- `session_id`：必填，非空。
- `profile_user_id`：本切片由前端当前登录上下文传入；后续鉴权切片再改为服务端可信身份。
- `user_message`：必填，去除首尾空白后非空。
- `limit`：固定由前端传 `5`，后端仍保留默认值逻辑。
- `context.scene`：本切片固定为 `agent_chat`。

前端调用签名改为：

```typescript
sendChat(sessionId: string, profileUserId: string, message: string): Promise<AgentChatResponse>
```

### 3. Canonical Response

```json
{
  "request_id": "agent_req_001",
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "turn_index": 1,
  "assistant_message": "我会优先推荐通勤背包，并补充可解释证据。",
  "recommended_items": [
    {
      "item_id": "B001",
      "title": "Commuter Backpack",
      "category": "Backpacks",
      "score": 0.91,
      "reason": "匹配通勤、轻量和中价位偏好"
    }
  ],
  "tool_calls": [
    {
      "tool_call_id": "toolu_001",
      "tool_name": "recommend_candidates",
      "service": "rs-service-recommend",
      "status": "SUCCESS",
      "metadata": {
        "limit": 5
      }
    }
  ]
}
```

`turn_index` 是正式响应字段。它由服务端按 session 已记录 turn 数量计算，从 `1` 开始，避免前端随机生成或猜测轮次。

### 4. Frontend Mapping

新增以下 wire 类型：

```typescript
export interface AgentChatWireRequest {
  session_id: string;
  profile_user_id: string;
  user_message: string;
  limit: number;
  context: { scene: 'agent_chat' };
}

export interface AgentChatWireResponse {
  request_id: string;
  session_id: string;
  profile_user_id: string;
  turn_index: number;
  assistant_message: string;
  recommended_items: AgentRecommendedItemWire[];
  tool_calls: AgentToolCallWire[];
}
```

映射后的页面模型保持：

```typescript
export interface AgentChatResponse {
  requestId: string;
  sessionId: string;
  assistantMessage: string;
  items: RecommendItemVO[];
  turnIndex: number;
}
```

`recommended_items` 映射为 `RecommendItemVO` 时：

- `rank` 使用数组下标加一。
- `score` 与 `reason` 原样保留。
- `source_tags` 固定为 `['agent_recommendation']`。
- `display.title` 和 `display.category` 使用 Agent 响应。
- `display.store` 和 `display.image_url` 先使用空字符串，随后仍由现有 Catalog 合并逻辑补齐。

### 5. Error Behavior

- 缺少 `session_id`、`profile_user_id` 或空 `user_message` 时，后端返回 HTTP `400`，不得进入 `AgentChatService`。
- 后端返回非 `2xx` 时，前端沿用 `requestJson` 的统一错误处理。
- 响应缺少 `request_id`、`turn_index` 或 `assistant_message` 时，前端映射函数抛出明确的契约错误，不生成假 request id 或随机 turn。
- 本切片不修改流式 `/api/agent/chat/stream` 契约。

## TDD 验证结构

### 共享契约样例

创建：

```text
java_agent/contracts/agent-chat/request.json
java_agent/contracts/agent-chat/response.json
```

Java 与前端测试读取同一份 JSON，避免两边各自复制期望字段。

### Java RED

扩展 `AgentChatControllerTest`：

- 从共享 request fixture 发起 MockMvc 请求。
- 验证 controller 收到完整 DTO。
- 从共享 response fixture 验证序列化结果。
- 新增缺少必填字段时返回 `400` 的测试。
- 首次 RED 原因应是 `turn_index` 缺失以及请求尚无 Bean Validation。

### Frontend RED

为 Java 前端加入 Vitest，并新增纯契约测试：

- `buildAgentChatWireRequest()` 必须生成共享 request fixture 的结构。
- `mapAgentChatWireResponse()` 必须把共享 response fixture 映射为页面模型。
- `sendChat()` 必须调用 `/agent/chat`，并传入 canonical wire request。
- 首次 RED 原因应是 wire 构建器、映射器不存在，而不是测试环境错误。

## 文件边界

计划涉及：

```text
java_agent/contracts/agent-chat/request.json
java_agent/contracts/agent-chat/response.json
java_agent/frontend/package.json
java_agent/frontend/package-lock.json
java_agent/frontend/src/api/agentClient.ts
java_agent/frontend/src/api/agentContract.ts
java_agent/frontend/src/api/agentContract.test.ts
java_agent/frontend/src/types/agent.ts
java_agent/frontend/src/views/AgentChat.tsx
java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/dto/AgentChatRequestDTO.java
java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentChatVO.java
java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java
java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/controller/app/AgentChatControllerTest.java
```

不会修改 Gateway、Session、Recommend、RAG、Catalog、Cloudflare Tunnel 或远程 Compose。

## 验收标准

本切片完成时必须同时满足：

1. Java 与 TypeScript 使用同一份 request/response fixture。
2. 前端真实模式发送 canonical `snake_case` 请求。
3. Java 返回包含 `turn_index` 的 canonical 响应。
4. 前端不再对 wire JSON 做不安全的页面类型断言。
5. 非法请求返回 `400`，契约缺字段时前端明确失败。
6. Java focused tests、Java frontend tests 和 TypeScript typecheck 全部通过。
7. 尚未执行远程部署；远程 Smoke 属于黄金链路后续切片。

## 每轮停靠点

实施时在以下位置暂停并向用户展示证据：

1. RED 测试及其预期失败。
2. 最小 GREEN 修改及 focused tests。
3. REFACTOR 后的完整相关回归。
4. 最终 diff 与下一切片建议。
