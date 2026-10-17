# 个人推荐 Agent 实现复核：主线接入与未完成边界

日期：2026-10-18。源码基线：`ed170a50dd7f6494b810605cced0d4e468d34738`。本次读取时工作区无既有修改，本文为新增研究记录。

## 结论与证据范围

**实现计划尚未完成。**近期提交主要补齐 P1 的生成调用观测、平台计量、OTLP/Langfuse 元数据导出和请求指纹。Loop、工具、记忆、压缩、RAG、训练等后续阶段仍有明确缺口；不能以“已有接口、YAML 或测试替身”替代整条产品或训练路径。实施清单仍将 P1 及 P2—P11 标为待完成，且列明阶段验收条件，见[实施计划](../superpowers/plans/2026-10-18-agent-capability-completion.md)。

本次按源码一手证据做静态调用核验，已阅读 `AGENTS.md`、`CLAUDE.md`、`CONTEXT.md` 及相关 ADR。**未重新运行测试、加载模型、训练、连接远程或读取 `.env`。**下文的“已有”指读到实现与调用，不表示本次重新证明运行效果；引用历史测试结果时单独说明。第 8 节另列本次浏览器文档对照，不从教程描述推断本项目已经实现。

| 能力 | 当前状态 | 可以确认的范围 | 尚不能确认的完成条件 |
| --- | --- | --- | --- |
| 显式 Loop / Hook | 已有基础执行，策略部分缺失 | 多轮模型—工具循环、阶段 Hook、轮数上限、失败收敛、取消 | 无进展检测、漂移检查和生产 Hook 治理策略 |
| 工具治理 | 授权 / 并发 / 取消已有；容错预算缺失 | 注册检查、Profile 复核、可重放限制、许可隔离 | 分类重试、依赖熔断 / 半开、Turn 总期限及 token / 费用原子预算 |
| Context | 外置 / 读回 / 恢复已有；自动压缩未闭环 | 工具结果外置、对话组预算裁剪、检查点读取 | 安全边界自动触发、摘要生产、完整工具配对保护、权威检查点写入 |
| 长期记忆 | Python 有基础链路；Java 有存储适配 | Python 提取 / 保存 / hydrate / 相关召回；Java 索引与正文读写 | Java 主线有效记忆注入、CAS、修改撤回失效与缓存一致性 |
| Skill / 委派 | 按需正文加载与受限 HTTP 委派已有 | 目录、load_skill、rag_agent HTTP 调用、结果外置 | 按不可变版本加载、撤销生效、通用独立 Worker 与实际采用证据 |
| RAG 查询规划 | Python 有代码；Java 主线接入不足 | Python pre-retrieval 支持、Java 候选内解释接口 | 查询规划结果驱动 Java 后续推荐请求的主线与消融 |
| SFT / GRPO | 训练脚手架 | 合成样本、资源门禁、加载模型 / LoRA、Trainer import | Trainer 实例、optimizer 更新、保存重载、当前 policy rollout、独立效果 |
| P1 观测 | 已交付局部且有历史本地验收 | 生成调用快照 / 缺失、去重账本、OTLP、请求指纹 | 跨 HTTP 父子传播、全调用种类、真实权重 / 数据版本与真实目标验收 |

## 1. Loop 与 Hook：扩展点可用，默认策略仍放行

- [AgentLoop.java:200](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:200) 真实执行有上限循环；每轮先检查中断，再派发 `BEFORE_MODEL_CALL`。失败工具数达到 2 或进入最后一轮时，设置 `final_answer_only`，见[同文件:213](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:213)；超限明确抛出异常，见[同文件:429](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:429)。这能约束探索次数，但没有比较工具、规范化参数和结果是否产生新进展。
- 工具前 Hook 可阻止、终止或改写参数，工具后 Hook 和失败 Hook 有调用位置，见[AgentLoop.java:253](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:253)、[同文件:560](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:560)。
- 生产默认 [GlobalAgentLoopHookDispatcher.java:13](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/GlobalAgentLoopHookDispatcher.java:13) 直接 `proceed()`；[RsAgentHookDispatcher.java:12](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/RsAgentHookDispatcher.java:12)、[RagAgentHookDispatcher.java:12](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/RagAgentHookDispatcher.java:12) 注入的处理器同样直接放行。本次在 Java Agent `src/main` 未找到无进展检测、滑动窗口重复调用检测或语义漂移检查的实际策略。

