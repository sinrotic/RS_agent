# RS_agent 技术选型与部署路线

## 1. 文档目的

本文档记录 RS_agent 当前阶段的技术选型、组件边界和后续演进路线，目标是把“为什么选这些组件、当前落到什么程度、哪些只是预留”讲清楚，避免把本地试运行能力误写成生产级系统。

当前项目主线是：

```text
传统推荐 backbone（召回 / 排序 / 规则）
        +
Agent 编排层（多轮对话 / 反馈响应 / 工具调用）
        +
RAG grounding（商品知识证据 / 解释 / 幻觉控制）
```

组件选型服务于这个主线，而不是为了堆满工业组件。

---

## 2. 当前阶段边界

当前阶段定位为 **local/trial/non-production MVP**：

- 不声明 production-ready。
- 不默认启动 vLLM/Qwen。
- 不默认训练、全量评估、全量索引、full pytest。
- 本地按 12GB 可承受、14GB 上限控制资源。
- 重任务优先远程运行或限流 smoke。
- 本地命令默认使用项目 `.venv`。
- debug / recall / simulation 类接口不得无认证暴露。

当前本地部署骨架位于：

```text
deploy/local/
```

---

## 3. 组件总览

| 组件 | 当前定位 | 当前状态 | 主要用途 |
|---|---|---|---|
| FastAPI | 服务编排层 | 已落地 | `/health`、`/ready`、推荐/反馈/session API |
| PostgreSQL | 结构化数据服务层 | 本地基础已准备，不默认导入数据 | 商品、交互、用户序列、会话、反馈、推荐日志、artifact/eval 元信息 |
| Qdrant | 向量数据库 | local/trial profile + env override + readiness fallback 已接入，未默认灌库 | 商品/RAG chunk/two_tower 向量检索、hybrid RAG dense backend |
| SQLite BM25 | 本地文本检索 fallback | 已使用 | Qdrant 不可用时提供 BM25 evidence fallback |
| Redis | 缓存/队列/短状态预留 | 暂不启动 | 后续缓存热门商品、session 加速、任务状态、轻量队列 |
| MinIO | 对象存储 / artifact store | local/trial 可选 profile + manifest/resolver/upload dry-run 已接入 | 模型、索引、评估报告、embedding、Qdrant snapshot 等大文件 |
| MLflow | 实验追踪 / Model Registry | manifest 预留 | 训练 run、模型版本、指标、artifact lineage |
| vLLM / Qwen | LLM 推理服务 | 外部 OpenAI-compatible adapter 已接入，默认 disabled | 后续 Agent 策略、rerank signal、对话能力增强 |
| Docker Compose | 本地试运行编排 | 已准备 | 本机启动 Qdrant/PostgreSQL/serving 等 local profile |
| Kubernetes / KServe | 生产化部署预留 | 当前不做 | 后续服务编排、弹性伸缩、模型服务治理 |

---

## 4. FastAPI：推荐 Agent API 编排层

### 为什么选 FastAPI

FastAPI 适合当前项目的服务入口，因为它：

- Python 原生，和现有推荐、Agent、训练/评估代码衔接成本低。
- 适合快速暴露结构化 API。
- Pydantic schema 能约束 public payload，避免内部 diagnostics 泄露。
- 本地 demo、前端展示、后续线上服务可以复用同一套接口语义。

### 当前职责

FastAPI 当前承担：

- `/health`：只做 liveness，不暴露复杂内部状态。
- `/ready`：暴露 serving config、Qdrant、fallback、manifest、DeepFM shadow、Agent provider 等结构化 readiness。
- 推荐/反馈/session API：服务 Agent 多轮交互和前端展示。

### 边界

当前 FastAPI 仍是本地 trial serving：

- session state 仍是 single-process / in-memory。
- 不声明生产级高可用。
- debug/simulation/recall debug 接口必须受开关和 token 约束。

---

## 5. PostgreSQL：结构化数据服务层

### 为什么选 PostgreSQL

PostgreSQL 是后端主数据库的成熟选择，适合存结构化业务数据：

- 支持标准 SQL 和复杂查询。
- `jsonb` 适合存 Agent feedback、推荐日志、候选列表等半结构化字段。
- 服务端并发和事务能力强于 SQLite。
- 后续可与前端、Agent session、评估记录、artifact registry 统一打通。

