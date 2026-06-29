const DEFAULT_API_BASE_URL = '/api';

export const API_BASE_URL = import.meta.env.VITE_RS_AGENT_API_URL ?? DEFAULT_API_BASE_URL;

// Mode toggle: whether to force mock mode even if the gateway is running.
// This is extremely helpful because some microservices (like rs-service-agent) do not have Java controllers implemented.
let forceMockMode = false;

export function isMockMode(): boolean {
  if (forceMockMode) return true;
  // If we can't find token and we're local, fallback to mock if backend not running
  const mockConfig = localStorage.getItem('rs_agent_use_mock');
  return mockConfig === 'true';
}

export function setMockMode(enabled: boolean) {
  forceMockMode = enabled;
  localStorage.setItem('rs_agent_use_mock', enabled ? 'true' : 'false');
}

export function getAccessToken(): string | null {
  return localStorage.getItem('rs_access_token');
}

export function getRefreshToken(): string | null {
  return localStorage.getItem('rs_refresh_token');
}

export function saveTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem('rs_access_token', accessToken);
  localStorage.setItem('rs_refresh_token', refreshToken);
}

export function clearTokens() {
  localStorage.removeItem('rs_access_token');
  localStorage.removeItem('rs_refresh_token');
  localStorage.removeItem('rs_profile_user_id');
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

export function requestHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Request-ID': createRequestId(),
  };
  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
  }
  return headers;
}

export function errorMessage(data: any, status: number): string {
  if (data?.error?.message) return data.error.message;
  if (data?.detail?.message) return data.detail.message;
  if (typeof data?.detail === 'string') return data.detail;
  if (data?.message) return data.message;
  return `请求失败，HTTP 状态码: ${status}`;
}

export async function mockDelay(ms = 600) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function requestJson<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  payload?: unknown
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: requestHeaders(),
    body: payload ? JSON.stringify(payload) : undefined,
  });

  // Handle Token Expiry (401 Unauthorized)
  if (response.status === 401) {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        const refreshRes = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refreshToken }),
        });
        if (refreshRes.ok) {
          const tokenData = await refreshRes.json();
          saveTokens(tokenData.accessToken, tokenData.refreshToken);
          // Retry the request
          return requestJson<T>(method, path, payload);
        }
      } catch (e) {
        clearTokens();
        throw new Error('会话过期，请重新登录');
      }
    }
    clearTokens();
    throw new Error('无权限，请登录');
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(data, response.status));
  }
  return data as T;
}

export async function postJson<T>(path: string, payload: unknown): Promise<T> {
  return requestJson<T>('POST', path, payload);
}

export async function getJson<T>(path: string): Promise<T> {
  return requestJson<T>('GET', path);
}
