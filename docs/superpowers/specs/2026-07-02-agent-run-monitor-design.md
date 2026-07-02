# Agent 运行监控复盘设计

日期：2026-07-02

## 背景

当前仓库已经有三块基础能力：

- `rs-service-agent` 已有 Agent loop、runtime prompt/skill/tool 配置接口，以及 `AgentTraceReporter` 上报机制。
- `rs-service-platform-trace` 已有内存聚合的 trace 服务，支持 account profile、recommend trace、agent turns、agent events、interaction events 和 session timeline。
- `frontend /observe` 已有 `ObserveConsole` 和 `TracePanel`，可以按 session/request 查看用户画像、推荐链路、Agent 多轮和时间线。

第一阶段目标是完善轨迹平台的 **运行监控复盘**，帮助开发时定位单次 agent 会话或请求的运行链路、耗时、token、工具调用、错误和基础质量信号。实时监控只做轻量刷新，不做完整 live board。

## 范围

本阶段包含：

- 单个 `sessionId` / `requestId` 的运行摘要。
- 按时间线展示模型调用、工具调用、RAG/推荐调用、最终答案和错误事件。
- 摘要覆盖链路耗时、token/成本上下文、错误与质量信号。
- 点击时间线事件查看输入摘要、输出摘要、错误信息和原始 `data`。
- 手动刷新，以及默认关闭的轻量自动刷新。

本阶段不包含：

- prompt、skill、tool 的在线编辑。
- 批量评估、实验对比和 A/B 测试。
- WebSocket 或完整实时运行看板。
- trace 数据持久化迁移。
- 新建独立监控服务。

## 推荐方案

采用 **复盘时间线** 作为第一版主布局。

该方案最贴合现有 `ObserveConsole`、`TracePanel` 和 `rs-service-platform-trace`，可以在现有查询入口和聚合服务上做最小增量。后续可以自然扩展到实时看板、调优工作台和批量评估。

备选方案：

- 实时运行看板：适合盯正在运行的请求，但需要新增运行状态索引和刷新/流式接口，第一版成本更高。
- 调试工作台：调优闭环更强，但会提前引入 prompt/skill/tool 编辑和实验保存，超出运行监控第一阶段边界。

## 架构

第一版不新建服务，沿用现有三层。

`rs-service-agent` 继续负责产生运行事件：

- 模型调用事件。
- 工具调用事件。
- RAG/推荐相关工具事件。
- 最终答案事件。
- 错误事件。
- token、耗时、模型/provider 等运行指标。

`rs-service-platform-trace` 作为运行监控聚合层：

- 在现有 `InMemoryPlatformTraceService` 基础上补充请求/会话运行摘要视图。
- 聚合 `AgentTraceEventVO`、`AgentSessionTraceVO`、`RecommendTraceVO`、`PlatformInteractionEventVO`。
- 根据事件推导状态、阶段摘要、token/耗时汇总和质量信号。
- 查询不到部分数据时返回 partial/empty 视图，不让页面整体失败。

`frontend /observe` 作为控制台入口：

- 保留当前 session/request 查询。
- 重排为摘要指标、运行概览、主时间线、事件详情面板。
- 轻量实时只做手动刷新和可选定时刷新，不引入 WebSocket。

## 数据模型

新增面向前端的聚合视图，建议命名为 `AgentRunMonitorVO`，由 `rs-service-platform-trace` 生成。

核心字段：

- `session_id`：会话标识。
- `request_id`：请求标识，可为空。
- `status`：运行状态，取值为 `running`、`success`、`failed`、`partial`。
- `summary`：总耗时、总 token、模型/provider、工具调用次数、错误数、推荐 item 数、是否有最终答案。
- `phases`：按阶段聚合的统计，例如 `model_call`、`tool_call`、`rag`、`recommend`、`final_answer`。
- `events`：按时间排序的事件明细，保留现有 `AgentTraceEventVO` 风格字段。
- `quality_signals`：规则生成的质量信号。
- `related_traces`：关联已有 agent turns、recommend traces 和 interaction events 的轻量引用。

事件字段第一版重点补齐：

- `event_type`
- `phase`
- `status`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `cache_read_input_tokens`
- `cache_write_input_tokens`
- `model_provider`
- `model_name`
- `tool_name`
- `error_code`
- `error_message`
- `input_summary`
- `output_summary`
- `data`
- `created_at`

