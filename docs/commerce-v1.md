# 库存、优惠券与秒杀第一版

本次按已确认规则实现：限量发券、每个 Account 每场活动一张、单券满减、不叠加。报价和券门槛统一使用 USD 美分，时间使用 UTC。页面目录价格仍是参考价，checkout_offer 保存可交易 SKU 的服务端报价。

## 已实现的链路

- 商品详情页支持领券、选 SKU/数量、选券、下单、订单状态查询、取消与返还。首页和 Agent 商品跳转会携带当前 Session、推荐交付请求标识，订单保存原始归因字段。
- promotion 的发行额度、个人券与领取请求绑定在同一个 MySQL 事务提交；Redis 只对活动入口限流，故障时暂停领取。不同请求键领取同一活动仍返回同一张券；同键换活动拒绝。
- 券预留与 orderId 绑定。AVAILABLE → LOCKED → USED；取消时返回 AVAILABLE，已过原有效期则 EXPIRED。已释放预留的迟到重试不能重新锁券。
- 订单先提交 CREATING 状态、报价快照与 checkout_workflow 待办，再由后台锁券、锁库存。支付/取消状态与后续待办一起提交，跨服务响应丢失时使用原业务键重试。
- 库存以已有 LOCK 流水作为订单/SKU 预留的互斥行。确认、释放先锁住该行并检查相反终态，库存条件 UPDATE 与流水同事务；不会用另一订单的聚合 locked_stock 满足错误的二次释放/确认。
- 秒杀第一版每 Account 每活动限购一件。活动报价在创建时冻结；MySQL 同事务扣活动准入额度、保存受理记录和待发送事件；Kafka 后台投递，订单消费幂等落地。请求/结果查询按 Account 隔离。
- 新活动先从普通可售库存划拨专属库存，确认完成后才开放受理；秒杀订单从活动池预留，取消后归还活动池，活动结束且受理任务结清后归还余量。历史活动保留原共享库存路径，不自动划拨。
- 秒杀取消/创建失败只在订单资源处理完成后返还活动额度，且最多一次；个人活动限购记录保留，取消后不能再次参与同一活动。
- 默认关闭模拟支付。启用后按钮明确显示“模拟支付（不扣款）”。本次没有新增真实支付渠道，也没有让 LLM 自动下单、领券或支付。
- 当前保留归因信息，尚未把真实支付/退款事件接入推荐偏好更新；不能把创建订单或领券视为真实购买反馈。

## 服务与接口

| 服务 | 入口 |
| --- | --- |
| promotion :8095 | GET /api/promotions/campaigns?itemId=…；GET /api/promotions/coupons；POST /api/promotions/campaigns/{id}/claim |
| order :8091 | GET /api/checkout/offers?itemId=…；POST/GET /api/checkout/orders；GET /api/checkout/orders/{id}；POST …/{id}/cancel |
| order（兼容入口） | /api/orders 的创建、查询、取消已接入新流程；旧客户端提交的 unitPrice 和 itemTitle 不作为成交依据 |
| seckill :8094 | GET /api/seckill/activities?itemId=…；GET /api/seckill/activities/{id}；POST …/{id}/submit；GET /api/seckill/requests/{requestId} |

公开接口的 Account 来自网关注入的 X-Account-Id。服务端内部接口位于 /internal，网关不转发；部署时服务端口应只暴露到回环/可信内部网络。旧订单服务及旧 Kafka 消费者保留用于历史数据兼容，不代表旧订单已经迁移到 checkout_workflow。

订单创建返回 CREATING 表示已持久受理；WAITING_PAYMENT 表示库存、优惠已确认。PAID/CANCELED 是订单事实，phase=DONE 表示对应资源处理也已完成。客户端遇到网络超时须保留 requestId 和原参数重试，不要生成新键。

## 运行与部署

先在仓库根目录构建相关模块（JDK 21）：

```powershell
$env:MAVEN_OPTS='-Xmx768m'
mvn -f java_agent/pom.xml -pl rs-service-promotion,rs-service-order,rs-service-inventory,rs-service-seckill,rs-api-gateway -am package
npm --prefix java_agent/frontend run build
```

promotion 同时保留普通 jar 供跨模块集成测试，并生成可执行 rs-service-promotion-exec.jar。发布打包脚本选择 exec jar 并统一命名为 services/rs-service-promotion.jar，Compose 使用此发布文件名；手动复制也要将可执行 exec jar 重命名为该文件名。其他服务沿用原可执行 jar 文件名，前端发布 dist。

