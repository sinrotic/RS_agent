# RS Agent Java remote app services

## Agent 多用户请求调度

Agent 保持单活实例：同一 Session 的 Turn 顺序执行，不同 Session 并行。Compose 已传递执行层容量参数；`.env.example` 保留通用默认值，GPU 1 当前模型的已验收候选参数位于 [agent-gpu1-concurrency.env.example](agent-gpu1-concurrency.env.example)。把其中的键合并到既有 `.env`，更新 Agent JAR 后重建 Agent 服务即可使用；本文件不改变模型服务参数。

候选配置同时容纳最多 32 个活跃 Turn，最多 16 路模型调用，推荐流水线最多 4 路；模型与推荐容量等待上限均为 15 秒。工具调用结束、模型调用结束或异常退出都会释放对应许可，模型容量等待期间取消 Turn 会及时退出。超过活跃 Turn 容量的请求仍按原有忙碌协议返回，同一 Session 保持原来的有界队列。

真实测试覆盖完整 LLM 常规推荐、目录和持久历史；32 请求突发两批均完整通过。此结果不代表任意复杂推荐或持续压力均支持 32 并发，不应据此部署多个 Agent 活跃副本。数据、失败配置及测试范围见 [并发验收报告](../../../../docs/reports/agent-concurrency-optimization-20261011/README.md)。后续已按用户授权切换当前共享 Agent；复杂请求测试及依赖变更边界见 [部署后报告](../../../../docs/reports/agent-live-complex-concurrency-20261011/README.md)。

当前交易版本新增活动专属库存、跨实例任务租约和运维认证。部署前重跑 `rs_service_commerce_v1_schema.sql`，再更新 Inventory、Order、Seckill、Payment 和前端；已有活动不自动划拨。配置两枚不同、至少 32 字符的 `RS_COMMERCE_OPS_READ_TOKEN` / `RS_COMMERCE_OPS_WRITE_TOKEN` 及 `RS_COMMERCE_OPS_OPERATOR_ID`；空配置默认拒绝运维接口。详细接口、工作台、监控目标和真实联合验收见 [交易说明](../../../../docs/commerce-v1.md)。

## 库存与优惠券第一版

新增 Promotion 服务和可恢复 Checkout 流程，full-commerce 模式还需部署 rs-service-promotion-exec.jar，并执行新增 rs_service_commerce_v1_schema.sql。普通下单现在先返回 CREATING，需查询订单直到 WAITING_PAYMENT。服务端报价来自 checkout_offer，客户端 unitPrice 不再决定成交金额。

商品详情页可以领券、用券下单和取消返还；RS_CHECKOUT_MOCK_PAYMENT_ENABLED 默认 false，联调环境可显式开启模拟支付。交易 smoke 改为使用提前配置的隔离测试商品、SKU 与活动，需设置 RS_SMOKE_CAMPAIGN_ID；不会再自动重置库存。

完整接口、构建产物、数据示例及验证边界见 [交易第一版说明](../../../../docs/commerce-v1.md)。

This compose stack runs the executable Spring Boot jars built under `~/RS_agent_java/services`.

It joins the middleware network created by `~/RS_agent_java/infra/docker-compose.yml`.

## Deployment modes

- `recommend` is the default. It starts User, Catalog, Recommend, Agent, Model, Platform Trace, and Gateway. Trade routes are absent from Gateway.
- `full-commerce` additionally starts Order, Inventory, Promotion, Payment, Seckill, and Kafka. Gateway loads the legacy trade routes when `RS_DEPLOYMENT_PROFILE=full-commerce`; Checkout and Promotion routes are also defined in the base configuration.

Both modes run idempotent MySQL and Scylla migrations before Java services start. Migration versions are recorded in `rs_schema_version` and `agent_schema_version`; Agent refuses to start when its MySQL or Scylla version is missing or stale.

## 经过 LLM 的完整推荐优化

`RS_AGENT_LLM_SYNTHESIS_ENABLED=true` 允许内置模板在首轮普通品类、候选事实校验通过时，复用本轮已完成的真实召回与排序，让 LLM 直接生成最终回答。带额外要求、历史上下文、自定义模板、非空 UI 状态或事实不足的请求继续执行完整工具流程。此开关优先于 `RS_AGENT_DIRECT_RECOMMENDATION_ENABLED`，不会使用无模型的模板正文。

