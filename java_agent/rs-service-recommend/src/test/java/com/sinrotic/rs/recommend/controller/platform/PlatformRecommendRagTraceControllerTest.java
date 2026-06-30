package com.sinrotic.rs.recommend.controller.platform;

import com.sinrotic.rs.recommend.domain.vo.RagHealthProviderVO;
import com.sinrotic.rs.recommend.domain.vo.RagHealthVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.recommend.domain.vo.RagTraceVO;
import com.sinrotic.rs.recommend.service.RagTraceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformRecommendRagTraceControllerTest {

    private MockMvc mockMvc;

    private RagTraceService ragTraceService;

    @BeforeEach
    void setUp() {
        ragTraceService = mock(RagTraceService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new PlatformRecommendRagTraceController(ragTraceService))
                .build();
    }

    @Test
    void getTraceUsesRecommendPlatformEndpoint() throws Exception {
        when(ragTraceService.getTrace("rag_req_001")).thenReturn(new RagTraceVO(
                "rag_req_001",
                "bluetooth earbuds",
                "bluetooth earbuds",
                List.of(new RagPipelineProviderStatusVO("milvus_vector", "READY", 3, 15)),
                Map.of("milvus_vector", 3),
                new RagPipelineStageCountsVO(3, 3, 2, 2, 2),
                "",
                15
        ));

        mockMvc.perform(get("/api/platform/recommend/rag/rag_req_001/trace"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rag_req_001"))
                .andExpect(jsonPath("$.providers[0].provider").value("milvus_vector"))
                .andExpect(jsonPath("$.latency_ms").value(15));
    }

    @Test
    void healthUsesRecommendPlatformEndpoint() throws Exception {
        when(ragTraceService.health()).thenReturn(new RagHealthVO(
                "UP",
                List.of(new RagHealthProviderVO("elasticsearch_bm25", "READY", "rs_agent_rag_bm25_v1", ""))
        ));

        mockMvc.perform(get("/api/platform/recommend/rag/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.providers[0].provider").value("elasticsearch_bm25"));
    }
}
