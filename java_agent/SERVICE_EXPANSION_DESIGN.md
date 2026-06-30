# 推荐 Agent Java 微服务扩展规划

## 1. 背景和设计原则

当前 Java 服务不应该照搬完整 B2B2C 商城。mall4cloud 的服务边界适合作为参考，但本项目的核心不是交易履约，而是基于推荐数据集构建一个可演示、可解释、可对话的推荐 Agent 平台。

本项目中的用户、商品和店铺具有明显的数据集虚拟化特征：

- 用户侧：真实注册账号绑定一个画像用户，后续推荐和 Agent 个性化围绕 `profile_user_id` 展开。
- 商品侧：商品来自数据集 metadata 和后续整理出的 catalog，不需要完整电商 SPU/SKU、库存和履约体系。
- 店铺侧：`store` 字段可虚拟化为店铺展示维度，但不等同真实商家实体。
- 推荐侧：核心价值在召回、排序、RAG grounding、Agent 对话、反馈闭环和链路可观测。

因此，服务扩展遵循以下原则：

1. **参考 mall4cloud，但不照搬完整商城**：保留 product、search、platform 等服务中对推荐链路有价值的部分。
2. **围绕推荐 Agent 主线拆服务**：优先补齐商品展示、搜索证据、行为闭环、链路观察。
3. **暂不做真实交易能力**：订单、支付、售后、履约、结算、完整商家后台先不进入当前阶段。
4. **服务先轻量规划，后续再落代码**：先明确边界和 Controller，再按 `rs-service-user` 的骨架方式实现。
5. **前台自然对话，后台复杂编排隐藏**：用户只感知注册、浏览、对话和反馈；推荐、RAG、工具调用和 trace 在后台完成。

## 2. 三个建议新增服务总览

最新调整：推荐链路里的搜索 / RAG evidence 不再作为长期独立微服务，已经迁入 `rs-service-recommend`。原 `rs-service-search-rag` 模块已从父工程和仓库目录中移除。更详细的边界见 `AGENT_RAG_BOUNDARY_DESIGN.md`。

建议新增三个长期服务：

| 服务 | 定位 | 对应 mall4cloud 参考 | 当前价值 |
| --- | --- | --- | --- |
| `rs-service-catalog` | 商品目录 / 虚拟店铺服务 | `mall4cloud-product` + 部分 `mall4cloud-multishop` | 给推荐、Agent 和前端提供商品详情、商品卡片、类目和虚拟店铺信息 |
| `rs-service-interaction` | 用户行为 / 反馈闭环服务 | mall4cloud 中没有完全对应服务 | 记录曝光、点击、收藏、反馈、模拟购买，支撑推荐闭环 |
| `rs-service-platform-trace` | 平台观察 / 推荐链路追踪服务 | `mall4cloud-platform` 的轻量化改造 | 查看账号画像、推荐 trace、排序分数、RAG evidence、Agent 工具调用和反馈事件 |

这三个长期服务和现有服务的关系是：

```text
rs-service-user
  负责真实账号、双 token、profile_user_id 绑定、session context

rs-service-catalog
  负责商品、类目、虚拟店铺、商品卡片

rs-service-recommend
  负责召回、排序、推荐理由、推荐 trace、推荐链路内的搜索 / RAG evidence / grounding

rs-service-agent
  负责多轮对话、偏好澄清、工具编排、自然语言解释

rs-service-interaction
  负责曝光、点击、反馈、模拟转化

rs-service-platform-trace
  负责链路观察、调试展示、面试演示
```

## 3. `rs-service-catalog`：商品目录 / 虚拟店铺服务

### 3.1 服务定位

`rs-service-catalog` 是推荐结果展示的基础服务。推荐服务可以只返回 `item_id`、分数和原因，但前端和 Agent 需要展示商品标题、图片、价格、类目、店铺、属性和文本摘要，这些信息应该由 catalog 统一提供。

它对应 mall4cloud 中的：

- `mall4cloud-product`：商品、类目、品牌、属性。
- `mall4cloud-multishop` 的一小部分：店铺信息、店铺商品列表。

但本项目不做完整商品中台，只做数据集商品目录和虚拟店铺展示。

### 3.2 核心职责

