---
id: kb-development-guide
type: runbook
status: current
owner: project-maintainers
last_verified: 2026-10-18
confidence: confirmed
---

# 开发、测试与部署指南

服务可靠性新增回归与远程验收见 [2026-09-05 修复记录](../superpowers/plans/2026-09-05-service-reliability-repairs.md)。BGE HTTP 契约测试使用 tests/test_bge_runtime_http.py，不加载模型权重。

## 环境基线

| 组件 | 版本/要求 | 依据 |
| --- | --- | --- |
| Java | 21 | `java_agent/pom.xml`、CI Temurin 21 |
| Maven | 能构建 Java 21/Spring Boot 4 项目 | Maven wrapper 当前不存在，使用系统 Maven |
| Python | 包声明 `>=3.10`；CI 使用 3.11 | `python_agent/pyproject.toml`、CI |
| Node.js | 20 | CI 和 Java 前端 README |
| Docker Compose | 支持 profiles 和 health condition | Java/Python deploy compose |
| 内存 | 默认按 12GB 可承受、14GB 硬上限规划本地任务 | 根 `CLAUDE.md` |

预计超过 14GB 的模型加载、全量导入、训练、评估或大数据任务必须改为限流 smoke、手动 profile 或远程执行。

## 开发前检查

在仓库根目录执行：

```powershell
git status --short
git branch --show-current
```

当前仓库经常存在并行中的未提交改动。不要重置、覆盖或顺手格式化与当前任务无关的文件。开始领域或架构修改前，依次阅读：

1. [项目规则](../../CLAUDE.md)
2. [领域词汇](../../CONTEXT.md)
3. 与修改范围相关的 [ADR](../adr/)
4. [项目当前状态](project-overview.md)
5. 对应模块的 README、配置和测试

需求和 PRD 使用 GitHub Issues，具体命令与中文要求见 [Issue tracker](../agents/issue-tracker.md)。

## Java 开发

### 全量测试

从仓库根目录运行：

```powershell
mvn -B -f java_agent/pom.xml test
```

这是 CI 的 Java 门禁。它会覆盖父 POM 中登记的所有模块。

### 聚焦模块测试

```powershell
mvn -B -f java_agent/pom.xml -pl rs-service-agent -am test
mvn -B -f java_agent/pom.xml -pl rs-service-recommend -am test
mvn -B -f java_agent/pom.xml -pl rs-service-catalog -am test
```

`-am` 同时构建依赖模块。改动 Gateway、公共父配置、跨服务 DTO 或部署契约后，仍应回到全量测试。

### 打包

```powershell
mvn -B -f java_agent/pom.xml clean package
```

不要在只需要单元测试时默认启动全部基础设施。需要真实 MySQL、Redis、ScyllaDB、Milvus 或模型服务的测试应通过显式 profile、环境变量或远程 tunnel 运行。

## Java 前端

```powershell
Set-Location java_agent/frontend
npm ci
npm run lint
npm test
npm run build
```

本地联调：

```powershell
npm run dev
```

Vite 默认运行在 `http://localhost:5173` 并将 `/api` 代理到 Java Gateway。真实模式不得把长效凭据写入 `localStorage`；认证安全模型见 [Java 前端 README](../../java_agent/frontend/README.md)。

## Python 开发

### 安装

仓库根目录已有 `.venv` 时：

```powershell
.venv\Scripts\python.exe -m pip install -e ".\python_agent[dev,serving]"
```

需要 Milvus、Elasticsearch、Cassandra、Artifact 或训练依赖时再显式安装对应 extra；不要为了轻量测试安装 `training` 全家桶。

### CI 等价轻量门禁

```powershell
Set-Location python_agent
..\.venv\Scripts\python.exe -m ruff check rs_core scripts/ci/validate_engineering_contracts.py scripts/ci/select_tests_by_marker.py tests
..\.venv\Scripts\python.exe scripts/ci/validate_engineering_contracts.py
..\.venv\Scripts\python.exe -m pytest -m "unit or smoke" -q
..\.venv\Scripts\python.exe -m pytest -m "serving" -q
```

CI 实际先用 `scripts/ci/select_tests_by_marker.py` 选择已登记测试，再 collect 并运行。新增测试时应使用 `unit`、`smoke`、`serving`、`slow`、`gpu`、`experiment`、`frontend` 中合适的 marker。

### 聚焦工程契约

```powershell
Set-Location python_agent
..\.venv\Scripts\python.exe -m pytest tests/contracts/test_engineering_contracts.py -q
..\.venv\Scripts\python.exe scripts/ci/validate_engineering_contracts.py
```

实验、训练和大规模评估默认不属于轻量门禁。执行前先确认输入范围、输出目录、预计内存、GPU、运行时间和是否会覆盖正式 Artifact。

## Python 前端

```powershell
Set-Location python_agent/frontend
npm ci
npm run lint
```

Python 前端是原型/演示入口，不应与 Java 主前端的 API 和认证契约混为一套。

## 测试矩阵

