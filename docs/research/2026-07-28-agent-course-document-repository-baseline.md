# 钉钉课程文档对照前的 RS_agent 仓库基线

> 日期：2026-07-28  
> 范围：只研究当前工作区内的源码、配置、测试结构与项目文档；未读取或转录钉钉文档正文。  
> 用途：作为后续逐页阅读课程文档时的对照底稿，避免把“仓库已有能力”“设计中能力”和“课程文档要求”混为一谈。

## 1. 结论摘要

当前仓库不是一个单一实现，而是两条互补但成熟度不同的主线：

1. `python_agent` 主要承载推荐算法、召回/排序/RAG、离线评测与训练脚手架，也有一套领域无关的 `GenericAgentLoop`；但线上推荐主路径仍是 legacy runtime，`generic_active` 会被明确拒绝，MemoryAgent 与 RagAgent 主要以 shadow/内部适配器形态接入。
2. `java_agent` 主要承载面向服务化的生产 Agent 编排：模型流式读取、工具调用循环、并行安全工具执行、`rs_agent → rag_agent` 委派、SSE 事件、运行时 skill/prompt/tool 配置、会话日志与持久化演进。
3. 仓库已经有较强的“推荐系统工程底座”，包括多路召回、两塔召回、BM25 + Milvus RAG、排序/重排、反馈约束、离线评测和部署编排；但没有找到“三塔召回”实现或命名。
4. 上下文与记忆已有两套实现思路：Python 有确定性预算裁剪、轮次摘要和默认关闭的跨 Session 长期记忆；Java 有事件日志、快照、压缩、冷热分层以及正在建设的 MySQL/Redis/Scylla 持久化。项目 ADR 已定义更严格的最终语义，但当前 Java 默认配置仍是内存存储且持久化关闭。
5. 流式能力后端已经存在，但不是 AG-UI 协议：Python 提供基础 SSE `token/done`；Java 提供 `token/tool_use/tool_result/answer_block/model_usage/done/error` 等自定义事件。当前前端没有检索到 `/chat/stream`、`EventSource` 或 `ReadableStream` 消费代码。
6. 评测与训练闭环已经具备较多结构化产物和规则，但训练执行仍不完整：SFT/GRPO runner 可以做资源门禁和构造 Trainer，却没有在当前代码中调用训练；所谓“自进化”目前主要停留在研究文档和人工可修改的运行时 prompt/skill/tool 接口，不是自动闭环。
7. 本文件记录的是**当前脏工作区快照**。Java 会话持久化、并发编排等大量文件尚未纳入 Git，不能直接视为已合并、已部署或已验收能力。

## 2. 仓库结构与职责

| 层次 | 当前职责 | 主要证据 |
| --- | --- | --- |
| Python Agent/推荐核心 | 对话规划、上下文、工具契约、推荐/RAG 子 Agent 适配器、rollout、reward | `python_agent/rs_core/agent/` |
| Python 在线推荐 | 多 provider 召回、候选合并、两塔向量查询、排序/重排 | `python_agent/rs_core/online/` |
| Python 离线闭环 | Agent scorecard、artifact、SFT/GRPO/GPT SFT、多轮模拟 | `python_agent/rs_core/offline/` |
| Python 服务 | FastAPI、会话、聊天、反馈、RAG、SSE | `python_agent/rs_core/serving/` |
| Java Agent 服务 | 流式 AgentLoop、工具调度、多 Agent 委派、skill、trace、Session | `java_agent/rs-service-agent/` |
| Java 推荐/RAG 服务 | 候选、召回、排序、推荐域 RAG 与 trace | `java_agent/rs-service-recommend/`；边界决策见 `java_agent/AGENT_RAG_BOUNDARY_DESIGN.md` |
| 部署 | Python 本地 compose；Java 远端 infra/app compose | `python_agent/deploy/README.md`；`java_agent/deploy/remote/` |

项目的领域词汇明确区分 Durable Session History、Effective Context、Context Checkpoint 与 Long-term Memory；后续讨论应继续沿用这些名称，不把“会话摘要”泛称为“长期记忆”。来源：`CONTEXT.md`。

## 3. 仓库现状：能力矩阵

