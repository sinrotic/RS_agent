package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/recommend/feedback/status")
public class RecommendFeedbackStatusController {

    private final RecommendationFeedbackEventStore eventStore;

    public RecommendFeedbackStatusController(RecommendationFeedbackEventStore eventStore) {
        this.eventStore = eventStore;
    }

    @GetMapping("/{eventId}")
    public RecommendFeedbackAckVO status(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @PathVariable String eventId
    ) {
        var event = eventStore.findByEventId(eventId).orElse(null);
        if (event == null || !event.identity().accountId().equals(accountId)
                || !event.identity().profileUserId().equals(profileUserId)) {
            return new RecommendFeedbackAckVO("", false, "status", 0);
        }
        return new RecommendFeedbackAckVO(
                event.eventId(), true, event.eventType().apiValue(), 0, false,
                eventStore.projectionStatus(eventId), event.preferenceVersion());
    }
}
