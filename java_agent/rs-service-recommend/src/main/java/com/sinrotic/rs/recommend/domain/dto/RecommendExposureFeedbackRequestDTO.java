package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Request body for recommendation exposure feedback.
 */
public record RecommendExposureFeedbackRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("item_ids")
        List<String> itemIds,
        @JsonProperty("exposed_at")
        Long exposedAt,
        List<RecommendExposureItemDTO> items
) {

    public RecommendExposureFeedbackRequestDTO(
            String requestId, String sessionId, List<String> itemIds, Long exposedAt
    ) {
        this(requestId, sessionId, itemIds, exposedAt, List.of());
    }

    public RecommendExposureFeedbackRequestDTO withDefaults() {
        FeedbackRequestValidation.text(requestId, "request_id");
        FeedbackRequestValidation.text(sessionId, "session_id");
        FeedbackRequestValidation.timestamp(exposedAt, "exposed_at");
        if (items != null && items.size() > FeedbackRequestValidation.MAX_EXPOSURE_ITEMS
                || itemIds != null && itemIds.size() > FeedbackRequestValidation.MAX_EXPOSURE_ITEMS) {
            FeedbackRequestValidation.fail("每次最多提交100个曝光商品");
        }
        if (items != null) for (var item : items) {
            if (item == null) FeedbackRequestValidation.fail("items不能包含空元素");
            FeedbackRequestValidation.text(item.itemId(), "item_id");
            if (item.position() != null && item.position() <= 0) FeedbackRequestValidation.fail("position必须为正数");
            if (item.visibleRatio() != null && (!Double.isFinite(item.visibleRatio()) || item.visibleRatio() < 0 || item.visibleRatio() > 1))
                FeedbackRequestValidation.fail("visible_ratio必须在0到1之间");
            if (item.visibleDurationMs() != null && item.visibleDurationMs() < 0) FeedbackRequestValidation.fail("visible_duration_ms不能为负数");
        }
        List<String> normalized = normalizedItemIds();
        if (normalized.isEmpty()) FeedbackRequestValidation.fail("至少提交一个曝光商品");
        normalized.forEach(itemId -> FeedbackRequestValidation.text(itemId, "item_id"));
        return new RecommendExposureFeedbackRequestDTO(
                requestId,
                sessionId,
                List.copyOf(normalized),
                exposedAt,
                items == null ? List.of() : List.copyOf(items)
        );
    }

    private List<String> normalizedItemIds() {
        if (items != null && !items.isEmpty()) {
            return items.stream().map(RecommendExposureItemDTO::itemId).toList();
        }
        return itemIds == null ? List.of() : itemIds;
    }
}
