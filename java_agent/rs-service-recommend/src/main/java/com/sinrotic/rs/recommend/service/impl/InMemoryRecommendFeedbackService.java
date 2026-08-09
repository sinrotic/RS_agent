package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.UUID;

/**
 * In-memory feedback sink until the event pipeline is attached.
 */
@Service
public class InMemoryRecommendFeedbackService implements RecommendFeedbackService {

    private static final Set<String> SUPPORTED_EVENT_TYPES = Set.of("click", "like", "dislike", "why");

    private final Set<String> acceptedFeedbackKeys = ConcurrentHashMap.newKeySet();

    @Override
    public RecommendFeedbackAckVO recordExposure(RecommendExposureFeedbackRequestDTO request) {
        List<String> itemIds = request.itemIds().stream()
                .filter(itemId -> itemId != null && !itemId.isBlank())
                .distinct()
                .toList();
        if (isBlank(request.requestId()) || isBlank(request.sessionId()) || itemIds.isEmpty()) {
            return rejected("exposure");
        }
        String key = feedbackKey("exposure", request.requestId(), request.sessionId(), itemIds);
        if (!acceptedFeedbackKeys.add(key)) {
            return new RecommendFeedbackAckVO(
                    key,
                    true,
                    "exposure",
                    0,
                    true
            );
        }
        return new RecommendFeedbackAckVO(
                "fb_exp_" + UUID.randomUUID(),
                true,
                "exposure",
                itemIds.size(),
                false
        );
    }

    @Override
    public RecommendFeedbackAckVO recordEvent(RecommendEventFeedbackRequestDTO request) {
        if (isBlank(request.requestId()) || isBlank(request.sessionId()) || isBlank(request.itemId())
                || isBlank(request.eventType())) {
            return rejected("invalid");
        }
        String eventType = request.eventType().toLowerCase(Locale.ROOT);
        if (!SUPPORTED_EVENT_TYPES.contains(eventType)) {
            return rejected(eventType);
        }
        String key = feedbackKey("event", request.requestId(), request.sessionId(),
                List.of(request.itemId(), eventType));
        if (!acceptedFeedbackKeys.add(key)) {
            return new RecommendFeedbackAckVO(
                    key,
                    true,
                    eventType,
                    0,
                    true
            );
        }
        return new RecommendFeedbackAckVO(
                "fb_evt_" + UUID.randomUUID(),
                true,
                eventType,
                1,
                false
        );
    }

    private String feedbackKey(String kind, String requestId, String sessionId, List<String> values) {
        if (!isBlank(requestId)) {
            return kind + "|" + sessionId + "|" + requestId;
        }
        return kind + "|-|-|" + String.join(",", values);
    }

    private RecommendFeedbackAckVO rejected(String feedbackType) {
        return new RecommendFeedbackAckVO(
                "fb_evt_" + UUID.randomUUID(),
                false,
                feedbackType,
                0,
                false
        );
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
