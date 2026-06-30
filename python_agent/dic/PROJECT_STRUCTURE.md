# 项目结构编排说明

## 1. 文档目标

本文档用于回答“项目应该如何编排，才能既好用又结构清晰”。当前结论是：**保留 `rs_core` 作为顶层 Python 包，在其内部按业务模块做渐进分区；FastAPI split app、runtime composition、data/offline worker 入口统一收敛到 `rs_core` canonical 路径，`deploy/` 作为容器化与 Nginx 路由层**。

这样既能吸收微服务架构的边界思想，又避免现在一次性把 `rs_core` 物理拆成多个顶层包带来的大规模 import 迁移和回归风险。

实际完成度以当前仓库内容为准；本文档描述目标编排和演进方向，不要求一次性完成所有移动。

迁移执行清单见：`dic/architecture/RS_AGENT_ARCHITECTURE_MIGRATION_PLAN.md`。迁移完成后的进一步 hardening、旧路径退役和真实主入口收束计划见：`dic/architecture/RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md`。后续使用 goal 执行时，原迁移计划用于确认完成基线，后续完善以 hardening 计划的 Phase 勾选项作为阶段完成标准。

当前已落地的实际骨架包括：`rs_core/data`、`rs_core/online`、`rs_core/agent`、`rs_core/offline` 四个核心模块的 engine/contract/client/adapters 边界；`rs_core.serving.api.online_app`、`rs_core.serving.api.agent_app`、`rs_core.data.runtime.worker`、`rs_core.offline.runtime.worker` 四类入口；以及 `deploy/nginx`、`deploy/docker`、`deploy/docker-compose.yml`。旧目录状态和收束条件见：`dic/architecture/RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md`，旧路径 import census 见：`dic/architecture/RS_AGENT_LEGACY_IMPORT_CENSUS.md`，Online Phase 2 入口清单见：`dic/architecture/RS_AGENT_ONLINE_PHASE2_ENTRYPOINT_INVENTORY.md`，Agent/RAG Phase 3 入口清单见：`dic/architecture/RS_AGENT_PHASE3_AGENT_RAG_ENTRYPOINT_INVENTORY.md`，Offline Phase 5 入口与 legacy 调用点清单见：`dic/architecture/RS_AGENT_PHASE5_OFFLINE_ENTRYPOINT_CENSUS.md`，后续退役顺序和验收口径见：`dic/architecture/RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md`。

---

## 2. 推荐目标骨架