MySQL 先执行原 rs_service_trade_schema.sql，再执行新增 rs_service_commerce_v1_schema.sql。远程 app Compose 已加入新迁移及 promotion 服务。新 SQL 只新增表，不清空已有库存或订单；必须先迁移再启动新版本。不要只执行建表脚本就把历史 Redis 预扣活动当作已迁移：旧活动应先停止受理并对账，确认旧 seckill-order-create 消息处理情况后再建立新的活动。

沿用远程 infra 和 app 的 full-commerce profile：启动 Kafka、Inventory、Order、Promotion、Seckill，网关使用 RS_DEPLOYMENT_PROFILE=full-commerce。保留原 User/Catalog/推荐等依赖配置。promotion 与 checkout 的网关路由也存在于基础配置，但服务未启动时页面会显示交易服务不可用。

仅联调环境可以设置 RS_CHECKOUT_MOCK_PAYMENT_ENABLED=true。默认 false；不能用此开关代替真实支付回调验证。既有支付服务回调能路由到新订单的状态推进，但真实渠道接入、支付服务自己的回调可靠性和退款仍需要后续专门验证。

### 模拟支付与故障演示

启用开关后，商品详情页可选择四种模拟支付场景。订单、库存预留和优惠券仍走现有服务与持久化状态机；仅模拟外部支付结果，不发生真实扣款。该模式仍需要交易服务及其数据库，不能替代无后端的前端演示模式。

POST /api/checkout/orders/{orderId}/mock-pay 接收可选 JSON：`{"scenario":"SUCCESS"}`。空请求体或 `{}` 兼容原来的成功模拟。

| scenario | 模拟行为 | 预期恢复方式 |
| --- | --- | --- |
| SUCCESS | 使用服务端券后金额确认支付，后台确认库存和核销券 | 查询 PAID，等待 phase=DONE |
| DECLINED | 返回 402，订单继续待支付，库存和券保持预留 | 切换成功场景重试，或取消返还 |
| TIMEOUT_BEFORE_PAYMENT | 立即返回模拟 504，未确认支付 | 查询原订单，再切换成功场景重试 |
| RESPONSE_LOST | 先持久化支付和后续待办，再返回模拟 504 | 查询原订单；同订单重试返回 PAID，不重复核销 |

上述超时采用立即返回错误模拟，不占用线程等待。页面遇到支付错误会主动回查订单，已有轮询继续刷新。已支付订单在任何场景下重试均返回已支付事实；已取消、创建中等状态拒绝支付。所有场景均检查开关及订单所属账号。模拟入口复用订单支付金额校验，但不经过真实支付渠道或支付服务回调网络，因此不能据此声称支付回调链路已完成验证。

本轮本地补充验证覆盖拒付/超时后取消返还、响应丢失后重建服务并幂等核销、所有场景的开关和账号隔离。远程 smoke 的 RS_SMOKE_MOCK_PAY=true 分支也已加入这些支付故障场景；真实环境执行仍需准备服务与测试数据。退款、物流和购买反馈尚未添加模拟实现。

Kafka 使用 checkout-seckill-accepted 与 checkout-seckill-accepted.DLT 两个 topic，并保持相同分区数。infra 的 full-commerce profile 已加入 commerce-kafka-init，一次性创建并核对两个 topic；默认 3 分区、1 副本，可通过 RS_COMMERCE_KAFKA_PARTITIONS/REPLICAS 设置。既有 topic 参数不符时初始化失败，需人工核对，脚本不会改写或删除既有 topic。先确认初始化成功，再启动 app 的交易服务。现有单 broker Compose 用于开发联调，尚未验证高可用。

消费者组 rs-checkout-seckill-v1 使用 earliest，禁用自动 offset 提交。投递失败保留待发送记录；消费者重试后可进入 DLT。消息已发布、持续 60 秒找不到订单时，以原 eventId 重新投递；达到重试计数预算后进入 REVIEW_REQUIRED，暂停自动重投并保留额度，需检查 DLT 和下游服务再通过内部接口恢复。迟到的真实订单仍可被对账发现。当前 attempts 同时累计发布失败与无订单重投，预算只在已发布但无订单的检查中使用；Kafka 发布故障仍继续重试。

