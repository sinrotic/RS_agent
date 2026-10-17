// 浏览器 API 夹具验证；真实 Redis/Kafka 验收使用远程 seckill_smoke.mjs。
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.RS_CHROMIUM_PATH ? { executablePath: process.env.RS_CHROMIUM_PATH } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const orders = new Map(), submissions = new Map(), bodies = new Map();
    let activeAccount = 'account';
    let secondAccountOrder;
    let originalAccountRequest;
    const resultFor = id => {
      if (activeAccount !== 'account') return null;
      const order = orders.get(id);
      return order ? { requestId: bodies.get(id).requestId, status: order.status, orderId: order.orderId } : null;
    };
    const activity = (id, remaining = 5, startOffset = -60000, endOffset = 3600000) => ({
      activityId: id, itemId: 'item', skuId: 'sku', itemTitle: `活动 ${id}`, unitPrice: 3000,
      totalQuantity: 5, remainingQuantity: remaining, startsAt: new Date(Date.now() + startOffset).toISOString(),
      endsAt: new Date(Date.now() + endOffset).toISOString(), serverTime: new Date().toISOString(),
      status: 'ACTIVE', participation: resultFor(id),
    });
    const makeOrder = id => ({ orderId: id === 'loss-before' ? 1001 : 1002, status: 'WAITING_PAYMENT', phase: 'READY',
      itemId: 'item', skuId: 'sku', itemTitle: `活动 ${id}`, quantity: 1, originalAmount: 3000,
      discountAmount: 0, totalAmount: 3000, couponId: null, expiresAt: new Date(Date.now() + 900000).toISOString(), failureReason: null });
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const request = route.request(), url = new URL(request.url()), endpoint = url.pathname;
      let body = {}, status = 200;
      if (endpoint === '/api/auth/me') body = { accountId: activeAccount, profileUserId: 'profile', username: '测试账号' };
      else if (endpoint === '/api/catalog/items/item') body = { item_id: 'item', title: '秒杀测试商品', price: 30, category: '测试', attributes: {} };
      else if (endpoint.startsWith('/api/inventory/')) body = { item_id: 'item', sku_count: 1, available_stock: 5, available: true };
      else if (endpoint === '/api/checkout/offers') body = [{ skuId: 'sku', itemId: 'item', itemTitle: '交易测试商品', unitPrice: 3000 }];
      else if (endpoint.startsWith('/api/promotions/')) body = [];
      else if (endpoint === '/api/checkout/capabilities') body = { mockPaymentEnabled: true };
      else if (endpoint === '/api/checkout/orders') {
        if (request.method() === 'POST') {
          const submitted = request.postDataJSON();
          if (activeAccount === 'account') {
            originalAccountRequest = submitted.requestId;
            await route.fulfill({ status: 504, contentType: 'application/json', body: '{"message":"模拟响应未知"}' });
            return;
          }
          assert.equal(activeAccount, 'account-b');
          assert.notEqual(submitted.requestId, originalAccountRequest);
          assert.equal(submitted.quantity, 1);
          secondAccountOrder = { ...makeOrder('account-b'), orderId: 1003 };
        }
        body = request.method() === 'POST' ? secondAccountOrder
          : activeAccount === 'account' ? [...orders.values()] : secondAccountOrder ? [secondAccountOrder] : [];
      }
      else if (endpoint === '/api/seckill/activities') body = [activity('loss-before'), activity('loss-after'),
        activity('future', 5, 3600000, 7200000), activity('sold-out', 0), activity('ended', 5, -7200000, -3600000), activity('account-loss'),
        { ...activity('preparing'), status: 'PREPARING' }, { ...activity('unavailable'), status: 'UNAVAILABLE' }];
      else if (endpoint === '/api/seckill/activities/old-review') body = {
        ...activity('old-review', 4, -259200000, -172800000), status: 'ENDED',
        participation: { requestId: 'old-original-request', status: 'REVIEW_REQUIRED', orderId: null },
      };
      else if (endpoint.endsWith('/submit')) {
        const id = endpoint.split('/')[4], submitted = request.postDataJSON();
        assert.equal(submitted.quantity, 1); assert.equal(submitted.itemId, 'item');
        assert.equal(submitted.accountId, undefined); assert.equal(submitted.unitPrice, undefined);
        if (bodies.has(id)) assert.equal(submitted.requestId, bodies.get(id).requestId, '重试须使用原请求键');
        bodies.set(id, submitted); submissions.set(id, (submissions.get(id) || 0) + 1);
        if (submissions.get(id) === 1) {
          if (id === 'loss-after') orders.set(id, makeOrder(id));
          status = 504; body = { message: '模拟响应丢失' };
        } else { orders.set(id, makeOrder(id)); body = { requestId: submitted.requestId, status: 'PROCESSING', orderId: null }; }
      } else if (endpoint.startsWith('/api/seckill/requests/')) {
        const id = [...bodies.keys()].find(id => bodies.get(id).requestId === endpoint.split('/').pop());
        body = id ? resultFor(id) : null;
        if (!body) { status = 404; body = {}; }
      } else if (endpoint.startsWith('/api/checkout/orders/')) {
        const order = [...orders.values()].find(order => order.orderId === Number(endpoint.split('/')[4]));
        assert.ok(order, '请求所属订单存在');
        if (endpoint.endsWith('/cancel')) { order.status = 'CANCELED'; order.phase = 'DONE'; }
        if (endpoint.endsWith('/mock-pay')) { order.status = 'PAID'; order.phase = 'DONE';
          if (request.postDataJSON().scenario === 'RESPONSE_LOST') status = 504;
        }
        body = status === 504 ? { message: '模拟支付响应丢失' } : order;
      } else throw new Error(`未配置浏览器夹具：${endpoint}`);
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto(`${process.env.RS_E2E_BASE_URL || 'http://127.0.0.1:5173'}/products/item`);
    const card = id => page.getByText(`活动 ${id} · 秒杀价`, { exact: false }).locator('..');
    await card('future').getByRole('button', { name: '立即抢购' }).waitFor();
    for (const id of ['future', 'sold-out', 'ended', 'preparing', 'unavailable']) assert.equal(await card(id).getByRole('button', { name: '立即抢购' }).isDisabled(), true);
    await page.evaluate(async () => {
      const shared = await import('/src/api/shared.ts');
      sessionStorage.setItem(shared.commerceStorageKey('seckill', 'item'), JSON.stringify({
        'old-review': { requestId: 'old-original-request', itemId: 'item', skuId: 'sku', quantity: 1 },
      }));
    });
    await page.reload();
    await card('old-review').getByText('处理时间较长，后台正在核对', { exact: true }).waitFor();
    assert.equal(submissions.has('old-review'), false, '恢复过期活动仅查询详情，不重新受理');
    await card('loss-before').getByRole('button', { name: '立即抢购' }).click();
    await card('loss-before').getByRole('button', { name: '重试原抢购请求' }).click();
    await card('loss-before').getByRole('button', { name: '查看订单' }).waitFor({ timeout: 15000 });
    assert.equal(submissions.get('loss-before'), 2);
    await card('loss-before').getByRole('button', { name: '查看订单' }).click();
    await page.locator('#checkout-order-1001').getByRole('button', { name: '取消订单' }).click();
    await page.locator('#checkout-order-1001').getByText('已取消', { exact: false }).waitFor();
    await card('loss-after').getByRole('button', { name: '立即抢购' }).click();
    await page.getByText('尚未确认抢购结果', { exact: false }).waitFor();
    await page.reload();
    await card('loss-after').getByRole('button', { name: '查看订单' }).waitFor({ timeout: 15000 });
    assert.equal(submissions.get('loss-after'), 1, '刷新后应恢复原受理记录，不自动重复提交');
    await card('loss-after').getByRole('button', { name: '查看订单' }).click();
    await page.getByLabel('模拟支付场景（不扣款）').selectOption('RESPONSE_LOST');
    await page.locator('#checkout-order-1002').getByRole('button', { name: '模拟支付（不扣款）' }).click();
    await page.locator('#checkout-order-1002').getByText('已支付', { exact: false }).waitFor();
    await card('loss-after').getByText('已支付', { exact: true }).waitFor({ timeout: 15000 });
    assert.deepEqual(errors, []);
    const output = path.resolve(__dirname, '../../../outputs/commerce-allocation-optimization-20261011/seckill-browser.png');
    await fs.mkdir(path.dirname(output), { recursive: true });
    await page.screenshot({ path: output, fullPage: true });
    await page.getByRole('button', { name: '提交订单', exact: true }).click();
    await page.getByRole('button', { name: '重试原订单提交', exact: true }).waitFor();
    await card('account-loss').getByRole('button', { name: '立即抢购' }).click();
    await card('account-loss').getByRole('button', { name: '重试原抢购请求' }).waitFor();
    activeAccount = 'account-b';
    // 同一页面更换服务端认证账号；交易组件需要同步清空内存中的旧请求。
    await page.evaluate(async () => { const auth = await import('/src/api/authClient.ts'); await auth.getMe(); });
    await card('loss-before').getByRole('button', { name: '立即抢购' }).waitFor();
    assert.equal(await page.getByRole('button', { name: '重试原抢购请求' }).count(), 0);
    assert.equal(await page.getByRole('button', { name: '重试原订单提交' }).count(), 0);
    const previousKeys = await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('checkout-pending:account:') || key.startsWith('seckill-pending:account:')));
    assert.deepEqual(previousKeys, []);
    await page.getByRole('button', { name: '提交订单', exact: true }).click();
    await page.locator('#checkout-order-1003').waitFor();
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(path.dirname(output), 'account-switch-browser.png'), fullPage: true });
    console.log('秒杀浏览器夹具验证通过：时段与售罄禁用、原请求重试、刷新恢复、订单打开、取消、支付响应丢失恢复和账号切换隔离');
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
