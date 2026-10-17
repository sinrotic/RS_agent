package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.metadata.EmptyUsage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;

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
        if (usage != null && !(usage instanceof EmptyUsage) && hasUsage(usage)) {
            Map<String, Object> measured = new LinkedHashMap<>();
            putKnown(measured, "prompt_tokens", usage.getPromptTokens());
            putKnown(measured, "completion_tokens", usage.getCompletionTokens());
            // Usage 的默认 total 会将缺失项当作 0 相加；不将该推导当作完整总量。
            if (usage.getPromptTokens() != null && usage.getCompletionTokens() != null) {
                putKnown(measured, "total_tokens", usage.getTotalTokens());
            }
            putKnown(measured, "cache_read_input_tokens", usage.getCacheReadInputTokens());
            putKnown(measured, "cache_write_input_tokens", usage.getCacheWriteInputTokens());
            if (usage.getNativeUsage() != null) measured.put("native_usage", usage.getNativeUsage());
            events.add(AgentModelStreamEvent.usage(measured));
        }
        return events;
    }

    private static boolean hasUsage(Usage usage) {
        // DefaultUsage 会把空的普通计数归一为 0；全 0 且无缓存明细不足以证明上游报过 usage。
        return positive(usage.getPromptTokens())
                || positive(usage.getCompletionTokens())
                || positive(usage.getTotalTokens())
                || usage.getCacheReadInputTokens() != null
                || usage.getCacheWriteInputTokens() != null;
    }

    private static boolean positive(Number value) {
        return value != null && value.longValue() > 0;
    }

    private static void putKnown(Map<String, Object> measured, String key, Number value) {
        if (value != null && value.longValue() >= 0) measured.put(key, value);
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