可配置项：

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| rs.promotion.claims-per-second | 200 | 每活动 Redis 固定窗口准入上限，保护 MySQL；不是已测得的业务 TPS |
| rs.seckill.admissions-per-second | 200 | 每活动秒杀准入上限 |
| rs.checkout.worker.delay-ms | 500 | 订单待办扫描间隔；每批最多 25 笔 |
| rs.seckill.worker.publish-delay-ms / reconcile-delay-ms | 100 / 1000 | 发布与对账分别调度，默认各批最多 100 笔 |
| rs.seckill.max-redrives | 10 | 已发布但持续无订单时的重试计数预算；部署变量 RS_SECKILL_MAX_REDRIVES |
| rs.checkout.kafka.concurrency | 3 | 单订单实例 Kafka 消费并发数 |
| rs.checkout.mock-payment-enabled | false | 是否允许显式模拟支付 |

订单未支付 15 分钟关闭。锁券时有效的券可以在订单支付期限内核销，取消时按原券有效期返还。已经超时才到达的支付通知会被拒绝，需由支付侧查证/退款；本版本未实现退款系统。

支付服务向订单回调时会附带持久化支付金额；Checkout 在订单状态事务内核对券后应付金额，缺失或不一致则拒绝。模拟 provider 的回调同样受 RS_CHECKOUT_MOCK_PAYMENT_ENABLED 控制。满减门槛必须大于优惠额，第一版不支持零元订单。

## 准备隔离的测试数据

使用独立测试商品/账号；下列示例只用于空的测试 SKU，不对已有库存做重置：

```sql
INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price,active)
VALUES ('commerce-smoke-sku','替换为真实目录item_id','交易测试商品',3000,TRUE);
INSERT INTO sku_stock(sku_id,item_id,available_stock,locked_stock,sold_stock)
VALUES ('commerce-smoke-sku','替换为真实目录item_id',10,0,0);

INSERT INTO promotion_campaign(campaign_id,title,item_id,total_quantity,remaining_quantity,
minimum_amount,discount_amount,starts_at,ends_at,expires_at)
VALUES ('commerce-smoke-campaign','满20减5','替换为真实目录item_id',100,100,2000,500,
UTC_TIMESTAMP(6),DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 1 DAY),DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 2 DAY));
```

活动管理也可从可信内部网络调用 POST /internal/promotions/campaigns。秒杀活动用经过写入凭证认证的 POST /internal/seckill/activities 创建，参数为 activityId/itemId/skuId/totalQuantity/startsAt/endsAt；首次创建要求 SKU 已有有效服务端报价。同 ID 同参数重试沿用报价和划拨记录，不重置额度。创建响应仅表示记录持久化，须查询活动至 ACTIVE/NOT_STARTED；PREPARING 表示划拨未确认，UNAVAILABLE 表示需要核对。库存不足不会开放活动。

## 自动验证与已知验证边界

本次测试包含实际 H2 SQL 事务、真实 MyBatis 库存 Mapper、并发领取、同账号不同键、同券双订单、支付/取消竞态、库存终态互斥、远程成功但响应丢失、服务实例重建后继续处理、Kafka 投递结果未知及幂等返还；另有 Spring Boot 完整应用装配和前端接口测试。H2 MySQL 兼容模式不能替代 MySQL InnoDB、真实 Redis 和 Kafka 的联合故障验证。

2026-09-13 本地验证：Gateway、Inventory、Promotion、Order、Seckill、Payment 六个相关模块合计 101 项测试通过，Maven package 成功；前端 27 项测试通过并完成生产构建。Compose 配置校验、smoke 脚本语法检查通过。

远程端到端 smoke 使用 Node 20+，不会打印令牌，也不会重置库存。先准备测试账号访问令牌、测试活动与可购买 SKU：

```powershell
$env:RS_SMOKE_GATEWAY_URL='http://127.0.0.1:18088'
# RS_SMOKE_TOKEN 使用测试账户令牌，从安全环境注入，不写入仓库。
$env:RS_SMOKE_ITEM_ID='替换为真实目录item_id'
$env:RS_SMOKE_SKU_ID='commerce-smoke-sku'
$env:RS_SMOKE_CAMPAIGN_ID='commerce-smoke-campaign'
node java_agent/deploy/remote/app/commerce_smoke.mjs
```

