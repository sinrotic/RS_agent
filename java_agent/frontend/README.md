# rs-frontend 前端适配目录

## 1. 定位

`rs-frontend` 是后续为 `java_agent` 微服务体系单独适配的前端目录。

根目录下已有的 `frontend/` 主要服务于 Python FastAPI 版本的 RS Agent 演示接口，例如：

```text
/session/start
/chat
/feedback
/recommend
/simulation/scene
```

Java 微服务版本的接口边界会更接近真实业务系统，例如：

```text
/api/auth/login
/api/auth/register
/api/sessions
/api/recommend
/api/agent/chat
/api/items/batch
/api/interactions/feedback
```

因此，后续 Java 版本前端建议放在本目录中独立演进，避免破坏现有 Python 演示前端。

## 2. 设计原则

- 复用现有 `frontend/` 的页面结构和组件设计。
- 重写 API client 和 TypeScript 类型定义，使其面向 Java gateway 和 Java 微服务。
- 保留商城推荐、Agent 对话、反馈闭环、平台观察几个核心页面。
- 不直接依赖 Python serving 的 `DisplayResponse` 路由命名，但可以保留类似的展示模型，减少 UI 改动。
- 第一阶段只做 Java 主链路，不急着迁移仿真沙箱和 debug 面板。

## 3. 建议目录结构

```text
rs-frontend/
├── README.md
├── package.json
├── vite.config.ts
└── src
    ├── api
    │   ├── shared.ts
    │   ├── authClient.ts
    │   ├── sessionClient.ts
    │   ├── recommendClient.ts
    │   ├── agentClient.ts
    │   ├── catalogClient.ts
    │   └── interactionClient.ts
    ├── components
    ├── views
    │   ├── Login.tsx
    │   ├── MallHome.tsx
    │   ├── AgentChat.tsx
    │   └── PlatformTrace.tsx
    └── types
        ├── auth.ts
        ├── session.ts
        ├── catalog.ts
        ├── recommend.ts
        ├── agent.ts
        └── interaction.ts
```

## 4. MVP 页面范围

第一版建议只做三个页面：

```text
Login
  - 注册
  - 登录
  - 保存 accessToken / refreshToken

MallHome
  - 创建 session
  - 请求首页推荐
  - 展示商品卡片
  - 喜欢 / 不喜欢 / 换一批

AgentChat
  - 多轮自然语言需求
  - 展示 Agent 回复
  - 展示推荐商品
  - 追问为什么推荐
```

`PlatformTrace` 可以后置，等 `rs-service-platform-trace` 有接口后再实现。

## 5. 与 Java 服务的对应关系

```text
Login
  -> rs-service-user

MallHome
  -> rs-service-user 创建 session
  -> rs-service-recommend 获取推荐
  -> rs-service-catalog 补商品卡片
  -> rs-service-interaction 记录反馈

AgentChat
  -> rs-service-agent 处理对话
  -> rs-service-recommend 获取推荐
  -> rs-service-recommend 获取 RAG evidence
  -> rs-service-catalog 补商品详情
```

## 6. 当前阶段处理方式

当前目录已经是可运行的 Vite 工程，面向 Java Gateway 提供登录、首页推荐、Agent 对话、Catalog 商品补全和推荐反馈页面。

```powershell
npm ci
npm run lint
npm test
npm run build
```

本地联调默认通过 `/api` 访问 Java Gateway；Mock 模式只用于无后端环境下的页面开发，不作为真实链路验收依据。
