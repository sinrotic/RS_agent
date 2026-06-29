# deploy

部署编排层，用于放置服务容器、网关和本地/远程部署脚本。

## 目录边界

- `docker/`：按服务拆分的 Dockerfile，只负责打包入口和运行命令。
- `nginx/`：API 网关配置，当前按 `/api/recommend`、`/api/recall`、`/api/rank` 分发到 online-service，按 `/api/chat`、`/api/session/*`、`/api/feedback`、`/api/rag/*` 分发到 agent-service。
- `docker-compose.yml`：按 profile 组合启动 frontend、online、agent、worker、gateway，并可选启动 MySQL、Redis、MinIO 与 Milvus infra。
- `local/`：本地 serving + infra 组合；其中 MySQL profile 是当前 local/trial SQL 结构化库主路径，Milvus profile 是当前 RAG 向量检索主路径。

## Compose profiles

- `frontend`：只启动 React/Vite build 后的 Nginx 静态前端，端口 `127.0.0.1:5173:80`。
- `online`：只启动 `rs_core/serving/api/online_app`，端口 `127.0.0.1:8000:8000`。
- `agent`：只启动 `rs_core/serving/api/agent_app`，端口 `127.0.0.1:8001:8001`。
- `gateway`：启动 Nginx gateway，端口 `127.0.0.1:8080:8080`，依赖 frontend、online、agent。
- `worker`：启动 `data_worker` 和 `offline_worker`，默认命令均为 `health`，不触发重任务。
- `infra`：可选启动 MySQL、Redis、MinIO 与 Milvus Standalone；默认不启动，只用于手动 smoke 或远程/夜间验证。local/trial 结构化库主路径为 MySQL，RAG 向量检索主路径为 Docker Milvus。

`infra` volumes 写入 `db/mysql`、`data/redis`、`data/minio`、`db/milvus`。这些是本地状态目录，不应作为代码产物提交；清理前需确认没有仍需保留的本地实验数据。MySQL 的项目级持久化目录固定为 `db/mysql`，Milvus Docker 数据固定为 `db/milvus`，便于与后续 `db/scylla` 长文本存储规划对齐。

Milvus Docker URI 分两类：宿主机脚本使用 `http://localhost:19530`，compose 内服务通过 `RS_MILVUS_URI=http://milvus-standalone:19530` 访问；collection 固定为 `rs_agent_rag_chunks_milvus_v1`。

## 轻量 smoke

```bash
docker compose -f deploy/docker-compose.yml --profile online up --build online_service
curl http://127.0.0.1:8000/health

docker compose -f deploy/docker-compose.yml --profile agent up --build agent_service
curl http://127.0.0.1:8001/health

# 轻量 gateway smoke（需要同时启 frontend/online/agent/gateway profile）
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/ci/run_gateway_smoke.py --base-url http://127.0.0.1:8080
```

`scripts/ci/run_gateway_smoke.py` 会启动 frontend + online + agent + gateway profiles，调用 `scripts/ci/gateway_smoke.py` 验证 `/api/health/online`、`/api/health/agent`、`/`、`/api/recommend`、`/api/recall`、`/api/rank`、`/api/session/start`、`/api/chat`、`/api/feedback` 和 `/api/rag/query`，最后自动执行 `down`；失败时将 compose logs 写到 `outputs/smoke/gateway/`，不输出 secret。Worker 默认执行 `health`，避免在本地隐式触发重训练、全量数据生成或大规模评估。

## CI / hardening checks

默认轻量迁移硬化检查：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py
```

该命令只运行 focused architecture pytest、migration scope ruff 和 `docker compose config --profiles`，不会默认启动 infra、gateway 容器、frontend build、Milvus RAG 全量导入、full-data import 或训练任务。本机执行仍按 12GB 可承受、14GB 上限控制；超过该范围的 Milvus/MinIO/MySQL 全量任务、full-data import、full-training 或模型加载应改为手动 profile、限流 smoke 或远程/offload。需要更完整本地验证时再显式追加：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --frontend-build
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/ci/run_migration_hardening_checks.py --gateway-smoke
```

`--gateway-smoke` 会构建并启动 frontend/online/agent/gateway profile，运行结束自动 `down`；`infra` profile、Milvus RAG 全量导入、MinIO/MySQL 全量任务和 heavy training 仍不属于默认 CI。