默认 smoke 覆盖领券、重复提交、锁券、取消和返还。服务端启用模拟支付后，可加 RS_SMOKE_MOCK_PAY=true 验证最终核销。脚本会消耗一次活动领取资格，模拟支付还会消耗一件测试库存；重跑需选择符合状态的测试账号/活动。

本机 Docker 未运行，本次没有启动真实 MySQL/Redis/Kafka 联合环境，未运行上述远程 smoke，也未取得 QPS/TPS 基准。不要把测试通过或准入上限配置写成已验证的高并发性能。本机完整环境需先估算资源：按 12GB 可承受、14GB 上限；高并发与故障压测优先在远程隔离环境执行。

## 2026-10-10 异步秒杀补充

商品详情页新增限量秒杀区：显示冻结价格、剩余名额与倒计时，未开始/售罄/结束时禁用新抢购。活动查询返回 UTC 时间和 serverTime，页面使用服务端时间差计算倒计时。列表包含未结束活动及最近 24 小时结束的活动，最多 100 条，并附带当前 Account 的参与记录，其他账号不能看到该记录。

抢购请求每活动保留同一个 requestId。网络结果未知时写入 sessionStorage，页面每 5 秒查询活动和结果；刷新后使用服务端参与记录恢复。只有用户点击才提交或重试，结果未知不会自动创建新请求。返回 DUPLICATE 时采用服务端原 requestId；NOT_STARTED/ENDED/STOCK_NOT_ENOUGH 表示本次未受理，不占活动额度。后台生成订单后，“查看订单”打开原订单，可使用已有取消/模拟支付按钮。

当前秒杀每活动限购一件，活动冻结价格不叠加优惠券，消息没有携带 Session 或推荐归因字段；普通下单仍保留这些能力。受理后的 PROCESSING/CREATING/WAITING_PAYMENT 与最终 PAID/FAILED/CANCELED/TIMEOUT_CLOSED 分开展示。已受理后活动结束仍继续处理原任务，订单支付期限从创建订单开始计算。

对账写入会锁住受理记录，检查当前终态与进度。迟到的 WAITING_PAYMENT/CREATING 结果不能覆盖终态，CREATING 不能覆盖 WAITING_PAYMENT。取消/失败仍在订单清理完成后最多返还一次额度。2026-10-10 的实现每批最多 25 条、顺序处理；2026-10-11 改为下文的有界并发与独立调度，实际吞吐仍需真实环境报告确定。

### 秒杀环境与验收

infra 使用 full-commerce profile，先完成 Kafka topic 初始化：

```bash
cd ~/RS_agent_java/infra
docker compose --env-file .env --profile full-commerce up -d kafka
docker compose --env-file .env --profile full-commerce run --rm commerce-kafka-init
```

确认两个 topic 参数相同，再启动 app 的 full-commerce 服务，网关设置 RS_DEPLOYMENT_PROFILE=full-commerce。发布包包含 .mjs 验证脚本，并统一使用 services/rs-service-promotion.jar；该文件来自可执行 exec jar。部署当前版本须重跑更新后的 commerce SQL，新增划拨、库存范围和任务租约扩展表。

使用可信内部接口创建隔离活动：POST /internal/seckill/activities，参数为 activityId/itemId/skuId/totalQuantity/startsAt/endsAt；时间按 UTC 输入。测试 SKU 应已配置 checkout_offer 和 sku_stock；不要覆盖真实库存。活动建立时从订单服务取冻结报价，不从客户端取价。

```powershell
$env:RS_SMOKE_GATEWAY_URL='http://127.0.0.1:18088'
# RS_SMOKE_TOKEN 从测试账户安全注入，不写入仓库。
$env:RS_SMOKE_SECKILL_ACTIVITY_ID='替换为独立测试活动'
$env:RS_SMOKE_SECKILL_ACTION='cancel'
node java_agent/deploy/remote/app/seckill_smoke.mjs
```

脚本验证首次受理、同键重试、不同键限购、Kafka 生成订单、冻结价格、库存预留、取消完成后的活动额度和可售库存恢复。测试要求账号未参与过、活动/SKU 在执行期间无其他交易。设置 ACTION=mock-pay 验证支付响应丢失恢复及 PAID，需服务端开启模拟支付；这会消耗一件测试库存。取消之后同账号不能重新参加同一活动，因此验证支付要换活动或账号。原 smoke.sh 在 full-commerce 且提供活动变量时会追加秒杀 smoke。