| 课程关注项 | 当前仓库状态 | 成熟度判断 |
| --- | --- | --- |
| AgentLoop | Python 有通用一次性骨架；Java 有真实模型—工具多轮循环、终止与中断 | Java 已实现主干；Python 通用 Loop 未 active |
| 多 Agent | Java 主 Agent 可调用唯一受支持的 `rag_agent`；Python 有 RagAgent/MemoryAgent adapter | 部分实现，拓扑很窄 |
| 召回 | 多 provider、多路融合、fallback、两塔、BM25/Milvus RAG | 较完整，但无“三塔” |
| 上下文压缩 | Python 预算化摘要/裁剪；Java 快照与冷热归档；ADR 定义安全压缩语义 | Python 已用；Java 目标能力仍在演进 |
| 长期记忆 | Python typed memory + memory/json store，默认关闭；Java 有存储模型/WIP 接口 | 原型/建设中，尚非完整线上闭环 |
| 流式输出 | Python/Java 都有 SSE；Java 事件更丰富 | 后端已实现，自定义协议 |
| AG-UI 实时进度 | 未找到 AG-UI 依赖、事件模型或前端消费 | 缺失 |
| 评测 | scorecard、reward、rollout、artifact、SFT judge、Qwen 对照 harness | 较丰富，但指标与发布门禁未统一自动化 |
| 训练闭环 | SFT/GRPO/GPT SFT/多轮生成脚手架与评分规范 | 部分实现，重训练未真正执行 |
| 部署 | Docker Compose、网关、基础设施、远端部署说明 | 已有可运行骨架，环境较复杂 |
| Harness | 有 Qwen 对照评测 harness；没有统一生产 Agent Harness 抽象 | 局部存在 |
| 自进化 | 有 SkillOpt 研究、运行时人工更新 prompt/skill/tool API | 自动闭环缺失 |
| Prompt 工程 | Python 有 XML-like 规范和边界 prompt；Java 有动态系统 prompt 与内置 skills | 已有基础，缺版本化实验/晋升闭环 |

## 4. AgentLoop

### 4.1 Python：领域无关骨架，但不是当前 active 主路径

`GenericAgentLoop` 把一次运行拆成 `ContextBuilder → Planner → ToolDispatcher → ResponseComposer → StateUpdater → OutputAdapter`。Loop 只协调顺序，返回 `RuntimePatch` 与 `CommitIntent`，不直接提交领域状态；输出分为 public、SFT、internal 三个投影。来源：`python_agent/rs_core/agent/runtime_core/loop.py:79-119`、`:121-176`。

这套 Loop 当前是“一次规划 + 一批工具 + 一次回复”的确定性骨架，不是模型持续产生 `tool_use` 后回灌 `tool_result` 的迭代循环。更关键的是：`AgentRuntimeConfig` 默认 `legacy`，而 `AgentOrchestrationFacade` 遇到 `generic_active` 会直接抛错，只有 `generic_shadow` 会追加影子报告。来源：`python_agent/rs_core/agent/runtime_core/config.py:8-28`、`python_agent/rs_core/workflow/facades.py:47-63`。

Python legacy runtime 已有稳定的推荐业务流水线：记忆预取、上下文压缩、对话规划、约束更新、前置工具、推荐/纯对话分支、后置工具、停止检查、诊断和 Session 摘要。来源：`python_agent/rs_core/agent/runtime/__init__.py:90-198`。

### 4.2 Java：真实的流式模型—工具循环

Java `AgentLoop` 在每个循环中调用模型流：

- token 未遇到工具调用时直接向客户端发送；
- 发现 `tool_use` 后执行 pre-tool hook、发送工具事件、并提交工具；
- 工具完成后把结果写回下一轮模型请求；
- `emit_final_answer` 作为结构化终止工具；
- 支持中断、hook stop、模型异常和最大循环次数保护。

来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java:134-172`、`:179-278`、`:281-380`。

工具执行编排显式区分并发安全工具与串行工具，`rag_support`、`recommend_candidates`、`model_chat` 等可并发；其余工具通过 serial barrier 排序。这不是多 Session 的全局并发模型，而是单次 Loop 内的工具调度。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/StreamingAgentToolUseOrchestrator.java:20-58`、`:60-125`。

