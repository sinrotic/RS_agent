# rs-service-order 服务职责说明

## 1. 服务定位

`rs-service-order` 是后续从推荐 Agent 平台扩展到真实交易链路时的订单服务。

当前已接入父工程，并新增 Checkout 流程：先持久化订单意图和服务端报价，再锁券、锁库存；支付、取消和超时关闭的后续资源操作由持久待办重试。普通 /api/orders 创建入口兼容旧请求格式，但不使用客户端单价。完整状态、接口及验证范围见 [交易第一版说明](../../docs/commerce-v1.md)。

## 2. 核心职责

后续真实交易版本中，`rs-service-order` 负责：

- 创建订单。
- 查询订单详情和订单列表。
- 维护订单状态流转。
- 处理订单取消和超时关闭。
- 接收支付成功结果，并触发库存确认扣减。
- 记录订单和推荐 request、session、profile user 的归因关系。
- 向 `rs-service-interaction` 发送真实转化事件。

## 3. 不负责的事情

`rs-service-order` 不负责：

- 商品主数据维护，这属于 `rs-service-catalog`。
- 库存数量维护、锁定、释放、扣减，这属于 `rs-service-inventory`。
- 支付渠道对接，这可以后续拆成 `rs-service-payment`。
- 推荐召回和排序，这属于 `rs-service-recommend`。
- Agent 对话编排，这属于 `rs-service-agent`。

## 4. 与其他服务的关系

典型链路如下：

```text
frontend
  -> rs-service-order 创建订单
  -> rs-service-inventory 锁定库存
  -> payment 支付成功
  -> rs-service-order 更新订单状态
  -> rs-service-inventory 确认扣减库存
  -> rs-service-interaction 记录真实购买事件
```

订单创建时建议保存推荐归因字段：

```text
orderId
accountId
profileUserId
sessionId
recommendRequestId
itemId
quantity
orderStatus
```

这样后续可以解释“这个购买是否来自某次推荐或 Agent 对话”。

## 5. 第一版接口草案

如果后续实现真实订单，第一版可以只做：

```text
POST /api/orders
GET  /api/orders/{orderId}
GET  /api/orders
POST /api/orders/{orderId}/cancel
POST /internal/orders/{orderId}/paid
```

其中：

- `POST /api/orders` 创建订单并请求库存锁定。
- `POST /api/orders/{orderId}/cancel` 取消订单并释放库存。
- `POST /internal/orders/{orderId}/paid` 由支付链路回调，确认订单已支付，并通知库存确认扣减。

## 6. 当前阶段处理方式

当前 full-commerce 模式启用本服务。/api/checkout 提供商品详情页交易入口，创建先返回 CREATING，后续查询进入 WAITING_PAYMENT 或 CREATION_FAILED。

交易入口会创建订单并锁定库存。模拟支付仅在显式启用的联调环境开放，会确认测试库存和券核销但不扣款。历史推荐反馈中的 mock_purchase 不等于这条交易链路的真实支付事实，第一版不自动将两者混合归因。

工作流使用有界并发；永久错误或重试耗尽后进入 REVIEW_ 阶段，可从内部巡检和带操作记录的恢复接口处理。旧秒杀消费者默认关闭；未接入 checkout_workflow 的历史订单不能继续调用旧支付/超时处理，需要先核对迁移。具体接口、配置和 SQL 部署顺序见上述交易说明。
