import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError, commerceStorageKey, createRequestId, getAccountId, subscribeAccount } from '../api/shared';
import { listOrderPage, listCouponPage, getCheckoutOrder, getOrderRefund, requestOrderRefund, mockPayCheckoutOrder,
  cancelCheckoutOrder, checkoutCapabilities } from '../api/commerceClient';
import type { CheckoutOrder, Coupon, Refund, RefundRequest, MockPaymentScenario } from '../api/commerceClient';

const money = (value: number) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'USD' }).format(value / 100);
const labels: Record<string, string> = { CREATING: '确认库存中', WAITING_PAYMENT: '待支付', PAID: '已支付', CANCELED: '已取消', TIMEOUT_CLOSED: '超时关闭', CREATION_FAILED: '创建失败', REFUNDING: '退款处理中', REFUNDED: '已退款', REVIEW_REQUIRED: '待人工核对' };
export function CommerceHistory() {
  const account = useSyncExternalStore(subscribeAccount, getAccountId);
  return account ? <AccountHistory key={account} account={account} /> : <p>请先登录查看订单与券包。</p>;
}
function AccountHistory({ account }: { account: string }) {
  const [orders, setOrders] = useState<CheckoutOrder[]>([]), [coupons, setCoupons] = useState<Coupon[]>([]);
  const [orderCursor, setOrderCursor] = useState<string | null>(null), [couponCursor, setCouponCursor] = useState<string | null>(null);
  const [refunds, setRefunds] = useState<Record<number, Refund>>({}), [pending, setPending] = useState<Record<number, RefundRequest>>({});
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [mockEnabled, setMockEnabled] = useState(false), [reason, setReason] = useState('未发货，申请整单退款');
  const [scenario, setScenario] = useState<MockPaymentScenario>('SUCCESS');
  const active = useRef(true), busyRef = useRef(false);
  const refreshOrder = async (id: number) => {
    const order = await getCheckoutOrder(id);
    if (!active.current) return;
    setOrders(values => values.map(value => value.orderId === id ? order : value));
    try {
      const refund = await getOrderRefund(id);
      if (!active.current) return;
      setRefunds(values => ({ ...values, [id]: refund }));
      setPending(values => { const next = { ...values }; delete next[id]; return next; });
      const key = commerceStorageKey('refund', String(id));
      try { if (getAccountId() === account && key) sessionStorage.removeItem(key); } catch { /* 服务端事实不依赖浏览器存储。 */ }
      if (refund.status === 'REFUNDED') await loadCoupons();
    } catch (failure) { if (!(failure instanceof ApiError && failure.status === 404)) throw failure; }
  };
  const loadOrders = async (cursor?: string) => {
    const page = await listOrderPage(cursor); if (!active.current) return;
    setOrders(values => cursor ? [...values, ...page.items.filter(item => !values.some(old => old.orderId === item.orderId))] : page.items);
    setOrderCursor(page.nextCursor);
    for (const order of page.items) {
      const key = commerceStorageKey('refund', String(order.orderId));
      try {
        const saved = key ? JSON.parse(sessionStorage.getItem(key) || 'null') as RefundRequest | null : null;
        if (saved?.requestId && typeof saved.reason === 'string') setPending(values => ({ ...values, [order.orderId]: saved }));
      } catch { /* 存储不可用时仍查询服务端退款事实。 */ }
    }
    await Promise.allSettled(page.items.filter(order => ['PAID', 'REFUNDING', 'REFUNDED'].includes(order.status)).map(order => refreshOrder(order.orderId)));
  };
  const loadCoupons = async (cursor?: string) => {
    const page = await listCouponPage(cursor); if (!active.current) return;
    setCoupons(values => cursor ? [...values, ...page.items.filter(item => !values.some(old => old.couponId === item.couponId))] : page.items);
    setCouponCursor(page.nextCursor);
  };
  useEffect(() => {
    active.current = true;
    Promise.all([loadOrders(), loadCoupons(), checkoutCapabilities().then(value => { if (active.current) setMockEnabled(value.mockPaymentEnabled); })])
      .catch(() => { if (active.current) setError('订单或券包暂时不可用，请稍后刷新。'); }).finally(() => { if (active.current) setLoading(false); });
    return () => { active.current = false; };
  }, [account]);
  useEffect(() => {
    let refreshing = false;
    const timer = window.setInterval(async () => {
      if (document.hidden || refreshing) return; refreshing = true;
      try { await Promise.allSettled(orders.filter(order => ['CREATING', 'WAITING_PAYMENT', 'REFUNDING'].includes(order.status) || pending[order.orderId]).map(order => refreshOrder(order.orderId))); }
      finally { refreshing = false; }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [orders, pending]);
  const act = async (operation: () => Promise<void>) => {
    if (busyRef.current) return; busyRef.current = true; setBusy(true); setError('');
    try { await operation(); } catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : '操作未确认，请查询原请求后重试。'); }
    finally { busyRef.current = false; if (active.current) setBusy(false); }
  };
  const refund = (order: CheckoutOrder) => act(async () => {
    if (!reason.trim()) throw new Error('请填写退款原因。');
    const request = pending[order.orderId] || { requestId: createRequestId(), reason, scenario };
    setPending(values => ({ ...values, [order.orderId]: request }));
    const key = commerceStorageKey('refund', String(order.orderId));
    try { if (key && getAccountId() === account) sessionStorage.setItem(key, JSON.stringify(request)); } catch { /* 保留内存中的原请求。 */ }
    try { await requestOrderRefund(order.orderId, request); } finally { await refreshOrder(order.orderId); }
    await loadCoupons();
  });
  const button = 'rounded-lg border border-indigo-400/40 px-3 py-2 text-indigo-200 disabled:opacity-40';
  return <main className="mx-auto w-full max-w-5xl space-y-6 overflow-y-auto p-6" aria-label="我的订单与券包">
    <h1 className="text-2xl font-semibold">我的订单与券包</h1>
    <p className="text-sm text-slate-400">支持查询历史记录和未发货订单整单退款。退款成功后，优惠券按原有效期恢复；秒杀限购资格保留。</p>
    {error && <p role="alert" className="text-amber-200">{error}</p>}
    <button className={button} disabled={busy || loading} onClick={() => act(async () => { await Promise.all([loadOrders(), loadCoupons()]); })}>刷新记录</button>
    <label className="block">退款原因<input aria-label="退款原因" className="ml-3 rounded bg-slate-800 p-2" maxLength={255} value={reason} onChange={event => setReason(event.target.value)} /></label>
    {mockEnabled && <label className="block text-amber-200">模拟退款场景（不发生真实资金变动）<select className="ml-3 rounded bg-slate-800 p-2" value={scenario} onChange={event => setScenario(event.target.value as MockPaymentScenario)}>
      <option value="SUCCESS">成功</option><option value="DECLINED">渠道拒绝</option><option value="TIMEOUT_BEFORE_PAYMENT">处理前超时</option><option value="RESPONSE_LOST">成功后响应丢失</option>
    </select></label>}
    <section className="space-y-3" aria-label="订单记录"><h2 className="text-lg font-semibold">订单记录</h2>
      {loading && <p>正在查询…</p>}{!loading && !orders.length && <p>暂无订单。</p>}
      {orders.map(order => <article key={order.orderId} className="space-y-2 rounded-xl bg-slate-900 p-4">
        <p>{order.itemTitle} · 订单 {order.orderId} · {labels[order.status] || order.status}</p>
        <p>数量 {order.quantity} · 实付 {money(order.totalAmount)} · 优惠 {money(order.discountAmount)}</p>
        {refunds[order.orderId] && <p role="status">退款：{labels[refunds[order.orderId].status] || refunds[order.orderId].status} · {money(refunds[order.orderId].amount)}{refunds[order.orderId].lastError && ' · 后台正在核对'}</p>}
        {order.status === 'PAID' && order.phase === 'DONE' && <button disabled={busy} className={button} onClick={() => refund(order)}>{pending[order.orderId] ? '重试原退款请求' : '申请整单退款'}</button>}
        {['CREATING', 'WAITING_PAYMENT'].includes(order.status) && <button className={button} disabled={busy} onClick={() => act(async () => { await cancelCheckoutOrder(order.orderId); await refreshOrder(order.orderId); })}>取消订单</button>}
        {order.status === 'WAITING_PAYMENT' && mockEnabled && <button className={button} disabled={busy} onClick={() => act(async () => { await mockPayCheckoutOrder(order.orderId); await refreshOrder(order.orderId); })}>模拟支付（不扣款）</button>}
      </article>)}
      {orderCursor && <button className={button} disabled={busy} onClick={() => act(() => loadOrders(orderCursor))}>加载更早订单</button>}
    </section>
    <section className="space-y-3" aria-label="我的券包"><h2 className="text-lg font-semibold">我的券包</h2>
      {!loading && !coupons.length && <p>暂无优惠券。</p>}
      {coupons.map(coupon => <article key={coupon.couponId} className="rounded-xl bg-slate-900 p-4"><p>{coupon.title} · {({ AVAILABLE: '可使用', USED: '已核销', EXPIRED: '已过期', LOCKED: '订单占用中' } as Record<string, string>)[coupon.status] || coupon.status}</p><p>满 {money(coupon.minimumAmount)} 减 {money(coupon.discountAmount)} · 有效期 {new Date(coupon.expiresAt + (coupon.expiresAt.endsWith('Z') ? '' : 'Z')).toLocaleString()}</p></article>)}
      {couponCursor && <button className={button} disabled={busy} onClick={() => act(() => loadCoupons(couponCursor))}>加载更多优惠券</button>}
    </section>
  </main>;
}
