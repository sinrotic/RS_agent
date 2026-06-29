# RS Agent Phase 3 Agent/RAG 入口清单

> 目的：为 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` Phase 3 的 Agent/RAG 链路硬化提供可复查证据。本文只记录当前入口、canonical owner、测试证据和后续收束边界；`rs_core/agent_runtime`、`rs_core/rsagent` 与 `rs_core/recsys/rag` 均已物理删除。

## 结论口径

- `rs_core.serving.api.agent_app` 已是新的 Agent HTTP public entrypoint，只暴露 session/chat/feedback/RAG，不暴露底层 `/recall`、`/rank`。
- `rs_core/agent/engine.AgentOrchestrationEngine` 已是 Agent/RAG/dialogue orchestration boundary；推荐能力通过 `OnlineRecommendationClient` 调 online，不直接拥有 recall/ranking。
- `rs_core/agent/*` 已从 facade 推进为 Agent 主实现承接：generic runtime 位于 `rs_core/agent/runtime_core`，RagAgent/MemoryAgent/Recommendation shadow adapter 位于 `rs_core/agent/adapters`；dialogue、planner、tools、explanation、feedback、memory domain、runtime、rerank、model client 与 schema contract 已从旧 `rs_core/rsagent` 迁入 canonical owner；Agent simulation facade 已改指 `rs_core.offline.simulation`；RAG schema/context/retriever/BM25/Elasticsearch/Milvus/local vector/hybrid/build utils 已物理迁入 `rs_core/agent/rag`。
- Phase 3 已按 contract/canonical owner 口径固化 public contract、调用点和测试证据，并把可安全替换的 workflow/script 生产调用点收束到 `rs_core/agent/*` 与 `rs_core/data` adapter；已完成 `rs_core.agent_runtime.core|adapters|contracts` 到 `rs_core.agent.runtime_core|adapters` 的物理迁移、`rs_core.rsagent` 到 `rs_core.agent.*` 的真实实现迁移，以及 `rs_core.recsys.rag` 到 `rs_core.agent.rag` 的真实实现迁移。

## Canonical Agent boundary

| 边界 | 文件/入口 | 当前职责 |
| --- | --- | --- |
| Agent HTTP app | `rs_core.serving.api.agent_app/app.py` | 暴露 `/session/start`、`/chat`、`/feedback`、`/rag/query`、`/session/end`、`/session/{session_id}`。 |
| Canonical engine | `rs_core/agent/engine/__init__.py` | `AgentOrchestrationEngine` 提供 start/chat/feedback/end/export、plan_dialogue、explain、memory_ref、rag_query 与 recommend client boundary。 |
| Agent contract | `rs_core/agent/contracts/__init__.py` | 导出 `DialogueResult`、`ExplanationResult`、`RagResult` 和旧 schema/tool contract。 |
| Online client boundary | `rs_core/online/clients/__init__.py` | Agent 推荐请求经 `OnlineRecommendationClient` 进入 online，不 import online recall/ranking 内部实现。 |
| Data client boundary | `rs_core/data/clients/__init__.py` | Agent RAG/memory 通过 `KnowledgeDataClient`、`MemoryDataClient` 等数据 client 暴露引用。 |

## `rs_core/agent/*` canonical owner 现状

| 新入口 | 当前实现来源 | Phase 3 含义 |
| --- | --- | --- |
| `rs_core/agent/dialogue/__init__.py` | canonical implementation | dialogue 真实实现已从旧 `rs_core.rsagent.dialogue` 迁入。 |
| `rs_core/agent/planner/__init__.py` | canonical implementation | LLM planner 已从旧 `rs_core.rsagent.llm_dialogue_planner` 迁入；`workflow/hybrid_environment.py` 走 canonical Agent path。 |
| `rs_core/agent/tools/__init__.py` | canonical implementation | tool manifest/hidden tool 边界真实实现已迁入；`workflow/hybrid_environment.py` 走 canonical Agent path。 |
| `rs_core/agent/runtime/__init__.py` | canonical implementation | domain-specific Agent runtime 已从旧 `rs_core.rsagent.runtime` 迁入；generic runtime 仍由 `rs_core/agent/runtime_core` 持有。 |
| `rs_core/agent/context/__init__.py` | canonical implementation | context bundle/budget 已从旧 `rsagent.context` 迁入，避免 workflow 直接依赖旧 namespace。 |
| `rs_core/agent/inference/__init__.py` | canonical implementation | rerank inference policy type 已从旧 `rsagent.inference_policy` 迁入。 |
| `rs_core/agent/explanation/__init__.py` | canonical implementation | explanation public output 已从旧 `rsagent.explanation` 迁入。 |
| `rs_core/agent/feedback/__init__.py` | canonical implementation | feedback parser/merge/normalize 已从旧 `rsagent.policy` 迁入。 |
| `rs_core/agent/memory/__init__.py` | canonical implementation | long memory store 已从旧 `rsagent.long_memory` 迁入。 |
| `rs_core/agent/rag/__init__.py` | canonical implementation + `rs_core.agent.adapters.rag`、`rs_core.agent.rag.semantic_description` | RAG schema/context/retriever/BM25/Elasticsearch/Milvus/local vector/hybrid/build utils 已迁入 `rs_core.agent.rag`；RagAgent adapter 位于 `rs_core.agent.adapters.rag`；semantic description 位于 `rs_core.agent.rag.semantic_description`。 |
| `rs_core/agent/simulation/__init__.py` | `rs_core.offline.simulation.*` + `rs_core.agent.simulation.contracts` | Agent 行为沙盒入口作为 public facade 保留 scene/batch 能力，但实现来源已收束到 canonical `rs_core.offline.simulation`，并用 `AgentSimulationSandboxContract` 固化和 offline simulation 的边界。 |

## 仍需治理的旧生产调用点

- `rs_core/workflow/hybrid_environment.py`：已把 dialogue、planner、tools、runtime、context、feedback、schema/inference 类型以及 RagAgent adapter import 收束到 `rs_core.agent.*`；runtime BM25 index path 解析已改经 `KnowledgeDataClient.local_rag_index_artifact()`，RAG retriever/policy/query planning 符号经 canonical `rs_core.agent.rag` 进入；旧 RAG active package 已删除。
- `rs_core/workflow/facades.py`：已把 Agent runtime/adapters/schema 类型收束到 `rs_core.agent.*`；runtime BM25 index path 解析已改经 `KnowledgeDataClient.local_rag_index_artifact()`，Qdrant RAG collection 名称已先经 `qdrant_rag_collection_artifact()` 投影后再交给 retriever；Qdrant 连接配置与 vector store 构造已收束到 `rs_core.data.adapters.QdrantAdapter`；底层 retriever/vector index 实现已归入 `rs_core.agent.rag`，workflow 只通过 Agent/Data 边界消费。
- `rs_core/serving/application/recommendation_service.py`、`rs_core/serving/facades.py` 与 `rs_core/serving/runtime/readiness.py`：旧 single-process service 的 Agent 类型、long memory、context 与 inference readiness import 已收束到 `rs_core.agent.*`；该入口仍是 compatibility demo/service，不代表 serving 旧路径可删除。
- `rs_core/rsagent/`：active package 已删除；dialogue、planner、tools、runtime、context、feedback、inference、explanation、memory、rerank、model client 与 schema contract 已迁入 `rs_core/agent/*`，并由 architecture path-not-exists guard 防止恢复。
- `rs_core/agent_runtime/`：active package 已删除；RagAgent adapter 真实实现已迁入 `rs_core/agent/adapters/rag.py`，底层 RAG 能力已收束到 `rs_core.agent.rag`。
- `scripts/recall/build_rag_bm25_index.py`、`scripts/recall/build_qdrant_rag_index.py`、`scripts/recall/build_milvus_rag_index.py`、`scripts/recall/build_rag_elasticsearch_bm25_index.py`：仍作为 RAG 索引构建脚本入口；manifest 已声明 `KnowledgeDataClient` 与 `knowledge_artifact`，artifact metadata 携带 local BM25 / Qdrant / Milvus / Elasticsearch 的数据边界信息，后续可继续归入 data/knowledge build job 或明确保留为手动 artifact build。

## 已有测试证据

| 领域 | 代表测试 |
| --- | --- |
| Agent public engine / services | `tests/contracts/test_architecture_migration_boundaries.py::test_agent_service_route_table_excludes_low_level_recommendation_routes`、`tests/contracts/test_architecture_migration_boundaries.py::test_agent_engine_calls_online_and_data_clients` |
| Dialogue | `tests/agent/test_agent_dialogue.py`、`tests/agent/test_agent_facade_parity.py` |
| Planner | `tests/agent/test_llm_dialogue_planner.py`、`tests/agent/test_agent_facade_parity.py` |
| Tools / hidden tool boundary | `tests/agent/test_agent_tools.py`、`tests/agent/test_agent_facade_parity.py`、`tests/test_agent_capability_manifest.py` |
| Runtime contract | `tests/agent/test_agent_runtime.py`、`tests/agent/test_agent_runtime_contracts.py` |
| RAG core / RagAgent adapter / projection | `tests/test_rag_core.py`、`tests/test_milvus_rag_index_build.py`、`tests/test_milvus_rag_retriever.py`、`tests/agent/test_rag_agent_adapter.py` |
| Multi-turn SFT grounding | `tests/test_multi_turn_sft_generator.py` |
| Service chat/feedback/RAG smoke | `tests/services/test_serving_smoke.py`、`tests/services/test_serving_reorg_compatibility.py` |
| Agent simulation sandbox | `tests/agent/test_agent_simulation_contract.py`、`tests/contracts/test_architecture_migration_boundaries.py::test_display_animation_and_simulation_ownership_is_documented` |

## Phase 3 最小推进顺序

1. **入口清单与文档门禁**：本文档和 contract test 固化 current canonical owner，避免把 facade-only 误判为真实迁移完成。
2. **生产调用点收束**：`workflow/hybrid_environment.py`、`workflow/facades.py` 与旧 serving 中可安全替换的 Agent/RagAgent runtime import 已改到 `rs_core.agent.*`；RAG BM25 index path 与 Qdrant collection 已先经 `KnowledgeDataClient` artifact contract 投影，artifact metadata 已携带数据 adapter 边界信息。
3. **RAG adapter 边界**：RagAgent adapter 真实实现已迁入 `rs_core/agent/adapters/rag.py`，并可从 `rs_core/agent/rag` 或 `rs_core/agent/adapters` 进入；旧 `rs_core/agent_runtime` active package 已删除。RAG 构建脚本 manifest 已声明 `KnowledgeDataClient` 与 `knowledge_artifact`，底层 BM25/Elasticsearch/Milvus/local vector/hybrid retriever 真实实现已迁入 `rs_core.agent.rag`，后续保留 internal-only projection 和 data adapter 边界测试。
4. **SFT/public display 守门**：复用现有 no-tool/no-display、selected_item_ids、terminal accept、hidden tool tests 作为 Phase 3 grounding 验收证据；Agent simulation sandbox contract 只允许 public display/session 形态，并把离线指标产出边界指向 `rs_core.offline.simulation`。
5. **旧路径退役**：`rs_core/agent_runtime`、`rs_core/rsagent` 与 `rs_core/recsys/rag` 均已完成 import census 清零并物理删除；architecture path-not-exists guard 防止旧路径恢复。