```text
RS_agent/
├─ rs_core/                         # 核心业务包：保留顶层包，内部按业务模块渐进分区
│  ├─ data/                         # 目标数据模块：清洗、窗口、特征、artifact、数据库/存储、数据 contract
│  ├─ offline/                      # 目标离线模型：训练、评估、仿真、实验产物
│  ├─ online/                       # 目标在线模型：推荐在线服务，负责召回、排序、online runtime
│  ├─ agent/                        # 目标 Agent 模块：对话、RAG、澄清、解释、反馈、记忆、工具
│  └─ common/                       # Shared Kernel：配置、IO、runtime 等极少通用能力
│
│  # 当前过渡期仍可保留既有目录，逐步迁入上面的目标分区：
│  ├─ data/                                     # dataproc 实现已迁入 rs_core/data/pipelines/；artifact 实现已迁入 rs_core/data/artifacts/；feature 目标目录为 rs_core/data/features/
│  ├─ offline/training/                         # Qwen/SFT/GRPO/GPT SFT 等训练实现 canonical owner；旧 rs_core/training 已退役
│  ├─ online/recall/source_registry/            # 原 recsys recall_sources 治理元数据 canonical owner；旧 rs_core/recsys active package 已删除
│  ├─ serving/ workflow/                        # serving 作为接入层、workflow 存量编排按 owner 继续收束
│  └─ display/                                  # 后端 display payload contract；纯 UI animation 属于 frontend，Agent 行为回放属于 rs_core/agent/simulation，离线可视化属于 offline report
│
├─ rs_core/serving/                 # HTTP 接入层：public app、split app、runtime composition，不放核心业务逻辑
│  ├─ api/online_app.py             # Online split app 部署入口，拥有 /rank
│  ├─ api/agent_app.py              # Agent split app 部署入口，拥有 /rag/query
│  └─ runtime/split_engines.py      # split engine 构造/cache
│
├─ rs_core/data/runtime/worker.py   # 数据导入、数据构建、artifact 构建 worker
├─ rs_core/offline/runtime/worker.py# 离线模型训练/评估 worker
│
├─ frontend/                        # 前端模块：React Web Demo、商品卡、反馈按钮、Session Replay
│
├─ deploy/                          # 部署编排层
│  ├─ nginx/                        # Nginx 路由：frontend + online-service + agent-service
│  ├─ docker/                       # 各服务 Dockerfile
│  │  ├─ online_service.Dockerfile
│  │  ├─ agent_service.Dockerfile
│  │  ├─ data_worker.Dockerfile
│  │  └─ offline_worker.Dockerfile
│  └─ docker-compose.yml            # 本地服务编排
│
├─ scripts/                         # CLI 入口：保留；只触发流程，不承载核心业务逻辑
│  ├─ data/ artifacts/              # 数据模块 CLI
│  ├─ training/ evaluation/ experiments/ # 离线模型 CLI
│  ├─ recall/ serving/              # 在线模型 CLI / smoke
│  ├─ assets/                       # 前端/展示素材生成
│  └─ ci/                           # CI / contract validation
│
├─ configs/                         # 配置：数据口径、离线实验、在线 serving、governance route
├─ tests/                           # 测试：建议后续按 data/offline/online/agent/services/contracts 分层
├─ dic/                             # 当前项目说明、工程叙事、方法报告和规范入口
├─ docs/                            # 对外或通用文档入口；项目叙事优先仍在 dic/
├─ data/                            # 本地数据目录，不作为代码主线，不应默认进 git
├─ outputs/                         # 运行产物、实验输出、报告 artifact，不作为实现逻辑
├─ rs_lab/                          # 纯探索实验；不保证质量，不直接晋升主线
├─ old_dic/                         # 历史草稿，只读归档，不作为当前规划依据
└─ build/、*.egg-info、.ruff_cache、__pycache__/、tmp*/  # 生成物或临时目录
```

---

## 3. 五个业务模块

### 3.1 数据模块 `rs_core/data/`

目标：把原始数据变成线上推荐、离线训练和 Agent/RAG 都能复用的基础资产。数据模块是 online、offline、agent 的底座，不直接承担推荐决策或对话编排；各种数据库、对象存储、向量库、缓存等基础设施连接也统一归入数据模块，通过 contract/client 对外提供。

当前来源：

- `rs_core/data/`（其中 `rs_core/data/pipelines/` 是 dataproc 实现目录，`rs_core/data/features/` 是 feature 目标目录，`rs_core/data/artifacts/` 是 artifact 实现目录，`rs_core/data/vectorstores/` 是 Milvus/vector store client、schema、filter、payload 与 build utils 的 canonical 实现）
- `rs_core/data/artifacts/`（artifact manifest/resolver 的 canonical 实现；旧 `rs_core/artifacts/` compatibility namespace 已退役删除）
- `rs_core/data/vectorstores/`（原 `rs_core/recsys/vectorstores` 中通用向量库基础设施能力已迁入这里；RAG 和 recall 只消费该 data boundary，不再拥有底层 Milvus client）
- `scripts/data/`
- `scripts/artifacts/`
- `configs/recall/`、`configs/ranking/` 中的数据口径和 artifact 路径配置

建议内部形态：

