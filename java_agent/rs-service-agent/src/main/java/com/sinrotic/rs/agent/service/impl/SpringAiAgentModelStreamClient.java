package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolResultStore;
import org.springframework.ai.chat.client.AdvisorParams;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.openai.OpenAiChatOptions;
import com.openai.models.chat.completions.ChatCompletionNamedToolChoice;
import com.openai.models.chat.completions.ChatCompletionToolChoiceOption;
import reactor.core.publisher.Sinks;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.CancellationException;

public class SpringAiAgentModelStreamClient implements AgentModelStreamClient {

    private final ChatClient chatClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private final SpringAiAgentToolCallbackFactory toolCallbackFactory;

    private final AgentToolResultExternalizer toolResultExternalizer;

    private final boolean constrainedDecodingEnabled;

    private OpenAiModelStreamResources streamResources;

    private Map<String, String> defaultCustomHeaders = Map.of();

    private int finalAnswerMaxTokens;

    private int defaultMaxTokens;

    private boolean compactToolSchemasEnabled;
    private String declaredModel = "";
    private Map<String, Object> declaredModelOptions = Map.of("status", "unknown");

    public SpringAiAgentModelStreamClient(ChatClient.Builder chatClientBuilder) {
        this(chatClientBuilder.build(), null);
    }

    public SpringAiAgentModelStreamClient(ChatClient.Builder chatClientBuilder, AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(chatClientBuilder.build(), runtimeConfigurationService);
    }

    public SpringAiAgentModelStreamClient(ChatModel chatModel) {
        this(chatModel, null);
    }

    public SpringAiAgentModelStreamClient(ChatModel chatModel, AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(chatModel, runtimeConfigurationService, null);
    }

    public SpringAiAgentModelStreamClient(
            ChatModel chatModel,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore
    ) {
        this(chatModel, runtimeConfigurationService, toolResultStore, false);
    }

    public SpringAiAgentModelStreamClient(
            ChatModel chatModel,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore,
            boolean constrainedDecodingEnabled
    ) {
        this(ChatClient.builder(chatModel).build(), runtimeConfigurationService, toolResultStore, constrainedDecodingEnabled);
        var defaults = chatModel.getDefaultOptions();
        if (defaults != null) {
            declaredModel = defaults.getModel();
            var selected = new LinkedHashMap<String, Object>();
            selected.put("model", defaults.getModel()); selected.put("temperature", defaults.getTemperature());
            selected.put("max_tokens", defaults.getMaxTokens()); selected.put("top_p", defaults.getTopP());
            selected.put("stop", defaults.getStopSequences());
            selected.put("top_k", defaults.getTopK());
            if (defaults instanceof OpenAiChatOptions openAi) {
                selected.put("max_completion_tokens", openAi.getMaxCompletionTokens()); selected.put("seed", openAi.getSeed());
                selected.put("frequency_penalty", openAi.getFrequencyPenalty()); selected.put("presence_penalty", openAi.getPresencePenalty());
                selected.put("reasoning_effort", openAi.getReasoningEffort()); selected.put("verbosity", openAi.getVerbosity());
                selected.put("response_format", openAi.getResponseFormat()); selected.put("logit_bias", openAi.getLogitBias());
                selected.put("n", openAi.getN());
            }
            declaredModelOptions = java.util.Collections.unmodifiableMap(selected);
        }
    }

    public SpringAiAgentModelStreamClient(ChatClient chatClient) {
        this(chatClient, null);
    }

    public SpringAiAgentModelStreamClient(
            ChatModel chatModel,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore,
            boolean constrainedDecodingEnabled,
            OpenAiModelStreamResources streamResources
    ) {
        this(chatModel, runtimeConfigurationService, toolResultStore, constrainedDecodingEnabled, streamResources, 0);
    }

    public SpringAiAgentModelStreamClient(
            ChatModel chatModel,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore,
            boolean constrainedDecodingEnabled,
            OpenAiModelStreamResources streamResources,
            int finalAnswerMaxTokens
    ) {
        this(chatModel, runtimeConfigurationService, toolResultStore, constrainedDecodingEnabled,
                streamResources, finalAnswerMaxTokens, false);
    }