本地 vLLM 可使用 `RS_AGENT_COMPACT_TOOL_SCHEMAS_ENABLED=true`，按答案区块类型约束必要字段并省略无关的 null；商品卡片、比较、追问和 A2UI 仍可使用，自定义工具 schema 不变。固定运行配置放在动态证据前，便于模型复用提示词前缀。其他模型提供方默认关闭这两个开关；`local-qwen` 配置默认开启。

标准内置循环可复用本轮已成功加载且内容版本一致的技能，避免再次调用模型加载同一技能；失败、内容更新、自定义循环与钩子仍沿用原行为。RAG 委派配置已补齐标准 getter，实际 HTTP 调用会使用配置的服务地址。

`RS_AGENT_FINAL_ANSWER_MAX_TOKENS` 仅调整限定为最终答案的模型步骤，普通工具沿用原预算。`RS_AGENT_STREAM_REQUEST_TIMEOUT` 默认 `120s`，避免超过默认 30 秒的合法流式请求被提前关闭；延长期限不计为速度提升。完整耗时和失败实验记录见 [真实 LLM 流程评测](../../../../docs/reports/agent-llm-optimization-20261011/README.md)。

## Online feedback closed loop

Agent 会话投影与 Recommend 交付/反馈的数据源使用显式 Hikari 连接池，每个服务实例默认最多 8 个连接、保留 2 个空闲连接，获取连接最多等待 3000ms。可以通过 `.env` 中的 `RS_AGENT_MYSQL_{MAXIMUM_POOL_SIZE,MINIMUM_IDLE,CONNECTION_TIMEOUT_MS}` 和 `RS_RECOMMEND_FEEDBACK_JDBC_{MAXIMUM_POOL_SIZE,MINIMUM_IDLE,CONNECTION_TIMEOUT_MS}` 分别调整；多实例需要合计数据库连接预算。

一条会话事件的 Session、Turn 和工具投影在同一个短事务中更新；推荐交付头与商品批量写入仍共用原事务。Scylla 权威记录继续先写，反馈事件与偏好版本的事务边界保持不变。[完整流程优化与验收](../../../../docs/reports/agent-persistence-optimization-20261010/README.md)。

The Recommend container uses MySQL as the authoritative delivery/event/idempotency store and Redis as the rebuildable online preference projection:

```text
RS_RECOMMEND_FEEDBACK_PERSISTENCE=jdbc
RS_RECOMMEND_FEEDBACK_PROJECTION=redis
```

`mysql-migrate` applies `rs_service_recommend_schema.sql`. Explicit `like` and `dislike` events allocate a preference version and write an Outbox row in the same transaction. Redis projection failures return `PENDING`; the Recommend worker retries with bounded backoff and periodically rebuilds current profile preferences from MySQL.

The gateway smoke now verifies delivery attribution, visible exposure, `APPLIED/PENDING`, duplicate idempotency, preference-version visibility, reversal, and Agent `card_set_id` propagation. It requires at least one projected Catalog item.

## Catalog bootstrap

Schema creation is automatic. Catalog data projection still runs after the raw Amazon source import:

Project the canonical product rows from `amazon_items_base`. Each batch commits
the catalog upsert and its cursor in the same transaction:

```bash
python3 ~/RS_agent_java/scripts/project_catalog_to_mysql.py \
  --container rs-agent-java-mysql \
  --batch-size 5000 \
  --progress-every 10
```

If the command stops, use the `run_id` printed by the script and resume it:

```bash
python3 ~/RS_agent_java/scripts/project_catalog_to_mysql.py \
  --container rs-agent-java-mysql \
  --resume-run-id RUN_ID \
  --batch-size 5000 \
  --progress-every 10
```

Do not start Catalog acceptance checks until the latest run is `COMPLETED` and
the projected and source counts match:

```bash
docker exec rs-agent-java-mysql sh -lc \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -e \
  "SELECT run_id,status,processed_rows,source_rows FROM rs_catalog_projection_run ORDER BY run_id DESC LIMIT 1; \
   SELECT COUNT(*) AS catalog_rows,COUNT(DISTINCT item_id) AS distinct_items FROM rs_catalog_item;"'
```

## Start order

```bash
cd ~/RS_agent_java/app_deploy
cp .env.example .env

docker compose --env-file .env up -d
docker compose --env-file .env ps
```

For full commerce, start Kafka in the infra stack and activate the matching app profile:

