import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';

// 在隔离的测试账户、活动和库存上执行；不创建账户，不输出访问令牌。
const base = (process.env.RS_SMOKE_GATEWAY_URL || 'http://127.0.0.1:18088').replace(/\/$/, '');
const token = process.env.RS_SMOKE_TOKEN;
const itemId = process.env.RS_SMOKE_ITEM_ID;
const skuId = process.env.RS_SMOKE_SKU_ID;
const campaignId = process.env.RS_SMOKE_CAMPAIGN_ID;
if (!token || !itemId || !skuId || !campaignId) {
  throw new Error('请设置 RS_SMOKE_TOKEN、RS_SMOKE_ITEM_ID、RS_SMOKE_SKU_ID、RS_SMOKE_CAMPAIGN_ID');
}
async function api(path, body, expectedStatus) {
  const response = await fetch(base + '/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  });
  const raw = await response.text();
  const value = raw ? JSON.parse(raw) : null;
  if (expectedStatus !== undefined) {
    assert.equal(response.status, expectedStatus, `接口 ${path} 状态不符合模拟场景`);
    return value;
  }
  assert.ok(response.ok, `接口 ${path} 返回 ${response.status}：${JSON.stringify(value)}`);
  return value;
}
async function waitOrder(id, predicate) {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    const order = await api('/checkout/orders/' + id);
    if (predicate(order)) return order;
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
  throw new Error('订单未在 90 秒内完成，请检查持久待办与服务状态');
}
const claimId = randomUUID();
const claimPath = '/promotions/campaigns/' + encodeURIComponent(campaignId) + '/claim';
const coupon = await api(claimPath, { requestId: claimId });
const duplicate = await api(claimPath, { requestId: claimId });
assert.equal(coupon.couponId, duplicate.couponId);
assert.equal(coupon.status, 'AVAILABLE', '测试券已使用或过期，请换测试账号或活动');
const offers = await api('/checkout/offers?itemId=' + encodeURIComponent(itemId));
const offer = offers.find(value => value.skuId === skuId);
assert.ok(offer, '请先配置测试 SKU 的服务端报价');
assert.ok(offer.unitPrice >= coupon.minimumAmount, '测试 SKU 的单件报价须满足券门槛');
const request = { requestId: randomUUID(), itemId, skuId, quantity: 1, couponId: coupon.couponId };
const created = await api('/checkout/orders', request);
const replay = await api('/checkout/orders', request);
assert.equal(created.orderId, replay.orderId);
const ready = await waitOrder(created.orderId, order => order.status === 'WAITING_PAYMENT' || order.status === 'CREATION_FAILED');
assert.equal(ready.status, 'WAITING_PAYMENT');
assert.equal(ready.totalAmount, offer.unitPrice - coupon.discountAmount);
await api('/checkout/orders/' + ready.orderId + '/cancel', {});
await api('/checkout/orders/' + ready.orderId + '/cancel', {});
await waitOrder(ready.orderId, order => order.status === 'CANCELED' && order.phase === 'DONE');
const returned = (await api('/promotions/coupons')).find(value => value.couponId === coupon.couponId);
assert.equal(returned.status, 'AVAILABLE');

if (process.env.RS_SMOKE_MOCK_PAY === 'true') {
  const capabilities = await api('/checkout/capabilities');
  assert.equal(capabilities.mockPaymentEnabled, true, '服务端未启用模拟支付');
  const paidOrder = await api('/checkout/orders', { ...request, requestId: randomUUID() });
  await waitOrder(paidOrder.orderId, order => order.status === 'WAITING_PAYMENT');
  const paymentPath = '/checkout/orders/' + paidOrder.orderId + '/mock-pay';
  for (const [scenario, status] of [['DECLINED', 402], ['TIMEOUT_BEFORE_PAYMENT', 504]]) {
    await api(paymentPath, { scenario }, status);
    assert.equal((await api('/checkout/orders/' + paidOrder.orderId)).status, 'WAITING_PAYMENT');
    assert.equal((await api('/promotions/coupons')).find(value => value.couponId === coupon.couponId).status, 'LOCKED');
  }
  await api(paymentPath, { scenario: 'RESPONSE_LOST' }, 504);
  assert.equal((await api('/checkout/orders/' + paidOrder.orderId)).status, 'PAID');
  // 同一个场景重试返回已持久化结果，不重复模拟故障或扣减资源。
  assert.equal((await api(paymentPath, { scenario: 'RESPONSE_LOST' })).status, 'PAID');
  await waitOrder(paidOrder.orderId, order => order.status === 'PAID' && order.phase === 'DONE');
  assert.equal((await api('/promotions/coupons')).find(value => value.couponId === coupon.couponId).status, 'USED');
}
console.log('交易 smoke 通过：领取幂等、服务端报价、锁券、订单幂等、取消返还' +
  (process.env.RS_SMOKE_MOCK_PAY === 'true' ? '、模拟拒付/超时/响应丢失恢复与核销' : ''));
