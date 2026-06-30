const DEFAULT_API_BASE_URL = '/api';

export const API_BASE_URL = import.meta.env.VITE_RS_AGENT_API_URL ?? DEFAULT_API_BASE_URL;
// Browser-delivered tokens must stay low-privilege trial tokens; never place debug or simulation tokens in Vite env.
export const RS_AGENT_TOKEN = import.meta.env.VITE_RS_AGENT_TOKEN ?? '';

export const DEBUG_PANEL_ENABLED = import.meta.env.VITE_ENABLE_DEBUG_PANEL === 'true';

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function requestHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Request-ID': createRequestId(),
    ...(RS_AGENT_TOKEN ? { Authorization: `Bearer ${RS_AGENT_TOKEN}` } : {}),
  };
}

export function errorMessage(data: any, status: number): string {
  if (data?.error?.message) return data.error.message;
  if (data?.detail?.message) return data.detail.message;
  if (typeof data?.detail === 'string') return data.detail;
  return `Request failed with ${status}`;
}

export async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: requestHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(data, response.status));
  }
  return data as T;
}
