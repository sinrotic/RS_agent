package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.controller.app.*;
import com.sinrotic.rs.recommend.controller.agent.AgentRecommendController;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.dto.*;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.vo.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/** 通过生产 Bean 装配和真实控制器锁定在线分支、偏好恢复、预算和追踪归属。 */
class AgentOnlineRecommendationRegressionTest {
    static final RecommendationIdentity ID = new RecommendationIdentity("account","profile","session");
    static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();

    @ParameterizedTest @ValueSource(booleans={false,true})
    void semanticDeliverySupportsFeedbackAndKeepsExactSession(boolean trained) {
        var f = new Fixture("10");
        f.context(trained).run(context -> {
            assertThat(context).hasNotFailed();
            var result = f.semantic(context.getBean(DefaultAgentRecommendService.class),Map.of());
            assertThat(result.candidates()).hasSize(1);
            assertThat(f.deliveries.requireFeedbackTarget(ID,result.requestId(),"item").identity()).isEqualTo(ID);
            for (var type:List.of("like","dislike","why"))
                assertThat(f.feedback.recordEvent(ID,new RecommendEventFeedbackRequestDTO(result.requestId(),"session","item",type,1.0,null)).accepted()).isTrue();
            assertThat(f.feedback.recordExposure(ID,new RecommendExposureFeedbackRequestDTO(result.requestId(),"session",List.of("item"),null)).accepted()).isTrue();
            assertThat(f.traces.getTrace(result.requestId()).sessionId()).isEqualTo("session");
            assertThat(f.traces.getTrace(result.requestId()).profileUserId()).isEqualTo("profile");
            assertThat(result.degradationReasons()).doesNotContain("trained_ranking_unavailable");
        });
    }

    @ParameterizedTest @ValueSource(booleans={false,true})
    void activeSessionDislikeSurvivesCacheExpiryInSemanticAndRerank(boolean trained) {
        var f = new Fixture("10");f.dislike();f.clock.hours(25);
        when(f.sessions.activeUntil("account","profile","session")).thenReturn(f.clock.origin.plus(Duration.ofHours(47)));
        assertThat(f.preferences.load(ID).itemPreferences().get("item").scope()).isEqualTo("profile");
        f.context(trained).run(context -> {
            assertThat(context).hasNotFailed();
            var agent = context.getBean(DefaultAgentRecommendService.class);
            // 直接进入 Agent；不能先经过首页将缓存恢复。
            assertThat(f.semantic(agent,Map.of()).candidates()).isEmpty();
            if (trained) assertThat(agent.rerankCandidates(f.request(Map.of())).candidates()).isEmpty();
            assertThat(f.preferences.load(ID).itemPreferences().get("item").scope()).isEqualTo("session");
            verify(f.sessions,never()).requireActive(anyString(),anyString(),anyString());
        });
    }

    @Test
    void rerankRestoresColdCacheAndReversalDoesNotResurrectDislike() {
        var f = new Fixture("10");f.dislike();
        f.preferences = new InMemoryOnlinePreferenceStore(f.clock);
        f.context(true).run(context -> {
            var agent = context.getBean(DefaultAgentRecommendService.class);
            assertThat(agent.rerankCandidates(f.request(Map.of())).candidates()).isEmpty();
            var original = f.events.currentSessionEvents(ID,"",10).getFirst();
            assertThat(f.feedback.reverse(ID,new RecommendFeedbackReversalRequestDTO(original.eventId())).accepted()).isTrue();
            assertThat(agent.rerankCandidates(f.request(Map.of())).candidates()).hasSize(1);
        });
    }

    @ParameterizedTest @ValueSource(booleans={false,true})
    void unavailableOrEndedSessionCannotReturnSemanticProducts(boolean trained) {
        for (var status:List.of(HttpStatus.GONE,HttpStatus.SERVICE_UNAVAILABLE)) {
            var f = new Fixture("10");
            when(f.sessions.activeUntil("account","profile","session")).thenThrow(new ResponseStatusException(status));
            f.context(trained).run(context -> {
                assertThat(context).hasNotFailed();
                assertThatThrownBy(() -> context.getBean(DefaultAgentRecommendService.class).semanticRecall(f.request(Map.of())))
                        .isInstanceOf(ResponseStatusException.class).hasMessageContaining(String.valueOf(status.value()));
                verifyNoInteractions(f.deliveryStore);
            });
        }
    }

