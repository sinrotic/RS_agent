import { beforeEach, describe, expect, it, vi } from 'vitest';
const { getJson, postJson } = vi.hoisted(() => ({ getJson: vi.fn(), postJson: vi.fn() }));
vi.mock('./shared', () => ({ getJson, postJson }));
import { claimCoupon, createCheckoutOrder, cancelCheckoutOrder, mockPayCheckoutOrder, listOffers,
  listSeckillActivities, getSeckillResult, submitSeckill, listOrderPage, listCouponPage, requestOrderRefund } from './commerceClient';

describe('交易接口', () => {
  beforeEach(() => { getJson.mockReset(); postJson.mockReset(); });
  it('历史游标安全编码，退款响应未知时仍保留原业务请求', async () => {
    await listOrderPage('123');await listCouponPage('a/b');
    expect(getJson.mock.calls).toEqual([['/checkout/orders/page?limit=20&beforeId=123'],['/promotions/coupons/page?limit=20&afterId=a%2Fb']]);
    const request={requestId:'stable-refund',reason:'整单退款',scenario:'RESPONSE_LOST' as const};
    postJson.mockRejectedValueOnce(new Error('unknown')).mockResolvedValueOnce({refundId:'same'});
    await expect(requestOrderRefund(10,request)).rejects.toThrow();await requestOrderRefund(10,request);
    expect(postJson.mock.calls).toEqual(Array(2).fill(['/checkout/orders/10/refunds',request]));
    expect(request).not.toHaveProperty('amount');expect(request).not.toHaveProperty('accountId');
  });
  it('失败重试保留同一个业务请求键和选中的券，不传递客户端金额或账号', async () => {
    const request = { requestId: 'stable-request', itemId: 'item', skuId: 'sku', quantity: 1, couponId: 'coupon' };
    postJson.mockRejectedValueOnce(new Error('连接中断')).mockResolvedValueOnce({ orderId: 1 });
    await expect(createCheckoutOrder(request)).rejects.toThrow('连接中断');
    await expect(createCheckoutOrder(request)).resolves.toEqual({ orderId: 1 });
    expect(postJson.mock.calls).toEqual([['/checkout/orders', request], ['/checkout/orders', request]]);
    expect(request).not.toHaveProperty('unitPrice');
    expect(request).not.toHaveProperty('accountId');
  });
  it('领取编码后的活动使用调用者保留的幂等键', async () => {
    await claimCoupon('campaign/one', 'claim-request');
    expect(postJson).toHaveBeenCalledWith('/promotions/campaigns/campaign%2Fone/claim', { requestId: 'claim-request' });
  });
  it('取消和模拟支付操作明确区分', async () => {
    await cancelCheckoutOrder(123);
    await mockPayCheckoutOrder(123);
    expect(postJson.mock.calls).toEqual([['/checkout/orders/123/cancel', {}], ['/checkout/orders/123/mock-pay', { scenario: 'SUCCESS' }]]);
  });
  it('响应丢失场景的重试仍针对同一订单', async () => {
    postJson.mockRejectedValueOnce(new Error('504')).mockResolvedValueOnce({ orderId: 123, status: 'PAID' });
    await expect(mockPayCheckoutOrder(123, 'RESPONSE_LOST')).rejects.toThrow('504');
    await expect(mockPayCheckoutOrder(123, 'RESPONSE_LOST')).resolves.toMatchObject({ status: 'PAID' });
    expect(postJson.mock.calls).toEqual(Array(2).fill(['/checkout/orders/123/mock-pay', { scenario: 'RESPONSE_LOST' }]));
  });
  it('SKU 查询编码商品标识', async () => {
    await listOffers('item&other');
    expect(getJson).toHaveBeenCalledWith('/checkout/offers?itemId=item%26other');
  });
  it('秒杀重试沿用同一请求，不传递客户端金额和账号', async () => {
    const request = { requestId: 'stable', itemId: 'item', skuId: 'sku', quantity: 1 as const };
    postJson.mockRejectedValueOnce(new Error('响应丢失')).mockResolvedValueOnce({ requestId: 'stable', status: 'PROCESSING' });
    await expect(submitSeckill('activity/one', request)).rejects.toThrow('响应丢失');
    await submitSeckill('activity/one', request);
    expect(postJson.mock.calls).toEqual(Array(2).fill(['/seckill/activities/activity%2Fone/submit', request]));
    await listSeckillActivities('item&one'); await getSeckillResult('req/one');
    expect(getJson.mock.calls).toEqual([['/seckill/activities?itemId=item%26one'], ['/seckill/requests/req%2Fone']]);
    expect(request).not.toHaveProperty('unitPrice'); expect(request).not.toHaveProperty('accountId');
  });
});
