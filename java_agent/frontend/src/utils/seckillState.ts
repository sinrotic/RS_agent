import type { SeckillActivity } from '../api/commerceClient';

export const seckillTerminal = (status: string) => ['PAID', 'FAILED', 'CANCELED', 'TIMEOUT_CLOSED'].includes(status);
export const seckillRejected = (status: string) => ['STOCK_NOT_ENOUGH', 'NOT_STARTED', 'ENDED'].includes(status);
export const seckillStatusLabel: Record<string, string> = {
  PROCESSING: '已受理，正在生成订单', CREATING: '正在确认库存', WAITING_PAYMENT: '订单已生成，待支付',
  PAID: '已支付', FAILED: '订单创建失败', CANCELED: '已取消，资源已释放', TIMEOUT_CLOSED: '超时关闭，资源已释放',
  DUPLICATE: '已参与，正在查询原请求', REVIEW_REQUIRED: '处理时间较长，后台正在核对',
  STOCK_NOT_ENOUGH: '本次未受理，活动已售罄', NOT_STARTED: '活动尚未开始', ENDED: '活动已结束',
};
export function seckillTiming(activity: SeckillActivity, serverNow: number) {
  const start = Date.parse(activity.startsAt), end = Date.parse(activity.endsAt);
  const status = serverNow >= end ? 'ENDED' : ['PREPARING', 'UNAVAILABLE'].includes(activity.status) ? activity.status : serverNow < start ? 'NOT_STARTED'
    : activity.remainingQuantity <= 0 ? 'SOLD_OUT' : 'ACTIVE';
  const seconds = Math.max(0, Math.ceil(((status === 'NOT_STARTED' ? start : end) - serverNow) / 1000));
  return { status, seconds };
}
