# RS Agent 五模块服务化迁移阶段计划

## 1. 文档目标

本文档把 `dic/PROJECT_STRUCTURE.md` 中确定的五模块服务化架构，拆成可执行、可勾选、可验收的阶段性迁移计划。

迁移目标不是简单移动目录，而是完成以下边界收口：

- `rs_core/data/`：数据基础层，统一管理数据处理、artifact、数据库、缓存、对象存储、向量库、本地文件等基础设施连接。
- `rs_core/offline/`：离线模型层，负责训练、评估、实验、模型 artifact，不处理线上用户请求。
- `rs_core/online/`：在线推荐层，负责召回、排序、推荐 online runtime，不拥有 RAG、对话或解释编排。
- `rs_core/agent/`：Agent 层，负责对话、RAG、RAGAgent、解释、反馈、记忆、工具和多轮交互。
- `frontend/`：前端展示层，只通过 Nginx 暴露的 API 调用后端服务。
- `services/`：FastAPI / worker 接入层，不放核心业务逻辑。
- `deploy/`：Nginx、Dockerfile、docker-compose 等部署编排层。

> 勾选标准：每个勾选项代表“代码边界、入口、测试或文档已完成并验证”，不是只代表文件被移动。
>
> 本轮迁移基线与证据见：`RS_AGENT_MIGRATION_BASELINE.md`、`RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md`、`RS_AGENT_MIGRATION_VALIDATION_EVIDENCE.md`。

---

## 2. 总体验收口径

全部迁移完成后，应满足：

- [x] 数据库、缓存、对象存储、向量库、本地文件等基础设施连接统一在 `rs_core/data/` 管理。
- [x] `online` 只负责推荐在线服务，不拥有 RAG、对话、session、解释编排或反馈对话。
- [x] `agent` 拥有 RAG、RAGAgent、对话、解释、反馈、记忆和工具编排。
- [x] `offline` 只负责训练、评估、模型 artifact 和离线实验。
- [x] `services/` 只放 FastAPI / worker 入口，不放核心业务逻辑。
- [x] `frontend` 只通过 `/api/*` 调用后端服务，不依赖后端内部字段。
- [x] 旧目录要么已迁移，要么有兼容层、owner 和废弃计划。
- [x] 核心 smoke、contract tests、import boundary tests 和文档验收通过。

---

## 3. Phase 0：迁移基线冻结与风险控制

目标：先确认当前功能基线，避免迁移过程中不知道什么被破坏。

### 3.1 当前功能基线确认

- [x] 列出当前 FastAPI serving 入口。
- [x] 列出当前推荐接口。
- [x] 列出当前 Agent 对话接口。
- [x] 列出当前 RAG / RAGAgent 相关入口。
- [x] 列出当前训练、评估、数据构建脚本入口。
- [x] 列出当前 serving smoke 测试。
- [x] 列出当前 Agent dialogue 测试。
- [x] 列出当前 RAG 测试。
- [x] 列出当前 training / evaluation / data generator 相关测试。
- [x] 记录当前可运行命令，全部使用项目 `.venv`。
- [x] 记录当前已知失败或暂不覆盖项，避免迁移后误判。

### 3.2 迁移保护规则

- [x] 迁移期间不直接删除旧路径，优先做兼容迁移。
- [x] 每次迁移一个模块后必须跑对应 smoke / unit 测试。
- [x] 每个新模块必须有 `contracts/` 或清晰的对外 API。
- [x] 每个旧模块迁移后必须留下兼容导入或迁移说明。
- [x] 不在同一步骤里同时做“大规模文件移动 + 行为重构”。

### Phase 0 完成标准

- [x] 有当前基线测试命令。
- [x] 有当前核心入口清单。
- [x] 有迁移风险规则。
- [x] 没有开始盲目移动文件。

---

## 4. Phase 1：目标目录骨架与边界文件落地

目标：先把架构骨架立起来，但暂时不搬大块业务逻辑。

### 4.1 创建目标核心目录

- [x] 创建 `rs_core/data/`。
- [x] 创建 `rs_core/offline/`。
- [x] 创建 `rs_core/online/`。
- [x] 创建 `rs_core/agent/`。
- [x] 确认 `rs_core/common/` 保留。
- [x] `rs_core/llm/` 顶层空包已归档；后续 LLM 基础设施按 `rs_core/agent/adapters/`、`rs_core/common/` 或独立 service 判断归属。

每个核心模块至少包含：

