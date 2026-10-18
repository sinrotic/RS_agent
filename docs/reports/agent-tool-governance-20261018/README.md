# Skill 禁用修复与工具执行治理验收

日期：2026-10-18。Skill 修复已独立提交 `b88167ea`；本报告记录随后接入 Java 产品执行链的工具治理及相关回归。覆盖 P2.2/P2.3 和 P2.1/P2.4 的部分内容，**不是全部能力计划或 P2 的最终验收**。

## 实际接入

生产 Spring 装配：`AgentLoop → GovernedAgentToolUseExecutor.openTurn → AgentCapabilityToolUseExecutor → VirtualThreadAgentToolUseExecutor → Capability Registry / 内部工具 → HTTP / 存储`。治理包装器是 Primary，原授权和资源许可保留；每次重试重新进入原执行链。

`openTurn` 在一次 Loop 的各轮模型调用之间共享期限、工具执行次数和重复检测状态；结束时关闭，下一 Turn 新建。熔断状态由当前活跃 Agent 实例跨 Turn 共享，遵循单活约定，不宣称分布式共享熔断。

- **Skill 禁用**：在实际执行 `load_skill` 时复核 enabled。目录隐藏后以旧名称加载、等待工具许可期间被禁用均拒绝，不返回正文或回查引用；管理员仍可读取配置，重新启用读取更新后的正文。已进入上下文的旧正文撤销和不可变版本资产没有因此完成。
- **失败分类与重试**：参数、响应解析、授权、容量、暂时依赖故障、超时、取消、未知分别处理；合法空列表保持成功。只对明确暂时依赖故障及可安全重放工具重试，带有界指数退避和抖动。重试受单工具尝试数、Turn 共享尝试数和剩余期限约束。超时、401/403、参数错误、畸形响应、容量拒绝和未知错误不自动重试。
- **期限与取消**：单工具执行超时独立于许可获取超时；Loop 期限通过既有中断上下文取消模型流和待执行工具。关闭 Turn 后取消定时任务，避免迟到期限污染其他 Turn。修复 Orchestrator 在取消先于 raw Future 发布时未继续取消实际任务的竞态。
- **无进展收敛**：按工具名、规范化参数和结果摘要检测重复。保留查询、分页、业务 ID 和预算等参数，剔除受控观测字段；外置结果附完整正文摘要，区分引用变化和预览以外的数据刷新。达到阈值后下一轮只允许最终回答，执行分支拒绝新工具，不依赖模型自觉服从提示。已在同轮并行发出的工作不会被反向撤销。
- **熔断**：recommend、rag、session、internal 四个受控组分别维护 CLOSED/OPEN/HALF_OPEN；默认连续三次基础设施失败后打开，冷却后仅放一个探针。epoch 隔离旧周期迟到成功/失败。业务、参数、授权、容量和取消不作为 CLOSED 状态的基础设施故障；半开探针未成功则继续冷却，不能把取消当恢复。

## 配置与结果

application.yml、受版本控制的 `.env.example` 和远程应用 Compose 已同步以下启动参数。参数不是运行中实例的实测配置。

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `RS_AGENT_TOOL_GOVERNANCE_ENABLED` | true | 治理包装器开关；关闭仍保留授权与原许可 |
| `RS_AGENT_TOOL_MAX_ATTEMPTS` | 2 | 一次工具调用最多尝试数，包含首次 |
| `RS_AGENT_TOOL_MAX_ATTEMPTS_PER_TURN` | 32 | Turn 共享工具尝试数；逻辑提交数也以此为上限 |
| `RS_AGENT_TOOL_EXECUTION_TIMEOUT_MS` | 30000 | 工具 Future 等待期限；包含其获取许可的等待 |
| `RS_AGENT_TURN_TIMEOUT_MS` | 120000 | 进入 Loop 后的执行期限 |
| `RS_AGENT_TOOL_RETRY_DELAY_MS` | 50 | 退避基础延迟 |
| `RS_AGENT_TOOL_NO_PROGRESS_LIMIT` | 3 | 同工具、参数、结果重复阈值 |
| `RS_AGENT_TOOL_CIRCUIT_FAILURE_THRESHOLD` | 3 | 依赖组连续基础设施失败阈值 |
| `RS_AGENT_TOOL_CIRCUIT_OPEN_MS` | 10000 | 熔断冷却期 |

`RS_AGENT_TOOL_ACQUIRE_TIMEOUT_MS` 继续控制工具许可等待，与执行超时不是同一个参数。次数上限最大 256，单调用尝试最多 3 次，计数与期限配置有启动校验。

内部结果附 `governance` 分类、实际尝试数及耗时；实际完成一次尝试的结果另含熔断状态和重复信号。新增门禁原因保留独立机器码，不回传参数、HTTP 响应正文或异常堆栈。没有新增公开 SSE 类型；仍使用现有 `tool_use/tool_result/interrupted/done` 及公开展示投影。

## 行为验收

机器可读结果、具体测试方法和文件/编译指纹见 [checks.json](checks.json)、[behavior-tests.json](behavior-tests.json) 与 [manifest.json](manifest.json)。

