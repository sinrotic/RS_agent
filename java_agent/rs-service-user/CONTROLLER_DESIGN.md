# rs-service-user Controller 设计文档

## 1. 服务定位

`rs-service-user` 当前不实现传统电商账号中心，而实现面向推荐 Agent 场景的 **用户上下文微服务**。

它服务的对象分成两层：

- **真实登录账号**：用于注册、登录、双 token 认证和前端身份体验。
- **画像用户**：用于推荐、RAG 和 Agent 的个性化上下文。

因此，本服务的核心职责是：

- 注册真实账号，并在注册时随机或指定绑定一个画像用户。
- 使用双 token 认证维护登录态。
- 暴露当前账号绑定的画像用户简要信息、画像、历史行为。
- 创建和维护一次前端用户会话 `user session`。
- 保存 Agent 多轮对话产生的临时偏好。
- 给推荐服务、Agent 服务提供内部用户上下文。

暂不负责：

- 收货地址、省市区、真实订单履约信息。
- 商家端用户管理、完整 RBAC。
- 完整商家/平台多角色权限体系。

参考 `mall4cloud-user` 和 `mall4cloud-auth` 的地方主要是：注册后自动登录、账号与业务用户信息分离、双 token 签发、统一认证上下文、面向内部服务的 context 查询接口。业务内容需要按本项目的数据集推荐场景重构。

---

## 2. 推荐 Controller 分层

建议第一版保留 4 类 Controller，平台观察台接口可作为第二阶段补充。

```text
com.sinrotic.rs.user.controller
├── auth
│   └── AuthController.java
├── app
│   ├── UserProfileController.java
│   └── UserSessionController.java
├── internal
│   └── InternalUserContextController.java
└── platform                 # 可选，第二阶段
    └── PlatformUserController.java
```

| Controller | 面向对象 | 核心职责 | 是否 MVP 必需 |
|---|---|---|---|
| `AuthController` | 前端登录态 | 注册、登录、刷新 token、退出登录、当前用户信息 | 是 |
| `UserProfileController` | 前端用户页 | 注册前画像预览、查绑定画像、查历史行为 | 是 |
| `UserSessionController` | 前端 + Agent | 基于当前账号创建 user session、查询 session、更新临时偏好 | 是 |
| `InternalUserContextController` | 推荐服务 / Agent 服务 | 提供 account context、session context、批量上下文 | 是 |
| `PlatformUserController` | 平台观察台 | 分页筛选 画像用户、查看画像质量、查看 session | 可选 |

---

## 3. AuthController

### 3.1 定位

面向前端登录态，参考 `mall4cloud-user + mall4cloud-auth` 的协作方式，但第一版可以先放在 `rs-service-user` 内部实现轻量认证。

核心模型是：

```text
真实账号 account_id
  -> 绑定一个 profile_user_id
  -> 推荐、RAG、Agent 使用 profile_user_id 读取画像和历史行为
```

注册后不再每次随机用户，而是固定绑定一个画像用户。后续登录同一账号时，推荐服务自然使用该账号绑定的画像。

建议基础路径：

```text
/api/auth
```

### 3.2 接口清单

#### 3.2.1 注册并绑定画像用户

```http
POST /api/auth/register
```

请求示例：

