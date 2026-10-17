# 在线反馈闭环设计

**状态：** 已确认，待实现  
**日期：** 2026-08-24  
**范围：** 让 `like`、`dislike` 在下一次推荐中产生可证明的确定性影响；`why` 与 `exposure` 保持非偏好语义。

**实现状态（2026-08-25）：** T1–T6 已落地到 Java Recommend/Agent、React 前端、MySQL/Redis 适配器和远端部署 smoke；本机单元、纵向切片、全仓 Java 测试与前端生产构建已通过。真实 MySQL/Redis/Gateway smoke 需在远端中间件环境执行。

## 1. 背景与当前缺口

当前 Java 推荐服务已经提供 exposure/event 接口和前端按钮，但 `InMemoryRecommendFeedbackService` 只在进程内记录幂等键，`DefaultHomeRecommendService` 与 `DefaultRecommendPipelineService` 不读取反馈。现状存在四个缺口：

1. 服务重启或多实例时，事件与幂等状态丢失；
2. `like/dislike` 不会改变下一次推荐；
3. 接口无法区分“事件已持久化”和“偏好已在线生效”；
4. Agent 请求 ID 与推荐结果归因 ID 容易混用，无法可靠校验反馈商品是否真正交付给当前用户。

本设计延续 ADR-0016 的公开事件语义，并以 ADR-0017 固定持久化与在线投影边界。

## 2. 目标

- Recommendation Feedback Event 先可靠持久化，再影响在线排序；
- 同一语义反馈在跨实例重试时只生效一次；
- Session Preference 立即强影响当前 Session；
- Profile Preference 跨 Session 弱影响排序，并允许用户查看、删除；
- 每次推荐明确返回使用的 Preference Version 和已应用反馈；
- Redis 丢失后能够从 MySQL 权威事实恢复；
- 反馈调整可通过 Trace 解释，不削弱候选覆盖和多样性门禁。

## 3. 明确不做

- 第一版不训练或在线更新机器学习模型；
- 反馈不允许绕过 Recall Source 创造新的 Candidate Item；
- `why`、曝光、点击不形成 Profile Preference；
- 单次 `dislike` 不直接屏蔽整个品牌或类目；
- Kafka 不作为默认 `recommend` 部署的正确性依赖；
- 不把推荐反馈写入 Durable Session History 或 Agent Long-term Memory；
- 不根据一次功能验收宣称 CTR、转化率或总体排序效果提升。

## 4. 核心不变量

1. Recommendation Feedback Event 追加保存，不被原地修改或删除；撤销通过 Feedback Reversal 表达。
2. MySQL 是事件与跨实例幂等的权威来源，Redis 是可重建在线投影。
3. 浏览器不能决定 Account 或 Profile User；身份只接受 Gateway 注入的可信头。
4. 反馈中的 `request_id` 必须指向 Recommendation Delivery，不得指向 Agent Turn 或普通 HTTP 请求。
5. 只有 Recommendation Delivery 中确实存在的 `item_id` 才能接收曝光或商品反馈。
6. `dislike` 强制排除原商品；相似商品只降权，除非用户另行明确表达品牌/类目排除。
7. `why`、`exposure`、`click` 不增加 Preference Version，不触发重排。
8. 推荐结果声称应用某次反馈时，必须已经读取不低于对应 Preference Version 的投影。

## 5. 领域模型

### 5.1 Recommendation Delivery

记录一次真正返回给 Profile User 的有序候选集合：

- `request_id`：推荐交付的稳定 ID；
- `account_id`、`profile_user_id`、`session_id`；
- `scene`：`home`、`agent_chat` 等；
- `preference_version`：生成该结果时实际读取的偏好版本；
- 有序商品项：`item_id`、rank、基础 score 和必要的商品特征快照；
- 创建时间和归因有效期。

首页响应继续使用 `request_id`。Agent 的 `product_cards.card_set_id` 必须等于 Recommendation Delivery 的 `request_id`；前端提交商品反馈时使用 `card_set_id`，不能使用 Agent 响应自身的请求 ID。

### 5.2 Recommendation Feedback Event

公开可提交的语义：

| 类型 | 偏好影响 | 行为 |
| --- | --- | --- |
| `exposure` | 无 | 逐商品保存真实可视曝光 |
| `click` | 无 | 只用于归因和后续离线评估 |
| `like` | 正向 | 更新 Session Preference，并弱更新 Profile Preference |
| `dislike` | 负向 | 当前 Session 排除原商品，并对相似商品降权 |
| `why` | 无 | 记录解释请求，不刷新推荐 |

