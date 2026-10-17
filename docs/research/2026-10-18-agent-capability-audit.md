# RS_agent 简历能力源码审计（阶段结论）

日期：2026-10-18。只读对象：`D:/sinrotic_code/python_project/summer/RS_agent`，读取时 HEAD 为 `f3287905`。工作区可能包含未提交改动，行号对应本次读取的工作区内容。

已阅读该仓库 `AGENTS.md`、`CLAUDE.md`。本次仅检索、阅读源码和配置；未加载模型、未执行测试、未修改该仓库。本文原先保存在简历仓库，现随实施计划复制到项目；原审计基于提交前工作区，项目基线已保存为 c5d5b597。源码行号作为阅读定位，功能状态仍须按计划重新验证。

## 口径与关键结论

- **已实现**：看到了具体方法体及相关调用；不代表本次验证了部署、性能或正确性。
- **部分实现／脚手架**：有存储、接口或准备流程，但目标闭环尚未在所查入口成立。
- **仅设计**：有明确 ADR 约束，但未查到对应完整执行路径。
- **本次未找到**：限于列明的目录与检索，不等于全仓不存在，更不排除远端、未提交材料或其他项目有实现。

最需要纠正的判断：**混合 RAG、Python 长期记忆基础链路、Hook 接入和在线 Judge 接口确实存在；完整记忆生命周期、安全边界自动压缩、Langfuse、实际 QLoRA SFT／GRPO 训练不能由现有类名或配置直接推出。** Java 服务和 Python Agent 是两套路径，不能把各自局部能力拼成已贯通的一条链路。

## 1. Agent 架构、Skill 与工具编排

**已实现：显式循环、阶段 Hook、可终止的工具循环及按需 Skill。**

- [AgentLoop.java:200](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:200)：循环上限来自 Profile；每轮检查中断，进入 `BEFORE_MODEL_CALL` 后发起模型流。213–219 行累计失败工具达到阈值时转为仅最终回答，428 行对超限明确失败。
- [AgentLoop.java:253](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:253)：执行前 Hook 可终止、阻止或改写工具参数；559 行派发失败 Hook，583 行派发执行后 Hook。
- [VirtualThreadAgentToolUseExecutor.java:84](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/VirtualThreadAgentToolUseExecutor.java:84)：真实处理 `load_skill`；141 行处理 `read_tool_result_lines`；不是只有提示词中的工具名称。

**部分实现：Hook 扩展点存在，不等于治理策略已经启用。**

- `GlobalAgentLoopHookDispatcher.java:13` 返回 `proceed()`；`RsAgentHookDispatcher.java:12`、`RagAgentHookDispatcher.java:12` 所装入的处理器也直接 `proceed()`。本次未在 Java Agent 生产目录发现 LoopDetector、滑窗熔断器的实际实现。
- `AgentExecutionLimiter.java:30` 开始构造并管理 active loop、model stream、tool、recommend 等不同许可；101 行后有超时准入及取消检查。这是并发准入治理，不能直接称为工具执行超时或熔断。

## 2. 推荐与 RAG

**已实现：词法＋向量证据检索、查询规划检索入口及配置。**

- [hybrid.py:24](../../python_agent/rs_core/agent/rag/hybrid.py:24)：`HybridCandidateRetriever` 可注入词法、向量后端；39 行进入 retrieve，56 行调用词法检索，71–72 行取向量证据并融合；具备实际融合和后端失败回退代码。
- [elasticsearch_bm25.py:53](../../python_agent/rs_core/agent/rag/elasticsearch_bm25.py:53)：独立 `ElasticsearchBM25QueryPlanningRetriever`，对查询检索商品信息并标记 `query_planning` 范围；与限制在候选商品集合内的解释证据检索分开。
- `python_agent/configs/serving/online_service.local_milvus.yaml:84` 配置 BM25 回退；91 行配置 BM25 权重；另有 Milvus 向量相关配置。

**范围限制：**上述证明有混合检索实现，不证明每个部署配置都实际使用该路径。本次没有进一步复核三塔训练、全部召回源和精粗排链路，不能据此对整个推荐系统做完整验收。

## 3. 上下文工程、外置结果与压缩配对保护

**已实现：大工具结果外置及按需读回。**

