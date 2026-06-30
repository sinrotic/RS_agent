# RS Agent Serving 架构分层说明

## 目标

本文件用于给后续执行本项目的 Agent 提供 serving 模块的架构上下文。当前 serving 模块已经从早期 demo-style 的根目录文件组织，重组为更接近 Spring Boot 分层思想的模块化单体：入口、DTO、业务编排、领域合同、基础设施适配和治理准入分别归位。

这次重组不是简单移动文件，而是为了让后续接入 Agent 对话、RAG、召回/排序 artifact、MySQL structured store、Redis、MinIO、Qdrant、Queue 等能力时，有清晰的文件边界和依赖方向。

## 总体架构

```text
rs_core/serving/
├── api/
│   ├── app.py                    # canonical FastAPI composition root，保留 uvicorn target
│   ├── factory.py                # 主 create_app()，只组装 public serving routes
│   ├── split_factory.py          # online/agent split app factory，不并入主 app
│   ├── dependencies.py           # request_id、auth/env gate 与 service dependency seam
│   ├── exceptions.py             # HTTP exception translation
│   ├── middleware.py             # request-id middleware
│   └── routers/                  # 按 endpoint surface 拆分 APIRouter
│       ├── recommendation.py     # session/chat/feedback/recommend/feed/session export
│       ├── runtime.py            # health/ready/recall
│       ├── online.py             # split online service routes: recommend/recall/rank
│       ├── agent.py              # split agent service routes: session/chat/feedback/rag
│       ├── demo.py               # demo endpoint
│       └── simulation.py         # simulation endpoints
├── schemas/
│   └── models.py                 # Request/Response DTO
├── application/
│   └── recommendation_service.py # Application Service / 业务编排
├── domain/
│   ├── boundary_map.py           # 架构边界与 ownership
│   ├── adapter_contracts.py      # adapter 合同
│   ├── serving_fact.py           # public-safe serving fact
│   └── state_facts_store.py      # serving fact grouping
├── infrastructure/
│   └── stores/
│       ├── structured_dataset.py       # 外部数据/底层实现 seam
│       ├── candidate_import_plan.py    # candidate JSONL 纯计划/normalize
│       ├── candidate_store_mysql.py    # MySQL writer，显式 write 才落库
│       └── candidate_store_cassandra.py# Cassandra/Scylla writer，显式 write 才落库
├── governance/
│   └── manifest_gate.py          # artifact / route 准入
├── runtime/
│   ├── composition.py            # ServingRuntimeComposition，缓存构造 serving/online/agent runtime
│   ├── config.py                 # serving config 解析与 env override
│   └── readiness.py              # public readiness 摘要
```

旧根目录 shim 已删除，后续不再通过 `rs_core.serving.app/schema/service/facts/adapter_contracts/boundary_map/manifest_gate` 接入；尤其不能恢复 `rs_core/serving/app.py` 作为 canonical app。脚本层 `scripts/serving/import_candidate_store_to_mysql.py` 与 `scripts/serving/import_candidate_store_to_cassandra.py` 只保留 CLI wrapper 职责。

## 与 Spring Boot 分层的类比

| Spring Boot 常见分层 | 当前 serving 对应位置 | 职责 |
| --- | --- | --- |
| `controller` / router | `rs_core/serving/api/app.py`、`factory.py`、`dependencies.py`、`routers/` | FastAPI app assembly、HTTP request/response、dependency override seam、request-time auth/env gate、health/ready/session/chat/feedback/recommend/recall/demo/simulation 路由 |
| split service factory | `rs_core/serving/api/split_factory.py`、`routers/online.py`、`routers/agent.py` | online/agent service 独立 route table；`/rank`、`/rag/query` 不并入主 app |
| service entrypoints | `rs_core/serving/api/online_app.py`、`rs_core/serving/api/agent_app.py` | 部署入口，薄封装 split factory 和 dependency，不承载业务 route 实现 |
| runtime composition | `rs_core/serving/runtime/composition.py`、`rs_core/serving/runtime/split_engines.py` | canonical runtime 与 split engine 构造/cache；旧 `services/` package 已物理删除 |
| `dto` / `request` / `response` | `rs_core/serving/schemas/models.py`、`rs_core/serving/schemas/__init__.py` | API request/response Pydantic DTO，包含 `RankRequest`、`RagQueryRequest` |
| `service` | `rs_core/serving/application/recommendation_service.py` | session、chat、feedback、recall、recommend、readiness 等业务编排 |
| `domain` / `contract` | `rs_core/serving/domain/` | BoundaryMap、AdapterContract、ServingFact、StateFactsStore 等核心合同和边界 |
| `repository` / `adapter` / `infrastructure` | `rs_core/serving/infrastructure/` | 外部数据和基础设施 seam，candidate import 拆为 pure plan 与 backend writer |
| governance / admission gate | `rs_core/serving/governance/manifest_gate.py` | route registry、artifact manifest、优化产物准入控制 |

