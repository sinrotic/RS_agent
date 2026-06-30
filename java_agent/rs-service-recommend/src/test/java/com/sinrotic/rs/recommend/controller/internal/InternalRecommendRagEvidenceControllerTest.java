package com.sinrotic.rs.recommend.controller.internal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.RagEvidenceBatchVO;
import com.sinrotic.rs.recommend.domain.vo.RagEvidenceItemVO;
import com.sinrotic.rs.recommend.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.recommend.service.RagEvidenceService;
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

class InternalRecommendRagEvidenceControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private RagEvidenceService ragEvidenceService;

    @BeforeEach
    void setUp() {
        ragEvidenceService = mock(RagEvidenceService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InternalRecommendRagEvidenceController(ragEvidenceService))
                .build();
    }

    @Test
    void batchEvidenceUsesRecommendRagEndpointAndDefaults() throws Exception {
        RagEvidenceBatchVO response = new RagEvidenceBatchVO(
                "rag_req_001",
                List.of(new RagEvidenceItemVO(
                        "B001",
                        List.of(new RagSupportSnippetVO("evidence", "Evidence for B001.", "candidate-scoped evidence"))
                ))
        );
        when(ragEvidenceService.batchEvidence(argThat(request ->
                "rag_req_001".equals(request.requestId())
                        && request.itemIds().contains("B001")
                        && request.maxSupportPerItem() == 3
                        && request.maxTextChars() == 220
                        && request.includeParentProfile()
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/recommend/rag/batch-evidence")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rag_req_001",
                                "item_ids", List.of("B001")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rag_req_001"))
                .andExpect(jsonPath("$.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.items[0].evidence[0].summary").value("Evidence for B001."));

        verify(ragEvidenceService).batchEvidence(argThat(request ->
                request.itemIds().contains("B001") && request.includeParentProfile()
        ));
    }
}