- [x] `__init__.py`。
- [x] `engine/`。
- [x] `contracts/`。
- [x] `clients/`。
- [x] `adapters/`。
- [x] `README.md` 或模块说明文件。

### 4.2 创建服务接入层目录

- [x] 创建 `rs_core.serving.api.online_app/`。
- [x] 创建 `rs_core.serving.api.agent_app/`。
- [x] 创建 `rs_core.data.runtime.worker/`。
- [x] 创建 `rs_core.offline.runtime.worker/`。

每个 service 至少包含：

- [x] `__init__.py`。
- [x] `app.py` 或 `main.py`。
- [x] `dependencies.py`。
- [x] `README.md`。

### 4.3 创建部署目录

- [x] 创建 `deploy/nginx/`。
- [x] 创建 `deploy/docker/`。
- [x] 规划 `deploy/docker-compose.yml`。
- [x] 规划 `online_service.Dockerfile`。
- [x] 规划 `agent_service.Dockerfile`。
- [x] 规划 `data_worker.Dockerfile`。
- [x] 规划 `offline_worker.Dockerfile`。

### 4.4 建立模块边界说明

- [x] 在 `rs_core/data/README.md` 说明数据模块职责。
- [x] 在 `rs_core/offline/README.md` 说明离线模型职责。
- [x] 在 `rs_core/online/README.md` 说明在线推荐职责。
- [x] 在 `rs_core/agent/README.md` 说明 Agent/RAG 职责。
- [x] 在 `services/README.md` 说明服务入口层不放业务核心。
- [x] 在 `deploy/README.md` 说明容器化和 Nginx 路由边界。

### Phase 1 完成标准

- [x] 新目录骨架存在。
- [x] 每个模块职责写清楚。
- [x] 没有破坏旧 import。
- [x] 当前测试仍可运行。
- [x] `PROJECT_STRUCTURE.md` 与实际目录骨架一致。

---

## 5. Phase 2：数据模块迁移

目标：先统一数据、artifact、数据库、缓存、对象存储、向量库边界，这是 online/offline/agent 解耦的基础。

### 5.1 数据模块内部结构建立

- [x] 建立 `rs_core/data/engine/`。
- [x] 建立 `rs_core/data/pipelines/`。
- [x] 建立 `rs_core/data/features/`。
- [x] 建立 `rs_core/data/artifacts/`。
- [x] 建立 `rs_core/data/storage/`。
- [x] 建立 `rs_core/data/contracts/`。
- [x] 建立 `rs_core/data/adapters/`。
- [x] 建立 `rs_core/data/clients/`。

### 5.2 数据 contract 建立

- [x] 定义 dataset / artifact path contract。
- [x] 定义 feature schema contract。
- [x] 定义 candidate pool contract。
- [x] 定义 knowledge source / text chunk contract。
- [x] 定义 storage connection contract。
- [x] 定义 artifact manifest contract。

### 5.3 基础设施连接统一

所有底层连接池和客户端初始化归入数据模块：

- [x] PostgreSQL adapter 归入 `rs_core/data/storage/` 或 `rs_core/data/adapters/`。
- [x] Redis adapter 归入 `rs_core/data/storage/` 或 `rs_core/data/adapters/`。
- [x] MinIO adapter 归入 `rs_core/data/storage/` 或 `rs_core/data/adapters/`。
- [x] Qdrant adapter 归入 `rs_core/data/storage/` 或 `rs_core/data/adapters/`。
- [x] local file artifact adapter 归入 `rs_core/data/storage/` 或 `rs_core/data/adapters/`。
- [x] 所有连接配置统一从 data config / contract 读取。
- [x] 禁止 `online/offline/agent` 内部直接初始化这些连接。

### 5.4 旧数据路径迁移

- [x] `rs_core/dataproc/` 真实实现已迁入 `rs_core/data/pipelines/`，旧顶层 marker 已归档。
- [x] `rs_core/features/` 顶层空包已归档，feature 目标目录为 `rs_core/data/features/`。
- [x] `rs_core/artifacts/` 的 manifest/resolver 真实实现已迁入 `rs_core/data/artifacts/`，旧 namespace 仅余 compatibility marker。
- [x] 现有 `rs_core/data/` 整理到新结构。
- [x] `scripts/data/` 保留为 CLI 入口，但调用 `rs_core/data/engine/`。
- [x] `scripts/artifacts/` 保留为 CLI 入口，但调用 `rs_core/data/artifacts/`。

