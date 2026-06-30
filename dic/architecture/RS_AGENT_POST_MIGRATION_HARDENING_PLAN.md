# RS Agent 架构迁移后硬化与退役计划

## 1. 文档目标

本文档承接已完成的 `RS_AGENT_ARCHITECTURE_MIGRATION_PLAN.md`，用于规划迁移完成后的进一步硬化、真实收束和旧路径退役。

当前阶段已经完成的是：五模块服务化 canonical 入口、services 接入层、deploy/Nginx、本地 gateway smoke、测试分层、兼容层 owner 和验证证据。后续阶段不再重新判定“架构迁移是否完成”，而是在已完成基线上继续收紧以下问题：

- 旧目录仍作为存量实现来源，需要逐步退役或降级为纯兼容 facade。
- `rs_core/online`、`rs_core/agent`、`rs_core/data`、`rs_core/offline` 已有 canonical 入口，但部分真实实现仍通过 facade 承接旧模块。
- Docker/Nginx 已完成本地 smoke，但 CI、schema snapshot、gateway smoke 自动化和 infra profile 验证还需要增强。
- 数据基础设施 adapter 已有 contract 形态，后续需要增强真实 disabled/dry-run/readiness/secret-safe 能力。
- 前端 API client 已收敛到 `/api`，后续需要稳定 public schema、类型同步和前后端 contract drift 检测。

> 勾选标准：每个勾选项代表“代码边界、入口、测试、smoke、文档或 grep/import 证据已经完成并验证”，不是只代表创建文件或写下计划。
>
> 本计划保持与 `RS_AGENT_ARCHITECTURE_MIGRATION_PLAN.md` 一致的 Phase + checklist + 完成标准格式。
>
> 本计划的完成口径限定为“canonical 入口真实化、兼容层退役准备、旧实现物理迁移和工程硬化”，不推翻上一轮已经完成的架构迁移结论。

---

## 2. 当前完成基线

本计划开始前，已完成并作为冻结基线的事实如下：

- [x] 复核 `RS_AGENT_ARCHITECTURE_MIGRATION_PLAN.md` 保持无未勾选项。
- [x] 复核 `RS_AGENT_MIGRATION_VALIDATION_EVIDENCE.md` 中记录的迁移套件、ruff、frontend build、Docker gateway smoke 仍可复现。
- [x] 复核 `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md` 覆盖所有仍保留的旧目录。
- [x] 复核 `tests/data|online|agent|services|contracts` 分层路径仍存在且可运行。
- [x] 复核 `rs_core.serving.api.online_app`、`rs_core.serving.api.agent_app`、`rs_core.data.runtime.worker`、`rs_core.offline.runtime.worker` 仍是服务入口层。
- [x] 复核 `deploy/docker-compose.yml` 和 `deploy/nginx/nginx.conf` 仍能支持 local gateway smoke。

### 当前不重新解决的问题

- [x] 不重新争论 RAG 是否归 online：RAG 继续归 `rs_core/agent`，底层知识库和向量库访问经 `rs_core/data`。
- [x] 不重新争论 services 是否放业务逻辑：services 继续只作为 HTTP / worker 接入层。
- [x] 不重新把 `old_dic/` 纳入规划依据：`old_dic/` 继续作为历史草稿。
- [x] 不默认删除旧目录：删除必须等待 import 清零、parity tests 和 smoke 通过。
- [x] 不默认启动重 infra、重训练或全量评估：本机仍按 12GB 可承受、14GB 上限控制。

---

## 3. 总体验收口径

本计划全部完成后，应满足：

- [ ] 新代码只通过 `rs_core/data`、`rs_core/online`、`rs_core/agent`、`rs_core/offline`、`rs_core.serving.api.online_app`、`rs_core.serving.api.agent_app`、`rs_core.data.runtime.worker` 和 `rs_core.offline.runtime.worker` canonical 入口开发。
- [ ] `rs_core/recsys`、`rs_core/rsagent`、`rs_core/workflow`、`rs_core/training`、`rs_core/evaluation`、`rs_core/dataproc` 等旧目录不再作为新增业务主入口。
- [ ] 每个旧目录都有退役等级、替代入口、import 清零条件和验证命令。
- [x] Online 推荐链路的 recall、ranking、COLD→DeepFM 由 `rs_core/online` public contract 承接。
- [ ] Agent/RAG 链路的 dialogue、planner、RAG、explanation、feedback、memory、simulation 由 `rs_core/agent` public contract 承接。
- [ ] Data/Infra 的 PostgreSQL、Redis、MinIO、Qdrant、local file 访问由 `rs_core/data` adapter/client 统一管理。
- [ ] Offline 的 training、evaluation、experiments、simulation 输出统一由 `rs_core/offline` 和 `rs_core.offline.runtime.worker` 管理。
- [ ] Services API 有稳定 schema、contract tests 和前端类型同步检查。
- [ ] Docker/Compose/CI 能重复验证轻量服务边界，不默认拉起重 infra 或模型。
- [ ] 旧实现物理删除前有 parity tests、grep/import 证据、rollback path 和工程叙事记录。

---

## 4. Phase 0：冻结迁移完成基线

目标：把上一轮迁移完成状态固化为后续 hardening 的起点，防止后续任务误把已完成迁移重新打开。

### 4.1 文档基线冻结

- [x] 在本文档中记录上一轮迁移完成证据入口。
- [x] 在 `dic/README.md` 推荐阅读顺序中加入本文档。
- [x] 在 `dic/PROJECT_STRUCTURE.md` 中说明本文档属于迁移后硬化计划，不替代原迁移计划。
- [x] 在 `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md` 增加“退役等级”列或补充说明。
- [x] 在 `RS_AGENT_MIGRATION_VALIDATION_EVIDENCE.md` 增加“迁移完成基线”小节。

### 4.2 验证命令冻结

- [x] 固化分层迁移套件命令。
- [x] 固化 migration scope ruff 命令。
- [x] 固化 frontend build 命令。
- [x] 固化 Docker gateway smoke 命令。
- [x] 固化 `git diff --check` 命令。
- [x] 将上述命令加入 README 或开发指南，避免后续只凭记忆运行旧路径测试。

### 4.3 完成边界声明

- [x] 明确“上一轮迁移完成”不等于“旧实现已全部物理删除”。
- [x] 明确本计划的对象是 hardening、真实化、退役和生产化准备。
- [x] 明确旧目录保留必须有 owner、兼容说明和收束条件。
- [x] 明确任何新功能如果绕过 canonical 入口，必须先补架构理由和迁移截止条件。

### Phase 0 完成标准

- [x] 当前迁移完成基线有明确文档入口。
- [x] 后续任务不会继续修改原迁移计划的完成口径。
- [x] 验证命令、证据文档和工程叙事口径一致。
- [x] 所有后续 hardening 工作都能追溯到本文档。

---

## 5. Phase 1：旧路径退役准备与 import 治理

目标：先建立退役治理机制，防止旧路径在后续开发中继续扩散。

### 5.1 旧路径分级

对以下目录逐项标记退役等级：

