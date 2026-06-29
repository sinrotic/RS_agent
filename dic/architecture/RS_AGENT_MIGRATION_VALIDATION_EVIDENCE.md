# RS Agent 架构迁移验证证据

## 迁移完成基线

上一轮五模块服务化迁移已完成并冻结为 hardening 起点：`RS_AGENT_ARCHITECTURE_MIGRATION_PLAN.md` 无未勾选项；`rs_core/data|online|agent|offline`、`services/*`、`deploy/*` 和 `tests/data|online|agent|services|contracts` 已形成 canonical 骨架；旧路径状态与退役条件记录在 `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md`；迁移后继续完善的执行标准记录在 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md`。

当前完成口径仍是“canonical 入口 + compatibility facade + owner/deprecation/retirement 条件”，不等同于旧实现已经全部物理删除。后续旧路径治理以 `RS_AGENT_LEGACY_IMPORT_CENSUS.md` 的 import census 和 hardening 计划 Phase 1-10 为准。

## 本轮已验证命令

均使用项目默认 `.venv`、前端本地 `npm` 或本地 Docker/Compose smoke；未触发重训练、全量评估或大规模数据加载。Docker smoke 只启动 frontend、online-service、agent-service、Nginx gateway，未启动 PostgreSQL/Redis/MinIO/Qdrant infra profile，验证后已 `down` 停止容器。

```bash
.venv/Scripts/python -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/services/test_serving_reorg_compatibility.py tests/agent/test_agent_runtime_contracts.py -q
# 52 passed in 4.37s

.venv/Scripts/python -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_dialogue.py tests/agent/test_agent_runtime.py tests/agent/test_rag_agent_adapter.py tests/agent/test_llm_dialogue_planner.py tests/agent/test_agent_tools.py tests/agent/test_agent_runtime_contracts.py tests/services/test_serving_smoke.py tests/services/test_serving_reorg_compatibility.py tests/services/test_serving_boundary_map.py tests/services/test_serving_run_service.py tests/online/test_online_retrieval_orchestrator.py tests/agent/test_multi_turn_sft_generator.py tests/agent/test_agent_scorecard.py tests/agent/test_agent_eval_artifact.py tests/contracts/test_engineering_contracts.py tests/data/test_postgres_dataset.py tests/data/test_recent_window_materializer.py tests/data/test_build_recall_views.py -q
# 393 passed in 14.64s

.venv/Scripts/python -m ruff check rs_core services scripts/data/engine_cli.py scripts/artifacts/engine_cli.py scripts/training/offline_engine_cli.py scripts/evaluation/offline_engine_cli.py scripts/experiments/engine_cli.py scripts/ci/generate_frontend_types.py tests/contracts/test_architecture_migration_boundaries.py tests/services/test_serving_reorg_compatibility.py tests/agent/test_agent_runtime_contracts.py
# All checks passed!

npm --prefix frontend run build
# tsc && vite build 成功，生成 dist/ 静态产物

docker compose -f deploy/docker-compose.yml --profile frontend --profile online --profile agent --profile gateway up -d --build
# frontend、online_service、agent_service、nginx 镜像构建并启动成功

./.venv/Scripts/python.exe - <<'PY'
# 通过 http://127.0.0.1:8080 验证 Nginx gateway：
# GET /api/health/online, GET /api/health/agent, GET /
# POST /api/recommend, POST /api/session/start, POST /api/chat, POST /api/rag/query
PY
# ('online_health', 200, 'online-service')
# ('agent_health', 200, 'agent-service')
# ('frontend_root', 200, True)
# ('recommend', 200, 'unbound_fallback')
# ('session_start', 200, 'local-session')
# ('chat', 200, 'local-session')
# ('rag', 200, 'KnowledgeDataClient')

docker compose -f deploy/docker-compose.yml --profile frontend --profile online --profile agent --profile gateway down
# gateway smoke 容器和网络已停止并移除

git diff --check
# 仅 Windows CRLF warning，无 whitespace error
```

## 迁移后 hardening Phase 0-1 验证

本轮先执行 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` 的 Phase 0 与 Phase 1：冻结迁移完成基线、补旧路径退役等级、生成 import census，并用 boundary test 固化 compatibility facade whitelist。

