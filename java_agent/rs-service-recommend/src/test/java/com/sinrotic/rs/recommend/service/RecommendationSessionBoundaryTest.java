package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.controller.app.*;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class RecommendationSessionBoundaryTest {
    final ObjectMapper json = new ObjectMapper();
    final InMemoryOnlinePreferenceStore preferences = new InMemoryOnlinePreferenceStore();
    final InMemoryRecommendationFeedbackEventStore events = new InMemoryRecommendationFeedbackEventStore();
    final DefaultRecommendationDeliveryService deliveries = new DefaultRecommendationDeliveryService(
            new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
    final RecommendationSessionValidator sessions = (account, profile, session) -> {
        if (!"shared-profile".equals(profile) || !("session-" + account).equals(session))
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
    };

    MockMvc mvc(RecommendationSessionValidator validator) {
        var catalog = new ItemEmbeddingText("item", "Book", "Book", "books", "books", "brand", BigDecimal.TEN, Map.of());
        var home = new DefaultHomeRecommendService(mock(RecommendTraceService.class), (cursor,limit) -> List.of(catalog),
                deliveries, preferences, new PreferenceAwareFinalReranker());
        var feedback = new DefaultRecommendFeedbackService(deliveries, events, preferences, Clock.systemUTC());
        return MockMvcBuilders.standaloneSetup(new HomeRecommendController(home, validator),
                new RecommendFeedbackController(feedback, validator)).build();
    }

    @ParameterizedTest
    @ValueSource(strings = {"/api/recommend/home", "/api/recommend/home/refresh"})
    void refusesForeignAndMissingSessionsBeforeDelivering(String endpoint) throws Exception {
        var mvc = mvc(sessions);
        for (String session : List.of("session-B", "never-created"))
            mvc.perform(post(endpoint).header("X-Account-Id", "A").header("X-Profile-User-Id", "shared-profile")
                    .contentType("application/json").content(json.writeValueAsString(Map.of("session_id", session))))
                    .andExpect(status().isNotFound());
        assertThat(preferences.loadProfile("shared-profile").itemPreferences()).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {"/api/recommend/feedback/event", "/api/recommend/feedback/exposure"})
    void refusesPreviouslyIssuedForeignSessionDeliveryBeforeAnyFeedbackWrites(String endpoint) throws Exception {
        var foreign = new RecommendationIdentity("A", "shared-profile", "session-B");
        deliveries.record("old-invalid-delivery", foreign, "home", 0,
                List.of(new RecommendationDeliveryItem("item",1,1,"books","brand",Map.of())));
        mvc(sessions).perform(post(endpoint).header("X-Account-Id", "A").header("X-Profile-User-Id", "shared-profile")
                .contentType("application/json").content(json.writeValueAsString(Map.of(
                        "request_id", "old-invalid-delivery", "session_id", "session-B", "item_id", "item",
                        "event_type", "like", "item_ids", List.of("item")))))
                .andExpect(status().isNotFound());
        assertThat(events.rebuildablePreferenceEvents(100)).isEmpty();
        assertThat(preferences.load(new RecommendationIdentity("B","shared-profile","session-B")).itemPreferences()).isEmpty();
    }

    @Test
    void ownedSessionFeedbackOnlySharesWeakProfilePreferenceWithOtherSession() throws Exception {
        var mvc = mvc(sessions);
        var home = mvc.perform(post("/api/recommend/home").header("X-Account-Id", "A").header("X-Profile-User-Id", "shared-profile")
                .contentType("application/json").content("{\"session_id\":\"session-A\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        String request = json.readTree(home.getContentAsString()).path("request_id").asText();
        mvc.perform(post("/api/recommend/feedback/event").header("X-Account-Id", "A").header("X-Profile-User-Id", "shared-profile")
                .contentType("application/json").content(json.writeValueAsString(Map.of(
                        "request_id",request,"session_id","session-A","item_id","item","event_type","like"))))
                .andExpect(status().isOk());
        assertThat(preferences.load(new RecommendationIdentity("A","shared-profile","session-A")).itemPreferences().get("item").scope()).isEqualTo("session");
        assertThat(preferences.load(new RecommendationIdentity("B","shared-profile","session-B")).itemPreferences().get("item").scope()).isEqualTo("profile");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/api/recommend/home", "/api/recommend/home/refresh", "/api/recommend/feedback/event", "/api/recommend/feedback/exposure"})
    void endedSessionsAndUnavailableAuthorityFailBeforeAnySideEffects(String endpoint) throws Exception {
        for (HttpStatus failure : List.of(HttpStatus.GONE, HttpStatus.SERVICE_UNAVAILABLE)) {
            var mvc = mvc((account,profile,session) -> {throw new ResponseStatusException(failure);});
            mvc.perform(post(endpoint).header("X-Account-Id", "A").header("X-Profile-User-Id", "shared-profile")
                    .contentType("application/json").content(json.writeValueAsString(Map.of(
                            "session_id","session-A","request_id","none","item_id","item","event_type","like","item_ids",List.of("item")))))
                    .andExpect(status().is(failure.value()));
        }
        assertThat(events.rebuildablePreferenceEvents(100)).isEmpty();
    }
}
