# rs-service-recommend Controller 设计文档

## 1. 服务定位

`rs-service-recommend` 是推荐链路的 Java 微服务入口，负责把首页推荐、召回、排序、推荐解释和链路 trace 封装成稳定 HTTP API。

当前项目的召回和排序模型已经训练完成，Java 服务第一版不重新训练模型，也不把全部算法逻辑搬到 Java 内部。推荐服务的职责是：

- 面向前端提供首页推荐结果。
- 面向 Agent 服务提供可解释的推荐候选。
- 面向内部服务提供召回、粗排、精排和 trace 查询能力。
- 编排用户上下文、候选召回、排序模型、商品卡片、RAG evidence 和行为反馈。
- 固化第一版首页推荐数量配置，避免前端、Agent 和算法侧各自写死数量。

暂不负责：

- 用户登录、画像绑定和 session 管理，这些属于 `rs-service-user`。
- 商品详情、图片、价格和类目补全，这些属于后续 `rs-service-catalog`。
- 通用知识库问答不属于本服务；推荐候选相关的 RAG evidence 检索已并入 `rs-service-recommend`。
- 曝光、点击、反馈和模拟购买事件落库，这些属于后续 `rs-service-interaction`。
- 模型训练、离线评估和候选池生成，这些仍由 Python 离线链路负责。

---

## 2. 首页推荐数量配置

第一版推荐采用以下固定默认值：

```yaml
recommend:
  home:
    recallPoolSize: 500
    coarseRankSize: 100
    fineRankSize: 50
    finalReturnSize: 20
    firstScreenDisplaySize: 8
```

对应链路：

```text
多路召回合并 top500
  -> 粗排截断 top100
  -> 精排截断 top50
  -> 多样性 / 去重 / 兜底重排 top20
  -> 首页接口返回 20 个
  -> 前端首屏展示 6-10 个，默认 8 个
```

设计原因：

- 当前 Python serving 配置已有 `candidate_pool_size=500`，可以直接承接现有 `pool500` artifact。
- ranking 实验中已有 `pool100` 配置，`coarseRankSize=100` 适合作为第一版 Java 服务截断。
- 精排保留 `50` 个，给多样性打散、类目/店铺去重、兜底替换和后续分页留空间。
- 首页接口返回 `20` 个，不只返回首屏数量，避免用户下滑时马上重新请求。
- `top_k=5` 更适合 demo 样例和解释输出，不建议作为正式首页推荐返回量。

后续调参边界：

| 场景 | 调整建议 |
| --- | --- |
| 延迟过高 | `recallPoolSize` 从 500 降到 300，`coarseRankSize` 从 100 降到 80 |
| 结果重复或单一 | 保持精排 50，在最终重排增加类目、店铺、来源打散 |
| 点击率不足且资源充足 | 先优化召回源权重，再考虑扩大召回池 |
| 想尝试 pool1000 | 当前治理配置不建议直接开启，需先通过离线评估和服务压测 |

---

## 3. Controller 分层

建议第一版按调用对象拆成 4 类 Controller：

```text
com.sinrotic.rs.recommend.controller
├── app
│   ├── HomeRecommendController.java
│   └── RecommendFeedbackController.java
├── internal
│   ├── InternalRecommendController.java
│   └── InternalRecommendPipelineController.java
├── agent
│   └── AgentRecommendController.java
└── platform
    └── PlatformRecommendTraceController.java
```

| Controller | 面向对象 | 核心职责 | 是否 MVP 必需 |
| --- | --- | --- | --- |
| `HomeRecommendController` | 前端首页 | 首页推荐、分页加载、刷新推荐 | 是 |
| `RecommendFeedbackController` | 前端行为入口 | 暂收轻量反馈请求，后续转发到 interaction 服务 | 可选 |
| `InternalRecommendController` | 内部服务 | 根据 account/session 获取推荐结果 | 是 |
| `InternalRecommendPipelineController` | 内部调试/平台 | 分阶段召回、粗排、精排、重排诊断 | 是 |
| `AgentRecommendController` | Agent 服务 | 面向对话推荐返回候选、理由和约束信息 | 是 |
| `PlatformRecommendTraceController` | 平台观察台 | 查看 request trace、召回来源、排序分数 | 第二阶段 |

---

## 4. HomeRecommendController

### 4.1 定位

`HomeRecommendController` 面向普通前端首页。前端不需要理解召回、粗排、精排，只需要传入当前 session 和场景，拿到可展示的推荐列表。

