package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.*;
import java.util.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class FeedbackProjectionFailureRegressionTest {
    @Test
    void duplicateAppliedFeedbackFailureReturnsToPendingAndWorkerRecoversIt() {
        var fixture = new Fixture();
        fixture.store.markProjectionApplied("original");
        var unavailable = mock(OnlinePreferenceStore.class);
        when(unavailable.apply(any())).thenThrow(new IllegalStateException("模拟 Redis 不可用"));
        var service = new DefaultRecommendFeedbackService(fixture.deliveries,fixture.store,unavailable,Clock.systemUTC());
        var ack = service.recordEvent(fixture.identity,
                new RecommendEventFeedbackRequestDTO("delivery","session","item","like",1.0,null));
        assertThat(ack.duplicate()).isTrue();
        assertThat(ack.applicationStatus()).isEqualTo("PENDING");
        assertThat(fixture.store.projectionStatus("original")).isEqualTo(ack.applicationStatus());
        assertThat(fixture.jdbc.queryForObject("SELECT applied_at FROM rs_recommend_feedback_outbox",java.sql.Timestamp.class)).isNull();
        fixture.makeDue();
        assertThat(fixture.store.pendingProjectionEvents(100)).hasSize(1);
        var repaired = new InMemoryOnlinePreferenceStore();
        new FeedbackProjectionRetryWorker(fixture.store,repaired,mock(RecommendationFeedbackMetrics.class)).retryPending();
        assertThat(fixture.store.projectionStatus("original")).isEqualTo("APPLIED");
        assertThat(fixture.store.pendingProjectionEvents(100)).isEmpty();
        assertThat(repaired.load(fixture.identity).itemPreferences().get("item").eventType()).isEqualTo("like");
        assertThat(fixture.jdbc.queryForObject("SELECT last_error FROM rs_recommend_feedback_outbox",String.class)).isNull();
        assertThat(fixture.jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommend_feedback_event",Integer.class)).isEqualTo(1);
    }

    @Test
    void lateFailureConservativelyRequeuesAndLaterSuccessClearsIt() {
        var fixture = new Fixture();
        fixture.store.markProjectionFailed("original","第一次失败");
        assertThat(fixture.store.projectionStatus("original")).isEqualTo("PENDING");
        fixture.store.markProjectionApplied("original");
        fixture.store.markProjectionFailed("original","迟到的失败回写");
        assertThat(fixture.store.projectionStatus("original")).isEqualTo("PENDING");
        fixture.makeDue();
        assertThat(fixture.store.pendingProjectionEvents(100)).hasSize(1);
        fixture.store.markProjectionApplied("original");
        assertThat(fixture.store.projectionStatus("original")).isEqualTo("APPLIED");
        assertThat(fixture.store.pendingProjectionEvents(100)).isEmpty();
        assertThat(fixture.jdbc.queryForObject("SELECT applied_at FROM rs_recommend_feedback_outbox",java.sql.Timestamp.class)).isNotNull();
        assertThat(fixture.jdbc.queryForObject("SELECT last_error FROM rs_recommend_feedback_outbox",String.class)).isNull();
    }

    static class Fixture {
        final RecommendationIdentity identity = new RecommendationIdentity("account","profile","session");
        final JdbcTemplate jdbc;
        final JdbcRecommendationPersistenceStore store;
        final DefaultRecommendationDeliveryService deliveries = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(),Clock.systemUTC(),Duration.ofHours(24));
        Fixture() {
            var source = new JdbcDataSource();
            source.setURL("jdbc:h2:mem:projection-failure-"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1");
            jdbc = new JdbcTemplate(source);
            jdbc.execute("CREATE ALIAS POW FOR 'java.lang.Math.pow'");
            jdbc.execute("""
                    CREATE TABLE rs_recommend_feedback_outbox(event_id VARCHAR PRIMARY KEY,status VARCHAR,attempt_count INT,
                        next_attempt_at TIMESTAMP,created_at TIMESTAMP,applied_at TIMESTAMP,last_error VARCHAR)
                    """);
            jdbc.execute("""
                    CREATE TABLE rs_recommend_feedback_event(event_id VARCHAR PRIMARY KEY,idempotency_key VARCHAR,request_id VARCHAR,
                        item_id VARCHAR,account_id VARCHAR,profile_user_id VARCHAR,session_id VARCHAR,event_type VARCHAR,
                        reverses_event_id VARCHAR,category VARCHAR,brand VARCHAR,attributes_json VARCHAR,
                        occurred_at TIMESTAMP,received_at TIMESTAMP,preference_version BIGINT,position_no INT,visible_ratio DOUBLE,visible_duration_ms BIGINT)
                    """);
            var item = new RecommendationDeliveryItem("item",1,1,"books","brand",Map.of());
            var now = Instant.now();
            var command = new FeedbackAppendCommand("delivery",identity,item,FeedbackEventType.LIKE,null,now,now);
            jdbc.update("""
                    INSERT INTO rs_recommend_feedback_event(event_id,idempotency_key,request_id,item_id,account_id,profile_user_id,
                        session_id,event_type,category,brand,attributes_json,occurred_at,received_at,preference_version)
                    VALUES ('original',?,'delivery','item','account','profile','session','like','books','brand','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)
                    """,command.idempotencyKey());
            jdbc.update("INSERT INTO rs_recommend_feedback_outbox VALUES ('original','PENDING',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL,NULL)");
            store = new JdbcRecommendationPersistenceStore(jdbc,new TransactionTemplate(new DataSourceTransactionManager(source)),new ObjectMapper());
            deliveries.record("delivery",identity,"home",0,List.of(item));
        }
        void makeDue() { jdbc.update("UPDATE rs_recommend_feedback_outbox SET next_attempt_at=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP)"); }
    }
}
