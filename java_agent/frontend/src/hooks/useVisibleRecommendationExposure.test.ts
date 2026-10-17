import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { recordExposure } from '../api/interactionClient';
import { clearTokens, saveAccountId, saveRealAccessToken } from '../api/shared';
import { useVisibleRecommendationExposure } from './useVisibleRecommendationExposure';

const effects = vi.hoisted(() => ({ cleanup: undefined as (() => void) | undefined }));
vi.mock('react', () => ({ useEffect: (effect: () => (() => void) | undefined) => { effects.cleanup = effect(); } }));
vi.mock('../api/interactionClient', () => ({ recordExposure: vi.fn() }));
const record = vi.mocked(recordExposure);
const accepted = { feedback_id: 'exposure-1', accepted: true, feedback_type: 'EXPOSURE', accepted_count: 1, application_status: 'NOT_APPLICABLE' as const, preference_version: 0 };
let observer: Observer;
class Observer {
  observed = new Set<Element>();
  callback: IntersectionObserverCallback;
  constructor(callback: IntersectionObserverCallback) { this.callback = callback; observer = this; }
  observe(element: Element) { this.observed.add(element); }
  unobserve(element: Element) { this.observed.delete(element); }
  disconnect() { this.observed.clear(); }
  emit(element: Element, visible = true) {
    if (this.observed.has(element)) this.callback([{ target: element, isIntersecting: visible, intersectionRatio: visible ? 0.8 : 0 } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
}
function mount() {
  const element = { dataset: { recommendItemId: 'item-1', recommendPosition: '1' } } as unknown as HTMLElement;
  const root = { querySelectorAll: () => [element] } as unknown as HTMLElement;
  useVisibleRecommendationExposure({ current: root }, 'delivery-1', 'session-1', 1);
  return element;
}

describe('真实曝光确认与重试', () => {
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-11T00:00:00Z'));
    vi.stubGlobal('localStorage', { getItem: () => null, removeItem: vi.fn() });
    vi.stubGlobal('window', { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (id: number) => clearTimeout(id) });
    vi.stubGlobal('IntersectionObserver', Observer);
    clearTokens(); saveRealAccessToken('token-A'); saveAccountId('A');
    record.mockReset(); record.mockResolvedValue(accepted);
  });
  afterEach(() => { effects.cleanup?.(); effects.cleanup = undefined; clearTokens(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('只在成功确认后停止观察，并保持成功去重', async () => {
    let resolve!: (value: typeof accepted) => void;
    record.mockReturnValue(new Promise(done => { resolve = done; }));
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    expect(observer.observed.has(element)).toBe(true);
    observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    expect(record).toHaveBeenCalledTimes(1);
    resolve(accepted); await Promise.resolve(); await Promise.resolve();
    expect(observer.observed.has(element)).toBe(false);
    observer.emit(element); await vi.advanceTimersByTimeAsync(5000);
    expect(record).toHaveBeenCalledTimes(1);
  });

  it('短暂 503 后退避重试同一曝光参数，捕获拒绝', async () => {
    record.mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce(accepted);
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    const original = record.mock.calls[0][0];
    expect(observer.observed.has(element)).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    expect(record).toHaveBeenCalledTimes(2);
    expect(record.mock.calls[1][0]).toEqual(original);
    expect(original.items?.[0].visible_duration_ms).toBe(1000);
    expect(observer.observed.has(element)).toBe(false);
  });

  it('网络中断连续失败时只进行三次自动尝试', async () => {
    record.mockRejectedValue(new TypeError('temporary network failure'));
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(30000);
    expect(record).toHaveBeenCalledTimes(3);
    expect(observer.observed.has(element)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('429 可以退避重试，422 不自动重试', async () => {
    record.mockRejectedValueOnce({ status: 429 }).mockRejectedValueOnce({ status: 422 });
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(30000);
    expect(record).toHaveBeenCalledTimes(2);
    observer.emit(element); await vi.advanceTimersByTimeAsync(30000);
    expect(record).toHaveBeenCalledTimes(2);
  });

  it('accepted=false 不标记成功且不无限重试', async () => {
    record.mockResolvedValue({ ...accepted, accepted: false });
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(30000);
    expect(record).toHaveBeenCalledTimes(1); expect(observer.observed.has(element)).toBe(true);
  });

  it('离开视口后仍能补报已经发生的曝光事实', async () => {
    record.mockRejectedValueOnce(new TypeError('network failure')).mockResolvedValueOnce(accepted);
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    observer.emit(element, false); await vi.advanceTimersByTimeAsync(1000);
    expect(record).toHaveBeenCalledTimes(2);
  });

  it('短于一秒的可见时间不构成曝光', async () => {
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(500);
    observer.emit(element, false); await vi.advanceTimersByTimeAsync(5000);
    expect(record).not.toHaveBeenCalled();
  });

  it('卸载会取消待重试任务', async () => {
    record.mockRejectedValueOnce({ status: 503 });
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    effects.cleanup?.(); await vi.advanceTimersByTimeAsync(10000);
    expect(record).toHaveBeenCalledTimes(1); expect(observer.observed.size).toBe(0);
  });

  it('切换账号后不再重试旧账号曝光', async () => {
    record.mockRejectedValueOnce({ status: 503 });
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    clearTokens(); saveRealAccessToken('token-B'); saveAccountId('B');
    await vi.advanceTimersByTimeAsync(10000); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    expect(record).toHaveBeenCalledTimes(1);
  });

  it('自动尝试耗尽后重新进入视口仍使用原始曝光事实补报', async () => {
    record.mockRejectedValueOnce({ status: 503 }).mockRejectedValueOnce({ status: 503 })
      .mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce(accepted);
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(10000);
    expect(record).toHaveBeenCalledTimes(3);
    const original = record.mock.calls[0][0];
    observer.emit(element, false); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    expect(record).toHaveBeenCalledTimes(4); expect(record.mock.calls[3][0]).toEqual(original);
    expect(observer.observed.has(element)).toBe(false);
  });

  it('卸载后到达的失败回包不再安排重试', async () => {
    let reject!: (reason: unknown) => void;
    record.mockReturnValue(new Promise((_done, fail) => { reject = fail; }));
    const element = mount(); observer.emit(element); await vi.advanceTimersByTimeAsync(1000);
    effects.cleanup?.(); reject(new TypeError('late network failure'));
    await vi.advanceTimersByTimeAsync(10000);
    expect(record).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });
});
