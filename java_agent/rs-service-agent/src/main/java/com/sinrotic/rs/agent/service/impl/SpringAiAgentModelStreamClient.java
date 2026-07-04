package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.tool.ToolCallback;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;

public class SpringAiAgentModelStreamClient implements AgentModelStreamClient {

    private final ChatClient chatClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private final SpringAiAgentToolCallbackFactory toolCallbackFactory;

    public SpringAiAgentModelStreamClient(ChatClient.Builder chatClientBuilder) {
        this(chatClientBuilder.build(), null);
    }

    public SpringAiAgentModelStreamClient(ChatClient.Builder chatClientBuilder, AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(chatClientBuilder.build(), runtimeConfigurationService);
    }

    public SpringAiAgentModelStreamClient(ChatModel chatModel) {
        this(ChatClient.builder(chatModel).build(), null);
    }

    public SpringAiAgentModelStreamClient(ChatModel chatModel, AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(ChatClient.builder(chatModel).build(), runtimeConfigurationService);
    }

    public SpringAiAgentModelStreamClient(ChatClient chatClient) {
        this(chatClient, null);
    }

    public SpringAiAgentModelStreamClient(ChatClient chatClient, AgentRuntimeConfigurationService runtimeConfigurationService) {
        this.chatClient = chatClient;
        this.toolCallbackFactory = new SpringAiAgentToolCallbackFactory(runtimeConfigurationService);
    }

    @Override
    public void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer
    ) {
        var promptSpec = chatClient.prompt()
                .system(systemPrompt(request))
                .user(userPrompt(request));
        List<ToolCallback> toolCallbacks = toolCallbackFactory.createToolCallbacks();
        if (!toolCallbacks.isEmpty()) {
            promptSpec = promptSpec.toolCallbacks(toolCallbacks);
        }
        promptSpec
                .stream()
                .chatResponse()
                .toStream()
                .flatMap(response -> SpringAiChatResponseMapper.toEvents(response).stream())
                .filter(event -> !event.isToken() || !event.delta().isBlank())
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
            prompt.append("""
                    你是一个中文购物推荐智能体。
                    除非用户明确要求其他语言，所有面向用户的回答、追问、总结和推荐理由都必须使用中文。
                    如果用户需求已经明确，直接基于候选商品和证据给出推荐，不要重复追问品类。
                    """);
        }
        appendContext(prompt, "available_skills", context.remove("available_skills"));
        appendContext(prompt, "available_tools", context.remove("available_tools"));
        appendContext(prompt, "tool_results", context.remove("tool_results"));
        if (!context.isEmpty()) {
            appendContext(prompt, "request_context", context);
        }
        prompt.append("""

                Spring AI 通道输出规则：
                - 当前模型通道已经绑定可用工具 schema；需要工具时发起真实 tool call，不要在文本里模拟工具调用。
                - load_skill 用于加载匹配当前会话状态的 skill；call_agent 用于委派子 agent；emit_final_answer 用于输出最终用户可见答案。
                - 如果已有 tool_results/request_context，就基于它们回答；如果没有足够商品证据，可以先调用合适工具，或只问一个中文澄清问题。
                - 不要向用户暴露内部工具名、tool call JSON、编排计划或系统实现细节。
                """);
        return prompt.toString();
    }

    private String userPrompt(AgentChatRequestDTO request) {
        return """
                用户原始问题：
                %s

                请严格遵守：
                - 只输出面向用户的中文回答。
                - 不要输出英文内部思考、工具调用计划、tool call JSON、无法调用工具的说明。
                - 如果已有推荐候选或检索结果，请直接用中文给出建议；如果证据不足，只问一个中文澄清问题。
                """.formatted(request.userMessage() == null ? "" : request.userMessage());
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
