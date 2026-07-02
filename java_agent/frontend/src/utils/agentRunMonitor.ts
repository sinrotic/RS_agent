import type { AgentRunEventVO, AgentRunMonitorVO, AgentRunStatus } from '../types/platformTrace';

export function formatMs(value?: number): string {
  if (!value || value <= 0) return '-';
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export function formatTokens(value?: number): string {
  if (!value || value <= 0) return '-';
  return value.toLocaleString();
}

export function statusTone(status?: AgentRunStatus | 'error' | string): string {
  switch (status) {
    case 'success':
      return 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10';
    case 'failed':
    case 'error':
      return 'text-rose-300 border-rose-500/30 bg-rose-500/10';
    case 'running':
      return 'text-cyan-300 border-cyan-500/30 bg-cyan-500/10';
    case 'partial':
    default:
      return 'text-amber-300 border-amber-500/30 bg-amber-500/10';
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