Feedback Reversal 是服务端创建的内部事件，引用被撤销事件；客户端不能直接伪造反向权重。

### 5.3 偏好状态

- Session Preference：24 小时无活动后结束；当前 Session 中权重为强影响。
- Profile Preference：明确 `like/dislike` 默认保留 180 天，跨 Session 以弱权重参与并随时间衰减。
- 同一 Profile User 对同一商品的最新有效明确反馈决定当前状态。
- Feedback Reversal 恢复到被撤销事件之前的有效状态。
- 用户可删除单条 Profile Preference 或清空全部偏好；在线影响应立即消失。

## 6. 数据设计

### 6.1 MySQL 权威表

#### `rs_recommendation_delivery`

| 字段 | 说明 |
| --- | --- |
| `request_id` | 主键，Recommendation Delivery ID |
| `account_id` | Gateway 认证账号 |
| `profile_user_id` | 画像主体 |
| `session_id` | 当前 Session |
| `scene` | 推荐场景 |
| `preference_version` | 本次结果使用的版本 |
| `created_at` / `expires_at` | 归因时间范围 |

#### `rs_recommendation_delivery_item`

| 字段 | 说明 |
| --- | --- |
| `request_id + item_id` | 联合主键 |
| `rank` | 实际交付位置 |
| `base_score` | 偏好调整前 score |
| `category`、`brand` | 确定性相似规则所需快照 |
| `attributes_json` | 仅保存允许参与规则的商品属性 |

#### `rs_recommend_feedback_event`

| 字段 | 说明 |
| --- | --- |
| `event_id` | 主键 |
| `idempotency_key` | 唯一键 |
| `request_id`、`item_id` | 归因到 Recommendation Delivery |
| `account_id`、`profile_user_id`、`session_id` | 服务端解析的身份 |
| `event_type` | exposure/click/like/dislike/why/reversal |
| `reverses_event_id` | Feedback Reversal 引用，普通事件为空 |
| `position`、`visible_ratio`、`visible_duration_ms` | 曝光证据 |
| `occurred_at`、`received_at` | 客户端发生时间与服务端接收时间 |
| `preference_version` | 产生偏好变化时分配；非偏好事件为空 |

#### `rs_profile_item_preference_projection`

保存可重建的当前 Profile Preference，供用户偏好页面和快速恢复使用；它不是事件权威来源。字段包括最新事件、当前状态、强度、过期时间和 Preference Version。

#### `rs_recommend_feedback_outbox`

与偏好事件同事务写入，记录 Redis 投影任务、重试次数和状态。它允许接口在 MySQL 已成功而 Redis 失败时返回 `PENDING`，并由后台任务最终恢复在线视图。

### 6.2 Redis 在线投影

建议键空间：

```text
rs:recommend:preference:session:{session_id}
rs:recommend:preference:profile:{profile_user_id}
rs:recommend:preference:version:{profile_user_id}
```

Session key 使用 24 小时滑动 TTL；Profile key 中每条明确偏好携带独立过期时间。Redis 只保存排序所需的紧凑字段和最近应用的事件 ID，不保存公开商品详情。

## 7. 身份与归因

推荐与反馈 Controller 必须读取 Gateway 注入的：

```text
X-Account-Id
X-Profile-User-Id
```

服务端执行以下校验：

1. Recommendation Delivery 的 Account、Profile User、Session 与可信头一致；
2. `item_id` 确实属于该 Delivery；
3. Delivery 尚在允许的归因时间内；
4. 前端即使提交 `account_id` 或 `profile_user_id` 也必须忽略或拒绝；
5. Agent 商品反馈通过 `card_set_id` 找到 Delivery，不接受 Agent Turn ID 代替。

## 8. API 契约

### 8.1 可视曝光

`POST /api/recommend/feedback/exposure`

```json
{
  "request_id": "rec_req_001",
  "session_id": "sess_001",
  "items": [
    {
      "item_id": "B001",
      "position": 1,
      "visible_ratio": 0.75,
      "visible_duration_ms": 1300
    }
  ],
  "exposed_at": 1782636400000
}
```

前端仅在可见面积不低于 50%、连续可见不低于 1 秒时上报。接口保持兼容已有 `item_ids`，但新前端必须使用 `items`；服务端逐商品持久化，`request_id + item_id + exposure` 在一次 Delivery 内只计一次。

### 8.2 商品反馈

`POST /api/recommend/feedback/event`

```json
{
  "request_id": "rec_req_001",
  "session_id": "sess_001",
  "item_id": "B001",
  "event_type": "like",
  "occurred_at": 1782636410000
}
```

