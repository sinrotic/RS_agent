import { readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import assert from 'node:assert/strict';

// 仅使用隔离活动和新测试账号；每账号一个业务请求并重复提交，结束后取消所建订单。
const base = (process.env.RS_SMOKE_GATEWAY_URL || 'http://127.0.0.1:18088').replace(/\/$/, '');
const activityId = process.env.RS_SMOKE_SECKILL_ACTIVITY_ID;
const accountFile = process.env.RS_SECKILL_LOAD_ACCOUNTS_FILE;
const concurrency = Number(process.env.RS_SECKILL_LOAD_CONCURRENCY || 8);
const budget = Number(process.env.RS_SECKILL_LOAD_ACCOUNTS || 50);
if (!activityId || !accountFile || !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 64
  || !Number.isInteger(budget) || budget < 1 || budget > 1000) throw new Error('请提供隔离活动、账号文件和合法的并发/账号预算');
const accounts = JSON.parse(await readFile(accountFile, 'utf8')).slice(0, budget);
assert.ok(accounts.length > 0 && accounts.every(a => typeof a.token === 'string' && a.token.length && typeof a.accountId === 'string'));
assert.equal(new Set(accounts.map(a => a.accountId)).size, accounts.length, '账号文件必须包含不同的测试账号');
const requestIds = accounts.map(() => randomUUID());
async function api(index, path, body) {
  const response = await fetch(base + '/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Authorization: `Bearer ${accounts[index].token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error(`HTTP_${response.status}`);
  return response.json();
}
async function parallel(values, operation) {
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, async () => {
    while (cursor < values.length) { const value = values[cursor++]; await operation(value); }
  }));
}
const path = `/seckill/activities/${encodeURIComponent(activityId)}`;
const initial = await api(0, path);
assert.equal(initial.status, 'ACTIVE');
const stockPath = `/inventory/items/${encodeURIComponent(initial.itemId)}/availability`;
const stockBefore = await api(0, stockPath);
// 预检所有账号均未参与，避免把历史请求回放误报为本轮吞吐。
await parallel(accounts.map((_, i) => i), async i => {
  assert.equal((await api(i, path)).participation, null, '测试账号已参与此活动，请换新活动');
});
const outcomes = {}, latencies = [], accepted = new Set(), unknown = new Set(), orders = new Map(), unresolved = new Set();
const started = performance.now();
await parallel(accounts.flatMap((_, i) => [i, i]), async i => {
  const begin = performance.now();
  let status;
  try {
    const result = await api(i, `${path}/submit`, {
      requestId: requestIds[i], itemId: initial.itemId, skuId: initial.skuId, quantity: 1,
    });
    status = result.status;
    if (!['STOCK_NOT_ENOUGH', 'NOT_STARTED', 'ENDED'].includes(status)) accepted.add(i);
  } catch (error) {
    status = error.message.startsWith('HTTP_') ? error.message : 'NETWORK_ERROR';
    if (status === 'NETWORK_ERROR' || status.startsWith('HTTP_5')) unknown.add(i);
  }
  outcomes[status] = (outcomes[status] || 0) + 1;
  latencies.push(performance.now() - begin);
});
const acceptanceMs = performance.now() - started;
// 对响应未知的账号也回查，避免已受理请求遗漏清理。
const polling = new Set(accounts.map((_, i) => i));
const deadline = Date.now() + 120000;
while (polling.size && Date.now() < deadline) {
  await parallel([...polling], async i => {
    try {
      const result = await api(i, `/seckill/requests/${requestIds[i]}`);
      accepted.add(i);
      if (result.orderId) { orders.set(i, result.orderId); polling.delete(i); }
      else if (['FAILED', 'REVIEW_REQUIRED'].includes(result.status)) polling.delete(i);
    } catch (error) {
      if (error.message === 'HTTP_404' && !accepted.has(i) && !unknown.has(i)) polling.delete(i);
    }
  });
  if (polling.size) await new Promise(resolve => setTimeout(resolve, 2000));
}
const generationMs = performance.now() - started;
for (const i of accepted) if (!orders.has(i)) unresolved.add(i);
for (const i of unknown) if (!orders.has(i) && !accepted.has(i)) unresolved.add(i);
let completedCancellations = 0;
const cleanupDeadline = Date.now() + 120000;
await parallel([...orders], async ([i, orderId]) => {
  try {
    await api(i, `/checkout/orders/${orderId}/cancel`, {});
    while (Date.now() < cleanupDeadline) {
      const result = await api(i, `/seckill/requests/${requestIds[i]}`);
      if (result.status === 'CANCELED') { completedCancellations++; return; }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  } catch { /* 在报告中保留未清理请求，不能将未确认当作已取消。 */ }
  unresolved.add(i);
});
const final = await api(0, path);
const stockAfter = await api(0, stockPath);
const sorted = latencies.toSorted((a, b) => a - b);
const percentile = p => sorted[Math.max(0, Math.ceil(sorted.length * p) - 1)];
const violations = [];
if (accepted.size > initial.remainingQuantity) violations.push('受理数超过初始名额');
if (final.remainingQuantity < 0) violations.push('出现负活动额度');
if (!unresolved.size && completedCancellations === accepted.size && final.remainingQuantity !== initial.remainingQuantity)
  violations.push('取消完成后活动额度未恢复');
if (!unresolved.size && completedCancellations === accepted.size && stockAfter.available_stock !== stockBefore.available_stock)
  violations.push('取消完成后可售库存未恢复');
const report = {
  timestamp: new Date().toISOString(), activityId, concurrency, accounts: accounts.length,
  requestCount: latencies.length, outcomes, p95Ms: percentile(0.95), p99Ms: percentile(0.99),
  requestQps: latencies.length / (acceptanceMs / 1000), acceptanceMs,
  uniqueAccepted: accepted.size, unknownResponseAccounts: unknown.size, generatedOrders: orders.size,
  observedOrdersPerSecond: orders.size / (generationMs / 1000), generationMs,
  completedCancellations, remainingBefore: initial.remainingQuantity, remainingAfter: final.remainingQuantity,
  stockBefore: stockBefore.available_stock, stockAfter: stockAfter.available_stock,
  unresolved: [...unresolved].map(i => ({ accountIndex: i, requestId: requestIds[i], orderId: orders.get(i) || null })), violations,
  note: '单批隔离测试的观测值，包含轮询等待；不是持续负载容量或高可用结论。令牌未写入报告。',
};
const output = process.env.RS_SECKILL_LOAD_REPORT;
if (output) await writeFile(output, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (violations.length || unresolved.size) process.exitCode = 2;