```bash
.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py -q
# 20 passed in 0.64s

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/services/test_serving_reorg_compatibility.py tests/agent/test_agent_runtime_contracts.py -q
# 57 passed in 4.89s

.venv/Scripts/python.exe -m ruff check tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!
```

新增/更新证据：

- `RS_AGENT_LEGACY_IMPORT_CENSUS.md`：记录 `rs_core/data|online|agent|offline`、`services`、`scripts`、`tests` 对旧路径的 import census。
- `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md`：补退役等级、允许的 compatibility import、禁止新增 import、parity/smoke 证据、rollback path 和删除前 checklist。
- `tests/contracts/test_architecture_migration_boundaries.py`：新增 new-code legacy import whitelist、services 只允许复用 serving schema、online 不回流 Agent/RAG、offline 不 import service route 等边界测试。

## 迁移后 hardening Phase 7 验证

本轮补充 Docker/Compose/CI 轻量硬化：新增 `.dockerignore` 防止镜像构建上下文包含 `.venv/`、`data/`、`outputs/`、缓存和前端依赖；新增 `scripts/ci/gateway_smoke.py` 与 `scripts/ci/run_gateway_smoke.py`，将 gateway smoke 脚本化并保证结束自动 `down`；新增 `scripts/ci/run_migration_hardening_checks.py`，默认只运行 focused pytest、ruff 和 compose config，不默认启动 infra、frontend build、full-data import 或训练任务。

```bash
.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py
# 58 passed in 4.58s
# All checks passed!
# docker compose config --profiles: agent, frontend, gateway, infra, online, worker

.venv/Scripts/python.exe scripts/ci/gateway_smoke.py --help
# CLI help 输出正常

.venv/Scripts/python.exe scripts/ci/run_gateway_smoke.py --help
# CLI help 输出正常

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py -q
# 21 passed in 0.63s

.venv/Scripts/python.exe -m ruff check tests/contracts/test_architecture_migration_boundaries.py scripts/ci/gateway_smoke.py scripts/ci/run_gateway_smoke.py scripts/ci/run_migration_hardening_checks.py
# All checks passed!
```

## 迁移后 hardening Phase 6 验证

本轮补齐 Services API contract 稳定化：新增 online/agent FastAPI OpenAPI snapshot 生成与校验，前端 `types.ts` 增加 public API request/response 类型，`generate_frontend_types.py` 从静态 re-export 扩展为 public marker、OpenAPI snapshot 存在性和 forbidden internal marker 检查；`frontend/src/api/onlineClient.ts` 只保留 `/recommend`、`/recall`、`/rank` online API，Agent/session 入口继续走 `/session/*`、`/chat`、`/feedback`，demo/simulation 留在 debug/sandbox client。

```bash
.venv/Scripts/python.exe scripts/ci/generate_frontend_types.py
# generated frontend\src\types\index.ts

.venv/Scripts/python.exe scripts/ci/generate_service_openapi_snapshots.py --check
# OpenAPI snapshots are up to date

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py -q
# 24 passed in 0.59s

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/services/test_serving_reorg_compatibility.py tests/agent/test_agent_runtime_contracts.py -q
# 61 passed in 4.44s

.venv/Scripts/python.exe -m ruff check tests/contracts/test_architecture_migration_boundaries.py scripts/ci/generate_frontend_types.py scripts/ci/generate_service_openapi_snapshots.py scripts/ci/gateway_smoke.py scripts/ci/run_gateway_smoke.py scripts/ci/run_migration_hardening_checks.py
# All checks passed!

npm --prefix frontend run build
# tsc && vite build 成功

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --gateway-smoke
# 61 passed in 4.90s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
# docker compose config --profiles: agent, frontend, gateway, infra, online, worker
# gateway smoke: online_health / agent_health / frontend_root / recommend / recall / rank / session_start / chat / feedback / rag 全部 200
```

## 迁移后 hardening Phase 2 局部验证：Online public contract

