import { RecommendExposureFeedbackRequest, RecommendEventFeedbackRequest, RecommendFeedbackAckVO } from '../types/interaction';
import { isMockMode, postJson } from './shared';

export async function recordExposure(req: RecommendExposureFeedbackRequest): Promise<RecommendFeedbackAckVO> {
  if (isMockMode()) {
    return {
      feedback_id: `expose-${Math.random().toString(36).substring(2, 9)}`,
      accepted: true,
      feedback_type: 'EXPOSURE',
      accepted_count: req.item_ids.length,
      duplicate: false
    };
  }

  // Real request to Java Endpoint: rs-service-recommend -> POST /api/recommend/feedback/exposure
  return postJson<RecommendFeedbackAckVO>('/recommend/feedback/exposure', req);
}

export async function recordEvent(req: RecommendEventFeedbackRequest): Promise<RecommendFeedbackAckVO> {
  if (isMockMode()) {
    return {
      feedback_id: `event-${Math.random().toString(36).substring(2, 9)}`,
      accepted: true,
      feedback_type: req.event_type.toUpperCase(),
      accepted_count: 1,
      duplicate: false
    };
  }

  // Real request to Java Endpoint: rs-service-recommend -> POST /api/recommend/feedback/event
  return postJson<RecommendFeedbackAckVO>('/recommend/feedback/event', req);
}