    public SpringAiAgentModelStreamClient(
            ChatModel chatModel,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore,
            boolean constrainedDecodingEnabled,
            OpenAiModelStreamResources streamResources,
            int finalAnswerMaxTokens,
            boolean compactToolSchemasEnabled
    ) {
        this(chatModel, runtimeConfigurationService, toolResultStore, constrainedDecodingEnabled);
        if (finalAnswerMaxTokens < 0) throw new IllegalArgumentException("finalAnswerMaxTokens must not be negative");
        this.finalAnswerMaxTokens = finalAnswerMaxTokens;
        this.compactToolSchemasEnabled = compactToolSchemasEnabled;
        this.streamResources = streamResources;
        if (chatModel.getDefaultOptions() instanceof OpenAiChatOptions options) {
            if (options.getCustomHeaders() != null) this.defaultCustomHeaders = Map.copyOf(options.getCustomHeaders());
            this.defaultMaxTokens = options.getMaxTokens() == null ? 0 : options.getMaxTokens();
        }
    }

    public SpringAiAgentModelStreamClient(ChatClient chatClient, AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(chatClient, runtimeConfigurationService, null);
    }

    public SpringAiAgentModelStreamClient(
            ChatClient chatClient,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore
    ) {
        this(chatClient, runtimeConfigurationService, toolResultStore, false);
    }

    private SpringAiAgentModelStreamClient(
            ChatClient chatClient,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolResultStore toolResultStore,
            boolean constrainedDecodingEnabled
    ) {
        this.chatClient = chatClient;
        this.toolCallbackFactory = new SpringAiAgentToolCallbackFactory(runtimeConfigurationService);
        this.toolResultExternalizer = new AgentToolResultExternalizer(toolResultStore);
        this.constrainedDecodingEnabled = constrainedDecodingEnabled;
    }