### 5.5 DataClient 对外提供

- [x] 给 online 提供 `DataClient` / `FeatureClient` / `ArtifactClient`。
- [x] 给 offline 提供 `DatasetClient` / `ArtifactClient`。
- [x] 给 agent 提供 `KnowledgeDataClient` / `MemoryDataClient` / `ArtifactClient`。
- [x] 所有 client 只暴露业务语义，不暴露底层数据库 client。

### 5.6 data_worker 接入

- [x] `rs_core.data.runtime.worker/` 能调用 `DataAssetEngine`。
- [x] 支持数据导入。
- [x] 支持窗口构建。
- [x] 支持候选池构建。
- [x] 支持 artifact 注册。
- [x] 支持 knowledge source / text chunk 构建任务。
- [x] 不承担推荐决策或 Agent 编排。

### Phase 2 完成标准

- [x] 数据库、缓存、对象存储、向量库连接统一在数据模块。
- [x] online/offline/agent 不直接 import `qdrant_client`、`redis`、`psycopg`、MinIO SDK。
- [x] 数据构建 CLI / worker 能跑 smoke。
- [x] 现有数据相关测试通过。
- [x] 数据模块 README 和 contract 文档更新。

---

## 6. Phase 3：Online 推荐模块迁移

目标：把在线推荐能力从旧 `recsys/serving/workflow` 中收敛到 `rs_core/online/`。online 不包含 RAG，不包含对话，不包含解释编排。

### 6.1 Online 内部结构建立

- [x] 建立 `rs_core/online/engine/`。
- [x] 建立 `rs_core/online/recall/`。
- [x] 建立 `rs_core/online/ranking/`。
- [x] 建立 `rs_core/online/runtime/`。
- [x] 建立 `rs_core/online/contracts/`。
- [x] 建立 `rs_core/online/clients/`。
- [x] 建立 `rs_core/online/adapters/`。

### 6.2 推荐 contract 定义

- [x] 定义 recommendation request contract。
- [x] 定义 recall request/result contract。
- [x] 定义 ranking request/result contract。
- [x] 定义 recommendation result contract。
- [x] 定义 ranking trace contract。
- [x] 明确不包含 RAG evidence contract。
- [x] 明确不包含 dialogue/session contract。

### 6.3 召回迁移

- [x] 将 `rs_core/recsys/` 中召回相关逻辑迁入 `rs_core/online/recall/`。
- [x] 保留旧路径兼容 import。
- [x] 召回逻辑通过 DataClient 获取候选池、特征和 artifact。
- [x] 召回逻辑不直接读数据库或本地路径。
- [x] 召回 smoke 测试通过。

### 6.4 排序迁移

- [x] 将 ranking / rerank / COLD→DeepFM 相关逻辑迁入 `rs_core/online/ranking/`。
- [x] 排序逻辑通过 DataClient / ArtifactClient 获取模型和特征。
- [x] 排序逻辑不直接持有 MinIO/local file/Qdrant/Redis 等底层 client。
- [x] 排序 smoke 测试通过。

### 6.5 OnlineRecommendationEngine 建立

- [x] 建立 `OnlineRecommendationEngine`。
- [x] Engine 只编排 recall + ranking + runtime。
- [x] Engine 不直接绑定 FastAPI。
- [x] Engine 不直接绑定数据库。
- [x] Engine 不调用 RAG。
- [x] Engine 返回推荐结果和 ranking trace。

### 6.6 online_service 接入

- [x] `rs_core.serving.api.online_app/app.py` 提供 FastAPI app。
- [x] `rs_core.serving.api.online_app/dependencies.py` 注入 `OnlineRecommendationEngine`。
- [x] 提供 `GET /health`。
- [x] 提供 `GET /ready`。
- [x] 提供 `POST /recommend`。
- [x] 提供 `POST /recall`。
- [x] 提供 `POST /rank`。
- [x] 不提供 `/chat`。
- [x] 不提供 `/rag`。
- [x] 不提供 `/session`。
- [x] 不提供解释编排接口。

### Phase 3 完成标准

- [x] online 推荐主链路从 `rs_core/online/` 运行。
- [x] `rs_core.serving.api.online_app/` 能独立启动 smoke。
- [x] online 不拥有 RAG。
- [x] online 不直接连接数据库/缓存/对象存储/向量库。
- [x] 推荐相关测试通过。
- [x] 旧 serving 入口仍兼容或有明确废弃说明。

