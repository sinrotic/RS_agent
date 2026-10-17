export interface StartSessionResponse {
  sessionId: string;
}

export interface UserSession {
  sessionId: string;
  accountId: string;
  profileUserId: string;
  entryScene: string;
  status: string;
  startedAt: string;
  lastActiveAt: string;
}

export interface SummaryDocumentInfo {
  relativePath: string | null;
  created: boolean;
  error: string | null;
}

export interface EndSessionResponse {
  sessionId: string;
  status: string;
  turnCount: number;
  summaryDocument: SummaryDocumentInfo | null;
}
