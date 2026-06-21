# Serving 受控试用部署 Checklist

本文档用于把当前 `rs_core/serving` 从本地 demo 运行收口到“可受控试用”的启动、鉴权、持久化和验收流程。它不把当前单进程 FastAPI 服务描述成生产级多实例 serving；当前定位仍是 **modular monolith + single-process trial serving**。

## 1. 适用范围

- 适用于 `scripts/serving/run_service.py` 启动的 RS Agent FastAPI 服务。
- 适用于 P0/P1 后的受控试用形态：`X-Request-ID`、strict auth、debug/simulation 隔离、SQLite + JSONL 轻量持久化。
- 不适用于公开互联网多租户服务；若要面向更公开的多用户试用，后续还需要 per-session owner binding 或登录态绑定。

## 2. 部署前检查

- [ ] 使用项目默认虚拟环境：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe`。
- [ ] 确认当前 serving config 可加载，默认由 `configs/governance/current_route_registry.yaml` 指向 current online route。
- [ ] 确认本次只部署受控试用，不把 `single_process_in_memory` 会话状态当成生产并发方案。
- [ ] 确认浏览器侧只放 low-privilege trial token，不放 debug token 或 simulation token。

## 3. 本地 loopback 启动

本机试用、前后端联调和 smoke 验证优先使用 loopback：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/serving/run_service.py --host 127.0.0.1 --port 8000
```

可选本地热重载：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/serving/run_service.py --host localhost --port 8000 --reload
```

检查项：

- [ ] `--host` 是 `127.0.0.1`、`localhost` 或 `::1`。
- [ ] 本地 loopback 可在未设置 `RS_SERVING_STRICT_AUTH=1` 时运行，便于开发。
- [ ] 不要用 loopback 默认放行配置去绑定 `0.0.0.0` 或真实网卡 IP。

## 4. 非 loopback 启动护栏

只要绑定到 `0.0.0.0`、局域网 IP 或其他非 loopback host，启动脚本会强制要求 strict auth 和必要 token。推荐配置：

```bash
export RS_SERVING_STRICT_AUTH=1
export RS_TRIAL_TOKEN="<generate-strong-random-trial-token>"
export RS_DEBUG_TOKEN="<generate-strong-random-debug-token>"
export RS_ENABLE_SIMULATION_ENDPOINTS=0
export RS_SERVING_PERSISTENCE_ENABLED=1
export RS_SERVING_SQLITE_PATH=outputs/serving/serving_persistence.sqlite
export RS_SERVING_JSONL_PATH=outputs/serving/serving_events.jsonl

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/serving/run_service.py --host 0.0.0.0 --port 8000
```

注意：当前 FastAPI app 中 simulation endpoint 默认可用。非 loopback 受控试用如果不需要 simulation，推荐显式设置 `RS_ENABLE_SIMULATION_ENDPOINTS=0`；如果需要开启 simulation，则必须配置强随机 simulation token：

```bash
export RS_ENABLE_SIMULATION_ENDPOINTS=1
export RS_SIMULATION_TOKEN="<generate-strong-random-simulation-token>"
```

非 loopback 启动检查项：

- [ ] `RS_SERVING_STRICT_AUTH=1`。
- [ ] `RS_TRIAL_TOKEN` 非空。
- [ ] `RS_DEBUG_TOKEN` 非空。
- [ ] 若未显式设置 `RS_ENABLE_SIMULATION_ENDPOINTS=0`，`RS_SIMULATION_TOKEN` 非空。
- [ ] 启动失败时先检查 env，而不是绕过 `_validate_serving_bind_security()`。

## 5. Token 边界

| Token | 目标用途 | 允许范围 | 禁止事项 |
|---|---|---|---|
| `RS_TRIAL_TOKEN` | 受控试用用户/API 调用 | `/ready`、session、chat、feedback、recommend、session export | 不允许访问 `/recall`、`/demo/e2e`、simulation |
| `RS_DEBUG_TOKEN` | 内部调试和诊断 | 兼容 trial endpoint，并允许 `/recall`、`/demo/e2e` | 不应下发到浏览器环境变量 |
| `RS_SIMULATION_TOKEN` | 多角色仿真沙盒 | simulation endpoint | 不应作为普通试用 token 使用 |

请求头建议统一使用：

```http
Authorization: Bearer <token>
```

当前服务也兼容 `X-RS-Token`、`X-Debug-Token`、`X-Simulation-Token`，但文档和脚本建议只使用 Bearer token，减少误用。试用和调试 token 优先通过环境变量或 secret store 注入；不要在共享机器、CI 日志或可被他人查看的 shell history 中直接写命令行 token。

## 6. Endpoint 权限矩阵

| Endpoint | 用途 | strict auth 下权限 | 开关 |
|---|---|---|---|
| `GET /health` | liveness 探活，不初始化 service | public | 无 |
| `GET /ready` | readiness 和 online route 摘要 | trial/debug | 无 |
| `POST /session/start` | 创建会话 | trial/debug | 无 |
| `POST /chat` | 多轮对话 | trial/debug | 无 |
| `POST /feedback` | 用户反馈 | trial/debug | 无 |
| `GET /session/{session_id}` | public session export | trial/debug | 无 |
| `POST /recommend` | public 推荐入口 | trial/debug | 无 |
| `POST /recall` | debug-only 候选召回 | debug | `RS_ENABLE_RECALL_ENDPOINT` |
| `POST /demo/e2e` | 内部闭环 demo | debug | `RS_ENABLE_DEMO_ENDPOINT` |
| `POST /simulation/scene` | 单场景用户仿真 | simulation/debug | `RS_ENABLE_SIMULATION_ENDPOINTS` |
| `POST /simulation/batch` | 批量用户仿真 | simulation/debug | `RS_ENABLE_SIMULATION_ENDPOINTS` |

重点验收：

- [ ] strict auth 开启时，无 token 调 trial endpoint 返回 `401`。
- [ ] trial token 调 `/recall` 返回 `403`。
- [ ] debug token 调 `/recall` 返回 `200`。
- [ ] endpoint env gate 关闭时，即使 token 正确也返回 `403`。
- [ ] `/health` 始终不要求 token。

## 7. Request tracing

所有 HTTP 响应都应包含：

```http
X-Request-ID: <request-id>
```

规则：

- 如果请求传入合法 `X-Request-ID`，服务回显该值。
- 如果请求缺失或传入非法值，服务生成 UUID。
- session、turn、feedback、recommend/recall request summary 会记录 public-safe request id。
- 不要把 token、内部 tool trace、RAG context、diagnostics 等信息拼进 request id 或 public summary。

## 8. 轻量持久化配置

环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `RS_SERVING_PERSISTENCE_ENABLED` | disabled if empty/false-like | 是否启用 serving persistence |
| `RS_SERVING_SQLITE_PATH` | `outputs/serving/serving_persistence.sqlite` | SQLite 查询库 |
| `RS_SERVING_JSONL_PATH` | `outputs/serving/serving_events.jsonl` | append-only JSONL 事件日志 |

推荐受控试用启用：

```bash
export RS_SERVING_PERSISTENCE_ENABLED=1
export RS_SERVING_SQLITE_PATH=outputs/serving/serving_persistence.sqlite
export RS_SERVING_JSONL_PATH=outputs/serving/serving_events.jsonl
```

持久化边界：

- [ ] 只持久化 public-safe session metadata、turn display、feedback event、request summary。
- [ ] 不持久化 `AgentSession.to_dict()`。
- [ ] 不落盘 `runtime_trace`、`rag_context`、tool traces、score/source_scores、diagnostics、user_profile、long_memory 内部状态。
- [ ] persistence 初始化或写入失败时 fail-open，不阻断主请求。
- [ ] public session export 可以从 SQLite fallback 重建，但不恢复内部 Agent 状态。

## 9. 黑盒 smoke 验收

服务启动后优先通过环境变量注入 token，再运行 smoke 脚本：

```bash
export RS_TRIAL_TOKEN="<trial-token-from-secret-store>"
export RS_DEBUG_TOKEN="<debug-token-from-secret-store>"

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/serving/smoke_trial_service.py \
  --base-url http://127.0.0.1:8000 \
  --user-id online-u1
