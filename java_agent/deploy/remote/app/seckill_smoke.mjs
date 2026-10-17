import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';

const base = (process.env.RS_SMOKE_GATEWAY_URL || 'http://127.0.0.1:18088').replace(/\/$/, '');
const token = process.env.RS_SMOKE_TOKEN;
const activityId = process.env.RS_SMOKE_SECKILL_ACTIVITY_ID;
const action = process.env.RS_SMOKE_SECKILL_ACTION || 'cancel';
if (!token || !activityId || !['cancel', 'mock-pay'].includes(action))
  throw new Error('请提供 RS_SMOKE_TOKEN、RS_SMOKE_SECKILL_ACTIVITY_ID；ACTION 为 cancel 或 mock-pay');
async function api(path, body, expectedStatus) {
  const response = await fetch(`${base}/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000),
  });
  if (expectedStatus !== undefined) { assert.equal(response.status, expectedStatus); return null; }
  assert.ok(response.ok, `接口 ${path} 返回 ${response.status}`);
  return response.json();
}
async function wait(read, predicate, label) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const value = await read();
    assert.notEqual(value.status, 'FAILED', '秒杀订单创建失败');
    assert.notEqual(value.status, 'CREATION_FAILED', '测试 SKU 库存不足或服务拒绝');
    assert.notEqual(value.status, 'REVIEW_REQUIRED', '事件已进入待核对，请检查死信和下游');
    if (predicate(value)) return value;
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  throw new Error(`${label} 未在两分钟内完成`);
}
const activityPath = `/seckill/activities/${encodeURIComponent(activityId)}`;
const activity = await api(activityPath);
assert.equal(activity.status, 'ACTIVE', '需要处于活动期且有名额的独立测试活动');
assert.equal(activity.participation, null, '该账号已参与，请换活动或账号');
if (action === 'mock-pay') assert.equal((await api('/checkout/capabilities')).mockPaymentEnabled, true);
const stockPath = `/inventory/items/${encodeURIComponent(activity.itemId)}/availability`;
const beforeStock = await api(stockPath);
const request = { requestId: randomUUID(), itemId: activity.itemId, skuId: activity.skuId, quantity: 1 };
const accepted = await api(`${activityPath}/submit`, request);
assert.equal(accepted.status, 'PROCESSING');
assert.equal((await api(`${activityPath}/submit`, request)).requestId, request.requestId);
const duplicate = await api(`${activityPath}/submit`, { ...request, requestId: randomUUID() });
assert.equal(duplicate.status, 'DUPLICATE');
assert.equal(duplicate.requestId, request.requestId);
const resultPath = `/seckill/requests/${encodeURIComponent(request.requestId)}`;
const result = await wait(() => api(resultPath), value => !!value.orderId, 'Kafka 消费与订单生成');
const orderPath = `/checkout/orders/${result.orderId}`;
const ready = await wait(() => api(orderPath), value => value.status === 'WAITING_PAYMENT', '库存预留');
assert.equal(ready.totalAmount, activity.unitPrice);
assert.equal(ready.quantity, 1);
assert.equal(ready.couponId, null);
assert.equal((await api(activityPath)).remainingQuantity, activity.remainingQuantity - 1);
if (action === 'cancel') {
  await api(`${orderPath}/cancel`, {}); await api(`${orderPath}/cancel`, {});
} else {
  await api(`${orderPath}/mock-pay`, { scenario: 'RESPONSE_LOST' }, 504);
  assert.equal((await api(`${orderPath}/mock-pay`, { scenario: 'RESPONSE_LOST' })).status, 'PAID');
}
const terminal = action === 'cancel' ? 'CANCELED' : 'PAID';
await wait(() => api(orderPath), value => value.status === terminal && value.phase === 'DONE', '订单资源处理');
await wait(() => api(resultPath), value => value.status === terminal, '秒杀结果对账');
assert.equal((await api(activityPath)).remainingQuantity, activity.remainingQuantity - (action === 'cancel' ? 0 : 1));
assert.equal((await api(stockPath)).available_stock, beforeStock.available_stock - (action === 'cancel' || activity.inventoryMode === 'ALLOCATED' ? 0 : 1));
const replay = await api(`${activityPath}/submit`, request);
assert.equal(replay.orderId, result.orderId);
assert.equal(replay.status, terminal);
console.log(`秒杀 smoke 通过：受理幂等、Kafka 订单生成、冻结报价、库存预留、${terminal}、额度与库存核对`);
