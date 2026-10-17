import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { A2uiView } from '../components/A2uiView';
import { A2uiMessage, SHOPPING_CATALOG_ID, applyA2uiMessages, resolveUiValue, uiStateContext, updateUiData } from './a2ui';

const initial: A2uiMessage[] = [
  { version: 'v0.9', createSurface: { surfaceId: 'shopping', catalogId: SHOPPING_CATALOG_ID } },
  { version: 'v0.9', updateComponents: { surfaceId: 'shopping', components: [
    { id: 'root', component: 'Column', children: ['summary', 'query', 'submit'] },
    { id: 'summary', component: 'Text', text: { path: '/summary' } },
    { id: 'query', component: 'TextField', label: '购买需求', value: { path: '/query' } },
    { id: 'submit-label', component: 'Text', text: '查找商品' },
    { id: 'submit', component: 'Button', child: 'submit-label', action: {
      event: { name: 'submit_query', context: { query: { path: '/query' } } },
    } },
  ] } },
  { version: 'v0.9', updateDataModel: { surfaceId: 'shopping', value: { summary: '正在查找', query: '' } } },
];

describe('shopping A2UI runtime', () => {
  it('renders native form controls and applies partial data and component updates', () => {
    const original = applyA2uiMessages(new Map(), initial);
    const state = applyA2uiMessages(original, [
      { version: 'v0.9', updateDataModel: { surfaceId: 'shopping', path: '/summary', value: '查询完成' } },
      { version: 'v0.9', updateDataModel: { surfaceId: 'shopping', path: '/query', value: '通勤耳机' } },
      { version: 'v0.9', updateComponents: { surfaceId: 'shopping', components: [
        { id: 'submit-label', component: 'Text', text: '重新查找' },
      ] } },
    ]);
    const html = renderToStaticMarkup(<A2uiView state={state} products={[]} disabled={false}
      onStateChange={vi.fn()} onSubmit={vi.fn()} onFeedback={vi.fn()} onOpen={vi.fn()} />);
    expect(html).toContain('查询完成');
    expect(html).toContain('重新查找');
    expect(html).toContain('value="通勤耳机"');
    expect(html).not.toContain('disabled=""');
    expect(original.get('shopping')?.data).toEqual({ summary: '正在查找', query: '' });
    expect(uiStateContext(state)).toMatchObject([{ surfaceId: 'shopping', data: { query: '通勤耳机' } }]);
  });

  it('removes a data field when value is absent and supports escaped pointers', () => {
    const state = applyA2uiMessages(applyA2uiMessages(new Map(), initial), [
      { version: 'v0.9', updateDataModel: { surfaceId: 'shopping', path: '/summary' } },
    ]);
    expect(state.get('shopping')?.data).toEqual({ query: '' });
    const data = updateUiData({}, '/a~1b/~0name', 'value');
    expect(resolveUiValue({ path: '/a~1b/~0name' }, data)).toBe('value');
    expect(updateUiData({ items: ['a', 'b'] }, '/items/0', 'c')).toEqual({ items: ['c', 'b'] });
    expect(updateUiData({ items: ['a', 'b'] }, '/items/0', undefined, true)).toEqual({ items: ['b'] });
  });

  it('rejects cycles atomically, unsupported catalogs, invalid bindings and unsafe paths', () => {
    const original = applyA2uiMessages(new Map(), initial);
    expect(() => applyA2uiMessages(original, [{ version: 'v0.9', updateComponents: {
      surfaceId: 'shopping', components: [{ id: 'root', component: 'Column', children: ['root'] }],
    } }])).toThrow('循环');
    expect(original.get('shopping')?.components.get('root')).toMatchObject({ children: ['summary', 'query', 'submit'] });
    expect(() => applyA2uiMessages(new Map(), [{ version: 'v0.9', createSurface: {
      surfaceId: 'shopping', catalogId: 'unknown',
    } }])).toThrow('组件目录');
    expect(() => applyA2uiMessages(original, [{ version: 'v0.9', updateComponents: {
      surfaceId: 'shopping', components: [{ id: 'summary', component: 'Text', text: { call: 'evil' } }],
    } }] as unknown as A2uiMessage[])).toThrow('绑定');
    expect(() => updateUiData({}, '/__proto__/polluted', true)).toThrow('路径');
    expect(() => updateUiData({}, '/bad~2escape', true)).toThrow('路径');
    expect(() => updateUiData({}, '/', { details: { diagnostics: 'secret' } })).toThrow('字段');
  });

  it('requires creation and supports explicit deletion', () => {
    expect(() => applyA2uiMessages(new Map(), [initial[1]])).toThrow('尚未创建');
    expect(applyA2uiMessages(applyA2uiMessages(new Map(), initial), [
      { version: 'v0.9', deleteSurface: { surfaceId: 'shopping' } },
    ]).size).toBe(0);
  });
});
