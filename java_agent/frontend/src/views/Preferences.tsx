import { useEffect, useState } from 'react';
import { getPreferences, removePreferenceCompletely, clearPreferencesCompletely, reverseFeedback, waitForFeedbackApplied } from '../api/interactionClient';
import { fetchCatalogItems } from '../api/catalogClient';
import { RecommendPreferencesVO } from '../types/interaction';

export function Preferences() {
  const [preferences, setPreferences] = useState<RecommendPreferencesVO>({ preference_version: 0, items: [] });
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [confirmClear, setConfirmClear] = useState(false);

  const reload = async () => {
    const value = await getPreferences();
    setPreferences(value);
    const ids = value.items.slice(0, 100).map(item => item.item_id);
    if (ids.length) {
      try {
        const catalog = await fetchCatalogItems(ids);
        setTitles(Object.fromEntries(catalog.map(item => [item.itemId, item.title || item.itemId])));
      } catch { setTitles({}); }
    }
    return value;
  };

  const mutate = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true); setConfirmClear(false);
    try { await action(); await reload(); setStatus(message); }
    catch (error) {
      try { await reload(); } catch { /* 保留原操作错误，刷新失败不覆盖它。 */ }
      setStatus(error instanceof Error ? error.message : '偏好暂时无法更新，请重试。');
    }
    finally { setBusy(false); }
  };

  useEffect(() => { void mutate(async () => undefined, ''); }, []);

  const remove = (itemId: string, eventId?: string) => mutate(async () => {
    if (!eventId) { await removePreferenceCompletely(itemId); return; }
    let ack = await reverseFeedback(eventId);
    if (!ack.accepted) throw new Error('偏好修改未被接受，请刷新后重试。');
    if (ack.application_status === 'PENDING') ack = await waitForFeedbackApplied(ack.feedback_id);
    if (ack.application_status === 'PENDING') throw new Error('修改已保存，在线偏好正在同步，请稍后刷新。');
  }, eventId ? '最近一次反馈已撤销，之前的偏好可能恢复。' : '此商品的偏好已删除。');

  return <section className="mx-auto w-full max-w-4xl space-y-5 overflow-y-auto text-left text-slate-100">
    <div className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
      <h1 className="text-2xl font-bold">我的推荐偏好</h1>
      <p className="mt-2 text-sm text-slate-400">查看喜欢和不感兴趣的商品。撤销最近一次反馈会恢复此前状态；删除商品偏好会清除该商品的明确偏好。</p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button disabled={busy} onClick={() => void mutate(async () => undefined, '偏好已刷新。')} className="rounded-lg border border-indigo-400/40 px-3 py-2 text-sm">刷新</button>
        <button disabled={busy || !preferences.items.length} onClick={() => setConfirmClear(true)} className="rounded-lg border border-rose-400/40 px-3 py-2 text-sm">清空偏好</button>
      </div>
      {confirmClear && <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-rose-500/10 p-3 text-sm">
        <span>清空当前账号的全部明确商品偏好？</span>
        <button disabled={busy} onClick={() => void mutate(async () => {
          await clearPreferencesCompletely();
        }, '推荐偏好已清空。')} className="rounded border border-rose-400/40 px-3 py-1">确认清空</button>
        <button onClick={() => setConfirmClear(false)}>取消</button>
      </div>}
      <p role="status" className="mt-3 text-sm text-amber-200">{busy ? '正在同步偏好...' : status}</p>
    </div>
    {!busy && !preferences.items.length && <p className="p-6 text-sm text-slate-400">暂无明确商品偏好，可以在推荐页面点击喜欢或不感兴趣。</p>}
    {preferences.items.map(item => <article key={item.item_id} className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <p className="font-semibold">{titles[item.item_id] || item.item_id}</p>
      <p className="mt-1 text-sm text-slate-400">{item.state === 'like' ? '喜欢' : '不感兴趣'}{item.category ? ` · ${item.category}` : ''}{item.brand ? ` · ${item.brand}` : ''}</p>
      <div className="mt-3 flex gap-3 text-sm">
        <button disabled={busy} onClick={() => void remove(item.item_id, item.feedback_event_id)} className="rounded-lg border border-indigo-400/40 px-3 py-2">撤销最近反馈</button>
        <button disabled={busy} onClick={() => void remove(item.item_id)} className="rounded-lg border border-slate-600 px-3 py-2">删除商品偏好</button>
      </div>
    </article>)}
  </section>;
}
