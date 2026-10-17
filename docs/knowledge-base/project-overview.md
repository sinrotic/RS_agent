---
id: kb-project-overview
type: overview
status: current
owner: project-maintainers
last_verified: 2026-09-05
confidence: confirmed
---

# 项目概览与当前状态

2026-09-05 服务修复已落地到本地代码，真实基础设施与模型仍待远程验收，详见 [修复记录](../superpowers/plans/2026-09-05-service-reliability-repairs.md)。

## 一句话定位

RS Agent 是“传统推荐 backbone + Agent 交互编排”的混合推荐系统：召回、排序和约束层负责可控的候选选择，Agent 负责多轮需求理解、工具编排、解释和反馈响应，RAG 负责基于商品事实的 grounding，而不是替代召回或排序。

## 开发主线

仓库包含两套相关实现：

- `java_agent/`：当前默认的功能开发和集成主线，采用 Java 21、Spring Boot/Cloud、微服务网关和 React 前端。
- `python_agent/`：推荐算法、Agent、Serving、离线训练与实验治理原型；稳定能力进入 `rs_core`，探索性实现留在 `rs_lab`。

除非任务明确属于 Python Agent、推荐实验或离线训练，新的产品能力和服务集成优先从 Java 主线开始。该规则来自仓库根 [README](../../README.md)。

## 仓库地图

| 路径 | 角色 | 当前约束 |
| --- | --- | --- |
| `java_agent/` | Java 微服务、Java 主前端、远程部署和 SQL Schema | 默认产品化主线 |
| `python_agent/rs_core/` | Python 稳定核心、Serving、在线与离线薄抽象 | 需要测试和治理门禁后才能沉淀 |
| `python_agent/rs_lab/` | 推荐实验、诊断、批处理与阶段性 gate | 产物默认不代表生产可用 |
| `python_agent/configs/governance/` | Python 当前路由和工程治理登记 | 路由状态的权威入口 |
| `python_agent/outputs/` | 运行 Artifact、指标和诊断结果 | 只有被正式引用的产物才可作为长期证据 |
| `db/`、`java_agent/sql/` | 本地持久化目录和 Java Schema | SQL/CQL 文件定义版本化 Schema；本地数据目录不是代码产物 |
| `docs/adr/` | 系统级架构决策 | 修改冲突行为前必须先检查 |
| `docs/research/` | 外部技术调研 | 只作决策输入，不直接代表项目事实 |
| `参考/`、`old_dic/` | 参考实现和历史资料 | 不作为当前实现或规划权威来源 |

## Java 能力状态

| 能力 | 状态 | 说明与权威入口 |
| --- | --- | --- |
| 推荐主部署 | `current` | 默认 `recommend` 模式包含 User、Catalog、Recommend、Agent、Model、Platform Trace 和 Gateway；见 [远程应用部署](../../java_agent/deploy/remote/app/README.md) |
| 商品交易扩展 | `optional` | `full-commerce` profile 额外启用 Order、Inventory、Payment、Seckill 和 Kafka；不属于默认推荐部署 |
| Agent 对话和流式输出 | `current` | `/api/agent/chat` 与 `/api/agent/chat/stream` 已有 Controller；流式协议为 SSE |
| Agent 会话持久化 | `configuration-dependent` | 本地默认可关闭或使用内存；远程 compose 默认启用 Redis 热状态、ScyllaDB 持久记录和 MySQL 投影，并执行 Schema 校验 |
| 推荐 RAG | `current boundary` | RAG 属于 Recommend，不是独立微服务；Agent 只调用推荐语义工具，具体检索实现被 Recommend 隐藏 |
| 在线反馈闭环 | `current code, acceptance pending` | 已有 MySQL 权威事件、Redis 投影与反馈重排；序列化、乱序、撤销和分批重建已有回归修复，远程故障恢复仍待验收 |
| Catalog 商品补全 | `current code, acceptance pending` | 已有单项和批量查询、MySQL 与缓存实现；真实商品展示链路仍应以测试和 Gateway smoke 完成情况验收 |
| 平台观察 | `current` | Platform Trace 聚合 User、Recommend、Agent 追踪；是否拉取真实下游数据由配置开关控制 |
| 浏览器认证 | `current code, acceptance pending` | 短期 access token、HttpOnly refresh cookie、CSRF 和 Redis token store 已有实现/说明，完整验收以测试为准 |

