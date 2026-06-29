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

export interface PlatformSessionOverviewVO {
  session_id: string;
  account_profile: PlatformAccountProfileVO;
  agent_trace: AgentSessionTraceVO;
  recommend_traces: RecommendTraceVO[];
  interaction_events: PlatformInteractionEventVO[];
  timeline: PlatformTimelineEventVO[];
}
