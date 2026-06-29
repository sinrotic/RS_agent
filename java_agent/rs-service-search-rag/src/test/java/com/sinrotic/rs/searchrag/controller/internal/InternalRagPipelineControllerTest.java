package com.sinrotic.rs.searchrag.controller.internal;

import com.sinrotic.rs.searchrag.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.searchrag.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.searchrag.service.RagPipelineService;
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

class InternalRagPipelineControllerTest {

    private MockMvc mockMvc;

    private RagPipelineService ragPipelineService;

    @BeforeEach
    void setUp() {
        ragPipelineService = mock(RagPipelineService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InternalRagPipelineController(ragPipelineService))
                .build();
    }

    @Test
    void runExecutesFullRagPipelineWithEsAndMilvusProviders() throws Exception {
        RagPipelineRunVO response = new RagPipelineRunVO(
                "rag_req_001",
                "run",
                List.of(
                        new RagPipelineProviderStatusVO("elasticsearch_bm25", "UP", 50, 18),
                        new RagPipelineProviderStatusVO("milvus_vector", "UP", 50, 31)
                ),
                Map.of("elasticsearch_bm25", 42, "milvus_vector", 38),
                new RagPipelineStageCountsVO(100, 80, 8, 3, 3),
                List.of(new RagSupportSnippetVO("description", "Candidate evidence summary.", "candidate-scoped description"))
        );
        when(ragPipelineService.run(argThat(request ->
                "rag_req_001".equals(request.requestId())
                        && "sess_001".equals(request.sessionId())
                        && "cheap commuter backpack".equals(request.query())
                        && request.candidateItemIds().equals(List.of("B001", "B002"))
                        && request.providers().equals(List.of("elasticsearch_bm25", "milvus_vector"))
                        && request.topKPerProvider() == 50
                        && request.mergedTopK() == 80
                        && request.rerankTopK() == 8
                        && request.small2big()
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/rag/pipeline/run")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "request_id": "rag_req_001",
                                  "session_id": "sess_001",
                                  "query": "cheap commuter backpack",
                                  "candidate_item_ids": ["B001", "B002"],
                                  "top_k_per_provider": 50,
                                  "merged_top_k": 80,
                                  "rerank_top_k": 8
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rag_req_001"))
                .andExpect(jsonPath("$.stage").value("run"))
                .andExpect(jsonPath("$.providers[0].provider").value("elasticsearch_bm25"))
                .andExpect(jsonPath("$.providers[1].provider").value("milvus_vector"))
                .andExpect(jsonPath("$.source_distribution.elasticsearch_bm25").value(42))
                .andExpect(jsonPath("$.stage_counts.raw_recall_count").value(100))
                .andExpect(jsonPath("$.stage_counts.rerank_count").value(8))
                .andExpect(jsonPath("$.support[0].field").value("description"));

        verify(ragPipelineService).run(argThat(request ->
                request.providers().equals(List.of("elasticsearch_bm25", "milvus_vector"))
                        && request.small2big()
        ));
    }
}
