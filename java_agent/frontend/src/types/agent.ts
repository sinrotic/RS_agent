import { RecommendItemVO } from './recommend';

export interface AgentChatRequest {
  sessionId: string;
  message: string;
}

export interface AgentChatResponse {
  requestId?: string;
  sessionId: string;
  assistantMessage: string;
  items: RecommendItemVO[];
  evidence?: any[];
  turnIndex: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  items?: RecommendItemVO[];
  turnIndex?: number;
}
