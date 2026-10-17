package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.service.OnlinePreferenceStore;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import com.sinrotic.rs.recommend.service.RecommendationSessionValidator;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.Optional;

/** 对话、浏览和反馈共用 User 的活动期限；读取偏好或后台重建本身不延长会话。 */
@Service
public class SessionPreferenceReader {
    private final RecommendationFeedbackEventStore events;
    private final OnlinePreferenceStore preferences;
    private final RecommendationSessionValidator sessions;

    public SessionPreferenceReader(RecommendationFeedbackEventStore events, OnlinePreferenceStore preferences,
                                   RecommendationSessionValidator sessions) {
        this.events = events;
        this.preferences = preferences;
        this.sessions = sessions;
    }

    public Optional<Instant> activeUntil(RecommendationIdentity identity) {
        try {
            return Optional.of(sessions.activeUntil(identity.accountId(),identity.profileUserId(),identity.sessionId()));
        } catch (ResponseStatusException ended) {
            if (ended.getStatusCode().value() == 404 || ended.getStatusCode().value() == 410) return Optional.empty();
            throw ended;
        }
    }

    public java.util.List<com.sinrotic.rs.recommend.domain.preference.ActiveRecommendationSession> activeSessions(
            String afterSessionId, int limit) {
        return sessions.activeSessions(afterSessionId,limit);
    }

    public java.util.List<RecommendationFeedbackEvent> events(RecommendationIdentity identity, String afterItemId, int limit) {
        return events.currentSessionEvents(identity,afterItemId,limit);
    }

    public void restore(RecommendationIdentity identity) {
        // 请求读取失败时不静默降为弱偏好，否则被明确排除的商品可能重新出现。
        Instant expiry = sessions.activeUntil(identity.accountId(),identity.profileUserId(),identity.sessionId());
        String cursor = "";
        while (true) {
            var page = events.currentSessionEvents(identity,cursor,1000);
            for (var event : page) restore(event,expiry);
            if (page.size() < 1000) return;
            cursor = page.getLast().item().itemId();
        }
    }

    public void restore(RecommendationFeedbackEvent event, Instant expiry) {
        RecommendationFeedbackEvent restored = null;
        if (event.eventType() == FeedbackEventType.REVERSAL) {
            var target = events.findByEventId(event.reversesEventId()).orElseThrow();
            restored = events.previousSessionExplicitEvent(target).orElse(null);
        }
        preferences.restoreSession(event,restored,expiry);
    }
}
