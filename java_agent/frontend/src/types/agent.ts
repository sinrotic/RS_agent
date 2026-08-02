import { RecommendItemVO } from './recommend';

export interface AgentChatRequest {
  session_id: string;
  profile_user_id: string;
  user_message: string;
  limit?: number;
  context?: Record<string, unknown>;
}

export interface AgentRecommendedItemVO {
  item_id: string;
  title: string;
  category: string;
  score: number;
  reason: string;
}

export interface AgentChatResponse {
  request_id: string;
  session_id: string;
  profile_user_id: string;
  turn_index: number;
  assistant_message: string;
  recommended_items: AgentRecommendedItemVO[];
  tool_calls: unknown[];
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  items?: RecommendItemVO[];
  turnIndex?: number;
}
