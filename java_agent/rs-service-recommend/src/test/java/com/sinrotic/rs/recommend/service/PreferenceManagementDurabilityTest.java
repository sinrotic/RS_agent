package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.controller.app.RecommendPreferenceController;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.data.redis.core.*;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class PreferenceManagementDurabilityTest {
    @ParameterizedTest
    @ValueSource(booleans = {false,true})
    void clearReadsDurableHistoryAndDoesNotResurrectAfterCacheLossOrCorruption(boolean corrupt) {
        var f = new Fixture(); f.history(2);
        f.cache.clear();
        if (corrupt) f.cache.put("rs:pref:v2:profile:profile","{invalid-json");
        assertThat(f.controller.preferences("profile").items()).hasSize(1);
        var result = f.controller.clear("account","profile");
        assertThat(result.operationComplete()).isTrue();
        assertThat(result.operations()).singleElement().satisfies(ack -> {
            assertThat(ack.accepted()).isTrue();
            assertThat(ack.feedbackId()).isNotBlank();
            assertThat(ack.applicationStatus()).isEqualTo("APPLIED");
        });
        assertThat(f.reversals()).isEqualTo(2);
        f.cache.clear(); f.worker().rebuildCurrentPreferences();
        assertThat(f.preferences.loadProfile("profile").itemPreferences()).isEmpty();
        assertThat(f.controller.preferences("profile").items()).isEmpty();
    }

    @Test
    void deleteItemReversesFactsWithNoCachedItemAndRepeatedDeleteDoesNotAddEvents() {
        var f = new Fixture(); f.history(2); f.cache.clear();
        var ack = f.controller.deleteItem("account","profile","item");
        assertThat(ack.operationComplete()).isTrue();
        assertThat(ack.preferenceVersion()).isEqualTo(4);
        assertThat(f.reversals()).isEqualTo(2);
        assertThat(f.controller.deleteItem("account","profile","item").operationComplete()).isTrue();
        assertThat(f.reversals()).isEqualTo(2);
        f.cache.clear(); f.worker().rebuildCurrentPreferences();
        assertThat(f.preferences.loadProfile("profile").itemPreferences()).isEmpty();
    }

    @Test
    void pendingFinalDeletionRemainsIncompleteWithEmptyFactsAndLostCacheUntilOutboxApplies() {
        var f = new Fixture(); f.history(1); f.cache.clear(); f.unavailable = true;
        var first = f.controller.clear("account","profile");
        assertThat(first.items()).isEmpty();
        assertThat(first.operationComplete()).isFalse();
        var receipt = first.operations().getFirst();
        assertThat(receipt.applicationStatus()).isEqualTo("PENDING");
        var retry = f.controller.clear("account","profile");
        assertThat(retry.operationComplete()).isFalse();
        assertThat(retry.operations().getFirst().feedbackId()).isEqualTo(receipt.feedbackId());
        assertThat(retry.operations().getFirst().duplicate()).isTrue();
        assertThat(f.controller.deleteItem("account","profile","item").operationComplete()).isFalse();
        assertThat(f.reversals()).isEqualTo(1);
        f.unavailable = false;
        // H2 的 TIMESTAMP 默认精度高于查询使用的 CURRENT_TIMESTAMP(3)，明确设为过去避免毫秒边界抖动。
        f.jdbc.update("UPDATE rs_recommend_feedback_outbox SET next_attempt_at = ?",java.sql.Timestamp.from(f.now.minusSeconds(1)));
        assertThat(f.events.pendingProjectionEvents(100)).extracting(RecommendationFeedbackEvent::eventId).contains(receipt.feedbackId());
        f.worker().retryPending();
        assertThat(f.events.projectionStatus(receipt.feedbackId())).isEqualTo("APPLIED");
        assertThat(f.controller.clear("account","profile").operationComplete()).isTrue();
        assertThat(f.preferences.loadProfile("profile").itemPreferences()).isEmpty();
    }

    @Test
    void sharedProfileDoesNotAllowAnotherAccountToReverseOwnedFacts() {
        var f = new Fixture(); f.history(1); f.cache.clear();
        var result = f.controller.clear("other-account","profile");
        assertThat(result.operationComplete()).isFalse();
        assertThat(result.operations().getFirst().accepted()).isFalse();
        assertThat(f.reversals()).isZero();
        assertThat(f.controller.preferences("profile").items()).hasSize(1);
    }

    @Test
    void currentSessionSqlPreservesOldFactsAndSeparatesOwnersSessionsAndItemPages() {
        var f = new Fixture(); f.history(1);
        var old = f.now.minus(Duration.ofHours(25));
        f.jdbc.update("UPDATE rs_recommend_feedback_event SET received_at = ?",java.sql.Timestamp.from(old));
        var original = f.events.currentSessionEvents(f.identity,"",1).getFirst();
        assertThat(original.receivedAt()).isBefore(f.now.minus(Duration.ofHours(24)));
        var other = new RecommendationIdentity("account","profile","another-session");
        f.events.append(new FeedbackAppendCommand("other-session",other,f.item,FeedbackEventType.DISLIKE,null,f.now,f.now));
        assertThat(f.events.currentSessionEvents(f.identity,"",1)).extracting(RecommendationFeedbackEvent::eventId)
                .containsExactly(original.eventId());
        assertThat(f.events.currentSessionEvents(other,"",1).getFirst().eventType()).isEqualTo(FeedbackEventType.DISLIKE);
        assertThat(f.events.currentSessionEvents(f.identity,"item",1)).isEmpty();
        assertThat(f.events.currentSessionEvents(new RecommendationIdentity("other-account","profile","session"),"",1)).isEmpty();
        assertThat(f.events.currentSessionEvents(new RecommendationIdentity("account","other-profile","session"),"",1)).isEmpty();
    }

    static class Fixture {
        final Instant now = Instant.now();
        final Clock clock = Clock.fixed(now,ZoneOffset.UTC);
        final RecommendationIdentity identity = new RecommendationIdentity("account","profile","session");
        final RecommendationDeliveryItem item = new RecommendationDeliveryItem("item",1,1,"books","brand",Map.of());
        final Map<String,String> cache = new HashMap<>();
        final JdbcTemplate jdbc;
        final JdbcRecommendationPersistenceStore events;
        final RedisOnlinePreferenceStore preferences;
        final RecommendPreferenceController controller;
        boolean unavailable;
        @SuppressWarnings("unchecked") Fixture() {
            var data = new JdbcDataSource(); data.setURL("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1");
            jdbc = new JdbcTemplate(data);
            jdbc.execute("CREATE ALIAS POW FOR 'java.lang.Math.pow'");
            jdbc.execute("""
                    CREATE TABLE rs_recommend_feedback_event(event_id VARCHAR PRIMARY KEY,idempotency_key VARCHAR UNIQUE,
                    request_id VARCHAR,item_id VARCHAR,account_id VARCHAR,profile_user_id VARCHAR,session_id VARCHAR,
                    event_type VARCHAR,reverses_event_id VARCHAR,category VARCHAR,brand VARCHAR,attributes_json VARCHAR,
                    occurred_at TIMESTAMP,received_at TIMESTAMP,preference_version BIGINT,position_no INT,
                    visible_ratio DOUBLE,visible_duration_ms BIGINT)
                    """);
            jdbc.execute("""
                    CREATE TABLE rs_profile_item_preference_projection(profile_user_id VARCHAR,item_id VARCHAR,
                    latest_event_id VARCHAR,effective_event_id VARCHAR,current_state VARCHAR,category VARCHAR,brand VARCHAR,
                    attributes_json VARCHAR,preference_version BIGINT,updated_at TIMESTAMP,expires_at TIMESTAMP,
                    PRIMARY KEY(profile_user_id,item_id))
                    """);
            jdbc.execute("""
                    CREATE TABLE rs_recommend_feedback_outbox(event_id VARCHAR PRIMARY KEY,status VARCHAR,attempt_count INT,
                    next_attempt_at TIMESTAMP,created_at TIMESTAMP,applied_at TIMESTAMP,last_error VARCHAR)
                    """);
            jdbc.execute("CREATE TABLE rs_preference_version(profile_user_id VARCHAR,session_id VARCHAR,version_no BIGINT,updated_at TIMESTAMP,PRIMARY KEY(profile_user_id,session_id))");
            events = new JdbcRecommendationPersistenceStore(jdbc,new TransactionTemplate(new DataSourceTransactionManager(data)),new ObjectMapper());
            var redis = mock(StringRedisTemplate.class);
            ValueOperations<String,String> values = mock(ValueOperations.class);
            when(redis.opsForValue()).thenReturn(values);
            when(values.get(anyString())).thenAnswer(call -> cache.get(call.getArgument(0)));
            when(redis.execute(any(RedisScript.class),anyList(),any(),any(),any())).thenAnswer(call -> {
                if (unavailable) throw new IllegalStateException("模拟 Redis 故障");
                String key = ((List<String>)call.getArgument(1)).getFirst();
                if (!Objects.equals(cache.getOrDefault(key,""),call.getArgument(2))) return 0L;
                cache.put(key,call.getArgument(3));return 1L;
            });
            preferences = new RedisOnlinePreferenceStore(redis,new ObjectMapper().findAndRegisterModules(),clock);
            var deliveries = new DefaultRecommendationDeliveryService(new InMemoryRecommendationDeliveryStore(),clock,Duration.ofHours(24));
            var feedback = new DefaultRecommendFeedbackService(deliveries,events,preferences,clock);
            controller = new RecommendPreferenceController(new PreferenceFactReader(events,clock),feedback);
        }
        void history(int count) {
            for (int i = 0; i < count; i++) {
                var event = events.append(new FeedbackAppendCommand("request-"+i,identity,item,
                        i % 2 == 0 ? FeedbackEventType.LIKE : FeedbackEventType.DISLIKE,null,now,now)).event();
                preferences.apply(event); events.markProjectionApplied(event.eventId());
            }
        }
        int reversals() { return jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommend_feedback_event WHERE event_type = 'reversal'",Integer.class); }
        FeedbackProjectionRetryWorker worker() { return new FeedbackProjectionRetryWorker(events,preferences,mock(RecommendationFeedbackMetrics.class),clock); }
    }
}
