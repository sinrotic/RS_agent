# Offline / Online Serving Contract ADR

- 日期：2026-06-13
- 状态：Accepted
- 决策范围：Offline System、Online Serving System、Traditional Recommendation、Agent Orchestration 的服务契约收口

## 背景

当前项目已经同时具备离线产物构建、在线服务、传统推荐链路和 Agent 编排能力，但如果不把边界写清楚，最容易出现三类误用：

1. 把离线 recall artifact 误当成 ranking promotion 证据。
2. 把 single-process demo/local serving 层误当成生产级微服务。
3. 把 Agent 工具编排误当成召回或排序主路的替代实现。

本 ADR 用来把这四层能力的职责、入口和治理语义固定下来。

## 决策

### 1. Offline System 只负责产物，不负责在线决策

离线系统负责生成并维护可服务化的 artifact，核心包括：

- recall candidate artifact
- source index / source manifest
- ranking config / rerank artifact
- RAG knowledge index
- governance registry / route registry

离线系统的输出目标是“可被在线读取”，不是“直接代表线上主路已晋升”。

### 2. Online Serving System 采用 single-process demo/local serving layer

当前在线服务是 **single-process demo/local serving layer**，不是独立生产级微服务，也不是多实例线上 serving 平台。

它的职责是把离线产物和传统推荐能力封装成可测试、可展示、可治理的接口，服务于本地 demo、评估、session replay 和 simulation。

### 3. Traditional Recommendation 继续作为稳定 backbone

传统推荐链路保持独立职责：

- 召回
- 候选合并
- 排序 / rerank
- 过滤
- 展示商品卡

它可以直接对外服务，也可以被 Agent 工具复用，但不因为 Agent 存在就被重写。

### 4. Agent Orchestration 只做工具编排

Agent 负责自然语言理解、多轮对话、澄清、工具选择、RAG 证据消费和反馈响应，不直接扫描全量商品空间，也不直接替代召回或排序模型。

Agent 只能通过服务端工具使用推荐系统能力，不能把内部 source、score、diagnostics 当作前台 contract 暴露出去。

## 在线契约

当前服务层固定使用以下入口：

- `POST /recall`
- `POST /recommend`
- `POST /chat`
- `POST /feedback`
- `POST /session/start`
- `GET /session/{session_id}`
- `POST /demo/e2e`
- `POST /simulation/scene`
- `POST /simulation/batch`

### 契约含义

| 入口 | 定位 | 说明 |
|---|---|---|
| `POST /recall` | 纯召回入口 | 只返回候选 item id，不做排序、不出商品卡、不输出诊断字段 |
| `POST /recommend` | 传统推荐入口 | 保留召回 + 排序 + 展示的完整推荐流程 |
| `POST /chat` | Agent 编排入口 | 由 Agent 调用工具完成多轮对话、推荐和解释 |
| `POST /feedback` | 反馈入口 | 记录结构化反馈，并影响后续会话响应 |
| `POST /session/start` | 会话初始化 | 为 demo / replay / simulation 初始化 session |
| `GET /session/{session_id}` | 会话导出 | 提供安全的会话轨迹导出，不暴露内部训练或诊断字段 |
| `POST /demo/e2e` | 一键闭环演示 | 用于快速验证首轮推荐、反馈和第二轮变化 |
| `POST /simulation/scene` | 单场景仿真 | 运行单个模拟客户场景 |
| `POST /simulation/batch` | 批量仿真 | 运行批量模拟评估 |

## pool500 readiness 语义

pool500 readiness 只表示 **recall artifact / source-index readiness**，不表示下面这些内容：

- ranking promotion
- pool1000 readiness
- production readiness
- ranking input replacement
- 独立生产级 recall service ready

也就是说，pool500 只能作为召回产物和 source index 的在线可读准备状态，不能自动升级为排序主路、更不能自动升级为生产上线能力。

## 路径一致性决策

治理层的稳定主路径以 **hot010 stable path** 为 artifact authority。当前在线服务配置 `configs/serving/online_service.yaml` 必须与 `configs/governance/current_route_registry.yaml` 保持一致。

### 约束

- `current_route_registry.yaml` 是当前路由权威登记，不是历史草稿。
- `online_service.yaml` 只能读取与当前治理一致的 online route / source index。
- worker-config 发生变化后，必须同步检查两者是否仍然对齐。
- 如果 registry 和 serving config 出现不一致，以治理注册表和 hot010 stable artifact 为准，而不是以临时服务配置为准。

## 影响

### 正向影响

- 把离线、在线、传统推荐和 Agent 四层职责拆开，避免 contract 漂移。
- 明确 single-process demo/local serving 的定位，避免误把 demo 当生产。
- 让 `/recall`、`/recommend`、`/chat`、`/feedback`、`/session/start`、`GET /session/{session_id}`、`/demo/e2e`、`/simulation/scene`、`/simulation/batch` 各自有清晰边界。

### 代价

- 需要维护 registry 与 serving config 的一致性检查。
- pool500 的 readiness 语义必须持续通过治理文档和测试固化，不能口头约定。

## 关联文档

- `dic/architecture/SYSTEM_ARCHITECTURE.md`
- `dic/architecture/ARCHITECTURE.md`
- `dic/guides/CODEBASE_GOVERNANCE_GUIDE.md`
- `configs/governance/current_route_registry.yaml`
- `configs/serving/online_service.yaml`

## 面试可讲点

- 我把离线产物、在线 serving、传统推荐和 Agent 编排的边界写成 ADR，避免把“能跑”误判成“能晋升”。
- 通过把 pool500 readiness 限定为 recall artifact / source-index readiness，能防止实验产物越权进入 ranking promotion 或 production readiness。
- 通过要求 `online_service.yaml` 和 `current_route_registry.yaml` 对齐，把治理权威和服务配置分离，降低 route 漂移风险。