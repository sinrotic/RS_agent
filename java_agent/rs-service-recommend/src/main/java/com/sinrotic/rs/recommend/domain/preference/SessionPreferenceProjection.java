package com.sinrotic.rs.recommend.domain.preference;

import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import java.time.Instant;

/** 会话内某商品的最新变更及该会话偏好剩余有效期。 */
public record SessionPreferenceProjection(RecommendationFeedbackEvent event, Instant expiresAt) { }
