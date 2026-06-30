export interface DisplayResponse {
  schema_version: string;
  session_id: string;
  user_id: string;
  turn_index: number;
  assistant_message: string;
  items: DisplayItem[];
  feedback_actions: FeedbackAction[];
  ui_state: {
    image_fallback_enabled: boolean;
    can_request_more: boolean;
  };
}

export interface DisplayItem {
  parent_asin: string;
  title: string | null;
  category: string | null;
  price: string | number | null;
  rating: string | number | null;
  store: string | null;
  features: string[];
  description: string | null;
  image_url: string | null;
  badges: string[];
  summary: string | null;
}

export type FeedbackActionType = 'like' | 'dislike' | 'show_different' | 'why';

export interface FeedbackAction {
  type: FeedbackActionType;
  label: string;
}

export interface StartSessionRequest {
  user_id?: string | null;
}

export interface StartSessionResponse {
  session_id: string;
}

export interface ChatRequest {
  session_id: string;
  message: string;
}

export interface ChatResponse {
  session_id: string;
  display: DisplayResponse;
}

export interface FeedbackRequest {
  session_id: string;
  action_type: string;
  item_id?: string | null;
  comment?: string | null;
}

export interface FeedbackResponse {
  session_id: string;
  display: DisplayResponse;
}

export interface RagQueryRequest {
  query: string;
  max_chunks?: number;
}

export interface RagQueryResponse {
  query: string;
  evidence: Record<string, any>[];
  evidence_count: number;
  max_chunks: number;
  data_client: string;
}

export interface RecommendFromSequenceRequest {
  user_id?: string | null;
  user_sequence: Record<string, any>;
  feedback_text?: string | null;
  top_k?: number;
  candidate_pool_size?: number | null;
  complete_pool500?: boolean;
}

export interface RecommendationResponse {
  request_id: string;
  display: Record<string, any>;
  items: Record<string, any>[];
  candidate_count: number;
  fallback_used: boolean;
  ranking_trace?: Record<string, any>;
}

export interface RecallRequest {
  user_id?: string | null;
  user_sequence: Record<string, any>;
  candidate_pool_size?: number | null;
  prior_turn_items?: string[];
}

export interface RecallResponse {
  request_id: string;
  candidate_item_ids: string[];
  candidate_count: number;
  retrieval_summary: Record<string, any>;
}

export interface RankRequest {
  candidate_item_ids: string[];
  return_top_k?: number;
  ranking_context?: Record<string, any>;
}

export interface RankingResponse {
  ranked_item_ids: string[];
  ranking_trace: Record<string, any>;
}

export type HomeFeedEventType = 'click' | 'like' | 'dislike' | 'dwell' | 'show_different' | 'search';
export type FeedRefreshAction = 'rerank_existing' | 'rerecall_pool500' | 'no_refresh' | 'fallback_cached_or_cold';

export interface HomeFeedEventRequest {
  session_id: string;
  event_type: HomeFeedEventType;
  display_revision: number;
  event_id?: string | null;
  item_id?: string | null;
  query?: string | null;
  dwell_ms?: number | null;
  metadata?: Record<string, any>;
  top_k?: number;
  candidate_pool_size?: number | null;
}

export interface FeedRefreshDecision {
  action: FeedRefreshAction;
  decision_source: string;
  reason_code: string;
  fallback_reason: string | null;
}

export interface DisplayRefreshResponse {
  session_id: string;
  request_id: string;
  display_revision: number;
  decision: FeedRefreshDecision;
  display: DisplayResponse;
  items: DisplayItem[];
  item_count: number;
  candidate_count: number;
  fallback_used: boolean;
  public_message: string;
}

export interface SummaryDocumentInfo {
  relative_path: string | null;
  created: boolean;
  error: string | null;
}

export interface EndSessionResponse {
  session_id: string;
  status: string;
  turn_count: number;
  summary_document: SummaryDocumentInfo | null;
}

export interface DemoRoundtripRequest {
  message: string;
  feedback_action?: string;
  user_id?: string | null;
  item_id?: string | null;
  comment?: string | null;
}

export interface DemoRoundtripResponse {
  session_id: string;
  first_display: DisplayResponse;
  feedback_display: DisplayResponse;
  change_summary: {
    first_item_ids: string[];
    feedback_item_ids: string[];
    added_item_ids: string[];
    removed_item_ids: string[];
    changed: boolean;
  };
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  items?: DisplayItem[];
  turn_index?: number;
}

export interface SanitizedTimelineEvent {
  public_event_id: string;
  event_type: 'chat' | 'feedback' | 'turn';
  turn_index: number;
  user_message: string;
  assistant_message: string;
  display_response_index: number;
}

export interface PublicTimeline {
  schema_version: string;
  session_id: string;
  user_id: string;
  events: SanitizedTimelineEvent[];
}

export interface SessionExportResponse {
  session_id: string;
  user_id: string;
  turn_count: number;
  public_timeline: PublicTimeline;
  display_responses: DisplayResponse[];
}

export interface SimulationSceneRequest {
  role_id?: string;
  max_turns?: number;
  user_id?: string | null;
}

export interface SimulationRole {
  role_id: string;
  persona: string;
  shopping_goal: string;
  budget_sensitivity: string;
  category_preferences: string[];
  keyword_preferences: string[];
  negative_preferences: string[];
  decision_style: string;
  feedback_style: string;
  memory: string[];
}

export interface SimulationState {
  expressed_preferences: string[];
  seen_item_ids: string[];
  satisfaction: number;
  current_question: string | null;
  ready_to_accept: boolean;
  turns_observed: number;
  final_action: string;
  accepted_item_id: string | null;
}

export interface SimulationAction {
  type: 'chat' | 'feedback';
  turn_index: number;
  message?: string;
  action_type?: FeedbackActionType;
  item_id?: string;
  comment?: string;
}

export interface SimulationSceneMetrics {
  turn_count: number;
  action_count: number;
  final_action: string;
  accepted_item_id: string | null;
  accepted: boolean;
  feedback_count: number;
  why_count: number;
  show_different_count: number;
  unique_seen_items: number;
  satisfaction: number;
  action_counts: Record<string, number>;
}

export interface SimulationSceneResponse {
  scene_id: string;
  role: SimulationRole;
  state: SimulationState;
  actions: SimulationAction[];
  session: SessionExportResponse;
  metrics?: SimulationSceneMetrics;
}

export interface SimulationBatchRequest {
  role_ids?: string[];
  max_turns?: number;
  repeats?: number;
  user_id?: string | null;
}

export interface SimulationBatchSummary {
  scene_count: number;
  avg_turn_count: number;
  accept_rate: number;
  avg_satisfaction: number;
  avg_unique_seen_items: number;
  feedback_count: number;
  why_count: number;
  show_different_count: number;
  action_counts: Record<string, number>;
  role_count?: number;
  roles?: Record<string, any>;
}

export interface SimulationBatchResponse {
  batch_id: string;
  summary: SimulationBatchSummary;
  scenes: SimulationSceneResponse[];
}
