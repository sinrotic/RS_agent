package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public final class SpringAiChatResponseMapper {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private SpringAiChatResponseMapper() {
    }

    public static List<AgentModelStreamEvent> toEvents(ChatResponse response) {
        if (response == null || response.getResults() == null) {
            return List.of();
        }
        List<AgentModelStreamEvent> events = new ArrayList<>();
        for (Generation generation : response.getResults()) {
            AssistantMessage message = generation.getOutput();
            if (message == null) {
                continue;
            }
            String text = message.getText();
            if (text != null && !text.isBlank()) {
                events.add(AgentModelStreamEvent.token(text));
            }
            for (AssistantMessage.ToolCall toolCall : message.getToolCalls()) {
                events.add(AgentModelStreamEvent.toolUse(
                        toolCall.id(),
                        toolCall.name(),
                        readArguments(toolCall.arguments())
                ));
            }
        }
        Usage usage = response.getMetadata() == null ? null : response.getMetadata().getUsage();
        if (usage != null && hasUsage(usage)) {
            events.add(AgentModelStreamEvent.usage(Map.of(
                    "prompt_tokens", zeroIfNull(usage.getPromptTokens()),
                    "completion_tokens", zeroIfNull(usage.getCompletionTokens()),
                    "total_tokens", zeroIfNull(usage.getTotalTokens()),
                    "cache_read_input_tokens", zeroIfNull(usage.getCacheReadInputTokens()),
                    "cache_write_input_tokens", zeroIfNull(usage.getCacheWriteInputTokens()),
                    "native_usage", usage.getNativeUsage() == null ? Map.of() : usage.getNativeUsage()
            )));
        }
        return events;
    }

    private static boolean hasUsage(Usage usage) {
        return positive(usage.getPromptTokens())
                || positive(usage.getCompletionTokens())
                || positive(usage.getTotalTokens())
                || positive(usage.getCacheReadInputTokens())
                || positive(usage.getCacheWriteInputTokens());
    }

    private static boolean positive(Number value) {
        return value != null && value.longValue() > 0;
    }

    private static Number zeroIfNull(Number value) {
        return value == null ? 0 : value;
    }

    private static Map<String, Object> readArguments(String arguments) {
        if (arguments == null || arguments.isBlank()) {
            return Map.of();
        }
        try {
            return OBJECT_MAPPER.readValue(arguments, new TypeReference<>() {
            });
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("spring ai tool call arguments are not valid JSON", ex);
        }
    }
}
