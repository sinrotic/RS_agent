# rs-frontend 前端适配目录

## Agent 结构化展示统一迁移（2026-10-11）

Agent 聊天页的商品展示统一经 `projectAgentUi` 转换为 A2UI，由 `A2uiView` 复用现有 `ProductCard` 渲染，移除了聊天页直接遍历商品并渲染卡片的旧分支。业务接口和 Catalog hydration 不变：标题、价格、图片、排序与推荐理由仍由业务服务提供，UI 消息只引用商品 ID。

模型本轮没有输出 UI、只输出表单、引用未知商品或恢复旧历史时，展示适配层根据业务结果生成默认 A2UI `ProductCards`；模型本轮已有可展示的商品 UI 时不追加重复卡片。前一轮的商品选择不会遮蔽新一轮无 UI 的业务推荐，模型表单和原始状态仍保留。旧 `product_cards` 回答块转换为 A2UI 商品组件，`comparison_table` 的商品 ID 转换为网格卡片，其文字内容及 `followup_question` 转换为 `Text`；普通回答仍显示在聊天记录中。空推荐也通过 A2UI `Text` 展示。

默认界面是由当前业务结果派生的展示投影，不写入模型 UI 状态、`context.a2ui_state` 或持久会话历史；恢复时重新生成，避免与模型创建的界面标识冲突。商品打开、反馈、曝光归因和详情服务降级路径保留。此迁移只针对 Agent 聊天页，不改变商城首页等非 Agent 页面。

验证：`npm test`、`npm run build`；启动开发服务器后运行 `npm run test:a2ui`，用 HTTP 夹具覆盖旧历史、无模型 UI、旧回答块、表单回传、未知商品与错误 UI、目录降级/重试、空结果、反馈和曝光归因。该浏览器检查不替代真实模型与业务服务验收。

### 现有 QA 部署与真实验收（2026-10-11）

已将前端独立部署到现有 QA 的 `127.0.0.1:18289`，代理现有网关 `18288`；未恢复已停止的正式环境，也未由此次发布重启模型或业务服务。前端容器为 `rs-e2e-857e8b14-a2ui-frontend`，发布目录位于 `/tmp/rs-agent-e2e-20261010-llm-opt-20261011/frontend-a2ui-20261011-20261011T024500Z`。本机可用 SSH 转发访问，回滚只需停止该前端容器，不影响 QA 后端。

`scripts/package-a2ui-qa.cjs` 生成带 SHA-256 清单的发布包；`scripts/deploy-a2ui-qa.py` 只允许本次 QA 根目录，校验现有依赖、端口、产物和容器名后部署，拒绝覆盖已有容器。

真实验收使用 `npm run test:a2ui:live`，需要设置 `RS_E2E_BASE_URL`、`RS_E2E_PRIVATE_FILE`（私有 QA 账户 JSON，不应提交）、`RS_E2E_OUTPUT`，已有浏览器可通过 `RS_CHROMIUM_PATH` 指定。可用 `RS_E2E_INDEX_SHA256` 核对已部署版本。脚本使用真实登录、模型、推荐和目录服务，无 HTTP 夹具或响应替换；同时校验商品事实、A2UI surface、去重和刷新恢复。

验收记录位于仓库 `outputs/a2ui-live-20261011/`：`deployment.json` 保存发布信息，`browser-stable.json` 保存两条链路通过的真实响应和 DOM 证据。模型无 UI 时 5 张商品卡片在默认 surface 展示；模型返回 `ProductCards` 时 5 张卡片在模型指定 surface 展示。初次超时及后续复跑记录均保留，不用成功记录覆盖失败记录。真实模型不保证每次请求都生成 A2UI，即使用户要求 UI，也可能只返回旧回答块；这种情况仍由默认 A2UI 投影展示真实商品。

## 2026-10-10 服务修复

聊天页区分反馈保存与生成结果，已保存反馈后的生成重试沿用原轮次 ID，不重复提交反馈；流式 409 要求先刷新历史，410/404 转为只读。浏览器夹具 `npm run test:e2e` 同时覆盖这些路径。