    @ParameterizedTest @ValueSource(booleans={false,true})
    void budgetSurvivesHomeToolsAndSemanticFailureFallback(boolean trained) {
        var f = new Fixture("1000");
        f.context(trained).run(context -> {
            var agent = context.getBean(DefaultAgentRecommendService.class);
            var budget = Map.<String,Object>of("price_max",100);
            assertThat(agent.profilePipeline(f.request(budget)).candidates()).isEmpty();
            assertThat(agent.coldFallback(f.request(budget)).candidates()).isEmpty();
            assertThat(agent.candidates(new AgentRecommendCandidatesRequestDTO("agent","session","profile","agent",1,budget,"account")).candidates()).isEmpty();
            assertThat(agent.profilePipeline(f.request(Map.of())).candidates().getFirst().price()).isEqualByComparingTo("1000");
            f.failRecall = true;
            assertThat(agent.semanticRecall(f.request(budget)).candidates()).isEmpty();
        });
    }

    @ParameterizedTest @ValueSource(booleans={false,true})
    void filteringHappensBeforeReturnLimitAndRejectsUnknownPriceWithBudget(boolean trained) {
        var f = new Fixture("1000");
        f.recalled = List.of(f.item, new ItemEmbeddingText("unknown","Unknown","Unknown","books","books","brand",null,Map.of()),
                new ItemEmbeddingText("affordable","Affordable","Affordable","books","books","brand",BigDecimal.TEN,Map.of()));
        f.context(trained).run(context -> {
            var result = f.semantic(context.getBean(DefaultAgentRecommendService.class),Map.of("price_max",100));
            assertThat(result.candidates()).extracting(AgentRecommendCandidateItemVO::itemId).containsExactly("affordable");
            assertThat(f.deliveries.requireFeedbackTarget(ID,result.requestId(),"affordable").items()).extracting(RecommendationDeliveryItem::itemId).containsExactly("affordable");
        });
    }

    @Test
    void candidateTraceAndDeliveryUseTaskSessionInsteadOfProfile() {
        var f = new Fixture("10");
        f.context(false).run(context -> {
            var agent = context.getBean(DefaultAgentRecommendService.class);
            var result = agent.candidates(new AgentRecommendCandidatesRequestDTO("agent","session","profile","agent",1,Map.of(),"account"));
            assertThat(f.traces.getTrace(result.requestId()).sessionId()).isEqualTo("session");
            assertThat(f.deliveries.requireFeedbackTarget(ID,result.requestId(),"item").identity()).isEqualTo(ID);
            verify(f.sessions).activeUntil("account","profile","session");
        });
    }

    @Test
    void persistenceFailurePropagatesAndDisabledRerankRetains503() {
        var f = new Fixture("10");
        doThrow(new IllegalStateException("模拟交付写入失败")).when(f.deliveryStore).save(any());
        f.context(false).run(context -> {
            var agent = context.getBean(DefaultAgentRecommendService.class);
            assertThatThrownBy(() -> agent.semanticRecall(f.request(Map.of()))).isInstanceOf(IllegalStateException.class).hasMessageContaining("交付写入失败");
            assertThatThrownBy(() -> agent.rerankCandidates(f.request(Map.of()))).isInstanceOf(ResponseStatusException.class).hasMessageContaining("503");
        });
    }

    @ParameterizedTest @ValueSource(booleans={false,true})
    void malformedBudgetAndForeignAccountFailBeforeDelivery(boolean trained) {
        var f = new Fixture("10");
        f.context(trained).run(context -> {
            var agent = context.getBean(DefaultAgentRecommendService.class);
            for (var budget:List.of(Map.<String,Object>of("price_max","invalid"),Map.<String,Object>of("price_min",20,"price_max",10))) {
                assertThatThrownBy(() -> agent.semanticRecall(f.request(budget))).isInstanceOf(ResponseStatusException.class).hasMessageContaining("400");
                assertThatThrownBy(() -> agent.profilePipeline(f.request(budget))).isInstanceOf(ResponseStatusException.class).hasMessageContaining("400");
            }
            var other = new AgentRecommendToolRequestDTO("agent","session","session","profile","book",List.of("item"),10,1,false,"agent",Map.of(),"foreign-account");
            when(f.sessions.activeUntil("foreign-account","profile","session")).thenThrow(new ResponseStatusException(HttpStatus.FORBIDDEN));
            assertThatThrownBy(() -> agent.semanticRecall(other)).isInstanceOf(ResponseStatusException.class).hasMessageContaining("403");
            verifyNoInteractions(f.deliveryStore);
        });
    }