```json
{
  "username": "alice",
  "password": "123456",
  "nickname": "Alice",
  "bind_strategy": "random",
  "segment": "hot_user"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `username` | string | 是 | 登录用户名，唯一 |
| `password` | string | 是 | 明文只出现在请求中，服务端必须使用 BCrypt/Argon2 存 hash |
| `nickname` | string | 否 | 前端展示昵称，缺省可使用 username |
| `bind_strategy` | string | 否 | `random` 或 `selected`，默认 `random` |
| `segment` | string | 否 | 随机绑定时按用户分层抽样，例如 `hot_user` |
| `profile_user_id` | string | 否 | `bind_strategy=selected` 时传入候选画像 ID |

服务端流程：

```text
1. 检查 username 是否已存在。
2. 加密 password，创建 rs_auth_account。
3. 按 bind_strategy 从 rs_profile_user / rs_user_profile 选择 profile_user_id。
4. 写入 rs_account_profile_binding。
5. 签发 accessToken + refreshToken。
6. 返回账号信息、绑定画像摘要和 token。
```

响应示例：

```json
{
  "account_id": "acc_001",
  "username": "alice",
  "nickname": "Alice",
  "profile_user_id": "A1XYZ",
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品",
  "access_token": "access_xxx",
  "refresh_token": "refresh_yyy",
  "expires_in": 1800
}
```

---

#### 3.2.2 登录

```http
POST /api/auth/login
```

请求示例：

```json
{
  "username": "alice",
  "password": "123456"
}
```

服务端流程：

```text
1. 查 rs_auth_account。
2. 校验密码 hash。
3. 查询 account 绑定的 active profile_user_id。
4. 构造 AuthPrincipal。
5. 签发 accessToken + refreshToken。
```

响应示例：

```json
{
  "account_id": "acc_001",
  "username": "alice",
  "nickname": "Alice",
  "profile_user_id": "A1XYZ",
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品",
  "access_token": "access_xxx",
  "refresh_token": "refresh_yyy",
  "expires_in": 1800
}
```

---

#### 3.2.3 刷新 token

```http
POST /api/auth/refresh
```

请求示例：

```json
{
  "refresh_token": "refresh_yyy"
}
```

建议采用 refresh token rotation：

```text
1. 校验 refreshToken 是否存在、未过期、未吊销。
2. 查询对应 account_id 和 profile_user_id。
3. 吊销旧 refreshToken。
4. 生成新的 accessToken + refreshToken。
5. 返回新 token。
```

响应示例：

```json
{
  "access_token": "access_new",
  "refresh_token": "refresh_new",
  "expires_in": 1800
}
```

---

#### 3.2.4 退出登录

```http
POST /api/auth/logout
Authorization: Bearer <access_token>
```

说明：

- 吊销当前 auth session。
- 后续可以增加 `POST /api/auth/logout-all`，用于退出该账号的全部设备。

---

#### 3.2.5 当前登录用户

```http
GET /api/auth/me
Authorization: Bearer <access_token>
```

响应示例：

```json
{
  "account_id": "acc_001",
  "username": "alice",
  "nickname": "Alice",
  "profile_user_id": "A1XYZ",
  "profile": {
    "segment": "hot_user",
    "history_count": 238,
    "profile_summary": "近期偏好通勤包、收纳用品和中低价商品"
  }
}
```

### 3.3 Token 设计建议

第一版推荐实现 **有状态 opaque 双 token**，更接近 mall4cloud，也更方便主动吊销：

```text
accessToken = 随机高强度字符串，用于普通请求
refreshToken = 随机高强度字符串，用于续期
服务端保存 token/session -> AuthPrincipal
```

`AuthPrincipal` 建议包含：

```text
accountId
username
nickname
profileUserId
role
sessionId
tokenVersion
```

存储方案：

- MVP 可先使用 PostgreSQL 表 `rs_auth_session`，方便调试。
- 后续可迁移到 Redis：`accessToken -> AuthPrincipal`、`refreshToken -> sessionId/accountId`。

如果后续改用 JWT，也建议只让 accessToken 使用 JWT，refreshToken 仍使用服务端存储的随机 token。

---

## 4. UserProfileController

### 4.1 定位

面向前端用户页面，用于选择和查看当前画像用户。

建议基础路径：

```text
/api/users
```

### 4.2 接口清单

#### 4.2.1 随机抽样用户

```http
GET /api/users/random
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `segment` | string | 否 | 用户分层，例如 `hot_user`、`normal_user`、`cold_user`、`sparse_user` |
| `min_history_count` | integer | 否 | 最小历史行为数 |
| `category` | string | 否 | 偏好类目过滤 |
| `store` | string | 否 | 偏好虚拟店铺 / Amazon metadata.store 过滤 |

