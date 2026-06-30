# RS Agent 数据库/中间件服务串联路线图

**状态**：项目级执行锚点，源自 `.omc/plans/rs-agent-service-datastores-middleware-plan.md`  
**日期**：2026-06-20  
**用途**：后续 `/team`、`/ralph` 或手工执行时，必须以本路线为准，防止长流程中范围漂移。

## 1. 执行总原则

1. **先闭环，后扩展**：先把本地/受控试用服务跑通、可回放、可验证，再引入生产级中间件。
2. **模块化单体优先**：当前 serving 仍是单进程内存 session，不急于拆微服务。
3. **推荐主链路与实验诊断隔离**：数据库/中间件接入不等于召回、排序 route promotion；禁止 oracle、label、holdout、diagnostic artifact 混入 public serving。
4. **状态分层**：session/turn/feedback、事件流、artifact、RAG evidence、日志指标分别有明确归属。
5. **可回放、可观测、可降级**：每个阶段必须有验收和验证证据。

## 2. 分阶段路线

| 阶段 | 目标 | 允许做 | 禁止提前做 |
|---|---|---|---|
| Phase 0 | 本地/受控试用闭环 | FastAPI 单进程、SQLite/JSONL、local artifact、SQLite FTS5、trial hardening、结构化日志 | MySQL runtime、Redis、RQ、MinIO、Prometheus、Kafka、ClickHouse |
| Phase 1a | 生产兼容合同与 SQL DDL baseline | Store contract、Trace ID、Failure Policy、SQL DDL baseline、schema mapping、governance tests | Alembic、MySQL runtime adapter、测试数据库强依赖 |
| Phase 1b | MySQL facts 最小落地 | CanonicalFactsStore、Store failure policy runtime、ServingOperationUnitOfWork、SQL contract tests | Redis、RQ、ArtifactStore 替换、KnowledgeStore 向量后端、Prometheus |
| Phase 1c | 可替换后端扩展 | Redis、RQ、ArtifactStore、KnowledgeStore、Prometheus client | Kafka/ClickHouse 进入 serving 强依赖 |
| Phase 2 | 生产数据闭环 | Kafka/Redpanda、ClickHouse、MinIO/S3、OpenSearch/Qdrant、Grafana、多实例 | 在未触发规模/多消费者/生产观测需求前提前推进 |

### Qdrant 向量基础层提前通道（2026-06-21）

用户已明确选择 Qdrant 作为后续 RAG 与向量召回的统一向量数据库方向，因此允许提前建设 **可选 Qdrant vector foundation**。这不等同于 Phase 2 全量生产化：

- Qdrant client 只能作为 optional dependency，不进入基础 serving 强依赖。
- 默认配置保持关闭，不改变当前 public serving 行为。
- RAG 只允许作为 candidate-scoped evidence backend，必须继续经过 RAG policy gate，不能用于 candidate generation、ranking input replacement 或 promotion。
- Two-tower 可先接入 Qdrant ANN backend，但必须继续受 train-only manifest、source config 与 no-holdout governance 控制，并保留 local exact vector baseline。
- 当前 BM25F/token 倒排的 `semantic` / `semantic_title_category_expansion` 不被替换；后续 dense 语义召回必须新增 `semantic_vector` source，并单独验证。

## 3. Approval Gate

后续执行必须使用分阶段批准，不允许用一个 `proceed` 做到底：

- `proceed_phase0`：仅批准 Phase 0。
- `proceed_phase0_1a`：批准 Phase 0 + Phase 1a。**当前建议最多批准到此阶段**。
- `proceed_phase1b`：单独批准 Phase 1b；必须先确认 MySQL 测试环境与 `/recommend degraded` 字段位置。
- `proceed_phase1c`：单独批准 Redis/RQ/ArtifactStore/KnowledgeStore/Prometheus。
- `proceed_phase2`：单独批准 Kafka/ClickHouse/Celery/MinIO/S3/Qdrant/OpenSearch/Grafana 等生产扩展。

## 4. Phase 0 必守边界

- 只承诺 `single worker / single process`。
- 对外试运行必须启用 strict auth/token gate。
- CORS 只能允许显式配置的前端 origin，不能默认 `*`。
- 服务重启会丢 active in-memory session；只承诺已落 SQLite/JSONL 的 public export / public timeline 可查。
- SQLite/JSONL 是 public serving 审计与回放底座，不是多实例强一致 session store。

### Phase 0 trial hardening 默认策略