```bash
cd ~/RS_agent_java/infra
docker compose --env-file .env --profile full-commerce up -d

cd ~/RS_agent_java/app_deploy
RS_DEPLOYMENT_PROFILE=full-commerce \
  docker compose --env-file .env --profile full-commerce up -d
```

Each Java container exposes Actuator liveness and readiness. Compose waits on readiness, which includes registered MySQL, Redis, discovery, and service-specific dependency indicators; Agent additionally checks MySQL and Scylla continuously.

After raw profile/catalog data is imported, run the gateway smoke. Full commerce also requires an item/SKU pair; the script creates disposable stock for that SKU before ordering:

```bash
RS_SMOKE_PROFILE_USER_ID=imported-user-id bash smoke.sh

RS_DEPLOYMENT_PROFILE=full-commerce \
RS_SMOKE_PROFILE_USER_ID=imported-user-id \
RS_SMOKE_ITEM_ID=item-id \
RS_SMOKE_SKU_ID=sku-id \
bash smoke.sh
```

Gateway is bound to remote `127.0.0.1:18088`. Use this for SSH tunnel or Cloudflare Tunnel.
Platform trace is bound to remote `127.0.0.1:18108` for direct observation calls during demos.

Catalog exact-ID reads use Redis as a cache and `rs_catalog_item` in MySQL as
the source of truth. The cache is enabled by default with a 24-hour TTL:

```bash
RS_CATALOG_CACHE_ENABLED=true
RS_CATALOG_CACHE_ITEM_TTL_SECONDS=86400
```

The first detail or batch request fills keys under
`rs:catalog:item:v2:*`; subsequent requests read those records from Redis.
The versioned prefix prevents a changed catalog projection from serving stale
records written with the previous serialization or field mapping.

Platform trace can also be reached through the gateway at `/api/platform/**`. In the remote compose stack it pulls
Agent, Recommend, and User traces over the internal Docker network when `RS_PLATFORM_TRACE_CLIENTS_ENABLED=true`.

## 2026-09-05 服务修复部署说明

默认 Model 改为真实 HTTP 适配器，Mock 只在 `mock-models` profile 下启用。配置 `RS_MODEL_RUNTIME_EMBEDDING_BASE_URL`；重排运行时就绪后再配置 `RS_MODEL_RUNTIME_RERANK_BASE_URL`。未配置能力返回 503，Agent 的直接模型连接仍按原配置运行。

平台 Trace 要求 `ADMIN` 或 `OBSERVER`，浏览器请求由 Gateway 注入可信角色；下游异常返回 502。反馈快照使用 `rs:pref:v2:*`，上线后等待 MySQL 分批重建并核验历史反馈和撤销，旧键不自动删除。

完整修复与验收见 [修复记录](../../../../docs/superpowers/plans/2026-09-05-service-reliability-repairs.md)。

## 发布校验与运行保障

2026-10-10 追加修复要求 User 与 Agent 一起发布，正式 Compose 已启用 Session 原子准入与归属校验。User 不可用时拒绝开启新 Turn，已结束 Session 仍可读历史；详情和验证范围见 [追加修复记录](../../../../docs/service-fixes-20261010.md)。本次发布产物使用新的 `outputs/service-completion-20261010/fixes-release` 目录，避免覆盖上一轮发布包。

先完成 JDK 21 的 `mvn package`、前端 `npm test`、`npm run build`、`npm run test:e2e` 和根目录 `python -m pytest tests -q`。随后在仓库根目录执行：

```bash
python java_agent/deploy/remote/app/prepare_service_release.py --output-dir outputs/service-completion-20261010/release
```

打包脚本检查 12 个 Spring Boot 可执行 JAR 和前端构建结果，生成 ZIP、源码及产物哈希清单、SHA256SUMS；同一输出目录不能覆盖已有发布包。清单描述当前工作区，包含未提交源码，不能只凭 Git HEAD 判断包的内容。脚本仅打包，不自动发布、迁移或加载模型。现有运行 `.env` 不进入发布包，`.env.example` 只是配置示例。

服务器解包到新的 release 目录，核对 SHA256SUMS 和每个产物的哈希。保留现有密钥与训练运行时配置，先取得数据库备份，再评估 Schema 迁移、替换服务和前端。新增 `degradation_reasons` 为可选公开状态；`/api/agent/chat` 和旧 `/sessions/{id}/turns` 也只返回公开答案，内部工具记录从受保护的平台接口读取。