- [x] `rs_core/dataproc/`：真实实现已迁入 `rs_core/data/pipelines/`，旧顶层 marker 已归档。
- [x] `rs_core/features/`：已归档顶层空包，feature 目标目录为 `rs_core/data/features/`。
- [x] `rs_core/artifacts/`：manifest/resolver 真实实现已迁入 `rs_core/data/artifacts/`。
- [x] `rs_core/training/`。
- [x] `rs_core/evaluation/`。
- [x] `rs_core/recsys/`。
- [x] `rs_core/recsys/rag/`。
- [x] `rs_core/recsys/semantic_description/`。
- [x] `rs_core/rsagent/`。
- [x] `rs_core/agent_runtime/`。
- [x] `rs_core/serving/`。
- [x] `rs_core/workflow/`。
- [x] `rs_core/simulation/`。
- [x] `rs_core/display/`。
- [x] `rs_core/animation/`：已归档顶层 marker，归属由 frontend / agent simulation / offline report 说明承接。
- [x] `scripts/data/`。
- [x] `scripts/artifacts/`。
- [x] `scripts/training/`。
- [x] `scripts/evaluation/`。
- [x] `scripts/experiments/`。
- [x] `scripts/recall/`。
- [x] `scripts/serving/`。

退役等级建议：

- [x] A 类：纯 compatibility facade，可在调用点清零后删除。
- [x] B 类：存量实现来源，短期保留，但禁止新增直接依赖。
- [x] C 类：需要迁移的核心实现，必须拆到新模块后再退役。
- [x] D 类：历史/探索入口，只保留归档或手动脚本，不进入主验证链路。

### 5.2 import census

- [x] 统计 `rs_core/data` 对旧路径的 import。
- [x] 统计 `rs_core/online` 对旧路径的 import。
- [x] 统计 `rs_core/agent` 对旧路径的 import。
- [x] 统计 `rs_core/offline` 对旧路径的 import。
- [x] 统计 `services` 对旧路径的 import。
- [x] 统计 `scripts` 对旧路径的 import。
- [x] 统计 `tests` 中仍覆盖旧路径的用例。
- [x] 输出 import census 报告到 `dic/architecture/` 或 `dic/experiments/`。

### 5.3 import boundary test 加强

- [x] 增加 new-code forbidden legacy import 测试。
- [x] 增加 compatibility facade whitelist。
- [x] 增加 serving 接入层不允许 import 旧业务核心内部模块的测试。
- [x] 增加 online 不允许 import agent / RAG 内部模块的测试。
- [x] 增加 agent 不允许 import online recall/ranking 内部实现的测试。
- [x] 增加 offline 不允许 import serving route 的测试。
- [x] 增加 data 之外模块不允许直接 import infra SDK 的测试。

### 5.4 退役条件模板

每个旧目录必须补齐：

- [x] 当前 owner。
- [x] 新 canonical 替代入口。
- [x] 当前允许的 compatibility import。
- [x] 当前禁止新增的 import。
- [x] parity test 名称。
- [x] smoke test 名称。
- [x] import 清零 grep 命令。
- [x] rollback path。
- [x] 删除前 checklist。

### Phase 1 完成标准

- [x] 旧路径都有退役等级。
- [x] import census 报告已生成。
- [x] import boundary test 能阻止新增旧路径依赖。
- [x] compatibility facade whitelist 明确。
- [x] 每个旧目录都有可执行退役条件。

---

## 6. Phase 2：Online 推荐链路真实收束

目标：让 `rs_core/online` 不只是 facade，而成为 recall、ranking、recommend runtime 的真实主入口。

### 6.1 Online contract 稳定

- [x] 固化 `RecallRequest` contract。
- [x] 固化 `RecallResult` / candidate pool contract。
- [x] 固化 `RankingRequest` contract。
- [x] 固化 `RankingResult` contract。
- [x] 固化 `RecommendRequest` / `RecommendationResult` contract。
- [x] 固化 `RankingTrace` / `RecallTrace` public-safe 字段。
- [x] 明确 internal diagnostics 不进入 public display。
- [x] 明确 pool200 / pool500 / shadow evidence 的字段边界。

### 6.2 Recall 入口收束

- [x] 梳理当前 `rs_core/recsys/recall` 的真实调用点。
- [x] 梳理 `scripts/recall` 中仍作为主入口的脚本。
- [x] 将 online recall public API 固定在 `rs_core/online/recall`。
- [x] 为每个 recall source 增加 new-vs-old parity smoke。
- [x] 将 candidate pool 读取改为经 `CandidatePoolClient` 或 data contract。
- [x] 明确 pool500 recall artifact 是 recall readiness / shadow evidence，不替代 ranking route。
- [x] 增加 recall route 不读取 oracle/label/holdout 的测试。

### 6.3 Ranking 入口收束

- [x] 梳理当前 `rs_core/recsys/ranking` 的真实调用点。
- [x] 梳理 COLD→DeepFM 当前所在路径和加载方式。
- [x] 将 ranking public API 固定在 `rs_core/online/ranking`。
- [x] 将 ranking artifact 读取改为经 `ArtifactClient`。
- [x] 为 COLD→DeepFM 增加 online contract wrapper。
- [x] 增加 ranking parity smoke，保证迁移不改变 smoke 输出。
- [x] 增加 ranking route 不直接访问 data file path 的测试。

### 6.4 Online runtime 与 serving 解耦

- [x] 梳理 `rs_core/workflow/online_recommendation.py` 的 online runtime 职责。
- [x] 将可复用 runtime host 迁入 `rs_core/online/runtime`。
- [x] `rs_core.serving.api.online_app` 只依赖 `OnlineRecommendationEngine`。
- [x] `rs_core/serving` 中旧 single-process demo 只保留兼容说明。
- [x] 增加 `/recommend`、`/recall`、`/rank` schema snapshot。
- [x] 增加 online ready public-safe dependency status。

当前 runtime 收束口径：`rs_core.serving.api.online_app` 已只经 `OnlineRecommendationEngine` 对外提供 `/recommend`、`/recall`、`/rank`；旧 `rs_core/serving` single-process demo 已声明 compatibility/demo 边界；旧 `RecommendationService` 构建 pool500 runtime host 时已改经 `rs_core.online.runtime.build_online_pool500_recommender()`，不再直接 import `rs_core.workflow.online_recommendation`。`OnlinePool500Recommender` 与 `OnlineRecommendationResult` 的真实实现已迁入 `rs_core/online/runtime/pool500.py`；旧 `rs_core/workflow/online_recommendation.py` 在 active import 清零后已退役删除，后续通过 path-not-exists guard 防止回流。旧 workflow 目录其他真实实现仍需继续按 owner 迁移，不能整体删除。

### 6.5 Online 验证

- [x] `tests/online` 覆盖 recall contract。
- [x] `tests/online` 覆盖 ranking contract。
- [x] `tests/online` 覆盖 recommend runtime smoke。
- [x] `tests/services` 覆盖 online service HTTP schema。
- [x] Docker gateway smoke 覆盖 `/api/recommend`、`/api/recall`、`/api/rank`。
- [x] ruff 覆盖 `rs_core/online` 与 `rs_core.serving.api.online_app`。

### Phase 2 完成标准

- [x] Online 主链路从 `rs_core/online` public API 进入。
- [x] 旧 `rs_core/recsys` 不再作为 online 新代码入口。
- [x] Recall/ranking parity smoke 通过。
- [x] Pool500 不会误替代当前 ranking route。
- [x] Online 服务 schema 和 gateway smoke 通过。

Phase 2 当前完成口径：Online public API、入口治理、recall/ranking parity、schema/gateway、Pool500 no-promotion 门禁和 runtime host 物理迁入均已具备代码与测试证据。旧 `rs_core/workflow/online_recommendation.py` 已在删除窗口退役，但这不表示旧 workflow 目录整体已经可删除。

