package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.controller.app.*;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.dto.*;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.h2.jdbcx.JdbcDataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.time.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class FeedbackWorkflowRegressionTest {
    static final Instant NOW = Instant.parse("2026-10-11T03:00:00Z");
    static final Clock CLOCK = Clock.fixed(NOW,ZoneOffset.UTC);
    static class Fixture {
        final RecommendationIdentity identity = new RecommendationIdentity("account","profile","session");
        final RecommendationDeliveryItem item = new RecommendationDeliveryItem("item-a",1,1,"category","brand",Map.of());
        final InMemoryRecommendationFeedbackEventStore events = new InMemoryRecommendationFeedbackEventStore();
        final InMemoryOnlinePreferenceStore preferences = spy(new InMemoryOnlinePreferenceStore(CLOCK));
        final DefaultRecommendationDeliveryService deliveries = new DefaultRecommendationDeliveryService(new InMemoryRecommendationDeliveryStore(),CLOCK,Duration.ofHours(24));
        final DefaultRecommendFeedbackService feedback = new DefaultRecommendFeedbackService(deliveries,events,preferences,CLOCK);
        final RecommendPreferenceController controller = new RecommendPreferenceController(new PreferenceFactReader(events,CLOCK),feedback);
        Fixture() { deliveries.record("delivery",identity,"home",0,List.of(item)); }
        void history(int count) {
            for(int i=0;i<count;i++) preferences.apply(events.append(command("history-"+i,item,FeedbackEventType.LIKE)).event());
        }
        FeedbackAppendCommand command(String request, RecommendationDeliveryItem item, FeedbackEventType type) {
            return new FeedbackAppendCommand(request,identity,item,type,null,NOW,NOW);
        }
        MockMvc mvc() { return MockMvcBuilders.standaloneSetup(new RecommendFeedbackController(feedback, mock(RecommendationSessionValidator.class)),controller)
                .setControllerAdvice(new RecommendFeedbackExceptionHandler()).build(); }
    }

    @Test
    void bulkClearReportsPartialProgressAndResumesLongHistory() throws Exception {
        var f = new Fixture(); f.history(103);
        var first = f.controller.clear("account","profile");
        assertThat(first.operationComplete()).isFalse();
        assertThat(first.operations()).hasSize(1);
        assertThat(first.operations().getFirst().operationComplete()).isFalse();
        assertThat(first.items()).hasSize(1);
        var second = f.controller.clear("account","profile");
        assertThat(second.operationComplete()).isTrue();
        assertThat(second.items()).isEmpty();
        assertThat(f.controller.clear("account","profile").operationComplete()).isTrue();
    }

    @Test
    void lostPendingClearResponseCanBeRecoveredWithoutDuplicateReversal() throws Exception {
        var f = new Fixture(); f.history(2);
        doThrow(new IllegalStateException("临时投影异常")).when(f.preferences).applyReversal(any(),nullable(RecommendationFeedbackEvent.class),nullable(RecommendationFeedbackEvent.class));
        var first=f.controller.clear("account","profile");
        var firstAck=first.operations().getFirst();
        assertThat(firstAck.applicationStatus()).isEqualTo("PENDING");
        assertThat(firstAck.feedbackId()).isNotBlank();
        var retry=f.controller.clear("account","profile").operations().getFirst();
        assertThat(retry.feedbackId()).isEqualTo(firstAck.feedbackId());
        assertThat(retry.duplicate()).isTrue();
        assertThat(retry.applicationStatus()).isEqualTo("PENDING");
        assertThat(f.events.pendingProjectionEvents(10)).hasSize(1);
        doCallRealMethod().when(f.preferences).applyReversal(any(),nullable(RecommendationFeedbackEvent.class),nullable(RecommendationFeedbackEvent.class));
        new FeedbackProjectionRetryWorker(f.events,f.preferences,mock(RecommendationFeedbackMetrics.class),CLOCK).retryPending();
        assertThat(f.events.projectionStatus(firstAck.feedbackId())).isEqualTo("APPLIED");
        assertThat(f.controller.clear("account","profile").operationComplete()).isTrue();
    }

    @Test
    void exposureValidationRejectsWholeBatchBeforeAnyWriteRegardlessOfItemOrder() throws Exception {
        for(String items:new String[]{"[\"item-a\",\"not-delivered\"]","[\"not-delivered\",\"item-a\"]"}) {
            var f=new Fixture();
            f.mvc().perform(post("/api/recommend/feedback/exposure").header("X-Account-Id","account").header("X-Profile-User-Id","profile")
                .contentType("application/json").content("{\"request_id\":\"delivery\",\"session_id\":\"session\",\"item_ids\":"+items+"}"))
                .andExpect(status().isUnprocessableEntity());
            assertThat(f.events.append(f.command("delivery",f.item,FeedbackEventType.EXPOSURE)).duplicate()).isFalse();
        }
    }

    @ParameterizedTest
    @ValueSource(strings={"{\"items\":[null]}","{\"item_ids\":[null]}","{\"items\":[{\"item_id\":\"item-a\",\"visible_ratio\":1.5}]}",
        "{\"items\":[{\"item_id\":\"item-a\",\"visible_duration_ms\":-1}]}","{\"exposed_at\":9223372036854775807,\"item_ids\":[\"item-a\"]}","{\"item_ids\":[]}"})
    void malformedExposureReturns400WithStableErrorCode(String fragment) throws Exception {
        var f=new Fixture();
        String body="{\"request_id\":\"delivery\",\"session_id\":\"session\","+fragment.substring(1);
        f.mvc().perform(post("/api/recommend/feedback/exposure").header("X-Account-Id","account").header("X-Profile-User-Id","profile")
            .contentType("application/json").content(body)).andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.error.code").value("INVALID_FEEDBACK_REQUEST"));
    }

    @Test
    void missingSessionReturns400AndValidLegacyExposureStillWorks() throws Exception {
        var f=new Fixture();
        f.mvc().perform(post("/api/recommend/feedback/event").header("X-Account-Id","account").header("X-Profile-User-Id","profile")
            .contentType("application/json").content("{\"request_id\":\"delivery\",\"item_id\":\"item-a\",\"event_type\":\"like\"}"))
            .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error.code").value("INVALID_FEEDBACK_REQUEST"));
        var request=new RecommendExposureFeedbackRequestDTO("delivery","session",List.of("item-a"),null);
        assertThat(f.feedback.recordExposure(f.identity,request).acceptedCount()).isEqualTo(1);
        assertThat(f.feedback.recordExposure(f.identity,request).duplicate()).isTrue();
    }

    @Test
    void jdbcExposureBatchRollsBackEarlierRowsOnLaterDatabaseFailureAndRetainsDeduplication() {
        var source=new JdbcDataSource(); source.setURL("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1");
        var jdbc=new JdbcTemplate(source);
        jdbc.execute("""
            CREATE TABLE rs_recommend_feedback_event (
                event_id VARCHAR PRIMARY KEY,idempotency_key VARCHAR UNIQUE,request_id VARCHAR,item_id VARCHAR,
                account_id VARCHAR,profile_user_id VARCHAR,session_id VARCHAR,event_type VARCHAR,reverses_event_id VARCHAR,
                position_no INT,visible_ratio DOUBLE,visible_duration_ms BIGINT,category VARCHAR(16),brand VARCHAR,
                attributes_json VARCHAR,occurred_at TIMESTAMP,received_at TIMESTAMP,preference_version BIGINT)
            """);
        var store=new JdbcRecommendationPersistenceStore(jdbc,new TransactionTemplate(new DataSourceTransactionManager(source)),new ObjectMapper());
        var f=new Fixture();
        var first=f.command("batch",f.item,FeedbackEventType.EXPOSURE);
        var invalid=f.command("batch",new RecommendationDeliveryItem("item-b",2,1,"x".repeat(32),"brand",Map.of()),FeedbackEventType.EXPOSURE);
        assertThatThrownBy(()->store.appendBatch(List.of(first,invalid))).isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommend_feedback_event",Integer.class)).isZero();
        var second=f.command("batch",new RecommendationDeliveryItem("item-b",2,1,"category","brand",Map.of()),FeedbackEventType.EXPOSURE);
        assertThat(store.appendBatch(List.of(first,second))).allMatch(result->!result.duplicate());
        assertThat(store.appendBatch(List.of(first,second))).allMatch(FeedbackAppendResult::duplicate);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommend_feedback_event",Integer.class)).isEqualTo(2);
    }

    @Test
    void memoryBatchAlsoRollsBackWhenAnAdapterFailsMidBatch() {
        var f=new Fixture();
        var failing=spy(f.events);
        var first=f.command("batch",f.item,FeedbackEventType.EXPOSURE);
        var second=f.command("batch",new RecommendationDeliveryItem("item-b",2,1,"category","brand",Map.of()),FeedbackEventType.EXPOSURE);
        doThrow(new IllegalStateException("第二行写入失败")).when(failing).append(second);
        assertThatThrownBy(()->failing.appendBatch(List.of(first,second))).isInstanceOf(IllegalStateException.class);
        assertThat(failing.append(first).duplicate()).isFalse();
    }
}
