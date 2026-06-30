# RS Agent 迁移基线

## 当前 FastAPI serving 入口

- 过渡兼容入口：`rs_core.serving.api.factory.create_app()` / `rs_core.serving.api.app:app`。
- 新 online 入口：`rs_core.serving.api.online_app:app`。
- 新 Agent/RAG 入口：`rs_core.serving.api.agent_app:app`。

## 当前推荐接口

- 兼容 serving：`POST /recommend`、`POST /recall`、`POST /feed/refresh`。
- 新 online-service：`POST /recommend`、`POST /recall`、`POST /rank`。

## 当前 Agent 对话接口

- 兼容 serving：`POST /session/start`、`POST /chat`、`POST /feedback`、`POST /session/end`、`GET /session/{session_id}`。
- 新 agent-service：`POST /session/start`、`POST /chat`、`POST /feedback`、`POST /rag/query`、`POST /session/end`、`GET /session/{session_id}`。

## 当前 RAG / RAGAgent 相关入口

- canonical 实现来源：`rs_core.agent.rag`；旧 `rs_core.recsys.rag` 与 `rs_core.agent_runtime.adapters.rag` active path 均已删除。
- 新归属入口：`rs_core.agent.rag`、`rs_core.agent.adapters.rag`、`AgentOrchestrationEngine.rag_query()`、`rs_core.serving.api.agent_app` 的 `/rag/query`。

## 当前训练、评估、数据构建脚本入口

- 数据：`scripts/data/*`、`scripts/artifacts/*`，新 worker smoke 入口为 `python -m rs_core.data.runtime.worker health`。
- 训练：`scripts/training/*`，新 worker smoke 入口为 `python -m rs_core.offline.runtime.worker health`。
- 评估：`scripts/evaluation/*`，新 worker smoke 入口为 `python -m rs_core.offline.runtime.worker run-evaluation-smoke`。

## 当前核心测试入口

- Serving smoke：`tests/services/test_serving_smoke.py`、`tests/services/test_serving_reorg_compatibility.py`、`tests/services/test_serving_boundary_map.py`、`tests/services/test_serving_run_service.py`。
- Agent dialogue/runtime/RAG：`tests/agent/test_agent_dialogue.py`、`tests/agent/test_agent_runtime.py`、`tests/agent/test_rag_agent_adapter.py`、`tests/agent/test_llm_dialogue_planner.py`、`tests/agent/test_agent_tools.py`、`tests/agent/test_agent_runtime_contracts.py`。
- Training / evaluation / data generator：`tests/agent/test_multi_turn_sft_generator.py`、`tests/agent/test_agent_scorecard.py`、`tests/agent/test_agent_eval_artifact.py`。
- 架构迁移边界：`tests/contracts/test_architecture_migration_boundaries.py`。

## 当前可运行命令

```bash
.venv/Scripts/python -m pytest tests/contracts/test_architecture_migration_boundaries.py -q
.venv/Scripts/python -m pytest tests/contracts/test_architecture_migration_boundaries.py tests/agent/test_agent_dialogue.py tests/agent/test_agent_runtime.py tests/agent/test_rag_agent_adapter.py tests/agent/test_llm_dialogue_planner.py tests/agent/test_agent_tools.py tests/agent/test_agent_runtime_contracts.py tests/services/test_serving_smoke.py tests/services/test_serving_reorg_compatibility.py tests/services/test_serving_boundary_map.py tests/services/test_serving_run_service.py tests/online/test_online_retrieval_orchestrator.py tests/agent/test_multi_turn_sft_generator.py tests/agent/test_agent_scorecard.py tests/agent/test_agent_eval_artifact.py tests/contracts/test_engineering_contracts.py -q
.venv/Scripts/python -m ruff check rs_core services tests/contracts/test_architecture_migration_boundaries.py
npm --prefix frontend run build
```

## 已知暂不覆盖项

- 不在本机默认启动 Qdrant/PostgreSQL/MinIO/Redis 容器或做全量导入。
- 不在本机默认跑 Qwen/DeepFM/双塔等重训练任务。
- 旧 `rs_core/recsys`、`rs_core/workflow`、`rs_core/serving` 仍作为过渡实现来源保留，收束状态见 `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md`。

## 迁移保护规则

- 不直接删除旧路径，优先以 compatibility facade 和状态文档过渡。
- 每个新模块必须有 engine/contract/client/adapters 或 README 边界。
- 每次阶段勾选前必须有 smoke、contract test、import boundary 或文档证据。
- 不在同一步骤里同时做大规模文件移动和行为重构。