| 变更类型 | 最低验证 | 追加验证 |
| --- | --- | --- |
| Java 单服务内部实现 | 对应模块测试 | 全量 Maven test |
| Gateway 路由、认证、身份头 | Gateway filter/route test | Java 前端 wire test、真实 Gateway smoke |
| Agent loop、工具、Session | Agent service test | MySQL/Scylla/Redis integration、SSE smoke、恢复测试 |
| Catalog Schema/缓存/补全 | Catalog focused test | SQL migration、批量契约、Redis 降级、Gateway smoke |
| Recommend/RAG | Recommend focused test | Elasticsearch/Milvus readiness、trace、真实 Catalog hydration |
| Java 前端类型或 API client | `lint` + `test` | `build` + Gateway smoke |
| Python core | ruff + focused pytest | unit/smoke marker 门禁 |
| Python serving | serving marker | Docker gateway smoke |
| Python route/Artifact/governance | engineering contract validator | 对应 gate、manifest 重放和资源审计 |
| 数据库 Schema | 幂等迁移测试 | 空库安装、旧版本升级、readiness/schema version 检查 |
| full-commerce | Order/Inventory/Payment/Seckill focused tests | Kafka、幂等、补偿和 full-commerce smoke |

测试通过只证明被覆盖范围；不得用 smoke 代替正式数据质量、模型效果或 promotion 结论。

## Java 远程部署

### 基础设施

远程 Linux 主机：

```bash
cd ~/RS_agent_java/infra
cp .env.example .env
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

### 应用

```bash
cd ~/RS_agent_java/app_deploy
cp .env.example .env
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

默认 `recommend` 模式启动 User、Catalog、Recommend、Agent、Model、Platform Trace 和 Gateway。完整交易模式：

```bash
cd ~/RS_agent_java/infra
docker compose --env-file .env --profile full-commerce up -d

cd ~/RS_agent_java/app_deploy
RS_DEPLOYMENT_PROFILE=full-commerce \
  docker compose --env-file .env --profile full-commerce up -d
```

启动前迁移和 Catalog bootstrap 的完整步骤见 [Java app runbook](../../java_agent/deploy/remote/app/README.md)。不要跳过 schema version、projection run 状态和 source/projected count 检查。

### Java smoke

```bash
RS_SMOKE_PROFILE_USER_ID=imported-user-id bash smoke.sh
```

`full-commerce` 还需要显式提供 item/SKU。Gateway 默认远程绑定 `127.0.0.1:18088`，Platform Trace 为 `127.0.0.1:18108`。

## Python Docker smoke

从 `python_agent/` 运行：

```bash
docker compose -f deploy/docker-compose.yml --profile online up --build online_service
curl http://127.0.0.1:8000/health

docker compose -f deploy/docker-compose.yml --profile agent up --build agent_service
curl http://127.0.0.1:8001/health
```

完整轻量 Gateway smoke：

```powershell
Set-Location python_agent
..\.venv\Scripts\python.exe scripts/ci/run_gateway_smoke.py --base-url http://127.0.0.1:8080
```

脚本应在结束后执行 compose `down`；失败日志进入 `outputs/smoke/gateway/`，不得输出 secret。详细 profile 说明见 [Python deploy README](../../python_agent/deploy/README.md)。

## 远程数据 tunnel

本地开发可通过 SSH 将远程 `127.0.0.1` 服务映射为本地 MySQL、Redis、Nacos、Elasticsearch、MinIO、ScyllaDB、Milvus 和 vLLM 端口。完整 PowerShell 命令和端口表见 [Remote Data Tunnel](../dev-remote-data-tunnel.md)。

规则：

- SSH alias `server` 必须来自开发者本地配置，不能提交密钥。
- 本地应用只连接 `127.0.0.1`；关闭 tunnel 终端即关闭访问。
- 不为方便联调而开放远程数据库公网端口。
- 若本地端口冲突，只修改 tunnel 本地侧和本地配置，不修改远程绑定。

## 完成一次迭代的最小清单

2026-10-18 起，个人推荐 Agent 的固定多轮 API 验收及计量口径见 [本地基线](../reports/agent-capability-baseline-20261018/README.md)。真实模型尝试的逐次观测、Skill Benchmark 用量账本与 Trace 有界导出参数见 [P1 首批实现](../reports/agent-model-observation-20261018/README.md)。平台现已接入最终调用账本和覆盖率，缺失或提前停止的未确认用量不能当作 0；独立 OTLP/Langfuse 开关、外发字段控制与本地验收见 [平台计量及 OTLP 报告](../reports/agent-otlp-and-usage-20261018/README.md)。外部导出默认关闭，真实远程验收和运维指标注册仍待补齐。

1. Issue/PRD 的验收条件可以映射到代码和测试。
2. 使用规范领域词汇，没有引入同义概念。
3. API、Schema、数据角色和部署 profile 的影响已检查。
4. 执行与风险相称的 focused test、contract test 和 smoke。
5. 更新相关知识库、ADR、runbook 或 route registry。
6. 记录未运行的重测试及原因，不把“未验证”写成“通过”。
7. 检查 `git diff --check` 和 `git status --short`，确认没有覆盖无关工作。
