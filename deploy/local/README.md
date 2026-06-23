# RS_agent 本地试运行部署（local/trial/non-production）

本目录只用于本机试运行 FastAPI serving + Qdrant + MinIO 的最小部署骨架，不声明 production-ready。当前阶段不默认启动 vLLM/Qwen、MLflow、BentoML/Triton、Kubernetes/KServe，也不默认训练、全量索引、全量评估或 full pytest。MinIO 是可选 artifact profile，默认不上传 Qwen/LoRA。

## 安全边界

- `docker-compose.yml` 默认只绑定 `127.0.0.1`。
- 如果改成 `0.0.0.0` 或任何非 loopback 地址，必须设置：
  - `RS_SERVING_STRICT_AUTH=1`
  - `RS_TRIAL_TOKEN`
  - `RS_DEBUG_TOKEN`
  - 若启用 simulation endpoints，还必须设置 `RS_SIMULATION_TOKEN`
- `.env.example` 只有占位 token，不能填入真实密钥后提交。
- 默认建议 `RS_ENABLE_SIMULATION_ENDPOINTS=0`，debug/recall/simulation 类接口不得无认证暴露。

## 本地启动（Docker）

```bash
cp deploy/local/.env.example deploy/local/.env
docker compose -f deploy/local/docker-compose.yml --profile qdrant --profile serving up --build
```

如需同时试运行本地 artifact store，可显式加 MinIO profile：

```bash
docker compose -f deploy/local/docker-compose.yml --profile qdrant --profile minio --profile serving up --build
```

默认只做 local smoke。服务启动命令仍会经过 `scripts/serving/run_service.py` 的非 loopback strict-auth 检查。MinIO 端口只绑定 `127.0.0.1:9000/9001`，`.env` 中的 `RS_MINIO_*` 只能放本地占位或本机密钥，不能提交真实密钥。

## 本地 PostgreSQL 空库准备

PostgreSQL 只用于本机 trial 数据服务层，不替代原始数据备份，不默认导入 full 或 2y 数据。当前 schema 初始化文件在：

```text
deploy/local/postgres/init/001_schema.sql
```

它会创建空表：`products`、`interactions`、`user_sequences`、`agent_sessions`、`feedback_events`、`recommendation_logs`、`artifact_registry`、`eval_runs`，并初始化在线召回候选库表：`item_neighbors`、`usercf_candidates`、`popular_candidates`、`category_candidates`、`user_category_profiles`、`candidate_store_manifests`。

磁盘空间不足时，先不要导入 2y。建议等远程备份校验完成、本地删除不再需要的 full/2y 副本并释放空间后，再做 2y smoke/import。

只启动 PostgreSQL 空库：

```bash
cp deploy/local/.env.example deploy/local/.env
# 修改 deploy/local/.env 里的 RS_POSTGRES_PASSWORD，占位值不能用于长期运行。
docker compose -f deploy/local/docker-compose.yml --profile postgres up -d postgres
```

本地连接串：

```text
postgresql://rs_agent:<password>@127.0.0.1:5432/rs_agent
```

PostgreSQL 数据目录使用项目本地 bind mount，落在 D 盘项目目录下：

```text
data/postgres/pgdata
```

该目录只用于本地数据库运行，已被 `.gitignore` 忽略，不要提交。迁移或备份 dump 建议临时放在：

```text
data/postgres_migration
```

如果从旧 Docker named volume 迁移过来，必须先 dump/restore 并完成行数、split、`interactions_without_product=0` 等校验；确认新 bind-mounted 数据库可用前，不要删除旧 Docker volume。

资源边界：compose 内 PostgreSQL 使用低资源参数（`shared_buffers=512MB`、`work_mem=16MB`、`maintenance_work_mem=256MB`、`max_connections=10`）。导入 2y 时必须流式/分批，不要一次性把 JSONL 全量读入内存；索引构建宁可慢一些，也不要放大本机内存和临时磁盘压力。

### 2y 只读访问 wrapper

`rs_core/data/postgres_dataset.py` 提供 local/trial 只读 wrapper，默认关闭。开启方式：

```bash
RS_POSTGRES_DATASET_ENABLED=1
```

