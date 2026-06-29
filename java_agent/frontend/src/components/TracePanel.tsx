import { Activity, Database, GitBranch, RefreshCw, Wrench } from 'lucide-react';
import { PlatformSessionOverviewVO, RecommendTraceVO } from '../types/platformTrace';

interface TracePanelProps {
  overview: PlatformSessionOverviewVO | null;
  loading: boolean;
  error?: string;
  onRefresh: () => void;
  selectedItemId?: string | null;
}

function entries(record?: Record<string, number>) {
  return Object.entries(record || {}).sort(([left], [right]) => left.localeCompare(right));
}

function activeRecommendTrace(overview: PlatformSessionOverviewVO | null): RecommendTraceVO | null {
  if (!overview || overview.recommend_traces.length === 0) return null;
  return overview.recommend_traces[overview.recommend_traces.length - 1];
}

export function TracePanel({ overview, loading, error, onRefresh, selectedItemId }: TracePanelProps) {
  const trace = activeRecommendTrace(overview);
  const selectedItem = selectedItemId && trace
    ? trace.items.find((item) => item.item_id === selectedItemId)
    : null;
  const turns = overview?.agent_trace.turns || [];

  return (
    <div className="bg-slate-800/80 border border-slate-700/60 rounded-2xl p-4 space-y-4 text-left">
      <div className="flex items-center justify-between gap-3 border-b border-slate-700/50 pb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-100">
            <Activity size={14} className="text-cyan-400" />
            Platform Trace
          </div>
          <div className="mt-1 truncate text-[10px] text-slate-500 font-mono">
            {overview?.session_id || 'session pending'}
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="shrink-0 inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-300 hover:text-white disabled:opacity-40"
          title="Refresh trace"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[11px] font-semibold text-rose-300">
          {error}
        </div>
      )}

      <section className="space-y-2">
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-400">
          <Database size={12} />
          Profile
        </div>
        <div className="rounded-xl bg-slate-950/50 border border-slate-700/60 p-3">
          <div className="text-[11px] font-mono text-indigo-300 truncate">
            {overview?.account_profile.profile_user_id || 'profile pending'}
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-350">
            {overview?.account_profile.profile_summary || 'No profile trace captured yet.'}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {(overview?.account_profile.top_categories || []).slice(0, 4).map((category) => (
              <span key={category} className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[9px] font-bold text-indigo-300">
                {category}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-400">
          <GitBranch size={12} />
          Recommendation
        </div>
        <div className="grid grid-cols-2 gap-2">
          {entries(trace?.stage_counts).map(([stage, count]) => (
            <div key={stage} className="rounded-lg border border-slate-700/60 bg-slate-950/40 px-2 py-2">
              <div className="truncate text-[9px] font-bold uppercase text-slate-500">{stage}</div>
              <div className="mt-0.5 text-sm font-extrabold text-slate-100">{count}</div>
            </div>
          ))}
        </div>
        {trace && (
          <div className="rounded-xl bg-slate-950/50 border border-slate-700/60 p-3">
            <div className="text-[10px] text-slate-500 font-mono truncate">request: {trace.request_id}</div>
            <div className="mt-2 space-y-1.5">
              {entries(trace.source_distribution).map(([source, count]) => (
                <div key={source} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="truncate text-slate-350">{source}</span>
                  <span className="font-bold text-cyan-300">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {selectedItem && (
        <section className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Selected Item</div>
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-mono text-cyan-200 truncate">{selectedItem.item_id}</span>
              <span className="text-[10px] font-bold text-cyan-300">#{selectedItem.final_rank}</span>
            </div>
            <div className="mt-1 text-xs font-extrabold text-slate-100">
              {selectedItem.final_score.toFixed(3)}
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-300">{selectedItem.reason}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {selectedItem.recall_sources.map((source) => (
                <span key={source} className="rounded-full bg-slate-950/70 px-2 py-0.5 text-[9px] font-bold text-slate-300">
                  {source}
                </span>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="space-y-2">
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-400">
          <Wrench size={12} />
          Agent Turns
        </div>
        <div className="space-y-2">
          {turns.length === 0 ? (
            <div className="rounded-xl border border-slate-700/60 bg-slate-950/40 px-3 py-2 text-[11px] text-slate-500">
              No agent turns captured.
            </div>
          ) : (
            turns.slice(-3).map((turn) => (
              <div key={turn.request_id} className="rounded-xl border border-slate-700/60 bg-slate-950/40 p-3">
                <div className="text-[10px] font-mono text-slate-500 truncate">{turn.request_id}</div>
                <div className="mt-1 text-[11px] text-slate-300 line-clamp-2">{turn.user_message}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {turn.tool_calls.slice(0, 3).map((tool) => (
                    <span key={tool} className="rounded-full bg-purple-500/10 px-2 py-0.5 text-[9px] font-bold text-purple-300">
                      {tool}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