```text
rs_core/data/
├─ engine/             # DataAssetEngine
├─ pipelines/          # 清洗、导入、窗口构建
├─ features/           # 特征工程
├─ artifacts/          # artifact manifest / version / path contract
├─ storage/            # MySQL / Redis / MinIO / Qdrant / local files 等基础设施访问
├─ vectorstores/       # Milvus/vector store client、schema、filter、payload 与 build utils
├─ contracts/          # 数据 schema / loader / storage contract
└─ adapters/           # 具体数据库、缓存、对象存储、向量库、本地文件适配
```

数据模块回答：数据从哪里来，如何清洗，如何形成候选池、特征、知识库原料和 artifact，哪些产物允许被在线模型、离线模型和 Agent 模块读取；同时回答数据库、缓存、对象存储、向量库等基础设施如何接入、治理和暴露给上层模块。

*注：`data/adapters/` 负责管理所有数据库与存储介质（MySQL, MinIO, Redis, Qdrant）的连接池初始化与客户端连接生命周期。其他业务模块（如 `online`、`offline`、`agent`）的 `adapters/` 只负责编写具体的业务查询逻辑，底层一律复用 `data` 统一初始化的连接实例，杜绝在各业务模块内重复编写底层的连接配置与连接池初始化代码。*

#### 3.1.1 Artifact 注册与热更新规范

- **离线注册**：`offline_worker` 或数据 pipeline 将模型或候选集输出后，需将其元数据及哈希注册进 `manifest.json`，并触发 `current_route_registry.yaml` 指向更新。
- **在线热更新**：在线 Serving 服务建立热加载模块（Hot-loader），监听 `current_route_registry.yaml` 的变更。当发现指向的模型或候选池哈希改变时，利用双缓冲加载（Double-Buffering）将新实例载入内存，并安全替换旧指针，实现零停机热升级。

### 3.2 离线模型 `rs_core/offline/`

目标：承接模型训练、离线评估和训练实验，产出可治理的模型/策略 artifact；它不直接处理线上用户请求。

当前来源：

- `rs_core/offline/training/`（Qwen/SFT/GRPO/GPT SFT、judge、reward、multi-turn SFT generator 的 canonical 实现；旧 `rs_core/training/` 已退役删除）
- `rs_core/offline/evaluation/`（Agent evaluation artifact、scorecard，以及离线 ranking/recall evaluation、frozen candidate signature、promotion gate 与 artifact inspection 的 canonical 实现；旧 `rs_core/evaluation/` 已退役删除，旧 `rs_core/recsys/evaluation.py` 已迁入 `rs_core/offline/evaluation/ranking.py`）
- `scripts/training/`
- `scripts/evaluation/`
- `scripts/experiments/`
- `rs_core/offline/simulation/`（离线评估、训练数据生成、simulation schema/policy/runner/model client 的 canonical 实现；旧 `rs_core/simulation/` 已退役删除）

建议内部形态：

```text
rs_core/offline/
├─ engine/             # OfflineModelEngine
├─ training/           # SFT / GRPO / DeepFM / Qwen training
├─ evaluation/         # scorecard / offline metrics / reports
├─ experiments/        # 半成熟训练/评估实验；纯探索仍放 rs_lab/
├─ simulation/         # 仅保留离线评估或训练数据生成相关仿真
├─ contracts/          # model artifact / metric / report contract
└─ adapters/           # artifact store / data client / model registry
```

离线模型模块回答：哪些模型或策略更好，如何证明更好，训练和评估产物如何注册为可治理 artifact。

### 3.3 在线模型 `rs_core/online/`

目标：在可接受延迟内生成推荐候选和排序结果；在线模型只负责推荐在线服务，不拥有 RAG、对话或解释编排。

当前来源：

- `rs_core/online/recall/` 已承接 recall source canonicalization、fallback merge、candidate merge、candidate store、pool500 artifacts、two-tower query/source manifest/vector index、Milvus two-tower build/backfill，以及 `source_registry/` recall source readiness 元数据；旧 `rs_core/recsys/` active package 已删除
- `rs_core/serving/application/` 中与推荐 online runtime 有关的逻辑
- `rs_core/workflow/` 中与 candidate/ranking route 有关的编排
- `scripts/recall/`
- `scripts/serving/`