发布后执行 `check_service_readiness.py`、`smoke.sh`、反馈验收与持久 Session 重启恢复验收。恢复 JAR 和前端可以回退应用版本，但不撤销已执行的 Schema 或业务数据变更。指标采集、告警、备份范围和恢复演练要求见 [运行保障说明](../ops/README.md)，本轮结果和剩余任务见 [服务完善记录](../../../../docs/service-completion-20261010.md)。

在部署主机运行 `python3 feedback_acceptance.py` 可进一步校验真实 Gateway 反馈及 MySQL 持久化：脚本选择未绑定且无历史反馈的画像，注册独立验收账号，断言交付落库、喜欢后召回新商品、不喜欢过滤及补页、Outbox APPLIED、重复提交幂等，以及撤销后的删除标记。结束时撤销测试偏好并登出，验收账号和审计事件保留。

## 2026-09-07 首页个性化与故障验收

2026-09-13 多路补齐：`RS_RECOMMEND_MULTI_RECALL_ENABLED=true` 启用 ItemCF weak/strong、Swing、UserCF、离线 Category 和 Popular。需先部署 `../model/README.md` 中的索引和运行时，版本必须匹配 `RS_RECOMMEND_MULTI_RECALL_VERSION`。执行 `python3 multi_recall_acceptance.py --jar <绝对路径> --output <报告.json>`，可用独立容器验证真实多路贡献、首页展示、换批和故障降级；使用端口 18133，交付/偏好保存在隔离内存中。Co-visit 诊断切片与已合并的标题类目扩展不会被当作独立正式来源启用。

2026-09-13：首页新增训练 epoch 5 双塔。默认开关关闭；先按 `../model/README.md` 准备独立 64 维索引与用户塔运行时，再设置 `RS_RECOMMEND_TWO_TOWER_ENABLED=true`。模型键为 `two_tower_sparse_aware_epoch5_queryv2`，集合为 `rs_agent_two_tower_epoch5_20260913`，`RS_RECOMMEND_TWO_TOWER_BASE_URL=http://172.21.0.1:18117`。只需重新创建 Recommend 服务。执行 `python3 two_tower_home_acceptance.py --jar /绝对路径/rs-service-recommend.jar --output acceptance.json` 可在隔离容器验证真实召回、换批与故障降级；依赖同目录的 `personalized_home_acceptance.py`、`feedback_acceptance.py`。验收端口 18133 须空闲。完整证据与回滚见 [双塔接入记录](../../../../docs/superpowers/plans/2026-09-13-two-tower-home-integration.md)。

首页已接通 User 正向历史、语义／类目召回、Catalog 探索、真实 BGE 排序及跨会话去重。部署时先执行 `rs_home_recommendation_indexes.sql` 与 `rs_agent_session_projection_upgrade.sql`；新版 Compose 的迁移任务已包括这两项。第二项仅升级 MySQL 会话投影，权威会话的 `agent-session` 版本仍为 `agent_session_v1`。

- `python3 personalized_home_acceptance.py`：验证两个画像、反馈召回、跨会话排除、有限并发并生成质量和延迟记录。
- `python3 isolated_feedback_fault_acceptance.py`：创建并清理独立数据库、Redis 与 Recommend 容器；验证模型降级及 Redis 中断后的 PENDING → APPLIED。
- 浏览器脚本 `frontend/scripts/verify-feed-pagination.cjs`：验证真实换批与好恶反馈。设置 `RS_E2E_AGENT=true` 额外验证普通聊天、SSE 和两轮持久记录。
- `python3 agent_session_recovery_acceptance.py`：选择已完成的浏览器验收会话，重启 Agent，验证回答恢复与跨画像 404。

指标通过 Recommend 的内部 `/actuator/metrics/rs.recommend.home.latency`、`rs.recommend.home.candidates`、`rs.recommend.home.category.coverage` 与 `rs.recommend.home.degraded` 查询。服务端口继续绑定本机，不通过前端公开这些管理接口。

BGE 使用 `model/rs-bge-runtime.service` 用户级 systemd 单元；启用 `loginctl enable-linger luo` 后随系统启动，并在进程异常退出时恢复。当前使用 `model_deploy/bge-runtime.env` 中的 GPU 2 与端口 18116。公网域名与 HTTPS 按用户要求延后。