### 在本项目中存什么

PostgreSQL 适合存：

- `products`：商品基础信息。
- `interactions`：用户行为、标签、时间窗、split。
- `user_sequences`：用户序列。
- `agent_sessions`：Agent 会话状态。
- `feedback_events`：用户反馈。
- `recommendation_logs`：推荐请求和展示结果。
- `artifact_registry`：artifact 路径、版本、hash、指标摘要。
- `eval_runs`：评估 run 和指标摘要。

本地 schema 初始化文件：

```text
deploy/local/postgres/init/001_schema.sql
```

服务侧只读访问通过 `rs_core/data/postgres_dataset.py` 的 local/trial wrapper 实现：默认关闭，开启后使用 `docker compose exec -T postgres psql` 执行白名单式轻量 `SELECT`，用于 `/ready` 的 `postgres_dataset` 状态、商品查询、用户序列和近期交互读取。该方案刻意不引入 psycopg/ORM，不打印 DSN/password；PostgreSQL 不可用时 fail-open 为 degraded，避免把可选数据层故障扩大成推荐服务不可用。

### 不适合存什么

PostgreSQL 不建议直接存：

- 原始巨大 JSONL / CSV / Parquet 文件。
- 模型 checkpoint。
- LoRA adapter。
- embedding `.npy` / `.pt` 大矩阵。
- Qdrant snapshot。
- 大型离线索引 artifact。

这些应放在文件系统或后续 MinIO；PostgreSQL 只存路径、版本、hash 和指标摘要。

### 当前状态

本地 PostgreSQL 使用 Docker Compose 启动，并将数据目录 bind mount 到 D 盘项目目录：

```text
data/postgres/pgdata
```

启动命令：

```bash
docker compose -f deploy/local/docker-compose.yml --profile postgres up -d postgres
```

该目录只作为 local/trial 数据库运行目录，已被 `.gitignore` 忽略；迁移或备份 dump 可临时放在 `data/postgres_migration`。如果从 Docker named volume 迁移，必须先 dump/restore 并校验行数、split 和 `interactions_without_product=0`，确认新库可用前不删除旧 volume。

已采用低资源参数：

```text
shared_buffers=512MB
work_mem=16MB
maintenance_work_mem=256MB
max_connections=10
max_parallel_workers=2
max_parallel_maintenance_workers=1
```

### 2y 数据导入策略

本地磁盘不足时，不应一边保留 full/2y 文件，一边直接导入 PostgreSQL。推荐流程：

1. 远程备份 full/2y 数据。
2. 校验远程备份完整。
3. 本地只保留 base 或必要数据副本。
4. 释放磁盘后启动 PostgreSQL。
5. 先做 tiny smoke 导入。
6. 再流式/分批导入 2y 核心结构化表。

导入时不要使用一次性全量 `pandas.read_json(..., lines=True)`，而应流式读取、批量 COPY/INSERT、后建索引。

---

## 6. Qdrant：向量数据库

### 为什么选 Qdrant

Qdrant 专注向量检索，适合作为推荐/RAG 的 dense backend：

- 支持向量相似度检索和 payload filter。
- 部署轻量，适合本地 Docker trial。
- 与 Python client 集成简单。
- 比把向量混入业务数据库更清晰，职责边界明确。

### 在本项目中做什么

Qdrant 用于：

- 商品文本 embedding 检索。
- RAG chunk embedding 检索。
- 后续 user interest embedding / item embedding 检索。
- hybrid RAG 的 dense vector backend。

当前配置入口：

```text
configs/serving/online_service.local_qdrant.yaml
configs/artifacts/rag_qdrant_manifest.yaml
```

### 当前状态

当前已经准备：

- `deploy/local/docker-compose.yml` 中的 Qdrant 服务。
- Qdrant optional dependency profile：`requirements-serving-qdrant.txt`。
- dense RAG embedding profile：`requirements-serving-rag-dense.txt`。
- hybrid RAG + Qdrant + BM25 fallback 配置。
- `RS_QDRANT_*` env override，可同时覆盖 RAG/two_tower/semantic Qdrant 连接目标。
- `/ready` Qdrant dependency / target kind / manifest / fallback 状态，且不泄漏 URL/path。
- two_tower serving config 已可选择 `backend=qdrant`，不可用时按配置保留 local fallback 语义。

