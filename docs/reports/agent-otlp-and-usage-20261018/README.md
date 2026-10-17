# 平台用量汇总与 OTLP 元数据导出

日期：2026-10-18。基于 `cd741819`，将生成调用账本接入平台监控，并增加独立开关的 OTLP/HTTP JSON 导出。推荐策略、Prompt、模型权重和简历保持原样。当前是本地协议与回归验收，真实 Langfuse 接收和远程部署仍待完成。

## 平台计量口径

平台按 `(session_id, request_id, model_call_id)` 汇总 `model_call_started/completed`。开始与完成乱序、重复完成和流式累计快照不会重复增加用量；冲突的完成快照不参与可信总量。只有所有已观测调用都拿到对应字段的最终非负整数，才产生该字段的总量。

`summary.prompt_tokens/completion_tokens/total_tokens` 和阶段 `total_tokens` 允许 null；明确回传的 0 保留为 0。`usage_coverage` 返回调用数、完成观测数、冲突数及各字段的已知小计、观察数、最终快照数和可信总量。小计可能包含未最终确认的观测值，不能当作完整计费量。

没有逐次调用标识的旧记录保留原始事件入口，汇总标为 `legacy_unverified`；新旧 Turn 混合为 `mixed`，总量保持未知。前端监控和观察页使用新账本，不再用 timeline 相加回填总 token，并显示最终回执覆盖率。后端与前端应配套更新，其他消费者需兼容可空字段。

耗时按 `[created_at - latency_ms, created_at]` 的区间并集合并，父子调用和并行事件不重复相加。前端标注 `Observed latency`：它是已测量区间的覆盖时长，未观测间隙不推断；各阶段可能重叠，不能再将阶段相加作为 Turn 总耗时。

## 外部导出路径

`AgentTraceReporter → 独立平台队列 / 独立 OTLP 队列 → 各自 HTTP 目标`。

外部投影只输出 Turn、模型调用、工具调用的完成 Span；开始事件仅用于有界时间缓存。每个目标使用独立的单工作线程、队列与失败统计，一个目标阻塞不阻断另一个目标。沿用上一批的单负载 64KiB、队列 512、请求 2 秒、退出等待 3 秒默认限制；同时启用两个目标时，排队负载上限约 64MiB，另计对象与线程开销。

