---
id: kb-contracts
type: contracts
status: current
owner: project-maintainers
last_verified: 2026-10-18
confidence: confirmed
---

# 接口与数据契约

2026-09-05：平台 Trace 入口要求 ADMIN 或 OBSERVER，下游调用失败返回 502；Model 未配置能力返回 503，Mock 需显式 mock-models profile。首页游标表示目录消费位置，允许有界扫描后的短页继续。详见 [服务修复记录](../superpowers/plans/2026-09-05-service-reliability-repairs.md)。

## 契约权威顺序

接口事实按以下顺序确认：

1. Java Controller、DTO/VO、Gateway route/filter 和对应 contract test。
2. Python FastAPI router、Pydantic/Dataclass Schema 和对应 serving/contract test。
3. 前端 TypeScript 类型与 client test，必须与服务端 wire contract 一致，但不是服务端事实来源。
4. 设计文档和本页用于解释边界；示例不得覆盖当前代码。

修改公开字段时，应同时更新服务端 Schema、前端类型、契约测试和本页索引。

## 接口命名空间

| 前缀 | 调用者 | 语义 | 是否经公共 Gateway |
| --- | --- | --- | --- |
| `/api/**` | 浏览器或外部应用客户端 | 产品 API，需要认证，登录/注册/刷新除外 | 是 |
| `/internal/**` | 可信服务 | 服务间接口，不得直接暴露公网 | 否 |
| `/agent/**` | Agent 工具适配器 | 稳定的推荐语义工具接口 | 否 |
| `/api/platform/**` | 平台观察/管理界面 | Trace、健康、运行配置和平台视图 | 是，仍需认证/角色保护 |
| `/callback/**` | 外部提供方 | 支付等回调，必须在目标服务验证签名和重放 | 仅 `full-commerce` 特定路由 |

路径前缀不能代替授权。新增 `/internal` 或 `/agent` 接口时，部署层仍必须保证它只能从受信网络访问。

## Java 外部 API 索引

下表列出当前外部能力族，不替代 Controller 的逐字段定义。

| 服务 | 路径族 | 主要能力 | 源码入口 |
| --- | --- | --- | --- |
| User | `/api/auth/**` | register、login、refresh、me、logout | `rs-service-user/.../controller/auth/AuthController.java` |
| User | `/api/users/**`、`/api/sessions/**` | 用户画像视图和用户 Session 创建/结束 | `rs-service-user/.../controller/app/` |
| Catalog | `/api/catalog/categories/**` | 类目与类目商品 | `CatalogCategoryController` |
| Catalog | `/api/catalog/items/**` | 商品详情、批量商品卡 | `CatalogItemController` |
| Catalog | `/api/catalog/stores/**` | 虚拟店铺和店铺商品 | `VirtualStoreController` |
| Recommend | `/api/recommend/home`、`/home/refresh` | 首页推荐与换一批 | `HomeRecommendController` |
| Recommend | `/api/recommend/feedback/**` | exposure 与交互事件 | `RecommendFeedbackController` |
| Agent | `/api/agent/chat`、`/chat/stream` | 同步与 SSE 对话 | `AgentChatController` |
| Agent | `/api/agent/sessions/{sessionId}/turns` | 当前画像用户拥有的 Session Turn | `AgentChatController` |
| Agent | `/api/agent/requests/{requestId}/interrupt` | 中断当前画像用户拥有的运行 | `AgentChatController` |
| Model | `/api/model/health` | 模型服务总健康 | `ModelHealthController` |
| Platform | `/api/platform/**` | User、Recommend、Agent、Model 的观察和受控运行配置 | 各服务 `controller/platform/` |
| Inventory | `/api/inventory/items/{itemId}/availability` | 商品库存可用性 | `AppInventoryController` |
| Trade | `/api/orders/**`、`/api/payments/**`、`/api/seckill/**` | 可选交易能力 | 对应服务 Controller，仅 `full-commerce` 可依赖 |

Gateway 路由最终以 [application.yml](../../java_agent/rs-api-gateway/src/main/resources/application.yml) 和 [application-full-commerce.yml](../../java_agent/rs-api-gateway/src/main/resources/application-full-commerce.yml) 为准。不能因为 Controller 存在就认定当前 deployment profile 一定可访问。

## Java 内部与 Agent API 索引

| 所有者 | 路径族 | 用途 |
| --- | --- | --- |
| Catalog | `/internal/catalog/context/**`、`/internal/catalog/items/**` | 商品文本、RAG 文档、embedding 文本和服务间商品视图 |
| Recommend | `/agent/recommend/**` | candidates、semantic recall、profile pipeline、fallback、rerank、RAG support |
| Recommend | `/internal/recommend/**` | 按 Session/Profile 推荐与 recall/coarse/fine/final pipeline |
| Recommend | `/internal/recommend/rag/**` | 批量证据和 RAG pipeline |
| Recommend | `/internal/recommend/semantic-item-index/**` | 语义商品索引重建 |
| Model | `/internal/model/**` | chat、stream、embed、infer、rank、registry 和健康 |
| Trace | `/internal/platform-trace/**` | Account profile、Recommend trace、Agent turn/event、交互事件写入 |
| Inventory | `/internal/inventory/**` | lock、confirm-deduct、release |
| Order | `/internal/orders/**` | paid、close-timeout |

Agent 不得直接调用 Elasticsearch/Milvus 或低层模型接口来绕过 Recommend 的业务契约。

## 认证与可信身份

Gateway 的当前规则：