Java 还设置了 active loop、model stream、tool call、Session queue 的背压参数；默认分别为 32、8、64、2。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/config/AgentExecutionProperties.java:6-24`。

## 5. 多 Agent

### 5.1 Java 当前拓扑

Java 当前有两个明确 profile：

- `rs_agent`：主推荐 Agent，拥有推荐、RAG support、catalog、卡片渲染、模型、skill、agent 委派和最终回答工具；
- `rag_agent`：内部证据 Agent，只拥有 `rag_evidence_search`、`load_skill`、`emit_final_answer`。

来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/RsAgentLoop.java:42-68`、`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/RagAgentLoop.java:41-58`。

`call_agent` 在工具执行器中委派 agent；但 `HttpAgentDelegateService` 目前只接受 `rag_agent`，其他名称直接报错。`rag_support/rag_evidence_search` 也会固定路由到 `rag_agent`。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/VirtualThreadAgentToolUseExecutor.java:122-143`、`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/HttpAgentDelegateService.java:29-56`。

因此这里是“主 Agent + 一个受限领域子 Agent”，还不是通用的 supervisor/worker、handoff、并行 fan-out 或多角色协作框架。

### 5.2 Python 当前拓扑

Python 定义了 `RagAgentAdapter` 与 `MemoryAgentAdapter`，都通过 `AgentRegistry/AgentRunner` 包装成内部 Agent：

- RagAgent 有 `pre_retrieval_query_support` 和 `post_ranking_evidence_support` 两个 stage；
- MemoryAgent 有 `pre_turn_memory_recall`、`post_turn_memory_snapshot`、`session_end_memory_summary` 三个 stage。

来源：`python_agent/rs_core/agent/adapters/rag.py:31-35`、`:698-705`；`python_agent/rs_core/agent/adapters/memory.py:29-33`、`:521-530`。

但当前 facade 只允许 MemoryAgent/RagAgent 的 `shadow` mode，其他 mode 被记为错误；generic active 也未开放。来源：`python_agent/rs_core/workflow/facades.py:64-99`。

## 6. 召回、排序与 RAG

### 6.1 多路召回

Python `CandidateRetrievalOrchestrator` 从配置构造多个 provider，先执行常规 provider，合并去重后如果候选不足再执行 fallback provider，并产出 provider coverage 与 underfill diagnostics。来源：`python_agent/rs_core/online/recall/online_retrieval/orchestrator.py:13-47`、`:49-144`。

当前 online 配置中能看到 category、item neighbor、popular、userCF、语义 token/vector、pool500 fallback 等多种 provider；仓库还包含 itemCF、Swing、co-visit、两塔等离线构建和在线查询代码。两塔模型明确由 `user_tower` 与 `item_tower` 构成，并有 Milvus item collection。来源：`python_agent/rs_core/offline/training/two_tower.py:1308-1332`、`python_agent/rs_core/data/vectorstores/milvus_contracts.py:7-26`。

**未找到任何 `three_tower`/“三塔”源码、配置或文档命中。** 后续必须从课程文档确认“三塔”的三类输入、训练目标、在线 serving 和它与现有两塔/多路召回的关系，不能仅凭名称改造。

### 6.2 RAG 边界

仓库已经做出清晰的服务边界决策：Agent 只调用推荐语义工具；候选、召回、排序、RAG evidence 和证据压缩归 `rs-service-recommend`；底层 Elasticsearch/Milvus 对 Agent 隐藏。来源：`java_agent/AGENT_RAG_BOUNDARY_DESIGN.md`。

Python RagAgent 强制 candidate-scoped evidence，不允许新增商品、改变排序或泄露 raw evidence；查询支持和候选证据支持也分为两个 stage。来源：`python_agent/rs_core/agent/adapters/rag.py:35-75`。

这与“通用知识库问答 RAG”不同：当前实现是推荐域 RAG，主要为查询扩展和候选解释服务。

## 7. 上下文压缩与长期记忆

### 7.1 Python 已实现的上下文预算

Python `ContextBundle` 保留当前目标、对话状态、约束、用户画像、已展示商品、近期 Turn 和归档 Turn 摘要；Session 摘要只保存受限数量的偏好、澄清历史和商品 ID。来源：`python_agent/rs_core/agent/context/__init__.py:48-102`、`:105-139`。

每个 Turn 的历史摘要只保留截断后的用户输入、助手回复、intent、action、item ids 与 fallback 标记；任意 dict/list/string 还会按预算裁剪并记录 `_truncated_*`。来源：`python_agent/rs_core/agent/context/__init__.py:183-200`、`:219-248`。

legacy runtime 在规划前和 Turn 完成后都重建 Session 摘要。来源：`python_agent/rs_core/agent/runtime/__init__.py:104-112`、`:190-192`、`:301-307`。

这是一套确定性结构化摘要，不是 LLM semantic compaction，也没有 Durable Session History/Checkpoint 的事务语义。

### 7.2 Python 长期记忆

Python `LongMemoryConfig` 默认 `enabled=False`，支持内存或 JSON store；记忆以 typed entries 保存 liked/disliked item、category、keyword、use case、max price 等，并使用确定性关键词重叠召回，默认最多保存 200 条、召回 20 条。来源：`python_agent/rs_core/agent/memory/__init__.py:13-31`、`:82-152`、`:178-250`。

因此它当前更像“可审计的用户偏好/约束快照”，而不是自动抽取自由文本、embedding 检索、冲突消解、遗忘策略完备的长期记忆系统。

### 7.3 Java Session 设计与实现状态

Java 现有压缩服务会把 mark 之前的事件归档，写入 snapshot，再从 hot store 删除已经归档的事件。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentSessionCompactionService.java:31-76`。