---

## 7. Phase 3：Agent/RAG 链路硬化

目标：让 `rs_core/agent` 真正承接 dialogue、planner、tools、RAG、explanation、feedback、memory 和 Agent simulation。

### 7.1 Agent public API 稳定

- [x] 固化 `AgentOrchestrationEngine` 对外方法。
- [x] 固化 dialogue plan contract。
- [x] 固化 tool call contract。
- [x] 固化 RAG evidence contract。
- [x] 固化 explanation contract。
- [x] 固化 feedback contract。
- [x] 固化 memory reference contract。
- [x] 固化 Agent simulation / sandbox contract。

当前 public API 收束口径：`AgentOrchestrationEngine` 已提供 start/chat/feedback/end/export、plan_dialogue、validate_rag_agent_call、explain、memory_ref、rag_query 和 online client recommend 边界；Phase 3 入口清单见 `RS_AGENT_PHASE3_AGENT_RAG_ENTRYPOINT_INVENTORY.md`。Agent simulation / sandbox 已通过 `rs_core.agent.simulation.AgentSimulationSandboxContract` 固化 schema_version、owner、debug service entrypoints、offline boundary、public-safe roots、forbidden public fields 和约束，明确 Agent 行为沙盒由 `rs_core.agent.simulation` 承接，离线指标产出经 `rs_core.offline.simulation` 管理，不把 simulation 评估结果混入 online ranking state。

### 7.2 `rs_core/rsagent` 收束

- [x] 梳理 `rs_core/rsagent` 的 dialogue、planner、tools、runtime、explanation 调用点。
- [x] 将新代码入口统一改为 `rs_core/agent/*`。
- [x] 对 `rs_core/agent/dialogue` 与 `rs_core/rsagent/dialogue` 建 parity tests。
- [x] 对 `rs_core/agent/planner` 与旧 planner 建 parity tests。
- [x] 对 `rs_core/agent/tools` 与旧 tools 建 manifest parity tests。
- [x] 对 `rs_core/agent/explanation` 与旧 explanation 建 public output tests。
- [x] 在旧 `rs_core/rsagent` facade 加清晰 deprecation note。

当前调用点 census 已记录在 `RS_AGENT_PHASE3_AGENT_RAG_ENTRYPOINT_INVENTORY.md`：`workflow/hybrid_environment.py`、`workflow/facades.py` 与旧 serving 中可安全替换的 Agent import 已收束到 `rs_core.agent.*`；workflow runtime 的 RAG import 已从 `rs_core.recsys.rag` 收束到 `rs_core.agent.rag` facade，RAG 构建脚本经 `rs_core.agent.rag` 引用构建符号。本轮已进一步把旧 `rs_core/rsagent` 的 dialogue、planner、tools、runtime、context、feedback、inference、explanation、memory、rerank、model client 与 schema contract 真实实现迁入 `rs_core/agent/*`，并删除 active `rs_core/rsagent` package；`rs_core/agent_runtime` 也已完成真实实现迁移并物理删除。剩余 `rs_core/recsys/rag` 底层实现仍未物理迁移，旧 RAG/recsys 路径退役和删除继续留待 Phase 10。

### 7.3 `rs_core/agent_runtime` 收束

- [x] 区分 generic runtime 与 domain-specific Agent runtime。
- [x] 将 RagAgent adapter 新入口收敛到 `rs_core/agent/adapters` 或 `rs_core/agent/rag`。
- [x] 将 LLM planner adapter 边界写入 Agent contract。
- [x] 保留 internal-only trace，不进入 public display。
- [x] 增加 output projection policy 测试。
- [x] 增加 hidden tool 不进入 SFT public target 的测试。

当前证据主要来自 `tests/agent/test_agent_runtime_contracts.py`、`tests/agent/test_agent_runtime.py`、`tests/agent/test_llm_dialogue_planner.py`、`tests/agent/test_agent_tools.py`、`tests/agent/test_agent_facade_parity.py` 与 `tests/agent/test_multi_turn_sft_generator.py`。本轮已把 `rs_core/agent_runtime/core` 的 generic runtime 真实实现物理迁入 `rs_core/agent/runtime_core`，把 `rs_core/agent_runtime/adapters` 的 RagAgent/MemoryAgent/Recommendation shadow adapter 真实实现物理迁入 `rs_core/agent/adapters`，并把旧 `contracts/compatibility.py` 收束为 `rs_core/agent/runtime_core/contracts.py`；随后删除 active `rs_core/agent_runtime` package。`rs_core/agent/rag` 与 `rs_core/agent/adapters` 已改为直接承接新实现，主代码和测试对 `rs_core.agent_runtime` 的显式 import 已清零。

### 7.4 RAG/RAGAgent 硬化

- [x] 梳理 `rs_core/recsys/rag` 当前 BM25/Qdrant/local file 访问点。
- [x] 将 knowledge chunk 读取统一改为 `KnowledgeDataClient`。
- [x] 将 Qdrant / BM25 / local file 配置经 data adapter contract 管理。
- [x] 固化 query rewrite disabled/shadow/active 三模式。
- [x] 固化 candidate-scoped evidence contract。
- [x] 固化 small2big parent context contract。
- [x] 增加 RAG 不读取 online 内部 ranking state 的测试。
- [x] 增加 RAG evidence 不泄漏 raw path/provider/source 的 public projection 测试。

当前 RAG/RagAgent evidence 主要来自 `tests/agent/test_rag_agent_adapter.py`、`tests/test_rag_core.py`、`tests/test_qdrant_cli_smoke.py`、`tests/test_qdrant_config_env.py` 与 `tests/contracts/test_architecture_migration_boundaries.py`。本轮已让 `scripts/recall/build_rag_bm25_index.py` 与 `scripts/recall/build_qdrant_rag_index.py` 在 manifest 中声明 `KnowledgeDataClient` 与 `knowledge_artifact`，并用 contract test 固化脚本不反向依赖 Agent/RagAgent runtime；同时 `workflow/facades.py` / `workflow/hybrid_environment.py` 的 runtime BM25 index path 解析已改经 `KnowledgeDataClient.local_rag_index_artifact()`，`workflow/facades.py` 的 Qdrant RAG collection 名称也先经 `qdrant_rag_collection_artifact()` 投影后再交给 retriever。最新补强是在 `rs_core.data.contracts.DataAdapterContract` 中表达 local BM25 与 Qdrant RAG collection 的 adapter_id/backend/resource_ref/connection_ref/read_only/metadata，并由 `KnowledgeDataClient` 的 RAG artifact metadata 携带 `adapter_contract`；`workflow/facades.py` 与 `workflow/hybrid_environment.py` 的 BM25 runtime path 已从 adapter contract 的 `resource_ref` 取值，`workflow/facades.py` 的 Qdrant collection name 也从 `qdrant://...` resource_ref 投影。随后将 Qdrant 连接参数解析与 vector store 构造收束到 `rs_core.data.adapters.QdrantAdapter`，`scripts/recall/build_qdrant_rag_index.py` 的 env/CLI Qdrant 配置读取改经 `rs_core.data.adapters`，`workflow/facades.py` 不再直接调用 `QdrantVectorStore.from_config()`。因此 Qdrant/BM25/local file 的 runtime/script 配置管理已按 data adapter contract 口径勾选；底层 BM25/Qdrant retriever 实现仍保留在 `rs_core/recsys/rag` / vectorstore，作为 Phase 10 物理迁移对象。

