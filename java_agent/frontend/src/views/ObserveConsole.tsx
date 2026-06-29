import { FormEvent, useState } from 'react';
import { Activity, Database, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { getRecommendTrace, getSessionOverview } from '../api/platformTraceClient';
import { getStoredProfileUserId } from '../api/shared';
import { TracePanel } from '../components/TracePanel';
import { PlatformSessionOverviewVO, RecommendTraceVO } from '../types/platformTrace';

export function ObserveConsole() {
  const storedProfileUserId = getStoredProfileUserId() || 'guest_user';
  const [sessionId, setSessionId] = useState<string>('');
  const [accountId, setAccountId] = useState<string>(storedProfileUserId);
  const [requestId, setRequestId] = useState<string>('');
  const [selectedItemId, setSelectedItemId] = useState<string>('');
  const [overview, setOverview] = useState<PlatformSessionOverviewVO | null>(null);
  const [recommendTrace, setRecommendTrace] = useState<RecommendTraceVO | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  const canQuerySession = Boolean(sessionId.trim());
  const canQueryRecommend = Boolean(requestId.trim());

  const loadOverview = async () => {
    if (!canQuerySession) return;
    setLoading(true);
    setError('');
    try {
      const data = await getSessionOverview(
        sessionId.trim(),
        accountId.trim() || undefined,
        requestId.trim() || undefined,
        accountId.trim() || undefined
      );
      setOverview(data);
      if (data.recommend_traces.length > 0) {
        setRecommendTrace(data.recommend_traces[0]);
      }
    } catch (e: any) {
      setError(e.message || 'Failed to load session overview');
    } finally {
      setLoading(false);
    }
  };

  const loadRecommendTrace = async () => {
    if (!canQueryRecommend) return;
    setLoading(true);
    setError('');
    try {
      const data = await getRecommendTrace(requestId.trim());
      setRecommendTrace(data);
      if (!sessionId && data.session_id) {
        setSessionId(data.session_id);
      }
    } catch (e: any) {
      setError(e.message || 'Failed to load recommend trace');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (canQuerySession) {
      await loadOverview();
      return;
    }
    await loadRecommendTrace();
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-slate-950 text-slate-100 text-left">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-6 lg:px-8">
        <section className="border-b border-slate-800 pb-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-cyan-300">
                <ShieldCheck size={12} />
                Internal Observability Console
              </div>
              <h1 className="text-2xl font-extrabold tracking-tight text-white">平台观测控制台</h1>
              <p className="max-w-2xl text-xs leading-relaxed text-slate-400">
                按 session 或 request 查询用户画像、推荐链路、Agent 多轮交互和候选商品解释。该入口用于内部排查，不在用户商城和对话页展示。
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 text-[10px] font-bold uppercase tracking-wide text-slate-400 sm:grid-cols-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                Profile
                <div className="mt-1 text-sm text-cyan-300">{overview?.account_profile ? 'Loaded' : 'Idle'}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                Recommend
                <div className="mt-1 text-sm text-cyan-300">{recommendTrace?.items.length || 0}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                Turns
                <div className="mt-1 text-sm text-cyan-300">{overview?.agent_trace.turns.length || 0}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                Events
                <div className="mt-1 text-sm text-cyan-300">{overview?.timeline.length || 0}</div>
              </div>
            </div>
          </div>
        </section>

        <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 p-4 lg:grid-cols-[1fr_1fr_1fr_1fr_auto_auto]">
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Session ID</span>
            <input
              value={sessionId}
              onChange={(event) => setSessionId(event.target.value)}
              placeholder="session_xxx"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Account / Profile</span>
            <input
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              placeholder="profile user id"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Request ID</span>
            <input
              value={requestId}
              onChange={(event) => setRequestId(event.target.value)}
              placeholder="recommend request id"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Selected Item</span>
            <input
              value={selectedItemId}
              onChange={(event) => setSelectedItemId(event.target.value)}
              placeholder="optional item id"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>
          <button
            type="submit"
            disabled={loading || (!canQuerySession && !canQueryRecommend)}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-xs font-bold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50 lg:self-end"
          >
            {loading ? <RefreshCw size={14} className="animate-spin" /> : <Search size={14} />}
            查询
          </button>
          <button
            type="button"
            onClick={loadRecommendTrace}
            disabled={loading || !canQueryRecommend}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-4 py-2 text-xs font-bold text-slate-200 transition hover:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-50 lg:self-end"
          >
            <Database size={14} />
            Trace
          </button>
        </form>

        {error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs font-semibold text-rose-200">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
          <TracePanel
            overview={overview}
            loading={loading}
            error={error}
            onRefresh={loadOverview}
            selectedItemId={selectedItemId || undefined}
          />

          <div className="space-y-6">
          <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
              <div className="flex items-center gap-2">
                <Activity size={16} className="text-cyan-300" />
                <div>
                  <div className="text-xs font-bold text-slate-100">会话时间线</div>
                  <div className="text-[10px] text-slate-500">{overview?.timeline.length || 0} 个观测事件</div>
                </div>
              </div>
            </div>
            {!overview || overview.timeline.length === 0 ? (
              <div className="px-4 py-8 text-xs text-slate-500">暂无时间线事件。写入 Agent 事件或用户交互事件后会出现在这里。</div>
            ) : (
              <div className="divide-y divide-slate-800">
                {overview.timeline.map((event) => (
                  <div key={event.event_id} className="grid gap-3 px-4 py-3 text-xs md:grid-cols-[120px_110px_1fr_160px]">
                    <div className="font-mono text-[10px] text-slate-500">{new Date(event.occurred_at).toLocaleString()}</div>
                    <div className="inline-flex w-fit items-center rounded-md border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 text-[10px] font-bold uppercase text-cyan-300">
                      {event.source}
                    </div>
                    <div className="min-w-0">
                      <div className="font-bold text-slate-200">{event.event_type}</div>
                      <div className="mt-1 truncate text-slate-500">{event.summary || event.entity_id || event.request_id}</div>
                    </div>
                    <div className="truncate font-mono text-[10px] text-slate-500">{event.request_id || event.event_id}</div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
              <div className="flex items-center gap-2">
                <Database size={16} className="text-cyan-300" />
                <div>
                  <div className="text-xs font-bold text-slate-100">用户交互事件</div>
                  <div className="text-[10px] text-slate-500">曝光、点击、喜欢、不感兴趣等事件</div>
                </div>
              </div>
            </div>
            {!overview || overview.interaction_events.length === 0 ? (
              <div className="px-4 py-8 text-xs text-slate-500">暂无用户交互事件。</div>
            ) : (
              <div className="overflow-hidden">
                <div className="grid grid-cols-[120px_1fr_110px_90px] border-b border-slate-800 bg-slate-950 px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                  <div>Time</div>
                  <div>Item</div>
                  <div>Type</div>
                  <div>Value</div>
                </div>
                {overview.interaction_events.map((event) => (
                  <button
                    key={event.event_id}
                    type="button"
                    onClick={() => setSelectedItemId(event.item_id)}
                    className="grid w-full grid-cols-[120px_1fr_110px_90px] gap-3 border-b border-slate-800 px-3 py-3 text-left text-xs text-slate-300 transition last:border-b-0 hover:bg-slate-800/60"
                  >
                    <div className="font-mono text-[10px] text-slate-500">{new Date(event.occurred_at).toLocaleTimeString()}</div>
                    <div className="truncate font-mono text-[11px]">{event.item_id || event.request_id}</div>
                    <div className="font-bold text-cyan-300">{event.event_type}</div>
                    <div>{event.event_value ?? '-'}</div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
              <div className="flex items-center gap-2">
                <Activity size={16} className="text-cyan-300" />
                <div>
                  <div className="text-xs font-bold text-slate-100">推荐链路明细</div>
                  <div className="text-[10px] text-slate-500">{recommendTrace?.request_id || '未选择 request'}</div>
                </div>
              </div>
              <button
                type="button"
                onClick={loadRecommendTrace}
                disabled={loading || !canQueryRecommend}
                className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-800 hover:text-cyan-300 disabled:opacity-40"
                title="刷新推荐链路"
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              </button>
            </div>

            {!recommendTrace ? (
              <div className="flex min-h-[360px] items-center justify-center text-xs text-slate-500">
                输入 sessionId 或 requestId 后查看推荐阶段、来源分布和商品解释。
              </div>
            ) : (
              <div className="grid gap-4 p-4 xl:grid-cols-[260px_1fr]">
                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                    <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">Stage Counts</div>
                    <div className="space-y-2">
                      {Object.entries(recommendTrace.stage_counts).map(([stage, count]) => (
                        <div key={stage} className="flex items-center justify-between text-xs">
                          <span className="text-slate-400">{stage}</span>
                          <span className="font-bold text-cyan-300">{count}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                    <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">Source Distribution</div>
                    <div className="space-y-2">
                      {Object.entries(recommendTrace.source_distribution).map(([source, count]) => (
                        <div key={source} className="flex items-center justify-between gap-3 text-xs">
                          <span className="truncate text-slate-400">{source}</span>
                          <span className="font-bold text-cyan-300">{count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="overflow-hidden rounded-lg border border-slate-800">
                  <div className="grid grid-cols-[70px_1fr_90px_1fr] border-b border-slate-800 bg-slate-950 px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                    <div>Rank</div>
                    <div>Item</div>
                    <div>Score</div>
                    <div>Reason</div>
                  </div>
                  <div className="max-h-[520px] overflow-y-auto">
                    {recommendTrace.items.map((item) => {
                      const selected = selectedItemId && item.item_id === selectedItemId;
                      return (
                        <button
                          key={item.item_id}
                          type="button"
                          onClick={() => setSelectedItemId(item.item_id)}
                          className={`grid w-full grid-cols-[70px_1fr_90px_1fr] gap-3 border-b border-slate-800 px-3 py-3 text-left text-xs transition last:border-b-0 ${
                            selected ? 'bg-cyan-500/10 text-cyan-100' : 'bg-slate-900/40 text-slate-300 hover:bg-slate-800/60'
                          }`}
                        >
                          <div className="font-bold text-cyan-300">#{item.final_rank}</div>
                          <div className="min-w-0">
                            <div className="truncate font-mono text-[11px]">{item.item_id}</div>
                            <div className="mt-1 truncate text-[10px] text-slate-500">{item.recall_sources.join(', ') || 'no source'}</div>
                          </div>
                          <div className="font-bold">{item.final_score.toFixed(3)}</div>
                          <div className="line-clamp-2 text-slate-400">{item.reason || 'No reason captured'}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
          </section>
          </div>
        </div>
      </div>
    </div>
  );
}