| 验收场景 | 实际结果 / 证据 |
| --- | --- |
| Skill 禁用与排队期间禁用 | `SkillDisableExecutionTest`：2 项，拒绝旧名称且不泄露正文，重新启用正常 |
| 真实 HTTP 503→200 / 401 / 畸形 JSON | `ToolGovernanceHttpTest`：可安全重放的读取重试成功；授权与解析失败只调用一次 |
| Registry 包装异常与再次授权 | 同套测试：分类穿过 Registry 保留，每次尝试分别产生授权审计 |
| 并发争用执行额度 | `GovernedAgentToolUseExecutorTest`：8 个并发逻辑调用、共享额度 2，实际执行 2 次，其余拒绝；重试消耗同一额度 |
| 重复、翻页、结果刷新、外置正文 | 同套测试：重复收敛；新分页、新 Turn 及正文刷新不误判，预览之外的变化也能区分 |
| 模型继续调用工具 | 真实 Loop 接入治理：收敛后模型再次请求工具，执行层返回 `TOOL_FINAL_ANSWER_ONLY`，实际工具次数不增加，最终仍可回答 |
| 超时、取消与释放 | 实际虚拟线程阻塞任务被中断，唯一许可可复用；不响应中断的任务保留许可至物理退出且不重试 |
| 挂起模型与 Turn 生命周期 | Spring AI 返回不结束的 Flux 时由 Loop 期限取消，终态 INTERRUPTED、原因为 turn_timeout；已关闭上下文不被迟到定时器中断 |
| 半开与旧周期 | `AgentToolCircuitBreakerTest` 及治理集成测试：同组只有一个探针，旧周期结果不改写新状态，取消探针不能登记恢复 |
| 取消先于 Future 发布 | `StreamingAgentToolUseOrchestratorTest`：用闩锁控制竞态，发布后实际 Future 仍被取消 |

最终 JDK21 Agent package：**283 项收集，282 通过，1 项既有本地 vLLM smoke 跳过**。本次相对先前 263 项基线新增 20 项，其中 Skill 2 项、治理及取消竞态 18 项。因部署配置有变更，按仓库要求追加全量 Maven test，并在最终分类修正后执行全量 package：14 个 Reactor 项目构建成功，773 项收集、772 通过、1 跳过。根部署/启动契约 56 项通过。完成最终打包后，Java/Python 评测与账本联调 42 项通过，未并行编译或读取类指纹。

该跨语言基准仍使用自定义 JSON 模型 Adapter，不代表生产治理包装器或真实模型效果；治理实际接入由 Primary 装配、真实 Loop、真实受控 HTTP 和物理工作线程测试分别验证。前端本批未修改，未重复其测试；平台及其他 Java 服务由全量 Maven 回归覆盖。没有加载正式模型、训练、远程部署或新增性能/满意度数字；存量 36 条工程规范问题仍按原基线跟踪。

## 学习文档对照

本批重新在浏览器打开以下五章，阅读可见课程目标、导言及首节；可见 DOM 未提供完整后续章节，因此这是本批机制对照，不能称为逐字通读整套教程。只保留设计归纳与验收映射，没有下载或复制教程全文。历史 22 章对照保留在 [中途复核](../../research/2026-10-18-agent-implementation-recheck.md)，不改写其冻结结论。

| 来源 | 本批对照结论 | 尚未完成 |
| --- | --- | --- |
| [19-5 Skill](https://alidocs.dingtalk.com/i/nodes/1DKw2zgV2Pxk3MmDtv1vPKZA8B5r9YAn) | 目录、正文分层保留；正文加载复核启用状态，Skill 不授予工具权限 | 不可变版本、资源层与已加载旧内容撤销 |
| [17-2 Hook 生命周期](https://alidocs.dingtalk.com/i/nodes/G53mjyd80p3KODZvCepelGK486zbX04v) | 调用前原授权、调用后分类/重复检查、下轮执行拒绝形成实际控制 | 全部必需业务断言、Hook 异常策略和读取状态治理 |
| [17-3 验证与漂移](https://alidocs.dingtalk.com/i/nodes/1zknDm0WRamL2nbvtzZz2pDz8BQEx5rG) | 本批确定性重复检测能收敛，不能据此认定推荐相关或目标未偏离 | 业务语义断言、目标漂移、误报/漏报与额外检查成本 |
| [16-5 熔断与排队](https://alidocs.dingtalk.com/i/nodes/NkDwLng8ZLyeODvXt3Y3xK5dVKMEvZBY) | 已验证外层三态熔断、半开竞争、取消和恢复；原准入/排队未被替换 | 下游细粒度依赖、持久任务恢复及业务幂等的完整演练 |
| [16-4 Token 预算](https://alidocs.dingtalk.com/i/nodes/ZQYprEoWonDwOA3lUQ6QDNby81waOeDk) | 时间与次数额度已共享；与已交付用量观测分开定位 | token/费用调用前原子预留、实际结算、模型降级和全调用成本 |

## 范围与后续

1. 期限从 `AgentLoop.openTurn` 开始，包含常规模型循环与治理内工具的等待；不包括入口准入、Session 排队。同步直达推荐可在 Loop 内旁路治理工具，定时器能发中断信号，但不强制结束该同步调用。已有推荐交付降级和 Recommend 内部 BGE/向量库降级也不自动暴露成外层熔断失败。
2. 超时是等待和取消契约，不是杀死任意 Java 代码的能力。既有 raw 执行器取消时最多等待 500ms 观察退出，客户端结果可能晚于配置期限；忽略中断的任务仍占用许可，只有真正退出才释放。治理依赖 `execute` 立即返回 Future，实际阻塞任务由工作执行器拥有。
3. 熔断采用受控依赖组连续失败计数，不是每个模型/索引端点的健康探测；取消不记录依赖成功。服务重启会重置这些内存状态。
4. 重复检查只是证据未变化的规则信号，不能覆盖查询持续变化的语义漂移，也不承担授权职责。非 JSON 结果无法生成完整摘要时保留引用差异，不猜测隐藏正文相同。
5. 按计划继续补必要业务断言、token/费用预算与路由，再推进自动安全压缩、记忆生命周期、Java RAG 查询规划及后续评测/训练。P1、P2、P5 和总体计划均未整体完成，远程验收继续保持未验证。
