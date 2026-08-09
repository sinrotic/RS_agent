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
    void streamChatExposesOnlyPublicTokenAndDoneEvents() throws Exception {
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
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("recommend_candidates"))))
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
    void chatReturnsAssistantMessageRecommendationsAndToolTrace() throws Exception {
        AgentChatVO response = new AgentChatVO(
                "agent_req_001",
                "sess_001",
                "A1XYZ",
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
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "profile_user_id", "A1XYZ",
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
                .andExpect(jsonPath("$.tool_calls[0].tool_name").value("recommend_candidates"))
                .andExpect(jsonPath("$.tool_calls[0].status").value("SUCCESS"));

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
        when(traceService.sessionTurns("sess_001")).thenReturn(response);

        mockMvc.perform(get("/api/agent/sessions/sess_001/turns"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.turns[0].request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.turns[0].user_message").value("想要一个通勤背包"))
                .andExpect(jsonPath("$.turns[0].tool_calls[0].tool_name").value("rag_support"))
                .andExpect(jsonPath("$.turns[0].recommended_item_ids[0]").value("B001"));

        verify(traceService).sessionTurns("sess_001");
    }

    @Test
    void interruptRequestReturnsInterruptedState() throws Exception {
        when(interrupter.interrupt("agent_req_001", "user_stop")).thenReturn(true);

        mockMvc.perform(post("/api/agent/requests/agent_req_001/interrupt")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "reason", "user_stop"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.interrupted").value(true))
                .andExpect(jsonPath("$.reason").value("user_stop"));

        verify(interrupter).interrupt("agent_req_001", "user_stop");
    }
}