- `comment_public` 默认不超过 500 字符，超长截断并记录 public-safe truncation 标记。
- 对 comment、session public timeline、request summary、JSONL audit export 做敏感字段过滤。
- 禁止 token、cookie、secret、raw prompt、tool trace、diagnostics、oracle、label、holdout、ground_truth、target_item 进入 public export。
- `GET /session/{session_id}` 只导出 public-safe timeline。
- retention 默认：session/public timeline 7 天，request log 14 天，feedback/comment 90 天，simulation namespace 7 天。
- simulation/debug 数据必须进入独立 namespace，不得混入真实 feedback/training 数据。

## 5. Phase 1a 默认路线

- 默认采用 **SQL DDL baseline**。
- Alembic 不进入 Phase 1a，除非用户显式选择作为独立 decision。
- 不实现 MySQL runtime adapter。
- 不要求测试数据库。
- 验证重点是 SQL 文件存在性、表/索引/约束 lint、SQLite/target schema mapping。

## 6. Phase 1b 前置决策

进入 Phase 1b 前必须再次确认：

- MySQL 测试环境：本地、远程，还是可跳过集成测试。
- `/recommend degraded` 放在 response body、metadata、header，还是仅 internal trace。
- active session 是否要求跨服务重启恢复。

## 7. Team/Ralph 执行要求

后续 `/team`、`/ralph`、`/team ralph` 执行必须：

1. 先读取本文件和 `.omc/plans/rs-agent-service-datastores-middleware-plan.md`。
2. 在 handoff 中写明当前批准阶段，默认不得超过 `proceed_phase0_1a`。
3. 任何 worker prompt 必须包含“禁止提前引入 Phase 1b/1c/2 组件”的边界。
4. team stage handoff 必须引用本文件，防止上下文压缩后丢失路线。
5. 若发现任务需要越过当前 approval gate，必须暂停并向用户确认。

## 8. Source of truth

详细规划以以下文件为准：

- `.omc/plans/rs-agent-service-datastores-middleware-plan.md`
- `.omc/plans/open-questions.md`

本文件是项目级摘要锚点；如二者冲突，以 `.omc/plans/rs-agent-service-datastores-middleware-plan.md` 的最新已批准版本为准。

## 9. 本轮 `proceed_phase0_1a` 落地状态（2026-06-20）

本轮只执行 Phase 0 + Phase 1a，未引入 MySQL runtime adapter、Redis/RQ、MinIO、Prometheus、Kafka/ClickHouse、Qdrant/OpenSearch 或多实例生产化。

已落地内容：

- Phase 0 trial hardening：新增 public text/payload sanitizer，覆盖 session public timeline、SQLite persistence、JSONL audit event、request summary 和 session export 的敏感字段过滤。
- Feedback public comment：默认 500 字符截断，并在 SQLite 中记录 `comment_truncated` / `comment_redacted` public-safe 标记。
- Retention/cleanup：在 `SQLiteJsonlServingPersistenceStore.cleanup_expired_public_records()` 中实现 session/public timeline 7 天、request log 14 天、feedback/comment 90 天的清理函数；simulation namespace 7 天作为 Phase 0 policy 常量保留，待 simulation 数据独立 namespace runtime 化。
- Phase 1a Store contract：新增 `rs_core/serving/store_contracts.py`，固化 `LocalAuditStore` fail-open、`CanonicalFactsStore` fail-closed、`DerivedSink` fail-open/retry，并禁止 `SafeServingPersistenceStore` 包裹 strict canonical facts store。
- Phase 1a Trace/RAG contract：固化 `http_request_id`、`operation_id`、`event_id`、`turn_id`、`artifact_manifest_id` 职责，以及 PlanningEvidence 与 FinalExplanationEvidence 分离边界。
- Phase 1a SQL DDL baseline：新增 `configs/serving/schema/phase1a_serving_baseline.sql` 与 `sqlite_to_phase1a_mapping.json`，只作为 schema contract，不包含 Alembic 或 MySQL runtime adapter。

验证证据：

- `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_trial_hardening.py tests/test_serving_store_contracts.py tests/test_serving_migrations.py tests/test_serving_persistence.py tests/test_serving_smoke.py tests/test_session_summary.py -q`：`82 passed, 1 warning`。
- `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check ...`（本轮改动 Python 文件）：`All checks passed!`。
- 独立 code-reviewer 最终复审 `APPROVE`，HIGH/MEDIUM/LOW findings 均为 0。

保留边界：Phase 1b/1c/2 仍需单独批准；`.omc/plans/open-questions.md` 中 MySQL 测试环境、`/recommend degraded` 字段位置、RAG evidence_status、active session 跨重启恢复、MinIO 需求仍为后续 gate。
