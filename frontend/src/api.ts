import type { ChatResponse, DemoRoundtripRequest, DemoRoundtripResponse, FeedbackResponse, StartSessionResponse, SessionExportResponse, SimulationSceneRequest, SimulationSceneResponse, SimulationBatchRequest, SimulationBatchResponse } from './types';

const API_BASE_URL = import.meta.env.VITE_RS_AGENT_API_URL ?? 'http://127.0.0.1:8000';

export async function fetchSessionExport(sessionId: string): Promise<SessionExportResponse> {
  const response = await fetch(`${API_BASE_URL}/session/${sessionId}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.error?.message ?? data?.detail ?? `Request failed with ${response.status}`;
    throw new Error(message);
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

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.error?.message ?? data?.detail ?? `Request failed with ${response.status}`;
    throw new Error(message);
  }
  return data as T;
}