建议基础路径：

```text
/api/recommend
```

### 4.2 首页推荐

```http
POST /api/recommend/home
Authorization: Bearer <access_token>
```

请求示例：

```json
{
  "session_id": "sess_001",
  "scene": "home",
  "page_size": 20,
  "cursor": "",
  "debug": false
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `session_id` | string | 是 | 当前用户会话 ID |
| `scene` | string | 否 | 默认 `home`，后续可扩展 `home_refresh`、`agent_entry` |
| `page_size` | integer | 否 | 默认 20，最大 20 |
| `cursor` | string | 否 | 下一页游标，第一版可以为空 |
| `debug` | boolean | 否 | 普通前端默认 false，不返回内部分数细节 |

服务端流程：

```text
1. 从 access token 获取 account_id。
2. 调 user-service 内部接口获取 session context。
3. 校验 session 属于当前 account。
4. 使用 profile_user_id 和 session preferences 触发推荐链路。
5. 多路召回合并到 500。
6. 粗排截断到 100。
7. 精排截断到 50。
8. 多样性、去重、兜底重排后返回 20。
9. 生成 request_id，并保存推荐 trace。
10. 返回 item_id、score、reason 和可选 display 字段。
```

响应示例：

```json
{
  "request_id": "rec_req_001",
  "session_id": "sess_001",
  "scene": "home",
  "profile_user_id": "A1XYZ",
  "items": [
    {
      "item_id": "B001",
      "rank": 1,
      "score": 0.932,
      "reason": "结合你近期关注的通勤和收纳偏好推荐",
      "source_tags": ["itemcf_strong", "semantic"],
      "display": {
        "title": "Commuter Backpack",
        "category": "Backpacks",
        "store": "Urban Carry",
        "image_url": ""
      }
    }
  ],
  "has_more": true,
  "next_cursor": "rec_req_001:20",
  "config": {
    "recall_pool_size": 500,
    "coarse_rank_size": 100,
    "fine_rank_size": 50,
    "final_return_size": 20,
    "first_screen_display_size": 8
  }
}
```

说明：

- MVP 阶段可以由推荐服务临时返回轻量 `display` 字段；等 `rs-service-catalog` 建成后，推荐服务只返回 item_id、分数和原因，商品卡片由 catalog 补全。
- `debug=false` 时不返回完整召回源分数、模型特征和内部权重，避免污染普通前端协议。
- `page_size` 第一版固定最大 20，避免前端一次请求过多结果。

### 4.3 刷新首页推荐

```http
POST /api/recommend/home/refresh
```

请求示例：

```json
{
  "session_id": "sess_001",
  "last_request_id": "rec_req_001",
  "exclude_item_ids": ["B001", "B002"]
}
```

用途：

- 用户下拉刷新。
- 前端想避开上一屏已经曝光的商品。
- 结合 interaction 服务曝光记录后，可自动排除已曝光商品。

第一版实现建议：

```text
使用同一套 home 推荐链路，但在最终重排阶段加入 exclude_item_ids。
如果可用候选不足 20，则使用 popular/category 兜底补齐。
```

---

## 5. InternalRecommendController

### 5.1 定位

`InternalRecommendController` 面向内部微服务调用，不直接暴露给普通前端。它让 Agent、平台观察台或后续任务可以基于 account/session/profile 获取推荐结果。

建议基础路径：

```text
/internal/recommend
```

### 5.2 根据 session 推荐

```http
POST /internal/recommend/by-session
```

请求示例：

```json
{
  "session_id": "sess_001",
  "scene": "home",
  "limit": 20,
  "include_trace": true
}
```

响应示例：

```json
{
  "request_id": "rec_req_002",
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "items": [
    {
      "item_id": "B001",
      "rank": 1,
      "score": 0.932,
      "reason": "来自相似历史商品和语义偏好的共同命中",
      "source_tags": ["itemcf_strong", "semantic"]
    }
  ],
  "trace_summary": {
    "recall_count": 500,
    "coarse_rank_count": 100,
    "fine_rank_count": 50,
    "final_count": 20
  }
}
```

### 5.3 根据画像用户推荐

```http
POST /internal/recommend/by-profile-user
```

请求示例：

```json
{
  "profile_user_id": "A1XYZ",
  "scene": "home",
  "limit": 20,
  "temporary_preferences": {
    "category": "backpack",
    "price_sensitivity": "high"
  }
}
```

用途：

- 离线联调。
- 平台观察台选择画像用户后直接预览推荐。
- Agent 服务在没有完整登录态时进行内部推荐试算。

边界：

- 普通前端不应直接调用该接口。
- 如果有 session，应优先使用 `by-session`，因为 session 包含临时偏好和行为上下文。

---

## 6. InternalRecommendPipelineController

### 6.1 定位

`InternalRecommendPipelineController` 用于分阶段观察推荐链路，帮助调试召回、粗排、精排和最终重排，不作为普通业务接口。

建议基础路径：

```text
/internal/recommend/pipeline
```

### 6.2 仅召回

```http
POST /internal/recommend/pipeline/recall
```

请求示例：

```json
{
  "profile_user_id": "A1XYZ",
  "session_id": "sess_001",
  "limit": 500,
  "sources": ["itemcf_strong", "itemcf_weak", "semantic", "category", "popular"]
}
```

响应示例：

```json
{
  "request_id": "rec_req_003",
  "stage": "recall",
  "candidate_count": 500,
  "source_distribution": {
    "itemcf_strong": 150,
    "itemcf_weak": 120,
    "semantic": 100,
    "category": 80,
    "popular": 50
  },
  "candidates": [
    {
      "item_id": "B001",
      "source": "itemcf_strong",
      "recall_score": 0.81
    }
  ]
}
```

### 6.3 粗排

```http
POST /internal/recommend/pipeline/coarse-rank
```

请求示例：

```json
{
  "request_id": "rec_req_003",
  "profile_user_id": "A1XYZ",
  "candidate_item_ids": ["B001", "B002"],
  "limit": 100
}
```

说明：

- 如果传入 `request_id`，优先复用该 request 的召回候选。
- 如果传入 `candidate_item_ids`，可用于平台调试指定候选集合。
- 输出默认 top100。

### 6.4 精排

```http
POST /internal/recommend/pipeline/fine-rank
```

请求示例：

```json
{
  "request_id": "rec_req_003",
  "profile_user_id": "A1XYZ",
  "candidate_item_ids": ["B001", "B002"],
  "limit": 50
}
```

说明：

- 第一版如果精排模型仍在 Python 侧，Java 只封装调用和响应。
- 如果后续模型导出 ONNX，可由 Java 使用 `onnxruntime` 做在线推理。
- 输出默认 top50。

### 6.5 最终重排

```http
POST /internal/recommend/pipeline/final-rerank
```

请求示例：

```json
{
  "request_id": "rec_req_003",
  "profile_user_id": "A1XYZ",
  "candidate_item_ids": ["B001", "B002"],
  "limit": 20,
  "exclude_item_ids": ["B010"],
  "diversity": {
    "category_max_per_page": 6,
    "store_max_per_page": 4,
    "source_max_ratio": 0.6
  }
}
```

说明：

- 输出默认 top20。
- 负责去重、已曝光过滤、类目打散、店铺打散、召回源占比控制。
- 如果候选不足，按 `popular -> category -> pool500_fallback` 顺序兜底。

---

## 7. AgentRecommendController

### 7.1 定位

`AgentRecommendController` 面向 `rs-service-agent`。相比首页接口，它需要返回更适合自然语言解释和多轮对话的结构，包括命中偏好、负约束、推荐理由和可选 evidence 引用。

建议基础路径：

```text
/agent/recommend
```

### 7.2 Agent 对话推荐

```http
POST /agent/recommend/candidates
```

请求示例：

```json
{
  "session_id": "sess_001",
  "user_query": "想要便宜一点的通勤背包",
  "intent": "recommend",
  "constraints": {
    "category": "backpack",
    "use_case": "commute",
    "price_sensitivity": "high"
  },
  "limit": 10,
  "include_evidence": true
}
```

响应示例：

```json
{
  "request_id": "rec_req_agent_001",
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "items": [
    {
      "item_id": "B001",
      "rank": 1,
      "score": 0.918,
      "reason": "价格更贴近你的预算，同时符合通勤背包偏好",
      "matched_preferences": ["category:backpack", "use_case:commute"],
      "source_tags": ["semantic", "itemcf_strong"],
      "evidence_refs": ["ev_B001_01"]
    }
  ],
  "agent_hints": {
    "summary": "优先推荐更便宜的通勤背包，并保留相似历史偏好",
    "should_ask_clarifying_question": false
  }
}
```

说明：

- Agent 推荐默认不需要返回 20 个，`limit` 建议 5-10。
- 内部仍可使用 `500 -> 100 -> 50` 的链路，只是在最终输出阶段取 top10。
- `include_evidence=true` 时可以调用 search-rag 服务补 evidence；如果 RAG 不可用，应返回空 evidence_refs，不阻塞推荐。

---

## 8. RecommendFeedbackController

### 8.1 定位

`RecommendFeedbackController` 是过渡接口。第一版如果 `rs-service-interaction` 尚未建设，可以由 recommend 服务临时接收轻量反馈；interaction 服务上线后，该 Controller 只做转发或废弃。

建议基础路径：

```text
/api/recommend/feedback
```

### 8.2 曝光上报

```http
POST /api/recommend/feedback/exposure
```

请求示例：

```json
{
  "session_id": "sess_001",
  "request_id": "rec_req_001",
  "item_ids": ["B001", "B002", "B003"],
  "scene": "home"
}
```

### 8.3 点击或负反馈上报

```http
POST /api/recommend/feedback/event
```

请求示例：

```json
{
  "session_id": "sess_001",
  "request_id": "rec_req_001",
  "item_id": "B001",
  "event_type": "dislike",
  "comment": "价格太高"
}
```

边界：

- 该 Controller 不做长期画像更新。
- 第一版最多记录 request_id、item_id、event_type，用于当前 session 排除和 trace。
- 长期行为闭环应迁移到 `rs-service-interaction`。

---

## 9. PlatformRecommendTraceController

### 9.1 定位

`PlatformRecommendTraceController` 面向平台观察台和面试演示。它不参与主链路推荐，只负责把一次推荐 request 的过程展示出来。

建议基础路径：

```text
/api/platform/recommend
```

### 9.2 查询推荐 trace

```http
GET /api/platform/recommend/{request_id}/trace
```

响应示例：

```json
{
  "request_id": "rec_req_001",
  "session_id": "sess_001",
  "profile_user_id": "A1XYZ",
  "scene": "home",
  "config": {
    "recall_pool_size": 500,
    "coarse_rank_size": 100,
    "fine_rank_size": 50,
    "final_return_size": 20
  },
  "stage_counts": {
    "recall": 500,
    "coarse_rank": 100,
    "fine_rank": 50,
    "final": 20
  },
  "source_distribution": {
    "itemcf_strong": 150,
    "semantic": 100,
    "category": 80,
    "popular": 50
  },
  "items": [
    {
      "item_id": "B001",
      "final_rank": 1,
      "final_score": 0.932,
      "recall_sources": ["itemcf_strong", "semantic"],
      "coarse_rank": 8,
      "fine_rank": 2,
      "reason": "结合你近期关注的通勤和收纳偏好推荐"
    }
  ]
}
```

用途：

- 展示为什么某个商品最终排到前面。
- 检查某个召回源是否占比过高。
- 检查推荐服务是否按 `500 -> 100 -> 50 -> 20` 执行。
- 支撑平台观察台和面试演示。

---

## 10. DTO / VO 建议

### 10.1 请求 DTO

```text
HomeRecommendRequestDTO
  sessionId
  scene
  pageSize
  cursor
  debug

