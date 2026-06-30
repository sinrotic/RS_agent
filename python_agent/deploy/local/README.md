# RS_agent 本地试运行部署（local/trial/non-production）

本目录只用于本机试运行 FastAPI serving + Docker Milvus RAG + MinIO 的最小部署骨架，不声明 production-ready。当前阶段不默认启动 vLLM/Qwen、MLflow、BentoML/Triton、Kubernetes/KServe，也不默认训练、全量索引、全量评估或 full pytest。Milvus 使用 Docker Standalone profile 运行，MinIO 是可选 artifact profile，默认不上传 Qwen/LoRA。

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
docker compose -f deploy/local/docker-compose.yml --profile milvus --profile serving up --build
```

如需同时试运行本地 artifact store，可显式加 MinIO profile：

```bash
docker compose -f deploy/local/docker-compose.yml --profile milvus --profile minio --profile serving up --build
```

默认只做 local smoke。服务启动命令仍会经过 `scripts/serving/run_service.py` 的非 loopback strict-auth 检查。MinIO 端口只绑定 `127.0.0.1:9000/9001`，`.env` 中的 `RS_MINIO_*` 只能放本地占位或本机密钥，不能提交真实密钥。

## 本地 MySQL 结构化库准备（主路径）

MySQL 是当前 local/trial 唯一结构化库主路径，用于数据集只读 smoke、候选库导入与在线召回候选读取；旧 SQL 路径已经退役，不再作为本地兼容目标。MySQL schema 初始化文件在：

```text
deploy/local/mysql/init/001_schema.sql
```

它会创建空表：`products`、`interactions`、`user_sequences`、`agent_sessions`、`feedback_events`、`recommendation_logs`、`artifact_registry`、`eval_runs`、`users`，并初始化在线召回候选库表：`item_neighbors`、`usercf_candidates`、`popular_candidates`、`category_candidates`、`user_category_profiles`、`pool_candidates`、`candidate_store_manifests`。其中 `users` 只是 local/trial 账号/画像占位表，不等同于下一阶段要构建的 user-store 业务模型；merchant/inventory 业务表仍延后，不在本次 local/trial schema 中提前新增。

磁盘空间不足时，先不要导入 2y。建议等远程备份校验完成、本地删除不再需要的 full/2y 副本并释放空间后，再做 2y smoke/import。

只启动 MySQL 空库：

```bash
cp deploy/local/.env.example deploy/local/.env
# 修改 deploy/local/.env 里的 RS_MYSQL_PASSWORD / RS_MYSQL_ROOT_PASSWORD，占位值不能用于长期运行。
docker compose -f deploy/local/docker-compose.yml --profile mysql up -d mysql
```

本地连接串仅用于人工理解，不要把真实密码写进命令行或日志：

```text
mysql://rs_agent:<password>@127.0.0.1:${RS_MYSQL_HOST_PORT:-3307}/rs_agent
```

MySQL 数据目录使用项目本地 bind mount，落在 D 盘项目根目录下：

```text
db/mysql
```

该目录只用于本地数据库运行，已被 `.gitignore` / `.dockerignore` 忽略，不要提交。迁移或备份 dump 建议临时放在：

```text
data/mysql_migration
```

资源边界：导入 2y 时必须流式/分批，不要一次性把 JSONL 全量读入内存；索引构建宁可慢一些，也不要放大本机内存和临时磁盘压力。MySQL CLI 密码通过容器内 `MYSQL_PASSWORD`/`MYSQL_PWD` 传递，脚本参数只接受 compose/service/db/user 等非 secret 配置，不在命令行传入 password/token。

### 2y MySQL 只读访问 wrapper

`rs_core/data/mysql_dataset.py` 提供 local/trial 只读 wrapper，默认关闭。开启方式：

```bash
RS_MYSQL_DATASET_ENABLED=1
```

实现只通过 `docker compose exec -T mysql sh -lc 'MYSQL_PWD="$MYSQL_PASSWORD" mysql ...'` 发起轻量 `SELECT`，默认 compose 文件、service、db/user 与 `scripts/data/import_recent2y_to_mysql.py` 保持一致；不新增 ORM 依赖，不读取或打印 URL/password/stderr/command。若 Docker/MySQL 不可用，Safe wrapper fail-open 为 degraded，不阻塞推荐服务。

只读 smoke 示例必须使用项目 `.venv`：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/data/smoke_mysql_dataset.py --health --summary
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/data/smoke_mysql_dataset.py --product <parent_asin>
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/data/smoke_mysql_dataset.py --user <user_id> --window-name recent_2y --limit 50
```

`--limit` 会在 wrapper 内夹到最大 200，避免本地 trial 查询放大资源占用。默认 smoke 脚本用于观察状态，即使 disabled/degraded 也会输出 JSON；如果需要把它作为检查门禁，可加 `--require-ok`，此时 `health.status != ok` 会返回非零退出码。