OTLP 接口使用完整 endpoint、`application/json`、十六进制 trace/span ID、十进制字符串纳秒时间戳和整数枚举。HTTP 200 仍需检查 `partialSuccess.rejectedSpans`；部分拒绝、非 200、非法响应或响应超过 4KiB 都计为失败，不记录响应正文。协议依据见 [OTLP specification](https://opentelemetry.io/docs/specs/otlp/)。

Langfuse 模式附加 `x-langfuse-ingestion-version: 4`，由配置提供 Basic Authorization；标注 `langfuse.observation.type`、HMAC 化的 session ID，以及最终确认的 `gen_ai.usage.input_tokens/output_tokens`。模型别名只能来自明确配置，不能据此推断真实权重版本或准确费用。协议依据见 [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry)。

## 外发字段控制

- 使用 HMAC-SHA256 为 Session、Turn、模型及工具调用生成稳定标识；原始 ID 和密钥不进入载荷。跨实例使用同一密钥才能关联；轮换密钥会改变标识。
- Span 名称固定，不发送任意工具名、模型事件文本、Prompt、工具参数/返回正文、原生 usage、异常文本或任意 data 字段。
- 状态只接受枚举；用量只接受五类非负整数。未最终确认的数值仅进入 `rs.usage.observed.*`，不进入标准最终 usage 属性。
- `prompt/tools/skills_sha256` 只有在生产者提供合法 64 位十六进制指纹时才允许外发；当前尚未补齐这些生产者，不能声称已有完整版本追溯。
- 时间缓存最多 1024 个哈希键；淘汰或缺失时按有效 latency 恢复，否则使用零区间并标记 `rs.duration.known=false`。

此控制应用于新增外部目标。现有内部平台继续保留原有诊断数据与访问权限，不因增加 OTLP 而自动获得对外发送正文的授权。

## 配置

Spring 配置、远程 Compose 及 `.env.example` 已贯通以下变量，默认不开启外部导出。

| 变量 | 用法 |
| --- | --- |
| `RS_AGENT_TRACE_ENABLED` | 原有内部平台开关，独立于外部开关 |
| `RS_AGENT_TRACE_OTLP_ENABLED` | 外部开关，默认 false |
| `RS_AGENT_TRACE_OTLP_ENDPOINT` | 完整 traces URL；Langfuse 为 `https://<host>/api/public/otel/v1/traces` |
| `RS_AGENT_TRACE_OTLP_AUTHORIZATION` | 由密钥管理注入完整 Authorization；Langfuse 使用 Basic base64(publicKey:secretKey) |
| `RS_AGENT_TRACE_OTLP_IDENTITY_KEY` | 至少 16 字符的 HMAC 密钥，部署时生成随机值，不能提交仓库 |
| `RS_AGENT_TRACE_OTLP_LANGFUSE` | Langfuse 适配头与必需鉴权校验，默认 false |
| `RS_AGENT_TRACE_OTLP_SERVICE_NAME` | 默认 `rs-service-agent` |
| `RS_AGENT_TRACE_OTLP_MODEL_NAME` | 可选运维确认的模型别名，默认空 |

启用后缺少 endpoint/密钥、地址内嵌凭据/查询参数/片段，或 Langfuse 缺少鉴权时，启动配置校验失败。关闭时不要求这些配置。既有队列、超时、单负载参数同时适用于两个目标。

## 验收结果

机器可读结果和文件指纹见 [checks.json](checks.json) 及 [manifest.json](manifest.json)。

| 检查 | 结果 |
| --- | --- |
| JDK21 Maven Agent 及平台 Trace 打包 | 成功；Agent 257 项收集，256 通过、1 跳过；平台 45 项全部通过 |
| 新增 OTLP 测试 | 白名单与敏感值哨兵、稳定标识/父子关系、非最终用量、缓存淘汰、真实本地 HTTP、独立目标故障、部分拒绝、超大/非法响应、配置与关闭生命周期 |
| 平台账本与 HTTP 契约 | 去重、乱序、冲突、开始后无完成、零与缺失、混合历史、嵌套/并行时长、序列化后的覆盖率 |
| 前端 | 类型检查、108 项测试、生产构建通过；新增面板渲染验证 null 与覆盖率 |
| 根部署/启动契约 | 56 项通过 |
| Python 账本与 Java Skill Benchmark 联调 | 35 项通过，包含已编译 Java 真实入口与 HTTP 模型替身 |
| Playwright 浏览器流程 | 历史恢复、续聊、中断、重试、A2UI、降级与反馈操作通过 |

Agent 唯一跳过项仍依赖本地 vLLM。HTTP 模型替身和本地 OTLP 接收器只验证工程协议，不构成真实模型质量、吞吐、费用或简历提升指标。此前记录的 36 条工程规范存量问题不在本次修复范围。

## 剩余工作

P1 仍未完成：跨 HTTP 委派的父子传播、模型/Prompt/Skill/数据完整版本、摘要和 Judge 等全部调用种类、指标注册、持久化导出重放及真实外部平台验收。本实现是显式 OTLP JSON Adapter，未接入 OpenTelemetry SDK 的全服务自动埋点。

导出不做自动重试或持久化补发；accepted/sent/failed/dropped/oversized/pending 保持 reporter Java 查询接口和首次告警，尚无运维端点或 Micrometer 注册。关闭超时可能丢失观测，每个目标独立 flush，双目标总等待可能接近两倍关闭期限。外部相同 Span ID 的落库去重行为也需在真实目标验证。

覆盖率的分母只包含收到的调用事件。如果开始和完成都被丢弃，账本无法发现这次调用，因此不能将它当作全系统账单；需结合后续导出丢失指标判断完整性。Trace 继续是观察视图，Session Event 与 Context Checkpoint 的持久化权威保持原有设计。
