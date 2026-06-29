package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;

public class SpringAiAgentModelStreamClient implements AgentModelStreamClient {

    private final ChatClient chatClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    public SpringAiAgentModelStreamClient(ChatClient.Builder chatClientBuilder) {
        this(chatClientBuilder.build());
    }

    public SpringAiAgentModelStreamClient(ChatModel chatModel) {
        this(ChatClient.builder(chatModel).build());
    }

    public SpringAiAgentModelStreamClient(ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    @Override
    public void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer
    ) {
        chatClient.prompt()
                .system(systemPrompt(request))
                .user(request.userMessage())
                .stream()
                .content()
                .toStream()
                .filter(token -> token != null && !token.isBlank())
                .map(AgentModelStreamEvent::token)
                .forEach(consumer);
        consumer.accept(AgentModelStreamEvent.done());
    }

    private String systemPrompt(AgentChatRequestDTO request) {
        Map<String, Object> context = new LinkedHashMap<>(request.resolvedContext());
        Object configuredPrompt = context.remove("system_prompt");
        StringBuilder prompt = new StringBuilder();
        if (configuredPrompt != null && !String.valueOf(configuredPrompt).isBlank()) {
            prompt.append(configuredPrompt);
        } else {
            prompt.append("You are a recommendation agent.");
        }
        appendContext(prompt, "available_skills", context.remove("available_skills"));
        appendContext(prompt, "available_tools", context.remove("available_tools"));
        appendContext(prompt, "tool_results", context.remove("tool_results"));
        if (!context.isEmpty()) {
            appendContext(prompt, "request_context", context);
        }
        return prompt.toString();
    }

    private void appendContext(StringBuilder prompt, String name, Object value) {
        if (value == null) {
            return;
        }
        prompt.append("\n\n")
                .append(name)
                .append(":\n")
                .append(writeJson(value));
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to serialize spring ai context", ex);
        }
    }
}
