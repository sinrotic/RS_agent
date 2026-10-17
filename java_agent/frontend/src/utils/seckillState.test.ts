import { describe, it, expect } from 'vitest';
import { seckillTiming, seckillTerminal, seckillRejected } from './seckillState';
import type { SeckillActivity } from '../api/commerceClient';
const activity: SeckillActivity = {
  activityId: 'activity', itemId: 'item', skuId: 'sku', itemTitle: '测试', unitPrice: 3000, totalQuantity: 5,
  remainingQuantity: 5, startsAt: '2026-10-10T00:00:00Z', endsAt: '2026-10-10T01:00:00Z',
  serverTime: '2026-10-10T00:00:00Z', status: 'ACTIVE', participation: null,
};
describe('秒杀状态', () => {
  it('使用服务端时钟，在开始和结束边界禁用抢购', () => {
    expect(seckillTiming(activity, Date.parse(activity.startsAt) - 1000)).toEqual({ status: 'NOT_STARTED', seconds: 1 });
    expect(seckillTiming(activity, Date.parse(activity.startsAt)).status).toBe('ACTIVE');
    expect(seckillTiming(activity, Date.parse(activity.endsAt)).status).toBe('ENDED');
    expect(seckillTiming({ ...activity, remainingQuantity: 0 }, Date.parse(activity.startsAt)).status).toBe('SOLD_OUT');
  });
  it('受理和待核对均不视为支付完成；入口拒绝可以重新参与', () => {
    expect(seckillTerminal('PROCESSING')).toBe(false); expect(seckillTerminal('REVIEW_REQUIRED')).toBe(false);
    expect(seckillTerminal('PAID')).toBe(true); expect(seckillTerminal('CANCELED')).toBe(true);
    expect(seckillRejected('NOT_STARTED')).toBe(true); expect(seckillRejected('STOCK_NOT_ENOUGH')).toBe(true);
    expect(seckillRejected('PROCESSING')).toBe(false);
  });
});