### 异常检查与恢复

内部接口只可从回环或可信网络访问，网关不转发：

| 接口 | 用途 |
| --- | --- |
| GET /internal/seckill/tasks/summary | 非终态、未发布、待核对任务数量；非终态也包含正常待支付 |
| GET /internal/seckill/tasks?minimumAgeSeconds=1200 | 返回超过指定年龄的非终态任务，最多 100 条 |
| POST /internal/seckill/tasks/{eventId}/retry | 仅恢复 REVIEW_REQUIRED 且未关联订单的任务，沿用原事件，不再次扣额度 |

REVIEW_REQUIRED 不是退款或失败结论，不直接回补额度。修复永久错误、核查死信后再调用恢复接口；迟到的有效订单也能自动结束待核对。查询失败保留受理记录和后续重试。2026-10-11 起恢复接口必须提交 operatorId/reason，并与任务恢复同事务写入操作记录；身份边界见下文。

```powershell
$env:RS_SECKILL_INTERNAL_URL='http://127.0.0.1:18094'
$env:RS_ORDER_INTERNAL_URL='http://127.0.0.1:18091'
$env:RS_PAYMENT_INTERNAL_URL='http://127.0.0.1:18093'
$env:RS_SECKILL_STALLED_SECONDS='1200'
node java_agent/deploy/remote/app/seckill_health.mjs
```

巡检输出数量、任务 ID、状态和重试原因；待核对或超龄任务存在时退出码 2。可接现有巡检任务，但本轮没有创建自动通知。Kafka lag/DLT 仍需要现有 Kafka 运维监控；仅上述 SQL 待办指标不能代表消费者健康。

### 有预算的并发验证

seckill_load.mjs 使用隔离活动和不同的新测试账号，每账号同一个请求键提交两次，检查受理不超过额度、幂等订单生成、取消后额度及可售库存恢复。账号文件是 JSON 数组，元素为 accountId/token，由运行环境安全提供；令牌不会进入报告。默认 50 个账号、8 并发，上限 1000 个账号、64 并发。响应未知会回查原请求，无法确认或清理的请求在报告中保留。

```powershell
$env:RS_SECKILL_LOAD_ACCOUNTS_FILE='安全位置的测试账号文件.json'
$env:RS_SECKILL_LOAD_ACCOUNTS='50'
$env:RS_SECKILL_LOAD_CONCURRENCY='8'
$env:RS_SECKILL_LOAD_REPORT='隔离环境报告.json'
node java_agent/deploy/remote/app/seckill_load.mjs
```

报告区分请求 QPS、P95/P99、唯一受理数、生成订单数及包含轮询时间的平均订单生成速率。单批观测值不能作为持续负载容量结论；真实容量测试还要记录实例数、活动配额、DB 锁等待、Redis 延迟、Kafka lag、服务 CPU/内存，并分别执行依赖中断及恢复测试。

本轮本地验证：Gateway/Inventory/Promotion/Order/Seckill 合计 113 项测试通过，Maven package 成功；前端 46 项测试及生产构建通过。浏览器 API 夹具验证了原请求重试、刷新恢复、时间/售罄禁用、订单打开、取消和支付响应丢失回查；截图保存在 outputs/seckill-completion-20261010。4 项 Node 脚本夹具验证覆盖取消 smoke、支付 smoke、并发报告和巡检退出码，均通过。Compose 配置校验通过。H2、模拟 Redis/Kafka、浏览器与脚本夹具只验证各自行为，本机 Docker 未运行，尚未执行真实联合 smoke 或取得真实性能数据。

## 对账与运维检查

```sql
SELECT phase,COUNT(*) AS count,MAX(attempts) AS max_attempts,MIN(next_attempt_at) AS oldest_due
FROM checkout_workflow GROUP BY phase;
SELECT status,dispatched,COUNT(*) AS count,MAX(attempts) AS max_attempts
FROM seckill_request_v1 GROUP BY status,dispatched;
SELECT campaign_id,total_quantity,remaining_quantity FROM promotion_campaign;
SELECT s.sku_id,s.available_stock,s.locked_stock,s.sold_stock
FROM sku_stock s WHERE s.available_stock<0 OR s.locked_stock<0 OR s.sold_stock<0;
```

