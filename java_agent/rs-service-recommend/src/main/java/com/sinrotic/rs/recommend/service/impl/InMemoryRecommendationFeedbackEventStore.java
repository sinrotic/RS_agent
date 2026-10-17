package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendCommand;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendResult;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.Optional;
import java.util.Comparator;

@Component
@ConditionalOnProperty(name = "rs.recommend.feedback.persistence", havingValue = "memory", matchIfMissing = true)
public class InMemoryRecommendationFeedbackEventStore implements RecommendationFeedbackEventStore {

    private final ConcurrentHashMap<String, RecommendationFeedbackEvent> events = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, RecommendationFeedbackEvent> eventsById = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, AtomicLong> preferenceVersions = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, String> projectionStatuses = new ConcurrentHashMap<>();

    @Override
    public synchronized FeedbackAppendResult append(FeedbackAppendCommand command) {
        String key = command.idempotencyKey();
        RecommendationFeedbackEvent existing = events.get(key);
        if (existing != null) {
            return new FeedbackAppendResult(existing, true);
        }
        synchronized (this) {
            existing = events.get(key);
            if (existing != null) {
                return new FeedbackAppendResult(existing, true);
            }
            long version = command.eventType().preferenceChanging()
                    ? preferenceVersions.computeIfAbsent(
                            command.identity().profileUserId(), ignored -> new AtomicLong()).incrementAndGet()
                    : 0L;
            RecommendationFeedbackEvent event = new RecommendationFeedbackEvent(
                    "fb_evt_" + UUID.randomUUID(), key, command.requestId(), command.identity(), command.item(),
                    command.eventType(), command.reversesEventId(), command.occurredAt(), command.receivedAt(),
                    command.position(), command.visibleRatio(), command.visibleDurationMs(), version);
            events.put(key, event);
            eventsById.put(event.eventId(), event);
            return new FeedbackAppendResult(event, false);
        }
    }

    @Override
    public synchronized java.util.List<FeedbackAppendResult> appendBatch(java.util.List<FeedbackAppendCommand> commands) {
        var batch = java.util.List.copyOf(commands);
        var createdKeys = new java.util.HashSet<String>();
        var versions = new java.util.HashMap<String,Long>();
        try {
            var results = new java.util.ArrayList<FeedbackAppendResult>(batch.size());
            for (var command : batch) {
                String key = command.idempotencyKey();
                if (!events.containsKey(key)) createdKeys.add(key);
                String profile = command.identity().profileUserId();
                if (!versions.containsKey(profile)) versions.put(profile,preferenceVersions.containsKey(profile) ? preferenceVersions.get(profile).get() : null);
                results.add(append(command));
            }
            return java.util.List.copyOf(results);
        }
        catch (RuntimeException failure) {
            createdKeys.forEach(key -> {
                var event = events.remove(key);
                if (event != null) eventsById.remove(event.eventId());
            });
            versions.forEach((profile,version) -> {
                if (version == null) preferenceVersions.remove(profile);
                else preferenceVersions.put(profile,new AtomicLong(version));
            });
            throw failure;
        }
    }

    @Override
    public synchronized Optional<RecommendationFeedbackEvent> findReversalOf(String eventId) {
        return eventsById.values().stream().filter(event -> eventId.equals(event.reversesEventId())).findFirst();
    }

    @Override
    public synchronized void markProjectionApplied(String eventId) { projectionStatuses.put(eventId,"APPLIED"); }

    @Override
    public synchronized void markProjectionFailed(String eventId, String error) { projectionStatuses.put(eventId,"PENDING"); }

    @Override
    public synchronized String projectionStatus(String eventId) {
        return projectionStatuses.getOrDefault(eventId, RecommendationFeedbackEventStore.super.projectionStatus(eventId));
    }

    @Override
    public synchronized java.util.List<RecommendationFeedbackEvent> pendingProjectionEvents(int limit) {
        return eventsById.values().stream().filter(event -> "PENDING".equals(projectionStatuses.get(event.eventId())))
                .sorted(Comparator.comparingLong(RecommendationFeedbackEvent::preferenceVersion)).limit(Math.max(1,limit)).toList();
    }

    @Override
    public synchronized Optional<RecommendationFeedbackEvent> findByEventId(String eventId) {
        return Optional.ofNullable(eventsById.get(eventId));
    }

    @Override
    public synchronized java.util.List<RecommendationFeedbackEvent> currentProfileEvents(
            String profileUserId, String afterItemId, int limit) {
        var latest = new java.util.HashMap<String,RecommendationFeedbackEvent>();
        eventsById.values().stream().filter(event -> event.eventType().preferenceChanging()
                && event.identity().profileUserId().equals(profileUserId)).forEach(event ->
                latest.merge(event.item().itemId(),event,
                        (left,right) -> left.preferenceVersion() > right.preferenceVersion() ? left : right));
        return latest.values().stream().filter(event -> event.item().itemId().compareTo(afterItemId) > 0
                && event.receivedAt().plus(java.time.Duration.ofDays(180)).isAfter(java.time.Instant.now()))
                .sorted(Comparator.comparing(event -> event.item().itemId()))
                .limit(Math.max(1,Math.min(1000,limit))).toList();
    }

    @Override
    public synchronized Optional<RecommendationFeedbackEvent> currentProfileItemEvent(String profileUserId, String itemId) {
        return eventsById.values().stream().filter(event -> event.eventType().preferenceChanging()
                && event.identity().profileUserId().equals(profileUserId) && event.item().itemId().equals(itemId))
                .max(Comparator.comparingLong(RecommendationFeedbackEvent::preferenceVersion))
                .filter(event -> event.receivedAt().plus(java.time.Duration.ofDays(180)).isAfter(java.time.Instant.now()));
    }

