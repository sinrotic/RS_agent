import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError, createRequestId, isMockMode, commerceStorageKey, getAccountId, subscribeAccount } from '../api/shared';
import { SeckillPanel } from './SeckillPanel';
import {
  Campaign, Coupon, Offer, CheckoutOrder, CheckoutRequest, MockPaymentScenario, listOffers, listCampaigns, listCoupons,
  claimCoupon, listCheckoutOrders, createCheckoutOrder, cancelCheckoutOrder, mockPayCheckoutOrder, checkoutCapabilities, getCheckoutOrder,
} from '../api/commerceClient';

const money = (cents: number) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'USD' }).format(cents / 100);
const statusLabel: Record<string, string> = {
  CREATING: '正在确认库存和优惠', WAITING_PAYMENT: '待支付', PAID: '已支付',
  CANCELED: '已取消', TIMEOUT_CLOSED: '超时关闭', CREATION_FAILED: '创建失败',
};
const complete = (order: CheckoutOrder) => ['DONE', 'FAILED'].includes(order.phase);

type CheckoutPanelProps = { itemId: string; sessionId?: string; recommendRequestId?: string };
export function CheckoutPanel(props: CheckoutPanelProps) {
  const accountId = useSyncExternalStore(subscribeAccount, getAccountId, () => null);
  if (!accountId) return <p className="text-sm text-slate-400">请登录后查看优惠券与交易功能。</p>;
  return <AccountCheckoutPanel key={JSON.stringify([accountId, props.itemId])} {...props} />;
}