重点监测长期 CREATING、非终态待办年龄/attempts、Kafka lag、DLT、已受理但无订单、已取消但资源未完成。技术失败保留待办；暂时故障按预算重试，永久错误或耗尽预算后暂停，核对后从原进度恢复。当前提供模拟退款，尚未提供真实退款、人工修改库存、分片配额或复杂促销后台。

## 2026-10-11 故障恢复与处理能力优化

### 旧链路与账号缓存

旧 `seckill-order-create` 消费者默认不再注册，远程 Compose 明确设置 `RS_CHECKOUT_LEGACY_SECKILL_CONSUMER_ENABLED=false`。正式秒杀仅使用 `checkout-seckill-accepted` 和 Checkout 持久工作流。不要为排空历史消息直接开启旧消费者：旧实现缺少可靠库存补偿，历史消息和旧订单必须先做专项核对。尚未接入 `checkout_workflow` 的旧订单，内部支付/超时接口返回 409；支付通知会进入 REVIEW，保留支付事实，不再走旧的“先改状态、再调用库存”路径。没有自动迁移或改写历史订单。

前端待确认请求使用 `checkout-pending:{Account}:{item}` / `seckill-pending:{Account}:{item}`，各标识分别编码，避免分隔符碰撞。Account 来自登录、刷新或 `/auth/me` 响应，与 Profile User 分开。刷新同账号保留原幂等键；切换账号和退出清理交易待确认缓存，并通知交易组件重置内存中的请求，旧版无账号范围缓存直接弃用。晚到响应不能重新写入其他账号的缓存。未知请求仍只在用户点击时用原键重试。

### 独立调度与有界并发

秒杀发布和对账分别调度，拥有独立执行池；慢对账不会占住发布调度线程。订单工作流也按批并发执行。单实例同一类批次不重叠；跨实例的重复处理继续由数据库状态保护和稳定资源请求键吸收。每个池的线程数、队列及每次读取规模均有限，单任务失败不会中断整批任务；服务关闭时停止执行池。

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| RS_SECKILL_WORKER_BATCH_SIZE | 100 | 发布、对账批大小，范围 1～500 |
| RS_SECKILL_WORKER_PUBLISH_CONCURRENCY | 4 | 发布线程数，范围 1～16 |
| RS_SECKILL_WORKER_RECONCILE_CONCURRENCY | 4 | 对账线程数，范围 1～16 |
| RS_SECKILL_WORKER_PUBLISH_DELAY_MS | 100 | 发布批次完成后的等待毫秒数 |
| RS_SECKILL_WORKER_RECONCILE_DELAY_MS | 1000 | 对账批次完成后的等待毫秒数 |
| RS_CHECKOUT_WORKER_BATCH_SIZE | 100 | 订单工作流批大小，范围 1～500 |
| RS_CHECKOUT_WORKER_CONCURRENCY | 4 | 订单处理线程数，范围 1～16 |
| RS_CHECKOUT_MAX_ATTEMPTS | 20 | 工作流阶段的失败次数上限，范围 1～1000 |
| RS_PAYMENT_NOTIFICATION_MAX_ATTEMPTS | 20 | 支付通知尝试次数上限，范围 1～1000 |
| RS_PAYMENT_MOCK_REFUND_ENABLED | false | 模拟退款入口开关 |

原 `rs.seckill.worker.delay-ms` 已由发布/对账两个属性替代。并发测试验证线程上限和超过旧 25 条批次限制的处理，不代表实测达到 200 QPS；提高并发需同时核算数据库连接池与远程服务容量，真实 P95/P99 和积压变化仍用隔离压测报告确认。

压测还需记录 Gateway 的入口限流配置：同一测试出口可能先触发 `RS_GATEWAY_MAX_REQUESTS_PER_MINUTE`。需要提高该配置时仅在隔离环境调整，报告区分入口 429 与秒杀业务拒绝，避免把入口限流当成后台吞吐瓶颈。

### 订单待核对与恢复

核销、释放、取消等阶段遇到永久 HTTP 错误，或暂时故障耗尽失败预算，进入 `REVIEW_{原阶段}`。暂时故障使用 5 秒起步、最长 60 秒的退避；CREATING 阶段明确的缺货/券不可用仍走既有失败补偿。暂停只改变工作流阶段，不伪造退款、释放完成或支付成功。即使订单已 PAID，未完成的核销仍出现在订单巡检里。