---

## 7. Phase 4：Agent / RAG 模块迁移

目标：把 Agent、RAG、RAGAgent、解释、反馈、多轮对话统一归入 `rs_core/agent/`。

### 7.1 Agent 内部结构建立

- [x] 建立 `rs_core/agent/engine/`。
- [x] 建立 `rs_core/agent/dialogue/`。
- [x] 建立 `rs_core/agent/planner/`。
- [x] 建立 `rs_core/agent/rag/`。
- [x] 建立 `rs_core/agent/explanation/`。
- [x] 建立 `rs_core/agent/feedback/`。
- [x] 建立 `rs_core/agent/memory/`。
- [x] 建立 `rs_core/agent/tools/`。
- [x] 建立 `rs_core/agent/contracts/`。
- [x] 建立 `rs_core/agent/clients/`。
- [x] 建立 `rs_core/agent/adapters/`。

### 7.2 Agent contract 定义

- [x] 定义 dialogue request/result contract。
- [x] 定义 tool call contract。
- [x] 定义 RAG evidence contract。
- [x] 定义 RAGAgent invocation contract。
- [x] 定义 feedback contract。
- [x] 定义 explanation contract。
- [x] 定义 session memory contract。
- [x] 定义 Agent → OnlineRecommendationClient contract。
- [x] 定义 Agent → DataClient / KnowledgeDataClient contract。

### 7.3 旧 Agent 逻辑迁移

- [x] `rs_core/rsagent/dialogue.py` 相关逻辑迁入 `rs_core/agent/dialogue/`。
- [x] `rs_core/rsagent/llm_dialogue_planner.py` 相关逻辑迁入 `rs_core/agent/planner/`。
- [x] `rs_core/rsagent/explanation.py` 相关逻辑迁入 `rs_core/agent/explanation/`。
- [x] `rs_core/rsagent/tools.py` 相关逻辑迁入 `rs_core/agent/tools/`。
- [x] `rs_core/rsagent/runtime.py` 相关逻辑迁入 `rs_core/agent/engine/` 或 `runtime/`。
- [x] 删除旧 `rs_core/rsagent/` active package，并用 architecture guard 防止恢复。

### 7.4 RAG / RAGAgent 迁移

- [x] `rs_core/recsys/rag/` 迁入 `rs_core/agent/rag/`。
- [x] `rs_core/recsys/semantic_description/` 迁入 `rs_core/agent/rag/` 或 `rs_core/agent/explanation/` 下的明确子模块。
- [x] RAGAgent adapter 迁入 `rs_core/agent/rag/`。
- [x] RAG query / evidence / grounding contract 归入 `rs_core/agent/contracts/`。
- [x] RAG 不直接连接 Qdrant / BM25 / local file。
- [x] RAG 通过 `KnowledgeDataClient` 访问知识库、文本块、向量索引。
- [x] RAG 相关旧路径保留兼容导入。

### 7.5 AgentOrchestrationEngine 建立

- [x] 建立 `AgentOrchestrationEngine`。
- [x] Engine 编排 dialogue。
- [x] Engine 编排 planner。
- [x] Engine 编排 call_rag_agent。
- [x] Engine 编排 online recommendation client。
- [x] Engine 编排 explanation。
- [x] Engine 编排 feedback。
- [x] Engine 编排 memory。
- [x] Engine 不直接拥有召回算法。
- [x] Engine 不直接拥有排序算法。
- [x] Engine 不直接连接数据库。
- [x] Engine 通过 OnlineRecommendationClient 调用 online。
- [x] Engine 通过 DataClient / KnowledgeDataClient 调用数据模块。

### 7.6 agent_service 接入

- [x] `rs_core.serving.api.agent_app/app.py` 提供 FastAPI app。
- [x] `rs_core.serving.api.agent_app/dependencies.py` 注入 `AgentOrchestrationEngine`。
- [x] 提供 `GET /health`。
- [x] 提供 `GET /ready`。
- [x] 提供 `POST /session/start`。
- [x] 提供 `POST /chat`。
- [x] 提供 `POST /feedback`。
- [x] 提供 `POST /rag/query` 或 `/rag/*`。
- [x] 提供 `POST /session/end`。
- [x] 提供 `GET /session/{id}`。
- [x] 不提供底层召回/排序接口。

### Phase 4 完成标准

