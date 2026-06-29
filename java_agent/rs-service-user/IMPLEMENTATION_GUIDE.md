# rs-service-user 实现阅读指南

这份文档用于配合 `CONTROLLER_DESIGN.md` 阅读后续代码。目标是让每个接口都能按固定路线理解，而不是在一堆类之间来回跳。

## 1. 推荐阅读顺序

阅读任何一个接口时，按下面顺序走：

```text
Controller
  -> Request DTO
  -> Service
  -> Mapper
  -> Entity
  -> Response VO
```

示例：后续阅读注册接口时，从 `AuthController` 开始，然后看 `RegisterRequestDTO`、`AuthService`、账号和绑定相关 `Mapper`、`AuthAccount` / `AccountProfileBinding`，最后看 `AuthTokenVO`。

## 2. 包职责

```text
com.sinrotic.rs.user
├── UserServiceApplication.java       # user 微服务启动入口
├── controller                        # HTTP 接口，只处理请求入口和响应出口
│   ├── auth                          # 注册、登录、token、当前账号
│   ├── app                           # 前端用户页使用的用户和 session 接口
│   ├── internal                      # 推荐服务、Agent 服务使用的内部上下文接口
│   └── platform                      # 第二阶段平台观察台接口
├── service                           # 业务编排，不直接暴露 HTTP 细节
├── mapper                            # MyBatis 数据访问接口
├── domain
│   ├── dto                           # 请求参数
│   ├── entity                        # 数据库表对象
│   └── vo                            # 响应视图对象
├── config                            # Spring、MyBatis、认证相关配置
├── exception                         # 业务异常和统一错误处理
└── util                              # 无状态工具类
```

## 3. 第一阶段实现闭环

第一阶段只建议打通 6 个 MVP 接口：

```text
1. POST /api/auth/register
2. POST /api/auth/login
3. POST /api/auth/refresh
4. GET  /api/auth/me
5. POST /api/sessions
6. GET  /internal/sessions/{session_id}/context
```

每次只实现一个小闭环。开发完成后，在本文件补一段“代码阅读路线”，说明这个接口经过哪些类。

## 4. 分层规则

- Controller 不写业务判断，只做参数接收、认证上下文读取、调用 Service。
- Service 负责业务流程，例如注册账号、绑定画像用户、签发 token。
- Mapper 只负责数据库读写，不拼业务流程。
- Entity 对应数据库表结构。
- DTO 对应请求体或查询参数。
- VO 对应接口响应，不直接返回 Entity。
- 内部接口和前端接口分开，避免推荐服务依赖前端页面模型。

## 5. 命名规则

- 真实登录账号统一叫 `accountId`。
- 画像用户统一叫 `profileUserId`。
- 前端用户会话统一叫 `sessionId`。
- 请求对象后缀用 `RequestDTO`。
- 响应对象后缀用 `VO`。
- 数据库对象使用业务名，不加 `DO` 后缀。

## 6. 后续每个接口的说明模板

```text
接口：
入口 Controller：
请求 DTO：
核心 Service 方法：
读写 Mapper：
涉及 Entity：
响应 VO：
主要异常：
测试入口：
```
