# rs-service-inventory 服务职责说明

## 1. 服务定位

`rs-service-inventory` 是后续真实交易链路中的库存服务，负责库存查询、锁定、释放和确认扣减。

当前推荐 Agent 项目没有真实履约、支付和库存一致性要求，因此第一阶段不需要实现库存服务。本目录先保留边界文档，避免后续把库存扣减误放进 `rs-service-recommend`、`rs-service-agent` 或 `rs-service-interaction`。

## 2. 核心职责

后续真实交易版本中，`rs-service-inventory` 负责：

- 查询商品可售库存。
- 创建订单时锁定库存。
- 订单取消或超时未支付时释放库存。
- 支付成功后确认扣减库存。
- 防止超卖。
- 记录库存流水，便于排查库存变更来源。

## 3. 不负责的事情

`rs-service-inventory` 不负责：

- 商品标题、图片、类目、虚拟店铺等商品展示信息，这属于 `rs-service-catalog`。
- 创建订单和订单状态流转，这属于 `rs-service-order`。
- 支付渠道回调，这可以后续放在 `rs-service-payment`。
- 用户行为反馈，这属于 `rs-service-interaction`。
- 推荐或 Agent 对话逻辑。

## 4. 与 catalog 的边界

`rs-service-catalog` 负责商品目录和商品展示。

`rs-service-inventory` 只负责库存状态。

如果项目只做虚拟库存展示，可以先把库存字段放在 `rs-service-catalog` 的商品卡片里；如果要做真实下单和并发扣减，则应该使用独立的 `rs-service-inventory`。

## 5. 库存状态模型

第一版可以按以下字段设计：

```text
itemId
availableQuantity
lockedQuantity
soldQuantity
updatedAt
```

库存流水可以记录：

```text
flowId
itemId
orderId
changeType
changeQuantity
beforeAvailableQuantity
afterAvailableQuantity
createdAt
```

建议的 `changeType`：

```text
LOCK
RELEASE
CONFIRM_DEDUCT
MANUAL_ADJUST
```

## 6. 第一版接口草案

如果后续实现真实库存，第一版可以只做内部接口：

```text
GET  /internal/inventory/items/{itemId}
POST /internal/inventory/lock
POST /internal/inventory/release
POST /internal/inventory/confirm-deduct
```

典型调用关系：

```text
rs-service-order 创建订单
  -> POST /internal/inventory/lock

rs-service-order 取消订单
  -> POST /internal/inventory/release

rs-service-order 支付成功
  -> POST /internal/inventory/confirm-deduct
```

## 7. 当前阶段处理方式

当前推荐 Agent MVP 不实现本服务。

如果前端需要展示“可购买”状态，可以先由 `rs-service-catalog` 返回静态或虚拟库存状态。只有当系统进入真实订单和支付阶段时，再启用独立库存服务。