建议内部形态：

```text
rs_core/online/
├─ engine/             # OnlineRecommendationEngine
├─ recall/             # recall / candidate retrieval
├─ ranking/            # ranking / rerank / COLD→DeepFM
├─ runtime/            # online runtime，不含 FastAPI route
├─ contracts/          # recommendation request/result/ranking trace contract
├─ clients/            # DataClient / ArtifactClient；数据库连接由数据模块封装
└─ adapters/           # 推荐算法运行时适配，不直接持有数据库/向量库/缓存 client
```

在线模型不拥有 RAG。它只负责推荐候选、召回、排序和 online runtime；如果推荐结果需要解释证据，由 Agent/RAG 模块通过 contract/client 消费推荐结果并补充 grounding。在线模型需要数据、特征、候选池或 artifact 时，通过数据模块暴露的 client/contract 访问，不直接连接 MySQL、Redis、MinIO、Qdrant 等基础设施。

### 3.4 Agent 模块 `rs_core/agent/`

目标：把自然语言需求转成可执行推荐约束，并负责对话、RAG、解释、反馈和多轮交互。Agent 相关能力都归入这里，包括 RAGAgent、证据检索、grounding 和对话沙盒。

当前来源：

- `rs_core/agent/`：Agent 对话、工具、运行时、memory、planner、feedback、rerank、model client 与 contract 的 canonical owner；旧 `rs_core/rsagent/` 已迁入后删除
- `rs_core/agent/runtime_core/`：generic runtime core，已从旧 `rs_core/agent_runtime/core` 迁入
- `rs_core/agent/adapters/`：RagAgent / MemoryAgent / Recommendation shadow adapter，已从旧 `rs_core/agent_runtime/adapters` 迁入
- `rs_core/agent/rag/`：RAG schema/context/retriever/BM25/Elasticsearch/Milvus/local vector/hybrid/build utils 的 canonical owner；旧 `rs_core/recsys/rag/` 已迁入后删除
- `rs_core/agent/rag/semantic_description/`：semantic description retrieval/scoring/index store 已从旧 `rs_core/recsys/semantic_description` 迁入
- `rs_core/agent/simulation/`：Agent sandbox contract/facade，复用 `rs_core/offline/simulation` 的 canonical scene/batch runner

建议内部形态：

```text
rs_core/agent/
├─ engine/             # AgentOrchestrationEngine
├─ dialogue/           # 多轮对话
├─ planner/            # 需求澄清、工具选择
├─ rag/                # RAGAgent / evidence retrieval / grounding
├─ runtime_core/       # generic Agent runtime core
├─ adapters/           # RagAgent / MemoryAgent / Recommendation shadow adapter
├─ explanation/        # 推荐解释
├─ feedback/           # feedback 响应
├─ memory/             # long memory / session memory
├─ tools/              # Agent 工具边界
├─ contracts/          # Agent tool / RAG evidence / dialogue contract
└─ clients/            # OnlineRecommendationClient / DataClient / MemoryClient
```

Agent 模块可以调用在线模型，但不直接拥有召回和排序算法。RAG 属于 Agent 能力，但向量库、对象存储、缓存和知识库原料仍由数据模块封装；Agent 通过 DataClient / KnowledgeDataClient 读取，不直接连接数据库。短期可以用本地 client 调用 `rs_core/online`，后续可替换为 HTTP/gRPC client 调 `online-service`。

### 3.5 前端模块 `frontend/` + display contract

目标：把推荐结果变成可看、可点、可反馈、可复盘的产品体验。

当前来源：

