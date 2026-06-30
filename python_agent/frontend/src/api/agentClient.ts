import type { ChatResponse, EndSessionResponse, FeedbackResponse, SessionExportResponse, StartSessionResponse } from '../types';
import { API_BASE_URL, errorMessage, postJson, requestHeaders } from './shared';

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
