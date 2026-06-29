package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendFeedbackService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class InMemoryRecommendFeedbackServiceTest {

    @Test
    void recordExposureAcknowledgesAllItems() {
        InMemoryRecommendFeedbackService service = new InMemoryRecommendFeedbackService();

        var response = service.recordExposure(new RecommendExposureFeedbackRequestDTO(
                "rec_req_001",
                "sess_001",
                List.of("B001", "B002"),
                1782636400000L
        ).withDefaults());

        assertTrue(response.accepted());
        assertEquals("exposure", response.feedbackType());
        assertEquals(2, response.acceptedCount());
    }

    @Test
    void recordEventAcknowledgesSingleEventType() {
        InMemoryRecommendFeedbackService service = new InMemoryRecommendFeedbackService();

        var response = service.recordEvent(new RecommendEventFeedbackRequestDTO(
                "rec_req_001",
                "sess_001",
                "B001",
                "click",
                1.0,
                1782636410000L
        ).withDefaults());

        assertTrue(response.accepted());
        assertEquals("click", response.feedbackType());
        assertEquals(1, response.acceptedCount());
    }
}