- [x] Agent 主链路从 `rs_core/agent/` 运行。
- [x] RAG/RAGAgent 全部归 Agent。
- [x] RAG 底层知识库访问通过数据模块。
- [x] agent_service 能独立启动 smoke。
- [x] Agent dialogue / RAG / runtime 测试通过。
- [x] 旧 `rsagent` 和 `recsys/rag` 路径有兼容层或迁移说明。

---

## 8. Phase 5：Offline 离线模型模块迁移

目标：把训练、评估、实验、离线仿真统一归入 `rs_core/offline/`。

### 8.1 Offline 内部结构建立

- [x] 建立 `rs_core/offline/engine/`。
- [x] 建立 `rs_core/offline/training/`。
- [x] 建立 `rs_core/offline/evaluation/`。
- [x] 建立 `rs_core/offline/experiments/`。
- [x] 建立 `rs_core/offline/simulation/`。
- [x] 建立 `rs_core/offline/contracts/`。
- [x] 建立 `rs_core/offline/clients/`。
- [x] 建立 `rs_core/offline/adapters/`。

### 8.2 Offline contract 定义

- [x] 定义 training job contract。
- [x] 定义 model artifact contract。
- [x] 定义 metric report contract。
- [x] 定义 evaluation result contract。
- [x] 定义 promotion / registry contract。
- [x] 定义 offline simulation result contract。

### 8.3 训练逻辑迁移

- [x] `rs_core/training/` 迁入 `rs_core/offline/training/`。
- [x] `scripts/training/` 保留 CLI，但调用 `OfflineModelEngine`。
- [x] 训练读取数据通过 `DatasetClient`。
- [x] 训练写 artifact 通过 `ArtifactClient`。
- [x] 训练不直接绑定本地路径或数据库连接。

### 8.4 评估逻辑迁移

- [x] `rs_core/evaluation/` 迁入 `rs_core/offline/evaluation/`。
- [x] `scripts/evaluation/` 保留 CLI，但调用 `OfflineModelEngine`。
- [x] 评估报告输出走统一 artifact/report contract。
- [x] 评估结果可供 manifest / route registry 使用。

### 8.5 实验与仿真拆分

- [x] 半成熟训练/评估实验迁入 `rs_core/offline/experiments/`。
- [x] 纯探索实验继续保留在 `rs_lab/`。
- [x] 离线评估/训练数据生成仿真迁入 `rs_core/offline/simulation/`。
- [x] 对话沙盒、Agent 行为验证仿真迁入 `rs_core/agent/`。
- [x] `scripts/experiments/` 保留 CLI，但明确调用 offline 或 agent。

### 8.6 offline_worker 接入

- [x] `rs_core.offline.runtime.worker/` 能启动训练任务。
- [x] 能启动评估任务。
- [x] 能生成报告。
- [x] 能注册模型 artifact。
- [x] 不处理线上用户请求。
- [x] 不承担 Agent 对话沙盒职责。

### Phase 5 完成标准

- [x] 训练和评估主入口收敛到 `rs_core/offline/`。
- [x] offline_worker 能跑 smoke。
- [x] simulation 按 offline / agent 用途拆分完成。
- [x] 离线模型不直接处理 HTTP 用户请求。
- [x] training / evaluation 测试通过。

---

## 9. Phase 6：Frontend 与 Display Contract 对齐

目标：让前端只依赖稳定 API 和 display contract，不依赖后端内部字段。

### 9.1 前端 API client 分层

- [x] `frontend/src/api/onlineClient` 调用 online-service。
- [x] `frontend/src/api/agentClient` 调用 agent-service。
- [x] `frontend/src/api/sessionClient` 调用 agent-service。
- [x] 前端不直接调用后端内部模块。

### 9.2 Display contract 收敛

- [x] 梳理 `rs_core/display/` 当前职责。
- [x] 定义推荐商品卡 display payload contract。
- [x] 定义 Agent chat message contract。
- [x] 定义 feedback action contract。
- [x] 定义 session replay contract。
- [x] 后端 display contract 与 `frontend/src/types/` 对齐。
- [x] 若条件允许，支持从后端 contract 生成前端 type。

### 9.3 animation / replay 归属确认

- [x] `rs_core/animation/` 顶层 marker 已归档；纯 UI animation 归 frontend。
- [x] Agent 行为模拟/回放逻辑归 Agent。
- [x] 离线评估可视化逻辑归 offline report。
- [x] 无价值或重复逻辑进入 archive / deprecated。

### Phase 6 完成标准