暂停的 CREATING 订单仍受支付期限约束，超时后切换到持久取消清理，防止停止重试后一直占券或库存。取消/失败只有在清理完成后才允许秒杀额度回补。操作员排除根因后恢复原阶段，远程库存和券请求沿用原幂等键；审计写入失败会回滚恢复操作。

| 接口 | 用途 |
| --- | --- |
| GET /internal/checkout/tasks/summary | 未完成资源任务与待核对数量；正常 READY 待支付不计入 |
| GET /internal/checkout/tasks?minimumAgeSeconds=1200 | 待核对及超过订单创建年龄阈值的未完成任务，最多 100 条 |
| POST /internal/checkout/tasks/{orderId}/retry | 仅恢复 REVIEW_ 阶段，保留订单与原处理键 |
| GET /internal/payment/notifications/summary | 支付通知未完成与待核对数量 |
| GET /internal/payment/notifications?minimumAgeSeconds=1200 | REVIEW 及到期时间超过阈值的通知，最多 100 条；沿用通知表的数据库时钟 |
| POST /internal/payment/notifications/{orderId}/retry | 将 REVIEW 恢复为 PENDING，沿用原支付流水 |
| POST /internal/payment/notifications/{orderId}/mock-refund | 仅在显式开启后模拟处理 mock 提供方的已支付 REVIEW 记录 |

订单恢复、支付通知恢复、秒杀事件重投及模拟退款均要求 JSON 请求体：

```json
{"reason":"已核对原订单及资源预留，故障已排除"}
```

这些接口不经公网 Gateway，只能从回环或可信内部网络使用，并要求 Bearer 运维凭证。只读凭证不能恢复任务或模拟退款；操作人的身份来自写入凭证的服务端配置，忽略客户端 operatorId。操作和原因持久保存于 `commerce_operation_audit`，与状态修改同事务。当前为只读/操作员两种配置凭证，尚未接入企业 SSO 或多人账号管理。

模拟退款返回 `mock=true,moneyMoved=false,status=MOCK_REFUNDED`。重复调用不重复记账或增加审计；通知停止重投，原 payment_orders 的 PAID 事实保留。不会调用真实支付渠道，不修改订单或库存，不适用于真实提供方；该状态仅用于演示退款核对分支。真实退款需要渠道接口、退款幂等键及退款结果对账后另行接入。

### 部署与验证

先重新执行更新后的 `rs_service_commerce_v1_schema.sql`，新增 `commerce_operation_audit` 表及 `rs-service-commerce-operations=commerce_operations_v1` 版本记录，再更新 Order、Payment、Seckill 和前端。脚本可重复执行，不清空历史数据。旧消费者保持关闭；不自动清理历史 Kafka 消息。

`seckill_health.mjs` 现在同时查询 Seckill、Checkout、Payment 三个内部服务。任一服务有待核对或超龄任务时退出码 2；接口不可连接或返回错误时非零退出，不报告健康。设置 `RS_SECKILL_INTERNAL_URL` / `RS_ORDER_INTERNAL_URL` / `RS_PAYMENT_INTERNAL_URL`，各默认指向本机 18094 / 18091 / 18093。阈值仍为 `RS_SECKILL_STALLED_SECONDS`，默认 1200 秒。未创建自动通知或监控任务。

上一轮验证覆盖：H2 持久订单/支付队列、暂停恢复与审计回滚、创建超时清理、旧消费者默认关闭、慢对账与发布隔离、批处理并发上限、账号切换与同账号刷新，以及浏览器的秒杀/取消/支付响应丢失恢复。证据保存于 `outputs/commerce-optimization-20261011`；当前真实联合验证见下节。

## 2026-10-11 活动库存、多实例与运行观察

新增表为 `inventory_activity_pool`、`inventory_activity_reservation`、`seckill_activity_allocation`、`checkout_stock_scope`、`commerce_worker_lease`；版本记录为 `rs-service-commerce-allocation=commerce_allocation_v1`。先执行更新后的 `rs_service_commerce_v1_schema.sql`，再一起更新 Inventory、Order、Seckill、Payment、前端。只新增扩展表，不清空旧订单/活动，不自动把已有活动的名额再扣一次库存。

