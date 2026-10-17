import { describe, it, expect } from 'vitest';
import { formatTokens, usageCoverageLabel } from './agentRunMonitor';
import type { AgentRunSummaryVO } from '../types/platformTrace';

const summary: AgentRunSummaryVO = {
  total_latency_ms: 100, prompt_tokens: null, completion_tokens: null, total_tokens: null,
  model_provider: '', model_name: '', tool_call_count: 0, error_count: 0, recommend_item_count: 0, has_final_answer: true,
};
describe('调用用量的缺失与覆盖率', () => {
  it('明确的零与未观测到的值显示不同', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(null)).toBe('-');
    expect(formatTokens(undefined)).toBe('-');
    expect(formatTokens(Number.NaN)).toBe('-');
  });
  it('历史记录不显示为零消耗，部分最终回执显示分母', () => {
    expect(usageCoverageLabel({ ...summary, usage_coverage: { mode: 'legacy_unverified' } })).toContain('未核验');
    const label = usageCoverageLabel({ ...summary, usage_coverage: {
      mode: 'canonical', model_calls: 2,
      fields: { total_tokens: { total: null, known_subtotal: 10, observed_calls: 1, finalized_calls: 1 } },
    } });
    expect(label).toContain('1/2');
    expect(label).toContain('总量不完整');
  });
});
