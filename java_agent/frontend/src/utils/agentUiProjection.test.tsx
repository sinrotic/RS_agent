import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { A2uiView } from '../components/A2uiView';
import type { AgentAnswerBlock } from '../types/agent';
import type { DisplayProduct } from './displayViewModel';
import { SHOPPING_CATALOG_ID, UiComponent, UiState, applyA2uiMessages, uiStateContext, visibleUiProductIds } from './a2ui';
import { projectAgentUi } from './agentUiProjection';

function product(itemId: string, rank = 1): DisplayProduct {
  return { itemId, title: `业务商品 ${itemId}`, category: '业务类目', store: '业务店铺',
    imageUrl: null, price: 55, rating: null, features: [], description: null, badges: [],
    reason: '业务推荐理由', score: 0.8, rank };
}
const products = [product('item-1'), product('item-2', 2)];
function modelUi(components: UiComponent[], surfaceId = 'shopping'): UiState {
  return applyA2uiMessages(new Map(), [
    { version: 'v0.9', createSurface: { surfaceId, catalogId: SHOPPING_CATALOG_ID } },
    { version: 'v0.9', updateComponents: { surfaceId, components } },
  ]);
}
function html(state: UiState, values = products, feedbackDisabled = false): string {
  return renderToStaticMarkup(<A2uiView state={state} products={values} disabled={false}
    feedbackDisabled={feedbackDisabled} onStateChange={vi.fn()} onSubmit={vi.fn()}
    onFeedback={vi.fn()} onOpen={vi.fn()} />);
}