质量信号第一版由规则生成：

- `missing_final_answer`：没有最终答案事件或最终答案为空。
- `empty_tool_result`：工具调用成功但输出为空。
- `tool_error`：存在工具错误事件。
- `model_error`：存在模型错误事件。
- `high_latency`：总耗时或单阶段耗时超过阈值。
- `no_recommendation_items`：推荐链路没有最终 item。
- `partial_trace`：当前 session/request 缺少关键关联数据。

## API 设计

在 `rs-service-platform-trace` 增加面向前端的查询接口：

```http
GET /api/platform/agent/runs/{requestId}/monitor
GET /api/platform/sessions/{sessionId}/agent-monitor
```

如果调用方同时有 `sessionId` 和 `requestId`，前端优先按 request 查询详情，同时保留 session 级上下文。

返回结构为 `AgentRunMonitorVO`。当不存在事件时，返回空视图：

- `status = partial`
- `summary` 数值为 0 或空状态
- `events = []`
- `quality_signals` 包含 `partial_trace`

内部写入接口继续复用现有：

```http
POST /internal/platform-trace/agent/events
POST /internal/platform-trace/agent/turns
POST /internal/platform-trace/recommend/trace
POST /internal/platform-trace/interactions/events
```

第一版不要求一次写入完整 monitor 对象。

## 前端设计

`/observe` 页面重排为四个区域。

顶部摘要条：

- 状态。
- 总耗时。
- 总 token。
- 模型/provider。
- 工具次数。
- 错误数。
- 最终答案状态。
- 手动刷新按钮。
- 自动刷新开关，默认关闭。

左侧运行概览：

- session/request 基本信息。
- 用户画像摘要。
- 最近一次 request。
- 质量信号标签。
- 推荐链路摘要。

主时间线：

- 按时间展示 `model`、`tool`、`rag`、`recommend`、`final_answer`、`error` 事件。
- 每行显示阶段、名称、状态、耗时、token、request/event id。
- 点击事件后在详情面板展示完整信息。

右侧详情面板：

- 输入摘要。
- 输出摘要。
- 错误 code/message。
- 原始 `data` JSON。
- 关联推荐链路或最终答案结构。

推荐链路明细继续复用当前已有列表，不把完整推荐结果塞进时间线行。

## 错误处理

- trace 服务缺少部分事件时，返回 `partial`，页面展示已有数据。
- agent 上报失败不影响主对话流程；上报失败建议记录本地 warn 日志。
- request/session 查不到时返回空监控视图，前端展示暂无事件。
- 大字段只在详情面板展示，时间线只展示摘要。
- 自动刷新只在 `running` 或 `partial` 状态下工作，进入 `success` 或 `failed` 后停止轮询。

## 测试设计

后端测试：

- 事件聚合顺序。
- `status` 推导。
- token/耗时汇总。
- phase 聚合。
- 质量信号生成。
- 空事件和缺失关联数据降级。

agent 侧测试：

- 模型调用事件字段完整性。
- 工具调用事件字段完整性。
- 错误事件字段完整性。
- 上报失败不影响主流程。

前端测试：

- TypeScript 检查。
- 摘要计算、事件排序、状态标签等纯函数保持可测。
- 当前项目若没有前端测试框架，第一版先用纯函数和手动 smoke 控制风险。

手动 smoke：

- mock 模式查询一个 session/request。
- 真实接口查询一个 session/request。
- 确认摘要、时间线、详情面板、推荐链路和空状态都能显示。

## 实施顺序

1. 后端补充 `AgentRunMonitorVO` 及聚合服务方法。
2. 后端补充 platform 查询接口。
3. agent 侧补齐关键事件字段，尤其是 phase/status/error/input_summary/output_summary。
4. 前端补充 monitor API client 和类型。
5. 重排 `/observe` 页面为摘要、概览、时间线、详情面板。
6. 增加自动刷新开关。
7. 补后端单测和前端 TypeScript 检查。

## 验收标准

- 输入 `sessionId` 或 `requestId` 后能看到运行摘要。
- 时间线按事件发生时间排序。
- 模型、工具、RAG/推荐、最终答案、错误事件至少能区分展示。
- token、耗时、工具次数、错误数能正确汇总。
- 点击时间线事件能查看详情。
- 缺失数据不导致页面崩溃。
- 自动刷新默认关闭，开启后不会在终态持续轮询。