因此 P2 应从现有 Hook 接入治理，保留正常翻页、参数改变与结果更新的反例测试；不能直接写成“已有 LoopDetector 自愈”。

## 2. 工具：权限与资源隔离成立，未形成容错预算模块

- [AgentCapabilityToolUseExecutor.java:38](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentCapabilityToolUseExecutor.java:38) 检查注册及可用性，Capability 执行还经 Registry 复核 Profile 和 Replay-safe 限制；后者的业务边界由 [ADR-0011](../adr/0011-profiled-runtime-capability-execution.md) 与 [ADR-0005](../adr/0005-first-release-tools-must-be-replay-safe.md) 定义。
- [AgentExecutionLimiter.java:30](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentExecutionLimiter.java:30) 分别限制 active loop、model、tool、recommend。其 `timeoutMs` 用于等待许可，见[同文件:96](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentExecutionLimiter.java:96)；许可在 `finally` 释放。这是准入等待超时，不是获得许可后的执行期限，也不是 Turn 总期限。
- [StreamingAgentToolUseOrchestrator.java:103](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/StreamingAgentToolUseOrchestrator.java:103) 对提交结果使用 `allOf(...).join()`；该等待位置没有统一剩余期限或分类重试。取消会传到原始 Future，见[同文件:120](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/StreamingAgentToolUseOrchestrator.java:120)。
- [JavaNetAgentModelProviderHttpClient.java:21](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/JavaNetAgentModelProviderHttpClient.java:21) 有单次 HTTP 30 秒限制；HTTP 状态、IO、中断被包装成异常。这里未提供业务无结果 / 参数 / 授权 / 暂时故障分类，也没有依赖共享熔断及受控半开探测。其他 SDK 可能有自己的内部重试，不能据此称为统一 Agent 治理。

当前 token 账本属于观察用途；源码尚不能证明调用前原子预留、并行共享余额、实际结算和缺失 usage 保守预占。资源许可、HTTP 超时和观测 token 总量不可互相替代。

## 3. Context：自动安全压缩与恢复读取应分开

- [AgentToolResultExternalizer.java:42](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentToolResultExternalizer.java:42) 将完整大结果保存为行，再给模型预览与引用；[VirtualThreadAgentToolUseExecutor.java:141](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/VirtualThreadAgentToolUseExecutor.java:141) 可按 offset / limit 读回。该路径是真实执行，不是只有提示词约定。
- [DefaultAgentSessionCompactionService.java:32](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentSessionCompactionService.java:32) 接受外部给定边界和摘要，随后归档、存快照、替换热事件。边界校验只查事件 ID，未检查 pending tool；本次全 Java Agent `src/main` 检索 `compactBeforeMark` 仅命中接口与实现，未找到自动业务调用。
- [AgentEffectiveContextService.java:18](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentEffectiveContextService.java:18) 读取摘要 / preserved / tail，按用户消息与回答分组，在 6000 **字符**内选择；tail 只组装 user / assistant，对工具组没有完整重建。其 `truncated` 及省略数被[编排服务:307](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java:307) 使用，且[同文件:349](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java:349) 写入裁剪提示。
- [DefaultAgentTranscriptRecoveryService.java:34](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentTranscriptRecoveryService.java:34) 确实读取最新 checkpoint 及其后增量。本次未找到与自动摘要连接的生产 checkpoint 保存路径；“能读检查点”不等于“自动产生正确检查点”。

