package com.sinrotic.rs.agent.controller.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import com.sinrotic.rs.agent.service.AgentChatService;
import com.sinrotic.rs.agent.service.AgentChatStreamService;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentTraceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AgentChatControllerTest {

    @Test
    void publicHistoryRejectsAnotherAccountEvenWhenProfileMatches() throws Exception {
        var agent = new com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.toolUse(
                        "emit_final_answer", Map.of("blocks", List.of(Map.of("type", "text", "content", "仅归属账号可读取"))))),
                new com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor());
        agent.chat(new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO("owned", "profile", "需求", 1, Map.of("authenticated_account_id", "owner-account")));
        var realMvc = MockMvcBuilders.standaloneSetup(new AgentChatController(agent, agent, agent, interrupter)).build();
        realMvc.perform(get("/api/agent/sessions/owned/history").header("X-Account-Id", "owner-account")
                .header("X-Profile-User-Id", "profile")).andExpect(status().isOk());
        realMvc.perform(get("/api/agent/sessions/owned/history").header("X-Account-Id", "other-account")
                .header("X-Profile-User-Id", "profile")).andExpect(status().isNotFound());
    }

    @Test
    void streamOwnershipFailureKeepsNotFoundStatus() throws Exception {
        org.mockito.Mockito.doThrow(new com.sinrotic.rs.agent.service.AgentSessionNotFoundException())
                .when(streamService).streamChat(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        var result = mockMvc.perform(post("/api/agent/chat/stream").header("X-Account-Id", "account")
                .header("X-Profile-User-Id", "profile").contentType(MediaType.APPLICATION_JSON)
                .content("{\"session_id\":\"session\",\"user_message\":\"建议\"}"))
                .andExpect(request().asyncStarted()).andReturn();
        mockMvc.perform(asyncDispatch(result)).andExpect(content().string(org.hamcrest.Matchers.containsString("\"status\":404")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("SESSION_NOT_FOUND")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"retryable\":false")));
    }

    @Test
    void streamConflictKeepsItsStatusAndDisablesBlindRetry() throws Exception {
        org.mockito.Mockito.doThrow(new org.springframework.web.server.ResponseStatusException(HttpStatus.CONFLICT, "private conflict"))
                .when(streamService).streamChat(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        var result = mockMvc.perform(post("/api/agent/chat/stream").header("X-Account-Id", "account")
                .header("X-Profile-User-Id", "profile").contentType(MediaType.APPLICATION_JSON)
                .content("{\"session_id\":\"session\",\"user_message\":\"建议\"}"))
                .andExpect(request().asyncStarted()).andReturn();
        mockMvc.perform(asyncDispatch(result)).andExpect(content().string(org.hamcrest.Matchers.containsString("\"status\":409")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("TURN_CONFLICT")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"retryable\":false")))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("private conflict"))));
    }

    @Test
    void publicHistoryDoesNotExposeToolRecordsOrRuntimeMetadata() throws Exception {
        when(traceService.sessionTurns("sess_001", "profile", "account"))
                .thenReturn(new AgentSessionTraceVO("sess_001", List.of(new AgentTurnVO("req", "问题", "回答",
                        List.of(new AgentToolCallVO("rag", "internal", "SUCCESS", Map.of("trace_ref", "private"))),
                        List.of("item"), List.of(Map.of("type", "text", "content", "回答", "trace_ref", "private")),
                        "FINAL_ANSWER", "delivery"))));
        mockMvc.perform(get("/api/agent/sessions/sess_001/history").header("X-Account-Id", "account").header("X-Profile-User-Id", "profile"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.turns[0].assistant_message").value("回答"))
                .andExpect(jsonPath("$.turns[0].answer_blocks[0].content").value("回答"))
                .andExpect(jsonPath("$.turns[0].tool_calls").doesNotExist())
                .andExpect(jsonPath("$.turns[0].answer_blocks[0].trace_ref").doesNotExist());
    }

    private final ObjectMapper objectMapper = new ObjectMapper();

    private MockMvc mockMvc;

    private AgentChatService chatService;

    private AgentChatStreamService streamService;

    private AgentTraceService traceService;

    private AgentInterrupter interrupter;

    @BeforeEach
    void setUp() {
        chatService = mock(AgentChatService.class);
        streamService = mock(AgentChatStreamService.class);
        traceService = mock(AgentTraceService.class);
        interrupter = mock(AgentInterrupter.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new AgentChatController(chatService, streamService, traceService, interrupter))
                .build();
    }

    @Test
    void streamChatReturnsTraceTokenAndDoneEvents() throws Exception {
        doAnswer(invocation -> {
            java.util.function.Consumer<AgentStreamEventVO> consumer = invocation.getArgument(1);
            consumer.accept(new AgentStreamEventVO("trace", "agent_req_001", Map.of(
                    "tool_name", "recommend_candidates",
                    "status", "SUCCESS"
            )));
            consumer.accept(new AgentStreamEventVO("token", "agent_req_001", Map.of(
                    "delta", "I "
            )));
            consumer.accept(new AgentStreamEventVO("token", "agent_req_001", Map.of(
                    "delta", "will help."
            )));
            consumer.accept(new AgentStreamEventVO("done", "agent_req_001", Map.of(
                    "done", true
            )));
            return null;
        }).when(streamService).streamChat(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "A1XYZ".equals(request.profileUserId())
                        && request.limit() == 5
        ), any());

        var result = mockMvc.perform(post("/api/agent/chat/stream")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "A1XYZ")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "profile_user_id", "A1XYZ",
                                "user_message", "Find a commuter backpack",
                                "limit", 5,
                                "context", Map.of("scene", "chat")
                        ))))
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(result))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("event: trace"))))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event: token")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"delta\":\"I \"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event: done")));

        verify(streamService).streamChat(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "A1XYZ".equals(request.profileUserId())
        ), any());
    }

    @Test
    void streamChatReturnsErrorAndDoneWhenStreamServiceFailsAfterCommit() throws Exception {
        doAnswer(invocation -> {
            java.util.function.Consumer<AgentStreamEventVO> consumer = invocation.getArgument(1);
            consumer.accept(new AgentStreamEventVO("trace", "agent_req_401", Map.of(
                    "tool_name", "model_chat",
                    "status", "STARTED"
            )));
            throw new IllegalStateException("Missing API key");
        }).when(streamService).streamChat(any(), any());

        var result = mockMvc.perform(post("/api/agent/chat/stream")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "A1XYZ")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_401",
                                "profile_user_id", "A1XYZ",
                                "user_message", "Find bluetooth earbuds"
                        ))))
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(result))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("event: trace"))))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event: error")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"message\":\"agent stream failed\"")))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("Missing API key"))))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event: done")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"finish_reason\":\"error\"")));
    }

    @Test
    void chatReturnsPublicAnswerAndRecommendationsWithoutToolTrace() throws Exception {
        AgentChatVO response = new AgentChatVO(
                "agent_req_001",
                "sess_001",
                "A1XYZ",
                1,
                "我会优先推荐通勤背包，并补充可解释证据。",
                List.of(new AgentRecommendedItemVO(
                        "B001",
                        "Commuter Backpack",
                        "Backpacks",
                        0.91,
                        "匹配通勤、轻量和中价位偏好"
                )),
                List.of(new AgentToolCallVO(
                        "recommend_candidates",
                        "rs-service-recommend",
                        "SUCCESS",
                        Map.of("limit", 5)
                ))
        );
        when(chatService.chat(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "A1XYZ".equals(request.profileUserId())
                        && "想要一个通勤背包".equals(request.userMessage())
                        && request.limit() == 5
                        && request.context().get("scene").equals("chat")
        ))).thenReturn(response);

        mockMvc.perform(post("/api/agent/chat")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "A1XYZ")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "profile_user_id", "spoofed-profile",
                                "user_message", "想要一个通勤背包",
                                "limit", 5,
                                "context", Map.of("scene", "chat")
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.profile_user_id").value("A1XYZ"))
                .andExpect(jsonPath("$.assistant_message").value("我会优先推荐通勤背包，并补充可解释证据。"))
                .andExpect(jsonPath("$.recommended_items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.recommended_items[0].reason").value("匹配通勤、轻量和中价位偏好"))
                .andExpect(jsonPath("$.tool_calls").doesNotExist());

        verify(chatService).chat(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && request.limit() == 5
        ));
    }

    @Test
    void sessionTurnsReturnsConversationHistoryForApp() throws Exception {
        AgentSessionTraceVO response = new AgentSessionTraceVO(
                "sess_001",
                List.of(new AgentTurnVO(
                        "agent_req_001",
                        "想要一个通勤背包",
                        "我会优先推荐通勤背包，并补充可解释证据。",
                        List.of(new AgentToolCallVO(
                                "rag_support",
                                "rs-service-recommend",
                                "SUCCESS",
                                Map.of("providers", List.of("elasticsearch_bm25", "milvus_vector"))
                        )),
                        List.of("B001")
                ))
        );
        when(traceService.sessionTurns("sess_001", "A1XYZ", "acc_001")).thenReturn(response);

        mockMvc.perform(get("/api/agent/sessions/sess_001/turns")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "A1XYZ"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.turns[0].request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.turns[0].user_message").value("想要一个通勤背包"))
                .andExpect(jsonPath("$.turns[0].tool_calls").doesNotExist())
                .andExpect(jsonPath("$.turns[0].recommended_item_ids[0]").value("B001"));

        verify(traceService).sessionTurns("sess_001", "A1XYZ", "acc_001");
    }

    @Test
    void interruptRequestReturnsInterruptedState() throws Exception {
        when(interrupter.interruptOwned("agent_req_001", "acc_001", "A1XYZ", "user_stop")).thenReturn(true);

        mockMvc.perform(post("/api/agent/requests/agent_req_001/interrupt")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "A1XYZ")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "reason", "user_stop"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.interrupted").value(true))
                .andExpect(jsonPath("$.reason").value("user_stop"));

        verify(interrupter).interruptOwned("agent_req_001", "acc_001", "A1XYZ", "user_stop");
    }

    @Test
    void chatRejectsMissingTrustedIdentityHeaders() throws Exception {
        mockMvc.perform(post("/api/agent/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "profile_user_id", "spoofed-profile",
                                "user_message", "hello"
                        ))))
                .andExpect(status().isBadRequest());
    }
}
