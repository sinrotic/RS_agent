package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.service.OnlinePreferenceStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.time.Clock;
import java.time.Instant;

@Component
@ConditionalOnProperty(name = "rs.recommend.feedback.projection", havingValue = "memory", matchIfMissing = true)
public class InMemoryOnlinePreferenceStore implements OnlinePreferenceStore {

    private final ConcurrentHashMap<String, OnlinePreferenceSnapshot> snapshots = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, OnlinePreferenceSnapshot> profileSnapshots = new ConcurrentHashMap<>();
    private final Clock clock;

    public InMemoryOnlinePreferenceStore() { this(Clock.systemUTC()); }
    public InMemoryOnlinePreferenceStore(Clock clock) { this.clock = clock; }

    @Override
    public OnlinePreferenceSnapshot apply(RecommendationFeedbackEvent event) {
        if (!event.eventType().preferenceChanging()) {
            return load(event.identity());
        }
        restoreSession(event,null,event.receivedAt().plus(PreferenceProjectionSupport.SESSION_TTL));
        restoreProfile(event,null);
        return load(event.identity());
    }

    @Override
    public OnlinePreferenceSnapshot load(RecommendationIdentity identity) {
        return PreferenceProjectionSupport.merge(loadProfile(identity.profileUserId()),
                PreferenceProjectionSupport.session(snapshots.getOrDefault(key(identity), OnlinePreferenceSnapshot.empty()),clock.instant()));
    }

    @Override
    public OnlinePreferenceSnapshot loadProfile(String profileUserId) {
        return PreferenceProjectionSupport.profile(profileSnapshots.getOrDefault(profileUserId, OnlinePreferenceSnapshot.empty()),clock.instant());
    }

    @Override
    public OnlinePreferenceSnapshot applyReversal(
            RecommendationFeedbackEvent reversal,
            RecommendationFeedbackEvent restoredPreferenceEvent
    ) {
        return applyReversal(reversal,restoredPreferenceEvent,
                restoredPreferenceEvent != null && restoredPreferenceEvent.identity().sessionId().equals(reversal.identity().sessionId())
                        ? restoredPreferenceEvent : null);
    }

    @Override
    public OnlinePreferenceSnapshot applyReversal(RecommendationFeedbackEvent reversal,
            RecommendationFeedbackEvent profileRestored, RecommendationFeedbackEvent sessionRestored) {
        restoreSession(reversal,sessionRestored,reversal.receivedAt().plus(PreferenceProjectionSupport.SESSION_TTL));
        restoreProfile(reversal,profileRestored);
        return load(reversal.identity());
    }

    @Override
    public void restoreProfile(RecommendationFeedbackEvent event, RecommendationFeedbackEvent restored) {
        profileSnapshots.compute(event.identity().profileUserId(),(ignored,current) -> PreferenceProjectionSupport.change(
                current == null ? OnlinePreferenceSnapshot.empty() : current,event,restored,"profile",null,clock.instant()));
    }

    @Override
    public void restoreSession(RecommendationFeedbackEvent event, RecommendationFeedbackEvent restored,Instant expiresAt) {
        if (!expiresAt.isAfter(clock.instant())) return;
        snapshots.compute(key(event.identity()),(ignored,current) -> PreferenceProjectionSupport.change(
                current == null ? OnlinePreferenceSnapshot.empty() : current,event,restored,"session",expiresAt,clock.instant()));
    }

    private String key(RecommendationIdentity identity) {
        return identity.profileUserId() + "|" + identity.sessionId();
    }
}