本轮先补 Phase 2 中最轻量且可稳定落地的 Online public contract：在 `rs_core/online/contracts` 增加 `RecallResult`、`RecallTrace`、`RankingTrace` 和 `POOL_EVIDENCE_FIELD_BOUNDARY`，让 `OnlineRecommendationEngine.recall()` / `rank()` 的 fallback 输出也走 public-safe contract，并明确 pool200 只作 offline evaluation、pool500 只作 recall readiness 或 shadow evidence、shadow evidence 只作 internal diagnostics；新增 `rs_core/online/recall.recall_from_sequence_contract()`，让 fallback recall 经 `CandidatePoolClient.from_item_ids()` 形成 public `RecallResult`；新增 `rs_core/online/ranking/cold_deepfm.py` 作为 COLD→DeepFM online contract wrapper，只允许 diagnostic shadow 计算并保持 public ranked order 不被替换，模型读取经 `ArtifactClient.read_json_artifact()`；新增/扩展 `tests/online/test_online_engine_contracts.py` 直接覆盖 canonical engine 的 `ready`、`recommend`、`recall`、`rank` 输出形态、CandidatePoolClient 读取、每个 recall source helper new-vs-old parity、ranking fallback 与 legacy stable input smoke 对齐、COLD→DeepFM shadow no-promotion、ranking route 经 ArtifactClient 读取 shadow model、oracle/label 字段拒绝、public service 422、pool evidence 边界和 internal marker 不泄漏。默认 hardening 检查已把该 online contract 测试纳入 focused suite。

```bash
.venv/Scripts/python.exe -m pytest tests/online/test_online_engine_contracts.py -q
# 11 passed in 0.48s

.venv/Scripts/python.exe -m ruff check rs_core/data/clients rs_core/online tests/online/test_online_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/online/test_online_engine_contracts.py -q
# 36 passed in 0.70s

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/online/test_online_retrieval_orchestrator.py tests/agent/test_agent_runtime.py tests/services/test_serving_run_service.py tests/online/test_online_engine_contracts.py -q
# 100 passed in 1.24s

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/services/test_serving_reorg_compatibility.py tests/services/test_serving_run_service.py tests/agent/test_agent_runtime.py tests/agent/test_agent_runtime_contracts.py tests/online/test_online_engine_contracts.py tests/online/test_online_retrieval_orchestrator.py -q
# 137 passed in 5.46s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py
# 137 passed in 5.13s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
# docker compose config --profiles: agent, frontend, gateway, infra, online, worker
```

当前 Phase 2 public 入口、recall/ranking contract、schema/gateway、Pool500 no-promotion、serving runtime boundary、旧 single-process demo compatibility 声明和 pool500 runtime host 物理迁入已有轻量验证；旧 `rs_core/workflow/online_recommendation.py` 已降级为 compatibility facade，但不代表旧 workflow 目录整体可删除。

## 迁移后 hardening Phase 2 局部验证：Online 入口清单

本轮继续补 Phase 2 的入口 census：新增 `dic/architecture/RS_AGENT_ONLINE_PHASE2_ENTRYPOINT_INVENTORY.md`，把 `rs_core.serving.api.online_app` + `rs_core/online` canonical boundary、旧 `rs_core/serving` single-process/demo 入口、`OnlinePool500Recommender` runtime host、`scripts/recall/*` artifact/index 构建入口、`rs_core/recsys/ranking.py` 真实 ranking 实现，以及 COLD→DeepFM 离线/诊断/tool 路线拆开记录。该文档用于支撑 hardening plan 中 recall/ranking 调用点梳理的勾选，但不等同于旧路径可删除，也不等同于 recall/ranking parity 已完成。

```bash
# 入口清单基于只读搜索与子代理交叉梳理；未触发训练、全量评估、Docker infra 或外部服务。
# 新增文档：dic/architecture/RS_AGENT_ONLINE_PHASE2_ENTRYPOINT_INVENTORY.md
```

## 迁移后 hardening Phase 3 局部验证：Agent/RAG 入口清单与 contract 证据

本轮启动 Phase 3 Agent/RAG 链路硬化：新增 `dic/architecture/RS_AGENT_PHASE3_AGENT_RAG_ENTRYPOINT_INVENTORY.md`，梳理 `rs_core/agent/*` public facade、`AgentOrchestrationEngine`、`rs_core.serving.api.agent_app`、旧 `rs_core/rsagent`、`rs_core/agent_runtime`、`rs_core/recsys/rag`、RAG index 构建脚本和已存在的 dialogue/planner/tools/runtime/RAG/SFT/service 测试证据。当前结论是：Agent public contract 与 grounding/SFT/RAG projection 证据已较完整，但 `workflow/hybrid_environment.py`、`workflow/facades.py`、旧 serving 和 `agent_runtime` adapter 仍有直接旧路径调用，不能把 facade 误判为旧路径可删除。