### 7.5 Agent grounding 与 SFT 数据边界

- [x] no-tool/no-display turn 不生成商品推荐。
- [x] `selected_item_ids` 只来自 public display。
- [x] terminal accept 不复用错误 diagnostics。
- [x] RAG support 不进入 public target 的 raw evidence 字段。
- [x] hidden tool call 不暴露给前端。
- [x] SFT artifact manifest 统计 dropped/no-display turns。
- [x] validator 拒绝无 grounding 商品列表。
- [x] validator 拒绝 oracle/label/holdout 字段。

当前 grounding 与 SFT 边界由 `tests/agent/test_agent_dialogue.py`、`tests/agent/test_agent_tools.py`、`tests/agent/test_agent_runtime.py`、`tests/agent/test_rag_agent_adapter.py`、`tests/agent/test_multi_turn_sft_generator.py` 和 service smoke 共同覆盖。

### 7.6 Agent 验证

- [x] `tests/agent` 覆盖 dialogue。
- [x] `tests/agent` 覆盖 planner。
- [x] `tests/agent` 覆盖 tools。
- [x] `tests/agent` 覆盖 runtime。
- [x] `tests/agent` 覆盖 RAG adapter。
- [x] `tests/agent` 覆盖 multi-turn SFT generator。
- [x] `tests/services` 覆盖 `/chat`、`/feedback`、`/rag/query`。
- [x] Docker gateway smoke 覆盖 session/chat/RAG。

当前轻量验证：`.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_runtime_contracts.py tests/agent/test_agent_runtime.py tests/agent/test_rag_agent_adapter.py tests/agent/test_agent_dialogue.py tests/agent/test_llm_dialogue_planner.py tests/agent/test_agent_tools.py tests/services/test_serving_smoke.py tests/services/test_serving_reorg_compatibility.py -q` 通过 `269 passed in 6.30s`；`tests/agent/test_multi_turn_sft_generator.py -q` 通过 `37 passed in 7.58s`；新增 facade parity 与 hybrid_environment import 收束后，`.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_dialogue.py tests/agent/test_agent_tools.py -q` 通过 `98 passed in 1.20s`；进一步收束 workflow Agent/RagAgent runtime import 后，`.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_runtime.py tests/agent/test_agent_runtime_contracts.py tests/agent/test_rag_agent_adapter.py tests/agent/test_agent_dialogue.py -q` 通过 `140 passed in 1.51s`；旧 serving Agent import 收束后，`.venv/Scripts/python.exe -m pytest tests/services/test_serving_smoke.py tests/services/test_serving_reorg_compatibility.py tests/services/test_serving_run_service.py tests/contracts/test_architecture_migration_boundaries.py -q` 通过 `115 passed in 5.68s`；RAG artifact data-client 边界补强后，`.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/contracts/test_architecture_migration_boundaries.py::test_rag_build_scripts_declare_data_client_artifact_boundary tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run tests/test_qdrant_config_env.py -q` 通过 `11 passed in 2.09s`；runtime BM25 path 与 Qdrant collection artifact 投影补强后，`.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_dialogue.py tests/agent/test_rag_agent_adapter.py -q` 通过 `87 passed in 1.75s`；旧 `rs_core/rsagent` deprecation boundary focused tests 通过 `5 passed in 0.51s`；Agent simulation sandbox contract focused tests 通过 `3 passed in 0.49s`；RAG data adapter contract focused tests 通过 `7 passed in 1.88s`；RAG 脚本与 workflow facade 收束验证通过 `.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py::test_agent_and_offline_runtime_entrypoints_use_canonical_facades tests/contracts/test_architecture_migration_boundaries.py::test_new_entrypoint_legacy_imports_are_whitelist_only tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run -q`，结果 `13 passed in 2.05s`；Qdrant adapter config 收束后，`.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py::test_agent_and_offline_runtime_entrypoints_use_canonical_facades tests/contracts/test_architecture_migration_boundaries.py::test_new_entrypoint_legacy_imports_are_whitelist_only tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run tests/data/test_data_adapter_readiness.py::test_qdrant_adapter_projects_config_and_builds_store -q` 通过 `16 passed in 2.47s`；扩展 hardening suite 最新通过 `424 passed in 19.88s`，OpenAPI snapshot、frontend type guard 与 ruff 均通过。Docker gateway smoke 已在 Phase 6/7 证据中覆盖 session/chat/feedback/RAG，但本轮未重新启动 Docker。

### Phase 3 完成标准

- [x] Agent 新代码入口统一走 `rs_core/agent`。
- [x] RAG/RAGAgent 不回流 online。
- [x] Agent 通过 client 调 online，不 import online 内部 recall/ranking。
- [x] SFT 和 public display grounding boundary 测试通过。
- [x] 旧 `rs_core/agent_runtime` 与旧 `rs_core/rsagent` 均已物理删除。

Phase 3 当前完成口径：Agent public API、dialogue/planner/tools/runtime/RAG/grounding/SFT/simulation sandbox、RAG artifact/data-adapter 表达和 Agent↔Online 边界均已有代码与测试证据；`rs_core/workflow` 与 `scripts/recall` 的新 runtime/script 入口已统一经 `rs_core.agent.*`，因此 `Agent 新代码入口统一走 rs_core/agent` 与 7.2“新代码入口统一”按 canonical owner 口径勾选。旧 `rs_core/agent_runtime` active package 已删除；旧 `rs_core/rsagent` 已完成实现迁移、import census 清零和 active package 删除；旧 `rs_core/recsys/rag` 也已完成真实实现迁入 `rs_core/agent/rag`、import census 清零和 active package 删除。

---

## 8. Phase 4：Data/Infra adapter 真实化

目标：把数据基础设施从 contract 层推进到更真实、可降级、可观测、secret-safe 的 adapter/client 形态。

### 8.1 Storage contract 完善

- [x] 固化 `StorageConnectionContract` schema。
- [x] 固化 local file adapter contract。
- [x] 固化 PostgreSQL adapter contract。
- [x] 固化 Redis adapter contract。
- [x] 固化 MinIO adapter contract。
- [x] 固化 Qdrant adapter contract。
- [x] 每个 adapter 支持 disabled mode。
- [x] 每个 adapter 支持 dry-run readiness。
- [x] 每个 adapter 输出 public-safe error type，不输出 secret。

### 8.2 DataClient 能力补齐

- [x] `DatasetClient` 支持 dataset manifest / split / window metadata。
- [x] `FeatureClient` 支持 feature schema / feature view contract。
- [x] `ArtifactClient` 支持 manifest / uri / hash / model family。
- [x] `CandidatePoolClient` 支持 pool contract / source / size / freshness。
- [x] `KnowledgeDataClient` 支持 chunk / source / embedding index metadata。
- [x] `MemoryDataClient` 支持 session memory ref / backend status。
- [x] 所有 client 不暴露底层 SDK client。

### 8.3 Infra readiness

- [x] PostgreSQL readiness 不执行昂贵 full count。
- [x] Redis readiness 不阻塞 online 主服务。
- [x] MinIO readiness 不输出 access key / secret key。
- [x] Qdrant readiness 不输出 raw endpoint credential。
- [x] local file readiness 不输出用户敏感绝对路径，必要时做 project-relative projection。
- [x] infra 不可用时按场景 degraded / fail-open / fail-fast。
- [x] readiness schema 有 tests/contracts 覆盖。

