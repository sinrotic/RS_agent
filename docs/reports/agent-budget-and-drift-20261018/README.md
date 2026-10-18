# Turn 预算与语义漂移检查验收

日期：2026-10-18。基于 `5364ab56`。本批先接通真实模型调用的预算预留与结算，再补语义复核与执行收敛。完成的是 Java Spring AI 主线的工程能力；真实模型质量校准、远程部署、自动摘要、远程 Worker 与模型降级仍按计划继续。

## 接入与预算契约

`AgentLoop → AgentReasoningPolicy.openTurn → AgentInterruptContext.budget → SpringAiAgentModelStreamClient 准备实际 system/user/tools → AgentBudgetCall → AgentTurnBudget.reserve → SDK HTTP → usage → settle → model_budget_completed`。

预留是执行门禁，不经过会吞异常的指纹观测回调。输入以准备后的 JSON UTF-8 字节数加 padding 作保守代理，输出以实际发送的 max_tokens 预留，并受服务端每调用上限约束。代理不是 tokenizer 精确计数，也不能证明任意供应商的隐藏输入开销；实际回执超预留时保留真实消耗、标记 breached 并阻止后续支出，不把账本强行截成上限。

一次预留同时检查 `已结算 + 在途/未知占用 + 新预留` 的 token、USD 和模型调用次数，检查与增加占用在同一锁内完成。每次 SDK 调用消耗一个调用名额；回执 token 变小不会退还调用名额。预算不读取用户 context 中的额度或价格。

| 状态 | 结算行为 |
| --- | --- |
| 传输正常结束且 prompt/completion 为合法整数，total 若提供则相符 | 用最终实际 token 替换预留，释放已确认未用的额度 |
| 显式最终 usage 回执 | 即使稍后业务失败，也允许按合法最终用量结算 |
| usage 缺失、部分、非法、互相矛盾，或提前取消且未获最终回执 | 不退款；保留或提高保守占用，实际用量保持未知 |
| 相同调用重复的最终回执 | 幂等，不重复计费；不一致最终回执标记冲突并拒绝新预留 |
| Turn 已关闭后迟到的合法最终回执 | 可以结算已有预留，不能重新预留或复活 Turn |

费用用 BigDecimal 计算配置费率估值：`(prompt × 输入USD/百万 + completion × 输出USD/百万) / 10^6`。只对显式匹配模型的费率计价；未知定价不填 0。最大 USD 为 0 表示关闭费用限制。启用费用限制必须同时提供 `pricing-configured=true`、模型名和两种费率，否则启动失败。当前对 prompt 按完整输入费率估值，未应用缓存折扣，也没有供应商账单对账，不称为实际财务账单。

在真实 HTTP 503 故障中发现：单次 `OpenAiChatOptions.maxRetries(0)` 没有覆盖 SDK 的全局重试，实际仍产生 4 次请求。因此 application.yml 显式设置 `spring.ai.openai.chat.max-retries=0`，预算启动时再次校验；修复后同一故障只发 1 次 HTTP，未知消耗保留预留。未来显式重试必须再次预留，不允许隐藏地复用一个名额。

`context.fork("worker" / "summary" / "drift_check")` 传播同一个账本及父中断信号。主生成与本批真正接入的语义复核共享 token/费用/次数，且复核也经过模型许可。真实 HTTP 验证了 worker 标签的受控模型调用，但这不代表已有远程 Worker/自动摘要产品路径已经补齐。Python/self-hosted Adapter 尚无可核验的下游输出上限和完整 usage 协议，受控预算开启时明确返回 `MODEL_BUDGET_ADAPTER_UNSUPPORTED`；四/五参数入口均不静默丢失 context。

## 语义漂移与执行效果

当前用户消息作为本 Turn 的目标；近期三次搜索只作过程背景，不覆盖用户的新目标。规则覆盖背包、帐篷、鞋、键盘、手机、笔记本六个类目，跨类目切换触发复核；另按搜索次数周期抽查。因此同一类目内、查询一直变化的漂移也有复核机会，不能用重复检测代替。

