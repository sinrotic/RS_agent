package com.sinrotic.rs.recommend.domain.feedback;

public record FeedbackAppendResult(RecommendationFeedbackEvent event, boolean duplicate) {
}
