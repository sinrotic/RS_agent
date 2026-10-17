import { useEffect, useRef, useState } from 'react';
import { ApiError, createRequestId, commerceStorageKey } from '../api/shared';
import { listSeckillActivities, getSeckillActivity, getSeckillResult, submitSeckill } from '../api/commerceClient';
import type { SeckillActivity, SeckillRequest, SeckillResult } from '../api/commerceClient';
import { seckillTerminal, seckillRejected, seckillTiming, seckillStatusLabel } from '../utils/seckillState';
import { recoverPendingActivities, seckillPollDelay } from '../utils/seckillRecovery';

const money = (cents: number) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'USD' }).format(cents / 100);
const countdown = (seconds: number) => `${Math.floor(seconds / 3600)}时${Math.floor(seconds % 3600 / 60)}分${seconds % 60}秒`;

export function SeckillPanel({ itemId, onOpenOrder }: { itemId: string; onOpenOrder: (orderId: number) => Promise<void> }) {
  const storageKey = commerceStorageKey('seckill', itemId);
  const requests = useRef<Record<string, SeckillRequest>>({});
  const [activities, setActivities] = useState<SeckillActivity[]>([]);
  const [results, setResults] = useState<Record<string, SeckillResult>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());
  const serverOffset = useRef(0);
  const busyRef = useRef(false);

  const persist = () => {
    try {
      if (storageKey && storageKey === commerceStorageKey('seckill', itemId)) sessionStorage.setItem(storageKey, JSON.stringify(requests.current));
    } catch { /* 页面仍保留请求键。 */ }
  };

  useEffect(() => {
    let active = true, fetching = false, failures = 0, timer: number | undefined;
    let latest: SeckillActivity[] = [];
    try {
      const saved = JSON.parse(storageKey ? sessionStorage.getItem(storageKey) || '{}' : '{}');
      requests.current = Object.fromEntries(Object.entries(saved).filter(([, value]) => {
        const r = value as SeckillRequest;
        return r?.itemId === itemId && typeof r.requestId === 'string' && typeof r.skuId === 'string' && r.quantity === 1;
      })) as Record<string, SeckillRequest>;
    } catch { requests.current = {}; }
    const refresh = async () => {
      if (fetching || !active) return;
      if (document.hidden) { timer = window.setTimeout(() => { void refresh(); }, 15000); return; }
      fetching = true;
      try {
        const listed = await listSeckillActivities(itemId);
        if (!active) return;
        const current = await recoverPendingActivities(listed, requests.current, getSeckillActivity, itemId);
        if (!active) return;
        latest = current; failures = 0; setError('');
        if (current[0]) serverOffset.current = Date.parse(current[0].serverTime) - Date.now();
        setActivities(previous => [...current, ...previous.filter(old => !current.some(a => a.activityId === old.activityId)
          && requests.current[old.activityId])]);
        const found: Record<string, SeckillResult> = {};
        for (const activity of current) {
          if (!activity.participation) continue;
          const result = activity.participation;
          found[activity.activityId] = result;
          if (seckillTerminal(result.status)) delete requests.current[activity.activityId];
          else requests.current[activity.activityId] = { requestId: result.requestId, itemId, skuId: activity.skuId, quantity: 1 };
        }
        const checked = await Promise.allSettled(Object.entries(requests.current)
          .filter(([id, request]) => found[id]?.requestId !== request.requestId).map(async ([id, request]) => {
          // 恢复网络结果未知的请求；404 时保留同一键，只有用户点击才重新提交。
          const result = await getSeckillResult(request.requestId);
          return { id, result };
        }));
        if (!active) return;
        for (const entry of checked) {
          if (entry.status === 'fulfilled') {
            found[entry.value.id] = entry.value.result;
            if (seckillTerminal(entry.value.result.status)) delete requests.current[entry.value.id];
          }
        }
        setResults(previous => ({ ...previous, ...found }));
        persist();
      } catch { failures++; if (active) setError('秒杀服务暂不可用，已提交的请求会保留，请稍后刷新。'); }
      finally {
        fetching = false;
        if (active) {
          setLoading(false);
          timer = window.setTimeout(() => { void refresh(); }, seckillPollDelay(latest, Object.keys(requests.current).length > 0, failures));
        }
      }
    };
    void refresh();
    const visible = () => {
      if (!document.hidden && !fetching) { window.clearTimeout(timer); void refresh(); }
    };
    document.addEventListener('visibilitychange', visible);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { active = false; window.clearTimeout(timer); window.clearInterval(clock); document.removeEventListener('visibilitychange', visible); };
  }, [itemId]);

  const participate = async (activity: SeckillActivity) => {
    if (!storageKey || storageKey !== commerceStorageKey('seckill', itemId)) {
      setError('账号状态已变化，请重新打开商品。'); return;
    }
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError('');
    const request = requests.current[activity.activityId] || {
      requestId: createRequestId(), itemId, skuId: activity.skuId, quantity: 1 as const,
    };
    requests.current[activity.activityId] = request; persist();
    try {
      const result = await submitSeckill(activity.activityId, request);
      setResults(current => ({ ...current, [activity.activityId]: result }));
      if (seckillRejected(result.status) || seckillTerminal(result.status)) delete requests.current[activity.activityId];
      else requests.current[activity.activityId] = { ...request, requestId: result.requestId };
      persist();
    } catch (failure) {
      if (failure instanceof ApiError && [400, 404, 409].includes(failure.status)) {
        delete requests.current[activity.activityId]; persist();
        setError('活动或请求参数已变化，请刷新活动后重试。');
      } else setError('尚未确认抢购结果，请稍候查询或使用原请求重试。');
    } finally { busyRef.current = false; setBusy(false); }
  };

  return <section className="space-y-3 border-t border-slate-700 pt-4" aria-label="限量秒杀">
    <h3 className="font-semibold text-slate-100">限量秒杀</h3>
    <p className="text-xs text-slate-400">每账号每活动限购一件。当前秒杀价不叠加优惠券；受理后等待订单确认。</p>
    {error && <p role="alert" className="text-sm text-amber-200">{error}</p>}
    {loading ? <p className="text-sm text-slate-400">正在查询活动...</p>
      : !activities.length && !error && <p className="text-sm text-slate-400">当前暂无秒杀活动。</p>}
    {activities.map(activity => {
      const timing = seckillTiming(activity, now + serverOffset.current);
      const result = results[activity.activityId] || activity.participation;
      const accepted = !!result && !seckillRejected(result.status);
      const unknown = !!requests.current[activity.activityId] && !accepted;
      const disabled = busy || accepted || (!unknown && timing.status !== 'ACTIVE');
      return <div key={activity.activityId} className="space-y-2 rounded-lg bg-slate-800/50 p-3 text-sm">
        <p className="text-slate-200">{activity.itemTitle} · 秒杀价 {money(activity.unitPrice)}</p>
        <p className="text-slate-400">剩余名额 {activity.remainingQuantity} / {activity.totalQuantity} · {
          timing.status === 'NOT_STARTED' ? `距开始 ${countdown(timing.seconds)}` : timing.status === 'ENDED' ? '已结束'
            : timing.status === 'SOLD_OUT' ? '已售罄' : `距结束 ${countdown(timing.seconds)}`}</p>
        {['PREPARING', 'UNAVAILABLE'].includes(timing.status) && <p className="text-amber-200">{
          timing.status === 'PREPARING' ? '活动库存准备中' : '活动暂不可用，请稍后查看'}</p>}
        {result && <p role="status" className="text-indigo-200">{seckillStatusLabel[result.status] || '正在查询结果'}</p>}
        {unknown && <p className="text-xs text-amber-200">结果尚未确认，重试会沿用原请求。</p>}
        <div className="flex gap-2">
          <button className="rounded-lg border border-indigo-400/30 px-3 py-2 text-indigo-200 disabled:opacity-40"
            disabled={disabled} onClick={() => { void participate(activity); }}>
            {unknown ? '重试原抢购请求' : accepted ? '已参与' : '立即抢购'}
          </button>
          {result?.orderId && <button className="rounded-lg border border-slate-500 px-3 py-2 text-slate-200" disabled={busy}
            onClick={() => { void onOpenOrder(result.orderId!).catch(() => setError('订单暂时无法打开，请稍后重试。')); }}>查看订单</button>}
        </div>
      </div>;
    })}
  </section>;
}
