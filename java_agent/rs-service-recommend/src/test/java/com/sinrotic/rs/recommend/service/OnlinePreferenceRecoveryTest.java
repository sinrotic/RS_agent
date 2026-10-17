package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.config.JacksonConfig;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.data.redis.core.*;
import org.springframework.data.redis.core.script.RedisScript;

import java.time.*;
import java.util.*;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class OnlinePreferenceRecoveryTest {
    private static final RecommendationIdentity IDENTITY = new RecommendationIdentity("account", "profile", "session");

    static Stream<OnlinePreferenceStore> stores() {
        return Stream.of(new InMemoryOnlinePreferenceStore(), redisStore());
    }

    @Test
    void rebuildRestoresTheEffectivePreferenceOfAReversal() {
        var events = mock(RecommendationFeedbackEventStore.class);
        var like = event("A", 1, FeedbackEventType.LIKE);
        var dislike = event("A", 2, FeedbackEventType.DISLIKE);
        var reversal = new RecommendationFeedbackEvent("reversal", "key-r", "request-r", IDENTITY,
                dislike.item(), FeedbackEventType.REVERSAL, dislike.eventId(), Instant.now(), Instant.now(), 3);
        when(events.rebuildablePreferenceEvents(1000)).thenReturn(List.of(reversal));
        when(events.rebuildablePreferenceEvents("", "", 1000)).thenReturn(List.of(reversal));
        when(events.findByEventId(dislike.eventId())).thenReturn(Optional.of(dislike));
        when(events.previousExplicitEvent(dislike)).thenReturn(Optional.of(like));
        var store = redisStore();
        new FeedbackProjectionRetryWorker(events, store, mock(RecommendationFeedbackMetrics.class))
                .rebuildCurrentPreferences();
        assertEquals("like", store.loadProfile("profile").itemPreferences().get("A").eventType());
        assertEquals(3, store.loadProfile("profile").version());
    }

    @Test
    void rebuildAdvancesBeyondFirstThousandItems() {
        var events = mock(RecommendationFeedbackEventStore.class);
        var first = java.util.stream.IntStream.rangeClosed(1, 1000)
                .mapToObj(i -> event(String.format("item-%04d", i), i, FeedbackEventType.LIKE)).toList();
        var last = event("item-1001", 1001, FeedbackEventType.DISLIKE);
        when(events.rebuildablePreferenceEvents(1000)).thenReturn(first);
        when(events.rebuildablePreferenceEvents("", "", 1000)).thenReturn(first);
        when(events.rebuildablePreferenceEvents("profile", "item-1000", 1000)).thenReturn(List.of(last));
        var store = new InMemoryOnlinePreferenceStore();
        var worker = new FeedbackProjectionRetryWorker(events, store, mock(RecommendationFeedbackMetrics.class));
        worker.rebuildCurrentPreferences();
        worker.rebuildCurrentPreferences();
        assertEquals(1001, store.loadProfile("profile").itemPreferences().size());
    }

    @ParameterizedTest
    @MethodSource("stores")
    void lateFeedbackForAnotherItemStillApplies(OnlinePreferenceStore store) {
        store.apply(event("B", 2, FeedbackEventType.LIKE));
        store.apply(event("A", 1, FeedbackEventType.DISLIKE));
        assertEquals(Set.of("A", "B"), store.load(IDENTITY).itemPreferences().keySet());
        assertEquals(2, store.load(IDENTITY).version());
    }

    static RecommendationFeedbackEvent event(String item, long version, FeedbackEventType type) {
        return new RecommendationFeedbackEvent("event-" + version, "key-" + version, "request-" + version,
                IDENTITY, new RecommendationDeliveryItem(item, 1, 1, "bags", "brand", Map.of()),
                type, type == FeedbackEventType.REVERSAL ? "event-1" : null,
                Instant.now(), Instant.now(), version);
    }

    @ParameterizedTest
    @MethodSource("stores")
    void reversalRetriesCannotRollBackVersionOrResurrectRemovedPreferences(OnlinePreferenceStore store) {
        var original = event("A", 1, FeedbackEventType.LIKE);
        var reversal = event("A", 2, FeedbackEventType.REVERSAL);
        store.apply(original);
        store.applyReversal(reversal, null);
        store.apply(event("B", 4, FeedbackEventType.LIKE));
        store.applyReversal(reversal, null);
        store.apply(original);
        assertEquals(4, store.load(IDENTITY).version());
        assertFalse(store.load(IDENTITY).itemPreferences().containsKey("A"));
        assertEquals(1, Collections.frequency(store.load(IDENTITY).appliedFeedbackEventIds(), reversal.eventId()));
        store.apply(event("A", 5, FeedbackEventType.DISLIKE));
        store.applyReversal(reversal, null);
        assertEquals("dislike", store.load(IDENTITY).itemPreferences().get("A").eventType());
    }

    @SuppressWarnings("unchecked")
    static RedisOnlinePreferenceStore redisStore() {
        return redisStore(false);
    }

    @Test
    void concurrentRedisWriterIsMergedAfterCompareAndSetConflict() {
        var store = redisStore(true);
        store.apply(event("A", 1, FeedbackEventType.LIKE));
        assertEquals(Set.of("A", "B"), store.loadProfile("profile").itemPreferences().keySet());
        assertEquals(2, store.loadProfile("profile").version());
    }

    @SuppressWarnings("unchecked")
    static RedisOnlinePreferenceStore redisStore(boolean conflict) {
        var data = new HashMap<String, String>();
        var conflicted = new HashSet<String>();
        var redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenAnswer(call -> data.get(call.getArgument(0)));
        doAnswer(call -> { data.put(call.getArgument(0), call.getArgument(1)); return null; })
                .when(values).set(anyString(), anyString(), any(Duration.class));
        when(redis.execute(any(RedisScript.class), anyList(), any(), any(), any()))
                .thenAnswer(call -> {
                    String key = ((List<String>) call.getArgument(1)).getFirst();
                    String expected = call.getArgument(2);
                    if (conflict && conflicted.add(key)) {
                        var other = new InMemoryOnlinePreferenceStore();
                        other.apply(event("B", 2, FeedbackEventType.LIKE));
                        var snapshot = key.contains(":profile:") ? other.loadProfile("profile") : other.load(IDENTITY);
                        data.put(key, new JacksonConfig().objectMapper().writeValueAsString(snapshot));
                        return 0L;
                    }
                    if (!Objects.equals(data.getOrDefault(key, ""), expected)) return 0L;
                    data.put(key, call.getArgument(3));
                    return 1L;
                });
        return new RedisOnlinePreferenceStore(redis, new JacksonConfig().objectMapper());
    }
}
