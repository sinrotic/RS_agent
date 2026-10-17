import { StartSessionResponse, EndSessionResponse, UserSession } from '../types/session';
import { isMockMode, postJson, getJson, requestHeaders, API_BASE_URL, mockDelay } from './shared';

export async function startSession(_userId?: string, entryScene = 'web'): Promise<StartSessionResponse> {
  if (isMockMode()) {
    await mockDelay(300);
    return {
      sessionId: `jsess-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    };
  }

  return postJson<StartSessionResponse>('/sessions', { entryScene });
}

export async function listSessions(): Promise<UserSession[]> {
  if (isMockMode()) return [];
  return getJson<UserSession[]>('/sessions?entryScene=agent_chat&limit=50');
}

export async function getSession(sessionId: string): Promise<UserSession> {
  return getJson<UserSession>(`/sessions/${encodeURIComponent(sessionId)}`);
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
