package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.messages.AssistantMessage;
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
        return events;
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