```bash
.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_runtime_contracts.py tests/agent/test_agent_runtime.py tests/agent/test_rag_agent_adapter.py tests/agent/test_agent_dialogue.py tests/agent/test_llm_dialogue_planner.py tests/agent/test_agent_tools.py tests/services/test_serving_smoke.py tests/services/test_serving_reorg_compatibility.py -q
# 269 passed in 6.30s

.venv/Scripts/python.exe -m pytest tests/agent/test_multi_turn_sft_generator.py -q
# 37 passed in 7.58s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 335 passed in 14.26s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

## 迁移后 hardening Phase 3 局部验证：Agent facade parity 与 workflow import 收束

本轮继续 Phase 3 中最小安全收束：新增 `rs_core/agent/context`、`rs_core/agent/inference` facade，并把 `rs_core/workflow/hybrid_environment.py` 中可安全替换的 `rs_core.rsagent.*` import 改为 `rs_core.agent.*` facade；新增 `tests/agent/test_agent_facade_parity.py` 固化 dialogue、planner、tools、explanation 新旧 facade parity。当前只证明旧实现可经新 Agent boundary 访问，不代表旧 `rs_core/rsagent` 可删除；`workflow/facades.py`、旧 serving 和 RagAgent adapter 仍需继续治理。

```bash
.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_dialogue.py tests/agent/test_agent_tools.py -q
# 98 passed in 1.20s

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_runtime.py tests/agent/test_agent_runtime_contracts.py tests/agent/test_rag_agent_adapter.py tests/agent/test_agent_dialogue.py -q
# 140 passed in 1.51s

.venv/Scripts/python.exe -m pytest tests/services/test_serving_smoke.py tests/services/test_serving_reorg_compatibility.py tests/services/test_serving_run_service.py tests/contracts/test_architecture_migration_boundaries.py -q
# 115 passed in 5.68s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 339 passed in 14.76s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

## 迁移后 hardening Phase 3 局部验证：RAG artifact data-client 边界

本轮继续收束 RAG/BM25/Qdrant 构建入口与轻量 runtime 路径的数据边界：`KnowledgeDataClient` 新增 local RAG index 与 Qdrant RAG collection 的 `ArtifactPathContract` 表达；`scripts/recall/build_rag_bm25_index.py` 与 `scripts/recall/build_qdrant_rag_index.py` 在 manifest 中写入 `data_client=KnowledgeDataClient` 和 `knowledge_artifact`；`workflow/facades.py` / `workflow/hybrid_environment.py` 的 runtime BM25 index path 解析改经 `KnowledgeDataClient.local_rag_index_artifact()`，`workflow/facades.py` 的 Qdrant RAG collection 名称也先经 `qdrant_rag_collection_artifact()` 投影后再交给 retriever。contract test 固化脚本不反向依赖 `rs_core.agent` / `rs_core.rsagent` / `rs_core.agent_runtime`。当前只代表 artifact/path/collection contract 边界增强，不代表 `rs_core/recsys/rag` 底层 retriever 实现已经物理迁移到 data adapter。

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/contracts/test_architecture_migration_boundaries.py::test_rag_build_scripts_declare_data_client_artifact_boundary tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run tests/test_qdrant_config_env.py -q
# 11 passed in 2.09s

.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_dialogue.py tests/agent/test_rag_agent_adapter.py -q
# 87 passed in 1.75s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 351 passed in 25.43s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

## 迁移后 hardening Phase 3 局部验证：旧 rsagent deprecation boundary

本轮补齐 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` Phase 3.2 的旧 namespace 退役治理标记：`rs_core/rsagent/__init__.py` 现在显式声明 deprecated compatibility namespace、替代入口 `rs_core.agent` 和禁止新增 production entrypoint；`tests/contracts/test_architecture_migration_boundaries.py::test_legacy_rsagent_namespace_declares_deprecation_boundary` 固化该边界。当前只代表旧 namespace 有清晰 deprecation note，不代表 `rs_core/rsagent` 真实实现已经迁走或可删除。

```bash
.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py::test_legacy_rsagent_namespace_declares_deprecation_boundary tests/agent/test_agent_facade_parity.py -q
# 5 passed in 0.51s