describe('unified Agent A2UI display projection', () => {
  it('renders business recommendations through A2UI when the model emits no UI', () => {
    const modelState: UiState = new Map();
    const state = projectAgentUi(modelState, { products });
    const output = html(state);
    expect(visibleUiProductIds(state)).toEqual(['item-1', 'item-2']);
    expect(output).toContain('data-a2ui-surface-id="rs-business-display"');
    expect(output).toContain('业务商品 item-1');
    expect(output).toContain('$55.00');
    expect(output).toContain('业务推荐理由');
    expect(output).toContain('data-recommend-position="2"');
    expect(modelState.size).toBe(0);
    expect(uiStateContext(modelState)).toEqual([]);
    expect(JSON.stringify(uiStateContext(state))).not.toContain('业务商品');
  });

  it('adapts legacy product blocks, preserves their layout/order and rejects unprovided IDs', () => {
    const answerBlocks: AgentAnswerBlock[] = [
      { type: 'product_cards', item_ids: ['invented', 'item-2', 'item-1', 'item-2'], layout: 'grid' },
      { type: 'product_cards', item_ids: ['item-1'] },
    ];
    const state = projectAgentUi(new Map(), { products, answerBlocks });
    const output = html(state);
    expect(visibleUiProductIds(state)).toEqual(['item-2', 'item-1']);
    expect(output).toContain('md:grid-cols-2');
    expect(output).not.toContain('invented');
    expect(output.match(/data-recommend-item-id=/g)).toHaveLength(2);
    expect(output.indexOf('data-recommend-item-id="item-2"')).toBeLessThan(output.indexOf('data-recommend-item-id="item-1"'));
  });

  it('resolves current card sets and falls back for stale deliveries or unknown legacy IDs', () => {
    const current = projectAgentUi(new Map(), { products, cardSetId: 'delivery',
      answerBlocks: [{ type: 'product_cards', card_set_id: 'delivery', layout: 'grid' }] });
    expect(html(current)).toContain('md:grid-cols-2');
    for (const block of [
      { type: 'product_cards' as const, card_set_id: 'old-delivery', layout: 'grid' },
      { type: 'product_cards' as const, item_ids: ['unknown'] },
    ]) {
      const state = projectAgentUi(new Map(), { products, cardSetId: 'delivery', answerBlocks: [block] });
      expect(visibleUiProductIds(state)).toEqual(['item-1', 'item-2']);
      expect(html(state)).not.toContain('md:grid-cols-2');
    }
  });

  it('reuses an actual model product UI without adding duplicate defaults or legacy cards', () => {
    const modelState = modelUi([{ id: 'root', component: 'ProductCards', itemIds: ['item-2'], layout: 'grid' }]);
    const state = projectAgentUi(modelState, { products,
      answerBlocks: [{ type: 'a2ui' }, { type: 'product_cards', item_ids: ['item-1', 'item-2'] }] });
    expect(state).toBe(modelState);
    expect(html(state).match(/data-recommend-item-id=/g)).toHaveLength(1);
    expect(visibleUiProductIds(state)).toEqual(['item-2']);
  });

  it('does not let an earlier Turn product selection hide a new delivery without model UI', () => {
    const modelState = modelUi([{ id: 'root', component: 'ProductCards', itemIds: ['item-2'], layout: 'grid' }]);
    const state = projectAgentUi(modelState, { products, answerBlocks: [] });
    expect(visibleUiProductIds(state)).toEqual(['item-1', 'item-2']);
    expect(html(state).match(/data-recommend-item-id=/g)).toHaveLength(2);
    expect(visibleUiProductIds(modelState)).toEqual(['item-2']);
    expect(html(state)).not.toContain('md:grid-cols-2');
  });

  it('keeps forms while falling back for detached, stale or unknown model product components', () => {
    for (const components of [
      [{ id: 'root', component: 'TextField', label: '需求', value: { path: '/query' } },
        { id: 'detached', component: 'ProductCards', itemIds: ['item-1'] }],
      [{ id: 'root', component: 'Column', children: ['query', 'cards'] },
        { id: 'query', component: 'TextField', label: '需求', value: { path: '/query' } },
        { id: 'cards', component: 'ProductCards', itemIds: ['old-product'] }],
    ] as UiComponent[][]) {
      const modelState = modelUi(components);
      const before = uiStateContext(modelState);
      const state = projectAgentUi(modelState, { products, answerBlocks: [{ type: 'a2ui' }] });
      expect(html(state)).toContain('<input');
      expect(html(state).match(/data-recommend-item-id=/g)).toHaveLength(2);
      expect(uiStateContext(modelState)).toEqual(before);
      expect(modelState.has('rs-business-display')).toBe(false);
    }
  });

  it('adapts comparison and follow-up blocks to supported A2UI components', () => {
    const state = projectAgentUi(new Map(), { products, answerBlocks: [
      { type: 'comparison_table', item_ids: ['item-1', 'item-2'] },
      { type: 'comparison_table', content: '比较结果：这两款价格相近。' },
      { type: 'followup_question', content: '您偏好哪个颜色？' },
      { type: 'text', content: '普通回答仍在聊天记录中' },
    ] });
    const output = html(state);
    expect(output).toContain('md:grid-cols-2');
    expect(output).toContain('比较结果');
    expect(output).toContain('您偏好哪个颜色');
    expect(output).not.toContain('普通回答仍在聊天记录中');
    expect(output.match(/data-recommend-item-id=/g)).toHaveLength(2);
  });

  it('rebuilds legacy history and replaces default cards when the business result changes', () => {
    const modelState = new Map();
    const first = projectAgentUi(modelState, { products });
    const next = projectAgentUi(modelState, { products: [product('item-3')] });
    expect(visibleUiProductIds(first)).toEqual(['item-1', 'item-2']);
    expect(visibleUiProductIds(next)).toEqual(['item-3']);
    expect(html(next, [product('item-3')])).not.toContain('业务商品 item-1');
    expect(uiStateContext(modelState)).toEqual([]);
  });

  it('renders empty results through A2UI and avoids collisions with model surface IDs', () => {
    const modelState = modelUi([{ id: 'root', component: 'Text', text: '模型界面' }], 'rs-business-display');
    const state = projectAgentUi(modelState, { products: [] });
    expect(state.size).toBe(2);
    expect(state.get('rs-business-display')).toBe(modelState.get('rs-business-display'));
    expect(html(state, [])).toContain('暂无对话推荐商品');
    expect(state.has('rs-business-display-1')).toBe(true);
    expect(modelState.size).toBe(1);
  });

  it('chunks product messages to catalog limits without dropping business results', () => {
    const many = Array.from({ length: 45 }, (_, index) => product(`item-${index}`, index + 1));
    const state = projectAgentUi(new Map(), { products: many });
    expect(visibleUiProductIds(state)).toHaveLength(45);
    expect(html(state, many).match(/data-recommend-item-id=/g)).toHaveLength(45);
    for (const surface of state.values()) {
      for (const component of surface.components.values()) {
        if (component.component === 'ProductCards') expect(component.itemIds.length).toBeLessThanOrEqual(20);
      }
    }
  });

  it('disables card feedback without a delivery ID but keeps form submissions enabled', () => {
    const modelState = modelUi([
      { id: 'root', component: 'Column', children: ['query', 'submit'] },
      { id: 'query', component: 'TextField', label: '需求', value: { path: '/query' } },
      { id: 'submit-label', component: 'Text', text: '查找' },
      { id: 'submit', component: 'Button', child: 'submit-label', action: {
        event: { name: 'submit_query', context: { query: '背包' } },
      } },
    ]);
    const output = html(projectAgentUi(modelState, { products }), products, true);
    expect(output.match(/disabled=""/g)).toHaveLength(6);
    expect(output).toMatch(/<button[^>]*>\s*<p[^>]*>查找<\/p>/);
    expect(output).toContain('查看商品详情');
  });
});
