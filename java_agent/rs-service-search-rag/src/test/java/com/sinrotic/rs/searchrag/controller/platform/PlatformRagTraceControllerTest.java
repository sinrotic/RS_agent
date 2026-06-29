package com.sinrotic.rs.searchrag.controller.platform;

import com.sinrotic.rs.searchrag.domain.vo.RagHealthProviderVO;
import com.sinrotic.rs.searchrag.domain.vo.RagHealthVO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.searchrag.domain.vo.RagTraceVO;
import com.sinrotic.rs.searchrag.service.RagTraceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformRagTraceControllerTest {

    private MockMvc mockMvc;

    private RagTraceService ragTraceService;

    @BeforeEach
    void setUp() {
        ragTraceService = mock(RagTraceService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new PlatformRagTraceController(ragTraceService))
                .build();
    }

    @Test
    void getTraceReturnsRagPipelineObservation() throws Exception {
        RagTraceVO response = new RagTraceVO(
                "rag_req_001",
                "cheap commuter backpack",
                "cheap commuter backpack",
                List.of(
                        new RagPipelineProviderStatusVO("elasticsearch_bm25", "UP", 50, 18),
                        new RagPipelineProviderStatusVO("milvus_vector", "UP", 50, 31)
                ),
                Map.of("elasticsearch_bm25", 42, "milvus_vector", 38),
                new RagPipelineStageCountsVO(100, 80, 8, 3, 3),
                "",
                71
        );
        when(ragTraceService.getTrace("rag_req_001")).thenReturn(response);

        mockMvc.perform(get("/api/platform/rag/rag_req_001/trace"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rag_req_001"))
                .andExpect(jsonPath("$.query_rewrite").value("cheap commuter backpack"))
                .andExpect(jsonPath("$.providers[0].provider").value("elasticsearch_bm25"))
                .andExpect(jsonPath("$.providers[1].provider").value("milvus_vector"))
                .andExpect(jsonPath("$.source_distribution.milvus_vector").value(38))
                .andExpect(jsonPath("$.stage_counts.compressed_support_count").value(3))
                .andExpect(jsonPath("$.latency_ms").value(71));

        verify(ragTraceService).getTrace("rag_req_001");
    }

    @Test
    void healthReturnsProviderReadiness() throws Exception {
        RagHealthVO response = new RagHealthVO(
                "UP",
                List.of(
                        new RagHealthProviderVO("elasticsearch_bm25", "UP", "rs_agent_rag_bm25_v1", ""),
                        new RagHealthProviderVO("milvus_vector", "UP", "", "rs_agent_rag_chunks_milvus_v1")
                )
        );
        when(ragTraceService.health()).thenReturn(response);

        mockMvc.perform(get("/api/platform/rag/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.providers[0].provider").value("elasticsearch_bm25"))
                .andExpect(jsonPath("$.providers[0].index_name").value("rs_agent_rag_bm25_v1"))
                .andExpect(jsonPath("$.providers[1].provider").value("milvus_vector"))
                .andExpect(jsonPath("$.providers[1].collection_name").value("rs_agent_rag_chunks_milvus_v1"));

        verify(ragTraceService).health();
    }
}