- 商品详情查询。
- 商品卡片批量补全。
- 类目树 / 类目列表。
- brand / store 展示维度。
- 虚拟店铺信息。
- 给推荐服务补商品展示信息。
- 给 Agent 组织商品卡片和解释上下文。
- 给 RAG 服务提供商品文本、属性和 metadata。

### 3.3 暂不负责

- 真实 SPU/SKU 全生命周期管理。
- 库存锁定。
- 真实商家入驻。
- 店铺审核。
- 商家后台。
- 商品上下架审批流。
- 复杂促销、优惠券、价格策略。

### 3.4 建议 Controller

```text
com.sinrotic.rs.catalog.controller
├── app
│   ├── CatalogItemController.java
│   ├── CategoryController.java
│   └── VirtualStoreController.java
├── internal
│   └── InternalCatalogController.java
└── platform
    └── PlatformCatalogController.java
```

### 3.5 建议接口

#### 商品详情

```text
GET /api/items/{item_id}
```

用途：前端打开商品详情页，或 Agent 展示单个商品时使用。

返回建议：

```json
{
  "item_id": "B001",
  "title": "Commuter Backpack",
  "category": "Backpacks",
  "brand": "Urban Carry",
  "store": "Urban Carry Store",
  "price": 39.99,
  "image_url": "https://example.com/item.jpg",
  "attributes": {
    "color": "black",
    "material": "nylon"
  },
  "summary": "适合通勤和日常收纳的中价位背包"
}
```

#### 批量商品卡片

```text
POST /api/items/batch
POST /internal/items/batch-card
```

用途：推荐服务返回一批 `item_id` 后，前端或内部服务批量补商品卡片。

请求示例：

```json
{
  "item_ids": ["B001", "B002", "B003"]
}
```

#### 类目查询

```text
GET /api/categories
GET /api/categories/{category_id}/items
```

用途：前端类目页、推荐解释、平台观察台。

#### 虚拟店铺查询

```text
GET /api/stores/{store_id}
GET /api/stores/{store_id}/items
GET /api/stores/random
```

用途：将数据集中的 `store` 字段展示为虚拟店铺。

### 3.6 和其他服务的协同

```text
recommend-service
  -> 输出 item_id 列表
  -> 调 catalog-service 补商品卡片

agent-service
  -> 调 catalog-service 获取商品详情
  -> 组织自然语言推荐解释和前端商品卡片

recommend-service RAG 子域
  -> 使用 catalog-service 的商品文本构建知识片段
  -> 或按 item_id 查询商品 metadata

platform-trace
  -> 展示推荐结果中的商品基础信息
```

## 4. `rs-service-recommend` 内部 RAG 子域：搜索 / RAG 证据

本节原先规划为独立 `rs-service-search-rag`，现在迁移为 `rs-service-recommend` 内部 RAG 子域。推荐链路里的关键词搜索、候选证据检索、RAG grounding、rerank evidence 和 small2big 压缩都由推荐服务统一暴露。旧模块已移除。

### 4.1 服务定位

`rs-service-recommend` 内部 RAG 子域参考 mall4cloud 的 `search` 能力，但不再单独拆成搜索微服务。

它负责把用户自然语言、推荐候选商品、商品文本、商品属性和知识片段连接起来，为推荐理由和 Agent 回答提供可追溯证据。

### 4.2 核心职责

- 关键词商品搜索。
- 自然语言商品检索。
- 按 `item_id` 查询商品证据。
- 批量查询 RAG evidence。
- 给 Agent 提供 grounding 信息。
- 给推荐解释提供文本证据。
- 对接 Python 侧 BM25、向量库、rerank、RAG pipeline。

### 4.3 暂不负责

- 完整 Elasticsearch 管理后台。
- 订单搜索。
- 商家后台搜索。
- Canal 级别复杂索引同步。
- 大规模索引调度平台。

### 4.4 建议 Controller

```text
com.sinrotic.rs.recommend.controller
├── agent
│   └── AgentRecommendController.java
├── internal
│   ├── InternalRecommendRagEvidenceController.java
│   └── InternalRecommendRagPipelineController.java
└── platform
    └── PlatformRecommendRagTraceController.java
```

### 4.5 建议接口

#### 商品搜索

```text
POST /api/recommend/search/items
```

请求示例：