### 8.4 Data worker 真实化

- [x] `rs_core.data.runtime.worker` 支持 dataset import dry-run。
- [x] 支持 recent window build dry-run。
- [x] 支持 candidate pool build smoke。
- [x] 支持 knowledge chunk build smoke。
- [x] 支持 artifact register smoke。
- [x] 支持 adapter readiness report。
- [x] 支持输出 machine-readable JSON report。
- [x] 不默认执行全量导入或重向量化。

### 8.5 Data 验证

- [x] `tests/data` 覆盖 storage contract。
- [x] `tests/data` 覆盖 each DataClient。
- [x] `tests/data` 覆盖 data_worker CLI。
- [x] `tests/contracts` 覆盖 secret-safe readiness。
- [x] Docker infra profile 仅在手动 smoke 或 nightly 中运行。
- [x] 文档说明本机资源边界和 remote/offload 条件。

当前轻量验证：本轮先完成 Phase 4 的 adapter readiness 与 DataClient contract 最小竖线，`LocalFileAdapter`、`PostgresAdapter`、`RedisAdapter`、`MinioAdapter`、`QdrantAdapter` 已提供 disabled/degraded/ok readiness 输出；`DataAssetEngine.readiness()` 汇总 storage readiness；`rs_core.data.runtime.worker` 新增 `readiness` JSON report，且 `python -m rs_core.data.runtime.worker readiness` 不再因包级 eager import 触发 RuntimeWarning。DataClient 侧补齐 dataset manifest/window/freshness、feature schema/view、artifact manifest/checksum/model family、candidate pool size/freshness、memory backend status 与 RAG embedding index metadata 的 contract helper。已运行 `.venv/Scripts/python.exe -m pytest tests/data/test_data_adapter_readiness.py tests/contracts/test_architecture_migration_boundaries.py::test_target_architecture_packages_are_importable tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight tests/contracts/test_architecture_migration_boundaries.py::test_data_asset_readiness_is_secret_safe -q`，结果 `11 passed in 1.52s`；已运行 `.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/online/test_online_engine_contracts.py -q`，结果 `15 passed in 1.26s`；已运行 `.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight tests/data/test_data_clients.py tests/data/test_data_adapter_readiness.py -q`，结果 `13 passed in 0.68s`；最新 `.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config` 通过 `412 passed in 18.05s`，OpenAPI snapshot、frontend type guard 与 ruff 均通过。当前仍未把 infra profile 文档与真实 client binding 全部生产化，因此 Phase 4 只标记已验证的 lightweight readiness/client contract 闭环。

### Phase 4 完成标准

- [x] online/offline/agent 不直接 import infra SDK。
- [x] Data adapter readiness public-safe。
- [x] data_worker smoke 可生成结构化 report。
- [x] 重 infra 不默认启动。
- [x] Data contract/client tests 通过。

---

## 9. Phase 5：Offline 训练评估链路收束

目标：让训练、评估、实验和模型 artifact 注册统一通过 `rs_core/offline` 与 `rs_core.offline.runtime.worker` 进入。

### 9.1 Offline contract 稳定

- [x] 固化 `ModelArtifactContract`。
- [x] 固化 training job contract。
- [x] 固化 evaluation job contract。
- [x] 固化 metric report contract。
- [x] 固化 experiment run contract。
- [x] 固化 simulation result contract。
- [x] 区分 offline-only fields 与 public serving fields。

### 9.2 Training 收束

- [x] 梳理 `rs_core/training` 调用点。
- [x] 将训练新入口统一到 `rs_core/offline/training`。
- [x] `scripts/training/offline_engine_cli.py` 只调用 offline worker/engine。
- [ ] Qwen SFT / GRPO 相关脚本保留资源门禁。
- [ ] DeepFM / COLD 训练入口注册 model artifact。
- [x] heavy training 默认 disabled，需要显式参数或远程执行说明。
- [ ] 训练输出 manifest 不包含 secret 或本机敏感路径。

### 9.3 Evaluation 收束

- [x] 梳理 `rs_core/evaluation` 调用点。
- [x] 将评估新入口统一到 `rs_core/offline/evaluation`。
- [x] `scripts/evaluation/offline_engine_cli.py` 只调用 offline worker/engine。
- [x] scorecard / metrics / report contract 稳定。
- [x] evaluation 不进入 online runtime。
- [x] evaluation-only oracle/label/holdout 不进入 public serving schema。
- [x] 评估 smoke 不默认加载全量模型或全量数据。

### 9.4 Experiments 收束

- [x] 梳理 `scripts/experiments` 中仍作为主入口的实验。
- [ ] 区分成熟实验、半成熟实验、纯探索实验。
- [ ] 成熟实验迁入 `rs_core/offline/experiments`。
- [ ] 纯探索继续留在 `rs_lab` 或明确归档。
- [x] experiment router 输出 engine route 和 smoke report。
- [ ] 任何实验晋升主路前必须经过 contract / gate / narrative。

### 9.5 Offline worker

- [x] `rs_core.offline.runtime.worker` 支持 training smoke。
- [x] 支持 evaluation smoke。
- [x] 支持 model artifact register。
- [x] 支持 experiment smoke。
- [x] 支持 resource estimate 输出。
- [x] 支持 heavy job refusal 或 remote/offload hint。
- [x] 不处理 online HTTP 用户请求。

当前轻量验证：本轮完成 Phase 5 的 Offline contract/smoke 最小竖线，`rs_core/offline/contracts` 固化 `ResourceEstimateContract`、`TrainingJobContract`、`ModelArtifactContract`、`MetricReportContract`、`EvaluationJobContract`、`EvaluationResultContract`、`ExperimentRunContract` 与 `OfflineSimulationResultContract`；`OfflineModelEngine` 只生成 dry-run/smoke contract，不触发训练、全量评估、模型加载或外部服务。`rs_core.offline.runtime.worker` 新增 training dry-run、model artifact register、evaluation smoke、experiment smoke、simulation smoke 与 resource estimate 命令；`scripts/training/offline_engine_cli.py`、`scripts/evaluation/offline_engine_cli.py` 与 `scripts/experiments/engine_cli.py` 已路由到 offline worker/engine。Agent evaluation artifact / scorecard 真实实现已物理迁入 `rs_core/offline/evaluation`，`scripts/evaluation/run_agent_evaluation.py` 与 Agent evaluation tests 已切 canonical import，旧 `rs_core/evaluation` active package 已删除并由 architecture path-not-exists guard 固化。已运行 `.venv/Scripts/python.exe -m pytest tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight -q`，结果 `6 passed in 0.64s`；evaluation 物理迁移 focused suite 通过 `48 passed`，focused ruff `All checks passed!`，AST import census 对 `rs_core.evaluation` 无输出；最新 `.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config` 通过 `417 passed in 17.52s`，OpenAPI snapshot、frontend type guard 与 ruff 均通过；额外 verifier 复查 Phase 5 最小实现，结论 `PASS`，并验证指定 contract/worker/CI 文件 py_compile、offline worker heavy resource-estimate CLI 无 RuntimeWarning。