Agent orchestration 只把 `TOOL_USE`、`TOOL_RESULT`、`ASSISTANT_MESSAGE` 等完整语义事件写入 journal，token delta、usage、trace 和 done 不进入持久语义历史；每 Turn 还写快照。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java:369-429`。

项目 ADR 的目标语义更加严格：

- ScyllaDB 追加事件与 Context Checkpoint 是权威事实，MySQL 是投影，Redis 是可重建热状态：`docs/adr/0001-session-history-and-checkpoint-authority.md:1-3`；
- checkpoint 不固化 system prompt、tool schema 和动态配置：`docs/adr/0002-context-checkpoint-excludes-runtime-injection.md:1-3`；
- 只允许在 Safe Compaction Boundary 切换上下文：`docs/adr/0003-compaction-only-at-safe-model-call-boundaries.md:1-3`；
- 紧急裁剪必须保留完整语义组并可审计：`docs/adr/0004-auditable-lossy-context-truncation.md:1-3`；
- 同 Session 串行、Session 间并行：`docs/adr/0006-serialize-turns-within-each-session.md:1-3`。

不过默认 Java 配置仍是 `session-store.type=memory`，`session-persistence.enabled=false`，trace 也默认关闭。来源：`java_agent/rs-service-agent/src/main/resources/application.yml:33-53`。因此 ADR 与当前可部署默认值之间仍有交付差距。

## 8. 流式输出与实时进度

Python FastAPI 暴露 `/chat/stream`，如果 engine 支持 `stream_chat` 就原样转发，否则退化为一次 token + done 的 SSE。来源：`python_agent/rs_core/serving/api/routers/agent.py:30-39`、`:60-74`。

Java 暴露 `/api/agent/chat/stream`，通过 `StreamingResponseBody` 输出标准 SSE，并有中断接口。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/app/AgentChatController.java:55-92`、`:94-113`。

