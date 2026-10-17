package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendCandidatesRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendConfigVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendDisplayVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.service.impl.DefaultAgentRecommendService;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

class DefaultAgentRecommendServiceTest {

    @Test
    void candidatesBridgeAgentRequestToHomeRecommendationPipeline() {
        HomeRecommendService homeRecommendService = request -> {
            assertEquals("task_001", request.sessionId());
            assertEquals("home", request.scene());
            assertEquals(10, request.pageSize());
            return new HomeRecommendVO(
                    "rec_req_agent_001",
                    request.sessionId(),
                    request.scene(),
                    "A1XYZ",
                    List.of(new RecommendItemVO(
                            "B001",
                            1,
                            0.932,
                            "agent candidate",
                            List.of("semantic"),
                            new RecommendDisplayVO("Commuter Backpack", "Backpacks", "Urban Carry", "")
                    )),
                    false,
                    "",
                    new HomeRecommendConfigVO(500, 100, 50, 20, 8)
            );
        };
        DefaultAgentRecommendService service = new DefaultAgentRecommendService(homeRecommendService);

        var response = service.candidates(new AgentRecommendCandidatesRequestDTO(
                "agent_001",
                "task_001",
                "A1XYZ",
                "home",
                10,
                Map.of("category", "Backpacks")
        ).withDefaults());

        assertEquals("rec_req_agent_001", response.requestId());
        assertEquals("agent_001", response.agentId());
        assertEquals("task_001", response.taskId());
        assertEquals("A1XYZ", response.profileUserId());
        assertEquals("B001", response.candidates().getFirst().itemId());
    }

    @Test
    void semanticRecallUsesAgentMinimalCandidateContract() {
        HomeRecommendService homeRecommendService = request -> new HomeRecommendVO(
                "rec_req_semantic_001",
                request.sessionId(),
                request.scene(),
                "A1XYZ",
                List.of(new RecommendItemVO(
                        "B001",
                        1,
                        0.932,
                        "matches portable stapler",
                        List.of("semantic"),
                        new RecommendDisplayVO("Portable Desktop Stapler", "Office Products > Staplers", "", "")
                )),
                false,
                "",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        );
        DefaultAgentRecommendService service = new DefaultAgentRecommendService(homeRecommendService);

        var response = service.semanticRecall(new AgentRecommendToolRequestDTO(
                "agent_001",
                "task_001",
                "sess_001",
                "A1XYZ",
                "portable stapler",
                null,
                null,
                null,
                null,
                null,
                Map.of()
        ).withSemanticDefaults());

        assertEquals("rec_req_semantic_001", response.requestId());
        assertEquals("B001", response.candidates().getFirst().itemId());
        assertEquals("Portable Desktop Stapler", response.candidates().getFirst().title());
        assertEquals("Office Products > Staplers", response.candidates().getFirst().categoryPath());
        assertEquals("matches portable stapler", response.candidates().getFirst().shortText());
        assertEquals("matches portable stapler", response.candidates().getFirst().reasonHint());
    }

    @Test
    void semanticRecallUsesTheQueryAwareProvider() {
        HomeRecommendService homeRecommendService = request -> new HomeRecommendVO(
                "fallback", request.sessionId(), request.scene(), "A1XYZ", List.of(), false, "",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        );
        SemanticItemRecallProvider provider = (requestId, query, limit) -> List.of(new com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText(
                query.contains("headphones") ? "HEADPHONES" : "STAPLER",
                "", query, "category", "category", "brand", BigDecimal.TEN, Map.of()
        ));
        DefaultAgentRecommendService service = new DefaultAgentRecommendService(homeRecommendService, provider);
        var preferences = new com.sinrotic.rs.recommend.service.impl.InMemoryOnlinePreferenceStore();
        var sessions = org.mockito.Mockito.mock(RecommendationSessionValidator.class);
        org.mockito.Mockito.when(sessions.activeUntil("A1XYZ","A1XYZ","sess_001"))
                .thenReturn(java.time.Instant.now().plus(java.time.Duration.ofHours(24)));
        var ranker = new com.sinrotic.rs.recommend.service.impl.TrainedAgentCandidateRanker(
                null, org.mockito.Mockito.mock(HomeModelRanker.class), (cursor,limit)->List.of(), preferences,
                new com.sinrotic.rs.recommend.service.impl.PreferenceAwareFinalReranker(),
                new com.sinrotic.rs.recommend.service.impl.DefaultRecommendationDeliveryService(
                        new com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationDeliveryStore(),java.time.Clock.systemUTC(),java.time.Duration.ofHours(24)),
                new com.sinrotic.rs.recommend.service.impl.InMemoryRecommendTraceService());
        ranker.setSessionPreferenceReader(new com.sinrotic.rs.recommend.service.impl.SessionPreferenceReader(
                new com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationFeedbackEventStore(),preferences,sessions));
        service.setTrainedAgentRanker(ranker);

        var headphones = service.semanticRecall(semanticRequest("noise cancelling headphones"));
        var stapler = service.semanticRecall(semanticRequest("desktop stapler"));

        assertNotEquals(headphones.candidates().getFirst().itemId(), stapler.candidates().getFirst().itemId());
        assertEquals("HEADPHONES", headphones.candidates().getFirst().itemId());
        assertEquals("STAPLER", stapler.candidates().getFirst().itemId());
    }

    @Test
    void filtersCandidatesByPriceRangeAndRequiresKnownPriceWithBudget() {
        DefaultAgentRecommendService service = new DefaultAgentRecommendService(request -> new HomeRecommendVO(
                "rec_req_price_001",
                request.sessionId(),
                request.scene(),
                "A1XYZ",
                List.of(),
                false,
                "",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        ));

        var candidates = List.of(
                new com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO(
                        "B_LOW",
                        "Budget Earbuds",
                        "Electronics > Headphones",
                        new BigDecimal("299.00"),
                        "",
                        "within budget",
                        "within budget"
                ),
                new com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO(
                        "B_HIGH",
                        "Premium Headphones",
                        "Electronics > Headphones",
                        new BigDecimal("1299.00"),
                        "",
                        "over budget",
                        "over budget"
                ),
                new com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO(
                        "B_UNKNOWN",
                        "Unknown Price Earbuds",
                        "Electronics > Headphones",
                        null,
                        "",
                        "price missing",
                        "price missing"
                )
        );

        var filtered = service.filterCandidatesForAgent(
                candidates,
                Map.of("price_min", 200, "price_max", 500)
        );

        assertEquals(List.of("B_LOW"), filtered.stream()
                .map(com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO::itemId)
                .toList());
    }

    private AgentRecommendToolRequestDTO semanticRequest(String query) {
        return new AgentRecommendToolRequestDTO(
                "agent_001", "task_001", "sess_001", "A1XYZ", query,
                null, 20, 5, null, "agent", Map.of()
        ).withSemanticDefaults();
    }
}
