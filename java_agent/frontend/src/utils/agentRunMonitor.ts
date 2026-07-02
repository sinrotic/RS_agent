import type { AgentRunEventVO, AgentRunMonitorVO, AgentRunStatus } from '../types/platformTrace';

export function formatMs(value?: number): string {
  if (!value || value <= 0) return '-';
  if (value < 1000) return `${value}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

export function formatTokens(value?: number): string {
  if (!value || value <= 0) return '-';
  return value.toLocaleString();
}

export function statusTone(status?: AgentRunStatus | 'error' | string): string {
  switch (status) {
    case 'success':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'failed':
    case 'error':
      return 'border-red-200 bg-red-50 text-red-700';
    case 'running':
      return 'border-sky-200 bg-sky-50 text-sky-700';
    case 'partial':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

export function shouldAutoRefresh(monitor?: AgentRunMonitorVO): boolean {
  return monitor?.status === 'running' || monitor?.status === 'partial';
}

export function eventTitle(event: AgentRunEventVO): string {
  return event.tool_name || event.event_type || event.phase || event.event_id;
}

export function sortRunEvents(events: AgentRunEventVO[]): AgentRunEventVO[] {
  return [...events].sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
}