.venv/Scripts/python.exe -m ruff check rs_core/rsagent/__init__.py tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!
```

## 迁移后 hardening Phase 3 局部验证：Agent simulation sandbox contract

本轮补齐 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` Phase 3.1 的 Agent simulation / sandbox contract：新增 `rs_core.agent.simulation.contracts.AgentSimulationSandboxContract`，固定 schema version、owner、Agent 行为沙盒目的、debug service entrypoints、`rs_core.offline.simulation` 离线边界、public-safe root 字段、forbidden public fields 和约束；`rs_core.agent.simulation` 继续显式导出 legacy scene/batch facade，避免破坏既有 simulation smoke。当前只代表 Agent 行为沙盒和 offline simulation 的 contract 边界已固定，不代表旧 `rs_core/simulation` 真实实现已经物理迁移或 serving 旧 debug endpoint 可删除。

```bash
.venv/Scripts/python.exe -m pytest tests/agent/test_agent_simulation_contract.py tests/contracts/test_architecture_migration_boundaries.py::test_display_animation_and_simulation_ownership_is_documented -q
# 3 passed in 0.49s

.venv/Scripts/python.exe -m ruff check rs_core/agent/simulation tests/agent/test_agent_simulation_contract.py scripts/ci/run_migration_hardening_checks.py
# All checks passed!
```

## 迁移后 hardening Phase 3 局部验证：RAG data adapter contract 初步落地

本轮继续推进 Phase 3.4 的 RAG data adapter 边界：新增 `rs_core.data.contracts.DataAdapterContract`，用 `adapter_id/backend/resource_ref/connection_ref/read_only/metadata` 表达 local BM25 index 与 Qdrant RAG collection；`KnowledgeDataClient.local_rag_index_artifact()` 与 `qdrant_rag_collection_artifact()` 的 artifact metadata 现在携带 `adapter_contract`；BM25/Qdrant 构建脚本 manifest 的 `knowledge_artifact` 因此同时包含 artifact contract 与 adapter contract 证据；runtime BM25 path 与 Qdrant collection name 已从 adapter contract 的 `resource_ref` 投影。随后将 Qdrant env/CLI 配置读取与 vector store 构造收束到 `rs_core.data.adapters.QdrantAdapter`：`scripts/recall/build_qdrant_rag_index.py` 从 `rs_core.data.adapters` 读取 Qdrant 配置 helper，`workflow/facades.py` 不再直接调用 `QdrantVectorStore.from_config()`。因此 Phase 3.4 的“统一经 data adapter contract 管理”按 runtime/script 配置口径已完成；后续又将底层 retriever/vector index 实现物理迁入 `rs_core.agent.rag`，并删除旧 `rs_core.recsys.rag` active package。

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/contracts/test_architecture_migration_boundaries.py::test_rag_runtime_consumes_data_adapter_contract_resource_refs tests/test_rag_core.py::test_qdrant_collection_name_is_derived_from_adapter_resource_ref tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run -q
# 7 passed in 1.88s

.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py::test_agent_and_offline_runtime_entrypoints_use_canonical_facades tests/contracts/test_architecture_migration_boundaries.py::test_new_entrypoint_legacy_imports_are_whitelist_only tests/contracts/test_architecture_migration_boundaries.py::test_rag_build_scripts_declare_data_client_artifact_boundary tests/contracts/test_architecture_migration_boundaries.py::test_rag_runtime_consumes_data_adapter_contract_resource_refs tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run tests/data/test_data_adapter_readiness.py::test_qdrant_adapter_projects_config_and_builds_store -q
# 16 passed in 2.47s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 424 passed in 19.88s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

## 迁移后 hardening Phase 3 局部验证：workflow Agent/RAG facade 继续收束