完整证据、限制和回滚方式见 [本轮记录](../../../../docs/superpowers/plans/2026-09-07-personalized-home-completion.md)。

## 已训练主排序接入

Recommend 使用 `RS_RECOMMEND_TRAINED_RANKING_ENABLED=true`、`RS_RECOMMEND_TRAINED_RANKING_BASE_URL=http://172.21.0.1:18119`、`RS_RECOMMEND_TRAINED_RANKING_VERSION=cold_deepfm_20260914`。先启动并核验 model 目录中的运行时，再启用该开关。

`trained_ranking_acceptance.py --jar <待发布 JAR> --output <报告.json>` 启动隔离 Recommend，验证首页、对话、已有候选重排、价格约束、反馈归因与运行时故障回退，完成后清理隔离容器。`deploy_trained_ranking_release.py` 是本次固定版本发布脚本，校验 JAR、模型、验收证据，备份并仅重启 Recommend；重复发布需重新核验版本和使用新的备份目录。域名配置仍按用户要求延后。

## 2026-10-10 账号边界与支付通知追加修复

User 刷新令牌时必须成功消费旧认证 Session，竞争失败的请求不会签发新令牌。Agent 的公开中断接口要求可信 `X-Account-Id` 与 `X-Profile-User-Id`，与执行中的 Turn 同时匹配。Recommend 的商品偏好删除新增 `operation_complete`：`APPLIED` 只表示本次撤销投影生效；历史超过单次 100 条预算时，前端继续分批删除并查询最终状态，全部完成后才显示删除成功。画像共享及会话偏好优先级保持现有领域定义。

可选交易模块的 `/api/payments/prepay` 使用 Gateway 注入的账号身份，忽略请求体账号字段，通过 Order 内部接口检查订单归属、待支付状态、有效期及最终应付金额。客户端金额与订单金额不一致时返回 400，订单不存在或不可支付返回 404/409，核验依赖暂时不可用返回 503。Payment 与 Order 需要一起更新。

部署前执行更新后的 `sql/rs_service_trade_schema.sql`，核验 `rs_schema_version` 中 `rs-service-payment-notification=payment_notification_v1`，再启用新 Payment。现有 Compose 迁移顺序已包含此文件。新增的 `payment_order_notifications` 与支付成功记录同事务写入，并为既有已支付记录补登记；重复迁移不会重置通知状态。

通知任务默认每秒检查最多 50 个到期任务，以数据库条件更新领取任务，租约 60 秒；中断任务租约到期后可恢复，旧执行者不能覆盖新执行者的处理结果。临时失败按指数退避重试，最长间隔 300 秒；成功记为 `DONE`，重复回调不重新发送已完成通知。订单服务明确返回 404/409 时记为 `REVIEW`，需核对订单超时、关闭或金额冲突后按既有退款流程处理，不能将该状态直接改成已支付。可配置 `rs.payment.notification.worker.enabled` 和 `rs.payment.notification.worker.delay-ms`。

核查通知积压可使用：

```sql
SELECT status, COUNT(*) FROM payment_order_notifications GROUP BY status;
SELECT order_id, attempts, last_error FROM payment_order_notifications WHERE status = 'REVIEW';
```

本轮证据位于 `outputs/service-completion-20261010/followup-audit`，发布包使用新的 `followup-release` 目录。数据库恢复与 Mapper 测试使用隔离 H2 的 MySQL 模式；本机 Docker 未运行，未执行真实 MySQL 或正式部署验收。

## 2026-10-10 登录态、支付编号与创建阶段订单清理

User 退出和刷新登录态时携带已知令牌哈希清理缓存，独立 Session 索引丢失不会导致旧令牌残留有效。User 和 Gateway 认证均要求缓存令牌与规范 Session 一致；规范 Session 不存在时拒绝缓存认证。Gateway 同时检查令牌哈希、过期时间及完整身份，兼容既有日期数组和字符串格式。更新 User 与 Gateway，过程中规范 Session 缺失的登录态需要重新登录。

Payment 编号改由 `payment_id` 表的数据库自增序列分配。先停止旧 Payment 发号，再执行更新后的 `sql/rs_service_trade_schema.sql`，核验 `rs_schema_version` 中 `rs-service-payment-id=database_id_v1`，最后启动新版 Payment。迁移会用既有 `payment_orders.payment_id` 最大值初始化序列，重复执行不会删除序列记录。旧 Payment 与新 Payment 不应同时发号。已有支付记录和支付编号保持不变。