- [AgentToolResultExternalizer.java:17](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentToolResultExternalizer.java:17)：限制内联行数、字符数与总工具结果消息大小；139 行构造引用、预览及读回工具。`VirtualThreadAgentToolUseExecutor.java:226`、229 行真实调用 externalizer。

**已实现但范围较窄：按标记归档，以及恢复时按对话组裁剪。**

- [DefaultAgentSessionCompactionService.java:32](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentSessionCompactionService.java:32)：接受外部给定的 `compactBeforeEventId`、`summaryPayload`，查边界后归档、保存快照并替换热事件。59 行仅查事件 ID；没有验证该事件是否处于无未完成工具调用的安全边界。
- [AgentEffectiveContextService.java:18](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentEffectiveContextService.java:18)：从 checkpoint、保留项和增量事件恢复可见消息；33 行开始以用户消息及回答分组，在 6000 字符预算内选择，保留摘要并报告省略数。这里不是 token 预算，也没有重建完整工具调用消息组。
- Python `rs_core/agent/context/__init__.py:113` 构造近期对话与归档摘要，另有工具与 RAG 文本预算。这是实际上下文整理代码，不能等同于 Java 安全压缩状态机已贯通。

**仅设计／未证实接入：自动安全边界压缩与 TOOL_USE／TOOL_RESULT 配对保护。**

- [ADR 0003:3](../../docs/adr/0003-compaction-only-at-safe-model-call-boundaries.md:3) 明确要求模型调用前、事件已持久化且无未完成工具调用时压缩，不拆开调用与结果；ADR 0004 还要求按完整语义组裁剪并审计。
- 在 `java_agent/rs-service-agent/src/main` 检索 `compactBeforeMark` 仅命中接口与实现，未见业务调用；检索 `checkpointStore.save`、`transcriptCheckpointStore.save` 未命中。本次不能证明存在自动触发、摘要生成、检查点写入及恢复的完整闭环。
- 本次没有复算简历的 32% 指标，不能把它直接归因于尚未证实的安全边界策略。

## 4. 长期记忆生命周期与会话恢复

### Python：已有跨会话记忆基础链路

- [memory/__init__.py:142](../../python_agent/rs_core/agent/memory/__init__.py:142)：根据配置选内存或 JSON 存储。155 行 hydrate 将历史约束合入当前会话；163 行从会话创建长期快照；178 行起提取喜欢、黑名单、偏好类别、关键词、价格等条目。
- [memory/__init__.py:224](../../python_agent/rs_core/agent/memory/__init__.py:224)：按查询词项、会话信息和历史商品给条目打分并截取前若干项。332 行按稳定 entry_id 构造更新，357 行以置信度决定同 key 覆盖。不是向量记忆检索，也不是完整冲突仲裁。
- [serving/facades.py:218](../../python_agent/rs_core/serving/facades.py:218)：实际 hydrate；224 行保存长期快照，说明并非只有独立工具函数。

### Java：会话读取及索引／正文存储存在，生命周期业务闭环不足

- [AgentSessionMemoryCapability.java:28](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentSessionMemoryCapability.java:28) 校验 session_id 后读取热事件并返回。它是会话读取能力，不是跨会话偏好提取与更新。
- `MysqlAgentMemoryIndexStore.java:24` 有索引快照 upsert；`ScyllaAgentMemoryItemStore.java:39` 有正文 save，68 行按 ID 查询；`AgentMemoryItem.java:6` 包含 status、sourceSessionId、version、contentHash 等字段。
- 索引 save 直接覆盖传入 version，不是 CAS；正文存储也是传入版本。本次在 Java main 的相关类型引用中，主要看到适配器与装配，未发现提取→相关检索→注入→冲突更新的完整使用链。

**本次未找到：**这些已查路径中的显式记忆删除／失效 API、TTL 清理、负向记忆冲突策略、版本 CAS 与 Java 端跨会话记忆完整注入。Python 的数量裁剪不应描述为完备失效机制；Java 有 version 字段不应描述为已实现版本一致性治理。

### 会话恢复：有真实持久化边界与增量恢复实现