- `frontend/`
- `rs_core/display/`
- 纯 UI animation 属于 frontend，Agent 行为回放属于 `rs_core/agent/simulation`，离线可视化属于 offline report
- `scripts/assets/`

建议：

```text
frontend/
├─ src/api/             # agentClient / onlineClient / sessionClient
├─ src/components/      # 商品卡、聊天窗口、反馈按钮
├─ src/features/        # session replay、simulation scene 等功能区
└─ src/types/           # 前端 contract 类型
```

`rs_core/display/` 当前可以继续作为后端 display payload contract；后续若前端类型稳定，可同步生成到 `frontend/src/types/`。前端只调用 Nginx 暴露的 `/api/*`，不直接依赖 `recsys` 或 `agent` 内部字段。

*注：为了防止前后端契约由于独立迭代发生接口“漂移”，建议在 `scripts/ci/` 中维护一个自动化类型同步脚本。每次后端 `contracts` 的 Pydantic Schema 修改后，在 CI 流程中利用 `pydantic-to-typescript` 等工具，自动将后端契约结构体编译转换成对应的 TypeScript 类型声明（`.ts`），并同步输出到 `frontend/src/types/` 下。*

---

## 4. Canonical 服务接入入口

旧 `services/` package 已物理退役；FastAPI split app、runtime composition、worker CLI 入口统一收敛到 `rs_core` 下的 canonical 路径。推荐、Agent、数据和训练逻辑仍放在 `rs_core` 对应业务模块，接入入口只做路由、依赖注入、异常处理、生命周期和 CLI 参数解析。

*注：`rs_core.data.runtime.worker`、`rs_core.offline.runtime.worker` 和 `scripts/` 下的 CLI 脚本都必须保持“轻量化外壳”属性。所有的数据清洗（Pipelines）、模型训练（Training）、离线评估等核心业务逻辑，必须沉淀在 `rs_core/` 对应的业务模块中。Worker 和 CLI 脚本仅负责做入参解析、异常监控、生命周期管理、MQ 消息确认（ACK/NACK），不应写具体的业务实现。*

### 4.1 `rs_core.serving.api.online_app`

职责：在线推荐 HTTP 服务，只处理推荐候选、召回、排序和健康检查，不承载 RAG、聊天、session 对话或反馈解释编排。

当前入口：

```text
rs_core/serving/api/online_app.py        # uvicorn target / create_app()
rs_core/serving/api/routers/online.py    # /rank router implementation
rs_core/serving/runtime/split_engines.py # OnlineRecommendationEngine 构造/cache
```

典型 API：

- `GET /health`
- `GET /ready`
- `POST /recommend`
- `POST /recall`
- `POST /rank`

### 4.2 `rs_core.serving.api.agent_app`

职责：Agent/RAG 对话 HTTP 服务，承载聊天、session、反馈、RAG evidence 和解释编排。

当前入口：

```text
rs_core/serving/api/agent_app.py         # uvicorn target / create_app()
rs_core/serving/api/routers/agent.py     # /rag/query router implementation
rs_core/serving/runtime/split_engines.py # AgentOrchestrationEngine 构造/cache
```

典型 API：

- `POST /session/start`
- `POST /chat`
- `POST /feedback`
- `POST /rag/query`
- `POST /session/end`
- `GET /session/{id}`

### 4.3 `rs_core.data.runtime.worker/` 与 `rs_core.offline.runtime.worker/`

数据和离线模块不一定要先提供 HTTP API，更适合优先作为 worker/CLI：

- `data_worker`：导入、清洗、窗口构建、候选池构建、数据库/缓存/对象存储/向量库连接封装、artifact 注册。
- `offline_worker`：训练、评估、仿真、报告、模型 artifact 预热。

后续如果需要管理界面或任务状态查询，可以再加 internal API。

---

## 5. 部署与 Nginx 路由

后续容器化建议按运行边界推进，不等于代码一开始就物理拆包。

推荐本地/演示部署：

