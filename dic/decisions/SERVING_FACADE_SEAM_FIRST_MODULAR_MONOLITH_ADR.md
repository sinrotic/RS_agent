# 服务层 Facade 的 seam-first modular monolith ADR

- 日期：2026-06-14
- 状态：Accepted
- 决策范围：Serving 层 P0/P1 contract skeleton、facade 边界、路由不变性、治理约束

## 背景

当前 serving 层已经同时承载 `/recall`、`/recommend`、`/chat`、`/feedback` 等入口，`RecommendationService` 和 `HybridRecommendationEnvironment` 也承担了较多编排职责。如果直接继续在实现层堆叠，会有两个风险：

1. route 和业务实现继续耦合，后续改造容易误伤现有行为。
2. `RecommendationService` 过厚后，facade、service、workflow 的职责边界会越来越模糊。

本轮目标不是拆微服务，也不是重写 serving 路由，而是在模块化单体内先做 seam 收口，把后续实现控制在可测试、可回滚的边界里。

## 决策

### 1. 采用 B1 seam-first modular monolith

当前 serving 继续保持单体内协作模式，P0/P1 先落地 facade contract skeleton，不改变现有 HTTP route 语义，也不把 serving 切成独立微服务。

### 2. 显式定义 facade 边界

Serving 层收敛为以下 facade 总 seam：

- `FeedbackSessionFacade`
- `RecallFacade`
- `RecommendationFacade`
- `AgentOrchestrationFacade`
- `EvidenceRAGFacade`

其中本轮 P0/P1 先落地前三个 facade 作为首批 contract skeleton：

- `FeedbackSessionFacade`
- `RecallFacade`
- `RecommendationFacade`

`AgentOrchestrationFacade` 与 `EvidenceRAGFacade` 仍属于同一条架构切面上的后续 seam；P2 的执行目标是把这两个 seam 继续补到模块化单体内部，但仍然只作为 facade 级适配层，不改变现有 HTTP route 形状，也不把 serving 拆成独立微服务。

这些 facade 只负责 contract seam、编排和适配，不承担独立服务职责。

### 3. `RecommendationService` 转为组装与委托入口

`RecommendationService` 继续作为 serving 的聚合入口和委托层，负责把 route 请求分发给对应 facade 或共享工作流，不再作为所有业务逻辑的最终承载点。

### 4. 治理约束保持冻结

本轮文档收口必须继续维持以下治理语义：

- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- RAG 只消费 evidence，不把诊断产物写进前台 contract
- DeepFM 只保留 shadow diagnostic，不作为 promotion 证据

### 5. 路由保持不变

现有 `/recall`、`/recommend`、`/chat`、`/feedback` 的入口和职责不在本轮调整，facade 只是在现有路由之下增加更清晰的实现分层。

## 边界说明

- 不拆微服务。
- 不改 `rs_core/serving/app.py` 的路由集合。
- 不把 facade 写成新的业务耦合层。
- 不放松 ranking / pool1000 / promotion 的治理门禁。
- 不把 RAG evidence、score、source、diagnostics 暴露到 public payload。

## 影响

### 正向影响

- 先把服务层切面写清楚，后续实现和测试都更容易对齐。
- `RecommendationService` 的职责会从厚对象收敛为委托入口，降低后续改造风险。
- 通过 facade seam 先冻结 contract，再逐步补实现，能避免把“结构重构”和“业务改动”混在一起。

### 代价

- 需要额外维护 facade 与 service 的委托关系。
- 需要用测试固化 facade 是否真的只做适配，不越权改写业务语义。

## 关联文档

- `dic/architecture/SYSTEM_ARCHITECTURE.md`
- `dic/decisions/SERVING_CONTRACT_OFFLINE_ONLINE_ADR.md`
- `.omc/handoffs/team-plan-to-team-exec-service-architecture-facades.md`
- `dic/ENGINEERING_NARRATIVE_LOG.md`

## 面试可讲点

- 先在模块化单体里做 seam-first 收口，而不是一上来拆微服务，可以把改造风险控制在可验证范围内。
- 通过 facade 把 `RecommendationService` 从厚对象变成委托入口，既保留现有路由，又给后续演进留出明确切面。
- 用治理冻结项把 `ranking_input_replacement`、`pool1000`、`promotion` 和 RAG/DeepFM 的诊断边界一次写清，避免架构文档和实现目标漂移。
