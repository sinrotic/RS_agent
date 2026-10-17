# Agent 能力落地：官方机制核验

核验日期：2026-10-18。

用途：为钉钉学习文档的阅读笔记和项目改进方案补充官方一手依据。本文是独立核验摘要，不是钉钉文档的原文摘录，也不代表项目已实现这些机制。未修改项目代码或简历。

“官方说明”仅概括对应来源；“项目验收建议”是结合项目提出的设计与验证建议。每个来源正文摘要控制在 150 字内，不逐字引用原文。版本相关参数须以项目实际依赖版本复核。

## 一、前述八项机制

### 1. 上下文工程与压缩

**官方说明：**可用轻量引用按需读取；压缩需保留决策、未解决问题及必要细节，先保证召回再去冗余；长期笔记与子 Agent 摘要适合不同任务。

**项目验收建议：**用固定长对话比较 token、约束保留及成功率；额外校验工具调用与结果配对。安全压缩边界需自行设计。

来源：[Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

### 2. Prompt Cache 与稳定前缀

**官方说明：**静态内容置前；命中要求前缀完全一致。工具定义变化会影响后续缓存；缓存读取 token 仍属于总输入。

**项目验收建议：**稳定系统提示与工具序列化顺序，动态信息置后；分别统计总输入、缓存读取与 TTFT，独立消融压缩和缓存。

来源：[Claude Platform — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

### 3. Sandbox 与工具授权边界

**官方说明：**Claude Code 的 Sandbox 约束 shell 及子进程的文件和网络访问；文件工具、MCP、Hook 不自动处于同一边界，另受权限机制管理。

**项目验收建议：**测试越界访问、子进程与回收；工具入口另校验授权。Worktree、隐藏 Schema 都不能替代执行隔离。

来源：[Claude Code — Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing)

### 4. Langfuse 链路数据模型

**官方说明：**Session 聚合多轮 Trace；Trace 包含嵌套模型、工具、检索 Observation。后台批量上报；短进程退出前需 flush。

**项目验收建议：**关联会话、轮次、任务及版本；注入失败、取消与跨线程调用，核对父子关系、错误及耗时完整性。

来源：[Langfuse — Core Concepts](https://langfuse.com/docs/observability/data-model)

### 5. SFT 的助手输出损失掩码

**官方说明：**`assistant_only_loss=True` 只计算会话数据中助手部分的损失，依赖聊天模板提供 generation 掩码；部分模型自动适配。

**项目验收建议：**检查实际 batch 的 labels，验证系统、用户及工具返回已屏蔽；复核助手工具调用和截断，不推断模型模板天然兼容。

来源：[Hugging Face TRL — SFT Trainer](https://huggingface.co/docs/trl/sft_trainer)

### 6. GRPO 的相对优势与奖励设计

**官方说明：**同一提示生成多条候选，以奖励计算组内相对优势；标准差归一化可能产生难度偏差。当前 TRL 默认 `beta=0`，不启用 KL 项。

**项目验收建议：**记录奖励分项、组内方差及长度；用留出集比较提示词、SFT、GRPO，检查奖励投机，并锁定配置版本。

来源：[Hugging Face TRL — GRPO Trainer](https://huggingface.co/docs/trl/grpo_trainer)

### 7. vLLM Prefix Cache 的收益范围

**官方说明：**共享前缀可复用 KV，跳过重复计算；主要节省 prefill，不减少 decode。前缀不共享或输出较长时收益有限。

**项目验收建议：**固定输入输出口径，分别测冷、热缓存及并发，记录命中、TTFT、TPOT 和总耗时；不能直接归因原有整体收益。

来源：[vLLM — Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/)

### 8. 结构化输出与约束解码

**官方说明：**支持 JSON Schema、正则、枚举及文法等生成约束；接口随版本变化，新版已移除旧 `guided_*` 字段。

**项目验收建议：**按实际版本适配；分别统计解析、Schema 合规、业务正确及调用成功率。格式约束后仍检查商品、参数和权限。

来源：[vLLM — Structured Outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)

## 二、补充核验：工具治理与可信评测

### 9. 工具协议生命周期与超时

**官方说明：**MCP 经初始化协商再运行；请求应设超时，超时后通知取消并停止等待。即使收到进度通知，也应有最大超时。

**项目验收建议：**区分连接、单次调用和整轮预算；注入持续进度但不结束的工具，验证总期限、取消传播、资源释放和迟到结果处理。

来源：[MCP 2025-11-25 — Lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)

### 10. 工具错误、重试与循环预算

**官方说明：**LangChain 将工具错误处理、指数退避重试、模型调用限制与工具调用限制分开；重试可配异常类型、次数、抖动及耗尽后的行为。

**项目验收建议：**先分类暂时失败、参数错误与拒绝授权；只重试安全操作，统一总预算，验证幂等及多层重试放大。

来源：[LangChain — Prebuilt middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)

### 11. 熔断与并发隔离

**官方说明：**熔断器以最小样本及滑窗统计失败、慢调用，按关闭、打开、半开转换。滑窗大小不限制并发，并发控制需 Bulkhead 等机制。

**项目验收建议：**按工具或下游隔离熔断状态，测试半开探测及恢复；单独设置超时、并发限额和拒绝指标，避免误将业务拒绝算故障。

来源：[Resilience4j — CircuitBreaker](https://resilience4j.readme.io/docs/circuitbreaker)

### 12. Judge 校准与评测环境隔离

**官方说明：**LLM Judge 应与人工专家校准，可按维度评分并允许未知；每次试验需清洁环境，共享状态或前次 Git 历史会虚增成绩。

**项目验收建议：**建立人工标注校准集，检查各维度分歧；固定 Rubric 与版本，重置记忆和环境，区分回归集与能力测试集。

来源：[Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

### 13. 训练、调参与最终评测分离

**官方说明：**需区分训练、超参调优和最终评测数据；在同一划分上训练和评测会误表征泛化效果，测试集应尽量反映实际使用数据。

**项目验收建议：**按用户或完整会话分组切分，检查相似轨迹跨集合重叠；最终测试不参与提示词选择、训练筛选或奖励调参。

来源：[Hugging Face Evaluate — Considerations for model evaluation](https://huggingface.co/docs/evaluate/considerations)

## 三、对项目方案的解释边界

- 上述资料证明机制的设计依据，不证明本项目的实现状态或收益；现有功能应由代码、配置和实验记录另行确认。
- 缓存命中与输入压缩是两项指标；格式遵循、业务正确、工具授权和推荐满意度也应分别评估。
- 取消通知或客户端停止等待不自动证明底层任务终止，更不等于副作用回滚；需要项目层面验收。
- 重试、超时、熔断、并发隔离各自解决不同问题，应通过故障注入验证组合行为。
- 文中数据切分粒度、工具配对边界、幂等检查及故障注入均是项目建议，不能当作对应来源的原文结论。
- 建议先建固定评测与 Trace，再做工具治理、上下文和记忆优化，最后推进 SFT、GRPO；每阶段保留基线、消融和回归记录。
