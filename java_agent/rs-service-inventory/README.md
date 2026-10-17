# rs-service-inventory 服务职责说明

## 1. 服务定位

`rs-service-inventory` 是后续真实交易链路中的库存服务，负责库存查询、锁定、释放和确认扣减。

当前已实现库存查询、锁定、释放和确认扣减。MySQL 条件更新与流水在本地事务中提交，同一订单/SKU 的 LOCK 流水作为预留互斥行，确认和释放只能进入一个终态。订单通过持久待办驱动库存操作及失败重试。完整接口和验证方式见 [交易第一版说明](../../docs/commerce-v1.md)。

新秒杀活动使用 `ActivityStockService` 划拨专属库存。划拨进入聚合 locked，订单预留/取消在活动池内转移，支付确认转为 sold，活动结束且预留清零后归还余量。划拨幂等、订单取消墓碑和池内数量约束持久保存；部署前重跑 commerce SQL，历史活动不自动划拨。

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

当前在 full-commerce 部署模式启用本服务。

商品详情页通过库存接口展示聚合可售状态，通过 checkout_offer 查询实际可购买 SKU。展示不构成库存承诺，下单必须通过本服务锁定库存。
