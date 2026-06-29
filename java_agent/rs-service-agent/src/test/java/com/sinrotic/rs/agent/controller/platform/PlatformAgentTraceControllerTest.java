package com.sinrotic.rs.agent.controller.platform;

import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import com.sinrotic.rs.agent.service.AgentTraceService;
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

class PlatformAgentTraceControllerTest {

    private MockMvc mockMvc;

    private AgentTraceService traceService;

    @BeforeEach
    void setUp() {
        traceService = mock(AgentTraceService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new PlatformAgentTraceController(traceService))
                .build();
    }

    @Test
    void platformSessionTurnsReturnsToolCallEvidence() throws Exception {
        AgentSessionTraceVO response = new AgentSessionTraceVO(
                "sess_001",
                List.of(new AgentTurnVO(
                        "agent_req_001",
                        "想要一个通勤背包",
                        "我会优先推荐通勤背包，并补充可解释证据。",
                        List.of(
                                new AgentToolCallVO(
                                        "recommend_candidates",
                                        "rs-service-recommend",
                                        "SUCCESS",
                                        Map.of("candidate_count", 2)
                                ),
                                new AgentToolCallVO(
                                        "model_chat",
                                        "rs-service-model",
                                        "SUCCESS",
                                        Map.of("model_key", "agent_4b")
                                )
                        ),
                        List.of("B001", "B002")
                ))
        );
        when(traceService.platformSessionTrace("sess_001")).thenReturn(response);

        mockMvc.perform(get("/api/platform/agent/sess_001/turns"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.turns[0].request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.turns[0].tool_calls[0].service").value("rs-service-recommend"))
                .andExpect(jsonPath("$.turns[0].tool_calls[0].metadata.candidate_count").value(2))
                .andExpect(jsonPath("$.turns[0].tool_calls[1].metadata.model_key").value("agent_4b"));

        verify(traceService).platformSessionTrace("sess_001");
    }
}
