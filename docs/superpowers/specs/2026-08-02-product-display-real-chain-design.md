# 推荐商品真实展示链路设计

**状态：** 已规划，待实现

**范围：** 第一版只完成推荐商品的真实展示与反馈闭环，不实现购物车、下单、支付、库存扣减或价格锁定。

## 目标

让首页和 Agent 对话使用同一条商品展示链路：推荐服务只产生 `item_id`、排序信息和推荐理由，Catalog 服务负责补全商品卡片，前端负责展示和记录用户反馈。

```text
推荐/Agent
  -> item_id + rank + score + reason
  -> POST /api/catalog/items/batch
  -> 统一 DisplayProduct
  -> ProductCard
  -> exposure / like / dislike / why
```

## 权责边界

- `rs-service-recommend`：召回、排序、推荐理由和推荐反馈接收。
- `rs-service-agent`：对话、Agent wire contract 和 `recommended_items`。
- `rs-service-catalog`：商品资料唯一来源，负责 ID 批量查询、缓存和 MySQL 降级。
- `rs-api-gateway`：暴露 `/api/catalog/**` 和 `/api/agent/**` 路由。
- React：请求编排、推荐数据与商品数据合并、展示状态和交互埋点。

## Catalog 批量契约

请求：

```json
{
  "item_ids": ["B001", "B002"]
}
```

接口：`POST /api/catalog/items/batch`

响应商品卡片字段：`item_id`、`title`、`category`、`brand`、`store_name`、`price`、`image_url`、`summary`。

规则：

- 输入最多 100 个 ID。
- 空白 ID 忽略。
- 未知 ID 不返回，不生成伪造商品。
- 返回结果恢复调用方输入顺序，并保留重复 ID 的展示语义。
- Redis 失败时继续读 MySQL；MySQL 失败时请求明确失败。
- 前端将 `store_name` 映射为 `store`，将 `summary` 映射为商品描述。

## Agent 对话契约

正式模式请求使用 `snake_case`：

```json
{
  "session_id": "sess_001",
  "profile_user_id": "user_001",
  "user_message": "想找一款通勤耳机",
  "limit": 5,
  "context": {"scene": "agent_chat"}
}
```

Agent 返回的 `recommended_items` 必须经过 Catalog 批量补全后再交给商品卡片组件。前端不得自行生成 `request_id` 或 `turn_index`。

## 反馈语义

- `exposure`：记录本次请求实际展示的商品。
- `like`：记录正向偏好，可触发后续重排。
- `dislike`：记录负向偏好，可触发排除或降权。
- `why`：只查询推荐解释，不改变用户偏好、不触发负反馈。

反馈请求至少包含 `request_id`、`session_id`、`item_id` 和事件类型；重复提交必须可识别，不能造成重复计数。

## 展示与降级

- Catalog 正常：展示真实标题、图片、价格、类目和店铺。
- 部分 ID 不存在：展示其余商品，并保持推荐顺序。
- 图片失效：显示统一占位，不影响商品文本展示。
- 价格或图片为空：显示明确占位，不填充虚假值。
- Catalog 整体失败：保留推荐标题/理由，显示商品详情暂不可用和重试入口。
- 首页和 Agent 对话必须复用同一 `DisplayProduct` 映射和 `ProductCard`。

## 验收标准

1. 首页真实模式调用 `/api/catalog/items/batch`，发送 `item_ids`，能够展示真实 Catalog 商品。
2. Agent 真实模式发送正式 `snake_case` 请求，并使用服务端返回的 `request_id`、`turn_index`。
3. 首页和 Agent 页面展示同一商品字段映射，不再各自拼装商品对象。
4. 批量查询的顺序、重复 ID、未知 ID、Redis 降级均有测试覆盖。
5. `like`、`dislike`、`why` 发送不同且正确的事件语义。
6. Catalog 超时、空图片、空价格和图片加载失败不会导致页面崩溃。
7. 前端类型检查、契约单测和一次真实 Gateway smoke 全部通过。

## 明确不做

- 商品详情完整页。
- 购物车、订单、支付和库存。
- 实时价格/库存锁定。
- 重新设计推荐算法、召回或排序逻辑。
- 修改现有会话持久化架构。
