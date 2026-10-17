import { RecommendItemVO } from './recommend';
import { A2uiMessage } from '../utils/a2ui';

export interface AgentAnswerBlock {
  type: 'text' | 'product_cards' | 'comparison_table' | 'followup_question' | 'a2ui';
  content?: string;
  card_set_id?: string;
  item_ids?: string[];
  layout?: string;
  messages?: A2uiMessage[];
}

export interface AgentChatRequest {
  session_id: string;
  profile_user_id: string;
  user_message: string;
  limit: number;
  context: Record<string, unknown>;
}

export interface AgentChatResponse {
  requestId: string;
  sessionId: string;
  profileUserId: string;
  cardSetId: string;
  turnIndex: number;
  assistantMessage: string;
  items: RecommendItemVO[];
  toolCalls: unknown[];
  answerBlocks?: AgentAnswerBlock[];
  degradationReasons?: string[];
}

export interface AgentRecommendedItemWire {
  item_id: string;
  title: string | null;
  category: string | null;
  score: number;
  reason: string | null;
}

export interface AgentChatWireResponse {
  request_id: string;
  session_id: string;
  profile_user_id: string;
  card_set_id?: string;
  turn_index: number;
  assistant_message: string;
  recommended_items: AgentRecommendedItemWire[];
  tool_calls?: unknown[];
  answer_blocks?: AgentAnswerBlock[];
  degradation_reasons?: string[];
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  items?: RecommendItemVO[];
  turnIndex?: number;
}

export interface AgentHistory {
  session_id: string;
  turns: Array<{
    request_id: string;
    turn_index: number;
    user_message: string;
    assistant_message: string;
    recommended_item_ids: string[];
    answer_blocks: AgentAnswerBlock[];
    finish_reason: string;
    card_set_id: string;
    degradation_reasons?: string[];
  }>;
}
