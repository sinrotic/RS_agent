const DEFAULT_API_BASE_URL = '/api';
const CSRF_COOKIE = 'rs_refresh_csrf';
const CSRF_HEADER = 'X-CSRF-Token';

type CredentialMode = 'real' | 'mock';

interface AccessCredential {
  mode: CredentialMode;
  token: string;
}

export const API_BASE_URL = import.meta.env.VITE_RS_AGENT_API_URL ?? DEFAULT_API_BASE_URL;

let forceMockMode = false;
let accessCredential: AccessCredential | null = null;
let authGeneration = 0;
export interface AuthSession { readonly generation: number; readonly mock: boolean; }
interface RefreshTask { session: AuthSession; promise: Promise<boolean>; controller: AbortController; }
let refreshTask: RefreshTask | null = null;
let currentAccountId: string | null = null;
const accountListeners = new Set<() => void>();
export const getAccountId = () => currentAccountId;
export function subscribeAccount(listener: () => void) {
  accountListeners.add(listener);
  return () => { accountListeners.delete(listener); };
}

function clearCommercePending() {
  try {
    const keys: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (key?.startsWith('checkout-pending:') || key?.startsWith('seckill-pending:') || key?.startsWith('refund-pending:')) keys.push(key);
    }
    keys.forEach(key => sessionStorage.removeItem(key));
  } catch { /* 禁用存储时仍可退出账号。 */ }
}

export function saveAccountId(accountId: string) {
  const changed = currentAccountId !== accountId;
  if (currentAccountId && changed) {
    invalidateAuthSession();
    clearCommercePending();
  }
  currentAccountId = accountId;
  // 旧版本没有账号范围的键不能安全归属，直接弃用。
  try {
    const keys: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (key && /^(checkout|seckill|refund)-pending:[^:]+$/.test(key)) keys.push(key);
    }
    keys.forEach(key => sessionStorage.removeItem(key));
  } catch { /* 存储不可用时仅依赖服务端记录。 */ }
  if (changed) accountListeners.forEach(listener => listener());
}

export function commerceStorageKey(kind: 'checkout' | 'seckill' | 'refund', itemId: string): string | null {
  return currentAccountId ? `${kind}-pending:${encodeURIComponent(currentAccountId)}:${encodeURIComponent(itemId)}` : null;
}

export function isMockMode(): boolean {
  if (forceMockMode) return true;
  return localStorage.getItem('rs_agent_use_mock') === 'true';
}

export function setMockMode(enabled: boolean) {
  const changed = enabled !== isMockMode();
  forceMockMode = enabled;
  localStorage.setItem('rs_agent_use_mock', enabled ? 'true' : 'false');
  if (changed) clearTokens();
}

export function getAccessToken(): string | null {
  const expectedMode: CredentialMode = isMockMode() ? 'mock' : 'real';
  return accessCredential?.mode === expectedMode ? accessCredential.token : null;
}

export function saveRealAccessToken(accessToken: string) {
  accessCredential = { mode: 'real', token: accessToken };
  removeLegacyStoredTokens();
}

export function saveMockAccessToken(accessToken: string) {
  accessCredential = { mode: 'mock', token: accessToken };
  removeLegacyStoredTokens();
}

function removeLegacyStoredTokens() {
  localStorage.removeItem('rs_access_token');
  localStorage.removeItem('rs_refresh_token');
}

export function clearTokens() {
  invalidateAuthSession();
  const changed = currentAccountId !== null;
  accessCredential = null;
  currentAccountId = null;
  clearCommercePending();
  removeLegacyStoredTokens();
  localStorage.removeItem('rs_profile_user_id');
  if (changed) accountListeners.forEach(listener => listener());
}

export function getStoredProfileUserId(): string | null {
  return localStorage.getItem('rs_profile_user_id');
}

export function saveStoredProfileUserId(profileUserId: string) {
  localStorage.setItem('rs_profile_user_id', profileUserId);
}

export function createRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function requestHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Request-ID': createRequestId(),
  };
  const token = getAccessToken();
  if (token) {
    headers.Authorization = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
  }
  return headers;
}

