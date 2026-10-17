# P1 首批：真实模型调用观测与有界 Trace 导出

日期：2026-10-18。上一批可重跑基线已提交并 push：`ba37959a`。本批不改推荐策略、Prompt、模型权重或简历。

当前代码及配置的文件指纹见 [manifest](manifest.json)，检查范围及结果见 [checks.json](checks.json)。

## 已接通的调用路径

`AgentLoop → 模型准入许可 → AgentModelCallObservation → 真实 AgentModelStreamClient → Trace / Skill Benchmark → Python model_usage 账本`。

只有拿到模型许可并真正调用客户端时，才产生 `model_call_started`。排队期间被取消不会伪造一次模型消耗。每次尝试有独立 `model_call_id`；`run_id`、`turn_id` 对应当前 Turn 的请求标识，`loop_index` 区分循环轮次。

`model_call_completed` 在 finally 中产生，区分正常完成、回答提前输出、Hook 停止、模型失败和中断。最终回答仍按既有行为立即停止上游，观测失败不会替换原异常或改变业务决策。计时使用单调时钟；首 token 仅在观察到文本 token 时记录，不把结构化工具输出时间冒充首 token。

用量保留最近一次快照，累计流式帧不相加。`usage_status` 描述普通输入/输出/总量三个字段是否齐全，缓存明细分别记录覆盖率；`usage_final` 独立描述是否已拿到最终用量：提前终止且没有最终回执时保持 false；完整非流式响应的可信 Adapter 可以明确标记最终用量。失败、缺失及不完整调用都保留在分母，未知总量为 null，同时提供已知小计、观察数量和最终快照数量。

新增观测只输出 ID、阶段、耗时、状态和允许的数值计数，不复制原始 native usage、Prompt 或工具正文。完成事件将计数放在嵌套 `usage` 中，避免旧平台把它和 `model_usage` 中间事件再次相加。公开 SSE 继续由原投影器筛选；新增观测事件不进入普通用户界面。

## 现有平台导出的保护

原 `HttpAgentTraceReporter` 每条事件创建一个虚拟线程任务且无界提交、静默忽略失败。现在使用单工作线程及有界 FIFO 队列，先生成有大小上限的序列化快照；队列满、关闭后提交或负载超限时丢弃观测，不同步等待 HTTP。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `RS_AGENT_TRACE_QUEUE_CAPACITY` | 512 | 等待队列事件数上限 |
| `RS_AGENT_TRACE_MAX_EVENT_BYTES` | 65536 | 单条 JSON 负载字节上限；排队负载最多约 32MiB，另有对象开销 |
| `RS_AGENT_TRACE_REQUEST_TIMEOUT_MS` | 2000 | 连接及读取期限 |
| `RS_AGENT_TRACE_SHUTDOWN_TIMEOUT_MS` | 3000 | 关闭时最多等待的清空时间，超时取消并记录未发送项 |

这些参数已经贯通 Spring 配置、Compose 和示例环境文件，但本轮没有远程部署。正常关闭会自动调用 reporter 的 `close()`。

`statistics()` 返回 accepted/sent/failed/dropped/oversized/pending；首次失败或丢弃输出不含载荷内容的警告。failed 包含序列化和发送失败，不能直接与 accepted 作简单恒等核算。当前是 Java 查询接口与日志，**尚未注册成运维 HTTP 接口或 Micrometer 指标**。不自动重试失败导出，避免形成无界重试风暴；语义调用记录依旧通过已有持久化路径管理，Trace 本身不作为会话权威。

## 验证证据

- Java Agent 及上游打包通过：Agent 收集 **249 项，248 通过、1 跳过**；跳过项仍为依赖本地 vLLM 的既有 smoke。
- 新增调用观测测试覆盖累计快照、首 token、提前停止、可信最终 usage、不同循环 ID、模型异常及观测 Sink 异常；扩展既有中断/准入用例，确认没有改变取消语义。
- 真实本地 HTTP 故障测试覆盖队列满丢弃、关闭前清空、超时失败、超大事件拒绝、关闭后提交和 Spring 生命周期关闭。
- 根目录部署及模型启动契约 **56 项通过**。
- Python 全门禁及 Ruff 结果见 [checks.json](checks.json)。既有 36 条工程规范问题仍未消除，见 [上一批报告](../agent-capability-baseline-20261018/README.md)。
- [完整受控 Java 联调记录](java-selfcheck.json) 包含 2 次基线与 2 次 Skill overlay 运行、原始工具/调用轨迹、Runtime 指纹和逐次账本。每个基线运行实际观察到 4 次模型尝试。HTTP 模型替身每次固定返回 **10/5/15 个合成 token 计数**，账本核对为 4×15=60；这些数字只证明协议传播、去重和最终快照处理，不能作为真实 token 消耗、模型能力或简历收益指标。

复跑顺序：先用 JDK21 对 `rs-service-agent` 执行 `package`，再设置 `RS_BENCHMARK_TEST_JAVA` 指向该 Java 可执行文件，运行 `python_agent/tests/test_skill_benchmark.py` 与 `test_agent_execution_metrics.py`。不能并行编译与读取类指纹。

## 尚未完成的 P1 范围

1. 跨 HTTP 委派的父子关联，以及模型/Prompt/Skill/数据的完整不可变版本字段。
2. 摘要、Judge、训练 rollout 等其他调用种类的观测。`attempt_scope` 明确为外层 `AgentModelStreamClient` 调用，SDK 内部若自动重试，尚不能逐个区分网络尝试；本次 `coverage_basis` 为 `observed_generation_attempts_only`，不是全系统计费账本。
3. Langfuse/OTLP Adapter、外部导出的完整脱敏策略、指标注册与持久化导出重放。
4. 现有平台汇总页仍使用旧事件口径，不作为此次最终快照账本的消费方；本批没有宣称平台已正确展示全部成本。评测报告使用新账本，并在未观察到调用时保留 unknown。
5. 本轮按仓库文档尝试 `server` 的只读 SSH 核验，8 秒连接超时；未访问到远程容器配置，也未运行真实模型或训练。

新增观测只能描述收到的调用事件；若导出队列丢弃了开始和完成事件，不能从缺失事件推断零调用。需要结合丢弃统计评估覆盖率。`ba37959a` 的基线 manifest 是那个工作快照的冻结证据，不应随着后续实现重写成当前线上配置。