```text
Browser
  |
  v
Nginx
  ├─ /                    -> frontend
  ├─ /api/recommend       -> online-service
  ├─ /api/recall          -> online-service
  ├─ /api/chat            -> agent-service
  ├─ /api/session/*       -> agent-service
  ├─ /api/feedback        -> agent-service
  ├─ /api/rag/*           -> agent-service
  ├─ /api/health/online   -> online-service /health
  └─ /api/health/agent    -> agent-service /health
```

推荐容器演进：

1. `frontend` + `online-service`：先让主推荐链路可运行。
2. `frontend` + `online-service` + `agent-service`：当 Agent 逻辑复杂后独立服务化。
3. 加 `data-worker` 和 `offline-worker`：把数据构建、训练、评估、仿真移出在线链路。
4. 接 MySQL / Redis / MinIO / Qdrant：统一放在数据模块的 storage/adapter 边界中，online/offline/agent 通过数据 contract/client 使用，不让业务 Engine 直接绑定具体基础设施。

**Dockerfile 构建与缓存最佳实践：**
- **统一构建上下文**：所有服务镜像（Dockerfile 位于 `deploy/docker/`）均在项目根目录下构建（即 `docker build -f deploy/docker/online_service.Dockerfile .`），确保能够正确复制并依赖 `rs_core`。
- **缓存依赖安装**：在 Dockerfile 编写中，遵循“先 COPY 依赖配置（如 `pyproject.toml` 等）进行依赖安装（`pip install`），再 COPY 源码（`rs_core/` 等）”的原则。避免因源码的任何微小变动而导致 Docker 镜像从头下载/编译 Python 依赖包。

---

## 6. 顶层目录职责

### 6.1 `rs_core/`

核心业务代码所在目录。当前阶段保留这个顶层 Python 包，避免一次性改动所有 import；内部逐步按 `data/offline/online/agent/common/llm` 收敛。

原则：

- 放可复用业务能力，不放一次性脚本。
- 每个业务模块有 engine、contracts、clients、adapters 的清晰边界。
- FastAPI 不放业务核心，只放在 `rs_core/serving/api/` 的 public/split app 与 router 中。
- 跨模块调用优先通过 contract/client，不直接 import 内部实现。

### 6.2 `scripts/`

命令入口层，继续保留。它适合做数据构建、训练、评估、smoke、artifact 校验等 CLI；当某个脚本成为长期 worker 入口，应迁入对应 `rs_core.data.runtime.worker` 或 `rs_core.offline.runtime.worker`。

### 6.3 `configs/`

配置目录，集中管理数据口径、训练/评估配置、serving 配置、governance route 和 artifact 路径。

配置不能单独代表能力晋升。召回/排序产物进入在线推荐链路、RAG 产物进入 Agent 链路，都应经过 manifest、route registry 和 gate。

### 6.4 `tests/`

测试目录。当前可以保留平铺测试，后续建议按模块重组：

```text
tests/
├─ data/
├─ offline/
├─ online/
├─ agent/
├─ services/
└─ contracts/
```

### 6.5 `dic/` 与 `old_dic/`

- `dic/`：当前说明文档、架构说明、工程叙事和方法报告。
- `old_dic/`：历史草稿，只读归档，不作为当前规划依据。

### 6.6 `rs_lab/`

纯探索实验目录，不保证质量，不直接参与主线。若实验接近晋升，应迁入 `rs_core/offline/experiments/` 并补配置、评估和文档证据。

### 6.7 已归档的顶层空包 / marker

`rs_core/llm/`、`rs_core/features/` 和 `rs_core/animation/` 已从 active `rs_core` 顶层路径归档到 `old_dic/legacy_migration_archive/2026-06-26/rs_core/`。后续如需新增 LLM 基础设施，应先判断是否属于 `rs_core/agent/adapters/`、`rs_core/common/` 或独立 service；feature 工程统一进入 `rs_core/data/features/`；纯 UI animation 属于 frontend，Agent 行为回放属于 `rs_core/agent/simulation`，离线可视化属于 offline report。

