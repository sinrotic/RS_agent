import type { SeckillActivity, SeckillRequest } from '../api/commerceClient';

// 列表会隐藏结束超过一天的活动，保存的未完成请求仍须按 ID 恢复详情。
export async function recoverPendingActivities(current: SeckillActivity[], requests: Record<string, SeckillRequest>,
  read: (id: string) => Promise<SeckillActivity>, itemId: string) {
  const missing = Object.keys(requests).filter(id => !current.some(activity => activity.activityId === id));
  const restored = await Promise.allSettled(missing.map(id => read(id)));
  return [...current, ...restored.flatMap((entry, index) => entry.status === 'fulfilled'
    && entry.value.activityId === missing[index] && entry.value.itemId === itemId ? [entry.value] : [])];
}
export function seckillPollDelay(activities: SeckillActivity[], pending: boolean, failures: number) {
  if (failures) return Math.min(60000, 5000 * 2 ** Math.min(failures, 4));
  if (pending || activities.some(activity => activity.status === 'ACTIVE')) return 5000;
  return activities.some(activity => activity.status === 'NOT_STARTED' || activity.status === 'PREPARING') ? 15000 : 60000;
}
