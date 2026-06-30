package com.sinrotic.rs.recommend.controller.internal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.recommend.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.recommend.service.RagPipelineService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalRecommendRagPipelineControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private RagPipelineService ragPipelineService;

    @BeforeEach
    void setUp() {
        ragPipelineService = mock(RagPipelineService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InternalRecommendRagPipelineController(ragPipelineService))
                .build();
    }

    @Test
    void runUsesRecommendRagPipelineEndpointAndDefaults() throws Exception {
        RagPipelineRunVO response = new RagPipelineRunVO(
                "rag_req_001",
                "run",
                List.of(new RagPipelineProviderStatusVO("elasticsearch_bm25", "READY", 2, 11)),
                Map.of("elasticsearch_bm25", 2),
                new RagPipelineStageCountsVO(2, 2, 1, 1, 1),
                List.of(new RagSupportSnippetVO("evidence", "Compressed candidate support.", "small2big"))
        );
        when(ragPipelineService.run(argThat(request ->
                "rag_req_001".equals(request.requestId())
                        && "bluetooth earbuds".equals(request.query())
                        && request.candidateItemIds().contains("B001")
                        && request.providers().contains("elasticsearch_bm25")
                        && request.rerankTopK() == 8
                        && request.small2big()
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/recommend/rag/pipeline/run")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rag_req_001",
                                "query", "bluetooth earbuds",
                                "candidate_item_ids", List.of("B001", "B002")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rag_req_001"))
                .andExpect(jsonPath("$.providers[0].provider").value("elasticsearch_bm25"))
                .andExpect(jsonPath("$.stage_counts.rerank_count").value(1))
                .andExpect(jsonPath("$.support[0].summary").value("Compressed candidate support."));
    }
}
