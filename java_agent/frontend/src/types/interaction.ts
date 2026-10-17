export type RecommendEventType = 'like' | 'dislike' | 'why' | 'click';

export interface RecommendExposureFeedbackRequest {
  request_id: string;
  session_id: string;
  item_ids?: string[];
  items?: Array<{
    item_id: string;
    position: number;
    visible_ratio: number;
    visible_duration_ms: number;
  }>;
  exposed_at: number;
}

export interface RecommendEventFeedbackRequest {
  request_id: string;
  session_id: string;
  item_id: string;
  event_type: RecommendEventType;
  event_value?: number;
  occurred_at: number;
}

export interface RecommendFeedbackAckVO {
  feedback_id: string;
  accepted: boolean;
  feedback_type: string;
  accepted_count: number;
  duplicate?: boolean;
  application_status: 'APPLIED' | 'PENDING' | 'NOT_APPLICABLE';
  preference_version: number;
  operation_complete?: boolean | null;
}

export interface RecommendPreferencesVO {
  preference_version: number;
  items: Array<{
    item_id: string;
    state: 'like' | 'dislike';
    category: string;
    brand: string;
    feedback_event_id: string;
    preference_version: number;
  }>;
}

export interface RecommendPreferenceClearVO extends RecommendPreferencesVO {
  operation_complete: boolean;
  operations: RecommendFeedbackAckVO[];
}
