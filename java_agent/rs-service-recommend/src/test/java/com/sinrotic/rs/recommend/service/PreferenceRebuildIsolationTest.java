package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.config.JacksonConfig;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.domain.preference.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.*;
import org.springframework.data.redis.core.script.RedisScript;

import java.time.*;
import java.util.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class PreferenceRebuildIsolationTest {
    final Instant now = Instant.parse("2026-10-11T03:00:00Z");
    final Clock clock = Clock.fixed(now,ZoneOffset.UTC);
    final RecommendationFeedbackMetrics metrics = mock(RecommendationFeedbackMetrics.class);

    @Test
    void corruptProfileAndSessionCachesRecoverWithoutBlockingHealthyProfiles() {
        var events = new InMemoryRecommendationFeedbackEventStore();
        var a = append(events,"profile-a","session-a","item");
        var b = append(events,"profile-b","session-b","item");
        var cache = new Cache();
        cache.data.put("rs:pref:v2:profile:profile-a","{invalid-json");
        cache.data.put("rs:pref:v2:session:profile-a:session-a","null");
        new FeedbackProjectionRetryWorker(events,cache.store,metrics,clock).rebuildCurrentPreferences();
        assertThat(cache.store.loadProfile("profile-a").itemPreferences().get("item").eventId()).isEqualTo(a.eventId());
        assertThat(cache.store.loadProfile("profile-b").itemPreferences().get("item").eventId()).isEqualTo(b.eventId());
        assertThat(cache.store.load(a.identity()).itemPreferences().get("item").scope()).isEqualTo("session");
        assertThat(cache.store.load(b.identity()).itemPreferences().get("item").scope()).isEqualTo("session");
    }

    @Test
    void corruptionRepairPreservesNewerConcurrentWriter() throws Exception {
        var events = new InMemoryRecommendationFeedbackEventStore();
        var old = append(events,"profile","session","item");
        var latest = events.append(new FeedbackAppendCommand("new-delivery",old.identity(),old.item(),
                FeedbackEventType.DISLIKE,null,now,now)).event();
        var cache = new Cache();
        String key = "rs:pref:v2:profile:profile";
        cache.data.put(key,"{invalid-json");
        var other = new InMemoryOnlinePreferenceStore(clock);
        other.apply(latest);
        cache.concurrentKey = key;
        cache.concurrentValue = new JacksonConfig().objectMapper().writeValueAsString(other.loadProfile("profile"));
        cache.store.restoreProfile(old,null);
        var actual = cache.store.loadProfile("profile");
        assertThat(actual.version()).isEqualTo(latest.preferenceVersion());
        assertThat(actual.itemPreferences().get("item").eventType()).isEqualTo("dislike");
        assertThat(actual.itemPreferences().get("item").eventId()).isEqualTo(latest.eventId());
    }

    @Test
    void transientProfileFailureDoesNotBlockOthersAndIsRetriedNextCycle() {
        var events = new InMemoryRecommendationFeedbackEventStore();
        var failed = append(events,"profile-a","session-a","item");
        append(events,"profile-b","session-b","item");
        var preferences = spy(new InMemoryOnlinePreferenceStore(clock));
        doThrow(new IllegalStateException("模拟单个 Profile 更新失败")).doCallRealMethod()
                .when(preferences).restoreProfile(eq(failed),isNull());
        var worker = new FeedbackProjectionRetryWorker(events,preferences,metrics,clock);
        worker.rebuildCurrentPreferences();
        assertThat(preferences.loadProfile("profile-a").itemPreferences()).isEmpty();
        assertThat(preferences.loadProfile("profile-b").itemPreferences()).containsKey("item");
        worker.rebuildCurrentPreferences();
        assertThat(preferences.loadProfile("profile-a").itemPreferences()).containsKey("item");
        verify(metrics).projectionRebuild("profile",false);
    }

    @Test
    void permanentSessionFailureDoesNotBlockOtherSessions() {
        var events = new InMemoryRecommendationFeedbackEventStore();
        var failed = append(events,"profile-a","session-a","item");
        var healthy = append(events,"profile-b","session-b","item");
        var preferences = spy(new InMemoryOnlinePreferenceStore(clock));
        doThrow(new IllegalStateException("模拟单个 Session 更新失败"))
                .when(preferences).restoreSession(eq(failed),isNull(),any());
        var worker = new FeedbackProjectionRetryWorker(events,preferences,metrics,clock);
        worker.rebuildCurrentPreferences();
        worker.rebuildCurrentPreferences();
        assertThat(preferences.load(healthy.identity()).itemPreferences().get("item").scope()).isEqualTo("session");
        assertThat(preferences.load(failed.identity()).itemPreferences().get("item").scope()).isEqualTo("profile");
        verify(metrics,times(2)).projectionRebuild("session",false);
    }

    @Test
    void failedItemOnFullPageDoesNotPreventPaginationOrRetryAfterScanCompletes() {
        var events = new InMemoryRecommendationFeedbackEventStore();
        for (int i=0;i<1001;i++) append(events,"profile-"+String.format("%04d",i),"session","item");
        var preferences = spy(new InMemoryOnlinePreferenceStore(clock));
        var first = events.rebuildablePreferenceEvents("","",1000).getFirst();
        doThrow(new IllegalStateException("第一页首项失败")).doCallRealMethod()
                .when(preferences).restoreProfile(eq(first),isNull());
        var worker = new FeedbackProjectionRetryWorker(events,preferences,metrics,clock);
        worker.rebuildCurrentPreferences();
        assertThat(preferences.loadProfile("profile-0999").itemPreferences()).containsKey("item");
        assertThat(preferences.loadProfile("profile-0000").itemPreferences()).isEmpty();
        worker.rebuildCurrentPreferences();
        assertThat(preferences.loadProfile("profile-1000").itemPreferences()).containsKey("item");
        worker.rebuildCurrentPreferences();
        assertThat(preferences.loadProfile("profile-0000").itemPreferences()).containsKey("item");
    }

    RecommendationFeedbackEvent append(InMemoryRecommendationFeedbackEventStore events,String profile,String session,String item) {
        return events.append(new FeedbackAppendCommand("delivery-"+profile+"-"+item,
                new RecommendationIdentity("account",profile,session),
                new RecommendationDeliveryItem(item,1,1,"books","brand",Map.of()),
                FeedbackEventType.LIKE,null,now,now)).event();
    }

    class Cache {
        final Map<String,String> data = new HashMap<>();
        final RedisOnlinePreferenceStore store;
        String concurrentKey;
        String concurrentValue;
        @SuppressWarnings("unchecked") Cache() {
            var redis = mock(StringRedisTemplate.class);
            ValueOperations<String,String> values = mock(ValueOperations.class);
            when(redis.opsForValue()).thenReturn(values);
            when(values.get(anyString())).thenAnswer(call -> data.get(call.getArgument(0)));
            when(redis.execute(any(RedisScript.class),anyList(),any(),any(),any())).thenAnswer(call -> {
                String key = ((List<String>)call.getArgument(1)).getFirst();
                if (key.equals(concurrentKey)) {
                    data.put(key,concurrentValue);
                    concurrentKey = null;
                }
                if (!Objects.equals(data.getOrDefault(key,""),call.getArgument(2))) return 0L;
                data.put(key,call.getArgument(3));
                return 1L;
            });
            store = new RedisOnlinePreferenceStore(redis,new JacksonConfig().objectMapper(),clock);
        }
    }
}