本轮继续推进 Phase 3 的轻量入口统一：`rs_core/workflow/hybrid_environment.py` 与 `rs_core/workflow/facades.py` 的 runtime RAG import 已从 `rs_core.recsys.rag` 收束到 `rs_core.agent.rag` facade；`rs_core/workflow/hybrid_demo.py` 中已有 facade 支撑的 contracts / feedback / inference import 已改为 `rs_core.agent.contracts`、`rs_core.agent.feedback`、`rs_core.agent.inference`，并在 facade 层补出 `RecommendationTurnResult`、`apply_feedback_to_candidates`、`apply_optional_inference_policy`；随后补齐 `rs_core.agent.decision`、`rs_core.agent.rerank`、`rs_core.agent.model_clients` facade，使 `hybrid_demo.py` 不再直接 import `rs_core.rsagent.decision`、`rs_core.rsagent.feedback_rerank` 或 `rs_core.rsagent.qwen_client`；`scripts/recall/build_rag_bm25_index.py` 与 `scripts/recall/build_qdrant_rag_index.py` 的 RAG 构建符号也改经 `rs_core.agent.rag`。训练/评估脚本侧，`scripts/training/smoke_qwen_training_env.py` 的轻量 config/sample/reward import 改经 `rs_core.offline.training`，`scripts/evaluation/run_simulation_evaluation.py` 与 `scripts/evaluation/run_agent_evaluation.py` 的 simulation import 改经 `rs_core.offline.simulation`。新增 contract test 固化这些入口不回退到旧 import。

当前记录当时只代表可安全替换的 facade import 已继续收束；后续已把 `rs_core/agent_runtime/adapters/rag.py` 真实实现迁入 `rs_core/agent/adapters/rag.py`，删除旧 `rs_core/agent_runtime` active path，并继续将 `rs_core/recsys/rag` 底层实现迁入 `rs_core/agent/rag` 后删除旧 active package。

```bash
.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py::test_agent_and_offline_runtime_entrypoints_use_canonical_facades tests/contracts/test_architecture_migration_boundaries.py::test_script_wrappers_route_to_new_engines tests/offline/test_offline_engine_contracts.py -q
# 15 passed in 0.88s

.venv/Scripts/python.exe -m pytest tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py::test_agent_and_offline_runtime_entrypoints_use_canonical_facades tests/contracts/test_architecture_migration_boundaries.py::test_new_entrypoint_legacy_imports_are_whitelist_only tests/test_rag_core.py::test_rag_bm25_build_script_outputs_usable_index tests/test_qdrant_cli_smoke.py::test_build_qdrant_rag_index_cli_dry_run -q
# 13 passed in 2.05s

.venv/Scripts/python.exe -m ruff check rs_core/workflow/hybrid_environment.py rs_core/workflow/facades.py rs_core/workflow/hybrid_demo.py rs_core/agent/contracts/__init__.py rs_core/agent/feedback/__init__.py rs_core/agent/inference/__init__.py rs_core/agent/decision/__init__.py rs_core/agent/rerank/__init__.py rs_core/agent/model_clients/__init__.py rs_core/agent/rag/__init__.py scripts/training/smoke_qwen_training_env.py scripts/evaluation/run_simulation_evaluation.py scripts/evaluation/run_agent_evaluation.py scripts/recall/build_rag_bm25_index.py scripts/recall/build_qdrant_rag_index.py tests/agent/test_agent_facade_parity.py tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!
```

## 迁移后 hardening Phase 3 当前收束状态

Phase 3 当前已经完成 Agent public API、dialogue/planner/tools/runtime/RAG/grounding/SFT/simulation sandbox、RAG artifact/data-adapter 表达，以及 Agent 不直接 import online recall/ranking 的边界测试。`rs_core/workflow` 与 `scripts/recall` 中可安全替换的 RAG/contract/feedback/inference/decision/rerank/model client import 已继续收束到 `rs_core.agent.*`；因此 `Agent 新代码入口统一走 rs_core/agent` 按 canonical owner 口径可作为本轮完成项。`rs_core/agent_runtime` 已迁入 `rs_core/agent/runtime_core` 与 `rs_core/agent/adapters` 后删除；`rs_core/rsagent` 已迁入 `rs_core/agent/*` 后删除；`rs_core/recsys/rag` 也已迁入 `rs_core/agent/rag` 后删除，并由 import census 与 path-not-exists guard 防恢复。