客户端不再提交可控制排序权重的 `event_value`；兼容期收到该字段时服务端忽略它。

### 8.3 撤销

`POST /api/recommend/feedback/reversal`

```json
{
  "feedback_event_id": "fb_evt_001"
}
```

只能撤销当前用户尚未被撤销的 `like/dislike`。撤销创建新的 Feedback Reversal，并分配新的 Preference Version。

### 8.4 确认响应

在 ADR-0016 现有字段上追加：

```json
{
  "feedback_id": "fb_evt_001",
  "accepted": true,
  "feedback_type": "like",
  "accepted_count": 1,
  "duplicate": false,
  "persisted": true,
  "application_status": "APPLIED",
  "preference_version": 17
}
```

`application_status`：

- `APPLIED`：事件持久化且 Redis 已应用；
- `PENDING`：事件持久化，但在线投影等待重试；
- `NOT_APPLICABLE`：exposure/click/why 不修改偏好。

推荐响应追加：

```json
{
  "preference_version": 17,
  "applied_feedback_event_ids": ["fb_evt_001"]
}
```

`applied_feedback_event_ids` 只列出对本次排序确实产生作用的事件，不等价于用户全部历史反馈。

### 8.5 偏好管理

```text
GET    /api/recommend/preferences
DELETE /api/recommend/preferences/items/{item_id}
DELETE /api/recommend/preferences
GET    /api/recommend/feedback/{event_id}
```

删除偏好通过领域事件表达，并同步产生新 Preference Version；不得直接删除权威事件后假装从未发生。

## 9. 写入与投影状态机

```text
RECEIVED
  -> 校验可信身份、Delivery、商品和幂等键
  -> MySQL 事务：分配版本 + 追加事件 + 更新可重建投影 + 写 Outbox
  -> COMMITTED
       -> Redis 更新成功 -> APPLIED
       -> Redis 更新失败 -> PENDING -> 后台重试 -> APPLIED
```

失败语义：

| 场景 | HTTP/结果 | 前端行为 |
| --- | --- | --- |
| MySQL 失败 | `503`，未接受 | 保留原列表，允许重试 |
| Redis 失败 | `202` + `PENDING` | 显示“已记录，正在同步”，暂不刷新 |
| 已应用 | `200` + `APPLIED` | 自动请求带期望版本的新推荐 |
| 重复提交 | 返回原事件 ID 和当前状态 | 不重复计数、不重复刷新 |
| 身份或归属不匹配 | `403` | 不写事件 |
| Delivery/商品不存在或过期 | `422` | 不写事件并提示结果已失效 |
| why | `200` + `NOT_APPLICABLE` | 打开解释面板，不刷新 |

并发反馈按 Profile User 串行分配 Preference Version；不同 Profile User 可以并行。

## 10. 确定性偏好调整

第一版新增 `PreferenceAwareFinalReranker`，只处理既有候选，不承担召回。

### 10.1 规则

- 当前 Session 对原商品的有效 `dislike`：强制排除；
- 有效 `like`：相同品牌、叶子类目和允许属性获得正向 adjustment；
- 有效 `dislike`：相似品牌、类目和允许属性只获得较弱负向 adjustment；
- Profile Preference 使用相同规则，但乘以小于 Session 的权重和时间衰减；
- 同一商品只有最新有效明确状态参与；
- 所有权重、上限、衰减和属性 allowlist 配置化；
- 基础 score 不可用时保持候选原稳定顺序，只用 adjustment 做局部重排。

建议初始配置用于功能验证，不代表最终效果参数：

| 匹配 | Session like | Session dislike | Profile 倍数 |
| --- | ---: | ---: | ---: |
| 同品牌 | `+0.12` | `-0.04` | `0.35` |
| 同叶子类目 | `+0.08` | `-0.03` | `0.35` |
| 允许属性重合 | 每项 `+0.02`，上限 `+0.04` | 每项 `-0.01`，下限 `-0.02` | `0.35` |

### 10.2 多样性保护

- 至少保留约 20% 的探索位不因正向偏好被同类商品完全占据；
- 第一屏同一叶子类目不得超过配置上限；
- preference adjustment 必须有绝对值上限；
- 规则只能在候选覆盖足够时重排，不能把空候选伪装成个性化成功。

### 10.3 Trace

内部 Trace 至少记录：

- `base_score`；
- Session/Profile adjustment；
- 排除原因；
- Preference Version；
- 实际应用的反馈事件 ID；
- 规则配置版本；
- 多样性保护是否改变最终位置。

这些字段只用于内部审计，不直接进入公开 Display Product。

## 11. 前端交互

### like/dislike