划拨将 `sku_stock.available_stock` 转为 `locked_stock`，活动池满足 `total = available + reserved + sold + returned`。活动订单预留/取消仅在池内转移；支付确认将聚合 locked 转为 sold。关闭池要求没有订单预留，余量才从 locked 返还普通 available。活动结束后先持久化 CLOSING 阻止新受理，再远程归还；未知响应按同一活动重试。存在未结清或待核对受理任务时保持划拨，不能为了释放库存伪造终态。新增事件携带 stockPoolId，订单持久保存库存范围，后续每个库存动作沿用该范围。

库存划拨响应未知时保持 PENDING，由独立调度重试；明确拒绝转为 REVIEW。内部 `GET /internal/seckill/allocations` 查看未完成划拨，`POST /internal/seckill/allocations/{id}/retry` 在核对补货等根因后恢复，并同事务记录审计。活动创建时刻统一截断为微秒，和数据库精度一致。

订单处理、秒杀发布、对账及活动库存维护增加数据库租约。领取标识随机生成，90 秒到期，任务结束按标识释放；提交进度前在同一事务锁定并检查标识及到期时间。远程调用在事务外，迟到实例不能覆盖接管后的本地状态；远程操作仍依赖业务幂等和取消墓碑，租约不等于消息只投递一次。

前端恢复保存的未完成请求时，补查列表未返回的活动详情；结束超过一天的活动仍能显示待核对状态。活动详情已经带回原请求结果时不再次单独查询。正常活动/未完成请求每 5 秒查询，未开始活动每 15 秒，无活动及已结束活动每 60 秒；网络故障退避到 60 秒，页面重新可见立即刷新。库存 PREPARING/UNAVAILABLE 状态禁用新抢购。

运维凭证通过部署环境安全提供：`RS_COMMERCE_OPS_READ_TOKEN`、`RS_COMMERCE_OPS_WRITE_TOKEN` 均至少 32 字符且必须不同，`RS_COMMERCE_OPS_OPERATOR_ID` 绑定写入审计身份。未配置凭证时默认拒绝运维接口访问；订单查询、支付报价等服务间业务接口仍由现有内部网络边界保护。巡检脚本读取只读凭证，不输出凭证。工作台通过 `node java_agent/deploy/remote/app/commerce_ops_console.mjs` 启动，仅绑定 `127.0.0.1:18096`；凭证只保留在页面内存，支持查看四类任务和带原因的原任务恢复。

Prometheus 增加交易待办数量、待核对数量和最老年龄，标签只含组件，不含账号或订单。Kafka 探测独立调度，每 30 秒读取消费组 lag 和 DLT 记录高水位；失败显示探测失败及 NaN，不能当作零积压。DLT 高水位包含保留的已处理记录，需要结合人工核对，不代表全部仍待处理。规则覆盖不可达、20 分钟滞留、待核对、Kafka 探测失败、持续 lag 和死信；full-commerce 才启用交易采集目标，未部署交易服务时保持空目标，避免误报。未部署监控或配置外部消息通知。

真实联合验收入口：

```powershell
python java_agent/deploy/local/commerce/run.py --faults --output outputs/commerce-allocation-integration
```

运行器复制固定版本 JAR 并记录 SHA-256，创建独立 Compose project、网络和测试数据库，容器上限约 4.3GB，退出清理本次环境。覆盖两套订单/秒杀实例、80 次提交/20 个唯一订单、普通库存耗尽后的活动库存预留、模拟支付/取消/活动余量归还；故障分支停止消费者、重启服务、停止与恢复 Kafka。报告包含 P95/P99、单批请求 QPS 和库存断言，直接访问服务并注入隔离测试 Account，不覆盖 Gateway 登录。外部支付仍为 Mock，单 broker 停机恢复不代表高可用，单批吞吐不代表持续容量。

当前版本验证：相关后端 169 项、前端 100 项、Node 7 项通过，Maven package、前端生产构建、两组 Edge 浏览器夹具和 Prometheus 配置/9 条规则校验通过。真实 MySQL/Redis/Kafka 双实例联合验收及消费者停机、服务重启、Kafka 停机恢复通过，本次隔离容器已清理，未执行部署。最终实测单批 80 次请求约 175.46 请求/秒，P95 138.30ms、P99 284.34ms；包含幂等回放和售罄拒绝，共生成 20 个唯一秒杀订单，不能把请求 QPS 当作订单 TPS。报告位于 `outputs/commerce-allocation-final-integration-20261011`，汇总与截图位于 `outputs/commerce-allocation-optimization-20261011`。尚未完成持续负载容量测试、数据库锁等待归因及真实支付渠道验收。
