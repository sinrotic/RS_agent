package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.service.OnlinePreferenceStore;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import java.time.Clock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Component
public class FeedbackProjectionRetryWorker {
    private static final Logger log = LoggerFactory.getLogger(FeedbackProjectionRetryWorker.class);

    private final RecommendationFeedbackEventStore eventStore;
    private final OnlinePreferenceStore preferenceStore;
    private final RecommendationFeedbackMetrics metrics;
    private String rebuildProfileCursor = "";
    private String rebuildItemCursor = "";
    private String sessionProfileCursor = "";
    private String sessionCursor = "";
    private String sessionItemCursor = "";
    private final Clock clock;
    private SessionPreferenceReader sessionPreferenceReader;
    private String activeSessionCursor = "";
    private com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity unfinishedSession;
    private String activeSessionItemCursor = "";

    @Autowired
    public void setSessionPreferenceReader(SessionPreferenceReader reader) { this.sessionPreferenceReader = reader; }

    @Autowired
    public FeedbackProjectionRetryWorker(
            RecommendationFeedbackEventStore eventStore,
            OnlinePreferenceStore preferenceStore,
            RecommendationFeedbackMetrics metrics
    ) {
        this(eventStore,preferenceStore,metrics,Clock.systemUTC());
    }

    public FeedbackProjectionRetryWorker(RecommendationFeedbackEventStore eventStore,
            OnlinePreferenceStore preferenceStore, RecommendationFeedbackMetrics metrics,Clock clock) {
        this.eventStore = eventStore;
        this.preferenceStore = preferenceStore;
        this.metrics = metrics;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "${rs.recommend.feedback.outbox.retry-delay:5000}")
    public void retryPending() {
        for (var event : eventStore.pendingProjectionEvents(100)) {
            try {
                project(event);
                eventStore.markProjectionApplied(event.eventId());
                metrics.projectionRetry(true);
            } catch (RuntimeException ignored) {
                eventStore.markProjectionFailed(event.eventId(), ignored.getMessage());
                metrics.projectionRetry(false);
            }
        }
    }

    @Scheduled(fixedDelayString = "${rs.recommend.feedback.projection.rebuild-delay:60000}")
    public synchronized void rebuildCurrentPreferences() {
        rebuildProfiles();
        rebuildSessions();
    }

    private void rebuildProfiles() {
        var page = eventStore.rebuildablePreferenceEvents(rebuildProfileCursor, rebuildItemCursor, 1000);
        for (var event : page) {
            try {
                preferenceStore.restoreProfile(event, restored(event,false));
                metrics.projectionRebuild("profile", true);
            } catch (RuntimeException failure) {
                metrics.projectionRebuild("profile", false);
                log.warn("画像偏好重建失败，后续扫描继续，下一扫描周期重试：eventId={}", event.eventId(), failure);
            }
            // 权威投影会在扫描结束后重新遍历；单项失败不能卡住其他用户，也不能永久跳过。
            rebuildProfileCursor = event.identity().profileUserId();
            rebuildItemCursor = event.item().itemId();
        }
        if (page.size() < 1000) {
            rebuildProfileCursor = "";
            rebuildItemCursor = "";
        }
    }

    private void rebuildSessions() {
        if (sessionPreferenceReader != null) {
            rebuildActiveSessions();
            return;
        }
        var page = eventStore.rebuildableSessionPreferences(sessionProfileCursor,sessionCursor,sessionItemCursor,
                clock.instant().minus(PreferenceProjectionSupport.SESSION_TTL),1000);
        for (var projection : page) {
            var event = projection.event();
            try {
                preferenceStore.restoreSession(event,restored(event,true),projection.expiresAt());
                metrics.projectionRebuild("session", true);
            } catch (RuntimeException failure) {
                metrics.projectionRebuild("session", false);
                log.warn("会话偏好重建失败，后续扫描继续，下一扫描周期重试：eventId={}", event.eventId(), failure);
            }
            sessionProfileCursor = event.identity().profileUserId();
            sessionCursor = event.identity().sessionId();
            sessionItemCursor = event.item().itemId();
        }
        if (page.size() < 1000) {sessionProfileCursor = "";sessionCursor = "";sessionItemCursor = "";}
    }

    private void rebuildActiveSessions() {
        // 每轮至多 50 个活跃会话和 1000 条偏好；直接查询 User，避免逐个验证整个历史反馈仓库。
        int remaining = 1000;
        if (unfinishedSession != null) {
            var expiry = sessionPreferenceReader.activeUntil(unfinishedSession);
            if (expiry.isPresent()) remaining -= rebuildSessionPage(unfinishedSession,expiry.get(),remaining);
            else finishActiveSession(unfinishedSession);
            if (unfinishedSession != null) return;
        }
        var sessions = sessionPreferenceReader.activeSessions(activeSessionCursor,50);
        for (var session : sessions) {
            remaining -= rebuildSessionPage(session.identity(),session.expiresAt(),remaining);
            if (unfinishedSession != null || remaining == 0) return;
        }
        if (sessions.size() < 50) activeSessionCursor = "";
    }

    private int rebuildSessionPage(com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity identity,
                                   java.time.Instant expiry, int limit) {
        java.util.List<com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent> page;
        try {
            page = sessionPreferenceReader.events(identity,activeSessionItemCursor,limit);
        } catch (RuntimeException failure) {
            metrics.projectionRebuild("session",false);
            log.warn("会话偏好事实读取失败，后续会话继续，下一扫描周期重试：sessionId={}",identity.sessionId(),failure);
            finishActiveSession(identity);
            return 0;
        }
        for (var event : page) {
            try {
                sessionPreferenceReader.restore(event,expiry);
                metrics.projectionRebuild("session",true);
            } catch (RuntimeException failure) {
                metrics.projectionRebuild("session",false);
                log.warn("活跃会话偏好重建失败，后续扫描继续，下一扫描周期重试：eventId={}",event.eventId(),failure);
            }
        }
        if (page.size() == limit) {
            unfinishedSession = identity;
            activeSessionItemCursor = page.getLast().item().itemId();
        } else finishActiveSession(identity);
        return page.size();
    }

    private void finishActiveSession(com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity identity) {
        activeSessionCursor = identity.sessionId();
        activeSessionItemCursor = "";
        unfinishedSession = null;
    }

    private com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent restored(
            com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent event, boolean session) {
        if (event.eventType() != FeedbackEventType.REVERSAL) return null;
        var target = eventStore.findByEventId(event.reversesEventId()).orElseThrow();
        return (session ? eventStore.previousSessionExplicitEvent(target) : eventStore.previousExplicitEvent(target)).orElse(null);
    }

    private void project(com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent event) {
        if (event.eventType() == FeedbackEventType.REVERSAL) {
            preferenceStore.applyReversal(event, restored(event,false),restored(event,true));
        } else {
            preferenceStore.apply(event);
        }
        if (sessionPreferenceReader != null) {
            sessionPreferenceReader.activeUntil(event.identity()).ifPresent(expiry -> sessionPreferenceReader.restore(event,expiry));
        }
    }
}