1. 卡片进入提交状态，防止重复点击；
2. `APPLIED` 后携带期望 Preference Version 自动刷新；
3. 新结果确认已应用对应事件后显示“推荐已根据反馈更新”；
4. `PENDING` 显示“反馈已记录，正在同步”，轮询事件状态；
5. 失败时保留原列表，不声称模型或偏好已更新；
6. 成功后短时间提供撤销入口。

### why

记录 `NOT_APPLICABLE` 事件并打开解释面板，不调用刷新接口、不改变 Preference Version。

### exposure

使用 `IntersectionObserver` 聚合真实可视项，达到阈值后批量上报；虚拟滚动中未进入视口的商品不得上报。

## 12. 恢复、保留与用户控制

- Session Preference 使用 24 小时滑动过期；
- Profile Preference 默认 180 天，重复明确反馈刷新有效期；
- Redis 丢失时从 MySQL 当前投影和未完成 Outbox 恢复，必要时可从事件全量重建；
- 用户删除偏好后，新版本立即覆盖旧在线状态；
- 原始事件的删除或匿名化由正式数据治理策略控制，默认在线保留期不长于 180 天；
- 数据保留策略变更不允许静默改变当前 Preference 的用户可见状态。

## 13. 测试与验收矩阵

### 13.1 单元测试

- 每种事件的合法性、身份、Delivery 商品归属；
- 幂等键在输入顺序、重复提交和多实例下稳定；
- like/dislike/why/exposure 的 Preference Version 语义；
- 最新明确反馈、撤销、过期和衰减；
- 确定性 adjustment、原商品排除和多样性保护；
- 前端 APPLIED/PENDING/失败/撤销状态机。

### 13.2 集成测试

- MySQL 事务同时提交事件、版本、投影和 Outbox；
- Redis 失败后返回 PENDING，并由重试恢复 APPLIED；
- Redis 全量清空后重建出相同偏好状态；
- 两个实例并发提交同一反馈只生成一个事件；
- 同一 Profile User 并发相反反馈得到确定版本顺序；
- Gateway 删除伪造身份头并注入真实身份；
- Agent `card_set_id` 能归因到正确 Recommendation Delivery。

### 13.3 行为验收

固定候选集下必须证明：

1. dislike 后，原商品从下一次推荐消失；
2. like 后，候选集中至少一个匹配品牌/类目/属性的商品获得可追踪加分；
3. 相似商品不会因一次 dislike 被全部排除；
4. why 前后商品顺序和 Preference Version 不变；
5. 重复反馈不重复生效；
6. 新 Session 只继承弱 Profile Preference，不继承旧 Session 强状态；
7. 删除 Profile Preference 后不再影响下一次推荐；
8. 首页和 Agent 使用相同反馈语义与归因规则；
9. 推荐覆盖率、多样性不低于设定的基线下限；
10. 完成一次真实 Gateway smoke，包含 APPLIED、PENDING 恢复、重复提交和撤销。

## 14. 指标与告警

第一版至少记录：

- 事件接收量、拒绝量和重复率；
- APPLIED/PENDING 数量与 PENDING 最长时间；
- Outbox 重试和死信数量；
- Redis 重建次数与耗时；
- 每种 feedback adjustment 的触发率；
- dislike 原商品再次出现率；
- why 导致排序变化的违规计数，目标为零；
- 推荐 P95 延迟、覆盖率和多样性保护触发率。

## 15. 实施切片与依赖

```text
T1 Recommendation Delivery 与身份归因
  -> T2 MySQL 事件、幂等、Preference Version、Outbox
      -> T3 Redis Session/Profile Preference 投影与恢复
          -> T4 PreferenceAwareFinalReranker 与 Trace
              -> T5 前端状态机、真实曝光、撤销和偏好管理
                  -> T6 Gateway 端到端 smoke、指标与文档收口
```

每个切片必须先补失败测试再实现。T1-T3 只建立正确性和状态，T4 才允许声称反馈影响排序；T6 通过之前不能关闭反馈闭环 Issue。

## 16. 完成定义

只有同时满足以下条件，在线反馈闭环才算完成：

- MySQL 持久化与跨实例幂等已替换内存接收器；
- Redis 在线投影能够失败恢复；
- 推荐结果携带并验证 Preference Version；
- like/dislike/why 的行为验收全部通过；
- 首页和 Agent 使用正确的 Recommendation Delivery ID；
- 用户能够撤销并删除跨 Session 偏好；
- 全部 Java、前端测试与真实 Gateway smoke 通过；
- ADR、知识库、接口文档和 GitHub Issue 状态同步更新。
