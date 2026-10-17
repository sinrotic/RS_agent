package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.SpringAiChatResponseMapper;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SpringAiChatResponseMapperTest {

    @Test
    void missingCacheUsageStaysMissingInsteadOfClaimingZeroCacheHits() {
        var response = new ChatResponse(List.of(), ChatResponseMetadata.builder()
                .usage(new DefaultUsage(100, 20, 120)).build());
        var usage = SpringAiChatResponseMapper.toEvents(response).getFirst().arguments();
        assertThat(usage).containsEntry("total_tokens", 120)
                .doesNotContainKeys("cache_read_input_tokens", "cache_write_input_tokens");
    }

    @Test
    void explicitlyReportedZeroUsageIsRetained() {
        var response = new ChatResponse(List.of(), ChatResponseMetadata.builder()
                .usage(new DefaultUsage(0, 0, 0, null, 0L, null)).build());
        var events = SpringAiChatResponseMapper.toEvents(response);
        assertThat(events).hasSize(1);
        assertThat(events.getFirst().arguments()).containsEntry("total_tokens", 0)
                .containsEntry("cache_read_input_tokens", 0L).doesNotContainKey("cache_write_input_tokens");
    }

    @Test
    void partialUsageDoesNotFillUnknownFields() {
        var partial = mock(org.springframework.ai.chat.metadata.Usage.class);
        when(partial.getPromptTokens()).thenReturn(null);
        when(partial.getCompletionTokens()).thenReturn(20);
        when(partial.getTotalTokens()).thenReturn(null);
        when(partial.getCacheReadInputTokens()).thenReturn(null);
        when(partial.getCacheWriteInputTokens()).thenReturn(null);
        var response = new ChatResponse(List.of(), ChatResponseMetadata.builder().usage(partial).build());
        assertThat(SpringAiChatResponseMapper.toEvents(response).getFirst().arguments())
                .containsEntry("completion_tokens", 20)
                .doesNotContainKeys("prompt_tokens", "total_tokens", "cache_read_input_tokens", "cache_write_input_tokens");
    }

    @Test
    void defaultInterfaceTotalFromPartialUsageIsNotACompleteMeasurement() {
        var partial = new org.springframework.ai.chat.metadata.Usage() {
            public Integer getPromptTokens() { return null; }
            public Integer getCompletionTokens() { return 20; }
            public Object getNativeUsage() { return null; }
        };
        assertThat(partial.getTotalTokens()).isEqualTo(20);
        var response = new ChatResponse(List.of(), ChatResponseMetadata.builder().usage(partial).build());
        assertThat(SpringAiChatResponseMapper.toEvents(response).getFirst().arguments())
                .containsEntry("completion_tokens", 20).doesNotContainKeys("prompt_tokens", "total_tokens");
    }

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

    @Test
    void mapsSpringAiUsageMetadataToUsageEvent() {
        ChatResponse response = new ChatResponse(
                List.of(new Generation(new AssistantMessage("hello"))),
                ChatResponseMetadata.builder()
                        .model("gpt-test")
                        .usage(new DefaultUsage(123, 45, 168, null, 11L, 22L))
                        .build()
        );

        List<AgentModelStreamEvent> events = SpringAiChatResponseMapper.toEvents(response);

        assertThat(events).extracting(AgentModelStreamEvent::type)
                .containsExactly("token", "usage");
        assertThat(events.get(1).arguments())
                .containsEntry("prompt_tokens", 123)
                .containsEntry("completion_tokens", 45)
                .containsEntry("total_tokens", 168)
                .containsEntry("cache_read_input_tokens", 11L)
                .containsEntry("cache_write_input_tokens", 22L);
    }
}
