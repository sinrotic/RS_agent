package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * In-memory feedback sink until the event pipeline is attached.
 */
@Service
public class InMemoryRecommendFeedbackService implements RecommendFeedbackService {

    @Override
    public RecommendFeedbackAckVO recordExposure(RecommendExposureFeedbackRequestDTO request) {
        return new RecommendFeedbackAckVO(
                "fb_exp_" + UUID.randomUUID(),
                true,
                "exposure",
                request.itemIds().size()
        );
    }

    @Override
    public RecommendFeedbackAckVO recordEvent(RecommendEventFeedbackRequestDTO request) {
        return new RecommendFeedbackAckVO(
                "fb_evt_" + UUID.randomUUID(),
                true,
                request.eventType(),
                1
        );
    }
}