但还没有默认执行：

- 启动 Qdrant 容器。
- 创建 collection。
- 全量构建商品/RAG 向量索引。
- 全量灌库。

### fallback 边界

Qdrant 不可用时必须降级 BM25，不能把 fallback 包装成 Qdrant 成功。

触发 fallback 的情况包括：

- `qdrant-client` 依赖缺失。
- Qdrant target 未配置。
- Qdrant 服务/collection 不可用。
- vector backend 运行时异常。
- dense vector 命中为空。

RAG 只提供 candidate-scoped evidence，不允许：

- candidate generation。
- ranking input replacement。
- promotion。

---

## 7. SQLite BM25：轻量文本检索 fallback

SQLite BM25 是当前本地 RAG 的可靠底座。

### 为什么保留

- 不需要独立服务。
- 适合本地小样本和 fallback。
- Qdrant 未启动时仍能提供商品知识 evidence。
- 便于测试和回归。

### 边界

SQLite BM25 不承担生产级向量检索；它是文本检索 fallback，不替代 Qdrant 的 dense retrieval 能力。

---

## 8. Redis：缓存、短状态和队列预留

### 为什么预留 Redis

Redis 适合解决高频短状态问题：

- 热门商品/热门候选缓存。
- session 快速读取。
- rate limit / token bucket。
- 推荐请求短期状态。
- 后台任务进度。
- 轻量队列。

### 为什么当前不启动

当前本地 MVP 还不需要 Redis：

- session 仍是 single-process/in-memory。
- 没有多 worker 并发服务。
- 没有生产级任务队列。
- 磁盘和资源优先给数据备份、PostgreSQL、Qdrant smoke。

### 后续引入时机

当出现以下需求时再引入 Redis：

- 前端多用户会话需要稳定短状态。
- 推荐接口需要缓存热门查询。
- 后台导入/索引任务需要状态追踪。
- API 需要限流。
- 服务从单进程扩展到多 worker。

---

## 9. MinIO：artifact store / resolver

### 为什么需要 MinIO

MinIO 是 S3-compatible object storage，适合存大文件和长期产物：

- 原始数据归档。
- 清洗后数据快照。
- 模型权重、LoRA adapter。
- Qdrant snapshot。
- embedding 文件。
- 评估报告和 metrics artifact。
- 离线索引产物。

### 当前状态

当前已从“仅预留字段”推进到 **local/trial 可选 profile + manifest resolver**：

- `deploy/local/docker-compose.yml` 增加 `minio` profile，端口只绑定 loopback。
- `rs_core/artifacts/manifest.py` 支持 manifest 读取、public-safe status、本地 sha256/size 计算和 artifact_store patch。
- `rs_core/artifacts/resolver.py` 支持 local / `file://` / `s3://` / `minio://` URI，下载到 cache 后校验 sha256/size，并显式报告 fallback。
- `scripts/artifacts/upload_to_minio.py` 支持 manifest/inventory dry-run、upload、verify；dry-run 不联网，适合作为默认验证入口。
- 核心 Pool500、RAG、DeepFM shadow manifest 已补充 `local_path`、`artifact_uri`、`minio_uri`、`sha256`、`size_bytes`、`cache_policy`、`uploaded_at` 等字段。

仍不默认上传 Qwen/LoRA，也不声明 production-ready；真实上传前需要确认本地 MinIO 已启动、bucket 已准备且密钥只保存在本地 `.env`。

### 和 PostgreSQL 的关系

PostgreSQL 存：

```text
artifact_id / artifact_type / path / version / sha256 / metrics_json
```

MinIO 存：

```text
真实大文件
```

---

## 10. MLflow：实验追踪与模型注册预留

### 为什么需要 MLflow

MLflow 适合管理训练和实验：

- tracking run。
- 参数记录。
- metric 记录。
- artifact 关联。
- model registry。

### 当前状态

当前不默认启动 MLflow，只在 manifest 中预留字段。原因是当前优先级仍是：

```text
pool500 排序链路 → Agent → 前端展示 → 数据服务层 → 持续优化
```