注意：本项目不是照搬 Spring Boot，也没有 Java/Spring IoC 容器。这里采用的是 Python + FastAPI 的模块化单体，并结合 Clean Architecture / Hexagonal Architecture 的依赖方向控制。

## 当前 canonical 路径与已删除旧入口

后续新代码必须使用 canonical 路径：

- FastAPI app canonical：`rs_core.serving.api.app`
- FastAPI app factory：`rs_core.serving.api.factory.create_app`
- FastAPI split app factory：`rs_core.serving.api.split_factory.create_online_app` / `create_agent_app`
- FastAPI dependency seam：`rs_core.serving.api.dependencies.get_service`
- FastAPI routers：`rs_core.serving.api.routers.*`
- API DTO canonical：`rs_core.serving.schemas`
- Application service canonical：`rs_core.serving.application.recommendation_service`
- Runtime composition canonical：`rs_core.serving.runtime.composition`
- BoundaryMap canonical：`rs_core.serving.domain.boundary_map`
- Adapter contracts canonical：`rs_core.serving.domain.adapter_contracts`
- Serving facts canonical：`rs_core.serving.domain.serving_fact`
- StateFactsStore grouping canonical：`rs_core.serving.domain.state_facts_store`
- Manifest gate canonical：`rs_core.serving.governance.manifest_gate`
- Structured dataset serving seam：`rs_core.serving.infrastructure.stores.structured_dataset`
- Candidate import plan：`rs_core.serving.infrastructure.stores.candidate_import_plan`
- Candidate store writers：`rs_core.serving.infrastructure.stores.candidate_store_mysql` / `candidate_store_cassandra`

以下旧路径已物理删除，不应在新代码、脚本或普通测试中继续依赖：

- `rs_core.serving.app`
- `rs_core.serving.schema`
- `rs_core.serving.service`
- `rs_core.serving.facts`
- `rs_core.serving.adapter_contracts`
- `rs_core.serving.boundary_map`
- `rs_core.serving.manifest_gate`

例外：deleted legacy guard 测试可以把这些路径作为 denylist 字符串，用 subprocess import-fail probe 防止旧 shim 被重新恢复。

## 关键边界约定

### 1. API 层只做入口，不直接接外部基础设施

`rs_core/serving/api/` 负责 FastAPI app assembly、router、HTTP 参数、response DTO、request-id middleware、exception translation 和 dependency seam，不应直接 import 或构造 Redis、MinIO、Qdrant、Psycopg、Celery、RQ 等真实基础设施客户端。`rs_core.serving.api.app:app` 仍是对外 uvicorn target；新增 endpoint 时优先放入对应 `routers/*.py`，不要把所有路由重新堆回 `app.py`。

### 2. FastAPI app factory 与 dependency override seam

`rs_core.serving.api.factory.create_app()` 是 public serving 主 app 组装入口，集中注册 CORS、middleware、exception handler 和 public routers。所有主 app router 默认随 app 注册，debug/demo/simulation/recall 等能力通过 request-time env gate 和 token gate 控制，不应在 import/include 阶段用 `os.getenv()` 条件跳过路由，否则会破坏 route table contract 和测试覆盖。

`rs_core.serving.api.split_factory` 只服务 split online/agent app：online 暴露 `/recommend`、`/recall`、`/rank`，agent 暴露 session/chat/feedback/RAG。route implementation canonicalization 不等于主 app route table merge；`/rank` 和 `/rag/query` 仍是 split-only routes，不应加入主 `create_app()`。

`get_service` 是推荐服务的 canonical dependency seam。测试或后续集成应优先通过 FastAPI `dependency_overrides` 或 canonical seam 注入 fake service，避免在业务代码里新增旧根目录 shortcut。

### 3. DTO 独立放在 schemas 层

后续新增 request/response DTO 时，默认放在：

```text
rs_core/serving/schemas/models.py
```

并同步更新 `models.__all__`，让 `rs_core.serving.schemas` 与 `rs_core.serving.schemas.models` 保持 canonical export 一致。

### 4. Application service 不直接穿透到底层数据实现

`RecommendationService` 是 serving application service，负责业务编排，但不应直接 import `rs_core.data`、真实 DB client 或外部 infra client。

例如 structured dataset 能力必须经由：

```python
from rs_core.serving.infrastructure.stores.structured_dataset import (
    StructuredDatasetStore,
    build_structured_dataset_store_from_env,
    ensure_safe_structured_dataset_store,
)
```

