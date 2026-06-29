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

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DefaultAgentRecommendServiceTest {

    @Test
    void candidatesBridgeAgentRequestToHomeRecommendationPipeline() {
        HomeRecommendService homeRecommendService = request -> {
            assertEquals("A1XYZ", request.sessionId());
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
        assertEquals(1, response.candidates().getFirst().rank());
        assertEquals("B001", response.candidates().getFirst().itemId());
        assertEquals("Portable Desktop Stapler", response.candidates().getFirst().title());
        assertEquals("Office Products > Staplers", response.candidates().getFirst().categoryPath());
        assertEquals("semantic", response.candidates().getFirst().sourceTags().getFirst());
        assertEquals("matches portable stapler", response.candidates().getFirst().shortText());
    }
}
