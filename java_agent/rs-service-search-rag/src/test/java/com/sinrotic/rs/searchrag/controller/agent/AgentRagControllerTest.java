package com.sinrotic.rs.searchrag.controller.agent;

import com.sinrotic.rs.searchrag.domain.vo.AgentRagSupportVO;
import com.sinrotic.rs.searchrag.domain.vo.RagAgentContextVO;
import com.sinrotic.rs.searchrag.domain.vo.RagGovernanceVO;
import com.sinrotic.rs.searchrag.domain.vo.RagItemSupportVO;
import com.sinrotic.rs.searchrag.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.searchrag.service.AgentRagService;
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

class AgentRagControllerTest {

    private MockMvc mockMvc;

    private AgentRagService agentRagService;

    @BeforeEach
    void setUp() {
        agentRagService = mock(AgentRagService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new AgentRagController(agentRagService))
                .build();
    }

    @Test
    void supportReturnsAgentGroundingContextWithDefaultEsAndMilvusProviders() throws Exception {
        AgentRagSupportVO response = new AgentRagSupportVO(
                "agent_req_001",
                "affordable commuter backpack",
                true,
                List.of("elasticsearch_bm25", "milvus_vector"),
                List.of(new RagItemSupportVO(
                        "B001",
                        List.of(new RagSupportSnippetVO(
                                "description",
                                "Lightweight waterproof backpack for daily commute.",
                                "small2big parent profile compressed"
                        ))
                )),
                List.of("B001 is stronger for commute, B002 is stronger for capacity."),
                new RagAgentContextVO(
                        "Evidence supports price, commute, and lightweight explanations.",
                        false
                ),
                new RagGovernanceVO(false, false, false, false)
        );
        when(agentRagService.support(argThat(request ->
                "agent_req_001".equals(request.requestId())
                        && "sess_001".equals(request.sessionId())
                        && "想要便宜一点的通勤背包".equals(request.userQuery())
                        && request.candidateItemIds().equals(List.of("B001", "B002"))
                        && request.providers().equals(List.of("elasticsearch_bm25", "milvus_vector"))
                        && request.rerankTopK() == 8
                        && request.small2big()
                        && request.maxSupportPerItem() == 3
                        && request.maxTextChars() == 220
        ))).thenReturn(response);

        mockMvc.perform(post("/agent/rag/support")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "request_id": "agent_req_001",
                                  "session_id": "sess_001",
                                  "user_query": "想要便宜一点的通勤背包",
                                  "candidate_item_ids": ["B001", "B002"],
                                  "rerank_top_k": 8
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.query_rewrite").value("affordable commuter backpack"))
                .andExpect(jsonPath("$.candidate_scoped").value(true))
                .andExpect(jsonPath("$.providers[0]").value("elasticsearch_bm25"))
                .andExpect(jsonPath("$.providers[1]").value("milvus_vector"))
                .andExpect(jsonPath("$.item_support[0].item_id").value("B001"))
                .andExpect(jsonPath("$.item_support[0].support[0].field").value("description"))
                .andExpect(jsonPath("$.agent_context.summary").value("Evidence supports price, commute, and lightweight explanations."))
                .andExpect(jsonPath("$.governance.candidate_generation_allowed").value(false))
                .andExpect(jsonPath("$.governance.ranking_input_replacement_allowed").value(false));

        verify(agentRagService).support(argThat(request ->
                request.providers().equals(List.of("elasticsearch_bm25", "milvus_vector"))
                        && request.small2big()
        ));
    }
}
