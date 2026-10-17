import { describe, it, expect } from 'vitest';
import { recoverPendingActivities, seckillPollDelay } from './seckillRecovery';
import { seckillTiming } from './seckillState';
import type { SeckillActivity } from '../api/commerceClient';
const old: SeckillActivity = { activityId: 'old', itemId: 'item', skuId: 'sku', itemTitle: '旧活动', unitPrice: 3000,
  totalQuantity: 5, remainingQuantity: 4, startsAt: '2026-10-01T00:00:00Z', endsAt: '2026-10-01T01:00:00Z',
  serverTime: '2026-10-11T00:00:00Z', status: 'ENDED', participation: { requestId: 'original', status: 'REVIEW_REQUIRED', orderId: null } };
describe('秒杀请求恢复与轮询', () => {
  it('列表不再包含活动时仍根据原请求恢复卡片，且不重新提交', async () => {
    const ids: string[] = [];
    const result = await recoverPendingActivities([], { old: { requestId: 'original', itemId: 'item', skuId: 'sku', quantity: 1 } },
      async id => { ids.push(id); return old; }, 'item');
    expect(ids).toEqual(['old']); expect(result[0].participation?.requestId).toBe('original');
  });
  it('部分详情失败不阻止其他恢复，也不展示其他商品的活动', async () => {
    const request = { requestId: 'original', itemId: 'item', skuId: 'sku', quantity: 1 as const };
    const result = await recoverPendingActivities([old], { old: request, missing: request, other: request }, async id => {
      if (id === 'missing') throw new Error('不可用'); return { ...old, activityId: id, itemId: 'other' };
    }, 'item');
    expect(result).toEqual([old]);
  });
  it('未完成请求及时查询，结束活动及故障采用较长间隔', () => {
    expect(seckillPollDelay([old], true, 0)).toBe(5000); expect(seckillPollDelay([old], false, 0)).toBe(60000);
    expect(seckillPollDelay([], true, 4)).toBe(60000);
    expect(seckillTiming({ ...old, status: 'PREPARING', endsAt: '2026-10-12T00:00:00Z' }, Date.parse(old.serverTime)).status).toBe('PREPARING');
  });
});