---

## 7. 新文件放置规则

新增文件先判断类型：

1. 数据资产与基础设施连接能力：`rs_core/data/`，入口脚本放 `scripts/data/` 或 `rs_core.data.runtime.worker/`；数据库、缓存、对象存储、向量库等适配也归这里。
2. 离线训练/评估/仿真能力：`rs_core/offline/`，入口放 `scripts/training/`、`scripts/evaluation/` 或 `rs_core.offline.runtime.worker/`。
3. 在线推荐能力：`rs_core/online/`，HTTP 接入放 `rs_core.serving.api.online_app/`。
4. Agent/RAG 能力：`rs_core/agent/`，HTTP 接入放 `rs_core.serving.api.agent_app/`。
5. 前端展示：`frontend/`，后端 display payload contract 暂放 `rs_core/display/`，后续迁入明确 contract。
6. 容器化/Nginx：`deploy/`。
7. 当前文档和叙事：`dic/`。
8. 纯探索：`rs_lab/`。
9. 历史材料：`old_dic/` 或 `dic/archive/`。

---

## 8. Engine / Contract / Adapter 原则

每个后端业务模块都应有 Engine，但 Engine 只做业务编排，不直接绑定基础设施。

推荐 Engine：

- `DataAssetEngine`
- `OfflineModelEngine`
- `OnlineRecommendationEngine`
- `AgentOrchestrationEngine`

调用方向：

```text
FastAPI route / Worker CLI
  -> Engine
  -> Domain logic
  -> Port / Client / Adapter
  -> Data storage adapters / external LLM
```

其中 MySQL、Redis、MinIO、Qdrant、本地文件等数据库或存储类基础设施默认收敛 to 数据模块；online/offline/agent 只依赖 DataClient/contract，不直接持有具体连接。

### 8.1 基础设施连接管理与业务适配解耦
- **底层连接池**：所有的数据库、向量检索库、对象存储（MySQL, Qdrant, Redis, MinIO）的底层 Client/连接池生命周期统一收拢在 `rs_core/data/` (或 `common/` 针对极通用的部分) 进行单例化初始化和健康检查。
- **业务适配层 (Adapters)**：各个业务模块（如 `online/adapters/`、`agent/adapters/`）严禁自行读取配置或实例化底层连接。各模块的 Adapter 必须通过依赖注入（DI）消费统一的 Client 实例，仅在各自的 Adapter 中编写业务相关的 Query 拼装（例如召回条件的 DSL 构建、特征的 Key-Value 读取），杜绝连接管理代码碎片化。

### 8.2 全链路 Trace 传递与降级规范

1. **Trace 传递**：
   - 跨模块或跨服务调用（如 Agent 调 Serving 服务）必须传递 `request_id` / `trace_ref`。
   - 数据库与向量适配层（MySQL, Qdrant）在日志中必须关联当前的 Trace，以便全链路剖析请求耗时。
2. **防灾降级（Fallback）**：
   - 核心链路必须实现降级闭环。在线推荐服务不可用或延迟超标时，必须自动降级到 `current_ranking_route` 声明的 `fallback_route`（如基于本地轻量存储的 `baseline_cached_popular`）。
   - Agent 模块调用 LLM API 超时或受限时，应降级到本地缓存或静态澄清提示，保证服务不崩溃。

禁止方向：

- FastAPI route 直接写推荐、训练、RAG 或 Agent 核心逻辑。
- Agent 直接 import online 模块内部实现。
- Online / Offline / Agent Engine 直接 import `qdrant_client`、`redis`、`psycopg`、MinIO SDK 等具体基础设施 client。
- 前端直接依赖后端内部字段。

推荐做法：