复核使用同一模型 Adapter 的独立调用：专用系统提示词、无工具、`tool_choice=none`、JSON 响应、默认最多 256 输出 token / 5 秒。用户目标、近期查询及候选查询作为 JSON 数据，不继承执行工具权限。返回必须恰好包含 decision/query/reason，查询必须与当前被检查查询一致，判定与理由枚举必须配套；多余字段、替换查询或无法解析均为 UNKNOWN。

| 结果 | 执行行为 |
| --- | --- |
| ALIGNED | 可以继续进入原工具治理、Capability 授权和资源许可，不因此获得新权限 |
| DRIFT | 拒绝当前工具，提示围绕当前目标修正查询或依据已有证据结束 |
| UNKNOWN / NOT_REVIEWED | 不计为语义通过；跨类目可疑动作无法核验时拒绝，普通未抽中/证据不足保留明确状态 |
| 累计两次被拒绝 | 只允许最终回答，同一段模型流及后续轮的新工具均被执行分支拒绝 |

模型可以在达到限制前修正查询；新 Turn 不继承旧目标和计数。预算不足、复核超时/异常、非法响应均不能登记为 ALIGNED。复核失败不等于已经判定漂移，误拦和语义误报分开统计。

内部事件 `drift_check_completed` 只含状态、规则信号、查询/目标摘要与耗时，不外发完整内容。复核的 `model_call_started/completed` 使用独立 ID 与 `call_kind=drift_check`，计入既有平台及 Python 账本；coverage basis 改为 `observed_model_client_invocations_only`，不夸大成全系统覆盖。公开 SSE 投影保持过滤预算/复核内部事件。

## 配置

以下均为已同步 application.yml、Compose 和受版本控制示例的启动默认值，不是远程生效配置。

| 环境变量 | 默认值 |
| --- | --- |
| `RS_AGENT_MODEL_BUDGET_ENABLED` | true |
| `RS_AGENT_TURN_MAX_TOKENS` / `RS_AGENT_TURN_MAX_MODEL_CALLS` | 131072 / 32 |
| `RS_AGENT_CALL_MAX_OUTPUT_TOKENS` / `RS_AGENT_INPUT_PADDING_TOKENS` | 4096 / 512 |
| `RS_AGENT_TURN_MAX_USD` / `RS_AGENT_PRICING_CONFIGURED` | 0 / false |
| `RS_AGENT_PRICED_MODEL` | 空；不能推断实际权重版本 |
| `RS_AGENT_INPUT_USD_PER_MILLION` / `RS_AGENT_OUTPUT_USD_PER_MILLION` | 0 / 0；pricing-configured=false 时视为未知定价 |
| `RS_AGENT_DRIFT_ENABLED` / `RS_AGENT_SEMANTIC_REVIEW_ENABLED` | true / true |
| `RS_AGENT_DRIFT_REVIEW_EVERY` / `RS_AGENT_MAX_DRIFT_VIOLATIONS` | 3 / 2 |
| `RS_AGENT_DRIFT_REVIEW_MAX_TOKENS` / `RS_AGENT_DRIFT_REVIEW_TIMEOUT_MS` | 256 / 5000 |

## 验收证据

机器结果、测试方法及源文件/编译指纹见 [checks.json](checks.json)、[behavior-tests.json](behavior-tests.json) 与 [manifest.json](manifest.json)。本地只使用受控模型响应和轻量测试，未加载正式模型。