响应示例：

```json
{
  "user_id": "A1XYZ",
  "display_name": "Profile User A1XYZ",
  "avatar_url": "/assets/avatar/default_03.png",
  "segment": "hot_user",
  "history_count": 238,
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品"
}
```

说明：

- 这是注册前画像预览、调试和平台观察台的随机用户入口。
- 真实登录后的推荐链路不应再依赖前端传入 `user_id`，而应使用账号绑定的 `profile_user_id`。
- 如果没有满足条件的用户，应返回明确空结果或业务错误，不要静默随机到其他分层。

---

#### 4.2.2 随机候选画像列表

```http
GET /api/users/random-candidates
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `segment` | string | 否 | 用户分层 |
| `limit` | integer | 否 | 候选数量，默认 3 |

响应示例：

```json
{
  "candidates": [
    {
      "profile_user_id": "A1",
      "segment": "hot_user",
      "history_count": 238,
      "profile_summary": "偏好通勤包、收纳用品"
    },
    {
      "profile_user_id": "A2",
      "segment": "normal_user",
      "history_count": 72,
      "profile_summary": "偏好运动用品、低价商品"
    }
  ]
}
```

用途：

- 注册前让用户选择一个虚拟画像。
- `POST /api/auth/register` 使用 `bind_strategy=selected` 时，可以传入这里返回的 `profile_user_id`。

---

#### 4.2.3 查询用户简要信息

```http
GET /api/users/{user_id}/simple
```

响应示例：

```json
{
  "user_id": "A1XYZ",
  "display_name": "Profile User A1XYZ",
  "avatar_url": "/assets/avatar/default_03.png",
  "segment": "hot_user"
}
```

用途：

- 前端顶部展示当前画像用户。
- 推荐结果页展示“当前推荐面向哪个用户”。

---

#### 4.2.4 查询用户画像

```http
GET /api/users/{user_id}/profile
```

响应示例：

```json
{
  "user_id": "A1XYZ",
  "segment": "hot_user",
  "history_count": 238,
  "top_categories": [
    {"category": "backpack", "count": 42},
    {"category": "office", "count": 31}
  ],
  "top_stores": [
    {"store": "Urban Carry", "count": 18}
  ],
  "recent_item_ids": ["B001", "B002", "B003"],
  "positive_item_ids": ["B010", "B011"],
  "negative_item_ids": [],
  "preferred_price_range": {
    "min": 20,
    "max": 80
  },
  "profile_summary": "该用户近期对通勤、收纳和中低价商品更敏感。"
}
```

说明：

- `top_stores` 来源可以使用 Amazon metadata 的 `store` 字段，但它只表示虚拟店铺/来源偏好，不等同完整 seller 实体。
- `profile_summary` 应由离线画像预处理生成，避免在线接口里做重计算。

---

#### 4.2.5 查询用户历史行为

```http
GET /api/users/{user_id}/history
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `limit` | integer | 否 | 返回条数，默认 50 |
| `event_type` | string | 否 | 行为类型过滤，例如 `interaction`、`click`、`purchase`、`positive`、`negative` |

响应示例：

```json
{
  "user_id": "A1XYZ",
  "events": [
    {
      "item_id": "B001",
      "event_type": "interaction",
      "event_time": "2026-05-01T10:00:00",
      "category": "backpack",
      "store": "Urban Carry"
    }
  ]
}
```

用途：

- 展示推荐依据。
- 给平台观察台说明用户画像来源。
- 给 Agent 解释“为什么推荐这些商品”。

---

## 5. UserSessionController

### 5.1 定位

管理一次前端用户会话。`session` 用来绑定：

