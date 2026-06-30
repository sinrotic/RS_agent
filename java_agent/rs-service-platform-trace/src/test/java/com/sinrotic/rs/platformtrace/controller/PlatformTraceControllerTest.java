package com.sinrotic.rs.platformtrace.controller;

import com.sinrotic.rs.platformtrace.controller.internal.InternalTraceController;
import com.sinrotic.rs.platformtrace.controller.platform.PlatformAgentTraceController;
import com.sinrotic.rs.platformtrace.controller.platform.PlatformRecommendTraceController;
import com.sinrotic.rs.platformtrace.controller.platform.PlatformSessionTraceController;
import com.sinrotic.rs.platformtrace.controller.platform.PlatformUserTraceController;
import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTurnVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceItemVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import com.sinrotic.rs.platformtrace.service.impl.InMemoryPlatformTraceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformTraceControllerTest {

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        PlatformTraceService traceService = new InMemoryPlatformTraceService();
        traceService.saveAccountProfile(new PlatformAccountProfileVO(
                "acc_001",
                "A1XYZ",
                "近期偏好通勤包和收纳用品",
                List.of("Backpacks", "Storage"),
                List.of("Urban Carry")
        ));
        traceService.saveRecommendTrace(new RecommendTraceVO(
                "rec_req_001",
                "sess_001",
                "A1XYZ",
                "home",
                Map.of("recall", 500, "final", 20),
                Map.of("itemcf_strong", 1),
                List.of(new RecommendTraceItemVO("B001", 1, 0.932, List.of("itemcf_strong"), "命中通勤偏好"))
        ));
        traceService.saveAgentSessionTrace(new AgentSessionTraceVO(
                "sess_001",
                List.of(new AgentTurnVO(
                        "agent_req_001",
                        "推荐一个通勤包",
                        "可以看看 B001",
                        List.of("recommend_candidates"),
                        List.of("B001")
                ))
        ));
        mockMvc = MockMvcBuilders.standaloneSetup(
                new PlatformUserTraceController(traceService),
                new PlatformRecommendTraceController(traceService),
                new PlatformAgentTraceController(traceService),
                new PlatformSessionTraceController(traceService),
                new InternalTraceController(traceService)
        ).build();
    }

    @Test
    void accountProfileEndpointReturnsPlatformProfile() throws Exception {
        mockMvc.perform(get("/api/platform/accounts/acc_001/profile"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.account_id").value("acc_001"))
                .andExpect(jsonPath("$.profile_user_id").value("A1XYZ"))
                .andExpect(jsonPath("$.top_categories[0]").value("Backpacks"));
    }

    @Test
    void recommendTraceEndpointReturnsStageCountsAndItems() throws Exception {
        mockMvc.perform(get("/api/platform/recommend/rec_req_001/trace"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_001"))
                .andExpect(jsonPath("$.stage_counts.recall").value(500))
                .andExpect(jsonPath("$.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.items[0].final_rank").value(1));
    }

    @Test
    void agentTurnsEndpointReturnsSessionTurns() throws Exception {
        mockMvc.perform(get("/api/platform/agent/sess_001/turns"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.turns[0].request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.turns[0].recommended_item_ids[0]").value("B001"));
    }

    @Test
    void agentEventEndpointStoresAndReturnsRequestEvents() throws Exception {
        String eventJson = """
                {
                  "event_id": "evt_001",
                  "session_id": "sess_001",
                  "request_id": "agent_req_001",
                  "event_type": "tool_result",
                  "tool_call_id": "call_001",
                  "tool_name": "recommend_candidates",
                  "agent_name": "rs_agent",
                  "model_provider": "spring_ai",
                  "model_name": "gpt-5.3-codex-spark",
                  "latency_ms": 42,
                  "prompt_tokens": 100,
                  "completion_tokens": 25,
                  "total_tokens": 125,
                  "cache_read_input_tokens": 11,
                  "cache_write_input_tokens": 22,
                  "data": {"status": "SUCCESS"}
                }
                """;

        mockMvc.perform(post("/internal/platform-trace/agent/events")
                        .contentType("application/json")
                        .content(eventJson))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.event_id").value("evt_001"))
                .andExpect(jsonPath("$.tool_call_id").value("call_001"));

        mockMvc.perform(get("/api/platform/agent/requests/agent_req_001/events"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.events[0].event_type").value("tool_result"))
                .andExpect(jsonPath("$.events[0].tool_call_id").value("call_001"))
                .andExpect(jsonPath("$.events[0].prompt_tokens").value(100))
                .andExpect(jsonPath("$.events[0].completion_tokens").value(25))
                .andExpect(jsonPath("$.events[0].total_tokens").value(125))
                .andExpect(jsonPath("$.events[0].data.status").value("SUCCESS"));
    }

    @Test
    void sessionOverviewEndpointReturnsJoinedTraceContext() throws Exception {
        mockMvc.perform(get("/api/platform/sessions/sess_001/overview")
                        .param("account_id", "acc_001")
                        .param("request_id", "rec_req_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.account_profile.account_id").value("acc_001"))
                .andExpect(jsonPath("$.agent_trace.turns[0].request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.recommend_traces[0].request_id").value("rec_req_001"));
    }

    @Test
    void interactionEventEndpointFeedsSessionTimeline() throws Exception {
        String eventJson = """
                {
                  "event_id": "interaction_evt_001",
                  "session_id": "sess_001",
                  "request_id": "rec_req_001",
                  "item_id": "B001",
                  "event_type": "like",
                  "event_value": 1.0,
                  "occurred_at": "2026-06-29T10:00:03Z",
                  "metadata": {"source": "mall"}
                }
                """;

        mockMvc.perform(post("/internal/platform-trace/interactions/events")
                        .contentType("application/json")
                        .content(eventJson))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.event_id").value("interaction_evt_001"))
                .andExpect(jsonPath("$.item_id").value("B001"));

        mockMvc.perform(get("/api/platform/sessions/sess_001/timeline"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].event_id").value("interaction_evt_001"))
                .andExpect(jsonPath("$[0].event_type").value("like"))
                .andExpect(jsonPath("$[0].entity_id").value("B001"));

        mockMvc.perform(get("/api/platform/sessions/sess_001/overview")
                        .param("account_id", "acc_001")
                        .param("request_id", "rec_req_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.interaction_events[0].event_id").value("interaction_evt_001"))
                .andExpect(jsonPath("$.timeline[0].event_type").value("like"));
    }
}
