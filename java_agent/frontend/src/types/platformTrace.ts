export interface PlatformAccountProfileVO {
  account_id: string;
  profile_user_id: string;
  profile_summary: string;
  top_categories: string[];
  top_stores: string[];
}

export interface RecommendTraceItemVO {
  item_id: string;
  final_rank: number;
  final_score: number;
  recall_sources: string[];
  reason: string;
}

export interface RecommendTraceVO {
  request_id: string;
  session_id: string;
  profile_user_id: string;
  scene: string;
  stage_counts: Record<string, number>;
  source_distribution: Record<string, number>;
  items: RecommendTraceItemVO[];
}

export interface AgentTurnVO {
  request_id: string;
  user_message: string;
  assistant_message: string;
  tool_calls: string[];
  recommended_item_ids: string[];
}

export interface AgentSessionTraceVO {
  session_id: string;
  turns: AgentTurnVO[];
}

export interface PlatformInteractionEventVO {
  event_id: string;
  session_id: string;
  request_id: string;
  item_id: string;
  event_type: string;
  event_value?: number;
  occurred_at: string;
  metadata: Record<string, unknown>;
}

export interface PlatformTimelineEventVO {
  event_id: string;
  session_id: string;
  request_id: string;
  event_type: string;
  source: string;
  entity_id: string;
  summary: string;
  occurred_at: string;
  data: Record<string, unknown>;
}

export interface AgentTraceEventVO {
  event_id: string;
  session_id: string;
  request_id: string;
  event_type: string;
  tool_call_id: string;
  tool_name: string;
  agent_name: string;
  model_provider: string;
  model_name: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cache_read_input_tokens?: number;
  cache_write_input_tokens?: number;
  data: Record<string, unknown>;
  created_at: string;
}

export type AgentRunStatus = 'running' | 'success' | 'failed' | 'partial';

export interface AgentRunSummaryVO {
  total_latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  model_provider: string;
  model_name: string;
  tool_call_count: number;
  error_count: number;
  recommend_item_count: number;
  has_final_answer: boolean;
}

export interface AgentRunPhaseVO {
  phase: string;
  status: AgentRunStatus | string;
  event_count: number;
  latency_ms: number;
  total_tokens: number;
}

export interface AgentRunEventVO {
  event_id: string;
  session_id: string;
  request_id: string;
  event_type: string;
  phase: string;
  status: AgentRunStatus | string;
  tool_call_id: string;
  tool_name: string;
  agent_name: string;
  model_provider: string;
  model_name: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  error_code: string;
  error_message: string;
  input_summary: string;
  output_summary: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface AgentRunRelatedTraceVO {
  agent_turn_count: number;
  recommend_request_ids: string[];
  interaction_event_count: number;
}

export interface AgentRunMonitorVO {
  session_id: string;
  request_id: string;
  status: AgentRunStatus;
  summary: AgentRunSummaryVO;
  phases: AgentRunPhaseVO[];
  events: AgentRunEventVO[];
  quality_signals: string[];
  related_traces: AgentRunRelatedTraceVO;
}

export interface PlatformSessionOverviewVO {
  session_id: string;
  account_profile: PlatformAccountProfileVO;
  agent_trace: AgentSessionTraceVO;
  recommend_traces: RecommendTraceVO[];
  interaction_events: PlatformInteractionEventVO[];
  timeline: PlatformTimelineEventVO[];
}
