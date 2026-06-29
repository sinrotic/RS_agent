# rs-service-order 服务职责说明

## 1. 服务定位

`rs-service-order` 是后续从推荐 Agent 平台扩展到真实交易链路时的订单服务。

当前项目的主线是推荐、RAG、Agent 对话和反馈闭环，因此第一阶段不需要实现真实订单。本目录先保留服务边界文档，后续只有当系统需要真实下单、支付状态流转和库存确认扣减时，再将它接入父工程。

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

当前推荐 Agent MVP 不实现本服务。

用户点击“购买”或“模拟购买”时，先由 `rs-service-interaction` 记录 `mock_purchase` 事件，用作推荐反馈信号，不生成真实订单，也不扣减真实库存。
