import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearTokens,
  getAccessToken,
  requestHeaders,
  requestJson,
  saveMockAccessToken,
  saveRealAccessToken,
  setMockMode,
} from './shared';

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('browser authentication session', () => {
  let storage: MemoryStorage;

  beforeEach(() => {
    storage = new MemoryStorage();
    vi.stubGlobal('localStorage', storage);
    vi.stubGlobal('document', { cookie: 'rs_refresh_csrf=csrf-token' });
    clearTokens();
    setMockMode(false);
  });

  afterEach(() => {
    clearTokens();
    vi.unstubAllGlobals();
  });

  it('keeps access and refresh credentials out of localStorage', () => {
    saveRealAccessToken('real-access');

    expect(getAccessToken()).toBe('real-access');
    expect(storage.getItem('rs_access_token')).toBeNull();
    expect(storage.getItem('rs_refresh_token')).toBeNull();
  });

  it('coalesces concurrent unauthorized responses into one cookie refresh', async () => {
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = init?.headers as Record<string, string> | undefined;
      if (url.endsWith('/auth/refresh')) {
        refreshCalls += 1;
        expect(init?.credentials).toBe('include');
        expect(headers?.['X-CSRF-Token']).toBe('csrf-token');
        await Promise.resolve();
        return jsonResponse(200, { accessToken: 'rotated-access' });
      }
      if (headers?.Authorization === 'Bearer rotated-access') {
        return jsonResponse(200, { path: url });
      }
      return jsonResponse(401, { message: 'expired' });
    });
    vi.stubGlobal('fetch', fetchMock);

    await Promise.all([
      requestJson('GET', '/sessions/one'),
      requestJson('GET', '/sessions/two'),
    ]);

    expect(refreshCalls).toBe(1);
    expect(getAccessToken()).toBe('rotated-access');
  });

  it('clears the in-memory access token when cookie refresh fails', async () => {
    saveRealAccessToken('expired-access');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      return String(input).endsWith('/auth/refresh')
        ? jsonResponse(401, { message: 'revoked' })
        : jsonResponse(401, { message: 'expired' });
    }));

    await expect(requestJson('GET', '/sessions/one')).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
  });

  it('never sends a mock token after switching to the real backend', () => {
    setMockMode(true);
    saveMockAccessToken('mock-access');
    setMockMode(false);

    expect(requestHeaders()).not.toHaveProperty('Authorization');
  });
});
