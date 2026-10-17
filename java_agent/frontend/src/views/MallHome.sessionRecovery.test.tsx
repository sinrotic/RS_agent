import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement, ReactNode } from 'react';
import { MallHome } from './MallHome';
import { GroupedRecommendationGrid } from '../components/GroupedRecommendationGrid';
import { recommendHome, refreshHome } from '../api/recommendClient';
import { startSession } from '../api/sessionClient';
import { recordEvent } from '../api/interactionClient';
import { ApiError } from '../api/shared';
import { useVisibleRecommendationExposure } from '../hooks/useVisibleRecommendationExposure';

// 执行真实组件的回调与状态转换；只替换渲染器和远程调用，无需新增浏览器依赖。
const hooks = vi.hoisted(() => ({
  values: [] as unknown[], refs: [] as { current: unknown }[], effects: [] as (() => void)[],
  cursor: 0, refCursor: 0, mounted: false,
}));
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = hooks.cursor++;
    if (!(index in hooks.values)) hooks.values[index] = initial;
    return [hooks.values[index], (next: unknown) => {
      hooks.values[index] = typeof next === 'function' ? next(hooks.values[index]) : next;
    }];
  },
  useRef: (initial: unknown) => {
    const index = hooks.refCursor++;
    return hooks.refs[index] ??= { current: initial };
  },
  useEffect: (effect: () => void) => { if (!hooks.mounted) hooks.effects.push(effect); },
}));
vi.mock('../api/recommendClient', () => ({ recommendHome: vi.fn(), refreshHome: vi.fn(), homeFeedbackCursor: vi.fn(() => '') }));
vi.mock('../api/sessionClient', () => ({ startSession: vi.fn() }));
vi.mock('../api/interactionClient', () => ({ recordEvent: vi.fn(), waitForFeedbackApplied: vi.fn() }));
vi.mock('../api/shared', async importOriginal => ({
  ...await importOriginal<typeof import('../api/shared')>(),
  getStoredProfileUserId: () => 'profile', isMockMode: () => false,
}));
vi.mock('../api/catalogHydration', () => ({ hydrateRecommendedProducts: vi.fn(async () => ({ products: [], catalogUnavailable: false })) }));
vi.mock('../utils/displayViewModel', () => ({ buildDisplayViewModel: vi.fn(() => ({ groups: [{ id: 'group', products: [] }] })) }));
vi.mock('../hooks/useVisibleRecommendationExposure', () => ({ useVisibleRecommendationExposure: vi.fn() }));
vi.mock('../components/GroupedRecommendationGrid', () => ({ GroupedRecommendationGrid: () => null }));
vi.mock('../components/RecommendationIntentSummary', () => ({ RecommendationIntentSummary: () => null }));

function render(): ReactElement {
  hooks.cursor = 0; hooks.refCursor = 0;
  const tree = MallHome({ onOpenProduct: vi.fn() });
  hooks.mounted = true;
  return tree;
}
function nodes(node: ReactNode): ReactElement<any>[] {
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (!node || typeof node !== 'object' || !('props' in node)) return [];
  const element = node as ReactElement<any>;
  return [element, ...nodes(element.props.children)];
}
function button(tree: ReactElement, label: string): ReactElement<any> {
  const found = nodes(tree).find(node => node.type === 'button' &&
    JSON.stringify(node.props.children).includes(label));
  if (!found) throw new Error(`未找到按钮：${label}`);
  return found;
}
async function mount() {
  render(); hooks.effects.splice(0).forEach(effect => effect());
  for (let i = 0; i < 8; i++) await Promise.resolve();
  return render();
}

describe('首页会话过期恢复', () => {
  beforeEach(() => {
    hooks.values = []; hooks.refs = []; hooks.effects = [];
    hooks.cursor = 0; hooks.refCursor = 0; hooks.mounted = false;
    vi.clearAllMocks();
    vi.mocked(startSession).mockResolvedValue({ sessionId: 'old-session' });
    vi.mocked(recommendHome).mockResolvedValue({
      request_id: 'old-delivery', session_id: 'old-session', profile_user_id: 'profile',
      scene: 'home', items: [], has_more: true, next_cursor: 'old-cursor',
      preference_version: 0, applied_feedback_event_ids: [], config: {} as never,
    });
  });

  it('刷新遇到 410 后清除旧会话与曝光，并通过重新加载创建新会话', async () => {
    const tree = await mount();
    vi.mocked(refreshHome).mockRejectedValueOnce(new ApiError('会话已结束', 410));
    await button(tree, '换一批推荐').props.onClick();
    let recovered = render();
    expect(nodes(recovered).some(node => node.props.role === 'alert')).toBe(true);
    expect(button(recovered, '换一批推荐').props.disabled).toBe(true);
    expect(useVisibleRecommendationExposure).toHaveBeenLastCalledWith(expect.anything(), '', '', []);
    vi.mocked(startSession).mockResolvedValueOnce({ sessionId: 'new-session' });
    const initialRecommendation = await vi.mocked(recommendHome).mock.results[0].value;
    vi.mocked(recommendHome).mockResolvedValueOnce({
      ...initialRecommendation,
      request_id: 'new-delivery', session_id: 'new-session',
    });
    await button(recovered, '重新加载').props.onClick();
    recovered = render();
    expect(startSession).toHaveBeenCalledTimes(2);
    expect(recommendHome).toHaveBeenLastCalledWith(expect.objectContaining({ sessionId: 'new-session' }));
    expect(nodes(recovered).some(node => node.props.role === 'alert')).toBe(false);
    expect(useVisibleRecommendationExposure).toHaveBeenLastCalledWith(expect.anything(), 'new-delivery', 'new-session', []);
    expect(recordEvent).not.toHaveBeenCalled();
  });

  it.each(['like', 'dislike', 'why'])('反馈 %s 遇到 410 后保留恢复入口，不把旧反馈重放进新会话', async action => {
    const tree = await mount();
    const grid = nodes(tree).find(node => node.type === GroupedRecommendationGrid)!;
    vi.mocked(recordEvent).mockRejectedValueOnce(new ApiError('会话已结束', 410));
    await grid.props.onFeedback(action, 'item');
    const recovered = render();
    expect(button(recovered, '重新加载')).toBeDefined();
    expect(useVisibleRecommendationExposure).toHaveBeenLastCalledWith(expect.anything(), '', '', []);
    expect(recordEvent).toHaveBeenCalledTimes(1);
    expect(refreshHome).not.toHaveBeenCalled();
  });

  it('临时 503 保留当前会话，允许再次刷新', async () => {
    const tree = await mount();
    vi.mocked(refreshHome).mockRejectedValueOnce(new ApiError('暂不可用', 503));
    await button(tree, '换一批推荐').props.onClick();
    const recovered = render();
    expect(nodes(recovered).some(node => node.props.role === 'alert')).toBe(false);
    expect(button(recovered, '换一批推荐').props.disabled).toBe(false);
    expect(useVisibleRecommendationExposure).toHaveBeenLastCalledWith(expect.anything(), 'old-delivery', 'old-session', []);
  });
});