应按 [ADR-0003](../adr/0003-compaction-only-at-safe-model-call-boundaries.md) 和 [ADR-0004](../adr/0004-auditable-lossy-context-truncation.md) 补安全边界、已持久化水位、完整工具配对和写入失败行为；[ADR-0002](../adr/0002-context-checkpoint-excludes-runtime-injection.md) 仍要求恢复后重新注入当前配置。本次未重算原 32% 指标，不将其归因给尚未闭环的新机制。

## 4. 长期记忆：Python 基础能力不能直接计入 Java 产品闭环

- Python [memory/__init__.py:155](../../python_agent/rs_core/agent/memory/__init__.py:155) 有 hydrate，178 行提取，224 行相关召回；[serving/facades.py:213](../../python_agent/rs_core/serving/facades.py:213) 实际调用加载、hydrate 及保存快照。因此不应把它说成完全没有实现。
- Java [AgentMemoryIndexStore.java:9](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentMemoryIndexStore.java:9) 与 [AgentMemoryItemStore.java:9](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/AgentMemoryItemStore.java:9) 都只有 save / find；[MysqlAgentMemoryIndexStore.java:24](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/MysqlAgentMemoryIndexStore.java:24) 使用 upsert 覆盖传入版本，[ScyllaAgentMemoryItemStore.java:39](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/ScyllaAgentMemoryItemStore.java:39) 保存正文。未发现 expected-version 条件写；`version` 字段本身不构成 CAS。
- 本次追踪这两个 Store 在 Java `src/main` 的类型引用，仅找到接口、适配器与装配；没有发现提取→相关检索→有效项注入的业务消费者。[AgentSessionMemoryCapability.java:28](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentSessionMemoryCapability.java:28) 读取的是热会话事件，按 [CONTEXT](../../CONTEXT.md) 应归会话读取，而非跨 Session 的长期记忆。

因此修改、撤回、失效、操作幂等、冲突返回、旧缓存失效及可信主体范围仍需 P4 实现和验收；Python 的数量裁剪也不能替代记忆撤回协议。

## 5. Skill、委派与 RAG：已有使用入口，生命周期和查询规划待接通

- [InMemoryAgentRuntimeConfigurationService.java:185](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java:185) 向模型提供已启用 Skill 目录；[同文件:272](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java:272) 从 classpath 读取 SKILL.md；[VirtualThreadAgentToolUseExecutor.java:84](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/VirtualThreadAgentToolUseExecutor.java:84) 真正处理 `load_skill`。但它调用的 [skill(name):139](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java:139) 只检查存在，未在读取正文时检查 enabled；仅从目录过滤禁用项并不保证显式旧名称不能再被加载。现有 upsert 覆盖内存值，也不是不可变版本资产与已加载正文撤销闭环。
- [HttpAgentDelegateService.java:29](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/HttpAgentDelegateService.java:29) 仅允许 `rag_agent`，构造 query / 候选 / 预算等 payload 并发 HTTP。这是受限专用委派，不是可泛化的 Supervisor-Workers 团队；源码未显示由该入口启动独立 Java RagAgentLoop。[AgentDelegateProperties.java:26](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/config/AgentDelegateProperties.java:26) 默认指向 Recommend 的 `/agent/recommend/rag/support`。
- 该接口落到 [DefaultRecommendRagService.java:29](../../java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/DefaultRecommendRagService.java:29)：检索后按已有 candidate IDs 返回 item_support；返回值使用原 userQuery，未形成“检索辅助改写→后续 Java 推荐调用”的查询规划闭环。
- Python [adapters/rag.py:628](../../python_agent/rs_core/agent/adapters/rag.py:628) 有 query support 结构，存在规范化和安全筛选实现；[retriever.py:329](../../python_agent/rs_core/agent/rag/retriever.py:329) 有独立 query-planning 检索构建。Java Skill 当前还明确“候选存在后才使用 RAG”，见 [unclear-need-clarification/SKILL.md:27](../../java_agent/rs-service-agent/src/main/resources/agent-skills/unclear-need-clarification/SKILL.md:27)。两条路径不能拼接成已落地的 Java 主线。