`RS_AGENT_PHASE5_OFFLINE_ENTRYPOINT_CENSUS.md` 已把 canonical wrapper、offline worker、training/evaluation/simulation canonical implementation 与剩余脚本/实验边界分层记录；training、evaluation 与 simulation 均已完成真实实现物理迁移和旧 active package 删除。训练脚本已切 `rs_core.offline.training.*`，但 Qwen SFT / GRPO / GPT SFT 重训练脚本仍不是 offline worker 化入口，DeepFM/COLD 真实训练输出与成熟实验迁移仍待后续收束。

### Phase 5 完成标准

- [ ] training/evaluation/simulation 主实现已统一到 offline 并删除旧 active package；training 重脚本 worker 化和成熟 experiment 迁移仍待完成。
- [x] offline worker smoke 通过。
- [x] heavy job 资源门禁明确。
- [x] evaluation-only 字段不进入 public serving。
- [x] 模型 artifact 注册链路有 contract tests。

---

## 10. Phase 6：Services API contract 稳定化

目标：让 `rs_core.serving.api.online_app` 与 `rs_core.serving.api.agent_app` 成为稳定 HTTP 边界，并让前端只依赖 public API。

### 10.1 Online service schema

- [x] 固化 `GET /health` response。
- [x] 固化 `GET /ready` response。
- [x] 固化 `POST /recommend` request/response。
- [x] 固化 `POST /recall` request/response。
- [x] 固化 `POST /rank` request/response。
- [x] 增加 OpenAPI snapshot 或 schema JSON 产物。
- [x] 增加 backward-compatible field policy。

### 10.2 Agent service schema

- [x] 固化 `GET /health` response。
- [x] 固化 `GET /ready` response。
- [x] 固化 `POST /session/start` request/response。
- [x] 固化 `GET /session/{session_id}` response。
- [x] 固化 `POST /session/end` request/response。
- [x] 固化 `POST /chat` request/response。
- [x] 固化 `POST /feedback` request/response。
- [x] 固化 `POST /rag/query` request/response。
- [x] 增加 OpenAPI snapshot 或 schema JSON 产物。

### 10.3 Public/Internal 字段分层

- [x] 标记 public API fields。
- [x] 标记 internal diagnostics fields。
- [x] 标记 training-only fields。
- [x] 标记 evaluation-only fields。
- [x] 标记 oracle/label/holdout forbidden fields。
- [x] 增加 public projection allowlist。
- [x] 增加 API response 不泄漏 internal path/trace/diagnostics file 的测试。

### 10.4 Frontend client 对齐

- [x] `frontend/src/api/shared.ts` 继续默认 `/api`。
- [x] `onlineClient` 只调用 online API。
- [x] `agentClient` 只调用 Agent API。
- [x] `sessionClient` 只调用 session API。
- [x] `demoClient` 不依赖后端内部字段。
- [x] `frontend/src/types` 从 schema 或脚本同步。
- [x] 增加 TypeScript build 对 schema drift 的保护。

### 10.5 Service 验证

- [x] `tests/services` 覆盖 online service。
- [x] `tests/services` 覆盖 agent service。
- [x] `tests/contracts` 覆盖 schema snapshot。
- [x] gateway smoke 覆盖 online + agent + frontend。
- [x] services 不写核心业务逻辑的静态测试通过。

### Phase 6 完成标准

- [x] API schema 有 snapshot 或稳定 contract。
- [x] 前端只依赖 public API。
- [x] internal/training/evaluation 字段不泄漏到 public response。
- [x] Services route 仍是 thin entrypoint。
- [x] service + frontend build + gateway smoke 通过。

---

## 11. Phase 7：Docker / Compose / CI 硬化

目标：从“本地 smoke 可跑”推进到“可重复、可选择、可治理的验证链路”。

### 11.1 Docker build context

- [x] 增加或完善 `.dockerignore`。
- [x] Docker build 不复制 `data/` 大文件。
- [x] Docker build 不复制 `outputs/` 大产物。
- [x] Docker build 不复制 `.venv/`。
- [x] Docker build 不复制 `.ruff_cache/`、`__pycache__/`。
- [x] 后端 Dockerfile 只安装 serving 必要依赖。
- [x] frontend Dockerfile 有稳定 npm cache 或 layer 顺序。

### 11.2 Compose profiles

- [x] `frontend` profile 文档清晰。
- [x] `online` profile 文档清晰。
- [x] `agent` profile 文档清晰。
- [x] `gateway` profile 文档清晰。
- [x] `worker` profile 文档清晰。
- [x] `infra` profile 文档清晰。
- [x] `infra` 不默认启动。
- [x] 每个 volume 挂载路径说明可复现性和清理方式。

### 11.3 Gateway smoke 自动化

- [x] 写 gateway smoke 脚本或 Make/CLI 入口。
- [x] 启动 frontend + online + agent + nginx。
- [x] 验证 `/api/health/online`。
- [x] 验证 `/api/health/agent`。
- [x] 验证 `/` frontend root。
- [x] 验证 `/api/recommend`。
- [x] 验证 `/api/recall`。
- [x] 验证 `/api/rank`。
- [x] 验证 `/api/session/start`。
- [x] 验证 `/api/chat`。
- [x] 验证 `/api/feedback`。
- [x] 验证 `/api/rag/query`。
- [x] smoke 结束自动 `down`。
- [x] 失败时保留 logs path，不泄漏 secret。

### 11.4 CI job 分层

- [x] lint job：ruff migration scope。
- [x] test job：分层迁移 suite。
- [x] contract job：engineering contracts + schema snapshot。
- [x] frontend job：npm build。
- [x] docker config job：compose config validation。
- [x] optional docker smoke job：手动或 nightly。
- [x] heavy infra job：默认关闭，只能手动触发或远程执行。

### 11.5 资源控制

- [x] CI 文档说明本地 12GB/14GB 边界。
- [x] heavy training job 不能进入默认 CI。
- [x] full-data import job 不能进入默认 CI。
- [x] Qdrant/MinIO/PostgreSQL 全量任务需要手动 profile 或远程执行。
- [x] smoke 与 full run 命令明确区分。

### Phase 7 完成标准

- [x] Docker build context 不包含大数据和本地环境。
- [x] Compose profiles 可按需启动。
- [x] Gateway smoke 可脚本化复现。
- [x] CI 能覆盖 lint/test/frontend/build/config。
- [x] 重任务不会被默认触发。

---

## 12. Phase 8：观测、诊断与运行报告

目标：让 online、agent、RAG、data、offline 的运行状态更容易解释、排查和面试复述。

### 12.1 Online diagnostics

- [ ] public response 包含 stable `fallback_used`。
- [ ] public response 包含 candidate_count。
- [ ] public response 包含 ranking route summary。
- [ ] public response 包含 recall source summary。
- [ ] internal response 可保留 detailed trace，但不进入 public display。
- [ ] fallback reason 有枚举和文档。
- [ ] candidate pool miss 有 public-safe reason。

### 12.2 Agent diagnostics

- [ ] chat response 可观测 should_recommend。
- [ ] chat response 可观测 display item count。
- [ ] chat response 可观测 tool chain summary。
- [ ] RAG response 可观测 evidence count。
- [ ] explanation response 可观测 evidence grounding status。
- [ ] internal planner trace 不进入前端 public display。
- [ ] no-grounding response 有稳定 reason。

### 12.3 Data/Infra diagnostics

- [ ] DataAssetEngine health 输出 storage dependency summary。
- [ ] adapter degraded reason 不泄漏 secret。
- [ ] artifact manifest miss 有 public-safe reason。
- [ ] candidate pool freshness 可观测。
- [ ] knowledge chunk source readiness 可观测。
- [ ] memory backend readiness 可观测。