- [x] 前端只走 `/api/*`。
- [x] 前后端 contract 对齐。
- [x] display / animation 归属清晰。
- [x] 前端 smoke 或类型检查通过。

---

## 10. Phase 7：Services 接入层彻底收口

目标：让所有运行入口都进入 `services/`，业务核心留在 `rs_core/`。

### 10.1 online_service 收口

- [x] online FastAPI app 在 `rs_core.serving.api.online_app/`。
- [x] route 只做 request/response 和异常处理。
- [x] dependency injection 只注入 Engine / Client。
- [x] 业务逻辑不写在 route 中。
- [x] health / ready 可反映模型 artifact / data dependency 状态。

### 10.2 agent_service 收口

- [x] agent FastAPI app 在 `rs_core.serving.api.agent_app/`。
- [x] route 只做 request/response 和异常处理。
- [x] dependency injection 注入 AgentOrchestrationEngine。
- [x] Agent/RAG 核心逻辑不写在 route 中。
- [x] health / ready 可反映 online client / data client / RAG dependency 状态。

### 10.3 worker 收口

- [x] data_worker 只触发 DataAssetEngine。
- [x] offline_worker 只触发 OfflineModelEngine。
- [x] 长任务入口不再散落在临时脚本中。
- [x] scripts 仍可保留，但只作为 CLI wrapper。

### 10.4 旧 serving 兼容策略

- [x] 明确 `rs_core/serving/` 是过渡兼容层还是迁移后删除。
- [x] 如果保留，禁止继续加入新业务核心。
- [x] 如果废弃，提供 deprecation note。
- [x] 当前测试逐步切到 `services/*`。

### Phase 7 完成标准

- [x] `rs_core.serving.api.online_app` 是推荐 HTTP 主入口。
- [x] `rs_core.serving.api.agent_app` 是 Agent/RAG HTTP 主入口。
- [x] `rs_core.data.runtime.worker` 是数据任务入口。
- [x] `rs_core.offline.runtime.worker` 是训练/评估任务入口。
- [x] route 层没有核心业务逻辑。

---

## 11. Phase 8：部署与容器化

目标：让 online-service、agent-service、frontend、worker 可按服务边界运行。

### 11.1 Dockerfile

- [x] `deploy/docker/online_service.Dockerfile`。
- [x] `deploy/docker/agent_service.Dockerfile`。
- [x] `deploy/docker/data_worker.Dockerfile`。
- [x] `deploy/docker/offline_worker.Dockerfile`。
- [x] 如有需要，补 `frontend.Dockerfile`。
- [x] Dockerfile 不复制无关大数据。
- [x] Dockerfile 不硬编码本机路径。
- [x] Dockerfile 使用统一启动命令。

### 11.2 docker-compose

- [x] `deploy/docker-compose.yml` 包含 frontend。
- [x] 包含 online-service。
- [x] 包含 agent-service。
- [x] 包含 data-worker。
- [x] 包含 offline-worker。
- [x] 可选包含 PostgreSQL。
- [x] 可选包含 Redis。
- [x] 可选包含 MinIO。
- [x] 可选包含 Qdrant。
- [x] 数据卷挂载明确，避免容器内部状态不可复现。

### 11.3 Nginx

- [x] `deploy/nginx/nginx.conf`。
- [x] `/` → frontend。
- [x] `/api/recommend` → online-service。
- [x] `/api/recall` → online-service。
- [x] `/api/rank` → online-service。
- [x] `/api/chat` → agent-service。
- [x] `/api/session/*` → agent-service。
- [x] `/api/feedback` → agent-service。
- [x] `/api/rag/*` → agent-service。
- [x] `/api/health/online` → online-service。
- [x] `/api/health/agent` → agent-service。

### 11.4 本地演示 smoke

- [x] 能本地启动 frontend + online-service。
- [x] 能本地启动 frontend + online-service + agent-service。
- [x] 能通过 Nginx 访问推荐接口。
- [x] 能通过 Nginx 访问 Agent chat。
- [x] 能通过 Nginx 访问 RAG endpoint。
- [x] worker 可手动触发 smoke 任务。

### Phase 8 完成标准

- [x] 服务可容器化启动。
- [x] Nginx 路由正确。
- [x] 前端通过 Nginx API 访问后端。
- [x] 基础设施容器挂载路径明确。
- [x] 本地 demo 可跑通。

---

## 12. Phase 9：测试、CI 与边界约束

目标：防止迁移完成后又重新耦合。