```bash
.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 424 passed in 19.88s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

## 迁移后 hardening Phase 4 局部验证：Data/Infra adapter readiness 最小闭环

本轮启动 Phase 4 的 Data/Infra adapter 真实化最小竖线：`LocalFileAdapter`、`PostgresAdapter`、`RedisAdapter`、`MinioAdapter`、`QdrantAdapter` 增加 disabled/degraded/ok readiness 输出，remote adapter 在未绑定真实 client 时 fail-open 为 degraded/disabled，不阻塞 online/agent/offline；PostgreSQL readiness 只调用 safe health，不执行 table full count；local file readiness 使用 `project_root` 这类 public config ref，不输出本机绝对路径；remote adapter readiness 对非 env/configured secret-like URL 投影为 `configured`，只输出 public-safe `error_type`。`DataAssetEngine.readiness()` 统一汇总 storage readiness，`rs_core.data.runtime.worker main.py` 新增 `readiness` 命令输出 machine-readable JSON report；`rs_core.data.runtime.worker/__init__.py` 移除对 `main` 的 eager import，避免 `python -m rs_core.data.runtime.worker readiness` 出现 RuntimeWarning。DataClient 侧补齐 dataset manifest/window/freshness、feature schema/view、artifact manifest/checksum/model family、candidate pool size/freshness、memory backend status 与 RAG embedding index metadata 的 contract helper。

当前只代表 adapter readiness/report 与 DataClient contract 轻量闭环已落地，不代表真实 infra client binding 或 infra profile 文档已全部生产化；infra profile 仍不默认启动。

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_data_adapter_readiness.py tests/contracts/test_architecture_migration_boundaries.py::test_target_architecture_packages_are_importable tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight tests/contracts/test_architecture_migration_boundaries.py::test_data_asset_readiness_is_secret_safe -q
# 11 passed in 1.52s

.venv/Scripts/python.exe -m ruff check rs_core/data/adapters/__init__.py rs_core/data/engine/__init__.py rs_core.data.runtime.worker/main.py rs_core.data.runtime.worker/__init__.py tests/data/test_data_adapter_readiness.py tests/contracts/test_architecture_migration_boundaries.py scripts/ci/run_migration_hardening_checks.py
# All checks passed!

.venv/Scripts/python.exe -m pytest tests/data/test_data_clients.py tests/online/test_online_engine_contracts.py -q
# 15 passed in 1.26s

.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight tests/data/test_data_clients.py tests/data/test_data_adapter_readiness.py -q
# 13 passed in 0.68s

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 412 passed in 18.05s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

## 迁移后 hardening Phase 5 局部验证：Offline contract/smoke 最小闭环

本轮启动 Phase 5 的 Offline 训练评估链路收束最小竖线：`rs_core/offline/contracts` 固化 resource estimate、training job、model artifact、metric report、evaluation job/result、experiment run 与 offline simulation result contract；`OfflineModelEngine` 默认只返回 dry-run/smoke contract，不启动重训练、全量评估、模型加载或外部服务。heavy training 或超过本机 14GB 上限的任务会被标记为 `blocked_heavy_job` / `heavy_job=true`，并给出 `remote_or_limited_smoke` 建议。`rs_core.offline.runtime.worker` 支持 training dry-run、model artifact register、evaluation smoke、experiment smoke、simulation smoke 与 resource estimate JSON 输出；`rs_core.offline.runtime.worker/__init__.py` 移除 eager import，保证 `python -m rs_core.offline.runtime.worker ...` 不产生 RuntimeWarning；`scripts/training/offline_engine_cli.py`、`scripts/evaluation/offline_engine_cli.py` 与 `scripts/experiments/engine_cli.py` 路由到 offline worker/engine。

当前只代表 Offline contract/smoke 与 wrapper route 闭环已落地；后续 evaluation 与 simulation 已完成物理迁移并删除旧 active package。训练和成熟实验真实实现仍未物理迁移完成，后续仍需做调用点 census、主路迁移、资源门禁下沉和 artifact manifest 生产化。

```bash
.venv/Scripts/python.exe -m pytest tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py::test_worker_entrypoints_are_engine_backed_and_lightweight -q
# 6 passed in 0.64s

.venv/Scripts/python.exe -m ruff check rs_core/offline rs_core.offline.runtime.worker tests/offline/test_offline_engine_contracts.py tests/contracts/test_architecture_migration_boundaries.py
# All checks passed!

