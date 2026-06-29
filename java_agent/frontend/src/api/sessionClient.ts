import { StartSessionResponse, EndSessionResponse } from '../types/session';
import { isMockMode, postJson, requestHeaders, API_BASE_URL, mockDelay } from './shared';

export async function startSession(userId?: string): Promise<StartSessionResponse> {
  if (isMockMode()) {
    await mockDelay(300);
    return {
      sessionId: `jsess-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    };
  }

  // Real request to Java Endpoint: rs-service-user -> POST /api/sessions (if route is configured in Gateway)
  // If the UserSessionController doesn't have post mapped, it will return error, which will be caught and can fall back.
  return postJson<StartSessionResponse>('/sessions', userId ? { profileUserId: userId } : {});
}

export async function endSession(sessionId: string, reason = 'manual'): Promise<EndSessionResponse> {
  if (isMockMode()) {
    await mockDelay(400);
    return {
      sessionId,
      status: 'SUCCESS',
      turnCount: 5,
      summaryDocument: {
        relativePath: `export/session_${sessionId}_summary.md`,
        created: true,
        error: null,
      },
    };
  }

  return postJson<EndSessionResponse>(`/sessions/end`, { sessionId, reason });
}

export function endSessionKeepalive(sessionId: string, reason = 'pagehide'): void {
  if (!sessionId) return;
  if (isMockMode()) return;

  const payload = JSON.stringify({
    sessionId,
    reason,
  });
  try {
    void fetch(`${API_BASE_URL}/sessions/end`, {
      method: 'POST',
      headers: requestHeaders(),
      body: payload,
      keepalive: true,
    });
  } catch {
    // Page-exit best effort only.
  }
}