function AccountCheckoutPanel({ itemId, sessionId, recommendRequestId }: CheckoutPanelProps) {
  const storageKey = commerceStorageKey('checkout', itemId);
  const [pending, setPending] = useState<CheckoutRequest | null>(() => {
    try {
      const value = JSON.parse(storageKey ? sessionStorage.getItem(storageKey) || 'null' : 'null');
      return value?.itemId === itemId && typeof value?.requestId === 'string' ? value : null;
    } catch { return null; }
  });
  const [offers, setOffers] = useState<Offer[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [orders, setOrders] = useState<CheckoutOrder[]>([]);
  const [skuId, setSkuId] = useState(pending?.skuId || '');
  const [quantity, setQuantity] = useState(pending?.quantity || 1);
  const [couponId, setCouponId] = useState(pending?.couponId || '');
  const [mockPaymentEnabled, setMockPaymentEnabled] = useState(false);
  const [mockScenario, setMockScenario] = useState<MockPaymentScenario>('SUCCESS');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const busyRef = useRef(false);
  const claimRequests = useRef(new Map<string, string>());
  const mounted = useRef(true);

  const reloadOrders = async () => {
    const [current, wallet] = await Promise.all([listCheckoutOrders(), listCoupons()]);
    if (mounted.current) {
      setOrders(current.filter(order => order.itemId === itemId));
      setCoupons(wallet);
    }
  };

  useEffect(() => {
    mounted.current = true;
    if (isMockMode()) { setLoading(false); return () => { mounted.current = false; }; }
    Promise.all([listOffers(itemId), listCampaigns(itemId), listCoupons(), listCheckoutOrders(), checkoutCapabilities()])
      .then(([items, activities, wallet, current, capabilities]) => {
        if (!mounted.current) return;
        setOffers(items); setCampaigns(activities); setCoupons(wallet);
        setOrders(current.filter(order => order.itemId === itemId));
        setSkuId(value => value || items[0]?.skuId || '');
        setMockPaymentEnabled(capabilities.mockPaymentEnabled);
      })
      .catch(() => mounted.current && setError('交易服务暂不可用，请稍后重新打开商品详情。'))
      .finally(() => mounted.current && setLoading(false));
    return () => { mounted.current = false; };
  }, [itemId]);

  const needsPolling = orders.some(order => !complete(order));
  useEffect(() => {
    if (!needsPolling) return;
    let fetching = false;
    const timer = window.setInterval(() => {
      if (fetching || document.hidden) return;
      fetching = true;
      reloadOrders().catch(() => {
        if (mounted.current) setError('订单状态暂时无法刷新，系统会继续处理，请勿重复下单。');
      }).finally(() => { fetching = false; });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [needsPolling, itemId]);

  const act = async (operation: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError('');
    try { await operation(); }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '操作未完成，请重试'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };

  const submit = () => act(async () => {
    if (!storageKey || storageKey !== commerceStorageKey('checkout', itemId)) throw new Error('账号状态已变化，请重新打开商品。');
    const request = pending || { requestId: createRequestId(), itemId, skuId, quantity, couponId: couponId || null,
      sessionId: sessionId || null, recommendRequestId: recommendRequestId || null };
    sessionStorage.setItem(storageKey, JSON.stringify(request));
    setPending(request);
    // 网络失败保留同一请求及参数；重试不会生成第二张订单。
    let order: CheckoutOrder;
    try { order = await createCheckoutOrder(request); }
    catch (failure) {
      if (failure instanceof ApiError && [400, 404, 409].includes(failure.status)) {
        if (storageKey === commerceStorageKey('checkout', itemId)) sessionStorage.removeItem(storageKey);
        if (mounted.current) setPending(null);
      }
      throw failure;
    }
    if (storageKey === commerceStorageKey('checkout', itemId)) sessionStorage.removeItem(storageKey);
    if (!mounted.current) return;
    setPending(null);
    setOrders(current => [order, ...current.filter(value => value.orderId !== order.orderId)]);
    await reloadOrders();
  });

  if (isMockMode()) return <p className="text-sm text-slate-400">登录真实账户后可查看优惠券与交易功能。</p>;
  if (loading) return <p className="text-sm text-slate-400">正在查询可购规格和优惠...</p>;
  const offer = offers.find(value => value.skuId === skuId);
  const amount = (offer?.unitPrice || 0) * quantity;
  const available = coupons.filter(coupon => coupon.status === 'AVAILABLE' &&
    (!coupon.itemId || coupon.itemId === itemId) && amount >= coupon.minimumAmount);
  const button = 'rounded-lg border border-indigo-400/30 px-3 py-2 text-sm text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-40';
  const selectedCoupon = available.find(coupon => coupon.couponId === couponId);

  return <section className="space-y-4 rounded-xl border border-indigo-500/20 bg-slate-900/60 p-4" aria-label="优惠与下单">
    <h2 className="font-semibold text-slate-100">优惠与下单</h2>
    {mockPaymentEnabled && <label className="block text-sm text-amber-200">模拟支付场景（不扣款）
      <select className="ml-2 rounded bg-slate-800 p-2" value={mockScenario} disabled={busy}
        onChange={event => setMockScenario(event.target.value as MockPaymentScenario)}>
        <option value="SUCCESS">支付成功</option>
        <option value="DECLINED">支付被拒</option>
        <option value="TIMEOUT_BEFORE_PAYMENT">支付前超时</option>
        <option value="RESPONSE_LOST">支付成功但响应丢失</option>
      </select>
    </label>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {campaigns.map(campaign => {
      const owned = coupons.some(coupon => coupon.campaignId === campaign.campaignId);
      return <div key={campaign.campaignId} className="flex items-center justify-between gap-3 text-sm">
        <span className="text-slate-300">{campaign.title} · 满 {money(campaign.minimumAmount)} 减 {money(campaign.discountAmount)}</span>
        <button className={button} disabled={busy || owned || campaign.remainingQuantity <= 0} onClick={() => act(async () => {
          let requestId = claimRequests.current.get(campaign.campaignId);
          if (!requestId) { requestId = createRequestId(); claimRequests.current.set(campaign.campaignId, requestId); }
          await claimCoupon(campaign.campaignId, requestId);
          await reloadOrders();
        })}>{owned ? '已领取' : campaign.remainingQuantity <= 0 ? '已领完' : '领取'}</button>
      </div>;
    })}
    {!campaigns.length && <p className="text-sm text-slate-400">当前暂无可领取的优惠券。</p>}
    {offers.length > 0 ? <>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-300">规格
          <select aria-label="购买规格" className="ml-2 rounded bg-slate-800 p-2" value={skuId} disabled={busy || !!pending}
            onChange={event => { setSkuId(event.target.value); setCouponId(''); }}>
            {offers.map(value => <option key={value.skuId} value={value.skuId}>{value.itemTitle} · {money(value.unitPrice)}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-300">数量
          <input aria-label="购买数量" className="ml-2 w-20 rounded bg-slate-800 p-2" type="number" min={1} max={99}
            value={quantity} disabled={busy || !!pending} onChange={event => {
              setQuantity(Math.max(1, Math.min(99, Number(event.target.value) || 1))); setCouponId('');
            }} />
        </label>
      </div>
      <label className="block text-sm text-slate-300">使用优惠券
        <select className="ml-2 rounded bg-slate-800 p-2" value={couponId} disabled={busy || !!pending} onChange={event => setCouponId(event.target.value)}>
          <option value="">不使用优惠券</option>
          {available.map(coupon => <option value={coupon.couponId} key={coupon.couponId}>{coupon.title} · 减 {money(coupon.discountAmount)}</option>)}
          {pending?.couponId && !available.some(c => c.couponId === pending.couponId) &&
            <option value={pending.couponId}>原订单优惠券</option>}
        </select>
      </label>
      <p className="text-sm text-slate-300">预计商品金额 {money(amount)}
        {selectedCoupon && `，优惠 ${money(selectedCoupon.discountAmount)}`}。实际应付以订单确认为准。</p>
      <button className={button} disabled={busy || !offer} onClick={submit}>
        {busy ? '处理中...' : pending ? '重试原订单提交' : '提交订单'}
      </button>
      {pending && <p className="text-xs text-amber-200">提交结果尚未确认。重试将查询或继续原订单，商品和优惠选择已暂时固定。</p>}
    </> : <p className="text-sm text-slate-400">该商品暂未开放下单。</p>}
    <SeckillPanel key={itemId} itemId={itemId} onOpenOrder={async orderId => {
      const order = await getCheckoutOrder(orderId);
      if (!mounted.current) return;
      setOrders(current => [order, ...current.filter(value => value.orderId !== orderId)]);
      window.setTimeout(() => document.getElementById(`checkout-order-${orderId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0);
    }} />
    {orders.length > 0 && <div className="space-y-3 border-t border-slate-700 pt-4">
      <h3 className="text-sm font-semibold text-slate-200">该商品的近期订单</h3>
      {orders.map(order => <div id={`checkout-order-${order.orderId}`} key={order.orderId} className="space-y-2 rounded-lg bg-slate-800/50 p-3 text-sm">
        <p className="text-slate-300">订单 {order.orderId} · {statusLabel[order.status] || '处理中'}</p>
        <p className="text-slate-300">数量 {order.quantity} · 应付 {money(order.totalAmount)} · 优惠 {money(order.discountAmount)}</p>
        {order.phase.startsWith('REVIEW_') ? <p className="text-xs text-amber-200">库存或优惠处理需要人工核对，订单状态已保留。</p>
          : !complete(order) && order.phase !== 'READY' && <p className="text-xs text-amber-200">正在完成库存与优惠处理，请稍候。</p>}
        {order.failureReason && <p className="text-xs text-amber-200">{order.failureReason}</p>}
        {(order.status === 'WAITING_PAYMENT' || order.status === 'CREATING') && <div className="flex gap-2">
          {order.status === 'WAITING_PAYMENT' && mockPaymentEnabled && <button disabled={busy} className={button} onClick={() => act(async () => {
            try { await mockPayCheckoutOrder(order.orderId, mockScenario); }
            catch (reason) {
              // 失败响应不代表未支付；主动回查，后台轮询也会继续恢复。
              await reloadOrders().catch(() => {});
              throw new Error(reason instanceof ApiError && reason.status === 402
                ? '模拟支付被拒，可切换成功场景重试或取消订单。'
                : '支付响应未确认，已尝试刷新原订单，请以订单状态为准。');
            }
            await reloadOrders();
          })}>模拟支付（不扣款）</button>}
          <button disabled={busy} className={button} onClick={() => act(async () => {
            await cancelCheckoutOrder(order.orderId); await reloadOrders();
          })}>取消订单</button>
          {order.status === 'WAITING_PAYMENT' && !mockPaymentEnabled && <span className="self-center text-xs text-slate-400">等待支付确认，超时自动关闭</span>}
        </div>}
      </div>)}
    </div>}
  </section>;
}