工具链使用 Node.js 22、Vite 8、Tailwind 4 与独立 PostCSS 插件，全依赖审计为 0 项漏洞。支持 Chrome 111+、Safari 16.4+、Firefox 128+；窄屏导航和聊天布局已验证。完整结果见 [修复记录](../../docs/service-fixes-20261010.md)。

## Agent 交互界面（2026-10-09）

Java Agent 的 `a2ui-interface` skill 按需加载界面规则和服务端生成的组件 Schema。`emit_ui` 发布界面并继续处理，`emit_final_answer` 完成本轮；聊天页通过 `/api/agent/chat/stream` 接收完整的 SSE `answer_block`，由 `A2uiView` 更新界面。REST `/api/agent/chat` 同时返回 `answer_blocks`。

当前实现是 A2UI v0.9 的购物组件子集，目录为 `urn:rs-agent:a2ui:shopping:v1`，不是完整的 Google Basic Catalog。支持 `Text`、`Row`、`Column`、`Card`、`ProductCards`、`TextField` 和 `Button`，以及 `createSurface`、`updateComponents`、`updateDataModel`、`deleteSurface`。暂不支持组件模板、相对路径、客户端函数和主题扩展。前端直接复用已有 `ProductCard`，只展示本轮已 hydration 的商品。

`Button.action.event.name` 使用 `submit_query`，`context.query` 可以是文字或绝对路径绑定。用户点击后，查询作为下一条用户消息发送，当前组件与表单状态通过 `context.a2ui_state` 回传。界面更新使用 A2UI 消息，不需要 JSON Patch。界面消息校验失败时保留文字对话入口；不执行模型生成的 HTML/JavaScript。

验证：本目录运行 `npm test`、`npm run build`；Java 父项目运行 `mvn -pl rs-service-agent -am test`。现有部署的 Nginx 已关闭代理缓冲，但本次代码改动仍需发布前后端后才会在远端入口生效。

## 当前可用入口（2026-09-06）

网页已部署到远端 Nginx，并通过本机 SSH 隧道访问：`http://127.0.0.1:18088/`。页面和 `/api/` 使用同一入口，默认连接真实 Java 服务。电脑重启或隧道断开后，从仓库根目录运行 `./java_agent/frontend/start-remote-preview.ps1` 即可恢复入口。部署配置及验收见 [前端部署说明](../deploy/remote/frontend/README.md)。

下面的历史设计说明保留作背景，当前功能以实际代码及部署验收为准。

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

Mock 模式可在应用顶部切换，仅用于 Java 服务不可用时的本地 UI 开发；生产浏览器配置不应启用。
# 2026-09-07 首页更新

首页已接入真实画像／反馈召回与模型排序；“喜欢，找相似”重新召回，“不感兴趣”过滤并重排当前交付。近期商品跨会话去重，能力不可用时会显示降级提示。仍通过 `http://127.0.0.1:18088/` 访问，域名以后配置。

本轮验证和已知边界见 [个性化上线记录](../../docs/superpowers/plans/2026-09-07-personalized-home-completion.md)。

## 会话恢复与偏好管理

对话页现在支持历史 Session 切换、刷新恢复、新建对话、服务端停止生成和原消息重试。浏览器仅保存当前 Session ID；历史文字、回答块和商品交付来自服务端。重试沿用 `client_turn_id`，已确认的最终结果直接恢复，无确认结果返回 409 并提示先核对历史。

“我的偏好”页面支持撤销最近反馈、删除单个商品偏好和确认后清空。推荐服务或个性化排序降级时，对话页显示相应提示。公开聊天和历史接口不返回内部工具记录。

开发环境需要 Node.js 22.12 或更新的兼容版本。执行 `npm test` 和 `npm run build`；浏览器流程检查先运行 `npx playwright install chromium`，启动 `npm run dev -- --host 127.0.0.1 --port 5173 --strictPort`，再运行 `npm run test:e2e`。已有浏览器可通过 `RS_CHROMIUM_PATH` 指定。该检查使用 HTTP 夹具，真实后端和重启恢复仍需部署验收。