Java Loop 的事件包含 token、tool_use、tool_result、answer_block、model_usage、done、error 等，足以构建实时进度 UI；但当前事件是项目自定义 `AgentStreamEventVO(event, request_id, data)`，不是已识别的 AG-UI schema。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentStreamEventVO.java:7-14`。

当前两个前端源码树都没有检索到 `/chat/stream`、`EventSource`、`ReadableStream/getReader` 或这些事件名的消费实现。Java 前端的 `sendChat` 仍调用非流式 `/agent/chat`。来源：`java_agent/frontend/src/api/agentClient.ts:6-56`。

## 9. 评测、训练与 Harness

### 9.1 已有评测闭环组件

Agent scorecard 当前覆盖：推荐有效性、交互质量、反馈响应、记忆一致性、训练数据质量。反馈维度会检查明确拒绝是否再次出现，训练数据质量会检查 SFT、reward 和 tool evidence 覆盖。来源：`python_agent/rs_core/offline/evaluation/agent_scorecard.py:18-38`、`:78-139`。

Agent artifact 会聚合 rollouts、scorecard、tool events 与 training signals，并生成 SFT、reward、preference、trajectory 四类记录。来源：`python_agent/rs_core/offline/evaluation/agent_artifact.py:15-44`、`:47-82`。

SFT judge 是本地确定性规则评审，包含硬门禁、Rubric 分数与 accept/accept_light/rewrite/reject 档位。来源：`python_agent/rs_core/offline/training/sft_judge.py:72-124`、`:157-189`。

项目评分规范还区分 SFT 数据质检、GRPO checkpoint 质检和线上 Session 满意度，并描述数据回流方向。来源：`python_agent/dic/standards/AGENT_SCORING_FRAMEWORK.md:1-26`、`:117-207`、`:230-434`。

### 9.2 当前 Harness

`run_qwen_evaluation_harness` 会对 `deterministic_baseline`、`rule_feedback_rerank`、`qwen_feedback_rerank` 三种模式运行同一 demo，并写 comparison JSON/Markdown。来源：`python_agent/rs_core/workflow/hybrid_demo.py:263-315`。

这是**特定 Qwen rerank 对照实验 harness**，不是统一管理 agent lifecycle、save point、恢复、权限、hooks、工具状态和多 Agent 的通用运行 Harness。

### 9.3 训练尚未真正闭环

SFT/GRPO runner 默认 dry-run，进入 heavy path 后只加载模型、LoRA config 并返回 Trainer 类名；当前函数没有构建 trainer 实例，也没有调用 `train()`、保存 checkpoint 或执行晋升。来源：`python_agent/rs_core/offline/training/sft_runner.py:11-49`、`python_agent/rs_core/offline/training/grpo_runner.py:12-50`。

GPT SFT 生成器可以在显式 enable/execute 后调用 API 生成样本并写 JSONL，但这是数据生成，不是模型训练。来源：`python_agent/rs_core/offline/training/gpt_sft_runner.py:18-64`、`:66-99`。

因此当前更准确的表述是“评测与训练数据管线 + 训练初始化脚手架”，不是完整的自动训练—评测—发布—回滚闭环。

## 10. 部署与运行约束

Python compose 已按 frontend、online、agent、gateway、worker、infra 分 profile；worker 默认只运行 health，不隐式触发重训练/全量评估。MySQL 是结构化主路径，Milvus 是 RAG 向量检索主路径。来源：`python_agent/deploy/README.md`。

Java 远端部署拆为 infra 与 app：Nacos/MySQL/Redis/Elasticsearch/MinIO 在 infra，Agent/Recommend/Model/Trace 等 Spring Boot 服务在 app；主机端口绑定 `127.0.0.1`，通过 SSH/Cloudflare Tunnel 暴露。来源：`java_agent/deploy/remote/infra/README.md`、`java_agent/deploy/remote/app/README.md`。

本地资源规则要求按 12GB 可承受、14GB 上限控制；全量数据、模型加载、训练和大评估应限流 smoke 或远程执行。来源：`CLAUDE.md`。

## 11. Prompt 工程、Skills 与“自进化”

### 11.1 Prompt 工程现状

Python 已定义 XML-like prompt 规范，要求写清 Role、Why、Success、Context、Tool Workflow、Runtime Boundary、Response Style 和 good/bad examples。来源：`python_agent/dic/standards/AGENT_PROMPT_STANDARD.md:1-86`。

RecommendationAgent 的实际 boundary prompt 已按该格式实现，并明确当前需求优先、候选集合约束、RAG/score/trace 不可泄露。来源：`python_agent/rs_core/agent/tools/__init__.py:822-860`。工具 planner 会把 hidden tool manifest 的最小摘要追加到 system prompt。来源：同文件 `:1747-1776`。

Java 运行时支持读取和修改 system prompt、skill 与 tool；内置 skill 按需通过 `load_skill` 加载，当前包含明确需求推荐、模糊需求澄清、反馈适应、冷启动和证据解释。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/platform/PlatformAgentRuntimeController.java:29-68`、`java_agent/rs-service-agent/src/main/resources/agent-skills/`。

### 11.2 自进化现状

仓库有 SkillOpt 自进化研究笔记，但业务运行时没有发现自动执行以下闭环的代码：

```text
线上/离线轨迹采集
→ 失败与成功模式挖掘
→ 自动修改 prompt/skill
→ held-out 评测
→ 安全门禁
→ 版本晋升/回滚
```

Java 的 runtime PUT API 只是**人工可变配置面**；当前实现使用进程内 map/volatile prompt，也没有从这些 endpoint 到评测和自动晋升的连接。来源：`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java:74-140`。

## 12. 已确认的主要差距

按“对项目改进的影响”排序：