export function errorMessage(data: any, status: number): string {
  if (data?.error?.message) return data.error.message;
  if (data?.detail?.message) return data.detail.message;
  if (typeof data?.detail === 'string') return data.detail;
  if (data?.message) return data.message;
  return `Request failed with HTTP status ${status}`;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export class AuthSessionChangedError extends Error {
  constructor() {
    super('登录状态已变化，请在当前账号下重新操作。');
    this.name = 'AuthSessionChangedError';
  }
}

export function captureAuthSession(): AuthSession {
  return { generation: authGeneration, mock: isMockMode() };
}

export function isCurrentAuthSession(session: AuthSession): boolean {
  return session.generation === authGeneration && session.mock === isMockMode();
}

export function assertCurrentAuthSession(session: AuthSession): void {
  if (!isCurrentAuthSession(session)) throw new AuthSessionChangedError();
}

/** 账号操作改变会话；同一会话旋转 access token 不改变代次。 */
export function invalidateAuthSession(): AuthSession {
  authGeneration += 1;
  const task = refreshTask;
  refreshTask = null;
  task?.controller.abort();
  return captureAuthSession();
}

export async function mockDelay(ms = 600) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function cookieValue(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${encodeURIComponent(name)}=`;
  const pair = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith(prefix));
  return pair ? decodeURIComponent(pair.slice(prefix.length)) : null;
}

async function refreshAccessToken(session: AuthSession): Promise<boolean> {
  assertCurrentAuthSession(session);
  if (isMockMode()) return false;
  if (refreshTask && isCurrentAuthSession(refreshTask.session)) return refreshTask.promise;

  const task: RefreshTask = { session, promise: Promise.resolve(false), controller: new AbortController() };
  refreshTask = task;
  task.promise = (async () => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Request-ID': createRequestId(),
    };
    const csrfToken = cookieValue(CSRF_COOKIE);
    if (csrfToken) headers[CSRF_HEADER] = csrfToken;

    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: '{}',
        signal: task.controller.signal,
      });
      if (!isCurrentAuthSession(session) || !response.ok) return false;
      const tokens = await response.json() as { accessToken?: string; accountId?: string };
      if (!isCurrentAuthSession(session) || !tokens.accessToken) return false;
      // cookie 对应的账号不能替换一个已经绑定的当前账号。
      if (currentAccountId && tokens.accountId && currentAccountId !== tokens.accountId) return false;
      saveRealAccessToken(tokens.accessToken);
      if (tokens.accountId) saveAccountId(tokens.accountId);
      return true;
    } catch {
      return false;
    } finally {
      if (refreshTask === task) refreshTask = null;
    }
  })();

  return task.promise;
}

function canRefresh(path: string): boolean {
  return !isMockMode() && !['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout'].includes(path);
}

async function executeResponse(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  payload: unknown,
  allowRefresh: boolean,
  signal?: AbortSignal,
  session = captureAuthSession(),
): Promise<Response> {
  assertCurrentAuthSession(session);
  const headers = requestHeaders();
  const sentAuthorization = headers.Authorization;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: 'include',
      headers,
      body: payload === undefined ? undefined : JSON.stringify(payload),
      ...(signal ? { signal } : {}),
    });
  } catch (error) {
    assertCurrentAuthSession(session);
    throw error;
  }
  assertCurrentAuthSession(session);

  if (response.status === 401 && allowRefresh && canRefresh(path)) {
    const currentToken = getAccessToken();
    const currentAuthorization = currentToken
      ? (currentToken.startsWith('Bearer ') ? currentToken : `Bearer ${currentToken}`)
      : undefined;
    if (currentAuthorization && currentAuthorization !== sentAuthorization) {
      return executeResponse(method, path, payload, false, signal, session);
    }
    const refreshed = await refreshAccessToken(session);
    assertCurrentAuthSession(session);
    if (refreshed) {
      return executeResponse(method, path, payload, false, signal, session);
    }
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    assertCurrentAuthSession(session);
    if (response.status === 401) clearTokens();
    throw new ApiError(errorMessage(data, response.status), response.status);
  }
  return response;
}

async function executeRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, payload: unknown, allowRefresh: boolean,
): Promise<T> {
  const session = captureAuthSession();
  const response = await executeResponse(method, path, payload, allowRefresh, undefined, session);
  const data = await response.json().catch(() => ({})) as T;
  assertCurrentAuthSession(session);
  return data;
}

/** Uses the same credentials and pre-stream 401 refresh as ordinary API requests. */
export async function postEventStream(
  path: string, payload: unknown, onEvent: (event: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const session = captureAuthSession();
  const response = await executeResponse('POST', path, payload, true, signal, session);
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error('Agent response is not an event stream');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  try {
    while (!finished) {
      const chunk = await reader.read();
      assertCurrentAuthSession(session);
      finished = chunk.done;
      buffer += decoder.decode(chunk.value, { stream: !finished });
      if (buffer.length > 1_000_000) throw new Error('Agent stream event exceeds size limit');
      let separator: RegExpExecArray | null;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const lines = frame.split(/\r?\n/);
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message';
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        assertCurrentAuthSession(session);
        if (data) onEvent(event, JSON.parse(data) as Record<string, unknown>);
      }
    }
    if (buffer.trim()) throw new Error('Agent stream ended with an incomplete event');
    assertCurrentAuthSession(session);
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function requestJson<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  payload?: unknown,
): Promise<T> {
  return executeRequest<T>(method, path, payload, true);
}

export async function postJson<T>(path: string, payload: unknown): Promise<T> {
  return requestJson<T>('POST', path, payload);
}

export async function getJson<T>(path: string): Promise<T> {
  return requestJson<T>('GET', path);
}