- 当前真实账号 `account_id`。
- 当前账号绑定的画像用户 `profile_user_id`。
- 当前入口场景。
- Agent 多轮对话中产生的临时偏好。

建议基础路径：

```text
/api/sessions
```

### 5.2 接口清单

#### 5.2.1 创建用户会话

```http
POST /api/sessions
```

请求示例：

```json
{
  "entry_scene": "home"
}
```

响应示例：

```json
{
  "session_id": "sess_001",
  "account_id": "acc_001",
  "profile_user_id": "A1XYZ",
  "entry_scene": "home",
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品",
  "started_at": "2026-06-26T10:00:00"
}
```

说明：

- 该接口需要 `Authorization: Bearer <access_token>`。
- 服务端从认证上下文中读取 `account_id` 和绑定的 `profile_user_id`，不要让前端手动传入 `profile_user_id`。
- `entry_scene` 建议枚举：`home`、`agent_chat`、`item_detail`、`search`。

---

#### 5.2.2 查询用户会话

```http
GET /api/sessions/{session_id}
```

响应示例：

```json
{
  "session_id": "sess_001",
  "account_id": "acc_001",
  "profile_user_id": "A1XYZ",
  "entry_scene": "home",
  "status": "active",
  "active_preferences": {
    "category": "backpack",
    "use_case": "commute",
    "price_sensitivity": "medium"
  },
  "started_at": "2026-06-26T10:00:00",
  "last_active_at": "2026-06-26T10:05:00"
}
```

用途：

- 前端恢复当前会话。
- Agent 服务读取当前临时偏好。
- 推荐服务读取 session 状态。

---

#### 5.2.3 更新会话临时偏好

```http
PATCH /api/sessions/{session_id}/preferences
```

请求示例：

```json
{
  "active_preferences": {
    "category": "backpack",
    "use_case": "commute",
    "price_sensitivity": "high",
    "negative_constraints": ["too_expensive", "too_large"]
  },
  "last_user_query": "太贵了，想要便宜一点的通勤包"
}
```

响应示例：

```json
{
  "session_id": "sess_001",
  "account_id": "acc_001",
  "profile_user_id": "A1XYZ",
  "active_preferences": {
    "category": "backpack",
    "use_case": "commute",
    "price_sensitivity": "high",
    "negative_constraints": ["too_expensive", "too_large"]
  },
  "updated_at": "2026-06-26T10:06:00"
}
```

说明：

- 该接口主要给 Agent 服务调用。
- 临时偏好只影响当前 session，不直接覆盖长期用户画像。
- 更新策略建议采用 merge，而不是整段覆盖；如果需要删除某个偏好，后续可增加显式 `remove_keys`。

---

#### 5.2.4 结束用户会话（可选）

```http
POST /api/sessions/{session_id}/close
```

响应示例：

```json
{
  "session_id": "sess_001",
  "status": "closed"
}
```

MVP 可以暂不实现，通过 session 过期或前端切换用户自然结束。

---

## 6. InternalUserContextController

### 6.1 定位

面向内部微服务调用，相当于本项目版本的 `Feign UserController`。它不直接服务普通前端页面。

建议基础路径：

```text
/internal
```

### 6.2 接口清单

#### 6.2.1 获取账号推荐上下文

```http
GET /internal/accounts/{account_id}/context
```

响应示例：

```json
{
  "account_id": "acc_001",
  "profile_user_id": "A1XYZ",
  "nickname": "Alice",
  "segment": "hot_user",
  "history_item_ids": ["B001", "B002", "B003"],
  "recent_item_ids": ["B010", "B011"],
  "top_categories": ["backpack", "office"],
  "top_stores": ["Urban Carry"],
  "preferred_price_range": {
    "min": 20,
    "max": 80
  },
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品",
  "source_version": "user_profile_v1"
}
```

用途：

