package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;

/**
 * Records recommendation feedback from app clients.
 */
public interface RecommendFeedbackService {

    RecommendFeedbackAckVO recordExposure(RecommendExposureFeedbackRequestDTO request);

    RecommendFeedbackAckVO recordEvent(RecommendEventFeedbackRequestDTO request);
}
