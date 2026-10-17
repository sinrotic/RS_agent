package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;

public interface OnlinePreferenceStore {
    OnlinePreferenceSnapshot apply(RecommendationFeedbackEvent event);

    OnlinePreferenceSnapshot load(RecommendationIdentity identity);

    OnlinePreferenceSnapshot loadProfile(String profileUserId);

    default OnlinePreferenceSnapshot applyReversal(RecommendationFeedbackEvent reversal) {
        return applyReversal(reversal, null);
    }

    OnlinePreferenceSnapshot applyReversal(
            RecommendationFeedbackEvent reversal,
            RecommendationFeedbackEvent restoredPreferenceEvent
    );

    default OnlinePreferenceSnapshot applyReversal(RecommendationFeedbackEvent reversal,
            RecommendationFeedbackEvent profileRestored, RecommendationFeedbackEvent sessionRestored) {
        return applyReversal(reversal, profileRestored);
    }

    void restoreProfile(RecommendationFeedbackEvent event, RecommendationFeedbackEvent restored);

    void restoreSession(RecommendationFeedbackEvent event, RecommendationFeedbackEvent restored,
                        java.time.Instant expiresAt);
}