- `/api/auth/login`、`/api/auth/register`、`/api/auth/refresh` 和 `OPTIONS` 不要求 bearer access token。
- 其他 `/api/**` 需要 `Authorization: Bearer <token>`。
- Gateway 先移除客户端提交的 `X-Account-Id`、`X-Profile-User-Id`、`X-User-Roles`，再根据已验证 token 注入可信值。
- 缺少 `X-Request-Id` 时 Gateway 生成 UUID，并向下游传递。
- 默认限流为每客户端每分钟 120 个 `/api/**` 请求；只有来自受信代理地址的 `X-Forwarded-For` 才参与真实客户端识别。

因此业务 Controller 必须信任 Gateway 注入的身份，而不是请求体内可伪造的 `profile_user_id`。Agent Controller 当前会用可信头覆盖请求体身份。

## 关键 Wire Contract

### Agent chat

正式请求使用 `snake_case`：

```json
{
  "session_id": "sess_001",
  "profile_user_id": "untrusted-client-value",
  "user_message": "想找一款通勤耳机",
  "limit": 5,
  "context": {"scene": "agent_chat"}
}
```

服务端使用 Gateway 注入的 `X-Profile-User-Id` 覆盖请求体中的画像用户。`limit` 为空或非正数时默认 5。

### Agent SSE

`POST /api/agent/chat/stream` 返回 `text/event-stream`。每个事件包含：

```text
event: <event-name>
data: {"event":"...","request_id":"...","data":{...}}
```

异常路径也必须发送 `error`，随后发送 `done` 且 `finish_reason=error`。客户端应按事件语义消费，不应依赖网络断开来判断正常完成。

### Catalog 批量补全

```json
{
  "item_ids": ["B001", "B002"]
}
```

规则：最多处理 100 个 ID；忽略空白 ID；未知 ID 不生成伪造商品；结果维持输入展示语义。完整字段以 `CatalogItemCardVO` 为准。

### 公开展示边界

公开展示使用 allowlist-first。以下内部证据不得进入 Agent/前端公开 payload：

- `trace_ref`
- `agent_runtime_trace`
- `diagnostics_path`
- `raw_export_trace_path`
- `ranking_evidence_path`

公开层只消费稳定的标识、展示字段、rank/score/reason、状态和明确允许的 timeline 字段。内部证据的保留不等于公开授权。

## Python Serving API

Python 当前有两类入口：

| 入口 | 路径 | 角色 |
| --- | --- | --- |
| 单进程 demo app | `/health`、`/ready`、`/session/start`、`/chat`、`/feedback`、`/session/end`、`/recommend`、`/feed/refresh`、`/session/{id}`、受控 demo/simulation | 本地展示、Session 闭环和仿真 |
| online split app | `/health`、`/ready`、`/recommend`、`/recall`、`/rank` | 在线推荐边界验证 |
| agent split app | `/health`、`/ready`、`/session/start`、`/chat`、`/chat/stream`、`/feedback`、`/rag/query`、`/session/end`、`/session/{id}` | Agent 服务边界验证 |

路由权威入口为 [factory.py](../../python_agent/rs_core/serving/api/factory.py)、[split_factory.py](../../python_agent/rs_core/serving/api/split_factory.py) 和 `rs_core/serving/api/routers/`。Python API 是 prototype/试运行契约，不能在没有集成决策时被当作 Java Gateway 的同名替代品。

## 事件契约

2026-10-18：平台 Agent Monitor 的 summary 输入/输出/总 token 和 phase 总 token 允许 null，未知不再补零。新增 `usage_coverage` 区分最终逐次调用、未核验历史与混合记录，返回各字段小计和最终回执覆盖率；原始事件入口保留。summary/phase 的耗时改为已测量时间区间并集，阶段可重叠，不能再次相加。新前后端配套升级。外部 OTLP 只发送白名单元数据与 HMAC 标识，并保持独立关闭，完整契约与验证见 [平台计量及 OTLP 报告](../reports/agent-otlp-and-usage-20261018/README.md)。

- Agent 会话事实使用领域定义的 Session Event；事件顺序与恢复约束见 [领域模型与核心不变量](domain-and-invariants.md)。
- `full-commerce` 秒杀使用 Kafka 主题 `seckill-order-create`，Order 以 consumer group `rs-service-order` 消费。
- 交易消息必须保留消费者幂等记录；当前 Schema 包含 `consumer_message_log`。
- 新增消息时必须记录 topic、producer、consumer group、key、payload Schema、幂等键、重试和失败处理，不能只记录 Java 类名。

## 兼容性规则

1. 新增可选字段通常可以向后兼容；删除、重命名、改变类型或语义必须版本化或提供迁移窗口。
2. `request_id`、`session_id`、`turn_id`、`item_id` 和 `profile_user_id` 不得混用或由前端猜测生成。
3. 内部 DTO 不得未经 allowlist 直接序列化为公开响应。
4. 前端 mock contract 与真实 backend contract 必须隔离，mock token 或 mock 字段不能进入真实请求。
5. 接口错误至少需要稳定 HTTP status 和机器可读 `code`；Gateway 当前错误形状为 `{"code":"...","message":"..."}`。
6. 修改 SSE 事件名、完成语义或字段时必须增加 wire contract test。

## 已知契约漂移

- Java 前端 README 的 `/api/items/*`、`/api/interactions/*` 摘要与当前 Gateway/Controller 不一致；以源码为准。
- 默认 Gateway 配置存在 `/api/inventory/**` 路由，而远程 compose 将 Inventory 放在 `full-commerce` profile。路径存在不等于默认部署后端可用，应通过 profile smoke 澄清并统一配置或文档。