- 服务之间通过 `Client` + `Contract` 调用。
- 短期可用 local client，长期可替换为 HTTP/gRPC client。
- 数据模块通过 artifact / manifest / storage contract 支撑在线、离线和 Agent；离线模型通过 model artifact / manifest / event 与在线模块连接，不直接阻塞在线请求。

---

## 9. 演进顺序

1. **文档和认知先行**：先确认五个业务模块 + canonical serving/worker 入口 + deploy 的目标结构。
2. **保留 `rs_core`，内部渐进分区**：不要立即物理拆成多个顶层包，降低 import 迁移风险。
3. **抽 contract**：数据 artifact、离线模型产物、在线推荐结果、Agent evidence、前端 display payload。
4. **抽 service adapter**：把 FastAPI route 从业务核心迁到 `rs_core.serving.api.online_app` 和 `rs_core.serving.api.agent_app`。
5. **补 worker**：将长期数据构建、训练、评估、仿真入口迁入 `rs_core.data.runtime.worker` 和 `rs_core.offline.runtime.worker`。
6. **补 Nginx 和容器化**：`frontend`、`online-service`、`agent-service` 先容器化，再接 worker 和基础设施容器。
7. **按证据物理拆分**：只有 contract 稳定、测试充分、存在独立扩缩容或资源隔离收益时，才考虑把业务模块拆成独立顶层包或独立服务仓库。

---

## 10. 面试表达口径

可以这样讲：

> 我没有一开始就把项目拆成多个微服务仓库，因为现有推荐、Agent、RAG 和 serving 之间 import 很密，过早物理拆包会制造大量回归。我采用的是渐进式服务化：保留 `rs_core` 作为核心业务包，内部按数据、离线模型、在线模型、Agent 四个业务模块收敛；前端独立；FastAPI split app、runtime composition、data/offline worker 入口统一收敛到 `rs_core` canonical 路径；Nginx、Dockerfile 和 docker-compose 放到 `deploy/`。每个后端模块都有 Engine、Contract、Client、Adapter，服务之间通过 contract 调用，实验产物通过 manifest 和 route registry 进入主链路。这样既有微服务的边界，也避免过早分布式化。

核心亮点：

- 业务结构清楚：数据 → 离线模型 → 在线模型 → Agent → 前端。
- 服务接入清楚：`rs_core.serving.api.online_app`、`rs_core.serving.api.agent_app`、`rs_core.data.runtime.worker`、`rs_core.offline.runtime.worker`。
- 部署路径清楚：Nginx 路由 frontend / online / agent，Dockerfile 集中在 `deploy/docker/`。
- 演进风险可控：先抽 contract 和 adapter，再拆服务和容器，最后才考虑物理拆包。

---

## 11. 自动化契约守卫与准入控制

为防止架构规范与实际代码在多轮重构中发生“边界腐烂”，项目建立了 **架构即代码（Architecture-as-Code）** 的自动化契约守卫，通过 CI/测试强制卡口：

1. **配置安全性与合规性 (`validate_config_contracts`)**：
   - 严禁包含以 `_tmp_` 开头的临时/个人调参配置。
   - 所有配置路径必须为基于项目根目录的相对路径，出现个人绝对路径（如 `D:/Users/...`）将直接阻塞 CI。
2. **命令入口守卫 (`validate_script_entrypoints`)**：
   - 任何 `scripts/` 下的 CLI 入口必须包含 `if __name__ == '__main__':` 守卫，防止在被其他模块意外 import 时执行业务逻辑。
3. **测试分类约束 (`validate_test_markers`)**：
   - 测试文件必须在文件顶部显式声明 `pytestmark = [pytest.mark.xxx]`，便于 CI 隔离慢速训练测试与快速 Serving/单元测试。
4. **控制面路由注册校验 (`validate_route_registry_contract`)**：
   - `configs/governance/current_route_registry.yaml` 声明的 current 状态路由，必须配有完整的设计依据（ADR 链）、可读配置及对应的 `required_output_paths`。