- [DefaultAgentSessionJournal.java:97](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentSessionJournal.java:97)：116 行先写权威 transcript，再更新 MySQL 投影和热状态；投影／热状态错误在 126、151 行捕获，权威 append 错误不被此处吞掉。
- [DefaultAgentTranscriptRecoveryService.java:33](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentTranscriptRecoveryService.java:33)：读取最新 checkpoint，保留摘要与原文，再读取 checkpointSeq 之后的 tail。恢复读取算法存在，但检查点自动生产链路见上一节限制。
- `DefaultAgentSessionColdLoadService.java:29` 从冷归档找最近快照，回填热快照及边界后事件；`InMemoryAgentOrchestrationService.java:272` 开始恢复与路由，588 行可注入热快照摘要。

**边界：**会话上下文恢复不等同执行中任务的精确续跑；本次未验证跨实例抢占、不可逆工具副作用或 exactly-once。ADR 0005 本身明确首版限 replay-safe 工具。

## 5. 工具治理与约束解码

**已实现：执行前权限复核、注册检查与 replay-safe 限制。**

- [InMemoryAgentCapabilityRegistry.java:58](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentCapabilityRegistry.java:58)：检查 Profile 一致性、已注册、Profile allowlist 与 replaySafe；未通过时不进入 capability.execute。异常转为结构化失败并写审计。
- [AgentCapabilityToolUseExecutor.java:38](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentCapabilityToolUseExecutor.java:38)：再次检查工具可用性并路由到 Registry；内部工具另查注册与 enabled。`InMemoryAgentRuntimeConfigurationService.java:102` 实施面向 Profile 的工具选择。
- `VirtualThreadAgentToolUseExecutor.java:255`、265 行取消底层 Future；`StreamingAgentToolUseOrchestrator.java:120` 取消已提交工具。已存在取消链，不代表各种外部调用都已完成强终止验收。

**约束解码已有配置与调用接入。** `SpringAiAgentModelStreamClient.java:191`、199 行有约束解码分支；`SpringAiAgentToolCallbackFactory.java:159` 对无效约束工具 Schema 失败；`application-local-qwen.yml:20` 启用该能力；部署启动脚本启用结构化后端并执行探针。

**本次未证实：**通用按工具滑窗熔断、完整执行超时策略和 LoopDetector。不要把循环次数限制、失败次数收敛或准入超时写成上述机制已完整实现。本次亦未审计 Sandbox，个人项目与 AgentTeam 的隔离实现不可互相代替举证。

## 6. 模型部署与推理优化

**已找到明确部署脚本／服务实现；未重新运行性能实验。**

- [start_qwen35_4b_vllm.sh:117](../../java_agent/deploy/remote/model/start_qwen35_4b_vllm.sh:117)：启用 prefix caching，120 行配置 structured outputs；124 行起接收量化参数；171 行结构化输出探针。仓库还有前缀预热脚本，不是只在简历中列功能名。
- [bge_m3_embedding_server.py:26](../../java_agent/deploy/remote/model/bge_m3_embedding_server.py:26)：支持 CUDA float16，限制 batch；81–84 行使用配置 batch 批推理。不能将这一批推理直接称为跨请求动态合批。
- `docs/reports/agent-resume-benchmark-20261011/README.md:32` 明确新模型为 MLP INT4、注意力／GDN BF16。属于部分量化，不是整个模型统一 8-bit。

**验收待补：**当前部署版本、冷／热缓存、并发成功率、TTFT／TPOT／总耗时的同口径实验；已有整体耗时改善不能直接拆给某个单项机制。

## 7. 仿真评测、Judge 与提示词迭代

**Trace 已有自研上报链路，不能写成已接入 Langfuse。**

- [HttpAgentTraceReporter.java:24](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/HttpAgentTraceReporter.java:24) 将事件提交虚拟线程并 POST 到自研 platform-trace 内部接口，异常被忽略；`InMemoryAgentOrchestrationService.java:697` 实际上报事件，`TraceReportingAgentCapabilityAuditSink.java:22` 上报能力审计。
- `AgentTraceReporterConfiguration.java:17` 默认缺配置时为 Noop；远端 `deploy/remote/app/docker-compose.yml:164` 默认开启上报。不能只看默认 Bean 判断部署没有 Trace，也不能据异步上报推断已有可靠投递。
- 在 Java Agent main、Python rs_core 和远端部署相关源码范围内，`langfuse`／`Langfuse`／`opentelemetry` 检索未命中。后续可复用现有事件模型接入，但本次不认定集成已完成。