```json
{
  "query": "适合通勤的黑色背包",
  "session_id": "sess_001",
  "top_k": 20
}
```

返回建议：

```json
{
  "query": "适合通勤的黑色背包",
  "items": [
    {
      "item_id": "B001",
      "score": 0.87,
      "matched_fields": ["title", "description", "category"],
      "evidence": "商品描述中包含通勤、轻量、防水等信息"
    }
  ]
}
```

#### RAG 问答 / 检索

```text
POST /api/recommend/rag/query
```

用途：Agent 面对用户自然语言问题时，检索商品或领域知识证据。

#### 商品证据查询

```text
POST /agent/recommend/rag/support
POST /internal/recommend/rag/batch-evidence
POST /internal/recommend/rag/pipeline/run
GET  /api/platform/recommend/rag/{requestId}/trace
GET  /api/platform/recommend/rag/health
```

用途：推荐结果出来后，按 item 批量补证据，避免 Agent 自己编理由。

### 4.6 Java 和 Python 的边界

建议边界如下：

```text
Java rs-service-recommend
  - 提供统一 HTTP API
  - 处理鉴权、请求参数、响应结构
  - 调用 Python RAG 服务或已构建的检索接口
  - 对 agent/internal/platform 统一返回 item evidence / chunk evidence / pipeline trace

Python RAG 模块
  - 负责 BM25/向量检索
  - 负责 rerank
  - 负责知识库构建
  - 负责离线索引生成
```

这样 Java 服务负责微服务治理和业务接口，Python 保留算法和检索工程能力。

## 5. `rs-service-interaction`：用户行为 / 反馈闭环服务

### 5.1 服务定位

`rs-service-interaction` 是推荐闭环服务。mall4cloud 的行为能力分散在订单、购物车、商品和搜索模块中，但本项目更适合把推荐相关行为单独抽出来。

它不负责真实交易，而是记录推荐系统需要的反馈信号。

### 5.2 核心职责

- 曝光记录。
- 点击记录。
- 收藏 / 喜欢。
- 不喜欢 / 负反馈。
- 模拟加购。
- 模拟购买。
- Agent 对话中的正负反馈。
- 推荐 request 级别的行为归因。
- 给 user/recommend/agent 提供 session 内近期行为。

### 5.3 暂不负责

- 真实订单。
- 支付。
- 退款。
- 发货。
- 售后。
- 地址履约。
- 商家结算。

### 5.4 建议 Controller

```text
com.sinrotic.rs.interaction.controller
├── app
│   └── InteractionController.java
├── internal
│   └── InternalInteractionController.java
└── platform
    └── PlatformInteractionController.java
```

### 5.5 建议接口

#### 曝光上报

```text
POST /api/interactions/exposure
```

请求示例：

```json
{
  "session_id": "sess_001",
  "request_id": "rec_req_001",
  "item_ids": ["B001", "B002", "B003"],
  "scene": "home_recommend"
}
```

#### 点击上报

```text
POST /api/interactions/click
```

请求示例：

```json
{
  "session_id": "sess_001",
  "request_id": "rec_req_001",
  "item_id": "B001",
  "scene": "home_recommend"
}
```

#### 反馈上报

```text
POST /api/interactions/feedback
```

请求示例：

```json
{
  "session_id": "sess_001",
  "item_id": "B001",
  "feedback_type": "dislike",
  "comment": "不想要这个价位"
}
```

#### 模拟购买

```text
POST /api/interactions/mock-purchase
```

用途：在不实现真实订单和支付的情况下，模拟转化信号。

#### 内部近期行为查询

```text
GET /internal/users/{profile_user_id}/recent-events
GET /internal/sessions/{session_id}/events
```

用途：推荐服务和 Agent 服务读取近期行为，用于下一轮推荐。

### 5.6 推荐闭环

有了 interaction 服务后，系统链路可以从“一次性推荐”变成“持续反馈”：

```text
推荐服务给出商品
  -> 前端展示，interaction 记录曝光
  -> 用户点击/喜欢/不喜欢
  -> interaction 记录行为事件
  -> user-service 或 agent-service 更新 session 临时偏好
  -> recommend-service 下一轮推荐时读取近期行为
  -> 推荐结果发生变化
```

这也是本项目区别于普通推荐接口的重要工程亮点。