P5 需先区分 Query Planning 和候选内 RAG Evidence 的领域边界，然后提供短请求不委派、长探索按需委派、版本撤销和查询消融证据。未发现的数据、权重、工具环境或采用记录不应由一个 Skill 内容哈希代替。

## 6. SFT / GRPO：当前没有真实 Trainer 执行

- [sft_runner.py:11](../../python_agent/rs_core/offline/training/sft_runner.py:11) 用合成样本、资源检查、加载模型 / tokenizer / LoRA；走到非 init 分支后，仅在 [同文件:46](../../python_agent/rs_core/offline/training/sft_runner.py:46) import `SFTTrainer`，记录类名并返回。没有构造 Dataset / Trainer、train、保存、恢复或导出。
- [grpo_runner.py:12](../../python_agent/rs_core/offline/training/grpo_runner.py:12) 同样使用合成样本及预先计算的奖励；[同文件:48](../../python_agent/rs_core/offline/training/grpo_runner.py:48) 仅 import `GRPOTrainer` 并返回类名。没有当前 policy 组采样、真实工具环境 rollout、生成 mask、优化器更新及保存。
- [data_contracts.py:126](../../python_agent/rs_core/offline/training/data_contracts.py:126) 将简单样本转成 system / user / assistant messages；该转换本身不是实际聊天模板编码或 assistant-only loss mask。需要在 P9 真正交付标签检查，在 P10 交付在线策略采样与奖励诊断。

这两条 runner 在当前源码下都不能称作“真实 SFT / GRPO 已训练”，也不能据此归因推荐满意度提升。本次没有运行重路径，资源门禁和远端训练要求继续适用。

## 7. 本轮新增 P1 能力如何定位

真实生成请求已有观察入口，见 [AgentLoop.java:642](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:642)；平台 [AgentUsageLedger.java:16](../../java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/impl/AgentUsageLedger.java:16) 只按 canonical 调用事件建账，并区分 final、缺失与冲突；[HttpAgentTraceReporter.java:150](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/HttpAgentTraceReporter.java:150) 提供发送 / 失败 / 丢弃统计。它们是确切增量，但不自动完成执行预算与全服务观测。

历史报告记录了 Java、Python、前端、受控 HTTP 和浏览器检查通过情况，见 [OTLP/账本验收](../reports/agent-otlp-and-usage-20261018/README.md)、[请求指纹验收](../reports/agent-request-fingerprints-20261018/README.md)。这些是先前提交的本地验收材料，本次没有重跑；报告本身也明确替身不代表真实模型效果、生成观察不包括全部 Judge / 摘要、配置别名和哈希不能证明远端权重 / 数据、跨 HTTP 父子传播仍缺失。P1 不应因已有 Langfuse 配置而提前关闭。

建议后续仍按计划顺序推进：先补观测关键关联及 P2 可执行治理，再补安全压缩、记忆与 Java RAG；冻结评测及 Prompt 基线后进行真实训练。简历中的机制与收益分别以接入证据、运行报告和同条件对照为依据。

## 8. 浏览器学习文档中途对照

本次通过现有浏览器阅读会话重新打开下列 22 个章节，核对页面可见的课程目标、导言和首节内容。网页当前可读取的段落并不覆盖各章后续全部细节，因此这是中途主题核验，**不是重新逐字通读 22 章或最终验收**。原来的学习笔记只作查漏，未将其后续设计建议冒充本次新读取的原文。未下载整套教程或保存原文副本。

表中“文档关注”是简要归纳；“本项目对照”来自前述源码核验、已有报告及实施清单，二者的证据分开。