**已实现：规则／模型驱动用户仿真、报告导出及多轮样本生成。**

- `python_agent/scripts/evaluation/run_simulation_evaluation.py:37` 运行多角色、多轮仿真，支持 deterministic/model；74 行处理模型不可用时的严格失败或回退；104 行导出批次、指标和报告。
- [simulation/policy.py:84](../../python_agent/rs_core/offline/simulation/policy.py:84)：模型策略实际调用 client，校验所选商品必须在展示池；非 strict 时可回退规则策略。22 行的 satisfaction 属于规则策略评分，不能默认视为真人满意度或独立 Judge 分。
- `offline/training/multi_turn_sft_generator.py:301` 有实际多轮样本生成入口；238 行等明确 persona 从 train-history 提取，但这不自动证明训练／调参／最终评测已按用户完全分离。

**有 Judge，但两类不能混淆。**

- [sft_judge.py:80](../../python_agent/rs_core/offline/training/sft_judge.py:80) 明确是 deterministic/local；92 行执行契约门禁、规则 Rubric 与加权决策。这是真实质量筛选器，但不是外部 LLM-as-Judge。
- [online_evaluation/evaluator.py:49](../../python_agent/rs_core/online_evaluation/evaluator.py:49) 有真实的模型回调式 Judge，校验维度、评分和逐字证据；82 行明确返回 `uncalibrated_proxy`、`used_for_promotion=False`；无 Judge 时返回 not_configured。这个模块不能说成完全不存在，也不能说成已完成人工校准的满意度评测。

**本次未证实：**固定人工校准集、Judge 与人工一致性报告、隔离留出集的提示词 A/B，以及完整分阶段收益消融。需查实验产物后再将其描述为已完成方法论闭环。

## 8. QLoRA SFT 与 GRPO 后训练

**阶段结论：所查本地 Qwen 入口为资源门禁与初始化脚手架，尚不能证明执行了训练。**

- [sft_runner.py:11](../../python_agent/rs_core/offline/training/sft_runner.py:11)：使用 synthetic 样本、验证依赖与资源门禁；34 行后加载模型和 LoRA；46 行 import SFTTrainer，48 行只返回类名。所查方法没有构造 Trainer、准备训练数据集或调用 train。
- [grpo_runner.py:12](../../python_agent/rs_core/offline/training/grpo_runner.py:12)：同样使用 synthetic 样本，先计算 reward；48 行 import GRPOTrainer，50 行仅返回类名，没有实际构造或训练。
- `offline/training/reward_adapter.py:7` 有标量奖励计算，26 行 TRL 形式包装，包含反馈约束和候选池检查。这证明奖励适配器存在，不证明在线 rollout→组内优势→参数更新已接通。
- `offline/training/gpt_sft_runner.py:76` 调用的是样本生成器，98 行写出 JSONL；名称不能直接解读为已提交模型微调作业。

**本次未找到：**上述 Qwen 训练目录中的 assistant-only loss 实际 batch 掩码、Trainer 构建与 train 调用、训练产物及独立前后评测链路。不能将此前简历 23% 仿真满意度直接归因这些脚手架；远端或其他目录是否有完整训练应另行核验。

## 建议作为落地路线使用的缺口

1. 先用现有 Trace 和在线评测接口固化任务集、错误分类与版本信息，补人工 Judge 校准，保留不经训练的提示词基线。
2. 在现有 Hook 上实现可验收的循环检测、分类恢复、工具熔断与预算；并发准入、执行期限、取消和重试分别测试。
3. 给压缩补安全边界检查、调用／结果配对、摘要／检查点生产与业务接入，并与前缀缓存独立消融。
4. 明确 Python 与 Java 的记忆职责，补生命周期策略与版本一致性，再验证跨会话恢复和旧偏好失效。
5. 补训练数据管线、助手掩码检查、SFT／GRPO 真正训练入口与资源方案；最后才做训练收益归因。

本笔记是阶段性源码审计，不是运行验收报告，也没有对简历数据做重新测量。