## 6. `rs-service-platform-trace`：平台观察 / 推荐链路追踪服务

### 6.1 服务定位

`rs-service-platform-trace` 参考 mall4cloud 的 `platform`，但不做完整系统后台，而是做推荐 Agent 平台的观察台。

它的重点不是管理菜单、角色、系统配置，而是让整个推荐链路可解释、可调试、可展示。

### 6.2 核心职责

- 查看真实账号绑定的 `profile_user_id`。
- 查看用户画像摘要。
- 查看推荐 request trace。
- 查看召回来源。
- 查看排序分数。
- 查看 RAG evidence。
- 查看 Agent 工具调用过程。
- 查看用户反馈事件。
- 支撑前端调试面板和面试演示。

### 6.3 暂不负责

- 完整系统用户管理。
- 完整 RBAC。
- 菜单管理。
- 多租户后台。
- 商家后台。
- 系统配置中心。

### 6.4 建议 Controller

```text
com.sinrotic.rs.platformtrace.controller
├── app
│   └── AppTraceController.java
├── internal
│   └── InternalTraceController.java
└── platform
    ├── PlatformUserTraceController.java
    ├── PlatformRecommendTraceController.java
    ├── PlatformAgentTraceController.java
    └── PlatformInteractionTraceController.java
```

### 6.5 建议接口

#### 查看账号画像

```text
GET /api/platform/accounts/{account_id}/profile
```

返回建议：

```json
{
  "account_id": "acc_001",
  "profile_user_id": "A1XYZ",
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品",
  "top_categories": ["Backpacks", "Storage"],
  "top_stores": ["Urban Carry", "Home Box"]
}
```

#### 查看推荐链路

```text
GET /api/platform/recommend/{request_id}/trace
```

展示内容：

- 请求场景。
- 用户画像。
- 候选池来源。
- 排序分数。
- 重排策略。
- 最终推荐结果。
- 推荐理由。

#### 查看 Agent 对话链路

```text
GET /api/platform/agent/{session_id}/turns
```

展示内容：

- 用户原始输入。
- Agent 提取的偏好。
- 调用过的工具。
- 推荐服务返回结果。
- RAG evidence。
- 最终回复。

#### 查看 session 行为事件

```text
GET /api/platform/sessions/{session_id}/events
```

展示内容：

- 曝光。
- 点击。
- 收藏。
- 负反馈。
- 模拟购买。
- Agent 正负反馈。

### 6.6 面试展示价值

这个服务可以帮助项目从“能推荐”升级为“能解释推荐链路”。面试时可以讲：

> 我没有直接照搬商城后台，而是围绕推荐 Agent 的工程需求做了链路可观测设计。每次推荐都可以追踪用户画像、候选召回、排序分数、RAG 证据、Agent 工具调用和最终反馈，便于调试和展示系统可信度。

## 7. 整体服务协同链路

一个完整请求可以按以下方式流转：

```text
1. 用户注册 / 登录
   -> rs-service-user 创建真实账号
   -> 绑定 profile_user_id
   -> 签发双 token

2. 前端创建会话
   -> rs-service-user 创建 session
   -> session 绑定 account_id 和 profile_user_id

3. 用户请求推荐
   -> rs-service-recommend 通过 user-service 获取用户上下文
   -> 基于 profile_user_id、画像、session 偏好召回和排序

4. 推荐结果补商品信息
   -> rs-service-catalog 批量补商品卡片
   -> 返回 title、price、category、store、image 等展示字段

5. Agent 对话推荐
   -> rs-service-agent 解析用户自然语言
   -> 调 recommend-service 获取推荐
   -> 调 recommend-service 内部 RAG 子域获取证据
   -> 调 catalog-service 补商品详情
   -> 返回自然语言解释 + 商品卡片

6. 用户产生行为
   -> rs-service-interaction 记录曝光、点击、反馈、模拟购买
   -> 推荐和 Agent 后续读取近期行为做动态调整

7. 平台观察
   -> rs-service-platform-trace 聚合展示画像、推荐 trace、RAG evidence、Agent 工具调用和反馈事件
```

简化图：

```text
frontend
  -> gateway
  -> user-service
  -> recommend-service
  -> catalog-service
  -> agent-service
  -> interaction-service
  -> platform-trace
```

## 8. 实现优先级