### 12.4 Offline diagnostics

- [ ] training smoke 输出 resource estimate。
- [ ] evaluation smoke 输出 metric summary。
- [ ] artifact register 输出 manifest summary。
- [ ] experiment smoke 输出 route 和 output path。
- [ ] failed heavy job 输出 offload suggestion。
- [ ] training/evaluation report 不混入 public serving response。

### 12.5 报告生成

- [ ] 增加 migration hardening smoke report。
- [ ] report 输出 markdown。
- [ ] report 输出 machine-readable JSON。
- [ ] report 包含 commands、versions、pass/fail、duration。
- [ ] report 包含 skipped heavy tasks 和原因。
- [ ] report 可引用到 `ENGINEERING_NARRATIVE_LOG.md`。

### Phase 8 完成标准

- [ ] 关键链路均有 public-safe diagnostics。
- [ ] internal trace 与 public response 明确隔离。
- [ ] smoke report 可复现。
- [ ] 面试叙事可从 report 和工程日志直接复述。

---

## 13. Phase 9：前端展示与 display contract 硬化

目标：让前端展示、商品卡、反馈、session replay 与后端 public API contract 稳定对齐。

### 13.1 Display payload contract

- [ ] 固化 display item schema。
- [ ] 固化 display slate schema。
- [ ] 固化 feedback action schema。
- [ ] 固化 session replay event schema。
- [ ] 固化 explanation display schema。
- [ ] public display allowlist 明确。
- [ ] internal trace forbidden list 明确。

### 13.2 Type sync

- [ ] 明确后端 Pydantic schema 到 TypeScript 的同步策略。
- [ ] `scripts/ci/generate_frontend_types.py` 不再只是静态 re-export 或明确其边界。
- [ ] schema 变化能触发 frontend type diff。
- [ ] TypeScript build 能发现缺失字段。
- [ ] 前端类型不引用后端内部 Python 模块路径。

### 13.3 Frontend behavior smoke

- [ ] 商品卡能渲染 online recommend response。
- [ ] Agent chat 能显示 message 和 display slate。
- [ ] feedback button 调 `/api/feedback`。
- [ ] session replay 能读取 public session export。
- [ ] RAG/explanation evidence 有安全展示边界。
- [ ] 空 display 不渲染伪商品。

### 13.4 Display / animation ownership

- [ ] `rs_core/display` 只保留后端 display payload contract 或迁出到 frontend types。
- [x] `rs_core/animation` 顶层 marker 已归档，纯 UI 动画、session replay、Agent 行为回放的 ownership 由 `dic/PROJECT_STRUCTURE.md` 和 architecture boundary test 承接。
- [x] 纯 UI 动画归 frontend。
- [x] Agent 行为回放归 agent simulation 或 session replay contract。
- [x] Offline 评估可视化归 offline report。
- [x] 旧 animation 顶层路径已归档；display 路径仍按 payload contract 条件后续退役。

### Phase 9 完成标准

- [ ] Frontend 只消费 public API / public types。
- [ ] Display 不泄漏 internal diagnostics。
- [ ] 类型同步或 schema drift 检测可运行。
- [ ] display/animation owner 清晰。
- [ ] frontend build 和 smoke 通过。

---

## 14. Phase 10：真实旧实现物理迁移窗口

目标：在前面 contract、parity、smoke、CI 都稳定后，再执行旧实现的真实物理迁移和删除。

### 14.1 物理迁移准入条件

每个旧目录迁移前必须满足：

- [ ] 已有新 canonical owner。
- [ ] 已有 public contract。
- [ ] 已有 parity test。
- [ ] 已有 smoke test。
- [ ] 已有 import census。
- [ ] 已有 rollback path。
- [ ] 已有 deprecation note。
- [ ] 已评估资源影响。
- [ ] 已更新工程叙事或 ADR。

### 14.2 Data 旧实现迁移

- [x] 将 `rs_core/dataproc` 的 recall_clean / recall_views / recent_window_materializer / validation 可复用实现迁入 `rs_core/data/pipelines`，旧顶层 marker 已归档。
- [x] `rs_core/features` 顶层空包已归档，后续 feature 可复用实现只进入 `rs_core/data/features`。
- [x] 将 `rs_core/artifacts` 的 manifest/resolver 可复用实现迁入 `rs_core/data/artifacts`，旧 namespace compatibility marker 已在显式删除窗口退役。
- [ ] 保留旧 facade 并加 deprecation warning 或文档说明。
- [ ] 调用点清零后删除旧路径。
- [ ] 跑 data parity + smoke + ruff。

### 14.3 Online 旧实现迁移

