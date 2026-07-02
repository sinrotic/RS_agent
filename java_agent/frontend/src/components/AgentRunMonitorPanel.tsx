import { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, RefreshCw, Wrench } from 'lucide-react';
import type { AgentRunEventVO, AgentRunMonitorVO } from '../types/platformTrace';
import { eventTitle, formatMs, formatTokens, sortRunEvents, statusTone } from '../utils/agentRunMonitor';

interface AgentRunMonitorPanelProps {
  monitor: AgentRunMonitorVO | null;
  loading: boolean;
  autoRefresh: boolean;
  onRefresh: () => void;
  onAutoRefreshChange: (enabled: boolean) => void;
}

function metricValue(label: string, value: string, tone?: string) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-sm font-bold ${tone || 'text-slate-100'}`}>{value}</div>
    </div>
  );
}

function signalTone(signal: string): string {
  const normalized = signal.toLowerCase();
  const amberSignals = new Set([
    'missing_final_answer',
    'high_latency',
    'empty_tool_result',
    'no_recommendation_items',
    'partial_trace'
  ]);
  if (normalized.includes('error') || normalized.includes('fail')) {
    return 'border-rose-500/30 bg-rose-500/10 text-rose-200';
  }
  if (
    amberSignals.has(normalized)
    || normalized.includes('warn')
    || normalized.includes('partial')
    || normalized.includes('missing')
    || normalized.includes('empty')
    || normalized.includes('high_latency')
    || normalized.startsWith('no_')
  ) {
    return 'border-amber-500/30 bg-amber-500/10 text-amber-200';
  }
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200';
}

function eventStatus(event: AgentRunEventVO): string {
  if (event.error_code || event.error_message) {
    return 'error';
  }
  return event.status || 'partial';
}

export function AgentRunMonitorPanel({
  monitor,
  loading,
  autoRefresh,
  onRefresh,
  onAutoRefreshChange
}: AgentRunMonitorPanelProps) {
  const sortedEvents = useMemo(() => sortRunEvents(monitor?.events || []), [monitor]);
  const [selectedEventId, setSelectedEventId] = useState<string>('');

  const selectedEvent = useMemo(() => {
    if (sortedEvents.length === 0) return null;
    if (selectedEventId) {
      const matched = sortedEvents.find((event) => event.event_id === selectedEventId);
      if (matched) return matched;
    }
    return sortedEvents[sortedEvents.length - 1];
  }, [selectedEventId, sortedEvents]);

  if (!monitor) {
    return (
      <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
        <div className="flex flex-col gap-3 border-b border-slate-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="text-xs font-bold text-slate-100">Agent Run Monitor</div>
            <div className="text-[10px] text-slate-500">Query by session or request to inspect the live run.</div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-[11px] text-slate-400">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(event) => onAutoRefreshChange(event.target.checked)}
                className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-950 text-cyan-500 focus:ring-cyan-500"
              />
              Auto-refresh
            </label>
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] font-bold text-slate-200 transition hover:border-cyan-500 disabled:opacity-40"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        </div>
        <div className="px-4 py-5 text-xs text-slate-500">
          Enter a `session_id` or `request_id` above, then query to load latency, tokens, tool calls, phases, and raw run events.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
      <div className="flex flex-col gap-4 border-b border-slate-800 px-4 py-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-bold text-slate-100">Agent Run Monitor</span>
              <span
                className={`inline-flex items-center rounded-md border px-2 py-1 text-[10px] font-bold uppercase ${statusTone(
                  monitor.status
                )}`}
              >
                {monitor.status}
              </span>
            </div>
            <div className="grid gap-2 text-[10px] text-slate-500 sm:grid-cols-2">
              <div className="truncate font-mono">session: {monitor.session_id || '-'}</div>
              <div className="truncate font-mono">request: {monitor.request_id || '-'}</div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-[11px] text-slate-400">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(event) => onAutoRefreshChange(event.target.checked)}
                className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-950 text-cyan-500 focus:ring-cyan-500"
              />
              Auto-refresh
            </label>
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] font-bold text-slate-200 transition hover:border-cyan-500 disabled:opacity-40"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-7">
          {metricValue('Status', monitor.status, statusTone(monitor.status).split(' ')[0])}
          {metricValue('Latency', formatMs(monitor.summary.total_latency_ms), 'text-cyan-300')}
          {metricValue('Tokens', formatTokens(monitor.summary.total_tokens), 'text-cyan-300')}
          {metricValue('Model', monitor.summary.model_name || monitor.summary.model_provider || '-', 'text-slate-100')}
          {metricValue('Tools', String(monitor.summary.tool_call_count || 0), 'text-indigo-300')}
          {metricValue('Errors', String(monitor.summary.error_count || 0), monitor.summary.error_count ? 'text-rose-300' : 'text-emerald-300')}
          {metricValue('Final', monitor.summary.has_final_answer ? 'Present' : 'Missing', monitor.summary.has_final_answer ? 'text-emerald-300' : 'text-amber-300')}
        </div>
      </div>

      <div className="grid gap-4 p-4 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <div className="mb-3 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                <Clock3 size={12} />
                Overview
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <div className="text-[10px] text-slate-500">Provider</div>
                  <div className="mt-1 text-slate-200">{monitor.summary.model_provider || '-'}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500">Events</div>
                  <div className="mt-1 text-slate-200">{monitor.events.length}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500">Recommend Links</div>
                  <div className="mt-1 text-slate-200">{monitor.related_traces.recommend_request_ids.length}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500">Interactions</div>
                  <div className="mt-1 text-slate-200">{monitor.related_traces.interaction_event_count}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500">Agent Turns</div>
                  <div className="mt-1 text-slate-200">{monitor.related_traces.agent_turn_count}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500">Recommend Items</div>
                  <div className="mt-1 text-slate-200">{monitor.summary.recommend_item_count}</div>
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <div className="mb-3 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                <CheckCircle2 size={12} />
                Quality Signals
              </div>
              {monitor.quality_signals.length === 0 ? (
                <div className="text-xs text-slate-500">No quality signals captured.</div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {monitor.quality_signals.map((signal) => (
                    <span
                      key={signal}
                      className={`rounded-md border px-2 py-1 text-[10px] font-bold ${signalTone(signal)}`}
                    >
                      {signal}
                    </span>
                  ))}
                </div>
              )}
            </section>
          </div>

          <section className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
            <div className="mb-3 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
              <Wrench size={12} />
              Phases
            </div>
            {monitor.phases.length === 0 ? (
              <div className="text-xs text-slate-500">No phase summary captured.</div>
            ) : (
              <div className="space-y-2">
                {monitor.phases.map((phase) => (
                  <div
                    key={phase.phase}
                    className="grid gap-2 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs md:grid-cols-[minmax(0,1fr)_90px_90px_80px_80px]"
                  >
                    <div className="min-w-0">
                      <div className="font-bold text-slate-100">{phase.phase}</div>
                      <div className="mt-1 text-[10px] text-slate-500">{phase.event_count} events</div>
                    </div>
                    <div className="text-slate-300">{formatMs(phase.latency_ms)}</div>
                    <div className="text-slate-300">{formatTokens(phase.total_tokens)}</div>
                    <div>
                      <span
                        className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-bold uppercase ${statusTone(
                          phase.status
                        )}`}
                      >
                        {phase.status}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-500">tokens</div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-950/60">
            <div className="border-b border-slate-800 px-3 py-3">
              <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Timeline</div>
            </div>
            {sortedEvents.length === 0 ? (
              <div className="px-3 py-6 text-xs text-slate-500">No run events captured.</div>
            ) : (
              <div className="divide-y divide-slate-800">
                {sortedEvents.map((event) => {
                  const selected = selectedEvent?.event_id === event.event_id;
                  const computedStatus = eventStatus(event);
                  return (
                    <button
                      key={event.event_id}
                      type="button"
                      onClick={() => setSelectedEventId(event.event_id)}
                      className={`grid w-full gap-3 px-3 py-3 text-left text-xs transition sm:grid-cols-[140px_96px_minmax(0,1fr)_100px] ${
                        selected ? 'bg-cyan-500/10' : 'hover:bg-slate-800/60'
                      }`}
                    >
                      <div className="font-mono text-[10px] text-slate-500">
                        {new Date(event.created_at).toLocaleString()}
                      </div>
                      <div>
                        <span
                          className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-bold uppercase ${statusTone(
                            computedStatus
                          )}`}
                        >
                          {computedStatus}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <div className="truncate font-bold text-slate-200">{eventTitle(event)}</div>
                        <div className="mt-1 truncate text-[10px] text-slate-500">
                          {event.phase || event.event_type}
                          {event.agent_name ? ` • ${event.agent_name}` : ''}
                          {event.input_summary ? ` • ${event.input_summary}` : ''}
                        </div>
                      </div>
                      <div className="text-[10px] text-slate-500">
                        <div>{formatMs(event.latency_ms)}</div>
                        <div className="mt-1">{formatTokens(event.total_tokens)}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <section className="rounded-xl border border-slate-800 bg-slate-950/60">
          <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-3 py-3">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Event Detail</div>
              <div className="mt-1 truncate font-mono text-[10px] text-slate-500">
                {selectedEvent?.event_id || 'no event selected'}
              </div>
            </div>
            {selectedEvent?.error_message ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-[10px] font-bold text-rose-200">
                <AlertTriangle size={11} />
                Error
              </span>
            ) : null}
          </div>

          {!selectedEvent ? (
            <div className="px-3 py-6 text-xs text-slate-500">Select a timeline row to inspect the event payload.</div>
          ) : (
            <div className="space-y-4 p-3">
              <div className="grid gap-3 text-xs sm:grid-cols-2">
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] text-slate-500">Event</div>
                  <div className="mt-1 text-slate-200">{selectedEvent.event_type || '-'}</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] text-slate-500">Phase</div>
                  <div className="mt-1 text-slate-200">{selectedEvent.phase || '-'}</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] text-slate-500">Tool</div>
                  <div className="mt-1 break-all text-slate-200">{selectedEvent.tool_name || '-'}</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] text-slate-500">Model</div>
                  <div className="mt-1 break-all text-slate-200">
                    {selectedEvent.model_name || selectedEvent.model_provider || '-'}
                  </div>
                </div>
              </div>

              {(selectedEvent.input_summary || selectedEvent.output_summary || selectedEvent.error_message) && (
                <div className="grid gap-3 xl:grid-cols-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                    <div className="text-[10px] text-slate-500">Input</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-300">
                      {selectedEvent.input_summary || '-'}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                    <div className="text-[10px] text-slate-500">Output</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-300">
                      {selectedEvent.output_summary || '-'}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                    <div className="text-[10px] text-slate-500">Error</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-300">
                      {selectedEvent.error_message || selectedEvent.error_code || '-'}
                    </div>
                  </div>
                </div>
              )}

              <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">Raw JSON</div>
                <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-slate-300">
                  {JSON.stringify(selectedEvent, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