RefreshHomeRecommendRequestDTO
  sessionId
  lastRequestId
  excludeItemIds

InternalRecommendBySessionRequestDTO
  sessionId
  scene
  limit
  includeTrace

InternalRecommendByProfileUserRequestDTO
  profileUserId
  scene
  limit
  temporaryPreferences

RecallRequestDTO
  profileUserId
  sessionId
  limit
  sources

RankStageRequestDTO
  requestId
  profileUserId
  candidateItemIds
  limit

FinalRerankRequestDTO
  requestId
  profileUserId
  candidateItemIds
  limit
  excludeItemIds
  diversity

AgentRecommendRequestDTO
  sessionId
  userQuery
  intent
  constraints
  limit
  includeEvidence

RecommendExposureRequestDTO
  sessionId
  requestId
  itemIds
  scene

RecommendFeedbackEventRequestDTO
  sessionId
  requestId
  itemId
  eventType
  comment
```

### 10.2 响应 VO

```text
HomeRecommendVO
  requestId
  sessionId
  scene
  profileUserId
  items
  hasMore
  nextCursor
  config

RecommendItemVO
  itemId
  rank
  score
  reason
  sourceTags
  display

RecommendDisplayVO
  title
  category
  store
  imageUrl

InternalRecommendVO
  requestId
  sessionId
  profileUserId
  items
  traceSummary