Amazon base raw 入库脚本 `scripts/data/import_amazon_base_to_mysql.py` 默认 dry-run；只有显式 `--write` 才写库。Phase 1 tiny smoke 可使用 `--create-schema --limit 10 --write` 创建/验证 `amazon_items_base` 与 `amazon_reviews_base`。其中 `amazon_reviews_base` 只保存结构化字段、`text_len`、`has_review_title`、`has_review_text` 和 `review_text_ref`，不保存完整 review title/text 正文，正文后续单独进入 Scylla review text store。

候选库导入脚本 `scripts/serving/import_candidate_store_to_mysql.py` 默认 dry-run，只做 schema 分类和行数报告；只有显式 `--write` 才通过 docker compose `mysql` stdin 写入本地 MySQL，并使用幂等 `ON DUPLICATE KEY UPDATE`。recent2y 导入脚本 `scripts/data/import_recent2y_to_mysql.py` 同样默认 dry-run，只有显式 `--write` 才写库；不要在本机默认启动全量导入。

## 本地 Scylla review text store 预留

Scylla 只作为后续 review 长文本存储预留，不在当前 MySQL 2y filtered base/raw 导入阶段自动写入。Windows 本机不要把 `/var/lib/scylla` bind mount 到项目目录 `data/scylla`：该方式在 Docker Desktop 文件共享层上容易导致 Scylla system keyspace flush 失败、commitlog 异常膨胀。当前 local compose 使用 Docker named volume：

```text
scylla_data:/var/lib/scylla
```

这仍然是持久化磁盘存储，但由 Docker/WSL Linux volume 管理，不直接出现在项目目录。查看位置和占用可用：

```bash
docker volume inspect local_scylla_data
docker run --rm -v local_scylla_data:/data alpine du -sh /data
```

如果 Docker Compose 项目名不同，实际 volume 名称以 `docker volume ls` 为准。正式导入 review 正文前，需要单独设计 Scylla schema/importer；不要复用 candidate-store Cassandra schema。

## 本地命令必须使用项目 `.venv`

Windows 示例：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_run_service.py
```

不要直接使用系统 Python。需要跑测试时优先 targeted 文件或单个用例，不跑 full pytest。

## 在线召回架构边界

当前在线召回服务采用分层降级：MySQL-backed candidate store providers 承接 `item_neighbors`、`usercf_candidates`、popular/category 等结构化候选；Pool500 JSONL 仍作为本地 fallback/backfill，不作为线上主存储；RAG 向量证据已切到 Milvus，本地保留 SQLite BM25 fallback，只提供 evidence-only grounding 和解释证据，不把 RAG chunk collection 伪装成推荐候选主召回。

候选库导入脚本 `scripts/serving/import_candidate_store_to_mysql.py` 默认 dry-run，只做 schema 分类和行数报告；只有显式 `--write` 才通过 docker compose `mysql` stdin 写入本地 MySQL，并使用幂等 `ON DUPLICATE KEY UPDATE`。命令参数只接受 compose/service/db/user 等非 secret 配置，不在命令行传入 password/token。

## Milvus RAG Docker 检索

当前 RAG 向量后端使用 Docker Milvus Standalone，不再把 Milvus Lite `.db` 作为运行态 target。宿主机脚本连接 `http://localhost:19530`，Docker serving 通过 compose network 连接 `http://milvus-standalone:19530`；collection 固定为 `rs_agent_rag_chunks_milvus_v1`，期望 row count 为 `371616`。Milvus 不可用、依赖缺失或向量命中为空时，语义上降级到 SQLite BM25/local fallback，不把 fallback 包装成 Milvus 成功。

启动 Milvus 后可用项目 `.venv` 做连接检查：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -c "from pymilvus import MilvusClient; c=MilvusClient(uri='http://localhost:19530'); print(c.list_collections())"
```

如 Docker Milvus collection 缺失或需要重建，优先从已验证的 Milvus Lite 迁移备份复制：`scripts/recall/copy_milvus_collection.py --source-uri <milvus_lite_backup.db> --target-uri http://localhost:19530 --collection-name rs_agent_rag_chunks_milvus_v1`。如果要从原始 item 文本重新编码，再先 dry-run，然后显式执行 `scripts/recall/build_milvus_rag_index.py --milvus-uri http://localhost:19530` 全量导入；不要在本机默认触发重建。

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
- Milvus：RAG/语义证据向量检索试运行后端，使用 Docker Standalone server 和 fallback diagnostics。
- MinIO：本地 trial artifact store，可选 profile + manifest/resolver/upload dry-run。
- MLflow：仍为后续实验追踪/模型注册预留。
- vLLM/Qwen：外部 OpenAI-compatible provider 可选接入；默认 disabled，不默认本地加载模型或启动 vLLM。