Java 模块清单的最终来源是 [父 POM](../../java_agent/pom.xml)，运行组合的最终来源是 [应用 Compose](../../java_agent/deploy/remote/app/docker-compose.yml)。

## Python 能力状态

| 能力 | 状态 | 说明与权威入口 |
| --- | --- | --- |
| 推荐与 Agent 原型 | `provisional_current` | FastAPI、CLI、Session、feedback、simulation 和展示契约用于演示与验证，不自动等价于 Java 产品主线 |
| Python 在线/Agent split app | `provisional_current` | `rs_core.serving.api.online_app` 与 `agent_app` 可独立启动，部署由 `python_agent/deploy/` 编排 |
| 当前召回路由 | `deprecated/continuation_only` | registry 将旧 `current_recall_route` 标为退役；pool500 只保留 continuation/shadow 语义 |
| 当前排序路由 | `current, effect claim forbidden` | registry 登记 `pool500_cold_coarse_then_deepfm_fine`，但候选覆盖 gate 未通过时不得宣称严格总体提升 |
| pool500 read-only shadow | `experimental` | 不允许候选生成、排序输入替换、promotion 或 pool1000 扩展；`FULL_POOL500_READY` 只表示 recall Artifact readiness |
| Qwen/QLoRA/SFT/GRPO | `planned/experimental` | 作为训练和对齐路线，不得表述为完整生产能力 |

Python 当前路线必须先查 [Current Route Registry](../../python_agent/configs/governance/current_route_registry.yaml)，再查其引用的配置、workflow、脚本、Artifact 和 promotion gate。

## 当前系统主流程

1. 浏览器通过 Gateway 登录并获得可信身份上下文。
2. 首页调用 Recommend 获得候选、排序信息和推荐理由；商品事实由 Catalog 补全。
3. Agent 接收用户消息，调用模型并执行受控工具；推荐和 RAG 工具路由到 Recommend。
4. Agent 将结构化结果或 SSE 事件返回前端，Platform Trace 提供观察视图。
5. exposure、like、dislike 等反馈回流推荐服务，供后续会话或离线处理使用。
6. 可选 `full-commerce` 模式才进入库存、订单、支付和秒杀链路。

详细调用关系见 [系统架构](architecture.md)，数据责任见 [数据流与事实来源](data-flow.md)。

## 明确不应混淆的边界

- Java 主线和 Python 原型共享业务目标，但不是两套都必须同步实现的生产服务。
- RAG 提供候选内商品证据，不得越过候选池创造商品或替代排序。
- `rs_lab`、smoke、diagnostic、shadow 和 simulation 产物不代表生产晋级。
- Catalog 商品事实与推荐分数/理由是不同责任；前端拼装 Display Product 不产生新的商品事实。
- `full-commerce` 是可选部署能力，不能反向扩大默认推荐模式的依赖面。

## 待澄清事项

以下不一致不能由知识库擅自裁决，应通过 GitHub Issue 关闭后再更新状态：

1. [Current Route Registry](../../python_agent/configs/governance/current_route_registry.yaml) 已将 pool200 召回标为退役，并登记新的当前排序策略；但 [Python PRD](../../python_agent/prd.json) 仍写有“现有 pool200/top_k=5 ranking gate”。运行路由暂以 registry 为引用，PRD 验收语句需要校准。
2. [真实商品展示设计](../superpowers/specs/2026-08-02-product-display-real-chain-design.md) 标记“已规划，待实现”，但当前工作区已经存在对应 Catalog、前端和测试改动。能力是否完成必须以验收测试和 Gateway smoke 为准。
3. [Java 前端 README](../../java_agent/frontend/README.md) 的摘要仍出现 `/api/items/*`、`/api/interactions/*`，而当前 Gateway 和 Controller 使用 `/api/catalog/**`、`/api/recommend/feedback/**`。开发应以 Gateway 配置和 Controller 为准，并后续修正文档漂移。
4. 本知识库创建时工作区存在大量未提交改动，因此这里记录的是 2026-08-06 的工作区快照，不是某个已发布 tag 的能力声明。