    @Override
    public void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer
    ) {
        streamAssistantEvents(requestId, request, consumer, null);
    }

    @Override
    public void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer,
            AgentInterruptContext interruptContext
    ) {
        streamAssistantEvents(requestId, request, consumer, interruptContext, ignored -> { });
    }

    @Override
    public void streamAssistantEvents(String requestId, AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer, AgentInterruptContext interruptContext,
            Consumer<Map<String, Object>> requestObservation) {
        if (streamResources == null) {
            streamAssistantEventsWithHeaders(request, consumer, null, interruptContext, requestObservation);
            return;
        }
        try (var scope = streamResources.open()) {
            if (interruptContext != null) {
                interruptContext.onInterrupt(scope::close);
            }
            var headers = new LinkedHashMap<>(defaultCustomHeaders);
            headers.putAll(scope.headers());
            streamAssistantEventsWithHeaders(request, consumer, headers, interruptContext, requestObservation);
        }
    }

    private void streamAssistantEventsWithHeaders(
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer,
            Map<String, String> headers,
            AgentInterruptContext interruptContext,
            Consumer<Map<String, Object>> requestObservation
    ) {
        String system = systemPrompt(request), user = userPrompt(request);
        var promptSpec = chatClient.prompt()
                .advisors(AdvisorParams.toolCallingAdvisorAutoRegister(false))
                .system(system)
                .user(user);
        Object completed = request.resolvedContext().get("tool_results");
        List<?> reusableSkills = constrainedDecodingEnabled && compactToolSchemasEnabled
                && Boolean.TRUE.equals(request.resolvedContext().get(AgentLoop.INTERNAL_SKILL_REUSE_CONTEXT_KEY))
                && completed instanceof List<?> results ? results : List.of();
        List<ToolCallback> toolCallbacks = toolCallbackFactory.createToolCallbacks(
                Boolean.TRUE.equals(request.resolvedContext().get("final_answer_only")), reusableSkills);
        boolean structuredToolMode = !toolCallbacks.isEmpty();
        OpenAiChatOptions.Builder options = null;
        List<Map<String, Object>> strictTools = List.of();
        if (!toolCallbacks.isEmpty()) {
            if (constrainedDecodingEnabled) {
                // Send the definitions once through the wire adapter. Registering callbacks too
                // would serialize duplicate tools fields through OpenAI additionalBodyProperties.
                strictTools = toolCallbackFactory.strictToolDefinitions(toolCallbacks, compactToolSchemasEnabled);
                options = strictToolOptions(strictTools,
                        Boolean.TRUE.equals(request.resolvedContext().get("final_answer_only")));
            } else {
                promptSpec = promptSpec.toolCallbacks(toolCallbacks);
            }
        }
        if (headers != null) {
            options = options == null ? OpenAiChatOptions.builder() : options;
            options.customHeaders(headers);
        }
        if (options != null) {
            promptSpec = promptSpec.options(options);
        }
        var finalStrictTools = strictTools;
        AgentModelRequestFingerprint.publish(requestObservation, () -> {
            Object tools = constrainedDecodingEnabled ? finalStrictTools : toolCallbacks.stream().map(callback -> {
                var definition = callback.getToolDefinition();
                return Map.of("name", definition.name(), "description", definition.description(),
                        "input_schema", definition.inputSchema());
            }).toList();
            var flags = Map.of("declared_defaults", declaredModelOptions, "constrained_decoding", constrainedDecodingEnabled,
                    "compact_tool_schemas", compactToolSchemasEnabled,
                    "final_answer_only", Boolean.TRUE.equals(request.resolvedContext().get("final_answer_only")),
                    "synthesis_only", Boolean.TRUE.equals(request.resolvedContext().get("recommendation_synthesis_only")),
                    "final_answer_max_tokens", finalAnswerMaxTokens, "default_max_tokens", defaultMaxTokens);
            return AgentModelRequestFingerprint.capture("spring_ai_prepared_request", SpringAiAgentModelStreamClient.class,
                    request, configuredSystemPrompt(request), tools, Map.of("system", system, "user", user, "tools", tools, "options", flags),
                    flags, declaredModel);
        });
        AtomicBoolean toolCallSeen = new AtomicBoolean(false);
        var responseFlux = promptSpec.stream().chatResponse();
        if (interruptContext != null) {
            Sinks.Empty<Void> interrupted = Sinks.empty();
            interruptContext.onInterrupt(() -> interrupted.tryEmitEmpty());
            // 以完成信号唤醒阻塞读取；仅关闭 Java Stream 不会结束 hasNext 的等待。
            responseFlux = responseFlux.takeUntilOther(interrupted.asMono());
        }
        // AgentLoop 可在最终回答或中断时提前退出；关闭流才能取消上游请求。
        try (var responses = responseFlux.toStream()) {
            responses
                    .flatMap(response -> SpringAiChatResponseMapper.toEvents(response).stream())
                    .filter(event -> !event.isToken() || !event.delta().isBlank())
                    .forEach(event -> {
                        if (event.isToolUse()) {
                            toolCallSeen.set(true);
                        }
                        if (!structuredToolMode || !event.isToken()) {
                            consumer.accept(event);
                        }
                    });
        }
        if (interruptContext != null && interruptContext.interrupted()) {
            throw new CancellationException("agent model stream interrupted");
        }
        if (structuredToolMode && !toolCallSeen.get()) {
            throw new IllegalStateException("model did not return a required structured tool call");
        }
        consumer.accept(AgentModelStreamEvent.done());
    }

    private OpenAiChatOptions.Builder strictToolOptions(List<Map<String, Object>> tools, boolean finalAnswerOnly) {
        Object toolChoice = finalAnswerOnly
                ? ChatCompletionToolChoiceOption.ofNamedToolChoice(ChatCompletionNamedToolChoice.builder()
                        .function(ChatCompletionNamedToolChoice.Function.builder().name("emit_final_answer").build())
                        .build())
                : "required";
        OpenAiChatOptions.Builder options = OpenAiChatOptions.builder();
        // 仅扩展最终回答。普通工具继续使用原预算，避免无效生成占满 4096 tokens。
        if (finalAnswerOnly && finalAnswerMaxTokens > 0) {
            options.maxTokens(Math.max(defaultMaxTokens, finalAnswerMaxTokens));
        }
        options.toolChoice(toolChoice);
        options.parallelToolCalls(false);
        options.extraBody(Map.of("tools", tools, "chat_template_kwargs", Map.of("enable_thinking", false)));
        return options;
    }

    private String systemPrompt(AgentChatRequestDTO request) {
        Map<String, Object> context = new LinkedHashMap<>(request.resolvedContext());
        context.remove(AgentLoop.INTERNAL_SKILL_REUSE_CONTEXT_KEY);
        context.remove("system_prompt");
        StringBuilder prompt = new StringBuilder(configuredSystemPrompt(request));
        // 固定规则和运行配置放在动态商品、Session 与工具证据之前，增加真实 KV 前缀复用。
        if (compactToolSchemasEnabled) appendOutputRules(prompt);
        appendContext(prompt, "available_skills", context.remove("available_skills"));
        if (compactToolSchemasEnabled) {
            var runtimeContext = new LinkedHashMap<String, Object>();
            for (String key : List.of("agent_name", "agent_description", "runtime_context_messages", "agent_profile_id",
                    "agent_model_ref", "agent_system_prompt_ref", "agent_allowed_capabilities",
                    "agent_allowed_output_blocks", "agent_max_loops", "server_loaded_skills")) {
                if (context.containsKey(key)) runtimeContext.put(key, context.remove(key));
            }
            if (!runtimeContext.isEmpty()) appendContext(prompt, "runtime_context", runtimeContext);
        }
        if (Boolean.TRUE.equals(context.remove("final_answer_only"))) {
            if (Boolean.TRUE.equals(context.get("recommendation_synthesis_only"))) {
                prompt.append("\n服务已按 server_loaded_skills 中的技能规则完成本次需求的候选召回、排序和商品品类、预算校验。你负责理解用户原始问题，并依据已有商品事实生成最终中文回答。只调用 emit_final_answer，不重复已经完成的检索步骤；理由仅限已有证据支持的属性，不推测商品能力。商品名称与详情由商品卡片完整展示，正文简要说明推荐结论和已有事实，避免重复整段商品标题。本轮商品已绑定同一卡片集，product_cards 用已有 card_set_id 引用全部商品，省略重复的 item_ids 和默认布局。\n");
            } else {
                prompt.append("\n本轮检索工具预算已用完。现在只允许调用 emit_final_answer，依据已有商品与工具证据给出最终中文回答。证据不满足需求时如实说明，不猜测商品能力，不重复加载技能或检索。\n");
            }
        }
        context.remove("available_tools");
        appendContext(prompt, "tool_results", toolResultExternalizer.externalizeAggregateToolResults(context.remove("tool_results")));
        if (!context.isEmpty()) {
            appendContext(prompt, "request_context", context);
        }
        if (!compactToolSchemasEnabled) appendOutputRules(prompt);
        return prompt.toString();
    }

    private String configuredSystemPrompt(AgentChatRequestDTO request) {
        Object configuredPrompt = request.resolvedContext().get("system_prompt");
        if (configuredPrompt != null && !String.valueOf(configuredPrompt).isBlank()) {
            return String.valueOf(configuredPrompt);
        } else {
            return """
                    你是一个中文购物推荐智能体。
                    除非用户明确要求其他语言，所有面向用户的回答、追问、总结和推荐理由都必须使用中文。
                    如果用户需求已经明确，直接基于候选商品和证据给出推荐，不要重复追问品类。
                    """;
        }
    }

    private void appendOutputRules(StringBuilder prompt) {
        prompt.append("""

                Spring AI 通道输出规则：
                - 当前模型通道已经绑定可用工具 schema；需要工具时发起真实 tool call，不要在文本里模拟工具调用。
                - load_skill 用于加载匹配当前会话状态的 skill；call_agent 用于委派子 agent；emit_final_answer 用于输出最终用户可见答案。
                - 如果已有 tool_results/request_context，就基于它们回答；如果没有足够商品证据，可以先调用合适工具，或只问一个中文澄清问题。
                - tool_results 是本轮已经执行的真实结果。不要再次加载已成功加载的技能，也不要重复获取已有证据。
                - 大结果包含 result_ref 时，使用 read_tool_result_lines 读取所需部分，不要为了读取结果重新执行检索。
                - 已有 recommendation_items 时可以据此推荐；若候选不满足用户要求，明确说明不足并结束本轮，不要无限检索。
                - 不要向用户暴露内部工具名、tool call JSON、编排计划或系统实现细节。
                """);
    }

    private String userPrompt(AgentChatRequestDTO request) {
        return """
                用户原始问题：
                %s

                请严格遵守：
                - 只输出面向用户的中文回答。
                - 不要输出英文内部思考、工具调用计划、tool call JSON、无法调用工具的说明。
                - 如果已有推荐候选或检索结果，请直接用中文给出建议；如果证据不足，只问一个中文澄清问题。
                - recommendation_items 是服务已经完成召回、排序并从目录取回的本轮真实商品。额外工具失败不会撤销这些商品；有这些商品时不要声称无法获取商品数据。额外属性缺少证据时明确说明该属性不能确认。
                - 商品推荐理由写在 text.content 中；商品卡片只填写 card_set_id、item_ids 和布局，不能代替正文理由。用户要求说明理由或比较差异时，在 text.content 或 comparison_table.content 中回答，不只输出介绍句。
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