| 章节与来源 | 文档关注 | 本项目对照 |
| --- | --- | --- |
| [03-0 按需派发](https://alidocs.dingtalk.com/i/nodes/np9zOoBVBYKQm4g0fe4enRjlW1DK0g6l) | 派发收益取决于独立输入、并行和上下文隔离 | 受限委派已有；独立 Worker、共享预算与收益对照未完成，见第 5 节 |
| [05 上下文治理](https://alidocs.dingtalk.com/i/nodes/X6GRezwJlArL250wi0jm4BB78dqbropQ) | 分层控制输出、缓存和摘要，保护当前条件 | 外置读回已接入；自动安全压缩与摘要生产待补，见第 3 节 |
| [06 长期记忆](https://alidocs.dingtalk.com/i/nodes/4lgGw3P8vRpPz59DFZDZQa6N85daZ90D) | 偏好跨会话读取、修改和删除后的有效性 | Python 基础链路存在；Java 使用、版本冲突与撤回闭环待补，见第 4 节 |
| [08 Rubric](https://alidocs.dingtalk.com/i/nodes/dxXB52LJqnM0N5xEUZAZQwpd8qjMp697) | 分项规则、人工复核和训练奖励分开验证 | 固定工程场景与规则已有；人工校准及满意度证据仍待 P7 |
| [08-1 SFT](https://alidocs.dingtalk.com/i/nodes/ZQYprEoWonDwOA3lUQ6QqbXj81waOeDk) | 工具轨迹、实际标签掩码和独立检查点评测 | Trainer 更新、标签检查、保存重载未实现，见第 6 节 |
| [08-2 Agentic RL](https://alidocs.dingtalk.com/i/nodes/QPGYqjpJYr3Yd94kIKEKZLP78akx1Z5N) | 当前策略重新采样、环境回放及奖励投机检查 | GRPO 仍为脚手架；教程主要展开 GSPO，不能混用算法与成绩 |
| [13-1 RAG](https://alidocs.dingtalk.com/i/nodes/7dx2rn0JbYBAo2X7fNvN2obdVMGjLRb3) | 按资料、切块、召回、去重和排序定位证据遗漏 | Python 有检索实现；Java 查询规划与后续推荐消费待接通，见第 5 节 |
| [13-2 推荐评测](https://alidocs.dingtalk.com/i/nodes/Exel2BLV5zwPpkRjhp5pmkdRJgk9rpMq) | 固定商品、查询与标注，分别测候选和最终排序 | 已有算法产物与历史报告；当前路线核验、固定候选预算消融仍按 P5 验收 |
| [14 主 Agent 组织](https://alidocs.dingtalk.com/i/nodes/LeBq413JAw62YKDRCzQzBY7zWDOnGvpb) | 按依赖执行、核对 Worker 结论并延续任务 | Loop 与工具组织已有；当前专用 HTTP 接口不等于完整多 Worker 架构 |
| [16-2 推理部署](https://alidocs.dingtalk.com/i/nodes/wva2dxOW4YPD3NrMfYqYBLN7Vbkz3BRL) | 兼容性、混合负载、显存和分阶段时延 | 部分量化、缓存与批推理有原配置及基准；本轮未核验远端或新增单因素结果，见 P8 |
| [16-3 观测](https://alidocs.dingtalk.com/i/nodes/DnRL6jAJMGp7P2mlh9k9X4xxWyMoPYe1) | 关联生成、子任务、工具、摘要和评分，避免漏计 | 生成观测、去重、覆盖率和 OTLP 已交付；摘要/Judge、跨 HTTP 关联及真实目标待补，见第 7 节 |
| [16-4 预算](https://alidocs.dingtalk.com/i/nodes/ZQYprEoWonDwOA3lUQ6QDNby81waOeDk) | 整任务累计额度与并发预留、结算及降级 | 当前是观测账本；原子预留、共享预算和受控路由待 P2 |
| [16-5 故障与排队](https://alidocs.dingtalk.com/i/nodes/NkDwLng8ZLyeODvXt3Y3xK5dVKMEvZBY) | 熔断、队列、防重跑与业务幂等各管一层 | 分层准入和取消已有；分类重试、熔断与半开未闭环，见第 2 节 |
| [16-6 安全与发布](https://alidocs.dingtalk.com/i/nodes/Amq4vjg890Bn5z3pIxjxP9YmJ3kdP0wQ) | 外部内容、资源归属、流式检查与退出恢复 | 已有权限和展示投影基础；攻击回归、完整 drain/恢复与目标部署待 P2/P6/P11 |
| [17-1 Harness](https://alidocs.dingtalk.com/i/nodes/OG9lyrgJPzZXGaRKhl2lXPv0WzN67Mw4) | 围绕模型组织执行、状态和验证，按失败层定位 | Runtime 主干已有；各治理策略和连续验收仍需落实，不以组件数量判完成 |
| [17-2 Hook](https://alidocs.dingtalk.com/i/nodes/G53mjyd80p3KODZvCepelGK486zbX04v) | 检查位置、执行顺序、拦截和观测故障分离 | Hook 调用真实存在，但默认处理器放行，见第 1 节 |
| [17-3 漂移](https://alidocs.dingtalk.com/i/nodes/1zknDm0WRamL2nbvtzZz2pDz8BQEx5rG) | 参数合法、业务语义与连续目标分别验证 | 格式/授权基础已有；无进展与语义漂移策略待 P2，不能用 maxLoops 代替 |
| [17-4 动态权限](https://alidocs.dingtalk.com/i/nodes/y20BglGWO2z0XZ7EUvEvG3ro8A7depqY) | 权限、批准对象、当前版本及重复执行分层检查 | Capability/Profile 复核已有；长期记忆修改的版本/幂等待补。个人项目不为照搬案例增加交易工具 |
| [18-3 Prompt 版本](https://alidocs.dingtalk.com/i/nodes/nYMoO1rWxaz265gMt9M90yoKV47Z3je9) | 保存版本内容、对照、发布和会话绑定 | 请求指纹可识别差异；不可变资产、A/B、回滚与撤销仍待 P7/P11 |
| [18-4 策略沉淀](https://alidocs.dingtalk.com/i/nodes/G53mjyd80p3KODZvCepel3Nv86zbX04v) | 带条件与反例的方法，分别验证展示、采用和收益 | 现有 Skill 不自动等于策略学习闭环；采用与效果证据待 P11 |
| [19-3 缓存友好](https://alidocs.dingtalk.com/i/nodes/ZQYprEoWonDwOA3lUQ6Qq77r81waOeDk) | 稳定前缀、最新状态与摘要事实分别治理 | 稳定输入布局已有；完整摘要/回查成本与冷热消融仍待 P3/P8 |
| [19-5 Skill](https://alidocs.dingtalk.com/i/nodes/1DKw2zgV2Pxk3MmDtv1vPKZA8B5r9YAn) | 目录、正文与资源分层读取，版本检查不授新权限 | 目录/正文已接通；禁用后的显式加载与已加载内容撤销存在缺口，见第 5 节 |

教程自身也区分已接入能力与实验方案：08、08-1、08-2 的可见导言明确说明训练流水线和成绩尚未完成；13-1 将 Hybrid/精排列为实验，并未说当前知识工具已接通。因此采用它们的方法时仍要以我们自己的代码、真实更新与运行证据验收，不能复制项目名或配置就登记为完成。

## 9. 对照后的优先事项与最终验收

这次检查没有修改项目代码或简历，也没有把任何待完成项改成勾选。

1. 先修明确的 Skill 禁用加载缺口，测试目录隐藏后显式旧名称加载被拒、正常加载不受影响。已进入上下文的旧正文撤销另作生命周期验收，不能用这一个检查替代。
2. 继续 P1 关键关联与 P2：在现有 Hook/执行入口补无进展、失败分类、期限、依赖熔断和共享预算，并验证实际拒绝/恢复分支。
3. 完成 P3/P4/P5 的产品路径：自动安全压缩与检查点生产、长期记忆修改撤回、RAG 查询规划驱动推荐。
4. 用冻结场景比较 Prompt，再实际执行 SFT 与 GRPO；验证 labels、参数更新、保存重载和独立留出效果。

最终再回到文档逐条复核时，每项至少应能指出：实际入口、持久化/恢复或训练产物、正常与失败用例、可重复的记录，以及仍不覆盖的条件。某模块可运行、工程测试通过和业务指标改善是三种不同的完成证据。
