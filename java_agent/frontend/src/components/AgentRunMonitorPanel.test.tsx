import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AgentRunMonitorPanel } from './AgentRunMonitorPanel';
import type { AgentRunMonitorVO } from '../types/platformTrace';

describe('运行面板的计量展示', () => {
  it('缺失总量显示横线，并显示最终回执覆盖率', () => {
    const monitor: AgentRunMonitorVO = {
      session_id: 'session', request_id: 'turn', status: 'success',
      summary: {
        total_latency_ms: 400, prompt_tokens: null, completion_tokens: null, total_tokens: null,
        model_provider: '', model_name: '', tool_call_count: 0, error_count: 0,
        recommend_item_count: 0, has_final_answer: true,
        usage_coverage: { mode: 'canonical', model_calls: 2,
          fields: { total_tokens: { total: null, known_subtotal: 15, observed_calls: 1, finalized_calls: 1 } } },
      },
      phases: [], events: [], quality_signals: [],
      related_traces: { agent_turn_count: 1, recommend_request_ids: [], interaction_event_count: 0 },
    };
    const html = renderToStaticMarkup(<AgentRunMonitorPanel monitor={monitor} loading={false} autoRefresh={false}
      onRefresh={() => {}} onAutoRefreshChange={() => {}} />);
    expect(html).toContain('最终用量 1/2');
    expect(html).toContain('总量不完整');
    expect(html).toMatch(/Tokens<\/div><div[^>]*>-<\/div>/);
    expect(html).toContain('Observed latency');
  });
});
