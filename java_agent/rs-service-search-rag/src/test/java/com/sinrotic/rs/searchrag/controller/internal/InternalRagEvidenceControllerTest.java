package com.sinrotic.rs.searchrag.controller.internal;

import com.sinrotic.rs.searchrag.domain.vo.RagEvidenceBatchVO;
import com.sinrotic.rs.searchrag.domain.vo.RagEvidenceItemVO;
import com.sinrotic.rs.searchrag.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.searchrag.service.RagEvidenceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalRagEvidenceControllerTest {

    private MockMvc mockMvc;

    private RagEvidenceService ragEvidenceService;

    @BeforeEach
    void setUp() {
        ragEvidenceService = mock(RagEvidenceService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InternalRagEvidenceController(ragEvidenceService))
                .build();
    }

    @Test
    void batchEvidenceReturnsCandidateScopedEvidenceForItems() throws Exception {
        RagEvidenceBatchVO response = new RagEvidenceBatchVO(
                "rag_req_001",
                List.of(
                        new RagEvidenceItemVO(
                                "B001",
                                List.of(new RagSupportSnippetVO("description", "Lightweight backpack.", "candidate-scoped description"))
                        ),
                        new RagEvidenceItemVO(
                                "B002",
                                List.of(new RagSupportSnippetVO("features", "Large capacity.", "candidate-scoped features"))
                        )
                )
        );
        when(ragEvidenceService.batchEvidence(argThat(request ->
                "rag_req_001".equals(request.requestId())
                        && request.itemIds().equals(List.of("B001", "B002"))
                        && request.maxSupportPerItem() == 3
                        && request.maxTextChars() == 220
                        && request.includeParentProfile()
        ))).thenReturn(response);

        mockMvc.perform(post("/internal/rag/batch-evidence")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "request_id": "rag_req_001",
                                  "item_ids": ["B001", "B002"]
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rag_req_001"))
                .andExpect(jsonPath("$.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.items[0].evidence[0].field").value("description"))
                .andExpect(jsonPath("$.items[1].item_id").value("B002"))
                .andExpect(jsonPath("$.items[1].evidence[0].summary").value("Large capacity."));

        verify(ragEvidenceService).batchEvidence(argThat(request ->
                request.itemIds().equals(List.of("B001", "B002"))
                        && request.includeParentProfile()
        ));
    }
}