    static class MutableClock extends Clock {
        final Instant origin = Instant.parse("2026-10-11T00:00:00Z");
        Instant now = origin;
        public Instant instant() { return now; }
        public ZoneId getZone() { return ZoneOffset.UTC; }
        public Clock withZone(ZoneId zone) { return this; }
        void hours(int hours) { now = origin.plus(Duration.ofHours(hours)); }
    }
    static class Fixture {
        final MutableClock clock = new MutableClock();
        final InMemoryRecommendationFeedbackEventStore events = new InMemoryRecommendationFeedbackEventStore();
        OnlinePreferenceStore preferences = new InMemoryOnlinePreferenceStore(clock);
        final RecommendationSessionValidator sessions = mock(RecommendationSessionValidator.class);
        final InMemoryRecommendTraceService traces = new InMemoryRecommendTraceService();
        final RecommendationDeliveryStore deliveryStore = spy(new InMemoryRecommendationDeliveryStore());
        final DefaultRecommendationDeliveryService deliveries = new DefaultRecommendationDeliveryService(deliveryStore,clock,Duration.ofHours(24));
        DefaultRecommendFeedbackService feedback;
        final ItemEmbeddingText item;
        List<ItemEmbeddingText> recalled;
        boolean failRecall;
        Fixture(String price) {
            item = new ItemEmbeddingText("item","Book","Book","books","books","brand",new BigDecimal(price),Map.of());
            recalled = List.of(item);
            when(sessions.activeUntil("account","profile","session")).thenReturn(clock.origin.plus(Duration.ofHours(24)));
            feedback = new DefaultRecommendFeedbackService(deliveries,events,preferences,clock);
        }
        AgentRecommendToolRequestDTO request(Map<String,Object> constraints) {
            return new AgentRecommendToolRequestDTO("agent","session","session","profile","book",List.of("item"),10,1,false,"agent",constraints,"account").withSemanticDefaults();
        }
        ApplicationContextRunner context(boolean trained) {
            var reader = new SessionPreferenceReader(events,preferences,sessions);
            var catalog = new CatalogEmbeddingTextClient() {
                public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor,int limit) { return "item".compareTo(cursor)>0?List.of(item):List.of(); }
                public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) { return ids.contains("item")?List.of(item):List.of(); }
            };
            var adjustment = new PreferenceAwareFinalReranker(clock,30);
            var home = new DefaultHomeRecommendService(traces,catalog,deliveries,preferences,adjustment);
            home.setSessionPreferenceReader(reader);
            HomeRecommendService homeEntry = new HomeRecommendService() {
                public HomeRecommendVO recommendHome(HomeRecommendRequestDTO request) { return home.recommendHome(request); }
                public HomeRecommendVO recommendHome(RecommendationIdentity identity,HomeRecommendRequestDTO request) {
                    return home.recommendHome(identity,request);
                }
            };
            feedback = new DefaultRecommendFeedbackService(deliveries,events,preferences,clock);
            var runner = new ApplicationContextRunner().withUserConfiguration(DefaultAgentRecommendService.class,TrainedAgentCandidateRanker.class)
                    .withPropertyValues("rs.recommend.trained-ranking.enabled="+trained)
                    .withBean(HomeRecommendService.class,()->homeEntry)
                    .withBean(SemanticItemRecallProvider.class,()->(request,query,limit)->{ if(failRecall) throw new IllegalStateException("模拟召回失败");return recalled; })
                    .withBean(OnlinePreferenceStore.class,()->preferences)
                    .withBean(PreferenceAwareFinalReranker.class,()->adjustment)
                    .withBean(RecommendationDeliveryService.class,()->deliveries)
                    .withBean(RecommendTraceService.class,()->traces)
                    .withBean(SessionPreferenceReader.class,()->reader)
                    .withBean(CatalogEmbeddingTextClient.class,()->catalog)
                    .withBean(HomeModelRanker.class,()->(request,query,items)->{ var scores=new HashMap<String,Double>();items.forEach(i->scores.put(i.itemId(),.8));return scores; })
                    .withBean(RecommendationStageObservation.class,()->new RecommendationStageObservation(false));
            if (trained) runner=runner.withBean(TrainedRankingClient.class,()->(profile,ids,protectedIds,stage,coarse,fine)->
                    new TrainedRankingClient.Result(ids.stream().map(id->new TrainedRankingClient.Item(id,.8,.8,.8)).toList(),ids.size(),ids.size(),ids.size()));
            return runner;
        }
        void dislike() {
            deliveries.record("seed",ID,"home",0,List.of(new RecommendationDeliveryItem("item",1,1,"books","brand",Map.of())));
            assertThat(feedback.recordEvent(ID,new RecommendEventFeedbackRequestDTO("seed","session","item","dislike",-1.0,null)).accepted()).isTrue();
        }
        AgentRecommendCandidatesVO semantic(DefaultAgentRecommendService agent,Map<String,Object> constraints) {
            try {
                MockMvc mvc = MockMvcBuilders.standaloneSetup(new AgentRecommendController(agent,mock(RecommendRagService.class))).build();
                var response = mvc.perform(post("/agent/recommend/semantic-recall").contentType("application/json").content(JSON.writeValueAsBytes(request(constraints)))).andReturn().getResponse();
                assertThat(response.getStatus()).isEqualTo(200);
                return JSON.readValue(response.getContentAsByteArray(),AgentRecommendCandidatesVO.class);
            } catch (Exception error) { throw new RuntimeException(error); }
        }
    }
}
