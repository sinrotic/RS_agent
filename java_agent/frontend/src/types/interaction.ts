export interface RecommendExposureFeedbackRequest {
  request_id: string;
  session_id: string;
  item_ids: string[];
  exposed_at: number;
}

export interface RecommendEventFeedbackRequest {
  request_id: string;
  session_id: string;
  item_id: string;
  event_type: string;
  event_value?: number;
  occurred_at: number;
}

export interface RecommendFeedbackAckVO {
  feedback_id: string;
  accepted: boolean;
  feedback_type: string;
  accepted_count: number;
}