.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --skip-compose-config
# 417 passed in 17.52s
# OpenAPI snapshots are up to date
# generated frontend\src\types\index.ts
# All checks passed!
```

额外只读 verifier 复查 Phase 5 最小实现，结论 `PASS`：指定 offline contracts/engine/worker/CI 文件 py_compile 通过，`python -m rs_core.offline.runtime.worker resource-estimate training --estimated-memory-gb 16 --heavy-job` 输出 `heavy_job: true`、`max_local_memory_gb: 14.0` 与 `recommendation: remote_or_limited_smoke`，且无 `RuntimeWarning`。

随后新增并持续更新 `RS_AGENT_PHASE5_OFFLINE_ENTRYPOINT_CENSUS.md`，记录 Phase 5 后续 legacy 调用点分层：`scripts/training/offline_engine_cli.py`、`scripts/evaluation/offline_engine_cli.py` 与 `scripts/experiments/engine_cli.py` 已路由到 offline worker；`rs_core/offline/training` 仍是 compatibility facade；`rs_core/offline/evaluation` 已改为 canonical implementation 并明确导出 Agent evaluation artifact / scorecard API；`rs_core/offline/simulation` 已承接 simulation schema/policy/presets/runner/model client，旧 `rs_core/simulation` active package 已删除；真实 legacy training implementation 仍在 `rs_core/training/*`；`scripts/training/*.py` 及相关 tests 仍直接覆盖 legacy 训练逻辑。该 census 用于支撑 Phase 5 调用点梳理勾选，但明确不代表旧训练/实验实现可删除。

## 本轮修复过的回归

- `scripts/ci/run_gateway_smoke.py --help` 首次运行时因脚本直接执行无法解析 `scripts.ci.gateway_smoke`，已在脚本顶部把项目根目录加入 `sys.path` 后重试通过。
- `run_migration_hardening_checks.py --gateway-smoke` 首次在 Compose 刚启动后立即请求 health，Nginx upstream 返回 502；已在 `gateway_smoke.py` 增加 online/agent health readiness wait 后重试通过。
- `tests/test_agent_runtime.py` 暴露旧测试 `_Plan` 没有 `response_directive` 字段，`AgentRuntime` 已改为兼容 `getattr(plan, "response_directive", "")`。
- `tests/test_agent_eval_artifact.py` 暴露 rollout safe diagnostics 过滤掉 `constraint_filter_events` / `feedback_rerank_events`，已保留内部训练 artifact 需要的 tool events，同时继续避免 public export 泄漏。
- ruff 暴露新兼容 facade 使用 `import *` 触发 F403，已在兼容层补 `# noqa: F403`；顺手清理 RAG/Qdrant 既有 unused lint。
- 将迁移相关测试迁入 `tests/data|online|agent|services|contracts` 后，修正了按子目录运行时的 `PROJECT_ROOT` 计算，避免测试只在历史平铺目录下通过。
- 首次 Nginx gateway smoke 使用空 `{}` 调 `/api/recommend` 返回 422；已改为符合 `RecommendFromSequenceRequest` 的 `user_sequence` 请求，并补 `/api/session/start` 后再验证 `/api/chat`。

## 已覆盖的边界

- `rs_core/data/adapters` 已提供 PostgreSQL storage facade 之外的 Redis、MinIO、Qdrant、local file adapter contract，并由 `DataAssetEngine.health()` 汇总 storage dependency 状态。
- `rs_core/online`、`rs_core/agent`、`rs_core/offline` 的 import boundary test 验证不直接 import `qdrant_client`、`redis`、`psycopg`、`minio`。
- `rs_core.serving.api.online_app` 只暴露 `/health`、`/ready`、`/recommend`、`/recall`、`/rank`。
- `rs_core.serving.api.agent_app` 暴露 session/chat/feedback/RAG，不暴露底层 `/recall`、`/rank`。
- `data_worker` 和 `offline_worker` 仅触发对应 Engine smoke，不隐式启动重训练或全量任务。
- `deploy/nginx/nginx.conf` 已包含 `/api/recommend`、`/api/recall`、`/api/rank`、`/api/chat`、`/api/session/*`、`/api/feedback`、`/api/rag/*`、`/api/health/online`、`/api/health/agent` 路由。
- `frontend/src/api/` 已按 agent/online/session/demo client 分层，默认 API base 改为 `/api`。
- `tests/data|online|agent|services|contracts` 已承接本轮迁移相关测试，完整迁移回归套件已按分层路径通过。