PipelineRecallVO
  requestId
  stage
  candidateCount
  sourceDistribution
  candidates

PipelineCandidateVO
  itemId
  source
  recallScore
  coarseScore
  fineScore
  finalScore

AgentRecommendVO
  requestId
  sessionId
  profileUserId
  items
  agentHints

RecommendTraceVO
  requestId
  sessionId
  profileUserId
  scene
  config
  stageCounts
  sourceDistribution
  items
```

---

## 11. Service 层建议

Controller 不直接写推荐逻辑，建议 Service 层分成以下几类：

```text
HomeRecommendService
  首页推荐编排，负责从 session 到最终 top20 的完整链路

RecommendPipelineService
  召回、粗排、精排、最终重排的统一 pipeline

RecallOrchestrationService
  多路召回源编排，输出去重后的 top500

CoarseRankService
  粗排服务，输入 top500，输出 top100

FineRankService
  精排服务，输入 top100，输出 top50

FinalRerankService
  多样性、去重、曝光过滤、兜底，输出 top20

AgentRecommendService
  面向 Agent 的推荐封装，输出 top5-top10 和解释字段

RecommendTraceService
  记录和查询 request trace

RecommendConfigService
  统一读取首页推荐数量配置和默认策略
```

第一版如果 Python online service 已经能完成完整推荐，Java 服务可以先做薄封装：

```text
Controller
  -> HomeRecommendService
  -> Python online_service /recommend
  -> Java 侧统一转换 VO、保存 trace、补默认配置
