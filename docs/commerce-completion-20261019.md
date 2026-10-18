# 交易链路补全（2026-10-19）

本轮补全整单退款、库存管理与对账、历史分页、管理页面、购买事件，以及持续联调和恢复演练入口。外部资金渠道使用 Mock，返回 `mock=true,moneyMoved=false`，不代表真实清算。第一版为每账号每活动一券、单券满减、不叠加；只支持未发货订单全额退款，不含部分退款、发货后退货或运费。

## 退款与补偿

用户在 `/commerce` 的“订单与券包”查看历史并申请整单退款。`POST /api/checkout/orders/{id}/refunds` 接收 `requestId,reason,scenario`，不接受客户端金额或账号。订单必须已支付且库存/券确认完成，随后进入 `REFUNDING`；同一订单仅有一个退款号，重复请求不能覆盖原因或重复退款。

持久阶段为 `PAYMENT → STOCK → COUPON → DONE`。支付模块核对可信原订单金额、原退款号并持久记账，确认成功后才退库返券。超时/响应丢失保留原退款号回查；明确拒绝或耗尽重试进入 `REVIEW_REQUIRED`。运维恢复原任务并记录身份、原因。重启通过数据库待办和租约恢复，远程调用在事务外。

普通订单退库匹配原 `CONFIRM` 数量，以唯一 `REFUND` 流水将 sold 返还 available。活动订单将预留转为 `REFUNDED`，活动 sold 转 returned，库存返普通池；不恢复活动额度或账号限购资格。券按原有效期恢复 `AVAILABLE/EXPIRED`；旧退款重放不能解锁再次使用的券。

取消后迟到的模拟支付仍保留支付事实并进入核对。运维模拟退款现在调用持久退款模块，确认后才将原通知标记 `MOCK_REFUNDED`；取消流程已释放资源，此分支不再退库存。退款回调使用 `mock-refund:SUCCEEDED/FAILED` 签名域，绑定退款号、订单、金额和渠道流水；成功不能被迟到失败覆盖。

`GET /api/checkout/orders/{id}/refund` 查询进度。内部 `/internal/checkout/refunds` 和 `/{refundId}/retry` 查看/恢复任务。Mock 场景为 `SUCCESS / DECLINED / TIMEOUT_BEFORE_PAYMENT / RESPONSE_LOST`；显式恢复拒绝时仍沿用原退款号。

## 库存与管理页面

`http://127.0.0.1:18096/manage` 提供入库、盘点、报价、优惠券和秒杀活动发布，以及差异、退款、事件待办查询。原异常工作台在 `/`。启动方式为 `node java_agent/deploy/remote/app/commerce_ops_console.mjs`。操作身份来自服务端运维凭证，写入忽略客户端 `operatorId`，凭证不存入浏览器存储。

`POST /internal/inventory/management/adjustments` 接收稳定请求键、SKU、商品、`RECEIPT/STOCKTAKE`、数量、原因。盘点带刚查询的 `expectedVersion`，实存包含已预留数量，不能低于 locked。参数冲突和并发变化拒绝，响应未知时页面冻结原请求供重试。

`inventory_stock_baseline + SUM(inventory_adjustment.delta_quantity)` 核对聚合总量；普通订单流水和活动池分别核对 locked/sold。后台分页巡检，差异保存为 `inventory_reconciliation`。人工登记核对只记录处置过程，后续复检一致才转 `RESOLVED`，不自动覆盖库存。

迁移首次用现有 SKU 当前总量登记期初基线，不证明迁移前流水正确。之后手工插入 SKU 必须建立经核对的基线，或使用入库接口；缺基线会产生差异。

## 历史与购买事件

订单使用 `GET /api/checkout/orders/page?beforeId=...&limit=20`，券包使用 `GET /api/promotions/coupons/page?afterId=...&limit=20`，返回 `items,nextCursor`。限定当前账号，单页最多 100 条，可连续加载，突破旧列表 50/200 条限制。退款未知请求按账号保存原键，切换账号清理待确认数据并丢弃迟到响应。

支付/退款事实同事务写入 `commerce_order_event / commerce_event_delivery`，后台向 Recommend 和活动订单对应的 Seckill 交付。失败退避、耗尽后核对；租约后重新读取状态。接收端按事件标识去重、校验原订单来源、只应用更高版本，退款版本 2 先到也不会被支付版本 1 重新激活。

购买信号独立保存为 `recommendation_purchase_signal`，不伪造 like，不覆盖显式反馈。真实购买对已有候选提供有限弱加分，退款仅撤销对应购买信号，不制造 dislike；显式 dislike 排除仍保留。180 天窗口依据原交易时间，迟到投递不刷新年龄。Mock 可审计，永不激活购买偏好。

