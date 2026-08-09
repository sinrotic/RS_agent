package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendFeedbackService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
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

    @Test
    void duplicateExposureIsAcknowledgedWithoutCountingAgain() {
        InMemoryRecommendFeedbackService service = new InMemoryRecommendFeedbackService();
        var request = new RecommendExposureFeedbackRequestDTO(
                "rec_req_002",
                "sess_002",
                List.of("B001", "B001", "B002"),
                1782636400000L
        ).withDefaults();

        var first = service.recordExposure(request);
        var duplicate = service.recordExposure(request);

        assertEquals(2, first.acceptedCount());
        assertTrue(duplicate.accepted());
        assertTrue(duplicate.duplicate());
        assertEquals(0, duplicate.acceptedCount());
    }

    @Test
    void likeDislikeAndWhyHaveExplicitEventSemantics() {
        InMemoryRecommendFeedbackService service = new InMemoryRecommendFeedbackService();

        var like = service.recordEvent(event("like"));
        var dislike = service.recordEvent(event("dislike"));
        var why = service.recordEvent(event("why"));

        assertTrue(like.accepted());
        assertTrue(dislike.accepted());
        assertTrue(why.accepted());
        assertEquals("why", why.feedbackType());
        assertEquals(1, why.acceptedCount());
    }

    @Test
    void unsupportedEventIsRejected() {
        InMemoryRecommendFeedbackService service = new InMemoryRecommendFeedbackService();

        var response = service.recordEvent(event("rerank"));

        assertFalse(response.accepted());
        assertEquals(0, response.acceptedCount());
    }

    private RecommendEventFeedbackRequestDTO event(String eventType) {
        return new RecommendEventFeedbackRequestDTO(
                "rec_req_" + eventType,
                "sess_003",
                "B003",
                eventType,
                1.0,
                1782636410000L
        ).withDefaults();
    }
}
