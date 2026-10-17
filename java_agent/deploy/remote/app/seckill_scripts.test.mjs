import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, unlink, rmdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

async function fixture({ seckillReview = true, checkoutReview = false } = {}) {
  let quota = 2, stock = 10;
  const records = new Map();
  const server = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://fixture');
    const account = request.headers.authorization;
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = raw ? JSON.parse(raw) : {};
    let record = records.get(account), value, code = 200;
    if (url.pathname.endsWith('/availability')) value = { available_stock: stock };
    else if (url.pathname === '/api/checkout/capabilities') value = { mockPaymentEnabled: true };
    else if (url.pathname === '/api/seckill/activities/fixture') value = {
      activityId: 'fixture', itemId: 'item', skuId: 'sku', status: quota ? 'ACTIVE' : 'SOLD_OUT',
      unitPrice: 3000, remainingQuantity: quota, participation: record ? record.result : null,
    };
    else if (url.pathname.endsWith('/submit')) {
      if (record) value = { ...record.result, status: record.result.requestId === body.requestId ? record.result.status : 'DUPLICATE' };
      else if (!quota) value = { requestId: body.requestId, status: 'STOCK_NOT_ENOUGH', orderId: null };
      else {
        quota--; stock--;
        record = { result: { requestId: body.requestId, status: 'WAITING_PAYMENT', orderId: records.size + 1 },
          order: { orderId: records.size + 1, status: 'WAITING_PAYMENT', phase: 'READY', totalAmount: 3000, quantity: 1, couponId: null } };
        records.set(account, record); value = { requestId: body.requestId, status: 'PROCESSING', orderId: null };
      }
    } else if (url.pathname.startsWith('/api/seckill/requests/')) {
      value = record?.result; if (!value) { code = 404; value = {}; }
    } else if (url.pathname.startsWith('/api/checkout/orders/')) {
      assert.ok(record); assert.equal(Number(url.pathname.split('/')[4]), record.order.orderId);
      if (url.pathname.endsWith('/cancel') && record.order.status !== 'CANCELED') {
        record.order.status = record.result.status = 'CANCELED'; record.order.phase = 'DONE'; quota++; stock++;
      }
      if (url.pathname.endsWith('/mock-pay') && record.order.status !== 'PAID') {
        record.order.status = record.result.status = 'PAID'; record.order.phase = 'DONE';
        if (body.scenario === 'RESPONSE_LOST') code = 504;
      }
      value = record.order;
    } else if (url.pathname === '/internal/seckill/tasks/summary') value = { pending: seckillReview ? 1 : 0, unpublished: 0, reviewRequired: seckillReview ? 1 : 0 };
    else if (url.pathname.startsWith('/internal/seckill/tasks')) value = seckillReview ? [{ eventId: 'fixture', status: 'REVIEW_REQUIRED', attempts: 10 }] : [];
    else if (url.pathname === '/internal/checkout/tasks/summary') value = { pending: checkoutReview ? 1 : 0, reviewRequired: checkoutReview ? 1 : 0 };
    else if (url.pathname.startsWith('/internal/checkout/tasks')) value = checkoutReview ? [{ orderId: 7, status: 'PAID', phase: 'REVIEW_CONFIRM_STOCK', attempts: 20 }] : [];
    else if (url.pathname === '/internal/payment/notifications/summary') value = { pending: 0, reviewRequired: 0 };
    else if (url.pathname === '/internal/payment/notifications') value = [];
    else { code = 404; value = {}; }
    response.writeHead(code, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(value));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { base: `http://127.0.0.1:${server.address().port}`, close: () => new Promise(resolve => server.close(resolve)) };
}
function run(name, environment) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [fileURLToPath(new URL(name, import.meta.url))], {
      env: { ...process.env, RS_SMOKE_SECKILL_ACTIVITY_ID: 'fixture', RS_SMOKE_TOKEN: 'fixture-token', ...environment },
    });
    let stdout = '', stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', reject); child.on('close', code => resolve({ code, stdout, stderr }));
  });
}
for (const action of ['cancel', 'mock-pay']) test(`smoke 夹具：${action}`, async () => {
  const server = await fixture();
  try {
    const result = await run('seckill_smoke.mjs', { RS_SMOKE_GATEWAY_URL: server.base, RS_SMOKE_SECKILL_ACTION: action });
    assert.equal(result.code, 0, result.stderr); assert.match(result.stdout, /smoke 通过/);
  } finally { await server.close(); }
});
test('并发脚本区分请求吞吐和订单生成，并在取消后检查额度', async () => {
  const server = await fixture(); const directory = await mkdtemp(join(tmpdir(), 'rs-seckill-fixture-'));
  const accounts = join(directory, 'accounts.json');
  try {
    await writeFile(accounts, JSON.stringify(Array.from({ length: 3 }, (_, i) => ({ accountId: `fixture-${i}`, token: `fixture-${i}` }))));
    const result = await run('seckill_load.mjs', { RS_SMOKE_GATEWAY_URL: server.base,
      RS_SECKILL_LOAD_ACCOUNTS_FILE: accounts, RS_SECKILL_LOAD_CONCURRENCY: '3', RS_SECKILL_LOAD_ACCOUNTS: '3', RS_SECKILL_LOAD_REPORT: '' });
    assert.equal(result.code, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    assert.equal(report.requestCount, 6); assert.equal(report.generatedOrders, 2);
    assert.equal(report.uniqueAccepted, 2); assert.equal(report.completedCancellations, 2);
    assert.equal(report.remainingAfter, 2); assert.deepEqual(report.unresolved, []);
    assert.deepEqual(report.violations, []); assert.ok(report.requestQps > 0);
    assert.doesNotMatch(result.stdout, /fixture-token|Bearer/);
  } finally { await unlink(accounts); await rmdir(directory); await server.close(); }
});
test('巡检发现待核对任务使用退出码 2', async () => {
  const server = await fixture();
  try {
    const result = await run('seckill_health.mjs', { RS_SECKILL_INTERNAL_URL: server.base, RS_ORDER_INTERNAL_URL: server.base, RS_PAYMENT_INTERNAL_URL: server.base });
    assert.equal(result.code, 2, result.stderr); assert.equal(JSON.parse(result.stdout).summary.reviewRequired, 1);
  } finally { await server.close(); }
});
test('秒杀记录正常但已支付订单卡在库存核销时，巡检仍告警', async () => {
  const server = await fixture({ seckillReview: false, checkoutReview: true });
  try {
    const result = await run('seckill_health.mjs', { RS_SECKILL_INTERNAL_URL: server.base, RS_ORDER_INTERNAL_URL: server.base, RS_PAYMENT_INTERNAL_URL: server.base });
    assert.equal(result.code, 2, result.stderr);
    const value = JSON.parse(result.stdout);
    assert.equal(value.summary.reviewRequired, 0); assert.equal(value.checkout.stalled[0].phase, 'REVIEW_CONFIRM_STOCK');
  } finally { await server.close(); }
});
test('三个服务均没有异常待办时，巡检返回成功', async () => {
  const server = await fixture({ seckillReview: false, checkoutReview: false });
  try {
    const result = await run('seckill_health.mjs', { RS_SECKILL_INTERNAL_URL: server.base, RS_ORDER_INTERNAL_URL: server.base, RS_PAYMENT_INTERNAL_URL: server.base });
    assert.equal(result.code, 0, result.stderr);
  } finally { await server.close(); }
});
