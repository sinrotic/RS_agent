package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.SpringAiChatResponseMapper;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SpringAiChatResponseMapperTest {

    @Test
    void mapsAssistantContentToTokenEvent() {
        ChatResponse response = new ChatResponse(List.of(new Generation(new AssistantMessage("hello"))));

        List<AgentModelStreamEvent> events = SpringAiChatResponseMapper.toEvents(response);

        assertThat(events).extracting(AgentModelStreamEvent::type).containsExactly("token");
        assertThat(events.getFirst().delta()).isEqualTo("hello");
    }

    @Test
    void mapsAssistantToolCallToToolUseEvent() {
        AssistantMessage message = AssistantMessage.builder()
                .content("")
                .toolCalls(List.of(new AssistantMessage.ToolCall(
                        "call_001",
                        "function",
                        "recommend_candidates",
                        "{\"limit\":2}"
                )))
                .build();
        ChatResponse response = new ChatResponse(List.of(new Generation(message)));

        List<AgentModelStreamEvent> events = SpringAiChatResponseMapper.toEvents(response);

        assertThat(events).extracting(AgentModelStreamEvent::type).containsExactly("tool_use");
        assertThat(events.getFirst().toolCallId()).isEqualTo("call_001");
        assertThat(events.getFirst().toolName()).isEqualTo("recommend_candidates");
        assertThat(events.getFirst().arguments()).containsEntry("limit", 2);
    }
}