```

`smoke_trial_service.py` 仍保留 `--trial-token` 和 `--debug-token` 作为本地临时 fallback，但不建议在共享机器或 CI 中使用命令行 token。

本地未开启 strict auth 时，可省略 token，但这样不能验证 `/recall` 的 debug-only 权限边界：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/serving/smoke_trial_service.py \
  --base-url http://127.0.0.1:8000 \
  --user-id online-u1
```

smoke 通过标准：

- [ ] `/health` 返回 `200`。
- [ ] `/ready` 返回 `200`。
- [ ] `/session/start`、`/chat`、`/feedback`、`/session/{id}` 跑通一轮 public session。
- [ ] `/recommend` 返回 public display/items 结构。
- [ ] 每个响应都有 `X-Request-ID`，且合法请求 id 会被回显。
- [ ] 提供 debug token 时，trial token 调 `/recall` 返回 `403`，debug token 调 `/recall` 返回 `200`。

## 10. 代码级回归验证

推荐在改动 serving 相关代码后运行：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_serving_persistence.py tests/test_serving_run_service.py
```

如涉及前端展示或 token header 行为，再运行：

```bash
npm --prefix D:/sinrotic_code/python_project/summer/RS_agent/frontend run lint
npm --prefix D:/sinrotic_code/python_project/summer/RS_agent/frontend run build
```

## 11. 当前阶段不解决的问题

- 当前 session export 仍依赖 trial/debug token + `session_id`，尚未做 per-session owner binding。
- 当前服务仍是单进程内存 session，SQLite fallback 只用于 public 回看，不用于恢复内部多轮推理状态。
- Vite dev dependency advisory 属于前端工具链后续任务，不阻塞 serving runtime 的 P1/P2 受控试用闭环。