## 迁移与部署

先备份，再执行 `rs_service_trade_schema.sql` 和更新后的 `rs_service_commerce_v1_schema.sql`，核对 `rs-service-commerce-completion=commerce_completion_v2`。新表独立，不删除历史订单；旧支付缺可信来源时，用户退款要求人工核对。

一起更新 Common、Inventory、Promotion、Order、Payment、Seckill、Recommend、前端和工作台。远程 Compose 已接通 Order 的 Payment/Recommend/Seckill 地址及 Inventory/Promotion 运维凭证。

| 配置 | 用途 |
| --- | --- |
| `RS_COMMERCE_SERVICE_TOKEN` | 独立服务凭证，至少 32 字符，Order/Payment/Recommend/Seckill 一致；新退款报价/退款/事件接口留空默认拒绝 |
| `RS_PAYMENT_MOCK_REFUND_ENABLED` | 开启持久 Mock 退款及其签名回调，默认关闭 |
| `RS_RECOMMEND_COMMERCE_ENABLED` | 迁移及 JDBC 就绪后开启购买事件接收和排序加分，默认关闭 |
| `RS_COMMERCE_OPS_READ_TOKEN / WRITE_TOKEN` | 两枚不同运维凭证，均至少 32 字符 |
| `RS_COMMERCE_OPS_OPERATOR_ID` | 写入审计身份 |

新增指标组件 `refund / trade-event / inventory-reconciliation` 沿用待办、待核对、最老年龄规则；增加数据库池持续等待告警，5xx 规则覆盖交易服务。备份脚本已纳入库存账本、对账、租约、事件、退款和购买投影。

`deploy/remote/ops/configure_alerts.py` 从 `RS_ALERT_WEBHOOK_URL` 生成私密通知配置，要求 HTTPS 且禁止写入 Git 仓库。通过 `RS_ALERTMANAGER_CONFIG` 挂载，经 `amtool check-config` 后使用；未配置时仍只保留本地告警。脚本不发送消息。

## 持续联调与恢复演练

仓库根目录运行：

```powershell
mvn -f java_agent/pom.xml -pl rs-service-order,rs-service-payment,rs-service-seckill,rs-service-recommend,rs-api-gateway,rs-service-user -am package
python java_agent/deploy/local/commerce/fullstack.py --ha --duration 60 --clients 4 --output outputs/commerce-fullstack
```

八个 Java 模块经真实 Gateway/User/Redis 登录完成领券、下单、签名支付和退款，覆盖限量秒杀、重复/伪造回调、账号头伪造、拒绝恢复、响应丢失及分页。运行器创建独立随机 project、网络、数据库和凭证，容器总上限低于 6GiB，复制固定 JAR、记录哈希，退出仅清理本次环境。

报告分开记录请求延迟、状态码、完成订单 TPS、MySQL 行锁等待、连接池和 Kafka 指标。默认 60 秒低内存持续闭环，不代表峰值容量；可以增加时长，但仍需按目标环境测试。

恢复分支验证三副本 Kafka 停一台后继续秒杀、MySQL GTID 追平后计划内提升、Redis 复制确认后计划内提升，检查既有令牌和新交易。MySQL/Redis 切换停写，调整本次网络别名并重启连接；这是计划内恢复演练，不是自动故障转移或非计划故障零丢失保证。[MySQL GTID 定位](https://dev.mysql.com/doc/refman/8.0/en/change-replication-source-to.html)、[Redis 复制](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/)、[REPLICAOF 提升](https://redis.io/docs/latest/commands/replicaof/)。

最后将快照恢复到独立 MySQL，对比业务行数、退款结清、库存与券守恒、Mock 隔离，再由隔离 Alertmanager 向隔离 webhook 投递合成告警。安全报告可上传；私密账号、SQL 备份、凭证及命令日志不入 Git/CI artifact。

GitHub Actions `Commerce completion validation` 在 `codex/commerce-*` 交易代码推送时运行，也支持手动指定时长。任一步失败则工作流失败，不将脚本存在当作验证通过。本机 Docker Desktop 因运行时套接字异常无法启动，真实持续联调、三副本 Kafka 单点故障、MySQL/Redis 计划内提升、备份恢复及合成通知已转由 Linux CI 全部验证通过，见 [完整验收报告](reports/commerce-completion-20261019/README.md)。代码提交 `ca66a38e`：后端 429 项、前端 109 项、Node 10 项、运维 3 项及 Chromium 夹具通过；4 并发约 62 秒完成 112 笔下单/支付/退款闭环。未部署正式环境、未发送外部告警。