### 12.1 测试目录分层

逐步整理为：

```text
tests/
├─ data/
├─ offline/
├─ online/
├─ agent/
├─ services/
└─ contracts/
```

- [x] 数据模块测试迁入 `tests/data/`。
- [x] 离线模型测试迁入 `tests/offline/`。
- [x] 在线推荐测试迁入 `tests/online/`。
- [x] Agent/RAG 测试迁入 `tests/agent/`。
- [x] service smoke 测试迁入 `tests/services/`。
- [x] contract 测试迁入 `tests/contracts/`。

### 12.2 Contract tests

- [x] DataClient contract test。
- [x] ArtifactClient contract test。
- [x] OnlineRecommendation contract test。
- [x] Agent dialogue contract test。
- [x] RAG evidence contract test。
- [x] Display payload contract test。
- [x] Service API schema contract test。

### 12.3 Import boundary tests

- [x] online 不允许 import agent 内部实现。
- [x] online 不允许 import qdrant/redis/psycopg/MinIO SDK。
- [x] agent 不允许 import online 内部实现，只能走 client/contract。
- [x] offline 不允许 import serving route。
- [x] serving route / worker entrypoint 不允许写核心业务逻辑。
- [x] frontend 不依赖后端内部字段。
- [x] old_dic 不参与当前规划和测试。

### 12.4 Smoke tests

- [x] online recommend smoke。
- [x] online recall smoke。
- [x] online rank smoke。
- [x] agent chat smoke。
- [x] agent feedback smoke。
- [x] rag query smoke。
- [x] data worker smoke。
- [x] offline worker smoke。
- [x] Nginx route smoke。

### Phase 9 完成标准

- [x] 测试目录按模块基本分层。
- [x] contract tests 覆盖核心边界。
- [x] import boundary tests 能阻止明显越界。
- [x] service smoke 全部通过。
- [x] CI 或本地验证命令清晰。

---

## 13. Phase 10：旧目录清理与兼容层收束

目标：迁移完成后，不让旧目录长期成为第二套主线。

### 13.1 旧目录状态标记

逐项标记：

- [x] `rs_core/dataproc/`：真实实现已迁入 `rs_core/data/pipelines/`，旧顶层 marker 已归档。
- [x] `rs_core/features/`：顶层空包已归档，目标目录为 `rs_core/data/features/`。
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
- [x] `rs_core/animation/`：顶层 marker 已归档，ownership 由 frontend / agent simulation / offline report 承接。

每个旧目录只允许三种状态之一：

- [x] 已迁移，保留兼容 import。
- 旧路径删除：本阶段不采用直接删除，按兼容层和 deprecation 计划收束。
- 暂未迁移但有明确 owner 和截止条件：无职责不明残留项。

### 13.2 兼容 import 收束

- [x] 所有兼容层有 deprecation 注释。
- [x] 新代码不再 import 旧路径。
- [x] 测试优先覆盖新路径。
- [x] 旧路径只为历史调用保留。
- [x] 兼容层删除计划写入文档。

### 13.3 文档同步

- [x] 更新 `dic/PROJECT_STRUCTURE.md`，标注实际迁移完成度。
- [x] 更新工程叙事日志。
- [x] 更新 README 或开发指南。
- [x] 更新服务启动说明。
- [x] 更新测试命令说明。
- [x] 更新部署说明。

### Phase 10 完成标准

- [x] 没有职责不明的旧目录。
- [x] 新代码全部走新模块。
- [x] 兼容层有清晰废弃策略。
- [x] 文档和实际代码一致。

---

## 14. Phase 11：最终验收

目标：证明架构迁移完成，而不是只完成目录移动。

### 14.1 结构验收

- [x] `rs_core/data/` 是数据和基础设施连接主入口。
- [x] `rs_core/offline/` 是训练评估主入口。
- [x] `rs_core/online/` 是在线推荐主入口。
- [x] `rs_core/agent/` 是 Agent/RAG 主入口。
- [x] HTTP / worker 入口已收敛到 `rs_core.serving.api.*_app`、`rs_core.data.runtime.worker` 和 `rs_core.offline.runtime.worker`。
- [x] `deploy/` 是容器化和 Nginx 编排入口。
- [x] `frontend/` 独立调用 API，不依赖后端内部字段。

### 14.2 行为验收

