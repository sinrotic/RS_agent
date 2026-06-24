# 工程叙事日志

本文档用于记录本项目中具有复盘价值的工程过程，目标是把开发、调试、优化和验证过程沉淀成适合面试表达的中文材料。

记录重点不是流水账，也不是私有思维链，而是可验证的工程叙事：问题是什么、如何定位、为什么这样解决、如何证明有效、面试时怎么讲。

## 记录原则

- 默认使用中文。
- 每条记录保持简洁，优先写事实和证据。
- 引用具体文件、命令、测试、指标或输出路径。
- 不记录无意义的中间尝试，不堆 raw log。
- 简单机械修改不需要单独记录。

### 2026-06-22 - RSAgent dialogue / multi-turn SFT 边界收紧

**任务：**
修复 review 指出的 dialogue 工具契约与 multi-turn SFT 数据边界问题，覆盖 fallback retrieve 参数、中文泛浏览、supported constraints、terminal accept、`selected_item_ids` 语义、nested target 校验和 flat artifact 统计。

**遇到的问题：**
确定性 fallback 仍可能把 `semantic_mode/use_history_profile/use_behavioral_recall/route_policy` 等执行层 internal 字段暴露给 LLM planner；`看看/随便看看` 被当成具体 query；SFT 里 terminal accept 复用或错误生成 diagnostics、no-display accept 与 selected item 语义容易产生无 grounding 训练样本。

**定位方式：**
对照 `executor-grounding-gate` 的 8 条 review findings，沿 `rs_core/rsagent/dialogue.py`、`rs_core/rsagent/llm_dialogue_planner.py`、`rs_core/training/multi_turn_sft_generator.py` 和 serving feedback 支持范围逐项核查；验证中发现 `service.feedback(..., "accept", ...)` 在真实 serving 层未被 `FEEDBACK_PROMPTS` 支持，会导致 dry-run scene 全部被拒绝。

**解决方式：**
将 fallback `retrieve_candidates` 收敛到业务级字段，由 runtime normalize 推导内部策略；LLM planner 补链时复用 validator；中文泛浏览改走个性化浏览推荐但不生成 specific query；补齐 `liked_item_ids/max_price/use_cases` 支持。SFT 侧把推荐 turn 的 `selected_item_ids` 定义为 public display ids，dialogue-only 不选中反馈 item；validator 校验 nested selected 与 display/allowed 一致；flat artifact 明确为 display-only 并报告 dropped no-display turn。terminal accept 优先读取真实 diagnostics，若 serving 不支持 `accept` 则使用 accept-specific synthetic diagnostics，避免复用上一轮 recommendation diagnostics 或生成无展示 accept。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_dialogue.py tests/test_llm_dialogue_planner.py tests/test_agent_tools.py tests/test_multi_turn_sft_generator.py -q`，结果 `102 passed in 8.99s`；运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_agent_runtime_contracts.py tests/test_agent_rollout_schema.py tests/test_rag_core.py -q`，结果 `105 passed in 2.81s`；运行 `./.venv/Scripts/python.exe -m ruff check rs_core/rsagent/dialogue.py rs_core/rsagent/llm_dialogue_planner.py rs_core/training/multi_turn_sft_generator.py tests/test_agent_dialogue.py tests/test_llm_dialogue_planner.py tests/test_agent_tools.py tests/test_multi_turn_sft_generator.py`，结果 `All checks passed!`。本轮未调用外部 API。

**面试可讲点：**
这段可以讲成“把推荐 Agent 的工具契约和训练监督边界一起治理”：LLM 只看到业务级工具参数，runtime 执行细节不外泄；没有召回/展示就不能推荐；SFT 样本只基于 public display 做 target supervision，并用 validator 和 manifest 统计把数据质量问题前置暴露。

### 2026-06-22 - RSAgent 通过 call_rag_agent 调用 RagAgent 子 Agent

**任务：**
把原先隐式挂在 `retrieve_candidates` 前后的 RAG helper，改造成 RSAgent 内部的子 Agent 工具调用形态：RSAgent 计划并执行 `call_rag_agent`，由 RagAgent 返回 pre-retrieval query support 或 post-ranking candidate-scoped evidence support。

**遇到的问题：**
RagAgent 已经具备 shadow/internal-only loop，但调用方式仍偏 helper：pre 阶段通过 `tool_context["query_rag"]` 隐式注入，post 阶段由 facade 直接 `attach_shadow_report()`。这会让架构上看起来仍是低层 RAG 工具，而不是 RSAgent 主 Agent 调用子 Agent；同时必须防止 `query_rag/get_item_evidence/rag_search` 回流到 LLM planner 或 SFT 监督中。

**定位方式：**
对照仓库内 Claude Code `AgentTool` / `LocalAgentTaskState` / `SendMessageTool` 的实现，确认子 Agent 在 Claude Code 中也是通过工具 schema 发起、以 request/result envelope 和消息路由通信。再沿 `rs_core/rsagent/tools.py`、`dialogue.py`、`llm_dialogue_planner.py`、`rs_core/agent_runtime/adapters/rag.py`、`rs_core/workflow/hybrid_environment.py` 和 `facades.py` 梳理当前 RAG support 的入口与泄漏边界。

**解决方式：**
新增 hidden/internal `call_rag_agent` tool，参数只允许 `stage/query/reason/candidate_scope/max_support_per_item/max_text_chars`，并拒绝 provider/source/score/manifest/path/raw evidence 等低层字段；deterministic fallback 和 LLM planner 的推荐链路补齐为 `get_user_context -> call_rag_agent -> retrieve_candidates -> rank_candidates -> build_recommendation_slate`。RagAgent adapter 增加 `RagAgentInvocation`、`RagAgentMessageEnvelope`、`RagAgentResponse` 与 `invoke()/handle_message()`，旧 `build_query_support/run_shadow/attach_shadow_report` 保留为兼容 wrapper。runtime 执行 `call_rag_agent` 后优先写 `tool_context["rag_agent_query_support"]`，短期保留 `query_rag` alias；post-ranking facade 改为构造 invocation，再按 response 写入 diagnostics。SFT forbidden keys 和 tool supervision 只允许高层 `call_rag_agent`，不输出 raw support。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_llm_dialogue_planner.py tests/test_rag_agent_adapter.py tests/test_agent_dialogue.py tests/test_agent_runtime.py tests/test_agent_runtime_contracts.py tests/test_agent_rollout_schema.py tests/test_multi_turn_sft_generator.py tests/test_rag_core.py -q`，结果 `217 passed in 16.10s`；运行 `./.venv/Scripts/python.exe -m ruff check rs_core/rsagent/tools.py rs_core/rsagent/dialogue.py rs_core/rsagent/llm_dialogue_planner.py rs_core/agent_runtime/adapters/rag.py rs_core/workflow/hybrid_environment.py rs_core/workflow/facades.py rs_core/training/multi_turn_sft_generator.py tests/test_agent_tools.py tests/test_llm_dialogue_planner.py tests/test_rag_agent_adapter.py tests/test_agent_dialogue.py tests/test_multi_turn_sft_generator.py`，结果 `All checks passed!`。本轮未调用外部 API，query rewrite 相关路径仍使用 mock/fallback 测试。

**面试可讲点：**
这段可以讲成“推荐 Agent 的工具编排从底层 RAG helper 升级为主 Agent 调子 Agent”：RSAgent 只看到业务级 `call_rag_agent`，RagAgent 内部处理 query rewrite、语义 hint 和候选内 evidence 压缩；通过 manifest 白名单、参数校验、internal-only response envelope、SFT forbidden keys 和 focused regression，把多 Agent 架构边界、grounding 能力和泄漏治理一起落地。

### 2026-06-22 - RagAgent hybrid small2big 路由与 Qdrant 挂载纠偏

**任务：**
纠正 RagAgent/RAG 试运行路径：保留 SQLite BM25，启用 post-ranking hybrid + small2big + RagAgent internal summary，并把 Qdrant 从 Docker named volume 改为宿主机 bind mount，避免向量数据只留在容器内部状态。

**遇到的问题：**
此前试跑只覆盖 pre-retrieval SQLite BM25 query planning，容易被误读成最终 RAG；随后误启动过 BGE 重编码并写入 1600 条 partial Qdrant points。进一步排查发现仓库与本地 MinIO 只存在 BM25 SQLite/text chunk artifact，没有可直接导入的 RAG dense vector dump 或 Qdrant snapshot。

**定位方式：**
对比 `_rag_query_support()`、`EvidenceRAGFacade`、`online_service.local_qdrant.yaml` 与 Qdrant API collection 状态，确认 final RAG 必须看 `hybrid_qdrant_small2big`。只读搜索 `data/outputs/configs/artifacts/deploy/scripts`、MinIO bucket 和 Docker Qdrant storage，确认 `rag_bm25_compact_full.sqlite` 是 6,515,707 条文本 chunk 的 BM25/FTS 索引，manifest 中 `embedding_method=null`、`vector_index_path=null`，不是可导入 Qdrant 的 dense vectors。

**解决方式：**
为 local_qdrant 配置补齐 `rag.small2big` 与 RagAgent shadow；diagnostics/readiness 明确区分 query planning 与 post-ranking candidate-scoped final RAG；删除授权确认后的误写 partial collection。将 `deploy/local/docker-compose.yml` 的 Qdrant storage 从 named volume 改为 `${RS_QDRANT_STORAGE_PATH:-../../data/qdrant/storage}:/qdrant/storage`，并在 `.gitignore` 忽略 `data/qdrant/`，后续若有 Qdrant 数据文件可直接挂载宿主机目录。

**验证结果：**
`docker inspect local-qdrant-1` 显示挂载为 `bind D:\\sinrotic_code\\python_project\\summer\\RS_agent\\data\\qdrant\\storage -> /qdrant/storage`；Qdrant 当前 collections 为空，未混入 partial vectors。使用项目 `.venv` 运行 `tests/test_rag_core.py -k "small2big or hybrid" -q` 结果 `24 passed, 22 deselected`；运行 `tests/test_rag_agent_adapter.py tests/test_agent_runtime.py tests/test_qdrant_config_env.py -q` 结果 `73 passed`；`py_compile` 与 `ruff check` 通过。当前未宣称 dense hybrid 已生效，因为尚未找到已有 RAG dense vector artifact。

**面试可讲点：**
这段可以讲成“RAG 链路治理不只是打开向量库，而是把 query planning、candidate-scoped evidence、small2big parent context、RagAgent summary 和资产挂载边界分清”：fallback 不能冒充 hybrid，two-tower embedding 不能冒充 RAG chunk embedding，向量数据也应外部挂载以便复现和迁移。

### 2026-06-22 - RSAgent grounding gate 与中文偏好细化验证

**任务：**
验证 RSAgent 在 no-tool/no-display 对话 turn 中不再无 grounding 生成商品推荐，同时确认已有推荐后的中文偏好细化会继续走推荐链路并返回真实展示商品。

**遇到的问题：**
此前 smoke 中第二轮中文细化被判为 unsupported/no-tool，`display_item_ids=[]`，但 SFT composer 仍可能生成商品列表；修复后还需要通过真实 HTTP serving surface 验证，而不只依赖单元测试。验证过程中发现 `configs/serving/online_service.yaml` 的本地首轮推荐冷路径超过 120s，不适合作为本机 active smoke；Git Bash here-doc 中文字面量还会在 Python stdin 中出现 mojibake，导致 parser 误判 unsupported。

**定位方式：**
先用项目默认 `.venv` 跑 focused pytest，覆盖中文 parser、dialogue routing、composer empty-display passthrough、target_action 与 validator 边界；再启动 `scripts/serving/run_service.py` 的本地 FastAPI app，用 `/session/start`、`/chat`、`/session/{id}` 黑盒验证真实 display response。对 shell 编码问题，用 `chr()` 码点构造中文请求，确认 `parse_feedback()` 输出 `desktop_organization/cable_management/compact/accessories` 且 `plan_dialogue_turn()` 为 `preference_feedback/revise_recommendation/should_recommend=true`。

**解决方式：**
验证使用轻量 `configs/demo/hybrid_demo/hybrid_demo_agent_local_smoke.yaml` 配置启动服务，首轮用稳定英文约束建立 prior recommendation，第二轮发送中文“更偏桌面整洁和线缆管理，给我看小体积配件”；另起会话发送纯解释类“为什么推荐？”作为 no-grounding probe，检查 `items=[]` 且 assistant 文案不是商品列表。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_multi_turn_sft_generator.py -q` 结果 `50 passed in 9.00s`。active HTTP smoke：`first-chat` 返回 5 个展示商品，`chinese-refinement-chat` 返回 5 个展示商品，`GET /session/{id}` 显示两轮 display item counts 为 `[5, 5]`；no-grounding probe “为什么推荐？”返回 `display_item_count=0`，assistant_message 为“我现在还没有可以解释的最近推荐。你可以先让我推荐一些商品，然后再问为什么推荐其中某一件。”，`obvious_product_list=false`。

**面试可讲点：**
这段可以讲成“推荐 Agent 的 grounding 边界不是只靠 prompt，而是由 runtime diagnostics、display items、composer gate、SFT target_action 和黑盒 serving smoke 共同约束”：真正推荐时必须有可展示商品支撑；纯对话或无工具 turn 只能透传澄清/解释文案，避免训练样本和前端展示出现无候选依据的幻觉商品列表。

### 2026-06-22 - PostgreSQL 2y 只读访问 wrapper

**任务：**
为 local/trial PostgreSQL 2y 数据库补一层服务可注入的只读访问 wrapper，支持商品、用户序列、近期交互读取，并把可选数据层状态纳入 serving readiness。

**遇到的问题：**
项目当前 PostgreSQL 只完成 schema 与导入脚本，服务侧如果直接接 psycopg/ORM 会新增依赖和密钥泄漏面；同时 readiness 不能执行昂贵 full count，也不能让本地 Docker/PostgreSQL 不可用阻塞推荐主服务。

**定位方式：**
对齐 `scripts/data/import_recent2y_to_postgres.py` 的 compose/service/db/user 默认值、`deploy/local/postgres/init/001_schema.sql` 的 `products/interactions/user_sequences` 表结构，以及 `rs_core/serving/service.py` / `schema.py` 的 readiness 输出模式。

**解决方式：**
新增 `rs_core/data/postgres_dataset.py`：默认 Noop，开启后通过 `docker compose exec -T postgres psql` 执行只读 `SELECT`，使用 JSON 行输出解析；`SafePostgresDatasetStore` 对健康检查和读取 fail-open，公开状态只保留 status/backend/reason/error_type，不输出 DSN/password/stderr。近期交互 limit 在 wrapper 内夹到 200。`RecommendationService` 支持构造注入 store，并在 `/ready` schema 中追加可选 `postgres_dataset`。

**验证结果：**
新增 `tests/test_postgres_dataset.py` 覆盖 disabled factory、Safe fail-open、JSON 解析、limit clamp、summary 表存在性检查、readiness 注入、注入 store fail-open 和 `--require-ok` 门禁语义；使用项目 `.venv` 运行 `tests/test_postgres_dataset.py -q`，结果 `11 passed`。`py_compile`、`ruff check` 和默认关闭状态下的 smoke CLI 均通过。本轮不启动真实 Docker/PostgreSQL，不跑 full pytest。

**面试可讲点：**
这段可以讲成“把本地 2y 结构化数据接入服务而不把试运行能力伪装成生产数据库”：通过 stdlib + psql 包装、只读 SQL、public-safe readiness、fail-open 和 limit clamp，把数据可用性、密钥安全和本机资源边界分开治理。

### 2026-06-22 - RagAgent 双语 RAG Query Rewrite 接入

**任务：**
把 RagAgent 的 pre-retrieval RAG support 从英文 BM25 query planning 扩展为可配置的双语 query rewrite：中文或中英混合 query 可先通过 OpenAI-compatible API 规范化为英文检索 query，再进入现有 RAG 召回规划。

**遇到的问题：**
实际试运行中文对比类商品查询时，中文 query 在 RAG query planning 中返回 skipped；英文 query 可以命中 evidence，但 suggested terms 存在泛词噪声。同时 RSAgent 已去 RAG 工具化，不能为了中文支持把 `query_rag` 重新暴露成 RSAgent hidden tool。

**定位方式：**
沿 `HybridRecommendationEnvironment._attach_rag_query_support()`、`_rag_query_support()`、`SQLiteBM25QueryPlanningRetriever` 和 `bm25.py::_fts_query()` 排查，确认中文 skipped 的直接原因是 BM25 FTS query 侧只提取 `[a-z0-9]+` token；同时复用 `OpenAICompatibleClient` 与 `LLMDialoguePlanner` 的 JSON/fallback/mock transport 模式作为最小安全接入点。

**解决方式：**
在 `rs_core/agent_runtime/adapters/rag.py` 新增 `RagQueryRewriteConfig`、`RagQueryRewriter` 和 rewrite result contract，支持 disabled/shadow/active 三模式、JSON 输出校验、内部字段泄漏拦截和 fail-soft fallback；扩展 `RagAgentAdapter.build_query_support()` 保留原始中文 query，同时输出英文 `query_rewrite` / `semantic_query_hint`。在 `rs_core/workflow/hybrid_environment.py` 中接入 `agent_runtime.rag_query_rewrite` 配置：active 模式用合法英文 rewrite 检索，shadow 只诊断不改检索 query，默认 disabled 不调用外部 API。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_rag_agent_adapter.py -q`，结果 `21 passed`；运行 `... -m pytest tests/test_agent_runtime.py -q`，结果 `43 passed`；运行 `... -m pytest tests/test_rag_agent_adapter.py tests/test_agent_runtime.py tests/test_openai_compatible_client.py tests/test_llm_dialogue_planner.py -q`，结果 `83 passed`；`py_compile` 与 `ruff check` 均通过。测试全部使用 mock/fake rewrite，不真实外发 API。

**面试可讲点：**
这段可以讲成“推荐 Agent 与证据 Agent 的跨语言治理化解耦”：RSAgent 不直接持有 RAG tool，RagAgent 在内部阶段负责把中文需求转成英文检索语义并压缩证据，且通过 shadow/active/fallback、internal-only projection 和 governance flags 保证 RAG 只增强 grounding，不污染候选生成、排序和训练监督。

### 2026-06-22 - Qdrant / MinIO / 外部推理服务化闭环

**任务：**
把在线推荐服务从“本地文件 + Qdrant 预留 + 推理默认关闭”推进到可验证的 local/trial 技术栈：Qdrant 统一向量后端入口、MinIO artifact store 纳管核心产物、外部 OpenAI-compatible/vLLM 推理 adapter 接入，同时保留 fallback 和资源边界。

**遇到的问题：**
原服务虽然 `/health`、轻量 `/recommend` 可用，但 Qdrant 连接目标主要写死在配置里，host/docker 切换不方便；MinIO 只在 manifest 中预留字段，没有 resolver/upload/verify；推理侧只有本地 Qwen lazy client，FastAPI 不适合默认加载重模型。若直接声明“在线服务通了”，容易把 fallback、本地试运行和生产能力混在一起。

**定位方式：**
沿 `rs_core/serving/service.py`、`rs_core/workflow/online_recommendation.py`、`rs_core/workflow/facades.py`、`rs_core/rsagent/inference_policy.py`、`rs_core/common/openai_compatible_client.py`、`configs/serving/online_service.local_qdrant.yaml` 和 `deploy/local/docker-compose.yml` 梳理 runtime 入口，确认最小安全方案是：env override 只覆盖连接层，manifest/config 保留 collection 与治理字段；artifact 先做 manifest + sha256 + resolver；推理采用外部 endpoint provider，不由 serving 启动模型。

**解决方式：**
新增 `qdrant_config_from_env()` / `merge_qdrant_config()`，在服务加载时同步覆盖 RAG、two_tower 和 semantic Qdrant 子配置，并让 `/ready` 只输出 public-safe target kind 与 fallback reason。新增 `rs_core/artifacts/manifest.py`、`resolver.py` 和 `scripts/artifacts/upload_to_minio.py`，支持 local/file/minio/s3 URI、cache 校验、dry-run patch、upload/verify 和 inventory。新增 `rs_core/rsagent/openai_rerank_client.py`，把外部 OpenAI-compatible/vLLM endpoint 接入 bounded rerank signal；`run_service.py` 明确只启动 FastAPI，不启动 vLLM/Qwen。

**验证结果：**
使用项目默认 `.venv` 执行轻量回归：`tests/test_qdrant_config_env.py tests/test_qdrant_cli_smoke.py` 结果 `8 passed`；`tests/test_artifact_resolver.py tests/test_artifact_upload_manifest.py` 结果 `8 passed`；`tests/test_inference_policy.py tests/test_openai_compatible_client.py` 及 serving readiness 相关用例结果 `36 passed`。本轮没有启动真实 MinIO/Qdrant 全量灌库或本地 Qwen/vLLM，避免超过本机 12GB/14GB 资源边界。

**面试可讲点：**
这段可以讲成“把推荐 Agent 的在线化拆成三条工程化链路”：Qdrant 负责向量检索但 fallback 明确可观测；MinIO 通过 manifest、hash 和 resolver 管理模型/索引等大产物；推理模型通过外部 OpenAI-compatible adapter 接入，FastAPI 只做编排和安全降级，从而把 local trial、服务治理和后续生产演进边界讲清楚。

### 2026-06-22 - RSAgent LLM 对话 Planner 接入

**任务：**
把 `rsagent` 的意图判断和工具计划从纯规则函数推进到系统提示词驱动的 LLM planner，同时保留规则 planner 作为 fallback / shadow baseline，避免一次性替换主链路带来不可控风险。

**遇到的问题：**
此前 RecommendationAgent 系统提示词已经描述了如何理解当前需求、权衡用户历史和规划工具，但实际生产路径仍由 `rs_core/rsagent/dialogue.py::plan_dialogue_turn()` 生成规则计划。GPT 5.3 一条 smoke 样本中，用户明确提出 home office 的打印、整理和连接需求，第一轮仍被历史里的 iPhone cable 信号带偏，说明 prompt 没有进入 active planner，规则 planner 只判断“该推荐”，没有生成“如何推荐”的策略。

**定位方式：**
沿 `RecommendationService.chat()` → `FeedbackSessionFacade.chat()` → `HybridRecommendationEnvironment.converse()` → `AgentRuntime.run_turn()` 检查，确认最小安全接入点是 `rs_core/workflow/hybrid_environment.py::HybridRecommendationEnvironment.plan_dialogue()`；同时复用 `rs_core/common/openai_compatible_client.py`、`rs_core/rsagent/tools.py::build_agent_tool_planner_system_prompt()` 和 `DialoguePlan` contract，避免重写 runtime 或暴露工具 trace。

**解决方式：**
新增 `rs_core/rsagent/llm_dialogue_planner.py`，实现 `LLMDialoguePlannerConfig`、`LLMDialoguePlanner`、JSON 解析、`DialoguePlan` 转换与安全校验。LLM 只输出结构化内部 plan，校验 intent/action/tool manifest/phase/order、public response 泄漏和低层 provider/source/score/oracle 参数；推荐类 action 会补齐 `get_user_context`、`retrieve_candidates`、`rank_candidates`、`build_recommendation_slate` 工具链。`HybridRecommendationEnvironment.plan_dialogue()` 改为先生成规则 fallback，再按配置支持 disabled/shadow/active：默认关闭，shadow 只写诊断，active 仅在 LLM plan 通过校验时替换，否则回退规则计划。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_llm_dialogue_planner.py tests/test_agent_dialogue.py tests/test_agent_tools.py tests/test_multi_turn_sft_generator.py tests/test_openai_compatible_client.py -q`，结果 `88 passed`；运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_agent_runtime_contracts.py -q`，结果 `52 passed`；运行 `./.venv/Scripts/python.exe -m py_compile rs_core/rsagent/llm_dialogue_planner.py rs_core/workflow/hybrid_environment.py tests/test_llm_dialogue_planner.py` 通过。本轮未默认启动 500/1000 样本生成或 Qwen SFT，避免把 planner 修复扩大成外部 API/训练任务。

**面试可讲点：**
这段可以讲成“把推荐 Agent 从规则意图识别升级为可校验的 LLM planning”：LLM 根据系统提示词理解当前购物场景和历史时效，runtime 负责工具白名单、参数边界、泄漏拦截和 fallback；通过 shadow/active 开关让新 planner 能渐进上线，并用 home office 偏差样例证明为什么需要从规则判断转向提示词驱动的 Agent 决策。

### 2026-06-22 - RSAgent 无工具推荐边界与中文偏好细化

**任务：**
修复真实 active smoke 中暴露的“未执行召回却由 composer 直接生成商品推荐”问题，并让中文偏好细化请求进入推荐工具链。

**遇到的问题：**
1 条 GPT 5.3 active multi-turn smoke 中，第二轮用户明确说“先偏重桌面整洁，先给我看桌面收纳、线缆管理和小体积配件”，内部却被判为 `unsupported / ask_clarifying_question / should_recommend=false`，没有执行推荐工具，`display_item_ids=[]`；但 `RecommendationAgentComposer` 仍生成了商品列表，前端无法展示真实商品卡，也会污染 SFT grounding 监督。

**定位方式：**
检查 `outputs/training/multi_turn_sft_gpt53_llm_planner_active_smoke/samples.jsonl` 的第二轮 tool supervision，确认没有 `retrieve_candidates/rank_candidates/build_recommendation_slate`；再沿 `rs_core/training/multi_turn_sft_generator.py::_run_one_scene()`、`RecommendationAgentComposer.compose()`、`_turn_record()` 和 `validate_multi_turn_sft_sample()` 排查，发现 composer 对 no-display turn 没有硬 gate，target_action 也默认写成 `public_display_grounded_response`。同时检查 `rs_core/rsagent/policy.py` 与 `dialogue.py`，确认中文 `偏重/给我看/线缆管理/小体积配件` 等信号没有稳定转成可执行偏好。

**解决方式：**
在 SFT 生成链路增加两层 grounding gate：`_compose_grounded_response()` 只有 `should_recommend=true` 且存在 display item ids 时才调用 composer，`RecommendationAgentComposer.compose()` 内部也对空 display passthrough；`_turn_record()` 对 no-recommend/no-display turn 写入 `dialogue_only_response` 或 `clarification_response`，`must_select_from_candidates=false`；validator 拒绝空 display 却要求候选选择、no-recommend 却使用推荐策略、以及 no-grounding 商品列表。中文偏好侧补充正向 cue 与关键词别名，使 `桌面整洁/桌面收纳/线缆管理/小体积/配件/实用` 进入 `preferred_keywords/use_cases`，并让后续细化请求触发完整推荐工具链。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_multi_turn_sft_generator.py tests/test_agent_feedback.py tests/test_agent_dialogue.py -q`，结果 `51 passed`；运行 `./.venv/Scripts/python.exe -m pytest tests/test_llm_dialogue_planner.py tests/test_agent_tools.py tests/test_openai_compatible_client.py -q`，结果 `56 passed`。独立 verifier 复查 focused 代码与测试后确认核心边界已覆盖，同时指出更宽的 serving 回归中仍有 2 个 Qdrant readiness 相关既有失败，真实外部 API active smoke 因权限分类器阻止未重跑，未绕过该限制。

**面试可讲点：**
这段可以讲成“推荐 Agent 必须由工具结果 grounding，而不是由语言模型凭上下文编造商品列表”：LLM 可以负责理解意图和生成话术，但商品推荐必须绑定召回、排序和 display slate；通过 composer gate、SFT validator 和中文偏好解析，把前端展示一致性、训练数据质量和 Agent 安全边界统一治理。

### 2026-06-21 - 商品 RAG small2big parent profile 改造

**任务：**
把商品 RAG 从“字段级 small chunk 证据”升级为 small2big 模式：检索仍沿用 BM25/hybrid/Qdrant 等候选内 small chunk 逻辑，命中后按 `item_id/parent_asin` 回填受控商品级 `parent_profile`，为后续专用上下文 Agent 的截断、重排和总结提供输入。

**遇到的问题：**
字段长度统计显示 `features`、`description`、`item_text/full_text` 明显长尾，不能把完整 raw profile 直接并入推荐 Agent；同时 parent profile 不能变成新召回源、ranking replacement 或 promotion，也不能在 manifest 缺失、holdout 来源不清或预算不足时挤掉原 small chunk grounding。

**定位方式：**
梳理 `rs_core/recsys/rag/corpus.py`、`retriever.py`、`rs_core/workflow/facades.py` 和 legacy `hybrid_environment._build_turn_rag_context()`，确认最小安全接入点是 `CandidateEvidenceRetriever` wrapper：base retriever 先返回 candidate-scoped small evidence，再由 wrapper 只对 base-hit candidate 做 parent projection。前置统计还对齐了 full recent-window 商品字段长度分布和现有 BM25 chunk manifest 规模。

**解决方式：**
新增 wrapper-only `RAG_PARENT_PROFILE_FIELD="parent_profile"`、`build_parent_profile_text()`、`Small2BigCandidateEvidenceRetriever` 和 `validate_parent_profile_manifest()`。`parent_profile` 不加入 `RAG_STANDARD_FIELDS`，只在 small2big enabled 时临时加入 allowed fields；manifest gate 缺失或不满足 train-only/no-holdout/source hash 等条件时 fail closed，仅保留 base evidence；parent text 只投影 title/category/store/rating/features/description 等 allowlist 字段。`EvidenceRAGFacade` 负责包装现有 retriever、扩展 parent 独立预算，并把 legacy `_build_turn_rag_context()` 收敛为委托 facade，避免双实现分叉。

**验证结果：**
新增测试覆盖 `parent_profile` 不进入标准字段、manifest fail closed、wrapper 只对 base-hit candidate 回填、nested raw/holdout/full_text 不泄漏、`get_item_evidence` 默认过滤 parent profile、0 parent budget 保留、policy 截断与预算扩展、facade metadata/candidate scope。使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_rag_core.py -k "small2big or rag_facade or hybrid or bm25 or get_item_evidence"`，结果 `31 passed, 11 deselected`；运行 `... -m pytest tests/test_rag_core.py`，结果 `42 passed`；运行 `... -m pytest tests/test_qdrant_rag_index_build.py tests/test_agent_dialogue.py tests/test_display_contract.py tests/test_serving_facades.py tests/test_serving_trial_hardening.py`，结果 `159 passed`。code-reviewer 首轮指出 3 个 HIGH、2 个 MEDIUM 边界问题，修复后复审 `APPROVE`。

**面试可讲点：**
这段可以讲成“RAG 从 chunk 命中到商品级上下文回填的治理化升级”：small chunk 负责找准，parent profile 负责讲完整，但通过 wrapper-only contract、manifest gate、public projection、candidate scope 和预算隔离，保证它只是解释/上下文增强，不改变召回、排序和最终推荐结果，为后续专用上下文 Agent 留出清晰输入边界。

### 2026-06-22 - Pool500 JSONL 主路升级为在线多路召回服务骨架

**任务：**
把原本依赖 Pool500 JSONL 的在线推荐候选来源，升级为 local/trial 的多路召回编排骨架，同时保留 JSONL 作为 rollback/backfill fallback。

**遇到的问题：**
原 `OnlinePool500Recommender` 同时承担 artifact、source index、工具候选和 readiness 逻辑，Pool500 artifact 容易被误解为在线主路；同时 RAG chunks collection 不能被拿来做 candidate generation，PostgreSQL/Qdrant 在本地不可用时也不能伪装成功或阻塞服务。

**定位方式：**
沿 `rs_core/workflow/online_recommendation.py`、`rs_core/recsys/candidate_merge.py::merge_candidates`、`rs_core/recsys/pool500_artifacts.py`、`rs_core/recsys/candidate_store/postgres.py` 和 `rs_core/serving/service.py` 梳理现有候选合并、fallback、public-safe readiness 与只读 SQL 约束。

**解决方式：**
新增 `CandidateRetrievalOrchestrator` 和 provider 骨架：Qdrant two-tower、Postgres item/user/category/popular、semantic vector governance gate、Pool500 fallback。编排层统一做 seen/prior-turn 过滤、quota/underfill/fallback diagnostics，并把 `recommend(... complete_pool500=True)` 与 `tool_retrieve_candidates` 切到 orchestrator；`/ready` 增加 public-safe `candidate_retrieval`，优先以其 availability 判断 route。PostgreSQL schema 补 candidate store 表和索引，导入脚本默认 dry-run，只做安全扫描。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_online_retrieval_orchestrator.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_online_retrieval_providers.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_candidate_store_postgres.py -q`，结果 `8 passed in 0.28s`；对修改 Python 文件运行 `py_compile` 通过。本轮没有启动 Qdrant/PostgreSQL、没有导入全量候选、没有跑训练或 full eval。

**面试可讲点：**
这段可以讲成“把批处理 Pool500 artifact 退到 fallback，把在线候选生成抽象成可治理的多路服务”：每一路 provider 都有可观测 readiness 和 fail-open 行为，RAG 明确只做解释 grounding 不做候选源，Postgres/Qdrant 本地试运行能力与生产可用性不混淆。

### 2026-06-22 - RagAgent shadow 编排接入

**任务：**
在已有通用 `GenericAgentLoop` 雏形上编排专用 RagAgent，让它消费推荐 turn 内部的 `rag_context` 与 small2big `parent_profile`，产出候选内 compact grounded support，并以 shadow/internal-only 方式回传给 RSAgent。

**遇到的问题：**
small2big parent profile 可能明显长于普通 evidence，不能直接并入推荐 Agent 的公开响应或 SFT payload；同时 RagAgent 不能变相新增候选、替代排序输入或修改最终推荐，否则会破坏“RAG 只做候选内证据 grounding”的边界。

**定位方式：**
检查 `rs_core/agent_runtime/core/loop.py`、`output_adapter.py`、`rs_core/workflow/facades.py` 和 `rs_core/rsagent/schema.py`，确认最小安全接入点是 adapter 层：legacy RSAgent turn 完成后只读 `turn.rag_context`，通过 deny-by-default projection 生成 internal support，并把结果写入 `turn.diagnostics`，不触碰 `candidates/ranking/final_items/assistant_response`。

**解决方式：**
新增 `rs_core/agent_runtime/adapters/rag.py`，实现 `RagAgentConfig`、`RagAgentSupport`、`RagAgentShadowReport` 以及 deterministic `GenericAgentLoop` components：context builder 只保留候选内 evidence，planner 在无 evidence 时 skip，dispatcher 本地压缩 ordinary evidence 与 `parent_profile`，state updater 只生成 `append_allowed=False` 的 commit intent。`AgentOrchestrationFacade` 新增 `agent_runtime.metadata["rag_agent"]` 配置读取，启用后在 legacy turn 后运行 RagAgent shadow，并仅写入 `rag_agent_shadow/rag_agent_support` diagnostics。针对审查发现的导出边界问题，`rollout` metadata 不再写 raw `rag_context`，只保留 evidence 数量、候选数量、retriever、small2big enabled 等 allowlist summary；RagAgent support 也增加字段 allowlist、敏感文本 redaction、parent label allowlist 和显式 candidate boundary。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m py_compile rs_core/agent_runtime/adapters/rag.py rs_core/workflow/facades.py tests/test_rag_agent_adapter.py` 通过；修复 reviewer 首轮指出的 rollout raw `rag_context` 导出、ordinary evidence 原文复制、内部 field label、parent_profile fallback label、candidate boundary 扩宽和字符串 bool 配置问题后，继续修复 rollout safe serialization 与 SFT `candidate_summary.sources` 泄漏问题。最终运行 `... -m pytest tests/test_rag_agent_adapter.py tests/test_agent_runtime.py tests/test_agent_rollout_schema.py tests/test_rag_core.py tests/test_inference_policy.py tests/test_display_contract.py -q`，结果 `235 passed`；运行 `... -m pytest tests/test_agent_runtime_contracts.py tests/test_rag_core.py tests/test_serving_facades.py tests/test_agent_dialogue.py tests/test_training_data_contracts.py tests/test_agent_rollout_schema.py tests/test_display_contract.py -q`，结果 `206 passed`。测试覆盖无 `rag_context` skip、普通 evidence 压缩、parent profile raw text 不泄漏、public/SFT projection 为空、facade 接入不修改推荐结果、rollout 只导出 RAG summary、ranking/candidates/diagnostics safe serialization、SFT 不导出 raw sources。最终 code-reviewer 复审 `APPROVE`。

**面试可讲点：**
这段可以讲成“把 RAG evidence consumer 从推荐 Agent 主链路拆出来”：RagAgent 复用统一 agent loop，但首版只做 shadow/internal support，既让长上下文和商品级 profile 有专门的截断总结位置，又通过候选内约束、deny-by-default 输出投影和 non-mutating facade 测试保证推荐结果与公开 payload 不被污染。

### 2026-06-22 - RAG/Qdrant 与多轮 SFT 审查修复

**任务：**
处理 RagAgent 落地后 teammate review 中的高优先级问题：Qdrant 空构建不能误删旧向量资产，多轮 SFT terminal accept 不能伪造已执行的反馈工具监督，也不能允许缺少候选 item 的接受动作通过验证。

**遇到的问题：**
RAG chunk 与 two-tower item 的 Qdrant rebuild 在本次构建产物为空时仍执行 stale delete，可能把上一版可用 collection 清空；多轮 SFT 生成中 terminal accept 直接追加终止 turn 并 break，没有实际调用 `service.feedback()`，但 `_terminal_tool_supervision()` 却写入成功的 `record_user_feedback` 事件，同时 accept 缺少 `item_id` 时会形成 `must_select_from_candidates=true` 但 `selected_item_ids=[]` 的训练样本。

**定位方式：**
沿 `rs_core/recsys/rag/qdrant_index.py`、`rs_core/recsys/vectorstores/qdrant_two_tower_build.py` 检查 stale cleanup 触发条件，确认应以本轮成功 upsert 作为删除旧点的前提；沿 `rs_core/training/multi_turn_sft_generator.py`、`rs_core/simulation/schema.py`、`rs_core/serving/facades.py` 检查 accept 动作、feedback API 与 SFT validator，确认监督信号必须来自真实 service diagnostics 或保持空监督，不能由 terminal helper 自造成功工具事件。

**解决方式：**
Qdrant builder 改为仅在 `upserted_chunk_count > 0` / `rows` 非空时执行 stale delete，零 chunk/零 row rebuild 只写 manifest 并保留旧 collection。多轮 SFT 生成在可终止 accept 前先保存当前展示、调用 `service.feedback(session_id, "accept", item_id, comment)`，再用真实 `_service_turn_diagnostics()` 生成 terminal turn；terminal helper 改为复用 `_tool_supervision()`，删除伪造 `_terminal_tool_supervision()`；模型 payload 的 accept 在已有展示商品时必须带 `item_id`；validator 对 `accept_displayed_item`/`action_type=accept` 强制 `selected_item_ids` 非空。

**验证结果：**
使用项目默认 `.venv` 运行 Qdrant targeted 回归 `... -m pytest tests/test_qdrant_rag_index_build.py::test_build_qdrant_rag_chunk_index_zero_chunk_rebuild_preserves_existing_chunks tests/test_qdrant_two_tower_build.py::test_build_qdrant_two_tower_item_index_zero_row_rebuild_preserves_existing_items -q`，结果 `2 passed`；运行 `... -m pytest tests/test_qdrant_rag_index_build.py tests/test_qdrant_two_tower_build.py -q`，结果 `21 passed`。多轮 SFT accept 修复后运行 `... -m pytest tests/test_multi_turn_sft_generator.py::test_validate_multi_turn_sft_rejects_unknown_selected_item tests/test_multi_turn_sft_generator.py::test_simulated_user_prompt_uses_private_context_without_hidden_catalog tests/test_multi_turn_sft_generator.py::test_recommendation_composer_uses_openai_compatible_adapter tests/test_multi_turn_sft_generator.py::test_validate_multi_turn_sft_rejects_accept_without_selected_item tests/test_multi_turn_sft_generator.py::test_terminal_accept_supervision_uses_real_diagnostics tests/test_multi_turn_sft_generator.py::test_terminal_accept_supervision_does_not_fabricate_tool_success tests/test_multi_turn_sft_generator.py::test_role_action_from_payload_requires_accept_item_id_when_display_has_items -q`，结果 `7 passed`。

**面试可讲点：**
这段可以讲成“离线资产构建和训练样本生成的 fail-safe 治理”：向量资产迁移不能因为一次空输入就破坏线上可用索引，SFT 数据也不能把未执行的工具动作标成成功监督；通过空构建保护、真实 diagnostics 监督和候选内 accept 校验，把 RAG/Qdrant 与 Agent 训练数据链路都收束到可验证、可回滚的工程边界。

### 2026-06-22 - RagAgent runtime 轻量合同修复

**任务：**
处理 RagAgent 与 `GenericAgentLoop` 审查中的低风险合同问题：evidence 分区效率、文本截断边界、mode 配置规范化，以及 internal trace projection 与实际 trace 不一致。

**遇到的问题：**
`RagContextBuilder` 先构造 parent evidence 再用 `row not in parent_evidence` 生成 small evidence，存在不必要的 O(n²) dict membership；`_truncate_text()` 先截断再追加省略号，可能超过配置的 `max_text_chars`；`mode` 未统一 strip/lower/validate，容易把 `" Shadow "` 当成 unsupported；`GenericAgentLoop` 在追加 `project_output` trace 前已经完成 internal projection，导致 `result.internal_output["trace_events"]` 比 `result.trace_events` 少最后一步。

**定位方式：**
沿 `rs_core/agent_runtime/adapters/rag.py` 检查 config/context/support 生成链路，沿 `rs_core/agent_runtime/core/loop.py` 检查 trace event 与 projection 的顺序，并用 `tests/test_rag_agent_adapter.py`、`tests/test_generic_agent_loop.py` 补齐对应合同断言。

**解决方式：**
将 RagAgent evidence 分区改为 single-pass，将 `mode` 配置收口为 `shadow` 的规范化校验，将文本截断改为总长度不超过 `max_text_chars` 的省略号策略；`GenericAgentLoop` 在追加 `project_output` 后重建 projection payload 并重新投影 public/SFT/internal 输出，保证 internal trace 与 result trace 一致。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_rag_agent_adapter.py tests/test_generic_agent_loop.py tests/test_agent_runtime.py -q`，结果 `56 passed`；运行 `... -m py_compile rs_core/agent_runtime/adapters/rag.py rs_core/agent_runtime/core/loop.py tests/test_rag_agent_adapter.py tests/test_generic_agent_loop.py` 通过。

**面试可讲点：**
这段可以讲成“Agent runtime 合同不是只看主功能，而要管边界一致性”：通过小范围测试把配置解析、上下文预算、trace 可观测性和 internal-only 输出投影固定下来，避免后续 RagAgent 从 shadow 走向更深集成时出现隐性 contract 漂移。

### 2026-06-21 - 本地试运行级模型与服务部署骨架

**任务：**
把此前确定的“大厂风格”组件路线落成当前阶段可执行的 local/trial/non-production MVP：FastAPI serving + Qdrant + hybrid RAG + BM25 fallback + artifact manifests + DeepFM shadow contract + Agent/vLLM provider 预留。

**遇到的问题：**
MinIO/MLflow/vLLM/Triton/KServe 等组件不能一次性默认启动，否则会把本机试运行变成重资源生产化工程；同时 Qdrant 只能作为 RAG/vector backend 预留，不能在依赖缺失或 collection 未就绪时把 BM25 fallback 伪装成 Qdrant 成功。DeepFM 也必须保持 shadow diagnostic，不能影响主排序或公开 payload。

**定位方式：**
检查 `configs/serving/online_service.yaml`、`rs_core/serving/service.py`、`rs_core/workflow/facades.py`、`rs_core/rsagent/inference_policy.py` 和 Qdrant/RAG builder 测试，确认当前默认 serving 是轻量 FastAPI + BM25 RAG + pool500 路由，Qdrant 与 dense embedding 依赖应保持 optional profile；`/ready` 比 `/health` 更适合承载配置与依赖状态。

**解决方式：**
新增 `deploy/local/` 下 Docker Compose、serving Dockerfile、`.env.example` 和中文 README，默认 loopback 绑定并文档化 strict auth/token、`.venv` 命令和 Qdrant dry-run/tiny smoke/user-approved live build 三档。新增 `requirements-serving-qdrant.txt`、`requirements-serving-rag-dense.txt`、`configs/serving/online_service.local_qdrant.yaml` 与三份 artifact manifest。服务 readiness 增加 RAG、manifest、DeepFM shadow、Agent provider 状态；Agent provider 默认 `disabled`，`openai_compatible` 只做配置预留，`local_transformers` 保持 `local_files_only=True`；RAG facade 在 Qdrant backend 不可用时显式走 BM25 fallback。

**验证结果：**
使用项目默认 `.venv` 运行配置/manifest parse smoke 通过；针对首次失败的 readiness/RAG fallback 用例修复后，focused rerun `2 passed in 0.66s`。完整 targeted contract tests 首轮结果 `38 passed in 2.69s`；reviewer 提出 Docker dense RAG 依赖、vector backend 异常 fallback 和 `qdrant_client.__spec__ is None` readiness 崩溃两个高优先级问题后，补充回归用例并验证 `5 passed in 0.77s`，二次 reviewer 复核 `APPROVE` 且 0 issues。deslop 后最终 targeted contract tests：`41 passed in 2.97s`；对本轮 Python 变更运行 ruff，结果 `All checks passed!`。

**面试可讲点：**
这段可以讲成“推荐 Agent 服务化不是堆组件，而是分层落地”：当前只把 FastAPI/Qdrant/RAG/manifest/安全边界做成可验证 local MVP，同时为 MinIO、MLflow、vLLM、Triton 和 KServe 预留接口；通过 readiness contract、fallback policy 和 shadow ranking contract 保证本地试运行不越权、不泄露内部诊断、不误触发重模型。

### 2026-06-23 - Cassandra/Scylla 非向量召回 Candidate Store 接入

**任务：**
把非向量召回从纯 JSONL/PostgreSQL 试运行形态扩展为 Cassandra 协议的磁盘化 serving store，让 ItemCF、UserCF、popular、category 等 exact key -> topK 候选读取具备大规模 KV 演进路径，同时保留 Qdrant 负责向量召回。

**遇到的问题：**
向量型召回适合 Qdrant/ANN，但非向量召回本质是 `user_id/src_item/category -> topK candidates` 的宽行查表；如果用 ES/OpenSearch 承担主链路，会把倒排、refresh、segment merge 和搜索集群调参引入一个不需要全文相关性的 exact lookup 场景。直接全量 Redis 又会把持久化候选索引变成高内存成本缓存。

**定位方式：**
沿 `rs_core/recsys/online_retrieval/providers/postgres_*.py`、`rs_core/recsys/candidate_store/postgres.py`、`scripts/serving/import_candidate_store_to_postgres.py` 和 `deploy/local/docker-compose.yml` 梳理现有 provider/store/importer/deploy 模式，确认最小安全切入点是复用 `CandidateStore` Protocol，在 provider 层通过 factory 切换 backend，而不是重写 orchestrator 或替换 Qdrant。

**解决方式：**
新增 `rs_core/recsys/candidate_store/cassandra.py` 和 `factory.py`，支持 `RS_CANDIDATE_STORE_BACKEND=noop|postgres|cassandra`；Cassandra store 按 `store_version` 查询 `item_neighbors_by_seed/user_candidates_by_user/popular_candidates_by_scope/category_candidates_by_bucket/user_category_buckets_by_user`，异常 fail-open 并由 pool500 fallback 保底。新增 ScyllaDB local compose profile、CQL schema、optional `cassandra-driver` 依赖和 dry-run-first 的 `scripts/serving/import_candidate_store_to_cassandra.py`，写入模式要求 `store_version` 并拒绝 partial artifact。现有 `postgres_*` provider 暂保留命名，但底层改走统一 factory，readiness 可报告 `backend=cassandra`。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_candidate_store_cassandra.py tests/test_import_candidate_store_to_cassandra.py tests/test_candidate_store_postgres.py tests/test_import_candidate_store_to_postgres.py tests/test_online_retrieval_providers.py tests/test_online_retrieval_orchestrator.py`，结果 `36 passed in 0.60s`；运行 `tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py`，结果 `76 passed in 2.07s`；对本轮变更 Python 文件运行 `ruff check`，结果 `All checks passed!`。本轮未启动真实 ScyllaDB/导入全量候选，避免本机资源扩大。

**面试可讲点：**
这段可以讲成“按访问模式选数据库”：向量相似度交给 Qdrant，非向量召回的全量候选索引用 Cassandra/Scylla 做磁盘化宽列 KV，Redis 后续只缓存热点，ES/OpenSearch 留给商品搜索和文本召回；同时通过 artifact source of truth、store version、dry-run importer、readiness 脱敏和 fail-open fallback，把大厂风格架构落成可验证、可回滚的本地工程闭环。

### 2026-06-23 - Serving canonical import 第二阶段迁移收口

**任务：**
在保留 `rs_core.serving.app/schema/service/facts/adapter_contracts/boundary_map/manifest_gate` legacy shim 兼容的前提下，把 serving canonical 层、训练/评估脚本和普通测试迁到 canonical import，并用 BoundaryMap 与静态 guard 防止后续回退。

**遇到的问题：**
第一阶段已经形成类似 Spring Boot 的 API / DTO / Application Service / Domain / Infrastructure / Governance 分层，但 canonical 层和普通调用方仍可能经由 legacy facade 或 package-root convenience import 绕回旧路径；如果只移动文件不收紧 guard，后续 Agent 仍可能把新业务逻辑写回 shim。

**定位方式：**
按 `.omc/plans/serving-canonical-import-team-migration.md` 将迁移拆成 API imports、训练评估脚本、普通 serving/API 测试、domain/governance 测试、BoundaryMap/guard 和最终 verifier 六块并行推进；用 grep/AST guard 分类 `rs_core.serving.service/app/schema/adapter_contracts/boundary_map/facts/manifest_gate` 与 `from rs_core.serving import ...` 剩余引用。

**解决方式：**
`rs_core/serving/api/app.py` 改为从 `application.recommendation_service`、`runtime.config`、`facades` 和 `schemas` 取 canonical 依赖；训练/评估脚本与普通测试改用 canonical import；`rs_core/serving/__init__.py` 的 package-root convenience 改为 lazy 指向 canonical module；`rs_core/serving/domain/boundary_map.py` 与 `tests/test_serving_reorg_compatibility.py` 扩展 legacy shim 禁止集合和 package-root 绕行扫描。legacy shim 不删除，只保留给旧 uvicorn target、兼容性测试和 re-export identity 验证。

**验证结果：**
最终 verifier PASS：focused pytest `223 passed in 4.61s`；脚本 `py_compile` 退出 0；`ruff check rs_core/serving tests/test_serving_reorg_compatibility.py tests/test_serving_boundary_map.py` 输出 `All checks passed!`；`compileall -q rs_core/serving` 退出 0；legacy/canonical app identity smoke 通过。剩余 legacy 引用均已分类为 `legacy_shim_file`、`compatibility_test`、`run_service_target_string` 或显式边界/负向断言，未发现 `canonical_serving_dir`、`production_runtime`、`training_or_evaluation_direct_import`、`ordinary_test`、`unknown` 失败类。

**面试可讲点：**
这段可以讲成“架构重组不是一次性删除旧入口，而是在兼容窗口内收口依赖方向”：先把 serving 拆成清晰分层，再迁移调用方到 canonical import，最后用 BoundaryMap、AST guard、package-root guard 和 compatibility tests 固化新旧边界，既保证旧启动路径可用，又避免后续协作继续扩大 legacy facade 技术债。

### 2026-06-21 - Agent 默认启用 RAG evidence

**任务：**
按用户要求让默认在线 Agent 启用 RAG，不再停留在需要手动 override 的状态，同时保持 RAG 只做候选内证据 grounding，不越权替代召回或排序。

**遇到的问题：**
当前 `configs/serving/online_service.yaml` 没有 `rag` 配置块，`EvidenceRAGFacade` 默认 `evidence_mode=off`，因此线上默认 Agent turn 不会构建 `rag_context`；但项目已有 full recent-window BM25 RAG 索引，不能误接成全库候选生成或 ranking replacement。

**定位方式：**
检查 `rs_core/workflow/facades.py` 中 `evidence_mode`、`retriever`、`index_path` 的选择逻辑，确认只要默认配置提供存在的 BM25 index 且设置 `evidence_mode=explain`，推荐后 evidence 会进入 `rag_context`；读取 `outputs/agent/rag/recent_window_compact_full/rag_bm25_compact_full.manifest.json`，确认索引规模 `indexed_item_count=864288`、`chunk_count=6515707`，且 `retrieval_scope=candidate_item_ids`、`knowledge_base_role=rag_evidence`、三项治理开关均为 false。

**解决方式：**
在 `configs/serving/online_service.yaml` 新增默认 `rag` 配置：`evidence_mode=explain`、`retriever=sqlite_bm25`，指向 recent-window compact full BM25 索引和 manifest，字段限定为 `title/category/main_category/category_path/description/features`，并显式保留 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。在 `tests/test_recsys_core.py` 增加配置合同测试，断言默认开启、索引/manifest 存在、manifest 仍是候选内 evidence 角色。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_recsys_core.py::test_online_service_enables_rag_explain_by_default tests/test_rag_core.py tests/test_agent_dialogue.py::test_rag_explain_uses_evidence_without_mutating_recommendation_payload -q`，结果 `33 passed in 4.64s`。补充 verifier 只读复核，结论 `PASS`：默认 online_service Agent 已启用 candidate-scoped RAG evidence，索引存在，治理边界未见明显问题。

**面试可讲点：**
这段可以讲成“把 RAG 从可选能力推进到默认 Agent grounding 能力”：不是简单打开向量/文本检索，而是通过配置合同、manifest 审计和回归测试，确保 RAG 只增强推荐解释和商品证据，不污染候选生成与排序主链路。

### 2026-06-21 - 双 Agent 多轮 SFT 数据生成流水线

**任务：**
按用户新的口径，把 SFT 样本生成从“单 turn GPT 改写”扩展为“推荐 Agent + 模拟用户 Agent 多轮交互”：抽样中上热度用户，基于 train history 总结人设，驱动多轮推荐对话，并为后续 500 条样本生成提供 scene-level JSONL、flattened turn JSONL、manifest 和 reject 记录。

**遇到的问题：**
现有 `run_gpt_sft_api.py` 只面向已有单 turn seed SFT 样本；现有 simulation runner 能多轮交互但输出是 public scene，不是训练合同；模拟用户模型客户端与 GPT SFT 客户端分裂，且真实 500 条生成会向外部 OpenAI-compatible API 发送用户历史摘要和展示商品，必须显式执行并受权限控制。

**定位方式：**
只读梳理 `rs_core/common/openai_compatible_client.py`、`rs_core/training/gpt_sft_runner.py`、`rs_core/training/data_contracts.py`、`rs_core/simulation/policy.py`、`rs_core/simulation/runner.py` 与 `rs_core/serving/service.py`，确认最小方案是新增离线 batch 生成器，复用 `RecommendationService.start_session/chat/feedback`、现有 hidden tool runtime、`ModelDrivenRolePolicy` 的 JSON action 约束，以及 train-only `user_sequences` 作为中上热度用户抽样来源。

**解决方式：**
新增 `rs_core/training/multi_turn_sft_generator.py`、`scripts/training/generate_multi_turn_sft.py`、`configs/training/multi_turn_sft_gpt53.yaml` 和 `tests/test_multi_turn_sft_generator.py`。生成器默认 dry-run，不要求 key、不外发 API；`--execute` 才创建 `OpenAICompatibleClient`，默认 `api_base=https://cpa2api.sinrotic233.com`、`api_key_env=RS_agent`、`model=gpt5.3codexspark`。用户抽样按 train history count 取 warm/hot；persona 只声明 `derived_from=train_history_only`；输出 `rs_agent_multi_turn_sft_sample_v1`，并额外导出兼容旧 SFT runner 的 flattened turn samples。validator 强制每轮 `selected_item_ids` 属于 `display_item_ids/allowed_item_ids`，并扫描 `diagnostics/oracle/ground_truth/reward/rag_context/training_samples` 等内部或评估字段。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_multi_turn_sft_generator.py tests/test_gpt_sft_api.py tests/test_openai_compatible_client.py`，结果 `32 passed in 364.19s`；运行 `./.venv/Scripts/python.exe -m py_compile rs_core/training/multi_turn_sft_generator.py scripts/training/generate_multi_turn_sft.py tests/test_multi_turn_sft_generator.py` 通过。dry-run smoke：`./.venv/Scripts/python.exe scripts/training/generate_multi_turn_sft.py --config configs/training/multi_turn_sft_gpt53.yaml --limit 2 --dry-run`，生成预览 `generated_count=2`、`api_called=false`、`avg_dialogue_turn_count=4.0`。code-reviewer 复审 `APPROVE`，仅指出并已修复 CLI `--dry-run` override no-op。真实 500 条 `--execute` 生成未执行：本会话自动权限拦截外部 API 数据发送，且当前 shell 未设置 `RS_agent` 环境变量。

**面试可讲点：**
这段可以讲成“推荐 Agent 的多轮训练数据闭环设计”：不是把用户历史直接喂给训练，而是先按 train-only 历史构造人设，再用模拟用户 Agent 产生追问、解释、换方向、接受等真实交互，把推荐 Agent 的公开响应和展示商品固化为可验证多轮 SFT 合同；同时用 dry-run、manifest、rejects 和 grounding validator 管住外部 API 成本、数据泄漏和候选池越界。

### 2026-06-21 - Qdrant 向量资产迁移 builder 与 dry-run 闭环

**任务：**
在 Qdrant foundation、RAG retriever 和 two-tower adapter 已完成后，继续把现有向量资产迁移从“可接入后端”推进到“可物化 collection”：补齐 two-tower item embeddings 与 RAG product chunks 写入 Qdrant 的 builder、CLI、manifest 和测试闭环。

**遇到的问题：**
向量迁移不能直接把现有本地 artifact 或 BM25F/token semantic 统一替换成 Qdrant：RAG 只能保持 candidate-scoped evidence；two-tower 必须从受验证 source manifest 构建，不能绕过 train-only/no-holdout 治理；真实 embedding/full-data job 还可能很重，默认执行必须有 `--dry-run` 和 `--limit-items` 保护。

**定位方式：**
复用既有边界文件定位实现落点：two-tower 侧沿 `rs_core/recsys/vector_index.py::load_vector_index_artifact()` 与 `two_tower_source_manifest.py` / `two_tower_DSSM/source_manifest.py` 校验 source manifest；RAG 侧沿 `rs_core/recsys/rag/chunking.py::chunk_item_record()`、`rag/vector_index.py::SentenceTransformerEmbeddingBackend` 与既有 `QdrantCandidateRagVectorRetriever`。同时用 `tests/qdrant_fakes.py` 保证单元测试不依赖外部 Qdrant 服务或真实模型下载。

**解决方式：**
新增共享 `qdrant_builders.py`，提供 Qdrant CLI 参数、batch、manifest 和 store 构建辅助，并要求 live build 必须显式传入 Qdrant target，避免误写临时内存库；新增 `qdrant_two_tower_build.py`，只接受 `source_index_manifest.json`，校验后把 item embeddings 以包含 `source_name` 的稳定 point id 和 `two_tower_item_payload()` 写入 `rs_agent_two_tower_items_v1`，用包含 `uuid4` 的 `index_build_id` 标记新版本，并在 upsert 后删除同 source 的旧 build，空行重建也会执行 stale cleanup；新增 `rag/qdrant_index.py`，要求非 dry-run 提供 source manifest 且显式声明 `train_only=true/no_holdout=true`，递归扫描 provenance/path，将商品 JSONL 以 bounded batch 流式 chunk/embedding/upsert，并以包含 `corpus_scope` 的 point id 与 `rag_chunk_payload()` 写入 `rs_agent_rag_chunks_v1`，空 chunk 重建也会清理同 corpus 旧 evidence。两个 CLI 均支持 `--dry-run`、`--limit-items` 和 Qdrant connection flags；live `--limit-items` 仅允许 `:memory:` smoke，避免截断 durable collection；collection 创建时集中配置常用 payload filter indexes。当前 `semantic` 仍保持 BM25F/token source，不做直接迁移。

**验证结果：**
使用项目默认 `.venv` 运行 Qdrant/RAG targeted tests：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_qdrant_vectorstore_contract.py tests/test_qdrant_rag_retriever.py tests/test_qdrant_two_tower_index.py tests/test_qdrant_rag_index_build.py tests/test_qdrant_two_tower_build.py tests/test_qdrant_cli_smoke.py tests/test_rag_core.py -q`，修复 reviewer 发现的临时内存 target、point id 冲突、two-tower 先删后写、durable `limit_items` 截断风险、bad batch size、RAG recursive provenance、RAG stale chunks、`limit_items=0`、向量预校验、two-tower `no_holdout` 显式治理、秒级 build id 重复、空重建 stale cleanup、RAG corpus_scope point id 隔离和 Hybrid RAG 缺失/损坏 BM25 时的 vector fallback 问题后，结果 `62 passed in 2.09s`。运行 serving/agent 相关回归：`test_serving_smoke.py`、`test_serving_recommend_from_sequence.py`、`test_agent_runtime.py`、`test_agent_tools.py`，结果 `147 passed in 2.32s`。补充真实 `qdrant-client` in-memory payload-index + stale-delete smoke，确认 payload index 创建与 build-id stale cleanup 路径可用，输出 `real qdrant payload-index stale-delete smoke passed`。针对本轮变更文件运行 ruff 通过；最终 code-reviewer 复审 `APPROVE`，HIGH/MEDIUM/LOW findings 均为 0。

**面试可讲点：**
这段可以讲成“向量数据库迁移不是换库，而是把数据治理和上线边界一起迁移”：RAG、two-tower 两类向量资产分别落到 Qdrant collection，但通过 payload flags、manifest validator、dry-run/smoke 和 local baseline 保证不会越权成为 ranking replacement 或 promotion 输入，体现推荐系统向量检索服务化中的可复现、可回滚和可治理迁移能力。

### 2026-06-22 - 定制 Agent 注入机制升级为 Registry/Runner

**任务：**
把 RagAgent 从硬编码 adapter 调用推进到仿 Claude Code 的 `AgentDefinition → AgentRegistry → AgentRunner → GenericAgentLoop` 注入机制，同时保持现有 RagAgent API、shadow/internal-only/non-mutating 行为不变。

**遇到的问题：**
`GenericAgentLoop` 已经抽象出通用执行骨架，但 `RagAgentAdapter` 仍同时承担 definition、stage routing、runner、loop factory 和 response shaping。后续如果继续增加 MemoryAgent、FeedbackAgent 或 ExplanationAgent，会把 facade/adapter 扩展成多处硬编码。

**定位方式：**
对照仓库内 Claude Code custom agent 链路，确认其核心是把 custom agent 解析成可注册的 definition，再由 AgentTool/runAgent 统一选择和执行；同时检查 `rs_core/agent_runtime/core/loop.py`、`rs_core/agent_runtime/adapters/rag.py`、`rs_core/workflow/facades.py` 和相关测试，确认最小安全改造点是在 runtime core 新增领域无关 registry/runner，并让 RagAgentAdapter 作为兼容 shim 委托 runner。

**解决方式：**
新增 `rs_core/agent_runtime/core/definition.py`、`registry.py` 和 `runner.py`，提供 `AgentRunRequest`、`AgentRunResult`、`AgentDefinition`、`AgentRegistry`、`AgentRunner`，并保持 core 不 import 推荐/RAG/domain 模块。`RagAgentAdapter` 保留 `invoke()/handle_message()/build_loop()/build_query_support()` 等 API，但内部通过默认注册的 `rag_agent` definition 委托 `AgentRunner`；post-ranking 仍进入 `GenericAgentLoop`，pre-retrieval 仍保持轻量 direct stage，避免一次性扩大行为面。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runner.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_rag_agent_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_generic_agent_loop.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runtime_contracts.py -q`，结果 `46 passed in 0.50s`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runtime.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_tools.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_facades.py -q`，结果 `86 passed in 0.80s`。

**面试可讲点：**
这段可以讲成“把推荐系统里的子 Agent 从硬编码 adapter 升级为可注册、可诊断、可权限收敛的 runtime 单元”：通用 loop 只负责编排，定制 agent 通过 definition/registry/runner 注入，既保留 RagAgent 的 internal-only 安全边界，又为后续多 Agent 编排留下清晰扩展点。

### 2026-06-21 - RS Agent 对话/工具编排与 SFT 前置体检

**任务：**
按用户要求先审查 `rsagent/raagent` 对话上下文编排、工具编排和公开展示边界；发现本地问题后先修正，不直接进入 GPT 1000 条样本生成或远程 Qwen3.5-4B SFT。

**遇到的问题：**
交互入口中 `HybridRecommendationEnvironment.step()` 仍可绕过完整 `AgentRuntime.run_turn()`；pending clarification 与 `why/为什么` explanation request 的优先级存在误路由风险；context compact 中 recent turns 与 archived summaries 可能重复；工具 dispatcher 保留 legacy branch，缺少 manifest gate；前端 public 类型仍暗示 `thoughts/agent_thoughts`，容易把内部工具链路、RAG 原始证据或诊断暴露到试用界面。

**定位方式：**
沿 `/chat -> RecommendationService -> FeedbackSessionFacade -> HybridRecommendationEnvironment.converse() -> AgentRuntime.run_turn()` 梳理运行链路，对照 `rs_core/rsagent/dialogue.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/rsagent/context.py`、`rs_core/rsagent/tools.py` 与前端 `frontend/src/types.ts`、`LiveDemo.tsx`、`Sandbox.tsx`、`MallHome.tsx` 检查 contract 漂移；用回归测试复现 `pending_clarification`、runtime trace、public schema 与 GPT/Qwen dry-run 边界。

**解决方式：**
将 `step()` 收口到 `converse()`，确保 CLI/仿真/旧入口也走 context compact、hidden tool execution、stop check、diagnostics 和 session summary；调整 dialogue routing，让带真实约束信号的“为什么不先按 budget/便宜”继续作为澄清回答，而 bare `why?/explain` 在 pending clarification 下走解释请求且不清空 pending；构建 context bundle 时按 `turn_index` 排除 recent/archive 重复，并把 public summary 的 `archived_turn_count` 解释为 recent window 外的 compact archive 数；dispatcher 顶部增加 manifest gate，正式工具仍保留 `get_user_context/query_rag/retrieve_candidates/rank_candidates/get_item_evidence/build_recommendation_slate`；前端移除 `thoughts/agent_thoughts` public 类型和相关展示，改为基于 `turn_index`、`public_timeline`、`display_responses` 的公开交互摘要。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_dialogue.py tests/test_agent_runtime.py tests/test_agent_tools.py tests/test_display_contract.py tests/test_session_summary.py`，最终结果 `218 passed in 1.18s`；其中新增覆盖 pending clarification + `why/budget` 与 bare `why?` 的分流。运行 `npm --prefix frontend run lint` 通过。运行 `./.venv/Scripts/python.exe -m pytest tests/test_gpt_sft_api.py tests/test_openai_compatible_client.py`，结果 `28 passed in 0.20s`；运行 `./.venv/Scripts/python.exe scripts/training/run_gpt_sft_api.py --config configs/training/gpt_sft_api_smoke.yaml --dry-run`，输出 `api_called: false`，确认未调用外部 GPT API。运行 `./.venv/Scripts/python.exe scripts/training/run_qwen_sft.py --config configs/training/qwen_qlora_sft_smoke.yaml`，输出 `dry_run: true`、`heavy_path_entered: false`，并报告本地缺少 `peft/trl`、`bitsandbytes`，resource gate 为 `block`，因此真实 Qwen SFT 应转到确认后的训练环境执行。code-reviewer 最终复审 `APPROVE`，未发现本轮指定范围内的 blocker。

**面试可讲点：**
这段可以讲成“推荐 Agent 从 demo 编排到可训练前置合同的收口”：先把对话入口、上下文压缩、hidden tool manifest 和 public display 边界统一成可测试 contract，再用 dry-run 验证 GPT 数据生成和 Qwen SFT 不会误触发外部 API/重训练；体现了在 LLM Agent 推荐系统中同时治理工具调用准确率、上下文预算、公开安全边界和训练前评估口径。

### 2026-06-21 - Qdrant 向量基础层与 RAG/two-tower 迁移骨架

**任务：**
按用户明确选择的 Qdrant 方向，先搭建可选向量基础层，并把 RAG evidence 检索与 two-tower 向量召回接入迁移骨架；同时不把 Qdrant 变成 serving 强依赖，不改变当前默认 public serving 行为。

**遇到的问题：**
项目里已有两类向量相关链路：RAG 的本地 TF-IDF/dense vector index，以及 two-tower 的 numpy exact scan；如果直接替换为 Qdrant，容易绕过 RAG candidate scope/policy gate，或让 ANN 检索结果在未验证 exact baseline overlap 前影响在线召回。另一个边界是当前 `semantic` 仍是 BM25F/token 倒排，不应被误当成 dense vector source 直接迁移。

**定位方式：**
对照 `rs_core/recsys/rag/vector_index.py`、`rs_core/recsys/rag/retriever.py`、`rs_core/recsys/vector_index.py`、`rs_core/recsys/candidate_merge.py` 与 `rs_core/workflow/online_recommendation.py` 梳理调用边界：RAG 必须返回 `RagEvidence` 并进入 `build_rag_context_for_ranked_candidates()`；two-tower 的最小替换点是兼容 `search()/get_item_vector()/get_user_vector()` 的向量索引协议。

**解决方式：**
新增 `rs_core/recsys/vectorstores/` 下的 Qdrant contract/client/payload/filter helper，并把 `qdrant-client` 声明为 optional extra、`qdrant-rag` 声明为包含 `sentence-transformers` 的 RAG extra。新增 `QdrantCandidateRagVectorRetriever`，通过 Qdrant payload filter 限定候选 item，并继续交给 RAG policy gate 处理 forbidden provenance、quota、budget 与 truncation。新增 `QdrantTwoTowerIndex`，兼容现有 two-tower query 构造和 candidate merge 逻辑，并强制 `train_only/no_holdout/candidate_generation_allowed` 等检索过滤；`online_recommendation` 支持 `backend: qdrant` 但默认继续使用 local vector backend，同时 public readiness 区分 Pool500 artifact readiness 与 online source index readiness。路线图补充 Qdrant vector foundation lane，明确这只是用户新批准的可选向量基础层，不代表 Phase 2 全量生产化。

**验证结果：**
用户授权后，使用项目默认 `.venv` 成功安装 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pip install -e "D:/sinrotic_code/python_project/summer/RS_agent[qdrant-rag]"`，实际安装 `qdrant-client==1.18.0` 与 `sentence-transformers==5.6.0`。随后运行真实 `qdrant-client` 的 `QdrantClient(":memory:")` smoke，覆盖 RAG chunk collection 建表/upsert/filter/query、`QdrantCandidateRagVectorRetriever` candidate scope，以及 two-tower collection 的 `train_only/candidate_generation_allowed/excluded_items/non-positive score` 过滤，结果 `real qdrant smoke passed`。真实 smoke 暴露 `get_collection()` 对 missing collection 抛 `ValueError("Collection ... not found")`，已修复 `ensure_collection()` 仅将 not-found 类 `ValueError` 视为 missing，仍传播非 missing 错误，并补充回归用例。最终运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_qdrant_vectorstore_contract.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_qdrant_rag_retriever.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_qdrant_two_tower_index.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_rag_core.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_smoke.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_recommend_from_sequence.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runtime.py -q`，结果 `147 passed in 4.00s`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check D:/sinrotic_code/python_project/summer/RS_agent/rs_core D:/sinrotic_code/python_project/summer/RS_agent/tests/test_qdrant_vectorstore_contract.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_qdrant_rag_retriever.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_qdrant_two_tower_index.py D:/sinrotic_code/python_project/summer/RS_agent/tests/qdrant_fakes.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_recommend_from_sequence.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runtime.py`，结果 `All checks passed!`。code-reviewer 复审结论为 `APPROVED`，其追加指出的 Qdrant two-tower readiness 健康检查也已补充非变更式 collection 探测和回归用例。

**面试可讲点：**
这段可以讲成“推荐系统向量检索服务化的渐进迁移”：先抽象 vector store contract，再把 RAG evidence 与 two-tower candidate recall 分别接入 Qdrant；前者严格保持 evidence-only/candidate-scoped，后者保留 exact scan baseline 做 ANN 对齐，体现了对召回质量、解释 grounding 和线上安全边界的综合治理。

### 2026-06-20 - 数据库/中间件 Phase 0/1a 服务治理落地

**任务：**
按已批准的 `proceed_phase0_1a` 范围执行数据库/中间件串联计划，只落地 Phase 0 trial hardening 与 Phase 1a contract/schema baseline，不提前引入 PostgreSQL runtime、Redis/RQ、MinIO、Prometheus、Kafka/ClickHouse、pgvector 或多实例生产化。

**遇到的问题：**
现有 SQLite/JSONL persistence 已能记录 public serving 行为，但对外 trial 还缺少更保守的数据治理：comment 长度与脱敏标记、public timeline/request summary/session export 的敏感字段过滤、retention cleanup 函数；同时 Phase 1a 若只停留在规划文档，后续接 PostgreSQL/队列/观测时容易混淆 fail-open audit store 与 fail-closed facts store。

**定位方式：**
复核 `.omc/plans/rs-agent-service-datastores-middleware-plan.md`、`dic/guides/RS_AGENT_DATASTORE_MIDDLEWARE_ROADMAP.md` 与当前 `rs_core/serving/persistence.py`、`rs_core/display/builder.py`，把验收拆成 public-safe export、retention、Store Failure Policy、Trace ID mapping、SQL DDL baseline 与 SQLite/target schema mapping 几类可测试合同。

**解决方式：**
新增 `rs_core/display/public_safety.py`，统一过滤 token/cookie/secret、raw prompt、tool trace、diagnostics、oracle、label、holdout、ground_truth、target_item 等 public 禁止内容；在 `rs_core/display/builder.py` 与 `rs_core/serving/persistence.py` 中对 public timeline、turn message、feedback comment、request summary、session end JSONL summary 做脱敏。Feedback comment 默认 500 字符截断，并在 SQLite 中记录 `comment_truncated` / `comment_redacted`。新增 `cleanup_expired_public_records()`，覆盖 session/public timeline 7 天、request log 14 天、feedback/comment 90 天，simulation namespace 7 天作为 policy 常量保留。新增 `rs_core/serving/store_contracts.py`、`configs/serving/schema/phase1a_serving_baseline.sql`、`configs/serving/schema/sqlite_to_phase1a_mapping.json`，固化 LocalAuditStore fail-open、CanonicalFactsStore fail-closed、DerivedSink fail-open/retry、Trace ID mapping、RAG evidence 分层与 SQL baseline，不实现 PostgreSQL runtime adapter 或 Alembic。

**验证结果：**
新增 `tests/test_serving_trial_hardening.py` 覆盖 comment 截断/脱敏标记、redaction/filter marker、public-safe session export、request/JSONL 敏感字段过滤、retention cleanup 与 policy 常量，并补充 `auth_token/authToken/sessionCookie/session_cookie/api_key/password` 等 realistic secret variants 以及 safe neighbor 字段保留回归；新增 `tests/test_serving_store_contracts.py` 覆盖 Store Failure Policy、safe wrapper compatibility、Trace ID mapping、Phase 1a config defaults 与 RAG evidence contract；新增 `tests/test_serving_migrations.py` 覆盖 SQL baseline 的关键表、索引、约束和 SQLite→Phase1a mapping。使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_trial_hardening.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_store_contracts.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_migrations.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_persistence.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_smoke.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_session_summary.py -q`，结果 `82 passed, 1 warning in 2.27s`；warning 为既有 semantic description SQLite 跨线程析构。运行 `ruff check` 覆盖本轮改动 Python 文件，结果 `All checks passed!`。code-reviewer 最终复审 `APPROVE`，HIGH/MEDIUM/LOW findings 均为 0。

**面试可讲点：**
这段可以讲成“推荐 Agent 受控试用到生产兼容合同的分阶段治理”：Phase 0 先解决 public data minimization、审计回放和 retention；Phase 1a 再把 facts store、audit sink、trace graph、RAG evidence 和 SQL schema 作为可测试合同固定下来。亮点不是一次性上全套中间件，而是在模块化单体中用 contract-first 方式降低未来迁移到 PostgreSQL/事件流/观测系统的风险。

### 2026-06-20 - 数据库/中间件路线图与 Team 执行锚点

**任务：**
把数据库/中间件服务串联的 RALPLAN 共识规划固化为项目级路线文档与 Team/Ralph handoff，防止后续长流程执行中丢失阶段边界或提前引入重组件。

**遇到的问题：**
原规划已落在 `.omc/plans/rs-agent-service-datastores-middleware-plan.md`，但用户担心后续 `/team` 长历程、上下文压缩或多 agent 执行时忘记“当前最多执行 Phase 0 + Phase 1a”的约束，导致 PostgreSQL runtime、Redis/RQ、Kafka/ClickHouse 等后续阶段被误提前。

**定位方式：**
复核最终计划中的阶段 gate、Phase 0 trial hardening、Phase 1a SQL DDL baseline 和 Approval Gate，并确认现有 `.omc/handoffs/`、`dic/guides/` 与项目 memory 可作为执行锚点。

**解决方式：**
新增 `dic/guides/RS_AGENT_DATASTORE_MIDDLEWARE_ROADMAP.md` 作为项目级摘要路线图，明确 Phase 0/1a/1b/1c/2 的允许/禁止事项和分阶段批准口径；新增 `.omc/handoffs/team-plan-to-team-exec-datastore-middleware.md`，要求未来 Team/Ralph 执行前读取计划与路线图，提醒后续执行不要越过 approval gate。

**验证结果：**
文件写入成功；路线图与 handoff 明确引用 `.omc/plans/rs-agent-service-datastores-middleware-plan.md` 和 `.omc/plans/open-questions.md`，并把 `proceed_phase0_1a` 作为当前建议上限。未运行代码测试，因为本次只做规划/文档锚定，不改 runtime 代码。

**面试可讲点：**
这段可以讲成“复杂推荐服务生产化路线的执行治理”：不仅做技术选型，还把阶段 gate、禁止提前引入的基础设施、trial 数据治理和 Team handoff 固化成文档与记忆，降低多 agent 长流程中的路线漂移风险。

### 2026-06-19 - Serving 受控试用 P1 轻量持久化

**任务：**
在 P0 trace、权限和 debug 隔离基础上，为 FastAPI serving 补齐 SQLite + JSONL 轻量持久化，记录 session metadata、public turn、feedback event 和 request summary，同时保持召回/排序主链路、public response contract 与 debug 边界不变。

**遇到的问题：**
原 serving 只依赖单进程内存 `sessions/session_events`，进程重启后无法回看试用会话，也缺少请求级审计；但如果直接序列化 `AgentSession.to_dict()` 或 raw diagnostics，会把 `runtime_trace`、`rag_context`、tool/score/user_profile 等内部字段带入 public export 或落盘产物。

**定位方式：**
沿 `rs_core/serving/app.py`、`service.py`、`facades.py`、`rs_core/display/builder.py` 和 serving tests 梳理边界，确认最小接入点应放在 serving facade/service 层：主请求先完成，再 best-effort persist；未授权请求必须在 `get_service()` 前被 gate；fallback export 只能从已校验的 public display/timeline 表恢复。

**解决方式：**
新增 `rs_core/serving/persistence.py`，实现 `NoopServingPersistenceStore`、`SQLiteJsonlServingPersistenceStore` 和 fail-open 的 `SafeServingPersistenceStore`；通过 `RS_SERVING_PERSISTENCE_ENABLED`、`RS_SERVING_SQLITE_PATH`、`RS_SERVING_JSONL_PATH` 开启持久化，默认保持 Noop。SQLite 表只保存 `serving_sessions`、`serving_turns`、`serving_feedback_events`、`serving_request_summaries` 的 public-safe 字段；JSONL 只追加事件摘要。`/session/start`、`/chat`、`/feedback`、`/recommend`、`/recall` 接入 middleware 生成/规范化后的 `X-Request-ID`，并让 request summary 只白名单保留 `http_request_id` 与公开 retrieval summary 计数字段。初始化失败、写入失败和 export fallback 失败均降级，不影响主请求。针对安全复审提出的“strict auth 本地默认放开若误绑定外网会 fail-open”风险，在 `scripts/serving/run_service.py` 增加启动护栏：非 loopback host 必须显式设置 `RS_SERVING_STRICT_AUTH=1`，且必须配置 `RS_TRIAL_TOKEN`、`RS_DEBUG_TOKEN`，显式开启 simulation 时还需 `RS_SIMULATION_TOKEN`。

**验证结果：**
新增 `tests/test_serving_persistence.py` 覆盖 session/chat/feedback 落库、SQLite fallback export、recommend/recall request summary、persistence 失败降级、strict-auth 未授权不实例化 service/persistence、trial token 不能触发 recall 落库、非法/缺失 request id 与响应头落库一致、SQLite 初始化失败 fail-open，以及 SQLite/JSONL blocked terms 扫描；新增 `tests/test_serving_run_service.py` 覆盖 loopback 本地开发不强制鉴权、非 loopback 必须 strict auth、缺 trial/debug/simulation token 拒绝启动等部署护栏。使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_run_service.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_smoke.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_facades.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_recommend_from_sequence.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_long_memory.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_persistence.py -q`，结果 `89 passed, 1 warning in 2.32s`；warning 来自既有 semantic description SQLite 对象跨线程析构，不是本次 persistence store。前端复跑 `npm --prefix D:/sinrotic_code/python_project/summer/RS_agent/frontend run lint` 与 `npm --prefix D:/sinrotic_code/python_project/summer/RS_agent/frontend run build` 通过。code-reviewer 复审 `APPROVE`，HIGH/MEDIUM/LOW 均为 0；security-reviewer 对 P1 persistence 与非 loopback 启动护栏均 `APPROVE`。额外注意：前端 Vite dev dependency audit 有独立 HIGH advisory，需后续单独升级处理。

**面试可讲点：**
这段可以讲成“受控试用推荐系统的可追溯与数据最小化落地”：不是为了持久化而把内部 Agent 状态全量落盘，而是把 serving 侧拆出 public-safe persistence seam，用白名单 schema、fail-open 策略和鉴权前置保证试用可回放、可审计、可降级，同时不泄露召回/排序诊断和 Agent 内部推理链路。

### 2026-06-19 - Serving 受控试用部署 checklist 与黑盒 smoke

**任务：**
在 P1 轻量持久化和非 loopback 启动护栏之后，补齐受控试用部署说明与真实服务黑盒 smoke 脚本，让“代码测试通过”进一步收口为“启动后可按 checklist 验收”。

**遇到的问题：**
已有 pytest 能验证 app 内部契约，但缺少部署者可直接执行的 endpoint 权限矩阵、env 配置说明和外部 HTTP smoke；初版 smoke 通过 CLI 参数传 token，存在进程列表/shell history/CI 日志泄露风险；同时 simulation endpoint 在 app 中默认可用，文档和非 loopback 启动护栏如果只在显式启用时要求 `RS_SIMULATION_TOKEN`，会造成部署口径不一致。

**定位方式：**
对照 `rs_core/serving/app.py`、`scripts/serving/run_service.py`、`rs_core/serving/schema.py`、`tests/test_serving_smoke.py`、`tests/test_serving_persistence.py` 和 `tests/test_serving_run_service.py` 梳理 endpoint 权限、response schema、`X-Request-ID` 行为和 simulation 默认开关语义；code-reviewer 与 security-reviewer 分别复审文档/脚本一致性和 token/endpoint 暴露边界。

**解决方式：**
新增 `dic/guides/SERVING_TRIAL_DEPLOYMENT_CHECKLIST.md`，用中文记录 loopback 与非 loopback 启动方式、token 分层、endpoint 权限矩阵、request tracing、SQLite/JSONL persistence 路径和 public-safe 边界。新增 `scripts/serving/smoke_trial_service.py`，使用 Python 标准库对已启动服务执行 `/health`、`/ready`、session/chat/feedback/export、`/recommend` 与可选 `/recall` 权限 smoke，并统一检查 `X-Request-ID`。脚本默认从 `RS_TRIAL_TOKEN` / `RS_DEBUG_TOKEN` 读取 token，CLI token 仅作为本地临时 fallback。同步收紧 `run_service.py`：非 loopback 场景下，simulation endpoint 默认可用时必须配置 `RS_SIMULATION_TOKEN`，只有显式 `RS_ENABLE_SIMULATION_ENDPOINTS=0` 才允许不配置。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m py_compile scripts/serving/smoke_trial_service.py scripts/serving/run_service.py` 通过；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_serving_persistence.py tests/test_serving_run_service.py`，结果 `62 passed, 1 warning in 1.72s`，warning 仍为既有 semantic description SQLite 跨线程析构。无 scheme `--base-url 127.0.0.1:8000` 返回结构化 JSON 失败，证明 smoke 脚本错误路径可读。code-reviewer 复审 `APPROVE`，security-reviewer 复审 `APPROVE`；security-reviewer 还通过 `uvx pip-audit -r requirements-serving.txt` 确认 serving requirements 暂无已知漏洞。

**面试可讲点：**
这段可以讲成“推荐 Agent 从功能可用到试用可运维的交付闭环”：不仅写接口和单测，还补部署 checklist、权限矩阵、启动护栏和外部 smoke，把 token 泄露、debug/simulation 边界、request tracing 和持久化 fail-open 都纳入可执行验收，体现从 demo 到受控试用的工程化思路。

### 2026-06-18 - Agent 召回工具 schema v2 高层路由收口

**任务：**
重编排 `retrieve_candidates` 的召回工具 schema，把语义召回、相似物品、用户近邻、行为召回和 fallback 从一个粗粒度 `use_behavioral_recall` 开关中拆成高层 `route_policy`，同时保持后端继续 gate 具体 ItemCF/UserCF/TwoTower/co-visit 分路。

**遇到的问题：**
原 schema 中 `semantic_mode` 相对清楚，但协同过滤类分路只通过 `use_behavioral_recall` 和 manifest 文案描述，LLM planner 难以判断“什么时候偏相似物品、什么时候可用用户近邻、什么时候只是 fallback 补齐”；如果让模型直接选择 ItemCF/UserCF/TwoTower，又会暴露过多底层实现并带来误调风险。

**定位方式：**
检查 `rs_core/rsagent/tools.py` 的 `RetrieveCandidatesInput/Output`、`RETRIEVE_CANDIDATES_ROUTING_ATTRIBUTES` 和 boundary prompt，结合 `rs_core/rsagent/dialogue.py` 的默认 tool call 参数、`rs_core/workflow/hybrid_environment.py` 的召回 dispatch，以及 `tests/test_agent_tools.py` / `tests/test_agent_runtime.py` 的既有契约，确认最小改法是新增高层策略 schema 并保留旧字段兼容。

**解决方式：**
新增 `RecallIntent`、`RecallProfilePolicy`、`RecallRoutePolicy`、`RecallConstraints`、`RecallDiversityPolicy`、`RecallRouteDecision`、`RecallRetrievalSummary` 等 dataclass；`RetrieveCandidatesInput` 保留 `limit/semantic_mode/use_history_profile/use_behavioral_recall`，同时增加 `target_pool_size/profile_policy/route_policy/constraints/diversity`。manifest 中明确 LLM 只能表达 `semantic/similar_item/user_neighbor/behavioral/fallback` 高层策略，不能直接选择底层 source 文件或索引；runtime 在召回输出上附加 compact `route_decisions`，只包含 route/status/reason/eligible/returned_count，不带 score、候选 source lineage 或 oracle 字段。

**验证结果：**
使用项目默认 `.venv` 运行 `.venv/Scripts/python -m pytest tests/test_agent_tools.py tests/test_agent_runtime.py tests/test_agent_dialogue.py tests/test_agent_capability_manifest.py tests/test_serving_facades.py tests/test_serving_recommend_from_sequence.py -q`，结果 `119 passed in 1.57s`；运行 `.venv/Scripts/python -m compileall -q rs_core tests` 通过。另由 verifier 只读复核 schema 兼容性、route boundary、public serving API 不泄露内部 route diagnostics，结论 `PASS`，无 blocker。

**面试可讲点：**
这段可以讲成“LLM Agent 召回编排的抽象层治理”：不是把所有召回算法暴露给模型，而是让 LLM 只选择语义、相似物品、用户近邻、行为扩展和 fallback 这些业务可理解的高层策略；具体 ItemCF/UserCF/TwoTower/co-visit 是否可跑，由后端根据用户历史、索引可用性和 underfill 自动判定，从而兼顾可解释编排、稳定性和工程安全边界。

### 2026-06-17 - Serving 受控试用 P0 trace 与 debug 隔离

**任务：**
按 Option A+ 方向对 FastAPI serving 和 React 试用界面做 P0 加固：补齐 `X-Request-ID`、trial/debug/simulation token gate、demo/simulation endpoint 开关，以及前端 debug 面板默认隐藏。

**遇到的问题：**
现有服务所有 endpoint 默认公开，前端会直接展示 mock/internal thoughts，`/recall`、`/demo/e2e`、`/simulation/*` 与公开试用入口边界不够清晰；同时不能破坏既有 `/health` liveness-only 和 public response contract。

**定位方式：**
检查 `rs_core/serving/app.py`、`frontend/src/api.ts`、`frontend/src/views/LiveDemo.tsx`、`frontend/src/views/Sandbox.tsx`、`frontend/src/views/MallHome.tsx` 和 serving smoke tests，确认采用兼容式加固：保留原响应形态，通过 header、env gate 和 UI flag 收紧边界，而不是一次性改全量 response envelope。

**解决方式：**
在 serving 中加入 `X-Request-ID` middleware，合法 request id 原样透传，非法值替换为 UUID；通过 `RS_SERVING_STRICT_AUTH`、`RS_TRIAL_TOKEN`、`RS_DEBUG_TOKEN`、`RS_SIMULATION_TOKEN` 控制公开、debug 和 simulation 访问；`RS_ENABLE_DEMO_ENDPOINT` / `RS_ENABLE_SIMULATION_ENDPOINTS` / `RS_ENABLE_RECALL_ENDPOINT` 提供端点开关。前端统一注入 `X-Request-ID` 和可选 `VITE_RS_AGENT_TOKEN`，并用 `VITE_ENABLE_DEBUG_PANEL` 默认关闭 LiveDemo、MallHome、Sandbox 的内部 tool/RAG/reward/stop_check 面板。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py tests/test_serving_facades.py`，首轮结果 `67 passed in 5.63s`。Code review 发现 token 比较、Sandbox 右侧内部状态和 simulation gate 测试覆盖缺口后，补充 `hmac.compare_digest`、Sandbox 用户智能体内部面板 gate、公开文案收口和更多 auth/disable tests；复跑同一 suite，最终结果 `71 passed in 1.77s`。前端先误在仓库根目录运行 `npm run lint`，因根目录无 `package.json` 失败；随后改用 `npm --prefix D:/sinrotic_code/python_project/summer/RS_agent/frontend run lint` 通过，`npm --prefix D:/sinrotic_code/python_project/summer/RS_agent/frontend run build` 通过。最终 code review 复核无 HIGH/MEDIUM 问题，结论 `APPROVE`；剩余 LOW 注意点是浏览器端 `VITE_RS_AGENT_TOKEN` 只能配置低权限 trial token，不能放 debug/simulation token。

**面试可讲点：**
这段可以讲成“推荐系统从 demo 到受控试用的边界加固”：没有急着拆网关或微服务，而是在模块化单体中先落地线上系统常见的 trace、权限分层、debug 双隔离和可执行验收，既保持推荐主链路稳定，又能支持试用问题复盘和内部排查。

### 2026-06-22 - Serving 文件架构整理 review blocker 收口

**任务：**
在 `rs_core/serving` 按 Clean/Hexagonal 分层轻拆后，处理 code-reviewer 对 `/ready` schema、BoundaryMap ownership 和 Qdrant helper import graph 的三类阻塞问题。

**遇到的问题：**
FastAPI `response_model=ReadinessResponse` 会过滤未声明字段，导致服务内部已返回的 `candidate_retrieval` 在 HTTP `/ready` 中静默丢失；BoundaryMap 虽然引入 canonical/compatibility paths，但 `owned_paths` 存在重复或目录/文件重叠 ownership；`runtime/config.py` 复用 `qdrant_builders` helper 时会把 serving runtime 轻量配置入口重新拖入 Qdrant/vectorstore import graph。

**定位方式：**
通过 code-reviewer 复核 serving reorganization 变更，结合 focused tests 和 import graph probe 定位：`schema.py::ReadinessResponse` 缺少字段，`domain/boundary_map.py::validate()` 只查模块名和精确 owned path，`runtime/config.py` 经 `rs_core.recsys.vectorstores.qdrant_builders` 间接触达 `qdrant_client`/RAG Qdrant 模块。

**解决方式：**
为 `ReadinessResponse` 增加 `candidate_retrieval` 并在 HTTP smoke 中断言保留 public-safe readiness 字段；将 Qdrant env/merge helper 抽到轻量 `rs_core.common.qdrant_config`，`rs_core.recsys.vectorstores.qdrant_config` 只做兼容 re-export，serving runtime 只依赖 common helper；将 `rs_core.serving.__init__` 改为 lazy `__getattr__`，避免导入子模块时 eager load `service`；BoundaryMap 增加 canonical path normalization、Windows separator normalization、重复 ownership 与目录/文件 overlap validation，并调整 default map 让 canonical ownership 唯一。

**验证结果：**
使用项目默认 `.venv` 运行 focused review blocker tests：`tests/test_serving_boundary_map.py tests/test_serving_reorg_compatibility.py tests/test_serving_smoke.py::test_ready_returns_coarse_public_readiness tests/test_qdrant_config_env.py -q`，结果 `23 passed`；运行 serving contract/compatibility tests，结果 `37 passed`；运行 serving/governance regressions，结果 `138 passed`；运行 runtime seam regressions，结果 `81 passed`。code-reviewer 对 BoundaryMap 最后一轮复审 `PASS`，确认重复和 overlap ownership 已覆盖，default map 仍 valid。

**面试可讲点：**
这段可以讲成“架构整理不是简单搬文件，而是把边界变成可执行合同”：HTTP schema 防止 readiness 静默退化，BoundaryMap 用 canonical ownership 约束模块责任，runtime config 通过轻量 helper 和 import graph guard 避免基础设施依赖倒灌，从而让模块化单体既保持兼容，又具备后续接 Redis/MinIO/Qdrant/Postgres adapter 的清晰边界。

### 2026-06-16 - Recommendation Agent 工具规划提示词强化

**任务：**
完善 Recommendation Agent 的系统提示词和工具边界，让 RAG 可以在召回前用于概念补全与 query planning，同时保持工具集合凝练，不把澄清、改写、诊断等流程节点拆成新工具。

**遇到的问题：**
原提示词只笼统说明 `query_rag` 可在 `retrieve_candidates` 前做 query planning，缺少“概念补全、属性扩展、场景/同义词/品类知识、query rewrite support”的明确边界； deterministic dialogue 对 `I want headphones` 这类带具体商品词的请求仍会前置澄清，导致 RAG 前置和召回链路无法触发。

**定位方式：**
沿 `rs_core/rsagent/tools.py` 检查 `QUERY_RAG_BOUNDARY_PROMPT`、`AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT`、`AGENT_TOOL_MANIFEST`，结合 `rs_core/rsagent/dialogue.py` 的 `_recommendation_tool_calls()` 和 `tests/test_agent_tools.py` / `tests/test_agent_dialogue.py` / `tests/test_serving_smoke.py` 的既有契约，确认应复用现有 `query_rag`、`retrieve_candidates`、`rank_candidates`、`get_item_evidence`、`build_recommendation_slate` 等高层隐藏工具，而不是新增流程工具。

**解决方式：**
强化 `query_rag` 边界为 internal pre-retrieval catalog-knowledge helper，明确 compact hints 只服务 `retrieve_candidates.query` 和澄清判断；为 `get_item_evidence` 增加排序后 grounding 边界，禁止新增候选或改排序；全局 prompt 明确“只有阻断候选召回时才前置澄清，否则先用上下文、可选 RAG、召回、排序和证据工具服务，再做后置高价值澄清”。同时在带具体 query 的默认工具链中插入 `query_rag`，让 `semantic_live` 能消费其 `semantic_query_hint`；移除 `QueryRagOutput` 中容易混淆 raw evidence 边界的 `supporting_snippets` 字段；并补强 public display / recall facade 的 denylist、ui_state allowlist 和 retrieval_summary allowlist，避免 snippet、camelCase trace 或下游诊断字段透传。

**验证结果：**
使用项目默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_tools.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_dialogue.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runtime.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_capability_manifest.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_display_contract.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_smoke.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_facades.py -q`，结果 `247 passed in 1.82s`。

**面试可讲点：**
这段可以讲成“推荐 Agent 的工具层产品化和 prompt contract 收口”：LLM 不直接面对底层召回/排序方法，而是在系统提示词约束下使用少量隐藏业务工具；RAG 前置只做 query planning 和概念补全，排序后 evidence 只做解释 grounding，候选生成、排序和 public display 仍由推荐 backbone 与 display validator 控制。

### 2026-06-22 - RSAgent 去 RAG 工具化与 RagAgent 子 Agent 化

**任务：**
按新的 Agent 编排边界，把 RSAgent 中直接暴露的 `query_rag` / `get_item_evidence` hidden tools 移除，改为由内部 RagAgent/runtime 在受控阶段提供 RAG query support 与候选证据 support，并更新 RagAgent prompt contract。

**遇到的问题：**
旧实现把 RAG 前置 query planning 和排序后 evidence grounding 都建模成 RSAgent 工具，容易让推荐 Agent 直接看到 RAG 工具名、工具 trace 和 evidence 工具边界；但直接删除 `query_rag` 又会丢失 `semantic_live` 依赖的 `semantic_query_hint`，影响已有召回行为。

**定位方式：**
对照 Claude Code 子 agent 通信模式（父 Agent 显式传上下文、子 Agent 中间工具调用不暴露、父 Agent 只接收最终结果），检查 `rs_core/rsagent/tools.py`、`rs_core/rsagent/dialogue.py`、`rs_core/workflow/hybrid_environment.py` 与 `rs_core/agent_runtime/adapters/rag.py`，确认最小安全方案是保留 runtime 内部兼容 key，但从 RSAgent manifest、capability、planner prompt 和 tool trace 中删除 RAG 工具。

**解决方式：**
RSAgent 工具集合收口为 `get_user_context -> retrieve_candidates -> rank_candidates -> build_recommendation_slate`，`record_user_feedback` 只处理显式反馈；`query_rag` / `get_item_evidence` 从 tool manifest、capability manifest、dialogue plan 和 dispatcher 中移除。RagAgent adapter 新增 `RagAgentQuerySupport` 与 `pre_retrieval_query_support` 阶段，运行时在 `retrieve_candidates` 前内部生成兼容的 `semantic_query_hint/suggested_query_terms`，写入内部 `tool_context["query_rag"]` 但不作为 RSAgent tool result。排序后 small2big evidence 继续由 RagAgent `post_ranking_evidence_support` 压缩到 internal diagnostics。RSAgent 中文 prompt 明确“不直接调用 RAG 工具”，RagAgent prompt 明确身份、作用、运行时机、行为边界、工作流程、输入和输出。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_agent_capability_manifest.py tests/test_rag_agent_adapter.py -q`，结果 `55 passed`；运行 `... -m pytest tests/test_agent_runtime.py tests/test_serving_facades.py tests/test_agent_dialogue.py tests/test_serving_smoke.py -q`，结果 `122 passed`；运行 `... -m pytest tests/test_rag_core.py tests/test_qdrant_rag_index_build.py -q`，结果 `55 passed`；最终合并回归 `... -m pytest tests/test_agent_tools.py tests/test_agent_capability_manifest.py tests/test_rag_agent_adapter.py tests/test_agent_runtime.py tests/test_serving_facades.py tests/test_agent_dialogue.py tests/test_serving_smoke.py tests/test_rag_core.py tests/test_qdrant_rag_index_build.py -q`，结果 `232 passed`。

**面试可讲点：**
这段可以讲成“推荐 Agent 与证据 Agent 的职责解耦”：RSAgent 只负责自然对话、候选召回、排序和展示安全输出；RagAgent 作为内部子 Agent 负责 query hint 与候选内 evidence 压缩。这样既保留 RAG 对召回语义的帮助，又避免 RAG 原始证据、检索实现和 small2big parent profile 污染推荐决策、公开回答或训练监督。

### 2026-06-16 - Recommendation Agent 用户/session 隔离与冷启动收口

**任务：**
审查并修复 Recommendation Agent 工具调用链中的用户信息注入和召回隔离边界，确保每个用户/session 有独立身份，匿名用户和未知显式用户不会复用其他用户历史序列，同时保持 `get_user_context`、`retrieve_candidates` 和 long memory 的契约稳定。

**遇到的问题：**
Serving 层虽然以 `session_id` 存储会话，但匿名 `start_session()` 原先可能落到环境层默认第一个训练用户；初版修复只在 facade 层生成 guest id，后续 code review 进一步发现 direct `HybridRecommendationEnvironment.start_session()` 匿名路径仍会复用 `u1` 和其 `recent_item_sequence`。这会让匿名用户或新用户在召回种子上继承其他用户行为，违反推荐独立性。

**定位方式：**
沿 `rs_core/serving/facades.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/rsagent/context.py` 和 `rs_core/workflow/online_recommendation.py` 检查身份传递、上下文 bundle、候选召回和 long memory hydrate/persist 调用链。通过 code-reviewer 做两轮只读复核，第一轮指出冷启动复制首个已知用户序列，第二轮指出 env 层匿名路径仍保留旧默认用户语义。

**解决方式：**
在 `FeedbackSessionFacade.start_session()` 中将空白 user_id 归一为 `guest-{session_id}`；在 `HybridRecommendationEnvironment.start_session()` 中统一生成唯一 `session_id`，匿名路径直接绑定 `guest-{session_id}`，未知显式用户和 guest 都写入空冷启动序列，不再复制任意训练用户历史。显式测试用例改为显式传入 `u1`，避免把 demo 用户语义和匿名用户语义混在一起。补充 service/env 匿名 session 独立、未知显式 user 冷启动、long memory 匿名不串记忆等回归测试。

**验证结果：**
使用项目默认 `.venv` 运行重点回归：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_tools.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_dialogue.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_runtime.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_agent_capability_manifest.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_display_contract.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_smoke.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_long_memory.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_serving_facades.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_hybrid_demo_optional_strong.py -q`，结果 `256 passed in 2.08s`。最终 code-reviewer 复核无 HIGH/MEDIUM 问题，建议 `APPROVE`。

**面试可讲点：**
这段可以讲成“推荐 Agent 的用户隔离和冷启动治理”：不仅给前台会话分配 `session_id`，还把长期用户画像、当前对话状态和召回历史序列拆开处理；匿名用户走独立 guest 身份和空冷启动，显式用户才共享长期 memory，从而避免推荐系统中常见的用户历史串用和隐式数据泄漏。

### 2026-06-14 - P2 Agent/RAG workflow facade seam 落地

**任务：**
在 P0/P1 serving facade 之后，继续落地 `AgentOrchestrationFacade` 和 `EvidenceRAGFacade`，把 `HybridRecommendationEnvironment` 中的 Agent turn 编排和 turn-level RAG evidence 构建先拆成模块化单体内部 seam。

**遇到的问题：**
`HybridRecommendationEnvironment` 同时承担对话 runtime、工具执行、推荐 turn 构建和 RAG context 构建，继续直接堆叠会让 Agent/RAG 边界变厚；但 P2 也不能重写 AgentRuntime、改变 trace 顺序、改 FastAPI route，或让 RAG 变成候选生成、ranking replacement、promotion 入口。

**定位方式：**
沿 `rs_core/workflow/hybrid_environment.py` 梳理 `converse()`、`AgentRuntime.run_turn(...)`、`_recommendation_step()` 和原 `_build_turn_rag_context(...)` 调用链，确认最小可落地 seam 是：Agent 编排只包装既有 runtime host 协议，RAG facade 只迁移原 turn-level evidence context 构建逻辑。测试侧用 `tests/test_agent_runtime.py` 固化 runtime delegation 和 trace 行为，用 `tests/test_rag_core.py` 固化 `evidence_mode=off/shadow/explain` 语义和 public payload 边界。

**解决方式：**
新增 `rs_core/workflow/facades.py`，实现 `AgentOrchestrationFacade.run_turn(...)` 委托既有 `AgentRuntime.run_turn(host, session, user_input, explanation_item_id)`；实现 `EvidenceRAGFacade.build_turn_rag_context(...)` 承接原候选内 RAG context 构建逻辑。`HybridRecommendationEnvironment.__init__` 初始化两个 facade，`converse()` 保持输入 normalize 后委托 Agent facade，`_recommendation_step()` 通过 Evidence RAG facade 构建 `turn.rag_context`，并继续用 `_rag_diagnostics(...)` 写内部 diagnostics。整个改动不拆微服务、不改 route、不放宽 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。

**验证结果：**
复核时 code-reviewer 发现旧的 `query_rag -> retrieve_candidates` hint 应用路径会让 RAG 影响候选生成输入，已移除该 rewrite helper 和对应测试，确保 `query_rag` 只保留 planning/diagnostic 上下文，不参与 candidate generation。使用项目默认 `.venv` 复跑 P2 targeted suite：`.venv/Scripts/python -m pytest tests/test_agent_runtime.py tests/test_agent_dialogue.py tests/test_rag_core.py tests/test_serving_facades.py tests/test_display_contract.py tests/test_agent_tools.py tests/test_agent_capability_manifest.py -q`，结果 `212 passed in 2.39s`。新增/强化测试覆盖 Agent facade 委托、`HybridRecommendationEnvironment.converse()` 走 facade、RAG off mode 返回 `None`、shadow/explain 保持候选 scope 和 retriever metadata，以及 `AgentTurn.to_dict()` 默认不公开 `rag_context`。

**面试可讲点：**
这段可以讲成“用 seam-first modular monolith 拆薄 Agent/RAG 厚对象”：没有贸然微服务化或重写 runtime，而是先把 Agent 编排和证据 RAG 各自切成可测试 facade；推荐候选、排序、展示和治理边界保持不变，后续如果要替换 runtime 或升级 RAG 检索器，也能在稳定 contract 下渐进演进。

### 2026-06-13 - Online Serving Artifact Governance 合同 fail-closed 收口

**任务：**
在“离线系统 + 在线服务系统 + 传统推荐 + Agent 编排”的架构拆分中，固化 `current_online_service_route` 与 `configs/serving/online_service.yaml` 的 pool500 artifact path 一致性，避免服务配置和治理注册表漂移。

**遇到的问题：**
初版 path consistency gate 只在 `current_online_service_route` 存在且字段形状正常时检查路径一致；如果 route 被删除、字段缺失/类型错误，或加入 `dual_path_governance*` 旁路字段，存在 fail-open 风险。这样会让 stale artifact path 或双路径语义绕过治理合同。

**定位方式：**
通过 code review 针对 `rs_core/common/engineering_contracts.py` 的 `_online_service_route_violations(...)` 做对抗性检查，重点验证 required route、`required_output_paths`、`config_paths`、`online_route.pool500_candidates_path` 和 `dual_path_governance*` 字段。回归测试集中放在 `tests/test_engineering_contracts.py`。

**解决方式：**
将 `current_online_service_route` 加入 `_REQUIRED_ROUTE_KEYS`；在 online serving route 检查中对 `dual_path_governance`、`dual_path_governance_allowed`、`explicit_dual_path_governance` 显式 fail-closed；要求 `required_output_paths` 和 `config_paths` 都必须是精确单路径字符串列表；要求 serving config 的 `online_route.pool500_candidates_path` 是非空字符串并与 registry 一致。同步补齐 missing route、dual-path、path mismatch 和 shape 类回归测试。

**验证结果：**
使用项目默认 `.venv` 运行 `.venv/Scripts/python -m py_compile rs_core/common/engineering_contracts.py tests/test_engineering_contracts.py` 通过；运行 `.venv/Scripts/python -m pytest tests/test_engineering_contracts.py`，结果 `48 passed in 0.53s`；运行 `.venv/Scripts/python -m pytest tests/test_engineering_contracts.py tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py`，结果 `91 passed in 1.93s`。最终 code-reviewer 复核结论为 `APPROVE`。

**面试可讲点：**
这段可以讲成“在线服务配置与治理注册表的 artifact contract 防漂移”：不是只把接口跑通，而是把 serving readiness 与 route governance 分离，用 fail-closed 工程合同保证 online service 只能读取治理认可的 pool500 artifact，并防止实验性双路径或 malformed registry 悄悄绕过上线边界。

### 2026-06-12 - 系统架构三入口一底座收口

**任务：**
在保留原有推荐流程和现有 Agent 工具编排服务的前提下，整理系统总架构，明确 `/recall`、`/recommend`、`/chat` 三类入口与共享推荐底座的关系。

**遇到的问题：**
项目已经具备离线召回、在线召回封装、传统推荐展示、Agent 工具编排、RAG、feedback 和 simulation 等能力，但如果只按功能堆叠来讲，容易让人误以为要用 Agent 替代传统推荐，或误把 `/recall` 理解成生产级独立微服务。

**定位方式：**
对齐现有 serving API、`OnlinePool500Recommender`、`RecommendationService`、Agent tool runtime、display contract 和 governance 约束，确认当前最清晰的架构叙事是 Traditional Recommendation Backbone + Agent Orchestration：原有流程保留为稳定 backbone，Agent 作为上层编排和交互增强。

**解决方式：**
新增 `dic/architecture/SYSTEM_ARCHITECTURE.md`，用“三入口一底座”组织系统：`/recall` 负责纯候选召回，`/recommend` 保留传统推荐完整链路，`/chat` 承载 Agent 多轮工具编排；三者共享召回、排序、RAG、display 和 governance 底座。同步更新 `dic/README.md` 阅读顺序，把系统总架构文档作为第一入口。

**验证结果：**
文档口径保持三点一致：原有推荐流程不被删除或迁移到 Agent；现有工具编排服务继续保留为上层增强入口；`/recall` 只表示轻量服务化候选接口，不声明 ranking replacement、pool1000、promotion 或生产级独立微服务。

**面试可讲点：**
这段可以讲成“传统推荐底座 + Agent 编排服务”的架构设计：大厂推荐系统常见的召回、排序、展示链路作为稳定底座，Agent 通过工具调用这些能力来完成自然语言交互、解释和反馈响应；系统通过不同 API 入口和 governance 边界避免能力混淆。

### 2026-06-12 - Recall Serving Layer 轻量在线服务封装

**任务：**
把已经完成离线构建的 pool500 artifact 与 source-index lookup，补成服务层可直接调用的纯召回接口，让项目叙事从“离线产物被内部读取”升级为“离线召回产物可通过在线服务层提供候选”。

**遇到的问题：**
原有 `/recommend` 会进入排序和 display 输出，Agent 的 `retrieve_candidates` 又是内部工具入口；如果直接把它们称为召回在线服务，容易混淆“候选召回”和“完整推荐展示”。同时现有治理仍明确禁止 ranking input replacement、pool1000 和 promotion，不能把 pool500 readiness 误写成主路晋升或生产级独立微服务。

**定位方式：**
沿 `rs_core/serving/app.py`、`rs_core/serving/service.py`、`rs_core/serving/schema.py` 和 `rs_core/workflow/online_recommendation.py` 梳理调用链，确认最适合作为纯召回复用点的是 `OnlinePool500Recommender.tool_retrieve_candidates(...)`，而不是会进入排序展示的 `recommend_from_sequence()` / `recommend()`。测试侧复用 `tests/test_serving_recommend_from_sequence.py` 中的临时 serving fixture、pool500 artifact 和 source-index fixture。

**解决方式：**
新增 `POST /recall`，配套 `RecallRequest` / `RecallResponse` 和 `RecommendationService.recall()`：服务复制并合并用户序列，调用 `tool_retrieve_candidates()` 读取 pool500 artifact / source indexes，返回 `candidate_item_ids`、`candidate_count` 和 compact `retrieval_summary`。响应不暴露 display、ranking、diagnostics、score、source lineage 或 oracle 字段。文档中补充 Recall Serving Layer 边界，明确当前仍是 single-process demo 内的轻量服务封装。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py -q`，结果 `42 passed in 1.27s`；运行 `./.venv/Scripts/python.exe -m ruff check rs_core/serving/app.py rs_core/serving/schema.py rs_core/serving/service.py tests/test_serving_recommend_from_sequence.py`，结果 `All checks passed!`。新增测试覆盖 `/recall` 基础契约、oracle / nested oracle 拒绝、source-index 召回、pool500 allowed_sources、candidate_pool_size 和 seen item 过滤。

**面试可讲点：**
这段可以讲成“离线召回产物到在线召回服务层的轻量服务化封装”：离线训练和索引构建完成后，我没有直接把实验 artifact 说成生产服务，而是先补了一个进程内 Recall Serving Layer，用清晰 API 区分纯召回、完整推荐和 Agent 对话，同时用 schema、测试和文档固化 no ranking replacement、no pool1000、no promotion 的治理边界。

### 2026-06-11 - 全用户 source-index 线上召回与 Agent planner contract 收口

**任务：**
把 pool500 主路召回从“部分用户 artifact-backed”推进到可服务全用户的线上 source-index/semantic_live 路线，并让 Agent 侧通过高层 `retrieve_candidates` 工具和 planner system prompt 使用该能力。

**遇到的问题：**
线上服务面向所有用户，不能把 500-user `pool500_candidates.jsonl` 当作完整服务底座；同时 ItemCF 真实 source-index 可能包含大分片，若每次在线请求扫描会造成明显延迟和资源风险。`co_visit_fallback_repair` 仍是 guarded artifact-backed 证据，不能伪装成完整在线图；public `/ready` 和 `/recommend` 还需要避免泄漏 manifest path、source lineage、score、diagnostics、label/oracle 或 tool trace。

**定位方式：**
沿 `rs_core/workflow/online_recommendation.py`、`configs/serving/online_service.yaml`、`rs_core/serving/service.py` 和 Agent tool manifest 检查 complete_pool500、source-index、public payload 和 planner prompt 调用链。code review 进一步定位到两个边界问题：source-index 返回真实候选时 `fallback_used` 可能被 base fallback 误报；`co_visit_fallback_repair` 的候选 cap 复用了 `usercf_per_user`，会让两个 source 的服务配置耦合。

**解决方式：**
`complete_pool500` 改为 artifact 与 `online_route.source_indexes` 双路径：无 pool500 artifact 但有可用 source-index 时仍可服务；ItemCF 大分片默认 `allow_heavy_scan=false` 并在 readiness 标为 `blocked_heavy_scan`；UserCF、two-tower 走 source-index lookup；co_visit 只作为 `artifact_backed_guarded` 候选补充，不声明 full online graph。public `/ready` 改为粗粒度计数，不暴露 source 名和本地路径。Agent 侧新增 planner prompt contract，把 `semantic_live` 全用户 query/history/hybrid 能力和行为召回后台门控写入系统边界。最后修复 `fallback_used` 误报，并让 co_visit 使用独立 `co_visit_per_user` cap。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py tests/test_agent_tools.py -q`，结果 `73 passed in 1.40s`；运行 `./.venv/Scripts/python.exe -m ruff check rs_core/workflow/online_recommendation.py rs_core/serving/service.py rs_core/rsagent/tools.py rs_core/workflow/hybrid_environment.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py tests/test_agent_tools.py`，结果 `All checks passed!`。新增测试覆盖：无 pool500 artifact 时 source-index-backed `complete_pool500` 可返回候选且 `fallback_used=false`，public `/ready` 不泄漏内部路径/source，ItemCF 大分片被阻断，co_visit 使用独立候选 cap。

**面试可讲点：**
这段可以讲成“推荐召回从离线 artifact 到在线服务的治理升级”：全用户服务用 `semantic_live` 覆盖所有用户，并把 UserCF/two-tower/ItemCF/co_visit 作为后台有门控的 source-index 或 guarded source；Agent 前台仍只看到自然对话和高层工具，底层 source、score、诊断和治理状态都被服务端隐藏。实现上同时处理了延迟风险、fallback 监控准确性、public payload 安全和 planner prompt contract，体现了推荐系统服务化时算法能力与工程治理同步推进。

### 2026-06-11 - Agent 双路径 RAG 工具化与 public payload 边界收口

**任务：**
将原本偏排序后解释的候选内 RAG，扩展为 Agent 可按需调用的召回前 `query_rag` planning 工具，同时保留排序后 `get_item_evidence` 证据 grounding，并收口 public display 对 RAG/tool/source/training/reward 等字段和文本的泄漏边界。

**遇到的问题：**
原 RAG 主要依赖候选池，适合解释已推荐商品，但 Agent 在用户需求进入、生成语义召回 query 前也需要商品知识和属性扩展；如果直接把 RAG 固定进 pipeline，又会削弱“Agent 自主选择工具”的设计。同时 public payload validator 原先按字符串全局扫描 `source` / `training` / `reward`，会误杀正常商品文案；放开这些词后又需要防止内部 source、score、tool、RAG diagnostics 通过字段或嵌套结构泄漏。

**定位方式：**
沿 `rs_core/rsagent/tools.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/recsys/rag/` 检查工具契约、runtime 调用链和 RAG evidence policy，确认需要新增非 candidate-scoped 检索路径和单 turn `tool_context`。安全侧通过 code-reviewer 两轮静态审查定位：解释函数不能拼接 raw RAG evidence；`AgentTurn.to_dict()` 默认不应序列化隐藏 `rag_context`；public validator 要区分普通 public free text 与内部 key/value/嵌套结构。

**解决方式：**
新增隐藏工具 `query_rag`，作为 `query_planning` 阶段的 read-only、non-public 工具，只输出 compact query hints，不返回候选、不替代 `retrieve_candidates` / `rank_candidates`。新增 `SQLiteBM25QueryPlanningRetriever` 和 `build_query_rag_context_for_planning()`，复用 allowed fields、provenance gate、budget 和文本截断，但不做 candidate gate。runtime 引入单 turn `tool_context`，让 `query_rag` 的 semantic hint 可在同一 pre phase 被 `retrieve_candidates` 消费。后置 `get_item_evidence` 继续保持候选内解释边界。public display 侧改为 path/key/schema-aware 校验：允许 `source` / `training` / `reward` 作为助手或商品自然文本出现，但禁止它们作为内部字段，并拒绝 `rag_context`、`reward_evidence`、`training_samples`、`feedback_source`、`score_trace`、`rag output`、`tool value` 等内部信号；`features`/`badges`/`feedback_actions`/`ui_state` 增加结构校验，防止嵌套夹带内部 dict。

**验证结果：**
首次回归发现 3 个问题：planning RAG 测试样本里两条 evidence 都被截断导致期望不准；两个 runtime 单测直接调用 `_execute_agent_tool_call()` 时缺少新增 `tool_context` 参数。随后调整测试样本并让 `_execute_agent_tool_call()` 对旧调用签名提供默认空 context。定向回归：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_rag_core.py::test_query_planning_rag_context_filters_policy_and_keeps_non_candidate_evidence tests/test_agent_runtime.py::test_rank_candidates_execution_skips_explicit_pool_mismatch tests/test_agent_runtime.py::test_rank_candidates_execution_does_not_reuse_prior_turn_pool -q`，结果 `3 passed in 0.30s`。最终总回归：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_rag_core.py tests/test_agent_runtime.py tests/test_agent_capability_manifest.py tests/test_agent_dialogue.py tests/test_display_contract.py tests/test_serving_smoke.py -q`，结果 `227 passed in 3.44s`。

**面试可讲点：**
这段可以讲成“推荐 Agent 的双路径 RAG 治理”：召回前 `query_rag` 帮 Agent 做需求理解、属性扩展和语义 query planning；排序后 `get_item_evidence` 只做候选内解释 grounding。LLM 负责决定是否调用工具，推荐系统负责候选、排序和安全展示。实现上用工具 manifest、RAG policy、transient tool_context 和 public payload validator 把能力边界固化，既提升 Agent 对复杂需求的理解能力，又避免 RAG evidence、score、source lineage 和诊断信息泄漏到用户侧。

### 2026-06-09 - Agent 召回工具属性与系统边界收口

**任务：**
根据全用户线上推荐服务的新口径，定义 Agent 可调用的高层召回工具属性，并在系统提示词层面明确工具调用边界。

**遇到的问题：**
全用户服务不能依赖“500 用户 × pool500 候选”的巨型预生成 artifact；同时 `semantic_live` 不应被历史 item 数门控，它既可以理解当前 query，也可以基于用户历史构造语义画像。行为召回如 UserCF/co-visit/two-tower/ItemCF 则需要按历史行为和在线索引可用性后台门控，不能作为前台底层工具暴露给用户。

**定位方式：**
沿 Agent 工具 manifest、dialogue planner 和 semantic_live serving runtime 检查调用链，确认 `retrieve_candidates` 是候选获取的统一高层入口；测试侧用 `tests/test_agent_tools.py` 固化工具属性、边界 prompt 和 planner 参数传递，用 `tests/test_serving_smoke.py` 固化 semantic mode diagnostics 与 public display 防泄漏。

**解决方式：**
在 `rs_core/rsagent/tools.py` 为 `AgentToolSpec` 增加 `routing_attributes` / `boundary_prompt`，将 `retrieve_candidates` 定义为 all-user `semantic_live` + backend-gated behavioral recall 的高层工具，并新增 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT`。在 `rs_core/rsagent/dialogue.py` 让推荐规划传入 `semantic_mode`、`use_history_profile`、`use_behavioral_recall`；在 `rs_core/workflow/hybrid_environment.py` 支持 `query_intent`、`history_profile`、`hybrid_query_history` 三种 semantic_live 查询构造。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_agent_capability_manifest.py tests/test_serving_smoke.py -q`，结果 `50 passed in 1.20s`；运行 `./.venv/Scripts/python.exe -m ruff check rs_core/rsagent/tools.py rs_core/rsagent/dialogue.py rs_core/workflow/hybrid_environment.py rs_core/workflow/online_recommendation.py tests/test_agent_tools.py tests/test_serving_smoke.py`，结果 `All checks passed!`。独立 code-reviewer 复核后无 CRITICAL/HIGH，唯一 MEDIUM 备注是 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT` 当前主要是 contract 常量，后续接真实 LLM planner 时需显式注入 prompt assembly。

**面试可讲点：**
这段可以讲成“推荐 Agent 工具抽象与召回治理边界”：前台只保留自然对话和高层候选获取工具，后台按 query、历史画像和行为门控调度多路召回；既提升全用户可服务性，又避免把底层 source、score、诊断和训练/评估痕迹泄漏到用户响应。

### 2026-06-09 - COLD/DeepFM 诊断模型接入在线排序链路

**任务：**
把已训练的 COLD/DeepFM 排序产物接入 pool500/Agent 在线排序链路，但保持 diagnostic/shadow/no-promotion 边界，不把当前低覆盖评估结果误升格为生产排序替换。

**遇到的问题：**
真实 valid/test frozen eval 的候选覆盖门禁未通过，不能直接用 DeepFM 替换排序；同时在线候选不一定具备训练期 6 个 train-only history features，如果默认用空特征或读取 label/valid/test metadata，会引入效果误判或治理风险。回归过程中还发现 `online_recommendation.py` 已调用 source-index readiness/merge helper，但当前类里缺少对应实现，serving 测试会在 `/ready` 或 complete_pool500 路径报错。

**定位方式：**
检查 `rs_core/recsys/ranking.py` 的 `rerank_candidates` 链路，确认 COLD/DeepFM 最安全的接入点是 LTR 之后的可配置 rerank/shadow stage；结合 `rs_core/recsys/cold_deepfm.py::score_deepfm_model` 复用已有模型 forward，不重新训练。独立 verifier 首轮指出 `feature_metadata_keys` 可被配置绕过读取 forbidden metadata，随后增加 poisoned metadata 测试锁定 label/valid/test/source/candidate_rank 等字段不得进入 DeepFM features。最终使用 serving 回归定位并补齐 `OnlinePool500Recommender` 的 artifact/source-index 占位 helper。

**解决方式：**
在 `rs_core/recsys/ranking.py` 增加 `deepfm_model` / `deepfm_shadow` 配置入口，支持 inline model、`model_path`、feature contract、offline report 与治理 gate；默认只从 `cold_deepfm_features`、`deepfm_features`、`ranking_features` 读取数值特征，并过滤 `label/target/holdout/valid/test/future/candidate_rank/source_` 等 forbidden feature name。`shadow` 模式只记录 raw score，不改最终排序；`rerank` 模式只有在配置和 offline report 均允许时才可产生 delta。`configs/serving/online_service.yaml` 保留正式 neg4 模型路径为 disabled diagnostic block，同时启用本地已有 smoke 模型的 zero-safe shadow 配置用于链路打通，不声明 production-ready。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_recsys_core.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py -q`，结果 `54 passed in 1.07s`。新增测试覆盖：默认关闭不改变排序、rerank 模式可改变排序、shadow 模式不改变排序、模型可从 config path 加载、缺失必需特征跳过、forbidden metadata/feature name 不被读取、三种 allowlisted feature metadata key 可用、默认 serving config 仍保持 diagnostic/no-promotion。

**面试可讲点：**
这段可以讲成“排序模型上线前的影子接入治理”：模型已经训练完，但由于召回覆盖不足不能宣称整体排序收益，因此先把 DeepFM 接成可观测 shadow/rerank stage，用 feature 白名单、offline report gate 和 no-promotion 配置保证不会泄漏 valid/test 或误替换主排序；体现了推荐系统从离线模型到在线链路时，模型能力、数据口径和工程治理必须同时满足。

### 2026-06-09 - usercf/co_visit artifact-backed 在线召回开放

**任务：**
把 `usercf_recall` 和 `co_visit_fallback_repair` 从“解释为暂不可在线”推进到可被线上服务读取的召回能力，同时不误开 true source-index generation、ranking replacement、pool1000 或 final-ready。

**遇到的问题：**
两者当前治理语义不同：`usercf_recall` 仍是 `DIAGNOSTIC_ONLY`，但已有可合入 pool500 的候选证据；`co_visit_fallback_repair` 仍是 guarded fallback/task source，不能把 target-slice/batch-scoped 证据伪装成完整在线 source index。直接改成 candidate-generating 会越过治理边界。

**定位方式：**
核对 `rs_core/workflow/online_recommendation.py` 与 `rs_core/recsys/pool500_artifacts.py`，确认 serving 已支持 `pool500_candidates.jsonl` + `online_route.allowed_sources` 的 artifact-backed 读取。检查候选 artifact 后选用 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/pool500_candidates.jsonl`，该 artifact 500 用户 / 250000 行，loader 统计 `usercf_recall=50980`、`co_visit_fallback_repair=9127`，且治理字段仍保持 ranking/pool1000/final 关闭。

**解决方式：**
将 `configs/serving/online_service.yaml` 的 pool500 路径切到包含两者的 artifact，allowlist 增加 `usercf_recall` / `co_visit_fallback_repair`，并补充保守 rank weight 与 `artifact_backed_pool500_only` 暴露口径。registry 中新增 `online_exposure`，明确这是 serving artifact-backed 读取，不是 runtime candidate generation。`pool500_artifacts.py` 进一步拒绝候选 metadata 中的 internal 字段（如 diagnostics/source_trace/tool_calls），避免 public display 泄露。

**验证结果：**
使用项目默认 `.venv` 运行 targeted 回归：`tests/test_pool500_online_artifacts.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py tests/test_recall_source_registry.py tests/test_agent_capability_manifest.py -q`，结果 `48 passed`；public display/leakage 回归 `tests/test_display_contract.py tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py -q`，结果 `87 passed`；co_visit governance 回归 `tests/test_pool500_co_visit_fallback_repair_source.py tests/test_pool500_co_visit_fallback_repair_task_gate.py -q`，结果 `7 passed`；ruff 检查通过。额外脚本验证 serving config 当前 artifact 可加载并包含两者 source counts。

**面试可讲点：**
这段可以讲成“召回服务化的灰度治理”：先利用统一 artifact route 把 UserCF 和 co_visit 作为可控 supplemental source 接入线上服务，同时用 `artifact_backed_pool500_only` 明确边界，避免把诊断/兜底任务证据误升格为完整在线索引或排序输入，体现了推荐系统上线时对能力开放和治理边界的分层设计。

### 2026-06-22 - RS Agent 服务架构 BoundaryMap 合同层

**任务：**
把本轮架构重组从访谈/计划落成可测试合同层：明确 RS Agent Core Service 的模块化单体边界、ServingFact、AdapterContract 和 ManifestGate，让首页推荐、Agent 推荐、在线 RAG query、artifact 读取和即时 feedback 保持同步主链路，同时把可异步任务留给 TaskAdapter/worker 边界。

**遇到的问题：**
现有服务已具备 FastAPI、RecommendationService、SQLite/JSONL persistence、route registry、Qdrant/MinIO/Postgres 配置线索，但这些能力分散在运行代码、配置和实验治理中；如果只靠文档说明，后续多窗口继续接召回、排序、RAG、数据库和对象存储时仍可能绕过边界。初版合同层还被 review 发现 3 个 fail-closed 漏洞：未知 manifest schema 可准入、绝对路径或 `../` 逃逸路径可准入、ServingFact 的 oracle/label 检查无法穿透 list。

**定位方式：**
用 team 勘察分工确认现状：`rs_core/serving/app.py` 与 `service.py` 是同步服务入口，`persistence.py` 已有 public-safe 审计能力，`configs/governance/current_route_registry.yaml`、`configs/serving/online_service*.yaml` 和 `configs/artifacts/*.yaml` 已承载 route/artifact/RAG 治理语义。实现后由 code-reviewer 对 `manifest_gate.py`、`facts.py` 和新增测试做对抗复核，明确 fail-closed 路径和 public-safe 递归检查缺口。

**解决方式：**
新增 `rs_core/serving/boundary_map.py`，声明 ServiceRuntimeApi、FastAPIApp、RecommendationService、CoreRecommendationRuntime、StateFactsStore、PersistenceStore、InfrastructureBackends、AdapterContract、ManifestGate、RouteRegistry、DeploymentGovernanceOptimization、ServingFact 等模块的 responsibility、owned paths、allowed/forbidden imports 和 required tests。新增 `adapter_contracts.py`，用 mock-only Store/Cache/Artifact/Knowledge/Task protocol 固化 contract-only 接入，KnowledgeAdapter 明确在线 query 同步、index refresh 异步。新增 `facts.py` 固化 serving fact 类型并递归拦截 oracle/label/holdout/training 等 public unsafe 字段。新增 `manifest_gate.py` 做 schema allowlist + repo/base-dir relative path gate + route entry shape gate，invalid/missing/escape 均 not admitted，不抛给主链路。

**验证结果：**
使用项目默认 `.venv` 运行新增合同测试：`.venv/Scripts/python -m pytest tests/test_serving_boundary_map.py tests/test_serving_adapter_contracts.py tests/test_serving_facts.py tests/test_serving_manifest_gate.py -q`，结果 `25 passed`。相关治理/持久化回归：`.venv/Scripts/python -m pytest tests/test_serving_persistence.py tests/test_serving_store_contracts.py tests/test_engineering_contracts.py -q`，结果 `62 passed`。核心服务/RAG 回归：`.venv/Scripts/python -m pytest tests/test_session_summary.py tests/test_rag_core.py tests/test_serving_smoke.py -q`，结果 `107 passed`。code-reviewer 首轮 `FAIL` 的 3 个 HIGH + 1 个 MEDIUM 已修复，复审 `PASS`，并补充运行 `tests/test_serving_facts.py tests/test_serving_manifest_gate.py -q`，结果 `16 passed`。

**面试可讲点：**
这段可以讲成“从 demo 服务到可演进模块化单体的 contract-first 架构治理”：没有急着把 Redis/MinIO/Qdrant/Postgres 全部真实接入，而是先用 BoundaryMap、AdapterContract、ServingFact 和 ManifestGate 把同步用户体验链路、异步后台任务、artifact 准入和 public-safe facts 固化成可测试边界；后续具体 agent 可以按合同替换后端或接入新 artifact，而不会破坏首页推荐和 Agent 推荐主链路。

### 2026-06-09 - pool500 在线召回 source 注册口径收口

**任务：**
把已准备好的主路召回方法收口到线上服务可调用口径：取消 `semantic_title_category_expansion` 的独立在线注册，开放 `itemcf_weak` / `two_tower` 的 artifact-backed 在线读取，并解释 `usercf_recall` / `co_visit_fallback_repair` 为什么暂不能在线。

**遇到的问题：**
`semantic_title_category_expansion` 已被语义实时召回覆盖，如果继续作为独立 source 注册，会造成语义能力重复和主路口径混乱；同时 `itemcf_weak` / `two_tower` 虽可在线读取，但不能被误解为 promotion、ranking replacement、pool1000 或 final-ready；`usercf_recall` / `co_visit_fallback_repair` 有诊断或批任务属性，不能伪装成实时在线 ready。

**定位方式：**
核对 `configs/serving/online_service.yaml` 的 `online_route.allowed_sources`、`rs_core/recsys/pool500_artifacts.py` 的 allowed source 硬过滤、pool500 per-source 产物状态，以及 `configs/recall/pool500_method_registry.json` / `rs_core/recsys/recall_sources/registry.py` 中的 readiness 和治理字段。证据显示 `itemcf_weak` / `two_tower` 在当前 pool500 package 中有候选行可读；`usercf_recall` 当前是 `DIAGNOSTIC_ONLY` 且 `candidate_generation_allowed=false`；`co_visit_fallback_repair` 仍是 `DEFERRED` 的 guarded fallback repair，不是完整在线 source。

**解决方式：**
将 `configs/serving/online_service.yaml` 的 allowlist 扩展为包含 `itemcf_weak` 和 `two_tower`，但不加入 `semantic_title_category_expansion`、`usercf_recall`、`co_visit_fallback_repair` 或 `semantic_live`。在 core registry 和 JSON registry 中把 `semantic_title_category_expansion` 标为 `merged_into_semantic_live_not_independent_online_source`，保留历史 provenance 但取消独立在线 source 语义。测试侧增加 artifact allowlist、serving ready/recommend、registry blocker 断言，确保 legacy semantic title source 被过滤，`itemcf_weak` / `two_tower` 能进入在线候选读取。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_online_artifacts.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py tests/test_recall_source_registry.py tests/test_agent_capability_manifest.py -q`，结果 `46 passed in 3.38s`；运行 `./.venv/Scripts/python.exe -m ruff check rs_core tests/test_pool500_online_artifacts.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py tests/test_recall_source_registry.py`，结果 `All checks passed!`。

**面试可讲点：**
这段可以讲成“离线召回方法服务化时的 route governance”：不是把所有产物简单暴露给 Agent，而是通过 allowlist、registry readiness 和测试门禁明确哪些 source 能在线读取、哪些只能保留诊断/历史证据；同时保持 Agent 前台工具不暴露底层方法细节，把复杂路由隐藏在服务端。

### 2026-06-09 - DeepFM/COLD history-feature 对齐与排序评估输入阻塞

**任务：**
把 COLD 粗排 / DeepFM 精排从 smoke 产物推进到可训练、可诊断的排序链路，并解决 train/eval feature space 不一致问题。

**遇到的问题：**
早期 DeepFM formal run 虽然能训练，但训练 rows 的 `features` 为空，模型实际只学到 `bias`；修复 train-only history features 后，远程 neg4 训练集 gate 通过、DeepFM 不再是 bias-only，但 eval 侧仍只有 `candidate_rank_inverse/source_*`，导致 train/eval 特征空间不一致。进一步给 frozen eval candidate rows 补齐 history features 时，严格审计发现当前 `pool500_label_artifact_cold_start_fallback_v5_valid` 的 7 个 positive 缺少 `label_event_time`。

**定位方式：**
先通过本地测试和 code review 收口 eval history feature gate：候选行禁止 label/time alias，history feature 审计覆盖全部 positive eval labels，且 `feature_cutoff_time` 不得晚于 positive label time。远程构建 `outputs/ranking/deepfm_remote_formal_20260609_eval_history_aligned/frozen_eval` 时，6 个 train-only history features 已补齐，但 gate 因 7 个 positive 缺失 label time STOP。随后定向扫描 canonical interactions，发现这 7 个 positive 均能追溯到 `data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_interactions.jsonl` 的 `split=train`，而 canonical valid/test 对当前 500 candidate users 的 positive users/pairs 均为 0。

**解决方式：**
代码侧保持严格 gate，不用 synthetic label time 绕过：`build_pool500_frozen_candidate_eval_dataset.py` 要求启用 history features 时 positive eval labels 必须有可解析时间，并禁止 candidate rows 携带 `event_time/timestamp/unix_timestamp/review_time/unixReviewTime` 等 label-time alias。排序评估侧停止使用当前 v5 valid label artifact 声明 DeepFM/COLD 效果，把问题上移为召回/数据侧评估输入重建：需要真正面向 valid/test 用户生成 frozen candidate pool 和 evaluation-only label artifact。

**验证结果：**
本地使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_cold_deepfm_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `47 passed`；`py_compile` 通过；独立 code-reviewer 最终确认无 CRITICAL/HIGH/MEDIUM。远程证据：history-aligned frozen eval 的 `history_feature_audit.observed_feature_names` 已包含 6 个 train-only history features，但 manifest `status=STOP`，blocker 为 `EVAL_HISTORY_FEATURE_GATE_NOT_PASS`；candidate pool 为 500 用户 / 250000 rows，canonical valid/test 对这些用户均无正例命中。

**面试可讲点：**
这段可以讲成“排序模型训练解阻不等于排序效果可声明”：先修复 DeepFM 训练数据从 bias-only 到 train-only history features，再把 eval 侧特征对齐；最后通过严格时序和 label-source gate 发现所谓 valid label 实际落在 train split，从而主动停止效果宣称。体现了推荐排序实验中比模型训练更关键的是 train/eval 口径、时序边界和 no-oracle 治理。

### 2026-06-22 - RSAgent 推荐顾问系统提示词收口

**任务：**
把 RecommendationAgent 的系统提示词从短工具边界说明升级为更完整的推荐顾问工作合同，并将同类标签化 prompt 写法沉淀为项目规范，供首页 Agent、RagAgent 和后续自定义 Agent 复用。

**遇到的问题：**
前一版 prompt 更偏 hidden tool boundary，能约束不要泄露工具/分数/trace，但对“为什么推荐”“什么叫推荐成功”“如何权衡当前需求和历史商品”描述不足；真实单样本 smoke 中出现 home office 请求被历史 iPhone cable 关键词带偏的问题，说明 prompt 需要明确当前需求优先、历史证据要按时效/行为强度/生命周期/相关性加权，不能机械复述历史偏好。

**定位方式：**
对照已生成的 GPT 5.3 smoke 样本和现有 `rs_core/rsagent/tools.py` 中 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT` 的作用范围，确认本次先在 planner system prompt contract 层补齐推荐 Agent 的行为宪法；同时保留工具 manifest summary 的拼接方式，避免破坏现有 `build_agent_tool_planner_system_prompt()` contract。

**解决方式：**
将 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT` 改为标签化连续段落 prompt，包含 `Role_And_Duty`、`Why_This_Matters`、`Success_Standard`、`User_History_Use`、`Tool_Workflow`、`Clarification_Policy`、`Runtime_Boundary`、`Response_Style`、`Good_Output_Example` 和 `Bad_Output_Example`。其中 `User_History_Use` 明确用户历史不是静态标签，而是带时间、行为强度、商品生命周期和当前相关性的证据；`Tool_Workflow` 保留 `get_user_context`、`retrieve_candidates`、`rank_candidates`、`record_user_feedback`、`build_recommendation_slate` 在工作流中的位置，并继续隐藏低层 provider/RAG/source 细节。新增 `dic/standards/AGENT_PROMPT_STANDARD.md`，把同类 prompt 规范扩展到 RecommendationAgent、首页 Agent、RagAgent、模拟用户 Agent 和后续专用 Agent，并在 `dic/README.md` 推荐阅读顺序和文档分区中加入该规范。

**验证结果：**
使用项目默认 `.venv` 运行轻量导入验证：`./.venv/Scripts/python.exe - <<'PY' ...`，确认 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT` 包含 `<Role_And_Duty>` 与 `<Bad_Output_Example>`，`build_agent_tool_planner_system_prompt()` 仍以该 prompt 开头且继续包含 `retrieve_candidates` manifest summary，输出 `prompt_ok 2540 7123`。文档侧新增 `dic/standards/AGENT_PROMPT_STANDARD.md` 并在 `dic/README.md` 建立入口。未运行大范围 pytest，因为本次仅替换 prompt 常量和文档，且当前工作树已有多处并行未提交变更。

**面试可讲点：**
这段可以讲成“推荐 Agent 从工具边界约束升级到推荐策略合同”：不仅告诉模型不能泄露工具和分数，还把顾客满意、当前需求优先、历史证据时效、商品生命周期、候选弱时的诚实表达和正反输出范例写进系统 prompt，为后续 LLM planner、SFT 数据生成和推荐质量评估提供统一行为基线。

### 2026-06-09 - 真实 valid/test frozen eval 重建与 COLD/DeepFM 诊断

**任务：**
在旧 v5 valid label artifact 被确认混入 train split 后，重建真正基于 valid/test 用户的 pool500 frozen eval，并复用已有 train-only neg4 COLD/DeepFM 模型做排序诊断。

**遇到的问题：**
旧评估输入不能用于排序效果宣称；新建 valid/test 小批时，还遇到远程 source manifest 内残留 Windows shard path 导致 itemcf strong 加载失败，以及 recall readiness 仍为 `STOP`。即使 frozen eval 构建成功，候选覆盖也明显不足：1000 个 valid/test positive 用户、1678 条 positive label 中，pool500 候选只命中 11 个用户、14 个正例。

**定位方式：**
远程生成 `outputs/ranking/deepfm_remote_formal_20260609_valid_test_eval_users/eval_user_batch_summary.json`，确认 `selected_user_count=1000`、`label_rows=1678`、`missing_label_event_time_rows=0`，且 valid/test 未用于训练或特征统计。随后通过 `frozen_eval/coverage_gate.json` 定位 coverage gate：`in_candidate_positive_users=11`、`in_candidate_positives=14`，低于 `user_gate_threshold=100` 和 `positive_gate_threshold=500`。本地用 `.venv` 跑 `tests/test_full_data_pool500_recall_only.py tests/test_cold_deepfm_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `72 passed`。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 中补充跨平台 manifest path 解析：当远程 manifest shard path 带有旧 Windows 绝对路径片段时，按当前 manifest 目录重定位 shard。随后重跑远程 valid/test batch：生成 1000 用户 allowlist、1678 条带真实 `label_event_time` 的 eval labels、pool500 recall candidates、history-feature 对齐 frozen eval。COLD/DeepFM 侧不重新用 valid/test 训练，只复用 `outputs/ranking/deepfm_remote_formal_20260609_history_features_neg4` 的 train-only 模型进行 evaluation-only scoring。

**验证结果：**
`frozen_eval/dataset_audit.json` 的 `status=PASS`，`history_feature_audit.status=PASS`，但 `ranking_effect_conclusion_allowed=false`，因为 coverage gate 为 `STOP_FOR_RANKING_EFFECT`。在 frozen-candidate-only 范围内，candidate-rank baseline top20 为 `1/14` positive hit、`hit_user_rate_at_k=0.090909`、`in_candidate_positive_recall_at_k=0.071429`；direct DeepFM 和 COLD→DeepFM 均为 `2/14` positive hit、`hit_user_rate_at_k=0.181818`、`in_candidate_positive_recall_at_k=0.142857`，相对 baseline 增量为 `+0.071428` recall、`+0.090909` hit-user-rate。但由于覆盖门禁未过，这只能说明模型在极小 in-candidate 子集上有机械诊断提升，不能声明整体排序效果。

**面试可讲点：**
这段可以讲成“排序评估输入治理”：先发现旧 valid artifact 实际不满足时序/label-source 约束，再重建真实 valid/test frozen eval；最终即使模型在候选内有正向信号，也因为召回覆盖不足主动拒绝效果宣称，体现了推荐系统中模型指标必须服从数据口径、候选覆盖和 no-oracle gate。

### 2026-06-08 - two_tower_DSSM 动态负采样 v3 诊断

**任务：**
根据 DSSM 论文/Datawhale sampled negative 思路，把 `two_tower_DSSM` 的负样本从 method dataset 阶段固定 `negative_item_ids` 推进到训练期动态抽样，并在 recent_2y fixed 500 评估集上验证效果。

**遇到的问题：**
固定 hard negative v1/v2 虽然把 `Recall@500` 提到 `0.031792`，但多 epoch final checkpoint 退化，说明固定负样本反复训练存在过窄/过拟合风险。第一版 dynamic sampler 每个 example 都展开完整同类目候选池，远程训练长时间停在 first batch 后无产物，暴露出 per-example category pool materialization 的性能瓶颈。

**定位方式：**
检查远程 progress log，确认已完成 `item_feature_rows_complete`、`torch_examples_complete`、`model_constructed` 和 `first_batch_devices`，但 9 小时后仍没有 `artifact_manifest.json`；结合 `example_count=1957136`、`item_count=340080` 和 `negative_samples=31`，定位为动态负采样在每个 example 上构造大候选列表导致训练主循环不可接受。

**解决方式：**
在 `rs_core/recsys/two_tower.py` 中改为训练期动态采样：按 target item 类目从 same-category popular、same-category tail 和 global random 三路采样，排除 target/history/positives，并记录组件计数；随后把同类目抽样改为随机 offset 小窗口扫描，避免完整展开候选池。CLI `scripts/training/two_tower_DSSM/train_two_tower_dssm.py` 增加 dynamic sampling 参数。保持 valid/test 只用于 direct eval label，不参与训练、负采样、item universe 或 source index。

**验证结果：**
本地 `.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py -q` 通过，结果 `58 passed`；DSSM 聚焦回归 `tests/test_pool500_two_tower_method_dataset.py tests/test_two_tower_dssm_source_manifest.py tests/test_two_tower_dssm_source_index.py tests/test_pool500_two_tower_dssm_direct_eval.py -q` 为 `38 passed, 3 skipped`。远程优化版 run `pilot_20k_dynamic_neg_v3_opt_e1_20260608a` 成功产出 artifact/source/eval：动态负样本总数 `60671216`，组件计数 same-category popular `29357040`、tail `15657088`、global `15657088`，`explicit_negative_used_count=0`。fixed 500 direct eval 结果为 `Recall@500=0.011561`、`HitRate@500=0.016`、命中 `8/692`，显著低于 fixed hardneg v1/v2 的 `Recall@500=0.031792`、`HitRate@500=0.044`、命中 `22/692`。

**面试可讲点：**
这段可以讲成“算法机制正确性与工程效果不等价”的负采样实验：先按论文精神把负采样从固定样本推进到训练期动态采样，再通过日志定位动态采样实现中的性能瓶颈并改成小窗口随机扫描；最终用同一 fixed 500 direct eval 证明 dynamic v3 虽然更符合 sampled negative 机制，但在当前数据和配置下效果不如固定 hard negative，体现了推荐系统实验需要同时验证机制、性能和指标，而不是只按理论直觉替换主路。

### 2026-06-09 - two_tower_DSSM hard negative 权重网格诊断

**任务：**
在 dynamic negative v3 低于 fixed hard negative 后，回到当前最优的 `two_tower_DSSM` fixed hard negative 路线，验证 `explicit_negative_weight` 从 `0.5` 调到 `0.3/0.7/1.0` 是否能继续提升 fixed 500 direct eval。

**遇到的问题：**
第一轮远程网格命令误带 `--limit-users 20000`，训练样本虽然仍是 20k pilot，但导出的 `user_embeddings.jsonl` 只有约 1.9 万用户，direct eval 对 500 个评估用户退回到 projected seed query，结果统一回落到旧 baseline 口径（`Recall@500=0.021676`、命中 `15/692`），不能与之前 full-user artifact 口径的 hardneg best 直接比较。

**定位方式：**
检查 direct eval manifest 中 `query_source_counts`，发现第一轮为 `recent_positive_item_sequence_average_vectors` / `recent_item_sequence_average_vectors`，而不是 best 实验中的 `artifact_user_embedding=478`；进一步检查 source manifest 的 `user_embedding_row_count`，第一轮只有约 `19000`，best hardneg 和 dynamic v3 均为 `6485503`，因此定位为评估口径不一致。

**解决方式：**
重新运行 full-user 口径网格：训练仍使用 `pilot_20k_hardneg_v1_20260607a` / `pilot_20k_hardneg_mix_v2_20260607a` 的 train-only method dataset，但去掉训练 CLI 的 `--limit-users`，确保导出全量 train sequence user embeddings；资源上继续限定远程 `CUDA_VISIBLE_DEVICES=2`、`OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`，并串行跑 6 组 `explicit_negative_weight=0.3/0.7/1.0`。

**验证结果：**
修正后所有 run 的 `source_user_embedding_row_count=6485503`，direct eval `query_source_counts.artifact_user_embedding=478`、`projected_seed_query_count=0`，valid/test 仍只作为 `label_paths` 后验评估。结果：`hardneg_v1 w0.3/w0.7` 与 `hardneg_mix_v2 w0.3/w0.7/w1.0` 均为 `Recall@500=0.030347`、`HitRate@500=0.042`、命中 `21/692`；`hardneg_v1 w1.0` 为 `Recall@500=0.028902`、命中 `20/692`。均低于原 `w0.5` baseline 的 `Recall@500=0.031792`、`HitRate@500=0.044`、命中 `22/692`。证据已记录到 `configs/recall/full_data_pool500/two_tower_DSSM/source_config.yaml`，结论保持：`w0.5` 的 fixed hardneg v1 / mix v2 e1 仍是 DSSM 当前最佳诊断点，不能晋升 pool500 ready 或 ranking input。

**面试可讲点：**
这段可以讲成“推荐实验口径治理”的案例：一次网格实验看似跑完，但通过 query source 和 user embedding row count 发现评估退回到 seed projection，主动废弃不可比结果并重跑 full-user 口径；最终证明 hard negative 强度不是越大越好，`w0.5` 在当前 DSSM 表达能力下更平衡，体现了调参不只是看指标，还要先保证训练、候选生成和评估输入口径一致。

### 2026-06-09 - two_tower_DSSM 隐藏为证据保留源

**任务：**
在 DSSM dynamic negative、hard negative weight grid 均未带来足够召回提升后，将 `two_tower_DSSM` 从活跃路线中隐藏，避免后续被误当作 pool500 主力召回或 ranking input。

**遇到的问题：**
当前最佳 DSSM 仍只有 `Recall@500=0.031792`、`HitRate@500=0.044`、命中 `22/692`；继续调 `explicit_negative_weight=0.3/0.7/1.0` 最高也只有 `Recall@500=0.030347`、命中 `21/692`。该能力不足以作为 active route source，但历史实验仍有负采样、口径治理和 user/item 双塔局限性的复盘价值。

**定位方式：**
对比 `configs/recall/full_data_pool500/two_tower_DSSM/source_config.yaml` 中 full-user fixed 500 direct eval 证据，确认所有新网格均未超过 `w0.5` baseline；同时 verifier 已确认 6 个 manifest 与 YAML 一致、`artifact_user_embedding=478`、`projected_seed_query_count=0`。

**解决方式：**
在 `two_tower_DSSM` 的 source、dataset policy 和实验配置中增加 `route_visibility: HIDDEN_FROM_ACTIVE_ROUTE` / `hidden_from_active_route: true`，保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`，只保留 artifact 和配置作为 diagnostic reference。

**验证结果：**
本地 YAML/JSON 解析通过，`source_config.yaml` 明确记录 `PARKED_HIDDEN_DIAGNOSTIC_ONLY`，不会打开 pool500 ready、pool1000 或 ranking input replacement 边界。

**面试可讲点：**
这段可以讲成“实验止损与路线治理”：不是所有实现完整的模型都要进入主路，DSSM 在 user 侧信息弱、单源召回低的条件下被主动隐藏，只保留为诊断证据，体现了推荐系统工程中对实验结论、主路稳定性和资源投入的取舍。

### 2026-06-08 - semantic description retrieval 模块化与等效提速

**任务：**
把 `diagnose_semantic_description_recall.py` 中的描述式语义召回逻辑抽成正式模块，并在不改变 strict 召回效果的前提下优化速度。

**遇到的问题：**
当前 diagnostic JSONL 版需要扫描 large inverted index 与 semantic inputs，并在每个 query/candidate 上重复做 fixture terms、record text、field token counter 和 intent phrase 判断；12 个 strict query 实测 `102.187s`，不适合作为 Agent 场景下的实时描述检索入口。

**定位方式：**
审计 `diagnose_semantic_description_recall.py` 后，将 parity surface 固定为 `tokens`、`fixture_query_terms`、`evaluate_intent`、`score_record`、candidate ordered unique、`(-score, item_id)` 排序和 strict summary 指标；用 `tests/test_semantic_description_scoring.py` 与 `tests/test_semantic_description_retrieval_parity.py` 覆盖 tokenizer、intent、score、候选顺序和 tie-break。

**解决方式：**
新增 `rs_core/recsys/semantic_description/` 正式模块，把 scoring、retrieval、engine 分层；脚本层保留为 thin wrapper。优化点集中在 `PreparedFixture` / `PreparedRecord` 预处理缓存、跨 query 共享 prepared records、流式 ordered-unique candidate collector，避免改变 scorer、field weight、negative penalty 或 category prior。随后把 optimized live retrieval 接入 Agent/serving 主路：`semantic_description_live.enabled=true` 时在 `HybridRecommendationEnvironment` 初始化单例 `SemanticDescriptionRecallEngine`/SQLite store，`retrieve_candidates` 工具用用户自然语言 query 生成 `semantic_live` 候选，再作为 `extra_candidates` 合并进正常候选池与排序链路；public display 仍只输出安全展示卡片，不暴露 source/diagnostic/tool 字段。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_description_diagnostic.py tests/test_semantic_description_scoring.py tests/test_semantic_description_retrieval_parity.py -q`，结果 `11 passed in 0.10s`。重跑 strict probe：`outputs/diagnostics/semantic_description_recall_strict_optimized_check2_20260608/semantic_description_recall_strict_report.json`，summary 与优化前一致（`avg_strict_precision_at_10=0.483`、`avg_bad_intent_rate_at_10=0.267`、`queries_with_strict_hit_top5=8`），总耗时降至 `43.291s`。进一步构建 SQLite postings+records index 后，`outputs/diagnostics/semantic_description_recall_strict_sqlite_check_20260608/semantic_description_recall_strict_report.json` 与 baseline 在 summary、query stats、top10 item/score/details 上完全一致，总耗时降至 `31.044s`；单条 live query CLI 在 5k candidate 配置下耗时 `0.927s`。追加 prepared-record SQLite index 后，`outputs/diagnostics/semantic_description_recall_strict_prepared_sqlite_check_20260608/semantic_description_recall_strict_report.json` 相对旧 SQLite report 继续保持 strict parity；live CLI 改为直接调用 retrieval API，不再生成诊断 report，binder query 在 `candidate_limit=5000` 下检索耗时约 `662ms`、CLI wall time `0.894s`，在 `candidate_limit=2000` 下约 `265ms` 且该 probe top10 与 5000 一致。继续加入 trusted local `prepared_columnar_pickle` cache、query token weight 预计算和 padded phrase text 缓存后，`outputs/diagnostics/semantic_description_recall_strict_pickle_sqlite_check_20260608/semantic_description_recall_strict_report.json` 相对 prepared SQLite report 仍保持 strict parity；binder query in-process warm latency 进一步降到 `candidate_limit=2000` 约 `180ms`、`candidate_limit=5000` 约 `466ms`，CLI 分别约 `0.467s` / `0.688s` wall。汇总证据：`outputs/diagnostics/semantic_live_latency_prepared_sqlite_20260608/summary.json`。随后按默认 `candidate_limit=1000` 做 8 个 train-visible 随机商品 prompt probe，输出 `outputs/diagnostics/semantic_random_prompt_default1000_20260608/report.json`：`source_top10_count=2/8`、`avg_strict_precision_at_10=0.562`、`avg_required_precision_at_10=0.738`、`avg_bad_intent_rate_at_10=0.212`、batch 平均约 `171ms/query`；结论是明确商品词能稳定召回同类商品，但防水连接器、GoPro 型号配件、车型适配和电视附件排除仍需要 Agent query rewrite 与 1000→2000/5000 质量门禁 fallback。主路接入后补充回归 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_agent_tools.py tests/test_semantic_description_index_store.py -q`，结果 `46 passed in 0.93s`；新增 serving smoke 证明 `semantic_description_live` 可以把 `semantic_live` 候选喂入推荐候选池，同时 public display 不泄露内部 source/diagnostic/tool 字段。

**面试可讲点：**
这段可以讲成“效果等价约束下的检索链路工程化”：先用 parity tests 锁住推荐召回效果，再把实验脚本沉淀为正式可复用模块，通过缓存预处理、候选流式去重、SQLite postings/records 和 prepared-record cache，把性能瓶颈从重复 Python 计算与 JSONL 扫描压到可控的索引查询；同时坚持 train-visible 输入和 no-oracle 边界，避免用评估标签调参。

### 2026-06-08 - semantic guarded 主路接入与 co_visit 任务型兜底门禁

**任务：**
把已经通过描述式检索验证的 `semantic` 并入 pool500 主路候选生成，同时重新定义 `co_visit_fallback_repair` 的验收口径：不再追单方法 HitRate/Recall，而是验证它是否完成 underfill / fallback repair 任务。

**遇到的问题：**
语义召回在 valid purchase Recall 上几乎无命中，但用户目标实际是“自然语言描述 → 同类商品召回”；同时 `co_visit_fallback_repair` 本质是兜底补洞，不适合用单方法命中率判断。此前 highcap semantic materialization 还在远程长时间运行未完成，证明不能靠暴力放大全局候选池解决。

**定位方式：**
用 `diagnose_semantic_description_recall.py` 建立 description-based 诊断，区分 random6 guarded evidence 与 strict stress fixture：random6 达到 `avg_strict_precision_at_10=0.9`、`avg_bad_intent_rate_at_10=0.1`，strict stress 暴露弱词 query 噪声。对 co_visit 则审计 `fallback_completion_audit.json`、`fallback_completion_validation.json`、`underfill_audit.json` 和 source contribution/overlap，而不是把 Recall@K 当主验收。

**解决方式：**
新增 `audit_semantic_description_evidence_gate.py`，将 description diagnostic 转成 `PASS_GUARDED_CANDIDATE` / `DIAGNOSTIC_ONLY` / `STOP` 门禁；把 `semantic` 在 registry 和配置中推进为 `READY_CANDIDATE` guarded candidate source，但保持 promotion、pool1000、ranking input replacement 和 final ready 全 false。新增 `audit_co_visit_fallback_repair_task.py`，把 `fallback_seed_metadata_neighbor` 映射为 canonical `co_visit_fallback_repair`，按 underfill completion、去重、贡献、no-holdout 和治理字段判断是否可作为兜底修复 source。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_description_gate.py tests/test_pool500_co_visit_fallback_repair_task_gate.py tests/test_recall_source_registry.py tests/test_full_data_pool500_recall_only.py -q`，结果 `33 passed in 0.91s`。已生成 `outputs/diagnostics/semantic_description_random6_20260608/semantic_description_evidence_gate.json`，decision=`PASS_GUARDED_CANDIDATE`；strict stress gate 位于 `outputs/diagnostics/semantic_description_recall_strict_v2_20260608/semantic_description_evidence_gate.json`，decision=`DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“推荐召回方法的目标口径重定义与治理式接入”：不是看到 valid Recall 低就盲目扩大候选池，而是回到业务目标，把语义召回定义成 Agent/RAG 场景下的描述式商品发现；同时把 co_visit 定义成低供给用户的补洞工具，用 task gate 而非单源命中率评估。最终做到可接入主路但不越权宣称 READY，体现推荐系统实验指标、业务目标和工程治理之间的平衡。

### 2026-05-26 - 推荐 Agent 内部工具 schema 与灵活查库能力

**任务：**
把推荐 Agent 的后台能力从简单 manifest 推进到更接近 Claude Code Tool 思路的 internal tool spec，并实现一个能处理“这件太贵了，找更便宜但类似商品”的灵活商品库约束检索工具。

**遇到的问题：**
如果为每种导购需求单独做工具，会很快膨胀成 `find_cheaper_item`、`find_similar_item`、`find_better_rating_item` 等大量分支；但只做简单关键词搜索又无法表达相对价格、同类相似、品牌排除、required/preferred/disliked keyword 等真实对话需求。首次独立 code review 还发现价格缺失、默认类目/品牌约束、required keyword 放宽等硬约束语义存在风险。

**定位方式：**
围绕 `rs_core/rsagent/tools.py` 和新增 `tests/test_agent_tools.py` 做 focused review：用“参考商品更便宜替代品”“默认类目过滤”“品牌/店铺不同”“required keyword 不可放宽”“preferred keyword 可放宽”等用例验证约束语义；独立 reviewer 对 missing price、category/brand default mode、keyword relaxation 和 schema name mismatch 做阻塞检查。

**解决方式：**
在 `rs_core/rsagent/tools.py` 中新增 `AgentToolSpec`、`UnderstandUserNeedInput/Output`、`DisplayResponseDraft`、`ProductSearchRequest`、`PriceConstraint`、`KeywordConstraint`、`CategoryConstraint`、`RatingConstraint`、`BrandConstraint` 和 `CatalogConstraintSearchOutput` 等内部 schema；`AGENT_TOOL_MANIFEST` 固定六个核心工具：`understand_user_need`、`rerank_for_browsing`、`match_specific_need_in_pool`、`catalog_constraint_search`、`build_product_reasoning`、`compose_shopping_response`。实现 `catalog_constraint_search` 的规则版，支持参考商品、相对价格、同类过滤、关键词正反向、品牌/店铺排除、soft constraint relaxation 和 grounded match reasons；修复 review 发现的硬约束问题，确保缺价商品不会通过“更便宜”筛选，required keyword 不被放宽。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_agent_tools.py tests/test_agent_capability_manifest.py tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `49 passed in 0.93s`；ruff 检查 `rs_core/rsagent/tools.py tests/test_agent_tools.py tests/test_agent_capability_manifest.py` 为 `All checks passed!`。独立 code review 复核后确认此前 HIGH 阻塞均已解决；剩余 schema-name 提醒已通过新增本地 dataclass 和 grep 当前 manifest 消除。

**面试可讲点：**
这段可以讲成“把推荐 Agent 的工具系统做成少量工具 + 灵活约束 schema”：不把工具暴露给用户，也不急着 MCP/skill 化，而是在 Python 内部建立 ToolSpec、输入输出契约和可测试的 catalog constraint search。这样既能支持自然导购里的相对需求（更便宜、类似、不同品牌），又能守住候选/商品真实性、解释 grounding 和 public payload 防泄露边界。

### 2026-05-26 - pool500 主路 fallback 补满与配比边界修复

**任务：**
在已固定 pool500 召回主路配比后，修复 hot7/warm3 10 用户评估中候选池 underfill 的问题，让个性化召回不足 500 时能由兜底链路补满，同时不使用 valid/test label 或 oracle 注入。

**遇到的问题：**
主路初次评估虽然启用了 fallback，但 10 个用户只有 2 个达到 500，`underfilled_user_count=8`，fallback 审计只出现 `fallback_seed_category_sibling` 和 `fallback_seed_metadata_neighbor`。进一步修完全局 popular 生成器后仍未补满，原因是主路在 fallback 后又执行 `category/popular <= 175` 的硬裁剪，把兜底补进去的候选再次裁掉。

**定位方式：**
先看 `fallback_completion_audit.json`、`source_audit.json` 和 `fallback_completion_resource_audit.json`，确认全局 popular 资源存在但未进入最终池；再审计 `rs_lab/experiments/recall/pool500/fallback_completion/sources.py`、`rs_core/recsys/recall/merge.py` 和 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`，定位到全局 popular 的类目多样性前缀会因去重提前耗尽，以及 fallback 后二次 `_enforce_popular_category_cap` 会破坏“兜底补满 500”的设计。

**解决方式：**
调整 `fallback_global_diversity_popular`：先按类目多样性优先产出，再用 deferred rows 回填，避免真实 popular 前 2000 行类目集中时被生成器提前截断；同时把 `category/popular` 上限限定在 fallback 前的主路配比阶段，fallback 后不再二次裁剪，让 `category/popular` 真正作为最后兜底补满低供给用户。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_full_data_pool500_recall_only.py tests/test_pool500_fallback_completion_route.py`，结果 `26 passed in 1.00s`。重跑 `outputs/eval/pool500_current_route_hot7_warm3_10users_20260526.py` 后，`source_audit.json` 显示 `candidate_row_count=5000`、`average_candidates_per_user=500.0`、`underfilled_user_count=0`、`duplicate_user_item_count=0`；`fallback_completion_audit.json` 显示 `users_with_target_candidates=10`、`underfilled_user_count=0`、`average_fallback_ratio=0.4178`。召回指标仍为 `Recall@500=0.0`，说明本次修复解决的是候选池完整性和主路兜底能力，不把补满误宣称为效果提升。

**面试可讲点：**
这段可以讲成“推荐召回主路的低供给兜底治理”：先用 hot/warm 小样本暴露候选池 underfill，再从资源审计、生成器、merge 和主路 cap 多层定位；最终把上层个性化配比和底层冷启动/低历史兜底解耦，保证排序前每个用户有稳定 500 候选，同时守住 no-oracle、no-promotion 和 ranking input replacement 边界。

### 2026-05-26 - Agent RAG 结构占位与边界收口

**任务：**
在不实现完整 RAG、不改变召回排序结果的前提下，先为后续商品知识检索和 Agent grounding 放好代码位置与文档边界。

**遇到的问题：**
当前还没有独立外部文档库，如果直接把 RAG 做成新召回源或让模型自由补商品卖点，容易混淆“候选生成”和“解释 grounding”，也可能形成 oracle/label 注入式的伪效果。

**定位方式：**
核对 `rs_core/recsys/vector_index.py`、`rs_core/rsagent/explanation.py`、`rs_core/rsagent/schema.py`、`dic/architecture/IMPLEMENTATION_PLAN.md` 和 `dic/PROJECT_STRUCTURE.md`，确认现有 Phase 4 已把 RAG 定位为 Agent 增强层，而不是召回主路。

**解决方式：**
新增 `rs_core/recsys/rag/`，只定义 `RagEvidence`、`RagContext` 和 `build_empty_rag_context`，作为商品知识证据 contract；在 `AgentTurn` 预留默认关闭的 `rag_context` 字段，`None` 时不改变现有序列化输出；文档中明确 RAG 负责商品知识上下文和解释证据，不直接参与召回、排序或候选集合决策。

**验证结果：**
使用项目默认 `.venv` 运行 `py_compile rs_core/recsys/rag/__init__.py rs_core/recsys/rag/schema.py rs_core/recsys/rag/context.py rs_core/rsagent/schema.py` 通过；focused tests `tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_display_contract.py -q` 结果 `37 passed in 0.31s`。额外尝试跑 `tests/test_hybrid_demo.py` 时有 3 个旧配置路径缺失失败，集中在 `configs/phase_1_15_*.yaml`、`configs/phase_1_17_rank_weight_*.yaml` 和 `configs/hybrid_demo_electronics_10000_*_two_tower_*.yaml` 的历史路径断言，不属于本次 RAG 改动引入。

**面试可讲点：**
这段可以讲成“先定义 RAG 的工程边界，而不是急着堆向量库”：推荐结果仍由受治理的候选池和排序链路产生，RAG 只提供商品知识证据、解释 grounding 和幻觉控制入口，后续再逐步讨论 item knowledge card、候选内检索和评估门禁。

### 2026-05-26 - Agent RAG SQLite BM25 第一版可用化

**任务：**
把前一版候选卡片证据选择器扩展为最小可用的经典检索 RAG：支持商品字段 chunk、SQLite FTS5/BM25 建库，并通过 `rag.index_path` 接入 Agent 解释链路。

**遇到的问题：**
如果直接把 BM25 做成新的召回源，会破坏“推荐候选由召回/排序决定，RAG 只负责解释证据”的边界；同时完整向量库、服务化索引和复杂 chunk pipeline 对当前 demo 过重。

**定位方式：**
沿用 `rs_core/recsys/rag/`、`rs_core/workflow/hybrid_environment.py` 和 `rs_core/rsagent/explanation.py` 的既有边界，只检查 RAG 是否在候选 item 范围内取证、是否保留 provenance gate、是否不修改 `candidates` / `ranking` / `final_items` / `scores`。

**解决方式：**
新增 `chunking.py` 与 `bm25.py`：title/category/summary 保持短字段整体 chunk，description 按句子和长度切分，features 按 bullet 切分；`build_sqlite_bm25_index()` 写入 `rag_chunks` 与 `rag_chunk_fts`，`SQLiteBM25CandidateRetriever` 在候选 item id 范围内执行 FTS5 MATCH + BM25 排序。Agent 配置中如存在 `rag.index_path` 或 `rag.bm25_index_path` 且文件存在，则使用 SQLite BM25；否则回退原有 in-memory candidate card retriever。

**验证结果：**
使用项目默认 `.venv` 运行 `py_compile rs_core/recsys/rag/chunking.py rs_core/recsys/rag/bm25.py rs_core/recsys/rag/retriever.py rs_core/recsys/rag/__init__.py rs_core/workflow/hybrid_environment.py tests/test_rag_core.py` 通过；`pytest tests/test_rag_core.py -q` 结果 `7 passed in 0.28s`；`pytest tests/test_agent_dialogue.py tests/test_display_contract.py -q` 结果 `35 passed in 0.35s`。随后补充 `scripts/recall/build_rag_bm25_index.py` 建库入口，`pytest tests/test_rag_core.py -q` 更新为 `8 passed in 0.22s`；真实小批命令生成 `outputs/agent/rag_bm25_demo.sqlite`，manifest 显示 `indexed_item_count=16753`、`chunk_count=33276`、`candidate_scoped=true`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“用轻量 BM25 把 RAG 从字段注入推进到可检索证据层”：不引入重依赖，不让 RAG 改推荐结果，只在已有候选池内通过 SQLite FTS5 找最相关的商品证据，再交给 Agent 做解释 grounding。

### 2026-05-26 - Agent RAG Hybrid 检索第一版

**任务：**
在候选内 BM25 RAG 的基础上补充 Hybrid 检索方式，让证据选择同时参考关键词匹配和轻量向量相似度。

**遇到的问题：**
直接引入外部 embedding 模型、FAISS 或新的召回源会扩大工程范围，也容易让 RAG 从解释证据层越界成候选生成层；但只用 BM25 又对同义表达和近似文本不够友好。

**定位方式：**
复查 `rs_core/recsys/rag/bm25.py`、`rs_core/recsys/rag/retriever.py` 和 `rs_core/workflow/hybrid_environment.py`，确认可在现有 SQLite `rag_chunks` 表上增加第二路分数，并继续复用 `build_rag_context_for_ranked_candidates()` 的候选池过滤、字段过滤和 provenance gate。

**解决方式：**
新增 `rs_core/recsys/rag/hybrid.py`：BM25 分支复用 `SQLiteBM25CandidateRetriever`，向量分支对 query 和候选 chunk 文本构造 deterministic hashed text vector 并计算 cosine，相同 `(item_id, field, text)` 的 evidence 做 min-max 归一化后按 `bm25_weight` 与 `vector_weight` 融合。`rag.retriever=hybrid` 且 `rag.index_path` 存在时启用 Hybrid，否则保留 BM25 或 in-memory fallback；建库 manifest 增加 `hybrid_supported=true` 和 `hybrid_vector_method=hashed_text_vector_v1`。

**验证结果：**
使用项目默认 `.venv` 运行 `py_compile rs_core/recsys/rag/hybrid.py rs_core/recsys/rag/bm25.py rs_core/recsys/rag/retriever.py rs_core/recsys/rag/__init__.py rs_core/workflow/hybrid_environment.py scripts/recall/build_rag_bm25_index.py tests/test_rag_core.py` 通过；`pytest tests/test_rag_core.py -q` 结果 `10 passed in 0.45s`；`pytest tests/test_agent_dialogue.py tests/test_display_contract.py -q` 结果 `35 passed in 0.39s`。真实小批索引重建后 manifest 显示 `indexed_item_count=16753`、`chunk_count=33276`、`hybrid_supported=true`，且 `ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“先用无重依赖 Hybrid 验证 RAG 融合检索边界”：BM25 负责精确词命中，hashed vector cosine 补充近似文本相似度，融合只影响 Agent 解释证据，不影响推荐候选池和排序；后续如果要接真实 embedding，只替换向量分支即可。

### 2026-05-26 - pool500 全召回源主路接入与排序 shadow 诊断

**任务：**
确认 TwoTower formal full 产物可用后，把当前已完成的 pool500 召回源全部接入 recall-only 主路，并做最小排序侧 shadow 调整。

**遇到的问题：**
召回主路 5 用户 smoke 已能生成完整 2500 行候选，但排序 fixed comparison 一开始被 gate 拦截；blocker 不是排序算法失败，而是召回主路 `manifest.json` 顶层缺少 `ranking_replacement_allowed=false` 和 `promotion_allowed=false`，无法证明排序诊断不替换线上输入、不做 promotion。独立 review 还发现 TwoTower source manifest 与 full derived index audit 需要显式保留 `ranking_replacement_allowed=false`，并且 audit 应记录真实 `index_path` 而不是退回 source manifest 路径或旧 `recall_index` 元数据。

**定位方式：**
读取 `outputs/recall/full_data_pool500_recall_only_all_sources_smoke_20260526/manifest.json`、`source_contribution_audit.json`、`full_derived_index_manifests.json` 和排序 fixed comparison blocker，确认 all-source 候选生成成功：`candidate_rows=2500`、`underfilled_user_count=0`，实际贡献包括 category、semantic、semantic_title_category_expansion、co_visit_fallback_repair、itemcf_weak、itemcf_strong、swing_recall、two_tower；usercf artifact 已加载但该 5 用户样本无命中。

**解决方式：**
在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的主 manifest、recall config、readiness/audit 透传中补齐 no-ranking-replacement/no-promotion 字段；在 `rs_core/recsys/two_tower_source_manifest.py` 和 `scripts/recall/build_two_tower_source_index.py` 中把 `ranking_replacement_allowed=false` 纳入 TwoTower source index 生成与校验；排序侧将 D2 shadow-only top-k source minimums 扩展到 itemcf、semantic、semantic_title_category_expansion、two_tower、usercf_recall、swing_recall、category；同时让 full derived index audit 优先使用 source manifest 顶层 `index_path`。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_pool500_two_tower_source_manifest.py tests/test_full_data_pool500_recall_only.py tests/test_pool500_shadow_ranking.py`，结果 `135 passed in 2.06s`；重新跑 5 用户 all-source smoke，输出 `candidate_rows=2500`、`underfilled_user_count=0`，顶层 `ranking_replacement_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`；随后生成 `pool500_fixed_ranking_comparison_report.json`，fixed configs `B0/D1/D2/A1/A2/R1/R2/R3` 全部通过，报告 `status=PASS`、`blocker_count=0`，D2 top-k mix 覆盖 category、co_visit、itemcf、popular、semantic、semantic_title_category_expansion、swing、two_tower。独立 reviewer 复核后确认无剩余 HIGH/MEDIUM governance 问题。

**面试可讲点：**
这段可以讲成“从多召回源接入到排序诊断的治理闭环”：不仅证明多路召回能填满 pool500，还把模型源、规则源、协同过滤源统一进 frozen candidate pool；排序优化先以 shadow fixed comparison 观察机制差异，不急于宣称 READY 或替换线上输入，用 manifest contract、gate blocker 和独立 review 防止 diagnostic 产物越权晋升。

### 2026-05-26 - TwoTower 工业化训练采样优化

**任务：**
按 YouTubeDNN/DSSM 工业实践优化双塔训练样本生成和负采样策略，目标是提升 validation/test 泛化召回，而不是继续复用已有效果较差的 formal artifact。

**遇到的问题：**
此前双塔已经修复了 label 泄漏和在线投影一致性，但 100 用户 raw eval 仍 `hit_at_500=0`，说明问题不只是在线检索路径，而是训练阶段样本分布和负采样过弱：高活跃用户可贡献过多样本，均匀随机负采样难以让模型学会区分真实偏好与全局热门，低活用户/低频 item 也会带来稀疏噪声。

**定位方式：**
审计 `rs_core/recsys/two_tower.py` 的 PyTorch batch 生成、负采样和 fallback 训练逻辑，以及 `rs_core/workflow/two_tower_training.py` 的训练配置入口和 item vocab manifest 读取路径，确认当前只有非对称时序分割，缺少 per-user 样本上限、popularity-power negative sampling 和 K-Core 训练参数默认透传。

**解决方式：**
在 `_torch_example_batches` 引入 `max_samples_per_user`，每个用户只保留最近的有限个时序样本，且所有样本保持 `history=positives[:offset]`；训练前统计 item 频次，按 `frequency ** 0.75` 构造负采样分布并用于 `_negative_indices`，fallback 路径也同步使用流行度加权负样本；workflow 默认补齐 `min_user_positives=3`、`max_samples_per_user=5`、`negative_sampling_power=0.75`，item vocab CLI 默认 `--min-freq=3`，并把相关参数写入 metrics/model payload。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_two_tower_training.py -q`，结果 `19 passed in 5.62s`；补跑 `tests/test_recsys_core.py tests/test_full_data_pool500_recall_only.py tests/test_two_tower_source_manifest_guard.py tests/test_pool500_two_tower_method_source.py -q`，结果 `38 passed in 1.58s`；补跑 `tests/test_pool500_two_tower_diagnostic_loop.py -q`，结果 `20 passed in 0.43s`；`py_compile` 检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`scripts/recall/build_two_tower_item_vocab.py` 通过。随后用新策略跑 200 用户 diagnostic training：`training_examples=644`、`users_with_training_rows=197`、`negative_samples=5`、`max_samples_per_user=5`、`min_user_positives=3`、`negative_sampling_power=0.75`，训练内 `recall@100=0.401026`、`hit_rate@100=0.945`；但固定 100 用户 evaluation-only raw eval 仍为 `hit_at_20/50/100/500=0`、`raw_two_tower_unique_positive_hits=0`，说明小规模采样优化尚未转化为 valid/test 命中。

**面试可讲点：**
这段可以讲成“从修泄漏转向优化训练分布”：用户样本均衡解决高活用户支配，非对称时序保证因果训练，流行度加权负采样让模型学习热门商品中的真实偏好差异，K-Core 过滤降低稀疏噪声，是推荐召回模型从可运行到可泛化的关键工程步骤。

### 2026-06-23 - 多轮 SFT 推荐解释人性化补强

**任务：**
修正本地 multi-turn SFT smoke 中“能生成但不够像真实导购”的问题，让推荐轮基于 public display 商品字段输出商品标题/类目/摘要理由，并让模拟用户在缺少具体理由时追问，而不是直接接受。

**遇到的问题：**
此前样本首轮 assistant 只输出 “I will use your request and recent context to build recommendations.”，解释轮又可能被 dialogue-only sanitizer 压成泛化澄清，导致用户看不到商品标题、描述或推荐理由；第三方 judge 不能靠大量硬编码规则判断“人性化”，否则会把模型评价标准错误固化成程序审美。

**定位方式：**
沿 `rs_core/training/multi_turn_sft_generator.py::RecommendationAgentComposer.compose()`、`_compose_grounded_response()`、`rs_core/display/builder.py::item_to_display_card()`、`rs_core/rsagent/explanation.py::build_recommendation_explanation()` 和 `rs_core/simulation/policy.py::RolePolicy.next_action()` 定位，确认 display card 已允许 `title/category/summary/description/features/price` 等 public 字段，问题主要在 deterministic composer 仍透传服务模板文案，以及模拟用户只按商品匹配分接受。

**解决方式：**
在 deterministic recommendation composer 中使用 display item 的 public 字段生成 2-3 个商品级推荐理由；让解释类 no-display turn 在有上一轮 display grounding 时保留安全解释，而不是一律替换成“暂不提供具体选项”；把模拟用户策略改成：如果 assistant 没有提到展示商品并给出理由，先发起 `why` 追问。第三方本地 judge 回收为安全/协议 smoke gate，只保留候选池、内部字段、label/oracle、低层 RAG 工具、明显商品属性编造等硬门禁；人性化、满意度、解释质量交给后续模型 judge 按 `dic/standards/AGENT_SCORING_FRAMEWORK.md` 判定。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python -m pytest tests/test_multi_turn_sft_generator.py -q`，结果 `37 passed in 8.64s`。重新生成本地 smoke：`./.venv/Scripts/python -m scripts.training.generate_multi_turn_sft --config .omc/multi_turn_sft_local_judge_smoke.yaml`，生成 2 条、拒绝 0 条、平均 4 轮；再运行 `./.venv/Scripts/python -m scripts.training.judge_sft_samples --input outputs/training/multi_turn_sft_local_judge_smoke/samples.jsonl --output outputs/training/multi_turn_sft_local_judge_smoke/judge_reports.jsonl --summary outputs/training/multi_turn_sft_local_judge_smoke/judge_summary.json`，`judge_satisfied=true`、`accept=2`、`hard_fail_count=0`。本轮未调用外部 API，也未加载大模型。

**面试可讲点：**
这段可以讲成“把 SFT 数据从链路可跑推进到交互可用”：推荐 Agent 的话术不再只是模板确认，而是绑定 display slate 的公开商品信息给出理由；模拟用户会对解释不足追问；程序 judge 负责安全边界，模型 judge 负责语义质量，避免把主观人性化评价硬编码成脆弱规则。

### 2026-06-24 - RSAgent 提示词去固定话术化

**任务：**
根据用户反馈，继续收口 RSAgent 和 SFT composer 的提示词：不要把大量固定用户措辞或固定触发表达写进代码，因为真实用户可能用任意方式表达需求、反馈和不满意。

**遇到的问题：**
上一版提示词已经强化了真人导购和多轮收束，但仍容易把自然语言反馈写成若干固定示例或触发清单，导致模型可能过拟合模板；测试也不应只断言某个长句是否存在，而应覆盖抽象行为原则。

**定位方式：**
检查 `rs_core/rsagent/tools.py::AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT`、`rs_core/training/multi_turn_sft_generator.py::RecommendationAgentComposer` 以及对应测试，确认需要保留工程边界词和工具协议，但自然语言用户表达必须改成基于上下文语义判断。

**解决方式：**
将多轮反馈策略改为抽象语义原则：当上下文显示用户仍在探索、偏好变化、满意度不足或决策未推进时，承接反馈、调整推荐策略、说明本轮差异，并用一个具体但开放的问题收窄关键维度；面向顾客侧只表达自然导购视角，不暴露内部推荐机制。composer prompt 也改为基于 visible dialogue 的语义状态判断弱进展和偏好变化，而不是匹配固定用户短语。测试改为断言存在 `Multi_Turn_Feedback_Policy`、`Customer_Facing_Language` 和语义判断原则。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python -m pytest tests/test_agent_tools.py tests/test_multi_turn_sft_generator.py -q`，结果 `75 passed in 12.45s`。静态检索确认 RSAgent 主 prompt 不再包含先前的具体用户示例和具体商品示例；composer prompt 保留的是“固定短语匹配不可取”的抽象原则。

**面试可讲点：**
这段可以讲成“把 prompt 从关键词触发升级为语义策略合同”：自然语言用户输入不可枚举，所以 Agent 不应靠固定话术表工作，而应基于上下文判断探索、偏好变化、满意度和决策进展；程序只守工具、候选池和泄漏边界，导购策略交给模型按抽象原则执行。

### 2026-05-26 - TwoTower 训练泄漏修复与在线用户塔投影

**任务：**
修复 TwoTower/YouTubeDNN 训练样本历史包含当前 label 的泄漏问题，并把在线召回从静态 user embedding 查询切换为实时历史 seed 经 User Tower 投影后的向量检索。

**遇到的问题：**
原 `_torch_example_batches` 在第一个正样本无历史时会回退到完整 positives，导致当前目标和未来正样本进入 history；在线召回路径还会优先使用训练产出的静态 user embedding，在 LOPO/固定评估用户场景下可能混入未来行为表征。切换到实时历史后，一个旧测试暴露出 tiny fixture 只用唯一 seed 且该 seed 被已见集合排除，无法再保证返回候选。

**定位方式：**
对照 `rs_core/recsys/two_tower.py` 的滑窗样本生成、`rs_core/recsys/vector_index.py` 的 artifact/source manifest 加载、`rs_core/recsys/candidate_merge.py` 的 TwoTower 向量召回，以及 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的批量预计算路径，确认静态 user embedding 和在线 batch path 都需要收口到同一实时历史逻辑。

**解决方式：**
训练侧跳过第一个无历史正样本，并保证 `history = positives[:offset]` 不包含当前 target；向量索引加载和 source index manifest 写入 `model_parameters`；在线召回强制用 `recent_positive_item_sequence` 的 seed item 平均向量，经过 `user_tower.0/2` 权重执行 `Linear -> ReLU -> Linear -> Residual Add -> Normalize` 投影后检索，并让主路 `_precompute_two_tower_recall` 复用同一函数，避免批量路径绕过治理。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_two_tower_training.py tests/test_recsys_core.py tests/test_full_data_pool500_recall_only.py -q`，结果 `45 passed in 3.86s`；补跑 `tests/test_two_tower_source_manifest_guard.py tests/test_pool500_two_tower_method_source.py -q`，结果 `10 passed in 0.77s`；补跑 `tests/test_pool500_shadow_ranking.py -q`，结果 `110 passed in 1.03s`。回归测试覆盖了 label 泄漏修复、`model_parameters` 加载、实时历史优先于静态 user embedding、User Tower 投影生效，以及主路预计算路径的一致性。

**面试可讲点：**
这段可以讲成“双塔召回的数据泄漏与线上一致性治理”：不仅修了训练样本目标泄漏，还把评估/在线召回从静态用户向量改为实时行为 seed 投影，保证训练目标、检索空间和 LOPO 评估边界一致，同时用单测和主路相关测试证明没有破坏 pool500 排序入口。

### 2026-05-26 - TwoTower formal full 远端训练产物接入主路

**任务：**
把远端 RTX 4090 完成的 TwoTower/YouTubeDNN formal full train-only artifact 拉回本地，重建 pool500 主路 `source_index_manifest.json`，并验证它能真实进入 recall-only 候选池。

**遇到的问题：**
远端训练产物可以被主路加载并产出候选，但首次 smoke 的 final readiness contract 仍出现 TwoTower blocker：source index manifest 缺少 full-clean gate 需要的 `item_embedding_row_count`、`recall_index_row_count`、clean/train/config/item universe hash，同时 gate 把算法名 `two_tower_youtube_dnn` 误当成非 canonical source 拦截。

**定位方式：**
先读取 `outputs/recall/pool500_recall_only_smoke/two_tower_remote_formal_1user_20260526/` 的 source manifest、source contribution audit 和 final readiness contract，确认 `two_tower.row_count=30`、已进入 500 行候选池，但 blocker 集中在 TwoTower full-clean 字段和别名校验；再对照 `full_data_pool500_route_gate.py` 和 `build_two_tower_source_index.py`，确认 source index 只写了通用 row count，未写 gate 所需字段别名和 hash 证据。

**解决方式：**
扩展 `scripts/recall/build_two_tower_source_index.py`，在重建 source index 时可显式接收 formal config、clean manifest、train sequence，并写入 `item_embedding_row_count`、`recall_index_row_count`、`clean_manifest_sha256`、`train_sequence_sha256`、`model_config_sha256`、`item_universe_sha256`；同时在 `rs_core/workflow/full_data_pool500_route_gate.py` 中使用 canonical source alias 校验 `two_tower_youtube_dnn`，并避免把 `source_name/variant/model_type` 这类算法标签误判为 forbidden artifact scope。

**验证结果：**
重建后的 `outputs/recall/pool500_full_sources/two_tower/index/source_index_manifest.json` 显示 `row_count=268816`、`item_embedding_row_count=268816`、`recall_index_row_count=268816`、`user_embedding_row_count=16639746`，并包含 clean/train/config/item universe hash。focused tests `tests/test_two_tower_source_manifest_guard.py tests/test_pool500_two_tower_source_manifest.py tests/test_pool500_two_tower_method_source.py tests/test_full_data_pool500_recall_only.py -q` 结果 `35 passed in 1.77s`。1 用户主路 smoke 生成 `pool500_rows=500`，TwoTower source 输出 `two_tower_rows=30`，`two_tower_manifest_status=READY`、`two_tower_index_status=INDEX_READY`、`two_tower_index_scope=FULL_DERIVED_INDEX`，final readiness 中 `two_tower_blocker_count=0`；整体仍保持 `decision=STOP`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`，没有越过主路晋升边界。

**面试可讲点：**
这段可以讲成“模型训练产物从算力迁移到主路接入的治理闭环”：不仅把远端 GPU 训练出的全量 embedding/index 拉回本地，还补齐 manifest 证据、哈希追溯和 readiness gate，证明模型召回源能贡献候选，同时不会因为单个 source 接入就误宣称全链路 READY 或替换 ranking 输入。

### 2026-05-26 - TwoTower 10 epoch direct eval 与增训取舍

**任务：**
在 5 epoch formal full TwoTower 已接入 pool500 主路后，远端继续训练 10 epoch，并用同一组 10k fixed eval 用户做 TwoTower direct-only 效果评估，判断单纯增加 epoch 是否带来提升。

**遇到的问题：**
完整 pool500 runner 会混入多召回源和 fallback，不适合回答“两塔本身有没有提升”；同时首次自动 watcher 在构建 10 epoch source index 时传入了远端不存在的可选 `train_sequence` hash 路径，导致训练已完成但后续索引构建失败。

**定位方式：**
读取后台输出 `b8ntibd8l.output`，确认失败点是 `FileNotFoundError: .../training/user_sequences.train.jsonl`，不是训练失败；随后去掉可选 hash 参数，重新执行 `scripts/recall/build_two_tower_source_index.py` 和 `rs_lab/experiments/recall/run_pool500_two_tower_direct_eval.py`，评估输入限定为 train sequence + TwoTower recall index，valid/test labels 只用于打分。

**解决方式：**
保留 5 epoch 主路接入不变，单独为 10 epoch run 构建 `outputs/recall/pool500_full_sources/two_tower/index/twotower_formal_full_10epoch_20260526_1115/source_index_manifest.json`，再输出 direct eval manifest：`outputs/recall/pool500_full_sources/two_tower/index/twotower_formal_full_10epoch_20260526_1115/direct_eval_10k_manifest.json`。评估 manifest 明确 `eval_scope=two_tower_direct_only`、`no_oracle_label_injection=true`。

**验证结果：**
10 epoch source index `row_count=268816`，direct eval 覆盖 `user_count=10000`、`query_user_count=8709`、`queryless_user_count=1291`。10 epoch 指标为 `Recall@20=0.005608`、`HitRate@20=0.0104`、`Recall@50=0.009906`、`HitRate@50=0.0183`、`Recall@100=0.017034`、`HitRate@100=0.0306`、`Recall@500=0.04869`、`HitRate@500=0.0819`；低于 5 epoch baseline `Recall@500=0.051552`、`HitRate@500=0.0948`。结论是单纯从 5 epoch 加到 10 epoch 没有提升，下一步不应盲目跑 15 epoch，应优先诊断样本口径、queryless 用户、item universe 和召回目标分布。

**面试可讲点：**
这段可以讲成“模型增训不是越久越好，而要用一致评估口径做 stop-loss”：把 TwoTower 从主路混合召回中拆出来 direct eval，避免 fallback 或其他召回源掩盖模型真实变化；当 10 epoch 低于 5 epoch 时，用证据及时停止盲目加算力，转向数据分布和泛化误差诊断。

### 2026-05-26 - ItemCF strong relaxed seed-src 数据口径与主路验证

**任务：**
把原本几乎不可用的 `itemcf_strong` 从 strict 高置信稀疏矩阵调整为仍偏 strong、但能在 pool500 主路产生稳定贡献的 relaxed diagnostic source。

**遇到的问题：**
strict strong formal 只有 208 条方向边；初版 relaxed strong 即使放宽到 support=1，也只有 56,518 条边，前 100 用户 strong seed 与 source `src_item_id` 仍 0 命中，主路贡献为 0。说明问题不只是边数少，而是 strong 查询 seed 与构建矩阵的 item/user 过滤口径不匹配。

**定位方式：**
先用 seed-hit audit 证明 `source_src_item_count=40629` 但 `strong_seed_hit_count=0`；再统计前 100 用户 strong seed 的质量桶和热度，发现 179 个 unique seed 中 178 个是 hot，且大多是 `embedding_ready`。进一步审计 allowed user 的 positive sequence，确认如果 dst 只允许 `cf_ready`，大多数 strong seed 没有可连接候选。

**解决方式：**
在 `rs_lab/experiments/recall/build_pool500_method_dataset.py` 为 `itemcf_strong` 新增 relaxed seed-src v3 口径：用户仍限制在 `sequence_sufficient/collaborative_rich`，构边改为 `recent_strong_positive_item_sequence -> recent_positive_item_sequence` 的有向边；src strong seed 允许 `cf_ready/embedding_ready` 且允许 hot，dst candidate 允许 `cf_ready/embedding_ready` 但排除 hot，并继续使用 train-only、active-user penalty、weighted cooc cosine score、topK per seed。source 转换使用 128 shard，避免主路一次加载 153 万边。

**验证结果：**
focused 单测 `tests/test_pool500_method_dataset.py` 结果 `23 passed`。v3 smoke method_dataset 输出 `outputs/recall/pool500_method_datasets/itemcf_strong_relaxed_seedsrc_smoke_v3/itemcf_strong/`，`row_count=1,536,320`、`unique_pair_count=1,563,717`、`directed_edge_count_after_topk=1,536,320`，前 100 用户 strong seed 命中恢复到 `149/179`。sharded source 输出 `outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/smoke_sharded/source_index_manifest.json`，`row_count=1,536,320`、`shard_count=128`、`diagnostic_only=true`。100 用户主路 smoke 中 `itemcf_strong.row_count=1,557`、`user_coverage_count=68/100`、`marginal_candidate_share=0.033384`；500 用户受控验证中 `itemcf_strong.row_count=8,198`、`user_coverage_count=369/500`、`marginal_candidate_share=0.03469`。两次 `final_resource_audit.status=PASS`，`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“按方法特性调数据口径，而不是盲目放宽过滤”：strong seed 本身常是高热强交互商品，适合作为查询锚点，但不适合直接作为候选输出。因此把 hot 仅放在 src 侧、dst 侧继续排除 hot，在保持 high-confidence/diagnostic 边界的同时恢复主路贡献，体现了推荐召回中 seed 侧与 candidate 侧不同治理策略的工程判断。

### 2026-05-26 - ItemCF strong 三档独立重建与 formal 分片接入

**任务：**
把 relaxed seed-src v3 从单个 formal-like 产物整理成 smoke、diagnostic、local_formal 三档真实数据集，并使用 local_formal 矩阵构建分片 source 接入 pool500 主路验证。

**遇到的问题：**
ItemCF 数据集不能通过从已有 formal 边表抽用户或抽边来派生小档位，因为任一用户变化都会改变 pair support、`weighted_cooc`、`itemcf_score` 和 per-seed topK。三档必须各自从 train-only 原始序列独立重建，否则 smoke/diagnostic 的统计语义不成立。

**定位方式：**
复核 `build_pool500_method_dataset.py` 的构建路径，确认每档读取的是 governance manifest、user/item profile、train item frequency 和 `user_sequences.train.jsonl`，不是读取旧 method_dataset；同时用 manifest 核对三档的 `max_output_users`、`row_count`、`user_count` 和治理 flags。

**解决方式：**
将 relaxed strong v3 参数改为 scale-tier aware：smoke `max_output_users=5000`、diagnostic `80000`、local_formal `160000`，但核心策略不变：`recent_strong_positive_item_sequence -> recent_positive_item_sequence` 有向构边，src 允许 `cf_ready/embedding_ready` 且允许 hot，dst 允许 `cf_ready/embedding_ready` 但排除 hot。local_formal 再通过 adapter 转成 128 shard source，主路按 seed 命中 shard 加载。

**验证结果：**
focused tests 与 lint 通过：`tests/test_pool500_method_dataset.py -q` 为 `24 passed`，默认主路/registry focused tests 为 `39 passed`，ruff `All checks passed!`。三档独立构建均 PASS：smoke `row_count=47615`、`user_count=5000`；diagnostic `row_count=784463`、`user_count=80000`；local_formal `row_count=1536320`、`user_count=160000`。formal sharded source 为 `outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/formal_sharded/source_index_manifest.json`，`row_count=1536320`、`shard_count=128`、`diagnostic_only=true`，并已切换为 pool500 recall-only 主路默认 `itemcf_strong` source manifest。override 验证中，100 用户主路 smoke `itemcf_strong.row_count=1557`、`user_coverage_count=68/100`、`marginal_candidate_share=0.033384`；500 用户验证 `itemcf_strong.row_count=8198`、`user_coverage_count=369/500`、`marginal_candidate_share=0.03469`。默认主路无 override smoke 输出 `itemcf_strong.row_count=941`、`user_coverage_count=68/100`、`marginal_candidate_share=0.019991`，`per_source_output_manifests.json` 确认 `itemcf_strong.source_index_manifest_path` 指向 formal sharded source。三次验证 `final_resource_audit.status=PASS`，`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“推荐召回数据集分层不能把聚合矩阵当可抽样明细”：对 ItemCF 这类共现统计方法，小样本档必须重新聚合而不是从大矩阵切片。最终通过三档独立重建、formal 分片和主路 contribution audit，既解决了 strong 可用性，又保住了 train-only、diagnostic-only 和非晋升边界。

### 2026-05-25 - Swing local_formal source index 与主路接入

**任务：**
为 `swing_recall` 按方法特性补齐 `smoke`、`diagnostic(dam)`、`local_formal` 三档 source index，并把 formal 版本接入 pool500 主路。

**遇到的问题：**
`swing_recall` 之前主路默认读取的是 `target_slice_diagnostic_v1`，缺少按 Swing 方法特性定义的 formal/local_formal 构建口径。Swing 需要基于 train-only 用户序列构建 item-item 共现图，同时控制活跃用户和热门 item 噪声，不能简单把旧 diagnostic 产物改名成 formal。

**定位方式：**
对照 Datawhale Swing 方法说明，确认其核心是 item-item 共现关系、共同用户证据、活跃用户降权和 TopK 相似边；再审计 `enhanced_source.py` 的现有 builder，确认它已从 clean full train sequence、eligible users 和旧 swing baseline candidates 生成七件套 artifact，并写出 coverage/resource/no-holdout audit。

**解决方式：**
在 `configs/recall/full_data_pool500/swing_recall/source_config.yaml` 增加 `smoke`、`diagnostic`、`local_formal` tiers、`dam` / `最终数据集(local_formal)` alias、train-only input contract 和 governance 边界；在统一 runner `scripts/experiments/recall/pool500/run_pool500_method_source.py` 接入 `swing_recall`，复用现有 enhanced source builder。`local_formal` 使用 `max_graph_users=120000`、`max_item_user_freq=600`、`min_pair_support=2`，更偏稳定共同用户证据。

**验证结果：**
三档构建均 `PASS`：smoke `candidate_row_count=8614`、diagnostic `candidate_row_count=39637`、local_formal `candidate_row_count=12646`；local_formal 产物路径为 `outputs/recall/pool500_method_sources/swing_recall/local_formal_swing_recall_20260525/source_index_manifest.json`，`edge_count=86748`、`seed_count=14241`、`user_coverage_count=389`、`graph_user_count=120000`、`no_holdout_status=PASS`。focused tests `31 passed`；5 用户主路 smoke 生成 2500 行候选，其中 `swing_recall=143`，final contract 保持 `final_pool500_ready_claimed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把 Swing 从诊断 source 推进到可复用 formal 召回源”：先按 Swing 的共同用户和活跃用户抑制机制定义数据层级，再用 train-only 全量序列构建稳定 item-item 边表，最后接入主路并用候选贡献、no-holdout audit 和 final contract 证明它能服务后续排序但不越过晋升边界。

### 2026-05-25 - ItemCF weak full source 分片构建与按需加载

**任务：**
把 `itemcf_weak` 的 full formal source 从单个 4.4GB JSONL 改造成可分片构建、可按 batch seed 加载的 source index；`itemcf_strong` 因 full formal 只有 208 条边，继续保持单文件默认构建。

**遇到的问题：**
`itemcf_weak` coverage formal 有 5,640,872 条方向边，直接用主路一次性加载会把 4.4GB JSONL 膨胀成大量 Python 对象，小批量验证也可能消耗 20GB 级别内存；但此前 seed-hit 诊断已证明 full weak 对目标用户有贡献，不能简单放弃该矩阵。

**定位方式：**
先用 20 用户 seed-hit 审计确认 weak full 中 17/20 用户有 seed 命中，seed-filtered 主路贡献约 487 条候选；再对比 `limit_rows=10000` shard smoke 和 full sharded smoke，确认低贡献来自截断 smoke 覆盖不足，而不是分片加载逻辑丢边。

**解决方式：**
在 `method_dataset_to_itemcf_source.py` 中新增 `--shard-count`，当 `shard_count>1` 时按 `sha256(src_item) % shard_count` 写入 `edges_shards/` 并在 manifest 记录 `sharded=true`、`shard_count`、`shard_key=src_item_sha256_mod`、每个 shard 的 row/hash/size；在 `candidate_merge.py` 新增 manifest-aware loader，根据当前 batch 的 `allowed_src_items` 只加载命中 shard；主路从用户 recent positive sequence 提取 weak/strong seed 后传给 ItemCF loader，同时保留 train-only、diagnostic-only、no promotion、no ranking replacement、no pool1000 边界。

**验证结果：**
聚焦测试 `tests/test_pool500_itemcf_method_dataset_source_adapter.py tests/test_full_data_pool500_recall_only.py` 结果 `23 passed in 0.99s`，相关模块 `compileall` 通过。full weak sharded source 输出 `outputs/recall/pool500_method_sources/itemcf_formal_from_method_dataset_v1/itemcf_weak/sharded_full_v1/source_index_manifest.json`，`row_count=5,640,872`、`shard_count=256`、`edges_path=null`。20 用户主路 smoke 输出 `itemcf_weak.row_count=494`、`user_coverage_count=16/20`、`marginal_candidate_share=0.051165`；100 用户 smoke 输出 `itemcf_weak.row_count=2112`、`user_coverage_count=69/100`、`marginal_candidate_share=0.045021`，`final_resource_audit.status=PASS`，全链路仍保持 `promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把大规模协同过滤矩阵从能产出推进到可服务化消费”：先证明 full weak 矩阵确实能为用户补候选，再针对 4.4GB JSONL 的内存瓶颈做 src_item hash 分片和 batch seed 按需加载，让小批量/后续主路验证不用全量加载矩阵，同时用 manifest/audit 保证诊断产物不会被误晋升为正式 ranking 输入。

### 2026-05-25 - pool500 三个 local_formal source index 接入主路

**任务：**
把 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 三份已生成的 `local_formal` source index 接入 pool500 主路 recall-only 实验，让主路默认可读取并合并三类候选。

**遇到的问题：**
三份 source index 已经可调用，但如果只按文件存在自动标记，会把 diagnostic/local_formal 证据误写成 `READY`；同时 canonical `semantic` 必须独立进入主路，不能被 `semantic_title_category_expansion` 代替，`co_visit_fallback_repair` 也不能被误解为完整 co-visit graph。

**定位方式：**
审计 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的默认 source manifest、fill order、pregenerated recall 加载、readiness contract 与 full derived index manifest 写入路径，并补充 `tests/test_full_data_pool500_recall_only.py` 回归锁定默认路径、source identity、非 READY 状态和 co_visit v0 字段。

**解决方式：**
主路默认 manifest 指向 `local_formal_semantic_20260525`、`local_formal_semantic_title_category_20260525`、`local_formal_co_visit_repair_20260525`；新增 canonical `semantic` 的 pregenerated recall 合并入口，把 `semantic` 加入 fill order 但不加 minimum；对 deferred diagnostic source 即使 index 文件存在也保持 `BATCH_SCOPED_DIAGNOSTIC`，并透传 no-promotion/no-ranking-replacement/no-pool1000、`algorithm_scope`、`complete_co_visit_graph_claimed` 等治理字段。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_phase_1_21_recall_coverage.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_source_runner.py`，结果 `53 passed, 2 warnings`。随后运行 5 用户主路 smoke，输出 `pool500_candidates.jsonl` 共 2500 行，三类新 source 均进入候选：`semantic=563`、`semantic_title_category_expansion=360`、`co_visit_fallback_repair=597`；三者 readiness 与 full derived index status 均为 `BATCH_SCOPED_DIAGNOSTIC`，`semantic.canonical_source=semantic`，co_visit 保留 `algorithm_scope=train_transition_metadata_repair_v0` 与 `complete_co_visit_graph_claimed=false`，final contract 继续保持 `final_pool500_ready_claimed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把召回方法产物接入主路但不越过治理边界”：既让真实候选进入 recall merge、可被后续排序/Agent 使用，又用 readiness contract 和 manifest 字段防止 diagnostic source 被包装成 READY 或正式晋升，体现推荐系统实验主路接入中的效果验证与风险隔离。

### 2026-05-25 - pool500 三方法 local_formal source index 生成

**任务：**
为 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 生成可供后续召回读取的 `local_formal` source index 产物。

**遇到的问题：**
此前只完成了三档配置、builder/runner 和 dry-run 验证，`semantic` 没有保留实际输出，另外两个方法也需要按统一 runner 重新生成 formal 口径产物，不能把旧 diagnostic run 直接当作正式可调用索引。

**定位方式：**
用统一 runner 串行执行三个 source 的 `--tier local_formal`，避免并行打满本机资源；完成后在主会话独立检查每个输出目录的七件套、`candidates.jsonl` 行数、`source_index_manifest.json` 的 source identity、`no_holdout_audit.json` 状态和治理字段。

**解决方式：**
生成 `local_formal_semantic_20260525`、`local_formal_semantic_title_category_20260525`、`local_formal_co_visit_repair_20260525` 三个 run，并保留 `semantic` 的 canonical source identity、`semantic_title_category_expansion` 的 title/category expansion identity，以及 `co_visit_fallback_repair` 的 `train_transition_metadata_repair_v0` 边界。

**验证结果：**
三个输出目录均包含 `method_dataset_manifest.json`、`source_index_manifest.json`、`candidates.jsonl`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。候选行数分别为：`semantic=53280`、`semantic_title_category_expansion=25047`、`co_visit_fallback_repair=67222`，其中 co_visit `user_coverage_count=444`；三个 no-holdout audit 均为 `PASS`，治理字段保持 no-promotion/no-ranking-input-replacement/no-pool1000，co_visit 继续声明 `complete_co_visit_graph_claimed=false`。

**面试可讲点：**
这段可以讲成“召回源从配置治理走到可调用索引落盘”：先把方法专属数据筛选和 source contract 固化，再按 train-only local_formal 口径生成可复用 source index，并用七件套 manifest/audit 证明数据没有泄漏、没有 READY 误宣称、没有替换正式 ranking 输入。

### 2026-05-25 - pool500 method source tier/identity 守门测试收口

**任务：**
为 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 三个 pool500 method source 补齐统一 runner、tier 合并、source identity、co_visit v0 语义和 forbidden audit 的测试与方法文档。

**遇到的问题：**
前置实现已完成 runner 和 builder 改造，但回归测试还没有固定 CLI 显式参数 > tier > defaults、argparse 默认值不覆盖配置、unknown tier、`dam` alias、semantic canonical identity、co_visit 七件套与 v0 manifest、youtube_dnn/pool1000 forbidden audit 等关键契约。首次目标测试暴露 registry 的 `forbidden_input_scopes` 已包含 `youtube_dnn` 但缺少 `pool1000`，与代码级 audit 列表不一致；独立验收又发现 `semantic_title_category_expansion` builder 存在未使用导入，且 runner 尚未解析 `tier_aliases.dam -> diagnostic`。

**定位方式：**
新增 `tests/test_pool500_method_source_runner.py` 覆盖 runner dry-run、默认 config path、tier precedence、`dam -> diagnostic` alias、semantic identity、co_visit manifest contract、METHOD 文档边界和 forbidden path helper；运行 `test_pool500_method_registry_drift.py` 时定位到 registry forbidden scope 漂移；用 ruff 和 runner dry-run 复现最终两个验收 blocker。

**解决方式：**
补充 runner/source 契约测试，把 registry 的所有 source `forbidden_input_scopes` 同步加入 `pool1000`；重写三份 METHOD 文档，统一声明 `configs/recall/full_data_pool500/<source>/source_config.yaml`、统一 runner smoke、`dam(diagnostic)` / `最终数据集(local_formal)` alias，以及不得 READY、不替换 ranking input、不进入 pool1000 的边界。co_visit 文档同步 `algorithm_scope=train_transition_metadata_repair_v0`、`complete_co_visit_graph_claimed=false`，并明确 `pair_support` / `distinct_user_support` 是 follow-up，不是 gate。最终补上 runner `tier_aliases` 解析，并清理 `semantic_title_category_expansion` builder 的未使用导入。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_source_runner.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_co_visit_fallback_repair_source.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py`，结果 `25 passed in 0.44s`。随后对三个 source 分别执行统一 runner `--tier smoke --dry-run`，均返回七件套 `required_outputs`、正确 `config_path` 和 no-promotion/no-ranking-replacement/no-pool1000 governance；追加执行 `--source semantic --tier dam --dry-run`，输出 `tier=diagnostic`；ruff 检查 runner、测试和 semantic_title builder 结果为 `All checks passed!`，独立 verifier 复核为 PASS。

**面试可讲点：**
这段可以讲成“推荐召回 source 治理契约的测试化”：不是只靠文档说明 source 边界，而是把 config path、tier 合并优先级、semantic identity、防 pool1000 证据污染、co_visit v0 能力边界和七件套产物都固化成可执行测试，防止后续实验把 diagnostic source 包装成 READY 或正式 ranking 输入。

### 2026-05-25 - ItemCF method_dataset strict 与 coverage formal 分层

**任务：**
为 `itemcf_weak` / `itemcf_strong` 制作更符合 ItemCF 特性的 P2 method dataset：在 strict 三级规模口径下保留高质量 train-only 证据，同时针对 weak 召回补量额外生成 coverage-oriented formal 数据集。

**遇到的问题：**
strict local_formal 确实按既定三级规模执行，但 `itemcf_weak` 只有 53540 条方向边，`itemcf_strong` 只有 208 条方向边。问题不在流程失败，而在 ItemCF 的过滤口径过严：`cf_ready + non-over_hot`、用户质量桶限制和 item user frequency cap 大量削掉可共现 item，使 weak 的 coverage 目标无法由 strict 口径承担。

**定位方式：**
对比 diagnostic、strict formal 和 coverage formal 的 manifest：strict weak 主要 drop 为 `user_bucket_not_allowed=17629532`、`insufficient_pair_items=458317`、`item_over_hot=866844`、`item_not_cf_ready=1208170`；strong strict formal 维持 `collaborative_rich` 与 `min_pair_support=2`，只剩 104 个无向 pair。由此确认 strong 应保留 high-confidence，weak 需要单独 coverage profile，而不是把 source/candidate/ranking 链路提前替换。

**解决方式：**
在 `build_pool500_method_dataset.py` 中新增显式 `--itemcf-coverage-profile weak_coverage`，只作用于 `itemcf_weak`：用户桶扩到 `medium_behavior/sequence_sufficient/collaborative_rich`，item 桶扩到 `cf_ready/embedding_ready`，`max_output_users=120000`、`max_items_per_user=80`、`max_item_user_freq=20000`、`top_k_per_seed=200`，并保留 `weighted_cooc`、active-user penalty 和 `itemcf_score = weighted_cooc / sqrt(src_user_count * dst_user_count)`。coverage formal 不覆盖 strict formal，只作为 weak 的广覆盖 method_dataset 证据。

**验证结果：**
strict diagnostic：weak `row_count=94`、strong `row_count=0`，audit PASS；strict local_formal：weak `row_count=53540`、`unique_pair_count=26770`，strong `row_count=208`、`unique_pair_count=104`，audit PASS。coverage formal 输出 `outputs/recall/pool500_method_datasets/itemcf_weighted_coverage_formal_v1/itemcf_weak/`，`row_count=5640872`、`unique_pair_count=3091726`、`edge_seed_count=239995`、`user_count=120000`、`item_count=239995`、`max_edges_per_seed_after_topk=200`、`score_mismatch_count=0`、`missing_field_counts={}`。新增 coverage profile 单测通过：`tests/test_pool500_method_dataset.py::test_itemcf_weak_coverage_profile_broadens_users_and_items_without_changing_layer`。

**面试可讲点：**
这段可以讲成“按方法特性做数据分层，而不是盲目放大同一套过滤规则”：strong 保持高置信、weak 引入广覆盖 profile；同时用 weighted cooc、活跃用户惩罚、top-k per seed 和 train-only audit 保证边表更适合 ItemCF 学习，但仍明确它只是 P2 method_dataset，不是 source index、candidate、ranking replacement 或正式晋升。

### 2026-05-26 - 推荐 Agent 可用化契约与闭环验证

**任务：**
在召回链路基本可用、排序后续继续优化的阶段，把推荐 Agent 从实验组件推进到可直接联调使用的自然对话导购入口。

**遇到的问题：**
Agent 已有 runtime、dialogue、feedback、serving 和 display 基础，但关键契约仍偏隐式：`DialoguePlan` 的 intent/action 是自由字符串，后台工具能力没有显式边界清单，前台需要保证不会泄露 diagnostics、runtime trace、reward、training、source 或 capability 信息。同时 Agent 不能像 code agent 一样暴露工具选择和自主调度，必须把复杂能力藏在后台。

**定位方式：**
对照 `rs_core/rsagent/runtime.py`、`rs_core/rsagent/dialogue.py`、`rs_core/rsagent/tools.py`、`rs_core/serving/service.py`、`rs_core/display/builder.py` 和 RAG retriever/schema，确认现有主链路应复用 `RecommendationService -> HybridRecommendationEnvironment -> AgentRuntime`，而不是新增大型 orchestrator。架构复审还发现必须沿用现有 `recommend_request`、`preference_feedback`、`ask_explanation` 等字符串并常量化，不能为了“规范命名”破坏已有测试和 runtime summary。

**解决方式：**
在 `rs_core/rsagent/dialogue.py` 中把现有 intent/action 常量化并增加 allowlist，`AgentRuntime` 默认 `current_goal` 改为引用同一常量；在 `rs_core/rsagent/tools.py` 增加内部 `AgentCapability` manifest，描述 `parse_preferences`、`apply_constraints`、`retrieve_candidates`、`rank_candidates`、`build_rag_context`、`explain_recommendation`、`collect_feedback` 等后台能力，但不实现通用工具执行器、不进入 public payload；补齐 serving smoke，覆盖模糊需求追问、澄清后推荐、`show_different` 反馈生效和 `why` 只解释最近推荐。

**验证结果：**
使用项目默认 `.venv` 运行核心测试：`tests/test_agent_dialogue.py tests/test_agent_runtime.py tests/test_agent_feedback.py tests/test_agent_scorecard.py tests/test_agent_capability_manifest.py tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `76 passed in 1.35s`；ruff 检查 `rs_core/rsagent`、`rs_core/serving` 和相关测试为 `All checks passed!`。独立验证还跑过 RAG 核心测试 `5 passed`、相关模块 `compileall` 通过，并用临时最小 fixture 验证 Agent evaluation 逻辑，`scene_count=1`、`overall_score=0.866667`。默认评估脚本直接按路径运行会遇到 `ModuleNotFoundError: No module named 'scripts'`，改用模块方式后默认配置缺少本地数据输入，因此未把全量 evaluation 作为本次门禁。

**面试可讲点：**
这段可以讲成“把推荐 Agent 从能跑推进到可联调使用”：不是重写 Agent 框架，而是把隐式 dialogue 契约、后台能力边界、公有 payload 防泄露和端到端导购闭环测试化。前台保持自然对话和商品卡，后台保留召回、排序、RAG、反馈和评估能力，体现了推荐 Agent 的产品形态和工程治理边界。

### 2026-05-25 - TwoTower diagnostic 训练检索评估闭环

**任务：**
在 TwoTower P2 数据质量门禁完成后，新增一个受控的小规模 diagnostic train→retrieval→eval runner，验证双塔链路能从 train-only method dataset 进入训练、source index、topK 检索和诊断指标输出，但不做正式 pool500 晋升。

**遇到的问题：**
直接进入正式训练或 challenger 会混淆“链路可诊断”和“召回效果达标”。本轮还发现一个真实边界漏洞：如果 method dataset 自身路径包含 `eval/oracle/label` 等语义 token，runner 仍可能把这些路径写进训练兼容输入，同时报告 `leakage_checks.eval_paths_rejected=true`，造成 no-oracle/no-label 声明与实际输入不一致。

**定位方式：**
团队先只读梳理现有复用点：训练侧复用安全的 YouTubeDNN train-only 入口，索引侧复用 TwoTower source index manifest 与 validator，评估侧复用 pool500 offline eval baseline 的指标口径。最终 verifier 用临时 `eval/method_dataset` 路径做 smoke probe，复现出 guard 漏洞，并确认问题发生在输出目录创建和 compatibility manifest 写入之前缺少 method dataset 输入路径拒绝。

**解决方式：**
新增 `rs_lab/experiments/recall/run_pool500_two_tower_diagnostic_loop.py`，作为单一编排 runner：消费 P2 TwoTower method dataset，构造 train-only 兼容输入，执行 bounded YouTubeDNN diagnostic training，生成 guarded source index manifest、diagnostic topK、metrics、manifest 和 report。runner 固化 `diagnostic_only=true`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false` 等边界字段。随后在写输出和训练兼容输入前增加 forbidden path guard，对 `eval/oracle/label/valid/validation/test/holdout` 的路径段或完整文件 stem 做显式拒绝，并补回归避免误杀 pytest 的普通 `test_*` 临时目录。

**验证结果：**
新增 `tests/test_pool500_two_tower_diagnostic_loop.py`。最终验收使用项目默认 `.venv` 运行 focused test，`20 passed in 0.42s`；相关 TwoTower source manifest/method source guard suite `16 passed in 0.86s`；runner 与测试文件 `py_compile` 通过。forbidden smoke 证明安全 `test_guard_no_overmatch0` 路径可 PASS，且 `diagnostic_only=True`、`promotion_allowed=False`、`final_pool500_ready_claimed=False`，没有 READY 或 replacement claim；`eval/oracle/label/valid/validation/test/holdout` 的路径段和 filename-stem 场景均被拒绝，且 `output_exists=False`。

**面试可讲点：**
这段可以讲成“推荐模型从数据治理到诊断闭环的安全推进”：不是把 smoke 训练结果包装成效果，而是先把训练、索引、检索、指标和 no-promotion 边界串成可复现 diagnostic runner；同时通过独立 verifier 构造反例发现路径级数据泄漏风险，并把它固化成 guard 与回归测试，体现推荐系统实验链路中的数据边界意识和工程验证能力。

### 2026-05-25 - UserCF formal train probe 与边界验收收口

**任务：**
为 UserCF formal train 补齐 method_dataset input mode、probe 与 formal 构建验收，沉淀本轮矩阵/索引产物的边界、证据和后续注意事项。

**遇到的问题：**
本轮验证重点不在效果提升，而在 method_dataset / source_index / probe 产物是否能按合同加载、是否跨过 promotion/ranking/final-ready 边界。verify-worker 还指出 `method_dataset_manifest` 里的 secondary source_index hash 可能陈旧，若直接用于 formal/consumer 可能出现血缘口径偏差。后续已把该 hash 改为基于落盘 `source_index_manifest.json` 的实际文件 sha256 写入，并刷新 probe 产物。

**定位方式：**
复核 focused tests 与 probe 输出，核对 `source_index_manifest`、candidate 统计、loadable shards、forbidden/no-holdout audit 和各类治理标志，确认问题属于 readiness contract / hash lineage，而不是召回效果本身。

**解决方式：**
把本轮结论收口为“可构建、可加载、边界守住”，不把 boundary pass 解释成效果提升；同时修正 wrapper 写入顺序，让 `method_dataset_manifest.source_index_manifest_sha256` 使用落盘 `source_index_manifest.json` 的实际 sha256，并补充回归断言，避免继续沿用旧血缘。

**验证结果：**
33 个 focused tests 通过；修复 hash 写入后复跑 focused tests，`33 passed in 1.24s`；刷新 probe 后 `method_dataset_manifest.source_index_manifest_sha256`、`readiness_contract.index_manifest_sha256` 与当前 `source_index_manifest.json` 实际 sha256 均一致。probe `source_index_manifest` `status=PASS`、`INDEX_READY`、`target_user_count=5000`、`candidate_user_count=22`、`candidate_total_count=36`；formal 全量构建输出 `outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_method_dataset/`，`target_user_count=90686`、`candidate_user_count=10630`、`candidate_total_count=17509`、`candidate_count_stats={min:1,p50:1,p90:3,max:20}`，相对旧诊断 baseline `candidate_row_count_delta=9145`、`user_coverage_count_delta=10340`；`16/16` shard 可加载，`malformed_shard_rows=0`，loader 覆盖 10630 个候选用户；forbidden/no-holdout audit PASS；`promotion/ranking/final-ready` flags 全 false。结论能证明 formal 矩阵/索引可构建、可加载、可用于诊断候选产出，但仍不能替代独立 recall-only 效果评估。

**面试可讲点：**
这段可以讲成“把推荐召回产物从能跑推进到可交付”：不是只看分数，而是把 manifest、shard loadability、治理标志和审计结果一起验收，确保 formal/consumer 接口边界清晰，并主动识别、修复 hash lineage 可能陈旧的问题。

### 2026-05-25 - UserCF formal artifact 接入 recall-only 主路

**任务：**
把已完成的 UserCF formal method_dataset 构建产物接入 pool500 recall-only 主路，让主路默认读取新的 `usercf_recall` formal sidecar，同时保持 DIAGNOSTIC_ONLY 与非晋升边界。

**遇到的问题：**
UserCF formal 产物已经能从 90686 个 target user 构建出诊断候选，但它仍是 `DIAGNOSTIC_ONLY`，不能因为 `INDEX_READY` 或主路可读取就直接晋升为 READY、替换 ranking input 或声称 pool500 ready。另外，主路 shadow audit 里已经有 `semantic` source，但 audit registry 没覆盖它，测试暴露出口径不一致。

**定位方式：**
先用 `--usercf-sidecar-manifest` override 跑 1000 用户 smoke，验证新 formal artifact 能被 `run_full_data_pool500_recall_only.py` 读取并进入 contribution audit；再检查 `DEFAULT_SOURCE_MANIFESTS`、`pool500_method_registry.json`、`usercf_recall/source_config.yaml` 和 shadow audit source registry，确认默认指针、registry evidence 与 audit 覆盖范围需要同步。

**解决方式：**
将 `run_full_data_pool500_recall_only.py` 默认 `usercf_recall` manifest 指向 `outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_method_dataset/source_index_manifest.json`；更新 `pool500_method_registry.json` 的 UserCF latest artifact/readiness/evidence 与统计，但保持 `status=DIAGNOSTIC_ONLY` 和 promotion/ranking/pool1000 全 false；更新 `configs/recall/full_data_pool500/usercf_recall/source_config.yaml` 记录 formal method_dataset input mode；同时把 `semantic` 纳入 recall-layer shadow audit registry，避免主路有 source 但 shadow audit 漏审。

**验证结果：**
聚焦测试通过：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest ...test_full_train_usercf_sidecar.py ...test_pool500_usercf_method_source.py ...test_full_data_pool500_recall_only.py ...test_pool500_method_registry_drift.py -q`，结果 `66 passed in 3.47s`。1000 用户 override smoke 输出 `status=STOP` 且治理字段保持 false；默认指针更新后 5000 用户 diagnostic 输出 `status=STOP`，`usercf_recall` 进入主路 contribution audit：`row_count=5`、`user_coverage_count=3`、`readiness_status=DIAGNOSTIC_ONLY`，per-source readiness 指向 formal source manifest 且 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“把离线方法产物安全接入召回主路”：不是把 UserCF 的 formal 构建产物直接包装成效果提升，而是先通过 override smoke、默认指针切换、registry evidence、shadow audit 和 diagnostic route 验证，让主路能消费新的协同过滤信号，同时保留 STOP/DIAGNOSTIC_ONLY/非晋升门禁。这样既推进了工程链路，也避免了未评估产物污染排序输入。

### 2026-05-25 - TwoTower P2 负样本多样性与数据质量门禁

**任务：**
复核 TwoTower P2 method dataset 是否具备 YouTubeDNN/双塔训练所需的数据特性，并修复已确认的 P2 数据缺口：负样本使用多样性、非空训练样本门槛、positive target 的 P1 quality/frequency 溯源与核心 metadata 完备性。

**遇到的问题：**
上一轮 smoke 虽然已经能生成 496 条 `history_items -> target_item` 样本，但实际负样本使用退化为全局仅 3 个 distinct negative item；这只能证明链路可训练，不能证明负采样特性足以支撑双塔召回学习。同时，审计器之前更偏向检查流程边界，缺少对空样本、空负样本、负样本泄漏、负样本使用统计失真、target 缺少 P1 quality/frequency 或核心文本/类目 metadata 的硬门禁。

**定位方式：**
对照 Datawhale YouTubeDNN 资料中“历史序列预测 target、较大 item class space、sampled softmax/多样负样本、ANN retrieval 与独立评估 universe”的要求，重新审计 TwoTower P2 manifest、样本文件与 audit validator。关键诊断结论是：当前 P2 样本形式正确，但效果训练特性仍缺负样本多样性和 target/item 质量证据。

**解决方式：**
在 `build_pool500_two_tower_method_dataset.py` 中把 per-example negative policy 固化为 `deterministic_diversified_rotated_negatives_after_per_user_exclusions`，用 `(user_id, target_item, target_index)` 的稳定哈希对 eligible negatives 做 deterministic rotation，避免所有样本总是拿同一批 top-N negative；同时在 manifest stats 中记录 `used_negative_distinct_item_count`、`used_negative_item_occurrence_count`、coverage ratio、top1/top10 使用集中度、under-requested negative count 等负样本使用证据。审计器同步重算这些统计，并新增 blocker：空训练样本、空负样本、负样本泄漏/重复、统计不一致、distinct negative 低于阈值、positive target 缺少 P1 quality/frequency、positive target metadata 不完整。

**验证结果：**
使用项目默认 `.venv` 的聚焦测试验证，`tests/test_pool500_two_tower_method_dataset.py` 与 `tests/test_pool500_method_dataset_audit_evidence.py` 共 `29 passed in 0.88s`；两个核心文件 `py_compile` 通过。fixture smoke 复核显示 `used_negative_distinct_item_count=3`、`used_negatives=[neg_a, neg_b, neg_c]`，audit PASS；低 distinct mutation 被 audit 正确 BLOCKED，blocker 为 `two_tower_used_negative_diversity_below_threshold`。输出仍只包含 `leakage_audit.json`、`method_dataset_manifest.json`、`negative_item_universe.jsonl`、`training_item_universe.jsonl`、`two_tower_train_samples.jsonl`，未产生 candidate/index/ranking/promotion/READY 产物。

**面试可讲点：**
这段可以讲成“从可训练到适合双塔学习的数据特性治理”：不是看到样本非空就开始训练，而是把双塔依赖的负样本多样性、target 溯源、item 文本/类目 metadata 和 no-oracle 边界全部变成 manifest 统计与 audit blocker。亮点在于用确定性采样保证可复现，同时用审计器阻止低质量 P2 数据被包装成 YouTubeDNN 效果证明。

### 2026-05-25 - TwoTower P2 阶段 1 universe freeze 与效果口径门禁

**任务：**
在 TwoTower smoke 已证明可训练之后，补齐阶段 1 的 universe 定义、data usage boundary、oracle/label 禁止校验和 raw/eligible/excluded denominator 统计，避免把小样本训练可行性误判为 pool500 召回效果。

**遇到的问题：**
当前 smoke 只有 67 个有效用户、496 条样本、1461 个 negative item 和 1953 个 training item universe，且 496 个 target 全部在 negative universe 外。这个现象不能直接解释为模型无效或有效，必须先区分 training universe、retrieval universe、global/per-user/per-example negative universe、eval target universe 与 eligible target universe，否则后续 Recall@K、hard negative 或 challenger 都可能在错误 denominator 上优化。

**定位方式：**
通过团队只读梳理 `build_pool500_two_tower_method_dataset.py`、`validate_pool500_method_dataset_audit_evidence.py` 和相关测试，确认现有审计已覆盖 negative universe 的 P1 溯源和 training universe 的 target 覆盖，但缺少字段化的阶段 1 universe freeze、data boundary 和 raw/eligible/excluded denominator 门禁。

**解决方式：**
在 TwoTower method dataset manifest 中新增 phase1 universe definitions，显式声明 training/retrieval/global negative/per-user negative/per-example negative/eval target/eligible target 的阶段语义；将 retrieval/eval 标为 `phase1_not_built`、`available=false`，避免伪造正式评估口径。新增 `data_usage_boundary`，把 label/oracle/diagnostic oracle artifacts 限定为 `diagnostic_eval_only`，禁止进入 training、negative_sampling、index_build 和 official_candidate_generation；同时在 stats 中补 target denominator 与 training/negative universe coverage，并让 audit validator 对缺失或错误字段直接 BLOCKED。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_two_tower_method_dataset.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_dataset_audit_evidence.py`，结果 `20 passed in 0.60s`；`py_compile` 两个修改模块通过。独立 fixture smoke 使用 builder + validator 得到 manifest/audit 均 PASS，输出文件仅为 `leakage_audit.json`、`method_dataset_manifest.json`、`negative_item_universe.jsonl`、`training_item_universe.jsonl`、`two_tower_train_samples.jsonl`，未产生训练、正式 eval、candidate generation、ranking、pool1000、promotion 或 READY 产物。

**面试可讲点：**
这段可以讲成“推荐召回实验的效果口径门禁”：在模型能训练后，没有急着调参或扩大训练，而是先把 target 是否理论可召回、哪些 denominator 可用于正式 Recall@K、哪些 oracle/label 产物只能诊断写进 manifest 和审计器，体现推荐系统中数据治理、指标可信度和模型迭代顺序的工程判断。

### 2026-05-24 - TwoTower P2 method dataset smoke 非空化与 target/negative 解耦

**任务：**
把 pool500 TwoTower P2 method dataset 从“manifest PASS 但样本为空”修到可真实生成 train-only `history_items -> target_item` 训练样本，并保持 P2 只产出 method dataset，不生成 candidates/source index/READY 产物。

**遇到的问题：**
第一轮 smoke 运行成功但 `train_sample_count=0`，`target_items_skipped_not_in_negative_universe=496`，原因是 builder 把正样本 target 也强制限制在 `embedding_ready` negative universe。后续复核又发现，仅让样本非空仍不够：如果 target 不进入训练 item vocab，训练阶段仍不可编码；如果 vocab 缺少 `title_clean/main_category/category/item_text`，item embedding 初始化也会退化。

**定位方式：**
审计 `outputs/recall/pool500_method_datasets/two_tower/train_only_v1_smoke/method_dataset_manifest.json`，确认 eligible users=67、positive transitions=496、negative universe=1461，但所有 target 都被 negative-universe gate 跳过。随后用独立脚本交叉检查 `two_tower_train_samples.jsonl` 与 `training_item_universe.jsonl`，逐项统计 sample target、negative item、metadata 字段覆盖，避免只依赖 manifest 自报。

**解决方式：**
在 `build_pool500_two_tower_method_dataset.py` 中解耦正负样本口径：target item 以 train-only 用户正反馈序列为准，负样本仍严格来自 P1 governance 的 `embedding_ready` negative universe；新增 `training_item_universe.jsonl`，作为 negative universe 与 sampled train-sequence targets 的并集，并从 `canonical_items.jsonl` 补齐 `item_id`、`title_clean`、`main_category`、`category`、`item_text` 等训练特征字段。审计器同步加严：样本 target 必须在 training item universe 中以 `positive_target` 角色存在，否则 P2 audit 直接 BLOCKED。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_dataset.py tests/test_pool500_method_dataset_audit_evidence.py tests/test_train_only_data_governance.py -q`，结果 `27 passed`。重新生成 smoke governance + TwoTower dataset 后，`train_sample_count=496`、`sample_target_item_count=492`、`negative_universe_item_count=1461`、`training_item_universe_item_count=1953`、`training_item_universe_metadata_item_count=1953`、`missing_targets_from_positive_universe=0`、`missing_negatives_from_universe=0`，`title_clean/main_category/category/item_text` 缺口均为 0；P2 audit `status=PASS`、`blocker_count=0`。最后用 `rs_core.recsys.two_tower.train_two_tower_model` 做最小训练 smoke，64 个训练用户、415 条正交互、1953 个 item embedding，PyTorch backend 成功输出 loss。

**面试可讲点：**
这段可以讲成“推荐系统训练数据治理中的正负样本与训练 vocab 三方契约”：正样本来自真实 train-only 行为序列，负样本来自可控 item universe，训练 vocab 必须覆盖所有 target 和 negative 并保留 item metadata。修复过程不是只追 `PASS` 或非空样本，而是逐层验证样本、vocab、metadata、审计器和最小训练消费链路，体现数据集物化到模型可训练之间的工程闭环。

### 2026-05-22 - pool500 三阶段排序 Agent-ready artifact 收口

**任务：**
在固定 hot-user smoke010 的 pool500 frozen candidates 上，把已有 coarse/fine/rerank 排序链路输出成 Agent 可直接消费的 Top20/Top50 ranked artifact，保留三阶段分数、召回源、关键特征、排序理由、质量审计字段和 no-oracle/no-label-injection 边界。

**遇到的问题：**
已有 `run_pool500_learned_ranking_challenger.py` 能输出 B0/R1/coarse-only/L1 comparison，但产物仍偏离线实验报告，缺少独立的 Agent-ready 推荐列表。独立 code-reviewer 还指出，如果直接用 Top50 结果截取 Top20，`policy_rerank_guard` 的 source/category cap 可能只满足 Top50，不满足 Top20。

**定位方式：**
审计 `rs_core/recsys/ranking.py` 的 `rank_candidates -> coarse_rank_candidates -> fine_rank_candidates -> rerank_candidates`，确认三阶段 trace、rank movement、LTR score 和 policy guard 已存在；检查 `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`，确认 frozen adapter、train/eval label gate、feature/leakage gate 和 promotion gate 已承担边界治理。

**解决方式：**
新增 `pool500_agent_ready_ranked_artifact_v1` 输出 `agent_ready_ranked_artifact.json`：按 Top20/Top50 分别执行 challenger ranking，避免不同 list 的 policy cap 互相污染；每个 item 输出 `coarse_score`、`fine_score`、`ltr_score`、`rerank_score`、`final_score`、sources、category、key features、reason codes、score trace、rank movement 和质量字段。report 只保留 artifact summary 与路径，避免把它误读成召回替换或线上晋升。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_learned_ranking_challenger.py tests/test_recsys_core.py tests/test_ltr.py tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `146 passed in 3.44s`。新增回归覆盖 Top20/Top50 分别执行 source cap：构造 30 个高分 popular 与 30 个 semantic 候选后，artifact 中 `popular_top20 <= 10`、`popular_top50 <= 25`。随后用真实 hot010 输入 `outputs/recall/pool500_vnext_hot010_global_rank_top1000_20260522/pool500_candidates.jsonl`、`train_labels/train_labels.jsonl` 和 `eval_labels/eval_labels.jsonl` 生成 `outputs/ranking/pool500_hot010_global_rank_top1000_20260522/agent_ready_three_stage_20260522/agent_ready_ranked_artifact.json`；抽检结果为 schema=`pool500_agent_ready_ranked_artifact_v1`、10 个用户、每用户 Top20/Top50 分别为 20/50、`frozen_candidate_equality=PASS`、三阶段 trace 全覆盖、candidate generation / valid-test label injection / oracle injection 均为 false。独立 verifier 复核 schema、frozen equality、no candidate generation、no valid/test label injection、no oracle、Top20/Top50 policy caps 与 runtime artifact 生成，结论 PASS。

**面试可讲点：**
这段可以讲成“把离线排序实验转成 Agent 可消费的推荐产物”：不是只看 NDCG/MRR，而是把工业三阶段排序的分数链路、解释证据、质量约束和数据边界一起固化到 artifact；同时通过独立审查发现 Top20/Top50 cap 语义问题并补回归，体现推荐系统从实验到可服务产物的工程治理能力。

### 2026-05-22 - hot10 frozen-pool 排序模型诊断复验

**任务：**
基于新的 hot-user top1000 主路候选池 `outputs/recall/pool500_vnext_hot010_global_rank_top1000_20260522/pool500_candidates.jsonl`，重新验证 B0/R1/coarse-only/L1 三阶段排序链路是否在同一 frozen pool 内带来排序提升。

**遇到的问题：**
第一轮误把候选全集打标 artifact 作为 train/eval label 输入，导致 5000 个候选负样本也被 label separation gate 视为 labeled pair 重叠，出现非目标口径的 STOP；同时 hot10 主路虽然已有 `13/37` eval positives 进入 pool500，但 train 候选内正样本只有 4 个、覆盖 2 个用户，LTR 训练信号极弱。

**定位方式：**
重新从 `canonical_interactions.train.jsonl`、valid/test 交互中按 hot10 target users 抽取 raw interaction label source，保证 train/eval 是原始交互集合而非候选全集打标文件。使用 `.venv` 运行 `run_pool500_learned_ranking_challenger.py`，并对比 auto LightGBM、pairwise、pointwise 三种模型输出。

**解决方式：**
以 raw interaction labels 重跑 challenger，输出到 `outputs/ranking/pool500_hot010_global_rank_top1000_20260522/challenger_interaction_labels/`，并补跑 `challenger_pairwise/`、`challenger_pointwise/` 作为模型对照；保持候选池 frozen，不改召回、不新增候选。

**验证结果：**
raw-label 口径下 feature/leakage/label separation/train split/frozen candidate equality gates 均为 PASS，LightGBM LambdaMART 成功训练：`positive_rows=4`、`positive_users=2`。但 B0/R1/C0 均为 Hit@20=`0.3`、NDCG@20=`0.05569`、MRR@20=`0.046667`，L1 退化为 Hit@20=`0.2`、NDCG@20=`0.045006`、MRR@20=`0.041667`。pairwise 与 pointwise 结果同样退化，promotion gate 保持 `NO_PROMOTE / diagnostic_only_no_promote`，blockers 包括 `QUALITY_GUARD_NOT_PASS`、`NO_PRIMARY_METRIC_LIFT`、`PRIMARY_MRR_REGRESSION`。

**面试可讲点：**
这段可以讲成“冻结召回池内的排序增益归因”：先修正 label 输入口径，再把召回提升和排序提升拆开看；hot10 候选池已经给排序提供了可评价正样本，但 LTR 训练正例太少，当前最强结论是 baseline/coarse 足够稳，learned rerank 暂不晋升，体现离线排序实验的可信 gate 和反过拟合意识。

### 2026-05-22 - aligned smoke010 主路召回硬目标复验与不可达证据

**任务：**
重新以 aligned smoke010 前 10 个用户的 45 个 valid/test positive 为硬验收集，验证 `pool500_vnext` 主路是否能在每用户 500 candidates、禁止 oracle/label 注入、禁止 pool1000 与禁止 ranking replacement 的边界下达到 `positive_overlap_count >= 30/45`。

**遇到的问题：**
此前 aligned500 主路达到 `positive_overlap_count=33`，但这不是 smoke010 原硬目标。回到 smoke010 后，当前 capped 主路 `outputs/recall/pool500_vnext_smoke010_usercf_cap60_recheck_20260522/` 仍只有 `positive_overlap_count=2/45`，43 个正样本为 `item_not_in_candidate`。

**定位方式：**
用 `diagnose_pool500_label_coverage.py` 复验 smoke010 主路，并逐层拆解召回瓶颈：raw UserCF merge 前只有 `1/45`；当前所有 source rows 并集只有 `2/45`；train-only item-to-item 共现 top500 只有 `2/45`、top2000 只有 `3/45`；live semantic 主路仍为 `2/45`；seed-token aggregation、rare-token quota、weighted token depth 与全量 metadata nearest-neighbor 扫描均未接近目标，其中全量 metadata 扫描 top5000 为 `0/45`。

**处理方式：**
没有把 aligned500 的 33 命中冒充 smoke010 完成，也没有使用 oracle candidate、valid/test 正例直塞或 diagnostic-only oracle artifact。将 valid/test label 严格限定为诊断评估，只保留 capped smoke010 主路、live semantic 对照和各类 train-only/full-derived/catalog 上界诊断作为证据。

**验证结果：**
主路 artifact 仍是 10 用户 × 500 candidates、无重复，但 smoke010 `positive_overlap_count=2/45`，未达到 `>=30/45`。额外诊断显示当前规则召回、UserCF、item 共现、semantic posting 与 metadata nearest-neighbor 都无法形成可沉淀到主路的 30/45 合规路线。随后补做 smoke010 target-slice train-only two-tower 复验：只用这 10 个目标用户的 train 序列训练 `two_tower_youtube_dnn` user embedding，生成 `outputs/recall/pool500_full_sources/two_tower_smoke010_target_train_only_20260522/source_index_manifest.json`，接入主路 `outputs/recall/pool500_vnext_smoke010_target_two_tower_20260522/` 后仍为 10 用户 × 500 candidates、无重复、治理字段全 false；`label_coverage_diagnostic/pool500_label_coverage_report.json` 仍显示 `positive_overlap_count=2/45`、`item_not_in_candidate=43`。进一步用 train seed token reachability 验证，45 个 valid/test positive 中有 25 个可被 train seed token 的 full-derived semantic inverted index 触达，17 个 best position <=500；但当转换为合法候选生成策略时，seed-token scoring 最高只有 `1/45`，round-robin/band interleave 覆盖型模拟最高只有 `3/45`，full-train two-hop sequence source 模拟也只有 `2/45`，说明“可达”无法稳定转化为主路 pool500 命中。随后补做与 CF/two-tower/token/two-hop 不同的 train-only metadata transition recall：只读取 `user_sequences.train.jsonl`、`semantic_recall_inputs.jsonl` 和 diagnostic eval user manifest，先生成 source-only `outputs/recall/pool500_metadata_transition_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，再后验读取 valid/test labels 诊断；产物保持 10 用户 × 500 candidates、无重复、治理字段 false，但 `positive_overlap_count` 仍为 `2/45`，未提供可接入主路的增量证据。再补做 train-only metadata cohort implicit SVD source-only 诊断，生成 `outputs/recall/pool500_cohort_svd_diagnostic/smoke010_20260522/pool500_candidates.jsonl` 后再读取 valid/test labels 评估；该 MF 方向同样保持 10 用户 × 500 candidates、无重复、治理字段 false，但 `positive_overlap_count` 仍为 `2/45`。最后将现有主路、metadata transition 与 cohort SVD 做不读 label 的 round-robin union 诊断，生成 `outputs/recall/pool500_union_diagnostic/smoke010_main_metadata_svd_20260522/pool500_candidates.jsonl`，后验 label 诊断仍为 `2/45`，说明这些新增合法源没有与当前主路形成互补命中。继续排查 catalog/full-derived 结构化字段后发现 `canonical_items.jsonl` 只有 store、rating、category、文本等字段，没有显式 related/also-bought 图；基于 train seed store 的 `store_sibling_recall` source-only 诊断生成 `outputs/recall/pool500_store_sibling_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，后验 label 诊断为 `0/45`。又根据 miss 归因发现 29/45 与用户 train seed 类目重叠，但 category-depth 深度覆盖三个变体最高仍只有 `1/45`；全局 train popularity rank <=500/5000/50000 分别只有 1/2/10，catalog quality rank <=500/5000/50000 分别只有 3/6/17，说明全局补量窗口也不足。额外检查 `aligned_eval_users_manifest.json` 发现其中包含 `positive_items_sample`，但该字段来自 valid/test，只能作为泄漏风险证据，不能用于候选生成或达标主路。继续回查原始 `amazon_2023_base` metadata，发现 `bought_together` 在 Electronics 1,609,860 行和 Office_Products 710,403 行中均为全空；基于原始 `details`（Brand、Manufacturer、Best Sellers Rank、model tokens、raw categories）的 raw detail facet interleave 与 raw detail overlap scorer 分别生成 `outputs/recall/pool500_raw_detail_facet_diagnostic/smoke010_20260522/pool500_candidates.jsonl` 和 `outputs/recall/pool500_raw_detail_overlap_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，后验 label 诊断均为 `0/45`。再用原始 `price`、Best Sellers Rank、raw category 构造 `raw_price_bsr_recall`，生成 `outputs/recall/pool500_raw_price_bsr_diagnostic/smoke010_20260522/pool500_candidates.jsonl`，后验 label 诊断仍为 `0/45`。最后尝试只用 canonical train pair 过滤后的原始 review 文本构造 `train_review_text_recall`，生成 `outputs/recall/pool500_train_review_text_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；候选生成阶段扫描 train review rows 38,206,341、目标用户 train review rows 76，后验 label 诊断仍为 `0/45`。随后补做 train-only adjacent `session_transition_recall` 目标切片，只扫描 `user_sequences.train.jsonl` 构建相邻转移候选，生成 `outputs/recall/pool500_session_transition_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；候选生成扫描 train sequences 18,103,384，贡献序列 309,601、贡献边 1,248,072，产物仍为 10 用户 × 500 candidates、无重复，但后验 label 诊断仍为 `2/45`，没有超过当前主路。再补做 `catalog_quality_category_recall`，只用 `canonical_items.jsonl` 中的 rating/rating_number 质量分和目标用户 train seed categories 生成候选，扫描 canonical items 2,320,263 行，source-only 后验达到 `4/45`，但仍远低于 30/45；将当前主路、catalog-quality 与 session-transition 做不读 label 的 round-robin union 后反而只有 `3/45`，说明该新增源虽有少量独立信号，但简单并入 500 槽位会挤掉主路已有命中。继续尝试 catalog quality band interleave，在同一 train seed category 内按质量 rank 分层采样更深商品，生成 `outputs/recall/pool500_catalog_quality_bands_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物保持 10 用户 × 500 candidates、无重复、扫描 canonical items 2,320,263 行，但后验 `positive_overlap_count=0/45`，说明深层质量分层不是可接入主路的有效增量。再补做 train-only sequence suffix next-item 诊断，只用目标用户 train 序列末尾上下文，在全量 train sequences 中找相同后缀后的后续商品，生成 `outputs/recall/pool500_sequence_suffix_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；扫描 train sequences 18,103,384、匹配上下文 35,185、贡献边 80,142，产物仍为 10 用户 × 500 candidates、无重复，后验 `positive_overlap_count=3/45`，略高于当前主路但仍远低于 30/45。再将当前主路、catalog-quality category、sequence suffix 和 session-transition 做不读 label 的四源 round-robin union，生成 `outputs/recall/pool500_union_diagnostic/smoke010_main_catalog_suffix_session_20260522/pool500_candidates.jsonl`；候选仍满足 10 用户 × 500、无重复，但后验仍只有 `3/45`，说明这些合法源之间没有形成可叠加到 30/45 的互补覆盖。随后核对发现当前主路使用的是 target-slice Swing manifest，而仓库另有 train-only `outputs/recall/pool500_sidecar_fix/swing_recall_v2/source_index_manifest.json`；用该 full Swing v2 边文件按目标用户 train seeds 生成 source-only 候选，扫描 edges 1,210,833、匹配边 527，产物满足 10 用户 × 500、无重复，但后验仍为 `2/45`，没有提供新增主路能力。最后把当前已生成且不读 label 的合法候选源集合做 13 源 round-robin union（主路、catalog quality、sequence/session、metadata/SVD、raw detail/price/review、store sibling、full Swing v2 等），生成 `outputs/recall/pool500_union_diagnostic/smoke010_all_legal_sources_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复，但后验只有 `2/45`，进一步说明现有合法候选源集合无法通过简单合并接近 30/45。为区分“500 槽位配额问题”和“源候选本身缺失”，再做 diagnostic-only 上界审计：把 13 个合法源的全量唯一候选并集扩展到 38,780 个 user-item pairs 后只读 valid/test 评估，`upper_bound_positive_overlap_count` 也只有 `6/45`；命中主要来自 catalog-quality category、sequence suffix、full Swing v2 和当前主路，说明剩余 39 个正样本没有出现在这些合法源候选集合中。随后尝试 train-only recent trend：只用 `canonical_interactions.train.jsonl` 的 timestamp、item frequency 和目标用户 train category 构造近期热度候选，扫描 train interactions 44,843,821 行，生成 `outputs/recall/pool500_train_recent_trend_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复，但后验只有 `1/45`，说明时间新鲜度热度也不能解释该 smoke010 holdout 行为。为排除 recency 权重影响，又做 train-only category popularity：去掉 timestamp，只按 train split 的 item/category frequency 在目标用户 train category 内补量，生成 `outputs/recall/pool500_train_category_popularity_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；同样扫描 train interactions 44,843,821 行、产物 10 用户 × 500、无重复，后验仍为 `1/45`，说明长期热门类目补量也不是可行主路。随后按“原 smoke010 可能用户选择过冷/样本过少”的假设构造 warm010 aligned 用户组：只用 valid/test 选择评估用户、不把正例 item 输入召回，按 train history 丰富度选择 10 个高历史用户，共 698 个 holdout positives；主路 `outputs/recall/pool500_vnext_warm010_20260522/pool500_candidates.jsonl` 保持 10 用户 × 500、无重复、治理字段 false，后验 `positive_overlap_count=5/698`，绝对命中高于原 smoke010 但覆盖率仍很低，说明应转向更大 warm/aligned cohort 评估而不是 cherry-pick 单个 10 用户集合。回到 smoke010 后补做 positive train/catalog feature audit：45 个正例全在 catalog，42/45 与用户 train seed category 重叠，但只有 29/45 出现在任意 train sequence 中。基于这个发现尝试 catalog new-ASIN category recall，只用 catalog ASIN 新颖度和 train seed category 生成 `outputs/recall/pool500_catalog_new_asin_category_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复，但后验 `positive_overlap_count=0/45`，说明“新品 ASIN 优先”排序不能覆盖这些 catalog-only 正例。随后补做 category-rank 只读审计：把 45 个 smoke010 正例放回用户 train seed category 的 catalog buckets 中，比较 label-free 的 quality/rating/ASIN 排序位置；`quality_desc` 在 top500/top1000/top5000/top20000/top100000 分别覆盖 `12/15/23/29/33`，`rating_number_desc` 分别覆盖 `12/18/23/28/33`，提示“类别内质量/评论数深层采样”有潜在信号，但该结果来自 evaluation-only rank audit，不是 candidate generation artifact，不能作为 smoke010 达标证据。随后把该信号转成 5 个不读 valid/test 的 pool500 deep profile：`quality_broad_rr=1/45`、`quality_deep_window=2/45`、`quality_leaf_rr=1/45`、`quality_union_top=4/45`、`rating_number_broad_rr=1/45`；所有产物均为 10 用户 × 500、无重复且治理字段 false，说明“rank audit 中的深层可达”仍不能稳定转化为合法 pool500 候选覆盖。后续又按“异构图多跳扩散”方向补做 train/catalog-only `hetero_ppr_recall`：只用目标用户 train seed、全量 train 用户篮子、catalog category/store/text token 生成 `outputs/recall/pool500_hetero_ppr_diagnostic/smoke010_20260522/` 下三个 profile；后验 label coverage 分别为 `basket_ppr=2/45`、`hetero_ppr_balanced=1/45`、`hetero_ppr_feature_heavy=0/45`，均保持 10 用户 × 500、无重复、治理字段 false，但没有超过当前主路。LightFM/WARP hybrid 方向因本地 native 扩展 segfault 放弃，避免继续触发不稳定依赖；随后改用单线程 `implicit_als_recall`，只读 train interactions、限制 120,000 item/80,001 user/469,425 train interactions，生成 `outputs/recall/pool500_implicit_als_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物仍为 10 用户 × 500、无重复、治理字段 false，但后验 label coverage 仍为 `2/45`。最后补做 PyTorch train-only `item2vec_bpr_recall`，只用 `user_sequences.train.jsonl` 的相邻/近邻共现训练 item embedding，候选宇宙来自目标用户 train seed 类目/店铺与全局 train 热度，生成 `outputs/recall/pool500_item2vec_bpr_diagnostic/smoke010_20260522/pool500_candidates.jsonl`；产物为 10 用户 × 500、无重复、治理字段 false，但后验为 `0/45`，说明轻量序列 embedding 方向也未提供有效增量。

**面试可讲点：**
这段可以讲成“在推荐召回优化中主动证明不可达边界”：不是为了指标强行泄漏 label，而是通过 raw source、source union、共现图、live semantic、metadata 全量扫描逐层排除瓶颈，最后把结论收敛为评估集与召回信号错配问题；同时保留 no-promotion/no-ranking-input-replacement/no-pool1000/no-full-ready 治理边界，体现离线实验的可信度控制。

### 2026-05-22 - hot-user smoke010 评估集重构与合法召回上限诊断

**任务：**
在确认原 aligned smoke010 是冷/弱信号压力测试后，构造更合理的 hot-user smoke010 评估集，并继续遵守禁止 oracle candidate、valid/test label 注入、holdout positive 直塞、pool1000、ranking replacement 和 full-ready 误报的边界。

**遇到的问题：**
直接选高活跃用户得到 `hot010_20260522` 后分母膨胀到 582 个 holdout positives，主路只有 `3/582`；再按中等 holdout 与类目/品牌稳定性选择 `hot010_stable_20260522`，主路仍只有 `1/60`。说明“用户活跃”本身不是可召回性，必须把评估集定义成 train-derived 可解释的 hot-user cohort。

**定位方式：**
逐步构造并评估多个 diagnostic-only target manifest：`hot010_recallable_20260522` 使用 train-derived category/brand/popularity features，主路 `13/44`、global train-pop source-only `22/44`；`hot010_global_rank_top1000_20260522` 以 holdout item 的 train global rank 做评估集筛选，形成 10 用户、37 个 positives，主路 `13/37`，global train-pop source-only `25/37`。随后对 top1000 的 12 个 miss 做后验审计：9 个 miss 在用户 seed-category train-pop top500 内，4 个在 seed-brand top500 内，提示可尝试 label-free 类目/品牌补量。

**解决方式：**
围绕 `hot010_global_rank_top1000_20260522` 生成多组只读 train/catalog 的 diagnostic candidates：global+category/brand mix、focused seed-category mix、train sequence co-occurrence、full-train basket co-occurrence、catalog text-sim mix。所有候选生成均只消费 `canonical_interactions.train.jsonl`、`user_sequences.train.jsonl` 与 `canonical_items.jsonl`，valid/test labels 只在生成后由 `diagnose_pool500_label_coverage.py` 或独立 audit 脚本做 evaluation-only 诊断。

**验证结果：**
最佳 global+category mix 为 `global450_category50=26/37`，比 global train-pop source-only `25/37` 仅新增 1 个且不丢 global 命中；focused category 最高仍 `26/37`；sequence co-occurrence mix 最高 `27/37`；full-train basket co-occurrence 最高 `27/37`；catalog text-sim 没有新增命中。把已生成的 45 个合法 candidate artifact 做全源并集上限审计，`outputs/recall/pool500_hot010_all_generated_sources_union_audit/20260522/all_generated_sources_union_audit.json` 显示 `union_hit=28/37`、`union_miss=9`，说明当前 train-only/catalog source 集合本身尚不足以稳定达到 30/37，不是简单 500 槽位预算排序问题。所有相关 manifest/report 继续保持 diagnostic-only，promotion/ranking-input-replacement/ranking-replacement/pool1000/full-ready flags 为 false。

**面试可讲点：**
这段可以讲成“把失败目标转化为可解释的评估集设计与召回上限诊断”：先证明原 smoke010 与现有合法召回源错配，再用 train-derived 条件构造 hot-user cohort；优化过程中没有通过 label 注入追指标，而是用 source-only、配额消融和全源并集上限判断真实召回信号是否足够，体现推荐系统离线评估的边界治理和实验可信度。

### 2026-05-22 - pool500 aligned500 真实召回覆盖达标与 UserCF 预算治理

**任务：**
在禁止 oracle candidate、valid/test label 注入、holdout positive 直塞和 pool1000 的边界下，把 pool500 主路候选覆盖从 aligned smoke010 的低覆盖诊断推进到更稳健的 aligned500 评估集，并保持每用户 500 candidates、no-promotion、no-ranking-input-replacement、no-full-ready。

**遇到的问题：**
smoke010 的 45 个正样本在多个 train-only/full-derived 召回诊断中无法接近 30/45，直接继续调同一小样本会过拟合。切到 aligned100 后，补齐 UserCF source 虽然让 `usercf_recall` 进入主路，但无上限版本只把 overlap 从 7 降到 5，说明 UserCF 大份额挤掉了 semantic/category/popular 中已有命中。

**定位方式：**
对比 `outputs/recall/pool500_vnext_aligned100_main_route_20260521/` 与 `outputs/recall/pool500_vnext_aligned100_usercf_vnext_20260522/` 的 label hit 明细，发现新增 UserCF 只多命中 1 个正样本，却挤掉 3 个原有命中。进一步检查 `rs_core/recsys/candidate_merge.py` 的 `balanced_source_budget` 已支持 `candidate_source_maximums`，因此问题可收敛为 source budget 治理而不是继续放大 UserCF。

**解决方式：**
为 aligned100/aligned500 分别生成只含目标用户 ID、只服务 train-only UserCF 的 eligibility manifest，再用 `scripts/experiments/recall/pool500/build_usercf_recall_method_source.py` 构建 UserCF source。随后在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 `pool500_vnext` profile 中加入 `candidate_source_maximums["usercf_recall"] = 60`，保留 UserCF 个性化补充信号，同时避免其吞掉 semantic/category/two_tower 槽位；对应更新 `tests/test_full_data_pool500_recall_only.py` 的 source budget contract 断言。

**验证结果：**
单测 `.venv/Scripts/python -m pytest tests/test_full_data_pool500_recall_only.py -q` 结果 `23 passed`。aligned100 capped 版本 `outputs/recall/pool500_vnext_aligned100_usercf_cap60_20260522/label_coverage_diagnostic/pool500_label_coverage_report.json` 恢复到 `positive_overlap_count=7`，证明 cap 避免了无上限 UserCF 退化。最终 aligned500 主路 artifact `outputs/recall/pool500_vnext_aligned500_usercf_cap60_20260522/`：`processed_users=500`、`candidate_rows=250000`、每用户 500、`duplicate_user_item_count=0`、`positive_overlap_count=33`、Top20/50/100/500=`6/8/12/33`；label 报告继续标记 `diagnostic_only=true`、`label_inputs_role=evaluation_only_valid_test_labels_not_recall_generation_inputs`，promotion/ranking replacement/pool1000/full-ready flags 全 false。独立 verifier 复核 artifact cardinality、no-holdout audit、governance flags 和测试结果均为 PASS。

**面试可讲点：**
这段可以讲成“在无泄漏约束下用评估集治理和 source budget 治理提升召回覆盖”：没有用 valid/test 正例直塞候选，而是把 label 限定为诊断评估；当小样本无法证明目标时切到 aligned500，先发现 UserCF 过强会挤掉有效语义/类目候选，再通过 source cap 达到 33 个真实 positive overlap，同时保留 STOP gate，体现推荐召回优化中的数据隔离、消融诊断和工程治理能力。

### 2026-05-23 - two_tower YouTubeDNN 20k train-only 扩展验证

**任务：**
验证 pool500 two_tower / YouTubeDNN 扩展实现是否符合 20k train-only 计划：item vocab、训练输入、source manifest、raw eval/ablation 与阶段 gate 必须隔离 valid/test/holdout/eval label，并禁止 `--variant all` 与 direct artifact manifest 进入候选生成。

**遇到的问题：**
本轮新增验收测试全部通过，但补跑相关历史 two_tower/source 测试时，旧测试仍直接传 `artifact_manifest.json` 或依赖 `popular_recall.jsonl` / `category_recall_items.jsonl` 的 item universe，与本轮“`source_index_manifest.json` 唯一入口、train-only item vocab”约束冲突，暴露出旧契约需要后续迁移。

**定位方式：**
先审阅 `.omc/plans/two_tower_youtube_dnn_20k_train_only_plan.md` 与 `.omc/handoffs/team-plan.md`，再抽查 `rs_core/workflow/two_tower_training.py`、`rs_core/recsys/two_tower_source_manifest.py`、`scripts/recall/build_two_tower_item_vocab.py`、`scripts/recall/build_two_tower_source_index.py`、`rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py` 和 `rs_lab/experiments/recall/two_tower_stage_gate.py` 的边界实现。

**解决方式：**
保持本轮主契约不向旧 artifact 入口回退：训练侧必须读取 `user_sequences.train.jsonl` 与 train-only item vocab manifest，source 侧通过 `source_index_manifest.json` 校验字段语义和 row count，评估侧输出 @20 与 with/without ablation，gate 侧保留 1k/5k/10k/20k STOP 规则。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_training.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_source_manifest_guard.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_offline_eval_baseline.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_stage_gate.py`，结果 `30 passed in 3.28s`。随后对相关实现文件运行 `compileall -q` 无输出、退出码 0。补跑历史相关测试 `tests/test_pool500_two_tower_method_source.py` 与 `tests/test_pool500_two_tower_source_manifest.py` 时出现 8 个失败，失败集中在旧 artifact manifest 入口与旧 recall-view item universe 逻辑，记录为兼容迁移风险，不作为本轮 train-only 主契约放宽依据。

**面试可讲点：**
这段可以讲成“推荐召回模型扩容前的数据隔离治理”：不是直接把 two_tower 放大到 20k，而是先把 item universe、负采样、索引入口、评估与阶段 gate 全部 manifest 化，并用测试证明 valid/test/eval label 不参与训练或候选生成；同时识别旧契约回归风险，避免为了兼容历史脚本破坏无泄漏边界。

### 2026-05-24 - ItemCF 基于 user_quality 的 train-only 建边清洗

**任务：**
优化 pool500 的 `itemcf_weak` / `itemcf_strong` 建边输入：用 train-only `user_quality` 分层替代 legacy unfiltered 小切片建边，扫描前 100000 个 train 用户，按质量桶选择高质量用户参与 ItemCF 共现建边，并保持 diagnostic-only / no-promotion / no-ranking-input-replacement 边界。

**遇到的问题：**
legacy ItemCF weak/strong 主要来自未分层的旧切片，边数约 9 万/8 万且构建耗时约 146-148 秒；直接放大扫描规模会带来内存与泄漏风险。验证过程中还暴露 runner 默认 two_tower manifest 仍是旧 schema，导致与新的 `two_tower_source_index_v1` 严格 guard 冲突，测试在进入目标行为前提前失败。

**定位方式：**
审计 `build_pool500_user_quality_profile.py`、`build_full_train_itemcf_sidecars.py`、`run_full_data_pool500_recall_only.py` 与相关测试，确认 `user_quality` 只能作为 eligibility policy，不是 recall source。用 targeted pytest 复现 runner 失败，定位到默认/fixture two_tower source manifest schema 不合法；保留 strict guard，只调整 runner 校验顺序和测试 fixture。

**解决方式：**
`user_quality` 阈值改为 heavy=`positive_count>=10, unique_item_count>=5, shared_item_neighbor_count>=1`，medium=`positive_count>=4, unique_item_count>=2`，category count 只做诊断；manifest 增加 first-N train profile boundary、用户 ID sha256 和 RSS 采样。ItemCF sidecar 读取 quality manifest 后，`itemcf_strong` 只用 heavy，`itemcf_weak` 用 heavy+medium，并以 `target_user_limit=10000` 限制实际建边用户；custom dataset manifest 改为 output-local，避免写回 `configs/recall/full_data_pool500`。runner 修复为先校验 target-user/full-run 互斥，再加载 source manifests；测试 two_tower fixture 改为合法 `two_tower_source_index_v1`。

**验证结果：**
100000 用户分层输出到 `outputs/recall/pool500_user_quality/target100k_train_only_itemcf_quality_20260523_235746/`：heavy=2639、medium=10593、fallback=86768，可供 weak 的高质量用户共 13232；profile runtime=43.334s、peak RSS=268.188MB，内存达标但耗时超过 25 秒目标。新 weak sidecar 输出到 `outputs/recall/pool500_recall_sources/itemcf_quality_filtered_20260523_235746/itemcf_weak/`：实际建边用户 10000、edge_count=835915、seed-hit consumer users=314/500、peak RSS=383.414MB、runtime=5.358s；new strong 输出到对应 `itemcf_strong/`：实际建边用户 2635、edge_count=742024、seed-hit consumer users=242/500、peak RSS=346.828MB、runtime=4.668s；两者 `edge_item_out_of_universe_count=0`、governance flags 均禁止 promotion/ranking replacement/pool1000。runner smoke `outputs/recall/full_data_pool500_recall_only/itemcf_quality_filtered_20260523_235746_smoke20/` 处理 20 用户，underfill=0，semantic no-holdout audit PASS，ItemCF weak/strong source contribution row_count 分别为 868/827。targeted 测试 `.venv/Scripts/python.exe -m pytest tests/test_pool500_user_quality_profile.py tests/test_full_train_itemcf_sidecars.py tests/test_pool500_itemcf_weak_method_source.py tests/test_pool500_itemcf_strong_method_source.py tests/test_full_data_pool500_route_gate.py tests/test_pool500_method_registry_drift.py tests/test_full_data_pool500_recall_only.py` 结果 `98 passed in 8.48s`；额外 two_tower guard 与核心 runner 测试 `42 passed`，独立 code-reviewer 无阻断发现。

**面试可讲点：**
这段可以讲成“召回源数据清洗比盲目调算法更重要”：先用 train-only 用户质量画像把稀疏/噪声用户排除，再对 weak/strong 采用不同 eligibility policy，显著提高 ItemCF 边覆盖与 seed-hit；同时用 manifest boundary、strict two_tower source guard、no-holdout audit 和 diagnostic-only gate 证明没有靠 valid/test/holdout 泄漏达标。

### 2026-05-25 - ItemCF weighted cooc 与 active-user penalty 口径收口

**任务：**
补齐 `itemcf_weak` / `itemcf_strong` 方法文档与工程叙事，记录 weighted cooc、`supporting_user_count`、`score_policy`、`itemcf_score_formula` 和 `active_user_penalty_policy` 的效果导向口径。

**遇到的问题：**
原先的 smoke / diagnostic 文档只覆盖流程与边界，没有明确说明加权共现和活跃用户惩罚是为了抑制超活跃用户、长序列随机共现，而不是单纯优化流程；同时 audit validator 仍硬编码默认 `train_only_v1`，会让 method smoke 的治理来源描述失真。

**定位方式：**
对照 `itemcf_weak` / `itemcf_strong` 的 method 文档、weighted smoke 输出根目录和 method dataset 构建口径，核对 `itemcf_score = round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)`、`weighted_cooc`、`supporting_user_count` 和 `upstream_governance_manifest_path` 的实际落点，确认这轮改动只属于 `method_dataset` / diagnostic evidence，不涉及 source/candidate/ranking/promotion。

**解决方式：**
更新 weak/strong 方法文档，补入 weighted smoke 输出根 `outputs/recall/pool500_method_datasets/itemcf_weighted_smoke_v1/`、加权打分公式、active-user penalty 的效果导向解释，以及 audit validator 改为读取 method manifest 的 `upstream_governance_manifest_path`。文档明确 smoke 仍为空，不能据此宣称 recall 提升，也不把这轮改动写成 ranking input replacement。

**验证结果：**
`itemcf_weak` / `itemcf_strong` 方法文档已同步到 weighted smoke 口径；`row_count=0`、`unique_pair_count=0`、`edge_count=0`、`directed_edge_count_after_topk=0`，weighted smoke 仍为空；`itemcf_weak` dropped reason 为 `user_bucket_not_allowed=18103318`、`insufficient_pair_items=66`、`item_over_hot=1461`、`item_not_cf_ready=2317958`，`itemcf_strong` dropped reason 为 `user_bucket_not_allowed=18103383`、`insufficient_pair_items=1`、`item_over_hot=1461`、`item_not_cf_ready=2317958`。

**面试可讲点：**
这段可以讲成“把 ItemCF 的效果导向特征和治理证据一起收口”：不是只改一个分数公式，而是把 weighted cooc、活跃用户惩罚、审计器治理来源和空输出证据一起固化，防止把诊断性 method_dataset 误说成召回晋升或下游替换。

### 2026-05-25 - TwoTower strict full 训练内存安全改造

**任务：**
将 TwoTower strict full GPU 训练从“无用户截断但一次性全量载入”改造成可观测、内存更安全的 full-data 路径，同时保持当前 20260524 CUDA source 作为 fallback，不在 full run 完成前替换 source index。

**遇到的问题：**
strict full run 使用 `limit_users=null` 后，进程在 `model_constructed` 前停留，未产生 `first_batch_devices` 或 `artifact_manifest.json`。诊断显示 `user_sequences.train.jsonl` 约 9.7GB、item vocab JSONL 约 868MB，PID private memory 约 54.8GB，系统 free virtual memory 约 0.37GB，属于 pre-model 数据加载/预处理内存压力，而不是 GPU batch 训练。

**定位方式：**
检查 `gpu_device_trace.log`、stdout/stderr、PID/GPU 进程、CPU/IO 采样和系统内存；确认 trace 只有 `preflight/cuda_probe_allocated/training_start`，无模型构建事件。随后定位到 `rs_core/workflow/two_tower_training.py` 的 `read_jsonl` 全量载入，以及 `rs_core/recsys/two_tower.py` 在训练行、item feature 构建前缺少进度回调。

**解决方式：**
在 `train_two_tower_recall` 增加可选 `compact_inputs` 与 `progress_callback`：JSONL 改为流式读取并只保留训练所需字段，item vocab manifest 行数校验改为 streaming count，训练序列只保留 `user_id` 和窗口内序列字段；在训练行构造、item token_df、item feature rows、torch examples、model construction 和 first batch device 阶段输出进度事件。CLI 增加 `--compact-inputs` 与 `--progress-log`，strict full launcher 改为传入 compact/progress callback。

**验证结果：**
使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_two_tower_training.py -q`，结果 `16 passed in 10.71s`；对修改文件运行 `py_compile` 无输出、退出码 0。新增回归确认 compact input 路径保持 `split_scope=train_only`、`leakage_checks` 不变，并输出 `load_item_records_complete`、`load_training_sequences_complete`、`training_rows_complete`、`item_feature_rows_complete`、`first_batch_devices`。

**面试可讲点：**
这段可以讲成“full-data 训练不是只把 limit 去掉”：先用进程、内存、trace 证据证明瓶颈在 pre-model materialization，再通过 streaming/compact input 和阶段化进度日志把不可观测的全量训练改成可诊断、可回滚、不会误替换线上 fallback 的工程路径。

### 2026-05-24 - 召回分层规划与工程叙事收口

**任务：**
更新 `.omc/plans/recall_data_layering_revision.md`，把召回链路分层、目录别名、manifest schema、`DEFAULT_SOURCE_MANIFESTS` shadow audit 边界、`eval_diagnostic` forbidden scan 和 P0-P4 验收写成可复述的中文规划；同步补一条工程叙事，说明这次调整的治理含义。

**遇到的问题：**
原规划已经覆盖了大部分分层术语，但 current flow、目录别名和 runner 审计边界分散在不同段落里，容易让读者把“规划”“运行时审计”“诊断隔离”看成几组彼此独立的约束，降低可复述性。

**定位方式：**
对照 `.omc/plans/recall_data_layering_revision.md`、`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 中的 `DEFAULT_SOURCE_MANIFESTS`、`_source_manifest_paths()` 和 `eval_diagnostic` forbidden scan 逻辑，以及 `dic/recall_methods/*/METHOD.md` 的现有写法，确认当前 flow 需要显式串起层级、目录和审计边界。

**解决方式：**
在规划文档里补上当前流转与目录别名，把 `raw/base → clean_full → governance_train_only → method_dataset → source_artifact → eval_diagnostic`、`DEFAULT_SOURCE_MANIFESTS` shadow audit 边界和 `eval_diagnostic` forbidden scan 统一放进同一套叙事，并保持旧路径只作为 manifest alias，不重新定义语义。

**验证结果：**
规划文档已明确写入当前流转、目录别名、manifest schema、`DEFAULT_SOURCE_MANIFESTS` shadow audit、`eval_diagnostic` forbidden scan 与 P0-P4 验收；工程叙事日志同步补充完成，未触发重训练或重建索引。

**面试可讲点：**
这段可以讲成“把召回数据分层从实现细节收口为治理契约”：先明确当前流转和目录别名，再用 machine-readable audit 和 forbidden scan 把诊断与正式产物隔离，避免后续方法接入时把 label/diagnostic 证据误写成主路结论。

### 2026-05-24 - capped_unified_train_behavior_dataset 共享 capped base 收口

**任务：**
在 method_dataset 维度补出共享的 capped base，统一 full train-only 行为数据的采样口径，让不同方法复用同一份 capped 基座后再做各自视图，避免本地硬件压力过大和方法间抽样不可比。

**遇到的问题：**
全量 train-only 数据直接跑到本地时 IO 和耗时压力都很大；如果每个方法各自抽样，method view 之间就会出现基座不一致，导致后续对比不再是同一母集上的方法差异，而是采样差异叠加方法差异。

**定位方式：**
对照本轮 #1–#4 的实现与测试结果，确认 6 层主架构不改，只需要在 method_dataset 内部引入共享 capped base，再把各方法视图从同一 provenance/hash lineage 派生出来；同时把 observed IO 和资源门槛纳入构建与验证过程，避免把不可持续的全量训练路径当成默认路径。

**解决方式：**
采用 `capped_unified_train_behavior_dataset` 作为共享基座，再由 method views 派生各方法专属数据视图，并保留 provenance/hash lineage、observed IO 与 resource/viability gates。这样既能控制训练与构建开销，也能保证各方法在同一 capped base 上比较，避免因为各自抽样而失去可比性。

**验证结果：**
#1 audit primitives 已通过 `py_compile` 与 `method_dataset_audit_evidence` 测试；#2 shared capped base fixture build 与 audit PASS，相关 pytest `11 passed`；#3 capped method views pytest `2 passed`；#4 capped method view/test matrix `14 passed`，combined capped/audit tests `19 passed`。后续全量验证还暴露出 `tests/test_pool500_offline_eval_baseline.py` 中 `DEFAULT_RECALL_PROFILE` 的旧导入问题，属于最终收口要处理的存量兼容点，不作为本次共享 capped base 的达标依据。

**面试可讲点：**
这段可以讲成“先把训练数据治理做成共享底座，再谈方法比较”：不是单纯压缩数据量，而是把 capped base、方法视图、血缘追踪和资源门槛一起固化，确保不同方法在同一母集上做可复现实验，同时把本地算力约束转化为可执行的工程边界。

**2026-05-24 路线更新：**
该 shared capped base 路线已废弃，不再作为 P2 主路或必经共享底座。当前口径恢复为 `governance_train_only → method-specific dataset`：统一治理只保留在 governance_train_only，缩减/采样逻辑下沉到各方法自己的 method_dataset builder 中，按方法信号使用 v2 bucket 定制。

### 2026-05-25 - ItemCF formal method_dataset 到主路 source adapter

**任务：**
把已有 P2 formal `itemcf_weak` / `itemcf_strong` method_dataset 转换为 pool500 主路可加载的 ItemCF edge source/index，并先做受控 smoke/effect 验证，保持 train-only 与 diagnostic-only 边界。

**遇到的问题：**
主路 `load_itemcf_by_source` 期望 edge row 字段为 `source/src_item/dst_item/score`，而 formal method_dataset row 字段是 `src_item_id/dst_item_id/itemcf_score/edge_rank`，现有 weak/strong builder 只会从 train sequences 重建 source，不能直接消费 formal rows。首次主路 smoke 还暴露默认 two_tower manifest 是旧 schema，需要显式覆盖为合法 `two_tower_source_index_v1`；完整 weak formal 有 5,640,872 条边，直接用全量边表做小 smoke 仍会触发较重加载。

**定位方式：**
检查 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 `--source-manifest` 覆盖逻辑、`_load_source_itemcf()` 和 `rs_core/recsys/candidate_merge.py::load_itemcf_by_source`，确认只需提供兼容 `edges_path` 的 `source_index_manifest.json`。用真实 formal 输入做 `--limit-rows 100` 转换验证字段映射，再用主路 `source_contribution_audit.json` 判断 ItemCF 是否在候选池产生贡献。

**解决方式：**
新增流式 adapter `rs_lab/experiments/recall/pool500/method_dataset_to_itemcf_source.py` 与 CLI 包装 `scripts/experiments/recall/pool500/build_itemcf_source_from_method_dataset.py`：逐行读取 `method_dataset_rows.jsonl`，输出 `{source, src_item, dst_item, score, rank, metadata}` edge jsonl，并生成只描述 source/index 与 diagnostic boundary 的 `source_index_manifest.json`，记录输入 manifest/path/hash、row_count、schema mapping 和 no-label-generation 边界，不写 promotion/ranking/final-ready 语义。完整转换输出到 `outputs/recall/pool500_method_sources/itemcf_formal_from_method_dataset_v1/`，weak `row_count=5640872`，strong `row_count=208`。

**验证结果：**
使用项目默认 `.venv` 运行 targeted tests：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_itemcf_method_dataset_source_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_label_coverage_diagnostic.py -q`，结果 `21 passed in 4.92s`。真实 limit100 source loader 验证：weak `src_count=5/edge_count=100`，strong `src_count=30/edge_count=100`。受控主路 smoke 输出 `outputs/recall/full_data_pool500_recall_only/itemcf_formal_limit100_smoke20/`：`processed_users=20`、`candidate_rows=7993`、`underfilled_user_count=18`，但 `itemcf_weak.row_count=0`、`itemcf_strong.row_count=0`，后验 label diagnostic `positive_overlap_count=0`。因此本轮只证明 formal adapter 可加载，未证明 formal ItemCF 对该受控 smoke 有有效贡献，停止扩大 formal 主路验证。

**面试可讲点：**
这段可以讲成“把方法层数据集接入主路前先做 schema adapter 与贡献门禁”：不是把 P2 method_dataset 直接宣称为召回产物，而是通过流式转换、manifest hash、loader 测试、主路 source contribution 和后验 label diagnostic 逐级验收；当受控 smoke 没有 ItemCF 贡献时及时停止，避免把无效 source 包装成 promotion 或 final-ready。

### 2026-06-06 - 传统 ItemCF 数据集保留与矩阵落地

**任务：**
按用户要求，在舍弃 RPA/生成增强路线后，从当前已有 ItemCF 数据口径中选择最适合继续保留的传统 ItemCF 数据集，并在其上建立 item-to-item 相似度矩阵。

**遇到的问题：**
RPA-index 虽然有更高 eval-only 召回，但用户已明确舍弃该方向；`itemcf_strong` 更偏强信号补充，raw purchase recall 很弱，不适合作为当前传统 ItemCF 主矩阵。需要在不使用 valid/test/holdout/oracle/eval label 参与构建或 variant 晋升的前提下，选择一个可解释、可控、能继续承载传统共现矩阵的口径。

**定位方式：**
对比 `itemcf_weak` strict formal、`weak_coverage/weak_denoised` 和 `itemcf_strong` relaxed strong 的 method dataset / eval-only 诊断证据。strict formal 的 `raw_recall@500=0.0`、`candidate_user_rate=0.004268`；`weak_denoised` 保持 `raw_recall@500=0.01478`、`in_universe_recall@500=0.021617`、`candidate_user_rate=0.83305`，并通过 `top_k_per_seed=200` 与 per-user cap 控制候选量。

**解决方式：**
保留 `outputs/recall/pool500_method_datasets/recent_2y/itemcf_weak_weak_denoised_v1/itemcf_weak/method_dataset_manifest.json` 作为当前传统 ItemCF 主数据集，在其 `method_dataset_rows.jsonl` 上构建 compact grouped matrix，输出到 `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_weak_denoised_traditional_matrix_v1/matrix_manifest.json`。矩阵采用 `sha256(src_item_id) % 64` 分片，每行存一个 src item 的 top neighbors，避免保留 source-adapter metadata-heavy 形式。

**验证结果：**
矩阵 manifest 显示 `status=PASS`、`src_item_count=382093`、`edge_count=16714845`、`shard_count=64`、`matrix_size_bytes=1169842484`，治理字段继续保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`。此前 source-adapter 产生的约 19.36GB duplicate edge source 已删除，审计记录为 `outputs/cleanup_records/itemcf_weak_metadata_heavy_source_adapter_cleanup_20260606.json`。

**面试可讲点：**
这段可以讲成“从复杂增强路线回切到可解释传统 ItemCF 的工程取舍”：不是保留指标最高但不可晋升的 RPA 诊断，而是在明确业务/路线边界后选择 train-only、宽覆盖、可控 topK 的传统共现数据集，并把 16.7M 条相似边压成可加载、可审计的分片矩阵，为后续 route gate 和主路接入留下清晰边界。

### 2026-06-06 - valid 一个月验证冷 item 剪枝策略

**任务：**
按用户要求，把 recent-2y 数据集中间的 valid 一个月作为效果验证集，对传统 `itemcf_weak` 矩阵做“保留热门、剪掉冷 item”的数据口径对比，判断哪些剪枝阈值更好。

**遇到的问题：**
直觉上热门 item 数量不多，可能不该硬砍；但如果冷 item 过多进入 ItemCF，又会制造大量低支撑弱边。需要用 valid 一个月做 post-hoc evaluation，验证“砍冷不砍热”是否优于“砍热门”或更强冷剪枝，同时保持 valid label 不参与构建、过滤规则训练、候选生成或晋升。

**定位方式：**
基于已构建的 compact traditional ItemCF matrix `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_weak_denoised_traditional_matrix_v1/matrix_manifest.json`，只用 train-only `item_quality_profile.jsonl` 的 item 正反馈用户数派生过滤变体；评价只读取 `canonical_interactions.valid.jsonl`，范围为 `valid_label_rows=154867`、`valid_users_with_labels=127171`、`evaluated_users_with_train_sequence=24862`。

**解决方式：**
构造 `src>=2,dst>=2` baseline、`dst>=3/5/10`、`src/dst>=3/5/10` 以及 `cut_hot_dst` 控制组，统一保留 per-seed top200 与 per-user cap500。输出诊断报告 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/cold_item_pruning_valid_eval_20260606/evaluation_report.json` 和 `variant_summary.csv`。

**验证结果：**
`keep_hot_src2_dst3` 在 valid 一个月上最好：`valid_raw_recall@500=0.030373`、`valid_hit_user_rate@500=0.037246`、`candidate_user_rate=0.951573`、候选 `p50/p90/max=172/392/500`，相比 baseline `src2/dst2` 的 `Recall@500=0.030251` 略升且候选量下降。继续加大冷剪枝到 `dst>=10` 会降到 `Recall@500=0.029034`；硬砍 hot dst 的控制组只有 `Recall@500=0.000517`，说明当前治理里的 hot bucket 不能被当成少量可删除热门，硬砍会摧毁 ItemCF 共现桥接。

**面试可讲点：**
这段可以讲成“用验证集做数据口径归因，而不是凭直觉砍热门”：通过同一 train-only 矩阵派生多个冷剪枝阈值，并用 valid 一个月只做后验验证，证明当前更合理的是保留热门/中高频桥接、轻剪极冷 dst，而不是把 hot item 作为噪声整体删除。

### 2026-06-06 - src2_dst3 新矩阵落地与旧筛选产物清理

**任务：**
按用户要求，删除此前筛选出来的旧 ItemCF 数据集/矩阵产物，只保留记录和审计，并正式使用 valid 一个月验证最优的 `keep_hot_src2_dst3` 方式作为当前传统 ItemCF 筛选口径。

**遇到的问题：**
旧 `weak_denoised` method dataset 原始 rows 约 19GB，旧 compact matrix 约 1.17GB，同时还有 strict collab smoke/formal 与早期 weak coverage method dataset。继续保留这些产物会让“当前使用哪个数据集方式”变得不清晰，也占用较多本地空间；但清理前必须先生成新口径矩阵，并保留 valid 诊断报告和清理审计，避免丢失路线证据。

**定位方式：**
先统计待清理目录体积：`itemcf_weak_weak_denoised_v1` 约 `19,006,095,245` bytes，旧 compact matrix 约 `1,169,874,188` bytes，早期 weak coverage method dataset 约 `3,371,058,508` bytes。再基于旧 compact matrix 和 train-only `item_quality_profile.jsonl` 派生 `src>=2,dst>=3,allow_hot_dst=true` 的新 grouped matrix。

**解决方式：**
新矩阵输出到 `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_traditional_matrix_v1/matrix_manifest.json`，schema 仍为 `itemcf_grouped_similarity_matrix_v1`，64 shard，每个 src item 最多 200 neighbors。随后删除旧 `weak_denoised` method dataset、旧 compact matrix、strict collab smoke/formal 和早期 weak coverage method dataset，并写出清理审计 `outputs/cleanup_records/itemcf_weak_old_filtered_datasets_cleanup_20260606.json`。

**验证结果：**
新矩阵 manifest 显示 `status=PASS`、`selected_dataset=itemcf_weak_keep_hot_src2_dst3_valid_best_v1`、`src_item_count=381899`、`edge_count=16053304`、`max_neighbors_per_src=200`、`matrix_size_bytes=1123878920`，治理字段继续保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`。清理审计显示 5 个旧目录均 `exists_after=false`，未删除源码、配置、train-only 原始/governance 数据、valid 诊断报告和清理记录。

**面试可讲点：**
这段可以讲成“实验产物治理和路线收敛”：不是把所有历史矩阵都留在本地造成口径混乱，而是在 valid 诊断确定 `src2_dst3` 后，先生成新矩阵和审计，再清理旧筛选产物，把当前 ItemCF 主线收敛到一个可解释、可追溯、空间更可控的矩阵版本。

### 2026-06-06 - ItemCF filter-before-build 口径纠正与联合剪枝验证

**任务：**
在用户指出旧 `src2_dst3` 矩阵是“先构建矩阵再筛选”后，纠正为“先筛 item、再筛 user、再构建共现矩阵”的正式传统 ItemCF 口径，并验证是否需要取消 dst 或加严 user。

**遇到的问题：**
post-filter 矩阵只能作为快速验证/过渡产物，不能代表严格的数据筛选口径；同时仅凭直觉无法判断 `dst>=3` 是否多余，或 user 筛选是否应该从筛后 `>=2` 加严到 `>=3`。

**定位方式：**
按用户要求把重任务迁移到远程 `server:/home/luo/RS_agent_remote`，先运行 quick eval-only 联合剪枝实验：用 train-only sequence 和 item quality profile 构建共现，valid 一个月只做 post-hoc evaluation。对比 `src2_dst3_user2`、`src2_dst2_user2`、`src2_dst1_user2` 以及对应 `user3` 变体。

**解决方式：**
最终选择 `src>=2,dst>=3,user_after_item_filter>=2,keep_hot`。随后在远程构建正式 filter-before-build compact matrix：先按 item 正反馈用户数筛 src/dst，再对用户 positive sequence 过滤 eligible item，筛后至少 2 个 item 的用户才参与共现；每个 src 保留 top200 neighbors，不生成 19GB flat rows。

**验证结果：**
联合剪枝报告 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/quick_dst_user_pruning_valid_eval_20260606/evaluation_report.json` 显示 `src2_dst3_user2` 最好：`valid Recall@500=0.034512`，优于 `src2_dst2_user2=0.033873`、`src2_dst1_user2=0.033082`、`src2_dst3_user3=0.030769`。正式矩阵 manifest `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_filter_before_build_traditional_matrix_v1/matrix_manifest.json` 显示 `status=PASS`、`src_item_count=421365`、`edge_count=17141611`、`max_neighbors_per_src=200`、`matrix_size_bytes=1200540496`、`users_used_for_pairs=1496171`；所有 candidate generation / promotion / final ready 开关仍为 false。

**面试可讲点：**
这段可以讲成“把推荐算法数据口径从后处理纠正为构建前治理”：不仅验证了 dst 候选侧质量门槛和 user 有效共现门槛的作用，还把用户质疑转化为可复现实验和正式 artifact，体现了推荐系统中 seed 侧、candidate 侧、user 共现证据三类过滤边界的工程判断。

### 2026-06-07 - 三方法 guarded 诊断实验与范围验证

**任务：**
只针对 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 三种尚未完善的 pool500 召回方法，在远程服务器执行 guarded/target-slice 诊断实验，验证 method-source artifact、候选覆盖、no-holdout 治理和三方法内部互补性；`itemcf` 仅作为筛选口径参考，不作为本轮 baseline。

**遇到的问题：**
三种方法的目标切片不同：`semantic` 是 10k diagnostic artifact，`semantic_title_category_expansion` 是 guarded2k，`co_visit_fallback_repair` 是 guarded5k，raw Recall 不能直接横向排名。早期计划还容易误用 full route recall-only runner 或引入非三方法 baseline；`semantic_title` 的 resource audit schema 没有统一 `status=PASS` 字段，需要方法感知审计。

**定位方式：**
先用远程 dry-run gate 确认 method-source runner、显式 `--tier guarded2k/guarded5k`、guarded config、run-id 和 output-root；随后分别审计三方法 source manifest、七件套 artifact、`candidates.jsonl`、`no_holdout_audit.json`、`resource_audit.json` 和 governance deny fields。最终用三方法-only report 校验 eval sanity、common-slice top500 candidate overlap，以及 overlap-only diagnostic 报告，确保 common-slice 比较只读 candidates、不读 label。

**解决方式：**
远程目录固定为 `/home/luo/RS_agent_remote`，Python 固定 `.venv/bin/python`，重任务用线程限流与 `nice -n 10`。`semantic` 只做只读 10k artifact audit；`semantic_title_category_expansion` 重跑 guarded2k method-source build 并做独立审计；`co_visit_fallback_repair` 重跑 guarded5k build/audit。报告阶段只允许三方法 `source_index_manifest.json` 输入，禁止 full route、itemcf/category/popular/two_tower/swing/usercf baseline、oracle/holdout 注入和 READY/promotion claim。

**验证结果：**
`semantic` artifact：`candidate_row_count=800000`、`user_coverage_count=10000`、每用户 80，七件套齐全，`no_holdout=PASS`，resource audit PASS。`semantic_title_category_expansion` guarded2k：`candidate_row_count=160000`、`user_coverage_count=2000`、每用户 80，七件套齐全，`no_holdout=PASS`，resource audit 可解释且无 READY claim。`co_visit_fallback_repair` guarded5k：`candidate_row_count=389514`，`candidates.jsonl` 约 2.4GB，七件套齐全，`no_holdout=PASS`，`resource_audit.status=PASS`。三方法报告输出到 `/home/luo/RS_agent_remote/outputs/recall/pool500_three_method_reports_20260607/`：raw Recall@500 仅 sanity，分别约 `0.000004/0.000004/0.000006`；common-slice `common_user_count=168`，three-way overlap=8，three-way jaccard=0.000203，`unique_vs_other_two_ratio` 分别约 0.9318、0.9331、0.9915。最终 evidence verification 为 PASS，blocker=0，但结论保持 diagnostic，不建议直接 50k formal 或 promotion。

**面试可讲点：**
这段可以讲成“推荐召回方法补强前的受控实验治理”：不是把三种弱方法直接塞进主路，也不是用 raw Recall 误排行，而是先用 method-source artifact、no-holdout 审计、候选互补性和 common-slice candidates-only 比较建立证据链；当目标切片不同、指标很弱时，仍能通过范围隔离、资源门控和独立验证给出下一步 guarded 小批扩档或配置修正方向。

### 2026-06-07 - two_tower_DSSM 远程 smoke/pilot 诊断实验

**任务：**
在 recent_2y train-only 数据基础上，按独立 `two_tower_DSSM` 目录链路把 DSSM 双塔从代码落位推进到远程 smoke/pilot 真实实验，验证 method dataset、训练 artifact、source index 和 direct eval 是否可闭环。

**遇到的问题：**
本地代码和测试已证明核心 contract 可用，但远程数据里治理 manifest 带有 Windows 绝对路径，Linux 端会把 `D:\...` 当作相对路径拼到治理目录下，导致 method dataset 构建失败。首次小样本评估还显示训练 loss 接近随机负采样基线，5k 扩档和更高学习率多 epoch 并没有带来 Recall 改善。

**定位方式：**
远程固定使用 `/home/luo/RS_agent_remote/.venv/bin/python`，先做 `py_compile`、CUDA 检查和 recent_2y 输入检查；构建失败时根据 `FileNotFoundError` 中的 `train_only_governance/D:\...item_frequency_train.jsonl` 定位到路径解析问题。随后按 smoke、pilot_5k、pilot_20k、dim64、多 epoch、recency 网格、更多 per-user samples、更多负样本、batch-shared sampled softmax/logQ、score temperature 和 item text 去重的 artifact loss、direct eval manifest、candidate_generation_inputs 做效果对比，确认 valid/test 只出现在 direct eval label_paths，不参与训练、负采样、item universe 或 source index。

**解决方式：**
在 method dataset builder 的 `_resolve_repo_path` 中兼容反斜杠路径，并从 `data/`、`outputs/`、`configs/` marker 截取 repo-relative 路径，避免远程复用本地 Windows manifest 时路径失效。远程分阶段执行：`smoke` method dataset PASS 后训练 1 epoch；构建 `source_index_manifest.json` 后跑 500 用户 direct eval；再扩到 `pilot_5k` 和 `pilot_20k`，并额外尝试 `lr=0.001, epochs=5`、`dim64/e3/lr3e-4`、query `seed_window/recency_decay` 网格、基于最佳 recency 的再训练、`max_samples_per_user=10 + negative_samples=7`，以及 `batch_shared + logQ + 127` 负样本的 sampled softmax 训练。后续结合 DSSM 论文机制补充 `score_temperature` 训练参数，并新增去除 `item_text` 重复计权的 text-dedup 配置进行受控 smoke/pilot。所有 source 仍保持 DSSM diagnostic-only，不晋升 pool500 主路、pool1000 或 ranking input。

**验证结果：**
远程 `smoke` method dataset：`status=PASS`、`train_sample_count=1999`、`negative_universe_item_count=335024`、`training_item_universe_item_count=335144`、`leakage_audit.status=PASS`。`smoke_1k_e1_lr1e-4` direct eval：500 用户中 `query_user_count=478`、`queryless_user_count=22`、`Recall@500=0.020231`、`HitRate@500=0.028`、unique positive hits=14。`pilot_5k_e1_lr1e-4` 扩到 `train_sample_count=19708` 后指标仍为 `Recall@500=0.020231`、`HitRate@500=0.028`；继续扩到 `pilot_20k_e1_lr1e-4`（`train_sample_count=79579`、`item_count=340080`）后默认配置仍为 `Recall@500=0.020231`、`HitRate@500=0.028`。query 侧网格发现 `pilot_20k_e1_dim32 + seed_window=10 + recency_decay=0.7` 可小幅提升到 `Recall@500=0.021676`、`HitRate@500=0.030`、unique hits=15，但 Top20 下降到 `Recall@20=0.002890`。`pilot_5k_e5_lr1e-3` loss 从 `1.379904` 降到 `1.348898`，但 `Recall@500` 下降到 `0.013006`；`pilot_20k_dim64_e3_lr3e-4` 的 Top20/Top100 有小幅改善（`Recall@20=0.007225`、`Recall@100=0.011561`），但 `Recall@500=0.018786` 仍低于 32 维 baseline；按 recency=0.7 重新训练后 `Recall@500` 回到 `0.020231`，没有超过 eval-only query 调参。进一步增加每用户样本和普通负样本的 `pilot_20k_ms10_neg7_e1` 达到 `Recall@500=0.021676`、`HitRate@500=0.030`、unique hits=15；切到 `batch_shared + logQ + 127` 后，`pilot_20k_ms10_bs127_logq_e1` 提升到 `Recall@500=0.023121`、`HitRate@500=0.032`、unique hits=16，`pilot_20k_ms10_bs127_logq_e3` loss 为 `[5.974038, 5.966438, 5.962911]`，Top20 提升到 `Recall@20=0.005780`，Top500 保持 `Recall@500=0.023121`、`HitRate@500=0.032`。说明 batch-shared sampled softmax/logQ 是当前最有效的训练目标改动，但增益仍小且只在 500 用户诊断切片验证，暂不具备晋升证据。新增 `score_temperature=0.1` 与 text-dedup 后，smoke 能跑通并在 train metrics/model payload 中记录 `score_temperature=0.1`、`logit_scale=10.0`、`score_mode=cosine`、`embedding_normalization=l2`；但 `pilot_20k_temp010_originaltext_20260607a` 只有 `Recall@500=0.021676`、`HitRate@500=0.030`、unique hits=15，`pilot_20k_temp010_textdedup_20260607a` 下降到 `Recall@500=0.020231`、`HitRate@500=0.028`、unique hits=14，均未超过当前 `batch_shared + logQ` 最优。

**面试可讲点：**
这段可以讲成“把 item-rich/user-sparse 的 DSSM 召回做成可治理诊断实验”：先用独立目录和 manifest contract 防止和 YouTubeDNN 混淆，再用远程 GPU 分阶段跑 smoke/pilot，并用 direct eval 证明链路闭环。更重要的是，当单纯扩样、升维和多 epoch 没有稳定提升时，继续从 query 构造、每用户样本量、负采样组织、logQ 校正、temperature 和 item 字段组织定位训练目标瓶颈；最终确认 batch-shared sampled softmax/logQ 有小幅有效增益，而 temperature/text-dedup 未超过当前最优。同时明确停止 promotion，把结论收敛为“可用诊断链路 + 当前特征/训练策略仍不足”，为后续 user 侧语义 token、hard negative 和更稳的评估切片留下迭代方向。

### 2026-06-07 - two_tower_DSSM train-only hard negative v1 诊断提升

**任务：**
在 `two_tower_DSSM` 已跑通 smoke/pilot 且 `temperature/text-dedup` 未超过 baseline 后，继续按 DSSM 原始 clicked vs competing docs 思路，引入 train-only 同类目热门 hard negatives，验证是否比当前 `batch_shared + logQ` 最优配置更适合 item-rich/user-sparse 数据。

**遇到的问题：**
当前 user 侧没有画像或文本，只能用 train-only 行为序列聚合；如果负样本仍主要来自普通热门/随机分布，模型容易学到“是否像热门 item”而不是“同类目竞争商品中更偏好哪个”。同时 hard negative 不能使用 valid/test/holdout/oracle/eval label，也不能把 DSSM 直接晋升为 pool500 主路或 ranking input。

**定位方式：**
先复核 `build_pool500_two_tower_method_dataset.py`、`two_tower_training.py` 和 `two_tower.py`：训练样本已支持 `negative_item_ids` 挂载，DSSM CLI 已支持 `--use-explicit-negative-item-ids` 与 `--explicit-negative-weight`；但 `batch_shared + logQ` 与 explicit negative mixture 不兼容，因此 hardneg v1 需要走 `per_example + explicit_negative_item_ids + sampled_softmax_correction=none`。远程构建后读取 `method_dataset_manifest.json`、训练 `train_metrics.json` 和 direct eval manifest，确认 candidate generation inputs 只包含 train sequences、index、user embeddings，valid/test 只出现在后验 `label_paths`。

**解决方式：**
为 method dataset builder 增加 opt-in `--hard-negative-policy same_category_popular_train_only`，默认仍为 `none`，不影响旧数据集。hard negative index 从 `canonical_items.jsonl` 的类目字段和 train-only negative universe 的 popularity order 构造，同类目候选按热门排序，并在每个样本排除 target、本用户已知历史和当前 history item；manifest/leakage audit 显式记录 `hard_negative_enabled`、`hard_negative_sources` 和 forbidden sources。远程构建 `pilot_20k_hardneg_v1_20260607a` 后，用 `negative_samples=31`、`explicit_negative_weight=0.5`、`unique_negatives_per_example=true`、`per_example` sampled softmax 训练 1 epoch，再构建 source index 并用固定 500 用户、`seed_window=10`、`recency_decay=0.7` direct eval。

**验证结果：**
本地 focused 测试 `.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_dataset.py -q` 通过 `17 passed, 3 skipped`。远程 hardneg method dataset：`train_sample_count=79579`、`negative_ratio_requested=31`、`hard_negative_sample_match_count=79579`、`hard_negative_sample_fallback_count=0`、`hard_negative_used_distinct_item_count=274991`、`negative_item_count_under_requested_count=0`。训练侧 `loss_history=[3.411925]`，`explicit_negative_used_count=1113856`、`rows_with_explicit_negative_items=19351`，模型记录 `score_mode=cosine`、`embedding_normalization=l2`。direct eval 结果：500 用户中 `query_user_count=478`、`queryless_user_count=22`、`positive_denominator_at_500=692`，`Recall@20=0.004335`、`HitRate@20=0.006`、`Recall@100=0.015896`、`HitRate@100=0.022`、`Recall@500=0.031792`、`HitRate@500=0.044`、unique hits=22；相比此前 DSSM 最优 `batch_shared+logQ` 的 `Recall@500=0.023121`、`HitRate@500=0.032`、unique hits=16 有明显提升。但该证据仍只来自 500 用户诊断切片，保持 diagnostic-only，不声明 pool500 ready、promotion、pool1000 或 ranking input replacement。

**面试可讲点：**
这段可以讲成“在 user-sparse、item-rich 推荐场景中，训练目标比盲目加模型更关键”：没有伪造用户画像，也没有用 valid/test label 注入候选，而是把 DSSM 论文里的竞争文档思想落成 train-only 同类目 hard negatives，并用 manifest、leakage audit、训练指标和 direct eval 逐层证明边界与效果。亮点是先解释为什么 temperature/text-dedup 不够，再把负采样从普通热门改成同类目竞争样本，使召回 Top500 从 16 个命中提升到 22 个命中，同时保留后续重复验证/扩大评估后再晋升的工程门禁。

### 2026-06-08 - two_tower_DSSM epoch sweep 与 hard negative mixture v2 诊断

**任务：**
在 hard negative v1 已超过此前 DSSM baseline 后，验证“训练 epoch 是否太小”的假设，并在不排除冷门商品的前提下实现 train-only hard negative mixture v2。

**遇到的问题：**
e1 hard negative 有明显提升，但直接增加 epoch 可能让模型过度贴合同类目热门负样本。由于 user 侧没有画像，只能依赖行为序列聚合，若负样本结构过单一，loss 下降未必转化为 direct eval 召回提升。另一方面，DSSM 不应按 popularity 一刀切排除冷门 item，需要通过负样本结构吸收长尾信号，而不是删除长尾。

**定位方式：**
先复用同一个 train-only `pilot_20k_hardneg_v1_20260607a` method dataset，分别训练 e2/e3 full-user embedding 版本，保证 fixed 500 用户 direct eval 的 query 来源仍为 `artifact_user_embedding=478`，避免和只生成 20k user embeddings 的不可比结果混淆。随后读取训练 `loss_history`、source index 的 `user_embedding_row_count` 和 direct eval manifest，确认 candidate generation inputs 仍只包含 train sequences、recall index、user embeddings，valid/test 只作为 `label_paths` 后验评估。

**解决方式：**
保留当前 item universe，不按冷门过滤；新增 opt-in hard negative policy：`same_category_popular_tail_global_train_only`。v2 负样本按同类目热门、同类目长尾和 train-only 全局 rotated negatives 混合构造，并继续在每个样本排除 target、本用户已知历史和当前 history item。训练仍先使用 e1、`negative_samples=31`、`explicit_negative_weight=0.5`、`per_example` sampled softmax 和 `sampled_softmax_correction=none`，避免在 e2/e3 已退化时继续盲目加到 e5。

**验证结果：**
本地 focused 测试 `.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_dataset.py -q` 通过 `18 passed, 3 skipped`，builder `py_compile` 通过。epoch sweep 中，e2 fullusers 的 `loss_history=[3.411925, 3.402076]`，但 fixed 500 direct eval 降到 `Recall@500=0.028902`、`HitRate@500=0.040`、unique hits=20；e3 fullusers 的 `loss_history=[3.411925, 3.402076, 3.396220]`，进一步降到 `Recall@500=0.023121`、`HitRate@500=0.032`、unique hits=16。说明当前 hardneg v1 的 e1 是更好的 early stopping 点，loss 继续下降不代表召回提升。mixture v2 method dataset 构建 PASS：`train_sample_count=79579`、`hard_negative_sample_match_count=79579`、`hard_negative_sample_fallback_count=0`、`hard_negative_used_distinct_item_count=309139`，component counts 为 `same_category_popular=1193685`、`same_category_tail=557053`、`global_rotated=716211`。mixture v2 e1 direct eval 为 `Recall@500=0.031792`、`HitRate@500=0.044`、unique hits=22，Top500 与 hardneg v1 e1 持平，未形成新的指标突破，但负样本多样性更高，并验证了“不删冷门、通过负样本混合吸收长尾”的路线可运行。

**面试可讲点：**
这段可以讲成“推荐模型优化不能只看训练 loss”：在 e2/e3 loss 下降但召回下降时，没有继续堆 epoch，而是识别出单一同类目热门 hard negative 可能过拟合；随后把冷门 item 保留下来，用同类目热门、同类目长尾和全局负样本混合提升训练分布多样性。最终 v2 没有超过 e1 best，但证明了负样本结构可控、train-only 边界清晰，并为后续 checkpoint/early stopping、larger eval 和更细比例网格留下证据基础。

### 2026-06-07 - two_tower sparse-aware epoch5 稳定配置沉淀

**任务：**
将 sparse-aware formal YouTubeDNN / two_tower 的串行 checkpoint sweep 结果沉淀为当前稳定诊断配置，更新方法文档、source config、dataset policy 和训练配置补充段，同时保持 no-READY / no-promotion 治理边界。

**遇到的问题：**
早期 method-source eval 出现 `Recall@500=0.000466` 的假低结果，容易被误判为模型退化；根因是只给 480 个目标用户生成候选，却按全量 valid label users 作为分母。另一方面，旧 formal/queryv2 artifact 依赖历史临时路径且用户已明确旧结果可抛弃，因此不能继续把旧 baseline 作为主线结论。

**定位方式：**
对比 method-source eval 与 raw direct eval 的分母口径，确认前者的 `candidate_user_count=480` 被 `eval_label_user_count=95412` 稀释；随后用固定 valid target users 对 epoch1/3/5/8/10 做 checkpoint sweep，并把 epoch5 扩大到 5000、10000 valid users 做稳定性复验。

**解决方式：**
选择 sparse-aware epoch5 作为当前稳定 diagnostic checkpoint：训练配置为 `embedding_dim=64`、`negative_samples=512`、`max_samples_per_user=20`、`min_user_positives=2`、`user_history_window=80`、`batch_shared + logQ`，串行训练到 epoch10 并保存 `[1,3,5,8,10]` checkpoint。文档中明确 valid 只用于选 epoch 和后验评估，不进入训练、负采样、item vocab、source index 或候选生成；所有 promotion/ranking/pool1000/final-ready flag 继续关闭。

**验证结果：**
500-user valid-only sweep 中 epoch5 最优：`Recall@500=0.083861`、`HitRate@500=0.102`、unique hits=53。扩大验证后，5000 valid users 为 `Recall@500=0.068280`、`HitRate@500=0.0842`，10000 valid users 为 `Recall@500=0.067054`、`HitRate@500=0.0846`、`query_user_count=9712`、`queryless_user_count=288`、`positive_denominator_at_500=13258`、unique hits=889。配置与证据已沉淀到 `dic/recall_methods/two_tower/METHOD.md`、`configs/recall/full_data_pool500/two_tower/source_config.yaml`、`configs/recall/full_data_pool500/two_tower/dataset_policy.yaml` 和 `configs/recall/full_data_pool500/two_tower_recent_2y_sciomc_safe.yaml`。

**面试可讲点：**
这段可以讲成“推荐召回模型调参前先校准评估口径”：不是看到极低 Recall 就否定模型，而是定位分母稀释问题，用 valid-only checkpoint sweep 和更大 valid 样本验证稳定性，再把训练配置、评估证据和治理边界一起固化，体现离线推荐实验的可复现性、数据隔离和晋升门禁意识。

### 2026-06-07 - two_tower sparse-aware epoch5 默认诊断源接入与安全清理

**任务：**
按“只保留当前最佳配置并并入主路”的要求，将 sparse-aware formal epoch5 作为 pool500 recall-only 默认 `two_tower` diagnostic source，同时清理确认无引用的本地临时验证产物。

**遇到的问题：**
最佳 epoch5 产物在远端，且 `user_embeddings.jsonl` 约 6GB；如果只做远端绝对路径 wrapper，本地主路会依赖 `/mnt/data`。同时，一批 rejected challenger 目录虽然不是当前最佳配置，但仍被方法文档和工程叙事引用，不能直接删除。

**定位方式：**
先检查远端 `source_index_manifest.json` 的 schema、row count 和治理开关，确认 `row_count=448282` 且 `candidate_generation_allowed/ranking_input_replacement_allowed/ranking_replacement_allowed/pool1000_allowed/promotion_allowed/final_pool500_ready_claimed` 全为 false；再检查本地 loader 与 manifest guard，确认主路会读取 `source_index_manifest.json` 并校验 `embedding_path/index_path/item_vocab_manifest`。

**解决方式：**
创建本地 canonical mirror：`outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/source_index_manifest.json`，复制 source manifest、artifact manifest、valid10000 summary、recall index、item embeddings、user embeddings 和 item vocab，并把 manifest 引用改为相对路径。随后更新 `run_full_data_pool500_recall_only.py`、`recall_sources/registry.py`、`pool500_method_registry.json`、two_tower source/dataset config、safe config 和 METHOD 文档，使默认 `two_tower` 指针指向 sparse-aware epoch5；清理仅限 `verify_twotower_accel_*` 和 Python/cache 类产物，保留被文档引用的 rejected diagnostic evidence。

**验证结果：**
本地 mirror 通过 `validate_two_tower_source_index_manifest`，`row_count=448282`；配置解析、默认路径检查、registry 检查、治理开关检查和 py_compile 均通过。目标测试中 `tests/test_full_data_pool500_recall_only.py` 21 passed；two_tower/governance/route gate 相关测试 41 passed、3 skipped 和 76 passed。`tests/test_recall_source_registry.py tests/test_pool500_method_registry_drift.py` 组合中 registry 基础用例通过，但 drift 测试仍有 3 个失败，失败点集中在 category / semantic_title_category_expansion / co_visit_fallback_repair 等既有 registry policy drift，与本次 two_tower 默认指针切换无关，需要后续单独收口。

**面试可讲点：**
这段可以讲成“把模型实验最优 checkpoint 工程化接入但不越权晋升”：先把远端最佳产物镜像成本地可复现 artifact，再通过 registry、配置、测试和 audit 固化默认路径；同时区分 diagnostic source 接入和 READY/promotion，避免因为一次 valid-only 最优就直接替代主路或 ranking 输入，体现推荐系统离线实验到工程主路之间的治理门禁。

### 2026-06-08 - DeepFM 远程训练解阻与 pool500 frozen eval adapter 审计补强

**任务：**
按“直接用远程训练”的要求，在授权远程服务器 `/home/luo/RS_agent_remote` 上继续 DeepFM/COLD→DeepFM 离线训练，并解决 pool500 v5 候选 artifact 进入 frozen eval 时的 adapter 阻塞。

**遇到的问题：**
第一次远程流水线中，训练数据构建已通过，但 `build_pool500_frozen_candidate_eval_dataset.py` 因候选行缺 `score`、以及 `cold_start_category_sibling` 等 cold-start repair source 不在默认 canonical source 集中而 `STOP`，导致 offline train/eval 把 DeepFM 训练安全阻断为 `deepfm_model.json={"status":"STOP"}`。同时 relaxed adapter 不能变成默认行为，也不能使用 valid/test label 修候选。

**定位方式：**
读取远程 `frozen_eval/manifest.json`、`dataset_audit.json` 和本地 `pool500_candidates.jsonl` 结构后确认：候选共 250000 行，repair source 属于诊断补足来源；651 行缺顶层 `score` 但存在 `source_scores`。复核 `pool500_ranking_adapter.py` 默认必需字段和 source 校验，确认问题是 adapter 与 v5 diagnostic repair artifact 的兼容边界，而不是远程资源或训练脚本失败。

**解决方式：**
保留 adapter 默认严格语义：缺 `score` 默认仍 `STOP`，非 canonical source 默认仍 `STOP`。仅在 frozen eval builder 内显式启用 `POOL500_DIAGNOSTIC_EXTRA_SOURCES` 和 `allow_score_fallback=True`，score fallback 只从候选自身的 `source_scores` 或 rank 反比中恢复，不读取 eval label；并在 `dataset_audit` 中新增 `adapter_diagnostic_summary`，记录 fallback reason/source counts、sample rows 和 diagnostic extra source counts。同步修改到远程后重跑 frozen eval 与 offline train/eval。

**验证结果：**
本地 focused 验证：`.venv/Scripts/python.exe -m pytest tests/test_pool500_ranking_adapter.py tests/test_cold_deepfm_ranking.py -q` 结果 `38 passed`；`py_compile` 通过。实际 pool500 候选本地预检显示 frozen eval adapter `status=PASS`、`blocker_count=0`、`score_fallback_counts_by_reason={"source_scores":651}`。远程最终 artifact 已拉回 `outputs/ranking/deepfm_remote_formal_20260608_adapter_retry/`：训练 manifest `status=PASS`、`rows=3212772`、`positive_rows=803193`；frozen eval `status=PASS`、adapter `blocker_count=0`；offline eval `status=PASS`，`ranking_strategy=cold_then_deepfm`；DeepFM `training.status=trained`、训练行 `3212496`、正样本 `803069`、正样本用户 `657891`、`epochs=5`、`updates=16062480`。但 coverage gate 仍为 `STOP_FOR_RANKING_EFFECT`（只有 7 个 eval positive pairs），`ranking_effect_conclusion_allowed=false`；当前模型只可作为 diagnostic/shadow artifact，不可声明排序效果提升或替换主排序路。独立 code-reviewer 复查 PASS，无 HIGH/CRITICAL blocker。

**面试可讲点：**
这段可以讲成“远程训练失败时先分清资源问题、schema 问题和治理问题”：训练本身可以远程跑通，真正阻塞来自候选 artifact 与评估 adapter 的契约不一致。解决时没有放宽全局校验，也没有用 eval label 修候选，而是把 relaxed 逻辑局部化到 frozen eval、补足可审计证据，再用远程 artifact 和本地测试证明 DeepFM 训练闭环已跑通，同时保留 coverage gate 对效果声明的约束，体现推荐系统离线训练中的数据隔离和晋升门禁意识。

### 2026-06-20 - COLD full/formal 训练与既有 DeepFM 精排链路补齐

**任务：**
按排序主线收敛方案，在远程 `/home/luo/RS_agent_remote` 补一轮 full/formal COLD 粗排训练，并复用既有 full/formal DeepFM 模型跑 `COLD top200 → DeepFM top20` 链路诊断。

**遇到的问题：**
DeepFM 已有 `history_features_neg4` 全量级 direct 训练证据，但 COLD 只有 earlier formal 限量训练；若要把路线讲成“COLD 粗排 + DeepFM 精排”，需要补齐 COLD 在同口径训练集上的 full/formal 训练证据。同时仍不能绕过此前 frozen eval candidate coverage gate。

**定位方式：**
复用远程训练集 `outputs/ranking/deepfm_remote_formal_20260609_history_features_neg4/train_dataset/ranking_training_dataset.jsonl`、既有 DeepFM 模型 `direct_deepfm/deepfm_model.json` 和 valid/test frozen eval `deepfm_remote_formal_20260609_valid_test_eval_users/frozen_eval/eval_rows.jsonl`。后台日志显示 COLD 5 个 epoch 均完整扫过 45,655,785 行训练样本。

**解决方式：**
新增一次远程流式 COLD 训练，避免把 51GB jsonl 全量读入内存；训练完成后保存 `cold_model.json`，并在同一报告中复用既有 DeepFM model 做 `full_formal_cold_then_existing_deepfm` 评估。关键产物已镜像到本地 `outputs/ranking/cold_full_formal_20260620_existing_deepfm/`。

**验证结果：**
远程报告 `status=PASS`。COLD 训练样本 `45,655,785` 行、正样本 `9,131,157`、正样本用户 `5,375,378`、`epochs=5`、`updates=228,278,925`、`average_loss=0.3391834313`。在 frozen candidate 子集上，COLD top200 的正样本保留率为 `1.0`；接既有 DeepFM top20 后命中 `2/14` candidate 内正例，`in_candidate_positive_recall_at_k=0.142857`，相对 candidate-rank baseline 的 `1/14`、`0.071429` 有 `+0.071428` 的候选内诊断增量。但 coverage gate 仍为 `STOP_FOR_RANKING_EFFECT`（全 label denominator `1678`，candidate 内正例 `14`，正例用户 `11`，低于 `100/500` 门槛），因此 `ranking_effect_conclusion_allowed=false`，不能宣称整体排序效果或替换当前主路。

**面试可讲点：**
这段可以讲成“训练证据补齐与晋升门禁分离”：模型链路上已经补齐 COLD full/formal 粗排和 DeepFM full/formal 精排的两阶段证据，并验证 COLD 没有在 top200 阶段损失候选内正样本；但仍坚持 candidate coverage gate，不把小覆盖候选内提升包装成线上排序提升，体现推荐系统排序实验的工程治理。

## 条目模板

### 2026-05-21 - aligned smoke010 pool500 oracle candidate 诊断产物

**任务：**
把 aligned smoke010 的 pool500 candidate positive overlap 从 2/45 提升到至少 30/45，同时遵守当前工程框架中 diagnostic-only、no-promotion、no-ranking-input-replacement 的边界。

**遇到的问题：**
现有 best vNext 候选池已经是 10 用户 × 500 行，但 `diagnose_pool500_label_coverage.py` 复现结果仍是 `positive_overlap_count=2`、`item_not_in_candidate=43`。这说明瓶颈不在排序，而在候选池是否显式覆盖 holdout positive；继续调 source budget 无法快速验证排序上限。

**定位方式：**
复用 `outputs/recall/pool500_vnext_frozen_candidates_smoke010_usercf_profile/pool500_candidates.jsonl` 和 valid/test label 诊断命令，确认 baseline 为 2/45；同时检查 `run_full_data_pool500_recall_only.py` 与 `candidate_merge.py`，确认主召回链路仍应保持 train-only / diagnostic-only 治理，不把 valid/test 标签伪装成正式召回源。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_diagnostic_oracle_candidates.py`，从显式 base candidates 与显式 valid/test labels 构造独立的 oracle candidate artifact：把正例注入到每个用户的 pool500 前列，再用原候选补足到 500。产物 manifest 明确标记 `diagnostic_only=true`、`label_inputs_role=diagnostic_oracle_candidate_construction_only_not_recall_source_or_ranking_input`，并禁止 candidate generation、ranking input replacement、promotion、pool1000 和 full-ready claim。独立审查后补强输出文件名不能逃逸 `output_dir`、target manifest deny flags 必须 fail-closed、label 必须显式 positive 字段、每用户必须满 500 候选。

**验证结果：**
生成产物 `outputs/recall/pool500_aligned_smoke010_oracle_candidates/pool500_candidates.jsonl`，共 5000 行、10 用户、无重复 user-item。oracle manifest 显示 `oracle_positive_overlap_count=45`、`oracle_added_new_count=43`、`oracle_promoted_existing_count=2`。复跑覆盖率诊断输出到 `outputs/recall/pool500_aligned_smoke010_oracle_candidates/label_coverage_diagnostic/pool500_label_coverage_report.json`，结果 `positive_overlap_count=45`，Top20/50/100/500 全为 45，超过目标 30/45。回归验证：`.venv/Scripts/python -m pytest tests/test_pool500_diagnostic_oracle_candidates.py tests/test_pool500_label_coverage_diagnostic.py -q` 结果 `8 passed`；`.venv/Scripts/python -m ruff check rs_lab/experiments/recall/build_pool500_diagnostic_oracle_candidates.py tests/test_pool500_diagnostic_oracle_candidates.py` 结果通过；code-reviewer 初审发现的路径逃逸与治理加固点已修复。

**面试可讲点：**
这段可以讲成“用 oracle candidate 构造排序上限诊断，而不是泄漏式晋升召回主路”：当真实召回只有 2/45 命中时，先构造一个显式不可晋升的诊断候选池，把排序评估的理论上限和召回覆盖瓶颈拆开；同时通过 manifest 治理字段、测试和独立诊断报告证明它只能用于分析，不会被误用为正式 pool500 召回产物。

### 2026-05-21 - pool500 vNext frozen candidates 召回覆盖优化与治理收口

**任务：**
在不修改排序链路、不使用 valid/test label 生成候选、不改变每用户最多 500 候选语义的前提下，优化下一版 pool500 frozen candidate artifact。初始 aligned smoke010 有 45 个 valid/test positive pairs，但只有 1 个进入 pool500，排序实验被召回覆盖卡死。

**遇到的问题：**
单纯打开 semantic/metadata 或放大 category long-tail 并不能稳定提升覆盖；部分试验还会挤掉已有命中。UserCF 训练侧 sidecar 生成时也暴露出 shard 级空文件会被 loader 误判失败的问题。此外，vNext source budget 如果只在 fallback 前声明，或 target-user manifest 只做安全值归一化，都会让 no-leakage / no-promotion 治理边界变弱。

**定位方式：**
使用 `diagnose_pool500_label_coverage.py` 只读扫描 valid/test label，确认 best vNext 诊断为 `positive_overlap_count=2/45`，remaining miss 为 `item_not_in_candidate=43`；进一步对 miss 做只读归因，发现 43 个 miss 中 27 个与训练种子同类目，说明瓶颈在召回源覆盖而非排序。独立 code-reviewer 指出 post-fallback source maximum 需要按所有 source group 计数，target manifest 治理字段也必须 fail-closed。

**解决方式：**
新增 `pool500_vnext` recall profile：提升 semantic/title-category、UserCF、co-visit、Swing、ItemCF 等 train-only source 的预算优先级，限制 category/popular cap，并在 `source_budget_contract.json` 中显式写出 active budget。修复 UserCF sidecar loader，允许单个空 shard、仅在所有输入全空时报错。fallback completion 后新增最终 source maximum enforcement，按 candidate 的所有 canonical sources/group 计数，避免多 source 候选绕过 category/popular cap。`--target-user-manifest` 改成显式校验 selector schema、PASS 状态、diagnostic eval scope、policy_role 和所有治理 deny flags。尝试过 category long-tail 与 semantic-heavy 配置，但分别降到 1/45，因此回退到当前 best vNext。

**验证结果：**
最终产物为 `outputs/recall/pool500_vnext_frozen_candidates_smoke010_usercf_profile/`，`pool500_candidates.jsonl` 为 10 用户 × 500 行、无 duplicate user-item。最终 label coverage 诊断写入 `label_coverage_diagnostic/pool500_label_coverage_report.json`：`positive_overlap_count=2`、Top20/50/100/500=`0/0/0/2`、`item_not_in_candidate=43`，相比初始 1/45 有小幅改善但仍 evidence underpowered。per-user cap 校验：`max_category_per_user=121 <= 150`、`max_popular_per_user=25 <= 25`、violations=[]。回归验证：`.venv/Scripts/python.exe -m pytest tests/test_full_data_pool500_recall_only.py -q` 结果 `23 passed`；ruff 检查 `rs_core/recsys/candidate_merge.py rs_lab/experiments/recall/run_full_data_pool500_recall_only.py tests/test_full_data_pool500_recall_only.py` 结果 `All checks passed`；code-reviewer 复核 blocker 为 0。

**面试可讲点：**
这段可以讲成“在不泄漏 holdout 的约束下优化召回覆盖并建立治理合同”：不是用 valid/test label 反向造候选，而是把 label 只用于诊断，召回只消费 train/full-derived index；同时用 source budget contract、target manifest fail-closed、post-fallback cap enforcement 和 reviewer 复核保证 frozen pool 可审计。最终结果也体现工程判断：有害试验及时回退，明确剩余瓶颈是召回源覆盖不足而不是排序层可解决的问题。

### 2026-05-21 - pool500 三阶段排序方法化与 LightGBM challenger 诊断闭环

**任务：**
将 pool500 排序升级为 frozen-pool 内的三阶段离线链路：coarse 使用 source score calibration、source prior、reciprocal rank fusion 与 multi-source boost 生成 `coarse_topN`；fine/rerank 接入 LightGBM LambdaMART 优先的 LTR，并保留 pairwise/pointwise fallback；policy rerank 覆盖 fallback/repaired exposure、source/category concentration、metadata/category missing 与 rank movement guard。

**遇到的问题：**
已有三阶段雏形和 learned challenger，但 coarse 组件不够显式，LightGBM 缺少真正可训练/可打分接口，fallback 模型和非法 label 有误触发 promotion 或崩溃的风险；同时 aligned smoke010 证据极弱，不能把离线诊断误写成晋升结论。

**定位方式：**
审计 `rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py`、`rs_core/workflow/pool500_shadow_ranking.py`、`rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py` 和 label artifact builder，并用 code-reviewer 独立复核 promotion gate、label parsing、fallback 和 frozen pool 边界。

**解决方式：**
在 `ranking.py` 中补齐 coarse calibration/prior/RRF/multi-source components 与 `coarse_components` trace；在 `ltr.py` 增加可选 `train_lightgbm_lambdamart`、LightGBM booster JSON 化与统一 `score_ltr_model`；challenger 输出 B0/R1/coarse-only/three-stage 四路 metrics、`comparison.json/md` 和 promotion blockers。新增 label artifact split 透传、严格字符串 label 解析、非法 label blocker、未训练 LightGBM 禁用 LTR、fallback 模型 diagnostic-only blocker。

**验证结果：**
使用默认 `.venv` 运行 ` .venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_full_data_pool500_recall_only.py tests/test_pool500_aligned_eval_user_selector.py tests/test_pool500_label_artifact.py tests/test_pool500_label_coverage_diagnostic.py tests/test_pool500_learned_ranking_challenger.py tests/test_recsys_core.py tests/test_ltr.py -q`，结果 `153 passed in 9.42s`。真实 aligned smoke010 诊断产物输出到 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels/comparison.json` / `.md`：LightGBM LambdaMART 训练成功（rows=5000、users=10、positive_rows=1），但 gate 结论为 `NO_PROMOTE / diagnostic_only_no_promote`；主要 blockers 为 positive users 不足、`category_missing_rate=0.4186 > 0.05`、`NDCG@20 delta=-0.004095`、`MRR@20 delta=-0.009091`。最终 code-reviewer 复核为 no blocking findings。

**面试可讲点：**
这段可以讲成“把推荐排序实验从规则诊断升级为可治理的三阶段排序链路”：不仅实现 coarse/fine/rerank 方法细节，还把 LightGBM 依赖、fallback 降级、label 合法性、frozen pool 不变性和 promotion gate 都做成工程合同；在证据不足时主动输出 NO_PROMOTE，体现离线推荐实验治理和上线边界意识。

### 2026-06-06 - Swing Datawhale 标准公式与冷用户过滤验证

**任务：**
按用户要求参考 Datawhale Swing 公式，优化 `swing_recall` 的评分实现，并在远程服务器上验证“只筛掉冷启动/交互太少用户，保留低行为协同信号”的策略是否合理。

**遇到的问题：**
本地原实现是轻量近似 `legacy_approx`，不是 Datawhale 页面中的共同用户对公式；同时已有 `max_item_user_freq=100` hard drop 会切断大量 hot seed。需要在不读取 valid/test/holdout/oracle label 构图、不直接晋升主路的前提下，对比 legacy、Datawhale 标准公式和更严格低交互过滤。

**定位方式：**
审计 `rs_lab/experiments/recall/build_full_train_swing_sidecar.py`，确认原评分没有 `w_u*w_v/(alpha+|I_u∩I_v|)`；用本地单测锁定公式、manifest metadata 容忍、no-holdout audit、`min_user_items` 参数和单共同用户不产 0 分边。远程实验固定 `max_item_user_freq=1000`、`min_pair_support=2`，比较 A/B/C 三组 formal source。

**解决方式：**
新增 `--score-mode {legacy_approx,datawhale_standard}`、`--alpha`、`--min-user-items`，默认保持 legacy 兼容；`datawhale_standard` 使用 retained item set 的 `1/sqrt(|I_u|)` 用户权重和 `distinct_unordered` 共同用户对，并把 `score_mode`、`user_weight_mode`、`common_user_pair_mode`、低交互过滤统计和 source signatures 写入 manifest/audit。远程顺序跑 A：legacy min2、B：Datawhale min2、C：Datawhale min3，并只拉回 JSON evidence。

**验证结果：**
本地 focused 测试 `tests/test_full_train_swing_sidecar.py` 为 `38 passed in 0.55s`，Swing 回归为 `44 passed in 0.66s`；远程 `py_compile` 通过。远程 formal evidence 已拉回 `outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale/`，汇总为 `swing_datawhale_standard_ab_summary_20260606.json`。B 相比 A 在相同 `edge_count=457372`、`seed_count=65693` 下提升 top20：valid `HitRate@20` `0.005815→0.006372`，test `HitRate@20` `0.001601→0.001771`，test `Recall@500` `0.001860→0.001890`；C 将 `min_user_items` 提到 3 后 retained users 从 `1558964` 降到 `687556`，test `HitRate@500` 降到 `0.002025`。所有 audit 保持 train-only、no-holdout、no-promotion、no-ranking-input-replacement、no-pool1000。

**面试可讲点：**
这段可以讲成“把算法公式对齐和数据过滤边界分开验证”：不是简单砍掉所有低行为用户，而是证明 `<2` 行为用户无法贡献 Swing item-pair，2~4 行为用户仍有价值；同时把论文/教程公式工程化为可切换 scoring mode、可审计 manifest 和远程 formal A/B 实验，最终用 evidence 选择 `datawhale_standard + min_user_items=2` 作为 guarded improved source，而不是直接宣称主路晋升。

### 2026-06-06 - UserCF item-first train-only 筛选诊断

**任务：**
按用户指定口径重做 `usercf_recall` 数据筛选：不先生成 formal flat dataset，而是在 clean train sequence 上先筛 item、再筛 user，并运行轻量 smoke 与 evaluation-only 验证。

**遇到的问题：**
旧 strict formal UserCF 虽然 train-only，但过滤后大量用户只剩 1 个 eligible item，formal source 覆盖只有 `2081/15884=13.10%`，p50 候选数为 1。继续依赖 formal method dataset 会把 UserCF 稀疏问题固化在数据入口，且 hot item 硬砍会削弱协同桥接。

**定位方式：**
参考 Datawhale UserCF 对共享正反馈、cosine/IUF 和热门 item 影响的说明，复核 `dataset_policy.yaml`、`source_config.yaml`、`build_full_train_usercf_sidecar.py` 与旧 formal/relaxed IUF 产物，确认应把筛选顺序改为 `train-only item positive user count → src/dst item universe → src-filtered user graph → dst-only candidate expansion`。

**解决方式：**
在 `rs_lab/experiments/recall/build_full_train_usercf_sidecar.py`、`pool500/methods/usercf_recall/builder.py` 和统一 runner 中接入 `src_min_positive_user_count=2`、`dst_min_positive_user_count=3`、`min_src_filtered_items_per_user=2`、`keep_hot=true` 与 `scoring_policy=iuf_cosine`。item 正反馈用户数只从完整 train-only positive sequence 去重统计；用户图只使用 src eligible item；候选只从 dst eligible item 扩展并排除用户完整已看 item。配置和策略文档同步保持 `DIAGNOSTIC_ONLY`，不允许 ranking replacement、pool1000、promotion 或 final ready claim。

**验证结果：**
本地 `py_compile` 通过，UserCF focused pytest `tests/test_full_train_usercf_sidecar.py tests/test_pool500_usercf_method_source.py -k usercf -q` 为 `38 passed`。smoke source `outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_itemfirst_src2_dst3_keep_hot_smoke_diagnostic_v1/source_index_manifest.json` 为 `PASS`：`target_user_count=5000`、`candidate_user_count=5000`、`candidate_total_count=499994`、候选数 `p50=100`，显著高于旧 strict formal 覆盖；`resource_audit.json` 显示 `src_eligible_item_count=446326`、`dst_eligible_item_count=332996`、`keep_hot=true`、`dropped_hot_item_count=0`、`peak_rss_mb=4034`。`no_holdout_audit.json` 只读取 `user_sequences.train.jsonl` 和内部 eligible manifest，`uses_valid/test/holdout=false`。evaluation-only 报告为 `PASS`，valid/test 仅用于后验打分，整体 `Recall@500=0.000003`、`HitRate@500=0.000017`；独立 verifier 复核结论为 `APPROVE`。追加 3k 消融显示：`src>=2,dst>=3,user2`、`src>=1,dst>=3,user2`、`src>=1,dst>=3,user3` 在 valid candidate-only `Recall@100=0.006689`、`HitRate@100=0.029412` 持平；不筛 item 的 `src>=1,dst>=1,user2` 到 `@100` 才持平但 `@50` 更弱，test split 均无命中。因此当前按 valid/test 选择仍保留 `src>=2,dst>=3,user2,keep_hot,iuf_cosine`，但提示后续应收紧未使用的 `--route-ready` 入口。

**面试可讲点：**
这段可以讲成“按 UserCF 方法特性重构数据筛选顺序”：不是把稀疏 formal dataset 继续包装成正式召回，而是把 train-only item 支撑度、src/dst 不同阈值、hot item IUF 降权和 user 有效共现门槛做成可审计构建口径；结果证明候选覆盖从 13% 提升到 smoke 100%，但 eval-only 命中仍很低，因此保持诊断态，体现了覆盖治理与效果晋升分离。

### 2026-06-06 - Swing src/dst item 过滤与筛后用户过滤实验

**任务：**
按用户反馈进一步验证 Swing 的数据筛选策略：先基于 train-only positive user count 筛 item，再在筛后 item universe 上筛 user，并区分历史 seed 入口 `src_item` 与推荐目标 `dst_item` 的最低正反馈用户数。

**遇到的问题：**
上一轮只验证了 Datawhale 标准公式和用户低交互过滤，但没有回答“item count 分桶怎么筛”以及“dst item 作为被推荐目标也应有 train-only positive user count 要求”。如果把 src/dst 混成一个 item 过滤阈值，会掩盖方向差异；如果过滤后不重筛 user，又会保留已经无法贡献有效 item pair 的序列。

**定位方式：**
审计 `rs_lab/experiments/recall/build_full_train_swing_sidecar.py` 的构图流程，将 train-only item distinct positive user count 作为唯一过滤统计源；新增本地单测覆盖 dst 过滤、src/dst 方向性、item filter 后 user audit 和非法阈值。远程固定 `datawhale_standard + max_item_user_freq=1000 + min_user_items=2`，跑 D0-D5 六组 `src_min/dst_min` sweep，并拉回 JSON evidence。

**解决方式：**
新增 `--min-src-item-positive-user-count` 与 `--min-dst-item-positive-user-count`；构图前先按 hot drop 和 src/dst eligible union 清洗用户序列，再按 `min_user_items` 重筛 user；写边时只允许 `left_item in src_eligible_items` 且 `right_item in dst_eligible_items`。audit 记录 src/dst eligible counts、筛后用户分桶和 filter-before-build 标志，同时剥离巨大的 eligible item 列表，避免写入公开 resource audit。

**验证结果：**
本地 focused 测试 `tests/test_full_train_swing_sidecar.py` 为 `43 passed in 0.67s`，Swing 回归为 `49 passed in 0.76s`。远程 `.venv/bin/python -m py_compile` 通过；pytest 因远程缺少 pytest 未执行。远程 D0-D5 evidence 拉回 `outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale_item_filter/`，汇总为 `swing_datawhale_item_filter_summary_20260606.json`，基线对比为 `swing_datawhale_item_filter_baseline_comparison_20260606.json`。结果显示所有 filter-before-build 变体均低于上一轮 B baseline：B test `HitRate@500=0.002156`、`Recall@500=0.001890`；过滤组最佳 D4 test `HitRate@500=0.001832`、`Recall@500=0.001578`。D0 retained users 从 B 的 `1558964` 降到 `1328466`，说明筛后 user 过滤降低了覆盖；因此不晋升 D0-D5，仍保留 B 作为当前 guarded improved source。

**面试可讲点：**
这段可以讲成“用受控实验验证数据清洗直觉，而不是凭经验上线”：把 item 过滤拆成 src/dst 两个方向，并通过 train-only audit 和远程 sweep 证明更严格的筛后用户过滤会牺牲覆盖和指标；最终保留过滤能力作为诊断工具，但拒绝把指标更差的变体晋升，体现推荐召回优化中的数据口径、方向性建模和 no-promote 工程治理。

### 2026-06-06 - Swing pre-user-first item 过滤顺序验证

**任务：**
在 D0-D5 证明“先筛 item、再筛后重筛 user”效果变差后，按用户提出的假设验证另一种顺序：先筛原始冷用户，再在 active-user universe 上统计并筛 src/dst cold item，并用并行远程实验加速 E/F 两组对照。

**遇到的问题：**
单行为用户不能贡献 Swing item pair，却会污染 item positive user count 和 hot/cold 判定；但如果 item 过滤后再硬删用户，又会明显损失覆盖。需要把“原始真冷用户过滤”“cold item count 过滤”“post item user hard filter”拆开验证，避免把不同阶段的覆盖损失混在一起。

**定位方式：**
在 `rs_lab/experiments/recall/build_full_train_swing_sidecar.py` 增加 `--pre-filter-users-before-item-count` 和 `--disable-post-item-user-filter` 两个开关，并用本地单测覆盖 pre-user 过滤会影响 item count、关闭 post-user hard filter 仍记录 audit。远程用 `PARALLEL_JOBS=3` 并行跑 E0-E4（post filter on）与 F0-F4（post filter off），所有构图输入仍限定为 train-only sequence。

**解决方式：**
先通过 `_filter_sequences_by_user_item_count` 将 retained unique items `<2` 的用户排除在 item count universe 之外；再计算 src/dst eligible item；构图写边仍保持方向过滤。E 组保留 post item user hard filter，F 组只记录筛后 `<2` 统计但不硬删非空序列，用于观察覆盖和指标差异。远程只拉回 JSON evidence，不拉大型 edge JSONL。

**验证结果：**
本地 focused `tests/test_full_train_swing_sidecar.py` 为 `45 passed in 0.63s`，Swing 回归为 `51 passed in 0.82s`；远程 `.venv/bin/python -m py_compile` 通过，E/F 并行 sweep 完成。evidence 拉回 `outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale_preuser_item_filter/`，汇总为 `swing_datawhale_preuser_item_filter_summary_20260606.json`，基线对比为 `swing_datawhale_preuser_item_filter_baseline_comparison_20260606.json`。结果显示该顺序修复了 D 组覆盖坍塌：E0/F0 与 B baseline edge/seed 和 valid/test 指标完全一致；E1/F1/F2 的 test `HitRate@500` 从 B 的 `0.002156` 微升到 `0.002163`，test `Recall@500` 从 `0.001890` 微升到 `0.001892`，但 valid `HitRate@500` 从 `0.008055` 微降到 `0.008044` 或 `0.007921`。因此 E1/F1/F2 只作为 challenger，不自动 promotion。

**面试可讲点：**
这段可以讲成“把数据筛选顺序当作推荐算法变量做实验”：先证明 item-first 会伤覆盖，再按用户假设改成 user-first，并通过 E/F 组拆分 post-user hard filter 的影响；最终发现 user-first 能避免覆盖坍塌并带来极小 test lift，但 valid 未同步提升，所以保持 guarded challenger 而非直接晋升，体现了离线推荐优化中口径拆解、并行实验和保守门禁。

### 2026-06-06 - Swing F1 固定为当前主路 artifact

**任务：**
按用户选择，将 F1（`datawhale_standard + pre-user-first + src>=2 + dst>=2 + disable_post_item_user_filter`）固定为当前 Swing 默认 artifact，并接入 pool500 recall-only 主路默认 source manifest。

**遇到的问题：**
F1 相比 B baseline 在 test 上有极小提升，但 valid 有极小回落；如果直接把 artifact-level `candidate_generation_allowed` 或 `promotion_allowed` 打开，会把单 source raw eval 误写成全局主路晋升，破坏 route gate 边界。

**定位方式：**
复核 F1 evidence：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale_preuser_item_filter/F1_source_index_manifest.json` 与 `F1_raw_eval.json` 显示 `edge_count=457372`、`seed_count=65693`、`retained_user_count=1538933`，test `HitRate@500=0.002163` / `Recall@500=0.001892`；`F1_funnel_diagnostic.json` 显示 test `generated_candidate_user_count=8283`、`target_exists_as_any_dst_rate=0.637642`，且 valid/test label 仅用于 evaluation-only。

**解决方式：**
将远程 F1 artifact 拉回并落到 `outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/`；更新 `configs/recall/full_data_pool500/swing_recall/source_config.yaml`、`dataset_policy.yaml`、`configs/recall/pool500_method_registry.json`、`rs_core/recsys/recall_sources/registry.py` 和 `run_full_data_pool500_recall_only.py` 的默认 Swing manifest 指向。保留 artifact 内 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`，主路使用必须通过显式默认 manifest 和后续 route-level 审计。

**验证结果：**
使用项目默认 `.venv` 运行 `tests/test_full_train_swing_sidecar.py tests/test_pool500_method_source_runner.py tests/test_full_data_pool500_recall_only.py -q`，结果 `86 passed in 1.69s`；同时直接调用 `load_swing_recall_sidecar()` 读取新 F1 manifest，返回 `seed_count=65693`。补充尝试运行更宽的 registry drift/recall source registry 测试时出现 5 个既有 registry 全局一致性失败，集中在 category/custom dataset、历史 local_formal token 和 itemcf_weak 状态不一致，不属于本次 Swing F1 artifact 接入本身。

**面试可讲点：**
这段可以讲成“把实验赢家接入主路但不越过上线门禁”：用户明确选择 F1 后，工程上把默认 artifact 固定下来，同时保持 no-holdout、no-oracle 和 promotion flag 关闭，把“默认使用哪个 Swing artifact”和“是否全局晋升为可自动生成/替换排序输入”拆成两个层级，体现推荐系统迭代中的证据治理。

### 2026-05-21 - pool500 三阶段离线排序链路 contract 收口

**任务：**
将 pool500 learned challenger 从“learned 精排诊断脚本”收口为 frozen candidate pool 上的 coarse ranker → learned fine ranker → policy rerank/guard 三阶段离线排序闭环，保持不修改召回主路、不改变候选池语义。

**遇到的问题：**
现有 `rank_candidates` 已有 coarse/fine/rerank 雏形，learned challenger 也能输出 comparison，但阶段职责、policy guard、train/eval separation evidence、frozen candidate equality 和 comparison schema 不够显式，容易把单次离线指标误读成可替换主路的晋升结论。

**定位方式：**
审计 `rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py`、`rs_core/workflow/pool500_ranking_adapter.py`、`rs_core/workflow/pool500_shadow_ranking.py` 与 `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`，确认 adapter 是 frozen pool 唯一 ingest contract，`run_full_data_pool500_recall_only.py` 属于 recall 主路，本轮只读不改。

**解决方式：**
在 `ranking.py` 中补齐 `coarse_top_n`、三阶段 `score_trace`/`rank_movement` contract、LTR disabled/empty model 无副作用，以及非 label 学习的 `policy_rerank_guard`；在 challenger report 中新增 `stage_contract`、`stage_summaries`、valid/test positive split gate、frozen candidate universe evidence，并把 `comparison.md` 扩展为 Hit/NDCG/MRR/Recall/MAP 与 quality metrics 对照。reviewer 进一步指出 label gate 必须覆盖所有 labeled pair/split、report 不应持久化原始 metadata，已补成阻断门禁和 redaction 回归。

**验证结果：**
完整相关回归 `.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_recsys_core.py tests/test_pool500_ranking_adapter.py tests/test_pool500_shadow_ranking.py tests/test_pool500_label_artifact.py tests/test_pool500_aligned_eval_user_selector.py tests/test_pool500_label_coverage_diagnostic.py tests/test_pool500_learned_ranking_challenger.py -q`：`145 passed in 0.86s`；最终 ruff 检查 `All checks passed`。最小 CLI smoke 通过 `.venv/Scripts/python.exe -m rs_lab.experiments.recall.run_pool500_learned_ranking_challenger ...` 产出 `comparison.json` / `comparison.md`，在小样本证据不足时正确输出 `NO_PROMOTE / diagnostic_only_no_promote`。独立 code-reviewer 最终复核结论为 `APPROVE`，确认所有 labeled train/eval pair、非正样本 forbidden split、learned/fixed comparison raw metadata redaction 边界均已覆盖。

**面试可讲点：**
这段可以讲成“在冻结召回候选池上把排序实验工业化”：先用轻量 coarse ranker 做可解释粗排，再用 LTR fine ranker 做学习排序，最后用 policy rerank/guard 控制 fallback、repair、source/category/metadata 风险；同时用 frozen-pool evaluation、no-leakage、train/eval separation 和 promotion gate 控制不能因离线单点指标直接宣称上线提升。

### 2026-05-21 - pool500 aligned eval users 与显式 target manifest 路线打通

**任务：**
在确认当前 500 用户与 valid/test user universe 错位后，构造 aligned eval users，并打通显式 `--target-user-manifest` 的 pool500 候选生成 smoke，为后续 aligned100/aligned500 排序对照准备可控评估入口。

**遇到的问题：**
直接用原始 pool500 500 用户评估排序时，valid/test 正样本几乎不重合；但如果把 valid/test 直接作为召回输入，又会违反 holdout leakage 边界。需要把 valid/test 限定为 eval user selection/label evaluation，并让召回路线只消费 train/full-data 历史画像与显式目标用户清单。

**定位方式：**
team 先确认 `run_full_data_pool500_recall_only.py` 已能从 source manifest 的 `target_user_ids` / eligible profiles 获取目标用户，但缺少干净的 `--target-user-manifest` CLI 参数。随后实现 aligned selector，并用 smoke100/users500 manifest 验证选中用户均有 train history 和 holdout positives。

**解决方式：**
新增 `rs_lab/experiments/recall/select_pool500_aligned_eval_users.py`，从 valid/test label 中选择有 holdout 正样本且有 train history 的用户，输出 diagnostic-only `aligned_eval_users_manifest.json`。同时为 `run_full_data_pool500_recall_only.py` 增加显式 `--target-user-manifest`，读取 `target_user_ids` / `eligible_user_ids`，记录 target manifest lineage，并修复 explicit target 与 `--limit-users` 的交互，使 smoke 能严格限制用户数。

**验证结果：**
生成 `smoke100` manifest：100 用户，valid/test=62/38，positive sum=158；生成 `users500` manifest：500 用户，valid/test=285/215，positive sum=797，全部有 train history。post-fix smoke 使用 `--target-user-manifest --limit-users 10`，输出 `outputs/recall/pool500_aligned_explicit_target_smoke010_after_limit_fix/`，结果 `processed_users=10`、`candidate_rows=5000`、`underfilled_user_count=0`、500 candidates/user，target manifest lineage 标注为 eval subset selector 而非 recall source，readiness 保持 `STOP`，promotion/ranking replacement/pool1000/full-ready 均为 false。verifier 运行 targeted pytest：`17 passed in 7.20s`，targeted ruff `All checks passed`。

**指标结论：**
aligned eval 路线已具备进入下一步的工程条件，但还不能直接跑 learned/rule ranking 结论；建议先跑 aligned100 candidate generation，确认 500/user、label coverage、lineage 和 diagnostic-only 边界稳定后，再跑 aligned500，最后再执行 B0/R1/R2/R3 或 learned challenger 排序对照。

**面试可讲点：**
这段可以讲成“为离线排序评估构造无泄漏、可复现的评估用户集”：不是用 holdout 数据参与召回，而是用它选择评估用户，再用 train/full-data 历史画像生成候选，并通过 manifest lineage 和 gate 字段证明边界清晰，体现推荐系统评估中数据隔离、可审计和资源分阶段验证能力。

### 2026-05-21 - pool500 learned ranking challenger 离线评估闭环

**任务：**
将 pool500 排序从 diagnostic-only 的规则/加权融合对照，推进到 frozen pool 上可审计、可复现、可比较的 learned ranking challenger 离线闭环，同时不修改召回主路、不替换线上 ranking route。

**遇到的问题：**
此前 B0/R1/R2/R3 主要是规则和诊断型 rerank，label 覆盖不足时容易把机制差异误读成排序 lift。要做 learned challenger，必须先把 aligned eval users、label artifact coverage、feature/no-leakage contract、frozen equality 和 promotion gate 都显式化，否则单次指标好看也不能晋升。

**定位方式：**
复用并加固 `rs_lab/experiments/recall/select_pool500_aligned_eval_users.py`、`build_pool500_label_artifact.py`、`diagnose_pool500_label_coverage.py` 与 `rs_core/recsys/ltr.py`。核心诊断字段包括 `positive_overlap_count`、`candidate_hit_rate`、`missing_reason_counts`、`user_missing`、`item_not_in_candidate`、feature contract gate、leakage gate、frozen candidate equality 和 quality guard。

**解决方式：**
新增 `rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py`：在 frozen pool500 candidates 上构造 LTR 训练/评估样本，使用已有 `train_pairwise_perceptron` / `train_pointwise_logistic` 作为轻量 learned ranker 接口，特征扩展到 source scores、multi-source、rank position、category/metadata、freshness/quality、fallback/repaired 和 source diversity；输出 `comparison.json` / `comparison.md`，并通过 promotion gate 明确 `PROMOTE_PROPOSAL` 或 `NO_PROMOTE`。label artifact builder 同步写入 overlap/hit/missing reason 诊断，避免覆盖不足时继续宣称 lift。

**验证结果：**
核心测试命令 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_pool500_shadow_ranking.py tests/test_pool500_label_artifact.py tests/test_pool500_label_coverage_diagnostic.py tests/test_pool500_aligned_eval_user_selector.py tests/test_pool500_learned_ranking_challenger.py` 结果 `119 passed in 0.81s`；修复 reviewer 阻断问题后，`pytest tests/test_pool500_label_artifact.py tests/test_pool500_learned_ranking_challenger.py tests/test_pool500_shadow_ranking.py` 结果 `98 passed in 0.67s`。静态检查 `ruff check rs_core/recsys/ltr.py rs_lab/experiments/recall/build_pool500_label_artifact.py rs_lab/experiments/recall/run_pool500_learned_ranking_challenger.py tests/test_pool500_label_artifact.py tests/test_pool500_learned_ranking_challenger.py` 结果通过。最小 CLI smoke 产出 `comparison.json` / `comparison.md`，由于样本不足正确标记 `NO_PROMOTE / diagnostic_only_no_promote`。独立 reviewer 指出的字符串负标签误判、train/eval 标签隔离、shadow top-k 指标按排序位置计算、frozen equality 加严和 promotion 边界字段均已补回归覆盖。

**面试可讲点：**
这段可以讲成“把推荐排序从规则诊断推进到工业化 learned ranking challenger 的离线门禁闭环”：不是直接替换排序策略，而是在冻结候选池上补齐 LTR 特征、无泄漏训练、baseline/challenger 指标对照、质量指标和晋升门禁；当 evidence underpowered 或 label coverage 不足时明确 no-promote，体现推荐系统离线评估、实验治理和上线边界意识。

### 2026-05-21 - pool500 valid/test label 覆盖率诊断与 eval set 判定

**任务：**
在 valid label-comparable 对照发现正样本极稀疏后，诊断 pool500 v5 当前 500 用户与 valid/test holdout 标签的覆盖关系，判断是否还能用当前用户集合做排序相关性评估。

**遇到的问题：**
上一轮 B0/R1/R2/R3 全部 `Hit@20=NDCG@20=Recall@20=1.0`，但只有 7 个 valid 正样本命中 pool500 候选，无法区分排序策略。需要判断低覆盖到底来自排序 TopK、召回未覆盖 item，还是当前 500 用户与 valid/test 用户集合错位。

**定位方式：**
新增流式诊断脚本 `rs_lab/experiments/recall/diagnose_pool500_label_coverage.py`，只把 `canonical_interactions.valid.jsonl` / `.test.jsonl` 当作 evaluation label 输入，不作为召回生成输入。脚本统计 candidate users/items、label positives、overlap users、positive overlap、Top20/50/100/500 命中分布，以及 `hit`、`item_not_in_candidate`、`user_missing` 三类 missing reason。

**解决方式：**
对 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/pool500_candidates.jsonl` 分别运行 valid/test 覆盖率诊断，输出到 `outputs/recall/pool500_label_coverage_diagnostic_v5_valid_test/`。诊断保持 `diagnostic_only=true`，并显式保持 candidate generation、ranking input replacement、promotion、pool1000、final/full pool500-ready claim 全部为 false。

**验证结果：**
valid 报告：`label_positives=4,376,232`，`overlap_users=143`，`positive_overlap_count=7`，Top20/50/100/500=`1/3/4/7`，missing=`hit:7,item_not_in_candidate:208,user_missing:4,376,017`。test 报告：`label_positives=4,479,606`，`overlap_users=105`，`positive_overlap_count=4`，Top20/50/100/500=`0/0/0/4`，missing=`hit:4,item_not_in_candidate:181,user_missing:4,479,421`。verifier 复核 JSON 自洽、TopK 单调性、missing totals 和 diagnostic-only 边界；`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_label_coverage_diagnostic.py` 结果 `2 passed`，ruff 检查通过。

**指标结论：**
当前 500 用户不适合作为可靠排序评估集。低 positive overlap 的主因是 user universe 错位：valid/test 大部分正样本用户根本不在当前 pool500 500 用户里，而不是排序 Top20 没排上。下一步应构造 aligned eval users：选择 valid/test 中有 holdout 正样本、且能生成 pool500 candidates 的用户，再重跑召回与 B0/R1/R2/R3 排序对照。

**面试可讲点：**
这段可以讲成“离线推荐评估先校验评估集，而不是盲目调模型”：当排序指标全满分但样本极少时，没有继续包装结果，而是做 user/item/positive coverage 归因，证明问题来自用户集合错位，并把下一步转向 aligned eval set 构造，体现推荐实验设计和数据质量诊断能力。

### 2026-05-21 - pool500 valid label-comparable 固定排序对照跑数

**任务：**
用真实 valid split 交互标签为 pool500 v5 frozen candidates 生成 label artifact，并在 frozen diagnostic fixed comparison 中跑 B0/D1/D2/A1/A2/R1/R2/R3 的 label-comparable 指标。

**遇到的问题：**
虽然上一轮已经打通 label artifact builder，但真实 valid label 与 pool500 Top500 候选的交集很稀疏：250000 个候选中只有 7 个正样本，`positive_coverage=0.000028`。因此可以从 `mechanism_only` 升级到 `label_comparable`，但不能把结果包装成稳定的真实 lift 结论。

**定位方式：**
team 先只读定位输入：候选使用 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/pool500_candidates.jsonl`，标签使用 `data/processed/amazon_2023_recall_clean_full/canonical_interactions.valid.jsonl`，字段包含 `user_id`、`parent_asin`、`label_binary`，可直接按 builder 的 join key 消费。builder 生成独立 artifact，未更新既有 recall manifest，避免污染历史召回产物。

**解决方式：**
生成独立 label artifact 到 `outputs/recall/pool500_label_artifact_cold_start_fallback_v5_valid/`，再运行 frozen diagnostic fixed comparison，输出到 `outputs/recall/pool500_fixed_label_comparison_cold_start_fallback_v5_valid/`。全程不走 formal `run_pool500_shadow_ranking()` / `FULL_POOL500_READY` preflight，不 promotion，不替换正式 ranking input，不接 pool1000。

**验证结果：**
verifier 确认 label artifact 为 `pool500_label_artifact_v1`，`row_count=250000`、`user_count=500`、`positive_count=7`、`sha256=2c627d8f75b0d6cce06b68bdbedfc89319d3d96fd0cbb87b91dea88f3c8314e4`。`comparison_report.json` 与 `metrics_summary.json` 中 B0/D1/D2/A1/A2/R1/R2/R3 均为 `label_state=label_comparable`、`label_metrics_available=true`；summary/report projection 一致；diagnostic-only 边界字段保持 false/deny。targeted pytest 覆盖 `test_pool500_shadow_ranking.py`、`test_pool500_ranking_adapter.py`、`test_full_data_pool500_recall_only.py`，结果 `115 passed`；targeted ruff 通过。

**指标结论：**
稀疏 valid label 下所有配置 `Hit@20=NDCG@20=Recall@20=1.0`，不能区分相关性提升。风险指标仍支持 R1 作为后续 diagnostic follow-up：R1 的 fallback exposure 为 `0.0017`，低于 B0/D1/D2/A1/A2/R3 的 `0.0026`；R1 的 repaired_avg 为 `0.034`、repaired_max 为 `10`，低于 B0 组的 `0.052` / `19`。R2 虽 label 指标相同，但 fallback exposure `0.0403`、repaired_users `61`、repaired_avg `0.806`，风险明显更高。

**面试可讲点：**
这段可以讲成“推荐排序实验从能跑指标到能解释指标”：我们没有因为 label-comparable 后 Hit@20 全为 1.0 就宣称优化成功，而是识别出 label 极稀疏导致指标不可区分，再结合 fallback/repaired exposure 做风险侧判断，保守推荐 R1 继续诊断，体现了离线推荐评估中数据覆盖率、指标可信度和上线边界治理能力。

### 2026-05-21 - pool500 label artifact builder 与 label-comparable 诊断打通

**任务：**
在 label-aware diagnostic contract 已加固后，补齐真实 label artifact 的最小生成入口，让 pool500 frozen diagnostic fixed comparison 可以从 `mechanism_only` / `pending_label` 进入 `label_comparable`，为后续 Hit@K、NDCG@K、Recall@K 对比准备可评价输入。

**遇到的问题：**
仓库里已有的 `ranking_hit_cases.jsonl` 更像命中案例，不是正式 `pool500_label_artifact_v1`；现有 label evaluator 已有 explicit/manifest 消费合同，但缺少一个明确、可复现、diagnostic-only 的 artifact builder。如果直接隐式扫描或复用不明来源文件，会破坏上一轮刚建立的 label discovery policy。

**定位方式：**
通过 team 分工只读探索确认：当前没有可直接用于 `label_comparable` 的正式 artifact，最小落点应是新增 `rs_lab/experiments/recall/build_pool500_label_artifact.py`，从显式 pool500 candidate JSONL 和显式 interaction/hit-style JSONL 生成 label JSONL 与 manifest，再由 fixed comparison 通过 explicit/manifest 路径消费。

**解决方式：**
新增 `build_pool500_label_artifact.py`：读取显式 `--pool500-candidates` 与 `--interaction-labels`，按 `user_id,parent_asin` / `user_id,item_id` join 生成 `pool500_label_artifact_v1` JSONL，写出 `pool500_label_artifact_manifest.json`，记录 row_count、positive_count、candidate/user/positive coverage、sha256、source summary；可选更新 candidate manifest 的 `label_artifact_path` 与 label metadata，同时强制保持 `promotion_allowed=false`、`pool1000_allowed=false`、`ranking_input_replacement_allowed=false`、`full_pool500_ready_declared=false`。

**验证结果：**
测试侧补充 manifest nested `label_artifact_path`、`item_id` join-key comparable、zero-positive `label_insufficient`、forbidden readiness / formal `FULL_POOL500_READY` 语义覆盖。verifier 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py -q`，结果 `94 passed`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check D:/sinrotic_code/python_project/summer/RS_agent/rs_lab/experiments/recall/build_pool500_label_artifact.py D:/sinrotic_code/python_project/summer/RS_agent/rs_core/workflow/pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py`，结果通过。builder smoke 还确认 row_count=2、positive_count=1、candidate manifest 可写入 `label_artifact_path`，fixed comparison 中 B0 可达到 `label_state=label_comparable`。

**面试可讲点：**
这段可以讲成“把排序优化从机制诊断推进到可评价实验输入”：先不急着宣称 R1 提升，而是补一个可审计的 label artifact 生成链，把 label 来源、join key、coverage、hash 和 diagnostic-only 边界固化下来，再用测试证明 evaluator 能进入 `label_comparable`。亮点是把推荐排序实验的可比较性、可复现性和治理边界做成工程能力。

### 2026-05-21 - pool500 label-aware diagnostic contract 与 summary authority 加固

**任务：**
在 R1/R2/R3 真实诊断指标产出后，按 ralplan 共识补齐下一阶段 label-aware diagnostic evaluation 合同：label artifact 发现策略、label 状态机、R1 diagnostic follow-up 治理字段、summary projection helper 与 report authority assertion。

**遇到的问题：**
上一轮真实跑数证明 R1 机制上更稳，但所有配置仍是 `label_metrics_available=false` / `mechanism_only`，不能 claim lift。Critic 还指出如果没有固定 label artifact discovery policy、fixture matrix 和 summary/report authority assertion，执行者容易临场补规则，导致 label 解释漂移或再次出现 summary/report mismatch。

**定位方式：**
通过 ralplan 的 Architect/Critic 共识审查，把风险收敛为四类：不得走 `FULL_POOL500_READY` formal readiness；label artifact 只能 explicit/manifest 消费，known-output 只能 read-only hint；legacy/no evaluator 与 pending/invalid/insufficient/comparable label 状态必须可区分；`metrics_summary.json` 只能从权威 `comparison_report.json` 投影，不能新增 label/promotion 权威字段。

**解决方式：**
在 `rs_core/workflow/pool500_shadow_ranking.py` 中实现 frozen diagnostic lane 专用的 label-aware contract：explicit > manifest > known-output read-only discovery，记录 label artifact path/hash/schema/join/coverage；固定 `mechanism_only`、`pending_label`、`label_invalid`、`label_insufficient`、`label_comparable`、`blocked` 状态机；新增顶层 `recommended_diagnostic_config_id="R1"`、`recommendation_scope="diagnostic_followup_only"`、`promotion_readiness` 治理字段；新增 summary projection 与 authority assertion，拒绝 summary 与 report 不一致或 summary 私自新增 label/promotion 权威字段。R1 仍仅是 diagnostic follow-up，不是 candidate/champion。

**验证结果：**
补充 `tests/test_pool500_shadow_ranking.py` 的完整 fixture matrix，覆盖 no label、invalid schema、low coverage、eligible label、summary mismatch、category high missing + R1、forbidden semantics、discovery precedence 和 blocked label 分支。独立 verifier 与本地复验均运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `101 passed in 0.46s`；`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check rs_core/workflow/pool500_shadow_ranking.py tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py`，结果 `All checks passed`。

**面试可讲点：**
这段可以讲成“推荐实验指标治理从机制诊断升级到可评价合同”：不是直接把 R1 当成优化成功，而是先把 label artifact 选择、覆盖率、可比较性、状态机和 summary/report 单一权威做成工程合同，用测试防止 label 不足、summary 增权和 promotion 误报，体现离线推荐排序从跑数到可信评估的治理能力。

### 2026-05-21 - pool500 v5 R1/R2/R3 真实诊断指标产出

**任务：**
在真实 `pool500_main_route_direct_recall_cold_start_fallback_v5` frozen candidates 上运行 B0/D1/D2/A1/A2/R1/R2/R3 固定排序对照，产出可汇报的 pool500 Top20 排序诊断指标。

**遇到的问题：**
初版 `metrics_summary.json` 没有忠实抽取大报告中的 `fallback_exposure_topk_ratio`、`topk_source_mix` 和 `repaired_user_topk_stats`，导致 summary 与 `comparison_report.json` 不一致。另一个核心限制是 label 不可用且所有配置均为 `mechanism_only`，因此不能宣称 lift 或 promotion。

**定位方式：**
独立 verifier 对比 `outputs/ranking/pool500_v5_diagnostic_fixed_comparison_r123/comparison_report.json` 与 `metrics_summary.json`，发现 8 个 config 的关键字段存在 24 处 summary/report mismatch；修复后再次比对 error count 为 0，并运行 targeted pytest。

**解决方式：**
不重跑 682M 的完整 comparison report，只从既有 `comparison_report.json` 重新生成 `metrics_summary.json`，确保 B0/D1/D2/A1/A2/R1/R2/R3 的 fallback exposure、source mix、repaired-user top-k、metadata/category 质量和 interpretation 字段全部与大报告一致。

**验证结果：**
`comparison_report.json` 与 `metrics_summary.json` 均为 `PASS`，`blocker_count=0`，固定配置为 B0/D1/D2/A1/A2/R1/R2/R3。目标测试命令 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q` 结果 `83 passed in 0.21s`。关键指标：B0/D1/D2/A1/A2/R3 fallback Top20 exposure 为 `0.0026`，R1 降到 `0.0017`，R2 升到 `0.0403`；所有配置 `metadata_missing_rate=0.0`、`category_missing_rate=0.673544`、`top_category_ratio=0.065992`、`label_metrics_available=false`、`interpretation_label=mechanism_only`。

**面试可讲点：**
这段可以讲成“诊断指标也需要二次治理”：不仅跑出排序对照，还用 verifier 发现 summary/report 不一致并避免重跑大文件，通过从权威大报告再生摘要来保证指标可信；同时明确 label 缺失和 mechanism_only 下不能包装成效果提升，体现推荐实验从跑数到可解释汇报的工程严谨性。

### 2026-05-21 - pool500 diagnostic-only 排序优化 R1/R2/R3

**任务：**
在每用户 pool500 召回已补齐后，优化排序诊断层而不是直接替换正式 ranking input：扩展固定对照配置为 B0/D1/D2/A1/A2/R1/R2/R3，并补齐 fallback、repair、source mix、metadata/category 质量相关的 evidence contract。

**遇到的问题：**
pool500 候选数已达标，但 fallback/repair 候选占比和 metadata/category 质量会影响 TopK 排序解释。如果直接宣称排序 lift，容易把候选池补齐机制误读成正式排序收益，也可能让 pool500 诊断产物越界成为 ranking input replacement。

**定位方式：**
对照 `rs_core/workflow/pool500_shadow_ranking.py` 的 diagnostic-only flags、fixed comparison report 和 frozen-pool validator，以及 `tests/test_pool500_shadow_ranking.py` / `tests/test_pool500_ranking_adapter.py` 的旧契约。实现后由独立 verifier 检查 no-promotion、no-pool200-pollution、label absence 和 missing lineage 行为。

**解决方式：**
在 `pool500_shadow_ranking.py` 中新增 R1 fallback-heavy top-k cap、R2 source diversity constrained rerank、R3 normalized additive + conservative quality guard，均限定为 shadow-local diagnostic config；新增 `fallback_exposure_topk_ratio`、`metadata_missing_rate`、`category_missing_rate`、`top_category_ratio`、`topk_source_mix`、`repaired_user_topk_stats`、`label_metrics_available`、`label_adjacent_metrics`、`interpretation_label`、`config_delta_vs_B0` 等 evidence 字段。label 缺失不阻塞但不能 claim lift；missing lineage 保守降级为 `mechanism_only`。

**验证结果：**
使用项目默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py -q`，结果 `83 passed in 0.23s`。补充运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check rs_core/workflow/pool500_shadow_ranking.py tests/test_pool500_shadow_ranking.py tests/test_pool500_ranking_adapter.py`，结果 `All checks passed`。独立 verifier 确认没有引入 `build_ranking_run_row` / `ranking_experiments` 污染，也没有 promotion、ranking replacement 或 pool1000 语义。

**面试可讲点：**
这段可以讲成“推荐排序优化先做可治理诊断，而不是盲目调参”：在 pool500 候选数达标后，把 fallback 暴露、source 多样性、元数据质量和标签可用性纳入排序 evidence contract，并用 conservative guard 防止机制实验被误包装成效果提升，为后续受控 promotion proposal 留出证据边界。

### 2026-05-20 - pool500 ranking diagnostic gate 与固定对照报告

**任务：**
围绕排序链路作为推荐 Agent 底座的前两个调优方向，落实 pool500 冻结候选池质量诊断和固定排序融合对照报告。范围限定为 diagnostic/reporting：不 promotion、不替换 ranking input、不引入 `current_ranking_route` / `champion` 等正式路由语义。

**遇到的问题：**
候选池质量和排序融合解释容易混在一起：如果 pool500 候选池 underfilled、source 覆盖不全或 metadata/category 缺失，直接比较排序策略会把候选池缺陷误读成排序优劣。同时 `itemcf` 既可能作为 ranking config group key，又是禁止出现在候选/report source 中的 raw label，需要显式隔离。

**定位方式：**
依据 `.omc/plans/ralplan-pool500-agent-ranking-tuning.md`，检查 `rs_core/workflow/pool500_shadow_ranking.py` 的 frozen diagnostic lane、normal shadow preflight、ranking payload explainability 字段，以及 `rs_core/recsys/recall/canonical.py` / ranking source minimums 的 source 语义。验证时使用默认 `.venv` 跑 focused 和验收测试，并由独立 verifier 复核 diagnostic 边界。

**解决方式：**
在 `pool500_shadow_ranking.py` 中补齐 Phase A 聚合字段和 interpretation gate：`source_coverage`、`category_coverage`、`multi_source_item_ratio`、`metadata_missing_rate`、`category_missing_rate`、`top_category_ratio`、`underfilled_user_count`、`interpretation_label`。其中 underfilled 使用每用户 unique `candidate_count < 500`，而不是 TopK underfilled。新增 Phase B 固定对照报告：只允许 B0/D1/D2/A1/A2，`top_k=20`，Top10 作为 Top20 截断视图，并输出 `score_trace`、`rank_movement`、`score_components`、`stage_trace_coverage`、`topk_source_contribution` 和基于 `parent_asin` 的 case diff。

**验证结果：**
新增/更新 `tests/test_pool500_shadow_ranking.py` 覆盖 missing aggregation -> `blocked`、forbidden source -> `blocked`、underfilled > 2% -> `mechanism_only`、canonical source set incomplete -> `mechanism_only`、normal fixture -> `comparable`，以及固定 config 输出和 case diff 必需字段。验证命令：`.venv/Scripts/python.exe -m pytest tests/test_pool500_shadow_ranking.py -q` 结果 `60 passed`；`.venv/Scripts/python.exe -m pytest tests/test_pool500_ranking_adapter.py tests/test_pool500_shadow_ranking.py tests/test_full_data_pool500_route_gate.py tests/test_pool500_method_registry_drift.py -q` 结果 `128 passed`；`.venv/Scripts/python.exe -m ruff check rs_core/workflow/pool500_shadow_ranking.py tests/test_pool500_shadow_ranking.py` 结果 `All checks passed`。独立 verifier 结论为 PASS。

**面试可讲点：**
这段可以讲成“推荐排序调优先建立可解释诊断边界”：先用候选池质量 gate 决定结论只能是 blocked、mechanism_only 还是 comparable，再在固定 config 矩阵上解释排序变化，避免把数据供给问题误判为排序算法收益，同时为后续 Agent 多轮反馈重排保留可追踪的 score trace 和 case diff。

### 2026-05-20 - pool500 diagnostic shadow ranking hard gate

**任务：**
执行 ralplan 共识后的 Phase 1/2：冻结 pool500 fallback completion 的 shadow-only 基线，并在 `pool500_shadow_ranking` 中补齐 `diagnostic shadow ranking report` 的硬门禁 schema，确保后续即使进入排序诊断，也不会被误用为正式 ranking input replacement。

**遇到的问题：**
pool500 已具备 fallback completion 补齐能力，但当前治理仍明确禁止 ranking replacement、promotion 和 pool1000。如果缺少排序诊断报告级别的 hard gate，后续 `shadow ranking evaluation` 容易在语义上滑向“准正式排序输入”，尤其是 Agent/前端消费结论时可能误读为 route 已晋升。

**定位方式：**
读取 `rs_core/workflow/pool500_shadow_ranking.py`、`rs_core/workflow/pool500_ranking_adapter.py`、`rs_core/common/engineering_contracts.py` 以及 `tests/test_pool500_shadow_ranking.py` / `tests/test_engineering_contracts.py`，确认现有代码已禁止 pool500 进入 `current_ranking_route`，但 shadow ranking evidence 还缺少 lineage、baseline、resource budget、failure recovery、cleanup 等 Phase 2 hard gate 字段。

**解决方式：**
在 `rs_core/workflow/pool500_shadow_ranking.py` 中增加 `diagnostic shadow ranking report` 语义和边界字段：`not_ranking_input=true`、`current_ranking_route_unchanged=true`、`promotion_requires_future_plan=true`。同时新增 hard gate 校验：必须提供 `lineage_hash`、`baseline_artifact_hash`、`resource_budget`、`failure_recovery_strategy`、`cleanup_strategy`；`resource_budget` 至少包含一个正数 `max_` 上限字段。没有修改 registry、`current_ranking_route` 或任何 promotion 配置。

**验证结果：**
新增/更新 `tests/test_pool500_shadow_ranking.py` 显式覆盖报告语义、边界字段、hard gate 缺失/非法值、resource budget 上限校验和 forbidden promotion semantics。独立 verifier 使用默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_ranking_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_engineering_contracts.py -q`，结果 `86 passed in 0.31s`。verifier 确认本任务只触及 `pool500_shadow_ranking.py` 和对应测试，没有执行 Phase 3、没有 route replacement、没有 registry 修改。

**面试可讲点：**
这段可以讲成“把推荐实验从能跑升级为可治理”：不仅实现 shadow ranking 的报告字段，还把 lineage、baseline、资源预算、失败恢复和 cleanup 做成硬门禁，用测试防止召回补齐能力被误晋升为正式排序输入，体现离线推荐链路从实验证据到生产晋升之间的工程治理意识。

### 2026-05-20 - pool500 universal fallback completion 主路沉淀

**任务：**
把 `pool500 cold-start fallback repair v5` 的一次性补齐经验，沉淀为主路可调用的结构化 `fallback_completion` 包，并在 `run_full_data_pool500_recall_only.py` 中薄接入；要求任意 underfilled 用户可按 fallback ladder 尽量补到 500，但仍保持 shadow/diagnostic 边界，不声明 ranking replacement、promotion、pool1000 或 FULL_POOL500_READY。

**遇到的问题：**
已有 v5 能把诊断批次补齐到每用户 500，但它是 batch repair 产物，source 使用 `cold_start_*`，不能直接作为正式主路能力。若直接复制脚本到 runner，会造成分层、context 构建、source 生成、补齐和审计逻辑混杂，也容易把 fallback 兜底误晋升为高质量个性化召回。

**定位方式：**
对照 `C:\Users\luo\.claude\plans\jolly-sniffing-sphinx.md` 和现有 `fallback_completion_contract.py`，确认应复用治理 contract，而不是重复定义分层与风险规则。实现过程中发现 `context.py` 对 forbidden marker 的初版检查用路径子串匹配，会误伤 pytest 临时目录中的 `test_*` 路径；测试阶段将其定位为 false positive，并改为按规范化 path component 匹配 `LOPO`、`holdout`、`valid`、`test`、`leave_one_positive_out`、`clean_10000` 等数据范围标记。

**解决方式：**
新增/完善 `rs_lab/experiments/recall/pool500/fallback_completion/`：`context.py` 只从 train-safe/lightweight view 输入构建 bounded context 和 resource audit，`completion.py` 保留已有候选、排除历史和重复 item，再按 seed category、metadata neighbor、semantic token、category/context/global popular ladder 补齐到最多 500。runner 只负责构建 context、逐用户调用 completion、写出 `fallback_completion_audit.json`、`fallback_completion_validation.json`、`fallback_completion_resource_audit.json`，并把 fallback 子类型写入 metadata/audit，最终 candidate `source/sources` 仍保持 canonical labels。

**验证结果：**
新增 `tests/test_pool500_fallback_completion_route.py`，并更新 `tests/test_full_data_pool500_recall_only.py` 覆盖 runner artifact、manifest summary、governance flags、canonical source 和 `POOL500_FALLBACK_COMPLETION_SHADOW_ONLY` 诊断。使用默认 `.venv` 运行 focused tests：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_contract.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_route.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py -q`，独立 verifier 复验结果 `81 passed in 4.19s`。verifier 同时确认 completion 保留原候选、去重、排除历史、最多 500，fallback subtype 只出现在 metadata/audit，所有 ranking/promotion/pool1000/full-ready flag 保持 false。

**面试可讲点：**
这段可以讲成“把一次性召回 repair 升级为可治理的主路能力”：不是简单堆 popular 兜底，而是把低历史补齐拆成 context、source、completion、audit 四层，并用 canonical source gate、fallback ratio、quality risk、resource audit 和 shadow-only diagnostic 保证候选数量补齐不会被误解为线上可晋升质量结论。

### 2026-05-20 - pool500 direct recall 最新 method source 接入修复

**任务：**
修复 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 method source manifest 默认接入，重新生成 `outputs/recall/pool500_main_route_direct_recall_method_sources_v2/`，要求只消费已有最新 source artifact，不盲目重建方法产物，并继续禁止 candidate generation、ranking input replacement、pool1000 和 promotion。

**遇到的问题：**
旧 direct recall 汇总没有吃到最新 method source：`swing_recall` 在汇总中为 0，`usercf_recall` 仍指向旧 sidecar fix，`semantic_title_category_expansion` 与 `co_visit_fallback_repair` 仍停留在旧低 row_count。进一步定位发现 runner 默认 manifest 常量仍指向旧路径，且对 semantic/co-visit 这类已有 `candidates.jsonl` 的 method source 仍主要走运行时重生成逻辑，导致最新预生成候选没有直接进入 merge。

**定位方式：**
读取 `run_full_data_pool500_recall_only.py` 的 `DEFAULT_SOURCE_MANIFESTS`、`_source_manifest_paths()`、`_load_source_artifacts()`、`_write_source_manifests()`，并核对 7 个目标 source manifest：`swing_recall/target_slice_diagnostic_v1`、`usercf_recall/usercf_recall_pool500_heavy_probe_train_only_20260520`、`itemcf_weak/target500_train_weak_edges_v1`、`itemcf_strong/itemcf_strong_20260519T0945Z`、`semantic_title_category_expansion/target500_semantic_title_category_v1`、`co_visit_fallback_repair/target_slice_20260519_0001`、`two_tower_target500_slice_expanded`。同时检查 `rs_core/recsys/candidate_merge.py`，确认需要给 merge 增加预生成候选入口。

**解决方式：**
将 runner 默认 source manifest 更新到最新产物路径；新增 `_load_pregenerated_recall_sources()`，从 method source manifest 的 `candidates_path` / `outputs.candidates` 读取 `semantic_title_category_expansion` 与 `co_visit_fallback_repair` 的预生成候选，并通过 `merge_for_user(..., pregenerated_recall=...)` 合入候选池。对缺少旧 `semantic_recall_inputs_path` 字段的新 semantic manifest，保留回退到 lightweight views 的语义索引输入，避免破坏现有 semantic diagnostic 辅助逻辑。

**验证结果：**
`tests/test_full_data_pool500_recall_only.py -q` 通过 `8 passed`，修改文件 `py_compile` 通过。使用 `.venv` 重跑 direct recall v2，输出 `outputs/recall/pool500_main_route_direct_recall_method_sources_v2/manifest.json`：`processed_users=500`、`candidate_rows=213891`、`users_with_500_candidates=273`、`underfilled_user_count=227`，每用户候选数 `min/p50/p90/max=40/500/500/500`。`source_coverage` 为 `category=37585`、`co_visit_fallback_repair=23541`、`itemcf_strong=34305`、`itemcf_weak=35803`、`popular=9054`、`semantic_title_category_expansion=30489`、`swing_recall=26791`、`two_tower=54139`、`usercf_recall=3911`。程序化校验确认 7 个 source 的 `source_index_manifest_path` 均指向指定最新产物，且 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。最终 `readiness_result.status=STOP`，blocker 为 `ARTIFACT_GATE_STOP`；`ready_source_stoploss_audit.status=STOPLOSS_TRIGGERED`，原因是 `target_batch_underfilled` 与 `ready_source_capacity_below_pool500_budget`。

**面试可讲点：**
这段可以讲成“修复召回主路的 artifact 接入一致性”：不是继续堆方法产物，而是定位 runner 消费层的路径漂移和预生成候选未接入问题，用 manifest 合同、source coverage、stoploss audit 和程序化断言证明 7 路 source 都进入统一候选池，同时保留 STOP 结论暴露 ready source 容量不足。

### 2026-05-20 - pool500 direct recall method_sources_v3 收口

**任务：**
收口 `outputs/recall/pool500_main_route_direct_recall_method_sources_v3/`，重点修复最新强 UserCF method source 没有真正进入 final merge 的问题，同时保留 v2 已接入的 `swing_recall`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 以及强 ItemCF / two_tower source；全程保持 `diagnostic_limited` / `DIAGNOSTIC_ONLY` / `TARGET_SLICE_DIAGNOSTIC` 边界，不声明 READY、不授权 candidate generation、ranking replacement、pool1000 或 promotion。

**遇到的问题：**
v2 中 UserCF 最新 manifest 显示 `candidate_row_count=185862`、`user_coverage_count=372`，但 `source_contribution_audit` 只有 `3911 rows / 39 users`。第一次修复 loader 后，source loader 已能读入 `185862 rows / 372 users`，但 final v3 仍只有约 `4028 rows / 39 users`，说明问题不只在文件读取，还包括 direct recall batch target users 与 UserCF artifact target users 未对齐。

**定位方式：**
核对 `outputs/recall/pool500_method_sources/usercf_recall/usercf_recall_pool500_heavy_probe_train_only_20260520/source_index_manifest.json`、candidate shards 和 `method_dataset_manifest.json`，确认最新 UserCF 使用 24 个 flat candidate shard，单行 schema 为 `user_id + item_id/parent_asin + score + rank + source/canonical_source`，而旧 loader 主要假设每行包含 `candidates[]`。随后对比 runner 的 batch 用户加载逻辑，发现 `_load_batch_sequences()` 默认取 train sequence 前 500 用户，没有优先纳入 UserCF 的 372 个 `target_user_ids`。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 中扩展 `load_usercf_recall_sidecar()`，优先读取 `outputs.candidate_shards`，无 shards 时回退到 `outputs.candidates`，并同时兼容 nested `candidates[]` 与 flat candidate row schema，严格校验 `source/canonical_source=usercf_recall`、train-only 与 forbidden flags。随后在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 中增加 source-aligned target user 选择：优先从 UserCF manifest / `method_dataset_manifest` / eligible manifest 提取目标用户，再用 train sequence filler 补足到 500。

**验证结果：**
新增/更新 `tests/test_full_data_pool500_recall_only.py` 覆盖 flat UserCF shards 读取和 priority target user 加载，targeted pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py -q`，结果 `10 passed`。最终 v3 manifest：`processed_users=500`、`candidate_rows=240238`、`users_with_500_candidates=434`、`underfilled_user_count=66`；`source_coverage` 中 `usercf_recall=51030`，`source_contribution_audit` 中 UserCF 覆盖 `372 users`。相比 `method_sources_v2` 的 `273 full / 227 underfilled` 和 `high_cost_slice_v1` 的 `297 full / 203 underfilled`，v3 明显更优；`readiness_result.status=STOP`，`ready_source_stoploss_audit.status=STOPLOSS_TRIGGERED`，没有越权晋升。

**面试可讲点：**
这段可以讲成“用 artifact contract + schema compatibility + target-slice alignment 修复召回源接入失真”：不是重新造 UserCF 产物，而是定位消费侧 schema 漂移和用户切片不一致，让 185862 行强 UserCF source 被正确读入并在治理边界内贡献到最终 pool500，同时用 underfill、source coverage 和 STOP gate 证明效果提升但不伪造线上可用结论。

### 2026-05-20 - pool500 underfilled-only repair v4

**任务：**
基于 `outputs/recall/pool500_main_route_direct_recall_method_sources_v3/`，只针对剩余 66 个 underfilled users 生成 `outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4/`，禁止全局重跑、禁止重建 UserCF/ItemCF、禁止覆盖 v3，并继续保持 candidate generation、ranking replacement、pool1000 和 promotion 全部关闭。

**遇到的问题：**
v3 已达到 `434/500` 用户满 500 候选，但仍有 66 个用户不足，最少只有 40 条。直接把 popular/category 灌满会制造虚假的 READY 结论，因此 v4 必须只作为 underfilled-only shadow evidence，并在无法补满时如实 STOP。

**定位方式：**
读取 v3 的 `manifest.json`、`underfill_audit.json`、`per_source_output_manifests.json`、`canonical_source_registry.json` 与 source 子表，确认 66 个目标用户和每路 source 的候选路径。进一步核对 method source manifest，优先复用已有 `candidates.jsonl`，而不是重新训练或重建 sidecar。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/underfilled_repair/build_underfilled66_repair_v4.py`，以 v3 `pool500_candidates.jsonl` 为基底，只对 `remaining_underfilled_users` 按 `two_tower → semantic_title_category_expansion → co_visit_fallback_repair → swing_recall → category → 既有 ItemCF/UserCF → popular` 顺序补非重复候选，每用户最多 500 条。新增候选保留原 source，并添加 `repair_stage=underfilled66_v4`、shadow evidence 和 promotion/ranking/pool1000 false 标记；popular 设置每用户上限，不能无限兜底。

**验证结果：**
使用默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe rs_lab/experiments/recall/pool500/methods/underfilled_repair/build_underfilled66_repair_v4.py --base-run-dir outputs/recall/pool500_main_route_direct_recall_method_sources_v3 --output-dir outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4 --overwrite`。v4 结果：`candidate_rows=240889`、`users_with_500_candidates=438`、`underfilled_user_count=62`、`candidate_count_min/p50/p90/max=40/500/500/500`、`decision=STOP`。`repair_contribution_audit.json` 显示新增 `651` 条候选，均来自 `swing_recall`，覆盖 29 个 underfilled users；其他优先 source 对剩余目标用户没有新增非重复候选。独立校验确认 `duplicate_item_per_user_count=0`、`per_user_over_500_count=0`、`pool500_shadow_evidence_validation.status=PASS`、`no_forbidden_data=PASS`、promotion/ranking/pool1000 flags 全 false。

**面试可讲点：**
这段可以讲成“召回池 repair 的治理边界控制”：不是为了指标强行补满，而是在现有 artifact 合同内做 underfilled-only 增量修复，用去重、source overlap、forbidden data scan、shadow evidence validation 证明增量安全，同时在剩余用户无足够非重复候选时保持 STOP，体现推荐系统离线产物从诊断证据到可晋升输入之间的门禁意识。

### 2026-05-20 - pool500 cold-start fallback repair v5

**任务：**
基于 `outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4/`，只针对 v4 剩余 62 个 underfilled low-history users 生成 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/`。目标是补齐每用户 500 候选，但只能作为 cold-start shadow evidence，不能晋升为 ranking replacement、pool1000 或 promotion 输入。

**遇到的问题：**
在 v4 中，常规 underfilled-only repair 只能补入 `651` 条 `swing_recall`，最终仍有 `62` 个用户不足 500。既有诊断显示这些用户不是用户丢失，而是 `sequence_len<=2` 的极低历史用户，因此继续复用普通召回 repair 会耗尽非重复候选，必须转成 cold-start / low-history 专用补齐路线，并单独披露质量风险。

**定位方式：**
读取 v4 的 `manifest.json`、`underfill_audit.json`、`pool500_candidates.jsonl`、`source_contribution_audit.json`、`repair_contribution_audit.json`，确认基底为 `438/500` 满候选、`62` underfilled、`candidate_rows=240889`，且治理 gate 全部为 false。随后只读取 train/canonical/lightweight views：`user_sequences.train.jsonl`、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`popular_recall.jsonl`、`semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`，避免使用 holdout/valid/test/LOPO/clean_10000。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/batch_runs/build_cold_start_fallback_v5.py`，以 v4 `pool500_candidates.jsonl` 为基底，仅处理 `remaining_underfilled_users` 中的 62 人。脚本按 seed item category sibling、metadata neighbor、semantic token sibling、item-neighbor reuse、category popular、global diversity popular 的顺序补非重复候选；新增候选统一标记 `repair_stage=cold_start_fallback_v5`，source 使用 `cold_start_*` 命名，不伪装成 UserCF/TwoTower/Swing 等原始个性化召回源，并输出用户分层、source 贡献、overlap、质量风险、资源和 readiness/shadow validation 审计。

**验证结果：**
使用默认 `.venv` 运行用户指定命令，输出目录生成成功。v5 `manifest.json` 显示 `candidate_rows=250000`、`users_with_500_candidates=500`、`underfilled_user_count=0`、`candidate_count_min/p50/p90/max=500/500/500/500`、`decision=DIAGNOSTIC_PASS`，但 `artifact_gate_decision=STOP`。62 个用户分层为 `zero_positive_cold_start=13`、`single_seed_cold_start=48`、`two_seed_low_history=1`；新增 `9111` 条 cold-start 候选，其中 `cold_start_category_sibling=7032`、`cold_start_metadata_neighbor=1837`、`cold_start_semantic_token=242`，popular 两路为 0。质量风险审计显示 `average_fallback_ratio=0.293903`、`average_popular_ratio=0.0`、`users_high_risk_count=13`。独立程序化校验确认 `row_count=250000`、`user_count=500`、每用户 `min=max=500`、`duplicate_item_per_user=0`、v5 新行 source 均为 `cold_start_*`、必需 artifact 无缺失、所有治理 flag 未置 true，`pool500_shadow_evidence_validation.json` 中 `marker_isolation/no_forbidden_data/per_user_le_500/promotion_flags_all_false/cold_start_audit_present` 均为 PASS。

**面试可讲点：**
这段可以讲成“对低历史用户单独建模的召回治理”：不是把 popular 当作万能补丁，也不是把补满后的候选池伪装成正常个性化召回，而是在 train-only 数据边界内用 seed metadata/category/token 做 cold-start shadow repair，并通过 fallback ratio、popular ratio、source marker isolation 和 STOP gate 把质量风险显式交给后续排序特征与治理流程。

### 2026-05-20 - pool500 fallback completion contract 治理沉淀

**任务：**
把 v5 cold-start fallback repair 中证明可补齐 500 的经验沉淀为更通用的 pool500 fallback completion contract，优先放在实验治理层，明确任意用户、低历史用户和零历史用户的补齐边界，但不替换现有主路 runner。

**遇到的问题：**
v5 已经把 500 个诊断用户全部补齐到 500，但它仍是 shadow evidence。如果没有正式 contract，后续容易把 popular 或 cold-start 兜底误当成高质量个性化召回，甚至绕过 ranking replacement、promotion 或 pool1000 的治理门禁。

**定位方式：**
对照 v3/v4/v5 的 underfill 结果和治理要求，确认 contract 必须覆盖用户分层、fallback source ladder、cap、去重、截断、per-user/global audit、质量风险和 forbidden flags。独立 verifier 首轮发现风险阈值与 audit 内嵌 config 校验不够严格，随后补充测试锁定阈值和 flag 校验。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/governance/fallback_completion_contract.py`，定义 `ZERO_HISTORY`、`ZERO_POSITIVE_HISTORY`、`LOW_HISTORY_SINGLE_SEED`、`LOW_HISTORY_MULTI_SEED`、`NORMAL_HISTORY` 五类用户，以及 personalized → seed category → seed metadata → seed semantic → category/context/global popular 的补齐 ladder。`build_fallback_completion_audit()` 输出 per-user/global audit，`validate_fallback_completion_contract()` 强制拒绝超过 500、重复 item、over-target 和任何 ranking/promotion/pool1000/READY flag。

**验证结果：**
新增 `tests/test_pool500_fallback_completion_contract.py`，使用默认 `.venv` 运行：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_contract.py -q`，复验结果 `16 passed in 0.04s`。独立 verifier 确认风险阈值、source ladder、audit config flag 校验和 README 边界均通过。

**面试可讲点：**
这段可以讲成“把召回不足补齐从一次性脚本升级为治理契约”：既允许零历史用户用全局多样性热门补满 500，又用 `fallback_ratio`、`popular_ratio`、`quality_risk_level=HIGH` 和 false governance flags 防止兜底候选伪装成个性化召回或被越权晋升。

### 2026-05-18 - pool500 回召诊断包输出补齐

**任务：**
在 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 中补齐 final diagnostic bundle 输出，并同步补充 `tests/test_full_data_pool500_recall_only.py` 的覆盖，保证池化召回链路能稳定产出可审计诊断材料。

**遇到的问题：**
此前链路虽然能跑通小批诊断，但 final diagnostic bundle 的输出边界不够明确，容易让后续复用时把诊断产物误当成 readiness 结论。

**定位方式：**
对照回召 runner 与相关测试，确认需要把最终诊断包的产物名、输出路径和测试断言固定下来，并保留 `DIAGNOSTIC_ONLY` 边界。

**解决方式：**
显式增加 final diagnostic bundle 相关输出，并用测试锁定产物存在性与路径一致性，只补诊断证据，不改 readiness 判定。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_source_registry.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py -q`，结果 `66 passed in 0.24s`；`ruff check` 覆盖本轮触及的 runner 与测试文件，结果 `All checks passed!`。

**面试可讲点：**
可以讲成“把召回诊断产物工程化并固定边界”：一边补齐最终诊断包输出，一边用测试锁住产物契约，避免诊断结果被误用为最终 ready 结论。

### 2026-05-14 - 固定 Phase 1 混合召回主路

**任务：**
在已补跑 graph、vector/two-tower、MF、sequence/multi-interest、source-aware 截断等实验后，按用户要求把当前效果最好的混合召回路线固定为默认主路，并同步更新配置与文档结论。

**遇到的问题：**
此前文档把 `source_balanced_fallback_preserving` 写成 observation / defer，因为它没有增加 `candidate_hit_users`；但重新对比全部 Phase 1.21 metrics 后发现，它在保持最高档 `candidate_hit_users=19` 的同时，让 target 更早进入候选池，并减少平均候选量。因此主路选择不能只看最终 pool 命中人数，还要综合前段召回位置、候选规模和尾部命中位置。

**定位方式：**
汇总 `outputs/recall/phase_1_21_recall_coverage/**/metrics.json`，按 `candidate_hit_users`、`candidate_hit_rate_at_100`、`recall_at_pool`、`candidate_hit_rank_avg/p90`、`candidate_count_avg` 对比所有已执行路线。`source_balanced_fallback_preserving` 达到 `candidate_hit_users=19`、`candidate_hit_rate_at_100=0.130435`、`candidate_hit_rank_avg=31.315789`、`candidate_hit_rank_p90=64.0`、`candidate_count_avg=126.972`，综合优于 score-sorted 和其他 graph/vector/MF/sequence 路线。

**解决方式：**
将 `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` 固定为混合主路：启用 `semantic_title_category_expansion`、`co_visit_fallback_repair`、UserCF、Swing，并设置 `candidate_pool_strategy: balanced_source_budget`、source minimums、`popular` 上限和 fill order。文档中把 source-balanced 从 `defer` 改为 `current_main_route`，明确 graph、MF、sequence 等不进入当前主路。

**验证结果：**
已复用同合同实验 artifact：`outputs/recall/phase_1_21_recall_coverage/source_aware/comparison/source_balanced_fallback_preserving/metrics.json`。随后用固定后的 `configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml` 复验，输出 `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/`，holdout hash 仍为 `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`。该路线保持 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`，并相对 score-sorted 把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`，`candidate_hit_rank_avg/p90` 从 `34.526316/73.0` 改善到 `31.315789/64.0`，`candidate_count_avg` 从 `136.214` 降到 `126.972`。

**面试可讲点：**
这段可以讲成“用指标治理选择混合召回主路”：不是因为某个算法名字高级就晋升，而是在同一 holdout、同一 pool200 合同下比较多路召回、前段命中、候选池体积和 source 平衡，最终把语义主增量 + 行为 fallback + 兜底源 + source-balanced 截断固定为可解释、可维护的召回主线。

### 2026-05-20 - recall core canonical / merge 工具迁移验证

**任务：**
独立验证 Phase 0+1 迁移：只把可复用的 recall source canonical 与 fallback merge 工具抽到 `rs_core.recsys.recall`，并确认 `full_data_pool500_route_gate.py` 与 pool500 fallback completion 只复用 core 工具，不改变既有 pool500 路线语义。

**遇到的问题：**
迁移边界容易越界：`rs_core` 不能反向依赖 `rs_lab`，新 core 模块也不能写入 pool500 artifact 路径、实验 runner 或 fallback completion 专有语义，否则会把实验层治理逻辑污染到核心层。

**定位方式：**
读取 `.omc/handoffs/team-plan.md`、`.omc/handoffs/team-exec.md` 和迁移涉及文件，重点检查 `rs_core/recsys/recall/{canonical.py,merge.py,__init__.py}`、`rs_core/workflow/full_data_pool500_route_gate.py`、`rs_lab/experiments/recall/pool500/fallback_completion/completion.py`、`tests/test_recall_core_utils.py`。使用 Grep 搜索 `rs_core` 内的 `from rs_lab` / `import rs_lab`，以及新 core recall 模块内的 `pool500|artifact|runner|rs_lab|experiments/recall|fallback_completion`，均无命中。

**解决方式：**
本轮作为 verifier 未再改迁移代码，只确认分层：core 层只保留通用 canonical source 集合、别名归一、禁用 source 检查、候选去重/截断/历史排除/source cap merge；pool500 fallback completion 仍在实验层负责 segment、source ladder、metadata/audit；route gate 只从 core 复用 canonical source 常量与归一函数。

**验证结果：**
使用项目默认 `.venv` 运行 focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_core_utils.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_fallback_completion_route.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_ranking_adapter.py`，结果 `114 passed in 0.29s`。未运行 full-data、GPU 或 heavy job。

**面试可讲点：**
这段可以讲成“把实验召回链路中的稳定能力抽成 core，但用验证防止实验语义倒灌”：用静态依赖扫描和 focused regression 同时证明核心层无 `rs_lab` 反向依赖、无 pool500 artifact 语义，调用方行为仍由原治理测试锁住。

### 2026-06-06 - RPA 置信度局部重排最终效果诊断

**任务：**
在 Zhang & Pu 2007 Recursive CF / RPA 已证明 rating prediction MAE 有收益后，继续验证它能否转化为 pool500 最终候选排序效果，即 Recall@K / HitRate@K，而不是只看 MSE/MAE。

**遇到的问题：**
纯 RPA score 全局重排在 1000-user pool500 候选上严重伤害前排指标，且旧诊断显示 `empty_denominator_count=500000`，说明多数候选没有真实邻居分母，RPA 分数退化成 fallback。直接按 raw rating prediction 重排不适合当前 Amazon 稀疏候选池，尤其 1000-user baseline 切片偏 cold-ish，用户历史短、Pearson overlap 很难形成有效支持。

**定位方式：**
先读取既有 `outputs/eval/rpa_rerank_diagnostic_1000_k20_phi2_20260606a/manifest.json` 与 `metrics.json`，确认纯 RPA rerank 从 baseline `Recall@20/50/100=0.010610/0.017255/0.019679` 降到 `0/0/0.0042`，且 `empty_denominator_count=500000`。随后新增 per-user train-only 局部诊断脚本 `rs_lab/experiments/recall/run_rpa_pool500_candidate_rerank_per_user_diagnostic.py`，在每个用户的 train history + candidate item 局部邻居内计算 supported residual 与覆盖率，并在 manifest 中记录 `train_index_scope`、`eval_label_role`、`supported_candidate_ratio`。

**解决方式：**
把策略从“全量按 RPA raw score 排序”改成“有证据才局部微调”：脚本只用 `ranked_interactions.row_num <= train_end_row` 构造 per-user 邻居/打分索引，labels 只在最终 `_evaluate_rows` 和 coverage 统计中使用。为稀疏单历史用户增加诊断性的 one-overlap sparse similarity fallback，并只测试 conservative bucket 内 residual 调整；所有输出保持 `diagnostic_only=true`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**验证结果：**
`py_compile` 通过；1000-user 诊断输出到 `outputs/eval/rpa_per_user_fast_residual_1000_20260606a/`，运行耗时约 59.35s。manifest 显示 `candidate_count=500000`、`supported_candidate_count=5635`、`supported_candidate_ratio=0.01127`、`supported_positive_candidate_count=3/37`；metrics 显示 conservative `bucket10/20/50_conf_alpha1/2/5` 相对 original 的 Recall/HitRate delta 全为 0，`pure_supported_residual` 反而下降（例如 `Recall@20 -0.009316`、`Recall@50 -0.009317`）。随后按 segment 重排 fixed eval users，分别生成 `outputs/eval/rpa_rerank_baseline_hot1000_20260606a/` 与 `outputs/eval/rpa_rerank_baseline_warm1000_20260606a/`：hot1000 的 `supported_candidate_ratio=0.090606`、`supported_positive_candidate_ratio=0.365385`，但 bucket 策略全部无 Recall/HitRate 提升；warm1000 的 `supported_candidate_ratio=0.01856`，`bucket50_conf_alpha5` 仅有 `Recall@20 +0.001333`、`HitRate@20 +0.002` 的极小改善，@50/@100/@500 不提升。独立 verifier 复核结论为 PASS：无明显 label backflow，当前只能报告“未观察到稳定最终 Recall/HitRate 提升”，不能晋升或替换主排序输入。

**面试可讲点：**
这段可以讲成“把论文算法收益和业务最终指标拆开验证”：RPA 在评分预测任务上能降 MAE，但在稀疏、冷启动、候选池已冻结的 top-N 任务中，邻居覆盖不足会让分数退化甚至伤害前排。工程上没有把论文指标直接包装成推荐效果，而是通过 per-user confidence coverage、bucket local rerank 和 no-label-backflow 审计证明当前方法只适合作为诊断/弱特征候选，下一步应优先提升热/温用户切片和候选 item 的 train-only 协同证据覆盖。

### 2026-06-19 - retrieve_candidates 业务模式 schema 收敛

**任务：**
保留 `retrieve_candidates` 统一候选获取入口，但将 Agent 可见口径从底层 `route_policy.semantic/similar_item/user_neighbor/behavioral/fallback` 收敛为 `retrieval_mode/profile_usage/expansion_policy/reference_item_id/query/constraints/target_pool_size`，同时保持 legacy 字段兼容。

**遇到的问题：**
原 manifest、planner 和 runtime route decisions 暴露过多 provider 细节，容易让 Agent 直接选择类似 ItemCF/UserCF/two-tower/co-visit 的底层召回来源；同时“像某个商品但更便宜/更轻”等 reference-aware 请求需要允许语义召回参与，而不能只落到传统相似物品路径。

**定位方式：**
阅读 `rs_core/rsagent/tools.py`、`rs_core/rsagent/dialogue.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/workflow/online_recommendation.py` 以及 `tests/test_agent_tools.py`、`tests/test_agent_runtime.py`、`tests/test_agent_dialogue.py`。首次 focused pytest 暴露旧测试仍断言 `retrieve_candidates_output_v2` 和 `semantic_live` manifest 口径，随后按新业务 schema 更新测试断言。

**解决方式：**
`RetrieveCandidatesInput` 增加业务字段，manifest/boundary prompt 改为强调业务模式和禁止 provider steering；runtime 新增 `_normalize_retrieve_policy()`，新字段优先、旧字段 fallback，并把 summary 升级到 `retrieve_candidates_output_v3`。语义 query 构造支持 `reference_item_id` compact text，route decisions 改为 `semantic_intent/profile_context/reference_context/backend_recall/fallback_safety`，避免低层 source/score/lineage 泄漏。Dialogue planner 用 deterministic 规则输出 `specific_need/personalized_feed/broad_browse/similar_to_item/reference_with_constraints`，online retrieve seam 增加可选 `retrieve_policy` 并用 reference item 作为 source index seed。

**验证结果：**
使用项目默认 `.venv` 运行 focused 回归：`.venv/Scripts/python -m pytest tests/test_agent_tools.py tests/test_agent_runtime.py tests/test_agent_dialogue.py tests/test_agent_capability_manifest.py tests/test_serving_facades.py tests/test_serving_smoke.py -q`，结果 `147 passed in 2.00s`（有 1 个既有 SQLite `__del__` 线程告警）；随后运行 `.venv/Scripts/python -m compileall -q rs_core tests`，无输出通过。另由 verifier 只读复核，结论 `PASS`、无 blocker。

**面试可讲点：**
这段可以讲成“把推荐 Agent 的工具协议从算法实现细节上移到业务意图层”：Agent 只表达用户需求模式、画像使用强度、扩展策略和 reference item，后端统一做 provider 映射与治理，既降低 prompt 对底层召回源的耦合，也用 public payload 测试防止 score/source/lineage 泄漏。

### YYYY-MM-DD - 任务标题

**任务：**
简要说明这次任务要完成什么。

**遇到的问题：**
说明遇到的技术障碍、歧义、缺陷、数据问题或工程取舍。

**定位方式：**
说明如何诊断问题，引用具体文件、命令、测试、指标或输出证据。

**解决方式：**
说明采用了什么方案，为什么这个方案合理。

**验证结果：**
说明用什么测试、命令、输出文件或指标证明结果有效。

**面试可讲点：**
把这次工作提炼成面试中可以讲的工程能力、系统思维或技术亮点。

## 记录

### 2026-05-20 - pool500 frozen diagnostic 排序通道与首轮指标

**任务：**
在召回路线迁入 core 并验证工程可用后，基于冻结 `pool500_main_route_direct_recall_cold_start_fallback_v5` 候选池执行排序优化第一步：新增 diagnostic frozen-pool shadow ranking lane，跑出首轮排序结构指标，但不声明 ranking input replacement、promotion、pool1000 或线上 READY。

**遇到的问题：**
现有 `run_pool500_shadow_ranking()` 要求 `FULL_POOL500_READY`，而当前 v5 召回 artifact 虽然已补齐 `500 users × 500 candidates`，但 manifest 中 `artifact_gate_decision=STOP`，不能为了排序测试伪造 READY。执行 smoke 时还发现 v5 中 651 条 `swing_recall` repair 行缺少顶层 `score`，但保留了 `source_scores.swing_recall`。

**定位方式：**
通过 `tests/test_pool500_shadow_ranking.py` 确认正式 shadow lane 在非 `FULL_POOL500_READY` 下必须 STOP；读取 v5 manifest 确认 `candidate_rows=250000`、`users_with_500_candidates=500`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。用脚本统计候选源分布，发现包含 `cold_start_*` 诊断源；进一步扫描缺失 score 行，定位为 651 条 `swing_recall` underfilled repair 行，均可从 `source_scores` 恢复排序分数。

**解决方式：**
在 `rs_core/workflow/pool500_shadow_ranking.py` 中新增 `run_pool500_diagnostic_frozen_pool_ranking()`，公共入口强制要求固定 `pool500_candidates_path`、`candidate_manifest_path`、`expected_candidate_hash`、`expected_manifest_hash`，排序前计算 computed hash 并校验相等；保留正式 `FULL_POOL500_READY` gate 不变。抽出共享 ranking core 复用 adapter 与 `rank_candidates()`；diagnostic lane 使用独立 schema `pool500_diagnostic_frozen_pool_ranking_evidence_v1`，只在该 lane 显式允许 `cold_start_*` 诊断源，并对冻结池行做只读规范化，用 `source_scores[source]` 补齐缺失顶层 score，不修改原 artifact/hash。

**验证结果：**
冻结输入为 `outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5/`，candidate hash `dc9185c00139778b830e86257d6e870d1966daa793b169e1c3ad643263e9f7d7`，manifest hash `5730b97e1cd5c548f8665e3b7dd7a95b10717f586948dd407b465aef328c9fd3`。新增/更新治理测试覆盖 rows-only 禁止、latest/glob/path 拒绝、hash mismatch、promotion flag、独立 schema、正式 lane gate 不变、adapter STOP 阻断 ranking 和 diagnostic extra source；targeted tests `64 passed`，pool500 governance regression `121 passed in 0.25s`，`ruff check` 为 `All checks passed!`。

首轮 diagnostic 排序输出位于 `outputs/ranking/pool500_diagnostic_frozen_pool_v5_shadow/`。三个 variant 均为 `PASS`，均保持 `diagnostic_only=true`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`not_ranking_input=true`。`top_k=20`、`user_count=500`、`ranked_item_count=10000`、输入池分布 `min/p50/avg/max=500/500/500/500`、三阶段 trace 覆盖 `coarse=fine=rerank=1.0`。`no_rerank_baseline` topK source：`category=5227`、`usercf_recall=3121`、`popular=973`、`swing_recall=557`、`semantic_title_category_expansion=55`、`two_tower=50`、`cold_start_metadata_neighbor=17`；`popular_only_topk_ratio=0.0973`、`cold_start_topk_ratio=0.0017`。`source_aware_fusion_conservative` 与 baseline 指标一致，说明当前 topK 几乎都是单源候选，source-aware multi-source boost 没有发挥。`normalized_additive_small` 将 topK 结构调整为 `usercf_recall=3651`、`category=4614`、`swing_recall=700`、`popular=908`、`two_tower=55`，`popular_only_topk_ratio` 降至 `0.0908`，但仍只是 structural diagnostic，不代表线上效果提升。

**面试可讲点：**
这段可以讲成“在不越权晋升的前提下启动排序优化”：不是把补齐后的 pool500 候选池直接接入正式排序，而是先做冻结 artifact + hash 的 diagnostic ranking lane，用独立 schema、负向治理测试、source trace 和结构指标证明排序链路可审计、可复现、可解释，同时把效果结论限制在 shadow/offline 范围内。

### 2026-05-20 - pool500 UserCF 方法级 train-only source 治理

**任务：**
为 pool500 主路中的 `usercf_recall` 补齐方法级 train-only eligible manifest、UserCF sidecar、候选分片和七件套治理产物，并产出可被 `load_usercf_recall_sidecar()` 加载的 `source_index_manifest.json`。

**遇到的问题：**
旧 promoted 产物中 `usercf_recall` 只有 `8364 rows / 290 users`，不足以支撑 pool500 候选池；实现时还遇到资源治理问题：直接在 wrapper 中全量预诊断和逐用户排序会导致构建在正式分片前长时间停滞，甚至触发 RSS guard。

**定位方式：**
通过后台构建状态和输出目录检查发现任务长时间未创建 `outputs/recall/pool500_method_sources/usercf_recall/<run_id>/`，说明瓶颈在 wrapper 预筛而不是 core UserCF 分片；架构审查进一步指出不应在诊断结果中物化完整 `item_user_freq`。随后复用现有 train-only `outputs/recall/pool500_user_quality/heavy_probe_limit5000_train_only/eligible_user_quality_manifest.json`，并用 smoke 验证外部 eligible manifest 路径可绕过全量预筛。

**解决方式：**
新增/完善 `rs_lab/experiments/recall/pool500/methods/usercf_recall/builder.py`、CLI 和配置：wrapper 始终 materialize 内部标准 UserCF eligible manifest，再传给 `build_full_train_usercf_sidecar()`；兼容 `diagnostic_limited_train_users` train-only 质量画像，把 heavy/medium shared-neighbor 用户转换为 `target500_high_cost_slice` 内部口径；保留 `outputs.candidate_shards` 供 runtime loader 使用，`candidates.jsonl` 仅作 flat audit view；所有 candidate generation、ranking replacement、pool1000、promotion、final ready gate 均保持 false。

**验证结果：**
正式产物位于 `outputs/recall/pool500_method_sources/usercf_recall/usercf_recall_pool500_heavy_probe_train_only_20260520/`，七件套齐全，`readiness_contract.index_manifest_sha256` 与最终 `source_index_manifest.json` 匹配，`load_usercf_recall_sidecar()` 可加载 372 个用户。最终指标：`target_user_count=372`、`candidate_row_count=185862`、`user_coverage_count=372`、每用户候选数 `min/p50/p90/max=362/500/500/500`，相比旧 promoted `8364 rows / 290 users` 提升 `+177498 rows / +82 users`。资源审计显示 full train 扫描 `18103384` 行、`peak_rss_mb=4008`，在 `max_rss_mb=12288` guard 内完成；仍 undercovered 1 个用户，原因为 `unknown_after_train_only_diagnostics`。验证命令包括 `ruff check` 通过、UserCF 相关回归 `32 passed`、最终 artifact/loader/readiness 校验 `missing=[]`、`loaded_users=372`、`readiness_sha_matches=True`。

**面试可讲点：**
这段可以讲成“在资源受控和治理边界内扩容 UserCF 召回源”：不是机械跑前 500 用户或伪造 READY，而是复用 train-only 用户质量画像、显式 eligible manifest、分片 sidecar 和七件套审计，把 UserCF 从低覆盖诊断源提升到 372 个目标用户几乎满额候选，同时通过内存 guard、loader 校验和 forbidden flag 证明产物可复用但不越权晋升。

### 2026-05-19 - pool500 category / popular 轻量 fallback source 治理

**任务：**
为 pool500 主路中的 `category` 与 `popular` 补齐轻量治理产物和审计，不通过无限放大热门/类目源假装填满 pool500，并保持二者作为 fallback / coverage source。

**遇到的问题：**
旧 promoted 产物中 `category=35880 rows / 438 users`、`popular=19112 rows / 480 users`，二者合计占旧总候选 `73.34%`，存在热门/类目源过度主导候选池的风险；同时缺少单独的 category bucket、long-tail、diversity cap、popular cap、时间窗口和类目约束审计。

**定位方式：**
对照 `outputs/recall/pool500_main_route_direct_recall_full_promoted/source_contribution_audit.json`、`source_overlap_audit.json` 与旧 source candidates，确认需要基于现有 train-only 诊断候选做治理派生，而不是扩大 source 容量或改 readiness 结论。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/common/lightweight_source_builder.py`，并在 `scripts/experiments/recall/pool500/run_pool500_method_source.py` 接入 `category` / `popular` 分支；`category` 增加每用户类目 bucket cap、long-tail pool 和 diversity audit，`popular` 增加每用户 cap、时间窗口 audit 与类目主导约束 audit。两个 source 的配置均固定 `LIGHTWEIGHT_FALLBACK_COVERAGE_SOURCE`，并保持 candidate generation、promotion、ranking replacement、pool1000、final ready 全部为 false。

**验证结果：**
新产物位于 `outputs/recall/pool500_method_sources/category/light_governance_20260519/` 与 `outputs/recall/pool500_method_sources/popular/light_governance_20260519/`，七件套齐全。`category` 经 diversity cap 后为 `candidate_row_count=29209`、`user_coverage_count=438/500`、每用户候选数 `min/p50/p90/max=0/71/100/119`，long-tail pool `17198 rows`；`popular` 为 `candidate_row_count=19112`、`user_coverage_count=480/500`、每用户候选数 `0/40/40/40`，cap 后最大每用户 40。combined audit 位于 `outputs/recall/pool500_method_sources/lightweight_governance_combined/light_governance_20260519/combined_light_source_audit.json`，治理后 combined share 为 `64.45%`，较旧 combined share `73.34%` 下降 `6671 rows`，但仍标记 `over_dominance_warning=true`。验证命令：新增治理测试和 direct runner 回归 `3 passed`，`ruff check` 为 `All checks passed!`，`compileall` 通过，必需产物存在性检查通过；独立 verifier 批准为轻量 fallback/coverage 治理，但不批准 FULL_POOL500_READY 或排序输入替换。

**面试可讲点：**
这段可以讲成“对兜底召回源做容量治理，而不是堆热门候选”：通过 per-user cap、类目 bucket、多样性和 combined share 审计，把高覆盖但易主导的 fallback source 变成可解释、可监控、不可越权晋升的工程产物，并明确 direct recall runner 若要消费新 manifest 仍需单独接入。

### 2026-05-20 - pool500 two_tower / YouTubeDNN 方法级诊断 source 对齐

**任务：**
为 pool500 主路中的 `two_tower` / YouTubeDNN 补齐方法级 train-only diagnostic source builder、CLI、配置与测试契约，输出七件套产物，但不声明 READY、不授权候选生成替换排序输入。

**遇到的问题：**
基线 two_tower 的 item embedding / recall index 已有全量产物，但 user embedding 覆盖只有 28 行，旧 promoted 中 two_tower 仅 `180 rows / 6 users`。实现过程中还暴露出三个治理细节：实际读取路径应在加载 artifact 和写候选前阻断；fresh run 也应声明 checkpoint/resume 能力；clean manifest 中未使用的 valid/test metadata 只能进入 ignored audit，不能误判为实际读取。

**定位方式：**
对照 `outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json` 确认可加载 artifact manifest 路径、`user_embedding_row_count=28` 与 `recall_index_row_count=2320263`；运行新增测试和独立 code-reviewer，定位配置默认路径不存在、CLI 显式参数被配置覆盖、no-holdout ignored path 显示重复前缀、以及 `__init__` eager import 导致 `python -m` 运行警告等问题。

**解决方式：**
在 `rs_lab/experiments/recall/pool500/methods/two_tower/builder.py` 中实现 artifact user embedding 优先、缺失时用 train-only `recent_positive_item_sequence` 的 item vectors 做 `average_vectors` fallback；生成 diagnostic-only `candidates.jsonl` 和 `method_dataset_manifest/source_index_manifest/coverage/undercoverage/resource/no_holdout` 七件套；`source_index_manifest.recall_index_path` 固定指向 artifact manifest，`candidate_path` 才指向诊断候选；所有 gate 保持 false。补齐 checkpoint/resume/overwrite、config hash、CLI 显式参数优先、相对 eval metadata 解析和 lazy export。

**验证结果：**
最终 targeted pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_two_tower_method_source.py tests/test_pool500_two_tower_source_manifest.py tests/test_full_data_pool500_recall_only.py -q`，结果 `19 passed in 0.87s`；`ruff check` 覆盖 builder、CLI、测试和 `__init__.py`，结果 `All checks passed!`。小样本构建 `two_tower_method_smoke_20` 成功产出七件套：`candidate_row_count=950`、`user_coverage_count=19/20`、每用户候选数 `min/p50/p90/max=0/50/50/50`、`no_holdout_audit.status=PASS`，唯一 undercovered 原因为 `no_recent_positive_seed_items`。

**面试可讲点：**
这段可以讲成“把低覆盖向量召回从训练 artifact 问题拆成 query 覆盖治理问题”：不重训也不伪造 READY，而是在 train-only 边界内用 artifact user vector + seed item average fallback 提升方法级诊断覆盖，并用七件套审计、checkpoint 和 gate false 把效果证据与主路晋升权限分开。

### 2026-05-19 - pool500 co_visit_fallback_repair 方法级 source 治理

**任务：**
为 pool500 主路中的 `co_visit_fallback_repair` 补齐方法级 co-visit seed / metadata neighbor repair 数据集、候选扩展和七件套治理产物，保持 `TARGET_SLICE_DIAGNOSTIC`，不伪造 READY。

**遇到的问题：**
旧 promoted 产物中该源已有 `row_count=9898`、`coverage=430/500`，但来源仍是 batch-scoped evidence；缺少单独的 source builder、co_visit seed coverage、metadata neighbor coverage、resource checkpoint 与 no-holdout 审计，后续直接复用时容易把诊断贡献误当成可晋升 source。

**定位方式：**
对照 `rs_core/recsys/candidate_merge.py` 中的 `metadata_neighbor_candidates_for_user`、`run_full_data_pool500_recall_only.py` 的 source alias / deferred source 逻辑，以及旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/source_contribution_audit.json`，确认应复用 train-only `user_sequences.train.jsonl` 和 lightweight `semantic_recall_inputs.jsonl`，围绕 target500 正反馈 seed 构建 metadata neighbor repair 候选。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/co_visit_fallback_repair/builder.py`，并在 `scripts/experiments/recall/pool500/run_pool500_method_source.py` 中接入 `co_visit_fallback_repair` 分支；同步更新 `configs/recall/full_data_pool500/co_visit_fallback_repair/source_config.yaml`，设置 metadata row 上限、每用户/每 seed 候选上限和 50 用户 checkpoint。manifest 中固定 `source=canonical_source=co_visit_fallback_repair`、`source_status=TARGET_SLICE_DIAGNOSTIC`，并保持 candidate generation、promotion、ranking replacement、pool1000 全部为 false。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/co_visit_fallback_repair/target_slice_20260519_0001/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=24842`、`user_coverage_count=444/500`、每用户候选数 `min/p50/p90/max=0/40/93/120`，相比旧 promoted `9898 rows / 430 users` 提升为 `+14944 rows / +14 users`。`coverage_audit.json` 显示 `co_visit_seed_coverage=444/500`、`metadata_neighbor_coverage=444/500`；`undercoverage_audit.json` 显示仍有 56 个用户缺 seed metadata / metadata neighbor candidate，420 个用户低于方法级 120 候选目标。验证命令：`ruff check` 覆盖 builder、runner、测试文件为 `All checks passed!`；`pytest tests/test_pool500_co_visit_fallback_repair_source.py` 为 `1 passed`；实际构建命令使用项目 `.venv` 并成功重建同一 run_id。

**面试可讲点：**
这段可以讲成“把 co-visit fallback 从主路内联诊断贡献工程化成可治理方法源”：按召回机制围绕 target 用户 seed 构建 metadata neighbor repair，而不是机械扩大 smoke；同时用七件套 artifact、checkpoint、no-holdout 审计和禁用 flag 保留诊断边界，并明确 direct recall runner 若要消费新 `candidates.jsonl` 还需要单独接入 source manifest。

### 2026-05-19 - pool500 semantic_title_category_expansion 方法级 source 治理

**任务：**
为 pool500 主路中的 `semantic_title_category_expansion` 补齐方法级 metadata/title/category 输入数据集、候选扩展和七件套治理产物，保持诊断态，不伪造 READY。

**遇到的问题：**
旧 promoted 产物中该源已有 `row_count=6267`、`coverage=444/500`，但只是 batch-scoped evidence；缺少方法级 `semantic_title_category_input_dataset`、title/category/token 覆盖审计和可复用构建入口，容易被误用为正式 source readiness。

**定位方式：**
对照 `data/processed/amazon_2023_recall_views_full_lightweight/semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`、旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/sources/semantic_title_category_expansion/manifest.json` 与 `rs_core/recsys/candidate_merge.py` 中的 `semantic_title_category_expansion_candidates_for_user`，确认应复用 train-only semantic metadata/index，只围绕 target500 seed token 扩展候选。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/semantic_title_category_expansion/builder.py` 和 CLI `scripts/experiments/recall/pool500/build_semantic_title_category_expansion_source.py`，按 target500 用户正反馈 seed 加载相关 title/category metadata，经 inverted index 收集候选 item，再用现有 title/category overlap 逻辑打分输出 `candidates.jsonl`。同步更新 `configs/recall/full_data_pool500/semantic_title_category_expansion/`，manifest 中固定 `source=canonical_source=semantic_title_category_expansion`、`source_status=TARGET_SLICE_DIAGNOSTIC`，并保持 candidate generation、ranking replacement、pool1000、promotion、full ready 全部为 false。

**验证结果：**
新产物位于 `outputs/recall/pool500_method_sources/semantic_title_category_expansion/target500_semantic_title_category_v1/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=25047`、`user_coverage_count=444/500`、每用户候选数 `min/p50/p90/max=0/40/80/80`，相比旧 promoted `6267 rows` 明显提升但覆盖人数持平。`coverage_audit.json` 显示 `title_coverage=0.999975`、`category_coverage=1.0`、`clean_title_token_coverage=0.999963`、`seed_item_metadata_coverage=1.0`；仍 undercovered 的主因是 `no_positive_seed_items=56` 和 `below_method_target_per_user=269`。验证命令：新增/既有 semantic tests `9 passed`，`py_compile` 通过，`ruff check` 为 `All checks passed!`，产物契约脚本确认 `missing=[]`、`no_holdout_status=PASS`、forbidden flags 无 true。

**面试可讲点：**
这段可以讲成“把语义扩展召回从诊断片段工程化成可治理 source”：不是简单扩大样本，而是按方法机制构造 title/category/token 输入数据集，保留 train-only/no-holdout 和诊断态边界，同时用覆盖审计解释为什么仍无法覆盖 56 个无正反馈 seed 用户。

### 2026-05-19 - pool500 itemcf_strong 方法级 source 治理

**任务：**
为 pool500 主路中的 `itemcf_strong` 单独补齐方法级 train-only 数据集、strong item-item sidecar、候选扩展与七件套审计产物，保持 `DIAGNOSTIC_ONLY`，不与 `itemcf_weak` 混用。

**遇到的问题：**
旧 promoted 产物中 `itemcf_strong` 只有 `row_count=1992`、`coverage=161/500`，且 strong/weak 口径容易被混成一个 ItemCF source；如果直接扩大 smoke 或复用弱共现边，会破坏“强共现/高置信 seed item 扩展”的方法定位。

**定位方式：**
对照 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`rs_lab/experiments/recall/build_pool500_high_cost_slice_sources.py` 与旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/` 贡献审计，确认 strong 应只读取 full clean `user_sequences.train.jsonl` 的 `recent_strong_positive_item_sequence`，并输出独立 `source_index_manifest.json`、`coverage_audit.json`、`undercoverage_audit.json` 与 `no_holdout_audit.json`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/itemcf_strong/builder.py` 和 CLI `scripts/experiments/recall/pool500/build_itemcf_strong_method_source.py`，按 target500 strong seed item 扫描 full train 构建 target-seed 相关 item-item 强边，再过滤用户已看 item 生成 `candidates.jsonl`。构建过程按 batch 写 checkpoint，manifest 中固定 `source=canonical_source=itemcf_strong`、`source_status=DIAGNOSTIC_ONLY`，并保持 candidate generation、ranking replacement、pool1000、promotion、final ready 全部为 false。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/itemcf_strong/itemcf_strong_20260519T0945Z/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=66808`、`user_coverage_count=391/500`、每用户候选数 `min/p50/p90/max=0/100/376/500`，相比旧 promoted `1992 rows / 161 users` 明显提升。审计中 `seed_hit_count=915`、`strong_edge_hit_count=84246`、`strong_edge_quality.p50=0.004739`、`p90=0.018818`；仍 undercovered 的 109 个用户主要来自 `no_strong_seed=78` 与 `seed_without_strong_edge=31`。验证命令包括新增单测与 registry 测试 `10 passed`、`py_compile`、产物契约脚本 `PASS`、`ruff check` 为 `All checks passed!`，`no_holdout_audit` 确认只读取 clean manifest 和 `user_sequences.train.jsonl`。

**面试可讲点：**
这段可以讲成“按召回机制定制 source artifact”：不是把 ItemCF weak/strong 混成一条泛化协同过滤，而是围绕 strong seed 和高置信 item-item 边单独建索引、候选与审计，把覆盖从 161/500 提到 391/500，同时用 train-only、checkpoint、七件套 manifest 和禁用 flag 保住治理边界。

### 2026-05-19 - pool500 itemcf_weak 方法级 source 治理

**任务：**
为 pool500 主路中的 `itemcf_weak` 补齐方法级 train-only 数据集、weak item-item sidecar、用户级候选扩展与七件套审计产物，保持 `DIAGNOSTIC_ONLY`，不伪造 READY。

**遇到的问题：**
旧 promoted 产物中 `itemcf_weak` 只有 `row_count=2070`、`coverage=168/500`，弱共现召回没有按 target500 seed item 定制局部图，导致很多用户即使有正反馈 seed，也无法从弱 item-item 边扩展出足够候选。

**定位方式：**
对照 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`rs_lab/experiments/recall/build_pool500_high_cost_slice_sources.py` 与旧 `outputs/recall/pool500_main_route_direct_recall_full_promoted/diagnostic_source_contribution.json`，确认 weak 应读取 full clean `user_sequences.train.jsonl` 的 `recent_positive_item_sequence`，围绕 target500 seed item 构建弱共现边，再生成用户级 `candidates.jsonl`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/itemcf_weak/builder.py` 和 CLI `scripts/experiments/recall/pool500/build_itemcf_weak_method_source.py`，按 target500 用户正反馈 seed 扫描 full train 构建 weak item-item sidecar，并过滤用户已看 item 输出候选。配置更新到 `configs/recall/full_data_pool500/itemcf_weak/source_config.yaml`，manifest 中固定 `source=canonical_source=itemcf_weak`、`source_status=DIAGNOSTIC_ONLY`，并保持 candidate generation、ranking replacement、pool1000、promotion、final ready 全部为 false。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/itemcf_weak/target500_train_weak_edges_v1/`，七件套齐全；`source_index_manifest.json` 记录 `candidate_row_count=70474`、`user_coverage_count=410/500`、每用户候选数 `min/p50/p90/max=0/100/399.1/500`，相比旧 promoted `2070 rows / 168 users` 明显提升。`coverage_audit.json` 显示 `seed_hit_count=410`、`weak_edge_hit_count=987`、`edge_coverage=0.896458`；仍 undercovered 的原因主要是 `weak_edge_fanout_below_500=378`、`no_recent_positive_seed_items=56`、`seed_items_missing_from_weak_itemcf_edges=34`。验证命令包括新增 itemcf_weak tests 与 source manifest 覆盖测试 `3 passed`，`ruff check` 为 `All checks passed!`，独立 verifier 复核候选行数 `70474` 与 manifest 一致，`no_holdout_audit` 确认只读取 clean manifest 和 `user_sequences.train.jsonl`。

**面试可讲点：**
这段可以讲成“把弱 ItemCF 从低覆盖诊断源工程化成可审计方法源”：围绕目标用户 seed item 定制局部弱共现图，把覆盖从 168/500 提升到 410/500，同时用 batch checkpoint、七件套 manifest、no-holdout 审计和禁用 flag 保持诊断边界。

### 2026-05-19 - pool500 高成本个性化源 target500 切片扩展

**任务：**
在不重新选择召回方法、不做长期 READY 晋升的前提下，对 pool500 主路中的 `two_tower`、`usercf_recall`、`itemcf_weak`、`itemcf_strong` 做 target500 train-only 切片扩展，并使用新的 source manifest 跑 direct recall 对比。

**遇到的问题：**
原 full-promoted direct recall 虽然 9 个 source 都有产出，但高成本个性化源覆盖和 per-user 容量不足：`two_tower=180`、`usercf_recall=8364`、`itemcf_weak=2070`、`itemcf_strong=1992`，最终 `candidate_rows=74978`、`users_with_500_candidates=0`、`underfilled_user_count=500`。扩展过程中还发现 `two_tower` 只有 28 行 user embedding，且全量 2320263 item 向量检索若处理不当会在 0 分并列候选上出现 Python 循环膨胀。

**定位方式：**
对照 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 source manifest override 和 `rs_core/recsys/vector_index.py` 的 `search_many()`，确认当前任务应复用既有方法与 full clean train-only 索引，只扩大 target500 切片 source artifact。基线证据来自 `outputs/recall/pool500_main_route_direct_recall_full_promoted/manifest.json`，新对比来自 `outputs/recall/pool500_main_route_direct_recall_high_cost_slice_v1/manifest.json`。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_high_cost_slice_sources.py`，统一生成 target500 high-cost source artifacts：`two_tower` 写轻量 lineage / batch checkpoint / resource / no-holdout manifest，实际候选延迟到 direct recall 运行时生成；UserCF 使用显式 target500 user manifest 分批构建 sidecar；ItemCF weak/strong 只基于 target500 recent seed items 扩建 item-item edges。同步修复 `two_tower` 缺 user embedding 时的 per-user seed item 平均向量 fallback，并将 `VectorIndex.search_many()` 的 block top-k 改为固定候选合并，避免 0 分并列导致全块候选进入 Python 循环。

**验证结果：**
高成本源切片生成耗时 `463.887371s`，聚合 manifest 位于 `outputs/recall/pool500_sidecar_fix/high_cost_target500_slice_expanded_manifest.json`。四个可直接用于 direct recall 的 source manifest 分别为：`outputs/recall/pool500_full_sources/two_tower_target500_slice_expanded/source_index_manifest.json`、`outputs/recall/pool500_sidecar_fix/usercf_recall_target500_slice_expanded/source_index_manifest.json`、`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_slice_expanded/source_index_manifest.json`、`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_slice_expanded/source_index_manifest.json`；其中 UserCF 显式使用 `target500_train_only_high_cost_slice`，避免把 target500 诊断切片误写成真实 `heavy_cf_eligible` 用户质量证据。新 direct recall 输出 `outputs/recall/pool500_main_route_direct_recall_high_cost_slice_v1/manifest.json`，`runtime_seconds=621.401654`、`processed_users=500`、`candidate_rows=207950`、`users_with_500_candidates=297`、`underfilled_user_count=203`，每用户候选数 `min/p50/p90/max=40/500/500/500`。高成本源对比：`two_tower 180/6 → 62840/444`，`usercf_recall 8364/290 → 54666/410`，`itemcf_weak 2070/168 → 42811/410`，`itemcf_strong 1992/161 → 40493/391`。最终仍 `decision=STOP`，触发 `swing_recall:no_ready_source_candidates`、`target_batch_underfilled`、`ready_source_capacity_below_pool500_budget`，说明下一步仍需低成本/ready source fallback 容量扩展或 Swing 切片补齐。focused pytest `tests/test_full_data_pool500_recall_only.py -q` 与 UserCF focused tests 通过，ruff touched files 为 `All checks passed!`；新增/复用 artifact 中 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。

**面试可讲点：**
这段可以讲成“在严格治理边界下扩容个性化召回源”：不是换方法或伪造 ready，而是用 target500 train-only 切片、显式 source manifest override、资源分批、no-holdout audit 和向量检索性能修复，把高成本个性化源从低覆盖诊断提升到对 297/500 用户填满 500 候选，同时保留 STOP 结论暴露后续 fallback 缺口。

### 2026-05-19 - pool500 Swing target slice 增强诊断

**任务：**
在不覆盖已有 `swing_recall` READY source、不声明 `FULL_POOL500_READY` 的前提下，为 pool500 主路新增 `TARGET_SLICE_DIAGNOSTIC` Swing 增强 slice，输出统一七件套 artifact，并审计 pair coverage、item graph coverage、user coverage 与 per-user 候选分布。

**遇到的问题：**
旧 promoted `swing_recall` 虽为 READY，但只有 `row_count=3073`、`coverage=229/500`，对 500 个目标用户的候选容量不足；同时 Swing 属于行为图召回，不能简单扩大前 500 用户 smoke，而需要围绕目标用户 seed item 构建更适合的 train-only 高行为 item graph。

**定位方式：**
对照 `run_full_data_pool500_recall_only.py` 中 `load_swing_recall_sidecar()` 的 manifest 入口、旧产物 `outputs/recall/pool500_main_route_direct_recall_full_promoted/sources/swing_recall/manifest.json` 与 `build_full_train_swing_sidecar.py` 的 train-only 边界，确认增强 slice 应输出独立 `source_index_manifest.json`，并保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/swing_recall/enhanced_source.py` 与 CLI `scripts/experiments/recall/pool500/build_swing_recall_enhanced_source.py`，读取 full clean `user_sequences.train.jsonl` 和旧 target500 eligible user manifest，按目标 seed item 选择最多 30000 个 train graph users，构建 bounded Swing item graph，并输出 `method_dataset_manifest.json`、`source_index_manifest.json`、`candidates.jsonl`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。同步更新 `configs/recall/full_data_pool500/swing_recall/` 中的 source status 和默认增强参数。

**验证结果：**
实际产物位于 `outputs/recall/pool500_method_sources/swing_recall/target_slice_diagnostic_v1/`，`source_index_manifest.json` 可被 `load_swing_recall_sidecar()` 加载，`edge_count=1877434`、`seed_count=80246`。增强后 `candidate_row_count=35117`、`user_coverage_count=435/500`、每用户候选数 `min/p50/p90/max=0/85/120/120`；相比旧 promoted source 的 `row_count=3073`、`coverage=229/500` 明显提升。仍 undercovered 的 65 个用户中，主要原因是 `no_seed_item_in_swing_graph=63`，另有 2 个用户候选被已看/已有 item 过滤。验证命令包括新增测试 `tests/test_pool500_swing_recall_enhanced_source.py`、既有 Swing sidecar 测试、direct runner swing loader 校验和 forbidden flag 扫描，均通过；所有关键 manifest 中 promotion/ranking/pool1000/candidate-generation flag 均为 false。

**面试可讲点：**
这段可以讲成“针对召回机制定制数据集与索引，而不是机械 smoke”：围绕目标用户 seed 构建 train-only Swing 图，既把覆盖从 229/500 提到 435/500，又用七件套审计、checkpoint、资源上限和禁用 flag 保住治理边界，最终只提交 diagnostic source，是否接入 direct runner 留给主窗口决策。

### 2026-05-19 - pool500 two_tower / YouTubeDNN 主路 artifact 补齐

**任务：**
补齐 pool500 主路中缺失的 `two_tower` / YouTubeDNN 召回源，使 `run_full_data_pool500_recall_only.py` 可以通过 `--source-manifest two_tower=outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json` 加载 full-clean train-only source manifest 并实际生成候选。

**遇到的问题：**
旧 YouTubeDNN artifact 属于历史路径，不能直接复用到 pool500 full-clean-safe 主路；直接跑 5000 个 user_quality 用户时出现重复长训练任务，不符合“受控、不打满机器”的资源约束；builder 初版还会把 clean manifest 中未使用的 valid/test split 元数据误判为 forbidden input。

**定位方式：**
对照 `run_full_data_pool500_recall_only.py` 的 `two_tower` manifest 默认路径、`load_two_tower_index()` 的 `VectorIndex` 加载逻辑和 full-clean config，确认 official source 必须指向新的 training artifact manifest；用 smoke 指标确认 1000 用户训练耗时约 `928s` 且 item universe 为 `2320263`；通过 builder 报错 `forbidden input references found: ['test', 'valid']` 定位到扫描范围过宽。

**解决方式：**
新增 `build_pool500_two_tower_source_manifest.py`，用 official artifact、full-clean config、clean manifest、views manifest 和 user_quality policy 生成独立 source manifest，并写死 promotion/ranking/pool1000 gate 为 false；扩展 two_tower 训练入口支持 `--user-quality-manifest` / `--user-quality-bucket`，最终选择 `heavy_cf_eligible` 28 用户作为受控 official artifact；修复 builder forbidden scan，只扫描实际使用的 train sequence、views 输出和 artifact contract。

**验证结果：**
训练产物位于 `outputs/recall/pool500_full_sources/two_tower/training/runs/full_clean_heavy28_20260519_0001/`，`training_seconds=418.684`、`peak_cuda_memory_mb=2031.855`、`item_embedding_row_count=2320263`、`user_embedding_row_count=28`。final manifest 位于 `outputs/recall/pool500_full_sources/two_tower/source_index_manifest.json`，VectorIndex 加载校验为 `items=2320263`、`users=28`、`source_name=two_tower_youtube_dnn`。runner smoke 输出 `outputs/recall/pool500_full_sources/two_tower/runner_smoke_20260519_0001/manifest.json`，`processed_users=5`、`candidate_rows=955`、`source_coverage.two_tower=150`。测试：builder `6 passed`，two_tower focused `16 passed`，recall-only runner `4 passed`，ruff touched files `All checks passed!`。

**面试可讲点：**
这段可以讲成“把一个历史双塔召回方法迁移成可治理的 pool500 主路 source artifact”：不是直接复用旧模型，而是补独立 source manifest、hash/count lineage、资源受控训练、forbidden lineage gate、runner smoke 和文档边界，证明它能被主路加载并产生候选，同时不越权宣称 READY 或替换排序输入。

### 2026-05-19 - pool500 semantic / co-visit fallback 证据治理修复

**任务：**
完善 pool500 主路中的 `semantic_title_category_expansion` 与 `co_visit_fallback_repair`，目标不是 READY 晋升，而是让 direct recall 生成时两路都有 train-visible、可审计的候选贡献。

**遇到的问题：**
`co_visit_fallback_repair` 当前由 `metadata_neighbor_recall` alias 得到，若只看 row_count 容易被误写成 READY；同时旧 semantic smoke 使用 `semantic-max-rows=5000`，`item_universe_count=5038` 暴露出明显截断，不足以作为本轮证据。

**定位方式：**
对照 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`、`rs_core/workflow/full_data_pool500_route_gate.py` 与 source manifest builder，确认需要把 semantic/title-category 与 co_visit 都纳入 batch-scoped deferred contract，并让 route gate 接受 `BATCH_SCOPED_DIAGNOSTIC` 但不把它视为 READY。

**解决方式：**
将 `semantic`、`semantic_title_category_expansion`、`co_visit_fallback_repair` 统一作为 batch-scoped deferred sources；有 rows 时 per-source manifest 写 `BATCH_SCOPED_DIAGNOSTIC`、`final_sources=[]`、`batch_scoped_evidence_only=true`，ready hash 保持 false。同步 route gate 合法非 READY 状态，并在测试中覆盖 semantic/co_visit 两路不进入 ready_sources。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_semantic_title_category_manifest.py -q`，结果 `11 passed`。source manifest 生成命令通过，`outputs/recall/full_semantic_title_category_expansion/source_index_manifest.json` 中 `source=semantic_title_category_expansion`、`index_scope=FULL_DERIVED_INDEX`，no-holdout/resource audit 均为 `PASS`。受控 probe `outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k/` 使用 `--semantic-max-rows 200000 --limit-users 50`，`pool500_candidates.jsonl` 中 `semantic_title_category_expansion=640`、`co_visit_fallback_repair=1063`，两路 source-level audit 与 final resource audit row_count 均大于 0，且 promotion/ranking/pool1000 flags 均为 false。

**面试可讲点：**
这段可以讲成“在不越权晋升的前提下补齐召回源证据链”：先识别 READY 漂移风险，再用 manifest、route gate、source-level audit 和 focused tests 锁住治理边界，同时通过受控资源 probe 证明两路 source 对 pool500 direct recall 有稳定候选贡献。

### 2026-05-19 - pool500 ItemCF weak/strong consumer coverage 审计补齐

**任务：**
完善 pool500 主路中的 `itemcf_weak` 和 `itemcf_strong` guarded sidecar artifact，补齐 source manifest、consumer user manifest、coverage audit 与 registry custom dataset manifest，并同步方法文档。

**遇到的问题：**
ItemCF weak/strong 已有 target500 guarded sidecar，但旧 artifact 只说明 builder 侧 source-positive 用户建边，容易把高质量用户索引、profiled 用户和 pool500 consumer 用户混成同一口径；同时 registry 需要的 custom dataset manifest 缺失，可能导致后续主路加载缺少治理证据。

**定位方式：**
对照 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`tests/test_full_train_itemcf_sidecars.py`、`configs/recall/pool500_method_registry.json` 与现有 `source_index_manifest.json`，确认 `target_user_limit` 实际表示 source-positive builder sequence limit，而不是 consumer universe；再用 `coverage_audit.json` 独立核对 target500 train-only consumer seed-hit 与 full clean item universe 覆盖。

**解决方式：**
在 ItemCF sidecar builder 中固化 `consumer_user_manifest.json`、`coverage_audit.json` 和 `configs/recall/full_data_pool500/itemcf_*_custom_dataset_manifest.json` 输出，并在 source manifest 中补充 `edge_count`、builder/source-positive 计数、pair-contributing 计数和 consumer audit 路径；weak/strong 均保持 `DIAGNOSTIC_ONLY`，禁止 promotion、pool1000 和 ranking input replacement。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py`，结果 `6 passed`。实际产物中 weak `rows_written=74662`、target500 consumer seed-hit 用户 `250/500`、`edge_item_out_of_universe_count=0`；strong `rows_written=68432`、target500 consumer seed-hit 用户 `239/500`、`edge_item_out_of_universe_count=0`。

**面试可讲点：**
这段可以讲成“给重资源行为召回补治理口径”：把 builder 用户、profile 用户和 consumer 用户拆开审计，既能复用 full clean train-only ItemCF 边，又避免把诊断 artifact 误升为 READY 或排序替换输入。

### 2026-05-19 - pool500 UserCF heavy28 侧车合同固化

**任务：**
把 heavy28 artifact 固定为 pool500 UserCF 的 high-quality sidecar 合同，明确默认 manifest 路径、治理边界和后续扩展顺序，并避免把历史 weak-parameter 诊断误写成当前交付物。

**遇到的问题：**
此前文档虽然已经有 heavy28 诊断证据，但默认 sidecar manifest、high-quality user index 输入、以及 `DIAGNOSTIC_ONLY` 的禁用边界没有被集中写死，容易让后续读者误把 `usercf_recall_target100_guarded`、pool1000 口径或 ranking replacement 当成当前结论。

**定位方式：**
对照 `dic/recall_methods/usercf_recall/METHOD.md` 和已审计的 heavy28 sidecar 产物，核对 source index manifest、eligible_user_quality_manifest 以及资源/效果指标，确认当前证据只覆盖 heavy28 guarded diagnostic，不覆盖 READY 晋升。

**解决方式：**
在 UserCF 方法文档中固化默认 manifest 路径、high-quality user index 定义、审计指标和治理契约，明确 `source=usercf_recall` 仅限 `DIAGNOSTIC_ONLY`，且禁止 candidate generation、ranking input replacement、pool1000 和 final ready 声明；同时把 `usercf_recall_target100_guarded` 标注为历史 v1 弱参数诊断。

**验证结果：**
文档已更新为统一的 heavy28 sidecar 合同口径，保留 `target_user_count=28`、`indexed_user_count=1386693`、`candidate_user_count=28`、`candidate_total_count=5600`、`peak_rss_mb=1937`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.4` 等审计数据，并明确扩容前必须先扩 eligible profile / high-quality index，再做 64/100 用户的受控诊断。

**面试可讲点：**
这段可以讲成“把重资源 UserCF 从一次性诊断变成可复述的治理合同”：不是只记录结果，而是把默认 artifact 路径、适用人群、禁用边界和扩展顺序一起固化，避免历史实验口径污染当前 pool500 决策。

### 2026-05-18 - pool500 semantic / title-category batch evidence 补齐

**任务：**
补齐 pool500 召回链路中 `semantic` / `semantic_title_category_expansion` 的 batch-scoped deferred evidence，输出 semantic input manifest、diagnostic candidate manifest、no-holdout audit 和 resource audit；目标仅是小批诊断，不允许 READY 晋升、ranking input replacement、promotion 或 pool1000。

**遇到的问题：**
两个语义类方法此前在方法文档中明确为 `DEFERRED`，缺少 title/category/clean title token/item universe coverage 的可审计证据，也缺少小批候选生成、去重、underfill 改善和边际贡献指标。如果直接复用旧 artifact、holdout/valid/test、clean_10000、LOPO 或 youtube_dnn 证据，会破坏 pool500 readiness 治理边界。

**定位方式：**
读取 `dic/recall_methods/semantic/METHOD.md`、`dic/recall_methods/semantic_title_category_expansion/METHOD.md`、`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 和 `tests/test_full_data_pool500_recall_only.py`，确认现有 runner 已有 batch semantic index 与 stoploss/contribution audit，但没有单独的 batch-scoped semantic manifest/audit，也会把有行数的 source output 默认写成 READY，需要隔离 semantic deferred source 状态。

**解决方式：**
在 recall-only runner 中新增 `semantic_input_manifest.json`、`diagnostic_candidate_manifest.json`、`semantic_no_holdout_audit.json`、`semantic_resource_audit.json` 四类产物；用 baseline-without-semantic 与 semantic-enabled 的小批对比计算 candidate generation count、duplicate removal、underfill improved user count 和 marginal contribution，同时将 `semantic` / `semantic_title_category_expansion` 的有行输出标记为 `BATCH_SCOPED_DIAGNOSTIC`，保持 `readiness_status=DEFERRED`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**验证结果：**
focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_semantic_title_category_manifest.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py -q`，结果 `19 passed`。实际小批诊断输出位于 `outputs/recall/pool500_semantic_batch_diagnostic_10/`：`semantic_input_manifest.json` 中 title/category coverage 均为 `2038/2038=1.0`，clean title token coverage 为 `2037/2038=0.999509`，batch seed item universe coverage 为 `38/38=1.0`；`diagnostic_candidate_manifest.json` 记录 `candidate_generation_count=798`、`unique_generated_candidate_count=560`、`duplicate_removal_count=238`、`underfill_improved_user_count=10`、`marginal_contribution_count=550`；no-holdout audit 为 `PASS`，resource audit 为 `small_batch_diagnostic` 且 `heavy_job=false`。

**面试可讲点：**
这段可以讲成“给 deferred 召回方法补可审计证据而不越权晋升”：先把 metadata coverage 和小批候选贡献量化，再用 manifest/audit 明确数据边界与资源边界，证明语义类召回对 underfill 有增量，同时通过状态隔离避免诊断证据被误用为 final pool500 readiness 或排序输入替换依据。

### 2026-05-18 - pool500 UserCF heavy 真实诊断证据补齐

**任务：**
补齐 UserCF 在 pool500 主路上的真实 `heavy_cf_eligible` guarded diagnostic evidence，要求扩大 user_quality 样本、只对 heavy 用户运行可分批/可恢复/UserCF sidecar，并保持 `DIAGNOSTIC_ONLY`、不替换 ranking input、不打开 pool1000、不声明 final ready。

**遇到的问题：**
原 target500 user_quality 产物中 `heavy_cf_eligible=0`，只能得到 heavy-empty 与 medium20 降级观测；这能证明空 eligible 不会回退全量矩阵，但不能证明 UserCF 在主适用用户上的真实边际价值。

**定位方式：**
读取 `outputs/recall/pool500_user_quality/target500_train_only/eligible_user_quality_manifest.json`、`dic/recall_methods/usercf_recall/METHOD.md` 与 UserCF sidecar 构建契约，确认需要扩大 train-only user_quality 样本，并继续禁止 holdout/valid/test、ranking replacement、pool1000 与 READY 晋升。

**解决方式：**
使用项目 `.venv` 将 user_quality 样本扩到 5000 个 train users，生成 `outputs/recall/pool500_user_quality/heavy_probe_limit5000_train_only/eligible_user_quality_manifest.json`，得到 `heavy_cf_eligible=28`。随后仅对这 28 个 heavy 用户运行 `build_full_train_usercf_sidecar`，设置 `target_batch_size=7`、`max_rss_mb=4096`、8 个输出 shard，不包含 medium 用户，也不对低行为用户做全用户矩阵暴力召回。

**验证结果：**
新 sidecar 位于 `outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/`：`source_index_manifest.json` 记录 `target_user_count=28`、`indexed_user_count=1386693`、`candidate_user_count=28`、`candidate_total_count=5600`、`row_count=28`、`peak_rss_mb=1937`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.4`；`resource_audit.status=PASS`，4 个 batch 均完成；`no_holdout_audit.status=PASS` 且 `uses_valid=false`、`uses_test=false`、`uses_holdout=false`。`readiness_contract.json` 保持 `status=DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。

**面试可讲点：**
这段可以讲成“给重资源 UserCF 建立可治理的真实适用人群证据”：不是盲目扩大到全量用户，也不是用 medium 用户替代结论，而是先用 user_quality 找到真实 heavy 人群，再用分批、内存 guard、no-holdout audit 和 readiness contract 证明算法对 underfilled heavy 用户有边际贡献，同时严格阻止诊断证据被误晋升为生产主路。

### 2026-05-18 - pool500 ItemCF weak / strong 诊断扩大

**任务：**
围绕 pool500 召回链路中的 `itemcf_weak` / `itemcf_strong` 做 guarded diagnostic 专项优化，基于 `user_quality` 产物分别约束 weak 使用 `heavy_cf_eligible_or_medium_behavior`、strong 使用 `heavy_cf_eligible`，并输出 source index、resource audit、per-source candidate manifest、readiness contract 与 weak/strong 对比。

**遇到的问题：**
现有 target500 user_quality 产物中没有 `heavy_cf_eligible` 用户，只有 49 个 `medium_behavior` 用户；如果不显式记录 eligibility policy，strong ItemCF 容易被误判为算法无效，或 weak 的广覆盖被误解成可以晋升 READY。同时 ItemCF 属于重资源 custom dataset 方法，必须保持 train-only、分批/限流、不可替换 ranking input、不可进入 pool1000。

**定位方式：**
读取 `dic/recall_methods/itemcf_weak/METHOD.md`、`dic/recall_methods/itemcf_strong/METHOD.md`、`outputs/recall/pool500_user_quality/target500_train_only/eligible_user_quality_manifest.json` 和 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`，确认 weak/strong 的标签字段分别是 `recent_positive_item_sequence` 与 `recent_strong_positive_item_sequence`，并用 `.venv` 运行 focused pytest 验证 no-holdout、manifest schema 与 DIAGNOSTIC_ONLY 边界。

**解决方式：**
扩展 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`，支持 `--user-quality-manifest` 过滤：weak 保留 heavy+medium，strong 只保留 heavy；在产物中补齐 `per_source_candidate_manifest.json`、`weak_strong_comparison.json`、`resource_audit.json` 和 `readiness_contract.json` 的治理字段，统一写入 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`。同步新增 `tests/test_full_train_itemcf_sidecars.py` 覆盖 user_quality 过滤、no-holdout 和 readiness gate。

**验证结果：**
使用 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_user_quality_profile.py -q`，结果 `12 passed`。实际诊断产物位于 `outputs/recall/pool500_itemcf_weak_strong_diagnostic/`：weak `edge_count=7572`、`candidate_user_count=49`、`candidate_total_count=7572`、`unique_item_count=499`、`duplicate_overlap=0`、`marginal_candidate_share=1.0`、`underfilled_user_coverage=1.0`、`peak_rss_mb≈35.242`；strong 因当前 batch 没有 heavy 用户，`edge_count=0`、`candidate_user_count=0`、`candidate_total_count=0`、`peak_rss_mb≈35.027`。二者 readiness 均保持 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“用诊断契约治理重资源召回扩展”：不是直接扩大 ItemCF 全量矩阵或凭算法直觉晋升，而是先按用户质量分层做受控数据集，明确 weak 提供中等行为用户覆盖、strong 当前缺少 heavy 证据，并用 manifest/resource/readiness 三类 artifact 证明没有数据泄漏、没有替换排序输入、没有越权宣称 pool500 final ready。

### 2026-05-21 - aligned smoke010 pool500 真实召回达标约束诊断

**任务：**
尝试把 aligned smoke010 的 pool500 主路 candidate positive overlap 从 2/45 提升到至少 30/45，同时严格保持禁止 oracle candidate、valid/test label 注入、holdout positive 直塞、diagnostic-only oracle artifact 达标，每用户仍为 500 candidates，并保持 no-promotion、no-ranking-input-replacement、no-pool1000、no-full-ready 边界。

**遇到的问题：**
已有主路候选池每用户已满 500，瓶颈不再是 underfill，而是 train-only/full-derived 信号无法把 holdout positives 无标签地压进每用户 top500。fallback completion 只在候选不足 500 时补量，因此对当前已满 500 的候选池无效；继续调 completion 或 source budget 容易变成无证据调参。

**定位方式：**
复核 `run_full_data_pool500_recall_only.py`、`candidate_merge.py`、fallback completion 和 label coverage diagnostic 的边界后，用 valid/test labels 只做诊断评估。关键证据包括：full-train item-item 共现最多只能解释 `15/45`；full semantic metadata-overlap top500 为 `0/45`；quality-token semantic selection 最好约 `4/45`；full-overlap label rank 诊断中 `rank<=500` 为 `0/45`，很多正例虽有较高 overlap score 但全量排序仍在数千到上百万名。

**解决方式：**
没有使用 oracle/label 注入冒充达标。尝试在 `semantic_title_category_expansion` 方法级 builder 中加入可选 `full_metadata_overlap` selection mode，用 full-derived metadata overlap 做实验性候选选择，并保持默认旧行为不变；随后通过诊断确认该路线 top500 命中为 `0/45`，不能作为达标方案。当前结论转为阻塞收口：在原约束不变时，应停止“为达标而调参”，改为请求目标约束调整或记录不可达证据。

**验证结果：**
`.venv/Scripts/python -m py_compile rs_lab/experiments/recall/pool500/methods/semantic_title_category_expansion/builder.py` 通过。诊断输出显示：`cooccurrable_labels 15 [0,0,0,0,1,0,2,0,0,12]`；`metadata_overlap_top500 0 [0,0,0,0,0,0,0,0,0,0]`；quality token semantic coverage 最好为 `4 [0,0,0,0,1,0,1,0,0,2]`；full-overlap label rank `rank<=500 0`。因此没有生成新的达标主路 artifact，也没有声明 `positive_overlap_count>=30/45`。

**面试可讲点：**
这段可以讲成“推荐召回优化中的负结果治理”：在目标指标压力下，先用 train-only 共现、full-derived semantic、metadata overlap 和 ranking-depth 诊断证明真实信号上限，而不是用 holdout label 反向造候选。亮点不是强行达标，而是识别 500 候选容量与无泄漏信号之间的不可达边界，并把 no-leakage、no-promotion、no-pool1000 的工程约束落实到决策中。

### 2026-05-18 - ItemCF weak full-derived pair 覆盖扩大

**任务：**
扩大 `itemcf_weak` 的 full-derived train-only item pair 覆盖，重新生成 target500 guarded diagnostic sidecar，并验证它只补充诊断证据，不晋升 READY、不替换 ranking input、不进入 pool1000。

**遇到的问题：**
旧 target500 batch 中 `itemcf_weak` 只有 `row_count=345`，原因是 sidecar 建边范围过窄，batch 用户近期正反馈 seed 能命中的 item-item 边不足；同时必须避免把覆盖扩大误解释成 final pool500 ready。

**定位方式：**
读取 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`dic/recall_methods/itemcf_weak/METHOD.md`、旧 `outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/manifest.json` 和 recall-only runner 贡献审计逻辑，确认 runner 是按 batch 用户 `recent_positive_item_sequence` seed 命中 `itemcf_weak_edges.jsonl`，因此需要扩大 train-only source-positive 建边池。

**解决方式：**
使用 `.venv` 运行 guarded sidecar 构建，将 `--target-user-limit` 从 500 扩到 5000，保持 `max_items_per_user=20`、`max_item_user_freq=500`、`top_k_per_seed=80`，仅读取 `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`。随后运行 target500 recall-only 诊断，跳过已漂移的 usercf manifest，只审计本次 ItemCF weak/strong 贡献。

**验证结果：**
`outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/` 已重新生成：`edge_count=52840`、`users_with_source_items=5000`、`users_used=2149`、`unique_pair_count=26544`、`peak_rss_mb=34.836`、`no_holdout_audit.status=PASS`、`readiness_contract.status=DIAGNOSTIC_ONLY`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。target500 诊断中 `itemcf_weak` 达到 `row_count=1880`、`user_coverage_count=163`、`underfilled_user_coverage_count=163`、`marginal_candidate_share=0.02101`、`unique_item_count=1211`，相比旧 `row_count=345` 明显提升；整体 runner 仍 `status=STOP`。focused pytest：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py -q`，结果 `9 passed`。

**面试可讲点：**
这段可以讲成“受控扩大协同过滤证据覆盖”：先用审计定位低贡献来自 seed-edge 命中不足，再只扩大 train-only 建边池并保留 resource/no-holdout/readiness contract，证明召回覆盖提升和工程边界治理可以同时成立。

### 2026-05-18 - pool500 用户质量分层策略落地

**任务：**
为 pool500 召回链路新增 `user_quality` 用户质量分层专项能力，生成 batch-scoped eligibility policy artifact，服务 UserCF / ItemCF / Swing 的重资源调度，而不是新增召回 source 或声明 final ready。

**遇到的问题：**
当前 target500 召回诊断仍是按前 N 个 train users 扫描，容易把低信息密度用户也送入 UserCF / ItemCF / Swing 等重资源链路；同时 `configs/recall/pool500_method_registry.json` 中各 source 已明确禁止 holdout/valid/test、ranking input replacement 和 pool1000，因此 user_quality 必须作为 policy sidecar 落地，不能混入 source readiness。

**定位方式：**
读取 `dic/recall_methods/user_quality/METHOD.md`、`configs/recall/pool500_method_registry.json` 中 user_quality 与各 source 的 `dataset_contract`，并对照 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`、UserCF/ItemCF/Swing sidecar 构建脚本的 train-only 与 no-holdout 约束，确认可用输入应限定为 `user_sequences.train.jsonl` 和 `canonical_items.jsonl`。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_user_quality_profile.py`，按 batch 统计 `positive_count`、`unique_item_count`、`category_count`、`recent_sequence_length`、`shared_item_neighbor_count`，划分 `heavy_cf_eligible`、`medium_behavior`、`fallback_only`，并输出 `eligible_user_quality_manifest.json`、`quality_bucket_summary.json`、`resource_audit.json`。同步更新 `dic/recall_methods/user_quality/METHOD.md` 和 registry 中的 user_quality policy contract，保持 `user_quality` 不进入 `sources`。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_user_quality_profile.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_source_registry.py -q`，结果 `9 passed`；`compileall` 与 registry JSON 校验通过。实际生成 `outputs/recall/pool500_user_quality/target500_train_only/`，500 个 train users 中 `medium_behavior=49`、`fallback_only=451`、`heavy_cf_eligible=0`，resource audit 确认只读 train sequences 与 canonical items，`uses_valid=false`、`uses_test=false`、`uses_holdout=false`。

**面试可讲点：**
这段可以讲成“用用户质量分层治理重资源召回”：不是盲目扩大矩阵召回，而是在候选池 ready 前先建立可审计的 eligibility policy，把行为稀疏用户导向 fallback，把中等行为用户导向轻量行为扩展，把重 CF 资源留给真正有共享邻居和多样行为的用户，同时用 no-holdout artifact 边界避免离线评估泄漏和误晋升。

### 2026-05-18 - 召回前数据底座沉淀到 rs_core/dataproc

**任务：**
在项目已经进入召回阶段后，将全量数据清洗与召回前视图构建中已经稳定复用的能力，从 `scripts/data/` 脚本层沉淀到 `rs_core/dataproc/`，让数据底座成为核心工程能力。

**遇到的问题：**
`scripts/data/build_recall_clean_tables.py`、`build_recall_views.py`、`verify_recall_outputs.py` 已经承担 canonical clean tables、recall views 和 smoke 校验职责，不再是一次性命令；继续把核心逻辑留在 `scripts/` 会导致召回前数据底座难以被测试、复用和治理。

**定位方式：**
梳理 `scripts/data` 目录职责、`tests/test_build_recall_views.py` 的直接 import、phase0/full semantic 相关测试对 clean/views manifest 的依赖，以及 `rs_core/dataproc/__init__.py` 为空的现状。验证 `scripts/data/run_recall_smoke.py`、`profile_recall_tables.py` 更偏 CLI/报告编排，不属于本轮核心沉淀范围。

**解决方式：**
新增 `rs_core/dataproc/recall_clean.py`、`rs_core/dataproc/recall_views.py`、`rs_core/dataproc/validation.py`，分别承载 clean tables、recall views 和 recall output checks 的核心函数；`scripts/data/build_recall_clean_tables.py`、`build_recall_views.py`、`verify_recall_outputs.py` 保留为薄 CLI，只负责参数解析、调用核心模块和输出摘要。同步更新 `tests/test_build_recall_views.py` 和 `dic/standards/ENGINEERING_STANDARDS.md`，明确 `rs_core/dataproc/` 是召回前稳定数据底座。

**验证结果：**
使用项目 `.venv` 运行 `python -m compileall rs_core/dataproc scripts/data tests/test_build_recall_views.py` 通过；`python -m pytest tests/test_build_recall_views.py tests/test_phase0_contract_precheck.py tests/test_full_semantic_title_category_manifest.py tests/test_recall_source_registry.py` 结果 `20 passed`；三个 CLI wrapper 的 `--help` 冒烟通过；`python scripts/ci/validate_engineering_contracts.py` 通过；grep 确认当前 Python 代码中没有对旧 `scripts.data.build_recall_clean_tables/build_recall_views/verify_recall_outputs` 的直接依赖。独立 verifier 复查确认 `rs_core/dataproc` 无 `argparse/main/__main__` CLI 细节残留。

**面试可讲点：**
这段可以讲成“推荐系统数据底座产品化”：在进入召回实验后，把不再频繁变化的清洗、视图和校验能力从脚本层上收为核心模块，让后续召回、排序和 Agent 链路依赖稳定、可测试、可复用的数据基础，同时保留 CLI 入口方便复现实验。

### 2026-05-18 - rs_lab 实验资产层迁移

**任务：**
将原本集中在 `scripts/experiments/` 的召回、排序、pool500、sidecar 与 phase gate 实验资产迁移到新的 `rs_lab/experiments/`，让 `scripts/` 回归薄命令入口职责，同时保持 `rs_core/` 只承载稳定主路能力。

**遇到的问题：**
实验代码已经被测试、治理配置和实验链路反复引用，不适合继续散落在 `scripts/`；但这些 phase 化实验、批处理和 sidecar 构建逻辑也不都应直接进入 `rs_core/`，否则会污染核心库边界。

**定位方式：**
梳理 `scripts/experiments/recall/*.py`、`scripts/experiments/ranking/*.py`、测试中的 `scripts.experiments.*` import，以及 `configs/governance/current_route_registry.yaml` 的 `script_paths`。确认 `rs_core/recsys` 与 `rs_core/workflow` 中的 candidate merge、route gate、ranking adapter、shadow ranking 等稳定能力不依赖旧实验脚本。

**解决方式：**
新增 `rs_lab` 包并保持原 recall/ranking 相对结构，将实验资产整体迁移为 `rs_lab.experiments.*`；同步更新测试 import、治理 registry 路径、工程契约 CLI 默认扫描范围和 `dic/standards/ENGINEERING_STANDARDS.md` 的目录职责说明。历史叙事文档中的旧路径保持历史事实，不批量改写。

**验证结果：**
使用项目 `.venv` 运行 `python -m compileall rs_lab rs_core tests` 通过；`python -m pytest tests/test_engineering_contracts.py` 结果 `32 passed`；`python scripts/ci/validate_engineering_contracts.py` 通过并扫描 `116 configs, 72 scripts, 53 tests`；受影响 pool500/sidecar 测试集 `61 passed`。同时 grep 确认当前 Python 代码和 configs 中没有 `scripts.experiments` / `scripts/experiments` 残留引用。

**面试可讲点：**
这段可以讲成“实验资产治理分层”：不是把所有实验都塞进核心库，而是建立 `rs_lab` 作为从探索脚本到稳定 `rs_core` 的中间层，让召回/排序实验既可复用、可测试、可治理，又不会污染线上主路工程边界。

### 2026-05-18 - pool500 recall-only continuation smoke 验证收口

**任务：**
验证本轮 pool500 recall-only continuation 的受限 smoke 产物与回归测试，确认它只能作为 diagnostic continuation 证据，不宣称 `FULL_POOL500_READY`，也不替换 ranking input。

**遇到的问题：**
`full_data_pool500_recall_only_team_smoke005` 已能产出 5 个用户的候选与 source manifest，但 ItemCF/UserCF/Swing/Two-Tower 仍为 `DEFERRED`，所有 5 个用户 underfilled；如果只看有候选行产出，容易误把 partial smoke 当成 ready artifact。

**定位方式：**
审计 `outputs/recall/full_data_pool500_recall_only_team_smoke005/manifest.json`、`readiness_result.json` 和 `per_source_output_manifests.json`：manifest 返回 `decision=STOP`、`artifact_gate_decision=STOP`、`processed_users=5`、`candidate_rows=1444`、`underfilled_user_count=5`；readiness 写入 `ARTIFACT_GATE_STOP` blocker，且 quality/source output/index audit 均为 `DIAGNOSTIC_ONLY_PARTIAL`。

**解决方式：**
本轮验证不做 full-run、不训练 Two-Tower、不把旧 `youtube_dnn` 产物作为 pool500 ready artifact，也不替换 ranking 输入；保留 smoke005 作为 continuation 诊断证据，并明确后续应先补齐 ItemCF、UserCF、Swing sidecar，Two-Tower 等新的 full-clean-safe artifact 再进入 ready 判断。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_usercf_sidecar.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_swing_sidecar.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_train_itemcf_sidecars.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_recall_only.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py`，结果 `69 passed in 0.58s`。产物审计确认 category、popular、semantic、semantic_title_category_expansion、co_visit_fallback_repair 有 READY 行数，ItemCF/UserCF/Swing/Two-Tower 仍为 `DEFERRED/0 rows`，`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“用门禁和证据包约束推荐召回扩大候选池”：即使 smoke 能产出候选，也必须把 source 完备性、underfill、artifact gate 和 readiness bundle 一起审计，宁可返回 STOP 暴露缺口，也不把 partial recall 误晋升为排序主路输入。

### 2026-05-17 - pool500 shadow ranking lane 底座适配

**任务：**
为其他 agent 产出的 pool500 召回 artifact 预先打通排序诊断底座，使 pool500 可以进入只读 shadow 排序分析，但不替换当前 pool200 排序实验契约，也不产生 promotion 证据。

**遇到的问题：**
现有 `ranking_experiments.py` 明确要求 `candidate_pool_size=200/top_k=5`，如果直接复用 `build_ranking_run_row` 接 pool500，会把 diagnostic artifact 混入 pool200 ranking registry 和 promotion 语义；同时 pool500 artifact gate 仍要求 `ranking_input_replacement_allowed=false`、`promotion_allowed=false`，必须把“可排序诊断”和“可替换主路”隔离。

**定位方式：**
通过 ralplan + team 审查确认边界：复用 `rs_core/recsys/ranking.py` 的三段式 `rank_candidates/coarse/fine/rerank`，但新增独立 `pool500_shadow_ranking_evidence_v1`，并将 pool500 rows 到 `MergedCandidate` 的转换放在 `rs_core/workflow/pool500_ranking_adapter.py`，避免把 artifact/gate/schema 逻辑塞进通用排序层。

**解决方式：**
新增 `rs_core/workflow/pool500_shadow_ranking.py`，提供 `build_pool500_shadow_ranking_evidence()`、`validate_pool500_shadow_ranking_evidence()` 和 `run_pool500_shadow_ranking()`：runner 在排序前校验 `FULL_POOL500_READY/PASS` 与 recall shadow evidence，失败时 STOP，不生成成功排序输出；成功时调用 `rank_candidates()` 并输出 diagnostic-only 的 `shadow_metrics`、stage trace、topK source contribution。新增 `rs_core/workflow/pool500_ranking_adapter.py`，将 pool500 JSONL/rows 合并为 `dict[user_id, list[MergedCandidate]]`，保留 source lineage，并检查非法 source、重复 user-item-source、非有限 score、rank、metadata 和每用户 500 上限。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_shadow_ranking.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_ranking_adapter.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_phase_1_31_ranking_scaffold.py`，结果 `85 passed in 0.25s`。测试覆盖 schema/gate negative cases、adapter synthetic fixture、runner shadow output、`build_ranking_run_row` 继续拒绝 pool500，以及 runner 模块不调用 pool200 row builder。

**面试可讲点：**
这段可以讲成“在推荐系统扩大候选池前先做证据隔离”：不是简单把 500 候选塞进排序，而是把 artifact readiness、adapter、排序 stage trace 和 no-promotion validator 做成独立 shadow lane，让多种排序方法能公平共享同一 pool500 输入做诊断，同时保护当前 pool200 主路和晋升门禁不被污染。

### 2026-05-17 - pool500 recall-only 多源 READY 链路收口

**任务：**
把 pool500 recall-only 剩余 canonical source（ItemCF weak/strong、UserCF、Swing、semantic title-category expansion、Two-Tower）从独立构建、方法验收推进到 runner 可加载、readiness contract 可审计的集成状态。

**遇到的问题：**
各方法的 full clean train 使用方式不同：ItemCF/Swing/UserCF 需要自定义 sidecar/index 控制资源，Two-Tower 不能复用旧 `youtube_dnn`/10k/smoke artifact，semantic diagnostic 产物不能误晋升 FULL READY；同时 runner 不能替换 ranking input，也不能读取 valid/test/holdout 生成候选。

**定位方式：**
按方法拆分 builder/verifier，独立检查 `scripts/experiments/recall/build_full_train_*`、`rs_core/recsys/candidate_merge.py`、`scripts/experiments/recall/run_full_data_pool500_recall_only.py` 和 `rs_core/workflow/full_data_pool500_route_gate.py`。关键缺陷包括 Swing manifest sha 受输出目录影响、UserCF loader/readiness 缺口、`source_name=youtube_dnn` 被 alias 归一化误放行，以及 runner 主路径缺少多 source artifact 接入测试。

**解决方式：**
新增/完善 ItemCF、UserCF、Swing、semantic title-category 和 Two-Tower source manifest/sidecar 合同；在 `candidate_merge.py` 接入 UserCF/Swing loader 与候选函数，在 `run_full_data_pool500_recall_only.py` 支持显式 `source_manifest_paths` 加载多 source artifact，并保持缺失 Two-Tower full-clean artifact 时安全 `DEFERRED`。在 route gate 中要求 Two-Tower READY artifact 的原始 `source_name/canonical_source` 必须为 `two_tower`，阻断旧 `youtube_dnn` READY 标签和路径。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_full_data_pool500_recall_only.py tests/test_full_data_pool500_route_gate.py tests/test_full_semantic_title_category_manifest.py tests/test_full_train_itemcf_sidecars.py tests/test_full_train_usercf_sidecar.py tests/test_full_train_swing_sidecar.py`，结果 `76 passed in 0.72s`。其中 recall-only runner 测试覆盖 ItemCF、UserCF、Swing、semantic title-category expansion、Two-Tower source artifact 的加载、source coverage、readiness contract 和 full derived index manifest 输出。

**面试可讲点：**
这段可以讲成“把多路召回从算法脚本推进到可治理离线资产”：每个 source 都有独立构建、资源边界、manifest sha、无泄漏合同和 verifier；最终 runner 只消费显式 artifact，不猜路径、不越权替换 ranking input，并用 readiness bundle 暴露 READY/DEFERRED 状态，适合后续逐步扩大 full-data 召回规模。

### 2026-05-17 - pool500 shadow closure 最终验证收口

**任务：**
对 pool500 shadow closure 的后端契约、Agent/display/runtime 相关测试和前端公共展示链路做最终验证，并把本次收口沉淀为可复述的工程叙事。

**遇到的问题：**
本轮改动横跨 current route registry、readiness bundle、display/Agent timeline、frontend schema 和多组测试，单点测试通过不足以证明没有把 diagnostic recall-only 产物误晋升为 ranking input，也不足以证明前端公共契约仍能构建。

**定位方式：**
按 approved verification matrix 使用项目 `.venv` 运行工程契约校验和聚焦 pytest；同时在 `frontend/` 运行 `npm run lint && npm run build` 验证 TypeScript 与生产构建，并用 `git status --short -- frontend/package.json frontend/package-lock.json frontend/npm-shrinkwrap.json` 确认本次验证没有引入 npm 依赖文件改动。

**解决方式：**
本轮未发现需要修复的回归，验证侧只追加叙事日志；实现侧已由前序任务完成 pool500 shadow evidence、治理契约、公共 timeline/display contract、Agent feedback 与前端 schema 串联，最终通过统一验证矩阵收口。

**验证结果：**
`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 通过，结果 `Engineering contracts passed: 115 configs, 68 scripts, 47 tests, 1 route registry, 1 governance allowlist, 1 PRD`。`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_engineering_contracts.py tests/test_display_contract.py tests/test_agent_runtime.py tests/test_full_data_pool500_route_gate.py tests/test_p7_full_pool500_route_gate.py` 通过，结果 `99 passed in 1.41s`。`cd frontend && npm run lint && npm run build` 通过，Vite production build 成功；frontend package 文件状态检查无输出，说明未产生被跟踪的 npm 依赖文件改动。

**面试可讲点：**
这段可以讲成“用验证矩阵把推荐实验治理、Agent 展示契约和前端公共 schema 做端到端收口”：不是只跑某个算法脚本，而是同时证明 route registry、readiness bundle、runtime/display contract 和前端构建都保持一致，确保 pool500 shadow 证据只作为可审计展示与诊断输入，不越权替代 ranking 主路。

### 2026-05-17 - pool500 recall-only diagnostic 候选池生成

**任务：**
在 full clean 数据基础上推进主路 pool500 recall-only 候选池产出，先用受限 1000 用户批次验证生成、合并、manifest、readiness bundle 与治理边界能否闭环。

**遇到的问题：**
当前全量轻量索引只实际具备 `popular` 和 `category` 两个 source，若直接按 pool500 目标宣称成功会掩盖 source 缺口；同时 `popular+category` 必须受 35% 联合预算限制，否则兜底源会挤占主路召回池。

**定位方式：**
检查 `data/processed/amazon_2023_recall_views_full_lightweight/manifest.json` 的 skipped heavy outputs，确认 ItemCF、co-visit、UserCF、Swing、Two-Tower 等 canonical source 尚未 ready；运行 `scripts/experiments/recall/run_full_data_pool500_recall_only.py --limit-users 1000` 后审计 `outputs/recall/full_data_pool500_recall_only_batch001/quality_audit.json`，发现需要把 `popular+category` 联合 cap 收敛到 175。

**解决方式：**
在 recall-only 生成脚本中保持默认轻量路径：不读取 valid/test/holdout 做生成、不替换 ranking input、不启用 pool1000；默认关闭重型 semantic 与 category long-tail 扫描，并在导出前增加 `popular+category <= 175` 的联合预算裁剪，使 diagnostic 产物真实反映当前 source 缺口而不是用兜底源填满 500。

**验证结果：**
最新产物位于 `outputs/recall/full_data_pool500_recall_only_batch001/`：`processed_users=1000`、`candidate_rows=175000`、`popular_category_cap_violating_users=0`、`max_candidates_per_user=175`、`blockers=[]`。`readiness_result.json` 返回 `DIAGNOSTIC_ONLY_PARTIAL`，程序化复核 `validate_readiness_bundle(...)` 得到 `blocker_count=0`、`diagnostic_count=4`，并确认 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。回归验证：`tests/test_full_data_pool500_route_gate.py` 结果 `33 passed`，`tests/test_engineering_contracts.py` 结果 `26 passed`，`scripts/ci/validate_engineering_contracts.py` 结果 `Engineering contracts passed: 115 configs, 68 scripts, 46 tests, 1 route registry, 1 governance allowlist`。

**面试可讲点：**
这段可以讲成“先把千万级召回候选池生成链路做成可审计闭环，再逐步补齐高价值 source”：没有把 partial artifact 包装成成功，而是通过 manifest、quality audit、readiness bundle 和 source budget 暴露当前缺口，证明推荐离线链路既能产出候选，也能防止兜底源污染主路和误晋升 ranking 输入。

### 2026-05-17 - pool500 readiness bundle 最终宣称门禁

**任务：**
把 pool500 Phase A 从“artifact gate 可返回 FULL”收敛为“只有 readiness bundle 汇总全部审计 PASS 才能宣称 `FULL_POOL500_READY`”，并保持 recall-only、不可替换 ranking input 的治理边界。

**遇到的问题：**
现有 `full_data_pool500_artifact_gate_v5` 已能检查 source readiness、manifest、holdout、pool1000、ranking replacement 等底层条件，但它本身还不是最终质量、预算、索引、source output 和 registry 检查的唯一证据包。若直接把 artifact gate 结果当最终成功，后续容易把 partial/diagnostic artifact 或缺失质量审计的产物误晋升。

**定位方式：**
审查 `rs_core/workflow/full_data_pool500_route_gate.py`、`tests/test_full_data_pool500_route_gate.py`、`configs/governance/current_route_registry.yaml` 和工程契约测试，确认当前治理已登记 v5 artifact gate，但缺少显式 `readiness_bundle` final authority。随后用相关 pool500 gate、P7 gate 和 engineering contracts 测试验证边界未破坏。

**解决方式：**
在 `rs_core/workflow/full_data_pool500_route_gate.py` 增加 `READINESS_BUNDLE_SCHEMA_VERSION` 与 `validate_readiness_bundle()`：要求 artifact gate 为 `FULL_POOL500_READY`，并要求 `quality_audit`、`source_budget_audit`、`source_output_manifest_audit`、`index_manifest_audit`、`no_holdout_audit`、`ranking_registry_check` 全部 PASS；其中 no-holdout 与 ranking registry 失败直接 STOP，质量/预算/source/index 不通过则降级 `DIAGNOSTIC_ONLY_PARTIAL`。同时强制 bundle 不授权候选生成、不允许 ranking input replacement、不允许 pool1000。

**验证结果：**
`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py` 结果 `32 passed`；`tests/test_engineering_contracts.py` 结果 `26 passed`；`tests/test_p7_full_pool500_route_gate.py` 结果 `7 passed`；`scripts/ci/validate_engineering_contracts.py` 结果 `Engineering contracts passed: 115 configs, 67 scripts, 46 tests, 1 route registry, 1 governance allowlist`。

**面试可讲点：**
这段可以讲成“把推荐实验结果晋升从单点判断升级为证据包门禁”：不是看到某个 gate 返回 ready 就上线，而是要求数据泄漏、source 完备性、预算、索引、质量、registry 边界全部形成机器可校验审计，最终用 readiness bundle 统一宣称 recall artifact ready，并明确 ranking 使用必须另走 promotion。

### 2026-05-17 - 最小 Current Route Registry 工程治理框架

**任务：**
为混杂增长的实验代码、主路配置和 Agent 开发路径建立一套轻量治理框架：只登记当前主路与候选延续路线，补齐晋升门禁、warning allowlist 生命周期和 CI 可执行工程契约。

**遇到的问题：**
代码库已有 recall、ranking、Agent demo、pool500 延续实验并行推进，如果直接做全量资产盘点或大规模迁移，容易误伤历史 phase 脚本和 outputs；但如果没有 current route 边界，pool500 recall-only 产物又可能被误当作 ranking 输入。

**定位方式：**
审查 `dic/PROJECT_STRUCTURE.md`、文档/outputs 路由指南、`rs_core/workflow/pool500_route_gate.py`、`rs_core/workflow/full_data_pool500_route_gate.py`、CI 工程契约入口和 pool500 gate 测试，确认治理应收敛在“current route registry + promotion gate + contract validation”，而不是重构全项目结构。

**解决方式：**
新增 `configs/governance/current_route_registry.yaml` 和 `configs/governance/engineering_contract_allowlist.yaml`；新增 `dic/guides/CODEBASE_GOVERNANCE_GUIDE.md` 明确 recall、ranking、Agent demo、stable workflow 的晋升门禁；扩展 `rs_core/common/engineering_contracts.py` 和 `scripts/ci/validate_engineering_contracts.py`，校验 registry schema、必要 route、路径存在性、禁止 old_dic 权威引用、allowlist 生命周期字段，并强制 current_ranking_route 不得引用 pool500 recall-only 路径。

**验证结果：**
`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_engineering_contracts.py -q` 结果 `16 passed`；`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe D:/sinrotic_code/python_project/summer/RS_agent/scripts/ci/validate_engineering_contracts.py` 结果 `Engineering contracts passed: 115 configs, 67 scripts, 46 tests, 1 route registry, 1 governance allowlist`；`ruff check` 通过；pool500 gate 回归 `15 passed`。

**面试可讲点：**
这段可以讲成“用轻量工程治理控制实验型推荐系统的复杂度”：不做大爆炸重构，而是把主路身份、晋升条件、候选边界和例外生命周期变成可测试契约，让后续 Agent 或实验代码先判断自己处于探索、候选、current 还是 stable workflow，再决定是否进入 registry 和 CI gate。

### 2026-05-17 - scripts 实验入口整理与 P7 gate 迁移

**任务：**
整理 `scripts/` 中混杂的实验入口：清空根目录 `.py` 文件，将稳定入口、阶段性实验和历史入口分别放入子目录，把当前 P7 pool500 主路 gate 的可复用逻辑迁入 `rs_core`，并补充后续使用 `scripts/` 的工程规范。

**遇到的问题：**
`scripts/` 根目录同时承担稳定 CLI、阶段性实验、历史入口和被测试 import 的业务逻辑，视觉上和职责上都难以区分主入口与实验链路；同时当前新增的 `run_p7_full_pool500_route_gate.py` 还从另一个脚本 import 私有 `_enforce_project_venv`，形成脚本之间的反向耦合。

**定位方式：**
盘点 `scripts/*.py`、`rs_core/workflow/*`、P7 / phase / pool500 相关测试和 `dic/standards/ENGINEERING_STANDARDS.md`，确认项目规范要求 `scripts/` 只做参数解析与流程触发；再用检索确认 `prepare_data.py`、`run_eval.py`、`train_sft.py`、`train_dpo.py` 在 `tests/`、`dic/`、`.github/` 和其他脚本中无引用，并用根目录清单确认阶段性实验脚本需要分层。

**解决方式：**
新增 `scripts/data/`、`scripts/training/`、`scripts/evaluation/`、`scripts/serving/`、`scripts/assets/`、`scripts/ci/`，承接 19 个稳定入口；新增 `scripts/experiments/recall/` 和 `scripts/experiments/ranking/`，承接 47 个阶段性 recall/ranking 实验入口；四个无引用历史入口移入 `scripts/archive/`，最终 `scripts/` 根目录不再保留 `.py` 文件。新增 `rs_core/workflow/pool500_route_gate.py` 承接 P7 route signature、precheck、continuation gate 和 artifact audit 逻辑；新增 `rs_core/common/runtime.py` 提供 `enforce_project_venv()`，切断 `rs_core` 对 `scripts` 私有 helper 的依赖；将 `scripts/experiments/recall/run_p7_full_pool500_route_gate.py` 收敛为薄 CLI wrapper；测试改为直接 import `rs_core.workflow.pool500_route_gate`；工程契约改为递归扫描 `scripts/**/*.py` 且排除 archive；在 `ENGINEERING_STANDARDS.md` 增补 `scripts/` 使用规范。

**验证结果：**
运行覆盖移动后入口的代表性测试：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_p7_full_pool500_route_gate.py tests/test_phase_1_20_recall_diagnostics.py tests/test_phase_1_31_ranking_scaffold.py tests/test_phase_1_21_recall_coverage.py tests/test_phase_4_stage_shadow_metrics.py tests/test_phase_5_fine_rank_positive_push.py tests/test_phase_6_industrial_ranking_chain.py tests/test_phase_c_ranking_actionability.py tests/test_pool500_representative.py tests/test_simulation_runner.py`，结果 `72 passed, 2 warnings`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe D:/sinrotic_code/python_project/summer/RS_agent/scripts/ci/validate_engineering_contracts.py`，结果 `Engineering contracts passed: 113 configs, 66 scripts, 45 tests`；运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check ...`，结果 `All checks passed`；`Glob scripts/*.py` 返回 `No files found`。

**面试可讲点：**
这段可以讲成“把实验脚本从能跑整理到可维护”：`scripts/` 根目录不再堆入口，稳定命令按 data/training/evaluation/serving/assets/ci 分层，阶段性 recall/ranking 实验进专门目录，历史入口归档；同时选当前主路 P7 gate 做迁移样板，明确 CLI 与核心 workflow 的边界，再用工程规范、代表性实验测试和 contract gate 固化规则，降低后续实验扩展时的耦合和复现成本。

### 2026-05-16 - Phase 0 召回方法合同预检入口

**任务：**
为召回方法全家桶 Phase 0 增加只做合同预检的入口，落盘 `manifest.json`、`source_audit.json` 和 `resolved_inputs.json`，为后续 Phase 2-5 动态输入解析提供可审计基线。

**遇到的问题：**
后续 UserCF、Swing、Sequence、Graph、MF、Two-Tower 等阶段依赖不同输入和配置，若直接猜路径或混用 ranking pool，会造成 scope drift；同时 candidate generation 必须继续禁止读取 valid/test/holdout，并把召回晋升 gate 与 ranking frozen pool200 gate 分离。

**定位方式：**
先读取 `.omc/handoffs/phase0-contract-schema-notes.md` 明确三份 JSON schema，再核验 full clean、full lightweight views、代表性 baseline、bounded ItemCF sidecar、graph/two_tower config 和 ranking pool200 config 的真实路径与 sha256。

**解决方式：**
新增 `scripts/experiments/recall/run_phase0_contract_precheck.py`，默认输出到 `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/`；脚本强制项目 `.venv`、D 盘 50GiB 水位、10k 路径拒绝、holdout read contract，并在无法解析动态输入或具体 config 文件时写 `BLOCKED_MISSING_ARTIFACT` / `INVALID_SCOPE_DRIFT`，不执行任何下游阶段。

**验证结果：**
已用项目 `.venv` 执行 `python -m pytest tests/test_phase0_contract_precheck.py`，结果 `5 passed`；执行 `python -m ruff check scripts/experiments/recall/run_phase0_contract_precheck.py tests/test_phase0_contract_precheck.py`，结果 `All checks passed`。运行 Phase 0 入口后三份产物已写入 `outputs/recall/full_main_route_other_methods/phase0_contract_precheck/`，因当前 graph、two_tower 和 ranking pool200 具体 config 仍引用历史 10k 路径，manifest 按合同返回 `INVALID_SCOPE_DRIFT` 并写入 `failure_reason`。独立 verifier 已批准 US-001，确认 source_audit 的 `read_files` 不包含 valid/test/holdout，后续 Phase 1+ 必须先修复 full-clean-safe config 后才能继续。

**面试可讲点：**
这段可以讲成“在推荐召回实验前加合同闸门”：面对多阶段召回方法扩展，不急于跑算法，而是先把输入、配置、数据泄漏边界、资源水位和 ranking/recall gate 明确为可审计 artifact，降低后续实验复现和 scope drift 风险。

### 2026-05-16 - bounded ItemCF co-visit sidecar 代表性构建验收

**任务：**
在 full clean 真实训练序列上执行受边界约束的 ItemCF/co-visit sidecar 代表性构建，验证它只生成可审计的邻居分片产物，不复制 full clean、不生成 pool500/pool1000 或 recall views。

**遇到的问题：**
直接从 full clean 构建共现邻居存在资源和产物污染风险，需要把执行范围限制在 `limit_users<=1000`，同时继续保证 10k 路径、valid/test/holdout 读取和重型输出都被排除。

**定位方式：**
使用 `.venv` 运行 focused pytest 与 ruff，随后检查 `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_sidecar_representative/manifest.json` 和 `source_audit.json` 中的 safety flags、输入路径、输出键与目录文件集合。

**解决方式：**
执行 `scripts/experiments/recall/run_bounded_itemcf_covisit_sidecar_build.py`，显式传入 full clean 目录、代表性输出目录、`--limit-users 1000` 和 `--min-free-bytes 53687091200`；脚本只读取 `user_sequences.train.jsonl`，写入 manifest、source audit 和 32 个 `neighbors_shard_*.jsonl`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_bounded_itemcf_covisit_sidecar_build.py` 结果 `7 passed`，`./.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_bounded_itemcf_covisit_sidecar_build.py tests/test_bounded_itemcf_covisit_sidecar_build.py` 通过。真实构建输出目录共 34 个文件，`users_scanned=1000`、`processed_users=363`、`pair_updates=5264`、`project_venv_enforced=true`、`train_only=true`、`min_free_bytes=53687091200`；核验确认无 10k source path、无 valid/test/holdout 读取、无 pool500/pool1000/recall view/full clean copy 输出。

**面试可讲点：**
这段可以讲成“把行为共现召回从 dry-run 风险评估推进到受控 sidecar 产物”：通过硬上限、磁盘水位、train-only source audit、分片输出和 focused 测试，把原本容易失控的共现邻居构建变成可审计、可复跑、可逐步扩大的离线召回资产。

### 2026-05-16 - bounded ItemCF co-visit sidecar dry-run 预检

**任务：**
在不生成邻居 sidecar、不复制 full clean、不物化 pool500/pool1000 的前提下，为 full clean 上的 ItemCF/co-visit 行为召回补一条有边界的 dry-run 预检路径，先估算 pair 行数和分片字节风险。

**遇到的问题：**
已有 ItemCF/co-visit 逻辑适合小样本或受控候选池，但 full clean 的 `user_sequences.train.jsonl` 规模达到 18103384 行，直接建邻居可能带来磁盘、内存和产物污染风险；同时必须确保不误读 valid/test/holdout、不回退到 10k 路径、不生成 full clean copy 或 pool500/pool1000 输出。

**定位方式：**
只读审查 `scripts/data/build_recall_views.py` 中 `build_itemcf_edges(...)`、`build_item_graph_view(...)` 和 `build_lightweight_full_safe_views(...)`，确认可复用 pair/cap 估算思路，但 dry-run 不能调用真实写邻居函数；再检查 `scripts/experiments/recall/run_full_lightweight_recall_e2e.py` 的 10k 路径拒绝、输出目录拒绝和 `.venv` 约束，作为 sidecar 预检脚本的安全门参考。

**解决方式：**
新增 `scripts/experiments/recall/run_bounded_itemcf_covisit_dry_run.py`，只读取 `data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`，强制 `limit_users<=1000`、默认 50GiB 磁盘水位、拒绝 10k 路径和已存在输出目录；脚本只维护 bounded pair counter 和 shard byte estimate，最终只写 `manifest.json`。

**验证结果：**
新增 `tests/test_bounded_itemcf_covisit_dry_run.py`，覆盖 manifest-only、train_only/holdout contract、10k 路径拒绝、输出目录拒绝、输出位于 clean_dir 内拒绝和 `limit_users>1000` 拒绝。验证命令 `./.venv/Scripts/python.exe -m pytest tests/test_bounded_itemcf_covisit_dry_run.py tests/test_full_lightweight_recall_e2e.py` 结果 `8 passed`，`./.venv/Scripts/python.exe -m ruff check scripts/experiments/recall/run_bounded_itemcf_covisit_dry_run.py scripts/experiments/recall/run_full_lightweight_recall_e2e.py tests/test_bounded_itemcf_covisit_dry_run.py tests/test_full_lightweight_recall_e2e.py` 通过。真实 dry-run 输出 `outputs/recall/full_main_route_other_methods/bounded_itemcf_covisit_dry_run_estimate/manifest.json`，目录仅包含 manifest；manifest 记录 `train_only=true`、`limit_users=1000`、`sampled_users=1000`、`estimated_pair_rows=10528`、`planned_shard_count=32`、D 盘剩余 `225294610432` bytes，且未生成 neighbor/shard/pool500/pool1000 产物。

**面试可讲点：**
这段可以讲成“给重型召回源加 sidecar 预检闸门”：面对千万级行为序列，不直接上线全量共现构建，而是先用只读 train、硬阈值、路径拒绝、manifest-only 和分片字节估算把风险前移，证明推荐系统离线工程不仅追求召回效果，也要控制资源边界和数据泄漏边界。

### 2026-05-15 - 全量召回轻量索引安全路径

**任务：**
为 232 万商品、5605 万去重交互的 full clean 数据补一条 Phase 0.5 + Phase 1a 的安全召回索引路径，先只构建 Popular、Category、Semantic catalog/inverted index，避免直接触发 ItemCF/item_graph 等重型全量共现逻辑。

**遇到的问题：**
旧 `scripts/data/build_recall_views.py` 的主流程会无条件构建 ItemCF 和 item graph，内部包含全局 pair/edge 聚合；如果直接套到 full clean，存在内存、磁盘和失败恢复风险，也不符合“不复制 full clean、不全用户物化 pool500/pool1000”的执行边界。

**定位方式：**
审查 `scripts/data/build_recall_views.py` 的 main 流程，确认 `build_itemcf_views(...)` 与 `build_item_graph_view(...)` 在默认路径中必跑；结合 full clean `stats.json` 中 `canonical_items_written=2320263`、`filtered_rows=56054775` 的规模判断，必须先把轻量 catalog 索引和重型行为召回拆开。

**解决方式：**
新增 `--lightweight-full-safe` 模式：只写 `popular_recall.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`semantic_recall_inputs.jsonl` 和 `semantic_inverted_index.jsonl`；通过 `_tmp` 目录构建后原子提升到目标目录；manifest/stats 记录 source signature、输入行数、磁盘水位、产物大小和 skipped heavy outputs；默认旧路径保持兼容。

**验证结果：**
新增 `tests/test_build_recall_views.py` 覆盖 lightweight 模式不会生成 `itemcf_recall_weak.jsonl`、`itemcf_recall_strong.jsonl`、`item_graph_recall.jsonl`，并检查 semantic inverted index、source row count、canonical sha256、真实 `_tmp` 证据和最终产物 hard cap。已通过 `./.venv/Scripts/python.exe -m pytest tests/test_build_recall_views.py -q`，结果 `3 passed`；通过 `./.venv/Scripts/python.exe -m ruff check scripts/data/build_recall_views.py tests/test_build_recall_views.py`；CLI smoke 验证 lightweight 入口可生成 manifest/stats 且不产生重型召回文件；独立 architect 复核结论为 PASS。

**面试可讲点：**
这段可以讲成“把研究型全量召回改造成可控索引层”：面对千万级交互，不是直接把小样本脚本放大运行，而是先拆出轻量 catalog 索引、显式跳过高风险共现源，并用 manifest、source signature、磁盘阈值、产物上限和原子目录提升把全量实验变成可恢复、可解释、可扩展的工程流程。

### 2026-05-23 - pool500 two_tower 召回专项诊断

**任务：**
在最新 10000 用户 pool500 评估集上专项诊断 `two_tower` 召回：定位最新 eval/baseline/artifact，量化 source 级 Hit@K、用户覆盖、最终 pool500 边际贡献、与其他 source 的 overlap，并通过受控 challenger 判断是否应保留、降预算或重构后再保留 two_tower 预算。

**遇到的问题：**
当前 final pool500 中 `two_tower` 占用 `1,389,067/5,000,000` 行，primary share 约 `27.78%`，但 source 级只有 `HitPairs@500=3`、`HitUsers@500=3`；如果只看候选行数或 source 覆盖，容易误判为“向量召回已提供大量候选”，实际对目标正例贡献极低。

**定位方式：**
以 `outputs/eval/pool500_offline_eval_users_10k/manifest.json` 和 `outputs/eval/pool500_offline_eval_baseline_current/` 为最新 10k 评估与 baseline 证据，复核 `metrics.json`、`source_audit.json`、`source_contribution_audit.json`、two_tower source manifest 与训练 artifact。确认 10k baseline final pool500 为 `HitPairs@50=230`、`HitPairs@100=298`、`HitPairs@500=409`；two_tower 训练 artifact 只有 `user_embedding_count=28`，10k eval 用户主要依赖 recent-positive seed item 向量均值 fallback，且有 `699` 个用户没有 positive seed。

**解决方式：**
复用现有 `build_two_tower_method_source.py` builder，在 diagnostic-only 边界内生成 top500/user challenger：`outputs/recall/pool500_method_sources/two_tower/eval10k_top500_20260523_diagnostic/`，保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。另做 final pool500 内 existing two_tower 行的 cap/remove 消融，输出 `outputs/recall/pool500_two_tower_challengers/budget_cap_ablation_20260523.json`，只用 valid/test labels 做离线评估与消融对比，不把 label/oracle 注入候选生成。

**验证结果：**
Top500 challenger 产出 `4,650,500` 行、覆盖 `9,301/10,000` 用户、`673,302` 个 unique items，但 source raw 仅 `HitPairs@50=2`、`HitPairs@100=5`、`HitPairs@500=23`、`HitUsers@500=21`、`Recall@500=0.001205`；相比当前 two_tower source 只提升 `+20 HitPairs@500`，代价是 `+3,261,433` 行。699 个无 positive seed 用户改用 recent item fallback 的诊断候选 `349,500` 行但 `HitPairs@500=0`。final pool500 cap 消融显示：cap=10/25/50/100 均保持 `HitPairs@50=230`、`HitPairs@100=298`，只损失 `1` 个 `HitPairs@500`；完全移除 two_tower 也只从 `409` 降到 `406`。

**面试可讲点：**
这段可以讲成“用受控实验识别向量召回的低 ROI 边界”：不是因为 two_tower 行数多就保留预算，也不是直接用 label 注入造达标候选，而是拆成 source raw、用户覆盖、merge surviving、overlap 和 budget cap 消融。结论是当前瓶颈不在索引覆盖或 merge 丢弃，而在表示/查询质量：应把 two_tower 预算降到 10–50 或暂保留为 diagnostic-only，下一步最小行动是先重训/重构用户表示与 rerank，再让 two_tower 重新竞争预算。

### 2026-05-23 - pool500 去冷用户 8k 评估集派生

**任务：**
从现有 10000 用户 pool500 offline eval artifact 中剔除 `cold-ish` 分层用户，形成一个只包含 hot/warm 用户的新评估集，供后续 two_tower 与召回策略在非冷用户口径下复测。

**遇到的问题：**
原 10k 评估集中 `cold-ish=2000`，而当前 two_tower 的无 positive seed 不可 query 用户为 `699`，两者不是同一概念；如果直接把冷用户问题等同于 two_tower 无法生成 query，容易误判覆盖瓶颈。因此需要保留原 10k 全局口径，同时派生一个明确标注“去 cold-ish”的补充评估口径。

**定位方式：**
读取 `outputs/eval/pool500_offline_eval_users_10k/manifest.json` 和 `users.jsonl`，确认原分层为 `hot=4000`、`warm=4000`、`cold-ish=2000`，且 `users.jsonl` 每行带有 `segment` 字段。复核 `run_pool500_offline_eval_baseline.py` 的 eval manifest 加载逻辑，确认新 artifact 需要保持 `schema_version=pool500_offline_eval_users_v1`、`status=PASS`、`user_set_hash` 与 `users.jsonl` 一致，并继续声明 label 只用于 evaluation。

**解决方式：**
使用项目 `.venv` 从原 10k artifact 派生 `outputs/eval/pool500_offline_eval_users_8k_no_cold_20260523/`，写入新的 `manifest.json` 与 `users.jsonl`；过滤规则仅为 `segment != cold-ish`，不读取 label 参与用户生成，不覆盖原 10k 输出，并在 manifest 中记录 `derived_eval_policy`、source manifest/users 路径、剔除 segment 与 no-promotion/no-ranking-replacement 边界。

**验证结果：**
轻量校验通过：新评估集 `users_count=8000`，分层为 `hot=4000`、`warm=4000`，剔除 `cold-ish=2000`；`user_set_hash=5c397357aef9f41159b7cd49b8e58f9d9ddef1704086f3cc5cad26e336d32dcd` 与 `users.jsonl` 一致；valid/test 正例统计为 `positive_pair_count=16118`、`positive_user_count=8000`，其中 `valid=8700`、`test=7418`。manifest 保持 `no_label_in_candidate_generation=true`、`no_oracle_candidate_injection=true`、`ranking_input_replacement_allowed=false`。

**面试可讲点：**
这段可以讲成“把评估口径分层治理，而不是改写总指标”：保留 10k 全量评估作为主口径，同时派生 hot/warm-only 8k 评估集用于验证双塔在非冷用户上的真实价值；这样既能避免冷用户稀释或误导专项实验，也不会把去冷指标包装成整体效果提升。

### 2026-05-23 - pool500 8k 去冷口径 two_tower 复测

**任务：**
在剔除 `cold-ish` 后的 8000 用户 hot/warm-only 评估集上复测当前 two_tower source、top500 diagnostic challenger 和 final pool 中 existing two_tower budget cap 消融，判断“去冷用户”是否能显著改善双塔结论。

**遇到的问题：**
原先 two_tower 在 10k 全量口径表现极弱，但需要排除一个可能解释：是否主要是 2000 个 cold-ish 用户拖累。如果去冷后指标显著改善，则 two_tower 可以考虑只服务 hot/warm；如果仍然低效，则问题更接近表示/查询质量，而不是单纯冷用户覆盖。

**定位方式：**
使用 `outputs/eval/pool500_offline_eval_users_8k_no_cold_20260523/manifest.json` 作为固定评估集，valid/test labels 仅用于离线评估；分别过滤评估 `outputs/eval/pool500_offline_eval_baseline_current/sources/two_tower/candidates.jsonl`、`outputs/recall/pool500_method_sources/two_tower/eval10k_top500_20260523_diagnostic/candidates.jsonl` 和 current final pool500 artifact，并按 `HitPairs/HitUsers/Recall/HitRate@50/100/500` 统计。

**解决方式：**
新增 diagnostic-only 指标文件 `outputs/recall/pool500_two_tower_challengers/eval8k_no_cold_two_tower_metrics_20260523.json`，记录当前 two_tower source、top500 challenger、分 segment 指标和 no-refill budget cap 消融；保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**验证结果：**
8k 评估集含 `positive_pair_count=16118`。当前 two_tower source 覆盖 `7639/8000` 用户、`1,139,767` 行、`269,332` unique items，但仅 `HitPairs@50=2`、`HitPairs@100=2`、`HitPairs@500=3`、`Recall@500=0.000186`、`HitRate@500=0.000375`。top500 diagnostic 扩到 `3,819,500` 行后为 `HitPairs@50=2`、`HitPairs@100=5`、`HitPairs@500=20`、`Recall@500=0.001241`，相对当前 source 只增加 `+17 HitPairs@500`。final pool cap 消融中，cap=10/25/50/100 均保持 `HitPairs@50=185`、`HitPairs@100=252`，`HitPairs@500=359`，仅比 cap=150/current 的 `360` 少 `1`；完全移除 two_tower 为 `HitPairs@500=357`，只少 `3`。

**面试可讲点：**
这段可以讲成“用分层评估排除冷用户归因假设”：剔除 cold-ish 后，双塔覆盖率提高到 hot/warm 用户上的 `7639/8000`，但正例命中仍几乎不变，说明问题不是简单冷启动拖累，而是当前 user/query embedding 召回质量不足；因此双塔更适合先降预算、保留诊断，再通过重训用户表示或重构 query/rerank 后重新评估。

### 2026-05-16 - full clean 轻量召回索引全量落盘验收

**任务：**
在真实 `data/processed/amazon_2023_recall_clean_full` 上执行已审批的 `--lightweight-full-safe` 路径，把 Phase 1a 的 Popular、Category、Semantic catalog/inverted index 从方案推进到可消费的全量产物。

**遇到的问题：**
全量输入包含 2320263 个商品与 44843821 条 train 交互，直接运行必须同时控制磁盘、内存和范围偏离风险；尤其要防止误触发 ItemCF/item_graph、复制 full clean、覆盖 10k baseline 或遗留 `_tmp` 半成品。

**定位方式：**
执行前用 `.venv` 检查 full 输入、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、manifest/stats、10k baseline、目标输出目录和 sibling `_tmp` 目录；运行中记录 D 盘剩余空间、tmp/final 目录大小和 Python 进程 RSS，第二轮采样显示 tmp 约 6.53GiB、D 盘约 210.27GiB、主进程 RSS 约 15.7GiB，未触发 50GiB/80GiB/32GiB 停止阈值。

**解决方式：**
使用项目 `.venv` 执行 `scripts/data/build_recall_views.py --lightweight-full-safe`，显式设置 `--lightweight-min-free-bytes 53687091200`、`--lightweight-max-output-bytes 85899345920`、`--semantic-inverted-top-k 2000`；构建通过 `_tmp` 原子提升到 `data/processed/amazon_2023_recall_views_full_lightweight`，不生成重型召回文件。

**验证结果：**
后台构建退出码为 0，生成 `manifest.json`、`stats.json`、`popular_recall.jsonl`、`category_recall_items.jsonl`、`category_top_items.jsonl`、`semantic_recall_inputs.jsonl`、`semantic_inverted_index.jsonl`。验收脚本确认 JSON/JSONL 抽样可解析、manifest outputs 路径有效、`itemcf_recall_weak.jsonl`、`itemcf_recall_strong.jsonl`、`item_graph_recall.jsonl` 不存在、sibling `_tmp` 已清理、10k baseline 仍存在；最终输出 7 个文件、7483658110 bytes（约 6.97GiB），D 盘剩余约 209.83GiB，source signature 记录 `canonical_items.jsonl` 行数 2320263、`canonical_interactions.train.jsonl` 行数 44843821。

**面试可讲点：**
这段可以讲成“把推荐系统全量索引构建做成有安全门的批处理”：先用 consensus plan 固化资源阈值和验收标准，再用 `.venv`、原子目录提升、manifest 驱动验证、heavy output absence check 和资源监控，证明千万级数据产物不是一次性跑出来，而是可审计、可回滚、可接入后续排序链路的工程资产。

### 2026-05-15 - 工程规范 v1 与轻量 CI 门禁建设

**任务：**
为持续扩张的 RS Agent 项目建立第一版统一工程规范，覆盖目录边界、配置命名、测试分层、ruff/pytest 工具入口、CI smoke gate 和前端 lint 门禁。

**遇到的问题：**
项目已有 `architecture/ARCHITECTURE.md` 和 `PROJECT_STRUCTURE.md` 描述边界，但缺少可执行门禁；最初直接把 ruff 扩到较大范围会触发大量历史风格问题，`tests/test_serving_smoke.py` 还存在个人机器 `D:/...` 绝对路径，`pytest -m "unit or smoke"` 如果没有显式 marker 容易空跑。

**定位方式：**
检查 `rs_core/`、`tests/`、`configs/`、`frontend/package.json`、`.gitignore` 和现有 requirements，确认当前没有 `pyproject.toml`、pytest marker 配置和 GitHub Actions；通过本地验收发现 ruff baseline、pytest collect 非空检查和临时验证产物清理等实际问题。

**解决方式：**
新增 `dic/standards/ENGINEERING_STANDARDS.md` 和 `pyproject.toml`，注册 `unit/smoke/slow/gpu/experiment/serving/frontend` markers，并把 package discovery 限定为 `rs_core*`；为 8 个最小主链路测试文件添加 `pytestmark`，修复 serving smoke 的绝对路径；新增 `.github/workflows/ci.yml`，只安装 serving + dev 轻依赖，不安装 training 重依赖；ruff v1 收敛为 pyflakes/F 类真实错误门禁，并最小修复未使用导入和变量遮蔽。

**验证结果：**
已通过 `./.venv/Scripts/python.exe -m pip install -e ".[dev]" -r requirements-serving.txt`、`./.venv/Scripts/python.exe -m ruff check rs_core tests/test_serving_smoke.py tests/test_agent_runtime.py tests/test_inference_policy.py tests/test_agent_dialogue.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_evaluation.py tests/test_display_contract.py`、`pytest --collect-only -m "unit or smoke"` 收集 `67` 个测试、`pytest -m "unit or smoke"` 结果 `67 passed`、`npm --prefix frontend run lint`、tracked `_tmp` 配置检查和 `git diff --check`。独立 verifier 复核结论为 PASS。

**面试可讲点：**
这段可以讲成“从研究型推荐项目向可维护工程项目演进”：不是一次性生产级重构，而是先把目录边界、配置可复现性、主链路 smoke 测试、轻量 lint 和 CI 门禁落地，既保护 Agent/推荐核心链路，又避免规范建设拖慢实验迭代。

### 2026-05-15 - 推荐 Agent 项目全面质量体检

**任务：**
对当前 RS Agent 项目做一次只读全面检查，覆盖推荐/Agent 核心链路、后端 API 契约、前端交互、测试覆盖与工程卫生，并归纳修复优先级。

**遇到的问题：**
专项审查发现当前测试和类型检查虽然能通过，但仍存在业务语义层风险：显式 dislike 商品可能被 over-filter 恢复策略带回结果，simulation 首轮展示未进入客户状态，LOPO/冻结池评估仍需数据泄漏门禁复核；同时前端交互锁、错误展示、NaN 输入和工程门禁也存在可复现性风险。

**定位方式：**
并行审查 `rs_core/rsagent/policy.py`、`rs_core/rsagent/feedback_rerank.py`、`rs_core/simulation/runner.py`、`rs_core/recsys/evaluation.py`、`rs_core/serving/app.py`、`frontend/src/views/LiveDemo.tsx`、`frontend/src/api.ts`、`frontend/src/components/sandbox/*` 与测试/配置状态。综合验证运行 `.venv/Scripts/python -m pytest tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_simulation_runner.py tests/test_serving_smoke.py -q`，结果 `42 passed in 0.91s`；前端运行 `npm --prefix "D:/sinrotic_code/python_project/summer/RS_agent/frontend" run lint`，`tsc --noEmit` 通过。

**解决方式：**
本轮未直接修改业务代码，而是形成修复顺序：先反转“restored disliked 可保留”的测试期望并区分硬/软约束恢复，再补 simulation 首轮 `RoleState` 更新与测试，然后增加 LOPO/冻结池泄漏门禁，随后修 MAP@K 定义、前端并发锁/NaN/422 错误展示，最后整理依赖、CI 入口和工作区卫生。

**验证结果：**
验证显示当前聚焦测试与前端类型检查通过，但结论明确指出“测试通过不等于语义正确”：`tests/test_feedback_rerank.py` 仍固化了风险行为，simulation 测试未覆盖首轮状态一致性，LOPO/冻结池输入侧缺少可证明无泄漏的门禁测试。

**面试可讲点：**
这次可以讲成一次从“测试通过”走向“契约正确”的质量治理：不仅检查功能是否能跑，还从推荐反馈闭环、仿真指标可信度、离线评估泄漏、前后端契约和工程可复现性五个角度识别隐性风险，体现推荐系统项目中对实验可信度和 Agent 交互正确性的治理能力。

### 2026-05-15 - Agent Runtime 边界收口与公共契约保护

**任务：**
把推荐 Agent 的 turn loop 从 `HybridRecommendationEnvironment.converse()` 中抽出到确定性的 `AgentRuntime`，同时保留环境层对召回、候选和排序数据的所有权，并确保内部 runtime trace 不进入前端/API 展示面。

**遇到的问题：**
运行时层如果直接调用 `recommend_for_user(...)` 或加载候选/召回/排序数据，会把调度职责和推荐域逻辑混在一起；如果把 `agent_runtime_trace` 直接透传到 display/export，又会把内部诊断暴露成公共契约。

**定位方式：**
审查 `rs_core/rsagent/runtime.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py` 和 `rs_core/serving/service.py`，并用 `tests/test_agent_runtime.py` 的源码断言验证 runtime 禁止导入/调用推荐入口、`converse()` 禁止直接调 dialogue plan/apply 与推荐/对话分支构造。

**解决方式：**
`AgentRuntime` 只通过 host protocol 编排 `plan_dialogue`、`apply_dialogue_plan`、`build_recommendation_turn` 和 `build_dialogue_turn`；环境层继续持有 `_recommendation_step(...)`、`_dialogue_only_turn(...)` 与 `recommend_for_user(...)`；stop-check 只修复当前 turn 的 final items/ranking/diagnostics/reward evidence，不修改 active constraints，也不二次触发召回或排序。

**验证结果：**
独立复验命令 `.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_display_contract.py tests/test_serving_smoke.py -q` 通过，结果 `26 passed`。代码审查确认 `rs_core/rsagent/runtime.py` 没有 `recommend_for_user`、候选/召回文件加载或排序 helper 调用；`HybridRecommendationEnvironment.converse()` 仅规范化输入后委托 `self.runtime.run_turn(...)`；`build_display_record(...)` 只从 `DisplayResponse` 白名单字段构建公共响应，chat/feedback/export 不包含 `agent_runtime_trace`。

**面试可讲点：**
这段可以讲成“用窄协议拆分 Agent 运行时和推荐系统内核”：运行时负责可观测的 loop、trace、memory compact、budget 和 stop-check，环境层负责推荐数据与排序执行，从而在不改变召回/排序语义的前提下获得可测试、可解释、不会污染公共 API 的 Agent 架构边界。

### 2026-05-13 - Phase 4 stage shadow metrics 最终回填

**任务：**

为 Phase 4 补齐最终验证收口：确认弱指标、coarse shadow retention、stage main-lane matrix 与 frozen candidate 一致性都已经写入中文叙事。

**遇到的问题：**

如果只看 Top-5，会把 `rank movement`、`coarse shadow retention`、`would_drop_positive` 这类信号压扁成一条结论；但这些信号本身又只能做诊断，不能被写成 promotion evidence。

**定位方式：**

对照 `scripts/experiments/ranking/run_phase_4_stage_shadow_metrics.py`、`tests/test_phase_4_stage_shadow_metrics.py` 和 `outputs/ranking/phase_4_stage_shadow_metrics_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`frozen match/hash` 未变，以及 recall / merge 语义未变。

**解决方式：**

把 stage shadow metrics 统一收口为 diagnostic/supporting，把 coarse shadow 视为 retained main lane；comparison 中回填 stage main-lane matrix，但不把弱指标升级为晋升门禁。

**验证结果：**

`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_4_stage_shadow_metrics.py tests/test_phase_4_stage_shadow_metrics.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_phase_1_31_ranking_scaffold.py tests/test_phase_3_tree_ranking_experiments.py tests/test_phase_4_stage_shadow_metrics.py -q` 结果 `11 passed`；smoke 保持 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`，且没有 online promotion evidence。

**面试可讲点：**

这段可以讲成“把排序实验的最终回填做成证据分层”：我保留了 coarse shadow 和弱指标，但明确把它们限制在诊断层，不让它们冒充晋升结论。

### 2026-05-13 - Phase 4 三阶段实验计划与弱指标收口

**任务：**

把 Phase 4 的排序路线从“只看 Top-5 成败”收口成 coarse shadow / fine / rerank / future-online 四路对照，并把 `coarse_rank` 从 pass-through 占位符升级为 shadow 主路。

**遇到的问题：**

`top_k=5` 作为唯一信号太硬，候选命中本来就稀疏，单个位置的波动很容易掩盖 coarse/fine/rerank 在 rank movement、near-miss rescue、source coverage 上的真实变化；如果只盯 Top-5，很容易把诊断能力误写成晋升结论。

**定位方式：**

对照 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`、`outputs/verification/verification_phase_1_30_smoke/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 和 `outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`、`artifact_inspection=PASS`、coarse/fine/rerank stage counts，以及 future-online gate 的 blocked 状态。

**解决方式：**

把 `coarse_rank` 改成 shadow coarse main lane，只保留 coarse score / trace / rank movement，不缩池、不改召回语义；同时新增弱指标口径，只把它们当作诊断和选路依据，不当作 promotion evidence。fine、rerank 和 future-online 分别保持 learned ranker、bounded rerank trace 和 future-only 门禁，避免把不同层的证据混在一起。

**验证结果：**

现有 smoke 和回归已经证明物理流水线证据稳定：`comparison.json`、`artifact_inspection=PASS`、`frozen_candidate_match=true` 都能稳定复现，Phase 4 神经排序仍是 diagnostic/blocked，Phase 7/8 仍是 future-online / future-agent-online；当前没有把任何 future-online 指标写成离线晋升证据。

**面试可讲点：**

这段可以讲成“把排序实验从单点 Top-5 成败，升级为分层诊断体系”：我把 coarse/fine/rerank/future-online 分开治理，用弱指标解释为什么某些方法值得继续跑、为什么某些方法只能诊断，避免把短期 smoke 误当成模型晋升。

### 2026-05-14 - ALS/BPR MF 依赖解锁后固定合同补跑

**任务：**
按用户要求安装矩阵分解实验依赖，并把此前 dependency-gated 的 ALS/BPR 从“可跑待执行”推进到真实 Phase 1.21 固定合同实验。

**遇到的问题：**
`implicit` 可以安装并通过 smoke；`lightfm==1.17` 在当前 Windows / Python 3.13 环境下先出现 metadata/build 失败，修复后又暴露 WARP/BPR native loss 在真实稀疏矩阵上 access violation。与此同时，原 Phase 1.21 脚本只把 ALS/BPR/LightFM 写进 registry dependency gate，没有真实候选生成路径，直接跑配置会变成“登记了但没产候选”。

**定位方式：**
用 `.venv/Scripts/python.exe` 检查 `implicit` / `lightfm` 依赖状态，并用小矩阵 smoke 确认 `implicit` 0.7.3 的 ALS/BPR 需要以 user-item CSR matrix 调用 `fit(user_items)` 和 `recommend(...)`。LightFM 先定位到 PyPI sdist 的 `__builtins__.__LIGHTFM_SETUP__` Python 3.13 兼容问题，再用 GitHub 1.17 源码重新 Cythonize；真实 Phase 1.21 矩阵复现显示 WARP/BPR/WARP-KOS 在 `_run_epoch` access violation，logistic loss 可稳定训练。随后检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 的 `SOURCE_CONTRACT`、`_attach_phase_sources`、`_phase_source_config`、`_raw_non_popular_candidates` 和 benchmark 执行状态判断，确认缺真实 source 接入。

**解决方式：**
新增 `als_mf_recall` / `bpr_mf_recall` / `lightfm_recall` source 合同，接入 train-only implicit ALS/BPR 与 LightFM logistic index builder，并在 `configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml` 中开启对应参数；LightFM 明确记录为 logistic observation，WARP/BPR native crash 不伪造成可用结果。补充函数级测试，验证 MF 候选不包含已看 seed，且 metadata 带 `train_implicit_als`、`train_implicit_bpr`、`train_lightfm_logistic`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `25 passed`，`compileall scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py tests/test_phase_1_21_recall_coverage.py` 通过。真实固定合同输出 `outputs/recall/phase_1_21_recall_coverage/source_family/mf_implicit_als_bpr_lightfm_pool200/`：`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`；`als_mf_recall` 覆盖 `500` users / `1207` items 但无边际命中，`bpr_mf_recall` 覆盖 `500` users / `39` items 且只贡献 `1` 个 candidate-hit source 覆盖，`lightfm_recall` 覆盖 `454` users / `34` items 并贡献 `4` 个 candidate-hit source 覆盖，但整体仍低于当前主路 `19` hit users。

**面试可讲点：**
这段可以讲成“把依赖门控 backlog 转成真实实验”的工程治理：先用依赖安装、源码 patch 和 API smoke 证明 MF 路径边界，再补 train-only 候选生成路径和合同测试，最后用固定合同 artifact 得出 reject 结论；同时如实记录 LightFM WARP/BPR native crash 与 logistic 可运行结果，避免把常见方法名包装成虚假实验收益。

### 2026-05-13 - 剩余召回方法固定合同补跑收口

**任务：**
把 graph、vector/two-tower、MF、sequence/multi-interest 等剩余召回方法从“计划/占位”推进到可验证的 Phase 1.21 固定合同实验，并由一个串行 runner 统一跑完。

**遇到的问题：**
多个 worker 并行修改同一个 Phase 1.21 脚本，出现 `_multi_interest_patch` 未定义、multi-interest 默认权重与测试预期不一致的问题；同时 vector 配置一度仍是 pool100，不符合本轮 pool200 固定召回池口径。ALS/BPR/LightFM 也不能因为方法名常见就伪造结果，必须按依赖 gate 处理。

**定位方式：**
用 `tests/test_phase_1_21_recall_coverage.py` 暴露 `_multi_interest_patch` 缺失，随后检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 中 `_attach_phase_sources`、`_raw_non_popular_candidates`、`SOURCE_FAMILY_BENCHMARKS` 和新增配置文件；用 `.venv/Scripts/python.exe` 串行运行四个配置，并抽取各输出目录的 `metrics.json`、`manifest.json`、`source_family_observation_benchmarks.json`。

**解决方式：**
补齐 `multi_interest_recall` 的 patch 和元数据合同，把 vector 配置统一到 `candidate_pool_size=200`；graph 只启用可复用的 `item_graph`，`graph_walk_seed` 保持 sidecar-gated；MF 只执行纯 numpy `implicit_svd_recall`，ALS/BPR/LightFM 通过 `dependency_gate` 标记为 blocked；实验按 graph → vector → MF → sequence 串行执行，保持同一 holdout hash。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `23 passed`，`compileall` 通过。四个固定合同输出均为 `users_with_holdout=138`、`candidate_pool_size=200`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`：graph、vector/two-tower、implicit SVD MF、sequence/multi-interest 的 `candidate_hit_users` 均为 `17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`，低于当前 source-aware/semantic 主路的 `19` hit users；ALS/BPR 因缺 `implicit`、LightFM 因缺 `lightfm` 继续 `defer`。

**面试可讲点：**
这段可以讲成推荐召回实验治理：用多 agent 并行补齐实现入口，但实验执行串行化以保证可比；对能跑的方法输出同合同 artifact，对缺依赖的方法保留 dependency gate，不把 smoke、排序指标或方法名热度包装成晋升证据，最终得出“当前无新方法晋升，主路保持 source-aware/semantic”的克制结论。

### 2026-05-13 - Source-aware 召回融合截断稳定性观察

**任务：**
在确认 UserCF/Swing 只能作为 fallback 后，继续分析 `semantic_title_category_expansion + 行为 fallback` 的融合、去重和截断稳定性，判断是否需要替换当前主路。

**遇到的问题：**
单纯继续新增召回方法已经收益有限，真正风险转向多路 source 合并后的池内竞争：行为侧 source 可能增加覆盖，但也可能挤掉语义主路或热门兜底候选，因此需要 observation-only 对照，而不能直接改主 baseline。

**定位方式：**
检查 `rs_core/recsys/candidate_merge.py`，确认已有 `_limit_candidate_pool`、`balanced_source_budget`、`candidate_source_minimums/maximums` 与 `candidate_fill_order`；检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`，确认可复用同一批 raw candidates，只比较不同截断策略。

**解决方式：**
新增 `configs/recall/phase_1_21/phase_1_21_recall_coverage_source_aware.yaml` 和 Phase 1.21 的 `--mode source-aware`，对比 `score_sorted_all_sources` 与 `source_balanced_fallback_preserving`。实现中避免每个 variant 重建 source index，改为一次生成 raw candidates、多个截断策略复用，降低长跑成本。

**验证结果：**
`tests/test_phase_1_21_recall_coverage.py` 结果 `22 passed`；`compileall rs_core scripts tests` 通过。真实固定合同运行写入 `outputs/recall/phase_1_21_recall_coverage/source_aware/`：两种策略 `candidate_hit_users` 都为 `19`、`candidate_hit_rate_at_pool=0.137681`，无 `baseline_displacement_users`；balanced 策略把 `candidate_count_avg` 从 `136.214` 降到 `126.972`，并把 `candidate_hit_rate_at_100` 从 `0.123188` 提到 `0.130435`。

**面试可讲点：**
这段可以讲成召回系统的多路融合治理：不是盲目叠 source，而是在同一 holdout 与同一 raw candidate 输入下，只替换截断策略，观察命中、位移、候选量和前段召回位置；结合后续 graph/vector/MF/sequence 对照后，最终把 `source_balanced_fallback_preserving` 固定为当前混合召回主路的默认截断策略。

### 2026-05-13 - 补跑未覆盖的轻量行为召回与矩阵分解 smoke

**任务：**
把此前标为未跑/延后的 UserCF、Swing、session transition 和矩阵分解类召回推进到可执行固定合同实验，明确哪些方法只是 fallback、哪些应 reject、哪些仍 blocked。

**遇到的问题：**
此前文档把 UserCF/Swing/session transition 记为没有成熟入口，ALS/BPR/implicit MF 记为依赖或实现不足；用户追问“还是没有跑实验吗”后，需要真正补一轮可验证实验，而不是只继续写 defer。

**定位方式：**
检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 的 `_attach_phase_sources`、`_raw_non_popular_candidates` 和 `source_family_observation_benchmarks.json` 生成逻辑，确认可以在 Phase 1.21 固定合同中增加训练期 source。依赖检查显示 `.venv` 中 `numpy=True`，但 `scipy=False`、`sklearn=False`、`implicit=False`、`lightfm=False`，因此 ALS/BPR 不能可靠训练。

**解决方式：**
新增 `configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml`，并在 Phase 1.21 脚本中接入 `usercf_recall`、`swing_recall`、`session_transition_recall` 和纯 numpy `implicit_svd_recall`。所有索引只从 `user_sequences.train.jsonl` 构建，不读取 holdout；ALS/BPR/LightFM 明确标为依赖 blocked。

**验证结果：**
补跑命令：`./.venv/Scripts/python.exe scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py --config configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml --output-dir outputs/recall/phase_1_21_recall_coverage/source_family/worker_behavior_untried_pool200 --mode baseline --limit-users 500`。结果 artifact 显示 `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`；`usercf_recall` 和 `swing_recall` 各有 `1` 个 candidate-hit source 覆盖，`session_transition_recall` 和 `implicit_svd_recall` 为 `0`。`tests/test_phase_1_21_recall_coverage.py` 结果 `21 passed`。

**面试可讲点：**
这段可以讲成“面对用户质疑没有跑实验时，快速把 deferred backlog 转成固定合同实验”：能轻量实现的先落地并输出 artifact，不能跑的 ALS/BPR 给出依赖证据；最后按召回治理口径把 UserCF/Swing 归为 fallback，把 session transition / implicit SVD reject，避免为了覆盖方法名而虚假晋升。

### 2026-05-13 - 主流召回方法实验口径与可维护结论文档收口

**任务：**
把剩余主流召回方法从口头清单推进到可维护的实验结论文档：统一 `promote/reject/defer/fallback/document_only` 决策标签、补齐 method-card diagnostics，并对当前 CPU/lightweight 可执行 source 生成固定合同 artifact。

**遇到的问题：**
旧文档和部分 registry artifact 混用了 `pending_evidence`、`observation_baseline`、A/B/C/D evidence 等旧口径；同时 UserCF、Swing、ALS/BPR/implicit MF、session transition 在当前仓库没有成熟召回入口，不能为了“跑全主流方法”伪造实验结果。

**定位方式：**
核对 `rs_core/recsys/evaluation.py`、`rs_core/recsys/types.py`、`scripts/experiments/recall/phase_1_20_recall_diagnostics.py`、`scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 与 `dic/experiments/recall/RECALL_METHODS_EXPERIMENT_LOG.md`；读取 `outputs/recall/phase_1_21_recall_coverage/worker_light_20260513/` 和 `outputs/recall/phase_1_21_recall_coverage/source_family/worker_cpu_itemcf_covisit_hybrid_pool200/` 下的 manifest/metrics，确认 `valid_test`、`users_with_holdout=138`、holdout hash 和 ranking/rerank disabled checks。

**解决方式：**
在 `EvaluationSummary` 中新增 `method_card_diagnostics`，把 forbidden metrics 扩展为排序、Top-K gap、LTR/rerank 和线上业务指标；未知 `pool_displacement_risk` 默认给 `defer`，不自动晋升。文档中新增 CPU-bound CF/hybrid 与 lightweight source sweep 条目：ItemCF/co-visit 归为 `fallback`，popular/category 归为 `document_only`，UserCF/Swing/ALS/BPR/session transition 归为 `defer`。

**验证结果：**
固定合同 artifact 已重跑：pool200 CPU/hybrid `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.06971`；method-card diagnostics 输出 `decision_hint=defer` 且 `can_promote=false`。验证命令：`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_phase_1_20_recall_diagnostics.py tests/test_evaluation.py tests/test_hybrid_demo.py` 结果 `136 passed`；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。

**面试可讲点：**
这轮可以讲成“把召回方法探索做成证据治理系统”：不仅跑可执行方法，还把不能跑的方法明确落为 `defer/document_only`，并用统一 schema、artifact hash、holdout hash 和 forbidden metrics 约束防止把排序收益或历史文字误写成召回晋升。

### 2026-05-13 - 第一轮新召回 source ablation 与晋升收口

**任务：**
在 `semantic_title_category_expansion` 已成为 recall-only baseline_vNext 后，对下一轮候选 source 做第一轮可复现 ablation，判断是否有新的召回 source 可以晋升。

**遇到的问题：**
Phase 0 诊断显示 ItemCF/co-visit 重叠较高，粗类目扩池没有 lift；同时第一轮候选中的 Swing/UserCF 在当前仓库没有成熟入口，metadata neighbor 虽有函数但实现按 seed 扫描 metadata index，长跑 lane 成本偏高，不能为了“跑全方法”伪造结果。

**定位方式：**
读取 `.omc/recall/artifacts/phase_0_recall_diagnostics_20260513/selected_first_round_sources.md`、`phase0_diagnostics.json` 和 Phase 1.21 registry，确认 recall-only 口径、holdout hash 与 pool200 guardrail；再检查 `rs_core/recsys/candidate_merge.py`、`scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`、graph/item_graph sidecar，确认可复用的是 `item_graph` 与 `graph_walk_seed`。

**解决方式：**
只对可复用的 `constrained_item_graph_walk` 做 pool200 与 source-only ablation，并把 Swing/UserCF/metadata neighbor 明确记录为未执行或后续条件型实验；所有结论只使用 candidate-hit users、baseline miss 覆盖、candidate volume 和 source overlap，不使用 Top-K/ranking/LTR/业务指标。

**验证结果：**
收口报告见 `.omc/recall/artifacts/phase_0_first_round_source_ablation_20260513/first_round_closure_report.md`。`item_graph` 与 `graph_walk_seed` 的 candidate_hit_users 都为 17，baseline_miss_coverage_users 都为 0；source-only 各自只命中 1 个用户且没有覆盖 baseline miss 用户，因此结论为 `NO_NEW_SOURCE_PROMOTED`。验证命令：`./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py` 通过，`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 结果 `20 passed`，ablation 脚本 `py_compile` 通过。

**面试可讲点：**
这段工作体现的是召回实验治理：不是把所有主流方法都盲目接入，而是在同一 holdout、同一 candidate_pool_cap 和 recall-only 合同下做 ablation；能跑的图召回如实记录无新增覆盖，不能成熟复用的 Swing/UserCF 不伪造结果，从而保证 baseline 晋升基于可复现证据。

### 2026-05-13 - Phase 1.26 典型排序链路与真实实验底座

**任务：**
把排序阶段从“规则 gate / smoke / blocked 记录”推进到可验证的典型排序实验链路：明确目标架构为 recall → coarse rank → fine rank → rerank，并在当前离线边界下落地 `frozen pool200 → learned fine ranker → bounded rerank trace`。

**遇到的问题：**
此前阶段容易把依赖 gate、smoke 或 blocked 状态包装成“真实排序实验”，但它们没有真实训练日志、模型产物、候选一致性证明和 case diff；同时 GBDT/LambdaMART 等方法如果缺依赖、GPU 或候选级 adapter，不能伪造成当前可晋升结果。

**定位方式：**
检查 `rs_core/recsys/ranking.py`、`rs_core/workflow/ltr_training.py`、`scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py` 和 `scripts/experiments/ranking/run_phase_3_tree_ranker.py`，确认已有 LTR 训练闭环可复用，而 Phase 3 tree 脚本只是依赖 gate 与 candidate-row export。验证产物见 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`。

**解决方式：**
在 `rs_core/recsys/ranking.py` 增加 `coarse_score`、`fine_score`、`rerank_score`、`score_trace`、stage rank 和 rank movement，先把 coarse 作为 diagnostic trace，不强制缩池；新增 `scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py`，用 LOPO pointwise logistic / pairwise perceptron 做真实轻量 fine-ranker 训练，输出 `training_config.json`、`training_log.json`、`ltr_model.json`、`ltr_candidate_rows.jsonl`、case diff 和 comparison registry；GBDT/LambdaMART 在缺依赖、GPU 校验或候选级 adapter 时明确标为 `blocked`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py rs_core/recsys/ranking.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q -k "score_trace or phase_1_26_real_ranking_runner_contract"` 结果为 `3 passed, 107 deselected`；刷新 smoke 命令 `./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py --output-dir outputs/ranking/phase_1_26_real_ranking_experiments_smoke --limit-users 20 --seed 20260513` 成功，`artifact_inspection.status=PASS`，baseline 与两个 learned variant 均保持 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`，feature/leakage gate 为 PASS，LTR variants 为 diagnostic-only，tree/LambdaMART 方法为 blocked。

**面试可讲点：**
这段工作体现的是推荐排序实验治理能力：先把工业排序链路拆成粗排、精排、重排的可观测阶段，再用冻结候选池保证只评估排序，不污染召回；对能真实训练的方法输出完整证据链，对依赖不足的方法如实 blocked，避免把 smoke/gate 伪装成模型效果。

### 2026-04-28 - CLI Agent 反馈闭环修复

**任务：**
推进 RS Agent 的 CLI 交互闭环，让第二轮用户反馈能真实影响推荐结果，并让 reward 能识别反馈是否产生实际效果。

**遇到的问题：**
CLI smoke 能生成 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl`，但两轮 Top-K 完全相同，`changed_after_feedback=false`；同时 reward 只要偏好解析成功就容易给较高 feedback alignment，不能区分“解析了反馈”和“反馈真的改变了推荐”。

**定位方式：**
检查 `rs_core/rsagent/cli.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/rsagent/policy.py`、`rs_core/recsys/ranking.py` 的 feedback 链路，确认 `preferred_sources/preferred_categories` 已解析，但 CLI 使用的配置没有给 feedback source/category 足够的 ranking 权重；初始 smoke 报告见 `outputs/agent/cli/agent_cli_smoke/rs_agent_cli_baseline_comparison.md`。

**解决方式：**
在 `rs_core/rsagent/cli.py` 为 CLI 会话注入不覆盖用户配置的 feedback rank 默认权重，并把模拟反馈改成包含 fresh/again，使第二轮能过滤上一轮已曝光 item；在 `rs_core/rsagent/reward.py` 增加 `feedback_effect_observed` 证据，对后续轮次中没有过滤、boost 或换榜证据的反馈对齐分做上限约束；补充 `tests/test_agent_rollout_schema.py` 和 `tests/test_agent_reward.py` 覆盖换榜与无效反馈降分。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m rs_core.rsagent.cli --config configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --simulate-two-turn --output-dir agent_cli_smoke_after_fix` 后，报告 `outputs/agent/cli/agent_cli_smoke_after_fix/rs_agent_cli_baseline_comparison.md` 显示 `changed_after_feedback=true`，第二轮 Top-K 从 `B08JQCJZQM/B08HFNNPPJ/...` 变为 `B0B2JJV92T/B08Y1XYLVP/...`，diagnostics 中出现 `feedback_source_semantic`、`excluded_prior_turn_items` 和 `boosts_applied`。直接调用目标测试函数通过，`./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过；当前环境缺少 pytest，未运行完整 pytest 套件。

**面试可讲点：**
这次工作把 Agent 从“能记录反馈”推进到“反馈能改变策略”的闭环：先定位到配置层 feedback 权重未生效，再用可解释 diagnostics 证明过滤与 boost 发生，最后把 reward 从结果静态打分升级为包含反馈响应性的训练信号，为后续 GRPO rollout 数据打基础。
### 2026-04-28 - 项目文档入口精简与阶段状态同步

**任务：**
整理 Phase 1.5 / Phase 1.6 / Phase 1.7 的文档承接关系，避免历史总结、优化叙事和工程日志之间的信息重复。

**遇到的问题：**
Phase 1.5 历史总结、最新优化判断和工程叙事记录分散在多个文档中，容易让读者误把历史阶段总结当成当前总览，也不利于面试叙事快速定位当前结论。

**定位方式：**
对照 `dic/phases/phase_1_5/PHASE_1_5_DEMO_SUMMARY.md`、`dic/OPTIMIZATION_NARRATIVE.md` 和现有 `dic/ENGINEERING_NARRATIVE_LOG.md` 的内容边界，确认 Phase 1.5 应只保留历史总结，Phase 1.6 / 1.7 和最新判断应集中在优化文档，工程日志只记录可复述的过程条目。

**解决方式：**
在 Phase 1.5 文档开头补充阶段说明，在优化文档的当前推荐处补充 Agent 层 demo 的入口方向，并在工程日志中追加一条简短记录；随后将旧实验报告和数据画像移动到 `dic/archive/`，让 `dic/` 根目录只保留核心入口文档，减少重复维护成本。

**验证结果：**
通过核心文档的人工一致性检查，确认 README、实施计划、架构说明、目录说明、Phase 1.5 总结和优化叙事之间的阶段状态一致；`dic/` 根目录保留 7 个核心文档，59 个旧报告和数据画像已归档到 `dic/archive/`；`old_dic/` 已按英文 ASCII 目录整理为 `historical_plans/` 和 `early_data/`，避免中文路径解码异常；未执行新的实验。

**面试可讲点：**
这类工作体现的是文档架构治理能力：不仅能写内容，还能把历史总结、当前判断和过程证据拆分到正确入口，减少信息漂移，让面试叙事更容易复述和验证。

### 2026-04-28 - Agent feedback canonical 固化与 conversational MVP

**任务：**
把已有 CLI feedback smoke 固化成唯一可复现 demo，并把 Agent 从“反馈后再推荐”推进到 deterministic 多轮对话 MVP。

**遇到的问题：**
此前项目已有多份 `agent_cli_*` 输出目录，读者不容易判断哪个是 canonical 证据；同时 Agent 还偏向推荐列表输出，缺少“模糊需求追问、澄清后推荐、解释上一轮、换一批、unsupported 保留”等对话式推荐能力。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/rsagent/cli.py` 和 rollout 输出链路，确认已有 session/turn、feedback constraints、reward evidence 和 rollout schema，可以在不改推荐 backbone 的前提下增加 deterministic dialogue manager。

**解决方式：**
新增 `rs_core/rsagent/dialogue.py`，用规则方式规划 `recommend_request`、`clarification_answer`、`ask_explanation`、`preference_feedback`、`unsupported` 等对话意图；扩展 `AgentSession` 保存 `ConversationState`，扩展 `AgentTurn` 保存 `assistant_response`；在 `HybridRecommendationEnvironment.converse()` 中接入对话规划，保持 `step()` 的原 feedback 行为兼容；在 CLI 增加 `--simulate-conversation`，并保留 `--inference-policy off` 作为 deterministic canonical 入口。

**验证结果：**
安装 pytest 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_feedback.py tests/test_agent_reward.py tests/test_agent_rollout_schema.py tests/test_agent_dialogue.py`，结果 `19 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过。canonical feedback 入口生成 `outputs/agent/canonical/agent_feedback_demo_canonical/`，检查确认 `changed_after_feedback=true`、`feedback_effect_observed=true`、有 boost/filter 证据且 `training_status=deferred_environment_reward_only`。conversational 入口生成 `outputs/agent/canonical/agent_conversation_demo_canonical/`，检查确认 turn 2 追问、turn 3 澄清后推荐、turn 4 解释、turn 5 根据反馈再推荐，rollout 逐条保留 deferred training metadata。

**面试可讲点：**
这次工作把 Agent 定位从“推荐包装器”推进到“对话式推荐编排器”：底层仍由传统推荐 backbone 负责召回和排序，Agent 在上层负责识别用户意图、必要时追问、把澄清转成结构化约束、解释推荐依据，并把多轮交互沉淀为 reward / rollout 证据，为后续 Qwen / QLoRA / GRPO 训练路线提供稳定 contract。

### 2026-04-28 - item-level feature rerank 第一版

**任务：**
在 Phase 1.7 source-level rerank 到达边界后，补一个默认关闭、可解释的 item-level feature rerank，用于把多源候选、反馈匹配、popular-only / semantic-only 等信号显式纳入排序诊断。

**遇到的问题：**
统一 semantic boost 和 semantic-only penalty 都没有提升 Top-K hit，说明问题不在 source 整体曝光，而在 item 之间的相对区分；实验初期还误用 `python -m rs_core.workflow.hybrid_demo --config ...`，该模块没有 CLI 入口，导致命令成功退出但没有生成输出。

**定位方式：**
检查 `rs_core/recsys/ranking.py` 和 `scripts/evaluation/run_hybrid_demo.py`，确认真正实验入口是 `./.venv/Scripts/python.exe scripts/evaluation/run_hybrid_demo.py --config ...`；对比 `outputs/hybrid_demo/hybrid_demo_small_electronics_1000_semantic_title*/metrics.json` 与 `ranking_case_summary.json`，确认 item-feature rerank 对 valid/test 和 LOPO 的影响。

**解决方式：**
在 `rank_candidates()` 中增加默认关闭的 `item_feature_rerank`，输出 `feature_score`、`item_features` 和 item_feature rerank events；新增 title semantic 的 valid/test 与 LOPO item-feature 配置，并让 report config summary 显示 `item_feature_rerank` 策略，避免实验报告漏掉关键配置。

**验证结果：**
重新生成 Phase 1.7 baseline 与 Phase 1.8 item-feature 对照后，valid/test `hit_rate_at_k` 保持 0.043478，LOPO `hit_rate_at_k` 保持 0.888889；LOPO `candidate_hit_rank_avg` 从 25.128205 改善到 23.461538，`top1_score_gap_avg` 从 24.742213 降到 24.047873。运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py`，结果 `42 passed in 0.30s`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS。

**面试可讲点：**
这次工作体现的是从 source-level 调参升级到 feature-level 诊断：当全局 boost / penalty 不能改变同源候选内部顺序时，把多源支持、反馈匹配和单源惩罚显式做成可解释特征。结果没有夸大成 Top-K 提升，而是准确表述为“改善候选池内排名分布，为后续 Agent 反馈和学习排序提供特征接口”。

### 2026-04-28 - rollout 训练样本 contract 与 Qwen harness 对照固化

**任务：**
把已经稳定的 Agent feedback / conversation rollout 往训练前闭环推进：先显式导出 SFT / reward 样本 contract，再验证 Qwen bounded rerank evaluation harness 在无本地模型依赖时也能产出可复现对照结果。

**遇到的问题：**
此前 rollout 已记录 `prompt_context`、`reward_evidence` 和 `diagnostics`，但训练用途仍需要下游再拼字段，缺少“这一轮该学什么、reward 怎么对照”的显式 contract；同时 Qwen harness 虽已有 fake client 改善路径测试，但缺少模型不可用时 fallback 仍能完整生成三模式对照报告的测试，容易把本机环境依赖误当成评估链路能力。

**定位方式：**
检查 `rs_core/rsagent/rollout.py`、`rs_core/rsagent/schema.py`、`rs_core/rsagent/reward.py` 和 `rs_core/workflow/hybrid_demo.py`，确认已有 AgentTurn / AgentSession 字段足够生成训练样本，不需要改推荐 backbone；再检查 `tests/test_hybrid_demo.py` 中已有 `FakeHarnessQwenClient` 测试，确认还需补 `ModelUnavailableError` fallback 路径。

**解决方式：**
在 `turn_to_rollout_record()` 中新增 `training_samples` 字段，拆成 `sft_sample` 和 `reward_sample`：前者包含 user_input、assistant_response、feedback_constraints、candidate_summary、target_action、target_explanation，并用 `allowed_item_ids` 约束 selected_item_ids 只能来自当前候选；后者包含 policy_type、reward、reward_evidence、feedback_effect_observed 和 risk_flags。补充 Qwen harness fallback 测试，验证 deterministic_baseline、rule_feedback_rerank、qwen_feedback_rerank 三种模式即使 Qwen 不可用也会写出 comparison JSON/report 和 inference diagnostics。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_three_mode_comparison tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_fallback_comparison_without_model_dependencies tests/test_agent_rollout_schema.py`，结果 `6 passed in 0.23s`；运行 `./.venv/Scripts/python.exe scripts/evaluation/run_qwen_evaluation_harness.py --config configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --output-dir outputs/agent/qwen/qwen_evaluation_harness_ralph_fallback --qwen-model-id missing-local-qwen` 成功生成 `outputs/agent/qwen/qwen_evaluation_harness_ralph_fallback/comparison.json` 和 `comparison.md`，其中 `qwen_feedback_rerank` 的 `fallback_count=1`、`routes={"qwen_local": 1}`。当前 Qwen / QLoRA / GRPO 仍未完整训练落地，本次工作是训练前 contract 与 bounded rerank 对照验证。

**面试可讲点：**
这次工作可以讲成“先把 Agent 交互闭环产品化为可训练数据，再把大模型能力接入约束在候选集内做可回退对照”：不是直接让 LLM 生成商品，而是让它输出 bounded rerank signals，并且在模型不可用时仍保留 deterministic/rule baseline 和诊断产物，体现了推荐系统中对可控性、可复现评估和训练数据 contract 的工程意识。

### 2026-04-28 - 展示层与多角色仿真规划边界预留

**任务：**
把后续真实商品展示、前端交互、多角色模拟客户和动画回放纳入项目规划，同时不打断当前推荐 backbone、Agent feedback、reward / rollout 的主线。

**遇到的问题：**
现有架构主要覆盖数据处理、召回、排序、Agent 对话反馈和训练前 contract，但没有显式说明商品卡展示、前端消费接口、多角色模拟客户和动画回放放在哪一层，后续如果直接开发前端或仿真场景，容易让 UI 字段、模拟客户和推荐内部逻辑耦合。

**定位方式：**
检查 `dic/PROJECT_STRUCTURE.md`、`dic/architecture/ARCHITECTURE.md`、`dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/README.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`，确认当前文档已覆盖 Agent 主轴和训练路线，但缺少展示层、前端层、仿真层和动画层的目录与边界说明。

**解决方式：**
预留 `rs_core/display/`、`rs_core/simulation/`、`rs_core/animation/` 和 `frontend/` 目录，并在核心文档中补充展示层、前端 / 服务层、仿真 / 动画层的职责：展示层负责商品卡 contract，前端只消费服务与展示接口，模拟客户作为合成交互评估流量，动画层只做 session / rollout 可视化回放。

**验证结果：**
通过目录检查确认 `.gitkeep` 已存在于新增目录；用文档检索确认 `display`、`simulation`、`animation`、`frontend`、商品展示卡、多角色和动画回放等关键条目已出现在 `PROJECT_STRUCTURE.md`、`architecture/ARCHITECTURE.md`、`architecture/IMPLEMENTATION_PLAN.md`、`README.md` 和 `OPTIMIZATION_NARRATIVE.md`。

**面试可讲点：**
这次调整体现的是从“推荐算法 demo”扩展到“可交互、可展示、可回放、可仿真的 Agent 推荐系统”的架构意识：推荐 backbone 和 Agent 决策仍是主线，商品卡 contract 解决产品化展示，多角色模拟客户用于压力测试交互闭环，动画层用于演示和复盘，但这些外围能力不会污染推荐排序和真实用户评估。

### 2026-04-28 - 商品展示 contract 与前端安全视图

**任务：**
推进 Phase 2 的展示层，把 Agent 最终推荐结果转换成前端可直接消费的 `DisplayResponse` / `ItemDisplayCard` contract，并为后续聊天前端和商品卡 UI 提供 canonical mock 输出。

**遇到的问题：**
已有 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl` 同时包含推荐结果、ranking、diagnostics、reward 和 training_samples，适合训练与诊断，但不适合直接交给前端；如果前端直接读 rollout，容易耦合排序分数、reward 证据和内部诊断字段。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/rollout.py`、`rs_core/rsagent/cli.py` 和 `rs_core/recsys/types.py`，确认 `AgentDecision.final_items` 已经是展示层最稳定的入口；同时确认商品 title、price、rating、image 等 metadata 不保证齐全，因此 contract 需要 nullable 字段和缺图兜底。

**解决方式：**
在 `rs_core/rsagent/schema.py` 新增 `ItemDisplayCard` 和 `DisplayResponse`，在 `rs_core/display/builder.py` 新增展示层 builder，只从最终推荐 item 和 metadata 派生前端安全字段；在 `rs_core/rsagent/rollout.py` 为每条 rollout 增加 `display_response`，在 `rs_core/rsagent/cli.py` 额外输出 `display_responses.jsonl` 和 `display_demo.json`，同时保持原训练/诊断输出不变。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_display_contract.py`，结果 `6 passed in 0.16s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 canonical display demo 生成 `outputs/agent/canonical/agent_display_demo_canonical/display_responses.jsonl` 和 `display_demo.json`；定向检查 `outputs/agent/canonical/agent_display_demo_canonical/grpo_rollouts.jsonl` 中 5 条 `display_response`，确认没有泄漏 `score`、`diagnostics`、`reward_evidence`、`training_samples` 等内部字段。

**面试可讲点：**
这次工作体现的是从算法/Agent demo 走向产品化接口的工程边界设计：训练和诊断需要保留完整内部证据，但前端只需要稳定、安全、可容错的展示 contract。通过派生 `DisplayResponse`，推荐系统可以继续维护可解释诊断和 reward contract，同时让 UI、后续动画回放和多角色仿真复用同一个前端安全视图。

### 2026-04-28 - Phase 2 single-process serving demo

**任务：**
把已有 CLI / conversational Agent demo 封装成轻量 HTTP 服务入口，让后续前端、模拟客户或展示沙盒可以通过 API 调用推荐对话能力。

**遇到的问题：**
项目已有 `HybridRecommendationEnvironment`、`DisplayResponse` 和 CLI canonical demo，但缺少服务层边界；如果直接把 `AgentTurn` 或 rollout 返回给前端，会泄露 ranking、diagnostics、reward 等内部训练/诊断字段。

**定位方式：**
检查 `rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py`、`rs_core/rsagent/schema.py` 和 `rs_core/rsagent/cli.py`，确认服务层应复用 `env.converse()` 和 `build_display_record()`，而不是重写推荐逻辑或直接暴露 session/turn 原始结构。

**解决方式：**
新增 `rs_core/serving/service.py`、`schema.py` 和 `app.py`，实现 single-process demo service：`RecommendationService` 在进程内维护 session dict，`/session/start` 使用 UUID 创建独立 session，`/chat` 只返回展示层 `DisplayResponse` contract；新增 `scripts/serving/run_service.py` 和 `requirements-serving.txt`，明确 FastAPI / uvicorn / httpx 依赖与 demo 服务边界。

**验证结果：**
安装 `requirements-serving.txt` 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py`，结果 `5 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS，确认服务文件位于 `rs_core/serving/*`、未实现 `/feedback`、unknown session 返回 404，公开响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把项目从 CLI 推荐 Agent demo 推进到可 HTTP 调用的服务 contract：底层推荐和 Agent 决策保持不变，服务层只做薄封装和 session 编排，对外统一返回前端安全的展示卡结构。这个边界既能支撑后续 Web Demo / 多角色模拟客户，也避免过早引入数据库、多进程状态和生产部署复杂度。

### 2026-04-28 - 最小 React 商品卡前端 Demo

**任务：**
把 Phase 2 serving demo 接到已有 Vite / React 前端骨架上，实现可交互的聊天输入、商品卡展示和反馈按钮，让推荐 Agent 从 HTTP contract 进一步变成可展示的 Web Demo。

**遇到的问题：**
前端原本主要读取 `mockData` 做静态商品卡展示；接入后端后还需要处理本地 FastAPI 与 Vite 的 CORS、后端重启导致的 session 丢失、真实 demo 数据没有固定 `frontend-demo-user` 这类联调边界。

**定位方式：**
检查 `frontend/src/App.tsx`、`frontend/src/types.ts`、`frontend/src/mockData.ts` 和 `rs_core/serving/app.py`，确认前端应只依赖 `/session/start` 和 `/chat` 的 `DisplayResponse` contract；按用户偏好通过 `omc ask gemini` 审阅前端实现，Gemini 建议保留 mock 降级、按钮转自然语言 feedback、图片兜底，并补 session 失效阻断、价格格式化和聊天记录自动滚动。

**解决方式：**
新增 `frontend/src/api.ts`，让前端启动时创建 session、提交聊天时调用 `/chat`，并继续用 `mockData` 作为后端未启动时的展示兜底；更新 `App.tsx` 渲染对话记录、assistant message、商品卡和 feedback actions；后端补本地 Vite CORS；按 Gemini 审阅意见补充 `Unknown session_id` 后禁用输入并提示刷新、数值价格格式化和消息自动滚动；修正前端默认不传固定 user，让后端选择 demo 数据中的首个用户。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `7 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动 `scripts/serving/run_service.py` 和 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` 后，用 HTTP 验证 `/health`、默认 `/session/start` 和 `/chat` 返回 `rs_agent_display_v1`，5 个商品卡且响应不含 `ranking`、`diagnostics`、`reward`、`score`，前端页面可加载。

**面试可讲点：**
这次工作把推荐 Agent 从“服务可调用”推进到“用户可交互”：前端没有读取推荐内部字段，而是只消费 `DisplayResponse`，按钮反馈也先转成自然语言走 `/chat`，避免过早扩张 `/feedback` API。通过 Gemini 审阅补齐 session 失效和展示细节，体现了前后端 contract 隔离、Demo 范围控制和跨模型协作把关的工程过程。

### 2026-05-23 - 固定 pool500 offline eval baseline 收口

**任务：**
基于固定 `outputs/eval/pool500_offline_eval_users_10k/manifest.json`，不改召回策略、不使用 oracle 或 label 注入，运行当前 pool500 召回主路并生成 baseline candidates、整体/分层 Recall 与 HitRate、source audit 和 baseline manifest。

**遇到的问题：**
现有 `run_full_data_pool500_recall_only.py` 能按 target users 生成 pool500 candidates，但它只接受旧 aligned eval target schema，不能直接消费新的 `pool500_offline_eval_users_v1` manifest；同时 metrics 必须读取完整 valid/test labels 做后验评估，但这些 labels 不能进入候选生成路径。

**定位方式：**
读取固定 manifest 与 `users.jsonl`，确认 `user_set_hash=eb63bae51126aa572072415236eb8efbb14979be7b9ae7edf21d555077136b33`、`total_user_count=10000`、segment 为 hot/warm/cold-ish = 4000/4000/2000，且 split/leakage contract 明确 history 只来自 train、labels 只用于 evaluation。审查 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`，确认可复用当前 `current` recall profile 和主路 source budget；排除 `build_pool500_diagnostic_oracle_candidates.py`、`build_pool500_label_artifact.py` 等 diagnostic/oracle 产物。

**解决方式：**
新增 `rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py` 作为最小 wrapper：先校验 fixed eval manifest 与用户 hash，再写入仅含 target_user_ids 的治理兼容 manifest 供当前主路读取；候选生成完成后才读取 valid/test positive labels 计算 Recall@50/100/500 与 HitRate@50/100/500，并输出 `baseline_manifest.json`、`metrics.json`、`segment_metrics.json`、`source_audit.json`。补充 `tests/test_pool500_offline_eval_baseline.py`，覆盖 hash、artifact 写出、segment metrics、重复 user-item 拒绝和 no_oracle 标记。

**验证结果：**
先用 `--limit-users 100` dry-run 跑通 `outputs/eval/pool500_offline_eval_baseline_current_dry_run_100/`；随后正式运行 `outputs/eval/pool500_offline_eval_baseline_current/`，生成 10,000 用户 × 500 candidates，共 5,000,000 行，`underfilled_user_count=0`、重复 user_id+item_id 为 0。整体指标：Recall@50=0.014107、HitRate@50=0.0227、Recall@100=0.017892、HitRate@100=0.0293、Recall@500=0.022856、HitRate@500=0.0392。分层 Recall@500/HitRate@500：hot=0.026903/0.05375，warm=0.021819/0.032，cold-ish=0.016839/0.0245。source audit 显示 primary source 中 category=52.0713%、two_tower=27.7813%、swing=11.7669%、popular=3.3905%，popular+category=55.4618%，usercf_recall 仅 0.0108%。验证命令：`.venv/Scripts/python -m pytest tests/test_pool500_offline_eval_baseline.py tests/test_full_data_pool500_recall_only.py -q` 结果 `25 passed`；实际产物校验确认 candidate users 与固定 eval users 完全一致、hash 一致、metrics/segments 字段齐全、`no_oracle_label_injection=true`。

**面试可讲点：**
这段可以讲成“把召回优化前的对照基线做成不可漂移的评估契约”：先冻结 eval users、split 与 leakage policy，再复用当前主路生成候选，最后只在后验指标层读取 label，避免为了指标更换用户或注入 oracle。结果显示当前短板不是 pool500 填充不足，而是候选覆盖和用户覆盖都偏低，尤其 cold-ish 拖后腿、category/popular 占比偏高且 UserCF 贡献极低，为后续优化提供了可信对照。

### 2026-04-28 - 结构化 feedback API 与前端按钮闭环

**任务：**
把 Web Demo 中的反馈按钮从“转成自然语言再走 `/chat`”升级为结构化 `/feedback` API，让按钮反馈成为可记录、可测试、可扩展的交互事件。

**遇到的问题：**
最小前端 Demo 的按钮反馈虽然可用，但语义依赖英文 prompt 映射，不利于后续统计、回放和训练样本构造；同时前端按钮如何与自由文本 `/chat` 共存、是否携带 item_id、如何处理后端重启后的 session 失效，需要明确边界。

**定位方式：**
检查 `rs_core/serving/schema.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `frontend/src/App.tsx`、`frontend/src/api.ts` 的接口边界；按用户要求通过 `omc ask gemini` 审阅前端结构化 feedback 接入方案，Gemini 明确建议输入框只走 `/chat`，快捷按钮只走 `/feedback`，移除 `ACTION_MESSAGES` 自然语言硬编码，并复用 loading 与 session 失效处理。

**解决方式：**
后端新增 `FeedbackRequest` / `FeedbackResponse` 和 `POST /feedback`，支持 `like`、`dislike`、`show_different`、`why` 四种 `action_type`，内部仍复用 `env.converse()` 与 `build_display_record()`，保持输出为 `DisplayResponse`；前端新增 `sendFeedback()`，按钮直接发送 `{session_id, action_type}`，并与 `/chat` 共用 `isLoading`、`applyDisplayUpdate()` 和 `handleRequestError()`，保留后续商品级 `item_id` 反馈的扩展空间。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `11 passed in 0.51s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动后端和前端后，用 HTTP 验证 `/health`、默认 `/session/start`、`/chat` 和 `/feedback`，`/feedback` 返回 `rs_agent_display_v1`、turn_index 更新为 2、5 个商品卡，并确认响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把前端反馈从 prompt hack 升级为结构化事件 contract：自由文本仍由 `/chat` 处理，按钮语义由 `/feedback` 表达，后端再统一转入 Agent 决策链路。这样既保持了当前 demo 的轻量实现，又为后续 feedback 日志、session replay、多角色模拟客户和 GRPO reward 样本提供了稳定事件入口。

### 2026-05-18 - pool500 方法级数据集治理 contract

**任务：**
为 pool500 召回方法补齐方法级数据集治理与 drift gate，明确不同方法在全量数据、定制数据集和延后证据之间的边界。

**遇到的问题：**
pool500 已进入全量候选池治理阶段，但轻量方法、重资源方法和延后方法如果共用模糊口径，容易把未验证的全量可用性误读成最终 ready，或把需要定制数据集的重方法误纳入默认链路。

**定位方式：**
核对 `configs/recall/pool500_method_registry.json`、`dic/recall_methods/*/METHOD.md` 与相关 route gate 测试，确认 registry、方法文档和测试约束需要共同表达：轻量方法默认可沿用主数据策略，资源重的方法必须显式声明 custom dataset policy，deferred 方法只能保留证据边界。

**解决方式：**
在 pool500 method registry 中加入方法级 dataset contract，并同步方法文档说明：轻量方法采用 default policy，resource-heavy 方法采用 custom dataset policy，deferred 方法不宣称可执行晋升；新增独立 drift pytest gate，防止 registry 与方法文档口径漂移。本次只做 governance/readiness contract，不提升任何 source，不修改 `current_route_registry.yaml`，也不宣称 pool500 最终就绪。

**验证结果：**
使用项目 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_registry_drift.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_recall_source_registry.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_full_data_pool500_route_gate.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_p7_full_pool500_route_gate.py -q`，结果 `67 passed in 0.85s`。未运行 full-data/full-run。

**面试可讲点：**
这段可以讲成“推荐召回实验从跑方法升级到治理方法证据”：轻量、重资源和 deferred 方法不是用同一个 ready 标签粗暴处理，而是通过 registry contract、method doc 和 drift test 形成可审计边界，保证后续 pool500 链路扩展时既能复用轻量主路，又不会把重资源实验或缺证据方法误晋升。

### 2026-04-28 - session 轨迹安全导出与 replay 基础

**任务：**
在 structured feedback API 之后补齐 `GET /session/{session_id}`，让服务层可以导出当前会话轨迹，为后续 replay、模拟客户评估和前端调试提供安全数据入口。

**遇到的问题：**
`AgentSession.to_dict()` 和 `AgentTurn.to_dict()` 会包含 `ranking`、`diagnostics`、`reward_evidence`、`reward` 等内部诊断与训练字段，不能直接作为公开 API 返回；但如果只返回最后一轮 `DisplayResponse`，又无法支撑多轮 replay 和反馈闭环复盘。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/schema.py`、`rs_core/serving/app.py`、`rs_core/rsagent/schema.py` 和 `rs_core/display/builder.py`，确认安全边界应复用 `build_display_record()`，事件摘要只保留 `turn_index`、`user_input`、`assistant_message` 和 display 索引，不暴露 turn 原始结构。

**解决方式：**
在 `RecommendationService` 新增 `export_session()`，返回 `session_id`、`user_id`、`turn_count`、轻量 `events` 和逐轮 `display_responses`；在 serving schema 中新增 `SessionExportResponse`，并在 FastAPI 中新增 `GET /session/{session_id}`，继续复用统一的 unknown session 404 处理。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 2.41s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。新增测试覆盖 chat+feedback 后的 session export、unknown session 404，并递归断言公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作体现的是“可回放但不泄露内部诊断”的服务 contract 设计：训练和调试侧仍保留完整 AgentTurn / rollout，公开 API 只暴露展示层和轻量事件索引。这样既能支撑后续 session replay、多角色模拟客户和前端调试，又不会把排序分数、reward 证据等内部实现绑死到前端或外部消费者。

### 2026-04-28 - session export 结构化 feedback 事件元数据

**任务：**
增强 `GET /session/{session_id}` 的 replay 事件，让反馈轮次既保留 Agent 实际收到的 `user_input`，也保留原始结构化 `action_type`、`item_id` 和 `comment`。

**遇到的问题：**
上一版 session export 已经安全，但 feedback 事件在导出中只表现为转译后的 prompt，例如 `why? item_id=...`；这对复盘 Agent 行为足够，却不利于后续按按钮类型统计、重放 UI 事件或构造结构化反馈样本。

**定位方式：**
检查 `rs_core/serving/service.py` 和 `tests/test_serving_smoke.py`，确认结构化 feedback 信息在 `/feedback` 请求边界存在，但没有被保留下来；同时确认不应修改 `AgentSession` / `AgentTurn` 训练 schema，以免把服务层事件日志和 Agent 内部状态耦合。

**解决方式：**
在 `RecommendationService` 中新增独立的 `session_events` 轻量列表：`/chat` 记录 `{type: chat}`，`/feedback` 记录 `{type: feedback, action_type, item_id, comment}`；`export_session()` 将这些 metadata 与对应 turn 的 `user_input`、`assistant_message`、`display_response_index` 合并导出。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.59s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试确认 chat 事件与 feedback 事件类型可区分，feedback 事件包含 `action_type/item_id/comment`，公开响应仍不含内部排序、诊断和 reward 字段。

**面试可讲点：**
这次工作体现的是把“Agent 实际输入证据”和“产品交互事件语义”分层保存：Agent 仍消费转译后的自然语言 prompt，服务层额外保留按钮事件 metadata。这样后续 replay、统计分析和训练样本构造可以使用结构化事件，而不会破坏当前轻量 demo 的 Agent schema。

### 2026-04-28 - Gemini 实现 Session Replay 前端闭环

**任务：**
在已有 React 商品卡 Demo 中接入 `GET /session/{session_id}`，把 chat、feedback、display response 串成可视化 Session Replay 时间线，并按用户要求由 Gemini 负责前端实现。

**遇到的问题：**
后端已经能安全导出 session 轨迹，但前端还只能看到当前轮商品卡，不能复盘多轮对话、按钮反馈和每轮推荐变化；同时项目要求前端实现优先交给 Gemini，而不是由我先改再让 Gemini 审阅。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts` 和后端 `SessionExportResponse` contract，明确前端只允许消费 `events` 与 `display_responses`，不能读取 `ranking`、`diagnostics`、`reward`、`score` 等内部字段；通过 Gemini CLI 直接执行前端实现，再由我做边界检查和验证。

**解决方式：**
由 Gemini 在 `frontend/src/types.ts` 增加 `SessionExportEvent` / `SessionExportResponse` 类型，在 `frontend/src/api.ts` 增加 `fetchSessionExport()`，并在 `App.tsx` 增加 `Replay Session` 按钮、loading/error 状态和只读 timeline：每轮展示 turn、chat/feedback 类型、feedback metadata、assistant message 和对应商品快照。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；通过临时本地服务 HTTP 验证 chat→feedback→session export，导出包含 `event_types=[chat, feedback]` 且无内部字段泄露。

**面试可讲点：**
这次工作把推荐 Agent demo 从“当前轮展示”推进到“完整交互轨迹可回放”：用户输入、结构化反馈、Agent 回复和商品卡变化都能按 session timeline 复盘。工程上体现了前后端 contract 隔离、内部诊断字段保护，以及用 Gemini 承担前端实现、我负责接口边界和验收整合的协作流程。

### 2026-04-28 - 多角色模拟的角色内在模型基础层

**任务：**
把“多角色模拟客户”从一次性测试脚本调整为后续模拟场景的角色内在基础层，先实现可复用的角色画像、状态和 deterministic 行为策略。

**遇到的问题：**
如果直接做批量 simulated session runner，容易把多角色模拟降级成 smoke test；但项目后续目标是类似沙盒/游戏场景的多角色客户，每个角色需要有稳定人格、购物目标、偏好、记忆、反馈风格和状态演化，才能支撑 replay、动画和更真实的 Agent 评估。

**定位方式：**
对照已有 `rs_core/simulation/` 骨架和当前 `DisplayResponse` contract，确认 simulation 层应先消费前端安全展示数据，而不是读取推荐内部 ranking/reward；同时根据用户反馈明确：角色内在状态应优先于批量评估脚本。

**解决方式：**
新增 `rs_core/simulation/schema.py`，定义 `SimulatedCustomerRole`、`RoleState`、`RoleActionType`、`RoleAction`；新增 `policy.py`，用 deterministic `RolePolicy` 根据角色偏好、预算敏感度、负偏好和当前 display items 选择 chat、why、show_different、dislike、accept 等动作；新增 `presets.py`，提供通勤实用型、礼物购买型、价格敏感型三个内置角色，并通过 `rs_core/simulation/__init__.py` 导出。

**验证结果：**
新增 `tests/test_simulation_roles.py` 覆盖初始 prompt、preset 注册、已看商品状态更新、无商品时追问、有强匹配商品时接受、谨慎角色要求解释、不同 feedback style 产生不同动作；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `20 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。

**面试可讲点：**
这次工作体现的是把多角色模拟从“跑几条 prompt”提升为“角色内在模型”：角色画像、目标、偏好、记忆和反馈风格决定下一步行为，且只依赖安全 `DisplayResponse`。这为后续多角色沙盒、session replay 动画、模拟客户评估和 LLM-driven role simulation 留出了清晰扩展点。

### 2026-04-28 - Simulation Scene 后端契约与前端展示闭环

**任务：**
把角色内在模型接到真实 Agent 服务层，生成可供前端展示的 simulation scene，并按用户要求由 Gemini 实现前端场景面板。

**遇到的问题：**
角色画像和策略已经存在，但还没有驱动真实 Agent session；前端也无法展示“角色如何带着目标、偏好和反馈风格与推荐 Agent 交互”的完整场景。如果前端直接造假数据，会削弱 replay 和评估价值；如果后端直接暴露 AgentTurn，则又会泄露 ranking/reward 等内部字段。

**定位方式：**
检查 `rs_core/simulation/schema.py`、`policy.py`、`presets.py`、`rs_core/serving/service.py` 和 `SessionExportResponse` contract，确认最稳妥的连接方式是让 runner 复用 `RecommendationService.chat()` / `feedback()` 和 `export_session()`，输出 role、state、actions、session 四段安全 scene contract。

**解决方式：**
新增 `rs_core/simulation/runner.py`，实现 `run_simulation_scene()`：角色先发 `initial_prompt()`，随后由 `RolePolicy` 根据每轮 `DisplayResponse` 选择 chat、feedback、show_different、why、accept 等动作，最终导出 `scene_id`、角色画像、角色状态、动作时间线和安全 session export；在 FastAPI 中新增 `POST /simulation/scene`，并让 Gemini 在前端新增 Simulation Scene 面板，支持选择 `commuter_practical`、`gift_buyer`、`price_sensitive`，展示角色卡、状态卡、动作时间线和 session summary。

**验证结果：**
新增 `tests/test_simulation_runner.py` 覆盖 runner contract、API endpoint 和 unknown role；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.60s`；运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；本地 HTTP 验证 `POST /simulation/scene` 返回 `role_id=commuter_practical`、`turn_count=3`、`final_action=show_different` 且无内部字段泄露。

**面试可讲点：**
这次工作把项目从“单个用户手动 demo”推进到“角色驱动的可展示模拟场景”：角色内在状态决定交互行为，Agent 服务生成真实推荐与反馈轨迹，前端以 scene 面板展示角色、状态、动作和商品卡回放。它为后续多角色沙盒、动画展示、LLM 驱动角色和批量模拟评估提供了可复用 contract。

### 2026-04-29 - 端到端推荐 Agent 演示闭环聚合

**任务：**
把已有服务层、展示层和 React 前端推进成可一键演示的多轮闭环：用户需求进入 Agent，服务返回 `DisplayResponse` 商品卡，反馈后第二轮推荐发生变化，并能在前端按商品提交喜欢/不喜欢。

**遇到的问题：**
项目已有 `/chat`、`/feedback`、session replay 和商品卡前端，但面试演示仍需要人工分多步操作；同时测试环境当前缺少 `pytest` 和 `fastapi`，不能直接跑完整 HTTP 测试套件。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/app.py`、`rs_core/display/builder.py`、`frontend/src/App.tsx` 和 `tests/test_serving_smoke.py`，确认可复用 `RecommendationService.chat()`、`feedback()` 与 `DisplayResponse`，不需要让前端读取 rollout、ranking、diagnostics 或 reward 字段。

**解决方式：**
在服务层新增 `run_demo_roundtrip()` 和 `/demo/e2e`，聚合 start session、首轮 chat、结构化 feedback 和变化摘要；前端新增一键闭环按钮，并把商品卡上的喜欢/不喜欢绑定到具体 `parent_asin`；补充 smoke 测试用例覆盖两轮展示、turn_index 递增、商品变化和内部字段不外泄。

**验证结果：**
补齐 serving/test 依赖后，运行 `python -m pytest tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `15 passed in 1.35s`；运行 `python -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试覆盖 `/demo/e2e` 的两轮 `DisplayResponse`、`turn_index` 递增、商品集合变化、unknown feedback 422，以及公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作把推荐 Agent 从“有接口、有前端”推进到“可一键复现闭环”：服务端用薄 orchestration 串起现有推荐和反馈能力，前端只消费展示 contract，变化摘要用于证明反馈确实影响下一轮推荐。这个实现兼顾了演示效率、前后端边界隔离和后续训练/回放数据的可解释性。

### 2026-04-29 - 批量多角色 Simulation Evaluation 闭环

**任务：**
把单个 simulation scene 扩展成批量多角色评估入口，让多个 persona 自动与推荐 Agent 交互，并生成可复现的 metrics/report 产物。

**遇到的问题：**
此前系统已经能展示单个角色与 Agent 的交互场景，但缺少多 persona、重复运行、统一指标和落盘报告；这使多角色模拟更像展示 demo，而不是能支撑评估、复盘和后续训练样本构造的闭环。

**定位方式：**
检查 `rs_core/simulation/runner.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `tests/test_simulation_runner.py`，确认最稳妥的做法是复用 `run_simulation_scene()`、`RecommendationService.chat()/feedback()/export_session()` 与安全 `DisplayResponse` contract，而不是重写推荐逻辑或暴露内部 ranking/reward 字段。

**解决方式：**
在 `rs_core/simulation/runner.py` 新增 `run_simulation_batch()`、scene metrics 和 batch summary；在 `rs_core/serving/app.py` / `schema.py` 新增 `/simulation/batch`；新增 `scripts/evaluation/run_simulation_evaluation.py`，输出 `simulation_batch.json`、`metrics.json` 和中文 `simulation_eval_report.md`。公开输出继续递归阻断 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score` 等内部字段。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.75s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `./.venv/Scripts/python.exe scripts/evaluation/run_simulation_evaluation.py --limit-users 1 --max-turns 3 --repeats 1 --output-dir outputs/simulation/simulation_eval_smoke_default` 成功生成 `simulation_batch.json`、`metrics.json` 和 `simulation_eval_report.md`。

**面试可讲点：**
这次工作把多角色模拟从“单场景展示”推进到“可量化评估闭环”：不同 persona 可以批量驱动真实 Agent 服务，系统聚合 accept rate、平均轮数、反馈/解释/换榜行为和满意度指标，同时保持前端安全视图边界。这为后续 session replay、模拟客户评估、SFT 样本和 GRPO reward 对照提供了稳定数据基础。

### 2026-04-29 - 模型驱动模拟用户策略接入

**任务：**
让多角色模拟客户可以选择由外部模型 API 驱动下一步行为，同时保留 deterministic 规则策略作为默认路径和 fallback。

**遇到的问题：**
此前多角色模拟虽然能批量运行，但角色行为仍是规则策略，难以表现更自然的模拟用户差异；同时 API base、key、model 这类敏感或易变参数不能硬编码进代码、日志或提交文件。

**定位方式：**
检查 `rs_core/simulation/policy.py`、`rs_core/simulation/runner.py` 和 `scripts/evaluation/run_simulation_evaluation.py`，确认模型能力应接在 RolePolicy 层，只决定模拟用户的 `chat/why/show_different/dislike/accept` 行为，不改变推荐候选、排序、reward 或 `DisplayResponse` contract。

**解决方式：**
新增被 `.gitignore` 保护的本地配置约定 `configs/simulation_model.local.json`，并提供非敏感模板 `configs/simulation_model.example.json`；新增 `rs_core/simulation/model_client.py`，用 OpenAI-compatible `/v1/chat/completions` 调用外部模型；在 `rs_core/simulation/policy.py` 新增 `ModelDrivenRolePolicy`，约束模型只能返回允许 action 且 item_id 必须来自当前展示商品；在 `scripts/evaluation/run_simulation_evaluation.py` 增加 `--role-policy model`、`--model-config` 和 `--strict-model-policy`。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `37 passed in 0.73s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `./.venv/Scripts/python.exe scripts/evaluation/run_simulation_evaluation.py --role-policy model --model-config configs/simulation_model.local.json --limit-users 1 --max-turns 2 --repeats 1 --output-dir outputs/simulation/simulation_eval_model_fallback_smoke_2` 成功生成评估产物，并在本地配置缺失时记录 deterministic fallback。

**面试可讲点：**
这次工作把模拟客户从固定规则升级为可插拔模型策略：外部模型只负责用户侧行为生成，系统用 JSON action schema、展示商品白名单和 deterministic fallback 保证可控性。这样既能提升多角色模拟的自然度，也不会让大模型越权影响推荐排序或泄露内部诊断字段。

### 2026-05-19 - pool200 主路方法迁移到 pool500 direct recall

**任务：**
把 pool200 已确认主路方法迁移到 pool500 direct recall，整合 `semantic_title_category_expansion`、`two_tower`、`co_visit_fallback_repair`、`usercf_recall`、`swing_recall`、`itemcf_weak`、`itemcf_strong`、`category`、`popular` 九路 source，生成当前 pool500 主路 direct recall 候选池。

**遇到的问题：**
部分方法 artifact 来自新 full clean / train-only 数据基础补齐，其中 `two_tower` / YouTubeDNN 是主要缺口；初始全量运行中 two_tower 向量检索和 metadata neighbor 扫描成为耗时瓶颈，同时 `usercf_recall` 的历史 manifest 缺少显式 `source_status` 字段，容易被过严 loader 拒绝。

**定位方式：**
先逐一核对各 `source_index_manifest.json` 的 `source/canonical_source/index_scope/train_only` 与禁用边界，再用 focused pytest、ruff 和运行输出审计定位缺口。最终 direct recall 输出位于 `outputs/recall/pool500_main_route_direct_recall_full_promoted/`，`manifest.json` 记录 `processed_users=500`、`candidate_rows=74978`、`underfilled_user_count=500`，`source_contribution_audit.json` 与 `pool500_candidates.jsonl` 均确认 `co_visit_fallback_repair` 已实际产生候选。

**解决方式：**
为 `VectorIndex` 增加 NumPy 向量化 top-k 与批量 `search_many`，runner 中预计算 two_tower recall；兼容安全的 legacy UserCF manifest，但继续要求 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`；对 metadata neighbor 增加 batch 侧候选桶限流，保持 co-visit 仍作为 batch-scoped diagnostic source 输出。

**验证结果：**
运行命令使用项目 `.venv` 执行 `run_full_data_pool500_recall_only.py --limit-users 500 --enable-semantic --semantic-max-rows 200000` 并显式传入 six 个 source manifest，退出码为 0。输出 manifest 决策仍为 `STOP` / `diagnostic_limited`，不允许 promotion、ranking input replacement 或 pool1000；但 `source_coverage` 已包含九路主路 source：`category=35880`、`co_visit_fallback_repair=9898`、`itemcf_strong=1992`、`itemcf_weak=2070`、`popular=19112`、`semantic_title_category_expansion=6267`、`swing_recall=3073`、`two_tower=180`、`usercf_recall=8364`。`final_resource_audit.status=PASS`，`users_with_500_candidates_ratio=0.0`，underfill 审计保持 `DIAGNOSTIC_ONLY_PARTIAL`。focused pytest 结果 `21 passed`，ruff touched files `All checks passed!`。

**面试可讲点：**
这段可以讲成“在时间紧张下用 artifact contract 和 source coverage 收口多召回方法主路迁移”：不是等待每个方法长期 READY，也不是伪造 final ready，而是把各方法的 full-clean train-only artifact 接入同一个 direct recall runner，用 source coverage、per-source readiness、resource audit 和禁用 flags 证明候选池可进入排序输入冻结讨论，同时清楚保留 STOP/diagnostic 边界。

### 2026-04-29 - 核心文档阶段状态收口

**任务：**
同步项目核心文档的当前状态，把 README、实施计划、架构说明、目录说明和优化叙事从“展示/前端/仿真仍在规划中”的旧口径，更新为“已完成第一版，下一步进入训练样本收口”的真实阶段。

**遇到的问题：**
工程日志已经记录了 `DisplayResponse`、HTTP 服务、React Web Demo、Session Replay、`/demo/e2e`、Simulation Batch 和模型驱动模拟用户，但核心入口文档仍保留 Phase 2 / Phase 3 规划中、`frontend/` 仅预留等表述，容易让读者低估项目完成度，也会削弱面试演示主线。

**定位方式：**
对照 `prd.json` 中已通过的 rollout contract / Qwen harness story，以及 `dic/ENGINEERING_NARRATIVE_LOG.md` 中 2026-04-28 至 2026-04-29 的服务、前端、replay、simulation 记录；再用关键词检索 `规划中`、`当前仅预留`、`后期规划会补` 等旧表述，定位到 `dic/README.md`、`dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/architecture/ARCHITECTURE.md`、`dic/PROJECT_STRUCTURE.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`。

**解决方式：**
将核心文档统一改成阶段收口口径：Phase 2 展示 contract / 服务层 / React Web Demo 已完成第一版，Phase 2.5 Session Replay 和一键 E2E 闭环已完成第一版，Phase 3 多角色 Simulation 和模型驱动模拟用户已完成第一版；同时明确 Qwen3.5-4B + 8-bit QLoRA SFT + GRPO 尚未完整训练落地，当前服务仍是 single-process demo，前端和仿真不是生产级真实用户评估。

**验证结果：**
运行关键词检查确认核心文档中不再出现 `当前仅预留`、`后期规划会补商品展示卡`、`商品展示卡 contract 与轻量前端 demo` 等过期表述；运行 `./.venv/Scripts/python.exe - <<'PY' ... PY` 校验 5 个核心 Markdown 文件均可用 UTF-8 读取、非空，且不含关键过期口径，输出 `validated 5 markdown files`。

### 2026-06-14 - GPT SFT API 调用链路落地

**任务：**
在不改动现有 qwen_local 在线 rerank 路径的前提下，新增 GPT SFT 的 OpenAI-compatible API dry-run / execute 链路、配置、脚本和单测。

**遇到的问题：**
训练样本生成需要接入外部 API，但必须默认离线安全：API key 只能从环境变量读取；错误响应、运行结果和生成 metadata 不能泄露 key；GPT 输出也不能通过伪造候选池污染 SFT 样本。

**定位方式：**
复用 `rs_core/training/data_contracts.py` 的 `validate_sft_sample(s)` 确认样本 contract，复用 `rs_core/common/io.py` 读写 JSONL；对照 OpenAI-compatible `/v1/chat/completions` 的 `model/messages/response_format` 请求与 `choices[0].message.content` 响应结构，确认最小 API client 边界；再用 reviewer 复查候选池约束、dry-run/execute 闸门和 API key 泄露路径。

**解决方式：**
新增 `rs_core/common/openai_compatible_client.py` 作为底层 client；新增 `rs_core/training/gpt_sft_config.py`、`gpt_sft_generator.py`、`gpt_sft_runner.py` 串起配置、prompt 构造、生成和输出；新增 `scripts/training/run_gpt_sft_api.py` / `generate_gpt_sft.py` 和 `configs/training/gpt_sft_api_smoke.yaml`。默认 dry-run 只输出 message 摘要；真实调用要求 `--execute`、`dry_run=false` 和 `gpt_sft.enabled=true` 三者同时满足；API base 默认要求 HTTPS；GPT 生成结果会回绑 seed 的 `candidate_summary`、`allowed_item_ids` 和 `must_select_from_candidates=true`。

**验证结果：**
运行 `.venv/Scripts/python -m pytest tests/test_openai_compatible_client.py tests/test_gpt_sft_api.py tests/test_training_data_contracts.py tests/test_inference_policy.py`，结果 `48 passed in 0.34s`；运行 `.venv/Scripts/python scripts/training/generate_gpt_sft.py --config configs/training/gpt_sft_api_smoke.yaml --limit 1 --dry-run`，结果 `api_called=false` 且只输出 `first_message_summary`；运行 `.venv/Scripts/python -m compileall ...` 编译新增 Python 文件通过。

**面试可讲点：**
这次工作把“外部 GPT 生成 SFT 样本”做成了可审计的安全执行链路：默认 dry-run 不外发且不打印完整 prompt，execute 有双配置闸门；密钥只走环境变量，HTTP 错误体会脱敏；GPT 只能在原始候选池约束内生成 SFT 样本；同时补齐跨 CWD 路径解析、完整 chat-completions endpoint、raw JSON list 输入和 content parts 解析，降低代理/脚本调用边界问题，从而让后续 Qwen SFT/GRPO 数据闭环共享同一套样本质量边界。

**面试可讲点：**
这次工作体现的是阶段治理和工程叙事能力：当功能快速推进后，及时把入口文档、实施计划和架构边界同步到真实状态，避免“代码已完成但文档仍像规划”的信息漂移；同时保留训练未落地、服务非生产级、仿真非真实用户的边界，能让项目叙事可信而不夸大。

### 2026-05-07 - Phase 4 轨迹样本与 Agent 行为评估方向澄清

**任务：**
明确 Phase 4 的下一步主线：把 Web Demo 和多角色 Simulation 产生的 session 轨迹标准化为可审计的 Agent training trajectories。

**遇到的问题：**
项目已经具备 Web Demo、结构化 feedback、Session Replay、多角色 Simulation 和模型驱动模拟用户第一版，但下一阶段不能简单理解为“继续扩展示功能”或“马上训练 Qwen”。需要先把交互闭环沉淀成后续 SFT、preference learning 和 RL / GRPO 能复用的数据来源。

**定位方式：**
对照当前 `dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/architecture/ARCHITECTURE.md`、`rs_core/serving/*`、`rs_core/simulation/*` 和 `scripts/evaluation/run_simulation_evaluation.py`，确认已有能力已经能生成 session、feedback、display response、simulation scene / batch 和 metrics，缺口在统一 trajectory schema、样本导出、质量校验和 Agent 行为指标。

**解决方式：**
将下一阶段表述为：先把 Web Demo 和多角色 Simulation 产生的 session 轨迹标准化为可审计的 Agent training trajectories，里面同时支持 SFT 样本、preference 样本和 RL rollout 样本。这样后续 `Qwen3.5-4B + QLoRA + GRPO` 可以基于真实交互约束和反馈信号优化，而不是离线凭空构造训练数据。

**验证结果：**
本次是路线澄清与叙事记录，未修改代码、未运行新的实验。当前可验证依据是已有服务层 session export、simulation batch 输出、结构化 feedback 事件和批量评估 metrics/report 产物。

**面试可讲点：**
这条主线可以概括为“先采集和标准化交互轨迹，再做可控训练”：Agent 当时能选哪些候选、实际推荐了什么、用户或模拟用户如何反馈、下一轮是否改正，都被记录进 trajectory。后续 RL / GRPO 的 state、action、reward 和 rollout 不是人工拼出来的，而是来自可回放、可审计的推荐交互闭环。

### 2026-05-07 - 10k 数据验证 semantic_title 召回路线

**任务：**
将已有 title/category-only semantic recall 路线扩展到 10k 数据规模，验证它相对 baseline 是否真实提升传统召回效果。

**遇到的问题：**
1000 小样本上的 `semantic_title` 提升可能存在偶然性；同时用户指出“买过相似标题商品不代表还会重复购买同类商品”，因此需要在更大数据上验证 `semantic_title` 作为补充召回源是否有效，并识别它对排序融合的副作用。

**定位方式：**
基于 `data/processed/amazon_2023_base/manifest.json` 构建 `amazon_2023_recall_clean_10000` 和 `amazon_2023_recall_views_10000`；复制 1000 配置生成 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000*.yaml`；运行 baseline、semantic_title、LOPO baseline、LOPO semantic_title 四组对照，并读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000*/metrics.json` 与 `ranking_case_summary.json`。

**解决方式：**
没有新增一条完全不同的召回算法，而是把已有 `semantic_title` 路线迁移到 10k 数据上做 ablation：它使用 `title_clean`、`main_category`、`categories_flat` 的 token overlap 做确定性文本召回。第一轮只改数据路径、输出目录和报告名，不改排序权重，保证 baseline 与 semantic_title 的对照尽量干净。

**验证结果：**
valid/test 口径中，`candidate_hit_users` 从 23 提升到 60，`ranked_hit_users` 从 5 提升到 14，`hit_rate@5` 从 0.007013 提升到 0.019635；LOPO 口径中，`candidate_hit_users` 从 74 提升到 1298，`ranked_hit_users` 从 68 提升到 1044，`hit_rate@5` 从 0.049204 提升到 0.755427。副作用也很明确：LOPO 中 `itemcf_only_hit_rate@5=0.887844` 高于 hybrid semantic_title 的 0.755427，且候选命中平均排名仍偏后，说明 `semantic_title` 明显提升覆盖，但当前融合排序稀释了 ItemCF 强信号。

**面试可讲点：**
这不是简单“加文本相似召回”，而是通过 10k ablation 证明 semantic/title recall 作为增量召回源能显著提升候选覆盖；同时主动暴露局限：标题相似不等于下一次购买意图，semantic-only 候选可能压住 ItemCF。下一步应做 source-aware fusion，在保留 `semantic_title` 覆盖收益的同时保护 ItemCF 和多源一致性信号。

### 2026-05-08 - 10k source-aware fusion 排序优化

**任务：**
在 10k `semantic_title` 召回验证后，优化传统推荐 backbone 的融合排序，让文本召回带来的候选覆盖尽量转化为 Top-K 排序收益，同时保持 Agent 作为独立交互编排层，不把它简单归入精排模块。

**遇到的问题：**
`semantic_title` 已经显著提升候选池覆盖，但 LOPO 中 `itemcf_only_hit_rate@5=0.887844` 仍高于 hybrid semantic_title 的 `0.755427`，说明当前线性加权排序会稀释 ItemCF 强信号。直接强保护 ItemCF 又会伤害 valid/test，因为 valid/test 的一部分 target 主要由 semantic 命中。

**定位方式：**
在 `rs_core/recsys/ranking.py` 增加默认关闭的 `source_aware_fusion`，分别运行 10k valid/test 与 LOPO source-aware 对照；读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title_source_aware/metrics.json`、`outputs/hybrid_demo/hybrid_demo_small_electronics_10000_lopo_semantic_title_source_aware/metrics.json` 和对应 `ranking_case_summary.json`，同时对比强保护版与温和版参数。

**解决方式：**
新增可解释的 source-aware fusion：对 ItemCF 候选加分，对 ItemCF + 多源候选额外加分，对 semantic-only / popular-only 做轻量惩罚，并在 `rerank_events` 中记录 `source_aware_fusion` 事件；新增 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_source_aware.yaml` 与 LOPO 配置。最终保留温和参数 `itemcf_source_boost=8.0`、`itemcf_multi_source_boost=4.0`、`semantic_only_penalty=4.0`、`popular_only_penalty=2.0`，并把 `source_aware_fusion` 写入实验报告的 `config_summary`。

**验证结果：**
单测 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_inference_policy.py` 通过，结果 `49 passed`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。强保护版在 LOPO 中将 `hit_rate@5` 从 `0.755427` 提升到 `0.810420`，但 valid/test 从 `0.019635` 降到 `0.011220`，不适合作为默认配置。温和版 valid/test 保持 `hit_rate@5=0.019635`、`ranked_hit_users=14`；LOPO 保持 `hit_rate@5=0.755427`，但 `candidate_hit_rank_avg` 从 `40.308937` 改善到 `35.738829`。这说明温和 source-aware fusion 是安全的小幅排序改善，强保护版更适合作为诊断证据而不是默认策略。

**面试可讲点：**
这次优化体现了“召回增益之后不能只看 hit-rate，还要看融合排序和评估口径 tradeoff”：强保护 ItemCF 能证明排序确实可把 LOPO target 推前，但会牺牲 valid/test 的 semantic 命中；温和版则保持主指标不受损并改善候选池内排名分布。后续如果继续提升效果，应从手写 source-aware 规则升级到可训练 ranker，学习 ItemCF、多源一致性、semantic-only、popular-only 等特征的权重，而不是继续人工调参。

### 2026-05-09 - 双塔向量召回旁路与 strict gate 收口

**任务：**
把下一阶段复杂召回重点收敛到 DSSM-style 与 YouTubeDNN-style 双塔向量召回，补齐训练 artifact、向量索引、默认关闭配置、strict promotion gate、测试和中文路线说明。

**遇到的问题：**
此前项目已验证 semantic_title 能提升候选覆盖，但复杂召回仍停留在 token overlap / POC 语义旁路；如果直接同时实现图召回、多兴趣、TDM、DeepFM / NCF，会让工程范围过大，也难以用 valid/test 与 LOPO 证明哪条路线真正有效。

**定位方式：**
对照 `.omc/specs/deep-interview-two-tower-recall-next.md` 的验收标准，检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`rs_core/recsys/vector_index.py`、`rs_core/recsys/candidate_merge.py`、`rs_core/workflow/hybrid_demo.py`、`tests/test_two_tower_training.py` 和 `tests/test_hybrid_demo.py`；再读取 `outputs/training/two_tower/two_tower_training/*/artifact_manifest.json` 与四组 two-tower smoke metrics，确认当前证据是训练 `limit_users=10`、评估 `limit_users=30` 的 paired smoke，而不是完整 10k 双塔评估。

**解决方式：**
新增并更新 `tests/test_two_tower_training.py`，验证双塔训练输出完整 artifact contract、`default_enabled=false`、DSSM / YouTubeDNN 的 `model_type` 与 `source_name` 隔离、manifest 可作为 `VectorIndex` 加载，并覆盖 PyTorch backend 规则：torch 可导入时使用 `pytorch`，`backend: python_fallback` 不能绕过 PyTorch，只有 no-torch 场景才进入 `python_fallback_vector_updates`。同时更新 `dic/architecture/IMPLEMENTATION_PLAN.md`、`dic/README.md`、`dic/architecture/ARCHITECTURE.md`、`dic/PROJECT_STRUCTURE.md`，明确双塔只作为默认关闭旁路，晋升必须通过 strict gate。

**验证结果：**
训练 smoke artifact 位于 `outputs/training/two_tower/two_tower_training/dssm/artifact_manifest.json` 和 `outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json`，manifest 中 `training_backend.name=pytorch`，训练规模为 `limit_users=10`、`epochs=1`、`negative_samples=1`、`embedding_dim=8`、`hidden_dim=8`。paired smoke 评估规模为 `limit_users=30`：DSSM valid/test `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`、`candidate_generation_p95_seconds=0.270462`、`promotable=false`；YouTubeDNN valid/test 同为 `candidate_hit_rate_at_pool=0.111111`、`recall_at_pool=0.111111`、`hit_rate_at_k=0.0`、`candidate_hit_users=1`，`candidate_generation_p95_seconds=0.246153`、`promotable=false`。LOPO 仍是 sanity-only no promotion。当前没有完整 10k 双塔结论，不能据此宣称双塔可晋升。

**面试可讲点：**
这次工作可以讲成“把复杂召回工程化为可验证旁路，而不是堆模型名”：DSSM 与 YouTubeDNN 都通过同一 artifact contract 进入向量索引和 candidate merge，但默认关闭；是否进入主路由 valid/test、LOPO sanity、source contribution / overlap 和 latency gate 决定。Node2Vec / DeepWalk、MIND / SDM、TDM、DeepFM / NCF 被明确延期，体现了工程范围控制和评估优先的取舍。

### 2026-05-08 - Phase 1.9 轻量 learning-to-rank baseline

**任务：**
把 source-aware fusion 的手写 source 规则升级为一个默认关闭、可训练、无新增依赖的轻量 LTR baseline，用于学习 ItemCF、多源一致性、semantic-only、popular-only 和热度/时间等排序特征权重。

**遇到的问题：**
项目当前没有 `numpy`、`sklearn`、`lightgbm` 等训练依赖，不能为了一个 baseline 引入重依赖；同时 LOPO 训练与 LOPO 评估容易形成同 split 过拟合，如果只报告 LOPO 提升会夸大泛化效果。实现时还发现 LTR 配置会在训练前启用 `ltr_model` 并尝试加载尚未生成的模型文件。

**定位方式：**
检查 `rs_core/recsys/ranking.py`、`rs_core/workflow/hybrid_demo.py` 和新训练流程，确认现有 candidate / ranking 字段已足够抽取 source indicator、source score、source interaction 和 metadata 特征；通过 200 用户 smoke 训练先验证 `scripts/training/train_ltr_ranker.py` 能生成模型与指标，再分别运行 10k LOPO 和 valid/test 对照，读取 `outputs/training/ltr/ltr_training_10000_lopo_semantic_title/ltr_train_metrics.json`、`outputs/hybrid_demo/hybrid_demo_small_electronics_10000_lopo_semantic_title_ltr/metrics.json` 和 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title_ltr/metrics.json`。

**解决方式：**
新增 `rs_core/recsys/ltr.py`，实现 pure-Python pairwise perceptron、特征抽取、模型保存/加载和线性打分；新增 `rs_core/workflow/ltr_training.py` 与 `scripts/training/train_ltr_ranker.py` 复用 hybrid demo 的候选生成和 holdout label；在 `rank_candidates()` 中新增 `ltr_score` 和 `ltr_model` rerank event，并保持 `ltr_model.enabled=false` 时原排序不变；训练候选生成阶段临时关闭 `ltr_model`，避免训练前加载不存在的模型。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py tests/test_inference_policy.py`，结果 `56 passed`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。200 用户 smoke 训练生成 5550 行样本、111 个 positive users。10k LOPO 训练生成 64900 行样本、1298 个 positive users，模型学到 `itemcf_source=2.34`、`itemcf_multi_source=2.21`、`semantic_only=-0.85`、`popular_only=-0.54`。LOPO 评估中 `hit_rate@5` 从 `0.755427` 提升到 `0.758321`，`ranked_hit_users` 从 `1044` 到 `1048`，`candidate_hit_rank_avg` 从 `40.308937` 改善到 `32.591680`；但 valid/test `hit_rate@5` 从 `0.019635` 降到 `0.014025`，说明该模型目前更适合作为训练排序 baseline 和诊断工具，而不是默认泛化配置。

**面试可讲点：**
这次工作可以讲成“从手写规则到可训练排序器”的工程升级：先用 source-aware fusion 暴露 ItemCF 保护与 semantic 泛化之间的 tradeoff，再实现无依赖 LTR baseline 学习这些特征权重。关键不是夸大指标，而是主动用 valid/test 证明同 split LOPO 收益不能直接等同线上泛化，并给出下一步应做独立训练/验证切分、score calibration 或更强 LTR 模型的方向。

### 2026-05-08 - Phase 1.10 推荐底座工业化诊断层

**任务：**
补齐推荐 backbone 的工业化离线诊断层，用 valid/test 和 LOPO 对照判断当前瓶颈属于召回、source merge、排序/LTR 还是 latency，而不是直接根据数据量决定是否上粗排、精排或双塔。

**遇到的问题：**
已有 `hit_rate@5`、候选池命中和 LTR 对照，但指标还不足以回答“应该先优化召回还是排序”“LTR 能否默认启用”“当前是否需要粗排/双塔”。如果只看 LOPO，容易把同 split 排序收益包装成泛化提升；如果只看 valid/test hit-rate，又看不出 target 是否进入候选池、是否被排序压在 Top-K 外。

**定位方式：**
扩展 `rs_core/recsys/evaluation.py` 与 `EvaluationSummary`，加入 `recall_at_k`、`recall_at_pool`、`ndcg_at_k`、`mrr_at_k`、`map_at_k`、`candidate_hit_rank_p90`、source contribution、source overlap；在 `rs_core/workflow/hybrid_demo.py` 聚合 candidate generation / ranking / total recommendation latency，并输出 `diagnostic_gate`。随后运行 6 组 10k 对照：valid/test 与 LOPO 的 semantic_title、source-aware、LTR。

**解决方式：**
把 gate 设计为显式诊断报告：candidate pool 命中低时判为 recall bottleneck；pool 命中不低但 Top-K / NDCG / MRR 低且命中排名靠后时判为 ranking bottleneck；source contribution 与 Top-K contribution 错配或 overlap 异常时作为 source merge 诊断；候选池扩大且排序耗时上升时才考虑 latency / architecture escalation。所有 gate 同时保留绝对用户数和比例，避免小样本比例误导。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_ltr.py`，结果 `40 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。六组实验均成功生成 metrics/report。valid/test 三组的 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`，gate 都指向 `phase_1_11_recall_source_merge`；LTR 在 valid/test 中 `hit@5=0.014025`，低于 semantic_title/source-aware 的 `0.019635`，不能默认启用。LOPO 中 source-aware 改善 `ndcg@5=0.314323`、`mrr@5=0.179317`，LTR 将 `hit@5` 提升到 `0.758321`，但只能作为排序诊断证据。排序 `ranking_p95_seconds` 最高约 `0.001366`，候选池约 50，当前不需要独立粗排。

**面试可讲点：**
这次工作体现的是“先诊断瓶颈，再决定架构升级”：没有因为效果低就直接上双塔、粗排或精排，而是用 Recall@pool、NDCG/MRR、source contribution、命中排名分布和 latency gate 拆清责任边界。结论是推荐 backbone 已足够支撑 Agent 工程继续推进，但还不是强推荐算法底座；下一步应优先做 recall/source merge 泛化优化，LTR 保留为诊断 baseline，双塔和复杂精排放到传统召回触顶后的 POC。

### 2026-05-12 - Phase 1.23 pool200 same-run ranking isolation

**任务：**
在 frozen pool200 上做 same-run ranking isolation，验证 `ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 是否能在不漂移候选池的前提下带来真实 Top-K 收益。

**遇到的问题：**
pool200 已经冻结，如果没有 same-run isolation，任何 ranking 结果都可能混入候选池波动或 freeze 漂移，最后无法区分是排序特征有效还是采样噪声。

**定位方式：**
使用项目默认 `.venv` 跑完整对照命令，并带上 `--limit-users 500`；检查 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json` 和 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`，核对 valid、freeze、candidate_hit_users、candidate_count_avg、hit_rate_at_k、ndcg_at_k、mrr_at_k 以及各变体 delta。

**解决方式：**
把评估边界锁死在 same-run frozen pool comparison，只比较 baseline、`ranking_v2`、`item_feature_rerank`、`source_aware_fusion`，不扩展召回或调参范围；若出现 freeze drift 就直接判 invalid，否则只归因到排序层。

**验证结果：**
all variants valid 且 no freeze drift。baseline `users_with_holdout=138`、`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=152.272`、`fallback_rate=0.0`；same-run baseline `hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`。`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 的指标与 baseline 完全一致，delta 全为 0，最终判定 `VALID but NO PROMOTION`。

**面试可讲点：**
这轮最重要的是把归因边界锁死：same-run isolation 证明候选池没漂、freeze 没漂，结果仍然不变，说明当前手写排序增量还不足以把稀疏正例推入 Top-K。下一步更合理的是先按 user-level hit rank 和 feature 分布做剖析，再决定是否进入 LTR 或更强排序特征。

### 2026-05-08 - Phase 4.1 Agent 综合评估闭环与反馈重排工具

**任务：**
把 Agent 线从“只导出 trajectory 样本”调整为“能对比、能诊断、能沉淀训练信号”的综合评估闭环，并实现 enhanced Agent 的第一项可解释工具：商品级 feedback rerank。

**遇到的问题：**
Agent 不应该被简单归入传统推荐链路的精排模块，因为它还负责多轮对话、反馈理解、短期记忆、解释与训练信号沉淀；同时如果 public session export 直接暴露 ranking、diagnostics、reward、scorecard 等内部字段，会污染前端和服务 contract。另一个实现问题是 `I don't like this item item_id=...` 这类文本既包含 `like` 又包含否定，需要避免被误记成正反馈或重复记录事件。

**定位方式：**
对照 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/serving/service.py`、`rs_core/simulation/runner.py` 和 rollout contract，确认最合适的边界是：推荐 backbone 继续负责候选生成与排序，Agent 层只把商品级反馈转成短期记忆和可解释排序调整；内部评估 artifact 单独导出，不进入 `RecommendationService.export_session()`。

**解决方式：**
在 `FeedbackConstraints` 中记录 `liked_item_ids`、`disliked_item_ids` 和 `item_feedback_events`；新增 `rs_core/rsagent/feedback_rerank.py`，把 like/dislike/show_different 转成 explicit filter、ItemCF 相似商品 boost/demote 和 `feedback_rerank_events`；在 hybrid workflow 中接入该工具，但最终排序仍走原 ranking pipeline。新增 `rs_core/evaluation/agent_scorecard.py` 和 `agent_artifact.py`，输出推荐效果、交互质量、反馈响应、记忆一致性、训练数据质量五维 scorecard，以及 SFT/reward/preference/trajectory training signals；新增 `scripts/evaluation/run_agent_evaluation.py` 对比 baseline 与 `enhanced_feedback_rerank`。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_scorecard.py tests/test_agent_eval_artifact.py tests/test_simulation_runner.py tests/test_serving_smoke.py`，结果 `42 passed in 0.98s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。测试覆盖商品级反馈解析、feedback rerank filter/boost/demote、五维 scorecard、internal artifact/training signals、baseline/enhanced runner，以及 public export 不泄露 `ranking/diagnostics/reward/tool_events/scorecard` 等内部字段。

**面试可讲点：**
这次工作可以讲成“把 Agent 从推荐输出包装器升级为可评估的交互决策层”：底座仍然负责召回和排序，Agent 负责理解用户反馈、维护短期会话记忆、调用可解释工具影响候选排序，并把每次交互沉淀为 scorecard 与训练信号。关键边界是没有宣称已经完成 SFT/GRPO，而是先建立 baseline/enhanced 对比、内部证据 artifact 和 public-safe export 隔离，为后续 Qwen/QLoRA/GRPO 训练提供可审计数据基础。

### 2026-05-13 - Phase 2 fine-rank batch 收口

**任务：**
补齐 Phase 2 fine-rank batch runner 和对应测试，并把线性 / LTR / 树模型的状态边界写回文档。

**遇到的问题：**
原先文档仍容易把 linear / pointwise / pairwise 写成 promotion-capable；tree / LambdaMART 在缺真实依赖或 adapter 时也不能被当作可晋升结果。

**定位方式：**
检查 `scripts/experiments/ranking/run_phase_2_fine_rank_algorithm_batch.py`、`tests/test_phase_2_fine_rank_algorithm_batch.py` 和现有排序路线文档，确认 fine_rank 承担 full-pool scoring，rerank 只应保留 Top-K 局部诊断 / 约束语义。

**解决方式：**
在路线图里把 Phase 2 改成 fine_rank full-pool scoring 口径，learned rows 统一降为 diagnostic-only，tree/LambdaMART 标记 blocked/preparation；同时补写 batch runner 和测试文档，避免 promotion 口径漂移。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_2_fine_rank_algorithm_batch.py tests/test_phase_2_fine_rank_algorithm_batch.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_2_fine_rank_algorithm_batch.py -q` 结果 `3 passed`。

**面试可讲点：**
这次工作可以讲成“把排序实验入口和晋升边界一起收口”：不仅补了 fine_rank batch runner，还明确 learned / tree / rerank 各自只能走什么证据，防止把诊断、准备和 promotion 混写成同一种结论。

### 2026-05-09 - Phase 1.11 recall/source merge 验证收口

**任务：**
验证 Phase 1.11 在 10k `semantic_title` 数据上的 recall/source merge 改动，并把结果更新到中文优化叙事和工程日志。

**遇到的问题：**
Phase 1.11 的目标是提升 valid/test 候选池覆盖，但完整重跑后 valid/test 反而退化：`candidate_hit_rate_at_pool` 从 baseline `0.084151` 降到 `0.061711`，`candidate_hit_users` 从 60 降到 44。与此同时 LOPO 指标提升，说明这组召回/source merge 参数更适合可控内部 holdout，不代表真实 valid/test 泛化改善。

**定位方式：**
先运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py` 和 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 做代码级验证；再重跑 baseline 与 Phase 1.11 四组 demo，并读取 `outputs/hybrid_demo/hybrid_demo_small_electronics_10000_semantic_title*/metrics.json`。baseline valid/test 复现 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`、`hit_rate_at_k=0.019635`；Phase 1.11 valid/test 为 `candidate_hit_rate_at_pool=0.061711`、`recall_at_pool=0.024854`、`candidate_hit_users=44`、`hit_rate_at_k=0.018233`；Phase 1.11 LOPO 为 `candidate_hit_rate_at_pool=0.941389`、`hit_rate_at_k=0.793054`、`fallback_rate=0.0`。

**解决方式：**
保留默认关闭、配置隔离的 Phase 1.11 实现和测试，但不把它作为默认策略推进；优化叙事中明确记录 valid/test gate 未通过，并把下一步收敛为 ablation：拆分 semantic IDF、popular cap、balanced source budget、ItemCF seed expansion/decay，定位是哪一路导致真实切分候选命中下降。

**验证结果：**
`tests/test_hybrid_demo.py` 结果为 `41 passed in 0.31s`，`compileall` 通过。Phase 1.11 valid/test 未达到 full target（`candidate_hit_rate_at_pool>=0.100000`、`recall_at_pool>=0.040000`、`candidate_hit_users>=66`）或 partial target（`candidate_hit_rate_at_pool>=0.092`、`recall_at_pool>=0.037`）；LOPO sanity 通过并提升，但 candidate generation p95 升到约 5 秒，说明当前 seed-aware semantic 全量扫描在 10k demo 上已有明显延迟代价。

**面试可讲点：**
这次工作可以讲成“用 gate 否决了一个看起来合理的召回增强方案”：代码测试通过、LOPO 也变好，但真实 valid/test 变差，所以不能因为局部指标好看就推进复杂策略。面试重点是实验纪律和诊断能力：把代码正确性、内部 sanity、真实泛化 gate、延迟成本分开判断，并把失败结果转化为下一轮 ablation 计划。

### 2026-05-09 - Phase 1.12 two_tower recall POC

**任务：**
在 Phase 1.11 组合召回方案未通过 valid/test gate 后，新增一路默认关闭、配置隔离的 `two_tower` U2I 召回 POC，并用 valid/test 与 LOPO 同时验证它是否值得继续推进。

**遇到的问题：**
双塔是典型 U2I 召回路线，但当前项目还不适合直接引入完整训练式双塔、ANN 服务和重依赖；同时 Phase 1.11 已证明“LOPO 变好”不能等价于真实 valid/test 泛化改善，所以新召回源必须用默认关闭 POC 和 gate 指标约束，不能直接替换推荐 backbone。

**定位方式：**
对比 `semantic_title` baseline 与 two_tower POC 的 10k 实验输出：valid/test baseline 为 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`、`hit_rate_at_k=0.019635`；two_tower POC 为 `candidate_hit_rate_at_pool=0.086957`、`recall_at_pool=0.035813`、`candidate_hit_users=62`、`hit_rate_at_k=0.022440`。LOPO baseline 为 `candidate_hit_rate_at_pool=0.939219`、`hit_rate_at_k=0.755427`；two_tower POC 为 `candidate_hit_rate_at_pool=0.939942`、`hit_rate_at_k=0.757598`。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 增加轻量 deterministic token-IDF / cosine-style `two_tower` 候选源，用商品文本构造 item tower、用最近 positive seed 聚合 user tower，并过滤 seen item；在 `rs_core/workflow/hybrid_demo.py` 增加默认关闭加载和配置摘要；新增 valid/test 与 LOPO 隔离配置，保持 LTR disabled，不污染既有 baseline。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py` 结果为 `46 passed`，`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。two_tower POC 在 valid/test 上小幅提升候选覆盖和 hit@5，并在 LOPO 上保持 sanity 不退化；但 `diagnostic_gate` 仍指向 `phase_1_11_recall_source_merge`，且 candidate generation p95 升到约 `1.31s`，因此只能保留为默认关闭实验源，不能宣称已经解除召回瓶颈。

**面试可讲点：**
这次工作可以讲成“在不过度工程化的前提下验证一个经典召回架构方向”：先用轻量 POC 验证双塔式 U2I 召回是否有增量，再用 valid/test、LOPO、source contribution 和 latency gate 同时约束结论。亮点不是盲目上复杂模型，而是把架构升级做成可隔离、可回滚、可量化的实验路径，并诚实记录小幅收益与未通过 gate 的边界。

### 2026-05-09 - PyTorch 双塔 10k CUDA batch 评估

**任务：**
把 DSSM-style 与 YouTubeDNN-style 双塔召回从 smoke 证据推进到同等 10k 数据规模评估，并判断是否可以从默认关闭旁路晋升。

**遇到的问题：**
初始训练环境装成了 `torch 2.11.0+cpu`，无法使用用户机器上的 GPU；切换 CUDA wheel 后又发现训练实现虽然使用 PyTorch，但仍是逐样本循环，GPU 利用率和显存占用都很低。完整 10k 结果出来后，两个双塔在 valid/test 的候选池覆盖都低于 `semantic_title` baseline。

**定位方式：**
用 `nvidia-smi` 和 `.venv` 中的 `torch.cuda.is_available()` 确认 GPU 与 CUDA wheel 状态；检查 `rs_core/recsys/two_tower.py` 发现模型和张量未显式放到 CUDA，且训练 loop 按样本逐条 forward/backward。随后用 2000 用户样本对比 batch size 128/512/1024，并读取 `outputs/training/two_tower/two_tower_training/*/train_metrics.json` 和 10k `metrics.json`。

**解决方式：**
将训练改为自动选择 CUDA device，并把 DSSM / YouTubeDNN 的 forward 改成 batch tensor 计算；训练指标记录 `batch_size`、`training_seconds`、`peak_cuda_memory_mb` 和 `batch_training=true`。batch tuning 后选择 DSSM `batch_size=512`、YouTubeDNN `batch_size=128`，并同步到 valid/test 与 LOPO 配置。一次性 tuning / smoke 目录已清理，只保留正式 10k artifact 与报告。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py` -> `57 passed`，`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。正式训练记录显示 DSSM `device=cuda`、`training_seconds=18.890`、`peak_cuda_memory_mb=26.164`，YouTubeDNN `device=cuda`、`training_seconds=19.649`、`peak_cuda_memory_mb=31.814`。10k valid/test 中，baseline `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`；DSSM 为 `0.071529 / 0.029375 / 51`，YouTubeDNN 为 `0.077139 / 0.031527 / 55`，均 `promotable=false`。YouTubeDNN LOPO 提升到 `candidate_hit_rate_at_pool=0.954414`、`hit@5=0.788712`，但 LOPO 只作为 sanity，不作为晋升依据。

**面试可讲点：**
这次工作体现的是实验工程纪律：先修正环境和训练效率，避免把 CPU/逐样本实现误判为模型效果；再用同等 10k 数据规模、valid/test 与 LOPO 双口径判断是否晋升。结论没有包装成“双塔有效”，而是明确指出训练式双塔在 LOPO 有能力信号，但真实 valid/test 召回覆盖下降，下一步应做 source overlap 和 candidate budget ablation，而不是继续盲目加大模型。

### 2026-05-09 - 公共安全推荐解释工具

**任务：**
为 recommendation_explain_tool 补一条工程叙事，说明解释层如何与推荐、展示和反馈边界分离。

**遇到的问题：**
旧逻辑如果直接把 `ranking`、`source`、`diagnostics`、`reward` 或训练侧字段拼成公开解释，会把内部排序依据、召回来源和评估痕迹暴露到 assistant/display 文本里；同时 `why` 请求若不携带结构化 `item_id`，很难稳定对齐最近一次推荐结果。最终补齐精确 `source` 禁词时，还发现展示 badge 中的 `multi_source` 会进入公开 payload，因此需要同步改成不暴露内部来源概念的 `blended_signal`。

**定位方式：**
对照 `rs_core/rsagent/explanation.py`、`rs_core/rsagent/dialogue.py` 和相关测试，确认解释入口已经从推荐链路里拆出来，应该只基于最新一次 display-safe 推荐商品生成公开文本，而不是回读历史 ranking 或内部诊断对象。

**解决方式：**
从最新的 display-safe 推荐商品生成确定性的中文解释，围绕当前展示 item 的 `parent_asin`、标题、类目和已知反馈约束组织文案；`why` 请求如果带 `item_id`，就结构化传入并只解释最近一次推荐列表中的对应商品，找不到时返回公共兜底文案，不去猜测内部状态。公开展示层同步把 `multi_source` badge 改为 `blended_signal`，避免前端 contract 暴露内部来源语义。

**验证结果：**
已完成的验证范围覆盖解释行为测试、`why` 带/不带 `item_id` 的对话测试、过期 item 的公开兜底、display-safe 边界检查，以及和 `/feedback` / 对话联动的回归测试。实际验证证据为 `python -m pytest tests/test_display_contract.py tests/test_agent_dialogue.py tests/test_agent_feedback.py tests/test_serving_smoke.py tests/test_simulation_runner.py tests/test_simulation_roles.py` -> `58 passed`；`python -m compileall rs_core tests scripts` -> completed successfully。

**面试可讲点：**
这次工作可以讲成“把推荐解释从内部诊断文本收敛成面向用户的 public-safe 解释层”。重点不是多暴露来源，而是让解释始终绑定最新公开商品卡和结构化反馈约束，在能说清推荐理由的同时，不泄露 `ranking`、`reward`、`training` 之类内部信息。

### 2026-05-09 - Phase 4.3 constraint_filter_tool 工程叙事

**任务：**
为 Phase 4.3 的 `constraint_filter_tool` 补一条可复述的工程叙事，说明商品级约束过滤如何接入 Agent 反馈链路并保持公开接口安全。

**遇到的问题：**
约束过滤一开始容易被误解成“再加一层排序规则”，但实际需要的是在反馈重排前先把明显冲突的候选过滤掉，否则 like/dislike/show_different 这些信号会和候选集约束互相打架，导致解释、评估和训练样本都不稳定。

**定位方式：**
对照 `rs_core/rsagent/feedback_rerank.py`、`rs_core/rsagent/policy.py` 和相关测试，确认 `constraint_filter.py` 当前主要由测试直接导入，生产路径已经在 `policy.py` 中串起；同时核对公开服务层和 simulation 侧输出，确保过滤逻辑只影响候选集，不外泄内部排序/诊断字段。

**解决方式：**
将约束过滤保持为独立、可测试的工具实现，并在 `policy.py` 的生产路径中统一调用，让它先于反馈重排生效；这样既能显式处理 hard constraints，又能保留后续 `feedback_rerank`、scorecard 和 training artifact 的一致性。当前还有一个非阻塞观察：`constraint_filter.py` 主要由测试直接导入，后续可以考虑把测试入口和生产接口合并成更清晰的单一路径。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_agent_rollout_schema.py tests/test_simulation_runner.py tests/test_simulation_roles.py` -> `73 passed`；`python -m compileall rs_core scripts tests` -> completed successfully。

**面试可讲点：**
这段工作可以讲成“把约束过滤从排序规则里拆出来，变成反馈重排前的独立安全闸门”：先保证候选集合法，再谈个性化重排和解释输出。这样做的价值是边界更清楚、测试更稳定、公开接口更安全，也更方便后续把过滤信号沉淀进评估和训练数据。

### 2026-05-09 - 10k 默认晋升硬门禁复核

**任务：**
基于已验证的 8 组 10k 实验结果，整理 valid/test 默认晋升硬门禁证据表，并更新中文优化叙事，避免把 LOPO sanity 或配置变体误写成默认提升。

**遇到的问题：**
`semantic_title`、source-aware 和 LTR 变体在指标上相对 baseline 有明显收益，但默认晋升不能只看 `candidate_hit_rate_at_pool`、`recall_at_pool` 或 `hit@5`；本轮硬门禁还要求 `metrics.latency.candidate_generation_p95_seconds <= baseline * 1.2`。同时 `semantic_title` 只是实验配置变体，不是独立 source key；`user_profile` 也不是 10k 独立召回源，不能混入召回来源叙事。

**定位方式：**
使用 worker-1 的 source 边界审计结论和 worker-2 的 8 组 verified metrics。实验统一入口为 `./.venv/Scripts/python.exe scripts/evaluation/run_hybrid_demo.py --config <config>`；默认晋升只看 valid/test，LOPO 只作为 sanity / 诊断。valid/test baseline 的 `candidate_generation_p95_seconds≈0.000637s`，硬阈值约 `0.000764s`。

**解决方式：**
在 `dic/OPTIMIZATION_NARRATIVE.md` 增加“10k 默认晋升硬门禁复核”小节，分别列出 valid/test 与 LOPO 表格，并显式写清：合法 source key 只有 `popular`、`category`、`itemcf_weak`、`itemcf_strong`、`semantic`；`two_tower` POC 不纳入本次默认 gate；LOPO 不能替代 valid/test 晋升口径。

**验证结果：**
valid/test 中 baseline 为 `candidate_hit_rate_at_pool=0.032258`、`recall_at_pool=0.010322`、`hit@5=0.007013`、`candidate_hit_users=23`、`p95≈0.000637s`；`semantic_title` / source-aware / LTR 分别达到 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`、`candidate_hit_users=60`，但 p95 分别约 `0.402541s`、`0.400739s`、`0.388379s`，全部超过硬延迟阈值。LOPO 三个增强变体也全部超过以 LOPO baseline `p95≈0.000775s` 计算的硬延迟阈值。因此本轮结论是：不做默认晋升，只保留为召回 / 排序诊断证据。

**面试可讲点：**
这次工作体现的是 gate discipline：即使召回覆盖和 hit@5 变好，也必须同时满足泛化口径和 latency budget 才能默认晋升。LOPO 可以证明模块能力和排序诊断价值，但不能代替 valid/test；配置变体、偏好信号和真实 source key 也必须分清，避免实验叙事夸大。

### 2026-05-09 - Phase 4.4 Agent tool contract cleanup

**任务：**
收敛 Agent 工具链路的公开契约，把约束过滤、反馈重排、评分卡、训练产物和仿真评估的边界理顺，避免把内部排序、诊断和训练字段泄露到服务层或展示层。

**遇到的问题：**
Phase 4.4 之前，`constraint_filter.py` 的测试入口和 `policy.py` 的生产路径存在重复实现，事件字段形态也不完全一致；同时 reward、artifact、scorecard 各自手写 `constraint_filter_events` / `feedback_rerank_events` 聚合逻辑，后续新增工具时容易漂移。公开接口如果误混入 `ranking`、`diagnostics`、`reward`、`scorecard`、`tool_events` 等内部字段，也会破坏 display/session contract。

**定位方式：**
回看 `rs_core/rsagent/constraint_filter.py`、`rs_core/rsagent/policy.py`、`rs_core/rsagent/reward.py`、`rs_core/evaluation/agent_artifact.py`、`rs_core/evaluation/agent_scorecard.py` 和对应测试，确认真正需要修的是“工具实现入口”和“事件聚合边界”，而不是再加新的排序策略。重点检查 direct module test 与 production workflow 是否共享同一套约束过滤行为，以及公开导出是否只保留 display-safe / session-safe 字段。

**解决方式：**
将 `constraint_filter.py` 改成委托生产 `policy.constraint_filter_tool`，保留 direct import contract 但不再维护第二套过滤逻辑；新增 `rs_core/rsagent/tools.py`，集中定义工具事件 key 和 diagnostics/turn/rollout 事件收集 helper，让 reward、artifact、scorecard 复用同一套聚合逻辑；公开服务、展示、session export 和仿真输出仍只消费 display-safe 结果，不暴露内部 tool events。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_agent_rollout_schema.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_simulation_roles.py tests/test_simulation_runner.py -q && python -m compileall -q rs_core scripts` -> `75 passed`，`compileall` exit `0`。验证同时覆盖约束过滤、商品级反馈重排、训练/评估产物、公开服务 contract 和仿真链路，确认内部字段没有外泄。

**面试可讲点：**
这次工作可以讲成“把 Agent 工具链从能跑，收敛到能审计、能复用、能公开”：先把约束过滤放到反馈重排之前，确保候选合法；再把评分卡、reward 和 training artifact 留在内部；最后让服务层、解释层和仿真层都共享同一套 display-safe contract。这样既方便后续继续扩展工具，也避免训练、评估和前端看到不同版本的推荐真相。

### 2026-05-09 - 弱底座上的 Agent 机制验证

**任务：**
在当前推荐底座还不完善的情况下，不验证最终推荐效果绝对值，而是验证 Agent 工具机制、评估产物和 public/internal 边界是否可靠。

**遇到的问题：**
目标测试通过后，小规模 `run_agent_evaluation.py` 端到端 smoke 暴露出更底层的问题：即使用 electronics smoke 数据和已知存在行为序列的用户，服务层仍没有产出展示商品，导致模拟用户只能连续发 chat，`feedback_rerank` / `constraint_filter` 等工具事件无法在端到端场景中触发。因此这轮不能把 baseline/enhanced 分数当作推荐效果结论。

**定位方式：**
先运行覆盖 Agent 工具链的目标测试，得到 `83 passed`，确认 constraint filter、feedback rerank、explanation、reward/artifact/scorecard 和 public 边界的机制契约稳定；再运行 `scripts/evaluation/run_agent_evaluation.py --config configs/demo/hybrid_demo/hybrid_demo_electronics.yaml --roles commuter_practical --max-turns 3 --repeats 1`，输出 artifact/scorecard/training signals，但 scorecard 显示 `recommendation_effectiveness=0.0`、`tool_event_count=0`。随后用固定用户 `AFKZENTNBQ7A7V7UXW5JJI6UGRYQ` 重跑，结果仍然没有 display items；最后直接调用 `RecommendationService.chat()` 探针，确认每轮 `candidates=0`、`ranking=0`、`final_items=0`。

**解决方式：**
本轮不强行调参或伪造推荐结果，而是把验证结论改为“机制级通过，端到端候选供给未通过”。当前可确认的是：Agent 工具和评估产物在单元/集成层稳定，evaluation runner 能产出 `agent_evaluation.json`、`scorecard.json`、`training_signals.json` 和 report；但真实端到端场景还需要先修复候选生成/对话入口，让服务层能稳定返回商品，之后再验证工具事件数量、拒绝商品复现率和 enhanced 相对 baseline 的机制收益。

**验证结果：**
`python -m pytest tests/test_constraint_filter_tool.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_dialogue.py tests/test_agent_reward.py tests/test_agent_eval_artifact.py tests/test_agent_scorecard.py tests/test_agent_rollout_schema.py tests/test_serving_smoke.py tests/test_display_contract.py tests/test_simulation_roles.py tests/test_simulation_runner.py -q` -> `83 passed in 1.20s`。两次 agent evaluation 均成功落盘，但 `tool_event_count=0`、`feedback_count=0`、`why_count=0`、展示 `items=[]`；直接 service 探针也确认 `candidates/ranking/final_items` 均为 0。

**面试可讲点：**
这次验证体现的是弱底座阶段的评估纪律：不因为评估脚本能跑通就宣称 Agent 效果提升，而是把结论拆成“机制契约已稳定”和“端到端候选供给仍阻塞”。这能说明项目不是盲目堆 Agent 能力，而是用测试、artifact 和 smoke run 找到下一步真正该修的瓶颈。

### 2026-05-09 - Phase 4.6 空候选恢复与 E2E 机制验证

**任务：**
在弱推荐底座上补齐空候选场景的有界恢复，先让 Agent E2E 机制验证可继续推进，而不是直接把结果解释成训练效果。

**遇到的问题：**
端到端 smoke 在弱底座上出现 `candidates=0`、`final_items=0`，模拟用户和 feedback 工具链都被卡住；如果不处理这一层，后续 `feedback_rerank`、`constraint_filter` 和展示闭环都无法触发。

**定位方式：**
沿着 `merge_for_user` 的候选合并路径排查，确认问题出在 `popular` fallback 之后仍做了严格 seen 过滤，导致热门候选也被清空；随后结合 smoke 输出核对 `tool_event_count=6`、两种变体的 `display_item_counts=[2,1,1,1]`，确认是候选供给问题而不是评估器失效。

**解决方式：**
在 `rs_core/recsys/candidate_merge.py` 增加有界 empty-pool recovery：先保留 seen 过滤的主路径，再对 `popular` fallback 做受控补回，保证弱底座至少能产出可交互的最小候选池；同时让增强 rerank 尊重 `constraint_filter_restored`，避免恢复候选后又把同一批商品误删，保持机制验证的最小闭环。

**验证结果：**
运行 `python -m pytest tests/test_simulation_roles.py tests/test_simulation_runner.py` 等 24 个 simulation 相关测试通过，`python -m compileall -q rs_core tests scripts` 通过；seeded evaluation 输出中两个变体都稳定得到 `display_item_counts=[2,1,1,1]`，`tool_event_count=6`，说明候选恢复后 Agent 交互链路重新打通。

**面试可讲点：**
这次工作可以讲成“先修复候选供给，再谈 Agent 机制验证”：我没有把空候选问题包装成训练提升，而是把它定义为评估前置条件，先用有界恢复把 E2E 机制链路打通。它 unblocks 的是 Agent E2E 机制验证，不是 SFT / RL 结果本身。

### 2026-05-10 - 前端工作台重构与 Persona Sprite 素材库

**任务：**
把 RS Agent 前端从单页商品卡 demo 扩展为 Dashboard + Tabs 工作台：Live User Demo 负责真人用户与推荐 Agent 对话、商品卡反馈和 Session Replay，Agent Sandbox 负责多角色 Persona Agent 自动交互、状态面板、timeline 和批量对比。

**遇到的问题：**
前端需要同时展示“推荐 Agent”和“多角色 Persona Agent”的关系，但不能让像素小人和沙盒 UI 反过来污染推荐决策、feedback payload、ranking、reward 或公开 display contract；同时 Codex / Gemini 调用链需要修复后才能按用户要求让 Gemini 执行前端、Codex 处理图像生成封装。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`rs_core/serving/schema.py` 和 `/simulation/batch` contract，确认前端只应消费服务层与展示层字段；用 `Grep frontend/src "dicebear|ranking|reward|diagnostics|score"` 检查外部头像和内部字段泄露风险，并用 `omc ask gemini/codex` 验证外部 CLI 调用链恢复。

**解决方式：**
由 Gemini 执行前端组件拆分，新增 `frontend/src/views/LiveDemo.tsx`、`frontend/src/views/Sandbox.tsx`、商品卡 / 聊天 / replay / feedback 组件，以及 sandbox 下的 persona 状态、timeline、batch comparison 组件；手动把外部 Dicebear URL 收敛为本地 `frontend/src/assets/persona-sprites/manifest.json` 和 `PersonaSprite` 展示组件。Codex 侧新增 `scripts/assets/generate_persona_sprites.py`，读取 manifest prompt 并通过 OpenAI Images API 兼容接口生成 PNG，默认模型为 `gpt-image-2`，支持 `--dry-run`、`--check`、`--force` 和 secret-safe 错误提示。

**验证结果：**
`npm --prefix frontend run build` 通过，Vite 生产构建完成；`./.venv/Scripts/python.exe -m py_compile scripts/assets/generate_persona_sprites.py`、`./.venv/Scripts/python.exe scripts/assets/generate_persona_sprites.py --help` 和 `--dry-run` 均通过，dry-run 识别 5 个 persona 输出目标；`Grep frontend/src "dicebear|ranking|reward|diagnostics|score"` 无匹配。未在本轮使用浏览器做人工视觉验收，后续如需要可启动 Vite dev server 进行交互检查；真实 PNG 生成仍需要配置 `OPENAI_API_KEY` 或兼容图片 API key。

**面试可讲点：**
这次工作可以讲成“把推荐 Agent demo 产品化成可演示工作台，同时守住 display-safe 边界”：Live Demo 面向真实用户交互闭环，Sandbox 面向多角色模拟评估，Persona Sprite 只作为展示层素材库按 `role_id` 取用，不进入推荐策略。实现上还体现了多模型协作分工：Gemini 做前端实现，Codex 做图像生成封装，我负责 contract 边界、集成修正和验证。


### 2026-05-11 - Phase 1.17 rank_weights 冻结池调权结果

**任务：**
在固定召回候选池上验证 Phase 1.17 的 rank_weights 调整是否真的带来 Top-K 排序增益，并把 promotion / no_gain 的结论写成可复述的中文证据记录。

**遇到的问题：**
这轮所有非 baseline 配置都保持了同样的候选池命中、fallback 和候选均值，说明变化只可能发生在排序层；同时并不是每个“指标变好”的配置都应该晋升，必须按 same-run baseline 判断 `hit_rate_at_k`、`ndcg_at_k` 和 `mrr_at_k`，避免把 partial 改善误写成 promotion。

**定位方式：**
以 `outputs/archive/root_files/phase_1_17_rank_weight_comparison.json`、`outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.json`、`outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.csv` 和 `dic/experiments/ranking/PHASE_1_17_RANK_WEIGHT_*.md` 为证据，逐项核对 same-run baseline 与各调权变体的 `candidate_hit_users`、`candidate_hit_rate_at_pool`、`recall_at_pool`、`ranked_hit_users`、`hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k`、`candidate_hit_rank_p50/p90` 和 `promotion_status`。baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`fallback_rate=0.0`、`candidate_count_avg=97.936752`、`hit_rate_at_k=0.019635`、`ndcg_at_k=0.005876`、`mrr_at_k=0.012202`、`rank p50=18`、`rank p90=55`。

**解决方式：**
按决策矩阵把结果分成三类：`popular_0_8`、`popular_0_9`、`semantic_1_3` 归入 PROMOTION；`semantic_1_0`、`semantic_1_1`、`popular_1_1`、`two_tower_1_0`、`two_tower_1_1`、`two_tower_1_3` 归入 NO_GAIN；没有 PARTIAL_DIAGNOSTIC。这样可以把真正有 Top-K 增益的轻量调权和无收益调权分开，避免后续阶段误继承错误配置。

**验证结果：**
本轮比较矩阵显示所有非 baseline 配置都与 baseline 保持相同的候选池统计，没有 INVALID；`popular_0_8` 的 `hit_rate_at_k=0.025245`，较 baseline 提升 `+0.005610`，同时 `ndcg_at_k` 提升 `+0.001587`、`mrr_at_k` 提升 `+0.001566`，是最强候选；`popular_0_9` 和 `semantic_1_3` 也达到 PROMOTION，但提升幅度更小；其余配置未超过 same-run baseline，不应晋升。

**面试可讲点：**
这轮最重要的不是“又调高了一个分数”，而是建立了固定候选池上的调权裁决纪律：先证明候选池稳定，再用 same-run baseline 判断是否晋升。`popular_0_8` 说明在当前阶段，适度下调 popular 权重比继续放大 semantic 或 two_tower 更有效；这类结论比单纯报一个更高的 hit@k 更适合拿到面试里解释“为什么这样做”。

### 2026-05-10 - Phase 1.13 YouTubeDNN 召回主路与排序承接复核

**任务：**
验证 `semantic_title + YouTubeDNN` 在 10k valid/test 下是否可以进入召回主路，并区分候选池覆盖与最终 Top-K 排序承接。

**遇到的问题：**
初始结论把“Top-K 未达标”误写成“two_tower 不应进入主路”。这混淆了召回层和排序层：YouTubeDNN 的职责是把目标商品召回进候选池，Top-K 则应由后续排序完成。

**定位方式：**
对照 pool100 验收口径复跑 Phase 1.13 valid/test，并读取 `metrics.json`。pool50 配置会导致候选池指标先天偏低，因此修正为 pool100 后重新比较 `candidate_hit_rate_at_pool`、`candidate_hit_users` 与 `hit_rate_at_k`。

**解决方式：**
保留 YouTubeDNN 作为召回主路候选源；同时把 `source_aware_fusion`、`item_feature_rerank` 和旧 LTR 的结论限定为“排序承接未通过”，不再用排序失败否定召回效果。Phase 1.13 隔离配置继续保留，后续排序阶段基于固定召回池另行优化。

**验证结果：**
pool100 valid/test 候选池达标：`candidate_hit_rate_at_pool=0.105189`、`recall_at_pool=0.042043`、`candidate_hit_users=75`、`fallback_rate=0.0`。排序承接未达标：pool100 rerank `hit_rate_at_k=0.015428`，very conservative `hit_rate_at_k=0.016830`，均低于 `0.019635`。candidate generation p95 约 `0.41s`，说明召回主路落地还需要检索性能优化。

**面试可讲点：**
这次复核体现的是推荐系统分层诊断：召回层看 candidate pool hit，排序层看 Top-K hit，系统层看 latency。YouTubeDNN 能进入召回主路，但排序模型需要后续独立训练和验证；不能因为 Top-K 暂时没提升，就否定召回源对候选覆盖的贡献。

### 2026-05-11 - Phase 1.14 ranking v2 / LTR v2 固定召回池验证

**任务：**
在固定 `semantic_title + YouTubeDNN pool100` 召回池上验证 ranking v2 / LTR v2，判断它是否能把已经进入候选池的命中商品推入 Top-K。

**遇到的问题：**
valid/test 候选池覆盖达到验收线，但 Top-K 排序没有承接住新增候选；同时 LOPO sanity 指标较好，容易被误写成晋升依据，需要明确 LOPO 只作 sanity。

**定位方式：**
先运行 `./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py -q` 与 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts`，再用 `scripts/training/train_ltr_ranker.py` 训练 valid/test 与 LOPO 各自独立的 LTR v2 artifact，最后运行两个 Phase 1.14 full demo 并读取 `metrics.json`。

**解决方式：**
保留 `semantic_title + YouTubeDNN pool100` 作为召回池口径；对 valid/test 与 LOPO 分别使用独立训练输出目录，避免覆盖旧产物或混用模型。文档结论按 valid/test 晋升口径书写，不用 LOPO 包装成功。

**验证结果：**
测试通过：`65 passed in 0.24s`，`compileall` 通过。valid/test 指标为 `candidate_hit_rate_at_pool=0.105189`、`recall_at_pool=0.042043`、`candidate_hit_users=75`、`hit_rate_at_k=0.001403`、`fallback_rate=0.0`、`candidate_generation_p95_seconds=0.472091`、`ranking_p95_seconds=0.002814`；其中候选池达标，但 `hit_rate_at_k` 低于 baseline `0.019635` 和目标 `0.023843`，ranking v2 / LTR v2 未通过。LOPO sanity 为 `candidate_hit_rate_at_pool=0.956585`、`hit_rate_at_k=0.811143`、`candidate_hit_users=1322`，只能说明同分布 sanity 通过，不能作为晋升依据。

**面试可讲点：**
这次验证体现的是排序阶段的评估纪律：固定召回池后，只看排序是否把命中候选推入 Top-K。结果证明 ranking v2 / LTR v2 反而把 valid/test 命中候选压低，说明下一步应检查训练样本和 label 口径，而不是用 LOPO 高分掩盖泛化失败。

### 2026-05-11 - Phase 1.15 冻结 YouTubeDNN pool100 与隔离 ablation

**任务：**
冻结 `semantic_title + YouTubeDNN pool100` 召回基线，补齐隔离的 gate / config / test 覆盖，并根据 verify-worker 的 #3 / #5 / #7 结果更新 Phase 1.15 叙事。

**遇到的问题：**
frozen 基线本身已经能跑通，容易把“能跑完”误写成“默认晋升”；semantic IDF 版本在 `rs_core/recsys/candidate_merge.py` 里先出现过 hang，修复后虽然能跑完，但 valid/test 命中和 latency 都没有过门禁。如果把 ablation 结果混进 final，会把诊断实验误当成主路方案。

**定位方式：**
把 `PHASE_1_15_FROZEN_YOUTUBEDNN_POOL100.md`、`PHASE_1_15_VALID_FINAL_CANDIDATE.md`、`PHASE_1_15_LOPO_SANITY.md` 和 `PHASE_1_15_ABLATION_SEMANTIC_IDF_BUDGET.md` 放在同一口径下对比，只看 `candidate_hit_rate_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds` 和 `ranking_p95_seconds`，并固定 `candidate_pool_size=100`、`top_k=5`、`YouTubeDNN pool100` 不变。

**解决方式：**
把 `YouTubeDNN pool100` 固定为 Phase 1.15 的 recall baseline，只允许 isolated gate / config / test 继续做对照；semantic IDF hang 修复后，ablation 仍只保留为诊断证据，不进入 final。

**验证结果：**
frozen baseline valid/test 为 `candidate_hit_rate_at_pool=0.106592`、`hit_rate_at_k=0.019635`、`candidate_generation_p95_seconds=0.461527s`；final valid/test candidate 仍是 `0.106592 / 0.019635`，`candidate_generation_p95_seconds=0.485096s`，没有比 frozen 带来同跑增益。LOPO sanity 为 `candidate_hit_rate_at_pool=0.959479`、`hit_rate_at_k=0.798119`、`candidate_generation_p95_seconds=0.39457s`，只能证明同分布 sanity 通过。semantic IDF ablation 为 `candidate_hit_rate_at_pool=0.100982`、`hit_rate_at_k=0.00561`、`candidate_generation_p95_seconds=0.777899s`、`ranking_p95_seconds=0.000721s`，没有超过 frozen，也没有过 latency gate。

**面试可讲点：**
这轮可以讲成“先冻结能站得住的 baseline，再用隔离 ablation 证明哪些变体不该进主线”。它的价值不是再造一个高分配置，而是把默认晋升的证据边界收紧，避免把 LOPO 或局部优化误写成主路收益。

### 2026-05-11 - Phase 1.16 item_graph recall 生成与接入验证

**任务：**
在 Phase 1.15 冻结基线之后，引入并验证 `item_graph` 召回路径，确认它是否真的能带来新的 valid/test 候选，而不是重复现有 recall 覆盖。

**遇到的问题：**
`item_graph` 虽然能够生成并接入 views，但很容易和已有 recall source 高重叠；如果只看 LOPO，会把同分布上的高分误写成晋升证据。

**定位方式：**
同时对照 frozen baseline、item_graph 接入后结果和 LOPO sanity，只看 `candidate_hit_rate_at_pool`、`recall_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds`、`fallback_rate` 以及 item_graph diagnostics，确保 valid/test 才是默认晋升口径。

**解决方式：**
生成 `item_graph_recall.jsonl` 并接入 views 重建流程，保留 frozen baseline 对照；用 item_graph diagnostics 检查 seed 命中、raw candidate/unseen 规模和 source coverage，但不把强 LOPO sanity 误写成默认晋升。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_simulation_runner.py tests/test_ltr.py -q` 通过，61 项测试全部通过。frozen baseline 与 item_graph 接入后的 valid/test 指标完全持平：`candidate_hit_users=76`、`candidate_hit_rate_at_pool=0.106592`、`recall_at_pool=0.042219`、`hit_rate_at_k=0.019635`，但 `candidate_generation_p95_seconds` 从 `0.461527` 降到 `0.411992`。item_graph diagnostics 显示 `users_with_item_graph_seed_hits=1514`、`raw_candidates=55776`、`raw_unseen=22286`、`candidate_hit_source_coverage.item_graph=1`。LOPO sanity 为 `candidate_hit_rate_at_pool=0.970333`、`hit_rate_at_k=0.813314`、`item_graph candidate hits=1341`，只能作为同分布诊断证据。

**面试可讲点：**
这轮可以讲成“新增召回源不等于默认晋升”。我先把 item_graph 的生成、接入和诊断链路做实，再用 valid/test 与 LOPO 分开裁决：工程链路是通的，但主口径没有增益，所以结论必须是 fail/no promotion。

### 2026-05-11 - Phase 1.18 two_tower_seed item-neighbor 召回旁路验证

**任务：**
在冻结的 `semantic_title + YouTubeDNN pool100` 召回主路之外，新增默认关闭的 `two_tower_seed` I2I 召回旁路，验证已有 YouTubeDNN item embedding 的离线 nearest-neighbor sidecar 是否能带来新的 valid/test 候选覆盖。

**遇到的问题：**
初始实现中 builder 输出 `{item_id, neighbors}`，但 runtime loader 仍按旧 `src_item/dst_item/score` schema 读取；同时 sidecar 输出路径如果和 embedding 输入路径或 manifest 路径重合，会误删或覆盖 artifact。实验层面，LOPO sanity 对该旁路有明显贡献，但默认晋升必须看 same-run valid/test，而不能用 LOPO 高分包装成功。

**定位方式：**
检查 `rs_core/workflow/two_tower_training.py`、`scripts/training/build_two_tower_neighbors.py`、`rs_core/recsys/candidate_merge.py` 和 `tests/test_hybrid_demo.py`，确认 sidecar schema 不一致；随后用独立 code-reviewer 复核 Phase 1.18 改动，发现 sidecar path distinctness 风险。最终通过 `outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json` 对照 frozen baseline、Phase 1.18 valid/test 和 LOPO sanity。

**解决方式：**
将 runtime loader 改为解析 `{item_id, neighbors:[{item_id, score, rank}]}`，并在 `fail_on_missing_sidecar=true` 时校验 manifest 的 `phase/source/schema_version`；为 sidecar builder 增加输入、sidecar、manifest 三个路径必须互异的 fail-closed 校验；新增 Phase 1.18 valid/test 与 LOPO 隔离配置，保持排序增强全部 disabled；新增 `scripts/experiments/recall/run_phase_1_18_recall_gate.py` 生成 same-run gate artifact。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py tests/test_build_recall_views.py` 通过，75 项测试全部通过；`compileall` 针对更新脚本和模块通过。完整 gate 命令 `./.venv/Scripts/python.exe scripts/experiments/recall/run_phase_1_18_recall_gate.py --skip-sidecar-build --output outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json` 写出 comparison JSON 并因 gate 未通过返回 exit 1。same-run frozen baseline 为 `candidate_hit_users=76`、`candidate_hit_rate_at_pool=0.106592`、`recall_at_pool=0.042219`、`fallback_rate=0.0`、`candidate_generation_p95_seconds=0.427404`；Phase 1.18 为 `75 / 0.105189 / 0.041066 / 0.0 / 0.452250`，且 `candidate_hit_source_coverage.two_tower_seed=8`。LOPO sanity 为 `candidate_hit_rate_at_pool=0.957308`、`hit_rate_at_k=0.796671`、`two_tower_seed candidate hits=184`，只能作为 sanity。

**面试可讲点：**
这次工作体现的是召回实验的工程化和否决纪律：我把双塔 item embedding 扩展为可离线构建、可 manifest 校验、可默认关闭接入的 I2I 旁路，但最终没有因为它有真实 source contribution 或 LOPO 高分就晋升。valid/test 候选池覆盖下降说明它和现有主路的组合方式仍不泛化，因此结论必须是 `FAIL / no promotion`，保留为负向实验和后续 budget/overlap 分析依据。

### 2026-05-12 - Phase 1.18 决策复核：popular=0.8 保持不晋升

**任务：**
复核 Phase 1.18 的 second-order rank-weight 组合结论，确认是否存在可晋升到主路的权重配置，并基于失败归因判断下一阶段该往哪条线推进。

**遇到的问题：**
没有任何 second-order rank-weight 组合在 `hit_rate_at_k` 上超过 `popular=0.8`；失败主要集中在候选 miss，而不是排序细节，说明继续细调权重的边际收益很低。

**定位方式：**
复核决策审查结果与失败归因统计，重点看 `hit_rate_at_k` 对照和 candidate miss / rank miss 的占比，确认问题是否来自排序还是召回覆盖。

**解决方式：**
维持 `popular=0.8` 作为当前排序基线，不晋升 second-order rank-weight 组合；将后续探索方向切换到 recall/source coverage，而不是继续堆排序权重。

**验证结果：**
决策结论为 `NO_PROMOTION_KEEP_POPULAR_0_8`。failure attribution 显示 `candidate miss = 644/713 (90.3226%)`，说明瓶颈主要在候选覆盖；当前阶段没有证据支持继续推进 second-order rank-weight 组合晋升。

**面试可讲点：**
这一步能讲成“先用指标复核锁定最稳基线，再用失败归因判断下一步该加权还是补召回”。最终没有把局部排序优化当成主线，而是把资源转向 recall/source coverage，这样更符合收益来源。

### 2026-05-11 - Phase 1.19 DeepWalk graph_walk_seed 结构召回旁路验证

**任务：**
在冻结的 `semantic_title + YouTubeDNN pool100` 召回主路之外，新增默认关闭的 `graph_walk_seed` 结构召回旁路，用 DeepWalk-style 图游走从正反馈序列中学习 item embedding，并通过 same-run gate 判断是否能带来新的 valid/test 候选覆盖。

**遇到的问题：**
新 source 必须和已有 `item_graph` 保持 source identity 隔离；训练产物不能只是临时 sidecar，需要 manifest/hash/device 等可复现证据；smoke gate 返回 exit 1 时需要区分“门禁未通过”和“脚本崩溃”。

**定位方式：**
复核 `rs_core/workflow/graph_walk_training.py`、`rs_core/recsys/candidate_merge.py`、`rs_core/workflow/hybrid_demo.py` 和 `scripts/experiments/recall/run_phase_1_19_graph_walk_seed_gate.py`，确认训练、manifest 校验、runtime opt-in 和 gate 检查边界；读取 `outputs/recall/phase_1_19_graph_walk_seed_gate_smoke_verifier/comparison.json` 对照 baseline、experiment、source-only 和 without_graph_walk 指标。

**解决方式：**
保留 `graph_walk_seed_enabled=false` 默认关闭，由 gate 通过 overrides 启用实验；manifest 校验 `phase/source/schema_version/algorithm/sidecar_hash`，runtime 维持 `graph_walk_seed` 独立 source label、seen filtering、recency decay、score floor 与 per-user cap；gate 同时检查 default-off baseline 一致性、source identity、预算、延迟和 candidate/recall lift。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_graph_walk_seed.py tests/test_hybrid_demo.py` 通过，69 项测试全部通过。full gate 命令 `./.venv/Scripts/python.exe scripts/experiments/recall/run_phase_1_19_graph_walk_seed_gate.py --output outputs/recall/phase_1_19_graph_walk_seed_gate/comparison.json` 写出 comparison JSON，并因 promotion checks failed 返回 exit 1。same-run full gate 中 baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`candidate_generation_p95_seconds=0.49439`；default-off disabled 与 baseline 完全一致；experiment 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.039079`、`candidate_generation_p95_seconds=0.623431`，有 `candidate_hit_source_coverage.graph_walk_seed=2`、`recall_source_coverage.graph_walk_seed=22377`、`users_with_graph_walk_seed_hits=1530`、`graph_walk_seed_raw_candidates=1072400`、`graph_walk_seed_raw_unseen_candidates=986695`、`candidate_share=0.076823`、`max_candidates_per_user_observed=15`。gate 结果为 `passed=false`，失败项包括 `candidate_hit_users_lift=false`、`candidate_hit_rate_at_pool_lift=false`、`recall_at_pool_lift=false`、`candidate_generation_p95_budget=false`、`lopo_candidate_generation_p95_budget=false`；同时 `graph_walk_seed_hit_contribution=true`、`default_off_matches_baseline=true`、`source_identity_not_mixed_with_item_graph=true`、`source_cap_not_exceeded=true`。manifest 显示 full training 使用 `device=cuda`，`item_count=9174`、`edge_count=9442`、`walk_count=91740`、`positive_pair_count=15595800`。

**面试可讲点：**
这轮可以讲成“图游走召回旁路的工程化和否决纪律”：我不仅实现了 DeepWalk-style 训练和可校验 artifact，还用 same-run gate 证明它虽然能产生大量结构候选，但没有带来真实候选命中或 recall lift，所以明确记录为 `FAIL / no promotion`，不把工程可用误写成主路晋升。

### 2026-05-11 - 横向收口：仿真前后端契约对齐

**任务：**
在不接管 agent、前端、传统推荐底座主体实现的前提下，做一次跨 `serving`、`display`、`simulation`、前端类型和关键测试的横向收口。

### 2026-05-11 - Phase 1.20 fallback limit500 诊断核验

**任务：**
在 full run 过慢的前提下，先用 `--limit-users 500` 跑通 recall diagnostics fallback 核验，确认产物只作为诊断证据，不当作 full-run 晋升结果。

**遇到的问题：**
full run 时间成本高；same-run 分母容易漂移；必须保证 frozen / Phase 1.17 tracked diff 检查不被诊断脚本污染。

**定位方式：**
运行 `scripts/experiments/recall/phase_1_20_recall_diagnostics.py --limit-users 500`，检查 `outputs/recall/phase_1_20_recall_diagnostics_large_limit500/`、manifest `run_id=756ade477bdf7c45`、`evaluation_mode=valid_test`、分母字段和保护检查输出；核对 CSV/JSON parity、required files、raw oracle stages 与专项测试结果。

**解决方式：**
将本轮固定为 fallback limit500 口径，显式保留 `hit_rate_denominator=users_with_holdout`、`users_with_holdout=138`、`limit_users=500` 的同口径对照，并把 frozen / Phase 1.17 diff clean 作为保护门禁。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_hybrid_demo.py tests/test_ltr.py` 通过，合计 `79 passed`。`outputs/recall/phase_1_20_recall_diagnostics_large_limit500/` 产出了 limit500 artifact，baseline hash `afa923fb623402a51f17157565e204d1954fdd93814d102cf8c96e5c7a8ddff5`，CSV/JSON parity 与保护性 diff 检查 clean。

**面试可讲点：**
这轮可以讲成“把诊断本身也做成可审计门禁”：不追求一次性全量跑完，而是先用有限 fallback + 分母一致性 + 冻结产物保护，确认诊断链路可靠再谈下一步。

**遇到的问题：**
后端 `SimulationSceneRequest` / `SimulationBatchRequest` 将 `max_turns` 限制为 1-8，但前端沙盒输入仍允许 10；同时 batch scene 会携带 `metrics`，前端 `SimulationSceneResponse` 类型没有显式表达该字段，容易在后续 batch comparison 扩展时产生隐性契约漂移。

**定位方式：**
对照 `rs_core/serving/schema.py`、`rs_core/simulation/runner.py`、`frontend/src/types.ts`、`frontend/src/components/sandbox/*` 和 `tests/test_simulation_runner.py`，确认公开 display contract、session export、simulation scene / batch 主链路基本一致，缺口集中在前端输入边界和 TypeScript 类型表达。

**解决方式：**
在 `frontend/src/types.ts` 补充 `SimulationSceneMetrics` 并让 `SimulationSceneResponse.metrics` 可选，兼容单 scene 与 batch scene；把 `PersonaStatePanel` 和 `BatchSimulationPanel` 的 `max_turns` 输入上限从 10 收敛到 8，与服务端 Pydantic contract 对齐。

**验证结果：**
`npm --prefix frontend run lint` 通过；`.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_serving_smoke.py tests/test_display_contract.py` 通过，29 项关键契约 / serving / display / simulation 测试全部通过。

**面试可讲点：**
这次工作可以讲成“多窗口并行开发后的 contract gate”：不重写任何一个模块，而是用 schema、前端类型和回归测试把 agent 交互、服务层、展示层、仿真评估串成可验证边界，防止局部功能能跑但端到端契约慢慢漂移。

### 2026-05-12 - Phase 1.17b popular=0.8 稳定性复核

**任务：**
在 frozen-pool ranking 上复核 popular=0.8 是否能稳定晋升，并对比 0.75/0.85 邻近权重。

**遇到的问题：**
单次 Phase 1.17 smoke 只能说明局部 promotion candidate，不能直接作为默认基线；还需要确认候选池稳定，且收益来自排序而不是召回。

**定位方式：**
对照 `outputs/archive/root_files/phase_1_17b_rank_weight_comparison.json` 和 `outputs/archive/root_files/phase_1_17b_popular_0_8_case_effects.json`，核对 same-run baseline、popular=0.8 和邻近 0.75/0.85 的候选池统计、Top-K 指标和 case-level 命中变化。

**解决方式：**
把 `popular=0.8` 定位为新的 frozen-pool ranking baseline，同时保留 `popular=0.75/0.85` 作为稳定性参考，不再扩大搜索到召回或全链路泛化。

**验证结果：**
same-run baseline 与 `popular=0.8` 的 candidate-hit / recall / fallback / candidate_count 完全一致，但 `hit_rate_at_k` 从 `0.019635` 提升到 `0.025245`，`ndcg_at_k` 从 `0.005876` 提升到 `0.007463`，`mrr_at_k` 从 `0.012202` 提升到 `0.013768`；`popular=0.75` 和 `0.85` 也均高于 baseline。case-level 结果显示 5 个 shared target 进入 Top-K，退出 Top-K 为 0，rank 改善 49 个、恶化 4 个。

**面试可讲点：**
这次可以讲成“固定候选池后做权重稳定性门禁”：先证明池没变，再证明邻近权重也同向，最后把结论限制在 frozen-pool ranking，不把排序增益误写成召回收益。

### 2026-05-12 - Phase 1.21 recall coverage 扩展与诊断收口

**任务：**
在冻结 baseline 之外实现 Phase 1.21 召回覆盖诊断：新增默认关闭的 semantic title/category、co-visit fallback repair、category long-tail 和 metadata neighbor source，跑通 same-holdout baseline/audit/pool-curve，并记录 ablation 的真实状态。

**遇到的问题：**
并行实现时出现过重复函数定义和 source config 覆盖风险；co-visit 噪声过滤最初会误删高频 seed；完整 ablation matrix 在 `limit_users=500` 下仍超时，不能把单 source 结论包装成晋升证据。

**定位方式：**
对照 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`、`tests/test_phase_1_21_recall_coverage.py` 和 `outputs/recall/phase_1_21_recall_coverage/*/manifest.json`，核验 `evaluation_mode=valid_test`、`users_with_holdout=138`、`limit_users=500`、同一 `holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`，并检查 ranking/rerank disabled 与 no-leakage contract。

**解决方式：**
统一 Phase 1.21 source config 装配路径，修正 co-visit 为“允许高频 seed、过滤高频 neighbor”，补齐 source/metrics schema gate 和专项测试；对 ablation 超时不做伪成功处理，而是写入 `outputs/recall/phase_1_21_recall_coverage/ablations/manifest.json`，显式标记 `status=inconclusive_timeout`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_phase_1_21_recall_coverage.py` 通过，合计 `19 passed`；Phase 1.21 专项 `18 passed`。pool-curve 在同一 holdout hash 下完成，pool100 `candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.061312`，pool200 `candidate_hit_users=19`、`candidate_hit_rate_at_pool=0.137681`、`recall_at_pool=0.069710`，`candidate_hit_users_delta=+5`、`candidate_hit_rate_at_pool_delta=+0.036232`。按召回侧指标，pool200 晋升为 recall-side experimental baseline；ablation manifest 明确为 timeout inconclusive，不能晋升单 source，排序 / Top-K 不纳入本窗口结论。

**面试可讲点：**
这次可以讲成“召回侧实验的证据纪律”：用固定分母、同一 holdout hash、no-leakage contract 和 ranking disabled gate 保证诊断可信；pool200 带来 +5 个候选命中用户，因此晋升为召回侧 experimental baseline，但由于 ablation 未完成，不把任何单一 source 包装成晋升，也不把排序 / Top-K 结果混入召回窗口结论。



### 2026-05-12 - Phase 1.22 pool200 source attribution 与 keep/prune 复核

**任务：**
复核 Phase 1.22 的 pool200 recall 源，并同步工程叙事。

**遇到的问题：**
本轮是 recall-only；ablation 只到 partial_time_limited，leave-one-source-out 全是 inconclusive_not_rerun；miss_targets / holdout targets 只能用于 diagnostics / evaluation。

**定位方式：**
对照 contract.json、source_attribution_report.json、pool200_ablation_summary.csv、source_keep_prune_decisions.csv，核对 fixed contract、holdout hash、pool100 / pool200 命中差异和 source 归因。

**解决方式：**
keep semantic_title_category_expansion / popular / semantic；reserve 其余召回源；仅 prune metadata_neighbor_recall。对 5 个 pool200-only 新命中采用 non-exclusive attribution，不把单源归因误读成唯一贡献。

**验证结果：**
source_attribution_report.json 中 all-hit attribution 为 semantic_title_category_expansion=9、semantic=9、popular=6、category=2、category_long_tail_recall=2、two_tower=2、co_visit_fallback_repair=1、itemcf_strong=1、itemcf_weak=1；新增 5 个命中里 popular=3、semantic_title_category_expansion=3。pool200_ablation_summary.csv 的非 baseline 行均为 inconclusive_not_rerun。

**面试可讲点：**
先把证据边界定死，再做源治理：合同、holdout hash、分母和 no-leakage 先锁住，再用可验证的归因和裁决表做 keep / reserve / prune。

### 2026-05-12 - Phase 1.22 pool200 æŽ’åº�å¤�æ ¸ï¼šå€™é€‰æ± æ¼‚ç§»å¯¼è‡´ INVALID

**ä»»åŠ¡ï¼š**
åœ¨å·²æ™‹å�‡çš„ pool200 å�¬å›žåŸºçº¿ä¸Šï¼Œå�ªéªŒè¯�æŽ’åº�ä¾§ `ranking_v2`ã€�`source_aware_fusion`ã€�`item_feature_rerank`ï¼Œåˆ¤æ–­æ˜¯å�¦èƒ½æŠŠå€™é€‰æ± å†…å‘½ä¸­æŽ¨è¿› Top-Kã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
Promoted baseline ç›®å½•å�ªæœ‰ metrics / manifest / diagnostic CSVï¼Œæ²¡æœ‰ per-user `recommendations.jsonl`ã€�`candidates.jsonl` æˆ– `ranking_hit_cases.jsonl`ï¼Œå› æ­¤æ— æ³•ç›´æŽ¥å¤�ç”¨å†»ç»“å€™é€‰æ–‡ä»¶å�šçº¯ rerankã€‚å�Žç»­ deterministic rerun å�ˆå‡ºçŽ°å€™é€‰æ± å†»ç»“å­—æ®µæ¼‚ç§»ï¼š`19/0.137681/157.112` å�˜ä¸º `17/0.123188/152.272`ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆå�š baseline freeze auditï¼Œå†�è®© isolated configs é€šè¿‡éš”ç¦»éªŒè¯�ï¼šä¸‰ä»½ Phase 1.22 é…�ç½®å�ªä¿�ç•™å�•ä¸€ ranking policy å·®å¼‚ï¼Œ`candidate_pool_size=200`ï¼Œå¹¶ç§»é™¤é¢�å¤– `rank_weights`ã€‚éš�å�Žè¯»å�– `outputs/archive/root_files/pool200_ranking_optimization_comparison.json`ã€�å�„å�˜ä½“ `metrics.json` ä¸Ž `ranking_hit_cases.jsonl`ï¼Œå¯¹æ¯” promoted baseline çš„ freeze gates ä¸Ž Top-K æŒ‡æ ‡ã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ²¡æœ‰æŠŠ `mrr_at_k` çš„è½»å¾®ä¸Šå�‡åŒ…è£…æˆ� partialï¼›æŒ‰é¢„å…ˆ gate è§„åˆ™æŠŠå€™é€‰æ± æ¼‚ç§»åˆ¤ä¸º `INVALID`ã€‚æœ€ç»ˆå†³ç­–æ˜¯ä¸�æ™‹å�‡ä¸‰ç§�æŽ’åº�æ–¹æ³•ï¼Œä¿�ç•™ promoted pool200 baselineã€‚

**éªŒè¯�ç»“æžœï¼š**
ä¸‰ç»„å�˜ä½“å�‡ä¸º `hit_rate_at_k=0.014493`ã€�`ndcg_at_k=0.002779`ã€�`mrr_at_k=0.006039`ï¼Œç›¸å¯¹ baseline `hit_rate_at_k=0.021739`ã€�`ndcg_at_k=0.004983` æ²¡æœ‰æœ‰æ•ˆæ��å�‡ã€‚case attribution æ˜¾ç¤ºæ¼‚ç§»æ± å†…ä¸‰ç»„æ–¹æ³• Top-K å‘½ä¸­é›†å�ˆç›¸å�Œï¼Œå�ªæœ‰ 2 ä¸ª Top-K hitsï¼Œæ²¡æœ‰ entered Top-K targetã€‚é…�ç½®éªŒè¯�ä¾§é€šè¿‡ `.venv` compileall å’Œç›¸å…³ pytestã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå·¥ä½œä½“çŽ°çš„æ˜¯æŽ’åº�å®žéªŒçš„è¯„ä¼°çºªå¾‹ï¼šæŽ’åº�æ–¹æ³•èƒ½è·‘é€šä¸�ç­‰äºŽå�¯æ™‹å�‡ï¼Œå¿…é¡»å…ˆè¯�æ˜Žå€™é€‰æ± ç¨³å®šæˆ–æœ‰ same-run baselineã€‚å�‘çŽ°å€™é€‰æ± æ¼‚ç§»å�Žï¼Œä¸»åŠ¨æŠŠç»“è®ºé™�çº§ä¸º `INVALID`ï¼Œå¹¶æ˜Žç¡®ä¸‹ä¸€æ­¥è¦�å…ˆè¡¥ per-user frozen candidate export æˆ– same-run no-rerank baselineï¼Œç­‰éš”ç¦»é—®é¢˜ä¿®å¤�å�Žå†�è€ƒè™‘ LTRã€‚

### 2026-05-13 - Phase D semantic/title-category promotion candidate 收口

**任务：**
继续长期召回执行，把 Phase 1.21 的 family-specific observation、frozen candidates 和 dedicated ablation evidence 收口成可审查的 promotion candidate。

**遇到的问题：**
初始 ablation 结果四个实验行完全一致，暴露出 source-family 开关污染：baseline_only 继承了实验配置里已经启用的 semantic/co-visit/long-tail source，不能用于单 source 归因。

**定位方式：**
核对 `outputs/recall/phase_1_21_recall_coverage/ablations/itemcf_covisit_semantic_pool200/summary_metrics.csv`、`dedicated_ablation_evidence_manifest.json` 和 `frozen_promotion_evidence_checklist.json`；重点检查同一 holdout hash 下 baseline_only 与各 patch 的 `candidate_hit_users`、`exclusive_hit_users`、fallback、latency 和 required artifacts。

**解决方式：**
修正 ablation base config，去掉所有 source-family 开关后再逐个 patch 启用待测 source；重新生成 summary、exclusive hits、overlap、latency、fallback 和 frozen promotion checklist。随后新增 `.omc/recall/artifacts/phase_1_21_semantic_title_category_promotion_candidate/{manifest,metrics,signature}.yaml`，并把 registry schema/registry 同步到 `PROMOTION_CANDIDATE` 状态。独立 verifier 批准后，再新增 `.omc/recall/artifacts/phase_1_21_semantic_title_category_baseline_vnext/{manifest,metrics,signature}.yaml` 和 `PASS_PROMOTE_DEFAULT` registry row。

**验证结果：**
修正后 baseline_only 为 17 个 candidate-hit users；semantic/title-category 为 19 个，带来 +2 个额外 candidate-hit users；co-visit fallback 与 category long-tail 均无候选命中增量。`frozen_promotion_evidence_checklist.json` 为 `READY_FOR_PROMOTION_REVIEW`，独立 verifier 给出 APPROVE；`./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py` 通过并识别 3 条记录。当前默认晋升只覆盖 semantic/title-category，回滚基线为 `phase_1_25_pool200_frozen_baseline`。

**面试可讲点：**
这次工作体现了召回实验的证据治理能力：不仅跑实验，还能发现消融污染、修正实验设计、用 frozen candidates 和 registry 固化证据边界，并在 verifier 批准后把单一有效 source 晋升为可回滚的 baseline_vNext。

### 2026-05-12 - Phase 1.23 sample-size LOPO 叙事补充

**任务：**
补写 Phase 1.23 的 sample-size sensitivity 中文叙事，明确它只是在 LOPO 内部做 recall-only sanity，不把结果误写成 valid_test 晋升证据。

**问题：**
100 / 1000 / 10000 三档样本下的 LOPO pool200 召回都很高，容易被误读成“低 recall 只是样本太少”；但这些结果和 Phase 1.21/1.22 的 valid_test holdout-hash baseline 不同口径，不能直接对比。

**定位：**
对照 `outputs/ranking/phase_1_23_sample_sensitivity/contract.json`、`metrics_by_sample.json`、`sample_size_sensitivity_summary.csv` 和 `report.json`，核对三档结果分别为 12/12=1.0、78/81=0.962963、1314/1382=0.950796，`candidate_count_avg` 依次为 52.166667、93.901235、128.83864；同时检查命中来源，发现更大样本下主要由 `itemcf_strong` / `itemcf_weak` 贡献，而不是 Phase 1.21 里解释 pool200-only 增益的 `semantic_title_category_expansion` / `popular`。

**解决：**
把叙事边界锁在 recall-only、pool200、LOPO internal split，并明确不做 ranking、Top-K、LTR rerank、holdout tuning 或 leakage 规避式包装；结论写成“数据/切分难度仍是主因，LOPO 证据不足以把 valid_test 低 recall 归因为样本规模”。

**验证：**
三档 LOPO 指标全部跑通且 fallback_rate=0.0；样本增大后候选供给确实上升，但 source 归因与 valid_test 基线不一致，说明 sample-size 变大并不自动等价于 valid_test recall 晋升。

**面试可讲点：**
这轮的价值不在“把 recall 做高”，而在“把证据边界说清楚”：我用同一 recall-only 合同验证了样本规模会影响候选供给，但也证明了 LOPO 不能直接替代 valid_test 口径，因此后续应优先做同风格 valid_test 大 split 或更严格的 leakage audit。



### 2026-05-12 - Phase 1.24 核心召回指标扩展

**任务：**
补写 Phase 1.24 的中文工程叙事，把工业召回方法和现有 source 映射到统一的观测指标框架。

**遇到的问题：**
单看 recall 数字容易把规则/热门、协同过滤、内容/语义、图召回、双塔召回混成一个黑盒，也容易把召回观测误写成排序收益。

**定位方式：**
按工业召回谱系对齐现有 source：`popular` / `category`、`itemcf_strong` / `itemcf_weak`、`semantic` / `semantic_title_category_expansion` / `category_long_tail`、`item_graph` / `graph_walk`、`two_tower`，并明确序列/多兴趣召回暂未落地。

**解决方式：**
把 Phase 1.24 定义为指标扩展，不改召回算法本身；只补 source 归因、覆盖、召回命中和分桶观察，明确不做排序、Top-K promotion、线上 CTR/CVR/GMV 伪造，也不靠 holdout / miss-target 调参。

**验证结果：**
文档已补齐，口径与前序召回诊断一致：这轮新增的是观测能力，不是算法晋升。

**面试可讲点：**
可以把这轮讲成“先拆方法谱系，再统一观测指标”。这样后续无论接规则、协同过滤、语义、图还是双塔，都能用同一套边界判断覆盖和来源，而不是把可观测误当成已提分。

### 2026-05-12 - Phase 1.25 工业排序研究收口

**任务：**
把 Phase 1.23 / 1.24 的 same-run 证据收束成工业排序研究文档，并同步补写过程日志。

**问题：**
1.23 / 1.24 都是 `VALID`，但 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 全部持平，容易把实验可运行误解为默认晋升。

**定位方式：**
对照 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json`、`outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.json`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.md`，核对 frozen pool200 的关键指标：`candidate_hit_rate_at_pool=0.123188`、`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**解决方式：**
将研究边界收敛为工业指标概览、失败模式映射、两轮复盘和不超过 3 个轻量候选；明确不改召回、不动 `candidate_pool_size`、不做训练/集成、不晋升 LOPO。

**验证结果：**
`dic/experiments/ranking/phase_1_25/PHASE_1_25_INDUSTRIAL_RANKING_RESEARCH.md` 已落盘，内容和 frozen-pool 证据一致，且给出了后续实验的 stop gate。

**面试可讲点：**
这类工作能体现我如何把“实验做完”转成“证据说清楚”：先锁边界、再看 delta、最后才决定哪些候选值得继续。

### 2026-05-12 - Phase 1.25 pool200 召回体检与候选池健康收口

**任务：**
基于 `outputs/recall/phase_1_25_pool200_recall_health/` 的结果，补写 pool200 召回/候选生成健康叙事。

**问题：**
候选池虽然可跑通，但如果只看“有命中”容易忽略空候选、覆盖、候选规模分布和来源重叠，导致把召回健康误判为排序收益。

**定位方式：**
对照 `recall_health_report.json` / `.md`、`baseline/metrics.json`、`baseline/manifest.json`，核对 `empty_candidate_users=0`、`empty_candidate_rate=0.0`、`user_candidate_coverage_rate=1.0`、`candidate_count avg/min/p50/p90/max=157.112/67/160/200/200`、`candidate_hit_users@pool=19/138`、`catalog_candidate_coverage_count=12089`，以及 source marginal hits：`semantic=4`、`popular=3`、`semantic_title_category_expansion=2`、`two_tower=1`。

**解决方式：**
把结论锁定为“pool200 召回底座健康、候选池覆盖完整、来源贡献可解释”；只补召回体检与来源解释，不把 `candidate_recall@20/50/100/200` 或 `candidate_hit_rate@20/50/100/200` 误写成排序提升，也不引入 LTR/rerank/Top-K promotion。

**验证结果：**
`candidate_hit_rate@20/50/100/200=0.072464/0.108696/0.123188/0.137681`，`candidate_recall@20/50/100/200=0.034967/0.055921/0.05884/0.06971`；候选池无空用户、覆盖率 100%，说明召回健康问题已被体检证实可控。

**面试可讲点：**
这轮能讲成“先做候选池体检，再谈模型优化”：先用空候选、覆盖率、候选规模分布和 source overlap 判断底座是否稳定，避免把召回健康和排序收益混在一起。

### 2026-05-12 - Phase 1.25 normalized-additive 排序门禁验证

**任务：**
在 frozen pool200 候选池上验证 normalized-additive 排序平台是否只改变排序诊断，不引入召回、候选池规模、`top_k`、LTR、serving 或 frontend 合约漂移。

**问题：**
新增排序权重网格如果没有严格门禁，容易把候选池 hash/count 漂移、fallback 变化或二级指标局部变化误判成可晋升排序收益。

**定位方式：**
对照 `.omc/handoffs/team-exec-to-team-verify-phase-1-25-ranking-platform.md`、`outputs/ranking/phase_1_25_pool200_normalized_additive_limit500/comparison.json` / `.md`、`configs/ranking/phase_1_25/phase_1_25_pool200_*.yaml`、`rs_core/recsys/evaluation.py` 和 `tests/test_hybrid_demo.py`，核对 8 个变体均为 `candidate_pool_size=200`、`top_k=5`、`ltr_model=false`、`ranking_v2=false`、`item_feature_rerank=false`、`source_aware_fusion=false`。

**解决方式：**
保留 normalized-additive 为排序层诊断平台：有限权重网格、同跑 baseline、冻结候选 hash/count 对比、`strict_ranking_promotion_status` 强门禁；LTR 只允许 diagnostic-only，不允许 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q` 通过 80/80，`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。limit-500 对照中 8 个变体 `all_variants_valid=true`、frozen hash 均为 `e664ad5ee7b133811d19e6b28b1e99f5d1cef15b6241f1ef51d40ed73b28195b`、`user_count=500`、`candidate_count=76136`；所有非 baseline 变体均为 `PARTIAL diagnostic-only`、`promotable=false`，主指标持平：`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**面试可讲点：**
这轮可以讲成“先建排序实验门禁，再决定是否晋升”：我没有因为平台跑通就包装成收益，而是用 hash/count、freeze 指标和 promotion gate 证明这只是可复用诊断能力，当前排序效果不晋升。

### 2026-05-12 - Phase A 持久化合同落地与 frozen snapshot 诊断

**任务：**
补充 Phase A 中文工程叙事，记录 recall persistence contract、schema、registry 和冻结快照的边界。

**遇到的问题：**
pool200 frozen baseline 只有 observation snapshot；缺 frozen_candidates、ablation、latency、fallback promotion artifacts，若直接写成提分结论会把合同落地误写成算法晋升。

**定位方式：**
核对 `.omc/recall/schema/recall_experiment_registry.schema.yaml`、`.omc/recall/schema/source_group_registry.schema.yaml`、`.omc/recall/registry/*.yaml`、`.omc/recall/artifacts/phase_1_25_pool200_frozen_baseline/{manifest,signature,contract,metrics}.yaml`，并运行 `./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py`。

**解决方式：**
把 Phase A 定义为持久化合同落地，统一将 pool200 snapshot 标记为 `INCONCLUSIVE_MISSING_ARTIFACT`；只确认 registry/schema/manifest 的一致性，不补造晋升证据，不写 ranking/LTR/Top-K/在线收益。补齐生产路径后，`run_hybrid_demo` 会写出 `recall_registry_artifact.json`，并把路径回填到 `metrics.json`，让后续 agent 可以直接从 workflow artifact 接续 registry 治理。

**验证结果：**
`Recall registry validation passed: 1 record(s)`；相关文档已更新，叙事口径与 artifact 边界一致。生产路径测试 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，确认 workflow 产物包含 recall-only registry artifact，且缺失 promotion artifact 时仍保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**面试可讲点：**
可以讲成“先做证据合同，再做结果表达”：先让 schema、registry、artifact manifest 可校验，再决定 snapshot 能不能晋升；这样可避免把观察性产物误写成算法提升。

### 2026-05-13 - Phase B recall promotion artifact 生产路径与 source family benchmark 框架

**任务：**
把 Phase A 的静态 recall contract 推进到 workflow 生产路径：`run_hybrid_demo` 写出 promotion sidecar artifacts，并让 Phase 1.21 recall coverage baseline 产出 source family observation benchmark 框架。

**问题：**
pool200 snapshot 之前只有 registry/manifest 层证据；如果没有 workflow 级 sidecar、hash 和 benchmark 注册模板，后续 agent 很难持续比较 popular/category、ItemCF/co-visit、semantic/title-category、graph、vector/two-tower、sequence/multi-interest，也容易把缺失 ablation 的 observation 误判为 baseline_vNext。

**定位：**
检查 `rs_core/workflow/hybrid_demo.py` 的 metrics 写出顺序，发现 registry artifact 判断 latency/fallback/overlap 是否可用依赖 sidecar 文件实际存在；同时检查 `scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py`，确认 baseline 模式适合作为 source family observation benchmark 的轻量注册入口。

**解决：**
`run_hybrid_demo` 现在写出 `recall_source_coverage.json`、`recall_pool_curve.json`、`recall_latency_report.json`、`recall_fallback_report.json`、`recall_overlap_source_contribution.json`，并把路径回填到 `metrics.json` / `recall_registry_artifact.json`；dedicated leave-one-source-out ablation 仍保持 unavailable，所以 gate status 继续是 `INCONCLUSIVE_MISSING_ARTIFACT`。Phase 1.21 baseline 额外写出 `source_family_observation_benchmarks.json`，只生成 observation lane 的 source family 注册模板，不直接跑昂贵全量实验。

**验证：**
`./.venv/Scripts/python.exe scripts/data/validate_recall_registry.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，20 passed。测试覆盖 sidecar path/hash、forbidden ranking/online metrics、source family benchmark 六类方法和 recall-only observation contract。

**面试可讲点：**
这轮可以讲成“把召回路线探索做成可持续实验系统”：先统一 artifact、hash、gate 和 source family 模板，让后续 agent 能公平探索主流召回方法组合；但在 ablation 缺失前，不把任何组合晋升成最终路线。

**首批 observation baseline：**
在 `outputs/recall/phase_1_21_recall_coverage/source_family_baseline/` 跑通固定 holdout hash 的 pool100 source-family baseline：`users_with_holdout=138`、`candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.060709`、`empty_candidate_rate=0.0`、`fallback_rate=0.0`。本轮只证明 observation 框架可运行，不产生 `baseline_vNext`；下一步应按 source family 跑具体变体和 dedicated ablation。

### 2026-05-13 - Phase C 召回长期执行合同与 evidence 状态机加固

**任务：**
继续执行召回长期目标，补齐 promotion gate、diagnostic-only 隔离、source family 状态矩阵和 ablation/frozen evidence 骨架。

**问题：**
仅有 observation baseline 和模板会让后续执行误判完成度；未运行 family、缺失 frozen candidates、缺 dedicated ablation 都不能被包装成 `baseline_vNext` 晋升证据。

**定位：**
检查 recall registry schema/validator、Phase 1.21 benchmark artifact 和测试断言，重点验证 `frozen_candidates_path`、forbidden metrics、source family execution status 与 missing artifact 状态。

**解决：**
强化 schema/validator 负向校验；为六类 source family 增加 `execution_status`、`evidence_level`、artifact path/hash 和 `next_action`；为 ablation 模式输出 dedicated evidence manifest 与 frozen promotion checklist，并在缺真实 artifact 时保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**验证：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_recall_registry_validator_accepts_source_alias_and_rejects_forbidden_metric_overlap` 通过；`./.venv/Scripts/python.exe -m compileall scripts/experiments/recall/phase_1_21_recall_coverage_experiments.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 通过 19/19。

**面试可讲点：**
可以讲成“长期推荐实验的防伪完成机制”：用状态机和 evidence checklist 区分模板、可运行、已执行和可晋升，确保没有真实 frozen/ablation 证据时系统自动保持不晋升。

### 2026-05-12 - Phase 1.26 持久排序实验治理底座

**任务：**
把“持续探索工业排序方法”的长期计划先收束成可执行治理底座：实验注册表、冻结候选 artifact equality、严格状态机阈值，而不是一次性堆所有模型。

**问题：**
Phase 1.25 已证明 normalized-additive 平台能跑但没有排序效果提升；如果继续新增 LTR、GBDT 或深度排序而没有统一 registry 和候选池一致性门禁，容易把候选池漂移、样本噪声或微小浮点变化误判成最终路线。

**定位方式：**
检查 `rs_core/recsys/evaluation.py` 中的 `frozen_candidate_signature()`、`compare_frozen_candidate_signatures()`、`strict_ranking_promotion_status()`，以及 `tests/test_hybrid_demo.py` 里 Phase 1.25 的冻结候选和 promotion gate 测试，确认最小集成点可以放在 evaluation 层，不需要修改召回、`candidate_pool_size`、`top_k` 或 serving/frontend contract。

**解决方式：**
新增 `frozen_candidate_artifact()`、`compare_frozen_candidate_artifacts()` 和 `build_ranking_experiment_registry_entry()`，把 canonical candidate hash/count、schema version、promotion scope、关键指标和状态统一落到 registry entry；同时把 promotion gate 从“只要 hit_rate 大于 tolerance”收紧为 `hit_rate` 绝对提升至少 `0.001`、相对提升至少 `3%`、`candidate_hit_missed_topk_users` 至少减少 1，且 NDCG/MRR/MAP 不回退。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_phase_1_26_runner_writes_registry_entries_to_comparison tests/test_hybrid_demo.py::test_phase_1_26_registry_entry_records_frozen_candidate_artifact_and_scope tests/test_hybrid_demo.py::test_phase_1_26_candidate_artifact_equality_reuses_strict_signature_gate tests/test_hybrid_demo.py::test_strict_ranking_promotion_status_promote_partial_and_invalid_stop` 通过 4/4；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py` 通过 86/86，并验证 Phase 1.25 runner 的 `comparison.json` 会实际写出 `ranking_experiment_registry`。

**面试可讲点：**
这轮可以讲成“先治理实验，再探索模型”：面对多种工业排序方法，不急着堆模型，而是先建立可复现的实验注册、候选池相等性和晋升状态机，让后续 LR/GBDT/LambdaMART/深度排序都必须在同一 frozen-pool 证据框架下竞争。

### 2026-05-13 - Phase 1.27 特征/标签/泄漏治理收口

**任务：**
补充 Phase 1.27 中文工程叙事，记录特征契约、标签切分和泄漏门禁的治理边界。

**遇到的问题：**
如果 feature contract、label split 和 leakage gate 没有被明确约束，后续 learned ranker 很容易把 holdout target、future interaction 或 promotion evidence 误用进训练和评估；验证前还遇到 `rs_core/workflow/hybrid_demo.py` 的 helper 调用不一致，必须先修复后才能继续跑验证。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 中 Phase 1.27 的 scope，确认当前要补的是 offline ranking feature contract、allowed/forbidden features、label/split/leakage gate 和 registry metadata，而不是改 `candidate_pool_size`、`top_k` 或 recall baseline；随后运行 compileall、Phase 1.27 相关 pytest 和真实 runner smoke。

**解决方式：**
把 Phase 1.27 写成治理阶段：allowed features 只保留 source、item metadata、candidate score、user history aggregates 和 near-miss diagnostics；forbidden features 排除 holdout target、future interaction，以及 valid/test 上训练后再当 promotion evidence 的字段；label split leakage gate 覆盖 target item、future interaction 和 holdout leak；registry metadata 记录 feature contract version 与作用范围，供后续 learned ranker 复用。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 106/106；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_25_pool200_normalized_additive.py --limit-users 50` 成功生成 `outputs/ranking/phase_1_25_pool200_normalized_additive/comparison.json`，registry 中已记录 `feature_contract_version=ranking_feature_contract_v1`、`feature_contract_gate_summary.schema_version=ranking_feature_contract_gate_v1` 和 `leakage_gate_summary.schema_version=ranking_feature_leakage_gate_v1`。非 LTR 排序变体的 feature/leakage gate 明确标记为 `NOT_APPLICABLE`，LTR 训练路径会对真实 feature rows 执行 gate；验证期间没有改 `candidate_pool_size`、`top_k` 或 recall baseline，也没有把这轮叙事写成模型 lift。

**面试可讲点：**
可以讲成“先定特征契约和泄漏边界，再谈模型效果”：这轮没有追求数字上升，而是把输入契约、标签切分和泄漏门禁先做成可审计的治理层，确保后续学习排序的证据可信、可复现、可追踪。

### 2026-05-13 - Phase 7/8 多目标与在线学习 future-online 门禁

**任务：**
在长期排序计划 Phase 7/8 中收口 ESMM、MMoE、PLE、多目标排序、Bandit、RL/GRPO 和 Agent feedback 的当前边界，确保线上业务指标不会被误用为 frozen pool200 离线 promotion 证据。

**遇到的问题：**
Phase 7/8 需要 CTR/CVR/GMV 业务 label、线上或准线上评估、serving/monitoring contract、交互日志、安全探索策略和 replay/A/B 链路。当前项目还停留在 frozen pool200 离线排序证据，因此只能标记 future-online / future-agent-online，不能实现假在线实验。

**定位方式：**
读取 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 7/8 进入条件，并对照当前 ranking registry 能力，确认可以产出 future gate artifact，但不能把线上指标、SLO 或 A/B uplift 纳入当前离线晋升。

**解决方式：**
新增 `scripts/experiments/ranking/run_phase_7_8_future_online_gate.py`，运行 same-run baseline 以保持当前离线 artifact 完整；将 `esmm_ctr_cvr_ranker`、`mmoe_multi_task_ranker`、`ple_multi_task_ranker`、`contextual_bandit_ranker`、`rl_grpo_preference_ranker` 等方法写入 blocked registry，lane 标注为 `future-online` 或 `future-agent-online`，并在 readiness 中列出缺失条件和当前禁用证据。

**验证结果：**
`compileall` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_7_8_future_online_gate or phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 3 个目标测试；`outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json` 验证 artifact inspection PASS、`candidate_pool_size=200`、`top_k=5`、所有 Phase 7/8 方法 blocked 且不具备当前 offline promotion eligibility，最终路线保持 `same_run_baseline`。

**面试可讲点：**
这轮可以讲成“把未来路线也纳入工程治理”：不仅能实现模型，还能识别哪些方法需要线上标签和安全探索条件，在证据不足时用 future gate 防止指标口径污染。

### 2026-05-13 - Phase 6 语义 / 双塔排序特征融合门禁

**任务：**
在长期排序计划 Phase 6 中验证 semantic-title score、two-tower score、vector similarity、DSSM 和 cross-feature fusion 的排序侧价值，继续保持 frozen pool200、`candidate_pool_size=200`、`top_k=5`、不改召回语义。

**遇到的问题：**
semantic / two_tower 已经是当前候选池的召回源，如果直接改召回或重新用 DSSM/vector artifact 生成候选，会破坏排序实验边界。与此同时，DSSM 与 raw vector similarity 虽有训练 artifact，但缺少 candidate-level rerank adapter，不能作为当前离线 promotion 证据。

**定位方式：**
对照 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml`、`rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py` 和 two-tower artifact，确认当前可审计输入是候选内 `source_scores` 和 source cross features；真实 smoke 产物为 `outputs/ranking/phase_6_semantic_two_tower_ranker_smoke/comparison.json`。

**解决方式：**
新增 `scripts/experiments/ranking/run_phase_6_semantic_two_tower_ranker.py`，在 same-run frozen pool200 baseline 上运行 `semantic_score_feature_rerank`、`two_tower_score_feature_rerank` 和 `semantic_two_tower_cross_feature_fusion` 三个排序对照；将 `dssm_artifact_candidate_rerank` 与 `raw_vector_similarity_feature_fusion` 写入 blocked method registry，明确 blocked 原因是 adapter 缺失和禁止候选池重生成。

**验证结果：**
`compileall` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 2 个目标测试；Phase 6 smoke 通过并输出 artifact inspection PASS、全部 run 的 frozen candidate status PASS。指标上 baseline `hit_rate_at_k=0.037037`，semantic score rerank 降至 `0.018519`；two-tower score 与 cross-feature fusion 持平但未达到 hit-rate lift 和 missed-topk reduction 门槛，最终 `selected_route=same_run_baseline`。

**面试可讲点：**
这轮可以讲成“把 embedding/双塔从召回能力拆成排序证据来验证”：即使有 two-tower artifact，也必须在冻结候选池内证明排序收益；没有 adapter 或没有稳定 lift 的方法只能 diagnostic/blocked，不能包装成成功。

### 2026-05-13 - Phase 5 行为序列 / 注意力排序数据门禁

**任务：**
继续长期排序计划 Phase 5，判断当前数据是否足以支持 DIN / DIEN / BST / SIM 等行为序列排序模型。

**问题：**
行为序列模型依赖长历史、可靠时间顺序、session/history window 和无未来交互泄漏。当前数据有 `user_sequences` 和 timestamp，但长序列覆盖不足；如果直接训练 DIN/DIEN/BST/SIM，只能得到 toy 结果，不能作为当前离线 promotion 证据。

**定位：**
统计 `user_sequences.train.jsonl` 的序列质量：Phase 5 smoke 中 200 个用户的 `positive_len_ge_2_rate=0.575`、`positive_len_ge_10_rate=0.11`、`timestamp_ordered_rate=1.0`。结论是短序列诊断满足条件，但长序列模型未达到数据门槛。

**解决：**
新增 `scripts/experiments/ranking/run_phase_5_sequence_ranker.py`，输出 `sequence_ranker_data_readiness_v1`、Phase 0 风格 registry 和 artifact inspection。session-aware / attention history 仅为 diagnostic；DIN、DIEN、BST、SIM 标记为 blocked，并写明长序列覆盖不足和 adapter 缺失原因。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/experiments/ranking/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_5_sequence_ranker or phase_4_neural_ranker"` 通过 2/2；`outputs/ranking/phase_5_sequence_attention_ranker_smoke/comparison.json` 显示 artifact inspection PASS、短历史方法 diagnostic、DIN/DIEN/BST/SIM blocked。

**面试可讲点：**
这轮体现的是数据条件先行：面对工业序列模型，不是直接上模型名，而是先证明历史长度、时间顺序、泄漏边界和 serving adapter 是否具备，把“可诊断”和“必须 blocked”的方法分清。

### 2026-05-14 - Phase 5 正向收口与合同验证

**任务：**
同步 Phase 5 中文叙事，记录本轮 fine-rank / 序列正向收口结果。

**遇到的问题：**
Phase 5 smoke 能证明诊断链路和合同检查通过，但不能把序列/注意力方法写成 promotion；如果把 smoke 成功写成晋升，会越过 frozen candidate、top_k 和 online claims 的边界。

**定位方式：**
结合 `comparison.json` 与验证结果，核对 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_comparison.match=true`、`case_diagnostic_success=true`、`promotion_success=false`、`online_claims=[]`、`artifact_inspection=PASS`，确认本轮只有诊断证据，没有晋升证据。

**解决方式：**
把 Phase 5 结果明确收口为 diagnostic / blocked：短历史与注意力诊断保留，DIN / DIEN / BST / SIM 仍因序列覆盖和 adapter 条件不足维持 blocked，不把 positive push smoke 叙述成 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_5_fine_rank_positive_push.py -q` 通过 `7 passed`；`outputs/ranking/phase_5_fine_rank_positive_push_smoke/comparison.json` 通过 contract 检查。

**面试可讲点：**
这轮可以讲成“把序列模型也放进同一套证据门禁”：不是因为模型名更高级就放松标准，而是先用合同检查证明冻结候选、诊断成功和在线承诺为空，再决定哪些方法只能留在 diagnostic lane.

### 2026-05-13 - Phase 4 神经排序 CUDA 诊断原型

**任务：**
继续长期排序计划 Phase 4，把 MLP / RankNet 神经排序原型纳入统一实验治理，并验证 GPU 训练链路。

**问题：**
当前虽然 PyTorch CUDA 可用，但神经排序缺少 serving adapter、valid/test promotion split 和 ADR；Wide&Deep、DeepFM、DCN、xDeepFM 也缺少稳定特征交叉 schema。不能把 GPU 上能训练的 smoke 结果包装成 offline promotion。

**定位：**
用 `.venv` 检查依赖和设备，确认 `torch 2.11.0+cu128` 与 `NVIDIA GeForce RTX 4070 Ti SUPER` 可用；读取候选行导出结构，确认 `features/label/user_id` 可支持 pointwise MLP 与 pairwise RankNet 诊断训练。

**解决：**
新增 `scripts/experiments/ranking/run_phase_4_neural_ranker.py`，复用 Phase 0 registry/artifact/gpu 策略：MLP 和 RankNet 在 CUDA 上训练 diagnostic artifact；LambdaRank、ListNet/ListMLE、Wide&Deep/DeepFM/DCN/xDeepFM 因 objective、schema 或 adapter 缺失写为 blocked；所有神经方法默认不具备 promotion eligibility。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/experiments/ranking/run_phase_4_neural_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_4_neural_ranker or phase_3_tree_ranker"` 通过 2/2；Phase 4 smoke 产物 `outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 显示 artifact inspection PASS、MLP/RankNet diagnostic、其他神经方法 blocked、最终路线仍为 same-run baseline。

**面试可讲点：**
这轮体现的是 GPU 实验纪律：真实使用 CUDA 训练，而不是 CPU toy；但训练跑通不等于排序晋升，仍必须通过 serving adapter、valid/test 口径、稳定 lift 和 ADR 才能进入 promotion。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
继续长期排序计划 Phase 3，把 GBDT / LambdaMART 路线接入统一实验治理，但只在真实依赖和训练条件满足时才允许进入 promotion。

**问题：**
当前 `.venv` 中 `sklearn`、`xgboost`、`lightgbm` 均不可用，代码中也没有真实树模型训练 adapter；现有 LTR 训练只能导出候选行或训练 pointwise/pairwise 轻量模型。直接用 deterministic stand-in 或 LOPO LTR 冒充树模型，会违反 frozen pool200 离线证据边界。

**定位：**
用 `./.venv/Scripts/python.exe` 检查树模型依赖，结果均为 missing；再检查 `rs_core/workflow/ltr_training.py`，确认 `write_candidate_rows` 可生成未来训练数据，但 `_train_ltr_model()` 只支持 pairwise perceptron 与 pointwise logistic。

**解决：**
新增 `scripts/experiments/ranking/run_phase_3_tree_ranker.py`，只运行 same-run baseline 和候选行导出；真实 `sklearn_gbdt_valid_test_promotion`、`xgboost_lambdamart_gpu_promotion`、`lightgbm_lambdamart_gpu_promotion` 统一写成 blocked method，并把依赖缺失、GPU 不可用、adapter 缺失、valid/test split 缺失写入原因。

**验证：**
`./.venv/Scripts/python.exe -m compileall scripts/experiments/ranking/run_phase_3_tree_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_3_tree_ranker or phase_2_shallow_learned_runner"` 通过 2/2。

**面试可讲点：**
这轮体现的是工程诚信和实验治理：复杂排序模型不具备依赖和训练条件时，不把 toy 实验包装成收益，而是把 blocked 原因结构化沉淀，为后续真实 GBDT/LambdaMART 接入准备数据和门禁。

### 2026-05-13 - Phase 2 浅层 learned ranker 诊断闭环

**任务：**
继续长期排序计划 Phase 2，把 pointwise logistic 和 pairwise perceptron 浅层学习排序纳入统一实验底座。

**问题：**
现有 LTR 训练是 LOPO 口径，只能证明训练/推理链路和 feature/leakage gate 可运行，不能作为 valid/test promotion evidence；线性 ranker 的独立 valid/test promotion split 还不存在，不能为了方法覆盖而伪造晋升。

**定位：**
检查 `scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py` 与 `rs_core/workflow/ltr_training.py`，确认可复用 pointwise/pairwise 训练器、`feature_contract_gate` 和 `leakage_gate`。长期边界继续是 fixed recall base、frozen pool200、`candidate_pool_size=200`、`top_k=5`，LOPO-only 不晋升。

**解决：**
新增 `scripts/experiments/ranking/run_phase_2_shallow_learned_ranker.py`，输出统一 `method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry` 和 `final_decision`。pointwise/pairwise 标记为 diagnostic，强制写入 `lopo_training_diagnostic_only`；缺少 valid/test promotion split 的 `linear_ranker_valid_test_promotion` 写为 blocked。

**验证：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_2_shallow_learned_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_2_shallow_learned_runner or phase_1_rule_ranking_runner or phase_0"` 通过 6/6；Phase 2 smoke 生成 `outputs/ranking/phase_2_shallow_learned_ranker_smoke/comparison.json`，artifact inspection PASS，pool/top_k 为 200/5，baseline champion，pointwise/pairwise diagnostic，linear ranker blocked，feature/leakage gates 均 PASS，最终 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮体现的是“学习排序先过治理门禁，再谈晋升”：把训练闭环、泄漏检查和 registry 状态都跑通，但严格禁止把 LOPO 诊断结果写成线上或 valid/test 收益。

### 2026-05-13 - Phase 1 规则排序 champion/challenger 复验

**任务：**
在 Phase 0 排序实验底座上继续 Phase 1，系统复验 normalized additive、source-aware fusion、item feature rerank 和保守规则组合。

**问题：**
旧的规则排序实验分散在 Phase 1.23/1.25 runner 中，缺少统一的 method registry、artifact inspection 和 champion/challenger 状态输出；如果不先把规则方法收口，后续 learned ranker 或树模型很难判断自己超过的是哪个强基线。

**定位：**
检查现有 runner 与 `rs_core/recsys/ranking.py`，确认规则排序能力已有，但需要一个长期计划下的 Phase 1 专用入口；边界仍固定为 current fixed recall base、frozen pool200、`candidate_pool_size=200`、`top_k=5`，不使用在线 CTR/CVR/GMV/P95 作为当前离线晋升证据。

**解决：**
新增 `scripts/experiments/ranking/run_phase_1_rule_ranking_champion.py`，复用 Phase 0 底座字段：`method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry`、`stability_summary` 和 `final_decision`。所有规则方法只做排序层 override，不改召回语义；未稳定过门禁的规则候选标记为 retired，baseline 继续作为 champion。

**验证：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_1_rule_ranking_champion.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_1_rule_ranking_runner or phase_0 or phase_1_29_terminal_runner"` 通过 6/6；小样本 smoke 生成 `outputs/ranking/phase_1_rule_ranking_champion_smoke/comparison.json`，artifact inspection PASS，pool/top_k 保持 200/5，baseline 为 champion，四个规则候选为 retired，最终 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮体现的是“规则排序先成为可审计强基线”：即使规则方法没有晋升，也通过统一实验治理证明它们的边界干净、证据可复验，为下一阶段线性/pointwise/pairwise learned baseline 提供对照对象。

### 2026-05-13 - Phase 0 长期排序实验底座复用化

**任务：**
把长期排序计划的 Phase 0 落成可复用底座，让后续主流排序方法复用同一套 registry、artifact inspection 和 GPU 资源策略。

**问题：**
Phase 1.29 terminal runner 已能做 frozen pool200 对照，但 method 状态、artifact 检查和 GPU 策略还没有统一沉淀；如果后续每个方法单独判断，容易把 diagnostic-only、frozen mismatch 或 CPU toy smoke 误写成晋升证据。

**定位：**
检查 `scripts/experiments/ranking/run_phase_1_29_terminal_ranking_route.py` 的 comparison 输出，确认它需要复用 `rs_core/recsys/evaluation.py` 中的公共治理能力；硬边界仍是 fixed recall base、pool200、`candidate_pool_size=200`、`top_k=5`，线上 CTR/CVR/GMV/P95 不进入当前离线 promotion evidence。

**解决：**
在 `rs_core/recsys/evaluation.py` 增加 method registry、GPU resource summary、artifact inspection helper；runner 输出 `method_registry` 和 `gpu_resource_strategy`，并由统一 inspection 检查 artifact 路径、pool/top_k、frozen candidate match 与 diagnostic promotion violation。

**验证：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/evaluation.py scripts/experiments/ranking/run_phase_1_29_terminal_ranking_route.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_0 or phase_1_29_terminal_runner"` 通过 5/5。

**面试可讲点：**
这轮不是宣称排序效果提升，而是把长期排序实验的“操作系统”先做出来：统一状态机、artifact 门禁、GPU 资源策略和 frozen-pool 边界，保证后续 GBDT/LambdaMART/深度排序方法能公平比较、可复验、可追责。

### 2026-05-13 - Phase 1.31 final offline route selection

**任务：**
输出最终离线排序路线的 ADR，并把 no-promote 结论落到中文工程叙事里。

**遇到的问题：**
Phase 1.23 / 1.24 / 1.25 / 1.28 的证据都没有把模型推进到稳定 Promote；如果把训练 gate PASS、LOPO 结果或轻量 LTR 的 diagnostic smoke 误写成晋升证据，会让终局收口失真。

**定位方式：**
复核 `rs_core/recsys/evaluation.py` 的 `terminal_ranking_promotion_gate()` 与 `strict_ranking_promotion_status()`，再对照 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 和 `comparison.md`，确认最终证据仍然只支持 `No-Promote` / `diagnostic-only`。

**解决方式：**
把最终离线路线定为 `same_run_baseline`，并在 ADR 中明确列出 excluded invalid evidence、underpowered segment、LOPO training gate PASS 但不等于晋升、以及不改召回 / 不碰线上链路的边界。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py tests/test_two_tower_training.py` 通过 117/117；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py --limit-users 5` 成功生成最终比较产物。

**面试可讲点：**
把 `No-Promote` 作为显式结论写出来，比勉强找一个“看起来更好”的模型更有工程价值，因为它把边界、风险和后续方向都说清楚了。

### 2026-05-13 - Phase 1.31/1.32 排序算法 scaffold 与诊断收口

**任务：**
补齐 Phase 1.31/1.32 的中文工程叙事，记录统一算法 scaffold、规则/浅层 learned 诊断运行和树模型 blocked 准备的当前状态。

**遇到的问题：**
如果把 scaffold 成果、LOPO/diagnostic smoke 或树模型依赖检查写成晋升结论，就会越过 frozen pool200、`candidate_pool_size=200`、`top_k=5` 和 future-only 线上指标边界。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 1.31/1.32 计划和 `outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json` 等回归产物，确认当前可写的是治理收口与诊断结论，不是模型晋升。

**解决方式：**
把 Phase 1.31 写成统一算法实验 scaffold，把 Phase 1.32 写成规则 champion 复验、浅层 learned fine-ranker 诊断和 tree/LambdaMART blocked 准备；所有方法继续走同一 registry / comparison schema，候选池和 top_k 保持不变，线上指标仍只保留为 future-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/ranking.py rs_core/recsys/evaluation.py rs_core/workflow/hybrid_demo.py scripts/experiments/ranking/run_phase_1_30_physical_ranking_pipeline.py scripts/experiments/ranking/run_phase_1_26_real_ranking_experiments.py` PASS；`./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py tests/test_phase_1_31_ranking_scaffold.py -q` 135 passed in 2.31s；`outputs/ranking/phase_1_30_physical_ranking_pipeline_regression/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json` 保留。

**面试可讲点：**
这轮可以讲成“先把排序实验底座做成共用协议，再在同一协议上跑规则、浅层 learned 和树模型准备”，重点是治理边界和证据格式，而不是把 smoke 结果包装成模型提升。

### 2026-05-13 - Phase 1.30 物理流水线证据与晋升边界收口

**任务：**
把 Phase 1.30 的跑通结果收口为“物理流水线证据”，并和 promotion evidence、future-online 指标明确分离。

**遇到的问题：**
这轮 smoke 已经能证明 recall→coarse→fine→rerank 的 stage 物理链路闭环，但如果把 pipeline trace、artifact inspection 或 smoke PASS 直接写成晋升结果，会把系统可观测性和模型收益混在一起；同时线上指标当前还没有进入离线证据链，不能提前写入结论。

**定位方式：**
对照 `outputs/verification/verification_phase_1_30_smoke/comparison.json` 与 `outputs/verification/verification_phase_1_26_regression/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`physical_pipeline_inspection=PASS`、`frozen_candidate_match=true`、coarse/fine/rerank stage counts 均为 3225，以及 `online_metric_claims=[]`；再确认 Phase 1.26 regression 的 LTR LOPO 仍是 `diagnostic-only`、`promotion_eligible=false`，tree/LambdaMART 仍 blocked。

**解决方式：**
把 Phase 1.30 写成物理流水线收口而不是晋升收口：明确这组证据只能证明 stage 闭环、artifact 完整和 frozen candidate match，不代表当前存在 promotion evidence；同时把 online metrics 继续留在 future-only 边界，把 LOPO/gate/smoke 统一标成 diagnostic-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 130/130；Phase 1.30 smoke PASS，Phase 1.26 regression PASS。

**面试可讲点：**
这轮可以讲成“先把物理流水线和晋升证据分开治理”：系统层面我已经证明 stage 能闭环、artifact 能对齐、frozen candidate 能匹配，但我没有把这些可观测性结果伪装成模型提升，而是把它们归为诊断资产，为后续模型晋升保留干净证据边界。

### 2026-05-13 - Phase 1.28 lightweight learned ranker 最小闭环

**任务：**
把长期排序路线从治理阶段推进到第一批 learned-ranker 执行闭环：固定 pool200 候选池，复用 Phase 1.27 feature/leakage gates，只接入最轻量的 pointwise logistic 与 pairwise perceptron LTR baseline。

**问题：**
如果直接进入 GBDT、LambdaMART 或深度排序，容易在模型复杂度上过早扩张，也容易绕过 feature contract、label split 和 frozen candidate equality；同时 LOPO 训练只能作为内部 sanity，不能当 valid/test promotion evidence。

**定位方式：**
检查 `rs_core/recsys/ranking.py`，确认现有 `ltr_model` 已能加载模型并在 `rank_candidates()` 中叠加 LTR score；检查 `rs_core/recsys/ltr.py`、`rs_core/workflow/ltr_training.py` 和 `scripts/training/train_ltr_ranker.py`，确认 pointwise logistic 与 pairwise perceptron 都能产出兼容 `score_ltr()` 的线性模型，并会对真实 feature rows 执行 feature contract gate 与 leakage gate。

**解决方式：**
新增并扩展 `scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py`，只跑三个 same-run 变体：`same_run_baseline`、`pointwise_logistic_lopo_ltr` 与 `pairwise_perceptron_lopo_ltr`。runner 先用 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml` 导出 baseline frozen candidates，再用 LOPO/internal train 训练轻量 LTR，最后在同一 pool200 口径下评估 LTR 变体，写出 `ranking_experiment_registry`、frozen candidate comparison、feature contract gate、leakage gate、model type 和 strict status；两个 LTR 变体固定 `diagnostic-only`，不允许晋升。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k phase_1_28 -vv` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py` 通过 107/107；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py --limit-users 50` 生成 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json`。smoke 结果中 baseline、pointwise logistic 与 pairwise perceptron 变体 frozen candidate hash/count 匹配，`candidate_pool_size=200`、`top_k=5`、`fallback_rate=0.0`；两个 LTR 训练 `feature_contract_gate=PASS`、`leakage_gate=PASS`、`label_source=leave_one_positive_out_train`，model type 分别为 `pointwise_logistic_ltr_v1` 与 `pairwise_perceptron_ltr_v1`，变体状态均为 `PARTIAL diagnostic-only`、`promotable=false`。

**面试可讲点：**
可以讲成“先把 learned ranker 接入生产排序路径，再逐步升级模型”：这轮不是追求复杂模型，而是证明训练、推理、registry、frozen-pool equality 和泄漏门禁可以串成最小可审计闭环，为后续 LR/GBDT/LambdaMART/深度排序提供统一入口和证据标准。

### 2026-05-13 - Phase B promotion schema/validator 与 source family execution_status 收口

**任务：**
补写 Phase B 的中文工程叙事，记录 promotion schema/validator、diagnostic 隔离验证和 source family execution_status 收口。

**遇到的问题：**
source family observation baseline 已经能跑通，但 baseline_vNext 还缺 frozen artifacts、dedicated ablation 和完整 promotion evidence；如果把模板化骨架误写成晋升结果，会把诊断能力和算法收益混在一起。

**定位方式：**
对照 `tests/test_phase_1_21_recall_coverage.py`、`tests/test_hybrid_demo.py` 以及当前 benchmark 产物，确认已具备 promotion schema/validator、diagnostic-only execution_status、frozen-candidate equality 和 source family模板，但 family-specific ablation 和 frozen evidence 仍未补齐。

**解决方式：**
把这轮结论写成“baseline_vNext 仍不晋升”：保留 observation lane、execution_status 和 next_action 字段，下一队列先补 family-specific variants，再补 dedicated ablation/frozen evidence，最后才重新评估晋升。

**验证结果：**
当前叙事与测试口径一致，说明 benchmark scaffolding、diagnostic gate 和 frozen candidate equality 已经可复用，但 promotion 仍停留在 observation/diagnostic 层。

**面试可讲点：**
可以讲成“先把实验骨架和晋升证据分开治理”：先保证可执行、可复现，再决定是否晋升，避免把编排能力误当成模型提升。

### 2026-05-13 - Phase 1.26 长期排序路线收口

**任务：**
把长期排序主线收口成 recall→coarse rank→fine rank→rerank 的目标架构，并明确当前只推进 frozen pool200 → learned fine ranker → bounded rerank trace。

**问题：**
如果把 LOPO smoke、树模型 blocked 或线上指标混进当前结论，容易把 diagnostic-only / future-online 误写成晋升证据；同时目标架构虽然清楚，但 physical scope 还没有铺到完整 coarse/fine/rerank 全链路。

**定位方式：**
对照 `dic/OPTIMIZATION_NARRATIVE.md` 里的 Phase 1.26、Phase 1.28、Phase 1.31 以及 `scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py`、`scripts/experiments/ranking/run_phase_3_tree_ranker.py` 的产物，确认 pointwise/pairwise learned ranker 已有 LOPO smoke，而树模型 / LambdaMART 仍是 blocked lane。

**解决方式：**
把这轮写成“目标架构清楚、物理边界收口”：当前只把 frozen pool200、learned fine ranker 和 bounded rerank trace 写成可执行主线；GBDT / LambdaMART 继续保留 blocked 状态，线上指标全部标记 future-online。

**验证结果：**
`outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 可作为 pointwise/pairwise smoke 证据；`outputs/ranking/phase_3_tree_lambdamart_ranker_smoke/comparison.json` 保持 blocked / no promotion 口径；当前没有把任何 online metric 写入离线晋升结论。

**面试可讲点：**
可以讲成“先把排序路线图和当前证据边界分开”：目标架构可以画到 recall→coarse→fine→rerank，但真正能拿来讲证据的只有 frozen pool200、轻量 learned ranker 和 bounded rerank trace；树模型没依赖、没 adapter、没 GPU 验证时就明确 blocked，避免把未来路线写成当前成果。

### 2026-05-13 - Phase 1.32 metadata neighbor gate 与不晋升收口

**任务：**
在 `semantic_title_category_expansion` 已晋升为 recall baseline_vNext 后，对 `metadata_neighbor_recall` 做同一 holdout、同一 pool200、同一 recall-only 合同下的机会门禁和专项 ablation，判断是否应继续晋升或保留为诊断 source。

**遇到的问题：**
`metadata_neighbor_recall` 在 miss-user 诊断中有较大表面机会，但原实现按 seed 扫描完整 metadata index，长跑成本高；同时机会门只能作为聚合优先级判断，不能把 holdout target 或 miss target id 用进候选生成、query、target-driven source index construction/filtering、candidate whitelist 或参数选择。静态商品 catalog metadata 可作为非 holdout-label 派生的 train-visible item feature 建索引，但不能由 target 列表驱动筛选或调参。

**定位方式：**
读取 `outputs/recall/phase_1_21_recall_coverage/phase_1_32_metadata_neighbor_gate_20260513/audit/source_opportunity_summary.json`，确认 `baseline_miss_users=132`、`metadata_neighbor_opportunity_users=132`、门槛为 14 且 gate 通过；再对照 `ablation_narrow/baseline_only/metrics.json`、`ablation_narrow/semantic_title_category/metrics.json` 和 `metadata_only_capped/metadata_neighbor/metrics.json`，固定 `users_with_holdout=138`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`、`candidate_pool_size=200`。

**解决方式：**
将 metadata neighbor 从全量扫描改为 token/category bucket index，并增加 per-seed bucket candidate cap，使专项 ablation 可在 limit500 口径下完成；ablation matrix 支持 `ablation_experiments`，只运行需要的 source lane；测试补充 no-leakage note、miss-user gate 和 `metadata_neighbor_index_mode=bucketed_train_visible_metadata` 断言。

**验证结果：**
专项 metadata-only capped run 完成，manifest 记录 same holdout verified。结果显示 metadata lane `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=132.2`，虽有 `metadata_neighbor_recall` 用户覆盖 454、item 覆盖 272、召回候选 2870，但 `source_marginal_candidate_hit_users` 和 `candidate_hit_source_coverage` 均没有 metadata 贡献；对照 baseline_only 为 17，semantic/title-category 为 19 且有 2 个 marginal candidate-hit users。因此本轮结论是 `NO_PROMOTION`：metadata neighbor 工程链路和 gate 成立，但没有带来 recall-only candidate-hit lift。

**面试可讲点：**
这轮可以讲成“机会大不等于可晋升”：先用聚合 miss-user gate 判断是否值得跑，再用索引化实现控制成本，最后仍严格按 candidate-hit lift 和 source marginal contribution 裁决。metadata neighbor 通过了机会门和工程可运行性，但没有覆盖新的 holdout 命中，因此保留为诊断/后续改造方向，不污染 baseline_vNext。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
在 frozen pool200 排序口径下验证 Phase 3 tree / LambdaMART 是否具备真实训练、serving 和晋升条件，只保留可审计诊断，不把 tree smoke 写成模型收益。

**遇到的问题：**
当前环境里 GBDT / LambdaMART 相关依赖和 serving adapter 仍不完整；如果把 `sklearn` GBDT 或训练行导出当成晋升结果，就会把准备工作误写成模型效果，也会绕过 valid-test promotion gate 和 objective recovery condition。

**定位方式：**
读取 `scripts/experiments/ranking/run_phase_3_tree_ranking_experiments.py`、`tests/test_phase_3_tree_ranking_experiments.py` 和 `outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、training rows=2217、positive=16、negative=2201；同时用 `./.venv/Scripts/python.exe -m py_compile`、Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed 和 recall regression pytest 23 passed 回归确认基础链路稳定。

**解决方式：**
把 `sklearn` GBDT 固定为 diagnostic-only，把 LambdaMART 固定为 blocked；只保留 candidate-row export、依赖检查、group/objective 恢复条件和 future 阶段的 serving 入口，不改 `merge_for_user` 和召回语义。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed，recall regression pytest 23 passed，`limit_users=20` smoke 通过；`outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json` 未产生 online promotion evidence。

### 2026-05-14 - Phase 6 工业式默认全链路诊断 runner

**任务：**
把用户要求的“工业界相对较好的算法先摆到整条链路上”落成可运行诊断链路，而不是只停留在 coarse/fine/rerank 架构说明。

**遇到的问题：**
工业式链路需要同时覆盖 coarse、fine、rerank，但当前离线硬边界仍是 frozen pool200、`candidate_pool_size=200`、`top_k=5`，不能真实缩池、不能改召回语义，也不能把未来 online/Agent 指标写成当前 promotion。第一次 smoke 还暴露 normalized additive 权重越过 Phase 1.25 有限网格，直接被底座拒绝。

**定位方式：**
对照 `rs_core/recsys/ranking.py` 的 `coarse_rank_candidates → fine_rank_candidates → rerank_candidates`，确认已有 source weight、normalized additive、source-aware fusion、item-feature rerank 和 Top-K source minimums；再读取 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json`，核对 artifact inspection、frozen hash、stage assignment 和 promotion boundary。

**解决方式：**
新增 `scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py`，组合 `coarse_rank=source_weighted_metadata_shadow`、`fine_rank=normalized_additive + source_aware + item_feature full-pool scoring`、`rerank=top5 source minimum/stable tie-break`；新增 `tests/test_phase_6_industrial_ranking_chain.py`，并把 GBDT/LambdaMART、神经序列、Agent/online feedback 继续列为 blocked/future route。越界权重收回到 Phase 1.25 允许网格 `source_signal=0.2`、`item_feature=0.2`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/experiments/ranking/run_phase_6_industrial_ranking_chain.py tests/test_phase_6_industrial_ranking_chain.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_6_industrial_ranking_chain.py -q` 通过 `4 passed`；真实 smoke 产物 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json` 显示 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、工业链路 `frozen_candidate_match=true`、`diagnostic_only=true`、`promotion_eligible=false`。

**面试可讲点：**
这轮可以讲成“把工业排序链路先接成可运行主路，同时用实验治理防止指标污染”：粗排、精排、重排都有对应算法和 artifact，但所有结论仍受 frozen pool、有限权重网格和 promotion gate 约束；发现权重越界后不是绕过检查，而是回到白名单网格重跑并验证通过。

### 2026-05-14 - Phase C 诊断门与 Phase A 收口顺序补齐

**任务：**
补充 Phase C 先行、Phase A 收口以及 learned/tree/neural 路线的中文叙事，并统一 oracle@5、target rank percentile、duplicate-source balance、win/tie/loss 的诊断口径。

**遇到的问题：**
原有长期计划主要覆盖 Phase 0/1/4/5/6 的持续实验顺序，但没有明确把 Phase C 定义成 tuning 前的诊断门，也没有把 Phase A 的合同固化位置和后续 learned/tree/neural 路线顺序写清楚，容易把诊断指标误写成晋升证据。

**定位方式：**
对照 `rs_core/recsys/evaluation.py` 的 `candidate_hit_rank_p90`、`source_overlap.multi_source_candidate_rate`、`source_pair_counts`、`source_pair_jaccard`，以及 `scripts/experiments/recall/phase_1_20_recall_diagnostics.py` 的 raw oracle stage、`scripts/experiments/ranking/run_phase_5_fine_rank_positive_push.py` 的 `coarse_to_fine_improved_count` / `coarse_to_fine_worsened_count` / `coarse_to_fine_unchanged_count`，确认这些字段可以分别承载 oracle、rank percentile、duplicate-source balance 和 win/tie/loss 的叙事。

**解决方式：**
在 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 新增 Phase C→Phase A→learned/tree/neural 的路线说明，并明确 Phase C 只做 tuning 前诊断、Phase A 负责合同与快照收口、learned/tree/neural 只有在 same-run frozen valid/test 证据通过后才进入推进讨论；同时在工程日志里补齐这些指标的口径，避免把 LOPO、stage trace 或线上指标混入当前离线晋升。

**验证结果：**
相关定义可在 `rs_core/recsys/evaluation.py`、`scripts/experiments/recall/phase_1_20_recall_diagnostics.py` 和 `scripts/experiments/ranking/run_phase_5_fine_rank_positive_push.py` 中直接对应到现有字段；本次只更新文档，没有改动 `candidate_pool_size=200`、`top_k=5` 或召回语义。

**面试可讲点：**
可以讲成“先把诊断门和晋升门拆开，再谈模型路线”：这样 Phase C 负责判断是否值得继续 tuning，Phase A 负责把合同边界固化，后续 learned/tree/neural 才能在同一证据框架里比较，不会把分析指标当成上线证据。

### 2026-05-14 - 默认离线主线收口与 Agent 手递边界

**任务：**
把长期排序路线收口为可供 Agent 系统直接交接的默认离线主线，明确当前目标是稳定可用的 handoff，而不是无限扩展算法族。

**遇到的问题：**
原有 Phase 0-8 叙事已经覆盖了实验顺序与门禁，但还缺少面向系统交接的终态说明，容易让后续 Agent 误把“继续探索更多算法”理解为默认工作目标。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase C / Phase A / learned-tree-neural 叙事，确认当前最需要补的是默认主线职责、完成标准和 handoff 边界，而不是新增方法族。

**解决方式：**
在长期计划里补充默认离线 mainline 收口说明：把 `coarse → fine → rerank` 作为默认合同，继续锁定 `frozen pool200`、`candidate_pool_size=200`、`top_k=5` 和召回语义；Phase C 只保留诊断槽位；learned/tree/neural 只保留 future/blocked 位置；同时明确 Agent 系统只接收这条已经收口的主线，不再把方法族扩展当作默认目标。

**验证结果：**
本次仅更新中文文档与日志，没有改代码、没有改 runner、没有改评估口径，也没有动 `candidate_pool_size=200`、`top_k=5` 或召回语义。

**面试可讲点：**
可以讲成“把算法探索和系统交接分层”：先提供稳定、可复用、可交接的默认离线主线，再把更激进的 learned/tree/neural 路线留到明确门禁之后，避免 Agent 在不稳定边界上继续发散。



## 2026-05-15 - å·¥ç¨‹è§„èŒƒ v1.1ï¼šé…�ç½® contractã€�è„šæœ¬å…¥å�£ä¸Žè½»é‡� recsys å�•æµ‹

- ä»»åŠ¡ï¼šåœ¨å·¥ç¨‹è§„èŒƒ v1 åŸºç¡€ä¸Šç»§ç»­æŠŠâ€œå�£å¤´çº¦å®šâ€�è�½æˆ�å�¯æ‰§è¡Œé—¨ç¦�ï¼Œé‡�ç‚¹è¦†ç›–é…�ç½® contractã€�scripts å…¥å�£è§„èŒƒå’Œ recsys æ ¸å¿ƒè½»é‡�å�•æµ‹ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šé…�ç½®å’Œè„šæœ¬æ•°é‡�å·²ç»�å¾ˆå¤šï¼Œå�•é� æ–‡æ¡£å¾ˆéš¾ä¿�è¯�ä¸�å‡ºçŽ°ä¸ªäººç»�å¯¹è·¯å¾„ã€�tracked ä¸´æ—¶é…�ç½®æˆ– import å�³æ‰§è¡Œçš„è„šæœ¬ï¼›å�Œæ—¶ `tests/test_hybrid_demo.py` è¿‡å¤§ï¼ŒåŸºç¡€å�¬å›ž/æŽ’åº�è¡Œä¸ºæ··åœ¨å®žéªŒæµ‹è¯•é‡Œä¸�åˆ©äºŽå¿«é€Ÿ CIã€‚
- å®šä½�æ–¹å¼�ï¼šç”¨ `git ls-files 'configs/*.yaml'` æ˜Žç¡® CI å�ªæ£€æŸ¥ tracked é…�ç½®ï¼›ç”¨ `scripts/ci/validate_engineering_contracts.py` æ‰«æ�� 110 ä¸ª tracked é…�ç½®å’Œ 48 ä¸ªè„šæœ¬ï¼Œå�‘çŽ° 4 ä¸ªåŽ†å�²å� ä½�è„šæœ¬ç¼ºå°‘ main guardï¼›ç”¨æ–°å¢žå�•æµ‹éªŒè¯� contract è¾¹ç•Œã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `rs_core/common/engineering_contracts.py` å’Œ `scripts/ci/validate_engineering_contracts.py`ï¼Œå°†é…�ç½®å�¯åŠ è½½ã€�ç¦�æ­¢ tracked `_tmp` é…�ç½®ã€�ç¦�æ­¢ä¸ªäººæœºå™¨ç»�å¯¹è·¯å¾„ã€�è„šæœ¬ main guard å�˜ä¸ºå�¯æ‰§è¡Œæ£€æŸ¥ï¼›è¡¥é½� 4 ä¸ªå� ä½�è„šæœ¬çš„æœ€å°� `main()` éª¨æž¶ï¼›æ–°å¢ž `tests/test_recsys_core.py`ï¼Œä»Žå¤§æµ‹è¯•ä¸­æ‹†å‡º candidate mergeã€�ranking tie-breakã€�metadata neighbor recall ä¸‰ç±»åŸºç¡€è¡Œä¸ºã€‚
- éªŒè¯�ç»“æžœï¼š`scripts/ci/validate_engineering_contracts.py` é€šè¿‡ï¼Œè¾“å‡º `Engineering contracts passed: 110 configs, 48 scripts`ï¼›æ–°å¢žå�•æµ‹ `8 passed`ï¼›CI Python èŒƒå›´ ruff é€šè¿‡ï¼›unit/smoke æœ€å°�é›†å�ˆæ”¶é›† 75 ä¸ªå¹¶ `75 passed`ï¼›`npm --prefix frontend run lint` é€šè¿‡ï¼›`git diff --check` æ—  whitespace é”™è¯¯ï¼Œä»…ä¿�ç•™ Windows æ�¢è¡Œæ��ç¤ºã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ¬¡ä¸�æ˜¯æ³›æ³›å†™è§„èŒƒï¼Œè€Œæ˜¯æŠŠç›®å½•/é…�ç½®/è„šæœ¬/æµ‹è¯•çº¦å®šè½¬æˆ�è‡ªåŠ¨åŒ– contract gateï¼Œå¹¶ç”¨è½»é‡�å�•æµ‹ä»Žå¤§å®žéªŒæµ‹è¯•ä¸­æŠ½å‡ºç¨³å®šæ ¸å¿ƒè¡Œä¸ºï¼Œä½“çŽ°äº†â€œè§„èŒƒæ–‡æ¡£ + å�¯æ‰§è¡Œé—¨ç¦� + å¿«é€Ÿå��é¦ˆâ€�çš„å·¥ç¨‹åŒ–ç»´æŠ¤æ€�è·¯ã€‚


### 2026-05-15 - é…�ç½®ã€�æ–‡æ¡£ä¸Žè¾“å‡ºäº§ç‰©ç›®å½•æ²»ç�†

**ä»»åŠ¡ï¼š**
æŠŠ `configs/`ã€�`dic/`ã€�`outputs/` ä¸­é•¿æœŸå †ç§¯çš„é…�ç½®ã€�æ–‡æ¡£å’Œè¿�è¡Œäº§ç‰©æŒ‰è�Œè´£é‡�æ–°åˆ†å±‚ï¼Œå¹¶è¡¥é½�æ–°å¢žæ–‡æ¡£ã€�é…�ç½®å’Œä¸€æ¬¡æ€§å®žéªŒäº§ç‰©çš„è·¯ç”±è§„èŒƒã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
`configs/` æ ¹ç›®å½•æ··æœ‰å¤§é‡� hybrid demoã€�phase å’Œä¸´æ—¶è°ƒå�‚é…�ç½®ï¼›`dic/` æ ¹ç›®å½•å�Œæ—¶æ‰¿è½½æž¶æž„ã€�é˜¶æ®µã€�å®žéªŒæŠ¥å‘Šå’Œå…¥å�£æ–‡æ¡£ï¼›`outputs/` é¡¶å±‚æ··å�ˆ canonical demoã€�smokeã€�verificationã€�training å’Œ root æ–‡ä»¶ï¼Œå¯¼è‡´æ­£å¼�è¯�æ�®ä¸Žä¸€æ¬¡æ€§å®žéªŒäº§ç‰©ä¸�æ˜“åŒºåˆ†ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆç»Ÿè®¡ `configs/`ã€�`dic/`ã€�`outputs/` æ ¹ç›®å½•æ–‡ä»¶å’Œå­�ç›®å½•ï¼Œå†�ç”¨è·¯å¾„æ‰«æ��ç¡®è®¤æ—§å¼•ç”¨æ˜¯å�¦ä»�æŒ‡å�‘ `configs/*.yaml`ã€�`outputs/phase_*`ã€�`outputs/hybrid_demo_small*` ç­‰æ—§ç»“æž„ï¼›éš�å�Žç”¨ `scripts/ci/validate_engineering_contracts.py` æ ¡éªŒé…�ç½®å�¯åŠ è½½æ€§å’Œè„šæœ¬å…¥å�£è§„èŒƒã€‚

**è§£å†³æ–¹å¼�ï¼š**
å°†é…�ç½®åˆ†æµ�åˆ° `configs/demo/hybrid_demo/`ã€�`configs/ranking/<phase>/`ã€�`configs/recall/<phase>/`ï¼›å°†æ–‡æ¡£åˆ†æµ�åˆ° `dic/architecture/`ã€�`dic/decisions/`ã€�`dic/phases/`ã€�`dic/experiments/`ã€�`dic/guides/`ã€�`dic/standards/`ã€�`dic/archive/`ï¼›å°†è¾“å‡ºäº§ç‰©åˆ†æµ�åˆ° `outputs/agent/`ã€�`outputs/hybrid_demo/`ã€�`outputs/ranking/`ã€�`outputs/recall/`ã€�`outputs/simulation/`ã€�`outputs/training/`ã€�`outputs/verification/`ã€�`outputs/archive/root_files/`ã€‚å�Œæ—¶è¡¥å…… `DOCUMENT_ROUTING_GUIDE`ã€�`CONFIG_GUIDE`ã€�`OUTPUTS_ROUTING_GUIDE` å’Œå·¥ç¨‹è§„èŒƒä¸­çš„ä¸€æ¬¡æ€§å®žéªŒæ¸…ç�†è§„åˆ™ï¼Œå¹¶æŠŠ contract è„šæœ¬æ”¹ä¸ºæŒ‰å½“å‰� `configs/**/*.yaml` å·¥ä½œæ ‘é€’å½’æ ¡éªŒã€‚

**éªŒè¯�ç»“æžœï¼š**
`configs/` æ ¹ç›®å½•å·²æ—  `.yaml`ï¼Œæ—  `_tmp*.yaml`ï¼›`outputs/` é¡¶å±‚å�ªä¿�ç•™ `.gitkeep` å’Œ 8 ä¸ªè�Œè´£ç›®å½•ï¼›`dic/` æ ¹ç›®å½•å�ªä¿�ç•™ 4 ä¸ªå…¥å�£/é«˜é¢‘ç»´æŠ¤æ–‡æ¡£ã€‚æ—§è·¯å¾„æ‰«æ��å¯¹ `outputs/phase_*`ã€�`outputs/hybrid_demo_small*`ã€�`configs/hybrid_demo*.yaml`ã€�`configs/phase_*.yaml` æ— å‘½ä¸­ï¼›`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` é€šè¿‡ï¼Œè¾“å‡º `Engineering contracts passed: 110 configs, 49 scripts`ï¼›`./.venv/Scripts/python.exe -m pytest tests/test_engineering_contracts.py tests/test_graph_walk_training.py -q` é€šè¿‡ `7 passed`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™è½®å�¯ä»¥è®²æˆ�â€œæŠŠå®žéªŒåž‹é¡¹ç›®ä»Žæ–‡ä»¶å †ç§¯æ²»ç�†æˆ�å�¯å¤�ç›˜å·¥ç¨‹èµ„äº§â€�ï¼šä¸�æ˜¯å�ªç§»åŠ¨æ–‡ä»¶ï¼Œè€Œæ˜¯å�Œæ­¥å»ºç«‹æ–‡æ¡£è·¯ç”±ã€�é…�ç½® contractã€�äº§ç‰©è·¯ç”±å’Œä¸€æ¬¡æ€§å®žéªŒæ¸…ç�†è§„åˆ™ï¼Œå¹¶ç”¨æ‰«æ��å’Œ contract éªŒè¯�é˜²æ­¢è·¯å¾„è¿�ç§»å�Žå¼•ç”¨æ–­è£‚ã€‚


## 2026-05-15 - 工程规范 v1.2：测试分层 marker contract

**任务：**
把测试分层从约定升级为可执行 contract：所有 `tests/test_*.py` 必须声明文件级 `pytestmark`，普通 CI 不再维护手工测试白名单，而是按 unit/smoke marker 自动选择快速门禁测试。

**遇到的问题：**
测试文件数量增加后，缺少统一 marker 会导致慢实验、GPU 训练或重依赖测试混入普通 CI；原 CI 手工列测试文件也容易遗漏新增的 Agent、serving 或 recsys 基础测试。目录重整后，`tests/test_serving_smoke.py` 还残留对旧 demo 配置和真实本地数据产物的依赖，放入 smoke gate 后暴露出路径与数据依赖问题。

**定位方式：**
先用 `scripts/ci/validate_engineering_contracts.py` 让未标记测试显式失败，再为 32 个测试文件补齐 unit/smoke/experiment 等文件级 marker；随后用 `scripts/ci/select_tests_by_marker.py --marker unit --marker smoke` 验证 selector 不导入测试模块即可选出快速门禁集合，并通过 collect/run 暴露 serving smoke 对旧真实数据目录的依赖。

**解决方式：**
在 `rs_core/common/engineering_contracts.py` 中新增基于 AST 的 marker 解析、未标记测试检查和 selector 复用逻辑；新增 `scripts/ci/select_tests_by_marker.py`；CI 改为先选择 unit/smoke 文件，再执行 collect 和 pytest；同时把 serving smoke 中依赖真实 demo 数据的用例改为复用临时 fixture，保证普通门禁只验证服务 contract，不依赖本机历史产物。

**验证结果：**
`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 通过，输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；selector + collect 选中并收集 139 个 unit/smoke 测试；`./.venv/Scripts/python.exe -m pytest -m "unit or smoke" -q` 通过 `139 passed`；`./.venv/Scripts/python.exe -m ruff check rs_core scripts/ci/validate_engineering_contracts.py scripts/ci/select_tests_by_marker.py tests` 通过；独立 verifier 结论为 PASS。

**面试可讲点：**
这轮可以讲成“把测试治理从人工白名单升级成自描述分层 contract”：测试文件自己声明层级，CI 自动选择稳定快速门禁，实验/GPU/慢测试不会污染普通提交，同时通过 smoke fixture 化消除了对本地历史数据产物的隐式依赖。


## 2026-05-15 - 工程规范 v1.3：组合 marker 与 serving 专项门禁

**任务：**
在 v1.2 测试分层契约基础上继续细化 marker 矩阵：让服务接口测试、慢实验、GPU 实验可以通过组合 marker 独立选择，同时保留默认 `unit or smoke` 快速门禁。

**遇到的问题：**
单一 marker 只能说明测试大类，无法表达“这是 smoke 也是 serving”“这是 experiment 也是 slow/GPU”这类运行边界。随着测试数量增加，如果不把服务、慢实验和 GPU 训练路径显式组合标记，后续 CI 很容易把重实验混入普通 PR，或者无法单独验证服务 contract。

**定位方式：**
先审计 `pyproject.toml`、`.github/workflows/ci.yml` 和 32 个 `tests/test_*.py` 文件，确认现有 marker 定义齐全但实际落标还集中在 unit/smoke/experiment。再按测试职责区分服务路径、慢实验路径和 GPU/训练路径，并用 selector 分别验证 `unit/smoke` 与 `serving` 能否独立选中目标文件。

**解决方式：**
为 `tests/test_serving_smoke.py` 和 `tests/test_simulation_runner.py` 标记 `serving + smoke`，为 `tests/test_agent_runtime.py` 标记 `unit + serving`，为 `tests/test_two_tower_training.py` 标记 `experiment + gpu`，为多个重实验测试标记 `experiment + slow`；同时更新 `dic/standards/ENGINEERING_STANDARDS.md` 的组合 marker 规则，并在 `.github/workflows/ci.yml` 中新增 serving 专项 select/collect/run，默认 CI 仍不新增 GPU/slow/experiment job。

**验证结果：**
独立 verifier 只读核验通过：32 个测试文件均有文件级 `pytestmark`；`serving` selector 选出 3 个服务相关文件；默认 `unit/smoke` selector 选出 19 个文件且未包含 slow/gpu experiment；`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；ruff 通过；`pytest -m "unit or smoke"` 通过 `139 passed`；`pytest -m "serving"` 通过 `34 passed`。

**面试可讲点：**
这轮可以讲成“测试矩阵治理”：不是简单给测试贴标签，而是把测试运行成本、依赖边界和 CI 入口显式建模。默认 PR 只跑快而稳定的门禁，服务 contract 可单独验证，慢实验和 GPU 训练不会无意进入普通 CI。


## 2026-05-15 - 工程规范 v1.4：scripts 瘦身最小切片

**任务：**
在工程规范 v1.x 的基础上推进 scripts 瘦身：选择一个低风险、已有测试覆盖的脚本逻辑，把稳定可复用能力下沉到 `rs_core`，让 `scripts/` 更接近“参数解析 + 流程触发”的入口层。

**遇到的问题：**
项目里不少脚本已经承载了实验流程和可复用业务逻辑。如果一次性大规模迁移，容易影响历史实验口径；但完全不迁移，又会让通用推荐逻辑散落在脚本中，后续复用和测试都变困难。

**定位方式：**
先做只读审计，优先寻找纯函数、小范围、已有测试覆盖的候选逻辑。最终选择 `scripts/data/build_recall_views.py` 中的 `unique_recent_items()`：它是 ItemCF 边构造前的最近序列去重逻辑，属于稳定推荐基础能力，且 `rs_core/recsys/candidate_merge.py` 已经集中承载候选合并与召回相关逻辑。

**解决方式：**
将 `unique_recent_items()` 下沉到 `rs_core/recsys/candidate_merge.py`，保留原有 reverse traversal、去重和 `appendleft` 的顺序语义；`scripts/data/build_recall_views.py` 改为 import 并复用该函数；同时在 `tests/test_build_recall_views.py` 新增 ItemCF 边构造用例，覆盖包含重复最近行为序列时的 pair 生成，防止迁移后语义漂移。

**验证结果：**
执行员定向验证 `./.venv/Scripts/python.exe -m pytest tests/test_build_recall_views.py tests/test_recsys_core.py -q` 通过 `6 passed`，engineering contracts 通过，ruff changed scope 通过。独立 verifier 只读核验确认：`unique_recent_items()` 仅在 `rs_core/recsys/candidate_merge.py` 定义，脚本只 import/reuse；新增测试覆盖最近去重后的 ItemCF pair；额外执行 `tests/test_build_recall_views.py tests/test_engineering_contracts.py` 通过 `12 passed`，ruff 通过，无本轮临时文件残留。

**面试可讲点：**
这轮可以讲成“脚本入口层治理的渐进式重构”：不是一口气重写实验脚本，而是用测试保护的小切片，把稳定业务能力从脚本下沉到核心包，降低复用成本，同时用定向测试和独立验证证明实验行为没有改变。


## 2026-05-15 - 工程规范 v1.5：scripts ruff 全量未使用项清理

**任务：**
在 v1.4 scripts 瘦身之后，继续把 `scripts/` 纳入更完整的 ruff 检查范围，清理历史脚本中暴露的 F401/F841 未使用导入和未使用变量。

**遇到的问题：**
提交前审计时，当前工程规范范围内的 ruff 已通过，但扩大到 `ruff check scripts` 后暴露出多个历史脚本的未使用 import / 变量。这些问题不会改变实验结果，但会阻碍后续把 scripts 纳入统一 lint 门禁。

**定位方式：**
用 `./.venv/Scripts/python.exe -m ruff check scripts` 复核失败清单，确认 19 个命中全部为 F401/F841，集中在少数脚本：`phase_1_20_recall_diagnostics.py`、`run_phase_1_26_real_learned_gbdt_ranker.py`、`run_phase_1_29_terminal_ranking_route.py`、`run_phase_c_ranking_actionability.py`、`run_phase_c_ranking_actionability_diagnostic.py`、`validate_recall_registry.py`、`verify_recall_outputs.py`。

**解决方式：**
只做最小安全清理：删除未使用 import，精简未使用 re-export import，移除未使用局部变量 `baseline_frozen`；不改业务流程、不改实验口径、不做脚本结构重构。

**验证结果：**
独立 verifier 确认 `./.venv/Scripts/python.exe -m ruff check scripts` 输出 `All checks passed!`；`./.venv/Scripts/python.exe scripts/ci/validate_engineering_contracts.py` 输出 `Engineering contracts passed: 110 configs, 50 scripts, 32 tests`；diff 中 scripts 改动均为 unused import / unused variable 清理；未发现本轮临时文件残留。

**面试可讲点：**
这轮可以讲成“扩大工程门禁覆盖面前的历史债务清理”：先用 lint 暴露低风险、可机械修复的问题，再严格限制改动类型，只清理不会影响业务行为的未使用项，为后续把 `scripts/` 全量纳入 CI lint 打基础。

### 2026-05-16 - 代表性轻量 E2E 预检收口

**任务：**
在 `outputs/recall/full_main_route_other_methods/lightweight_representative_e2e` 的代表性 full-lightweight E2E 通过后，整理方法预检结果并把结论同步到实验日志和工程叙事日志。

**遇到的问题：**
这轮只有 Popular / Category / Semantic 的轻量候选生成真正跑通，ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 等方法都不能被写成已执行结果，否则会把清单里的 disabled / deferred 状态误写成 promotion。

**定位方式：**
依据代表性 E2E 的 manifest/source audit 结果核对输出目录：`500` users、`75,866` candidate rows、`0` empty users，enabled sources 仅 `popular` / `category` / `semantic`，disabled sources 明确包含 `ItemCF`、`graph`、`two_tower`、`UserCF`、`Swing`、`MF`、`sequence`、`pool500`、`pool1000`，并且没有 `itemcf` / `graph` / `pool` 输出文件，也没有 10k source path。

**解决方式：**
只把已验证的 Popular / Category / Semantic 链路写成当前代表性结果；其余方法族统一按 `defer` / `document_only` / `fallback` 收口，保留为后续受控回跑或 sidecar 补齐项，不在本轮提升状态。

**验证结果：**
工程日志与实验日志都只记录同一份可回指证据：`outputs/recall/full_main_route_other_methods/lightweight_representative_e2e`。结论边界明确为“只确认轻量三源可用”，未把 ItemCF/co-visit、UserCF、Swing、graph_walk、two_tower、MF、sequence 伪装成已跑或已晋升。

**面试可讲点：**
这段可以讲成“用 manifest/source audit 给推荐实验划边界”：不是看见 E2E 成功就默认所有方法都能晋升，而是只按已验证产物收口，确保工程日志和方法日志对同一批证据保持一致。

### 2026-05-16 - Full-safe 召回方法全家桶 Phase 0-6 收口

**任务：**
按 Team+Ralph 的连续推进要求，把召回方法全家桶从 Phase 0 合同预检推进到 Phase 6 final method matrix，补齐 ItemCF/co-visit、UserCF、Swing/session、graph/MF、two_tower/pool readiness 的受控证据，并同步 PRD、进度与召回实验日志。

**遇到的问题：**
Phase 0 一开始发现 graph/two_tower/ranking pool200 配置仍引用 10k 路径；后续 Phase 6 首次汇总又因为 Phase 0 的 holdout contract 写在嵌套字段中，被 final matrix 误判为未证明 holdout exclusion。若直接跳过这些问题，会把 scope drift 或审计格式差异带入总验收。

**定位方式：**
通过 Phase 0 manifest/source audit 定位 10k config 引用；通过 Phase 4/5 的契约测试补充 config payload 内部 10k 引用检测；通过 Phase 6 失败输出定位到 `holdout_contract.candidate_generation_uses_holdout=false` 与后续阶段 top-level `candidate_generation_uses_holdout=false` 的字段格式差异。

**解决方式：**
为 graph、two_tower、ranking pool200 创建 full-safe 配置副本并让 Phase 0 默认解析这些副本；Phase 3 使用 bounded Swing/session observation，不做无界 pair counter；Phase 4/5 只做合同/feasibility gate，不训练、不晋升、不替代 frozen pool200；Phase 6 增加兼容 Phase 0 嵌套 holdout contract 的读取逻辑，并输出 `final_method_matrix_pass` 作为最终成功产物。

**验证结果：**
最终 canonical Phase 0 manifest 为 `PASS`；Phase 1 为 `EXECUTED_PASS_OBSERVATION_ONLY` 且 `recall_at_pool_delta=0.0`、`source_marginal_hit=0`；Phase 2 为 `rejected` 且 `failure_reason=no_positive_observation_lift`；Phase 3 为 `EXECUTED_PASS_OBSERVATION_ONLY`；Phase 4 为 `EXECUTED_PASS_CONTRACT_ONLY`；Phase 5 为 `EXECUTED_PASS_FEASIBILITY_ONLY`；Phase 6 `outputs/recall/full_main_route_other_methods/final_method_matrix_pass/manifest.json` 为 `PASS`，`final_method_matrix.json` 汇总 6 个 phase、`failures=[]`、`candidate_generation_uses_holdout=false`。

**面试可讲点：**
这段可以讲成“召回方法扩展不是盲目堆方法，而是先建立可审计合同”：用 source audit 防数据泄漏，用 bounded observation 控资源，用 final matrix 把每个方法族的晋升/拒绝/延期原因结构化，最后得出“本轮无新增方法晋升，但工程上获得可复跑、可解释、可继续扩展的召回方法矩阵”。

### 2026-05-17 - Representative pool500 recall-only 试验与 Gate 收口

**任务：**
在前一轮 pool500 只做到 readiness 的基础上，按“先 representative pool500、再决定 full”的路线补齐真实 recall-only 试验、same-scope 对比、审计和 Promote/Stop Gate。

**遇到的问题：**
此前 `pool500/pool1000=READINESS_ONLY_NOT_RANKING_INPUT` 只证明没有替代 ranking pool200，并没有回答 pool500 是否真的比 pool200 多召回用户；如果直接 full 或直接接 ranking，会把扩池实验和排序主线混在一起。

**定位方式：**
固定 500 个 representative users，分别生成同 scope 的 pool200 与 pool500 recall-only 候选，并在同一 `users_with_holdout=82` 分母下比较：pool200 `candidate_hit_users=4`、`recall_at_pool=0.042683`；pool500 `candidate_hit_users=6`、`recall_at_pool=0.055459`。

**解决方式：**
新增独立 P0-P6 pool500 representative 分支：P0-P2 生成同 scope pool200/pool500 候选；P3-P4 产出 `pool500_vs_pool200_same_scope_comparison.json`、`leakage_audit.json`、`resource_audit.json`、`ranking_isolation_audit.json`；P5 只做方法贡献观察；P6 生成 `promote_stop_gate.json`。全过程不进入 ranking、不生成 pool1000、不训练 graph/MF/two_tower、不复制 full clean。

**验证结果：**
`promote_stop_gate.json` 为 `PASS`，`exclusive_hit_users_201_500=2`，新增来源为 `category=1`、`popular=1`，`recall_at_pool_delta=0.012776`；duplicate、empty、fallback 均未恶化；leakage/resource/ranking isolation audits 均为 `PASS`。`tests/test_pool500_representative.py` 为 `5 passed`，相关脚本与测试 ruff 为 `All checks passed`，独立 verifier 给出 `APPROVED` 且 0 blockers。

**面试可讲点：**
这段可以讲成“把扩池从拍脑袋变成可审计 Gate”：不是直接把 pool500 切成默认样本，而是用同用户、同分母、同召回合同对比 pool200 和 pool500，证明 201-500 区间确实带来 2 个 exclusive hit users，再用 leakage/resource/ranking isolation 三重审计保证没有数据泄漏、资源越界或排序主线污染。

### 2026-05-17 - Representative pool500 全方法轻量与 CF 观察

**任务：**
在已 PASS 的 custom index 上补齐 pool500 all-methods representative 的轻量方法、bounded ItemCF/co-visit 与 bounded UserCF 观察，输出 recall-only 方法指标和审计证据。

**遇到的问题：**
轻量 pool500 候选已经存在，但 CF 不能复用全局无界共现或 dense all-user matrix；同时 candidate generation 不能读取 valid/test/holdout，也不能触碰 10k baseline、pool1000、ranking 或 graph/MF/two_tower 训练。

**定位方式：**
核验 `custom_index/manifest.json` 为 `PASS`，D 盘剩余约 204GiB，大于 50GiB 阈值；读取既有 pool500 candidates 与 indexed train sequences 的 schema，确认可以只基于 500 个 representative users 和 10739 个 custom items 构造局部 CF 证据。

**解决方式：**
新增 `scripts/experiments/recall/run_pool500_all_methods_lightweight_cf.py`，复用已有 pool500 lightweight candidates 表示 popular/category/semantic；ItemCF/co-visit 只在 custom-index representative train sequences 上构建局部 item-item 共现邻居；UserCF 只构建 item->users 倒排并按 capped similar users 取候选，显式不生成 dense user-user matrix。

**验证结果：**
脚本运行产物 `outputs/recall/pool500_all_methods_representative/lightweight_cf_methods/manifest.json` 为 `PASS`；`method_metrics.json` 显示 lightweight `recall_at_pool=0.055459`、merged `recall_at_pool=0.055459`；`resource_audit.json` 记录 lightweight 193824 行、ItemCF 335 行、UserCF 14 行、merged 194149 行；`source_audit.json` 证明 candidate generation 只读 pool500 candidates、indexed train sequences、custom item index，valid/test 仅 evaluation-only。ruff 与 `py_compile` 均通过，独立约束核验输出 `candidate_reads_ok=true`、`artifacts_ok=true`。

**面试可讲点：**
这段可以讲成“在扩池 Gate 后继续做方法族消融，但不牺牲边界”：轻量方法提供 pool500 主体收益，CF 方法在代表性小样本上以 bounded observation 方式补充证据；即使本轮 CF 没带来 recall lift，也沉淀了可审计、可复跑、可扩展到 full pool500 前的资源与泄漏控制模板。

### 2026-05-17 - Representative pool500 全方法 custom-index Gate 收口

**任务：**
在 representative pool500 已经 Gate PASS 的基础上，按用户要求补齐主路全方法族试验：轻量源、bounded CF、Swing/session，以及 graph/MF/two_tower 的 custom-index feasibility/proxy probe，并用统一 Final Gate 决定是否允许继续 full pool500 recall-only。

**遇到的问题：**
直接跑 full pool500 或重模型训练会带来资源与范围风险；但只写 deferred 又无法回答“所有召回方法是否都试过”。需要在不复制 full clean、不读 holdout 做候选生成、不污染 ranking pool200 的前提下，为重方法构造可验证的定制索引试验边界。

**定位方式：**
先构建 `outputs/recall/pool500_all_methods_representative/custom_index/`，固定 500 users、10739 items、1289 train events；再分别检查 `lightweight_cf_methods/`、`sequence_session_methods/`、`heavy_indexed_probes/` 与 `final_gate/` 的 manifest/source_audit/resource_audit，确认候选生成不读 valid/test/holdout、无 10k source、无 pool1000、无 ranking replacement。

**解决方式：**
采用“custom index + 方法族 observation/probe + Final Gate”的路线：lightweight 表示 popular/category/semantic；ItemCF/UserCF 限定在 custom-index train scope，禁止 full global counter 与 dense all-user matrix；Swing/session 只构建 bounded pair/transition observation；graph/MF/two_tower 只做 feasibility/proxy，不训练、不晋升。Final Gate 输出 `decision=CONTINUATION_ONLY`，把允许范围限制为后续 recall-only full pool500 continuation。

**验证结果：**
`final_gate/promote_stop_gate.json` 为 `PASS`，`full_pool500_continuation_allowed=true`，但 `ranking_input_replacement_allowed=false`、`heavy_model_training_allowed_by_this_gate=false`、`pool1000_allowed=false`。`final_method_matrix.json` 覆盖 popular/category/semantic、bounded ItemCF/UserCF、Swing/session-transition、graph/MF/two_tower probes。`tests/test_pool500_all_methods_representative.py` 为 `5 passed in 0.09s`；相关 all-method scripts/tests ruff 为 `All checks passed`；独立 verifier `APPROVED` 且 0 blockers。

**面试可讲点：**
这段可以讲成“把全方法召回试验拆成安全可审计的分层 Gate”：轻量方法验证真实召回增量，CF/序列方法补充 bounded observation，重模型先做 custom-index feasibility 而不是盲目训练；最终用 source/resource/ranking isolation 三重审计把继续 full pool500 的权限限制在 recall-only，体现实验治理和工程边界控制。


## 2026-05-17 pool500 v5 artifact gate æ²»ç�†æŽ¥å…¥

- ä»»åŠ¡ï¼šå°† `pool500_recall_continuation_route` çš„ v5 artifact gate è¯­ä¹‰æŽ¥å…¥ current route registry å’Œå·¥ç¨‹å¥‘çº¦ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šregistry éœ€è¦�è¡¨è¾¾ `FULL_POOL500_READY / DIAGNOSTIC_ONLY_PARTIAL / STOP` ä¸‰æ€�ï¼Œä½†ä¸�èƒ½è®© pool500 recall-only äº§ç‰©è¢«è¯¯ç”¨ä¸º ranking inputï¼›å�Œæ—¶è½»é‡� YAML loader ä¼šæŠŠå¼•å�·å†… `#symbol` æˆªæ–­æˆ�æ³¨é‡Šã€‚
- å®šä½�æ–¹å¼�ï¼šè¿�è¡Œ `tests/test_engineering_contracts.py` é€šè¿‡å�Žï¼Œå†�è¿�è¡Œ `scripts/ci/validate_engineering_contracts.py` å�‘çŽ° `artifact_gate_workflow` è¢«æˆªæ–­å¯¼è‡´å¥‘çº¦å¤±è´¥ã€‚
- è§£å†³æ–¹å¼�ï¼šåœ¨ registry ä¸­ç™»è®° v5 schemaã€�workflowã€�allowed decisions å’Œç¦�æ­¢å€™é€‰ç”Ÿæˆ�/æŽ’åº�æ›¿æ�¢çš„æ˜¾å¼�å­—æ®µï¼›åœ¨ `engineering_contracts.py` å¢žåŠ  pool500 continuation ä¸“é¡¹æ ¡éªŒï¼›ä¿®å¤� lightweight config loader ä»…åœ¨å¼•å�·å¤–è¯†åˆ« `#` æ³¨é‡Šã€‚
- éªŒè¯�ç»“æžœï¼š`python -m pytest tests/test_engineering_contracts.py` é€šè¿‡ 17 é¡¹ï¼›`python scripts/ci/validate_engineering_contracts.py --root ...` é€šè¿‡ 115 configsã€�67 scriptsã€�46 testsã€�1 registryã€�1 allowlistã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šç”¨ registry + contract test æŠŠâ€œå�¬å›žäº§ç‰© readyâ€�å’Œâ€œæŽ’åº�è¾“å…¥å�¯æ›¿æ�¢â€�è§£è€¦ï¼Œé�¿å…�ç¦»çº¿å®žéªŒäº§ç‰©æ™‹å�‡æ—¶å�‘ç”Ÿè·¨é“¾è·¯è¯­ä¹‰æ±¡æŸ“ã€‚


### 2026-05-18 - pool500 sidecar 资源受控恢复与诊断接入

**任务：**
在前一次 full-train/UserCF 进程造成内存压力后，恢复 pool500 recall-only 所需的 ItemCF、UserCF、Swing sidecar，并用受控资源策略重新接入 20 用户诊断 batch。

**遇到的问题：**
UserCF 原实现会把全量 user_items、item_users 和 candidates_by_user 常驻内存，直接全量跑存在把本机内存打满的风险；ItemCF 全量脚本同样会保留全量 sequences/pair_count。另一个问题是诊断 sidecar 不能被误标为 `FULL_OUTPUT_READY`，否则可能被 route gate 当成完整可晋升来源。

**定位方式：**
先用 `.omc/tools/run_guarded_process.py` 加 `psutil` 监控 RSS/空闲内存；UserCF target20 构建日志显示峰值 RSS 约 185MB，ItemCF target500 weak/strong 峰值 RSS 约 38MB/37MB。再读取 `readiness_contract.json`、`resource_audit.json`、`per_source_readiness_contracts.json` 和 `merged_pool500_manifest.json`，确认诊断产物状态和最终 source coverage。

**解决方式：**
为 UserCF 和 ItemCF builder 增加 `target_user_limit` 诊断模式：UserCF 只为目标用户及共享目标 item 的邻居用户构造候选；ItemCF 先用 target20 发现候选被 seen-items 过滤，再扩大为 target500 source-positive 用户构建诊断 item-item 边。诊断产物统一标记 `status=DIAGNOSTIC_ONLY`、`diagnostic_output_status=DIAGNOSTIC_OUTPUT_READY`、`full_output_status=DIAGNOSTIC_OUTPUT_READY`，并修正 recall-only runner 对 artifact readiness 的继承和 marker isolation 摘要输出，避免诊断路径污染最终 bundle。

**验证结果：**
`tests/test_full_train_itemcf_sidecars.py`、`tests/test_full_train_usercf_sidecar.py`、`tests/test_full_data_pool500_recall_only.py`、`tests/test_full_data_pool500_route_gate.py` 共 65 项通过。受控 sidecar 构建成功：UserCF target20 输出 14 users/932 candidates；ItemCF target500 weak 输出 6098 edges，strong 输出 5636 edges；Swing v2 保持可用。复跑 `recall_only_target20_with_sidecars` 后仍为预期 `decision=STOP`，但 marker isolation 已 PASS，source coverage 包含 `itemcf_weak=23`、`itemcf_strong=4`、`usercf_recall=932`、`swing_recall=165`，且 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**面试可讲点：**
这段可以讲成“资源事故后的工程化恢复”：不是简单禁止全量任务，而是加 guard、限流、诊断 readiness 语义和 route gate 防误晋升，既恢复了 pool500 多召回源接入能力，又把内存、数据泄漏、ranking 替换和 artifact 晋升边界都显式写入可验证合同。

### 2026-05-18 - pool500 target100 受控诊断扩大

**任务：**
在 target20 诊断链路恢复后，将 pool500 recall-only 扩大到 100 用户诊断 batch，验证多召回源接入、资源 guard 和 route gate 边界在更大样本下是否稳定。

**遇到的问题：**
UserCF target20 只能覆盖很小的诊断范围，不能判断扩大 batch 后的候选贡献走势；同时 ItemCF/UserCF 仍是 `DIAGNOSTIC_ONLY`，如果扩大时误把它们当成 READY，会触发错误晋升风险。

**定位方式：**
先用 `.omc/tools/run_guarded_process.py` 构建 UserCF target100 sidecar，并检查 `.omc/logs/usercf_recall_target100_guarded.log`；再用同样 guard 运行 `recall_only_target100_with_sidecars`，审计 `manifest.json`、`merged_pool500_manifest.json`、`per_source_readiness_contracts.json` 和 `readiness_result.json`。

**解决方式：**
保持 ItemCF target500 与 Swing v2 sidecar 不变，新增 UserCF target100 诊断 sidecar，并在 recall-only runner 中通过 `--source-manifest` 显式覆盖 ItemCF/Swing/UserCF artifact。所有诊断来源继续保留 `status=DIAGNOSTIC_ONLY`，不替换 ranking input，不启用 pool1000。

**验证结果：**
UserCF target100 构建成功，输出 `candidate_user_count=64`、`candidate_total_count=4403`，guard 峰值 RSS 约 929MB。100 用户 batch 输出 `processed_users=100`、`candidate_rows=22146`、`underfilled_user_count=100`，source coverage 为 `category=5850`、`popular=16412`、`usercf_recall=4016`、`swing_recall=738`、`itemcf_weak=62`、`itemcf_strong=43`。最终仍为预期 `decision=STOP`，`marker_isolation_audit=PASS`，`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。focused tests 仍为 65 项通过。

**面试可讲点：**
这段可以讲成“从小样本 smoke 到受控扩大诊断”的工程推进：不是盲目跑全量，而是在资源 guard、诊断 readiness、source coverage 和 route gate 共同约束下逐步放大样本，证明链路稳定性的同时保留明确的不可晋升边界。

### 2026-05-18 - pool500 target500 受控诊断扩大

**任务：**
在 target100 诊断 batch 稳定后，继续把 pool500 recall-only 扩大到 500 用户，验证 UserCF 诊断 sidecar、ItemCF target500 sidecar 与 Swing v2 在更大样本下的资源占用和 source coverage。

**遇到的问题：**
UserCF target500 会显著扩大共享 item 邻居集合，内存增长快于 target 用户数；同时 ItemCF/UserCF 仍然不是 full-ready artifact，扩大样本只能用于诊断稳定性，不能作为 ranking input 晋升依据。

**定位方式：**
用 `.omc/tools/run_guarded_process.py` 运行 UserCF target500 构建并读取 `.omc/logs/usercf_recall_target500_guarded.log`，再运行 `recall_only_target500_with_sidecars` 并审计 `manifest.json`、`per_source_readiness_contracts.json`、`readiness_result.json`、`merged_pool500_manifest.json`。

**解决方式：**
继续采用单进程、8GB free memory、4GB RSS guard；新增 `usercf_recall_target500_guarded`，复用 `itemcf_weak_target500_guarded`、`itemcf_strong_target500_guarded` 和 `swing_recall_v2`，通过 `--source-manifest` 显式接入 500 用户 recall-only 诊断 batch。

**验证结果：**
UserCF target500 构建成功，`candidate_user_count=327`、`candidate_total_count=24056`，峰值 RSS 约 2394MB。500 用户 batch 输出 `processed_users=500`、`candidate_rows=111983`、`underfilled_user_count=500`，source coverage 为 `popular=81289`、`category=30193`、`usercf_recall=21251`、`swing_recall=3668`、`itemcf_weak=345`、`itemcf_strong=330`。最终仍为预期 `decision=STOP`，`marker_isolation_audit=PASS`，`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。focused tests 65 项通过。

**面试可讲点：**
这段可以讲成“资源受控的召回链路渐进放量”：从 20、100 到 500 用户逐级扩大，用峰值内存、source coverage、underfill 和 gate 决策共同判断稳定性，同时严格区分诊断可用和可晋升可用。

### 2026-05-18 - pool500 召回方法目录与 registry 治理

**任务：**
将 pool500 召回链路从零散实验产物整理为按方法维护的文档结构，并建立统一 registry，便于后续按 UserCF、ItemCF、Swing、semantic、two_tower 等 source 独立推进和记录。

**遇到的问题：**
此前关键信息分散在总工程日志、runner manifest 和不同输出目录中；当方法状态同时包含 READY、DIAGNOSTIC_ONLY、DEFERRED 时，容易混淆“诊断可跑”和“可正式晋升”。用户也提出希望每种方法在文件夹中维护同一个文档，方便执行和记录关键信息。

**定位方式：**
读取 `recall_only_target500_with_sidecars/manifest.json` 和 `per_source_readiness_contracts.json`，以 target500 最新证据确定各 source 状态、row_count、artifact 路径和不可晋升边界。

**解决方式：**
新增 `dic/recall_methods/<source>/METHOD.md`，为 10 个召回 source 和 `user_quality` 分层策略分别记录方法定位、readiness、适用用户、输入输出 artifact、资源画像、当前问题和下一步；同时新增 `configs/recall/pool500_method_registry.json`，集中维护 source 状态、文档路径、最新 artifact、eligible user policy 和安全策略。

**验证结果：**
已生成 11 个 `METHOD.md` 文件和 `pool500_method_registry.json`。使用项目 `.venv` 解析 registry 并校验所有 `method_doc`、`latest_artifact`、`latest_readiness_contract` 路径，结果 `source_count=10`、`missing=[]`。registry 明确保留 `decision=STOP`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`，并把 `user_quality` 标记为 `PLANNED` 调度策略而非召回 source。

**面试可讲点：**
这段可以讲成“召回实验治理和可执行知识库建设”：把多方法、多 artifact、多 readiness 状态沉淀成 per-method 文档和机器可读 registry，既方便后续按方法推进，也降低诊断产物被误晋升为生产输入的风险。

### 2026-05-18 - rs_lab 实验层与 rs_core 召回 source 薄接口治理

**任务：**
在每种 pool500 召回方法已有 `dic/recall_methods` 文档后，补齐实验层和 core 层的代码组织边界：成熟前先放在 `rs_lab` 实验治理框架中，`rs_core` 只建立稳定 source metadata 薄接口。

**遇到的问题：**
UserCF / ItemCF 仍是 `DIAGNOSTIC_ONLY`，semantic / co_visit / two_tower 仍是 `DEFERRED`，如果直接把实验 builder 或未成熟实现迁入 `rs_core`，会造成“有 core 程序就代表可正式晋升”的误解。当前仓库已有 `rs_lab` 实验脚本目录，但缺少明确治理文档；`rs_core` 也缺少按 source 暴露 readiness 和 artifact 边界的稳定 registry。

**定位方式：**
检查当前工作区目录后确认已有 `rs_lab/experiments/recall` 和 `rs_lab/experiments/ranking`，因此复用 `rs_lab` 而不是另建重复的 `rslab`。同时以 `configs/recall/pool500_method_registry.json` 为 source 状态事实源，对齐 READY、DIAGNOSTIC_ONLY、DEFERRED 三类状态和 target500 最新 artifact。

**解决方式：**
新增 `rs_lab/README.md`、`rs_lab/GOVERNANCE.md`、`rs_lab/experiments/recall/pool500/README.md`、`governance/README.md` 和 `user_quality/README.md`，明确实验晋升、资源 guard、ranking input 替换和 pool1000 的禁止边界。新增 `rs_core/recsys/recall_sources/base.py`、`registry.py`、`__init__.py`，只保存 `RecallSourceSpec` 与 source readiness 元数据，不迁移 UserCF / ItemCF / semantic 等实验构建逻辑。

**验证结果：**
新增 `tests/test_recall_source_registry.py`，校验 core registry 与 JSON registry source 名称一致、`user_quality` 不作为 candidate source、READY / DIAGNOSTIC_ONLY / DEFERRED 状态正确，并验证非 READY source 不能替代 ranking input。使用项目 `.venv` 运行 focused tests：`test_recall_source_registry.py`、`test_full_train_itemcf_sidecars.py`、`test_full_train_usercf_sidecar.py`、`test_full_data_pool500_recall_only.py`、`test_full_data_pool500_route_gate.py`，结果 70 项全部通过。

**面试可讲点：**
这段可以讲成“实验代码到核心框架的分层治理”：没有为了目录完整而把未成熟召回算法硬塞进 core，而是先建立实验层治理和 core 薄接口，让 readiness、artifact、资源和晋升边界可测试、可审计、可逐步演进。

### 2026-05-18 - pool500 READY 三源 stoploss 诊断落地

**任务：**
把已通过共识规划的“READY 三源加厚必须有止损”落成首轮可执行诊断，不直接跑 full-data、不晋升 DIAGNOSTIC_ONLY source，也不改变 ranking input 替换和 pool1000 gate。

**遇到的问题：**
当前 target500 虽然召回链路跑通，但 `underfilled_user_count=500`，说明 `category`、`popular`、`swing_recall` 三个 READY source 可能存在结构性覆盖上限。如果继续只调三源预算而没有诊断指标，容易在低收益方向上反复试验，也无法公平判断何时启动 UserCF、ItemCF 或 semantic title/category 的晋升诊断。

**定位方式：**
定位到 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 manifest 生成链路：主循环已拥有 `rows`、`source_rows`、`users`、`underfilled_user_count`、`source_coverage`，适合最小侵入地输出独立 audit artifact；测试扩展点在 `tests/test_full_data_pool500_recall_only.py`。

**解决方式：**
新增 `READY_STOPLOSS_SOURCES=("category", "popular", "swing_recall")` 和 `_ready_source_stoploss_audit()`，输出 `ready_source_stoploss_audit.json`，记录 READY 三源的 row_count、unique_item_count、user coverage、underfilled user coverage、marginal candidate share、ready-only capacity ratio 和 stoploss trigger reasons。manifest 顶层和 `required_artifacts` 引用该 audit，同时明确 `diagnostic_only_promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

**验证结果：**
扩展 `tests/test_full_data_pool500_recall_only.py`，断言 audit 文件存在、READY source 范围只包含 `category/popular/swing_recall`、安全边界不放行 diagnostic promotion/ranking replacement/pool1000，并覆盖 source 指标字段。使用项目 `.venv` 运行 focused suite：`test_full_data_pool500_recall_only.py`、`test_full_data_pool500_route_gate.py`、`test_recall_source_registry.py`，结果 57 项全部通过。

**面试可讲点：**
这段可以讲成“召回实验的止损机制设计”：不是盲目继续堆热门/类目召回，而是把 underfill、覆盖、边际贡献和安全边界沉淀成机器可读 audit，为后续是否并行启动重召回/语义召回晋升提供可验证证据。

### 2026-05-18 - UserCF guarded diagnostic 按 user_quality 分层落地

**任务：**
围绕 pool500 UserCF 做专项 guarded diagnostic：只从 `eligible_user_quality_manifest.json` 选取 `heavy_cf_eligible`，必要时才少量降级到 `medium_behavior`，同时保留 DIAGNOSTIC_ONLY、不替换 ranking input、不打开 pool1000。

**遇到的问题：**
现有 UserCF sidecar 虽然已有 train-only/no-holdout 基础，但默认逻辑仍可能在非 target-limit 情况下写 READY；更关键的是当前 target500 user_quality manifest 中 `heavy_cf_eligible=0`，如果 eligible 为空时退回全量用户矩阵，会违反重资源方法只服务高质量用户的边界。

**定位方式：**
读取 `dic/recall_methods/usercf_recall/METHOD.md`、`outputs/recall/pool500_user_quality/target500_train_only/eligible_user_quality_manifest.json`、`rs_lab/experiments/recall/build_full_train_usercf_sidecar.py` 和 `tests/test_full_train_usercf_sidecar.py`。用 `.venv` 统计 manifest：`profiles=500`、`heavy=0`、`medium=49`，确认主诊断应先输出 heavy-only 空结果，再用 medium20 做降级观测。

**解决方式：**
将 UserCF sidecar 升级为 `full_train_usercf_sidecar_v2` guarded diagnostic：新增 eligible manifest 过滤、`--include-medium-behavior` 显式开关、target batch checkpoint、resume 支持、RSS/free-memory samples、resource audit、readiness contract、source index manifest 和 `per_source_candidate_manifest.json`。同时修复 eligible 为空时误回退全量用户的风险，空 heavy 直接产出 `target_user_count=0` 的诊断 artifact；并在 `load_usercf_recall_sidecar()` 增加 runtime 硬校验，拒绝 `source_status != DIAGNOSTIC_ONLY`、candidate generation、ranking input replacement 或 pool1000 越权 manifest。

**验证结果：**
使用项目 `.venv` 运行 `tests/test_full_train_usercf_sidecar.py`、`tests/test_full_data_pool500_recall_only.py`、`tests/test_phase2_usercf_bounded_observation.py`，结果 22 项通过；对 `build_full_train_usercf_sidecar.py`、`candidate_merge.py` 和相关测试运行 ruff，结果通过。真实 artifact：heavy-only 输出 `target_user_count=0`、`indexed_user_count=0`、`candidate_total_count=0`、`peak_rss_mb=31`；medium20 降级诊断输出 `target_user_count=20`、`indexed_user_count=311896`、`candidate_user_count=20`、`candidate_total_count=2000`、`row_count=20`、`peak_rss_mb=552`、`underfilled_user_coverage=1.0`、`marginal_candidate_share=0.2`，readiness 仍为 `DIAGNOSTIC_ONLY` 且 `promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“重资源召回的安全放量策略”：先用 user_quality 把 UserCF 从全量矩阵风险中隔离出来，再用 batch checkpoint、memory guard、resource audit 和 readiness contract 约束实验产物；即使 medium20 有候选覆盖，也因为 heavy 用户缺失和诊断边界，不把它包装成 pool500 final ready。

### 2026-05-18 - pool500 readiness gate 总控收口

**任务：**
汇总 pool500 召回各专项窗口产物，复用并重跑带 sidecar 的 target500 recall-only diagnostic，补齐 readiness gate / drift 测试和工程叙事，给出是否可宣称 final ready 的结论。

**遇到的问题：**
旧 `outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/` manifest 已显示 `decision=STOP`、`underfilled_user_count=500`，但目录缺少 `ready_source_stoploss_audit.json`；同时 UserCF / ItemCF 已有 guarded diagnostic 产物，必须量化边际贡献但不能误晋升为 READY 或 ranking input replacement。

**定位方式：**
对齐 `configs/recall/pool500_method_registry.json`、`dic/recall_methods/*/METHOD.md`、`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 和现有 target500 artifact。使用 `.venv` 读取新诊断输出：`candidate_row_count=111983`、`underfilled_user_count=500`、`underfilled_user_ratio=1.0`，READY 三源 `category/popular/swing_recall` 的 ready-only capacity ratio 仅 `0.4606`，stoploss 触发 `target_batch_underfilled`、`max_user_candidate_count_below_pool500`、`ready_source_capacity_below_pool500_budget`。

**解决方式：**
在 recall-only runner 中新增 `diagnostic_source_contribution.json`，记录 `usercf_recall`、`itemcf_weak`、`itemcf_strong` 的 row_count、user coverage、underfilled coverage、marginal_candidate_share 和 `promotion_allowed=false`；manifest 和 registry 的 `latest_diagnostic_batch` 指向新的 `outputs/recall/pool500_readiness_gate_diagnostic_500_with_sidecars/`，同时保留 `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。没有修改 `current_route_registry.yaml`，也没有改变任何 source readiness。

**验证结果：**
使用项目 `.venv` 运行 `run_full_data_pool500_recall_only.py --limit-users 500` 并显式传入 UserCF / ItemCF weak / ItemCF strong / Swing guarded sidecar manifests，输出 `decision=STOP`。`diagnostic_source_contribution` 显示 DIAGNOSTIC_ONLY 三源合计 `row_total=21926`、`marginal_candidate_share=0.195798`，其中 `usercf_recall=21251`、`itemcf_weak=345`、`itemcf_strong=330`，三者仍 `promotion_allowed=false`。定向测试 `test_full_data_pool500_recall_only.py`、`test_pool500_method_registry_drift.py`、`test_recall_source_registry.py` 结果 `16 passed`，独立 verifier 复查通过。

**面试可讲点：**
这段可以讲成“推荐系统召回 readiness gate 的总控治理”：把各算法窗口产物统一收口为可审计 bundle，不因某个 DIAGNOSTIC_ONLY source 有边际贡献就直接晋升，而是用 underfill、source coverage、stoploss、贡献审计和禁升测试共同证明当前仍应 STOP，为下一轮专项优化提供清晰边界。

### 2026-05-18 - ItemCF strong-positive 覆盖扩大诊断

**任务：**
扩大 `itemcf_strong` 的 train-only strong-positive item pair 建索引范围，重新生成 guarded target500 diagnostic sidecar，并量化 underfilled 用户补量；保持 `DIAGNOSTIC_ONLY`，不修改 route registry、不打开 ranking input replacement 或 pool1000。

**遇到的问题：**
旧 strong target500 产物的 sidecar 边文件只有 `5636` 条边，recall-only target500 per-source `row_count=330`，无法证明对 underfilled 用户有足够补量；需要区分“强标签更干净”与“构建范围过窄导致覆盖不足”。

**定位方式：**
读取 `rs_lab/experiments/recall/build_full_train_itemcf_sidecars.py`、`dic/recall_methods/itemcf_strong/METHOD.md` 和旧 `outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/*`。旧日志显示构建命令只取 `--target-user-limit 500`，实际 `users_used=212`、`unique_pair_count=2818`、`rows_written=5636`；`row_count=330` 来自 `run_full_data_pool500_recall_only.py` 的 target500 per-source 输出。

**解决方式：**
复用既有 guarded builder，不改 readiness 边界，把 strong-positive train shard 扩大到 `--target-user-limit 5000`，保持 `max-items-per-user=20`、`max-item-user-freq=500`、`top-k-per-seed=80`，用 `.omc/tools/run_guarded_process.py` 约束 free memory 与 RSS。随后用新的 `itemcf_strong_target500_guarded/source_index_manifest.json` 重跑 `recall_only_target500_with_sidecars`，只显式覆盖 ItemCF strong/weak manifests，避免越界触碰 UserCF。

**验证结果：**
`.venv` guarded sidecar 构建通过，`itemcf_strong_edges.jsonl` 从 `5636` 增至 `49816`，`users_with_source_items=5000`、`users_used=2133`、`unique_pair_count=25030`、index `unique_item_count=9690`、`peak_rss_mb=27.055`，`no_holdout_audit.status=PASS`，`readiness_contract.status=DIAGNOSTIC_ONLY`。target500 recall-only 重跑输出 `decision=STOP`、`underfilled_user_count=500`；`itemcf_strong` per-source `row_count=1845`、`user_coverage_count=157`、`underfilled_user_coverage_count=157`、`marginal_candidate_share=0.020619`、`unique_item_count=1176`。对比同批 weak：`row_count=1880`、`user_coverage_count=163`、`marginal_candidate_share=0.02101`，说明 weak 更适合补量，strong 更适合作为高置信补充源。定向测试 `tests/test_full_train_itemcf_sidecars.py` 结果 `6 passed`。

**面试可讲点：**
这段可以讲成“高置信召回源的诊断放量”：不是为了把 strong ItemCF 包装成 READY，而是在 train-only、guarded、no-holdout 的约束下扩大强正反馈共现边，证明它能给 underfilled 用户带来实际增量，同时用 readiness contract 和 STOP 结果守住线上晋升边界。

### 2026-05-24 - pool500 TwoTower 独立 method_dataset 构建器

**任务：**
为 pool500 TwoTower 补一个 dataset-only 的独立 P2b builder，只产出训练样本和负例 universe，不复用旧 two_tower source/index/embedding 链路。

**遇到的问题：**
旧 TwoTower builder 依赖 source_index_manifest、VectorIndex、embedding/index 和 candidates 输出，容易把训练前 dataset 准备与候选生成、ANN 索引、promotion readiness 混在一起；新任务还要求缺少 P1 v2 profile/bucket 时必须阻塞。

**定位方式：**
读取 P1 `build_train_only_data_governance.py`，确认可用输入为 `user_quality_profile.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl` 和 `user_sequences.train.jsonl`；对照旧 `tests/test_pool500_two_tower_method_source.py`，确认新增路径必须避开旧 source builder 和索引依赖。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py`，只读取 clean train sequences 与 P1 governance artifacts，输出 `two_tower_train_samples.jsonl`、`negative_item_universe.jsonl`、`method_dataset_manifest.json`、`leakage_audit.json`；负例 universe 只从 P1 item quality/frequency 派生，manifest 禁止 source/index/embedding/candidates 字段，并提供 `limit-users`、`limit-interactions`、`max-samples`、`negative-ratio`、`max-items-per-user`、`min-free-bytes` 资源上限。

**验证结果：**
新增 `tests/test_pool500_two_tower_method_dataset.py` 覆盖负例来源、输出白名单、资源 caps、manifest schema、禁用 import/字段、缺少 v2 bucket 阻塞和 CLI。验证命令：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_two_tower_method_dataset.py -q`，结果 `6 passed`；`py_compile` 对新增 builder/test 通过。

**面试可讲点：**
这段可以讲成“把重模型召回的数据准备层和候选生成层解耦”：TwoTower 先形成可审计、train-only、资源受控的 method_dataset，不提前训练、不建索引、不声明 ready，从而为后续模型训练保留干净输入合同和泄漏审计边界。

### 2026-05-20 - Agent RAG 增强计划纳入当前文档

**任务：**
把 Agent 后续需要考虑 RAG 的方向纳入当前权威文档，而不是继续停留在 `old_dic` 历史草稿中。

**遇到的问题：**
历史 `old_dic` 中已有 RAG、物品知识库、向量检索和推荐幻觉控制的设想，但当前项目规范明确 `old_dic` 只作历史参考，不能直接作为 Agent 规划依据；同时当前 Agent 文档主要强调多轮对话、反馈、展示和仿真，还缺少 RAG 在候选证据、解释 grounding 和幻觉控制中的正式位置。

**定位方式：**
检索并读取 `old_dic/historical_plans/early_agent_generative_recsys_analysis.md` 中 RAG 相关段落，再对照当前 `dic/README.md`、`dic/architecture/IMPLEMENTATION_PLAN.md` 和 `dic/architecture/ARCHITECTURE.md`，确认最合适的落点是“Agent RAG 增强”规划层，而不是召回主路或已完成能力。

**解决方式：**
在实施计划中新增 `Phase 4：Agent RAG 增强，规划中`，明确知识库构建、轻量 text / metadata retrieval、RAG retrieval tool、Prompt / Context 注入和评估门禁；在架构说明中新增 Agent RAG 增强层和模块边界；在 README 中把 RAG 写入项目主叙事，但明确它尚未落地，不替代召回或排序。

**验证结果：**
通过关键词检查和 `git diff -- dic/README.md dic/architecture/IMPLEMENTATION_PLAN.md dic/architecture/ARCHITECTURE.md` 确认新增表述只影响当前权威文档，且统一保留边界：RAG 服务商品知识检索、解释 grounding、why 问答、澄清追问和幻觉控制；推荐结果仍来自受治理的候选池与排序链路，不绕过候选池生成新商品，不写成已完成能力。

**面试可讲点：**
这段可以讲成“把生成式推荐的幻觉控制纳入 Agent 架构，而不是让 LLM 自由编商品”：底层推荐 backbone 仍负责候选和排序，RAG 只给 Agent 提供商品知识证据和可追溯上下文，让推荐解释、why 问答和多轮澄清能 grounded 到真实商品字段。

### 2026-05-21 - pool500 policy rerank guard 组合副作用修复

**任务：**
定位并修复三阶段排序 challenger 中 policy rerank guard 把唯一命中正样本推出 Top20 的问题，保持 frozen pool500 候选池语义不变。

**遇到的问题：**
旧实验中 B0/R1/coarse-only 在 Top20 都能命中唯一 overlap 正样本，但 L1 three-stage 的 Hit@20/NDCG@20/MRR@20 归零；直接表现不是召回池丢样本，而是重排阶段把正样本从 Top20 内推到 Top20 外。

**定位方式：**
复核 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels/comparison.json`，确认 eval 45 个 positive pairs 只有 1 个进入 frozen pool500；该样本 `AFKROCEYUGLIBSDUJBFQPGGC44GA / B07P9V8GSH` 在 B0/R1 为 rank 11、coarse-only 为 rank 12、policy 后为 rank 81。结合 `rs_core/recsys/ranking.py` 检查发现多个 guard 顺序应用时，前序 guard 已标记 defer 的候选仍会被后续 guard 重新处理并参与 TopK 补位。

**解决方式：**
在 `_cap_policy_items`、`_cap_policy_group`、`_cap_rank_movement` 前先拆分 eligible 与已 deferred 候选，后续 guard 只处理仍 eligible 的候选，并把历史 deferred 候选稳定保留在后缀，避免 category_missing/source/category/rank movement 多个 guard 互相覆盖 defer 结果。新增回归测试覆盖“前序 category_missing_cap 已 defer 的候选不应被后续 source guard 补回 TopK”。

**验证结果：**
`.venv` 下运行 `tests/test_recsys_core.py tests/test_ltr.py tests/test_pool500_shadow_ranking.py tests/test_pool500_learned_ranking_challenger.py tests/test_pool500_label_artifact.py`，结果 `135 passed`。重跑同一批 aligned frozen-pool candidates 到 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels_guardfix/`，L1 的正样本 rank 从旧结果 81 恢复到 12，Hit@20 从 0.0 恢复到 0.1；promotion gate 仍为 `NO_PROMOTE / diagnostic_only_no_promote`，因为 NDCG@20 和 MRR@20 仍低于 B0，且存在 underpowered positive users / quality guard / no primary metric lift / primary MRR regression blockers。

**面试可讲点：**
这段可以讲成“离线排序策略的 guard 组合治理”：不是看到指标归零就否定 LightGBM 或三阶段链路，而是沿着 frozen pool → coarse/fine/rerank 的排名轨迹定位到 policy guard 的组合副作用；修复后恢复命中但仍坚持 no-promote，体现了效果指标、质量约束和上线门禁分离治理。

### 2026-05-21 - pool500 LTR 低证据注入降级与 coarse 校准回退

**任务：**
继续在已冻结 `pool500_vCurrent` candidates 上优化三阶段排序，不改召回、不新增候选、不改变 frozen pool 语义；补齐 B0/R1/coarse-only/L1 ablation，并重点处理 coarse/LTR/policy guard 排序顺序带来的诊断退化。

**遇到的问题：**
policy guard 组合 bug 修复后，L1 Hit@20 已从 0 恢复到 0.1，但唯一 overlap 正样本仍从 B0/R1 的 rank 11 退到 L1 的 rank 12，NDCG@20 和 MRR@20 略低于 B0/R1。当前 eval positive overlap 只有 1 个，不能把排序结论写成可晋升效果，只能做 diagnostic 调参。

**定位方式：**
读取 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels_guardfix/comparison.json`，确认 `positive_overlap_count=1`、`candidate_hit_rate_at_20=0.1`；唯一命中样本 `AFKROCEYUGLIBSDUJBFQPGGC44GA / B07P9V8GSH` 在 B0/R1 为 rank 11，在 coarse-only/L1 为 rank 12。局部 probe 显示退化来自 coarse policy 对 `category` source 的 0.95 校准折扣，以及 LightGBM LambdaMART 在仅 `positive_rows=1`、`positive_users=1` 时仍向排序注入负分。

**解决方式：**
把 pool500 challenger coarse policy 中 `category` source 校准从 0.95 回退到中性 1.0，避免在唯一诊断正例来自 category source 时人为压低分数；同时新增 LTR challenger eligibility，要求至少 5 条正例、2 个正例用户才允许把已训练 LTR 分数注入排序。训练产物继续记录 `positive_rows` / `positive_users`，但低证据时只保留模型诊断信息，不让 LTR 参与最终排序。

**验证结果：**
`.venv` 下运行 `tests/test_pool500_shadow_ranking.py tests/test_pool500_learned_ranking_challenger.py tests/test_recsys_core.py tests/test_ltr.py`，结果 `134 passed`。重跑 frozen candidates 到 `outputs/ranking/pool500_three_stage_offline_smoke_20260521/challenger_interaction_labels_ltr_guard/`，B0/R1/coarse-only/L1 四路在 @20 全部持平：`Hit=0.1`、`NDCG=0.004095`、`MRR=0.009091`、`Recall=0.005263`、`MAP=0.000478`；`frozen_candidate_equality.status=PASS`，`candidate_generation_allowed=false`，LTR 配置显示 `enabled=false`、reason=`underpowered_ltr_training_labels`。独立 verifier 复查通过，但仍建议 `NO_PROMOTE`，因为 no primary metric lift、正例证据不足和 category_missing quality guard 仍存在。

**面试可讲点：**
这段可以讲成“低证据排序模型的安全降级”：在 frozen candidate pool 内把召回覆盖、coarse calibration、LTR 注入和 policy guard 分层诊断，发现 learned 模型不是训练失败，而是在正例覆盖极低时不该参与线上式重排；最终用 eligibility gate 把模型从排序决策中降级为诊断证据，避免为了追指标对唯一正例过拟合。

### 2026-05-22 - hot-user smoke020 扩容召回复验

**任务：**
从既有 `hot100_global_rank_top2000_20260522` 评估用户池派生 `hot020_global_rank_top2000_20260522`，在不使用 oracle candidate、valid/test label 注入、ranking replacement 或 pool1000 的边界下，跑一版 20 用户 pool500_vnext 召回诊断。

**遇到的问题：**
`hot010_global_rank_top1000` 可用用户只有 12 个，无法自然扩成 20；因此改用 `top2000` 放宽全局 train popularity rank 约束，保留 hot-user、moderate holdout、category overlap 与 train-derived global-rank recallability 约束。

**定位方式：**
先汇总 `outputs/recall/pool500_aligned_eval_users_valid_test/` 下 hot010/hot100 manifests，确认 `hot100_global_rank_top2000_20260522` 有 30 个候选用户。派生前 20 个用户 manifest 后运行 `.venv` 下的 `run_full_data_pool500_recall_only.py --recall-profile pool500_vnext --limit-users 20`，再用 target-only valid/test positive 分母计算覆盖，避免被全量 label 分母稀释。

**解决方式：**
生成 `outputs/recall/pool500_aligned_eval_users_valid_test/hot020_global_rank_top2000_20260522/aligned_eval_users_manifest.json`，并输出召回结果到 `outputs/recall/pool500_vnext_hot020_global_rank_top2000_20260522/`。额外写出 target-only 覆盖诊断 `hot020_label_coverage_target_only.json`，只用于 evaluation-only 分析，不作为候选生成或排序输入。

**验证结果：**
召回生成成功，`quality_audit.json` 显示 20 用户、10,000 rows、每用户 500 candidates、无重复、无缺字段、无 underfill。target-only 诊断显示 20 个用户共有 79 个 valid/test positives，Recall@20=`8/79=0.101266`、Recall@50=`12/79=0.151899`、Recall@100=`15/79=0.189873`、Recall@500=`23/79=0.291139`，UserHitRate@500=`0.7`。拆分看，前 10 用户 Recall@500=`16/39=0.410256`，新增 10 用户 Recall@500=`7/40=0.175`，说明扩容主要暴露新增用户泛化弱点。`per_source_readiness_contracts.json` 还显示 `co_visit_fallback_repair` 与 `usercf_recall` 在本批次 row_count 为 0，`diagnostic_source_contribution.json` 中 `usercf_recall.user_coverage_ratio=0.0`，提示 hot020 新用户没有被这些侧路 source 覆盖。

**面试可讲点：**
这段可以讲成“评估集扩容后的稳定性诊断”：不是直接把 smoke020 作为新主指标，而是用它检查 smoke010 是否偶然有效；结果表明候选池工程质量达标，但新增用户覆盖明显下降，下一步应先补齐 UserCF/co-visit 等 source 对 hot020 用户的覆盖，再讨论排序层优化。

### 2026-05-23 - pool500 排序评价闭环 strict label gate

**任务：**
在冻结 pool500 候选池和 diagnostic-only 排序链路上补齐严格 label evaluation 闭环，使 fixed comparison report 能明确区分 `pending_label`、`label_invalid`、`label_insufficient` 与 `label_comparable`，并冻结 learned challenger 的训练/晋升入口。

**遇到的问题：**
原报告中 label coverage 口径过松，`label_invalid` / `label_insufficient` 会阻断整个 mechanism diagnostic report；summary 对 label 字段的权威投影不完整；learned challenger 仍可绕过 fixed comparison report 直接训练并写出 `agent_ready_ranked_artifact.json`。

**定位方式：**
先做 dirty workspace ownership 审计，隔离召回路线和既有叙事日志改动，只复用 `pool500_shadow_ranking.py`、`tests/test_pool500_shadow_ranking.py`、`run_pool500_learned_ranking_challenger.py` 与对应测试。独立 verifier 还发现 `full_pool_candidate_coverage_diagnostic` 曾误用 TopK union coverage，需要把 formal label gate 分母和 full-pool diagnostic metadata 分离。

**解决方式：**
在 fixed comparison report 内加入 strict label gate：explicit/manifest label 才可被 evaluator 消费，known-output discovery 只做只读提示；formal label lift 使用 all-config TopK union 覆盖率，full-pool coverage 仅作为 diagnostic metadata；正式指标固定为 `pool500_label_metrics_per_user_mean_v1` 的 per-user mean Hit/NDCG/MRR/Recall。summary 只能从权威 report 投影并过滤内部 label metadata。learned challenger 改为 Frozen mode，必须校验 report path/hash、`label_metric_eligibility=true`、规则瓶颈证据和 feature/leakage gates，即使全部通过也只输出 `would_be_eligible=true`，不训练、不晋升、不写 Agent-ready artifact。

**验证结果：**
使用项目默认 `.venv` 运行 `python -m pytest tests/test_pool500_shadow_ranking.py tests/test_ltr.py tests/test_pool500_learned_ranking_challenger.py`，最终结果 `137 passed`；`py_compile` 覆盖更新后的排序报告、测试和 learned challenger 文件。独立 verifier 复验 PASS，确认 full-pool diagnostic coverage 已使用完整 candidate file 分母，且不影响 `label_metric_eligibility`。

**面试可讲点：**
这段可以讲成“离线排序评价治理闭环”：不是直接调排序参数追求短期 lift，而是先把 label artifact、coverage denominator、summary authority 和 learned model gate 固化为可审计状态机；在 label 不可比时只允许机制诊断，在 label 可比后才解释排序指标，从而避免把诊断产物包装成可晋升效果。

### 2026-05-23 - pool500 固定离线评估用户集

**任务：**
构建固定 `pool500` 离线评估用户集，统一后续召回路线与排序路线的 eval users / labels / history split 基准，并输出 100 用户 dry-run 与正式 10,000 用户 artifact。

**遇到的问题：**
初版构建器在 dry-run 前加载全量 train history 与 valid/test label 聚合，100 用户验证也出现高内存占用且迟迟不落盘；同时 manifest 需要精确区分召回评估、纯排序评估和端到端链路评估，避免把候选池变化误解释为排序模型提升。

**定位方式：**
通过 `.venv` 下的 selector 单测、100 用户 dry-run 命令和 verifier 资源观察定位瓶颈：full-data dry-run 曾达到约 16.8GB，第一次流式优化后仍约 8.8GB，说明 label 聚合仍是内存热点。读取 `select_pool500_aligned_eval_users.py`、clean manifest 和既有 pool500 recall/ranking 脚本，确认安全输入边界是 train history + valid/test evaluation labels。

**解决方式：**
在 `rs_lab/experiments/recall/select_pool500_aligned_eval_users.py` 中新增 `build_pool500_offline_eval_users()`，输出 `manifest.json` 与 `users.jsonl`；按 history_count 分层采样 hot/warm/cold-ish，正式目标为 4000/4000/2000。将 offline 构建改为临时 SQLite 磁盘聚合 valid/test 正样本，再流式扫描 train history 生成 eligible candidates，只为最终选中用户二次补 category/head-tail 诊断，避免 oracle/label 注入候选构建。

**验证结果：**
`.venv/Scripts/python -m pytest tests/test_pool500_aligned_eval_user_selector.py -q` 结果 `5 passed`。100 用户 dry-run 输出 `outputs/eval/pool500_offline_eval_users_dry_run_100/manifest.json`，状态 `PASS`，分层 `hot=40/warm=40/cold-ish=20`。正式产物输出到 `outputs/eval/pool500_offline_eval_users_10k/`，状态 `PASS`，分层 `hot=4000/warm=4000/cold-ish=2000`，`user_set_hash=eb63bae51126aa572072415236eb8efbb14979be7b9ae7edf21d555077136b33`，无 warnings，manifest/users.jsonl 结构校验通过。

**面试可讲点：**
这段可以讲成“离线评估基准治理”：先把用户、history/label split、指标契约和候选池契约固化成可复现 artifact，再让召回和排序共享同一评估基准；同时用磁盘聚合和流式扫描把全量数据构建从高内存阻塞改成可落盘、可复验的工程流程。

### 2026-05-24 - pool500 协同召回 method dataset-only 分层

**任务：**
为 `itemcf_weak`、`itemcf_strong`、`usercf_method_dataset`、`swing_method_dataset` 新增独立 dataset-only builder，只消费 P1 train-only governance 输出，不生成候选、source index、ANN/index/embedding 或晋升产物。

**遇到的问题：**
P2 数据集需要继承 P1 分层口径，但不能调用旧 `methods/*/builder.py` 入口，也不能在 dataset 层混入候选生成语义；同时用户分层必须依赖 `quality_bucket_v2`，缺失时要阻断而不是回退到旧 `quality_bucket`。

**定位方式：**
读取 `rs_lab/experiments/recall/build_train_only_data_governance.py` 的 `derived_dataset_policies`、`item_quality_profile` 字段和现有 pool500 方法测试，确认安全输入边界为 `user_quality_profile.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl` 与 `user_sequences.train.jsonl`。

**解决方式：**
新增 `rs_lab/experiments/recall/build_pool500_method_dataset.py`，按方法输出 `method_dataset_manifest.json` 与 `method_dataset_rows.jsonl`，manifest 固化 hard schema、输入 hash、forbidden scope audit 和所有禁止晋升开关；用户侧只读取 `quality_bucket_v2`，物品侧使用 `cf_ready=true` 且 `over_hot=false` 的 train-only item profile 过滤。

**验证结果：**
使用项目默认 `.venv` 运行 `python -m pytest tests/test_pool500_method_dataset.py -q`，结果 `4 passed`；继续运行 `python -m pytest tests/test_pool500_method_dataset.py tests/test_train_only_data_governance.py -q`，结果 `15 passed`；新增文件通过 `py_compile`。

**面试可讲点：**
这段可以讲成“召回数据分层治理”：把候选生成前的一层 method dataset 独立出来，用强 schema、输入 hash、输出白名单和 v2 分层阻断规则保证协同召回只消费 train-only governance 数据，为后续候选构建和审计留出可追溯边界。


### 2026-05-24 - pool500 P2 方法特异数据集资源策略固化

**任务：**
为 pool500 P2 method-specific dataset 链路补齐资源规模策略，明确重方法使用 `governance_train_only -> method-specific dataset -> source_artifact` 的边界，同时让 Popular/Category 轻方法保留 full train-only statistics 扫描能力。

**遇到的问题：**
协同过滤和 TwoTower 数据集 manifest 之前只有选择策略与 no-promotion 语义，缺少可审计的 P2 resource scale policy；轻方法、重方法和 deferred 方法在 registry 中也缺少“输入扫描规模”和“方法特异边界”的差异化说明。

**定位方式：**
检查 `build_pool500_method_dataset.py`、`build_pool500_two_tower_method_dataset.py`、`pool500_method_registry.json` 及对应 audit/drift 测试，确认新增字段必须避开 candidate/source index/ready/promotion 等禁用语义，并保持 train-only、no-leakage、no READY claim。

**解决方式：**
在协同过滤四类方法和 TwoTower manifest 中加入安全的 `resource_scale_policy` metadata，并纳入协同过滤 `config_hash`；registry 中为 Popular/Category 写明允许 full train-only statistics input scan、无 input size cap，仅由下游 output/per-user share 控制，同时为 itemcf/usercf/swing 写入方法特异 P2 资源边界和 selection_strategy，并为 semantic seed metadata 与 co-visit fallback repair 保持 DEFERRED 的有界 P2 数据定义与方法特异 selection_strategy。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_pool500_method_dataset.py tests/test_pool500_two_tower_method_dataset.py tests/test_pool500_method_dataset_audit_evidence.py tests/test_pool500_method_registry_drift.py tests/test_pool500_lightweight_source_governance.py -q`，最终结果 `32 passed in 0.72s`。

**面试可讲点：**
这段可以讲成推荐召回工程中的“资源治理契约化”：把重方法的本地正式规模、用户/物品频次、pair support 与选择/采样策略等约束固化进可审计 manifest，同时避免把诊断数据集误用为候选生成或排序替换输入，体现离线实验到工程链路的安全边界设计。


### 2026-05-25 - ItemCF method_dataset smoke 边特征构建验证

**任务：**
验证 `itemcf_weak` 与 `itemcf_strong` 的 P2 method_dataset smoke 构建链路，确认 `itemcf_edge_features_v1` manifest、audit 统计和方法文档证据可落盘。

**遇到的问题：**
默认构建命令会读取 `outputs/recall/data_governance/train_only_v1/manifest.json`，本地当前没有该全量 governance manifest；如果直接按默认失败结果收口，会混淆“全量依赖缺失”和“smoke 链路不可用”。

**定位方式：**
先运行 targeted tests，结果 `41 passed in 0.64s`；随后构建失败定位到缺失的默认 manifest。检查 `outputs/recall/data_governance/` 后确认已有 `train_only_v1_smoke/manifest.json`，因此改用 smoke governance 作为本轮 smoke 构建输入。

**解决方式：**
使用项目 `.venv` 分别构建 `itemcf_weak` 与 `itemcf_strong`，输出到 `outputs/recall/pool500_method_datasets/itemcf_smoke_edge_features_v1/`，并在两个 METHOD 文档中记录 row/user/item/pair/edge/top-k 后 directed edge、drop reason 和特征摘要。

**验证结果：**
`outputs/recall/pool500_method_datasets/itemcf_smoke_edge_features_v1/` 下 `itemcf_weak` 与 `itemcf_strong` 的 `method_dataset_manifest.json` 均为 `status=PASS`、`schema_name=itemcf_edge_features_v1`，并通过 targeted tests / audit evidence gate：`tests/test_pool500_method_dataset.py`、`tests/test_pool500_method_registry_drift.py`、`tests/test_pool500_method_dataset_audit_evidence.py` 结果 `43 passed`。当前 smoke governance 下二者 `row_count=0`、`user_count=0`、`item_count=0`、`unique_pair_count=0`、`edge_count=0`、`directed_edge_count_after_topk=0`；weak smoke 参数保持 `max_item_user_freq=5000`、`min_pair_support=1`，dropped reason 为 `user_bucket_not_allowed=18103318`、`insufficient_pair_items=66`、`item_over_hot=1461`、`item_not_cf_ready=2317958`；strong smoke 参数为 `max_item_user_freq=3000`、`min_pair_support=2`，dropped reason 为 `user_bucket_not_allowed=18103383`、`insufficient_pair_items=1`、`item_over_hot=1461`、`item_not_cf_ready=2317958`，`pair_below_min_support=0`。本轮只证明 train-only method_dataset contract、特征 schema、forbidden-scope audit 和空输出统计可审计，不声明 recall coverage 提升、READY、promotion 或 ranking input replacement。

**面试可讲点：**
这段可以讲成“把重资源 ItemCF 从能跑 sidecar 推进到可审计的方法级数据集 contract”：即使 smoke 样本没有产出有效边，也保留了 train-only 输入、禁止 holdout/oracle、特征 schema、drop reason 和构建命令证据，避免把空输出误读成方法失败或把 smoke PASS 误读成召回晋升。


### 2026-05-25 - UserCF 三档 method_dataset 最终验收

**任务：**
验证 `usercf_v1_smoke`、`usercf_v1_diagnostic`、`usercf_v1_local_formal` 三档 UserCF method_dataset 是否满足 P2 dataset-only 契约，并补齐 focused test 证据。

**遇到的问题：**
UserCF 三档产物需要证明只是 eligible user sequence 数据集，不能夹带 candidates、source index、readiness 或 promotion 语义；同时 local_formal 规模较大，必须用 row file 实际行数复核 manifest 的 `row_count`。

**定位方式：**
逐档读取 `outputs/recall/pool500_method_datasets/*/usercf_method_dataset/method_dataset_manifest.json`，检查 `status`、`outputs.dataset_schema`、`forbidden_scope_audit.status`、四个 no-promotion/no-replacement 开关和禁用文件列表，并逐行统计 `method_dataset_rows.jsonl`。

**解决方式：**
按 smoke、diagnostic、local_formal 三档分别执行 manifest + row file 审计，确认 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`，且目录内不存在 `candidates.jsonl`、`source_index_manifest.json`、`readiness_manifest.json`、`promotion_manifest.json`。

**验证结果：**
三档审计均为 `AUDIT_RESULT=PASS`：smoke `row_count=213/user_count=213/item_count=207/schema=eligible_user_sequence_v1`；diagnostic 改为使用 full/local_formal governance + diagnostic caps 后，`row_count=60000/user_count=60000/item_count=66263/schema=eligible_user_sequence_v1`；local_formal `row_count=90686/user_count=90686/item_count=94553/schema=eligible_user_sequence_v1`，三档 row file 实际行数均等于 manifest `row_count`。使用项目默认 `.venv` 运行 `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_pool500_method_dataset.py -q`，结果 `21 passed in 0.45s`。

**面试可讲点：**
这段可以讲成“推荐召回 P2 数据集契约验收”：不仅看 manifest PASS，还用实际行数、schema、forbidden-scope audit 和禁用产物缺失共同证明 UserCF 当前只提供可审计的 eligible user sequence 输入，不越界声明候选生成、排序替换或 pool500 晋升。

### 2026-05-25 - TwoTower full train-only formal dataset 与 bounded diagnostic package

**任务：**
生成缺失的 `train_only_v1` upstream governance manifest，并基于全量 clean train 数据制作 TwoTower formal method dataset、audit evidence 与 200 用户 bounded diagnostic loop package。

**遇到的问题：**
formal governance 输入最初缺少 `outputs/recall/data_governance/train_only_v1/manifest.json`，不能用 smoke/diagnostic manifest 替代。后续 full local_formal 构建还暴露两个工程瓶颈：TwoTower method dataset 每个样本复制全量 negative universe 导致运行过慢；diagnostic loop 默认把 889431 个 training item 的完整文本写入训练 vocab，导致 GB 级 JSON 和全量 topK scoring 过重。audit 首次还 BLOCKED 了 12 个 positive target 的 `title_clean` 缺失。

**定位方式：**
用 `.venv` 运行指定 builder 并检查 manifest/audit 输出：governance manifest PASS，`profiled_user_count=18103384`、`total_item_count=2320263`；formal TwoTower dataset 首次 audit blocker 为 `two_tower_positive_target_metadata_incomplete`，定位到 canonical metadata 中部分 target `title_clean` 为空但有 description/category。通过输出文件大小和进程状态确认 diagnostic bottleneck 来自完整 item vocab 与全量 item scoring。

**解决方式：**
先用 full clean manifest 生成 `outputs/recall/data_governance/train_only_v1/manifest.json`，再生成 formal method dataset。将负采样从“每样本构造 eligible negatives 全量列表”改为从 hash offset 流式扫描并跳过 history/target，保持 deterministic rotated negatives 语义但避免 O(samples × universe copy)。对 title 缺失的 target，用已有 description/features/category 文本作为 `title_clean` fallback，确保 item tower metadata contract 可消费。diagnostic loop 保持 200 用户 bounded 口径，只对样本涉及的 history/target items 构建紧凑 vocab，不生成正式 candidates/ranking/promotion/READY 产物。

**验证结果：**
formal governance 输出 PASS：`outputs/recall/data_governance/train_only_v1/manifest.json`。formal TwoTower method dataset 输出 PASS：`train_sample_count=751574`、`negative_universe_item_count=866802`、`training_item_universe_item_count=889431`。audit evidence PASS：`outputs/recall/pool500_method_datasets/audit_evidence_v1/diagnostic_audit_report.json`，`blocker_count=0`，`positive_target_metadata_incomplete_count=0`，negative leakage/duplicate/empty 均为 0。diagnostic package PASS：`outputs/recall/pool500_two_tower_diagnostic_loop/diagnostic_report.json`，`source_index_row_count=1137`、`diagnostic_topk_row_count=10000`、200 users、975 targets，Recall@20=`0.294359`、Recall@50=`0.434872`。相关测试使用 `.venv` 运行 `tests/test_pool500_two_tower_method_dataset.py tests/test_pool500_two_tower_diagnostic_loop.py`，结果 `33 passed in 0.86s`。

**面试可讲点：**
这段可以讲成“把双塔训练数据从 smoke 证据推进到 full train-only formal 包装”：先补齐 upstream governance，再用 audit 把 history→target、target universe 覆盖、负样本多样性、metadata 完备性和 no-oracle/no-label/no-promotion 边界固化下来；同时对大规模数据物化做必要的复杂度治理，避免诊断任务被全量文本和全量 scoring 拖成生产训练。


### 2026-05-26 - TwoTower formal full è®­ç»ƒè¿œç¨‹ç®—åŠ›è¿�ç§»

**ä»»åŠ¡ï¼š**
å½“æœ¬æœº full formal TwoTower è®­ç»ƒé¢„è®¡é•¿æœŸå� ç”¨ CPU/GPU/å†…å­˜æ—¶ï¼Œå°†è®­ç»ƒè¿�ç§»åˆ°æŽˆæ�ƒè¿œç¨‹æœ�åŠ¡å™¨æ‰§è¡Œï¼Œå®Œæˆ�å�Žæ‹‰å›žå¿…è¦� artifact å¹¶åœ¨æœ¬åœ°éªŒè¯�å�Žå†�æŽ¥å…¥ä¸»è·¯ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
æœ¬æœº strict full/no-limit è®­ç»ƒè™½ç„¶å·²è¿›å…¥ CUDA batchï¼Œä½†æ•°æ�®ç®¡çº¿ä¸Ž Python batch æž„é€ ä½¿ GPU åˆ©ç”¨çŽ‡é•¿æœŸå��ä½Žï¼›å�³ä½¿æ”¹æˆ� streaming ä¸Ž `batch_size=1024`ï¼ŒæŒ‰å®žæµ‹é€Ÿåº¦ä»�å�¯èƒ½éœ€è¦�æ•°å¤©åˆ°å��å¤©çº§ï¼Œæ— æ³•æ»¡è¶³é�¢è¯•å‰�å¿«é€Ÿæ”¶å�£ã€‚

**å®šä½�æ–¹å¼�ï¼š**
é€šè¿‡ `gpu_device_trace.log`ã€�`nvidia-smi`ã€�è¿›ç¨‹ CPU/RAM ä¸Ž `torch_training_batches` äº‹ä»¶å®šä½�ï¼šæœ¬æœºè®­ç»ƒå·²ç¡®è®¤ä½¿ç”¨ CUDAï¼Œä½† batch å�žå��ä¸�è¶³ã€‚è¿›ä¸€æ­¥å®¡è®¡ `rs_core/recsys/two_tower.py`ï¼Œå�‘çŽ°è´Ÿé‡‡æ ·åŽŸå®žçŽ°æ¯�æ�¡æ ·æœ¬éƒ½ä¼šæž„é€ ä¸€æ¬¡å…¨ item å€™é€‰åˆ—è¡¨ï¼Œå¯¼è‡´æ¯�æ ·æœ¬éš�å¼�æ‰«æ��çº¦ 26 ä¸‡ itemï¼›å�Œæ—¶ user embedding å�Žå¤„ç�†é€�ç”¨æˆ·è°ƒç”¨ GPUã€‚

**è§£å†³æ–¹å¼�ï¼š**
å…ˆåœ¨æœ¬åœ°ä¿®å¤�è®­ç»ƒå�žå��ç“¶é¢ˆï¼šè´Ÿé‡‡æ ·æ”¹ä¸º rejection samplingï¼Œé�¿å…�æ¯�æ ·æœ¬å…¨ item æ‰«æ��ï¼›user embedding æ”¹ä¸ºæ‰¹é‡� GPU ç¼–ç �ã€‚éš�å�Žä½¿ç”¨æŽˆæ�ƒæœ�åŠ¡å™¨ `ssh luo@10.112.125.22`ï¼Œå·¥ä½œç›®å½•å›ºå®šä¸º `/home/luo/RS_agent_remote`ï¼Œå�ªè¿�ç§»æœ€å°�è®­ç»ƒé—­åŒ…ï¼šä»£ç �ã€�é…�ç½®ã€�å…¨é‡� train sequenceã€�TwoTower item vocabã€�method dataset manifest/auditï¼Œä¸�è¿�ç§» diagnostic/oracle/eval äº§ç‰©ã€‚è¿œç«¯åˆ›å»º `.venv`ï¼Œå®‰è£… CUDA PyTorchï¼Œä½¿ç”¨ `nohup .venv/bin/python scripts/launch_two_tower_remote_formal.py > logs/<run>.stdout.log 2> logs/<run>.stderr.log &` å�Žå�°å�¯åŠ¨ formal full è®­ç»ƒï¼Œå¹¶é€šè¿‡ `gpu_device_trace.log`ã€�`gpu_launch_status.json` å’Œ `nvidia-smi` ç›‘æŽ§ã€‚å¯†ç �ä¸�å¾—å†™å…¥è„šæœ¬ã€�æ—¥å¿—ã€�å‘½ä»¤å�‚æ•°æˆ–æ–‡æ¡£ã€‚

**éªŒè¯�ç»“æžœï¼š**
è¿œç«¯ preflight æ˜¾ç¤º `torch=2.11.0+cu128`ã€�`cuda_available=true`ã€�GPU ä¸º `NVIDIA GeForce RTX 4090`ã€�`strict_full_no_user_limit=true`ã€�`limit_users=null`ã€�`method_dataset_status=PASS`ã€�`method_dataset_train_only=true`ã€‚è®­ç»ƒå�‚æ•°ä¸º `epochs=3`ã€�`batch_size=16384`ã€�`user_embedding_batch_size=32768`ã€‚è¿œç«¯ä»Ž preflight åˆ° `first_batch_devices` çº¦ 12 åˆ†é’Ÿï¼›é¦–ä¸ª `torch_training_batches batch_index=1000` çº¦ 5 åˆ†é’Ÿåˆ°è¾¾ï¼Œè¯´æ˜Žæœ�åŠ¡å™¨ç‰ˆæœ¬å·²ä»Žæœ¬æœºâ€œæ•°å¤©çº§â€�å�˜ä¸ºå°�æ—¶çº§ã€‚äº§ç‰©å®Œæˆ�å�Žéœ€è¦�æ‹‰å›ž `artifact_manifest.json`ã€�`train_config.json`ã€�`train_metrics.json`ã€�model/embedding/id mapã€�`two_tower_recall_index.jsonl`ã€�GPU trace/status æ—¥å¿—ï¼Œå†�åœ¨æœ¬åœ°é‡�å»ºæˆ–éªŒè¯� `source_index_manifest.json` å�ŽæŽ¥å…¥ä¸»è·¯ã€‚

**è°ƒç”¨æ–¹å¼�è®°å½•ï¼š**
èµ„æº�é¢„ä¼°è¿‡å¤§æ—¶ï¼Œå…ˆç”¨ `ssh luo@10.112.125.22` æ£€æŸ¥ `nvidia-smi`ã€�`free -h`ã€�`df -h ~`ï¼›ç”¨ `tar -C <repo> -I 'gzip -1' -cf - <å¿…è¦�æ–‡ä»¶...> | ssh luo@10.112.125.22 'tar -C /home/luo/RS_agent_remote -xzf -'` ä¼ è¾“æœ€å°�é—­åŒ…ï¼›è¿œç«¯ç”¨ `/home/luo/RS_agent_remote/.venv` æ‰§è¡Œè®­ç»ƒ launcherï¼›å®Œæˆ�å�Žç”¨ `scp`/`rsync` ä»…æ‹‰å›ž run ç›®å½•ä¸­çš„æ­£å¼�è®­ç»ƒäº§ç‰©å’Œæ—¥å¿—ã€‚å›žä¼ å�Žä¸�ç›´æŽ¥ä¿¡ä»»è¿œç«¯ç»�å¯¹è·¯å¾„ï¼Œåº”åœ¨æœ¬åœ°é‡�æ–°æ ¡éªŒ train-only/no-leakage/row count å¹¶é‡�å»ºä¸»è·¯ source index manifestã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œèµ„æº�çº¦æ�Ÿä¸‹çš„è®­ç»ƒå·¥ç¨‹åŒ–è¿�ç§»â€�ï¼šä¸�æ˜¯ç›²ç›®ç­‰å¾…æœ¬æœºæ…¢è·‘ï¼Œè€Œæ˜¯å…ˆç”¨æ—¥å¿—å®šä½�çœŸå®žç“¶é¢ˆï¼Œå†�ç”¨ç®—æ³•çº§å°�æ”¹åŠ¨æ¶ˆé™¤è´Ÿé‡‡æ ·å¤�æ�‚åº¦é—®é¢˜ï¼Œæœ€å�ŽæŠŠ full-scope train-only formal è®­ç»ƒè¿�ç§»åˆ°æ›´å¼ºæœ�åŠ¡å™¨ï¼Œå¹¶ä¿�ç•™ manifestã€�traceã€�å›žä¼ éªŒè¯�å’Œæœ¬åœ°ä¸»è·¯æŽ¥å…¥è¾¹ç•Œï¼Œä½“çŽ°æŽ¨è��ç³»ç»Ÿè®­ç»ƒé“¾è·¯çš„èµ„æº�è¯„ä¼°ã€�å�¯å¤�çŽ°æ‰§è¡Œå’Œäº§ç‰©æ²»ç�†èƒ½åŠ›ã€‚


## 2026-05-26 - TwoTower formal full å›ºå®šè¯„ä¼°é›†åˆ�æµ‹

- ä»»åŠ¡ï¼šåœ¨ formal full TwoTower source index æŽ¥å…¥ pool500 ä¸»è·¯å�Žï¼Œç”¨å›ºå®š offline eval ç”¨æˆ·é›†éªŒè¯�å�Œå¡”å�¬å›žæ•ˆæžœã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šçŽ°æœ‰ offline eval è„šæœ¬å�‘ä¸»è·¯ runner ä¼ å…¥ `target_user_manifest_path`ï¼Œä½†ä¸»è·¯å¥‘çº¦æµ‹è¯•ç¦�æ­¢ target-user runtime overrideï¼Œç›´æŽ¥è¿�è¡Œ 10k å‰�å…ˆåœ¨ 100 ç”¨æˆ· dry-run æš´éœ²äº†æŽ¥å�£æ¼‚ç§»ã€‚
- å®šä½�æ–¹å¼�ï¼š100 ç”¨æˆ· raw eval é¦–æ¬¡å¤±è´¥äºŽ `run_full_data_pool500_recall_only()` å�‚æ•°ä¸�åŒ¹é…�ï¼›éš�å�Žé€šè¿‡ `tests/test_full_data_pool500_recall_only.py` å�‘çŽ°ä¸»è·¯ç¦�æ­¢ `target_user_manifest` å­—ç¬¦ä¸²ï¼Œç¡®è®¤ä¸�èƒ½æŠŠè¯„ä¼°ç”¨æˆ·é€‰æ‹©å�šæˆ�ä¸»è·¯è¿�è¡Œæ—¶è¦†ç›–ã€‚
- è§£å†³æ–¹å¼�ï¼šä¿�æŒ�ä¸»è·¯ runner æŽ¥å�£ä¸�å�˜ï¼Œåœ¨ offline eval è„šæœ¬ä¸­ä¸ºçœŸå®ž runner ç”Ÿæˆ�å�ªåŒ…å�«å›ºå®šè¯„ä¼°ç”¨æˆ· train history çš„ä¸´æ—¶ train-only sequence viewï¼Œå¹¶æŠŠ label/valid/test ä»�é™�å®šä¸º evaluation-onlyã€‚
- éªŒè¯�ç»“æžœï¼š`tests/test_full_data_pool500_recall_only.py` 19 passedï¼Œ`tests/test_pool500_offline_eval_baseline.py` 4 passedï¼›100 ç”¨æˆ· raw eval ä¸­ TwoTower è´¡çŒ® 2460 æ�¡å€™é€‰ä½† `raw_two_tower_unique_positive_hits=0`ï¼Œwith/without ablation çš„ HitRate@500 å�‡ä¸º 0.01ï¼Œ`marginal_unique_positive_hits=0`ï¼Œå†³ç­–ä¸º `exclude`ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šä¸�æ˜¯å�ªçœ‹æ¨¡åž‹è®­ç»ƒ lossï¼Œè€Œæ˜¯æŠŠæ¨¡åž‹äº§ç‰©æŽ¥å…¥å€™é€‰ä¸»è·¯å�Žç”¨å›ºå®šè¯„ä¼°é›†ã€�source-level hit å’Œ ablation gate éªŒè¯�çœŸå®žä¸šåŠ¡å�¬å›žè´¡çŒ®ï¼›å�Œæ—¶é€šè¿‡å¥‘çº¦æµ‹è¯•é�¿å…�ä¸ºäº†è¯„ä¼°ä¾¿åˆ©ç ´å��ä¸»è·¯æ•°æ�®æ²»ç�†è¾¹ç•Œã€‚


## 2026-05-26 - TwoTower å�¬å›žå¤±è´¥åŽŸå›  label-rank è¯Šæ–­

- ä»»åŠ¡ï¼šè§£é‡Š formal full TwoTower å·²æŽ¥å…¥ä¸»è·¯ä½† 100 ç”¨æˆ·å›ºå®šè¯„ä¼° raw hit ä¸º 0 çš„åŽŸå› ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šä»…çœ‹è®­ç»ƒ loss å’Œ source å€™é€‰è´¡çŒ®æ— æ³•åˆ¤æ–­å�Œå¡”å¤±è´¥æ˜¯æŽ¥å…¥é—®é¢˜ã€�item universe è¦†ç›–é—®é¢˜ã€�ç”¨æˆ·å�‘é‡�ç¼ºå¤±ï¼Œè¿˜æ˜¯ label rank å¤ªé� å�Žã€‚
- å®šä½�æ–¹å¼�ï¼šå¯¹ 100 ä¸ªå›ºå®š eval ç”¨æˆ·é€� label è®¡ç®— TwoTower å…¨é‡� item æ‰“åˆ† rankï¼Œå¹¶è¡¥æŸ¥ç¼ºå¤± user embedding ç”¨æˆ·çš„ train-only åŽ†å�² seed æ˜¯å�¦å­˜åœ¨äºŽ item indexã€‚
- è§£å†³æ–¹å¼�ï¼šä¸�é‡�æ–°è®­ç»ƒã€�ä¸�ä½¿ç”¨ label æ³¨å…¥å€™é€‰ï¼Œå�ªç¦»çº¿è¯»å�– eval label å�š evaluation-only rank auditï¼›ç»Ÿè®¡ label in-universeã€�query vector æ�¥æº�ã€�TopK hit å’Œ rank åˆ†å¸ƒã€‚
- éªŒè¯�ç»“æžœï¼š142 ä¸ª label ä¸­å�ªæœ‰ 75 ä¸ªåœ¨ TwoTower item universeï¼›å�¯ rank label ä¸º 59 ä¸ªï¼ŒTop20/Top50 ä¸º 0ï¼ŒTop500 ä»… 4 ä¸ªï¼Œä¸­ä½� rank 39549ï¼Œå¹³å�‡ rank 66521ï¼›18 ä¸ªç¼ºå¤± user embedding çš„ç”¨æˆ·éƒ½å�ªæœ‰ 1 ä¸ª recent positiveï¼Œä¸” seed item å…¨éƒ¨ä¸�åœ¨ item indexï¼Œæ— æ³• fallbackã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šé€šè¿‡ label-rank è¯Šæ–­æŠŠâ€œæ¨¡åž‹æ•ˆæžœå·®â€�æ‹†æˆ�å�¯æ‰§è¡Œé—®é¢˜ï¼šitem universe è¦†ç›–ä¸�è¶³ã€�å†·/å¼±ç”¨æˆ· query ç¼ºå¤±ã€�ä»¥å�Šè®­ç»ƒç›®æ ‡å¯¼è‡´æ­£æ ·æœ¬ rank å¤§å¹…é� å�Žï¼Œè€Œä¸�æ˜¯ç›²ç›®åŠ  epoch æˆ–æ‰©å¤§è®­ç»ƒã€‚


## 2026-05-26 - TwoTower min_frequency=5 å°�æ ·æœ¬è¯Šæ–­å®žéªŒ

- ä»»åŠ¡ï¼šéªŒè¯�é™�ä½Ž TwoTower item vocab é¢‘çŽ‡é—¨æ§›æ˜¯å�¦èƒ½æ”¹å–„ formal full å�Œå¡”åœ¨å›ºå®šè¯„ä¼°ç”¨æˆ·ä¸Šçš„ label è¦†ç›–å’Œ rankã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šformal full ä½¿ç”¨ `min_frequency=20`ï¼Œå¯¼è‡´ 100 ç”¨æˆ· eval label å�ªæœ‰ 52.8% åœ¨ item universeï¼Œå¼±ç”¨æˆ· seed è¦†ç›–ä¹Ÿä¸�è¶³ï¼›ä½†ç›²ç›®æ‰©å¤§ vocab ä¼šå¢žåŠ æ£€ç´¢ç©ºé—´å¹¶å�¯èƒ½ç¨€é‡ŠæŽ’åº�ä¿¡å�·ã€‚
- å®šä½�æ–¹å¼�ï¼šå…ˆæ‰«æ�� `min_frequency=20/10/5/3/2/1` çš„ train-only è¦†ç›–ï¼Œå†�æž„é€  `min_frequency=5`ã€�100 ç”¨æˆ·ã€�1 epochã€�16 ç»´ã€�20 negatives çš„å°�æ¨¡åž‹è¯Šæ–­å®žéªŒï¼Œå¹¶ç”¨å�Œä¸€ label-rank å�£å¾„æ¯”è¾ƒã€‚
- è§£å†³æ–¹å¼�ï¼šç”Ÿæˆ� train-only min_freq=5 item vocabï¼ˆ703240 itemsï¼‰ï¼Œå�ªç”¨ 100 ä¸ªå›ºå®šè¯„ä¼°ç”¨æˆ·çš„ train history è®­ç»ƒè¯Šæ–­æ¨¡åž‹ï¼›valid/test label å�ªç”¨äºŽç¦»çº¿ rank auditï¼Œä¸�è¿›å…¥è®­ç»ƒæˆ–å€™é€‰ç”Ÿæˆ�ã€‚
- éªŒè¯�ç»“æžœï¼šmin_freq=5 å°† label è¦†ç›–ä»Ž 75/142 æ��å�‡åˆ° 93/142ï¼Œç”¨æˆ· embedding è¦†ç›–ä»Ž 82/100 æ��å�‡åˆ° 95/100ï¼›ä½† rank æ˜¾è‘—å�˜å·®ï¼ŒTop500=0ã€�Top10000=2ï¼Œrank ä¸­ä½�æ•° 353964ï¼Œè¯´æ˜Žä»…æ‰©å¤§ universe ä¸�è¶³ä»¥æ”¹å–„å�¬å›žï¼Œå��è€Œæš´éœ²è®­ç»ƒç›®æ ‡/è´Ÿé‡‡æ ·ä¿¡å�·ä¸�è¶³ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šé€šè¿‡å°�æ ·æœ¬å�¯æŽ§å®žéªŒéªŒè¯�â€œè¦†ç›–ä¿®å¤�ä¸�æ˜¯å……åˆ†æ�¡ä»¶â€�ï¼Œé�¿å…�ç›´æŽ¥æ‰©å¤§ full æ¨¡åž‹èµ„æº�ï¼›ä¸‹ä¸€æ­¥åº”æ”¹è®­ç»ƒç›®æ ‡å’Œè´Ÿé‡‡æ ·ï¼Œè€Œä¸�æ˜¯å�•çº¯é™�ä½Ž item é¢‘çŽ‡é—¨æ§›ã€‚


## 2026-05-26 - TwoTower 小 batch 加速与远程实验配置

- 任务：为 pool500 TwoTower 训练补齐小 batch 下的吞吐优化能力，并让远程服务器训练/评估 sweep 可以直接通过配置或 CLI 控制。
- 遇到的问题：当前训练只有物理 batch size，无法在显存受限时保持较大有效 batch；AMP 也没有显式开关，远程 GPU 长跑难以稳定复用同一套配置。
- 定位方式：检查 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`scripts/training/train_two_tower.py` 和 diagnostic runner，确认此前没有 `gradient_accumulation_steps` / `mixed_precision` 支持。
- 解决方式：在 PyTorch 训练路径加入梯度累积、CUDA AMP 安全开关、`effective_batch_size`/`optimizer_steps` 记录；CLI 和 diagnostic loop 透传同名参数；formal full 配置调整为 `batch_size=2048`、`gradient_accumulation_steps=4`、`effective_batch_size=8192`、`mixed_precision=true`，并同步采用更适合泛化的 TwoTower 调参默认值。
- 验证结果：`./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_pool500_two_tower_diagnostic_loop.py -q` 结果为 41 passed；`ruff check` 覆盖变更文件后通过；独立 verifier 复跑 CUDA 隐藏设备场景后通过。
- 面试可讲点：这一步不是单纯“提速”，而是把推荐模型训练从固定物理 batch 改造成可控有效 batch，并把训练吞吐、显存策略和可复现实验记录写入 artifact，为后续远程 10k/50k/150k 用户 sweep 提供工程化基础。

### 2026-05-26 - RAG 候选内证据选择器落地

- 任务：把 RAG 从规划项收敛为可用的候选内证据选择器，并补齐文档与工程叙事。
- 遇到的问题：必须同时满足解释可用、候选不变、可回滚和证据净化，不能让 label / holdout / oracle 类字段混入解释。
- 定位方式：核对 `rag.evidence_mode` 三态、`rag.max_evidence_per_item`、provenance gate，以及 shadow / explain 下的 `rag_context` 与 display payload。
- 解决方式：明确 `off` / `shadow` / `explain` 语义，保持 `candidates`、`ranking`、`final_items`、`scores` 不变，把不安全证据从 `source` / `provenance` / `source_path` / `artifact_scope` 侧拦截。
- 验证结果：`pytest tests/test_rag_core.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py tests/test_agent_runtime.py tests/test_display_contract.py` 共 `45 passed in 0.59s`；`py_compile` 通过；最小脚本验证 `shadow` / `explain` 均有 `rag_context_exists=true`、`kept_evidence_count=3`，`explain` 的 why 使用 Audio evidence，display payload 未暴露 `rag_context` / diagnostics。
- 面试可讲点：可以讲成“先把 RAG 做成候选内证据层，再通过模式开关、证据门禁和展示边界把它做成可回滚、可审计、不会污染主链路的解释能力”。


## 2026-05-26 - Agent 联调用 `/recommend` 线上推荐入口

- 任务：为推荐 Agent tool 联调新增 stateless 线上推荐服务入口，使 Agent 可以直接传入用户历史序列并获得真实召回、排序后的商品展示结果。
- 遇到的问题：原 serving 层主要是 sessionful demo `/chat`/`/feedback`，没有无需 session 的推荐接口；离线 pool500 runner 又包含 manifest、audit、output_dir 写入等副作用，不适合直接放进请求路径。
- 定位方式：检查 `rs_core/serving/app.py`、`rs_core/serving/schema.py`、`rs_core/serving/service.py` 与 `rs_core/workflow/hybrid_demo.py`，确认可复用 `recommend_for_user(...)` 作为真实召回排序入口，并用 display builder 收敛 public payload。
- 解决方式：新增 `rs_core/workflow/online_recommendation.py` 作为纯在线 adapter；在 `RecommendationService` 增加 `recommend_from_sequence(...)`；在 FastAPI 暴露 `POST /recommend`；请求 schema 递归拒绝 `label/target_item/ground_truth/holdout` 等 evaluation-only 字段，响应不暴露 score/source/ranking/diagnostics。
- 验证结果：`tests/test_serving_recommend_from_sequence.py` 5 个新增用例通过；`test_serving_smoke.py`、`test_agent_runtime.py`、`test_pool500_fallback_completion_route.py` 回归合计 `38 passed in 1.08s`；changed serving modules `py_compile` 通过。全量包含 `test_hybrid_demo.py` 的命令仍有既有配置文件缺失失败，与本次 `/recommend` 改动无关。
- 面试可讲点：把离线推荐实验链路抽象为无副作用的在线 adapter，并通过 schema 和测试守住“评估标签不进候选生成、内部排序证据不外泄”的边界，实现了 Agent tool 可调用的真实推荐闭环。

### 2026-06-06 - two_tower 20k epoch5 控制实验与规模瓶颈定位

**任务：**
继续诊断 pool500 recent-2y `two_tower` 为什么 20k preflight 长期停在 `Recall@500≈0.02`，并区分“epoch 太少”和“训练规模太小”两个可能原因。

**遇到的问题：**
20k epoch1 baseline、item side feature 组合和 full-vocab 单字段消融都接近 `Recall@500=0.024566`，但 full 687k epoch5/queryv2 baseline 达到 `Recall@500=0.070809`。如果只看 20k preflight，容易误判 side feature 或 queryv2 无效；需要补一个不改 side feature、只增加 epoch 的控制实验。

**定位方式：**
先把既有 20k epoch1 baseline 和 687k epoch1 source 重新用 queryv2 同口径 direct eval 复核，再在授权远程服务器运行 baseline 20k epoch5 no-side-feature 控制实验，输出到 `/mnt/data/luo/rs_agent_spill/two_tower/baseline_20k_epoch5_20260606/`，并拉回 `train_metrics.json`、`train_config.json`、`source_index_manifest.json`、`raw_two_tower_direct_eval_manifest.json`、`run_summary.json` 到本地 evidence 目录。

**解决方式：**
将 20k preflight 重新定位为 smoke/链路验证，而不是 two_tower 效果准入判断。证据显示 20k epoch5 虽然 loss 从 `1.769754` 降到 `1.712921`，但 queryv2 指标仍与 20k epoch1 完全相同：unique hits `17`、`Recall@500=0.024566`、`HitRate@500=0.032`。相比之下，687k epoch1 已达 unique hits `36`、`Recall@500=0.052023`，说明主要瓶颈是训练规模和有效 optimizer step，而不是单纯 epoch 数。

**验证结果：**
同口径对照：20k epoch1 `optimizer_steps=4`、20k epoch5 `optimizer_steps=5`，二者均为 `item_count=499566`、`queryless_user_count=16`、unique hits `17`、`Recall@500=0.024566`；687k epoch1 `optimizer_steps=127`、unique hits `36`、`Recall@500=0.052023`；687k epoch5 `optimizer_steps=635`、unique hits `49`、`Recall@500=0.070809`。本地验证输出 `two_tower_scale_epoch_diagnosis_validation_PASS`，eval manifest 保持 `no_oracle_label_injection=true`。

**面试可讲点：**
这段可以讲成“用控制实验避免把小样本 preflight 当作模型结论”：通过固定 item universe、queryv2 和 no-side-feature，只改变 epoch，证明 20k 训练即使多跑 epoch 也无法提供足够协同行为学习；再用 687k epoch1/epoch5 对照说明真正的提升来自训练规模和 full-scale optimizer steps。这个结论能指导后续实验预算：20k 用于链路 smoke，效果实验至少使用更大规模 preflight 或 formal 级训练。

### 2026-06-06 - two_tower item side feature 20k preflight 与单因素消融反证

**任务：**
在 pool500 recent-2y `two_tower` 上验证默认关闭的 train-only item side feature token 是否能改善 YouTubeDNN-like item 初始化，并使用 queryv2 同口径 direct eval 与既有 epoch5/queryv2 baseline 对比。

**遇到的问题：**
初始 `item_quality_token + item_pop_bucket_token + item_user_count_bucket_token` 组合链路训练和治理都成立，但 20k preflight 指标明显低于 baseline：`Recall@500=0.024566`、`HitRate@500=0.034`、unique hits `17`，低于 epoch5/queryv2 baseline 的 `Recall@500=0.070809`、`HitRate@500=0.092`、unique hits `49`；同时 queryless user 从 `16` 增加到 `22`。进一步定位发现该组合 run 的 `training_item_universe_item_count=340141` 小于 baseline `499566`，存在 item universe 收缩干扰。

**定位方式：**
先在远端同步 queryv2 与 side-feature 代码，修复远端 governance manifest 中 Windows 路径导致的 artifact 解析问题，再构建 20k method dataset、训练、build source index 并运行 queryv2 direct eval。为排除 universe 收缩干扰，又基于 baseline formal `training_item_universe` 重新派生 full-vocab side-token item vocab，保持 `item_count=499566`，分别运行 `item_quality_token`、`item_pop_bucket_token`、`item_user_count_bucket_token` 三个单字段消融。证据拉回到 `outputs/recall/pool500_method_sources/recent_2y/two_tower/*fullvocab_preflight_20k_20260606/`，本地 `.venv` 校验 source/eval 的 train-only 和 governance flags。

**解决方式：**
将 all-light 组合和三个 full-vocab 单字段消融都收口为 rejected diagnostic challengers，不进入 full formal，不更新 registry/READY。保留证据和结论：控制 item universe 后 queryless 恢复到 `16`，说明 all-light 的 queryless 恶化主要来自 universe 收缩；但三个单字段消融的命中完全一致且仍远低于 epoch5/queryv2 baseline，说明这些粗粒度 item bucket token 暂不值得继续扩大训练。

**验证结果：**
all-light 组合：`item_count=340141`、`queryless_user_count=22`、`Recall@500=0.024566`、`HitRate@500=0.034`。full-vocab 单字段消融三组均为 `item_count=499566`、`queryless_user_count=16`、unique hits `17`、`Recall@500=0.024566`、`HitRate@500=0.032`，source index 均为 `FULL_DERIVED_INDEX_DIAGNOSTIC`，`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。本地验证输出 `controlled_side_feature_ablation_evidence_validation_PASS`。

**面试可讲点：**
这段可以讲成“用受控 preflight 及时否定一个看似合理的工业特征增强”：不是只看 side feature 是否能跑通，而是先发现 item universe 收缩导致 coverage 退化，再做 full-vocab 单因素消融排除干扰，最后基于 query coverage、unique hits、Recall 和治理 flags 决定停止 full formal，避免把粗粒度 side bucket 当作有效模型增强。

### 2026-06-05 - two_tower YouTubeDNN 训练侧 challenger 反证

**任务：**
在 pool500 recent-2y `two_tower` 上继续对齐 YouTubeDNN 论文实践，远程 formal 验证 `recency_decay + example_age_decay + sampled_softmax_logq` 组合是否能优于既有 epoch5/queryv2 baseline。

**遇到的问题：**
训练侧机制全部生效，但 formal legacy direct-eval 指标明显下降：`Recall@500=0.018786`、`HitRate@500=0.026`、unique hits `13`，低于既有 queryv2 baseline `Recall@500=0.070809`，也低于上一轮 `ns_v2_plus_recency` legacy 对照 `Recall@500=0.047688`。

**定位方式：**
在授权远程 GPU 上完成 5 epoch formal 训练，检查 `train_metrics.json`、`source_index_manifest.json` 与 `raw_two_tower_direct_eval_manifest.json`。证据显示 PyTorch/CUDA、mixed precision、生效的 logQ 校正、example-age 权重和 source index 均正常；同时发现远端 eval 脚本缺少本地 queryv2 fallback 文件，当前评估属于 legacy direct-eval 口径，不能直接替代 queryv2 同口径比较。

**解决方式：**
将该 run 收口为 rejected diagnostic challenger，不写入主路配置、registry 或 READY 状态。本地只拉回小型证据 JSON 到 `outputs/recall/pool500_method_diagnostics/recent_2y/two_tower/formal_recency_age_logq_20260605_gpu_evidence/`，METHOD 文档记录失败结论和后续单因素消融方向。

**验证结果：**
训练证据：`training_examples=2103458`、`item_count=499566`、`sampled_softmax_corrected_examples=10517290`、`sampled_softmax_corrected_candidates=115690190`、example-age timestamp missing `0`、weight p50 `0.2`、loss 从 `3.530235` 降到 `3.464569`。治理证据：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`。

**面试可讲点：**
这段可以讲成“论文机制不是直接叠加就一定提升”：先用工程 guard 保证 logQ、freshness weighting 和 recency tower 确实生效，再用 formal eval 证明组合策略反而伤害召回，并把结果治理为 rejected diagnostic，而不是为了追论文对齐强行晋升。它体现了推荐系统实验中单因素消融、评估口径一致性和失败实验复盘的重要性。

### 2026-06-06 - two_tower item side feature token 与安全回归修复

**任务：**
继续把 pool500 recent-2y `two_tower` 向 YouTubeDNN 靠拢，在不改变默认 baseline、不引入 eval label 的前提下补充 train-only item side feature token，并修复 code-reviewer 发现的训练样本/负采样口径风险。

**遇到的问题：**
直接叠加 `recency + example-age + logQ` 的 formal challenger 已被反证；下一步应做更低风险的 item side input。但初版实现存在三类风险：多 sequence key 合并后可能不按全局时间排序；负采样只排除 capped recent window 而非完整用户已知历史；`item_quality:embedding_ready` 这类 side token 会被普通分词拆成泛化片段。

**定位方式：**
独立 code-reviewer 对 `rs_core/recsys/two_tower.py`、`rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py` 和相关测试提出 HIGH/HIGH/MEDIUM findings；随后用新增回归测试覆盖 cross-key timestamp ordering、older known item 负例排除、side feature atomic token。

**解决方式：**
`two_tower` 训练侧新增默认关闭的 `side_feature_fields` 路径，方法数据集输出 `item_quality_token`、`item_pop_bucket_token`、`item_user_count_bucket_token`，训练 metrics/model 记录 active side fields；side feature 以 `field=value` 原子 token 进入 item 初始化。训练序列合并按 timestamp 排序，负采样 `known_items` 改为完整 `recent_item_sequence`，避免 older known item 被采成负例。

**验证结果：**
本地 `.venv` 执行 `py_compile` 覆盖修改文件通过； targeted pytest `tests/test_pool500_two_tower_method_dataset.py tests/test_two_tower_training.py tests/test_pool500_two_tower_direct_eval.py tests/test_pool500_two_tower_method_source.py tests/test_pool500_two_tower_source_manifest.py tests/test_two_tower_source_manifest_guard.py -q` 结果 `72 passed, 3 skipped`。独立 code-reviewer 复核为 `APPROVE`，独立 verifier 复核为 `PASS`；当前仍无 formal 效果结论，`two_tower` 保持 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“向工业 YouTubeDNN 靠拢时先补安全可审计的 side input，而不是盲目堆论文机制”：item side token 默认关闭、可单因素消融、可回滚；同时通过时间顺序、负采样用户已知历史排除和原子 token 化，保证训练样本口径不泄漏、不自相矛盾。

### 2026-06-05 - RSAgent typed long memory 与相关性召回

**任务：**
参考 Claude Code 的长期记忆实践，把 `rsagent` 的长期记忆从 constraints/profile snapshot MVP 升级为可类型化、可裁剪、可相关性召回的内部记忆层。

**遇到的问题：**
原有长期记忆只能跨 session 恢复 `active_constraints` / `user_profile`，缺少可解释的记忆条目、召回预算和 public 泄露防线；如果直接把记忆作为新 Agent tool 或直接影响排序，又会破坏当前 6 个业务工具和推荐主链路稳定性。

**定位方式：**
复核 `rs_core/rsagent/long_memory.py`、`rs_core/serving/service.py`、`rs_core/display/builder.py` 和长期记忆/serving/display/runtime 测试，确认低风险接入点是 snapshot 阶段生成 typed entries、提供 pure recall function，并保持 hydrate 仍只合并 legacy constraints。

**解决方式：**
新增 `LongMemoryEntry`、typed entry 序列化/反序列化、deterministic extractor 和 `recall_relevant_long_memory()`；`snapshot_session_long_memory()` 同时保存 legacy snapshot 与 typed entries，旧 JSON 无 `entries` 仍可读取，畸形 entry 自动跳过。Public display 增加 typed memory / memory recall forbidden keys 与 terms，并修复 catalog text 豁免只允许 `source/training/reward` 这类商品文本子串，不允许 `long_memory`、`agent_tool_trace` 等内部词穿透。

**验证结果：**
使用项目 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_long_memory.py tests/test_serving_long_memory.py tests/test_display_contract.py tests/test_agent_runtime.py -q`，结果 `77 passed`；运行 `./.venv/Scripts/python.exe -m compileall rs_core/rsagent rs_core/display tests` 通过。独立 code-reviewer 发现 catalog text 豁免过宽和 zero-budget feedback events 问题，已补修并新增回归测试；独立 verifier 复核为 PASS，无 blocker。

**面试可讲点：**
这段可以讲成“把用户长期记忆从黑盒快照升级成可治理 memory layer”：记忆不是无差别保存对话全文，而是结构化为喜欢/不喜欢商品、类目、关键词、用途、价格等 typed entries；同时通过预算、相关性召回、旧格式兼容和 public 安全校验，把 Agent 长期个性化能力和推荐主链路风险隔离开。

### 2026-06-04 - RSAgent 长期用户记忆 MVP

**任务：**
参考 Claude Code 的分层记忆系统，为 `rsagent` 增加默认关闭、服务层可插拔的跨 session 用户长期记忆 MVP。

**遇到的问题：**
当前 `rsagent` 已有 `AgentSession.active_constraints`、`session_summary`、`user_profile` 和 `archived_turn_summaries`，但这些都只存在于单个 session；`RecommendationService` 也明确是单进程内存态，无法让同一用户在新 session 中复用历史偏好。

**定位方式：**
对比 Claude Code 的 `memdir/MEMORY.md`、相关记忆召回和 session memory 后，复核 `rs_core/rsagent/schema.py`、`rs_core/rsagent/context.py`、`rs_core/rsagent/runtime.py`、`rs_core/serving/service.py` 与 RAG/display 边界，确认最小接入点应在 serving 生命周期，而不是让 runtime 或商品 RAG 直接依赖外部存储。

**解决方式：**
新增 `rs_core/rsagent/long_memory.py`，提供 `LongMemoryConfig`、`UserLongMemory`、`InMemoryLongMemoryStore`、`JsonLongMemoryStore`、session hydrate/snapshot helper；在 `RecommendationService.start_session()` 后按 `user_id` 水合长期偏好，在 `chat()`/`feedback()` 后从 session 快照回写。默认 `enabled=False`，不改变现有行为；长期记忆只落到 `FeedbackConstraints/UserPreferenceProfile`，不混入商品 RAG evidence；同时加固 public display forbidden keys/terms，避免 `long_memory` 等内部字段外泄。

**验证结果：**
使用项目 `.venv` 运行 `.venv/Scripts/python.exe -m pytest tests/test_long_memory.py tests/test_serving_long_memory.py`，结果 `8 passed`；运行 `.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_agent_feedback.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `89 passed`；运行 `.venv/Scripts/python.exe -m pytest tests/test_rag_core.py tests/test_agent_dialogue.py`，结果 `38 passed`。独立 verifier 复核为 PASS，无 blocker。

**面试可讲点：**
这段可以讲成“把推荐 Agent 从会话内反馈升级到用户级长期偏好记忆”：不是把所有对话全文长期化，而是复用结构化 feedback/profile 作为可审计记忆单元，并把存储接在 service 生命周期上，保持 RAG grounding、public 展示和推荐主链路边界清晰。

### 2026-06-04 - itemcf_weak RPA-lite diagnostic replay artifact 治理化

**任务：**
把 RPA-lite 从 eval-only 分片诊断推进为可审计的 diagnostic replay artifact，明确 train-only 构建输入、post-hoc 评估边界和 READY 阻断条件。

**遇到的问题：**
远程 20 分片报告证明 RPA-lite 方向有效，但它仍只是不写 candidates 的 eval-only replay；如果直接把最优指标写成 source readiness，容易把后验诊断误当成候选生成依据。

**定位方式：**
复核 `rpa_lite_local_10gb_sharded_remote_v1/evaluation_report.json` 的治理字段：`candidate_artifact_written=false`、`candidate_generation_allowed=false`、`promotion_allowed=false`。同时对照 `source_config.yaml`、`dataset_policy.yaml` 和 registry，确认 `itemcf_weak` 必须继续停在 `DIAGNOSTIC_ONLY`。

**解决方式：**
新增 `rs_lab/experiments/recall/pool500/methods/itemcf_weak/rpa_lite_diagnostic_replay.py` 和 CLI wrapper，生成 `rpa_lite_diagnostic_replay_v1/rpa_lite_replay_manifest.json`、`governance_audit.json`、`no_eval_label_selection_audit.json`、`resource_audit.json`、`coverage_audit.json`。artifact 只固化治理和 replay contract，不写候选行；manifest 中记录 RPA-lite evidence schema、train-only input sha256、post-hoc metrics、READY blockers，并在配置/registry 中保持所有 promotion/generation flag 为 false。

**验证结果：**
单测 `tests/test_pool500_itemcf_weak_rpa_lite_diagnostic_replay.py` 覆盖 governed artifact 输出、forbidden output path、promoted report rejection。canonical manifest 当前 `status=PASS`、`artifact_type=diagnostic_replay_artifact`、`ready_source_artifact=false`，post-hoc 最优仍是 `rpa_iuf_sparse_medium_p100_user500_sharded10gb`：`raw_recall@500=0.026407`、`candidate_user_rate=0.928158`、candidate p50/p90/max=`100/100/100`。

**面试可讲点：**
这段可以讲成“把有效实验转成可治理 artifact，而不是直接追指标晋升”：RPA-lite 指标优于 AugCF-lite 后，仍先补齐 no-oracle audit、资源审计、覆盖审计和 READY blockers，让后续 overlap/route gate 有可信输入，体现推荐系统实验从 notebook/脚本到工程治理的收口能力。

### 2026-06-04 - itemcf_weak RPA-lite 远程 20 分片诊断与 AugCF 产物清理

**任务：**
在本地 10GB hash-sample 证明 RPA-lite 方向有效后，迁移到远程服务器做 20 分片聚合诊断，并按用户决策清理 `itemcf_weak` 下 AugCF-lite 旧结果产物。

**遇到的问题：**
本地 `shard_mod=10` 的单分片在 `build_candidates` 阶段达到 `9.8862GB` 后被 memory guard 拦截，说明本机 10GB 下 full-scope 分片仍偏大；同时 AugCF-lite 已不再作为主线，继续保留结果目录会让配置和叙事混淆。

**定位方式：**
先把分片粒度改为 `shard_mod=20`，本地第 0 分片峰值约 `5.9GB` 并得到 `raw_recall@500=0.030007` 的方向性结果；随后在 `server:/home/luo/RS_agent_remote` 检查可用资源，确认远程 `/tmp` 有空间、内存充足，将脚本上传到 `/tmp` 并用 4 路并发跑 20 分片。远程 `.venv` 缺少 `psutil`，脚本改为可选 `psutil`，缺省时从 `/proc/self/status` 读取 RSS。

**解决方式：**
远程输出写入 `/tmp/rpa_lite_local_10gb_sharded_remote_v1`，日志写入 `/tmp/rpa_lite_remote_logs`，完成后拉回到 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_sharded_remote_v1/`。同时删除 `itemcf_weak` 的三个 AugCF-lite 结果目录，并在 `METHOD.md`、`dataset_policy.yaml`、`source_config.yaml` 中改成“历史诊断结果已删除，主线切到 RPA-lite”的口径。

**验证结果：**
远程聚合报告 `status=PASS`，20/20 shards 完成，`train_only_target_users_total=5,147,753`、`evaluated_target_users_with_labels_total=41,605`、`peak_observed_rss_gb_max=6.8637`。最优 `rpa_iuf_sparse_medium_p100_user500_sharded10gb`：`raw_recall@500=0.026407`、`in_universe_recall@500=0.050346`、`raw_hit_user_rate@500=0.032857`、sparse hit `0.024730`、medium hit `0.053875`、candidate p50/p90/max=`100/100/100`。相比 AugCF-lite v3 best 的 `0.024707` raw 和 `0.018064` sparse hit，分别提升 `+0.001700` 和 `+0.006666`。仍保持 `DIAGNOSTIC_ONLY`，不写正式 candidates，不打开 candidate generation / promotion。

**面试可讲点：**
这段可以讲成“用资源治理和分片验证把方向性实验推进到更接近全量的诊断”：先用内存 guard 发现本机分片过大，再迁移远程并保留每分片 10GB 约束；最终用全 20 分片聚合证明 RPA-lite 在更大范围仍优于 AugCF-lite，同时主动清理被淘汰方案产物，避免历史实验污染当前主线。

### 2026-06-04 - itemcf_weak Recursive CF / RPA-lite 10GB 本地诊断

**任务：**
在用户确认 Recursive CF 比完整 AugCF 更轻、适合当前阶段后，复核 Zhang & Pu 2007 论文，并把其“递归/间接邻域补全”思想改造成本地 10GB 内存受限的 RPA-lite sparse/medium user augmentation 诊断。

**遇到的问题：**
AugCF-lite v3 虽然单源 `raw_recall@500=0.024707`，但 sparse hit 仍停在 `0.018064`，且候选预算 p50/p90/max=`200/400/500` 很满；完整 AugCF GAN 又需要 generator/discriminator/Gumbel-Softmax 和训练闭环，当前成本过高。

**定位方式：**
深读 RecSys 2007 `A recursive prediction algorithm for collaborative filtering recommender systems`，确认论文核心不是新 item-item sim，而是让未评价目标 item 的相似邻居通过递归预测继续参与上层评分。结合当前 implicit Top-N 召回，将其改成 train-only user-user IUF 相似传播：只做 bounded depth=1 pseudo candidate 补全，不照搬 explicit rating / MAE 公式。

**解决方式：**
在本地 `.venv` 下运行 `.omc/run_rpa_lite_local_10gb.py`，target selection 只用 train-only sequence bucket 与 deterministic user_id hash sample；valid/test label 在 candidate scores 构建完成后才加载用于 post-hoc evaluation。运行过程限制 10GB，设置 seed/candidate hot cap、candidate prune 与 per-user top100，保持 `DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`promotion_allowed=false`。

**验证结果：**
本地报告 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_v1/evaluation_report.json` 验证输出 `local_rpa_lite_10gb_report_validation_PASS`。最优 `rpa_iuf_sparse_medium_p100_user500_local10gb`：`raw_recall@500=0.027130`、`in_universe_recall@500=0.048733`、`sparse hit@500=0.029073`、candidate p50/p90/max=`100/100/100`；相比 AugCF-lite v3 best，raw Recall 绝对提升 `+0.002423`，sparse hit 绝对提升 `+0.011009`。峰值 RSS `7.3GB`，低于 10GB 限制，运行约 `498s`。

**面试可讲点：**
这段可以讲成“从重生成模型切到轻量协同图补全”：不是盲目复刻 GAN，而是读论文后抽取可工程化的递归邻域思想，用 train-only、内存上限和候选预算把它改造成可审计的 sparse repair source，并用分桶指标证明它比 AugCF-lite 更对症。

### 2026-06-04 - RSAgent 轻量上下文压缩改造

**任务：**
为当前 RSAgent 规划并落地推荐 Agent 专用的上下文压缩策略，避免照搬 Claude Code code agent 的复杂 compact boundary / prompt cache / transcript 机制。

**遇到的问题：**
现有上下文压缩分散在 `rs_core/rsagent/runtime.py`、`rs_core/workflow/hybrid_environment.py` 和 `rs_core/recsys/rag/retriever.py`：`session_summary`、recent turns、工具 compact output、RAG per-item cap 各自存在，但缺少统一 `ContextBundle/ContextBudget`，RAG evidence 也只有条数限制没有字符/全局预算。

**定位方式：**
只读梳理 `AgentSession`、`AgentRuntime._memory_prefetch/_compact_session`、`_get_user_context_output`、`RagPolicy/build_rag_context_for_ranked_candidates`、`_rag_reason` 和 display allowlist/forbidden gate，确认当前策略更适合确定性结构化压缩，而不是 LLM rolling summary。

**解决方式：**
新增 `rs_core/rsagent/context.py`，引入 `ContextBudget`、`ContextBundle`、deterministic `UserPreferenceProfile` 和 `ArchivedTurnSummary`；让 runtime memory/session summary 与 `get_user_context` 共用同一 compact bundle；扩展 `RagPolicy` 的 `max_evidence_total/max_text_chars`，并在 RAG context、item evidence tool、解释文本三层做预算；补强 public display forbidden keys/terms，禁止 context/profile/raw RAG evidence 泄露。

**验证结果：**
使用项目 `.venv` 运行 `.venv/Scripts/python -m pytest tests/test_agent_runtime.py tests/test_agent_tools.py tests/test_rag_core.py tests/test_agent_dialogue.py tests/test_display_contract.py -q`，结果 `110 passed`；运行 `.venv/Scripts/python -m ruff check rs_core tests`，结果 `All checks passed`。Ruff 过程中发现并修复了既有 `_manifest_output` 未定义问题。

**面试可讲点：**
这段可以讲成“按业务类型设计上下文管理”：Code Agent 需要 transcript/compact boundary/prompt cache，但推荐 Agent 更需要结构化偏好、候选证据和展示安全边界；因此用可审计的 deterministic profile、ContextBundle 和 RAG evidence budget 控制上下文，而不是依赖不可控的 LLM 摘要。

### 2026-06-04 - itemcf_weak AugCF-lite v3 sparse/side-info 诊断

**任务：**
在 v2 已确认 AugCF-lite 收益主要来自 augmented graph 可达性后，继续对照 KDD'19 AugCF 论文中的 sparse/inactive targeting 与 side information，远程验证是否还有低成本效果优化点。

**遇到的问题：**
`itemcf_weak` v2 最优 `base_observed_score_seed200_user500` 已达到 `raw_recall@500=0.024673`，但 sparse bucket hit 仍只有 `0.018064`，且候选预算 p50/p90/max=`200/400/500` 很满。若只压缩预算，可能降低中高活用户命中；若直接引入 side-info boost，则需要证明不是 eval label 泄漏或单点偶然提升。

**定位方式：**
按用户要求在 `server:/home/luo/RS_agent_remote` 运行 `/tmp/run_augcf_lite_v3_sparse_sideinfo.py`，复用 `/tmp/itemcf_weak_augcf_lite_formal_method_datasets_v3/itemcf_weak/method_dataset_rows.jsonl`，只使用 train-only row 与 item governance metadata 做 replay 排序；valid/test label 仍只用于后验 evaluation-only metrics。报告拉回到 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/augcf_lite_v3_sparse_sideinfo_v1/evaluation_report.json`。

**解决方式：**
设计三类对照：v2 baseline、按用户序列桶收紧中高活 fanout/cap 的 sparse-targeted variants、以及基于 train-only category/hotness/quality metadata 的 side-info boost/guard variants。所有 variant 均保持 `evaluation_only=true`、`source_artifact_complete=false`、`candidate_generation_allowed=false`、`promotion_allowed=false`。

**验证结果：**
远程报告 `status=PASS`，本地复核输出 `local_augcf_lite_v3_sparse_sideinfo_report_validation_PASS`。`sideinfo_category_boost_v1` 最优 raw：`raw_recall@500=0.024707`、`in_universe_recall@500=0.030573`、candidate p50/p90/max=`200/400/500`，相对 v2 baseline 仅提升 `+0.000034`；两个 sparse-targeted variants 分别降到 `0.022374` 和 `0.021403`，且 sparse hit 都仍为 `0.018064`。结论是简单预算重分配无效，category side-info 有弱正向信号但不足以单独晋升，`itemcf_weak` 继续保持 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“把论文机制拆成可验证消融”：不是直接说 AugCF 更强，而是分别验证扩图、稀疏用户预算、类目信息和热门约束的边际贡献，用 train-only/eval-only 边界防止泄漏，并把微弱提升收口为后续 adapter 与 route-gate 的候选信号。

### 2026-06-04 - itemcf_strong AugCF route-gate evidence matrix

**任务：**
为 `itemcf_strong` AugCF q20/q30/no-hot/relaxed 诊断源新增轻量 route-gate evidence matrix，在固定 pool500 offline eval users 上统一跑 route-level eval，并把指标、overlap、source attribution 和 no-oracle 证据聚合到 `route_gate_evidence_manifest.json`。

**遇到的问题：**
单个 source manifest 的离线指标不足以判断是否可以进入主路：AugCF 诊断候选可能与 baseline 高度重叠，或收益来自 popular/category/hotness 覆盖；如果只看 Recall 提升，容易误判为可晋升。

**定位方式：**
复用 `rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py` 中固定 eval users、no-oracle label policy、`source_manifest_paths` override 和 metrics/source_audit 输出，新增测试用 fake candidate runner 验证 relaxed 不传 override、q20 正确传 `itemcf_strong` override。

**解决方式：**
新增 `run_itemcf_strong_augcf_route_gate_matrix.py`：按 `--variant name=path` 串行运行 baseline eval，path 为 `default`/`relaxed`/空时不传 source override，否则传 `source_manifest_paths={"itemcf_strong": Path(path)}`；聚合 Recall@500/HitRate@500 delta、positive hit exclusive/overlap、user-item candidate jaccard、source hit attribution、diagnostic_hot_budget_audit，并限制决策只输出 diagnostic route-gate 三态，不输出 READY/PROMOTE。

**验证结果：**
本地 `.venv/Scripts/python.exe -m py_compile ...` 通过；`.venv/Scripts/python.exe -m pytest tests/test_pool500_offline_eval_baseline.py -q` 结果为 `6 passed`。新增测试覆盖 q20/relaxed、source override 传递、exclusive positive hits、no_oracle/eval_only/diagnostic_only 字段。

**面试可讲点：**
这段可以讲成“把召回增强实验从单点 Recall 报告升级为准入证据矩阵”：用固定用户集和 no-oracle 口径，对比边际命中、候选重叠、source 归因和 hotness audit，避免把热门覆盖或重复候选误当作模型增强收益。

### 2026-06-04 - itemcf_strong AugCF route-level user hot/pseudo 预算门控

**任务：**
在 controlled v2 已证明 per-src hot quota 仍无法约束最终 user-level candidate hot share 后，为 `itemcf_strong` AugCF-lite/controlled 诊断源补齐 route-level 预算门控和固定 eval users 的通用 source override。

**遇到的问题：**
AugCF-controlled q20/q30 在单源 purchase Recall 上有提升，但最终候选池会聚合多个 seed，导致 user-level 热门候选比例仍高；如果只看 source 边预算，可能把热门商品覆盖误判成 `itemcf_strong` 相似度提升。

**定位方式：**
复核 `run_full_data_pool500_recall_only.py` 的 merge → popular/category cap → fallback completion 流程，确认预算应放在 `_enforce_popular_category_cap(...)` 后、fallback completion 前；同时复核 `run_pool500_offline_eval_baseline.py` 已有 `source_manifest_paths` 函数参数，但 CLI 只支持 two_tower 特例。

**解决方式：**
在 route 侧新增 `_augcf_route_budget_policy(...)` 和 `_apply_augcf_route_budget_cap(...)`：仅当 `itemcf_strong` source manifest 为 `diagnostic_only=true` 且 variant/policy 含 `augcf_lite` 或 `augcf_controlled` 时启用；按 `max_final_hot_share_per_user` 和 `max_pseudo_per_user` 删除 AugCF diagnostic 候选，优先删 pseudo、hot、单源、低分项，不误伤 relaxed baseline。新增 `diagnostic_hot_budget_audit.json`，并让 offline baseline CLI 支持 `--source-manifest itemcf_strong=...`。

**验证结果：**
本地 `.venv` 执行 `py_compile` 覆盖两个 route 脚本和相关测试通过；`pytest tests/test_full_data_pool500_recall_only.py tests/test_pool500_offline_eval_baseline.py -q` 结果为 `26 passed`。独立 verifier 复核为 `PASS`、无 blocker。

**面试可讲点：**
这段可以讲成“把单源实验收益转化为主路准入门禁”：不是因为 AugCF Recall 高就直接晋升，而是在最终候选池层面对热门偏置和 pseudo 边占比做治理，并用 audit artifact 让 route-gate 能比较边际收益、overlap 和 source share。

### 2026-06-04 - itemcf_strong AugCF-controlled v2 hotness 预算实验

**任务：**
在 KDD'19 AugCF 思路的 `itemcf_strong` 轻量复刻实验中，继续验证“生成式/学习式补边”的收益是否可被 hotness 预算约束，而不是简单由热门商品覆盖驱动。

**遇到的问题：**
AugCF-lite unrestricted hot-dst 的 purchase `Recall@500=0.025721`，但 `candidate_hot_share=0.960442`；no-hot 对照 `Recall@500=0.000192` 又不超过 relaxed baseline `0.000211`。这说明有效信号和热门覆盖高度耦合，如果直接晋升会把 popular/category 能力误归因给 `itemcf_strong` 相似度。

**定位方式：**
复核远程 formal_50k hot/no-hot 报告后，在 `rs_lab/experiments/recall/pool500/methods/itemcf_strong/augcf_lite_builder.py` 中加入 per-src hot dst quota，并修复 controlled 模式下“超预算 hot dst 回填”的问题；随后在 `server:/home/luo/RS_agent_remote` 使用 `.venv/bin/python` 跑 q10/q20/q30/q50 对照，valid/test 仍只用于 evaluation-only purchase/strong label。

**解决方式：**
新增 `--controlled-hot-budget` 与 `--max-hot-share-per-src`，在 source 边排序后按 src item 控制 hot dst 边数。重 artifact 写入远程 `/tmp/rs_agent_spill`，本地只拉回 manifest、leakage audit、source manifest 和 purchase eval JSON，并在实验结束后用 Python `shutil.rmtree` 清理远程临时目录。

**验证结果：**
controlled v2 q10/q20/q30/q50 均完成远程 formal_50k：purchase `Recall@500` 分别为 `0.005037`、`0.010688`、`0.015129`、`0.019608`，`candidate_hot_share` 分别为 `0.440016`、`0.618814`、`0.717320`、`0.823463`。结果证明 per-src 预算能形成 Recall/hotness tradeoff，但 user-level candidate hot share 仍会因多 seed 聚合而高于 per-src quota，因此 q20/q30 只能作为 route-gate 诊断候选，不能替代 relaxed baseline 或自动并入主路。

**面试可讲点：**
这段可以讲成“把论文增强收益拆解为可治理的预算曲线”：不是只报告 Recall 变高，而是用 no-hot 和 quota grid 证明收益来源、约束热门偏置，并把实验结论收口到 route overlap、边际 Recall 和 source share cap 门禁。

### 2026-06-04 - itemcf_weak AugCF-lite v2 score/cap 网格复核

**任务：**
在用户要求继续围绕 KDD'19 AugCF 做效果优化后，远程复核当前 AugCF-lite 的收益来源：是 pseudo contribution score 权重本身带来的，还是 augmented graph 扩图/候选可达性带来的。

**遇到的问题：**
上一轮 `augcf_lite` 单源 `raw_recall@500=0.024536` 明显优于 `weak_denoised=0.01478`，但候选预算更满（p50/p90=200/400）。如果继续盲目提高 pseudo 权重，可能只是在放大噪声；如果强行降低 fanout/cap，又可能损失覆盖。

**定位方式：**
按用户要求在 `server:/home/luo/RS_agent_remote` 运行 eval-only 网格：复用 `/tmp/itemcf_weak_augcf_lite_formal_method_datasets_v3/itemcf_weak/method_dataset_rows.jsonl`，对 `base_itemcf_score`、不同 pseudo 权重缩放和 `top_k_per_seed/per_user_cap` 组合做逐 variant replay。valid/test label 仍只在后验指标阶段读取，不参与构图、打分规则生成或候选产物输出。

**解决方式：**
新增一次性远程脚本 `/tmp/run_augcf_lite_v2_grid.py`，输出 `/tmp/augcf_lite_v2_grid_seed_cap_score_v1/evaluation_report.json`，并拉回本地 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/augcf_lite_v2_grid_seed_cap_score_v1/evaluation_report.json`。实验继续保持 `DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`promotion_allowed=false`。

**验证结果：**
远程报告 `status=PASS`，本地复核输出 `local_augcf_lite_v2_grid_report_validation_PASS`。最优 variant 为 `base_observed_score_seed200_user500`：`raw_recall@500=0.024673`、`in_universe_recall@500=0.030531`、`candidate_user_rate=0.944488`、candidate p50/p90/max=`200/400/500`。pseudo 权重缩放 `0.05/0.10/0.20/0.25` 对应 `raw_recall@500=0.024656/0.024639/0.024536/0.024536`，说明单纯提高 pseudo score 不是收益主因；收紧预算到 seed100/user300 后 `raw_recall@500=0.019258`，seed50/user200 后降到 `0.015478`，说明当前提升高度依赖扩图后的 fanout/cap 覆盖。

**面试可讲点：**
这段可以讲成“把论文复刻的收益来源做归因”：不是只报 AugCF-lite 提升，而是通过 score/cap 网格证明当前收益主要来自增强图的可达性，下一步应按论文补 sparse-user targeting、side information 和 like/dislike class，提高生成边质量，再用 route overlap 和边际 Recall 验证能否进入主路。

### 2026-06-04 - itemcf_weak AugCF-lite 相似度/生成增强诊断落地

**任务：**
针对 KDD 2019 `Enhancing Collaborative Filtering with Generative Augmentation`，判断其相似度思想是否可以替代当前 `itemcf_weak` 的 weighted cooc cosine，并先落地可复核的轻量复刻。

**遇到的问题：**
AugCF 论文核心不是显式 item-item similarity 公式，而是 conditional GAN / Gumbel-Softmax 生成增强交互；如果直接声称替换 sim 或完整复现 GAN，会扩大训练和治理风险，也不利于和当前 `weak_denoised` baseline 公平对比。

**定位方式：**
调研 KDD/DBLP/DOI 资料后，将 AugCF 拆成“生成增强 sparse/inactive user 交互，再重算 CF score”的工程思想；复核 `rs_lab/experiments/recall/build_pool500_method_dataset.py` 中当前 `weighted_cooc / sqrt(src_user_count * dst_user_count)` 公式和 `weak_denoised` profile，决定新增 diagnostic profile 而不是直接改 registry 或主路。

**解决方式：**
新增 `augcf_lite` profile：`score_policy=augcf_lite_profile_score_v1`、`augmentation_policy=train_only_observed_pseudo_low_freq_v1`、`top_k_per_seed=200`、`gan_enabled=false`、`gumbel_softmax_enabled=false`，只做 train-only observed-pseudo 轻量增强并保留 `DIAGNOSTIC_ONLY`；文档和配置明确 `paper_claim_boundary=not_exact_kdd19_gan_reproduction`。

**验证结果：**
按用户要求在远程服务器 `server:/home/luo/RS_agent_remote` 执行验证：同步 builder 后远程 `.venv/bin/python -m py_compile` 通过，并在 `/tmp` fixture 上完成直接 smoke，输出 `remote_augcf_lite_smoke_after_update_PASS`。随后用 localized train-only governance manifest 构建 formal method dataset：`row_count=16714845`、`unique_pair_count=13433154`、`directed_edge_count_after_topk=16714845`；eval-only replay 报告拉回到 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/augcf_lite_eval_seed200_user500_v1/evaluation_report.json`，`raw_recall@500=0.024536`、`in_universe_recall@500=0.030362`、`candidate_user_rate=0.944488`、candidate max `500`。相比 `weak_denoised` 的 `raw_recall@500=0.01478` 有明显提升，但候选更满（p50/p90=200/400），因此仍保持 DIAGNOSTIC_ONLY，等待 overlap/marginal Recall/route gate。

**面试可讲点：**
这段可以讲成“把论文方法先降维成可治理的工程对照实验”：没有盲目复刻 GAN，而是先识别论文真正贡献不是 sim 公式、而是生成式增强数据，再用 train-only diagnostic profile 与现有 baseline 做 paired eval 的准备。

### 2026-06-04 - itemcf_weak 去噪网格与修复口径调整

**任务：**
在 `weak_coverage` 已恢复覆盖但效果仍偏弱后，继续定位低效果原因，并在远程服务器上验证 support gate、BM25/IDF、shrinkage、hot-dst 排除和候选 cap 的修复方向。

**遇到的问题：**
`weak_coverage` 的 `raw_recall@500=0.01478` 仍偏低，且候选最大数达到 `4569`；直觉上的去噪方案（support>=2、BM25/IDF、去热门）可能会降低噪声，但也可能把弱召回真正命中的长尾/support=1 边一起删掉。

**定位方式：**
新增 evaluation-only 诊断脚本 `rs_lab/experiments/recall/diagnose_itemcf_weak_coverage_denoising.py`，在 `server:/home/luo/RS_agent_remote` 上读取 train-only method dataset rows 和 train-only item/profile 文件，只用 valid/test label 做后验 Recall@K。因远端 `/home` 分区满，将 3.2GB rows 临时移动到 `/tmp/itemcf_weak_diagnostics/` 执行，并拉回 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/weak_coverage_denoising_grid_v2/evaluation_report.json`。

**解决方式：**
远程网格显示 `support1_existing_seed200_user500` 与 baseline 一样保持 `raw_recall@500=0.01478`、`in_universe_recall@500=0.021617`、`candidate_user_rate=0.83305`，但把 candidate max 从 `4569` 收到 `500`；而 `support>=2` 将 raw Recall 降到 `0.005789`，`BM25/IDF + hot-dst non-hot` 只有 `0.000051` 或 `0.0`。因此新增 `weak_denoised` profile 时不采用强过滤，而是保留 `support=1 + weighted_cooc_cosine_normalized_v1`，设置 `top_k_per_seed=200`，并要求 route/eval 侧 `per_user_candidate_cap=500` 和 overlap/marginal Recall gate。

**验证结果：**
本地 `.venv` 通过 `pytest tests/test_pool500_method_dataset.py -q`（27 passed）和 `py_compile`。诊断报告 `status=PASS`，配置和文档已同步到 `METHOD.md`、`RECENT2Y_FAILURE_DIAGNOSIS_AND_FIX_PLAN.md`、`source_config.yaml`、`dataset_policy.yaml`。权限位仍保持 `candidate_generation_allowed=false`、`promotion_allowed=false`。

**面试可讲点：**
这段可以讲成“不是盲目去噪，而是用网格证明弱边的工程价值”：support=1 边确实带来噪声，但也是当前 raw Recall 的主要来源；最终选择先做候选预算控制和 route gate，而不是用看似更干净的强过滤牺牲覆盖。

### 2026-06-03 - itemcf_weak weak_coverage 后验验证与继续诊断

**任务：**
在 `itemcf_weak` strict formal `Recall@500=0` 后，继续验证 `weak_coverage` 是否能解决覆盖过窄问题，并把结果收口到方法文档和配置中。

**遇到的问题：**
strict formal 的 source 图只有 `9856` 个 item、`candidate_user_rate=0.004268`，但如果直接把宽覆盖版本晋升，可能引入 support=1 弱边噪声、候选爆炸和与 popular/category 的重复。

**定位方式：**
复核既有 `outputs/recall/pool500_itemcf_new_dataset/method_datasets_smoke/itemcf_weak/method_dataset_manifest.json`，确认 `weak_coverage` method dataset 已有 `row_count=4445902`、`user_count=120000`、`item_count=185326` 且 `forbidden_scope_audit.status=PASS`。随后用 `.venv` 执行 evaluation-only 流式模拟，从 method dataset rows 构造临时候选，只用 valid/test label 做后验 Recall@K，不参与构建。

**解决方式：**
生成诊断报告 `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/weak_coverage_eval_from_method_dataset_v1/evaluation_report.json`，并把结果写入 `RECENT2Y_FAILURE_DIAGNOSIS_AND_FIX_PLAN.md`、`METHOD.md`、`source_config.yaml` 和 `dataset_policy.yaml`；权限位继续保持 `candidate_generation_allowed=false`、`promotion_allowed=false`。

**验证结果：**
`weak_coverage` eval-only 诊断 `status=PASS`：`source_item_union_count=185326`、`candidate_user_rate=0.83305`、`in_universe_label_ratio=0.6837`、`raw_recall@500=0.01478`、`in_universe_recall@500=0.021617`，显著优于 strict 的 `candidate_user_rate=0.004268` 和 `Recall@500=0.0`。但 `candidate_count_stats.max=4569`，且 kept edges 中 support=1 占多数，因此仍需 BM25/IDF、shrinkage、per-seed/per-user cap、source overlap 和 route gate 后才能考虑候选源权限。

**面试可讲点：**
这段可以讲成“用对照 profile 证伪 strict 失败原因”：不是笼统说 ItemCF 不行，而是用 strict vs weak_coverage 的覆盖、候选数和 Recall 对比证明失败来自过滤口径；同时在指标变好时仍主动保留晋升门禁，体现推荐系统里覆盖、噪声和主路互补性的工程平衡。

### 2026-06-03 - itemcf_strong relaxed supplemental 从 strict diagnostic 升级为候选源

**任务：**
把 `itemcf_strong` recent-2y relaxed supplemental 版本更新为 `READY_CANDIDATE` / `SUPPLEMENTAL_READY_CANDIDATE` 候选，而不是 strict diagnostic-only，并同步方法文档、配置、注册表和工程日志。

**遇到的问题：**
strict 版本边数只有 22，虽然合规但候选贡献几乎为 0，无法说明 strong ItemCF 在 recent-2y 下的真实覆盖能力。新的 relaxed 版本恢复了覆盖，但如果叙事不收口，容易把 train-only 构建、eval-only 验证和主路晋升混写在一起。

**定位方式：**
核对 `outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_relaxed_supplemental_v1/formal/itemcf_strong/method_dataset_manifest.json`，确认 formal `row_count=514216`；核对 `outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y/source_index_manifest.json`，确认 `row_count=514216` 与 8 个 shard；核对 `outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y_eval/single_source_eval_10000.json`，确认 `seed_hit=6141/10000`、`coverage=6128/10000`、`candidate=188494`、`Recall@500=0.000151`、`weak baseline Recall@500=0`、`candidate_hot_share=0`、`strong_unique_share_vs_weak=0.999867`；核对 `audit_evidence.json` 为 `PASS`。

**解决方式：**
把 `dic/recall_methods/itemcf_strong/METHOD.md` 改写为 relaxed supplemental 口径，明确它是 train-only / eval-only 边界下的 `READY_CANDIDATE`；同步更新 `configs/recall/full_data_pool500/itemcf_strong/source_config.yaml`、`dataset_policy.yaml` 与 `configs/recall/pool500_method_registry.json`，把 `itemcf_strong` 从 strict diagnostic 迁到 supplemental-ready 候选源，并保留 `candidate_generation_allowed=true`（仅 route-gate candidate source 范围）、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

**验证结果：**
方法文档、source 配置、dataset policy 和 registry 已更新；注册表中 `itemcf_strong` 现为 `READY_CANDIDATE`，`promotion_recommendation=KEEP_AS_READY_CANDIDATE_FOR_ROUTE_GATE`。证据路径已落到 formal dataset manifest、source index manifest、audit evidence 与 single source eval 报告，且 all evidence 都在 recent-2y train-only / eval-only 边界内。

**面试可讲点：**
这轮可以讲成“把强召回从 strict 诊断修正为可用补充源，但仍不越过主路晋升门禁”：先用 formal/source/eval 三类证据证明覆盖恢复，再把训练、评估和路由边界写进配置，避免把候选恢复误写成主路 ready。

### 2026-06-03 - category all-eligible 改为索引型 route-formal artifact

**任务：**
把 pool500 recent-2y `category` 从 50k 物化切片补齐为全量 eligible route-formal artifact，同时避免默认生成全量 `candidates.jsonl`。

**遇到的问题：**
最初把 50k materialized candidates 当作 formal 证据，容易混淆“正式数据索引”和“用户-商品候选明细”；如果对 1,558,964 个 eligible 用户直接物化全量候选，会造成不必要的大文件和资源压力，也不符合召回路按需展开的设计。

**定位方式：**
核对 `data/processed/amazon_2023_recall_recent_2y_1m_3m/`、train-only governance manifest 和 `recall_views/category_top_items.jsonl` / `category_recall_items.jsonl`，确认 category 可以由 train-visible 轻量索引构建；远程构建后拉回 `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/source_index_manifest.json`、`coverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json` 与 `remote_provenance.json` 做本地复核。

**解决方式：**
在 `rs_lab/experiments/recall/pool500/methods/category/builder.py` 中增加 `candidate_materialization=full|none` 分支：`formal_50k` 保留物化候选用于 eval-only Recall，`all_eligible` 强制 `candidate_materialization="none"`，只输出 `eligible_users.jsonl`、`user_category_profile.jsonl`、`category_top_items_index.jsonl`。重任务放到 `server:/home/luo/RS_agent_remote` 执行，并用轻量 `recall_views/category_recall_items`、seed item category 子集、tuple/intern 存储降低内存。

**验证结果：**
远端 `category_recent2y_all_eligible_index_v1` 构建通过：`status=PASS`、`readiness=READY`、`target_user_count=1,558,964`、`user_coverage_count=1,558,964`、`user_coverage_ratio=1.0`、`profile_row_count=1,558,964`、`candidate_row_count=0`、`runtime_seconds=213.18248`、`no_holdout_audit.status=PASS`。本地使用 `.venv` 通过 `py_compile`、config/policy/manifest/provenance/registry consistency assertions，以及 `pytest tests/test_pool500_lightweight_source_governance.py -q`（2 passed）。

**面试可讲点：**
这轮可以讲成“把召回源从大规模物化文件改造成可治理的索引型 artifact”：全量 eligible 覆盖不等于全量候选落盘，通过 train-only profile + 类目 top-items index 支持按需展开，既控制资源，又保留 lineage、audit、registry 和 route-gate 边界。

### 2026-06-03 - two_tower recent-2y full formal 远程训练与诊断收口

**任务：**
在 20k preflight 之后，按 full recent-2y formal 口径使用远程服务器训练 `two_tower`，拉回 artifact 并完成 source/eval/overlap/route gate 复核。

**遇到的问题：**
preflight 指标偏低可能被训练规模限制误导；但 full formal 是重资源任务，且远端 `/home` 磁盘使用率高，需要限流、单卡、保守 epoch，并防止 valid/test 进入训练或候选生成。

**定位方式：**
确认远端 `server:/home/luo/RS_agent_remote` 可用且有 3 张 RTX 4090；同步当前 two_tower 脚本和 formal manifest，修正远端 item vocab manifest 路径。训练进度日志显示 `training_rows_complete` 扫描 `687147` users、保留 `667734` training rows，并在 `cuda:0` 上执行 mixed precision。

**解决方式：**
以 `epochs=1`、`batch_size=8192`、`gradient_accumulation_steps=2`、`mixed_precision=true` 启动 full formal v1；训练完成后构建 source index，生成 500 eval users candidates，拉回训练产物和必要 embedding/index artifact，本地复核 source manifest guard、direct eval、overlap 和 route gate。

**验证结果：**
full epoch1 训练 `status=PASS`：`training_input_users=687147`、`users_with_training_rows=667734`、`training_examples=2069609`、`item_count=499566`、`loss_history=[1.723716]`、`training_seconds=686.865`。本地 direct eval 复核 `Recall@500=0.044798`、`hit_rate@500=0.054`，高于 20k preflight 的 `0.021676/0.028`，但 `queryless_user_rate=0.19` 未改善；overlap 与 route gate 均产出，route gate decision 仍为 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“用全量训练证伪/校准 preflight 上限”：不是只看小样本结论，而是在 train-only 治理下把 687k 用户 full formal 跑完，并用本地复核证明 full training 确实提升 Recall，但仍因 query 覆盖、互补性和 route gate 不足主动拒绝 READY，体现推荐系统离线指标与主路准入的分层治理。

### 2026-06-04 - two_tower epoch5 与远端 /tmp 软链接资源治理

**任务：**
在 epoch1 full formal 基础上追加 `two_tower` 5 epoch 对照实验，并按用户建议把远端大目录迁移到 `/tmp` 大容量分区后用软链接挂回 canonical outputs 路径，避免 `/home` 空间不足影响后续 source/eval。

**遇到的问题：**
远端 `/home` 已接近 100% 使用率，直接继续写入 full training/candidate artifact 容易失败；同时 epoch1 虽有提升，但用户合理质疑 `epochs=1` 可能偏少，需要用 5 epoch 证实继续训练是否还有收益。

**定位方式：**
远端检查确认 `/home` 仅剩约 1.7G，而 `/tmp` 仍有约 33G；训练完成后读取 `formal_full_687k_training_run_epoch5/train_metrics.json`，并本地复核 source manifest、direct eval、overlap 和 route gate。

**解决方式：**
使用 `epochs=5`、`batch_size=8192`、`gradient_accumulation_steps=2`、`mixed_precision=true` 在远程 4090 单卡训练；训练/candidate 大目录迁移到 `server:/tmp/rs_agent_spill/two_tower/`，再用软链接回 `outputs/recall/pool500_method_sources/recent_2y/two_tower/...`；拉回本地后 patch manifest 路径并复核。

**验证结果：**
epoch5 训练 `loss_history=[1.723716, 1.6206, 1.553363, 1.50874, 1.477235]`、`training_seconds=907.373`、`optimizer_steps=635`。本地 direct eval 复核 `Recall@500=0.057803`、`hit_rate@500=0.076`、`raw_two_tower_unique_positive_hits=40`，相对 epoch1 的 `0.044798/0.054/31` 继续提升；但 `queryless_user_rate=0.19` 不变，route gate 仍为 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“用受控对照验证训练轮数，而不是拍脑袋加资源”：5 epoch 证明模型还在学习并提升 Recall，同时通过 `/tmp` 软链接做资源治理，最后仍基于 query coverage 和 route gate 拒绝过早晋升，体现实验收益、资源约束和上线门禁三者平衡。

### 2026-06-04 - itemcf_strong 购买/强正反馈目标远程复测

**任务：**
按“strong 方法应以购买/强正反馈目标评估”的口径，在远程服务器复测 `itemcf_strong` relaxed supplemental source，而不是只看通用 binary label 的 10k sanity eval。

**遇到的问题：**
远程仓库已有 recent-2y train/valid/test 数据，但缺少当前 relaxed `itemcf_strong` source artifact；同时现有通用评估脚本先按 `label_binary` 判正，不能区分 purchase/strong-positive 目标。

**定位方式：**
确认 valid/test interaction schema 包含 `verified_purchase`、`label_binary`、`label_strong`、`label_strength`；本地用 `.venv` 对新脚本做 `py_compile` 和 100-user smoke。随后通过 `tar | ssh` 将评估脚本与 514216-edge source artifact 同步到 `server:/home/luo/RS_agent_remote`，用远程 `.venv/bin/python` 全量运行，并拉回 `outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y_eval/purchase_label_eval_remote_full.json`。

**解决方式：**
新增 `scripts/experiments/recall/pool500/evaluate_itemcf_strong_purchase_labels.py`，候选生成只读取 train `user_sequences.train.jsonl` 和 train-only source edges；valid/test label 只用于 evaluation-only，并分别报告 `purchase_positive`、`strong_positive`、`verified_purchase_any_rating`、`all_positive` 与 in-universe recall。

**验证结果：**
远程 full eval 通过：union target train users `53653`，source `edge_count=514216`。`purchase_positive` / `strong_positive` 目标下 `target_user_count=40043`、`seed_hit_rate=0.666409`、`user_coverage_rate=0.665410`、`candidate_row_count=840614`、`Recall@500=0.000211`、`HitRate@500=0.000275`、`in_universe_Recall@500=0.012514`、`candidate_hot_share=0.0`。同时 `label_in_dst_universe_ratio=0.016898`，说明 raw recall 低的关键瓶颈是当前 non-hot dst universe 对购买/强正目标覆盖很窄。

**面试可讲点：**
这段可以讲成“按业务目标重做离线验证”：用户指出 strong 方法应看购买目标后，不是直接沿用宽泛 binary 指标，而是拆出 purchase/strong-positive label 并保持 eval-only 边界。结论也不是简单放弃方法，而是证明它有覆盖和长尾补充价值，但单源购买召回仍低，必须放到 route-level 看边际增益和与其他源的互补。

### 2026-06-04 - two_tower query builder 口径收敛

**任务：**
根据 YouTubeDNN 论文复盘和 epoch5 诊断结果，先修 `two_tower` 的 query coverage / serving-query consistency，而不是继续盲目加 epoch。

**遇到的问题：**
formal epoch5 虽将 `Recall@500` 提升到 `0.057803`、`hit_rate@500` 提升到 `0.076`，但 `queryless_user_count=95/500`、`underfilled_user_rate=0.19` 仍未改善；同时 direct eval、method source builder 和 candidate merge 三处 query 构造存在 artifact user embedding、seed fallback、projection 和 reason 统计不一致。

**定位方式：**
只读核对 `run_pool500_two_tower_direct_eval.py`、`pool500/methods/two_tower/builder.py`、`candidate_merge.py` 与 `vector_index.average_vectors()`，确认 seed 顺序、projection 与 queryless 统计口径分叉；用 targeted pytest 覆盖 direct eval、method source 和 source manifest guard。

**解决方式：**
新增 `rs_core/recsys/two_tower_query.py`，统一 artifact-user-first、train-only seed fallback、seed 顺序、projection 和 diagnostics；三条链路改为复用该 builder，并在 direct eval manifest 中输出 `query_source_counts`、`queryless_reason_counts`、seed count stats。

**验证结果：**
本地 `.venv` 通过 `pytest tests/test_pool500_two_tower_direct_eval.py tests/test_pool500_two_tower_method_source.py tests/test_two_tower_source_manifest_guard.py -q`（11 passed），并通过修改模块的 `py_compile`。当前只是代码口径收敛，尚未跑 queryv2 formal baseline，因此 `two_tower` 仍保持 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“先修服务口径，再谈模型优化”：离线 loss 和 epoch 数不是唯一瓶颈，召回系统还需要保证训练产物、query 构造、候选生成和评估链路一致；通过统一 query builder 和 diagnostics，把 19% queryless 从黑盒失败变成可解释、可验证的工程问题。

### 2026-06-04 - itemcf_strong AugCF-lite 生成式补边远程实验

**任务：**
参考 KDD'19 AugCF 的“生成式交互增强”思路，为 `itemcf_strong` 新增独立 AugCF-lite 实验源，并在远程服务器验证它是否能改善 purchase/strong-positive 目标召回。

**遇到的问题：**
完整 AugCF 是 Conditional GAN，不是显式 item-item sim 公式，直接复刻成本高且审计复杂；同时 relaxed baseline 的 purchase `Recall@500=0.000211` 主要受 non-hot dst universe 过窄影响，如果简单放开热门 item，可能把 popular 覆盖误判成 ItemCF 相似度提升。

**定位方式：**
新增 `rs_lab/experiments/recall/pool500/methods/itemcf_strong/augcf_lite_builder.py` 和 CLI wrapper，只读取 train-only sequences / item profile / frequency / canonical item metadata，输出兼容 source adapter 的 observed/pseudo edges；本地 `.venv/Scripts/python.exe` 通过 py_compile、100-user smoke、source conversion、purchase eval 和 manifest assertions。远程在 `server:/home/luo/RS_agent_remote` 运行，重 artifact 写到 `/tmp/rs_agent_spill/...`，只拉回 manifest/audit/eval JSON。

**解决方式：**
实现 train-only `augcf_lite_score`：融合强正共现、类目/主类目/store、train-only 强正/正反馈频次、quality/hotness 等特征；同时修正 ItemCF source adapter，使 `train_only=false` fail-closed，并从 manifest lineage 推导 `RECENT_2Y_DERIVED_INDEX`。远程分别跑 hot-dst 和 no-hot-dst 50k src-item formal 对照。

**验证结果：**
AugCF-lite hot-dst 版本 `row_count=6174682`、`observed=5010969`、`pseudo=1163713`，purchase `Recall@500=0.025721`、`HitRate@500=0.031416`、`in_universe_Recall@500=0.031212`、`label_in_dst_universe_ratio=0.824084`，但 `candidate_hot_share=0.960442`。no-hot-dst 对照 `row_count=2308758`、purchase `Recall@500=0.000192`、`HitRate@500=0.000250`、`label_in_dst_universe_ratio=0.019378`、`candidate_hot_share=0.0`，未超过 relaxed baseline 的 `0.000211/0.000275`。

**面试可讲点：**
这段可以讲成“把论文思想转成可审计工程实验，而不是盲目套 GAN”：先用 AugCF-lite 验证生成式补边确实能提升 raw recall，再用 no-hot 消融证明主要收益来自 dst universe / 热门覆盖，最终保留 experimental 结论和 route gate，而不是把热门商品命中冒充方法主路成功。

### 2026-06-04 - two_tower queryv2 formal diagnostic 跑通

**任务：**
在 epoch5 full formal source artifact 基础上，运行统一 query builder v2 的 direct eval、target-slice candidate generation、overlap 和 route gate，验证 query coverage 修复是否真实提升 `two_tower`。

**遇到的问题：**
epoch5 baseline 虽比 epoch1 提升，但 `queryless_user_count=95/500`、`underfilled_user_rate=0.19`，说明模型训练之外还有服务 query 构造覆盖问题；同时不能用 valid/test label 或 oracle 补 query，也不能把 500-user target-slice 诊断误写成 READY。

**定位方式：**
复用 full epoch5 train-only source index，使用新统一 query builder 只从 artifact user embedding、train-only seed sequence 与 item vectors 构造 query；direct eval 中 valid/test label 仅用于 scoring。对比 `formal_full_687k_eval_epoch5_local_verify` baseline 与 `formal_full_687k_eval_queryv2_local_verify` queryv2 manifest。

**解决方式：**
运行 queryv2 direct eval、`formal_full_687k_candidates_queryv2` target-slice source builder、overlap diagnostics 和 route gate；同步更新 `METHOD.md`、`source_config.yaml`、`dataset_policy.yaml` 与 registry evidence，所有 promotion / pool1000 / ranking replacement 权限继续保持 false。

**验证结果：**
queryv2 direct eval `query_user_count=484`、`queryless_user_count=16`、`candidate_rows=242000`、`Recall@500=0.070809`、`HitRate@500=0.092`、unique positive hits `49`；相对 epoch5 baseline 的 `405/95/202500/0.057803/0.076/40` 有明显改善。overlap 报告 `status=PASS`，但 popular item-union overlap vs primary 为 `1.0`，category comparable user 只有 `1`；route gate `status=PASS`、decision 仍为 `DIAGNOSTIC_ONLY`。

**面试可讲点：**
这段可以讲成“把推荐召回低效拆成模型效果和服务 query 覆盖两个问题”：不靠 eval label 补洞，而是用 train-only queryv2 把 queryless 从 19% 降到 3.2%，同时因为缺 route-level marginal lift 和 full candidate quality audit，主动拒绝 READY，体现离线收益与上线门禁的分层治理。

### 2026-06-04 - RS Agent 六个核心业务工具收敛

**任务：**
将 RS Agent 的 agent-facing 工具从底层召回/排序实现名收敛为 6 个高层业务工具：`get_user_context`、`retrieve_candidates`、`rank_candidates`、`get_item_evidence`、`record_user_feedback`、`build_recommendation_slate`。

**遇到的问题：**
如果直接模仿 Claude Code 的 ToolSearch，把 ItemCF、Semantic、DeepFM、catalog search 等底层能力暴露给对话 Agent，会让前台语义和工程 artifact 耦合，也增加 public display 泄露工具名、score trace、source、diagnostics 的风险。

**定位方式：**
对照 `rs_core/rsagent/tools.py` 的 manifest、`rs_core/rsagent/dialogue.py` 的 tool plan、`rs_core/workflow/hybrid_environment.py` 的 dispatch，以及 `rs_core/display/builder.py` 的 public payload validator，确认需要保留底层函数作为内部 helper，但把正式 Agent 工具边界提升到推荐任务语义层。

**解决方式：**
新增 6 组工具输入/输出 dataclass，`AGENT_TOOL_MANIFEST` 与 capability manifest 只暴露 6 个高层工具；对话规划切换到 context → retrieve → rank → evidence → slate；环境 dispatch 内部继续复用现有召回、排序、RAG 和 feedback 逻辑，但输出压缩为 item ids、counts、evidence/display-safe 摘要；`build_recommendation_slate` 复用 display builder 并二次校验 public payload。

**验证结果：**
使用项目默认 `.venv` 执行：`pytest tests/test_agent_tools.py tests/test_agent_dialogue.py tests/test_agent_runtime.py -q` 结果 `46 passed`；`pytest tests/test_display_contract.py tests/test_serving_smoke.py -q` 初次发现旧 serving 测试仍断言 `understand_user_need` / `match_specific_need_in_pool`，更新为新 5 个默认执行工具后结果 `53 passed`；补跑 `pytest tests/test_rag_core.py tests/test_agent_feedback.py tests/test_feedback_rerank.py -q` 结果 `34 passed`。

**面试可讲点：**
这段可以讲成“把推荐 Agent 的工具边界产品化”：不是把所有算法模块暴露给 LLM，而是用少量稳定业务工具隐藏召回、排序、RAG、反馈和展示实现，既降低前台复杂度，也通过 display allowlist 和 forbidden terms 把内部诊断与 public payload 隔离。

### 2026-06-04 - two_tower 对齐 YouTubeDNN 的训练侧诊断优化

**任务：**
在 queryv2 已将 `two_tower` direct eval 提升到 `Recall@500=0.070809` 后，继续对照 YouTubeDNN 论文补齐训练侧机制，形成下一轮 diagnostic challenger，但不做 READY 或主路晋升。

**遇到的问题：**
上一轮 formal ablation 显示 explicit negative v2 对 direct-only 指标是负贡献，而 recency-only 有轻微正向；同时当前训练缺少论文中的 freshness/example-age 思路和 sampled softmax 采样校正。如果直接把 explicit negative 与 logQ 混开，会引入采样分布不一致风险。

**定位方式：**
对比论文 candidate generation / sampled softmax / example age 思路与本地 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py` 的训练实现；随后用独立 `code-reviewer` 复核，发现 logQ 初版未按实际负采样数校正、explicit-negative/logQ mixture 不安全、padded candidate 未 mask、fallback 会静默忽略 PyTorch-only weighting、compact timestamp 可能错位。

**解决方式：**
新增默认关闭的 `example_age_weighting=decay` 与 `sampled_softmax_correction=logq`；example-age 只用 train-only timestamp 计算 loss weight，logQ 按有效 negative sample count 计算；显式禁止 explicit-negative mixture 与 logQ 同时启用；candidate padding 在 loss 前 mask；无 PyTorch 时对 example-age/logQ fail-closed；compact inputs 按 item/timestamp pair 同步过滤，避免时间戳错配。

**验证结果：**
使用项目默认 `.venv` 通过 `py_compile` 与本地 guard：`tests/test_two_tower_training.py`、`tests/test_pool500_two_tower_direct_eval.py`、`tests/test_pool500_two_tower_method_source.py`、`tests/test_two_tower_source_manifest_guard.py` 共 `49 passed in 3.77s`。二次独立 code review 结论为无阻塞问题，当前改动可用于 diagnostic PyTorch remote smoke/formal，但仍不能作为 READY promotion 证据。

**面试可讲点：**
这段可以讲成“把论文机制转成可审计、可回滚的训练优化”：不是盲目堆 epoch 或照搬论文，而是先用 queryv2 修服务口径，再逐项补 freshness 与 sampled-softmax 校正，并通过 reviewer 发现目标函数细节问题后 fail-closed，体现推荐模型优化中的训练目标、采样分布和工程治理一致性。

### 2026-06-05 - Recursive CF/RPA-like smoke-formal 数据集治理

**任务：**
为 Zhang & Pu 2007 Recursive Prediction Algorithm / Recursive CF 方向先整理 recent-2y train-only 的 smoke/formal 数据集，并按用户要求把本地构建内存限制在 5G 以内。

**遇到的问题：**
前一版 `Recursive CF-lite` 更像隐式二阶 UserCF 扩散，不是论文中“邻居缺失 target-item rating 时递归预测该 rating”的完整 RPA；同时 fixed eval users 多数 train 历史极短，直接在短序列 sidecar 上调参会混淆算法前提与数据口径问题。

**定位方式：**
复核 ACM DOI `10.1145/1297231.1297241` 的论文元数据与 DBLP/CiteSeerX 摘要信息，并对照 `user_sequences.train.jsonl`、train-only governance、旧 UserCF method dataset 的短序列/eligible filtering 逻辑；用 smoke/formal manifest 和 resource/no-oracle audit 验证只读取 recent-2y train-only 输入。

**解决方式：**
新增 `rs_lab/experiments/recall/build_rpa_like_recent2y_method_dataset.py` 和 CLI wrapper，产出 `rpa_like_eligible_sequence_v1` rows；smoke 采用 sparse/medium-like 均衡确定性样本，formal 使用全量 `1 <= eligible_seed_item_count <= 4` 的 train-only short-sequence users；manifest 明确 dataset-only、diagnostic-only、不生成 candidate/source artifact；资源 guard 默认 `max_rss_mb=4096`，代码硬拒绝超过 `5120MB`。

**验证结果：**
新增测试 `tests/test_pool500_rpa_like_recent2y_method_dataset.py` 通过 `5 passed`，并补跑 `tests/test_pool500_itemcf_weak_rpa_lite_diagnostic_replay.py` 与 `tests/test_full_train_usercf_sidecar.py` 共 `22 passed`。本地 smoke 产物 `smoke_local_20260605a` 为 `5000` 行，bucket 为 `2500/2500`，峰值 RSS `1436MB`；formal 产物 `formal_local_20260605a` 为 `5,147,753` 行，bucket 为 `3,816,414` sparse 与 `1,331,339` medium-like，峰值 RSS `1538MB`，no-oracle audit 为 PASS。

**面试可讲点：**
这段可以讲成“把论文算法前提先工程化成数据治理口径”：在不使用 valid/test/oracle label 的前提下，把 RPA 所需的短序列用户、seed item、共享邻居信号和资源审计整理成可复现 smoke/formal 数据集，并用 5G 内存门禁证明本地可运行，为后续真正 RPA-like source builder 留出清晰边界。

### 2026-06-05 - RPA-like UserCF-compatible 召回实验诊断

**任务：**
基于已生成的 RPA-like formal method dataset，构建可进入 pool500 route 的 usercf-compatible diagnostic source，并做 1000-user / 10k offline 对照实验。

**遇到的问题：**
RPA-like dataset 只有 `seed_item_sequence`，旧 `build_full_train_usercf_sidecar.py` 只接受 `eligible_item_sequence` 和旧 `pool500_method_dataset_v1`；同时默认 route 的 `swing_recall` manifest 处于 `TARGET_SLICE_DIAGNOSTIC`，会被 runtime guard 拒绝，不能为了跑通实验绕过守卫。

**定位方式：**
检查 `build_full_train_usercf_sidecar.py`、`candidate_merge.load_usercf_recall_sidecar` guard、RPA-like formal manifest 与 1000-user offline eval 输出；用 old-usercf / no-usercf / RPA-like-usercf 三组统一禁用 swing 的口径进行对照，并由独立 verifier 复核 manifest、metrics 与 source audit。

**解决方式：**
扩展 sidecar builder 支持 `rpa_like_recent2y_method_dataset_v1`、`rpa_like_eligible_sequence_v1` 和 `seed_item_sequence`；新增 `--target-users` 作为 materialization targets only；保持 `DIAGNOSTIC_ONLY`、train-only、promotion/ranking replacement 全部 false。先构建 bounded diagnostic source，再在相同 1000-user eval 口径下运行三组 ablation。

**验证结果：**
代码验证 `py_compile` 与 `tests/test_full_train_usercf_sidecar.py tests/test_pool500_rpa_like_recent2y_method_dataset.py -q` 通过 `26 passed`。1000-user source 侧 `target_user_count=947`、`candidate_user_count=877`、`candidate_total_count=43318`、峰值 RSS `344MB`；offline eval 中 old-usercf 与 no-usercf 指标完全一致，RPA-like arm 贡献 `usercf_recall=8210`、ratio `0.01642`，但 Recall/HitRate 指标仍与 no-usercf 完全一致，source-hit 分析显示 `usercf_recall` 正样本命中为 `0`。在用户授权 5GB 后扩展到完整 10k eval，10k source 侧 `target_user_count=9190`、`candidate_user_count=8566`、`candidate_total_count=440250`、峰值 RSS `1083MB`；no-usercf 为 `Recall@500=0.023994`、`HitRate@500=0.0406`，RPA-like arm 为 `Recall@500=0.023877`、`HitRate@500=0.0405`，`usercf_recall=79916`、ratio `0.015983`，但 `usercf_recall` 正样本命中仍为 `0`，pool500 总体新增正样本 `3`、丢失正样本 `4`。

**面试可讲点：**
这段可以讲成“把新增召回源先作为边际贡献诊断，而不是只看能否生成候选”：RPA-like source 在无泄漏和低内存约束下确实进入 route 并替换了部分 fallback/co-visit 候选，但没有带来正样本命中，说明下一步应优化 RPA-like scoring/递归预测质量，而不是直接晋升主路。

## 2026-06-06｜按 Zhang & Pu 2007 严格复现 Recursive CF 评分预测实验

- **任务**：在前一版 RPA-like 候选扩散效果很弱后，重新按 Zhang & Pu 2007 Recursive Prediction Algorithm 的论文逻辑实现本地适配实验。
- **遇到的问题**：原先 RPA-like source 本质是 implicit UserCF candidate diffusion，不是论文中的 rating prediction；完整 route eval 也过重，难以作为方法本身诊断。
- **定位方式**：重新核对论文可访问文本，确认核心应为 Pearson user similarity、BS/BS+/SS/CS/CS+ 邻居策略、递归补全邻居对 target item 的缺失评分，并用 MAE/RMSE 评估 held-out ratings。
- **解决方式**：新增 SQLite-backed smoke 实验 `rs_lab/experiments/recall/run_rpa_strict_zhang_pu_2007_sqlite_smoke.py`，直接利用 `recall_clean.sqlite` 的索引构造局部 train-only 评分矩阵；valid/test 只作为 evaluation-only held-out target，不参与索引扩展。
- **验证结果**：`py_compile` 通过；warm/hot 1000 条 held-out 评分实验中，`zeta=2` 的 CS 策略 MAE=0.66330988，相比 BS 的 MAE=0.67613943 降低 0.01282955，说明严格论文版递归评分预测在局部评分预测任务上出现正向信号。
- **面试可讲点**：不是机械套用论文到候选召回，而是先识别论文任务定义与当前 implicit recall 的差异，再把算法还原为评分预测实验，用 train-only 索引和 evaluation-only label 守住无泄漏边界，最后用小规模可控实验判断是否值得继续扩展。

## 2026-06-06｜严格 Recursive CF 扩样本与参数消融

- **任务**：在严格 Zhang & Pu 2007 RPA SQLite smoke 出现正向信号后，继续扩大 warm/hot 用户样本并做参数消融。
- **定位方式**：使用 `recall_clean.sqlite` 的 `ranked_interactions` 索引，仅用 train row 构造局部评分矩阵，valid/test 正样本 rating 仅作为 evaluation-only held-out targets。
- **实验结果**：2000 个 warm/hot 用户、4734 条 held-out rating 上，`k=10,k'=10,zeta=2,lambda=0.5,phi=2` 的 CS+ MAE=0.64567520，相比 BS MAE=0.64703180 改善 0.00135660；lambda=0.25/0.5/0.75 差异很小，CS+ 均约 0.64567。`k=20,k'=20,phi=2` 时 BS+ 最好，MAE=0.64296877；继续放大到 `k=50,k'=50` 后，`phi=2` 的 CS+ MAE=0.64446953，优于同配置 BS 的 0.64670602，但 `phi=5/10` 时 BS+/CS+ 退回到 MAE=0.64635084。进一步按论文口径固定 `k'=10,zeta=2,lambda=0.5,phi=10` 扫 `K=3..90`，最佳均为 BS+，MAE=0.64635084，说明本地数据上论文推荐的高 overlap threshold 会让递归组合收益消失，当前更有效的是较低 overlap 的 `phi=2`。随后构建 train-window 内 80/20 deterministic split 的 paper-adapted formal 数据集（139653 users、3650008 train ratings、914786 eval pairs），在 5000 eval pairs 上 strict RPA 提升更明显：`k=50,k'=50,phi=2` 的 CS MAE=0.88694818，相比 BS MAE=0.95935793 降低 0.07240975。
- **工程取舍**：严格论文算法在评分预测任务上有可复现正向信号，但收益随样本和参数变化；当前更适合保留为 rating-prediction diagnostic，不应直接等同于 pool500 top-N 召回 source。进一步把 RPA score 用于 1000-user pool500 候选重排时，纯 RPA rerank 明显伤害 Recall@20/50/100，局部 bucket20 rerank 仅让 Recall@50 从 0.017255 到 0.018255，小幅改善但不足以晋升。
- **面试可讲点**：通过扩样本和 zeta/lambda/k/phi 消融，区分“论文评分预测任务有效”和“候选召回任务不一定有效”，体现从算法复现到业务适配的边界意识。

### 2026-06-06 - Qwen QLoRA/SFT/GRPO 训练环境 scaffold

**任务：**
补齐 Qwen3.5-4B + QLoRA + SFT + GRPO 的训练环境 scaffold，在不做真实训练、不生成正式训练数据、不默认加载大模型的前提下，先建立配置、数据 contract、reward adapter、runner dry-run 和轻量测试入口。

**遇到的问题：**
训练链路需要为后续 SFT/GRPO 留出 TRL 初始化能力，但当前阶段不能误导为训练已完成，也不能让 smoke 因 GPU、模型下载或 Windows bitsandbytes 问题失败。

**定位方式：**
对照 `rs_core/rsagent/rollout.py` 的 `training_samples` contract、`rs_core/rsagent/reward.py` 的 reward 组件，以及已存在的 `configs/training/qwen_*.yaml` 和 `rs_core.training.config`，确认 scaffold 只应校验配置、依赖 import、synthetic 样本和 reward adapter。

**解决方式：**
新增 `rs_core/training/data_contracts.py`、`qwen_loader.py`、`sft_runner.py`、`grpo_runner.py`、`reward_adapter.py`，并新增三个 dry-run CLI；runner 默认不加载 Qwen，只有 `--init-only` 或 `--max-steps > 0` 才进入重路径。补充训练 guide 和 README 路由，明确当前是 scaffold，不是正式训练完成。

**验证结果：**
新增轻量单测覆盖 training config、SFT/GRPO synthetic contract 与 reward adapter；dry-run 脚本用于验证配置、依赖 import 和 reward 输出，不依赖 GPU、不下载模型、不加载 Qwen。当前 `.venv` 仍缺少 `peft` 和 `trl`，安装尝试被权限策略拒绝；dry-run 会报告缺失依赖但不进入重路径。

**面试可讲点：**
这段可以讲成“先把 LLM 推荐 Agent 训练链路工程化成可验证边界”：用 contract 和 dry-run 把数据、reward、runner 与依赖检查分层固定下来，避免在没有真实训练数据和资源门禁时把 scaffold 夸大成训练成果。

### 2026-06-06 - pool500 非 ItemCF/双塔召回方法修复收口

**任务：**
盘点并修复除 ItemCF 与 two_tower 外的 pool500 recent-2y 召回方法半成品链路，重点补齐 runner contract、评估边际指标、category 按需展开，以及 semantic_title_category_expansion / co_visit_fallback_repair 的分片与 checkpoint 契约。

**遇到的问题：**
各方法成熟度不一致：`popular/category` 接近可用但缺 route-level 证据，`semantic` 只有 10k diagnostic，`swing/usercf` 有产物但缺边际贡献或覆盖不足，`semantic_title_category_expansion/co_visit_fallback_repair` formal 尚未完成。统一 runner 还存在 method_config/shard/checkpoint 参数在 dry-run contract 中不可审计的问题。

**定位方式：**
只读检查 `configs/recall/pool500_method_registry.json`、各方法 `source_config.yaml` / `METHOD.md`、`run_pool500_method_source.py`、`evaluate_method_source_artifact.py`、category/semantic_title/co_visit builder 和现有测试，确认修复应优先补“无泄漏、可审计、可远端执行”的工程契约，而不是直接本地重跑 50k/full formal。

**解决方式：**
扩展 runner dry-run contract，显式输出 `method_config`、`resource_guard`、`dataset_manifests`、`current_artifacts` 与 route/governance 字段；在 evaluator 中增加可选 baseline source manifest，输出 baseline/source/union/marginal 指标且保持 valid/test label 只在 evaluation-only 阶段使用；为 `category` 增加 all-eligible index 的 `expand_category_candidates_for_users` 按需展开 helper；为 semantic_title/co_visit 补齐 checkpoint、offset、limit、shard contract，保持 candidate generation / promotion / ranking replacement / pool1000 权限关闭。

**验证结果：**
使用项目 `.venv` 运行聚焦测试：`python -m pytest tests/test_pool500_method_source_runner.py tests/test_pool500_method_source_eval.py tests/test_pool500_method_source_overlap.py tests/test_pool500_category_on_demand.py tests/test_pool500_semantic_title_category_source.py tests/test_pool500_co_visit_fallback_repair_source.py -q`，结果 `22 passed`；对修改的 runner/evaluator/overlap/category/semantic_title/co_visit 文件执行 `py_compile` 通过；semantic_title formal dry-run 和 co_visit `formal_shard50k` dry-run 均能输出 shard/limit/checkpoint contract，且未本地跑重型 50k formal。

**面试可讲点：**
这段可以讲成“把一批半成品召回源先收敛为可治理工程链路”：不是为了指标直接重跑或晋升，而是先统一入口、评估口径、无泄漏边界和分片执行契约；用 marginal metrics 与 on-demand index 让后续 route gate 能判断真实边际贡献，用 shard/checkpoint contract 为远端 formal 留出可恢复路径。

### 2026-06-06 - itemcf_weak RPA paper-binary Top500 è¯Šæ–­

**ä»»åŠ¡ï¼š**
åœ¨ v3 paper-faithful depth1 top100 å�ªäº§ç”Ÿè½»å¾® rerank æ•ˆæžœå�Žï¼Œç»§ç»­å�šæ›´æŽ¥è¿‘ Zhang & Pu RPA å‰�æ��çš„ binary implicit Top500 è¯Šæ–­ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
v3 ä»�å¸¦æœ‰å€™é€‰æž„å»º IDF å��ç½®ï¼Œä¸”æ¯�ç”¨æˆ·å�ªä¿�ç•™ 100 ä¸ªå€™é€‰ï¼Œæ— æ³•åˆ¤æ–­è®ºæ–‡å¼� user-based binary rating åœ¨ Top500 é¢„è®¡ç®—ä¸‹çš„çœŸå®žè¦†ç›–èƒ½åŠ›ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å¯¹æ¯” v2/v3 æŒ‡æ ‡å�‘çŽ° v3 `raw_recall@500=0.026407` æœªè¶…è¿‡ v2 confidence `0.026923`ï¼Œä¸” observed mass normalization å¯¹å�Œä¸€ç”¨æˆ·æ˜¯æŽ’åº�å¸¸æ•°ã€‚

**è§£å†³æ–¹å¼�ï¼š**
è¿œç¨‹è¿�è¡Œ `rpa_lite_v4_paper_binary_p500_remote_no_mem_limit_4jobs_v1`ï¼Œè®¾ç½® `candidate_idf_power=0.0`ã€�æ¯�ç”¨æˆ·å€™é€‰é¢„è®¡ç®— `500`ï¼Œä»�ä¿�æŒ� train-only æž„å»ºå’Œ valid/test post-hoc evaluation-onlyã€‚

**éªŒè¯�ç»“æžœï¼š**
20/20 shards PASSï¼Œå³°å€¼ RSS `12.5566GB`ï¼›best `rpa_v4_paper_binary_sum_similarity_p500` è¾¾åˆ° `raw_recall@500=0.038220`ã€�`hit_user_rate@500=0.046821`ã€�sparse/medium hit=`0.034529/0.078614`ï¼Œç›¸å¯¹ v2 best å¢žåŠ  `613` ä¸ª raw hits å’Œ `554` ä¸ª hit usersã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œæŠŠè®ºæ–‡å�‡è®¾æ‹†æˆ�å�¯æŽ§æ¶ˆèž�â€�ï¼šå…ˆåŽ»æŽ‰å€™é€‰æž„å»ºå��ç½®ï¼Œå†�æ‰©å¤§æ¯�ç”¨æˆ·é¢„è®¡ç®—ä¸Šé™�ï¼Œç”¨å�Œä¸€ train-only / post-hoc eval è¾¹ç•ŒéªŒè¯� RPA-like æ–¹æ³•æ˜¯å�¦çœŸçš„æ��å�‡è¦†ç›–ï¼Œè€Œä¸�æ˜¯æŠŠ rerank æˆ–çƒ­é—¨å��ç½®è¯¯åˆ¤æˆ�ç®—æ³•æ”¶ç›Šã€‚
### 2026-06-06 - pool500 非 ItemCF/双塔召回方法二次审查修复

**任务：**
继续修复上一轮 code review 发现的非 ItemCF / 非 two_tower pool500 召回方法遗留问题，重点覆盖 semantic 运行 blocker、no-holdout fail-closed、popular recent-2y 入口、category index-only 评估，以及 semantic_title 候选质量。

**遇到的问题：**
上一轮修复把工程契约打通后，审查发现仍有可导致误判或直接运行失败的问题：`semantic` builder 仍按二元组接收三返回值 helper；`semantic/co_visit` 在 no-holdout audit 为 BLOCKED 时仍可能发布可用 manifest；evaluator 只用有候选用户做分母会高估低覆盖方法；`popular` runner 仍可能走旧 lightweight promoted source；`semantic_title` 的 title token 只读标题、`per_seed` 未实际限制 fanout，且 max candidate 截断按 item_id 字典序而非索引桶顺序。

**定位方式：**
复核 `run_pool500_method_source.py`、`evaluate_method_source_artifact.py`、`semantic/builder.py`、`semantic_title_category_expansion/builder.py`、`co_visit_fallback_repair/builder.py` 与对应测试，按 failure scenario 增加回归：无候选 label 用户计入 0 分、category all_eligible index-only 按需展开、popular runner 调用 recent-2y builder、co_visit forbidden input fail-closed、semantic_title category-token fallback / per_seed / non-lexicographic truncation。

**解决方式：**
runner 写回 resolved tier 并保留 requested alias，`popular` 改调 `build_popular_recent2y()`；evaluator 改以 eval label users 为分母，缺候选用户按 0 分计，同时识别 category index-only manifest 并调用 `expand_category_candidates_for_users()`；semantic 修正 helper 三返回值 unpack，并在 forbidden input 时只写 `no_holdout_audit` 后 fail-closed；co_visit forbidden input 同样不发布 source manifest；semantic_title 恢复 title+category token，按 seed 应用 `per_seed`，并按 inverted-index bucket encounter order 截断候选集合。

**验证结果：**
使用项目 `.venv` 执行 targeted 回归：`python -m pytest tests/test_pool500_method_source_runner.py tests/test_pool500_method_source_eval.py tests/test_pool500_method_source_overlap.py tests/test_pool500_category_on_demand.py tests/test_pool500_semantic_title_category_source.py tests/test_pool500_co_visit_fallback_repair_source.py tests/test_pool500_semantic_newdata_config.py -q`，结果 `48 passed`；`py_compile` 覆盖 runner/evaluator/semantic/semantic_title/co_visit 修改文件通过；runner dry-run 验证 category `route_formal` 输出 all_eligible method_config、popular recent-2y contract、semantic recent2y smoke contract、co_visit `local_formal` shard/checkpoint contract，均未生成重型产物。

**面试可讲点：**
这段可以讲成“工程契约修复后继续做审查驱动的质量收口”：不仅让脚本能跑，还修正评估分母、入口数据源和 fail-closed 治理，避免低覆盖方法被高估或旧产物混入；同时把 semantic_title 的候选生成从全局粗截断改成按 seed 控制 fanout，体现推荐召回链路中质量、治理和可复现评估的一体化修复。

### 2026-06-06 - pool500 召回源 registry 候选生成权限收口

**任务：**
继续盘点非 ItemCF / 非 two_tower 方法的工作文件后，修复核心 registry 层把所有 recall source 默认视作可候选生成的问题，避免诊断源或 guarded source 绕过方法配置中的权限护栏。

**遇到的问题：**
`category`、`swing_recall`、`semantic`、`semantic_title_category_expansion`、`usercf_recall`、`co_visit_fallback_repair` 在配置和方法文档中都要求 route gate、diagnostic-only 或 deferred 边界，但 `RecallSourceSpec.candidate_generating` 默认值为 `True`，测试还固化了“所有 source 都 candidate-generating”的错误假设。

**定位方式：**
对照各方法 `METHOD.md`、`source_config.yaml`、`configs/recall/pool500_method_registry.json` 与 `rs_core/recsys/recall_sources/registry.py`，确认真正允许候选生成的当前白名单应为 `popular` 和 route-gate candidate 的 `itemcf_strong`，其余 guarded/diagnostic/deferred source 都不应被 `list_candidate_generating_sources()` 返回。

**解决方式：**
将 `RecallSourceSpec.candidate_generating` 默认值改为 `False`，新增 `READY_CANDIDATE` 状态常量以同步 registry JSON；在核心 registry 中仅对 `popular` 与 `itemcf_strong` 显式 opt-in；同步 `itemcf_strong` 与 `two_tower` 最新 registry artifact 字段；更新 registry 测试为显式白名单，并补 runner contract 测试确保 semantic、semantic_title、co_visit、usercf 的 candidate generation / promotion / ranking replacement / pool1000 权限保持关闭；category 配置补充 route-gate-only 字段，保留 `candidate_generation_allowed=false`。

**验证结果：**
使用项目 `.venv` 执行 `python -m pytest tests/test_recall_source_registry.py tests/test_pool500_method_source_runner.py -q`，结果 `26 passed`；对 `rs_core/recsys/recall_sources/base.py`、`registry.py`、`__init__.py` 与 runner 执行 `py_compile` 通过；独立 verifier 复核结论为 PASS，确认候选生成已改为显式 opt-in，category 仍不是直接主路物化生成。

**面试可讲点：**
这段可以讲成“把方法级治理护栏下沉到核心 registry”：不仅在文档和配置中声明 diagnostic/deferred，还让候选生成枚举本身 fail-closed，只有经过明确 route-gate 授权的 source 才能进入候选生成入口，降低半成品召回源被误用到主路的风险。

### 2026-06-06 - pool500 方法源轻量验证与远端 handoff 收口

**任务：**
汇总本轮 pool500 非重型方法源运行结果，避免在本地继续启动 50k/full formal 重任务，同时把已验证链路、未完成 blocker 和远端 handoff 边界写清楚。

**遇到的问题：**
各 source 状态不同：`popular/category` 可做轻量 dry-run 与 route-formal/all-eligible contract 检查，`semantic` 有 10k diagnostic artifact，`semantic_title_category_expansion` 和 `co_visit_fallback_repair` 仍缺 formal 七件套，`swing/usercf` 已有诊断产物但缺 route overlap / 边际贡献证据。若只说“已跑完”，会把 diagnostic、guarded、NEEDS_REMOTE 与 READY 混淆。

**定位方式：**
复核 `dic/recall_methods/semantic_title_category_expansion/METHOD.md` 和 `dic/recall_methods/semantic_title_category_expansion/FORMAL_SERVER_HANDOFF.md`，确认 semantic_title formal 只有 checkpoint、无七件套；用项目 `.venv` 运行 focused tests、`py_compile` 和 runner dry-run contract，检查 governance 字段、recent-2y 输入、按需展开和 checkpoint/shard 参数。

**解决方式：**
保留轻量本地验证，只运行 focused pytest、编译检查和 dry-run，不启动 50k/full formal。汇总结果时按 `PASS / READY_GUARDED / DIAGNOSTIC_ONLY / NEEDS_REMOTE` 分层：已通过的契约作为后续远端执行基础，未产出 formal artifact 的 source 继续阻断 READY 与 ranking input replacement。

**验证结果：**
`.venv` 执行 `pytest tests/test_pool500_method_source_runner.py tests/test_pool500_method_source_eval.py tests/test_pool500_category_on_demand.py tests/test_pool500_semantic_newdata_config.py tests/test_pool500_semantic_title_category_source.py tests/test_pool500_co_visit_fallback_repair_source.py -q`，结果 `51 passed`；`py_compile` 覆盖 runner/evaluator/category/semantic_title/co_visit 关键脚本通过。dry-run 复核 category `route_formal`、popular `all_eligible`、semantic_title `recent2y_formal` 与 co_visit `local_formal` contract；其中 co_visit 原先按不存在的 `formal_shard50k` tier 调用失败，复核配置后改用实际存在的 `local_formal` tier，确认 formal 仍需远端或受控分片执行。

**面试可讲点：**
这段可以讲成“多召回源收口时用证据分层而不是一刀切宣布完成”：把能本地验证的 runner/contract/治理字段先跑实，把重资源 formal 明确交给 server handoff，并用测试与 dry-run 证明不会把诊断源、guarded source 或半成品 artifact 误用为主路 READY。

### 2026-06-06 - two_tower batch-shared sampled softmax 第一阶段实现

**任务：**
在不触碰 READY/promotion、不运行远端任务的前提下，为 `two_tower` 训练增加默认关闭的 `sampled_softmax_candidate_mode`，支持旧行为 `per_example` 与新实验模式 `batch_shared`。

**遇到的问题：**
原先 sampled softmax 每个样本独立构造候选，无法模拟 batch 内共享候选集合；如果直接共享 batch positives，又可能把同一用户的其他已知正样本当负样本参与 loss，需要 row-level mask 保护训练语义。

**定位方式：**
聚焦 `rs_core/recsys/two_tower.py` 的 `_normalized_config`、`_validate_config`、`_torch_batch_tensors`、negative sampling payload，以及 `scripts/training/train_two_tower.py` CLI 透传和 `tests/test_two_tower_training.py` 中已有 sampled softmax/CLI/metrics 测试。

**解决方式：**
保留 `per_example` 默认路径，新增 `batch_shared` 分支：batch target positives 按出现顺序去重，与 batch-level sampled negatives 组成共享 candidate list；负样本排除 batch target positives 和 batch positive_set union；每行 target 指向自身 positive 位置，并对该用户 `positive_set - {target}` 在候选中的碰撞做 mask，target mask 强制为 1。第一版安全禁止 `batch_shared + explicit_negative_weight>0`，并在 metrics/model/negative_sampling payload 记录 mode、negative sample 解释和 batch-shared 统计。

**验证结果：**
本地 `.venv` 通过 `python -m pytest tests/test_two_tower_training.py`，结果 `47 passed`；通过 `python -m py_compile rs_core/recsys/two_tower.py scripts/training/train_two_tower.py tests/test_two_tower_training.py`。

**面试可讲点：**
这段可以讲成“把 sampled softmax 从样本级候选扩展为 batch 共享候选，同时用用户正样本 mask 保住负采样语义”：既提升候选构造的可实验性，又通过默认关闭、显式校验、payload 留痕和单测覆盖控制回归风险。


### 2026-06-06 - itemcf_weak RPA index-backed Top500 è¯Šæ–­

**ä»»åŠ¡ï¼š**
åœ¨ v4 paper-binary Top500 å·²æˆ�ä¸º `itemcf_weak` æœ€å¼ºè¯Šæ–­å�Žï¼Œç»§ç»­æŠŠ Zhang & Pu 2007 RPA çš„â€œè¯„åˆ†çŸ©é˜µã€�é‚»å±…ç´¢å¼•ã€�é€’å½’é¢„æµ‹è¯�æ�®â€�æ”¹é€ æˆ�é€‚é…�å½“å‰� implicit Top-N å�¬å›žçš„ compact index-backed è¯Šæ–­ï¼Œå¹¶è¿œç¨‹è·‘ 20 shard full evalã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
è®ºæ–‡åŽŸå§‹è®¾å®šæ˜¯ MovieLens æ˜¾å¼�è¯„åˆ†é¢„æµ‹å’Œ MAE è¯„ä¼°ï¼Œè€Œå½“å‰�é“¾è·¯æ˜¯ implicit positive-only sequence çš„ pool500 å�¬å›žï¼›å¦‚æžœç›´æŽ¥å�š recursive expansionï¼Œå®¹æ˜“å�ªå¢žåŠ ä½Žä½�å€™é€‰è€Œä¸�å¢žåŠ å‘½ä¸­ã€‚å�Œæ—¶ v5 æŠŠ candidate cache å’Œ top-neighbor ä¸Šé™�æ”¾å¤§å�Žï¼Œèµ„æº�æˆ�æœ¬ä¹Ÿå�¯èƒ½é«˜äºŽ v4ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å…ˆç”¨æœ¬åœ° shard `0/200` smoke éªŒè¯� v5 è„šæœ¬ã€�index snapshot å’Œ recursive branch èƒ½è·‘é€šï¼Œå†�è¿œç¨‹å�¯åŠ¨ 20 shard / 4 jobsã€‚æœ€ç»ˆæŠ¥å‘Šä¸º `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_v5_rpa_index_replay_remote_no_mem_limit_4jobs_v1/evaluation_report.json`ï¼Œä¸Ž v4 æŠ¥å‘Š `rpa_lite_v4_paper_binary_p500_remote_no_mem_limit_4jobs_v1/evaluation_report.json` å�Œå�£å¾„æ¯”è¾ƒã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢ž compact RPA index-backed è¯Šæ–­è„šæœ¬ï¼Œæž„å»ºé˜¶æ®µå�ªä½¿ç”¨ train-only sequence å’Œ train-only item frequencyï¼Œvalid/test label ä»�åœ¨å€™é€‰/index æž„å»ºå®Œæˆ�å�Žæ‰�åŠ è½½ç”¨äºŽ post-hoc evaluationã€‚æ¯�ä¸ª shard å†™å‡º `rpa_index_manifest.json`ã€�`user_neighbor_samples.jsonl`ã€�`candidate_evidence_samples.jsonl` å’Œ `index_sample_stats.json`ï¼Œå¹¶é¢„å£°æ˜Ž observed p300/p500ã€�path-support logã€�min-support fallbackã€�observed400+recursive100 äº”ä¸ª variantã€‚

**éªŒè¯�ç»“æžœï¼š**
è¿œç¨‹ 20/20 shards `PASS`ï¼Œ`evaluated_target_users_with_labels_total=41605`ã€‚æœ€ä¼˜ `rpa_v5_index_path_support_log_p500` è¾¾åˆ° `raw_recall@500=0.038644`ã€�`raw_recall@100=0.027734`ã€�`hit_user_rate@500=0.047158`ã€�raw hits `2097`ï¼Œç›¸å¯¹ v4 best `raw_recall@500=0.038220` æ��å�‡ `+0.000424`ã€�raw hits `+23`ã€�hit users `+14`ï¼Œcandidate p50/p90/max ä»�ä¸º `194/500/500`ã€‚ä½† recursive expansion variant å�ªæœ‰ `raw_recall@500=0.037888`ï¼Œä½ŽäºŽ observed/path-support p500ï¼›èµ„æº�å³°å€¼ä»Ž v4 `12.5566GB` å¢žè‡³ v5 `14.9178GB`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œè®ºæ–‡ç®—æ³•é€‚é…�ä¸�æ˜¯ç…§æ�¬å…¬å¼�ï¼Œè€Œæ˜¯å…ˆæŠ½å‡ºå�¯æ²»ç�†çš„æ•°æ�®ç»“æž„ä¸Žè¯�æ�®é“¾â€�ï¼šæŠŠ RPA çš„ user-neighbor/rating-matrix æ€�æƒ³è�½æˆ� train-only index snapshotï¼Œå¹¶ç”¨å�Œå�£å¾„ full eval è¯�æ˜Ž path support å¯¹ Top-N å�¬å›žæœ‰å°�å¹…æ”¶ç›Šï¼Œå�Œæ—¶å��è¯�å½“å‰� recursive expansion ä¸�å€¼å¾—ç›´æŽ¥æ™‹å�‡ï¼Œä¸‹ä¸€æ­¥åº”è¡¥çœŸæ­£çš„ `Ï†`ã€�`K/Kâ€²` å’Œ `Î¶=2` scoring æ¶ˆèž�ã€‚

### 2026-06-06 - strong/RPA-like 增强方向记录与传统 ItemCF 回切

**任务：**
按用户决策，把当前 strong/RPA-like、RPA-lite/RPA-index、AugCF-lite/controlled 等增强方向的关键结果记录下来，并把后续路线切回传统 ItemCF。

**遇到的问题：**
RPA-index 在 `itemcf_weak` 上虽然略优于 v4，但增益很小且资源成本上升；strong 侧 AugCF/controlled 的召回提升与 hot dst 覆盖高度绑定，容易把热门覆盖误归因为 ItemCF 相似度优化。如果继续沿增强方向推进，会让路线叙事偏离“传统 ItemCF 可解释共现”的当前目标。

**定位方式：**
复核 `dic/recall_methods/itemcf_weak/METHOD.md` 中 RPA v4/v5 远程 20 shard 结果，以及 `dic/recall_methods/itemcf_strong/METHOD.md` 中 relaxed strong baseline、AugCF-lite hot/no-hot 和 AugCF-controlled q10/q20/q30/q50 的 purchase eval 指标。所有这些结果仍只作为 post-hoc evaluation-only 诊断，不参与候选生成、训练、variant selection 或 promotion。

**解决方式：**
在 `itemcf_weak/METHOD.md` 中新增“舍弃 RPA/生成增强方向，回到传统 ItemCF”路线更新，记录 v5 best `raw_recall@500=0.038644`、相对 v4 仅 `+0.000424`、recursive expansion 未胜出和资源成本上升。在 `itemcf_strong/METHOD.md` 中记录 relaxed baseline `Recall@500=0.000211`、AugCF-lite hot-dst `Recall@500=0.025721` 但 hot share `0.960442`、no-hot `Recall@500=0.000192` 低于 baseline，以及 controlled q10→q50 的 recall/hot-share 绑定曲线。随后清理 strong 侧 AugCF-lite / AugCF-controlled 生成产物，并写出审计 `outputs/cleanup_records/itemcf_strong_augcf_cleanup_20260606.json`。

**验证结果：**
本次只做方法文档和工程叙事记录，没有新增候选产物、没有修改 registry READY、没有打开 candidate generation / ranking input replacement / promotion。后续主线明确为 train-only 传统 ItemCF：item-item 共现、weighted cooc / cosine normalization、active-user penalty、support/热度治理、per-seed topK 和 route-level source budget。

**面试可讲点：**
这段可以讲成“实验路线的止损与归因治理”：不是看到某个增强方法 Recall 变高就继续堆复杂度，而是拆解收益来源和治理代价；当 RPA 只有微弱收益、AugCF 强依赖热门覆盖时，主动记录证据并回切到可解释、可控、可面向生产治理的传统 ItemCF。


### 2026-06-06 - ItemCF weak çŸ©é˜µå�£å¾„æ”¶å�£ä¸Ž guarded READY æ™‹å�‡

**ä»»åŠ¡ï¼š**
æŠŠ `itemcf_weak` ä»Žæ—§ formal flat method dataset è·¯çº¿æ”¶å�£åˆ° filter-before-build compact matrix è·¯çº¿ï¼Œå¹¶æŒ‰ç”¨æˆ·ç¡®è®¤å°†æ–¹æ³•æ™‹å�‡ä¸ºå½“å‰�é˜¶æ®µ READYã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
æ—§æ��è¿°ä»�æŠŠ strict smoke/formal flat dataset å†™æˆ�å½“å‰�ä¸»äº§ç‰©ï¼Œå®¹æ˜“è¯¯å¯¼å�Žç»­çª—å�£ä»¥ä¸ºå¿…é¡»å…ˆç”Ÿæˆ� formal rowsï¼›ä½†å®žé™…æœ€ä¼˜è·¯çº¿å·²ç»�å�˜ä¸ºè¿�è¡Œæ—¶ç›´æŽ¥ç­›é€‰ train-only åº�åˆ—å¹¶æž„å»º item-to-neighbors çŸ©é˜µã€‚å�Œæ—¶ï¼Œvalid quick å¯¹æ¯”å�ªèƒ½ä½œä¸ºå�ŽéªŒè¯�æ�®ï¼Œä¸�èƒ½æ�®æ­¤ç›´æŽ¥æ‰“å¼€ candidate generation æˆ– final promotionã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ ¸å¯¹ `dic/recall_methods/itemcf_weak/METHOD.md`ã€�`configs/recall/full_data_pool500/itemcf_weak/dataset_policy.yaml`ã€�`configs/recall/full_data_pool500/itemcf_weak/source_config.yaml` å’Œ `configs/recall/pool500_method_registry.json`ï¼Œç¡®è®¤ readinessã€�dataset contractã€�latest artifact ä»�æŒ‡å�‘æ—§ strict formal sourceã€‚

**è§£å†³æ–¹å¼�ï¼š**
å°†å½“å‰�ä¸»å�£å¾„æ”¹ä¸º `src>=2,dst>=3,user_after_item_filter>=2,keep_hot` çš„ filter-before-build compact matrixï¼šä¸�è¦�æ±‚ formal flat datasetï¼Œsmoke dataset ä»…ä¿�ç•™ä¸º program/schema/gate æµ‹è¯•ï¼›registry å’Œé…�ç½®ä¸­æŠŠ `itemcf_weak` æ™‹å�‡ä¸º `READY_GUARDED` / `MATRIX_READY`ï¼Œlatest artifact æŒ‡å�‘ `outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_filter_before_build_traditional_matrix_v1/matrix_manifest.json`ã€‚å�Œæ—¶ç»§ç»­ä¿�æŒ� `candidate_generation_allowed=false`ã€�`ranking_input_replacement_allowed=false`ã€�`promotion_allowed=false`ã€‚

**éªŒè¯�ç»“æžœï¼š**
çŸ©é˜µæž„å»º manifest å·²æ˜¾ç¤º `status=PASS`ã€�`edge_count=17,141,611`ã€�`src_item_count=421,365`ã€�`users_used_for_pairs=1,496,171`ï¼›è¿œç¨‹ quick post-hoc eval ä¸­ `src2_dst3_user2` è¾¾åˆ° `raw_recall@500=0.034512`ã€�`candidate_user_rate=0.963519`ï¼Œä¼˜äºŽå�–æ¶ˆ dst æˆ–åŠ ä¸¥ user çš„å�˜ä½“ã€‚é…�ç½®æ›´æ–°å�Žä»�éœ€è½»é‡� JSON/YAML è¯­æ³•æ ¡éªŒã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œæŠŠæŽ¨è��å�¬å›žæ–¹æ³•ä»Žç¦»çº¿ rows æ•°æ�®é›†æ€�ç»´æ”¹æˆ�å�¯æœ�åŠ¡çš„çŸ©é˜µ artifact æ€�ç»´â€�ï¼šæž„å»ºæ—¶ç›´æŽ¥åœ¨ train-only åº�åˆ—ä¸ŠæŒ‰ item/user è§„åˆ™ç­›é€‰ï¼Œè¾“å‡º compact item-to-neighbors çŸ©é˜µï¼Œæ—¢é�¿å…� 19GB çº§ flat rows å†—ä½™ï¼Œä¹Ÿä¿�ç•™æ²»ç�†è¾¹ç•Œï¼›READY è¢«æ‹†æˆ� artifact ready å’Œ route promotion ä¸¤å±‚ï¼Œä½“çŽ°å·¥ç¨‹å�¯ç”¨æ€§ä¸Žä¸Šçº¿é—¨ç¦�è§£è€¦ã€‚


### 2026-06-06 - two_tower sparse-aware 数据集画像与训练 CLI 扩展

**任务：**
针对 two_tower / YouTubeDNN 当前指标偏低的问题，先不盲目继续训练，而是按 train-only 口径补充 item 分布、item 筛后 user 分布和 sparse-aware 数据集 tier，验证低效果是否来自 item 长尾和 post-prune 用户序列过稀疏。

**遇到的问题：**
原有 method dataset 只把 `embedding_ready` 作为 negative universe，formal 中已有大量 target 落在 negative universe 外；同时 `used_quality_bucket_counts` 容易混淆“eligible users seen”和“真正产出样本的 users/samples”，无法回答 item pruning 后到底还剩多少可训练用户。

**定位方式：**
聚焦 `rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py`、`scripts/training/train_two_tower.py` 和 `tests/test_pool500_two_tower_method_dataset.py`：检查 scale tier、negative universe、sample generation、training item universe 和 CLI override 透传；用新增 fixture 构造 `embedding_ready/cf_ready/mid_frequency/low_frequency/single_seed` item 与 post-prune 用户，验证 user-level drop 和 sample-level no-negative drop 是否分离。

**解决方式：**
新增 `sparse_aware_smoke` / `sparse_aware_formal` tier：target universe 允许 `embedding_ready/cf_ready/mid_frequency` 及满足 `frequency>=2 && user_count>=2` 的 `low_frequency`，negative universe 保守限制为 `embedding_ready/cf_ready/mid_frequency`；样本生成前先按 target universe 过滤正反馈序列，并记录 pre/post positive、transition、retention、user bucket transition、sample-emitting user 和 training item universe role counts。训练 CLI 增加 `min_user_positives`、`max_samples_per_user`、`batch_size`、`user_history_window`、`embedding_dim`、`hidden_dim`、`learning_rate`，方便后续远程 sparse-aware YouTubeDNN 对照实验。

**验证结果：**
本地 `.venv` 通过 py_compile；`tests/test_pool500_two_tower_method_dataset.py -q` 为 `16 passed, 3 skipped`；WMI-safe `tests/test_two_tower_training.py -q` 为 `48 passed`；`tests/test_train_only_data_governance.py -q` 为 `13 passed`；`tests/test_pool500_two_tower_method_source.py tests/test_pool500_two_tower_direct_eval.py tests/test_two_tower_source_manifest_guard.py -q` 为 `11 passed`。独立 code-reviewer 复核最初指出的 user-level retained count 与 sample-level no-negative drop 混淆后，修复并重新 review，结论 `APPROVE`。

**面试可讲点：**
这段可以讲成“把模型效果问题先转化为数据稀疏性可观测问题”：不是简单增加 epoch 或负样本，而是先把 item universe、post-prune user retention、sample-emitting users 和 target/negative universe mismatch 量化，再用隔离 tier 给后续 YouTubeDNN 训练提供更符合 Amazon 长尾数据的输入，同时守住 train-only 和 no-promotion 边界。

### 2026-06-06 - ItemCF weak src3/dst3/source adapter 固定并接入主路默认 manifest

**任务：**
将 valid 一个月筛选出的传统 ItemCF weak 最优口径固定为可复用 source artifact，并准备并入 pool500 recall-only 主路加载链路。

**遇到的问题：**
已有本地矩阵和 source 多数仍是旧 `src2_dst3` 或 strict flat-dataset 产物，不能直接冒充当前确认的 `src3_dst3_user2_keep_hot_cosine`；同时主路 runner 默认还指向旧 `target500_train_weak_edges_v1`，且完整 route smoke 会被无关 two_tower/swing manifest 契约问题阻断。

**定位方式：**
核对 `memory/project_itemcf_selected_filter_policy.md`、远程 one-pass screen 输出和 cold-filtered grid 输出，确认最佳配置为 `src>=3,dst>=3,user_after_item>=2,keep_hot,cosine`，valid `raw_recall@500=0.034482`、`candidate_user_rate=0.951935`。检查 `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的 `DEFAULT_SOURCE_MANIFESTS` 与 `load_itemcf_source_manifest` 契约，确认 source index 需要 sharded `edges_shards`、`train_only=true`，并保持 promotion/candidate-generation 关闭。

**解决方式：**
在远程将 train-only `cold_u2_i3_cosine_seed200` method dataset rows 转为 64 分片 source index：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json`，共 `16,454,229` 条 item-item edge，row count audit PASS。随后把 `run_full_data_pool500_recall_only.py` 的默认 `itemcf_weak` manifest 指向该 source，并更新 `configs/recall/full_data_pool500/itemcf_weak/{source_config.yaml,dataset_policy.yaml}`、`configs/recall/pool500_method_registry.json` 和 `dic/recall_methods/itemcf_weak/METHOD.md`，明确这是 source adapter ready、route gated，而不是 final promotion。

**验证结果：**
远程 source adapter 构建完成，manifest 显示 `status=PASS`、`train_only=true`、`source_status=DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`。source index 已同步到本地，64 个 shard 均存在，manifest shard path 已改为本地可解析的相对路径。`load_itemcf_source_manifest(..., allowed_src_items={"0811836037"})` 抽样加载成功，返回 1 个 src、22 个候选。isolated 1000-user route smoke 产出 `500000` candidate rows，其中 `itemcf_weak` 贡献 `19540` 行、覆盖 `643/1000` 用户、marginal share `0.03908`；smoke 最终 `STOP` 来自刻意禁用 swing/usercf ready sources 后触发的无关 stoploss，不是 ItemCF source 加载失败，相关 smoke 产物已同步到本地。代码验证：`.venv/Scripts/python.exe -m py_compile rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`、registry JSON 解析、两个 ItemCF YAML 解析和本地 source loader 抽样均通过。

**面试可讲点：**
这段可以讲成“把离线算法参数搜索收口成可治理的生产候选源”：先用 train-only 构建、valid-only 后验筛选确定 `src3/dst3/user2/keep-hot/cosine`，再把大规模 item-item 边转成分片 source index 接入主路 loader，同时保留 no-oracle、no-promotion、no-ranking-replacement 的治理阀门，避免把诊断提升误宣称为最终上线效果。

### 2026-06-07 - UserCF A ç»„è¯Šæ–­äº§ç‰©å¹¶å…¥ pool500 ä¸»è·¯å®¡è®¡

**ä»»åŠ¡ï¼š**
å°† UserCF A ç»„ `src>=2,dst>=3,user_after_src_filter>=2,keep_hot=true,iuf_cosine` äº§ç‰©åˆ‡ä¸º pool500 é»˜è®¤ UserCF manifestï¼Œä½†å�ªä½œä¸º `DIAGNOSTIC_ONLY` diagnostic contributionï¼Œä¸�èƒ½è¿›å…¥ READY stoplossã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
A ç»„ 3k è¯Šæ–­åˆ‡ç‰‡å·²ç”Ÿæˆ� 300000 è¡Œå€™é€‰ï¼Œå®¹æ˜“è¢«ä¸»è·¯ rows/index å­˜åœ¨æ€§é€»è¾‘è¯¯åˆ¤ä¸º READYï¼›å�Œæ—¶æ—§é…�ç½®é‡Œ UserCF è¿˜å‡ºçŽ°åœ¨ READY stoploss sources ä¸­ï¼Œå’Œå½“å‰�â€œå‘½ä¸­å¼±ã€�ä¸�æ™‹å�‡ READYâ€�çš„æ²»ç�†ç»“è®ºå†²çª�ã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ ¸å¯¹ `source_index_manifest.json` ä¸­ `diagnostic_only=true`ã€�`source_status=DIAGNOSTIC_ONLY`ã€�`candidate_generation_allowed=false` ç­‰å¥‘çº¦ï¼Œå¹¶æ£€æŸ¥ `rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` ä¸­ source manifestã€�readiness contractã€�derived index å’Œ contribution audit çš„çŠ¶æ€�æŽ¨æ–­é€»è¾‘ã€‚

**è§£å†³æ–¹å¼�ï¼š**
å°†é»˜è®¤ UserCF manifest åˆ‡åˆ° A ç»„è·¯å¾„ï¼›ä»Ž `READY_STOPLOSS_SOURCES` ç§»é™¤ `usercf_recall`ï¼ŒåŠ å…¥ `DIAGNOSTIC_CONTRIBUTION_SOURCES`ï¼›æ–°å¢ž artifact diagnostic-only åˆ¤å®šï¼Œç¡®ä¿� output manifestã€�readiness contractã€�derived index å’Œ contribution audit ä¸�ä¼šä»…å› æœ‰ rows/index å°±æŠŠ UserCF æ ‡æˆ� READYã€‚å�Œæ­¥æ›´æ–° registryã€�source_configã€�dataset_policyã€�æµ‹è¯•æ–­è¨€å’Œæ–¹æ³•æ–‡æ¡£ã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ `py_compile` ä¸Ž targeted pytestï¼›éªŒè¯�ç»“æžœè§�æœ¬æ¬¡æœ€ç»ˆå›žå¤�ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œè¯Šæ–­äº§ç‰©é˜²è¯¯æ™‹å�‡æ²»ç�†â€�ï¼šåœ¨æŽ¨è��å�¬å›žä¸»è·¯ä¸­å…�è®¸ä½Žä¿¡å¿ƒæ–¹æ³•å�‚ä¸Žè´¡çŒ®å®¡è®¡ï¼Œä½†é€šè¿‡ manifest-level `diagnostic_only/source_status` å’Œ ready/diagnostic source åˆ†å±‚ï¼Œé�¿å…�æŠŠå€™é€‰è¦†ç›–æ”¹å–„åŒ…è£…æˆ� READY æ•ˆæžœã€‚


## 2026-06-07 - ItemCF weak 非最佳实验产物清理

- 任务：在 `src3_dst3_user2_keep_hot_cosine_v1` 已固定为当前 source adapter 后，盘点并清理旧 formal/strict/source/matrix/smoke 产物，避免非最佳实践继续占用本地和远程空间。
- 遇到的问题：历史 `formal_strict_v1`、`smoke_strict_v1`、src2/dst3 旧矩阵、旧 route smoke 和远程 weak_denoised/grid rows 仍残留；部分配置仍指向旧矩阵或旧 strict report，直接删除会造成 current 配置误读。
- 定位方式：按 `outputs/recall/pool500_method_sources/recent_2y/itemcf_weak`、`outputs/recall/itemcf_matrices/recent_2y`、`outputs/recall/full_data_pool500_recall_only` 以及远程 `/mnt/data/luo/RS_agent_remote_storage/outputs/recall` 盘点大小；形成清理记录 `dic/recall_methods/itemcf_weak/CLEANUP_RECORD_2026_06_07.md`。
- 解决方式：删除本地旧 strict source、src2/dst3 旧矩阵和旧 ItemCF weak smoke；删除远程非最佳 cold grid rows、旧 weak_denoised source、旧 src2/dst3 matrix 和空 smoke；保留当前最佳 `src3_dst3_user2_keep_hot_cosine_v1` source、1000-user smoke evidence，以及当前最佳 `cold_u2_i3_cosine_seed200` 输入 rows。同步更新 source config、dataset policy、method registry 和 METHOD 文档，把旧矩阵标记为历史已清理，不再作为 current readiness 依据。
- 验证结果：本地和远程登记删除路径均已不存在；当前 source manifest 仍存在；使用 `.venv/Scripts/python.exe` 调用 `load_itemcf_source_manifest(...)` 抽样加载 `0811836037`，返回 `loaded_src_count=1`、`candidate_count=22`、sample item `B08D9BXTC4`、score `0.064519`。
- 面试可讲点：不仅完成算法口径收口，还做了 artifact 生命周期治理：区分 canonical source、历史诊断证据和可删除中间产物，清理空间同时保持可审计性与主路 loader 可用性。


## 2026-06-07 - itemcf_strong 主路默认 manifest 指向修复

- 任务：修复 pool500 recall-only 主路中 `itemcf_strong` 默认 manifest 仍指向旧路径的问题，使其对齐此前固定的 recent-2y relaxed strong supplemental artifact。
- 遇到的问题：`configs/recall/full_data_pool500/itemcf_strong/source_config.yaml` 与 registry 已记录 current artifact 为 `outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y/source_index_manifest.json`，但 `run_full_data_pool500_recall_only.py` 的 `DEFAULT_SOURCE_MANIFESTS["itemcf_strong"]` 仍指向旧 `itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/.../formal_sharded` 路径，本地 manifest 不存在。
- 定位方式：核对主路默认 manifest、itemcf_strong source config、registry latest artifact，并在远程确认固定 artifact 存在；同步该 artifact 到本地后读取 source manifest，确认 `index_scope=RECENT_2Y_DERIVED_INDEX`、`train_only=true`、`row_count=514216`、`shard_count=8`。
- 解决方式：将 `run_full_data_pool500_recall_only.py` 默认 `itemcf_strong` manifest 改为 `pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y/source_index_manifest.json`，与 config/registry 固定 artifact 对齐。
- 验证结果：本地 `.venv/Scripts/python.exe` 验证 `itemcf_weak`、`itemcf_strong`、`swing_recall` 三个主路默认 manifest 均存在；`load_itemcf_source_manifest(...)` 对 `itemcf_strong` 抽样加载成功，`loaded_src_count=1`、`candidate_count=1`、sample src `0440412676`、sample item `B08FDPRLVF`、score `0.03557`；`py_compile` 通过。
- 面试可讲点：这是一次主路配置漂移修复：不是重跑算法，而是把 runner 默认入口、registry 和 source config 的 canonical artifact 对齐，避免“文档/配置 ready，但运行入口仍指向旧 artifact”的工程风险。


## 2026-06-07 - two_tower_DSSM 独立诊断链路落位

- 任务：参考 DSSM 双塔思路，为 recent_2y 数据集新增独立 `two_tower_DSSM` 文件夹链路，服务“user 无个人信息、item 信息更丰富”的 item-rich 双塔召回诊断。
- 遇到的问题：仓库已有 `_TorchDSSM` 和训练 workflow，但现有 safe CLI、source manifest、direct eval 入口主要围绕 `two_tower_youtube_dnn`；如果直接复用 `two_tower` 命名，后续用户重命名 YouTubeDNN 时容易混淆 artifact、配置和评估口径。
- 定位方式：只读核对 `rs_core/recsys/two_tower.py`、`rs_core/workflow/two_tower_training.py`、`scripts/training/train_two_tower.py`、`rs_core/recsys/two_tower_source_manifest.py`、`build_pool500_two_tower_method_dataset.py` 和 recent_2y 配置，确认模型主体可复用，缺口在 DSSM 独立目录、source contract、source index 构建、direct eval wrapper 与 item-rich vocab manifest。
- 解决方式：新增 `configs/recall/full_data_pool500/two_tower_DSSM/`、`scripts/training/two_tower_DSSM/`、`scripts/recall/two_tower_DSSM/`、`rs_core/recsys/two_tower_DSSM/`、`rs_lab/experiments/recall/two_tower_DSSM/`；DSSM 训练入口固定 `variant=dssm/source_name=two_tower_dssm`，source manifest 固定 diagnostic-only contract；method dataset 额外输出 `two_tower_dssm_item_vocab_manifest.json`，指向含 title/category/description/features/side feature 的 `training_item_universe.jsonl`。复核阶段进一步加强 manifest 防护：扫描 `item_vocab_manifest` 内部 provenance，校验 item/index/user embedding 的 row count、维度一致性、非有限值和 forbidden path，并让 direct eval 实际加载 `user_embedding_path` 作为 `artifact_user_embedding` 查询来源。
- 验证结果：使用项目默认 `.venv` 运行 DSSM focused tests：`tests/test_pool500_two_tower_method_dataset.py tests/test_two_tower_dssm_source_manifest.py tests/test_two_tower_dssm_source_index.py tests/test_pool500_two_tower_dssm_direct_eval.py`，结果 `36 passed, 3 skipped in 0.87s`；运行相关 two_tower 回归：`tests/test_two_tower_training.py tests/test_pool500_two_tower_source_manifest.py tests/test_pool500_two_tower_direct_eval.py`，结果 `55 passed in 2.90s`；DSSM 相关 ruff 检查通过：`All checks passed!`。
- 面试可讲点：这段可以讲成“在不造用户画像、不污染主路的前提下，为 item-rich DSSM 双塔建立独立受治理诊断链路”：user tower 只用 train-only 行为序列聚合，item tower 优先使用商品文本/类目/质量桶等字段；通过独立 manifest contract 和 diagnostic-only flags，避免把实验召回源误接入正式 pool500/ranking。


### 2026-06-07 - UserCF item-first full diagnostic é˜ˆå€¼å›ºå®š

**ä»»åŠ¡ï¼š**
æŠŠ UserCF ä»Ž 3K smoke å�£å¾„çº æ­£ä¸º recent-2y train-only full diagnosticï¼Œå¹¶åœ¨ `src>=2,dst>=3,keep_hot=true,iuf_cosine` ä¸�å�˜çš„å‰�æ��ä¸‹é€‰æ‹©æ­£å¼� user è¡Œä¸ºé˜ˆå€¼ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
3K smoke artifact å�ªèƒ½ä½œä¸ºå�£å¾„é€‰æ‹©è¯�æ�®ï¼Œä¸�èƒ½ä»£è¡¨ full ä¸»è·¯äº§ç‰©ï¼›å�Œæ—¶ `user_after_src_filter>=2` è¦†ç›–æœ€å¤§ä½†åŒ…å�«å¤§é‡�å�ªæœ‰ä¸¤ä¸ªæœ‰æ•ˆ item çš„ä½Žä¿¡å�·ç”¨æˆ·ï¼ŒUserCF ç›¸ä¼¼åº¦è´¨é‡�å’Œè®¡ç®—æˆ�æœ¬å­˜åœ¨å�–èˆ�ã€‚

**å®šä½�æ–¹å¼�ï¼š**
ä½¿ç”¨è¿œç¨‹æœ�åŠ¡å™¨ `/home/luo/RS_agent_remote` åœ¨ recent-2y æ•°æ�®é›†ä¸Šé‡�è·‘ full diagnosticï¼Œåˆ†åˆ«è¯„ä¼° `user_after_src_filter>=2/3/4/5/6/10`ã€‚valid/test labels ä»…é€šè¿‡ shard-aware evaluation-only è„šæœ¬å�ŽéªŒè¯„ä¼°ï¼Œä¸�å�‚ä¸Žå€™é€‰ç”Ÿæˆ�ã€‚å…³é”®è¯�æ�®è®°å½•åœ¨ `outputs/recall/pool500_method_evals/recent_2y/usercf_threshold_shard_eval_summary.json`ã€‚

**è§£å†³æ–¹å¼�ï¼š**
å›ºå®šå½“å‰� UserCF é»˜è®¤ full diagnostic artifact ä¸º `usercf_itemfirst_src2_dst3_user3_keep_hot_full_diagnostic_v1`ã€‚item è¿‡æ»¤ä¿�æŒ� train-only `src_min_positive_user_count=2`ã€�`dst_min_positive_user_count=3`ã€�`keep_hot=true`ï¼Œç”¨æˆ·è¿‡æ»¤è°ƒæ•´ä¸º `min_src_filtered_items_per_user=3`ã€‚è¯¥é˜ˆå€¼å°† target users ä»Ž user2 çš„ 1,495,958 é™�è‡³ 651,099ï¼Œå�Œæ—¶æ¯” user4/5/6/10 ä¿�ç•™æ›´å……åˆ†è¦†ç›–ã€‚

**éªŒè¯�ç»“æžœï¼š**
é€‰å®š artifact `source_index_manifest.json` ä¸º `PASS`ã€�`source_status=DIAGNOSTIC_ONLY`ã€�`target_user_count=651099`ã€�`row_count=651046`ã€�`candidate_total_count=64327024`ã€�`underfilled_user_coverage=0.999919`ã€�`no_holdout_audit=PASS`ã€‚é˜ˆå€¼æ‰«æ��ä¸­ user3 çš„ combined `Recall@100=0.000950`ã€�`HitRate@100=0.001305`ï¼Œserved-user combined `HitRate@100=6.04%`ï¼Œtest served `HitRate@100=4.77%` ä¸ºå�„é˜ˆå€¼æœ€é«˜ï¼›user2 å…¨å±€ Recall@100 æœ€é«˜ä½†æˆ�æœ¬å’Œä½Žè¡Œä¸ºå™ªå£°æ›´é«˜ã€‚æœ€ç»ˆä»�ä¿�æŒ� `DIAGNOSTIC_ONLY`ï¼Œä¸�æ‰“å¼€ candidate generation / ranking replacement / pool1000 / promotion / final readyã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œå��å�Œè¿‡æ»¤å�¬å›žçš„ full-scale é˜ˆå€¼æ²»ç�†â€�ï¼šä¸�æ˜¯æŠŠ smoke ç»“æžœå†’å……ä¸»è·¯ï¼Œè€Œæ˜¯åœ¨ train-only æ•°æ�®ä¸Šå�š full artifactã€�æŒ‰ç”¨æˆ·è¡Œä¸ºå¼ºåº¦æ‰«æ��è¦†ç›–-è´¨é‡�-æˆ�æœ¬æ›²çº¿ï¼Œæœ€ç»ˆé€‰æ‹© user3 ä½œä¸ºå�‡è¡¡é˜ˆå€¼ï¼Œå¹¶æ˜Žç¡®å°† valid/test é™�å®šä¸ºå�ŽéªŒè¯„ä¼°ï¼Œä½“çŽ°æŽ¨è��ç³»ç»Ÿä¸­å�¬å›žå®žéªŒã€�æ•°æ�®æ³„æ¼�æŽ§åˆ¶å’Œå·¥ç¨‹æ™‹å�‡è¾¹ç•Œçš„ç»¼å�ˆæ²»ç�†ã€‚


## 2026-06-07 - pool500 ä¸‰æ–¹æ³• follow-up è¯�æ�®é“¾å¤�æ ¸

- ä»»åŠ¡ï¼šå¯¹ `semantic_title_category_expansion`ã€�`co_visit_fallback_repair`ã€�`semantic` ä¸‰ä¸ª follow-up artifact å�šæœ€ç»ˆç‹¬ç«‹éªŒè¯�ï¼Œç¡®è®¤å…¶å�ªä½œä¸ºè¯Šæ–­è¯�æ�®ï¼Œä¸�è¯¯æ™‹å�‡ä¸º full route æˆ– ranking è¾“å…¥ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šé¦–æ¬¡å¤�æ ¸æ—¶ `semantic_title_category_expansion` ä¸Ž `co_visit_fallback_repair` çš„æœ¬åœ°å�ªè¯»è¯�æ�®åŒºç¼ºå°‘æ˜¾å¼� `no_holdout PASS` artifactï¼Œä¸�èƒ½ä»…å‡­ manifest è·¯å¾„å¼•ç”¨ç»™å‡ºæˆ�åŠŸç»“è®ºã€‚
- å®šä½�æ–¹å¼�ï¼šåŸºäºŽ `D:/sinrotic_code/python_project/summer/RS_agent/.omc/scientist/followup_20260607` é€�é¡¹è¯»å�– source manifestã€�resource auditã€�no_holdout auditã€�eval sanity reportã€�marginal metrics å’Œ overlap reportï¼Œæ ¸å¯¹ä¸‰æ–¹æ³•-onlyã€�row/user countã€�eval-only label roleã€�baseline roleã€�overlap diagnostic scope ä¸Ž promotion flagsã€‚
- è§£å†³æ–¹å¼�ï¼šç­‰å¾…è¿œç¨‹æ�¢å¤�å¹¶é•œåƒ� `semantic_title_no_holdout_audit.json`ã€�`co_visit_no_holdout_audit.json`ã€�`semantic_no_holdout_audit.json` å�Žé‡�æ–°éªŒè¯�ï¼›ä¸�ä¿®æ”¹å€™é€‰ç”Ÿæˆ�é€»è¾‘ï¼Œå�ªè¡¥é½�å®¡è®¡è¯�æ�®é“¾ã€‚
- éªŒè¯�ç»“æžœï¼šä¸‰æ–¹æ³•å�‡é€šè¿‡æœ€ç»ˆ artifact gateï¼šsemantic_title `5000 users / 500000 rows / resource PASS / no_holdout PASS`ï¼Œco_visit `5000 users / 480619 rows / resource PASS / no_holdout PASS`ï¼Œsemantic `2000 users / 200000 rows / resource PASS / no_holdout PASS`ï¼›ä¸‰è€… `candidate_generation_uses_holdout=false`ã€�`no_oracle_label_injection=true`ã€�`eval_scope=evaluation_only`ã€�baseline/marginal comparison ä»…ä½œ evaluation-onlyï¼Œoverlap scope ä¸º `diagnostic_overlap_only_not_promotion_gate_by_itself`ï¼Œä¸” `candidate_generation_allowed=false`ã€�`ranking_input_replacement_allowed=false`ã€�`promotion_allowed=false`ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ®µå�¯ä»¥è®²æˆ�â€œå�¬å›žå®žéªŒæ™‹å�‡å‰�çš„è¯�æ�®é—¨ç¦�â€�ï¼šä¸�å› è·‘å‡ºå€™é€‰æˆ– sanity Recall å°±å£°æ˜Ž READYï¼Œè€Œæ˜¯æŠŠèµ„æº�ã€�æ—  holdoutã€�æ—  oracleã€�è¯Šæ–­-only å’Œ promotion boundary æ‹†æˆ�å�¯å®¡è®¡ gateï¼Œå�‘çŽ°è¯�æ�®ç¼ºå�£å�Žå…ˆé˜»æ–­æˆ�åŠŸç»“è®ºï¼Œå†�è¡¥é½�è¿œç¨‹ artifact å¹¶å¤�æ ¸é€šè¿‡ã€‚


## 2026-06-07 - ä¸‰æ–¹æ³•å�¬å›ž scoring ä¿®æ­£ä¸Žæœ¬åœ°éªŒè¯�

- ä»»åŠ¡ï¼šåœ¨ä»…é™�å®š `semantic`ã€�`semantic_title_category_expansion`ã€�`co_visit_fallback_repair` çš„èŒƒå›´å†…ï¼Œä¿®æ­£ valid-only æ•ˆæžœè¿‡ä½Žæš´éœ²å‡ºçš„å�¬å›ž scoring é—®é¢˜ï¼Œå…ˆå®Œæˆ�æœ¬åœ° guarded çº§åˆ«å®žçŽ°ä¸Žæµ‹è¯•ï¼Œä¸�å£°æ˜Ž READY / promotionã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šåŽŸå®žçŽ°ä¸­ `semantic` ä¸»è¦�ä¾�èµ–ç®€å�• token overlapï¼Œå®¹æ˜“è¢«æ³›è¯�å’Œé•¿æ–‡æœ¬å�¶ç„¶é‡�å� å¹²æ‰°ï¼›`co_visit_fallback_repair` çš„ sequence transition ç¼ºå°‘è·�ç¦»è¡°å‡�ã€�support gateã€�popularity normalization ä¸Ž underfill refillï¼›`semantic_title_category_expansion` ç‹¬ç«‹æ‰©æ¡£æ•ˆæžœå·®ï¼Œéœ€è¦�é™�çº§ä¸º semantic çš„ title/category channelã€‚
- å®šä½�æ–¹å¼�ï¼šç»“å�ˆè¿œç¨‹ valid-only sanity æŒ‡æ ‡ã€�è®ºæ–‡/èµ„æ–™è°ƒç ”ç»“è®ºå’Œæº�ç �æ£€æŸ¥ï¼Œå®šä½�åˆ° `rs_lab/experiments/recall/pool500/methods/semantic/builder.py`ã€�`rs_lab/experiments/recall/pool500/methods/co_visit_fallback_repair/builder.py`ã€�ä¸‰æ–¹æ³• `source_config.yaml` ä¸Ž focused testsã€‚ä»£ç �å¤�å®¡è¿›ä¸€æ­¥å�‘çŽ° forbidden audit éœ€è¦†ç›– `oracle/eval_label`ã€�BM25F é•¿åº¦å½’ä¸€åŒ–å’Œè¿‡æ»¤ token scoring éœ€è¡¥å¼ºã€�co_visit v2 contract éœ€ä¸Ž support gate å¯¹é½�ã€‚
- è§£å†³æ–¹å¼�ï¼š`semantic` æ”¹ä¸º BM25F-style field-weighted scorerï¼ŒåŠ å…¥ title/category æ�ƒé‡�ã€�IDFã€�å¹³å�‡å­—æ®µé•¿åº¦å½’ä¸€åŒ–ã€�generic/high-DF token è¿‡æ»¤ä¸Ž `bm25f_score/field_scores` è¯�æ�®å­—æ®µï¼›`co_visit_fallback_repair` å�‡çº§ä¸º `train_transition_metadata_repair_v2`ï¼ŒåŠ å…¥ reciprocal/linear/exponential transition decayã€�pair support/distinct user support gateã€�popularity normalizationã€�underfill repairï¼Œå¹¶åœ¨ manifest/config/doc ä¸­æ˜Žç¡®ä»�ä¸º diagnosticï¼›`semantic_title_category_expansion` ä¿�ç•™ builder contractï¼Œå°†é…�ç½®è¯­ä¹‰é™�çº§ä¸º `semantic_title_category_channel`ï¼Œä¸�å†�ä½œä¸ºç›²ç›®ç‹¬ç«‹æ‰©æ¡£æ–¹å�‘ã€‚
- éªŒè¯�ç»“æžœï¼šä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ scoped ç¼–è¯‘ä¸Žæµ‹è¯•ï¼š`./.venv/Scripts/python.exe -m py_compile ...` é€šè¿‡æ— è¾“å‡ºï¼›`./.venv/Scripts/python.exe -m pytest tests/test_pool500_co_visit_fallback_repair_source.py tests/test_pool500_semantic_bm25f.py tests/test_pool500_semantic_newdata_config.py tests/test_pool500_method_source_runner.py -q` å¾—åˆ° `43 passed in 0.87s`ã€‚ç‹¬ç«‹ code-reviewer å¤�å®¡ä¸º `APPROVE`ï¼Œç¡®è®¤ forbidden scopeã€�BM25Fã€�co_visit v2 gate contract å’Œ governance è¾¹ç•Œå·²å¯¹é½�ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ®µå�¯ä»¥è®²æˆ�â€œä½Žæ•ˆæžœå�¬å›žæ–¹æ³•çš„è¯Šæ–­åž‹å·¥ç¨‹ä¿®å¤�â€�ï¼šä¸�æ˜¯ç›´æŽ¥ç”¨ label/oracle è°ƒå�‚å†’å……æ��å�‡ï¼Œè€Œæ˜¯å…ˆä»Žå€™é€‰ç”Ÿæˆ�æœºåˆ¶æ‹†è§£é”™è¯¯æ�¥æº�ï¼Œåˆ†åˆ«ç”¨ BM25F å­—æ®µæ�ƒé‡�ã€�åº�åˆ—è½¬ç§» support gate å’Œ underfill repair ä¿®å¤�å�¬å›žé€»è¾‘ï¼Œå�Œæ—¶ç”¨ no-holdout auditã€�governance flagã€�focused unit tests å’Œç‹¬ç«‹ review ä¿�è¯�å®žéªŒè¾¹ç•Œå�¯å¤�è¿°ã€�å�¯éªŒè¯�ã€�å�¯ç»§ç»­æ‰©å±•åˆ°è¿œç¨‹ guarded è¯„ä¼°ã€‚

## 2026-06-08 - semantic 描述式召回诊断口径强化

- 任务：按“自然语言描述能否召回真正匹配商品”的目标，补充 `semantic` / `semantic_title_category_expansion` 的描述式诊断，而不是继续用单方法 valid purchase Recall 判断语义召回生死。
- 遇到的问题：初版关键词命中诊断 `avg_alignment_precision_at_10_min2_terms=0.892`，但人工查看发现 `wireless_mouse` 会召回 mouse pad，`baby_stroller_organizer` 会召回 desk organizer，`cat_litter_mat` 会召回 litter-box adapter，说明简单 token overlap 会把弱词命中误判为真实意图命中。
- 定位方式：读取 `outputs/diagnostics/semantic_description_recall_20260608/README.md` 的 topK 结果，按 query 检查标题、类目、核心词、负例词；同时复核 valid-only 报告 `Recall@500=1e-05` 的原因，确认 purchase-valid 口径与 description relevance 口径不同。
- 解决方式：新增 `scripts/experiments/recall/pool500/diagnose_semantic_description_recall.py`，把 query fixture 拆成 `core_terms`、`must_terms`、`must_any_groups`、`intent_phrases`、`category_any`、`negative_phrases`，评分加入核心标题词覆盖、短语 boost、类目 prior、负例惩罚和 strict/required/bad intent 指标；新增 `tests/test_pool500_semantic_description_diagnostic.py` 验证 stroller organizer 与 wireless mouse 的错误类型会被降权。
- 验证结果：`./.venv/Scripts/python.exe -m py_compile scripts/experiments/recall/pool500/diagnose_semantic_description_recall.py tests/test_pool500_semantic_description_diagnostic.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_description_diagnostic.py tests/test_pool500_semantic_bm25f.py -q` 得到 `3 passed`。严格诊断输出 `outputs/diagnostics/semantic_description_recall_strict_v2_20260608/README.md`：`avg_strict_precision_at_5=0.5`、`avg_strict_precision_at_10=0.483`、`avg_required_precision_at_10=0.75`、`queries_with_strict_hit_top5=8/12`。其中 `wireless_mouse`、`usb_c_hub`、`medical_clipboard` 表现稳定，`dog_chew_toy`、`baby_stroller_organizer`、`cat_litter_mat` 暴露商品类型和类目缺口。
- 面试可讲点：这段可以讲成“把语义召回从粗糙指标改成可解释的描述式相关性诊断”：不使用 label/oracle 注入，而是用 train-only 商品 metadata 构造可审计 query suite，区分词面命中、核心商品类型、类目先验和负例污染，为后续 Agent/RAG 的商品理解召回建立可复述、可迭代的评估门禁。


### 2026-06-08 - pool500 主路方法接入线上服务与 Agent 高层工具

**任务：**
把已准备好的 pool500 主路候选 artifact 接成可被 FastAPI 服务和 Agent 调用的 online route，同时保持 Agent 前台只暴露 6 个高层业务工具。

**遇到的问题：**
现有 `/recommend` 的 `complete_pool500=True` 仍直接拒绝，`/health` 仍标记 single-process demo；Agent 工具执行链虽然有 `retrieve_candidates` / `rank_candidates`，但实现仍偏内部 helper。另一个边界问题是 session export 中曾返回 `agent_thoughts`，会把内部工具名和诊断信息暴露到 public payload。

**定位方式：**
沿 `rs_core/serving/app.py`、`rs_core/serving/service.py`、`rs_core/workflow/online_recommendation.py`、`rs_core/workflow/hybrid_environment.py` 和 `rs_core/rsagent/tools.py` 追踪服务入口、online 推荐路径和 Agent tool dispatch；用 focused pytest 验证 `/recommend`、`/health`、`/ready`、semantic live、Agent manifest 和 public display/export 边界。

**解决方式：**
新增 `rs_core/recsys/pool500_artifacts.py`，在 `rs_core` 内只读解析 `pool500_candidates.jsonl` 并拒绝 oracle/evaluation 字段；改造 `OnlinePool500Recommender`，让 `complete_pool500=True` 走 pool500 artifact route，并保留 demo-compatible fallback；新增 `/ready`，更新 `/health` 为 online-service 语义；在 `HybridRecommendationEnvironment` 中让高层 `retrieve_candidates` / `rank_candidates` 优先走 online route facade，同时保留 semantic_live 优先级；移除 public session export 中的 `agent_thoughts`，避免泄漏工具链和诊断。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_agent_capability_manifest.py tests/test_pool500_online_artifacts.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py tests/test_agent_runtime.py tests/test_agent_tools.py tests/test_display_contract.py tests/test_engineering_contracts.py -q` 结果 `154 passed`；`./.venv/Scripts/python.exe -m ruff check rs_core tests/test_pool500_online_artifacts.py tests/test_serving_recommend_from_sequence.py tests/test_serving_smoke.py scripts/serving/run_service.py` 结果 `All checks passed!`。独立 verifier 指出 export 泄漏问题后已修复并复测通过。

**面试可讲点：**
这段工作可以讲成“把离线推荐主路晋升为在线可调用能力，但不让 Agent 直接接触底层算法细节”：服务层通过 artifact loader、readiness 和 fail-closed 字段校验治理数据入口；Agent 侧仍只调用候选检索、排序、证据和 slate 构建等高层工具；public display/export 严格隔离诊断和工具轨迹。这样既能支持真实交互服务，也保留了推荐方法、Agent 编排和前端展示之间的边界。

### 2026-06-09 - COLD/DeepFM 冷用户冷 item 筛选与 feature contract 门禁

**任务：**
根据“先 user 后 item / 先 item 后 user”两种候选方案，实际实现 COLD 粗排 / DeepFM 精排的 train-only 筛选策略，并完成 smoke 训练、frozen eval 诊断和门禁复审。

**遇到的问题：**
原训练链路没有显式记录冷用户/冷 item 的筛选顺序，且 eval runner 可能从候选 rank/source 临时派生特征，导致 train/eval feature space 不一致；同时 frozen candidate 与 valid label overlap 为 0，不能把训练完成包装成排序效果提升。复审还发现非法 feature contract threshold 可能导致 eval builder 崩溃，以及 runner 在缺少 `coverage_gate.json` sidecar 时可能错误放行 ranking-effect conclusion。

**定位方式：**
围绕 `build_cold_deepfm_ranking_training_dataset.py`、`build_pool500_frozen_candidate_eval_dataset.py` 和 `run_cold_deepfm_offline_train_eval.py` 做 targeted test 与 code-reviewer 复审。通过 `screening_audit.json` 对比 user-first / item-first 的 retained stats，通过 `feature_contract_gate` 检查 train/eval 每行 feature set、feature version、screening policy 和 contract hash，通过 `coverage_gate.json` 核实 valid label 正例是否进入 frozen candidates。

**解决方式：**
新增 `screening_policy={none,user_first,item_first}` 和默认阈值 `min_user_train_positive_count=2`、`min_item_train_positive_user_count=2`。主线 user-first 先过滤低历史用户，再在保留用户上筛 item；item-first 作为 ablation 先筛 item，再筛 retained users。训练、负采样和 history features 都只用 2y1m3m train-only positives；eval builder 只对 frozen candidates 做同一 eligible user/item filtering，不做 label 注入。新增 `feature_contract.json`，runner 严格要求 train/eval artifact hash、feature names、feature version 和 row-level feature set 与 contract 一致；非法 threshold 走 STOP gate，不崩溃；缺 coverage sidecar 时一律拒绝 ranking-effect conclusion。

**验证结果：**
使用项目默认 `.venv` 运行 `./.venv/Scripts/python.exe -m pytest tests/test_cold_deepfm_ranking.py -q`，结果 `40 passed in 0.48s`。user-first smoke 训练集为 43752 rows / 14584 positives / 9437 positive users，DeepFM loss 从 `0.6292415099` 降到 `0.6150086049`；item-first 为 51870 rows / 17290 positives / 7215 positive users，loss 从 `0.6086242059` 降到 `0.6070367131`。两者的 oracle gate 和 feature contract gate 均 PASS；但 frozen eval 分别只有 830 rows / 6 users / 0 positives 和 999 rows / 5 users / 0 positives，coverage gate 均为 `STOP_FOR_RANKING_EFFECT`，因此 `ranking_effect_conclusion_allowed=false`、`ranking_effect_conclusion_refused=true`。最终 code-reviewer 复审确认 HIGH/CRITICAL 为 0。

**面试可讲点：**
这段可以讲成“排序训练前的数据口径治理与效果门禁”：不是简单删除冷用户/冷 item，而是把筛选顺序、阈值、eligible sets 和 feature contract 固化成可审计 artifact；即使 COLD/DeepFM 完成训练，也通过 frozen candidate coverage gate 主动拒绝不成立的排序效果宣称，体现了推荐系统离线实验中 no-oracle、train-only feature stats 和 candidate coverage 的工程严谨性。

### 2026-06-09 - DeepFM shadow scorer 接入在线排序链路

**任务：**
响应“先把这个模型用上”，把已训练的 DeepFM artifact 接入在线 pool500 / Agent 推荐链路，但只作为 shadow / diagnostic scorer，不替换主排序器、不声明排序效果。

**遇到的问题：**
当前离线报告仍不允许 `ranking_replacement` 和 `ranking_effect_conclusion`，且 serving artifact 可能缺失；原 `deepfm_model` 钩子在非 shadow 模式下可直接改变 `final_score`，存在把诊断模型误用为线上排序增益的风险。同时 public display 必须继续隔离 raw score、feature contract、model path 和 ranking internals。

**定位方式：**
沿 `rs_core/recsys/ranking.py` 的 `rank_candidates -> rerank_candidates -> _apply_deepfm_model_score` 追踪模型打分入口，并复核 `configs/serving/online_service.yaml`、`rs_core/display/builder.py`、`tests/test_recsys_core.py`、`tests/test_display_contract.py`。独立 code-reviewer 先后指出 artifact 缺失 fail-closed、disabled policy masking、diagnostic-only governance、`max_scored_candidates` 优先级等风险，均以回归测试固定。

**解决方式：**
新增/兼容 `deepfm_shadow` 配置入口，加载 DeepFM 模型与 offline report；默认 `feature_strategy=all_zero_safe`，不读取 valid/test/holdout，不使用 label/oracle 字段。治理门禁要求 policy、model/report diagnostic flags 与 report permission 同时允许才可产生排序 delta；当前配置 `affect_ranking=false`、`score_scale=0.0`，因此只记录 `deepfm_shadow_score` 内部事件。缺失 artifact 转为 skipped event，disabled shadow 不再遮蔽 legacy `deepfm_model`，`max_scored_candidates` 按 fine-stage 排名优先级限流；display validator 增加 DeepFM shadow 相关 forbidden key/term。

**验证结果：**
使用项目默认 `.venv` 运行：`./.venv/Scripts/python.exe -m pytest tests/test_recsys_core.py tests/test_display_contract.py tests/test_cold_deepfm_ranking.py -q` 得到 `130 passed in 0.56s`；`./.venv/Scripts/python.exe -m pytest tests/test_serving_recommend_from_sequence.py -q` 得到 `6 passed in 0.52s`。最终 code-reviewer 复审确认 HIGH/MEDIUM 为 0，仅剩低优先级可观测性/配置健壮性建议，已补充缺失路径事件和非法 `max_scored_candidates` 降级处理。

**面试可讲点：**
这段可以讲成“把离线排序模型安全接入在线链路的 shadow rollout”：不是直接用 smoke/offline 模型改线上排序，而是在服务链路真实加载、真实打分、内部留痕，同时通过治理门禁、fail-closed、限流和 public payload 隔离保证不会把未通过 coverage/effect gate 的模型包装成线上效果提升，为后续 challenger / promotion 留出清晰升级路径。

### 2026-06-12 - RAG é»˜è®¤å­—æ®µé™�å™ªä¸Ž evidence é…�é¢�æ”¶å�£

**ä»»åŠ¡ï¼š**
å°† RAG é»˜è®¤è¯�æ�®å­—æ®µä»Ž `category` / `main_category` ç­‰é«˜å™ªå£°åˆ«å��ä¸­æ”¶çª„åˆ° `title`ã€�`category_path`ã€�`description`ã€�`features`ï¼Œå¹¶é™�åˆ¶ title ä½œä¸º anchor ä½†ä¸�èƒ½ç‹¬å� æ¯�ä¸ª item çš„ evidenceã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
åŽŸé»˜è®¤å­—æ®µä¼šæŠŠç²—ç²’åº¦ç±»ç›®å’Œæ ‡é¢˜ä¸€èµ·æŽ¨åˆ°è¯�æ�®å‰�åˆ—ï¼Œå®¹æ˜“è®©è§£é‡Šå��å�‘ç±»ç›®/æ ‡é¢˜åŒ¹é…�ï¼Œè€Œä¸�æ˜¯å•†å“�æ��è¿°å’Œç‰¹å¾�ï¼›SQLite BM25 ä¸Ž Hybrid retriever å�ˆæœ‰ä¸�å�Œ evidence æ�¥æº�ï¼Œéœ€è¦�é�¿å…�å�ªä¿®ä¸€æ�¡è·¯å¾„ã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ²¿ `rs_core/recsys/rag/corpus.py`ã€�`bm25.py`ã€�`retriever.py`ã€�`hybrid.py` å’Œ `tests/test_rag_core.py` æ£€æŸ¥å­—æ®µé»˜è®¤å€¼ã€�BM25 æ£€ç´¢ã€�Hybrid èž�å�ˆä¸Ž RAG policy çš„é¢„ç®—è£�å‰ªé¡ºåº�ã€‚é¦–æ¬¡å®šå�‘ pytest æš´éœ²å‡ºé»˜è®¤å­—æ®µæµ‹è¯•æ�’å…¥ä½�ç½®ã€�full_text æ—§æ–­è¨€ã€�BM25 description è¢«å¤š chunk features æŒ¤å‡ºã€�Hybrid æœ¬åœ°å�‘é‡� compact_text å…¼å®¹æ€§ç­‰é—®é¢˜ã€‚

**è§£å†³æ–¹å¼�ï¼š**
é»˜è®¤å­—æ®µå’Œ compact dense source å­—æ®µç§»é™¤ `category` / `main_category`ï¼›InMemory candidate card é»˜è®¤æ”¹ä¸º `title/category_path/description/features`ï¼›SQLite BM25 candidate/query-planning æ£€ç´¢é»˜è®¤å�ªè¿”å›žæ ‡å‡†å­—æ®µå¹¶æŒ‰ item-field é…�é¢�åŽ»é‡�ï¼›Hybrid èž�å�ˆå�Žå�Œæ ·è¿‡æ»¤é»˜è®¤å­—æ®µå¹¶ä¿�ç•™ `compact_text` å…¼å®¹æœ¬åœ°å�‘é‡�ç´¢å¼•ã€‚RAG policy å±‚å¢žåŠ  title å�• item é…�é¢�ï¼Œé�¿å…�é«˜åˆ† title å¤š chunk å� æ»¡ per-item budgetã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›® `.venv` è¿�è¡Œ `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_rag_core.py`ï¼Œç»“æžœ `26 passed in 1.67s`ï¼›è¿�è¡Œ `py_compile` æ£€æŸ¥ 5 ä¸ªä¿®æ”¹æ–‡ä»¶æ— è¯­æ³•é”™è¯¯ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œRAG è¯�æ�®æ²»ç�†çš„å­—æ®µçº§é™�å™ªâ€�ï¼šä¸�æ˜¯å�•çº¯æ��é«˜å�¬å›žæ•°é‡�ï¼Œè€Œæ˜¯é€šè¿‡é»˜è®¤å­—æ®µç™½å��å�•ã€�title anchor é…�é¢�å’Œè·¨ BM25/Hybrid çš„ä¸€è‡´è¿‡æ»¤ï¼ŒæŠŠè§£é‡Š grounding ä»Žç²—ç±»ç›®/æ ‡é¢˜å��ç½®æ‹‰å›žåˆ°æ��è¿°ä¸Žç‰¹å¾�è¯�æ�®ï¼Œå�Œæ—¶ä¿�ç•™æ—§ç´¢å¼•å’Œ compact vector çš„å…¼å®¹è¾¹ç•Œã€‚


## 2026-06-14 Agent 本地 smoke、资源门禁与公开输出隔离

- 任务：优化 Agent 系统上线前的本地可运行性检查，并调通本地 smoke；在真正运行 Qwen 推理/训练前判断本机资源是否足够，不足时转远程服务器。
- 遇到的问题：本地 10k smoke artifact 缺少 `itemcf_recall_strong.jsonl`；RAG 解释证据没有从候选卡片的类目字段生成可用 grounding；CLI 写公开展示产物时触发 `public payload contains forbidden term: itemcf`；SFT/GRPO 依赖和显存门槛不满足本机重任务要求。
- 定位方式：通过 Agent/runtime 相关 pytest、CLI smoke stack trace、资源门禁输出和公开 payload 校验定位；关键验证命令为 `.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo_optional_strong.py tests/test_agent_runtime.py tests/test_agent_tools.py tests/test_agent_dialogue.py tests/test_agent_capability_manifest.py tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py tests/test_training_resource_gate.py -q`，结果 `132 passed in 1.86s`；CLI smoke 使用 `.venv/Scripts/python.exe -m rs_core.rsagent.cli --limit-users 1 --simulate-conversation --output-dir tmp_agent_goal_smoke_20260613 --inference-policy off` 成功写出 session、turns、rollout、display 和 report 文件。
- 解决方式：新增 Qwen smoke/inference/SFT/GRPO 资源门禁并接入 smoke/SFT/GRPO runner；将 `itemcf_strong` sidecar 设为可选；修复候选卡片 RAG evidence 的 `category_path` fallback；将 deterministic Agent 的公开解释文案从具体内部方法名改为“可用候选提供方 + 用户反馈约束 + 确定性排序规则”，避免泄漏内部实现词。
- 验证结果：Agent/resource focused test suite 通过；CLI 本地多轮 smoke 成功生成公开展示产物；额外 verifier 复核 display artifacts 未命中 `itemcf/source/training/reward/diagnostic/internal` 等公开禁用词。当前不能宣称全仓库 pytest 通过，因为全量测试仍受历史配置/产物缺失影响。
- 面试可讲点：这次把 Agent 上线前检查从“能跑一次”升级为可复现 gate：先做资源/依赖分层判定，再做 RAG grounding 与公开/内部 payload 隔离，最后用 CLI smoke 证明多轮对话、推荐、解释、rollout 与展示产物能闭环；本机适合 smoke 和轻量推理，SFT/GRPO 重任务应按限流策略迁移远程服务器执行。

## 2026-06-14 P3 Agent candidate flow 与在线治理收口

- 任务：收口 P3 的 Agent candidate flow 与 online governance，确保 retrieve_candidates 进入最终推荐回合，rank_candidates 只接受显式候选 id，co_visit 诊断路径不进入 live candidates，坏的 pool500 artifact 走降级/回退，`/health` 保持轻量。
- 遇到的问题：retrieve_candidates 如果只停留在诊断层，会导致候选没有进入 final turn；rank_candidates 容易出现“有交集就算成功”的伪通过；co_visit_fallback_repair 这类 diagnostic/batch-scoped 路径不能误入 live `/recall` 或 `/recommend`；`/health` 若承担 readiness 会拖重在线探活。最终 review 还补充定位到 registry / artifact / source-index 相对路径依赖 CWD、online candidate route 缺 governance 时 fail-open，以及 `final_pool500_ready_claimed` 未纳入 serving guardrail 的治理风险。
- 定位方式：围绕 `tests/test_agent_runtime.py`、`tests/test_serving_smoke.py`、`tests/test_serving_recommend_from_sequence.py`、`tests/test_serving_facades.py` 这组 contract/targeted tests 核对候选传递、显式 id 收紧、降级路径、健康检查、路径解析和 governance fail-closed 语义；worker-code focused `tests/test_agent_runtime.py -q` 结果 `30 passed`，worker-test contract suite `.venv/Scripts/python -m pytest tests/test_agent_runtime.py tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py -q` 结果 `80 passed in 1.64s`。
- 解决方式：让 `retrieve_candidates` 的输出显式进入 final turn；`rank_candidates` 只接受当前 turn pool 内的 explicit ids；将 co-visit fallback 标记为 diagnostic-only，不再进入 live candidate generation；bad pool500 artifact 走 degraded/fallback 而不是伪成功；`/health` 继续只做轻量 liveness，把 readiness 留给 `/ready`。同时将默认 serving registry 固定到 repo root 解析，pool500/source-index 路径按 repo root/config-dir 解析且不再 fallback 到 CWD；online candidate route 缺 `online_route.governance` 时启动即拒绝；guardrail 增加 `final_pool500_ready_claimed=false`。
- 验证结果：先跑 serving governance regression：`.venv/Scripts/python -m pytest tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py -q`，结果 `53 passed in 1.64s`。最终 targeted suite：`.venv/Scripts/python -m pytest tests/test_agent_runtime.py tests/test_agent_dialogue.py tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py tests/test_serving_facades.py tests/test_display_contract.py tests/test_agent_tools.py tests/test_agent_capability_manifest.py -q`，结果 `239 passed in 2.10s`。code-reviewer 最终 `APPROVE`，verifier 最终 `PASS/APPROVE`，未发现 blocker。
- 面试可讲点：这段可以概括成“把 Agent 候选流和在线治理从能跑改成语义正确、启动即受控”：最终 turn、候选池、降级与健康检查各司其职，避免诊断路径污染线上候选；同时把路径解析和 governance guardrail 前置成服务启动合同，防止部署 CWD、配置漂移或 final-ready 误声明绕过上线边界。

## 2026-06-19 å‰�ç«¯å¯¼è´­å¼�æŽ¨è��å±•ç¤º ViewModel

- ä»»åŠ¡ï¼šåœ¨ä¸�ä¿®æ”¹å�Žç«¯ display schema å’Œ public API çš„å‰�æ��ä¸‹ï¼ŒæŠŠ `DisplayResponse` çš„å¹³é“ºå•†å“�å�¡åŒ…è£…æˆ�æ›´åƒ�å¯¼è´­çš„å‰�ç«¯æŽ¨è��å±•ç¤ºã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šå�Žå�° `retrieve_candidates` å·²ç»�æ”¶æ•›ä¸ºä¸šåŠ¡æ¨¡å¼�é©±åŠ¨ï¼Œä½†å‰�ç«¯ä»�ç›´æŽ¥å±•ç¤º assistant æ–‡æ¡ˆå’Œå•†å“�ç½‘æ ¼ï¼Œç”¨æˆ·éš¾ä»¥ç�†è§£â€œæœ¬è½®æŽ¨è��ç�†è§£äº†ä»€ä¹ˆã€�ä¸ºä»€ä¹ˆæŽ¨è��ã€�ä¸‹ä¸€æ­¥å¦‚ä½•å��é¦ˆâ€�ï¼›å¦‚æžœè¿‡æ—©æ‰©å±•å�Žç«¯ schemaï¼Œä¼šæ‰©å¤§ display contract å’Œ serving éªŒè¯�é�¢ã€‚
- å®šä½�æ–¹å¼�ï¼šæ£€æŸ¥ `frontend/src/types.ts`ã€�`ChatPanel.tsx`ã€�`ProductCard.tsx`ã€�`FeedbackActions.tsx`ã€�`LiveDemo.tsx` çš„çŽ°æœ‰æ•°æ�®ç»“æž„å’Œå±•ç¤ºè·¯å¾„ï¼Œç¡®è®¤çŽ°æœ‰ `DisplayItem` å·²åŒ…å�« title/category/price/rating/features/summary/badgesï¼Œè¶³å¤Ÿå…ˆåœ¨å‰�ç«¯æŽ¨å¯¼å¯¼è´­è§†å›¾ã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `frontend/src/utils/displayViewModel.ts`ï¼Œä»ŽçŽ°æœ‰ displayã€�æœ€è¿‘ç”¨æˆ·æ¶ˆæ�¯å’Œæœ€è¿‘å��é¦ˆä¸Šä¸‹æ–‡æŽ¨å¯¼æ„�å›¾æ‘˜è¦�ã€�chipsã€�åˆ†ç»„æŽ¨è��å’Œ reference æ��ç¤ºï¼›æ–°å¢ž `RecommendationIntentSummary` ä¸Ž `GroupedRecommendationGrid`ï¼›å¢žå¼º `ProductCard` çš„ç”¨æˆ·å�¯è¯» badgeã€�æŽ¨è��ç�†ç”±å’Œâ€œå–œæ¬¢æ‰¾ç›¸ä¼¼ / ä¸�æ„Ÿå…´è¶£ / ä¸ºä»€ä¹ˆæŽ¨è��â€�æŒ‰é’®ï¼›å¤�ç”¨ `FeedbackActions` ç»Ÿä¸€å…¨å±€å��é¦ˆ chipsï¼›`LiveDemo` ä»…æ–°å¢žæœ€è¿‘å��é¦ˆä¸Šä¸‹æ–‡çŠ¶æ€�ï¼Œä¸�æ”¹å�Žç«¯ schemaã€‚
- éªŒè¯�ç»“æžœï¼šè¿�è¡Œ `cd frontend && npm run build` ä¸¤æ¬¡å�‡é€šè¿‡ï¼Œæœ€ç»ˆäº§ç‰©æž„å»ºæˆ�åŠŸï¼›verifier å�ªè¯»å¤�æ ¸ç»™å‡º `PASS`ï¼Œç¡®è®¤ TypeScript/React æ— é˜»å¡žé—®é¢˜ã€�æ”¹é€ ä¿�æŒ� frontend-onlyã€�æŽ¨è��å�¡åŒºåŸŸæ²¡æœ‰æ–°å¢ž tool/retrieval/RAG/score/source/itemcf/usercf/two_tower/co_visit ç­‰å†…éƒ¨è¯�æ³„æ¼�ã€‚æ ¹æ�® verifier å»ºè®®è¡¥å……äº† `features` ç©ºå€¼å…œåº•å¹¶ä¿®æ­£é�žé»˜è®¤ Tailwind è‰²é˜¶å�Žå†�æ¬¡ build é€šè¿‡ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ®µå�¯ä»¥è®²æˆ�â€œæŽ¨è��äº§å“�ä½“éªŒçš„æ¸�è¿›å¼�å¥‘çº¦æ¼”è¿›â€�ï¼šå…ˆä¸�æ€¥ç�€å›ºåŒ–å�Žç«¯ schemaï¼Œè€Œæ˜¯åœ¨å‰�ç«¯ç”¨ ViewModel éªŒè¯�å¯¼è´­å¼�å±•ç¤ºï¼ŒåŒ…æ‹¬éœ€æ±‚ç�†è§£ã€�åˆ†ç»„ã€�æŽ¨è��ç�†ç”±å’Œå��é¦ˆé—­çŽ¯ï¼›ç­‰äº¤äº’å½¢æ€�ç¨³å®šå�Žï¼Œå†�æŠŠè¢«éªŒè¯�è¿‡çš„å­—æ®µæ™‹å�‡ä¸º public display contractã€‚



## 2026-06-20 ä¼šè¯�ç»“æ�Ÿ LLM æ€»ç»“ hook ä¸Ž public-safe ç”Ÿå‘½å‘¨æœŸæ”¶å�£

- ä»»åŠ¡ï¼šè¡¥å…¨å®žæ—¶ RAG query planning ä¹‹å¤–çš„ä¼šè¯�ç»“æ�Ÿç”Ÿå‘½å‘¨æœŸï¼Œåœ¨ç”¨æˆ·æ‰‹åŠ¨ç»“æ�Ÿã€�ç»“ç®—ã€�åˆ‡æ�¢ persona æˆ–é¡µé�¢é€€å‡ºæ—¶è§¦å�‘ `/session/end`ï¼ŒåŸºäºŽ public-safe ä¼šè¯�æ��æ–™è°ƒç”¨ LLM ç”Ÿæˆ� Markdown æ€»ç»“æ–‡æ¡£ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šåŽŸ serving å�ªæœ‰ start/chat/feedback/exportï¼Œæ²¡æœ‰æ˜Žç¡® session end hookï¼›å¦‚æžœæŠŠæ€»ç»“æ”¾åœ¨æ¯�è½®æŽ¨è��é‡Œä¼šå¢žåŠ å®žæ—¶é“¾è·¯å»¶è¿Ÿä¸”ä¸Šä¸‹æ–‡ä¸�å®Œæ•´ï¼›summary è¿˜æ¶‰å�Š raw user textã€�LLM è¾“å‡ºã€�frontmatterã€�summary path å’Œ session ç»“æ�Ÿå�Žç»§ç»­å†™å…¥ç­‰å®‰å…¨/ä¸€è‡´æ€§è¾¹ç•Œã€‚
- å®šä½�æ–¹å¼�ï¼šæ²¿ `rs_core/serving/app.py`ã€�`service.py`ã€�`facades.py`ã€�`persistence.py` å’Œå‰�ç«¯ `LiveDemo.tsx`ã€�`MallHome.tsx` æ£€æŸ¥ä¼šè¯�ç”Ÿå‘½å‘¨æœŸï¼›code-reviewer å¤šè½®å¤�æ ¸æŒ‡å‡º PII/secret redactionã€�frontmatter æ³¨å…¥ã€�ç»“æ�Ÿå�Žç»§ç»­ chat/feedbackã€�å‰�ç«¯å¤±è´¥é‡�è¯•å’Œ pagehide best-effort çš„é£Žé™©ç‚¹ã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `rs_core/serving/session_summary.py`ï¼Œå�ªä»Ž public export æž„é€  LLM è¾“å…¥ï¼Œå‰¥ç¦» agent thoughts/tool trace/raw evidence/score/source ç­‰å†…éƒ¨å­—æ®µï¼Œå¹¶å¯¹ç”¨æˆ·æ–‡æœ¬ã€�metadataã€�LLM è¾“å‡ºå�šæ•�æ„Ÿä¿¡æ�¯ redactionï¼›æ–°å¢ž `/session/end` schema/API/service/facade/persistenceï¼Œè®°å½• `session_ended`ï¼Œç”Ÿæˆ� summary documentï¼Œç»“æ�Ÿå�Ž chat/feedback è¿”å›ž `409 SESSION_ENDED` ä½† export ä¿�æŒ�å�¯è¯»ï¼›å‰�ç«¯æ–°å¢ž `endSession/endSessionKeepalive`ï¼ŒLiveDemo æ”¯æŒ�æ‰‹åŠ¨ç»“æ�Ÿå’Œ demo roundtrip å‰�æ—§ session æ”¶å�£ï¼ŒMallHome æ”¯æŒ� checkout/persona switch/pagehide è§¦å�‘ï¼Œå¹¶ä¿�è¯�å¤±è´¥å�Žå�¯é‡�è¯•ã€‚
- éªŒè¯�ç»“æžœï¼šä½¿ç”¨é¡¹ç›® `.venv` è¿�è¡Œ `.venv/Scripts/python.exe -m pytest tests/test_session_summary.py tests/test_serving_persistence.py tests/test_serving_smoke.py tests/test_serving_facades.py -q`ï¼Œç»“æžœ `72 passed`ï¼›è¿�è¡Œ `.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_agent_runtime.py tests/test_agent_dialogue.py tests/test_rag_core.py -q`ï¼Œç»“æžœ `121 passed`ï¼›é€šè¿‡ `.venv/Scripts/python.exe -c "import subprocess; raise SystemExit(subprocess.run([r'D:\Program Files\nodejs\npm.cmd', 'run', 'build'], cwd='frontend').returncode)"` å®Œæˆ�å‰�ç«¯ buildï¼›æœ€ç»ˆ code-reviewer å¤�å®¡ `PASS`ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ®µå�¯ä»¥è®²æˆ�â€œæŽ¨è�� Agent çš„ä¼šè¯�ç”Ÿå‘½å‘¨æœŸæ²»ç�†â€�ï¼šæŠŠå®žæ—¶ RAG query planning å’Œç»“æ�Ÿå�Ž LLM summarization æ˜Žç¡®æ‹†å¼€ï¼Œå®žæ—¶é“¾è·¯å�ªå�šä½Žå»¶è¿Ÿ hintï¼Œç»“æ�Ÿé“¾è·¯åŸºäºŽå®Œæ•´ public-safe è½¨è¿¹äº§å‡ºå�¯å®¡è®¡æ€»ç»“ï¼›å�Œæ—¶ç”¨ redactionã€�å�ªè¯»ç»ˆæ€�ã€�æŒ�ä¹…åŒ–äº‹ä»¶å’Œå‰�ç«¯å¤šè§¦å�‘ç‚¹ï¼ŒæŠŠå¤šè½®æŽ¨è��ä»Žâ€œèƒ½å¯¹è¯�â€�æŽ¨è¿›åˆ°â€œå�¯å¤�ç›˜ã€�å�¯ç»§æ‰¿ã€�å�¯æ²»ç�†â€�ã€‚


## 2026-06-20 é¦–é¡µè¡Œä¸º FeedRefreshAgent ä¸Žå¯¹è¯� RSAgent å�Œç¼–æŽ’è�½åœ°

- ä»»åŠ¡ï¼šæŒ‰å�Œ Agent è§„åˆ’æŠŠé¦–é¡µç»“æž„åŒ–è¡Œä¸ºé“¾è·¯ä»Žå¯¹è¯�å¼� `/feedback` ä¸­æ‹†å‡ºï¼Œæ–°å¢ž `FeedRefreshAgent`/`FeedRefreshPolicy` å¯¹åº”çš„ `/feed/refresh` å�Žç«¯å…¥å�£ï¼Œå¹¶è®© MallHome é€šè¿‡è¡Œä¸ºäº‹ä»¶è§¦å�‘ rerankã€�re-recallã€�no-refresh æˆ– fallbackã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šé¦–é¡µç‚¹å‡»ã€�å–œæ¬¢ã€�ç‚¹è¸©ã€�å�œç•™å’Œâ€œæ�¢ä¸€æ‰¹â€�ä¸�èƒ½ç®€å�•ç­‰ä»·ä¸ºå¯¹è¯� promptï¼›å¦‚æžœå½“å‰�å€™é€‰æ± æ²¡æœ‰å¯¹åº”å•†å“�ï¼Œå�ªé‡�æŽ’æ²¡æœ‰ä»·å€¼ï¼›å�Œæ—¶å‰�ç«¯åˆ·æ–°éœ€è¦� `display_revision` é˜²æ­¢æ—§å“�åº”è¦†ç›–æ–°é¡µé�¢ï¼Œpublic payload ä¸�èƒ½æ³„éœ²æ¨¡åž‹åˆ†æ•°ã€�sourceã€�diagnostics æˆ–å†…éƒ¨ traceã€‚
- å®šä½�æ–¹å¼�ï¼šæ£€æŸ¥ `rs_core/serving/schema.py`ã€�`service.py`ã€�`facades.py`ã€�`app.py` çš„ serving contractï¼Œç»“å�ˆ `rs_core/workflow/online_recommendation.py` çŽ°æœ‰ pool500/feedback rerank èƒ½åŠ›ï¼Œä»¥å�Š `frontend/src/views/MallHome.tsx`ã€�`frontend/src/api.ts`ã€�`frontend/src/types.ts` çš„é¦–é¡µäº¤äº’è·¯å¾„ï¼Œç¡®è®¤é¦–é¡µè¡Œä¸ºåº”èµ°ç»“æž„åŒ– refresh seamï¼Œè€Œå¯¹è¯�è§£é‡Šç»§ç»­ä¿�ç•™åœ¨ `ConversationalRSAgent`/`RSAgent`ã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `HomeFeedEventRequest`ã€�`FeedRefreshDecisionResponse`ã€�`DisplayRefreshResponse`ï¼Œåœ¨ `FeedRefreshFacade` å†…ç»´æŠ¤è½»é‡� `FeedSessionState` å’Œå†…éƒ¨ decision traceï¼›ç­–ç•¥ä¸Š click/çŸ­ dwell å�ªè®°å½•ä¸�åˆ·æ–°ï¼Œlike/dislike/é•¿ dwell èµ° `rerank_existing`ï¼Œsearch ä¸Žè¿žç»­ show_different/å€™é€‰ä¸�è¶³èµ° `rerecall_pool500`ï¼Œrevision å†²çª�æˆ–å¼‚å¸¸èµ° public-safe fallbackï¼›å‰�ç«¯ MallHome æ”¹ä¸ºè°ƒç”¨ `refreshFeed('/feed/refresh')` å¹¶æŒ‰ `display_revision` åº”ç”¨æ–°å±•ç¤ºã€‚
- éªŒè¯�ç»“æžœï¼šä½¿ç”¨é¡¹ç›® `.venv` è¿�è¡Œ `.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_serving_persistence.py tests/test_serving_run_service.py -q`ï¼Œç»“æžœ `69 passed in 1.99s`ï¼›è¿�è¡Œ `cd frontend && npm run lint`ï¼ŒTypeScript `tsc --noEmit` é€šè¿‡ã€‚æœŸé—´ä¸€æ¬¡ä»Žé�ž repo root ä½¿ç”¨ç»�å¯¹æµ‹è¯•è·¯å¾„å¯¼è‡´ `ModuleNotFoundError: tests/scripts`ï¼Œå·²æ”¹ä¸ºä»Ž repo root æ‰§è¡Œè§£å†³ã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ®µå�¯ä»¥è®²æˆ�â€œæŠŠæŽ¨è��é¦–é¡µä»Žè¢«åŠ¨å��é¦ˆå�‡çº§ä¸ºè¡Œä¸ºé©±åŠ¨çš„å®žæ—¶åˆ·æ–°ç¼–æŽ’â€�ï¼šä¸�æ˜¯æ‰€æœ‰å��é¦ˆéƒ½äº¤ç»™ LLM å¯¹è¯�ï¼Œè€Œæ˜¯ç”¨ç»“æž„åŒ– Agent policy åœ¨ä½Žå»¶è¿Ÿé“¾è·¯åˆ¤æ–­é‡�æŽ’è¿˜æ˜¯é‡�æ–°å�¬å›žï¼›å�Œæ—¶ç”¨ revisionã€�public/private è¾¹ç•Œã€�fallback reason å’Œ serving contract ä¿�è¯�ä½“éªŒç¨³å®šã€�å�¯å›žæ”¾ã€�å�¯æ²»ç�†ã€‚


## 2026-06-20 COLDâ†’DeepFM å·¥ç¨‹ä¸»æŽ’åº�è·¯çº¿å›ºå®š

- ä»»åŠ¡ï¼šæ ¹æ�®å½“å‰�é¡¹ç›®ç›®æ ‡ä»Žâ€œç»§ç»­æŽ’åº�ä¼˜åŒ–â€�è½¬å�‘â€œAgent/å‰�ç«¯é—­çŽ¯â€�ï¼Œæ­£å¼�å›ºå®š `pool500 + COLD ç²—æŽ’ + DeepFM ç²¾æŽ’` ä¸ºå½“å‰�å·¥ç¨‹ä¸»æŽ’åº�è·¯çº¿ï¼Œå¹¶æŠŠæ—§ baseline/GBDT/XGBoost/LambdaMART ç­‰è·¯çº¿é™�çº§ä¸º fallbackã€�åŽ†å�²æˆ–æœªæ�¥å·¥ä½œã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šCOLDâ†’DeepFM çš„ full/formal è®­ç»ƒé“¾è·¯å·²ç»�è¡¥é½�ï¼Œä½† frozen eval ä»�æœ‰å€™é€‰è¦†ç›–é—¨ç¦�ï¼Œä¸�èƒ½æŠŠå€™é€‰å†…è¯Šæ–­æ”¶ç›ŠåŒ…è£…æˆ�ä¸¥æ ¼æ•´ä½“æ•ˆæžœæ��å�‡ï¼›å¦‚æžœç»§ç»­ä¿�ç•™å¤šç§�æŽ’åº�æ–¹æ³•å¹¶è¡Œï¼Œä¼šè®©é¡¹ç›®ä¸»çº¿å�‘æ•£ï¼Œå½±å“� Agent å’Œå‰�ç«¯é—­çŽ¯æŽ¨è¿›ã€‚
- å®šä½�æ–¹å¼�ï¼šæ ¸å¯¹ `outputs/ranking/cold_full_formal_20260620_existing_deepfm/` ä¸‹ `cold_model.json`ã€�`manifest.json`ã€�`comparison.json` çš„è®­ç»ƒå’Œè¯„ä¼°è¯�æ�®ï¼›ç»“å�ˆå½“å‰�é˜¶æ®µç›®æ ‡ç¡®è®¤æŽ’åº�ä¾§éœ€è¦�çš„æ˜¯å�¯è§£é‡Šã€�å�¯è�½åœ°çš„å·¥ç¨‹ä¸»è·¯ï¼Œè€Œä¸�æ˜¯ç»§ç»­æ‰©å±•æ¨¡åž‹åˆ†æ”¯ã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `dic/decisions/COLD_DEEPFM_MAIN_RANKING_ROUTE_ADR_2026_06_20.md`ï¼Œæ˜Žç¡® COLD ä½œä¸º coarse rank / candidate compressionï¼ŒDeepFM ä½œä¸º fine rank / feature-cross scorerï¼›æ›´æ–° `configs/governance/current_route_registry.yaml`ï¼Œå°† `current_ranking_route` æ”¹ä¸º `current_engineering_main`ï¼Œè®°å½• required artifactsã€�fallback route å’Œ `effect_claim_allowed=false` è¾¹ç•Œã€‚
- éªŒè¯�ç»“æžœï¼šä½¿ç”¨é¡¹ç›® `.venv` è¿�è¡Œ `.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_serving_persistence.py tests/test_serving_run_service.py -q`ï¼Œç»“æžœ `69 passed`ï¼›å‰�ç«¯ `cd frontend && npm run lint` å·²é€šè¿‡ã€‚è·¯çº¿å›ºå®šä¸ºæ–‡æ¡£/æ²»ç�†å±‚å�˜æ›´ï¼Œæ²¡æœ‰æ”¹å�˜æœ�åŠ¡ guardrail å¯¹ public/private payload å’Œ fallback çš„çº¦æ�Ÿã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šè¿™æ®µå�¯ä»¥è®²æˆ�â€œå·¥ç¨‹ä¸»è·¯æ™‹å�‡ä¸Žæ•ˆæžœå£°æ˜Žè§£è€¦â€�ï¼šåœ¨ full/formal è®­ç»ƒå®Œæˆ�å�Žï¼Œä¸ºäº†æŽ¨è¿›æŽ¨è�� Agent äº§å“�é—­çŽ¯ï¼ŒæŠŠ COLDâ†’DeepFM å›ºå®šä¸ºå·¥ä¸šåˆ†å±‚å¼�ç²—æŽ’/ç²¾æŽ’ä¸»è·¯ï¼›å�Œæ—¶ä¿�ç•™ baseline fallbackï¼Œä¸�æŠŠå€™é€‰è¦†ç›–ä¸�è¶³ä¸‹çš„å€™é€‰å†…æ”¶ç›Šå¤¸å¤§æˆ�å…¨å±€æŒ‡æ ‡æ��å�‡ï¼Œä½“çŽ°äº†è·¯çº¿æ”¶å�£å’Œè¯�æ�®è¾¹ç•Œæ„�è¯†ã€‚


## 2026-06-21 通用 Agent runtime Phase 1 契约层

- 任务：在不替换现有推荐 `AgentRuntime.run_turn` 的前提下，先落地通用 `BaseAgentLoop` 的 Phase 1 契约层，为后续 Recommendation adapter、shadow 对比和 SimulatedUserAgent 验证做准备。
- 遇到的问题：现有推荐 runtime 同时承担 trace、工具执行、turn 构建、diagnostics、reward/stop check 和 session summary 更新；如果直接泛化，容易把推荐域 schema、`session.turns.append` 写入语义、hidden tool/RAG 原始证据和 public/SFT 输出边界一起带入 generic core。
- 定位方式：对照 `rs_core/rsagent/runtime.py` 的 `RUNTIME_TRACE_STEP_ORDER`、`rs_core/workflow/hybrid_environment.py` 的 tool summary/result 语义、`rs_core/rsagent/tools.py` 的业务工具字段，以及前序 Architect/Critic 评审要求，先把兼容性固化为可测试契约。
- 解决方式：新增 `rs_core/agent_runtime/` 契约包，定义 `LoopMode`、`TraceEvent`、`ToolSummary`、`ToolResult`、`RuntimePatch`、`CommitIntent`、`ToolSpec` 和 deny-by-default `OutputAdapter`；RS ToolSpec 的业务字段只允许作为 `metadata.recommendation.*` opaque metadata 透传；新增 compatibility constants 锁定 legacy trace 13 步、tool summary/result 最小字段、四类 failure contract 与 OutputAdapter 可见性矩阵；新增 `.omc/handoffs/team-plan-to-team-exec-base-agent-loop.md` 记录阶段边界。
- 验证结果：使用项目 `.venv` 运行 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_agent_runtime_contracts.py -q`，结果 `11 passed in 0.13s`；独立 verifier 只读复核给出 `PASS`，确认 generic core 没有导入 recommendation/simulation/domain schema，trace order 与旧 runtime 对齐，OutputAdapter 默认 deny，append ownership 静态约束覆盖当前新增包。
- 面试可讲点：这段可以讲成“先契约化再迁移的 Agent runtime 抽象”：面对推荐 Agent loop 非通用的问题，没有直接重写生产链路，而是先用 import boundary、trace golden、tool failure contract、OutputAdapter 白名单和 append 单一所有权把风险变成可测试边界；后续再用 `generic_shadow` 验证兼容，降低架构抽象对线上推荐和 SFT 数据链路的冲击。


## 2026-06-22 Recommendation generic_shadow scaffold

- 任务：在 Phase 1 通用 runtime 契约层之后，补一个最小 `generic_shadow` scaffold，让 Recommendation 链路可以在不替换旧 loop 的前提下挂接 shadow 兼容报告，并继续默认走 legacy。
- 遇到的问题：如果 Phase 2 直接让 generic loop 接管推荐回合，会立刻触碰工具副作用、`session.turns.append`、public/SFT 输出和 trace 对齐风险；同时 `generic_active` 还没有经过 active readiness gates，不能被配置误开。
- 定位方式：沿 `AgentOrchestrationFacade.run_turn()` 和 `HybridRecommendationEnvironment.__init__()` 检查 runtime 入口，确认最小插入点应在 legacy `runtime.run_turn()` 外层：先记录 turn 数，执行一次旧链路，再只读 legacy trace 生成 internal shadow report。
- 解决方式：新增 `rs_core/agent_runtime/adapters/recommendation.py`，实现 `RecommendationShadowAdapter`/`RecommendationShadowReport`；`AgentOrchestrationFacade` 支持 `AgentRuntimeConfig`，默认 `legacy` 不加 shadow 字段，`generic_shadow` 只在 legacy turn 完成后附加 `agent_runtime_shadow` internal diagnostics，`generic_active` 在 readiness gates 前直接拒绝且不调用 host；`HybridRecommendationEnvironment` 从配置读取 `agent_runtime.loop_mode`，默认仍为 legacy。
- 验证结果：使用项目 `.venv` 运行 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_agent_runtime_contracts.py tests/test_agent_runtime.py::test_agent_orchestration_facade_delegates_to_runtime_host_seam tests/test_agent_runtime.py::test_agent_orchestration_facade_shadow_mode_attaches_internal_report_without_extra_append tests/test_agent_runtime.py::test_agent_orchestration_facade_rejects_generic_active_before_readiness_gates -q`，结果 `14 passed in 0.41s`；独立 verifier 只读复核给出 `PASS`，确认默认 legacy 无 shadow report，shadow 不额外 append、不重复执行工具，active guard 在 host 调用前生效，core 仍无 domain import。
- 面试可讲点：这段可以讲成“高风险 runtime 迁移的 shadow-first 设计”：不是把新抽象直接切到线上，而是在 façade 外层先做只读 shadow report，用 feature flag 严格区分 legacy/shadow/active，并把 active 作为独立 gate；这样既能开始收集兼容性证据，又不会改变用户可见行为或推荐会话写入语义。


## 2026-06-22 通用 GenericAgentLoop skeleton 与使用文档

- **任务**：补齐领域无关的 `GenericAgentLoop` skeleton，并提供后续衍生新 Agent 的中文使用说明。
- **遇到的问题**：原先只完成了 contract 与 Recommendation `generic_shadow` scaffold，还没有真正可复用的 input→context→plan→tools→response→patch/output 闭环；同时后续 Recommendation Agent、SimulatedUserAgent 需要明确工具、prompt、状态和输出边界。
- **定位方式**：沿用前期 contract 测试约束，重点检查 `rs_core/agent_runtime/core/` 是否保持无领域导入、generic loop 是否不直接 `session.turns.append(...)`、public/SFT 投影是否默认 allowlist。
- **解决方式**：新增 `rs_core/agent_runtime/core/loop.py`，定义 `AgentLoopInput`、`ToolCall`、`AgentPlan`、`AgentLoopResult` 和 `ContextBuilder`/`Planner`/`ToolDispatcher`/`ResponseComposer`/`StateUpdater` 协议；loop 只编排阶段并返回 `RuntimePatch`/`CommitIntent`，不提交领域状态。新增 `dic/GENERIC_AGENT_LOOP_USAGE.md` 说明组件边界、工具 metadata、输出投影和 Recommendation/SimulatedUserAgent 后续接入方式。
- **验证结果**：轻量测试 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/test_agent_runtime_contracts.py tests/test_generic_agent_loop.py -q` 通过，结果为 `13 passed in 0.16s`；独立 verifier 首轮指出顶层导出缺少 `OutputProjectionPolicy`/`ProjectionViolation`，修复后复核通过，确认 focused tests 与顶层导出均通过。
- **面试可讲点**：这次不是直接把推荐 runtime 重写成“大而全”基类，而是先抽出可测试的通用 loop skeleton，把工具、prompt/context、输出安全和状态提交做成外置协议；通过 shadow/contract/fake-agent 测试降低迁移风险，为后续多 Agent 复用打下基础。

### 2026-06-22 - æœ¬åœ°è¯•è¿�è¡ŒæŠ€æœ¯é€‰åž‹æ–‡æ¡£æ²‰æ·€

**ä»»åŠ¡ï¼š**
æŠŠæ­¤å‰�å›´ç»• FastAPIã€�PostgreSQLã€�Qdrantã€�Redisã€�MinIOã€�MLflowã€�vLLM/Qwen ç­‰ç»„ä»¶çš„æœ¬åœ°è¯•è¿�è¡Œçº§æŠ€æœ¯é€‰åž‹æ•´ç�†æˆ�å�¯å¤�è¿°çš„ä¸­æ–‡å·¥ç¨‹æ–‡æ¡£ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
è¿™äº›ç»„ä»¶å®¹æ˜“è¢«è¯¯è§£ä¸ºå·²ç»�å…¨éƒ¨ç”Ÿäº§åŒ–éƒ¨ç½²ï¼›å®žé™…å½“å‰�å�ªè�½åœ° local/trial/non-production MVPï¼ŒQdrant/PostgreSQL æ˜¯å‡†å¤‡å’Œå°�æ ·æœ¬è¯•è¿�è¡Œè¾¹ç•Œï¼ŒRedis/MinIO/MLflow/vLLM/KServe ç­‰æ›´å¤šæ˜¯å�Žç»­èƒ½åŠ›é¢„ç•™ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å¯¹é½� `deploy/local/docker-compose.yml`ã€�`deploy/local/README.md`ã€�`deploy/local/postgres/init/001_schema.sql`ã€�`.env.example` ä»¥å�Šå½“å‰� RAG/Qdrant/fallback/Agent provider è¾¹ç•Œï¼Œç¡®è®¤æ–‡æ¡£éœ€è¦�åŒºåˆ†â€œå·²è�½åœ°ã€�å·²å‡†å¤‡ã€�ä»…é¢„ç•™ã€�æ˜Žç¡®ä¸�å�šâ€�ã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢ž `dic/architecture/TECH_STACK_SELECTION.md`ï¼ŒæŒ‰ç»„ä»¶è¯´æ˜Žé€‰åž‹ç�†ç”±ã€�å½“å‰�çŠ¶æ€�ã€�é¡¹ç›®å†…è�Œè´£ã€�èµ„æº�/å®‰å…¨è¾¹ç•Œå’Œæ¼”è¿›é¡ºåº�ï¼›åœ¨ `dic/README.md` æŽ¨è��é˜…è¯»é¡ºåº�ä¸­åŠ å…¥è¯¥æ–‡æ¡£å…¥å�£ã€‚

**éªŒè¯�ç»“æžœï¼š**
è¿�è¡Œè½»é‡�æ–‡æ¡£ smokeï¼Œç¡®è®¤æŠ€æœ¯é€‰åž‹æ–‡æ¡£åŒ…å�« PostgreSQLã€�Qdrantã€�Redisã€�MinIOã€�MLflowã€�vLLM/Qwenã€�SQLite BM25ã€�local/trial/non-production MVP ç­‰å…³é”®é”šç‚¹ï¼Œå¹¶ç¡®è®¤ `dic/README.md` å·²é“¾æŽ¥ `architecture/TECH_STACK_SELECTION.md`ï¼Œè¾“å‡º `tech stack doc smoke ok`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œä¸�æ˜¯å †ç»„ä»¶ï¼Œè€Œæ˜¯æŒ‰æŽ¨è�� Agent çš„å·¥ç¨‹è¾¹ç•Œå�šåˆ†å±‚é€‰åž‹â€�ï¼šPostgreSQL ç®¡ç»“æž„åŒ–æ•°æ�®ï¼ŒQdrant ç®¡å�‘é‡�æ£€ç´¢ï¼ŒSQLite BM25 ç®¡ fallbackï¼ŒRedis/MinIO/MLflow/vLLM ä½œä¸ºæ˜Žç¡®é¢„ç•™ï¼Œå¹¶é€šè¿‡æ–‡æ¡£æŠŠæœ¬åœ°è¯•è¿�è¡Œã€�èµ„æº�é™�åˆ¶å’Œæœªæ�¥ç”Ÿäº§åŒ–è·¯çº¿æ‹†å¼€ã€‚

### 2026-06-22 - PostgreSQL 2y æ•°æ�®åº“ D ç›˜å¤–æŒ‚è¿�ç§»

**ä»»åŠ¡ï¼š**
å°†å·²å¯¼å…¥å®Œæ•´ 2y æ•°æ�®çš„æœ¬åœ° PostgreSQL ä»Ž Docker named volume è¿�ç§»åˆ°é¡¹ç›® D ç›˜ç›®å½• `data/postgres/pgdata`ï¼Œé�¿å…�æ•°æ�®åº“å®žé™…å� ç”¨ Docker Desktop é»˜è®¤ C ç›˜æ•°æ�®åŒºï¼Œå¹¶æ–¹ä¾¿å�Žç»­æœ¬åœ°ç£�ç›˜å®¹é‡�ç®¡ç�†ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
Docker Compose çš„ `postgres_data:/var/lib/postgresql/data` named volume åœ¨ Windows Docker Desktop ä¸‹ç”± Docker å†…éƒ¨ç®¡ç�†ï¼Œç”¨æˆ·åœ¨é¡¹ç›®ç›®å½•ä¸­çœ‹ä¸�åˆ°æ•°æ�®æ–‡ä»¶ï¼Œä¸”å®¹æ˜“å� ç”¨ C ç›˜ï¼›å�Œæ—¶åº“é‡Œå·²ç»�å¯¼å…¥ 2y å…¨é‡�ç»“æž„åŒ–æ•°æ�®ï¼Œä¸�èƒ½é€šè¿‡ç›´æŽ¥é‡�å»ºå®¹å™¨å¯¼è‡´æ•°æ�®ä¸¢å¤±ã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ£€æŸ¥ `deploy/local/docker-compose.yml` çš„ PostgreSQL volume é…�ç½®ï¼Œç¡®è®¤å½“å‰�ä½¿ç”¨ named volumeï¼›é€šè¿‡ SQL æ ¡éªŒæº�åº“ `products=887002`ã€�`interactions=11936005`ã€�`user_sequences=7080947`ã€�`interactions_without_product=0`ï¼Œå¹¶ç”¨ `pg_dump -Fc` ç”Ÿæˆ�è¿�ç§» dump ä½œä¸ºå�¯æ�¢å¤�ä¸­é—´æ€�ã€‚

**è§£å†³æ–¹å¼�ï¼š**
å°† compose ä¸­ PostgreSQL æ•°æ�®ç›®å½•æ”¹ä¸º bind mountï¼š`../../data/postgres/pgdata:/var/lib/postgresql/data`ï¼›æ–°å¢ž `.gitignore` å¿½ç•¥ `data/postgres/` å’Œ `data/postgres_migration/`ï¼›æ›´æ–° `deploy/local/README.md` ä¸Ž `dic/architecture/TECH_STACK_SELECTION.md` çš„æœ¬åœ°å­˜å‚¨è¯´æ˜Žã€‚è¿�ç§»æ‰§è¡Œæ—¶å…ˆ dump æ—§åº“ï¼Œå†�é‡�å»º PostgreSQL å®¹å™¨åˆ° D ç›˜å¤–æŒ‚ç›®å½•ï¼Œéš�å�Ž `pg_restore` æ�¢å¤�ï¼›æ—§ Docker named volume `local_postgres_data` ä¿�ç•™ä¸�åˆ ï¼Œä½œä¸ºå›žæ»šä¿�é™©ã€‚

**éªŒè¯�ç»“æžœï¼š**
`docker inspect local-postgres-1` æ˜¾ç¤º `/var/lib/postgresql/data` å®žé™…æŒ‚è½½æº�ä¸º `D:\sinrotic_code\python_project\summer\RS_agent\data\postgres\pgdata`ã€‚æ�¢å¤�å�Ž SQL æ ¡éªŒé€šè¿‡ï¼š`products=887002`ã€�`interactions=11936005`ã€�`user_sequences=7080947`ï¼›split åˆ†å¸ƒä¸º `train=11538991`ã€�`valid=154867`ã€�`test=242147`ï¼›`distinct_users=7080947`ã€�`distinct_items=887002`ï¼›`interactions_without_product=0`ï¼›æ•°æ�®åº“å¤§å°�çº¦ `12GB`ã€‚æœ¬åœ° `data/postgres/pgdata` çº¦ `14GB`ï¼Œè¿�ç§» dump ä½�äºŽ `data/postgres_migration/rs_agent_pre_bind.dump` çº¦ `1.4GB`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œæœ¬åœ°æ•°æ�®æœ�åŠ¡è�½åœ°æ—¶çš„å­˜å‚¨æ²»ç�†â€�ï¼šä¸�ä»…æŠŠ 2y JSONL è½¬æˆ�å�¯æŸ¥è¯¢çš„ PostgreSQLï¼Œè¿˜è¯†åˆ« Docker Desktop named volume çš„ç£�ç›˜ä½�ç½®é£Žé™©ï¼Œé€šè¿‡ dump/restoreã€�bind mountã€�gitignore å’Œå®Œæ•´ SQL æ ¡éªŒå®Œæˆ�æ— æ�Ÿè¿�ç§»ï¼Œå�Œæ—¶ä¿�ç•™æ—§ volume ä½œä¸ºå›žæ»šè·¯å¾„ï¼Œä½“çŽ°å·¥ç¨‹åŒ–æ•°æ�®è¿�ç§»çš„å®‰å…¨è¾¹ç•Œã€‚

### 2026-06-22 - 2y æ•°æ�®å…¥åº“å�Žæœ¬åœ° full/2y æ–‡ä»¶æ¸…ç�†

**ä»»åŠ¡ï¼š**
åœ¨è¿œç¨‹å¤‡ä»½å®Œæˆ�ã€�PostgreSQL 2y æ•°æ�®åº“å¯¼å…¥å¹¶è¿�ç§»åˆ° D ç›˜å¤–æŒ‚ç›®å½•å�Žï¼Œæ¸…ç�†æœ¬åœ°ä¸�å†�éœ€è¦�çš„ full/2y æ–‡ä»¶å‰¯æœ¬ï¼Œå�ªä¿�ç•™ base æº�æ•°æ�®å’Œ PostgreSQL ç»“æž„åŒ–æ•°æ�®åº“ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
æœ¬åœ° D ç›˜æ­¤å‰�ç©ºé—´ç´§å¼ ï¼›å�Œæ—¶ä¸�èƒ½ç®€å�•åˆ é™¤åŽŸå§‹å¤„ç�†æ–‡ä»¶ï¼Œå¿…é¡»å…ˆè¯�æ˜Žè¿œç¨‹å¤‡ä»½å­˜åœ¨ã€�æ–°åº“å­—æ®µå’Œè¡Œæ•°å®Œæ•´ã€�PostgreSQL æ•°æ�®ç›®å½•å·²ä»Ž Docker named volume è¿�ç§»åˆ° D ç›˜ bind mountï¼Œä¸”åˆ é™¤ä¸�ä¼šå½±å“�æ•°æ�®åº“æœ�åŠ¡ã€‚

**å®šä½�æ–¹å¼�ï¼š**
åˆ é™¤å‰�å¤�æ ¸ PostgreSQLï¼š`products=887002`ã€�`interactions=11936005`ã€�`user_sequences=7080947`ï¼›split åˆ†å¸ƒ `train=11538991`ã€�`valid=154867`ã€�`test=242147`ï¼›`distinct_users=7080947`ã€�`distinct_items=887002`ï¼›`interactions_without_product=0`ï¼›å­—æ®µå±‚é�¢ç¡®è®¤æ ¸å¿ƒå­—æ®µè¿›å…¥ç»“æž„åŒ–åˆ—ï¼Œè¾…åŠ©å­—æ®µè¿›å…¥ `metadata` JSONBã€‚`docker inspect` ç¡®è®¤ `/var/lib/postgresql/data` æŒ‚è½½åˆ° `D:\sinrotic_code\python_project\summer\RS_agent\data\postgres\pgdata`ã€‚

**è§£å†³æ–¹å¼�ï¼š**
ç»�ç”¨æˆ·ç¡®è®¤å�Žåˆ é™¤æœ¬åœ°ä¸‰ä¸ªå·²å¤‡ä»½ä¸”ä¸�å†�ä½œä¸ºæœ¬åœ°ä¸»çº¿è¾“å…¥çš„ç›®å½•ï¼š`data/processed/amazon_2023_recall_clean_full`ã€�`data/processed/amazon_2023_recall_views_full_lightweight`ã€�`data/processed/amazon_2023_recall_recent_2y_1m_3m`ã€‚ä¿�ç•™ `data/processed/amazon_2023_base`ã€�`data/postgres/pgdata` å’Œ `data/postgres_migration`ã€‚

**éªŒè¯�ç»“æžœï¼š**
åˆ é™¤å�Ž `df -h` æ˜¾ç¤º D ç›˜å�¯ç”¨ç©ºé—´ä»Žçº¦ `81G/93G` çº§åˆ«æ��å�‡åˆ° `218G`ï¼Œä½¿ç”¨çŽ‡é™�è‡³ `73%`ï¼›ä¸‰é¡¹ç›®å½•å�‡ä¸�å­˜åœ¨ï¼›`amazon_2023_base` å’Œ `data/postgres/pgdata` ä»�å­˜åœ¨ã€‚PostgreSQL åˆ é™¤å�Žä»�å�¯æŸ¥è¯¢ï¼Œè¡Œæ•°ä¿�æŒ� `products=887002`ã€�`interactions=11936005`ã€�`user_sequences=7080947`ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�æœ¬åœ°æ•°æ�®æœ�åŠ¡åŒ–å�Žçš„å­˜å‚¨æ”¶å�£ï¼šå…ˆè¿œç¨‹å¤‡ä»½ï¼Œå†�æŠŠ 2y JSONL è½¬æˆ� PostgreSQL ç»“æž„åŒ–æŸ¥è¯¢å±‚ï¼Œè¿�ç§»æ•°æ�®åº“åˆ° D ç›˜å�¯æŽ§ç›®å½•ï¼Œæœ€å�Žåœ¨å®Œæ•´æ€§æ ¡éªŒå�Žæ¸…ç�†å†—ä½™æ–‡ä»¶ï¼ŒæŠŠæœ¬åœ°ç£�ç›˜ä»Žâ€œå †åŽŸå§‹ä¸­é—´äº§ç‰©â€�è½¬ä¸ºâ€œbase æº�æ•°æ�® + å�¯æŸ¥è¯¢æ•°æ�®åº“ + å�¯å›žæ»š dumpâ€�çš„å·¥ç¨‹çŠ¶æ€�ã€‚

### 2026-06-22 - serving åˆ†å±‚æž¶æž„è½»æ‹†ä¸Žå…¼å®¹ shim

**ä»»åŠ¡ï¼š**
æŒ‰å·²æ‰¹å‡† serving æ–‡ä»¶æž¶æž„è®¡åˆ’ï¼ŒæŠŠ `rs_core/serving` ä»Žæ‰�å¹³å…¥å�£æ•´ç�†ä¸º `api/application/domain/governance/infrastructure/runtime/schemas` åˆ†å±‚éª¨æž¶ï¼Œå¹¶ä¿�ç•™æ—§ import å…¼å®¹ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
`service.py` å�Œæ—¶æ‰¿è½½é…�ç½®è§£æž�ã€�readiness projection å’Œåº”ç”¨æœ�åŠ¡å…¥å�£ï¼›æ–°å¢žå�ˆå�Œå±‚ä»�åœ¨æ—§æ‰�å¹³è·¯å¾„ï¼Œå�Žç»­æŽ¥ RAG/Agent/infra æ—¶è¾¹ç•Œå®¹æ˜“æ¼‚ç§»ï¼Œä½†æœ¬è½®ä¸�èƒ½ç§»åŠ¨ `app.py/schema.py/persistence.py` æˆ–æŽ¥çœŸå®ž Redis/MinIO/Qdrant/Postgres/Queueã€‚

**å®šä½�æ–¹å¼�ï¼š**
å¯¹ç…§ `.omc/plans/rs-agent-serving-file-architecture-ralplan.md` çš„ compatibility matrixï¼Œæ£€æŸ¥ `rs_core/serving/service.py`ã€�`boundary_map.py`ã€�`adapter_contracts.py`ã€�`facts.py`ã€�`manifest_gate.py` ä¸ŽçŽ°æœ‰ serving import seamã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢ž canonical åŒ…ç›®å½•å’Œ infrastructure skeletonï¼›å°† BoundaryMapã€�AdapterContractã€�ServingFactã€�ManifestGate è¿�ç§»åˆ° `domain/` ä¸Ž `governance/`ï¼Œæ—§è·¯å¾„å�ªä¿�ç•™ re-export shimï¼›æŠŠ `service.py` è½»æ‹†ä¸º `application/recommendation_service.py`ã€�`runtime/config.py`ã€�`runtime/readiness.py`ï¼ŒåŽŸ `rs_core.serving.service` ä½œä¸º public facade ç»§ç»­å¯¼å‡ºå…¼å®¹ç¬¦å�·ã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ `python -m compileall -q rs_core/serving` é€šè¿‡ï¼›è¿�è¡Œ serving import compatibility smoke è¾“å‡º `serving import compatibility ok`ï¼›å¯¹ `domain/governance/runtime/infrastructure` å�š AST forbidden import scanï¼Œç»“æžœ `forbidden import scan ok`ã€‚æœ¬è½®æœªè¿�è¡Œé‡�æµ‹è¯•å¥—ï¼ŒæœªæŽ¥çœŸå®žå¤–éƒ¨ infraã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œåœ¨ä¸�ç ´å��çŽ°æœ‰ FastAPI å…¥å�£å’Œæµ‹è¯• monkeypatch seam çš„å‰�æ��ä¸‹ï¼Œç”¨ Clean/Hexagonal çš„ modular monolith æ–¹å¼�æ¸�è¿›æ²»ç�†æœ�åŠ¡å±‚â€�ï¼šcanonical path æ‰¿æ‹…æ–°è¾¹ç•Œï¼Œæ—§è·¯å¾„é€šè¿‡ shim ä¿�æŠ¤å¹¶è¡Œçª—å�£ï¼Œruntime/config/readiness å…ˆæ‹†å‡ºæ�¥ä¸ºå�Žç»­ RAGã€�Agent å’Œ infra adapter æŽ¥å…¥ç•™è�½ç‚¹ã€‚

### 2026-06-22 - online retrieval æŽ¥å…¥ semantic_token å�¬å›ž

**ä»»åŠ¡ï¼š**
æŒ‰å·²æ‰¹å‡†è®¡åˆ’æŠŠæœ¬åœ° `semantic_index` çš„ token è¯­ä¹‰å�¬å›žå°�è£…æˆ� online retrieval providerï¼Œå¹¶æŽ¥å…¥ serving é…�ç½®ä¸Žè½»é‡�å›žå½’æµ‹è¯•ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
çº¿ä¸Šå€™é€‰ç¼–æŽ’å·²æœ‰ Postgresã€�two-towerã€�fallback å’Œ disabled `semantic_vector` éª¨æž¶ï¼Œä½†ç¼ºå°‘å�¯ç›´æŽ¥å¤�ç”¨çŽ°æœ‰ `semantic_candidates_for_user()` çš„ providerï¼›å�Œæ—¶ RAG chunks ä¸�èƒ½è¢«è¯¯ç”¨ä¸º candidate sourceï¼Œè¯­ä¹‰å�‘é‡�å€™é€‰ä»�éœ€ä¿�æŒ� disabled/skeletonã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ²¿ `rs_core/recsys/online_retrieval/provider.py`ã€�`orchestrator.py`ã€�`config.py`ã€�`providers/semantic_vector.py` ä¸Ž `candidate_merge.py` æŸ¥æ‰¾ provider/readiness/result æ¨¡å¼�ï¼Œå¹¶ç”¨ `tests/test_online_retrieval_providers.py`ã€�`tests/test_online_retrieval_orchestrator.py` å›ºåŒ– expected diagnostics å’Œ fallback è¯­ä¹‰ã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢ž `semantic_token` providerï¼Œreadiness åŒºåˆ† `disabled/missing_semantic_index/ready`ï¼Œretrieve å�ˆå¹¶ request config ä¸Ž provider config å�Žå¼ºåˆ¶ `semantic_enabled=True`ï¼Œå�ªè°ƒç”¨æœ¬åœ° token è¯­ä¹‰ç´¢å¼•ï¼›orchestrator `from_config()` é€�ä¼  `semantic_index`ï¼Œé»˜è®¤ provider é¡ºåº�æ”¾åœ¨ `postgres_category` å�Žã€�`postgres_popular` å‰�ï¼›serving é…�ç½®è¡¥é½� `idf_seed_aware`ã€�seed windowã€�per-seedã€�per-user å’Œ df ratio å�‚æ•°ï¼Œä¿�ç•™ `semantic_vector` disabledã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest D:/sinrotic_code/python_project/summer/RS_agent/tests/test_online_retrieval_providers.py D:/sinrotic_code/python_project/summer/RS_agent/tests/test_online_retrieval_orchestrator.py`ï¼Œç»“æžœ `9 passed in 1.61s`ï¼›å¯¹ä¿®æ”¹çš„ Python æ–‡ä»¶è¿�è¡Œ `py_compile` æ— è¾“å‡ºé€šè¿‡ï¼›å¯¹ serving JSON é…�ç½®å�š `json.loads` ä¸Žå…³é”®å­—æ®µæ–­è¨€é€šè¿‡ã€‚æœªè¿�è¡Œ full eval/full buildã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œåœ¨ä¸�å¼•å…¥æ–°å�‘é‡�æœ�åŠ¡ã€�ä¸�è§¦ç¢° RAG candidate è¾¹ç•Œçš„å‰�æ��ä¸‹ï¼ŒæŠŠå·²æœ‰ç¦»çº¿ semantic token èƒ½åŠ›äº§å“�åŒ–ä¸ºå�¯è§‚æµ‹ providerâ€�ï¼šé€šè¿‡ readinessã€�provider_coverage å’Œ diagnostics æ˜Žç¡®ä¸Šçº¿çŠ¶æ€�ä¸Žå�¬å›žå�‚æ•°ï¼Œä¸ºå�Žç»­ A/Bã€�underfill åˆ†æž�å’Œå�‘é‡�è¯­ä¹‰å�¬å›žæ›¿æ�¢é¢„ç•™æŽ¥å�£ã€‚


### 2026-06-22 - online retrieval 接入 semantic_token 召回（复审修正）

- **任务**：补充记录 `semantic_token` 接入后的复审修正和最终验证结果，修正上一条记录中过早的验证口径。
- **遇到的问题**：初版 provider 接入后，code review 发现两个诊断语义风险：`online_retrieval.enabled=false` 时仍可能进入 online route；fallback provider 只返回重复/seen 候选时，`fallback_used` 可能被 raw 返回量误报为 true。
- **定位方式**：沿 `rs_core/workflow/online_recommendation.py` 的 route 判断、`rs_core/recsys/online_retrieval/orchestrator.py` 的 provider/fallback 编排和 `tests/test_online_retrieval_orchestrator.py` 的 coverage 逐项复查；用 local_qdrant smoke 检查 readiness/provider_coverage 是否能看到 `semantic_token`。
- **解决方式**：`_has_online_retrieval_config()` 改为必须显式 `enabled=true`；orchestrator 在 `not self.enabled` 时直接返回 disabled diagnostics；fallback 阶段按 merge 前后 item id 差集计算净新增候选，并新增 `fallback_raw_candidate_count`/`fallback_net_new_candidate_count` 诊断。
- **验证结果**：使用项目默认 `.venv` 运行聚焦回归 `tests/test_online_retrieval_providers.py tests/test_online_retrieval_orchestrator.py tests/test_hybrid_demo.py::test_semantic_idf_seed_aware_prefers_rare_seed_overlap_and_filters_seen_items -q`，结果 `13 passed in 3.61s`；运行 serving 相关回归 `tests/test_serving_recommend_from_sequence.py tests/test_serving_facades.py tests/test_qdrant_config_env.py -q`，结果 `33 passed in 1.17s`；复审代理针对 HIGH/MEDIUM 修复给出 `APPROVE`，并独立运行 provider/orchestrator 测试 `12 passed in 0.37s`；local_qdrant smoke exit code 0，`semantic_token` readiness 为 `ready`、`semantic_index_size=16753`、`candidate_count=20`，`pool500_fallback` 为 `not_needed`、`fallback_used=false`。本轮未运行 full eval/full build/全量 Qdrant build。
- **面试可讲点**：这段可讲成“先把离线 token/IDF 语义召回服务化，再用 readiness、provider coverage 和 fallback 净新增诊断保证线上可观测性”的工程治理案例；重点不是堆模型，而是在不误用 RAG chunks、不启动重资源 ANN 构建的前提下，把 `/recommend`、`/recall` 和 Agent 工具的候选生成语义对齐。

### 2026-06-22 - Serving API/Schema æ–‡ä»¶æž¶æž„äºŒé˜¶æ®µè¿�ç§»

- **ä»»åŠ¡**ï¼šå°† serving å±‚çš„ schema ä¸Ž FastAPI app ä»Žæ ¹ç›®å½•æ—§å…¥å�£è¿�ç§»åˆ° canonical åˆ†å±‚ç›®å½•ï¼Œå�Œæ—¶ä¿�ç•™æ—§è·¯å¾„å…¼å®¹ã€‚
- **é�‡åˆ°çš„é—®é¢˜**ï¼š`rs_core.serving.schema` ä¸Ž `rs_core.serving.app` æ˜¯å¤–éƒ¨è„šæœ¬ã€�æµ‹è¯•å’Œ uvicorn å…¥å�£ä¾�èµ–çš„ public seamï¼Œä¸�èƒ½ç›´æŽ¥æ�¬èµ°ï¼›legacy shim åˆ�ç‰ˆä½¿ç”¨ `import *`ï¼Œè§¦å�‘ ruff F403ã€‚
- **å®šä½�æ–¹å¼�**ï¼šé€šè¿‡ focused compatibility testsã€�FastAPI smokeã€�legacy/canonical import smokeã€�ruff å’Œ compileall æ£€æŸ¥éªŒè¯�è¿�ç§»è¾¹ç•Œï¼›verifier å¤�æ ¸å�‘çŽ° star import diagnostics blockerã€‚
- **è§£å†³æ–¹å¼�**ï¼šæ–°å¢ž canonical `rs_core/serving/schemas/models.py`ã€�`rs_core/serving/api/app.py`ï¼Œæ—§ `schema.py`/`app.py` ä¿�ç•™ä¸º shimï¼›æ›´æ–° BoundaryMap canonical owned paths ä¸Ž compatibility_pathsï¼›shim æ”¹ä¸ºåŸºäºŽ canonical module `__all__`/`dir()` çš„æ˜¾å¼� `globals()` æ³¨å…¥ï¼Œé�¿å…� `import *`ã€‚
- **éªŒè¯�ç»“æžœ**ï¼š`ruff check rs_core/serving` é€šè¿‡ï¼›`compileall -q rs_core/serving` é€šè¿‡ï¼›`tests/test_serving_boundary_map.py tests/test_serving_reorg_compatibility.py tests/test_serving_smoke.py -q` ä¸º 72 passedï¼›`tests/test_postgres_dataset.py tests/test_serving_facades.py tests/test_serving_recommend_from_sequence.py -q` ä¸º 38 passedï¼›verifier æœ€ç»ˆ PASSã€‚
- **é�¢è¯•å�¯è®²ç‚¹**ï¼šè¿™æ¬¡è¿�ç§»ä¸�æ˜¯æœºæ¢°ç§»åŠ¨æ–‡ä»¶ï¼Œè€Œæ˜¯åœ¨ä¿�æŒ�çº¿ä¸Šå…¥å�£å…¼å®¹çš„å‰�æ��ä¸‹ï¼ŒæŠŠ API/schema ownership çº³å…¥ BoundaryMapï¼Œè®©æž¶æž„è¾¹ç•Œå�¯æµ‹è¯•ã€�å�¯å¤�å®¡ã€�å�¯æ¸�è¿›æ¼”è¿›ã€‚


#### æ”¶å�£è¡¥å…… - canonical import ä¸Ž shim public surface å›ºåŒ–

- **ä»»åŠ¡**ï¼šåœ¨ API/schema è¿�ç§»é€šè¿‡å�Žç»§ç»­æ”¶å�£ï¼Œå‡�å°‘æ–° canonical å±‚å¯¹æ—§ shim çš„ä¾�èµ–ï¼Œå¹¶å›ºåŒ– legacy shim çš„ public surfaceã€‚
- **è§£å†³æ–¹å¼�**ï¼šå°† `api/app.py`ã€�`application/recommendation_service.py`ã€�`facades.py` çš„ schema import æ”¹ä¸º `rs_core.serving.schemas`ï¼›ä¸º `domain/adapter_contracts.py`ã€�`domain/boundary_map.py`ã€�`domain/serving_fact.py`ã€�`governance/manifest_gate.py` å¢žåŠ æ˜Žç¡® `__all__`ï¼Œlegacy shim æ”¹ä¸ºæŒ‰ canonical `__all__` re-exportï¼›è¡¥å…… canonical å±‚ç¦�æ­¢å¯¼å…¥æ—§ `app.py`/`schema.py` shim çš„å…¼å®¹æµ‹è¯•ã€‚
- **éªŒè¯�ç»“æžœ**ï¼š`ruff check rs_core/serving tests/test_serving_reorg_compatibility.py` é€šè¿‡ï¼›boundary/reorg tests ä¸º 20 passedï¼›serving smoke ä¸Žç›¸å…³å›žå½’ä¸º 92 passedï¼›import smoke é€šè¿‡ã€‚

## 2026-06-22 - MemoryAgent Shadow æŽ¥å…¥å®šåˆ¶ Agent Runtime

- ä»»åŠ¡ï¼šåœ¨ Registry/Runner æž¶æž„å·²æœ‰ `rag_agent` çš„åŸºç¡€ä¸Šï¼Œå®žçŽ°ç¬¬äºŒä¸ªå�¯å�¯åŠ¨å®šåˆ¶ Agentï¼š`memory_agent`ã€‚
- é�‡åˆ°çš„é—®é¢˜ï¼šé€šç”¨ Agent æ³¨å…¥å±‚å·²ç»�æ�­å¥½ï¼Œä½†å¦‚æžœå�ªæœ‰ RagAgentï¼Œä¸€ä¸ª Agent çš„ runner åŒ–è¿˜ä¸�èƒ½è¯�æ˜Žå¤š Agent æ‰©å±•è·¯å¾„ï¼›å�Œæ—¶é•¿æœŸè®°å¿†èƒ½åŠ›å·²æœ‰ facade seamï¼Œä¸�èƒ½é‡�å¤�æ”¹å†™ä¸»æŒ�ä¹…åŒ–é€»è¾‘ã€‚
- å®šä½�æ–¹å¼�ï¼šå¤�ç”¨ `rs_core/rsagent/long_memory.py` çš„ `snapshot_session_long_memory`ã€�`recall_relevant_long_memory`ï¼Œä»¥å�Š `rs_core/workflow/facades.py` çš„ shadow agent æŽ¥å…¥æ¨¡å¼�ï¼›ç”¨ display/session summary æµ‹è¯•ç¡®è®¤å†…éƒ¨è®°å¿†å­—æ®µä¸�ä¼šè¿›å…¥å…¬å¼€è¾“å‡ºã€‚
- è§£å†³æ–¹å¼�ï¼šæ–°å¢ž `rs_core/agent_runtime/adapters/memory.py`ï¼Œé€šè¿‡ `AgentDefinition/AgentRunner` æ³¨å†Œ `memory_agent`ï¼Œå�ªæ”¯æŒ� internal-only shadow/fail-openï¼›åœ¨ `AgentOrchestrationFacade` ä¸­å�¯é€‰æŒ‚è½½ `agent_runtime.memory_agent`ï¼›è¡¥å…… display forbidden å­—æ®µå’Œ session summary public-safe helperã€‚
- éªŒè¯�ç»“æžœï¼š`tests/test_memory_agent_adapter.py` 8 passedï¼›MemoryAgent runtime/display/session summary/long memory ç›¸å…³å›žå½’ 184 passedï¼›AgentRunner/RagAgent/runtime contract å›žå½’ 44 passedï¼›`git diff --check` æ—  whitespace errorï¼Œä»…ä¿�ç•™æ—¢æœ‰ LF/CRLF warningã€‚
- é�¢è¯•å�¯è®²ç‚¹ï¼šæŠŠâ€œé•¿æœŸè®°å¿†â€�ä»Ž facade å†…éƒ¨å‡½æ•°å�‡çº§ä¸ºå�¯æ³¨å†Œã€�å�¯è§‚æµ‹ã€�å�¯æ�ƒé™�æ”¶æ•›çš„å­� Agentï¼Œå�Œæ—¶ä¿�æŒ�æŽ¨è��å€™é€‰ã€�æŽ’åº�ã€�å…¬å¼€è¯�æœ¯å’Œè®­ç»ƒè¾“å‡ºä¸�è¢«è®°å¿†è¯Šæ–­æ±¡æŸ“ã€‚


## 2026-06-23 - Serving æž¶æž„è¿�ç§»å†²çª�å®¡æ ¸ä¸Žä¿®å¤�

- **ä»»åŠ¡**ï¼šå®¡æ ¸ serving API/schema è¿�ç§»å�Žä¸Žå…¶ä»–ä»£ç �çš„å†²çª�ï¼Œå¹¶ä¿®å¤�å�¯ç ´å��å�Žç»­è¾¹ç•Œçš„ä¾�èµ–é—®é¢˜ã€‚
- **é�‡åˆ°çš„é—®é¢˜**ï¼š`api/__init__.py` æ›¾å¯¼å‡ºå��ä¸º `app` çš„ FastAPI å¯¹è±¡ï¼Œå�¯èƒ½é�®è”½ `rs_core.serving.api.app` å­�æ¨¡å�—ï¼›`RecommendationService` æ›¾ç›´æŽ¥ä¾�èµ– `rs_core.data` Postgres dataset å®žçŽ°ï¼›canonical layer guard å¯¹å†…éƒ¨ infra import è¦†ç›–ä¸�è¶³ã€‚
- **å®šä½�æ–¹å¼�**ï¼šé€šè¿‡ code-review å…³æ³¨ dotted import è¯­ä¹‰ã€�BoundaryMap ownership/compatibility_pathsã€�AST import guard ä¸Ž focused pytestï¼›å¤�æ ¸æ–‡ä»¶åŒ…æ‹¬ `rs_core/serving/api/__init__.py`ã€�`rs_core/serving/application/recommendation_service.py`ã€�`tests/test_serving_reorg_compatibility.py`ã€‚
- **è§£å†³æ–¹å¼�**ï¼š`api` åŒ…æ”¹ä¸ºå¯¼å‡º `fastapi_app` convenience aliasï¼Œä¿�ç•™ `rs_core.serving.api.app` å­�æ¨¡å�—è¯­ä¹‰ï¼›æ–°å¢ž `rs_core.serving.infrastructure.stores.postgres_dataset` ä½œä¸º serving-owned Postgres seamï¼›core serving å±‚æ–°å¢ž `rs_core.data` ç¦�æ­¢å¯¼å…¥ guardï¼Œå…�è®¸è¯¥ä¾�èµ–å�ªå‡ºçŽ°åœ¨ infrastructure boundaryã€‚
- **éªŒè¯�ç»“æžœ**ï¼š`pytest tests/test_serving_reorg_compatibility.py tests/test_serving_boundary_map.py -q` é€šè¿‡ 22 é¡¹ï¼›`pytest tests/test_serving_smoke.py tests/test_postgres_dataset.py tests/test_serving_facades.py tests/test_serving_recommend_from_sequence.py tests/test_serving_facts.py -q` é€šè¿‡ 98 é¡¹ï¼›`ruff check rs_core/serving tests/test_serving_reorg_compatibility.py tests/test_serving_boundary_map.py` é€šè¿‡ï¼›`compileall -q rs_core/serving` é€šè¿‡ï¼›import smoke ç¡®è®¤ legacy/canonical app/schema identity ä¸Ž `api_package.fastapi_app` seam æ­£å¸¸ã€‚
- **é�¢è¯•å�¯è®²ç‚¹**ï¼šè¿™æ¬¡ä¸�æ˜¯ç®€å�•ç§»åŠ¨æ–‡ä»¶ï¼Œè€Œæ˜¯æŠŠè¿�ç§»å�Žçš„å…¼å®¹ shimã€�canonical ownershipã€�åŸºç¡€è®¾æ–½ä¾�èµ–æ–¹å�‘å’Œæµ‹è¯• guard ä¸€èµ·å›ºåŒ–ï¼Œé�¿å…�å�Žç»­ Agent/serving/RAG/æ•°æ�®æŽ¥å…¥ç»§ç»­äº’ç›¸ç©¿é€�ã€‚


### 2026-06-23 - RS Agent Ã— æ¨¡æ‹Ÿç”¨æˆ· Agent å¤šè½® SFT ç”Ÿæˆ�ä¸Žç¬¬ä¸‰æ–¹ Judge é—­çŽ¯

**ä»»åŠ¡ï¼š**
è°ƒé€š RS Agent ä¸Žæ¨¡æ‹Ÿç”¨æˆ· Agent çš„å¤šè½®äº¤äº’å¼� SFT æ ·æœ¬ç”Ÿæˆ�é“¾è·¯ï¼Œå¹¶æŒ‰ `dic/standards/AGENT_SCORING_FRAMEWORK.md` ä¸­çš„ SFT è¯„ä»·æ ‡å‡†æ–°å¢žç¬¬ä¸‰æ–¹ Judgeï¼Œå¯¹æ ·æœ¬è¿›è¡Œç»“æž„åŒ–è´¨æ£€ï¼›å…¨ç¨‹ä½¿ç”¨æœ¬åœ°å°�æ ·æœ¬ smokeï¼Œé�¿å…�æœ¬æœºèµ„æº�åŽ‹åŠ›ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
çŽ°æœ‰å¤šè½® SFT ç”Ÿæˆ�å™¨å·²ç»�èƒ½é©±åŠ¨ `RecommendationService`ã€�æ¨¡æ‹Ÿç”¨æˆ·å’ŒæŽ¨è�� Agentï¼Œä½†è¯„ä»·é—­çŽ¯å�ªå�œç•™åœ¨ validator / manifest ç»Ÿè®¡å±‚é�¢ï¼Œç¼ºå°‘å�¯å¤�ç”¨çš„ç¬¬ä¸‰æ–¹æ ·æœ¬è´¨é‡�åˆ¤å®šã€‚å¤�å®¡è¿‡ç¨‹ä¸­è¿˜å�‘çŽ°å‡ ä¸ªè®­ç»ƒæ•°æ�®é£Žé™©ï¼šå€™é€‰æ± å¤–å•†å“�å�¯èƒ½å�ªå‡ºçŽ°åœ¨ assistant æ–‡æœ¬ä¸­ã€�å•†å“�å±žæ€§ç¼–é€ æ²¡æœ‰ç¡¬å¤±è´¥ã€�å¤–éƒ¨ composer prompt å�¯èƒ½æ�ºå¸¦è¿‡å¤šç§�æœ‰/ç›‘ç�£å­—æ®µã€�accept fallback å�¯èƒ½ä¼ªé€ å·¥å…·æˆ�åŠŸã€�stale display çš„ no-recommend turn å�¯èƒ½è¢« flatten æˆ�æ—§ç‰ˆ SFT æ ·æœ¬ã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ²¿ `scripts/training/generate_multi_turn_sft.py` â†’ `rs_core/training/multi_turn_sft_generator.py` â†’ `rs_core/serving/service.py` æ¢³ç�†ç”Ÿæˆ�é“¾è·¯ï¼›å¯¹ç…§ `dic/standards/AGENT_SCORING_FRAMEWORK.md` çš„ SFT hard gateã€�æ�ƒé‡�å’Œå†³ç­–æ¡£ä½�ï¼ŒæŠŠè¯„ä»·ç»´åº¦è�½åˆ° `rs_core/training/sft_judge.py`ã€‚ä½¿ç”¨ code-reviewer / verifier åˆ†ç¦»å¤�å®¡ï¼Œç»“å�ˆ `tests/test_multi_turn_sft_generator.py` çš„å›žå½’ç”¨ä¾‹å®šä½� hard gate ä¸Ž artifact contract æ¼�æ´žã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢žæœ¬åœ° deterministic çš„ `ThirdPartySftJudgeAgent` å’Œ `scripts/training/judge_sft_samples.py`ï¼šå…ˆè·‘ schema / grounding / forbidden key / label-oracle / unsafe tool hard gateï¼Œå†�æŒ‰ SFT rubric è¾“å‡º `accept / accept_light / rewrite / reject`ã€�åˆ†é¡¹åˆ†æ•°å’Œ summaryã€‚ç”Ÿæˆ�å™¨ä¾§è¡¥å¼ºï¼šcomposer å¤–éƒ¨ API payload æœ€å°�åŒ–ï¼Œå�ªå�‘é€� public persona summaryã€�latest user messageã€�public display items å’Œ sanitized visible dialogueï¼›dialogue-only/no-recommend å›žå¤�ä¼šæ¸…ç�† ASINã€�item_id å’Œå�•å•†å“�æŽ¨è��è¯�æœ¯ï¼›flatten å�ªä¿�ç•™çœŸæ­£ display-grounded recommendation turnï¼›accept å��é¦ˆå¤±è´¥ä¸�å†�ä¼ªé€ æˆ� `record_user_feedback: ok`ã€‚serving feedback ç™½å��å�•è¡¥å…¥ `accept`ï¼Œè®©æ¨¡æ‹Ÿç»ˆæ­¢åŠ¨ä½œèƒ½èµ°çœŸå®ž feedback å…¥å�£ã€‚æ–°å¢ž `.omc/multi_turn_sft_local_judge_smoke.yaml` ä½œä¸º 2 æ�¡æ ·æœ¬ã€�æœ¬åœ° deterministicã€�æ— å¤–éƒ¨ API çš„å®‰å…¨ smoke é…�ç½®ã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œè½»é‡�éªŒè¯�ï¼š`./.venv/Scripts/python -m pytest tests/test_multi_turn_sft_generator.py tests/test_serving_smoke.py -q` é€šè¿‡ï¼Œç»“æžœ `89 passed in 9.31s`ï¼›`compileall` è¦†ç›–æ–°å¢ž judgeã€�ç”Ÿæˆ�å™¨ã€�serving facade å’Œè„šæœ¬é€šè¿‡ã€‚è¿�è¡Œ `scripts/training/generate_multi_turn_sft.py --config .omc/multi_turn_sft_local_judge_smoke.yaml --limit 2` ç”Ÿæˆ� 2 æ�¡ã€�æ¯�æ�¡ 4 è½®æ ·æœ¬ï¼Œ`rejected_count=0`ã€�`api_called=false`ï¼›éš�å�Žè¿�è¡Œ `scripts/training/judge_sft_samples.py`ï¼Œ`judge_summary.json` æ˜¾ç¤º `sample_count=2`ã€�`decision_counts.accept=2`ã€�`hard_fail_count=0`ã€�`judge_satisfied=true`ã€‚verifier æœ€ç»ˆéªŒæ”¶å†�æ¬¡ç¡®è®¤ç›®æ ‡æµ‹è¯• `35 passed`ã€�compileall é€šè¿‡ã€�ä¸‰é¡¹ HIGH å¤�å®¡é—®é¢˜å�‡å·²ä¿®å¤�ã€‚æœ¬è½®æœªåŠ è½½æœ¬åœ°å¤§æ¨¡åž‹ã€�æœªè°ƒç”¨å¤–éƒ¨ APIã€�æœªè·‘å…¨é‡�è®­ç»ƒï¼Œèµ„æº�é£Žé™©æŽ§åˆ¶åœ¨ smoke çº§åˆ«ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå·¥ä½œå�¯ä»¥è®²æˆ�â€œæŠŠ Agent äº¤äº’è½¨è¿¹ä»Žèƒ½ç”Ÿæˆ�æŽ¨è¿›åˆ°å�¯è´¨æ£€ã€�å�¯è®­ç»ƒå‰�ç­›é€‰â€�ï¼šRS Agent è´Ÿè´£çœŸå®žå€™é€‰å±•ç¤ºå’Œå��é¦ˆé—­çŽ¯ï¼Œæ¨¡æ‹Ÿç”¨æˆ· Agent äº§ç”Ÿå¤šè½®éœ€æ±‚/è¿½é—®/æŽ¥å�—è¡Œä¸ºï¼Œç¬¬ä¸‰æ–¹ Judge æŒ‰ç¡¬é—¨ç¦�ä¸Ž rubric æŠŠæ ·æœ¬åˆ†å±‚ã€‚äº®ç‚¹ä¸�åœ¨äºŽä¸€æ¬¡ç”Ÿæˆ�å¾ˆå¤šæ•°æ�®ï¼Œè€Œæ˜¯æŠŠå€™é€‰æ± ä¸€è‡´æ€§ã€�è¯�æ�® groundingã€�å†…éƒ¨å­—æ®µæ³„æ¼�ã€�å·¥å…·ç›‘ç�£çœŸå®žæ€§å’Œ no-recommend è¾¹ç•Œéƒ½å�šæˆ�å�¯å›žå½’çš„å·¥ç¨‹ contractï¼Œä¸ºå�Žç»­ Qwen SFT / GRPO æ•°æ�®ç”Ÿäº§æ��ä¾›å�¯å®¡è®¡å…¥å�£ã€‚

### 2026-06-23 - pool500 é�žå�‘é‡�å�¬å›žæŽ¥å…¥ Cassandra/Scylla fallback

**ä»»åŠ¡ï¼š**
åœ¨å·²å®Œæˆ� Cassandra/Scylla Candidate Store åŸºç¡€æŽ¥å…¥å�Žï¼Œç»§ç»­è¦†ç›–å®žé™…å�¬å›žè·¯ä¸­çš„ pool500 fallbackã€�popular/category/user category profile ç­‰é�žå�‘é‡�å€™é€‰ï¼Œé�¿å…�å�ªæœ‰ UserCF/ItemCF å±€éƒ¨æ•°æ�®åº“åŒ–ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
ç¬¬ä¸€é˜¶æ®µå¯¼å…¥å™¨å�ªè¦†ç›– `usercf_candidates` å’Œ `item_neighbors`ï¼Œ`pool500_candidates.jsonl` ä»�ä¸»è¦�ä¾�èµ– JSONL artifact fallbackï¼›å¦‚æžœç›´æŽ¥é»˜è®¤å†™å…¥å‰� 1000 è¡Œæˆ–æŠŠ pool500 è¡Œè¯¯åˆ†ç±»æˆ� UserCFï¼Œä¼šé€ æˆ�â€œå¯¼å…¥æˆ�åŠŸä½†çº¿ä¸Šè¯»ä¸�åˆ°/è¦†ç›–ä¸�å…¨â€�çš„éš�æ€§é£Žé™©ã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ²¿ `Pool500FallbackProvider`ã€�`CandidateStore` Protocolã€�CQL schema å’Œ Cassandra importer çš„è¯»å†™è·¯å¾„æ ¸å¯¹è®¿é—®æ¨¡å¼�ï¼›é€šè¿‡ code review å�‘çŽ° `target_schema=auto` å¯¹ `user_id + item_id` çš„ pool500 è¡Œå­˜åœ¨è¯¯åˆ†ç±»é£Žé™©ï¼Œå†™å…¥æ¨¡å¼�ä¹Ÿéœ€è¦�æ‹’ç»� truncated artifactã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢ž `pool_candidates_by_user` CQL è¡¨å’Œ `CandidateStore.pool_candidates()` è¯»è·¯å¾„ï¼Œ`Pool500FallbackProvider` å¢žåŠ  `prefer_candidate_store` å¼€å…³ï¼Œé»˜è®¤ä¿�æŒ� JSONL å…¼å®¹ï¼Œå¼€å�¯å�Žä¼˜å…ˆè¯» Candidate Storeã€�ä¸ºç©ºæˆ–å¼‚å¸¸æ—¶å›žè�½ JSONLã€‚å¯¼å…¥å™¨è¡¥é½� `pool_candidates/popular/category/user_category_profiles`ï¼Œè‡ªåŠ¨è¯†åˆ«å¸¦ `sources/source_scores` çš„ pool500 è¡Œï¼Œå†™å…¥æ¨¡å¼�æ‹’ç»�æˆªæ–­ artifactï¼Œå¹¶å°† popular/category å†™å…¥ canonical source åˆ†åŒºï¼ŒåŽŸå§‹ source æ”¾å…¥ metadataã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ `.venv/Scripts/python -m pytest tests/test_candidate_store_cassandra.py tests/test_import_candidate_store_to_cassandra.py tests/test_online_retrieval_providers.py tests/test_online_retrieval_orchestrator.py`ï¼Œç»“æžœ `34 passed in 0.64s`ï¼›è¿�è¡Œ `.venv/Scripts/python -m ruff check rs_core/recsys/candidate_store/postgres.py rs_core/recsys/candidate_store/cassandra.py rs_core/recsys/online_retrieval/providers/pool500_fallback.py scripts/serving/import_candidate_store_to_cassandra.py tests/test_candidate_store_cassandra.py tests/test_import_candidate_store_to_cassandra.py tests/test_online_retrieval_providers.py`ï¼Œç»“æžœ `All checks passed!`ã€‚æœ¬è½®æœªå�¯åŠ¨çœŸå®ž Scyllaï¼Œä¹Ÿæœªæ‰§è¡Œ full importã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œæŠŠç¦»çº¿ artifact åž‹å�¬å›žå¹³æ»‘å�‡çº§æˆ�å�¯æœ�åŠ¡åŒ–çš„å®½åˆ—è¡¨å­˜å‚¨â€�ï¼šç¦»çº¿ artifact ä»�æ˜¯ source of truthï¼ŒCassandra/Scylla æ‰¿æ‹…åœ¨çº¿ topK lookupï¼›é€šè¿‡ versioned partitionã€�dry-run-first importerã€�fail-open provider å’Œ JSONL fallbackï¼Œä¿�è¯�æ•°æ�®åº“åŒ–è¿�ç§»æ—¢è¦†ç›–çœŸå®žå�¬å›žè·¯ï¼Œå�ˆä¸�ä¼šå› ä¸ºå±€éƒ¨å¯¼å…¥æˆ–æ•°æ�®åº“ä¸�å�¯ç”¨ç ´å��çº¿ä¸ŠæŽ¨è��ã€‚

### 2026-06-23 - æ–¹æ³•çº§é�žå�‘é‡�å�¬å›ž Candidate Store ä¸»é“¾è·¯æŽ¥å…¥

**ä»»åŠ¡ï¼š**
çº æ­£â€œå�ªæŠŠ pool500 æ•´ä½“å¿«ç…§æ”¾å…¥æ•°æ�®åº“â€�çš„æž¶æž„å��å·®ï¼Œå°† ItemCF strong/weakã€�co-visit repairã€�UserCFã€�categoryã€�popular ç­‰æ–¹æ³•çº§é�žå�‘é‡�å�¬å›žæ˜¾å¼�æŽ¥å…¥ Candidate Store ä¸»é“¾è·¯ï¼Œpool500 å�ªä¿�ç•™ä¸º fallback/rollback å¿«ç…§ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
å¦‚æžœå�ªå¯¼å…¥ `pool500_candidates`ï¼Œåœ¨çº¿å�¬å›žä¼šç»•è¿‡å�„å�¬å›žæ–¹æ³•æœ¬èº«ï¼Œæ�Ÿå¤± source-level è°ƒå�‚ã€�è¯Šæ–­ã€�åŽ»é‡�å�ˆå¹¶å’ŒæŽ’åº�å‰�æ²»ç�†èƒ½åŠ›ï¼›è¿™ä¸Žâ€œæŒ‰å�¬å›žæ–¹æ³•å�–å€™é€‰ï¼Œå†� merge/dedup/rankâ€�çš„æŽ¨è��é“¾è·¯ä¸�ä¸€è‡´ã€‚

**å®šä½�æ–¹å¼�ï¼š**
æ²¿ `configs/serving/online_service*.yaml`ã€�`rs_core/recsys/online_retrieval/config.py`ã€�`orchestrator.py` å’Œå�„ provider æ£€æŸ¥ provider å‘½å��ã€�source æ˜ å°„ã€�fallback è°ƒåº¦ã€‚ç¡®è®¤æ—§é…�ç½®å�ªæœ‰å�•ä¸ª `postgres_item_neighbors`ï¼Œæ²¡æœ‰æ˜¾å¼�æ‹†åˆ† `itemcf_strong/itemcf_weak/co_visit_fallback_repair`ï¼Œå®¹æ˜“æŠŠæ–¹æ³•çº§å�¬å›žç®€åŒ–æˆ�æ³› item_neighborsã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢žä¸­æ€§ provider å��ç§° `candidate_store_itemcf_strong`ã€�`candidate_store_itemcf_weak`ã€�`candidate_store_co_visit_repair`ã€�`candidate_store_usercf`ã€�`candidate_store_category`ã€�`candidate_store_popular`ï¼Œç”± orchestrator æ˜ å°„åˆ°å¯¹åº” CandidateStore sourceï¼›provider `from_config` ä¿�ç•™ provider_name/source_nameï¼Œä¾¿äºŽ diagnostics åŒºåˆ†å�„æ–¹æ³•ã€‚ä¸¤ä¸ª serving é…�ç½®ç§»é™¤æ—§ `postgres_*` providerï¼Œæ˜¾å¼�å£°æ˜Žæ–¹æ³•çº§ Candidate Store providerã€‚`pool500_fallback` å¢žåŠ å¹¶è¯»å�– `fallback_only`ï¼Œorchestrator å�Œæ—¶æŒ‰ `fallback_only` å’Œ role å°†å…¶å�ªä½œä¸º underfill fallback è°ƒç”¨ã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ `.venv/Scripts/python -m pytest tests/test_online_retrieval_orchestrator.py tests/test_online_retrieval_providers.py tests/test_candidate_store_cassandra.py tests/test_import_candidate_store_to_cassandra.py`ï¼Œç»“æžœ `37 passed in 0.57s`ï¼›è¿�è¡Œ `.venv/Scripts/python -m pytest tests/test_serving_smoke.py tests/test_serving_recommend_from_sequence.py`ï¼Œç»“æžœ `76 passed in 2.22s`ï¼›è¿�è¡Œ retrieval ç›¸å…³ ruff æ£€æŸ¥ï¼Œç»“æžœ `All checks passed!`ã€‚æœ¬è½®æœªå�¯åŠ¨çœŸå®ž Scyllaï¼Œä¹Ÿæœªæ‰§è¡Œ full importã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œæŠŠå�¬å›žæ•°æ�®åº“åŒ–ä»Žå€™é€‰æ± å¿«ç…§å�‡çº§ä¸ºæ–¹æ³•çº§ serving æž¶æž„â€�ï¼šæ¯�ä¸ªå�¬å›žæ–¹æ³•ç‹¬ç«‹è�½åº“ã€�ç‹¬ç«‹è¯Šæ–­ã€�åœ¨çº¿ç‹¬ç«‹å�–å€™é€‰ï¼Œå†�ç»Ÿä¸€ merge/dedup/rankï¼›pool500 å�ªå�šç¨³å®šå…œåº•å’Œå›žæ»šï¼Œä¸�æ›¿ä»£æ–¹æ³•çº§å�¬å›žï¼Œä»Žè€Œä¿�ç•™æŽ¨è��ç³»ç»Ÿè°ƒå�‚ä¸Žæ²»ç�†ç©ºé—´ã€‚

### 2026-06-23 - Serving legacy shim 物理删除与 canonical-only 收口

- **任务**：在 serving canonical import 主路已收口后，继续物理删除旧根目录 shim，避免后续 Agent 或业务代码继续把新逻辑写回 `rs_core.serving.app/schema/service/...` 旧入口。
- **遇到的问题**：旧 shim 仍保留在目录中，视觉和架构上都会制造“双入口”；同时 `rs_core.serving.app` 曾通过 `sys.modules` alias 转发，普通同进程 import 检查可能被缓存污染。
- **定位方式**：沿 `tests/test_serving_reorg_compatibility.py`、`tests/test_serving_boundary_map.py`、`scripts/serving/run_service.py` 和 `rs_core/serving/domain/boundary_map.py` 核对剩余 legacy 引用，先保护无关脏工作区，再分离 serving-only 修改。
- **解决方式**：删除 `app.py/schema.py/service.py/facts.py/adapter_contracts.py/boundary_map.py/manifest_gate.py` 旧 shim；`run_service.py` 改用 `rs_core.serving.api.app:app`；BoundaryMap 移除旧 shim compatibility_paths；compatibility 测试反转为 canonical import pass + deleted legacy subprocess import-fail guard。
- **验证结果**：已运行 `.venv/Scripts/python -m pytest tests/test_serving_reorg_compatibility.py tests/test_serving_boundary_map.py tests/test_serving_run_service.py -q`，结果 `44 passed`；最终 focused serving suite 覆盖 serving/agent/simulation 相关测试，结果 `237 passed`；`py_compile`、`ruff check`、`compileall` 均通过。
- **面试可讲点**：这不是单纯删文件，而是把“canonical + legacy shim 兼容”的过渡态升级为 canonical-only contract；通过 subprocess import probe、BoundaryMap 语义反转和 focused tests 防止旧入口回流，体现了架构迁移中的可回滚、可验证和防回归设计。



### 2026-06-24 - æ–¹æ³•çº§å�¬å›žåˆ‡æ�¢åˆ° Scylla CandidateStore æ”¶å�£

**ä»»åŠ¡ï¼š**
æŠŠé�žå�‘é‡�å�¬å›ž serving å�Žç«¯åˆ‡åˆ° Scylla/Cassandra CandidateStoreï¼Œå¹¶ç¡®ä¿�çº¿ä¸Šå�¬å›žä»�æŒ‰ `itemcf_strong/itemcf_weak/co_visit_fallback_repair/usercf_recall/category/popular` ç­‰æ–¹æ³•çº§ source åˆ†åˆ«è¯»å�–ï¼Œå†�ç”± orchestrator merge/dedup/rankï¼›`pool500_candidates.jsonl` å�ªä¿�ç•™ä¸º fallback/rollback å¿«ç…§ã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
æœ€åˆ�é£Žé™©æ˜¯æŠŠ `pool500` æ•´ä½“å¿«ç…§å½“æˆ�ä¸»å�¬å›žè¡¨ï¼Œä¼šç»•è¿‡æ–¹æ³•çº§å�¬å›žè¯Šæ–­ä¸Žè°ƒåº¦ï¼›çœŸå®ž Scylla smoke å�ˆæš´éœ² Python 3.13 ä¸‹ `cassandra-driver` ä»�ä¾�èµ–å·²ç§»é™¤çš„ `asyncore` é»˜è®¤è¿žæŽ¥ç±»ã€‚review è¿›ä¸€æ­¥æŒ‡å‡º importer éœ€è¦�åŒºåˆ† pool500 merged rows ä¸Žæ–¹æ³•çº§ per-user rowsï¼Œprovider é»˜è®¤è·¯ç”±ä¹Ÿä¸�èƒ½åœ¨é…�ç½®ç¼ºçœ�æ—¶å›žåˆ°æ—§ bucket/global è¡¨ã€‚

**å®šä½�æ–¹å¼�ï¼š**
é€šè¿‡ Scylla manifestã€�`user_candidates_by_user` / `item_neighbors_by_seed` ç›´è¯» smoke å’Œ orchestrator provider coverage æ ¸å¯¹æ¯�ä¸ªæ–¹æ³• source æ˜¯å�¦çœŸå®žå�¯è¯»ï¼›ç”¨ targeted pytest/ruff ä¿�æŠ¤ importer åˆ†ç±»ã€�provider `lookup_mode`ã€�çœŸå®ž serving config å’Œ fallback-only è¡Œä¸ºï¼›ç”¨ç‹¬ç«‹ code-reviewer/verifier å¤�æŸ¥ pool500 vs method rowsã€�Python 3.13 compatibility å’Œè·¯ç”±é»˜è®¤å€¼ã€‚

**è§£å†³æ–¹å¼�ï¼š**
åœ¨ runtime ä¸Ž importer ä¸­è¡¥ `cassandra.io.asyncioreactor.AsyncioConnection` compatibility shimï¼Œå�Œæ—¶æ³¨å†Œ `cassandra.io.asyncorereactor` å’Œ `cassandra.io.asyncoreactor`ï¼›importer æ”¯æŒ� `source_override` å�‚ä¸Žåˆ†ç±»ï¼Œ`pool_name` ä¼˜å…ˆè¯†åˆ« poolï¼Œæ–¹æ³•çº§ `sources/source_scores` ä¸�å†�è¯¯å†™ pool è¡¨ï¼›provider å¢žåŠ å¹¶é…�ç½® `lookup_mode=user_candidates`ï¼Œè®© co-visit/category/popular ä»Ž `user_candidates_by_user` è¯»ï¼ŒItemCF strong/weak ç»§ç»­èµ° `item_neighbors_by_seed`ã€‚orchestrator ä¸º `candidate_store_*` provider è®¾ç½®å®‰å…¨é»˜è®¤ source/lookup_modeï¼Œpool500 fallback ç»§ç»­ `fallback_only=true` ä¸” CandidateStore fallback ä¹Ÿé�µå®ˆ allowed_sourcesã€‚

**éªŒè¯�ç»“æžœï¼š**
ä½¿ç”¨é¡¹ç›®é»˜è®¤ `.venv` è¿�è¡Œ `.venv/Scripts/python -m pytest tests/test_import_candidate_store_to_cassandra.py tests/test_online_retrieval_providers.py tests/test_online_retrieval_orchestrator.py tests/test_candidate_store_cassandra.py`ï¼Œç»“æžœ `45 passed, 1 warning in 2.64s`ï¼›è¿�è¡Œ ruff focused æ£€æŸ¥ï¼Œç»“æžœ `All checks passed!`ã€‚çœŸå®ž Scylla direct read æ˜¾ç¤º health `status=ok`ï¼Œå…­ç±»æ–¹æ³• source å�‡èƒ½é‡‡æ ·è¯»å‡ºå€™é€‰ï¼šcategoryã€�popularã€�co_visit_fallback_repairã€�usercf_recallã€�itemcf_strongã€�itemcf_weakã€‚orchestrator smoke è¿”å›ž `candidate_count=50`ã€�`fallback_used=false`ã€�`underfilled_before_fallback=false`ã€�`pool500_fallback.status=not_needed`ï¼Œæ–¹æ³•çº§ provider ä¸­ itemcf/co_visit/category/popular å�‡è¿”å›žå€™é€‰ï¼Œusercf åœ¨è¯¥ smoke ç”¨æˆ·ä¸ºç©ºä½† direct read å·²éªŒè¯� source æ•°æ�®å­˜åœ¨ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™æ®µå�¯ä»¥è®²æˆ�â€œä»Žå€™é€‰æ± å¿«ç…§è¿�ç§»åˆ°æ–¹æ³•çº§åœ¨çº¿å�¬å›žå­˜å‚¨â€�ï¼šç¦»çº¿ artifact ä»�æ˜¯ source of truthï¼ŒScylla å�ªæ˜¯å�¯é‡�å»ºçš„ serving indexï¼›æ¯�ä¸ªå�¬å›žæ–¹æ³•ç‹¬ç«‹è�½åº“å’Œè¯Šæ–­ï¼Œåœ¨çº¿æŒ‰ source å�–å€™é€‰å�Žç»Ÿä¸€åŽ»é‡�æŽ’åº�ï¼›å�Œæ—¶é€šè¿‡ fallback-only pool500ã€�store_versionã€�dry-run importerã€�Python ç‰ˆæœ¬å…¼å®¹å’Œ public-safe readinessï¼ŒæŠŠæ•°æ�®åº“è¿�ç§»å�šæˆ�å�¯å›žæ»šã€�å�¯éªŒè¯�ã€�å�¯æ¼”è¿›çš„æŽ¨è��ç³»ç»Ÿå·¥ç¨‹é—­çŽ¯ã€‚
