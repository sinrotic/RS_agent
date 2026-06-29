package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

public abstract class AgentLoop {

    private static final int DEFAULT_MAX_AGENT_LOOPS = 8;

    private final AgentProfile profile;

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    private final AgentToolUseExecutor toolUseExecutor;

    private final AgentModelStreamClient modelStreamClient;

    protected AgentLoop(
            AgentProfile profile,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient
    ) {
        this.profile = profile;
        this.runtimeConfigurationService = runtimeConfigurationService;
        this.toolUseExecutor = toolUseExecutor;
        this.modelStreamClient = modelStreamClient;
    }

    public AgentLoopResult run(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer) {
        String requestId = "agent_req_" + UUID.randomUUID().toString().substring(0, 8);
        List<AgentToolCallVO> toolCalls = new ArrayList<>();
        List<Map<String, Object>> toolResults = new ArrayList<>();
        StringBuilder assistantMessage = new StringBuilder();
        AgentChatRequestDTO loopRequest = withRuntimeContext(request);
        boolean completed = false;

        for (int loop = 0; loop < maxLoops() && !completed; loop++) {
            try {
                modelStreamClient.streamAssistantEvents(requestId, loopRequest, modelEvent -> {
                    if (modelEvent.isToken()) {
                        assistantMessage.append(modelEvent.delta());
                        consumer.accept(new AgentStreamEventVO("token", requestId, Map.of("delta", modelEvent.delta())));
                        return;
                    }
                    if (modelEvent.isToolUse()) {
                        String toolCallId = resolveToolCallId(modelEvent);
                        if ("emit_final_answer".equals(modelEvent.toolName())) {
                            String finalMessage = emitFinalAnswerBlocks(requestId, modelEvent.arguments(), consumer);
                            throw new AgentLoopFinalAnswerSignal(finalMessage);
                        }
                        consumer.accept(new AgentStreamEventVO("tool_use", requestId, Map.of(
                                "tool_call_id", toolCallId,
                                "tool_name", modelEvent.toolName(),
                                "arguments", modelEvent.arguments()
                        )));
                        CompletableFuture<AgentToolCallVO> future = toolUseExecutor.execute(modelEvent)
                                .thenApply(result -> new AgentToolCallVO(
                                        toolCallId,
                                        modelEvent.toolName(),
                                        profile.serviceForTool(modelEvent.toolName()),
                                        String.valueOf(result.getOrDefault("status", "SUCCESS")),
                                        result
                                ));
                        AgentToolCallVO toolCall = future.join();
                        toolCalls.add(toolCall);
                        toolResults.add(toolResultPayload(toolCall));
                        consumer.accept(toolResultEvent(requestId, toolCall));
                        throw new AgentLoopToolUseSignal();
                    }
                });
                completed = true;
            } catch (AgentLoopFinalAnswerSignal signal) {
                assistantMessage.append(signal.assistantMessage());
                completed = true;
            } catch (AgentLoopToolUseSignal ignored) {
                loopRequest = withToolResults(loopRequest, toolResults);
            }
        }
        if (!completed) {
            throw new IllegalStateException("agent loop exceeded max iterations: " + maxLoops());
        }

        consumer.accept(new AgentStreamEventVO("done", requestId, Map.of("done", true)));
        return new AgentLoopResult(profile.name(), requestId, assistantMessage.toString(), List.copyOf(toolCalls));
    }

    protected int maxLoops() {
        return DEFAULT_MAX_AGENT_LOOPS;
    }

    private AgentChatRequestDTO withRuntimeContext(AgentChatRequestDTO request) {
        Map<String, Object> context = new java.util.LinkedHashMap<>(request.resolvedContext());
        context.put("agent_name", profile.name());
        context.put("agent_description", profile.description());
        context.putAll(runtimeConfigurationService.modelContext());
        return withContext(request, context);
    }

    private AgentChatRequestDTO withToolResults(AgentChatRequestDTO request, List<Map<String, Object>> toolResults) {
        Map<String, Object> context = new java.util.LinkedHashMap<>(request.resolvedContext());
        context.put("tool_results", List.copyOf(toolResults));
        return withContext(request, context);
    }

    private AgentChatRequestDTO withContext(AgentChatRequestDTO request, Map<String, Object> context) {
        return new AgentChatRequestDTO(
                request.sessionId(),
                request.profileUserId(),
                request.userMessage(),
                request.limit(),
                context
        );
    }

    private AgentStreamEventVO toolResultEvent(String requestId, AgentToolCallVO toolCall) {
        return new AgentStreamEventVO("tool_result", requestId, Map.of(
                "tool_call_id", toolCall.toolCallId(),
                "tool_name", toolCall.toolName(),
                "service", toolCall.service(),
                "status", toolCall.status(),
                "metadata", toolCall.metadata()
        ));
    }

    private Map<String, Object> toolResultPayload(AgentToolCallVO toolCall) {
        return Map.of(
                "tool_call_id", toolCall.toolCallId(),
                "tool_name", toolCall.toolName(),
                "service", toolCall.service(),
                "status", toolCall.status(),
                "metadata", toolCall.metadata()
        );
    }

    private String resolveToolCallId(AgentModelStreamEvent modelEvent) {
        if (modelEvent.toolCallId() != null && !modelEvent.toolCallId().isBlank()) {
            return modelEvent.toolCallId();
        }
        return "toolu_" + UUID.randomUUID().toString().substring(0, 8);
    }

    private String emitFinalAnswerBlocks(
            String requestId,
            Map<String, Object> arguments,
            Consumer<AgentStreamEventVO> consumer
    ) {
        Object rawBlocks = arguments.get("blocks");
        if (!(rawBlocks instanceof List<?> blocks)) {
            throw new IllegalArgumentException("emit_final_answer requires blocks");
        }
        List<String> textBlocks = new ArrayList<>();
        for (Object rawBlock : blocks) {
            if (!(rawBlock instanceof Map<?, ?> block)) {
                throw new IllegalArgumentException("emit_final_answer block must be an object");
            }
            Object rawType = block.get("type");
            if (!(rawType instanceof String type) || type.isBlank()) {
                throw new IllegalArgumentException("emit_final_answer block requires type");
            }
            Map<String, Object> eventData = new java.util.LinkedHashMap<>();
            eventData.put("type", type);
            for (Map.Entry<?, ?> entry : block.entrySet()) {
                if (entry.getKey() instanceof String key && entry.getValue() != null) {
                    eventData.put(key, entry.getValue());
                }
            }
            if ("text".equals(type)) {
                Object content = block.get("content");
                if (!(content instanceof String text) || text.isBlank()) {
                    throw new IllegalArgumentException("text answer block requires content");
                }
                textBlocks.add(text);
            }
            consumer.accept(new AgentStreamEventVO("answer_block", requestId, Map.copyOf(eventData)));
        }
        return String.join("\n", textBlocks);
    }

    private static class AgentLoopToolUseSignal extends RuntimeException {
    }

    private static class AgentLoopFinalAnswerSignal extends RuntimeException {

        private final String assistantMessage;

        AgentLoopFinalAnswerSignal(String assistantMessage) {
            this.assistantMessage = assistantMessage;
        }

        String assistantMessage() {
            return assistantMessage;
        }
    }
}