### P0：`rs-service-catalog`

优先级最高。原因是推荐结果最终要展示商品，而商品详情、图片、价格、类目、store 不应该散落在推荐服务或前端里。

第一版只要实现：

- 商品详情。
- 批量商品卡片。
- 类目查询。
- 虚拟 store 查询。

### P1：`rs-service-recommend` 内部 RAG 子域

Agent 和推荐解释进入主线后需要做。原因是自然语言推荐不能只靠模型编理由，需要商品文本和证据 grounding。

第一版只要实现：

- 商品关键词搜索。
- 按 item 查询 evidence。
- 批量 evidence 查询。
- Java API 对接 Python RAG。

### P1：`rs-service-interaction`

推荐闭环阶段必须做。原因是没有 interaction，系统只能静态推荐；有了 interaction，才能根据曝光、点击、反馈调整下一轮推荐。

第一版只要实现：

- 曝光。
- 点击。
- 正负反馈。
- 模拟购买。
- session 近期行为查询。

### P2：`rs-service-platform-trace`

展示和面试阶段做。它不是推荐运行的最低依赖，但对系统可解释性、调试和展示非常有价值。

第一版只要实现：

- 用户画像查看。
- 推荐 trace 查看。
- Agent 工具调用查看。
- session 行为事件查看。

## 9. 当前阶段暂不实现的 mall4cloud 能力

以下能力暂不进入当前阶段：

| mall4cloud 能力 | 当前是否需要 | 原因 |
| --- | --- | --- |
| 真实订单服务 | 暂不需要 | 当前只需要模拟转化信号，不需要履约 |
| 支付服务 | 不需要 | 与推荐 Agent 主线无关 |
| 完整商家后台 | 暂不需要 | 店铺来自数据集 `store` 字段虚拟化 |
| 复杂 RBAC | 暂不需要 | 第一版只有普通 account 和可选 admin viewer |
| Leaf ID 服务 | 不需要 | 可先用 UUID 或数据库生成 ID |
| OSS / 文件服务 | 可后置 | 如果图片和文档暂用已有 URL，不必单独建服务 |
| 库存锁定 | 不需要 | 无真实库存和下单履约 |
| 促销营销体系 | 不需要 | 当前重点是推荐、RAG 和 Agent |

## 10. 后续落代码建议

如果后续开始真正创建 Java 服务，可以按 `rs-service-user` 的方式统一骨架：

```text
rs-service-xxx/
├── pom.xml
└── src/main/java/com/sinrotic/rs/xxx
    ├── XxxServiceApplication.java
    ├── controller
    │   ├── app
    │   ├── internal
    │   └── platform
    ├── service
    ├── mapper
    ├── domain
    │   ├── dto
    │   ├── entity
    │   └── vo
    ├── exception
    └── util
```

建议每个服务第一轮都只做：

- POM。
- 启动类。
- Controller 空骨架。
- Service 空骨架。
- Mapper 空接口。
- DTO/VO/Entity 代表对象。
- Exception。
- `package-info.java`。

暂不急着做：

- 完整数据库表。
- Mapper XML。
- Nacos 配置。
- Elasticsearch 配置。
- Kafka 消息流。
- Redis 缓存。
- 复杂权限。

这样可以先把服务边界和代码结构搭起来，再逐个服务补真实业务。

## 11. 面试可讲点

这部分可以总结成：

> 我参考了 mall4cloud 的 B2B2C 微服务拆分，但没有直接照搬完整商城。因为我的项目基于推荐数据集，没有真实商家、订单和支付，所以我保留了商品目录、搜索、平台观察等对推荐链路有价值的边界，并新增了推荐系统更需要的 RAG evidence、交互反馈和 Agent trace。最终服务拆分围绕“真实账号绑定画像用户 -> 推荐 -> 商品展示 -> RAG 证据 -> Agent 对话 -> 行为反馈 -> 链路观察”展开，更贴合推荐 Agent 平台的目标。

这体现的工程取舍是：

- 能识别参考项目中哪些能力可复用，哪些应该裁剪。
- 没有为了微服务而微服务，而是围绕推荐链路拆分。
- 能把数据集项目包装成真实服务体验。
- 能为后续前端展示、Agent 对话、评估调试和面试展示留下清晰扩展点。