- `rs-service-recommend` 召回/排序前获取账号绑定的画像用户。
- `rs-service-agent` 生成推荐解释前读取账号绑定画像。
- 推荐与 Agent 内部应使用 `profile_user_id` 查询画像，不直接用 `account_id` 作为推荐用户 ID。

---

#### 6.2.2 获取会话上下文

```http
GET /internal/sessions/{session_id}/context
```

响应示例：

```json
{
  "session_id": "sess_001",
  "account_id": "acc_001",
  "profile_user_id": "A1XYZ",
  "active_preferences": {
    "category": "backpack",
    "price_sensitivity": "high"
  },
  "profile_summary": "近期偏好通勤包、收纳用品和中低价商品"
}
```

用途：

- 推荐服务结合长期画像和 session 短期偏好进行重排。
- Agent 服务恢复多轮上下文。

---

#### 6.2.3 批量获取用户上下文

```http
POST /internal/users/batch-context
```

请求示例：

```json
{
  "user_ids": ["A1", "A2", "A3"]
}
```

响应示例：

```json
{
  "users": [
    {
      "user_id": "A1",
      "segment": "hot_user",
      "top_categories": ["backpack", "office"],
      "recent_item_ids": ["B001", "B002"]
    },
    {
      "user_id": "A2",
      "segment": "cold_user",
      "top_categories": [],
      "recent_item_ids": ["B009"]
    }
  ]
}
```

用途：

- 批量评估。
- 平台观察台。
- 推荐服务批量预热。

---

## 7. PlatformUserController（第二阶段可选）

### 7.1 定位

面向平台观察台，不是商家端用户管理。它用于选择适合演示的用户、查看画像质量和 session 记录。

建议基础路径：

```text
/api/platform/users
```

### 7.2 可选接口

```http
GET /api/platform/users
GET /api/platform/users/{user_id}/profile-summary
GET /api/platform/users/{user_id}/sessions
```

分页查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | integer | 页码 |
| `page_size` | integer | 每页条数 |
| `segment` | string | 用户分层 |
| `min_history_count` | integer | 最小历史行为数 |
| `category` | string | 偏好类目 |
| `store` | string | 偏好虚拟店铺/store |

MVP 可先不实现，等前端平台观察视角开始建设时再补。

---

## 8. DTO / VO 建议

### 8.1 请求 DTO

```text
RegisterRequestDTO
  username
  password
  nickname
  bindStrategy
  segment
  profileUserId

LoginRequestDTO
  username
  password

RefreshTokenRequestDTO
  refreshToken

RandomUserQueryDTO
  segment
  minHistoryCount
  category
  store

RandomCandidateQueryDTO
  segment
  limit

CreateUserSessionDTO
  entryScene

UpdateSessionPreferenceDTO
  activePreferences
  lastUserQuery

BatchUserContextRequestDTO
  accountIds
  profileUserIds
```

### 8.2 响应 VO

```text
AuthTokenVO
  accountId
  username
  nickname
  profileUserId
  profileSummary
  accessToken
  refreshToken
  expiresIn

CurrentAccountVO
  accountId
  username
  nickname
  profileUserId
  profile

ProfileUserSimpleVO
  profileUserId
  displayName
  avatarUrl
  segment

UserProfileVO
  profileUserId
  segment
  historyCount
  topCategories
  topStores
  recentItemIds
  positiveItemIds
  negativeItemIds
  preferredPriceRange
  profileSummary

UserHistoryVO
  profileUserId
  events

UserSessionVO
  sessionId
  accountId
  profileUserId
  entryScene
  status
  activePreferences
  startedAt
  lastActiveAt

UserContextVO
  accountId
  profileUserId
  nickname
  segment
  historyItemIds
  recentItemIds
  topCategories
  topStores
  preferredPriceRange
  profileSummary
  sourceVersion

SessionContextVO
  sessionId
  accountId
  profileUserId
  activePreferences
  profileSummary
```

---

## 9. 建议的数据对象