- [x] 将 `rs_core/recsys/recall` 主实现迁入 `rs_core/online/recall`，旧 active package 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/online_retrieval` orchestrator/providers 主实现迁入 `rs_core/online/recall/online_retrieval`，旧 active package 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/candidate_store` CandidateStore contract、Noop/Safe wrapper、MySQL/Scylla(Cassandra) backend、factory 与 row schema adapter 主实现迁入 `rs_core/online/recall/candidate_store`，旧 active package 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/pool500_artifacts.py` pool500 candidate artifact loader、oracle/internal-field guard、per-user candidate index 与 readiness 输出主实现迁入 `rs_core/online/recall/pool500_artifacts.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/candidate_merge.py` 候选加载、召回候选生成、source budget 与候选融合主实现迁入 `rs_core/online/recall/candidate_merge.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/types.py` 中跨 online/agent/offline 使用的 shared dataclass types 迁入 `rs_core/common/recsys_types.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/ltr.py` 中 LTR 特征提取、打分、轻量训练与模型读写工具迁入 `rs_core/online/ranking/ltr.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/vector_index.py` 中 two-tower/local vector index 加载、搜索和归一化工具迁入 `rs_core/online/recall/vector_index.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/two_tower_source_manifest.py` 中 two-tower source index manifest governance/validation 迁入 `rs_core/online/recall/two_tower_source_manifest.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/two_tower_query.py` 中 artifact-user-first 查询向量构建、train-only seed fallback、user tower projection 与 diagnostics 迁入 `rs_core/online/recall/two_tower_query.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/ranking` 主实现迁入 `rs_core/online/ranking`，旧 `rs_core/recsys/ranking.py` active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 COLD→DeepFM 主实现与 online serving diagnostic shadow wrapper 迁入 `rs_core/online/ranking/cold_deepfm.py`，旧 `rs_core/recsys/cold_deepfm.py` active module 已删除。
- [ ] 将 online runtime host 从 `rs_core/workflow` 收束到 `rs_core/online/runtime`。
- [ ] 保留旧 facade 并加 deprecation note。
- [ ] 跑 online parity + service smoke + gateway smoke。

### 14.4 Agent 旧实现迁移

- [x] 将 `rs_core/rsagent/dialogue` 主实现迁入 `rs_core/agent/dialogue`。
- [x] 将 `rs_core/rsagent/llm_dialogue_planner` 主实现迁入 `rs_core/agent/planner`。
- [x] 将 `rs_core/rsagent/tools` 主实现迁入 `rs_core/agent/tools`。
- [x] 将 `rs_core/rsagent/explanation` 主实现迁入 `rs_core/agent/explanation`。
- [x] 将 `rs_core/rsagent` 的 runtime、context、feedback、inference、memory、rerank、model client 与 schema contract 迁入 `rs_core/agent/*`，并删除 active `rs_core/rsagent` package。
- [x] 将 `rs_core/agent_runtime` 中 Agent-specific adapter 迁入 `rs_core/agent/adapters`，并将 generic runtime core 迁入 `rs_core/agent/runtime_core`。
- [x] 将 `rs_core/recsys/rag` 主实现迁入 `rs_core/agent/rag`，并删除旧 active package；数据访问继续经 `rs_core/data` adapter 边界收束。
- [x] 删除旧 Agent namespace 后用 path-not-exists guard 防恢复。
- [x] 跑 agent parity + SFT boundary + service smoke 的 focused 子集。

### 14.5 Offline 旧实现迁移

- [x] 将 `rs_core/training` 主实现迁入 `rs_core/offline/training`，并删除 active 旧 package。
- [x] 将 `rs_core/recsys/two_tower.py` 中 two-tower 训练、负采样、PyTorch/fallback 模型与 artifact 保存主实现迁入 `rs_core/offline/training/two_tower.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/recsys/evaluation.py` 中离线 ranking/recall 评估、冻结候选签名、ranking registry、promotion gate 与 artifact inspection 主实现迁入 `rs_core/offline/evaluation/ranking.py`，旧 active module 已删除并由 architecture path-not-exists guard 防恢复。
- [x] 将 `rs_core/evaluation` 主实现迁入 `rs_core/offline/evaluation`，并删除 active 旧 package。
- [ ] 将成熟实验迁入 `rs_core/offline/experiments`。
- [x] 将离线仿真迁入 `rs_core/offline/simulation`，并删除 active 旧 `rs_core/simulation` package。
- [ ] 保留旧 facade 并加 deprecation note。
- [ ] 跑 offline smoke + training/evaluation contract tests。

### 14.6 删除窗口

删除旧路径前必须逐项完成：

- [ ] grep/import 证明没有主代码依赖旧路径。
- [ ] tests 证明旧 facade 删除不会破坏主链路。
- [ ] docs 说明新路径和迁移方式。
- [ ] changelog 或工程叙事记录删除原因。
- [ ] 如有外部调用风险，先发布一个 deprecated release/window。
- [ ] 删除后跑 full migration hardening suite。

### Phase 10 完成标准

- [ ] 旧实现不再作为主实现来源。
- [ ] 旧 facade 可按目录逐步删除。
- [ ] 删除不破坏 online/agent/data/offline/serving/front-end smoke。
- [ ] 每次删除都有证据和 rollback path。

---

## 15. Phase 11：最终硬化验收

目标：证明迁移后硬化完成，而不仅是新增计划或文档。

### 15.1 结构验收

- [ ] `rs_core/data` 是数据和基础设施连接真实主入口。
- [ ] `rs_core/online` 是 online recall/ranking/recommend runtime 真实主入口。
- [ ] `rs_core/agent` 是 dialogue/planner/RAG/explanation/feedback/memory 真实主入口。
- [ ] `rs_core/offline` 是 training/evaluation/simulation/experiment/model artifact 真实主入口。
- [ ] HTTP / worker thin entrypoint 已收敛到 `rs_core.serving.api.*_app`、`rs_core.data.runtime.worker` 和 `rs_core.offline.runtime.worker`。
- [ ] `deploy` 是本地服务编排和 gateway smoke 入口。
- [ ] `frontend` 只依赖 public API 和 public types。

### 15.2 行为验收

- [ ] Online `/recommend`、`/recall`、`/rank` smoke 通过。
- [ ] Agent `/chat`、`/feedback`、`/rag/query` smoke 通过。
- [ ] Data worker dataset/window/artifact/chunk smoke 通过。
- [ ] Offline worker training/evaluation/artifact smoke 通过。
- [ ] Frontend build 通过。
- [ ] Docker gateway smoke 通过。
- [ ] Optional infra profile smoke 有文档和跳过说明。

### 15.3 边界验收

- [ ] online 不拥有 RAG。
- [ ] agent 不直接 import online 内部 recall/ranking 实现。
- [ ] online/agent/offline 不直接 import infra SDK。
- [ ] serving route / worker entrypoint 不写核心业务逻辑。
- [ ] offline 不处理线上用户请求。
- [ ] frontend 不依赖后端内部字段。
- [ ] old_dic 不参与当前规划。
- [ ] legacy paths 不再新增主业务依赖。

### 15.4 测试验收

- [ ] `tests/data` 通过。
- [ ] `tests/online` 通过。
- [ ] `tests/agent` 通过。
- [ ] `tests/offline` 通过。
- [ ] `tests/services` 通过。
- [ ] `tests/contracts` 通过。
- [ ] import boundary tests 通过。
- [ ] schema snapshot tests 通过。
- [ ] frontend build 通过。
- [ ] ruff / lint 通过。
- [ ] `git diff --check` 通过。

### 15.5 文档验收

- [ ] `PROJECT_STRUCTURE.md` 与当前硬化状态一致。
- [ ] `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md` 与实际旧路径状态一致。
- [ ] `RS_AGENT_MIGRATION_VALIDATION_EVIDENCE.md` 或新 evidence 文档记录最终验证。
- [ ] `ENGINEERING_NARRATIVE_LOG.md` 有硬化和退役记录。
- [ ] README 推荐阅读顺序包含本文档。
- [ ] 服务启动、测试、部署、gateway smoke 文档可用。

### Phase 11 完成标准

- [ ] 所有 Phase 0-11 勾选项完成。
- [ ] 旧实现退役状态清晰，无职责不明残留。
- [ ] canonical 入口真实承接主链路。
- [ ] 测试、lint、frontend build、gateway smoke 通过。
- [ ] 文档、代码、验证证据一致。
- [ ] 可以认为迁移后硬化与旧路径退役准备完成。

---

## 16. 推荐执行顺序摘要

```text
Phase 0   冻结迁移完成基线
Phase 1   旧路径退役准备与 import 治理
Phase 2   Online 推荐链路真实收束
Phase 3   Agent/RAG 链路硬化
Phase 4   Data/Infra adapter 真实化
Phase 5   Offline 训练评估链路收束
Phase 6   Services API contract 稳定化
Phase 7   Docker / Compose / CI 硬化
Phase 8   观测、诊断与运行报告
Phase 9   前端展示与 display contract 硬化
Phase 10  真实旧实现物理迁移窗口
Phase 11  最终硬化验收
```

建议优先执行：

1. [ ] Phase 0：冻结当前完成基线，避免后续误改原迁移完成口径。
2. [ ] Phase 1：建立 import census、legacy whitelist 和退役等级。
3. [ ] Phase 6 / Phase 7 中的轻量 CI 与 gateway smoke 自动化，先把回归门禁固化。
4. [ ] Phase 2 / Phase 3：分别推进 online 和 Agent/RAG 的真实主入口收束。
5. [ ] Phase 10：等 parity、smoke、CI 都稳定后，再逐目录做物理迁移和删除。

关键执行原则：

- [ ] 先治理边界，再移动实现。
- [ ] 先做 parity tests，再删除旧路径。
- [ ] 先稳定 public contract，再扩大前端/服务依赖。
- [ ] 先 smoke，小样本闭环验证，再考虑全量或重任务。
- [ ] 每次勾选必须有代码、测试、smoke、文档或 grep/import 证据。
- [ ] 不把 compatibility facade 的存在误判为硬化失败；但也不允许 compatibility facade 继续扩展成第二套主线。