    @Override
    public synchronized java.util.List<RecommendationFeedbackEvent> currentSessionEvents(
            com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity identity, String afterItemId, int limit) {
        var latest = new java.util.HashMap<String,RecommendationFeedbackEvent>();
        eventsById.values().stream().filter(event -> event.eventType().preferenceChanging()
                && event.identity().equals(identity)).forEach(event -> latest.merge(event.item().itemId(),event,
                    (left,right) -> left.preferenceVersion() > right.preferenceVersion() ? left : right));
        return latest.values().stream().filter(event -> event.item().itemId().compareTo(afterItemId) > 0)
                .sorted(Comparator.comparing(event -> event.item().itemId()))
                .limit(Math.max(1,Math.min(1000,limit))).toList();
    }

    @Override
    public synchronized boolean isReversed(String eventId) {
        return eventsById.values().stream().anyMatch(event -> eventId.equals(event.reversesEventId()));
    }

    @Override
    public synchronized Optional<RecommendationFeedbackEvent> previousExplicitEvent(RecommendationFeedbackEvent target) {
        return eventsById.values().stream()
                .filter(event -> event.preferenceVersion() > 0
                        && !event.eventId().equals(target.eventId())
                        && event.identity().profileUserId().equals(target.identity().profileUserId())
                        && event.item().itemId().equals(target.item().itemId())
                        && (event.eventType() == com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType.LIKE
                        || event.eventType() == com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType.DISLIKE)
                        && !isReversed(event.eventId()))
                .max(Comparator.comparingLong(RecommendationFeedbackEvent::preferenceVersion));
    }

    @Override
    public synchronized java.util.List<RecommendationFeedbackEvent> rebuildablePreferenceEvents(
            String afterProfileUserId, String afterItemId, int limit) {
        var latest = new java.util.HashMap<java.util.List<String>, RecommendationFeedbackEvent>();
        eventsById.values().stream().filter(event -> event.eventType().preferenceChanging()).forEach(event ->
                latest.merge(java.util.List.of(event.identity().profileUserId(), event.item().itemId()), event,
                        (left, right) -> left.preferenceVersion() > right.preferenceVersion() ? left : right));
        return latest.values().stream().filter(event -> event.receivedAt().plus(java.time.Duration.ofDays(180)).isAfter(java.time.Instant.now())).filter(event ->
                        event.identity().profileUserId().compareTo(afterProfileUserId) > 0
                        || (event.identity().profileUserId().equals(afterProfileUserId)
                        && event.item().itemId().compareTo(afterItemId) > 0))
                .sorted(Comparator.comparing((RecommendationFeedbackEvent event) -> event.identity().profileUserId())
                        .thenComparing(event -> event.item().itemId()))
                .limit(Math.max(1, limit)).toList();
    }

    @Override
    public synchronized Optional<RecommendationFeedbackEvent> previousSessionExplicitEvent(RecommendationFeedbackEvent target) {
        return eventsById.values().stream().filter(event ->
                event.identity().profileUserId().equals(target.identity().profileUserId())
                && event.identity().sessionId().equals(target.identity().sessionId())
                && event.item().itemId().equals(target.item().itemId())
                && !event.eventId().equals(target.eventId())
                && (event.eventType() == com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType.LIKE
                    || event.eventType() == com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType.DISLIKE)
                && !isReversed(event.eventId())).max(Comparator.comparingLong(RecommendationFeedbackEvent::preferenceVersion));
    }

    @Override
    public synchronized java.util.List<com.sinrotic.rs.recommend.domain.preference.SessionPreferenceProjection> rebuildableSessionPreferences(
            String afterProfileUserId, String afterSessionId, String afterItemId, java.time.Instant activeSince,int limit) {
        var latest = new java.util.HashMap<java.util.List<String>,RecommendationFeedbackEvent>();
        var activities = new java.util.HashMap<java.util.List<String>,java.time.Instant>();
        eventsById.values().stream().filter(event -> event.eventType().preferenceChanging()).forEach(event -> {
            var identity = event.identity();
            activities.merge(java.util.List.of(identity.profileUserId(),identity.sessionId()),event.receivedAt(),
                    (left,right) -> left.isAfter(right) ? left : right);
            latest.merge(java.util.List.of(identity.profileUserId(),identity.sessionId(),event.item().itemId()),event,
                    (left,right) -> left.preferenceVersion() > right.preferenceVersion() ? left : right);
        });
        return latest.values().stream().filter(event -> activities.get(java.util.List.of(
                    event.identity().profileUserId(),event.identity().sessionId())).isAfter(activeSince))
                .filter(event -> event.identity().profileUserId().compareTo(afterProfileUserId) > 0
                    || (event.identity().profileUserId().equals(afterProfileUserId)
                    && (event.identity().sessionId().compareTo(afterSessionId) > 0
                    || (event.identity().sessionId().equals(afterSessionId) && event.item().itemId().compareTo(afterItemId) > 0))))
                .sorted(Comparator.comparing((RecommendationFeedbackEvent e) -> e.identity().profileUserId())
                    .thenComparing(e -> e.identity().sessionId()).thenComparing(e -> e.item().itemId()))
                .limit(Math.max(1,limit)).map(event -> new com.sinrotic.rs.recommend.domain.preference.SessionPreferenceProjection(
                    event,activities.get(java.util.List.of(event.identity().profileUserId(),event.identity().sessionId()))
                        .plus(java.time.Duration.ofHours(24)))).toList();
    }
}