实现只通过 `docker compose exec -T postgres psql` 发起轻量 `SELECT`，默认 compose 文件、service、db/user 与 `scripts/data/import_recent2y_to_postgres.py` 保持一致；不新增 psycopg/ORM 依赖，不读取或打印 DSN/password。`/ready` 会追加 public-safe 的 `postgres_dataset` 状态；若 Docker/PostgreSQL 不可用，Safe wrapper fail-open 为 degraded，不阻塞推荐服务。

只读 smoke 示例：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/data/smoke_postgres_dataset.py --health --summary
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/data/smoke_postgres_dataset.py --product <parent_asin>
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/data/smoke_postgres_dataset.py --user <user_id> --window-name recent_2y --limit 50
```

`--limit` 会在 wrapper 内夹到最大 200，避免本地 trial 查询放大资源占用。默认 smoke 脚本用于观察状态，即使 disabled/degraded 也会输出 JSON；如果需要把它作为检查门禁，可加 `--require-ok`，此时 `health.status != ok` 会返回非零退出码。

## 本地命令必须使用项目 `.venv`

Windows 示例：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_run_service.py
```

不要直接使用系统 Python。需要跑测试时优先 targeted 文件或单个用例，不跑 full pytest。

## 在线召回架构边界

当前在线召回服务采用分层降级：Qdrant two_tower provider 是主召回入口；PostgreSQL candidate store providers 承接 `item_neighbors`、`usercf_candidates`、popular/category 等结构化候选；Pool500 JSONL 仍作为本地 fallback/backfill，不作为线上主存储；RAG 只提供 evidence-only grounding 和解释证据，不把 RAG chunk collection 伪装成推荐候选主召回。

候选库导入脚本 `scripts/serving/import_candidate_store_to_postgres.py` 默认 dry-run，只做 schema 分类和行数报告；只有显式 `--write` 才通过 docker compose `psql` stdin 写入本地 PostgreSQL，并使用幂等 `ON CONFLICT`。命令参数只接受 compose/service/db/user 等非 secret 配置，不在命令行传入 password/token。

## Qdrant RAG build 三档

1. **dry-run（默认建议）**：只检查配置和 manifest，不写入远端 Qdrant。
2. **tiny smoke**：小样本、短超时、限流，确认 collection/schema/embedding 链路可用。
3. **user-approved live build**：用户明确授权后再跑；需要监控资源，不在本机打满 12GB 内存，不默认全量索引。

本地配置入口：`configs/serving/online_service.local_qdrant.yaml`。`RS_QDRANT_URL`、`RS_QDRANT_HOST`、`RS_QDRANT_PORT` 等 env 会覆盖 RAG/two_tower 等 Qdrant 连接目标；Qdrant 不可用、依赖缺失或向量命中为空时，语义上降级到 BM25/local fallback，不把 fallback 包装成 Qdrant 成功。

## MinIO artifact dry-run / upload

先用 dry-run 生成计划，不联网：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/artifacts/upload_to_minio.py \
  --manifest configs/artifacts/pool500_serving_manifest.yaml \
  --dry-run
```

显式确认本地 MinIO 已启动、bucket 已准备、`.env` 密钥只用于本机后，再执行 upload/verify。当前只纳管 Pool500、RAG、DeepFM/COLD/two_tower/label 等核心产物；Qwen/LoRA 只预留字段，不自动上传。

## 外部 vLLM / OpenAI-compatible 推理

FastAPI serving 不启动 vLLM，也不默认加载 Qwen。若要接外部 vLLM/OpenAI-compatible endpoint，先单独启动模型服务，再设置：

```bash
RS_AGENT_INFERENCE_POLICY=openai_compatible
RS_AGENT_OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:<vllm-port>/v1
RS_AGENT_OPENAI_COMPATIBLE_MODEL=<model-name>
RS_AGENT_OPENAI_COMPATIBLE_API_KEY=<local-token>
```

`/ready` 只报告 provider、endpoint/model 是否配置和 fallback policy，不发真实 probe，不打印 API key、完整 endpoint 或 prompt。

## 组件定位

- FastAPI：推荐 Agent API 编排层。
- Qdrant：RAG/two_tower/语义向量检索试运行后端，支持 env 覆盖和 fallback diagnostics。
- MinIO：本地 trial artifact store，可选 profile + manifest/resolver/upload dry-run。
- MLflow：仍为后续实验追踪/模型注册预留。
- vLLM/Qwen：外部 OpenAI-compatible provider 可选接入；默认 disabled，不默认本地加载模型或启动 vLLM。
