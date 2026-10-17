import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { writeFile } from 'node:fs/promises';

const hosts = { order: 'http://127.0.0.1:24291', orderB: 'http://127.0.0.1:24391',
  seckill: 'http://127.0.0.1:24294', seckillB: 'http://127.0.0.1:24394', inventory: 'http://127.0.0.1:24292' };
const activityId = `it-${randomUUID()}`;
const requests = Array.from({ length: 40 }, (_, i) => ({ account: `it-account-${i}`, requestId: randomUUID() }));
const latencies = [], outcomes = {};
async function api(host, path, account, body, token, expected) {
  const response = await fetch(hosts[host] + path, { method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(account ? { 'X-Account-Id': account } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000) });
  if (expected !== undefined) { assert.equal(response.status, expected, path); return; }
  assert.ok(response.ok, `${path}: HTTP ${response.status}`);
  const text = await response.text(); return text ? JSON.parse(text) : null;
}
async function wait(read, predicate, label) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const result = await read(); if (predicate(result)) return result;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`${label} 超时`);
}
async function parallel(values, action) {
  let cursor = 0;
  await Promise.all(Array.from({ length: 8 }, async () => { while (cursor < values.length) await action(values[cursor++]); }));
}
const writeToken = process.env.RS_COMMERCE_OPS_WRITE_TOKEN, readToken = process.env.RS_COMMERCE_OPS_READ_TOKEN;
assert.ok(writeToken && readToken, '运行器必须提供临时运维凭证');
await api('seckill', '/internal/seckill/tasks/summary', null, undefined, null, 401);
await api('seckill', '/internal/seckill/tasks/not-an-event/retry', null, { reason: '拒绝只读写入' }, readToken, 403);
await api('seckill', '/internal/seckill/activities', null, { activityId, itemId: 'it-item', skuId: 'it-sku', totalQuantity: 20,
  startsAt: new Date(Date.now() - 1000).toISOString().replace('Z', ''), endsAt: new Date(Date.now() + 45000).toISOString().replace('Z', '') }, writeToken);
await wait(() => api('seckill', `/api/seckill/activities/${activityId}`, 'it-reader'), value => value.status === 'ACTIVE', '活动划拨');
const stock = () => api('inventory', '/api/inventory/items/it-item/availability', 'it-reader');
assert.equal((await stock()).available_stock, 10);
const ordinary = await api('order', '/api/checkout/orders', 'it-ordinary', { requestId: randomUUID(), itemId: 'it-item', skuId: 'it-sku', quantity: 10, couponId: null });
await wait(() => api('order', `/api/checkout/orders/${ordinary.orderId}`, 'it-ordinary'), value => value.status === 'WAITING_PAYMENT', '普通订单锁库存');
assert.equal((await stock()).available_stock, 0);
const started = performance.now();
await parallel(requests.flatMap((request, index) => [{ ...request, index }, { ...request, index }]), async request => {
  const begin = performance.now();
  const result = await api(request.index % 2 ? 'seckillB' : 'seckill', `/api/seckill/activities/${activityId}/submit`, request.account,
    { requestId: request.requestId, itemId: 'it-item', skuId: 'it-sku', quantity: 1 });
  latencies.push(performance.now() - begin); outcomes[result.status] = (outcomes[result.status] || 0) + 1;
});
const acceptanceMs = performance.now() - started;
const accepted = [];
await parallel(requests, async request => {
  const activity = await api('seckill', `/api/seckill/activities/${activityId}`, request.account);
  if (!activity.participation) return;
  assert.equal(activity.participation.requestId, request.requestId);
  const result = await wait(() => api('seckill', `/api/seckill/requests/${request.requestId}`, request.account), value => !!value.orderId, 'Kafka 消费');
  const order = await wait(() => api('order', `/api/checkout/orders/${result.orderId}`, request.account), value => value.status === 'WAITING_PAYMENT', '活动库存预留');
  assert.equal(order.totalAmount, 3000); accepted.push({ ...request, orderId: result.orderId });
});
assert.equal(accepted.length, 20, '普通库存为零时，活动专属库存仍应全部创建订单');
assert.equal(new Set(accepted.map(record => record.orderId)).size, 20, '重复受理不得产生多订单');
const generationMs = performance.now() - started;
await parallel(accepted.map((record, index) => ({ ...record, pay: index < 10 })), async record => {
  await api('order', `/api/checkout/orders/${record.orderId}/${record.pay ? 'mock-pay' : 'cancel'}`, record.account, {});
  await wait(() => api('order', `/api/checkout/orders/${record.orderId}`, record.account), value => value.phase === 'DONE', '资源结清');
  await wait(() => api('seckill', `/api/seckill/requests/${record.requestId}`, record.account), value => value.status === (record.pay ? 'PAID' : 'CANCELED'), '结果对账');
});
await api('order', `/api/checkout/orders/${ordinary.orderId}/cancel`, 'it-ordinary', {});
await wait(() => api('order', `/api/checkout/orders/${ordinary.orderId}`, 'it-ordinary'), value => value.phase === 'DONE', '普通订单释放');
assert.equal((await stock()).available_stock, 10, '活动取消的十件仍留在活动池');
const pool = await wait(() => api('inventory', `/internal/inventory/activities/${activityId}`), value => value.status === 'CLOSED', '活动结束归还余量');
assert.equal(pool.sold_quantity, 10); assert.equal(pool.returned_quantity, 10); assert.equal(pool.reserved_quantity, 0);
assert.equal((await stock()).available_stock, 20);
const sorted = latencies.toSorted((a, b) => a - b), percentile = p => sorted[Math.ceil(sorted.length * p) - 1];
const report = { timestamp: new Date().toISOString(), mode: 'REAL_MYSQL_REDIS_KAFKA', activityId, instances: { order: 2, seckill: 2 },
  requestCount: latencies.length, outcomes, p95Ms: percentile(0.95), p99Ms: percentile(0.99), requestQps: latencies.length / (acceptanceMs / 1000),
  acceptanceMs, generationMs, uniqueAccepted: accepted.length, uniqueOrders: accepted.length, paid: 10, canceled: 10,
  finalPool: pool, finalAvailableStock: 20, violations: [],
  note: '隔离双实例单批联调；请求直连服务并使用测试 Account 头，未覆盖 Gateway 登录。外部付款采用 Mock，不代表持续容量或高可用。' };
await writeFile(process.env.RS_IT_REPORT, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
