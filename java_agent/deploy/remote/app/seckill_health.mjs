// 从可信内部网络运行；可接现有定时巡检，以退出码 2 表示需要处理。
const base = (process.env.RS_SECKILL_INTERNAL_URL || 'http://127.0.0.1:18094').replace(/\/$/, '');
const orderBase = (process.env.RS_ORDER_INTERNAL_URL || 'http://127.0.0.1:18091').replace(/\/$/, '');
const paymentBase = (process.env.RS_PAYMENT_INTERNAL_URL || 'http://127.0.0.1:18093').replace(/\/$/, '');
const inventoryBase = (process.env.RS_INVENTORY_INTERNAL_URL || 'http://127.0.0.1:18092').replace(/\/$/, '');
const threshold = Number(process.env.RS_SECKILL_STALLED_SECONDS || 1200);
if (!Number.isInteger(threshold) || threshold < 0 || threshold > 2592000) throw new Error('待办年龄参数不合法');
async function read(host, path) {
  const token = process.env.RS_COMMERCE_OPS_READ_TOKEN || process.env.RS_COMMERCE_OPS_WRITE_TOKEN;
  const response = await fetch(host + path, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error(`交易巡检接口 ${path} 返回 ${response.status}`);
  return response.json();
}
const [summary, stalled, checkoutSummary, checkoutStalled, paymentSummary, paymentStalled,refunds,events,inventoryCases] = await Promise.all([
  read(base, '/internal/seckill/tasks/summary'), read(base, `/internal/seckill/tasks?minimumAgeSeconds=${threshold}`),
  read(orderBase, '/internal/checkout/tasks/summary'), read(orderBase, `/internal/checkout/tasks?minimumAgeSeconds=${threshold}`),
  read(paymentBase, '/internal/payment/notifications/summary'), read(paymentBase, `/internal/payment/notifications?minimumAgeSeconds=${threshold}`),
  read(orderBase,'/internal/checkout/refunds'),read(orderBase,'/internal/checkout/events'),read(inventoryBase,'/internal/inventory/management/reconciliations'),
]);
const safeTasks = tasks => tasks.map(task => ({ orderId: task.orderId||task.order_id, activityId: task.activityId,
  refundId:task.refund_id,eventId:task.eventId||task.event_id,target:task.target,
  status: task.status, phase: task.phase, attempts: task.attempts, lastError: task.lastError||task.last_error }));
const needsAttention=tasks=>tasks.filter(task=>{
  if(task.status==='REVIEW_REQUIRED')return true;
  const raw=task.created_at;if(typeof raw!=='string')return true;
  const time=Date.parse(/[Zz]|[+-]\d\d:\d\d$/.test(raw)?raw:raw+'Z');
  return !Number.isFinite(time)||Date.now()-time>=threshold*1000;
});
const refundAttention=needsAttention(refunds),eventAttention=needsAttention(events);
console.log(JSON.stringify({ summary, stalled: safeTasks(stalled), checkout: { summary: checkoutSummary, stalled: safeTasks(checkoutStalled) },
  payment: { summary: paymentSummary, stalled: safeTasks(paymentStalled) },refunds:safeTasks(refundAttention),events:safeTasks(eventAttention),inventoryDifferences:inventoryCases.length }));
if ([summary, checkoutSummary, paymentSummary].some(value => value.reviewRequired > 0)
    || [stalled, checkoutStalled, paymentStalled,refundAttention,eventAttention,inventoryCases].some(value => value.length > 0)) process.exitCode = 2;