MLflow 在 COLD/DeepFM/Qwen 训练链路稳定后再接入更合适。

---

## 11. vLLM / Qwen：模型推理服务预留

### 当前路线

项目训练层规划是：

```text
Qwen3.5-4B + 8-bit QLoRA SFT + GRPO
```

但当前服务层默认：

- `provider=disabled`。
- 不默认本地加载 Qwen。
- 不默认启动 vLLM。
- `openai_compatible` 已有外部 endpoint adapter，可生成 bounded rerank signal，但默认关闭。
- `local_transformers` 保持 `local_files_only=True`，仅在显式启用时懒加载。
- `/ready` 只报告 provider 是否配置、endpoint/model 是否设置、probe 是否运行和 fallback policy，不泄漏 API key、完整 endpoint 或 prompt。

### 为什么不默认启动

本机资源有限，直接启动 Qwen/vLLM 会和数据导入、Qdrant、PostgreSQL、训练任务抢资源；当前 deterministic baseline + tool orchestration 更适合先打通全链路。

---

## 12. 数据分层建议

本项目的数据建议分层如下：

```text
base 原始/基础数据
        |
        | 清洗 / 时间窗切分
        v
2y 结构化训练数据
        |
        | 流式导入核心表
        v
PostgreSQL
        |
        | embedding / chunk build
        v
Qdrant

大型 artifact / 原始备份 / 模型 / 索引快照
        |
        v
MinIO 或远程文件系统
```

当前本地建议：

- 保留 `amazon_2023_base` 作为本地基础数据。
- full 数据集不再作为当前主线输入。
- 2y 数据集用于 PostgreSQL/推荐主链路。
- full 和 2y 在远程备份校验后，本地可按需要删除副本释放磁盘。

---

## 13. 推荐演进顺序

### Step 1：本地服务骨架

已完成：

- FastAPI serving。
- Qdrant compose/profile/config。
- PostgreSQL compose/schema 基础。
- RAG manifest / BM25 fallback。
- DeepFM shadow diagnostic contract。

### Step 2：远程备份与本地磁盘释放

进行中：

- 将 full/2y 相关大数据目录备份到远程。
- 校验远程文件数、大小、关键 manifest。
- 本地暂不删除，等待确认。

### Step 3：PostgreSQL tiny smoke

后续执行：

- 启动 PostgreSQL 空库。
- 导入小样本 products/interactions/user_sequences。
- 验证按用户、商品、时间窗查询。
- 验证 schema 和索引。

### Step 4：2y 核心表导入

后续执行：

- 分批导入 2y 核心结构化数据。
- 后建索引。
- 记录导入 manifest、行数、用户数、商品数、时间范围、split 分布。

### Step 5：Qdrant tiny smoke

后续执行：

- 启动 Qdrant。
- 小样本构建商品/RAG chunk embedding。
- 验证 `/ready` 识别 Qdrant 可用。
- 验证 hybrid RAG dense + BM25 fallback。

### Step 6：Agent / 前端接入数据服务层

后续执行：

- Agent 查询 PostgreSQL 中的用户历史、商品详情、反馈。
- Qdrant 提供 evidence。
- 前端消费统一 display contract。

---

## 14. 面试表达版本

可以这样概括：

> 我没有把推荐 Agent 做成一个只靠大模型输出的 demo，而是按真实推荐系统拆成数据层、召回排序层、RAG grounding 层和 Agent 编排层。结构化数据用 PostgreSQL 管，向量检索用 Qdrant 管，大文件和模型产物后续放 MinIO，实验和模型版本后续接 MLflow，Redis 作为缓存和短状态层预留。当前本地只落地 non-production MVP：FastAPI 服务、Qdrant 配置、PostgreSQL schema、BM25 fallback 和 manifest 治理，避免一上来启动重模型或全量索引，把资源风险和工程边界控制住。

---

## 15. 当前明确不做

- 不把 PostgreSQL 当作原始大文件仓库。
- 不把 Qdrant fallback 伪装成向量召回成功。
- 不用 Redis 代替持久化数据库。
- 不默认启动 MinIO/MLflow/vLLM/KServe。
- 不把 local Docker Compose 写成生产部署。
- 不把 DeepFM shadow 作为主排序替代。
- 不让 RAG 替代召回或排序输入。