- 全量 Java package：798 项收集，797 通过，1 项既有本地 vLLM smoke 跳过；14 个 Reactor 项目构建成功。其中 Agent 308 项收集、307 通过、1 跳过；本批新增 25 项预算/语义回归。
- 预算回归：并发争用同一余额、精确费用计算、实际结算退款、未知/非法/非最终回执、重复与冲突、迟到回执、真实 HTTP 输出上限、拒绝先于网络、父子同账、取消、SDK 隐藏重试，以及不支持 Adapter 的拒绝。
- 漂移回归：必要属性、多目标、否定需求、用户主动切换、同类目漂移、UNKNOWN/未抽样、纠正后继续、超时取消、观测故障不放行、同流执行拒绝与最终回答。真实 HTTP 验证复核请求无工具、状态解析、usage 同账及余额不足时不请求供应商。
- 根部署/启动契约 56 项通过；最终打包后 Java/Python 联调、用量账本和漂移评测共 50 项通过，其中独立 Python 漂移评测新增 8 项。CI 的 unit/smoke/serving 选择集共 126 个文件，1279 通过、3 跳过；显式使用 JDK21 和工程替身密钥，不加载正式模型。Ruff 全 CI 范围及本批新脚本通过。离线 CLI 另以空复核记录验证 10 项均保持 NOT_REVIEWED，没有生成模型质量成绩。
- 前端没有改动，未重跑；其他 Java 服务和平台账本由全量构建回归。未重新执行已知 36 条存量规范问题的全仓规范扫描，也没有将它们登记为修复。

离线入口：[agent_drift_evaluate.py](../../../python_agent/scripts/evaluation/agent_drift_evaluate.py)。从 `python_agent` 运行：

```powershell
python -m scripts.evaluation.agent_drift_evaluate --scenarios benchmarks/skill_benchmark/drift-scenarios-v1.json --reviews <实际复核JSONL> --output <报告JSON>
```

每个 review 至少包含 `scenario_id/review_status/blocked`，可附实际 `latency_ms/model_calls`。场景标签单独提供，拒绝未登记 ID 和重复结果；usage 缺最终回执不能退款或当作 0。报告分开给出已复核混淆矩阵、全标注漂移检出率、UNKNOWN/未复核、误拦、未核验拦截、检查用量及耗时覆盖率。10 个场景是独立手工编写的工程样例；没有正式模型预测/人工校准，不能据此宣称准确率、误报率或推荐满意度提升。

## 文档对照与未完成范围

本批重新在浏览器阅读以下两章可见目标、导言和首节；没有取得后续全文，不称为整章/整套教程的最终验收，也没有下载教程副本。以下是短摘要与本项目证据映射。

| 来源 | 本批实现与测试 | 仍待补齐 |
| --- | --- | --- |
| [16-4 预算与路由](https://alidocs.dingtalk.com/i/nodes/ZQYprEoWonDwOA3lUQ6QDNby81waOeDk) | 任务共享额度、调用前原子预留、最终结算；显式区分费用估值、窗口容量和未知占用 | tokenizer/供应商账单校准、实际摘要/远程 Worker 协议、已验证模型档位降级与提前收尾额度 |
| [17-3 验证与漂移](https://alidocs.dingtalk.com/i/nodes/1zknDm0WRamL2nbvtzZz2pDz8BQEx5rG) | 独立语义复核、规则抽查、UNKNOWN、误报/漏报入口及执行层纠正/收敛 | 更全面的目标/证据抽取、商品身份与硬约束断言、真实模型人工校准及额外成本/质量消融 |

本批仍有明确边界：预算是当前受控 Loop 的内存事实，未建立崩溃后的持久计费恢复；迟到结算是账本接口契约，尚未接入供应商异步账单回推，退出快照允许仍有未知占用。非响应中断的实际调用占用仍保留到退出；并发账本不等于已完成并发服务容量评测。语义复核不是防提示注入或事实正确的完整证明，规则只作抽查信号，未抽中的调用仍可能漂移。当前使用同一模型档位，复核会增加成本与延迟；模型许可不足也可能产生 UNKNOWN，需要后续负载与阈值消融。P2.5 全调用覆盖、P2.6 降级、P2.7/P2.8、真实质量与远程验收继续保持未完成。