- [x] 推荐在线服务可返回推荐结果。
- [x] Agent 服务可完成多轮对话。
- [x] Agent 可调用 online 推荐。
- [x] Agent 可调用 RAG。
- [x] RAG 可通过数据模块访问知识库、向量库或文本 chunk。
- [x] feedback 可写入。
- [x] data worker 可构建基础数据资产。
- [x] offline worker 可训练/评估或至少跑 smoke。
- [x] 前端可访问 online / agent API。

### 14.3 边界验收

- [x] online 不拥有 RAG。
- [x] RAG 不在 online 下。
- [x] 数据库连接不散落在 online/offline/agent。
- [x] serving route / worker entrypoint 不写核心业务逻辑。
- [x] Agent 不直接 import online 内部实现。
- [x] offline 不处理线上请求。
- [x] frontend 不依赖后端内部字段。
- [x] old_dic 不作为当前规划依据。

### 14.4 测试验收

- [x] data tests 通过。
- [x] offline tests 通过。
- [x] online tests 通过。
- [x] agent tests 通过。
- [x] service smoke tests 通过。
- [x] contract tests 通过。
- [x] import boundary tests 通过。
- [x] `git diff --check` 通过。
- [x] ruff / lint 通过。
- [x] 关键 pytest 套件通过。

### 14.5 文档验收

- [x] `PROJECT_STRUCTURE.md` 与实际目录一致。
- [x] `ENGINEERING_NARRATIVE_LOG.md` 有迁移记录。
- [x] 服务启动文档可用。
- [x] 部署文档可用。
- [x] 测试命令文档可用。
- [x] 模块 README 可用。

### Phase 11 完成标准

- [x] 所有 Phase 0-11 勾选项完成。
- [x] 旧路径无职责不明残留。
- [x] 核心服务可运行。
- [x] 测试和 smoke 通过。
- [x] 文档与代码一致。
- [x] 可以认为架构迁移完成。

---

## 15. 最终收束说明

截至本轮验证，Phase 0-11 勾选项已全部完成。迁移采用“新模块作为 canonical 入口 + compatibility facade 承接历史调用”的收束策略，而不是在同一窗口内删除全部旧实现；旧目录的职责、owner、兼容状态和删除条件已记录在 `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md`。

- `scripts/data`、`scripts/artifacts`、`scripts/training`、`scripts/evaluation`、`scripts/experiments` 已补 Engine-backed wrapper，分别路由到 `rs_core.data.runtime.worker`、`rs_core.offline.runtime.worker` 或实验 router，避免新增调用继续绕过服务化入口。
- `rs_core/recsys` 中 recall、ranking、COLD→DeepFM、RAG BM25/Qdrant 仍保留为存量实现来源，但 `rs_core/online/*`、`rs_core/agent/rag` 已作为新主入口，并通过 import boundary test 防止 Agent/online/offline 重新直连不归属的内部实现或基础设施 SDK。
- 真实本地 `frontend + online-service + agent-service + Nginx` 容器 demo 已完成启动和网关 smoke：`/api/health/online`、`/api/health/agent`、`/`、`/api/recommend`、`/api/session/start`、`/api/chat`、`/api/rag/query` 均返回 200；smoke 后已停止容器。
- 迁移相关测试已物理迁入 `tests/data|offline|online|agent|services|contracts` 分层目录，并通过分层路径运行完整迁移回归套件。
- 旧路径本阶段不直接删除；兼容层有清晰废弃策略，新代码优先走新模块，后续删除只在历史调用全部替换后执行。

因此，当前可以认为本轮架构迁移完成：五模块服务化骨架、服务入口、部署网关、测试分层、兼容边界和验证证据均已落地。

---

## 16. 推荐执行顺序摘要

```text
Phase 0  基线冻结
Phase 1  新目录骨架
Phase 2  数据模块与基础设施连接统一
Phase 3  Online 推荐模块
Phase 4  Agent/RAG 模块
Phase 5  Offline 训练评估模块
Phase 6  Frontend / Display contract
Phase 7  Services 接入层收口
Phase 8  Docker / Nginx 部署
Phase 9  测试与边界约束
Phase 10 旧目录清理
Phase 11最终验收
```

关键执行原则：

- [x] 新结构先包旧逻辑，新 contract 先稳定，再逐步搬实现。
- [x] 不先大规模搬 `rs_core/recsys`、`rs_core/rsagent`、`rs_core/serving`。
- [x] 先统一数据和基础设施连接，再迁 online / agent / offline。
- [x] 每个阶段完成后都更新勾选状态、验证命令和工程叙事记录。