```text
AuthAccount
  accountId
  username
  passwordHash
  nickname
  avatarUrl
  status
  tokenVersion
  createdAt
  updatedAt

AccountProfileBinding
  bindingId
  accountId
  profileUserId
  bindingStrategy
  segment
  status
  createdAt
  updatedAt

AuthSession
  sessionId
  accountId
  accessTokenHash
  refreshTokenHash
  accessExpiresAt
  refreshExpiresAt
  revokedAt
  userAgent
  ip
  createdAt
  updatedAt

ProfileUser
  profileUserId
  displayName
  avatarUrl
  segment
  historyCount
  firstEventTime
  lastEventTime
  status
  createdAt
  updatedAt

UserProfile
  profileUserId
  topCategoriesJson
  topStoresJson
  recentItemIdsJson
  positiveItemIdsJson
  negativeItemIdsJson
  preferredPriceRangeJson
  profileSummary
  sourceVersion
  updatedAt

UserEvent
  eventId
  profileUserId
  itemId
  eventType
  eventTime
  category
  store
  source

UserSession
  sessionId
  accountId
  profileUserId
  entryScene
  activePreferencesJson
  lastUserQuery
  startedAt
  lastActiveAt
  status
```

第一版可以把 `UserSessionPreference` 合并进 `UserSession.activePreferencesJson`，减少表数量。

---

## 10. MVP 实现顺序

优先实现以下 6 个接口即可打通“注册账号 -> 绑定数据集画像 -> 登录推荐”的主链路：

```text
1. POST /api/auth/register
2. POST /api/auth/login
3. POST /api/auth/refresh
4. GET  /api/auth/me
5. POST /api/sessions
6. GET  /internal/sessions/{session_id}/context
```

第二步补充画像预览和账号上下文：

```text
7.  GET /api/users/random-candidates
8.  GET /api/users/{profile_user_id}/profile
9.  GET /api/users/{profile_user_id}/history
10. GET /internal/accounts/{account_id}/context
11. PATCH /api/sessions/{session_id}/preferences
```

第三步再做平台观察台：

```text
12. GET /api/platform/users
13. GET /api/platform/users/{profile_user_id}/profile-summary
14. GET /api/platform/users/{profile_user_id}/sessions
```

---

## 11. 和其他微服务的协同

### 11.1 推荐首页链路

```text
Frontend
  -> POST /api/auth/register 或 POST /api/auth/login
  -> 返回 account_id + profile_user_id + 双 token
  -> POST /api/sessions，携带 Authorization
  -> rs-service-recommend 请求 /internal/sessions/{session_id}/context
  -> 推荐服务使用 profile_user_id 获取画像并返回 item_id + score + reason
  -> catalog 服务补商品详情
  -> 前端展示推荐卡片
```

### 11.2 Agent 多轮对话链路

```text
Frontend 用户输入自然语言需求
  -> rs-service-agent
  -> GET /internal/sessions/{session_id}/context
  -> Agent 提取临时偏好
  -> PATCH /api/sessions/{session_id}/preferences
  -> rs-service-recommend 基于 user context + session preferences 重新推荐
```

### 11.3 行为反馈链路

```text
Frontend 点击 / 不喜欢 / 模拟购买
  -> interaction-service 记录行为
  -> 后续离线任务更新 user_profile
  -> user-context-service 暴露新的画像版本
```

---

## 12. 设计边界

当前阶段可以在 `rs-service-user` 内实现轻量认证，但不要把本服务扩展成完整电商用户中心。以下能力暂缓：

- 收货地址、省市区。
- 商家端用户管理。
- 真实会员体系。
- 复杂 RBAC 权限。
- 多租户商家/平台后台认证体系。

认证边界：

- 只支持普通 account。
- 注册时绑定一个画像用户。
- 双 token 只用于登录态、刷新和退出，不承载商家/平台权限。
- 后续如果账号体系变复杂，再从 `rs-service-user` 中拆出独立 `rs-service-auth`。