Order 的创建阶段现在允许取消，并受原有 15 分钟有效期约束。关闭状态与清理任务同事务提交；后台先取消优惠券预留，再取消库存预留。新增内部 `/internal/promotions/reservations/cancel` 和 `/internal/inventory/cancel` 接口，资源尚未锁定时也登记取消结果，阻止迟到的锁定请求。清理失败沿用持久任务重试；进程恢复后可继续，不重复释放已完成的资源。前端为创建中的订单展示取消入口。

应先更新 Inventory 与 Promotion，再更新 Order 与前端；整个过程中保留清理任务。第一版单实例 Agent 的约束不受此改动影响。可以核查创建阶段超时及未完成清理：

```sql
SELECT o.order_id, o.status, w.phase, w.attempts, w.last_error
FROM orders o JOIN checkout_workflow w ON w.order_id = o.order_id
WHERE (o.status = 'CREATING' AND w.expires_at <= UTC_TIMESTAMP())
   OR w.phase IN ('CANCEL_COUPON', 'CANCEL_STOCK');
```

回归证据位于 `outputs/service-completion-20261010/second-audit`。验证包括隔离 H2、真实 Mapper、并发锁定/取消、响应丢失、持久清理任务恢复和浏览器夹具；真实 MySQL 与正式环境尚未验收，未启动离线服务。

## 2026-10-10 异步秒杀入口与对账补齐

商品详情页增加活动、倒计时、抢购及原订单打开。Seckill 增加活动查询、终态与进度保护、持续无订单任务待核对、内部待办查询与恢复接口。部署先完成 infra 的 commerce-kafka-init；app 使用 full-commerce，RS_SECKILL_MAX_REDRIVES 默认 10。发布包纳入 .mjs 脚本，promotion 可执行 exec jar 在发布目录统一命名为 rs-service-promotion.jar。

seckill_smoke.mjs 验证实际 Kafka→订单→库存→支付/取消→额度对账；seckill_load.mjs 提供有预算的隔离并发测试与报告，seckill_health.mjs 提供异常检查。均要求准备隔离数据及环境，未在真实依赖上执行。命令、身份边界、事件重投规则与验证证据见 [交易实施说明](../../../../docs/commerce-v1.md)。

## 2026-10-11 交易恢复与有界并发

部署前重跑 `rs_service_commerce_v1_schema.sql` 新增操作审计表，再更新 Order、Payment、Seckill 和前端。旧秒杀消费者保持关闭；旧订单的支付/超时内部接口返回待迁移冲突，避免静默跳过库存处理。秒杀发布、对账独立调度，订单工作流改为有界并发；默认批大小 100、各池 4 个线程。

新增 Checkout 和 Payment 待核对查询、恢复接口，恢复请求需 `operatorId/reason` 并写入同事务审计。模拟退款默认关闭，仅适用于 mock 支付记录。`seckill_health.mjs` 同时检查三个交易服务，已支付但库存核销未完成的订单也会告警。配置、内部接口和测试范围见 [交易实施说明](../../../../docs/commerce-v1.md)。

## 2026-10-11 在线偏好恢复与代理限流修复

Recommend 分别扫描画像投影和仍在偏好有效期内的会话事件，按画像、会话、商品游标分批恢复。已应用事件也参与会话恢复，因此同商品在不同会话中的相反反馈不会互相替代。撤销分别寻找画像与原会话中的有效前序反馈，跨会话画像继承保持弱影响。

会话快照新增可选 `expiresAt`，已有 v2 缓存格式仍能读取。当前读取和重建以 User 权威会话最近活动时间加 24 小时为期限，并只写入剩余 TTL；重复重建不续期，过期会话不会因画像恢复重新获得强偏好。画像中的商品分别按各自更新时间保留 180 天，其他商品的反馈不会延长其期限。排序增加画像时间衰减，半衰期默认 30 天，可设置 `RS_RECOMMEND_PROFILE_HALF_LIFE_DAYS`，或 Spring 属性 `rs.recommend.preference.profile-half-life-days`；会话强偏好规则保持原有含义。