1. **Java 与 Python 的 Agent 真源不统一**：Java 是真实 LLM tool loop，Python 是推荐算法与 legacy runtime；通用 Python Loop 又未 active。需要先确定未来谁拥有主 AgentLoop、状态和工具协议。
2. **Session ADR 尚未完全落地**：权威历史、checkpoint、安全压缩边界已经设计，但默认部署仍 memory/disabled，大量持久化文件处于工作区 WIP。
3. **多 Agent 只有窄委派**：目前唯一明确子 Agent 是 `rag_agent`；MemoryAgent 仍 shadow，缺少通用任务隔离、上下文裁剪、错误传播和预算协议。
4. **没有三塔召回**：现有是两塔 + 多路召回 + 融合排序，不能直接声称覆盖课程“三塔”。
5. **没有 AG-UI 集成**：后端自定义 SSE 已有，但事件协议、状态归约和前端实时消费缺失。
6. **训练不是闭环**：有样本、reward、judge、scorecard 和 harness，但没有真正训练执行、checkpoint 管理和自动晋升。
7. **自进化没有生产实现**：仅有研究和人工修改接口，缺少验证、版本、发布、回滚和数据治理。
8. **Prompt 配置缺版本化实验治理**：Python prompt 偏静态代码，Java prompt/skill 偏进程内动态配置；两边缺少统一版本、关联 trace、A/B 和 promotion record。

## 13. 待从钉钉文档补充并逐项核对

后续阅读课程文档时，至少需要回答这些问题：

### AgentLoop / Harness

- 课程里的 AgentLoop 是单 Agent 工具循环，还是包含 session persistence、retry、interrupt、hook、compaction 的完整 Harness？
- 每个 Turn/operation/tool 的状态机和可恢复边界是什么？
- 对并行工具、同 Session 串行、跨 Session 并行如何约束？

### 多 Agent

- 多 Agent 是 supervisor/worker、handoff、agent-as-tool，还是固定 pipeline？
- 子 Agent 获得哪些上下文，结果如何裁剪，错误/超时/取消如何传播？
- 是否需要 MemoryAgent、EvaluatorAgent、Planner/Critic 等新角色，还是保持 `rs_agent + rag_agent` 即可？

### 三塔召回

- 三个 tower 的准确语义、输入特征、训练目标、负采样和在线 serving 是什么？
- 它是替代现有两塔，还是作为新 provider 加入多路召回？
- 与 BM25、Milvus semantic、ItemCF/Swing/userCF、DeepFM/LTR 的分工是什么？

### 上下文与记忆

- 压缩触发阈值、摘要模型、safe boundary、失败降级、恢复验证如何定义？
- 长期记忆的抽取、召回、冲突、衰减、遗忘、隐私和用户可编辑机制是什么？
- 是否明确区分 Durable Session History、Effective Context 与 Long-term Memory？

### 流式输出 / AG-UI

- 课程要求的 AG-UI 版本、事件名、state snapshot/delta、tool progress 和 error contract 是什么？
- 前端如何归约事件、断线重连、去重、恢复与取消？
- 现有自定义 SSE 应适配 AG-UI，还是保留内部协议并加转换层？

### 评测、训练、自进化

- 核心 benchmark、数据集、judge、hard gate 和 promotion threshold 是什么？
- Harness 如何冻结模型、prompt、工具、数据 split 与随机种子，保证可复现？
- 自进化到底优化 prompt、skill、memory policy、tool description 还是模型参数？
- 如何用 held-out 集验证，如何版本化、灰度、回滚并避免 reward hacking？

### 部署

- 目标是单体、Java/Python 双服务，还是更清晰的 control plane/data plane？
- 模型服务、Agent 服务、推荐服务、trace/observability、Redis/MySQL/Scylla/Milvus 的生产拓扑与容量假设是什么？
- 课程所讲的部署是否包含监控、告警、成本、限流、幂等、灾难恢复与安全审计？

## 14. 后续对照方法

主代理逐页读完课程文档后，可以在本文件基础上新增一张三列清单：

| 课程要求 | 仓库证据 | 改进决策 |
| --- | --- | --- |
| 文档原意与验收标准 | 当前源码/配置/测试位置 | 保留、补齐、替换或明确不采用 |

只有能落到“接口、状态、数据、测试、部署和评测门禁”的课程内容才进入实施计划；概念性表述先保留为待验证假设。
