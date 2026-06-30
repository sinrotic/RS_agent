package com.sinrotic.rs.recommend.controller.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidatesVO;
import com.sinrotic.rs.recommend.service.AgentRecommendService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AgentRecommendControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private AgentRecommendService agentRecommendService;

    @BeforeEach
    void setUp() {
        agentRecommendService = mock(AgentRecommendService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new AgentRecommendController(agentRecommendService))
                .build();
    }

    @Test
    void candidatesReturnsAgentReadyRecommendItems() throws Exception {
        AgentRecommendCandidatesVO response = new AgentRecommendCandidatesVO(
                "agent_req_001",
                "agent_001",
                "task_001",
                "A1XYZ",
                List.of(new AgentRecommendCandidateItemVO(
                        "B001",
                        "Commuter Backpack",
                        "Backpacks",
                        null,
                        "",
                        "agent candidate",
                        "matches broad backpack needs"
                ))
        );
        when(agentRecommendService.candidates(argThat(request ->
                "agent_001".equals(request.agentId())
                        && "task_001".equals(request.taskId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.limit() == 20
                        && request.constraints().get("category").equals("Backpacks")
        ))).thenReturn(response);

        mockMvc.perform(post("/agent/recommend/candidates")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "agent_id", "agent_001",
                                "task_id", "task_001",
                                "profile_user_id", "A1XYZ",
                                "scene", "home",
                                "limit", 20,
                                "constraints", Map.of("category", "Backpacks")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.agent_id").value("agent_001"))
                .andExpect(jsonPath("$.task_id").value("task_001"))
                .andExpect(jsonPath("$.profile_user_id").value("A1XYZ"))
                .andExpect(jsonPath("$.candidates[0].item_id").value("B001"));

        verify(agentRecommendService).candidates(argThat(request ->
                "agent_001".equals(request.agentId())
                        && request.limit() == 20
        ));
    }

    @Test
    void semanticRecallReturnsAgentMinimalCandidateFields() throws Exception {
        AgentRecommendCandidatesVO response = agentCandidates("rec_req_semantic_001", "semantic");
        when(agentRecommendService.semanticRecall(argThat(request ->
                "agent_001".equals(request.agentId())
                        && "task_001".equals(request.taskId())
                        && "sess_001".equals(request.sessionId())
                        && "A1XYZ".equals(request.profileUserId())
                        && "portable stapler".equals(request.query())
                        && request.recallLimit() == 100
                        && request.returnCount() == 20
        ))).thenReturn(response);

        mockMvc.perform(post("/agent/recommend/semantic-recall")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "agent_id", "agent_001",
                                "task_id", "task_001",
                                "session_id", "sess_001",
                                "profile_user_id", "A1XYZ",
                                "query", "portable stapler"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_semantic_001"))
                .andExpect(jsonPath("$.candidates[0].item_id").value("B001"))
                .andExpect(jsonPath("$.candidates[0].title").value("Portable Desktop Stapler"))
                .andExpect(jsonPath("$.candidates[0].category_path").value("Office Products > Staplers"))
                .andExpect(jsonPath("$.candidates[0].price").value(13.99))
                .andExpect(jsonPath("$.candidates[0].rating_summary").value("评分 4.3，约 186 条评价"))
                .andExpect(jsonPath("$.candidates[0].short_text").value("Portable stapler for office and student use."))
                .andExpect(jsonPath("$.candidates[0].reason_hint").value("Matches portable office use."));

        verify(agentRecommendService).semanticRecall(argThat(request ->
                request.recallLimit() == 100
                        && request.returnCount() == 20
        ));
    }

    @Test
    void profilePipelineReturnsDefaultTwentyCandidates() throws Exception {
        AgentRecommendCandidatesVO response = agentCandidates("rec_req_profile_001", "profile");
        when(agentRecommendService.profilePipeline(argThat(request ->
                "A1XYZ".equals(request.profileUserId())
                        && request.returnCount() == 20
        ))).thenReturn(response);

        mockMvc.perform(post("/agent/recommend/profile-pipeline")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "profile_user_id", "A1XYZ"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_profile_001"))
                .andExpect(jsonPath("$.candidates[0].reason_hint").value("Matches portable office use."));
    }

    @Test
    void coldFallbackReturnsDefaultTwentyFallbackCandidates() throws Exception {
        AgentRecommendCandidatesVO response = agentCandidates("rec_req_cold_001", "cold_fallback");
        when(agentRecommendService.coldFallback(argThat(request ->
                request.returnCount() == 20
                        && Boolean.TRUE.equals(request.diversityRequired())
        ))).thenReturn(response);

        mockMvc.perform(post("/agent/recommend/cold-fallback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_cold_001"))
                .andExpect(jsonPath("$.candidates[0].short_text").value("Portable stapler for office and student use."));
    }

    @Test
    void rerankCandidatesReturnsDefaultTwentyCandidates() throws Exception {
        AgentRecommendCandidatesVO response = agentCandidates("rec_req_rerank_001", "rerank");
        when(agentRecommendService.rerankCandidates(argThat(request ->
                request.candidateItemIds().contains("B001")
                        && request.returnCount() == 20
        ))).thenReturn(response);

        mockMvc.perform(post("/agent/recommend/rerank")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "candidate_item_ids", List.of("B001", "B002")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_rerank_001"))
                .andExpect(jsonPath("$.candidates[0].reason_hint").value("Matches portable office use."));
    }

    private AgentRecommendCandidatesVO agentCandidates(String requestId, String sourceTag) {
        return new AgentRecommendCandidatesVO(
                requestId,
                "agent_001",
                "task_001",
                "A1XYZ",
                List.of(new AgentRecommendCandidateItemVO(
                        "B001",
                        "Portable Desktop Stapler",
                        "Office Products > Staplers",
                        new java.math.BigDecimal("13.99"),
                        "评分 4.3，约 186 条评价",
                        "Portable stapler for office and student use.",
                        "Matches portable office use."
                ))
        );
    }
}
