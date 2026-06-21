import type { ChatResponse, DemoRoundtripRequest, DemoRoundtripResponse, DisplayRefreshResponse, EndSessionResponse, FeedbackResponse, HomeFeedEventRequest, StartSessionResponse, SessionExportResponse, SimulationSceneRequest, SimulationSceneResponse, SimulationBatchRequest, SimulationBatchResponse } from './types';

const API_BASE_URL = import.meta.env.VITE_RS_AGENT_API_URL ?? 'http://127.0.0.1:8000';
// Browser-delivered tokens must stay low-privilege trial tokens; never place debug or simulation tokens in Vite env.
const RS_AGENT_TOKEN = import.meta.env.VITE_RS_AGENT_TOKEN ?? '';

export const DEBUG_PANEL_ENABLED = import.meta.env.VITE_ENABLE_DEBUG_PANEL === 'true';

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function requestHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Request-ID': createRequestId(),
    ...(RS_AGENT_TOKEN ? { Authorization: `Bearer ${RS_AGENT_TOKEN}` } : {}),
  };
}

function errorMessage(data: any, status: number): string {
  if (data?.error?.message) return data.error.message;
  if (data?.detail?.message) return data.detail.message;
  if (typeof data?.detail === 'string') return data.detail;
  return `Request failed with ${status}`;
}

export async function fetchSessionExport(sessionId: string): Promise<SessionExportResponse> {
  const response = await fetch(`${API_BASE_URL}/session/${sessionId}`, {
    method: 'GET',
    headers: requestHeaders(),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(data, response.status));
  }
  return data as SessionExportResponse;
}

export async function runSimulationScene(request: SimulationSceneRequest): Promise<SimulationSceneResponse> {
  return postJson<SimulationSceneResponse>('/simulation/scene', request);
}

export async function runSimulationBatch(request: SimulationBatchRequest): Promise<SimulationBatchResponse> {
  return postJson<SimulationBatchResponse>('/simulation/batch', request);
}

export async function runDemoRoundtrip(request: DemoRoundtripRequest): Promise<DemoRoundtripResponse> {
  return postJson<DemoRoundtripResponse>('/demo/e2e', request);
}

export async function startSession(userId?: string): Promise<StartSessionResponse> {
  return postJson<StartSessionResponse>('/session/start', userId ? { user_id: userId } : {});
}

export async function sendChat(sessionId: string, message: string): Promise<ChatResponse> {
  return postJson<ChatResponse>('/chat', { session_id: sessionId, message });
}

export async function sendFeedback(sessionId: string, actionType: string, itemId?: string, comment?: string): Promise<FeedbackResponse> {
  return postJson<FeedbackResponse>('/feedback', {
    session_id: sessionId,
    action_type: actionType,
    ...(itemId ? { item_id: itemId } : {}),
    ...(comment ? { comment } : {}),
  });
}

export async function refreshFeed(request: HomeFeedEventRequest): Promise<DisplayRefreshResponse> {
  return postJson<DisplayRefreshResponse>('/feed/refresh', request);
}

export async function endSession(sessionId: string, reason = 'manual', clientEvent = 'manual', writeSummary = true): Promise<EndSessionResponse> {
  return postJson<EndSessionResponse>('/session/end', {
    session_id: sessionId,
    reason,
    client_event: clientEvent,
    write_summary: writeSummary,
  });
}

export function endSessionKeepalive(sessionId: string, reason = 'pagehide', clientEvent = 'pagehide'): void {
  if (!sessionId) return;
  const payload = JSON.stringify({
    session_id: sessionId,
    reason,
    client_event: clientEvent,
    write_summary: true,
  });
  try {
    void fetch(`${API_BASE_URL}/session/end`, {
      method: 'POST',
      headers: requestHeaders(),
      body: payload,
      keepalive: true,
    });
  } catch {
    // Page-exit best effort only.
  }
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
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