Gateway 与前端 Nginx 配置一起更新。Nginx 将 `X-Forwarded-For` 覆盖为实际直连客户端地址，Gateway 仅接受明确可信代理提供的最右侧数字 IP，兼容原有 Nginx 追加模式；外部输入的前缀不形成新限流桶。Compose 和 `.env.example` 默认设置 `RS_GATEWAY_TRUSTED_PROXIES=rs-frontend`。已有运行 `.env` 中若仍为空，更新为此值后再更新 Gateway。支持逗号分隔的明确 IP 或 DNS 名称，不应配置整个容器网段为可信来源。

可信代理 DNS 在有界线程池中解析，结果保留 30 秒并自动重新解析，适应前端容器地址变化；解析失败时忽略转发身份，按直连地址限流。入口契约为单层可信 Nginx；如以后添加外层代理，需要明确配置真实客户端地址净化规则后再接入，不能直接信任客户端传入的地址链。

本次不新增业务表或修改历史事件，无需重建离线产物。证据在 `outputs/service-completion-20261010/third-audit`：隔离 H2 查询、模拟 Redis TTL/CAS、代理请求及全量 Java 构建。不启动正式服务；真实 MySQL、Redis、Nginx 与 Docker DNS 的联合验收仍需在部署环境完成。

## 2026-10-11 支付回调、批量清空与曝光事务修复

Payment 使用与 Checkout 相同的 `RS_CHECKOUT_MOCK_PAYMENT_ENABLED` 开关，默认关闭。关闭时预支付和模拟回调返回 404，且不登记付款或通知。仅在联调中显式启用；Payment 回调还要求 `RS_PAYMENT_MOCK_CALLBACK_SECRET` 至少32个UTF-8字节，留空或长度不足时拒绝回调。Compose 已向 Payment 传递两个配置；本次没有写入运行环境中的密钥。

旧固定签名不再接受。模拟发送端按 `mock`、去掉首尾空白的交易号、十进制订单号、十进制金额、原始 `rawPayload` 的顺序签名；每个字段先编码为UTF-8，并在字节前加4字节大端长度，整个序列计算HMAC-SHA256，签名使用小写十六进制。`rawPayload` 保留原始空白。Java 联调端可调用 `MockPaymentCallbackSignature.sign`。这只定义模拟回调协议，真实支付渠道仍需独立接入。

Recommend 与前端一同更新。`DELETE /api/recommend/preferences` 保留偏好列表字段，并新增 `operation_complete` 与 `operations` 回执。每次最多处理100次撤销；前端等待PENDING回执并持续提交剩余批次，最终读取空列表后才报告清空成功。超过20批仍有进展的历史会继续处理；连续20批状态没有进展时显示可重试提示。撤销重试返回原事件回执，不新增撤销。部分成功或失败后页面重新读取实际列表。

曝光先校验整批投递归属、有效期与商品，再由反馈仓库原子提交，后续写入失败会回滚本批已有写入。输入缺少必填字段、包含空商品或非法曝光数值时返回400与 `INVALID_FEEDBACK_REQUEST`；每批最多100个商品，兼容原有 `item_ids` 格式。无效投递或商品返回422且不写入本批事件。无需新增数据库迁移或更新离线产物。

隔离复现、回归日志和修复前基线位于 `outputs/service-completion-20261011/fourth-audit`；未启动正式服务或执行部署，真实依赖联合验收仍需在部署环境进行。

## 2026-10-11 Agent 在线推荐分支修复

语义召回非空时始终执行会话偏好恢复、最终筛选、交付持久化与追踪，`RS_RECOMMEND_TRAINED_RANKING_ENABLED` 只控制专用模型排序。关闭时保留召回次序作为基础分数；已有候选重排接口仍返回 503。会话活动或偏好读取、交付写入失败会向上返回错误，仅召回失败或为空时允许首页回退。

语义排序与已有候选重排使用和首页相同的 `SessionPreferenceReader`，按真实 Account、Profile User 与 Session 恢复强偏好。首页响应的 `display` 新增可选 `price` 字段，Agent 转换保留 Catalog 价格；各成功与回退路径使用同一套预算约束，有预算时不接受未知价格，非法约束返回 400。Agent 候选入口使用 Task 对应的真实 Session 写入响应、交付和追踪，Profile User 仍为独立字段。

此轮只需更新 Recommend 代码，无新增数据库迁移或配置项。修复前基线、隔离复验和模块回归记录位于 `outputs/service-completion-20261011/eighth-audit`；本轮未部署，未处理离线部分。
