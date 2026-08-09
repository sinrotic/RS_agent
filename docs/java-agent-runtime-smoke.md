# Java Agent Runtime 真实链路 Smoke

Java 单元测试通过，只能证明 Runtime 在本地内存模式下可用；真实的 Gateway → Recommend → Agent 链路需要先启动远程 app compose 和 middleware compose。

## 启动前检查

- Redis 可连接：`redis-cli -h 127.0.0.1 -p 6379 ping` 返回 `PONG`。
- Gateway `18088`、Recommend `18103`、Agent `18104` 的 `/actuator/health/readiness` 返回 HTTP 200。
- `.env` 已配置数据库、Redis、Nacos、LLM key，且 Catalog projection 已完成。
- Docker CLI 能连接 Docker daemon；仅安装 CLI 不足以启动 compose。

## 启动与执行

```bash
cd deploy/remote/infra
docker compose --env-file .env up -d

cd ../app
docker compose --env-file .env up -d
RS_SMOKE_PROFILE_USER_ID=imported-user-id bash smoke.sh
```

`smoke.sh` 默认验证注册、登录、会话创建、首页推荐和 Agent 对话；`full-commerce` 模式还需要设置 `RS_SMOKE_ITEM_ID` 与 `RS_SMOKE_SKU_ID`。

如果部署在 SSH tunnel 或反向代理后，可用 `RS_SMOKE_GATEWAY_URL` 覆盖 Gateway 地址。只有在 readiness 已由外部探针验证时，才设置 `RS_SMOKE_PREFLIGHT=false` 跳过本地前置检查。

## 当前环境结果

当前机器 Redis 返回 `PONG`，但 Gateway、Recommend、Agent 端口均未监听，Docker daemon 不可用。因此本轮只能完成 Java 集成测试，不能宣称真实端到端 Smoke 通过；启动依赖后重新执行上述命令即可。
