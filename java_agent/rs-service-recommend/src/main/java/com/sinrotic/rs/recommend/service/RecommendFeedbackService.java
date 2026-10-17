package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendFeedbackReversalRequestDTO;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;

/**
 * Records recommendation feedback from app clients.
 */
public interface RecommendFeedbackService {

    RecommendFeedbackAckVO recordExposure(RecommendExposureFeedbackRequestDTO request);

    RecommendFeedbackAckVO recordEvent(RecommendEventFeedbackRequestDTO request);

    default RecommendFeedbackAckVO recordExposure(
            RecommendationIdentity identity,
            RecommendExposureFeedbackRequestDTO request
    ) {
        return recordExposure(request);
    }

    default RecommendFeedbackAckVO recordEvent(
            RecommendationIdentity identity,
            RecommendEventFeedbackRequestDTO request
    ) {
        return recordEvent(request);
    }

    default RecommendFeedbackAckVO reverse(
            RecommendationIdentity identity,
            RecommendFeedbackReversalRequestDTO request
    ) {
        return new RecommendFeedbackAckVO("", false, "reversal", 0);
    }
}
