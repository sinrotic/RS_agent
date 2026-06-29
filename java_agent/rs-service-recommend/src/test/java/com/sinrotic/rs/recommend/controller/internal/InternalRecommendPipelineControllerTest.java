package com.sinrotic.rs.recommend.controller.internal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.domain.vo.PipelineRecallVO;
import com.sinrotic.rs.recommend.service.RecommendPipelineService;
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

class InternalRecommendPipelineControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private RecommendPipelineService recommendPipelineService;

    @BeforeEach
    void setUp() {
        recommendPipelineService = mock(RecommendPipelineService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InternalRecommendPipelineController(recommendPipelineService))
                .build();
    }

    @Test
    void recallReturnsCandidatePoolAndSourceDistribution() throws Exception {
        PipelineRecallVO response = new PipelineRecallVO(
                "rec_req_recall_001",
                "recall",
                500,
                Map.of(
                        "itemcf_strong", 150,
                        "semantic", 100
                ),
                List.of(new PipelineCandidateVO(
                        "B001",
                        "itemcf_strong",
                        0.81,
                        null,
                        null,
                        null
                ))
        );
        when(recommendPipelineService.recall(argThat(request ->
                "A1XYZ".equals(request.profileUserId())
                        && "sess_001".equals(request.sessionId())
                        && request.limit() == 500
                        && request.sources().contains("itemcf_strong")
                        && request.sources().contains("semantic")
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/recommend/pipeline/recall")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "profile_user_id", "A1XYZ",
                                "session_id", "sess_001",
                                "limit", 500,
                                "sources", List.of("itemcf_strong", "semantic")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_recall_001"))
                .andExpect(jsonPath("$.stage").value("recall"))
                .andExpect(jsonPath("$.candidate_count").value(500))
                .andExpect(jsonPath("$.source_distribution.itemcf_strong").value(150))
                .andExpect(jsonPath("$.source_distribution.semantic").value(100))
                .andExpect(jsonPath("$.candidates[0].item_id").value("B001"))
                .andExpect(jsonPath("$.candidates[0].recall_score").value(0.81));

        verify(recommendPipelineService).recall(argThat(request ->
                "A1XYZ".equals(request.profileUserId())
                        && "sess_001".equals(request.sessionId())
                        && request.limit() == 500
        ));
    }

    @Test
    void coarseRankReturnsTopCandidatesWithCoarseScores() throws Exception {
        PipelineRecallVO response = new PipelineRecallVO(
                "rec_req_003",
                "coarse_rank",
                100,
                Map.of(),
                List.of(new PipelineCandidateVO(
                        "B001",
                        "itemcf_strong",
                        0.81,
                        0.73,
                        null,
                        null
                ))
        );
        when(recommendPipelineService.coarseRank(argThat(request ->
                "rec_req_003".equals(request.requestId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.candidateItemIds().contains("B001")
                        && request.limit() == 100
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/recommend/pipeline/coarse-rank")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rec_req_003",
                                "profile_user_id", "A1XYZ",
                                "candidate_item_ids", List.of("B001", "B002"),
                                "limit", 100
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_003"))
                .andExpect(jsonPath("$.stage").value("coarse_rank"))
                .andExpect(jsonPath("$.candidate_count").value(100))
                .andExpect(jsonPath("$.candidates[0].item_id").value("B001"))
                .andExpect(jsonPath("$.candidates[0].coarse_score").value(0.73));

        verify(recommendPipelineService).coarseRank(argThat(request ->
                "rec_req_003".equals(request.requestId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.limit() == 100
        ));
    }

    @Test
    void fineRankReturnsTopCandidatesWithFineScores() throws Exception {
        PipelineRecallVO response = new PipelineRecallVO(
                "rec_req_004",
                "fine_rank",
                50,
                Map.of(),
                List.of(new PipelineCandidateVO(
                        "B001",
                        "itemcf_strong",
                        0.81,
                        0.73,
                        0.91,
                        null
                ))
        );
        when(recommendPipelineService.fineRank(argThat(request ->
                "rec_req_004".equals(request.requestId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.candidateItemIds().contains("B001")
                        && request.limit() == 50
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/recommend/pipeline/fine-rank")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rec_req_004",
                                "profile_user_id", "A1XYZ",
                                "candidate_item_ids", List.of("B001", "B002"),
                                "limit", 50
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_004"))
                .andExpect(jsonPath("$.stage").value("fine_rank"))
                .andExpect(jsonPath("$.candidate_count").value(50))
                .andExpect(jsonPath("$.candidates[0].item_id").value("B001"))
                .andExpect(jsonPath("$.candidates[0].fine_score").value(0.91));

        verify(recommendPipelineService).fineRank(argThat(request ->
                "rec_req_004".equals(request.requestId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.limit() == 50
        ));
    }

    @Test
    void finalRerankReturnsFinalCandidatesWithFinalScores() throws Exception {
        PipelineRecallVO response = new PipelineRecallVO(
                "rec_req_005",
                "final_rerank",
                20,
                Map.of(),
                List.of(new PipelineCandidateVO(
                        "B001",
                        "itemcf_strong",
                        0.81,
                        0.73,
                        0.91,
                        0.95
                ))
        );
        when(recommendPipelineService.finalRerank(argThat(request ->
                "rec_req_005".equals(request.requestId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.candidateItemIds().contains("B001")
                        && request.excludeItemIds().contains("B010")
                        && request.diversity().get("category_max_per_page").equals(6)
                        && request.limit() == 20
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/recommend/pipeline/final-rerank")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rec_req_005",
                                "profile_user_id", "A1XYZ",
                                "candidate_item_ids", List.of("B001", "B002"),
                                "exclude_item_ids", List.of("B010"),
                                "limit", 20,
                                "diversity", Map.of(
                                        "category_max_per_page", 6,
                                        "store_max_per_page", 4,
                                        "source_max_ratio", 0.6
                                )
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_005"))
                .andExpect(jsonPath("$.stage").value("final_rerank"))
                .andExpect(jsonPath("$.candidate_count").value(20))
                .andExpect(jsonPath("$.candidates[0].item_id").value("B001"))
                .andExpect(jsonPath("$.candidates[0].final_score").value(0.95));

        verify(recommendPipelineService).finalRerank(argThat(request ->
                "rec_req_005".equals(request.requestId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.limit() == 20
        ));
    }
}