不要在 `rs_core/serving/application/`、`api/`、`domain/`、`runtime/` 等 core serving 层直接写：

```python
from rs_core.data import ...
```

### 5. Infrastructure 层是外部能力 seam

`rs_core/serving/infrastructure/` 可以包装底层实现，但应把这些能力暴露为 serving-owned protocol / factory / adapter seam。真实 backend 依赖应尽量 lazy import，并通过测试 guard 控制依赖方向。

Candidate store import 已拆为三层：`candidate_import_plan.py` 只做路径解析、schema 识别、normalize、dedupe 和 dry-run report；`candidate_store_mysql.py` / `candidate_store_cassandra.py` 才负责 backend-specific writer；`scripts/serving/import_candidate_store_to_*.py` 只做 CLI 参数解析和调用。默认 dry-run，不允许 import 主 app 时 eager load DB driver 或真实写库。

### 6. Runtime composition 是服务构造边界

`rs_core.serving.runtime.composition` 与 `rs_core.serving.runtime.split_engines` 是 runtime 构造/cache 的 canonical owner；`api/dependencies.py` 继续保留 FastAPI auth、request_id、env gate 和 dependency helper。旧 `services/runtime.py` 已删除，不要把 service 构造逻辑重新散回 split entrypoint 或 public app。

### 7. Data / Offline worker 已从外部 services 包物理收敛

旧 `services/data_worker`、`services/offline_worker` 已迁入 `rs_core.data.runtime.worker` 与 `rs_core.offline.runtime.worker`；它们仍属于 Data/Offline 工作流入口，不并入 serving BoundaryMap owner，也不作为 serving route 拆分目标。

### 8. Governance 层负责优化产物准入

召回、排序、RAG、DeepFM、artifact manifest、route registry 等进入 serving runtime 前，应通过 governance / manifest gate 进行准入，不应由 endpoint 或 service 随意硬编码路径绕过。

### 9. 已删除旧 shim 不应恢复为 canonical owner

`rs_core/serving/app.py`、`schema.py`、`service.py`、`facts.py` 等旧路径已经删除。BoundaryMap 中这些文件不应出现在 `owned_paths` 或 `compatibility_paths`；测试只允许在 deleted legacy guard 的 denylist 中保留这些字符串。

## 测试与回归要求

涉及 serving 架构、API/schema、boundary、shim、infra seam 的修改，优先运行以下 focused checks：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest \
  tests/services/test_serving_boundary_map.py \
  tests/services/test_serving_reorg_compatibility.py \
  tests/contracts/test_architecture_migration_boundaries.py \
  -q
```

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest \
  tests/test_serving_smoke.py \
  tests/data/test_mysql_dataset.py \
  tests/test_serving_facades.py \
  tests/test_serving_recommend_from_sequence.py \
  tests/test_serving_facts.py \
  -q
```

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ruff check \
  rs_core/serving \
  tests/test_serving_reorg_compatibility.py \
  tests/test_serving_boundary_map.py
```

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m compileall -q rs_core/serving
```

如果涉及 `scripts/serving/run_service.py`，还应补跑：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_run_service.py -q
```

## 后续 Agent 执行提示

后续 Agent 在修改 serving 代码前，应先判断改动属于哪一层：

1. HTTP endpoint / request handling：优先改 `rs_core/serving/api/routers/*.py`；只有 app assembly、uvicorn target 或 package export 需要改 `rs_core/serving/api/app.py` / `factory.py`。
2. Request/response DTO：优先改 `rs_core/serving/schemas/models.py`。
3. 业务编排：优先改 `rs_core/serving/application/recommendation_service.py` 或相邻 application module。
4. 核心合同、fact、boundary：优先改 `rs_core/serving/domain/`。
5. 外部数据/缓存/检索/对象存储/队列 seam：优先改 `rs_core/serving/infrastructure/`。
6. artifact / route / manifest 准入：优先改 `rs_core/serving/governance/`。
7. 已删除旧根目录 shim 不应恢复；新增业务逻辑必须进入对应 canonical 分层。

面试表述可概括为：

> 我们把原本 demo-style 的 serving 模块，参考 Spring Boot 常见的 controller-service-dto-repository 分层思想，重组为 FastAPI API 层、schemas DTO 层、application service 层、domain contract 层、infrastructure adapter 层和 governance 准入层。随后进一步删除旧根目录 shim，把兼容测试反转为 deleted legacy guard，并通过 BoundaryMap、import guard 和 focused regression tests 固化 canonical-only 依赖方向，为后续接入 RAG、MySQL structured store、Redis、MinIO、Qdrant、Queue 和推荐优化 artifact 留出清晰边界。