```

后续再逐步把召回、排序、ONNX 推理等能力迁移到 Java 内部。

---

## 12. 和其他微服务的协同

### 12.1 首页推荐链路

```text
Frontend
  -> POST /api/recommend/home
  -> rs-service-recommend 校验 token 和 session
  -> rs-service-user /internal/sessions/{session_id}/context
  -> 推荐 pipeline 召回 500、粗排 100、精排 50、返回 20
  -> rs-service-catalog 批量补商品卡片（后续）
  -> rs-service-interaction 记录曝光（后续）
  -> Frontend 首屏展示 8 个，向下滚动继续展示剩余结果
```

### 12.2 Agent 推荐链路

```text
Frontend 用户输入自然语言
  -> rs-service-agent
  -> POST /agent/recommend/candidates
  -> rs-service-recommend 根据 session 和 constraints 推荐 top10
  -> POST /agent/recommend/rag/support
  -> rs-service-recommend 补候选商品 evidence
  -> rs-service-agent 组织自然语言解释和商品卡片
```

### 12.3 平台 trace 链路

```text
Platform UI
  -> GET /api/platform/recommend/{request_id}/trace
  -> 查看召回来源、排序分数、阶段数量、最终理由
```

---

## 13. MVP 实现顺序

第一阶段先打通首页推荐主链路：

```text
1. POST /api/recommend/home
2. POST /internal/recommend/by-session
3. GET  /api/platform/recommend/{request_id}/trace
```

第二阶段补分阶段调试能力：

```text
4. POST /internal/recommend/pipeline/recall
5. POST /internal/recommend/pipeline/coarse-rank
6. POST /internal/recommend/pipeline/fine-rank
7. POST /internal/recommend/pipeline/final-rerank
```

第三阶段补 Agent 和反馈能力：

```text
8.  POST /agent/recommend/candidates
9.  POST /api/recommend/home/refresh
10. POST /api/recommend/feedback/exposure
11. POST /api/recommend/feedback/event
```

---

## 14. 设计边界

当前阶段要避免把推荐服务做成所有能力的混合服务：

- 推荐服务可以临时返回商品展示字段，但不长期拥有商品目录。
- 推荐服务可以临时接收反馈事件，但不长期拥有用户行为闭环。
- 推荐服务可以返回 reason，但具体 RAG evidence 检索应交给 search-rag 服务。
- 推荐服务保存 trace，用于调试和平台展示，但不负责完整平台后台。
- 首页推荐默认返回 20 个，首屏展示数量由前端控制，服务端只通过 `firstScreenDisplaySize=8` 给出建议。

第一版最重要的工程目标是稳定固化：

```text
session context
  -> recall top500
  -> coarse rank top100
  -> fine rank top50
  -> final return top20
  -> trace 可观察
```
