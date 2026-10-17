import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function storage() {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    key: (index: number) => [...values.keys()][index] ?? null,
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const json = (status: number, value: unknown) => ({ status, ok: status >= 200 && status < 300, json: async () => value }) as Response;
const token = (accountId: string) => ({ accessToken: `token-${accountId}`, accountId, profileUserId: `profile-${accountId}` });

describe('登录会话变化时的并发请求', () => {
  let shared: typeof import('./shared');
  let auth: typeof import('./authClient');

  beforeEach(async () => {
    vi.resetModules();
    vi.stubGlobal('localStorage', storage());
    vi.stubGlobal('sessionStorage', storage());
    vi.stubGlobal('document', { cookie: 'rs_refresh_csrf=test-csrf' });
    shared = await import('./shared');
    auth = await import('./authClient');
    shared.saveRealAccessToken('token-A');
    shared.saveAccountId('A');
  });
  afterEach(() => { shared.clearTokens(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  const switched = { name: 'AuthSessionChangedError' };

  it('切换账号后不使用 B 的凭证重放 A 的下单请求', async () => {
    const old = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue(json(200, {}));
    vi.stubGlobal('fetch', fetchMock);
    const request = shared.requestJson('POST', '/checkout/orders', { requestId: 'intent-A', itemId: 'item-A' });
    const rejected = expect(request).rejects.toMatchObject(switched);
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    old.resolve(json(401, {}));
    await rejected;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(shared.getAccountId()).toBe('B');
  });

  it('同一账号旋转 token 时可以重试在途请求', async () => {
    const old = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue(json(200, { ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    const request = shared.requestJson('GET', '/sessions/one');
    shared.saveRealAccessToken('token-A-rotated');
    old.resolve(json(401, {}));
    expect(await request).toEqual({ ok: true });
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer token-A-rotated');
  });

  it.each([200, 401])('退出后忽略迟到的刷新回包（HTTP %i）', async status => {
    const refresh = deferred<Response>();
    const started = deferred<void>();
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/auth/refresh')) { started.resolve(); return refresh.promise; }
      return json(401, {});
    });
    vi.stubGlobal('fetch', fetchMock);
    const request = shared.requestJson('GET', '/sessions/one');
    const rejected = expect(request).rejects.toMatchObject(switched);
    await started.promise;
    shared.clearTokens();
    refresh.resolve(json(status, token('A')));
    await rejected;
    expect(shared.getAccessToken()).toBeNull();
    expect(shared.getAccountId()).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('旧刷新任务完成时不清掉新任务，且旧失败不清空 B 的登录', async () => {
    const refreshA = deferred<Response>(); const refreshB = deferred<Response>();
    const startedA = deferred<void>(); const startedB = deferred<void>(); const twoUnauthorized = deferred<void>();
    let refreshCount = 0; let bUnauthorized = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/refresh')) {
        refreshCount += 1;
        if (refreshCount === 1) { startedA.resolve(); return refreshA.promise; }
        startedB.resolve(); return refreshB.promise;
      }
      const authorization = (init.headers as Record<string, string>).Authorization;
      if (authorization === 'Bearer token-B-rotated') return json(200, { ok: true });
      if (authorization === 'Bearer token-B' && ++bUnauthorized === 2) twoUnauthorized.resolve();
      return json(401, {});
    }));
    const old = shared.requestJson('GET', '/sessions/A');
    const rejected = expect(old).rejects.toMatchObject(switched);
    await startedA.promise;
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    const b1 = shared.requestJson('GET', '/sessions/B1');
    await startedB.promise;
    refreshA.resolve(json(401, {})); await rejected;
    expect(shared.getAccessToken()).toBe('token-B');
    const b2 = shared.requestJson('GET', '/sessions/B2');
    await twoUnauthorized.promise;
    await Promise.resolve(); await Promise.resolve();
    refreshB.resolve(json(200, { accessToken: 'token-B-rotated', accountId: 'B' }));
    expect(await Promise.all([b1, b2])).toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCount).toBe(2);
  });

  it('旧 /auth/me 成功回包不覆盖 B 的账号及交易记录归属', async () => {
    const old = deferred<Response>(); vi.stubGlobal('fetch', vi.fn(() => old.promise));
    const request = auth.getMe(); const rejected = expect(request).rejects.toMatchObject(switched);
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    old.resolve(json(200, { accountId: 'A', username: 'A' })); await rejected;
    expect(shared.getAccessToken()).toBe('token-B'); expect(shared.getAccountId()).toBe('B');
    expect(shared.commerceStorageKey('checkout', 'item')).toBe('checkout-pending:B:item');
  });

  it('响应头到达后切换账号也不会接纳旧 JSON 数据', async () => {
    const body = deferred<unknown>(); const reading = deferred<void>();
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 200, ok: true, json: () => { reading.resolve(); return body.promise; } })));
    const request = auth.getMe(); const rejected = expect(request).rejects.toMatchObject(switched);
    await reading.promise;
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    body.resolve({ accountId: 'A' }); await rejected;
    expect(shared.getAccountId()).toBe('B');
  });

  it('旧 401 错误体迟到时不清除新登录', async () => {
    const body = deferred<unknown>(); const reading = deferred<void>();
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 401, ok: false, json: () => { reading.resolve(); return body.promise; } })));
    const request = shared.requestJson('POST', '/auth/login', {});
    const rejected = expect(request).rejects.toMatchObject(switched);
    await reading.promise;
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    body.resolve({ message: 'old login rejected' }); await rejected;
    expect(shared.getAccessToken()).toBe('token-B');
  });

  it('同账号重新登录也会使旧写请求失效', async () => {
    const old = deferred<Response>();
    const fetchMock = vi.fn(async (url: string) => url.endsWith('/auth/login') ? json(200, token('A')) : old.promise);
    vi.stubGlobal('fetch', fetchMock);
    const request = shared.requestJson('POST', '/promotions/campaigns/c/claim', {});
    const rejected = expect(request).rejects.toMatchObject(switched);
    await auth.login({ username: 'A', password: 'test-only-password' });
    old.resolve(json(401, {})); await rejected;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('较早的登录回包不能覆盖较晚登录', async () => {
    const first = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(json(200, token('B'))));
    const loginA = auth.login({ username: 'A', password: 'test-only-password' });
    const rejected = expect(loginA).rejects.toMatchObject(switched);
    await auth.login({ username: 'B', password: 'test-only-password' });
    first.resolve(json(200, token('A'))); await rejected;
    expect(shared.getAccountId()).toBe('B'); expect(shared.getStoredProfileUserId()).toBe('profile-B');
  });

  it('开始退出即使旧请求失效，退出的迟到回包不清除新账号', async () => {
    const old = deferred<Response>(); const logout = deferred<Response>();
    const fetchMock = vi.fn(async (url: string) => url.endsWith('/auth/logout') ? logout.promise : old.promise);
    vi.stubGlobal('fetch', fetchMock);
    const request = shared.requestJson('GET', '/sessions/one');
    const requestRejected = expect(request).rejects.toMatchObject(switched);
    const leaving = auth.logout(); const logoutRejected = expect(leaving).rejects.toMatchObject(switched);
    old.resolve(json(200, { ok: true })); await requestRejected;
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    logout.resolve(json(200, {})); await logoutRejected;
    expect(shared.getAccountId()).toBe('B'); expect(shared.getAccessToken()).toBe('token-B');
  });

  it('退出返回 401 时不自动刷新并恢复会话', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(401, {})); vi.stubGlobal('fetch', fetchMock);
    await expect(auth.logout()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(shared.getAccessToken()).toBeNull();
  });

  it('首次加载可以用 cookie 恢复账号，初次绑定不使同一会话失效', async () => {
    shared.clearTokens();
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/refresh')) return json(200, token('A'));
      return (init.headers as Record<string, string>).Authorization === 'Bearer token-A'
        ? json(200, { accountId: 'A', username: 'A' }) : json(401, {});
    }));
    expect(await auth.getMe()).toEqual({ accountId: 'A', username: 'A' });
    expect(shared.getAccessToken()).toBe('token-A'); expect(shared.getAccountId()).toBe('A');
  });

  it('刷新 cookie 属于不同账号时不能换身份重放写请求', async () => {
    const fetchMock = vi.fn(async (url: string) => url.endsWith('/auth/refresh') ? json(200, token('B')) : json(401, {}));
    vi.stubGlobal('fetch', fetchMock);
    await expect(shared.requestJson('POST', '/checkout/orders', {})).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2); expect(shared.getAccessToken()).toBeNull();
  });

  it('切换模式会中止旧刷新，切回真实模式也不能接纳旧回包', async () => {
    const refresh = deferred<Response>(); const started = deferred<void>(); let signal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/refresh')) { signal = init.signal ?? undefined; started.resolve(); return refresh.promise; }
      return json(401, {});
    }));
    const request = shared.requestJson('GET', '/sessions/one'); const rejected = expect(request).rejects.toMatchObject(switched);
    await started.promise;
    shared.setMockMode(true); expect(signal?.aborted).toBe(true);
    shared.setMockMode(false); refresh.resolve(json(200, token('A'))); await rejected;
    expect(shared.getAccessToken()).toBeNull(); expect(shared.getAccountId()).toBeNull();
  });

  it('正常退出仍清除当前凭证及账号', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(200, {})));
    await auth.logout(); expect(shared.getAccessToken()).toBeNull(); expect(shared.getAccountId()).toBeNull();
  });

  it('旧请求网络失败时返回会话失效错误，避免调用方清空新登录', async () => {
    let reject!: (reason: unknown) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((_done, fail) => { reject = fail; })));
    const request = shared.requestJson('GET', '/auth/me'); const rejected = expect(request).rejects.toMatchObject(switched);
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    reject(new TypeError('network failure')); await rejected;
    expect(shared.getAccessToken()).toBe('token-B');
  });

  it('反馈轮询等待期间切换账号，不使用新账号查询旧反馈', async () => {
    vi.useFakeTimers(); vi.stubGlobal('window', { setTimeout });
    const fetchMock = vi.fn().mockResolvedValue(json(200, { feedback_id: 'feedback-A', accepted: true, application_status: 'PENDING' }));
    vi.stubGlobal('fetch', fetchMock);
    const client = await import('./interactionClient');
    const pending = client.waitForFeedbackApplied('feedback-A');
    const rejected = expect(pending).rejects.toMatchObject(switched);
    await vi.advanceTimersByTimeAsync(0);
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    await vi.advanceTimersByTimeAsync(1000); await rejected;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('已打开的事件流在切换账号后丢弃旧事件并取消读取', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const cancelled = vi.fn();
    const stream = new ReadableStream<Uint8Array>({ start(value) { controller = value; }, cancel: cancelled });
    const started = deferred<void>();
    vi.stubGlobal('fetch', vi.fn(async () => { started.resolve(); return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }); }));
    const onEvent = vi.fn();
    const request = shared.postEventStream('/agent/chat/stream', {}, onEvent);
    const rejected = expect(request).rejects.toMatchObject(switched);
    await started.promise; await Promise.resolve();
    shared.clearTokens(); shared.saveRealAccessToken('token-B'); shared.saveAccountId('B');
    controller.enqueue(new TextEncoder().encode('event: done\ndata: {"done":true}\n\n'));
    await rejected;
    expect(onEvent).not.toHaveBeenCalled(); expect(cancelled).toHaveBeenCalledTimes(1);
  });
});
