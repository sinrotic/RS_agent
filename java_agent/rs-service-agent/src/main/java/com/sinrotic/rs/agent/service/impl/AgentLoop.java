package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletionException;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

public abstract class AgentLoop {

    private static final int DEFAULT_MAX_AGENT_LOOPS = 8;

    private final AgentProfile profile;

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    private final AgentToolUseExecutor toolUseExecutor;

    private final AgentModelStreamClient modelStreamClient;

    private final AgentLoopHookDispatcher hookDispatcher;

    private final AgentInterrupter interrupter;

    protected AgentLoop(
            AgentProfile profile,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient
    ) {
        this(
                profile,
                runtimeConfigurationService,
                toolUseExecutor,
                modelStreamClient,
                new NoopAgentLoopHookDispatcher(),
                new InMemoryAgentInterrupter()
        );
    }

    protected AgentLoop(
            AgentProfile profile,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient,
            AgentLoopHookDispatcher hookDispatcher
    ) {
        this(
                profile,
                runtimeConfigurationService,
                toolUseExecutor,
                modelStreamClient,
                hookDispatcher,
                new InMemoryAgentInterrupter()
        );
    }

    protected AgentLoop(
            AgentProfile profile,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient,
            AgentLoopHookDispatcher hookDispatcher,
            AgentInterrupter interrupter
    ) {
        this.profile = profile;
        this.runtimeConfigurationService = runtimeConfigurationService;
        this.toolUseExecutor = toolUseExecutor;
        this.modelStreamClient = modelStreamClient;
        this.hookDispatcher = hookDispatcher == null ? new NoopAgentLoopHookDispatcher() : hookDispatcher;
        this.interrupter = interrupter == null ? new InMemoryAgentInterrupter() : interrupter;
    }

    public AgentLoopResult run(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer) {
        String requestId = "agent_req_" + UUID.randomUUID().toString().substring(0, 8);
        AgentInterruptContext interruptContext = interrupter.createTurn(requestId, request.sessionId());
        List<AgentToolCallVO> toolCalls = new ArrayList<>();
        List<Map<String, Object>> toolResults = new ArrayList<>();
        Map<String, Object> modelUsage = new java.util.LinkedHashMap<>();
        StringBuilder assistantMessage = new StringBuilder();
        AtomicReference<AgentTurnState> state = new AtomicReference<>(new AgentTurnState(
                requestId,
                request.sessionId(),
                request,
                assistantMessage,
                toolCalls,
                toolResults,
                modelUsage,
                interruptContext,
                0,
                AgentLoopPhase.CREATED,
                AgentLoopTransition.complete(AgentFinishReason.FINAL_ANSWER),
                null
        ));
        try {
            AgentChatRequestDTO loopRequest = withRuntimeContext(request);
            state.set(state.get().withRequest(loopRequest).withPhase(AgentLoopPhase.SESSION_START_HOOK));
            loopRequest = applyHookContext(
                    loopRequest,
                    hook(AgentLoopHookEvent.SESSION_START, requestId, 0, loopRequest)
                            .dispatch(hookDispatcher)
            );
            state.set(state.get().withRequest(loopRequest).withPhase(AgentLoopPhase.USER_PROMPT_HOOK));
            loopRequest = applyHookContext(
                    loopRequest,
                    hook(AgentLoopHookEvent.USER_PROMPT_SUBMIT, requestId, 0, loopRequest)
                            .dispatch(hookDispatcher)
            );
            boolean completed = false;

            for (int loop = 0; loop < maxLoops() && !completed; loop++) {
                final int loopIndex = loop;
                try {
                    state.set(state.get().withLoopIndex(loopIndex));
                    throwIfInterrupted(interruptContext);
                    state.set(state.get().withPhase(AgentLoopPhase.BEFORE_MODEL_CALL_HOOK));
                    loopRequest = applyHookContext(
                        loopRequest,
                        hook(AgentLoopHookEvent.BEFORE_MODEL_CALL, requestId, loopIndex, loopRequest)
                                .dispatch(hookDispatcher)
                    );
                    state.set(state.get().withRequest(loopRequest).withPhase(AgentLoopPhase.MODEL_STREAMING));
                    AgentChatRequestDTO currentLoopRequest = loopRequest;
                    modelStreamClient.streamAssistantEvents(requestId, loopRequest, modelEvent -> {
                        throwIfInterrupted(interruptContext);
                        if (modelEvent.isToken()) {
                            assistantMessage.append(modelEvent.delta());
                            consumer.accept(new AgentStreamEventVO("token", requestId, Map.of("delta", modelEvent.delta())));
                            throwIfInterrupted(interruptContext);
                            return;
                        }
                        if (modelEvent.isToolUse()) {
                            String toolCallId = resolveToolCallId(modelEvent);
                            if ("emit_final_answer".equals(modelEvent.toolName())) {
                                String finalMessage = emitFinalAnswerBlocks(requestId, modelEvent.arguments(), consumer);
                                state.set(state.get()
                                        .withTransition(AgentLoopTransition.complete(AgentFinishReason.FINAL_ANSWER))
                                        .withPhase(AgentLoopPhase.COMPLETED));
                                throw new AgentLoopFinalAnswerSignal(finalMessage);
                            }
                            state.set(state.get()
                                    .withPhase(AgentLoopPhase.TOOL_USE_DETECTED)
                                    .withPendingToolCall(new PendingToolCall(
                                            toolCallId,
                                            modelEvent.toolName(),
                                            modelEvent.arguments(),
                                            AgentLoopPhase.TOOL_USE_DETECTED
                                    )));
                            AgentLoopHookResult preToolHook = hook(AgentLoopHookEvent.PRE_TOOL_USE, requestId, loopIndex, currentLoopRequest)
                                    .withTool(toolCallId, modelEvent.toolName(), modelEvent.arguments())
                                    .dispatch(hookDispatcher);
                            if (preToolHook.preventContinuation()) {
                                state.set(state.get()
                                        .withTransition(AgentLoopTransition.complete(AgentFinishReason.HOOK_STOPPED))
                                        .withPhase(AgentLoopPhase.COMPLETED));
                                throw new AgentLoopHookStoppedSignal(preToolHook.message());
                            }
                            AgentModelStreamEvent toolEvent = preToolHook.hasUpdatedToolArguments()
                                    ? AgentModelStreamEvent.toolUse(toolCallId, modelEvent.toolName(), preToolHook.updatedToolArguments())
                                    : modelEvent;
                            state.set(state.get().withPendingToolCall(new PendingToolCall(
                                    toolCallId,
                                    toolEvent.toolName(),
                                    toolEvent.arguments(),
                                    AgentLoopPhase.TOOL_USE_DETECTED
                            )));
                            consumer.accept(new AgentStreamEventVO("tool_use", requestId, Map.of(
                                    "tool_call_id", toolCallId,
                                    "tool_name", toolEvent.toolName(),
                                    "arguments", toolEvent.arguments()
                            )));
                            throwIfInterrupted(interruptContext);
                            if (preToolHook.blocked()) {
                                AgentToolCallVO toolCall = blockedToolCall(toolCallId, toolEvent, preToolHook.message());
                                toolCalls.add(toolCall);
                                toolResults.add(toolResultPayload(toolCall));
                                consumer.accept(toolResultEvent(requestId, toolCall));
                                state.set(state.get()
                                        .clearPendingToolCall()
                                        .withPhase(AgentLoopPhase.TOOL_RESULT_READY)
                                        .withTransition(AgentLoopTransition.continueLoop()));
                                throw new AgentLoopToolUseSignal();
                            }
                            state.set(state.get().withPhase(AgentLoopPhase.TOOL_EXECUTING));
                            CompletableFuture<Map<String, Object>> toolFuture = toolUseExecutor.execute(toolEvent);
                            CompletableFuture<AgentToolCallVO> future = toolFuture
                                    .thenApply(result -> new AgentToolCallVO(
                                            toolCallId,
                                            toolEvent.toolName(),
                                            profile.serviceForTool(toolEvent.toolName()),
                                            String.valueOf(result.getOrDefault("status", "SUCCESS")),
                                            result
                                    ));
                            interruptContext.onInterrupt(() -> {
                                toolFuture.cancel(true);
                                future.cancel(true);
                            });
                            AgentToolCallVO toolCall;
                            try {
                                toolCall = future.join();
                                throwIfInterrupted(interruptContext);
                            } catch (CancellationException error) {
                                AgentToolCallVO interruptedToolCall = interruptedToolCall(toolCallId, toolEvent, interruptContext.reason());
                                toolCalls.add(interruptedToolCall);
                                toolResults.add(toolResultPayload(interruptedToolCall));
                                consumer.accept(toolResultEvent(requestId, interruptedToolCall));
                                state.set(state.get()
                                        .clearPendingToolCall()
                                        .withPhase(AgentLoopPhase.INTERRUPTED)
                                        .withTransition(AgentLoopTransition.complete(AgentFinishReason.INTERRUPTED)));
                                throw new AgentLoopInterruptedSignal(interruptContext.reason());
                            } catch (CompletionException error) {
                                AgentToolCallVO failedToolCall = interruptContext.interrupted()
                                        ? interruptedToolCall(toolCallId, toolEvent, interruptContext.reason())
                                        : failedToolCall(toolCallId, toolEvent, error);
                                AgentLoopHookContext failureHook = hook(AgentLoopHookEvent.POST_TOOL_USE_FAILURE, requestId, loopIndex, currentLoopRequest);
                                if (failedToolCall.status().equals("INTERRUPTED")) {
                                    failureHook = hook(AgentLoopHookEvent.INTERRUPT, requestId, loopIndex, currentLoopRequest);
                                }
                                failureHook
                                        .withTool(toolCallId, toolEvent.toolName(), toolEvent.arguments())
                                        .withToolResult(failedToolCall.metadata())
                                        .withError(error.getMessage())
                                        .dispatch(hookDispatcher);
                                toolCalls.add(failedToolCall);
                                toolResults.add(toolResultPayload(failedToolCall));
                                consumer.accept(toolResultEvent(requestId, failedToolCall));
                                if (interruptContext.interrupted()) {
                                    state.set(state.get()
                                            .clearPendingToolCall()
                                            .withPhase(AgentLoopPhase.INTERRUPTED)
                                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.INTERRUPTED)));
                                    throw new AgentLoopInterruptedSignal(interruptContext.reason());
                                }
                                state.set(state.get()
                                        .clearPendingToolCall()
                                        .withPhase(AgentLoopPhase.TOOL_RESULT_READY)
                                        .withTransition(AgentLoopTransition.continueLoop()));
                                throw new AgentLoopToolUseSignal();
                            }
                            AgentLoopHookResult postToolHook = hook(AgentLoopHookEvent.POST_TOOL_USE, requestId, loopIndex, currentLoopRequest)
                                    .withTool(toolCallId, toolEvent.toolName(), toolEvent.arguments())
                                    .withToolResult(toolCall.metadata())
                                    .dispatch(hookDispatcher);
                            if (postToolHook.preventContinuation()) {
                                state.set(state.get()
                                        .clearPendingToolCall()
                                        .withTransition(AgentLoopTransition.complete(AgentFinishReason.HOOK_STOPPED))
                                        .withPhase(AgentLoopPhase.COMPLETED));
                                throw new AgentLoopHookStoppedSignal(postToolHook.message());
                            }
                            toolCalls.add(toolCall);
                            toolResults.add(toolResultPayload(toolCall));
                            consumer.accept(toolResultEvent(requestId, toolCall));
                            state.set(state.get()
                                    .clearPendingToolCall()
                                    .withPhase(AgentLoopPhase.TOOL_RESULT_READY)
                                    .withTransition(AgentLoopTransition.continueLoop()));
                            throw new AgentLoopToolUseSignal();
                        }
                        if (modelEvent.isUsage()) {
                            modelUsage.putAll(modelEvent.arguments());
                            consumer.accept(new AgentStreamEventVO("model_usage", requestId, modelEvent.arguments()));
                        }
                    });
                    throwIfInterrupted(interruptContext);
                    state.set(state.get().withPhase(AgentLoopPhase.POST_MODEL_STREAM_HOOK));
                    AgentLoopHookResult postModelHook = hook(AgentLoopHookEvent.POST_MODEL_STREAM, requestId, loopIndex, loopRequest)
                            .withAssistantMessage(assistantMessage.toString())
                            .withMetadata(modelUsage)
                            .dispatch(hookDispatcher);
                    if (postModelHook.preventContinuation()) {
                        state.set(state.get()
                                .withTransition(AgentLoopTransition.complete(AgentFinishReason.HOOK_STOPPED))
                                .withPhase(AgentLoopPhase.COMPLETED));
                        completed = true;
                        break;
                    }
                    loopRequest = applyHookContext(loopRequest, postModelHook);
                    state.set(state.get().withRequest(loopRequest).withPhase(AgentLoopPhase.STOP_HOOK));
                    AgentLoopHookResult stopHook = hook(AgentLoopHookEvent.STOP, requestId, loopIndex, loopRequest)
                            .withAssistantMessage(assistantMessage.toString())
                            .dispatch(hookDispatcher);
                    if (stopHook.preventContinuation()) {
                        state.set(state.get()
                                .withTransition(AgentLoopTransition.complete(AgentFinishReason.HOOK_STOPPED))
                                .withPhase(AgentLoopPhase.COMPLETED));
                        completed = true;
                        break;
                    }
                    if (stopHook.blocked()) {
                        toolResults.add(hookResultPayload(AgentLoopHookEvent.STOP, "BLOCKED", stopHook.message()));
                        loopRequest = withToolResults(loopRequest, toolResults);
                        state.set(state.get()
                                .withRequest(loopRequest)
                                .withTransition(AgentLoopTransition.continueLoop()));
                        continue;
                    }
                    loopRequest = applyHookContext(loopRequest, stopHook);
                    state.set(state.get()
                            .withRequest(loopRequest)
                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.FINAL_ANSWER))
                            .withPhase(AgentLoopPhase.COMPLETED));
                    completed = true;
                } catch (AgentLoopFinalAnswerSignal signal) {
                    assistantMessage.append(signal.assistantMessage());
                    state.set(state.get()
                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.FINAL_ANSWER))
                            .withPhase(AgentLoopPhase.COMPLETED));
                    completed = true;
                } catch (AgentLoopToolUseSignal ignored) {
                    loopRequest = withToolResults(loopRequest, toolResults);
                    state.set(state.get()
                            .withRequest(loopRequest)
                            .withTransition(AgentLoopTransition.continueLoop()));
                } catch (AgentLoopInterruptedSignal signal) {
                    hook(AgentLoopHookEvent.INTERRUPT, requestId, loopIndex, loopRequest)
                            .withAssistantMessage(assistantMessage.toString())
                            .withError(signal.reason())
                            .dispatch(hookDispatcher);
                    consumer.accept(interruptedEvent(requestId, signal.reason()));
                    state.set(state.get()
                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.INTERRUPTED))
                            .withPhase(AgentLoopPhase.INTERRUPTED));
                    completed = true;
                } catch (AgentLoopHookStoppedSignal signal) {
                    if (!signal.message().isBlank()) {
                        consumer.accept(new AgentStreamEventVO("hook_stopped", requestId, Map.of("message", signal.message())));
                    }
                    state.set(state.get()
                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.HOOK_STOPPED))
                            .withPhase(AgentLoopPhase.COMPLETED));
                    completed = true;
                } catch (RuntimeException error) {
                    state.set(state.get()
                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.MODEL_ERROR))
                            .withPhase(AgentLoopPhase.FAILED));
                    hook(AgentLoopHookEvent.STOP_FAILURE, requestId, loopIndex, loopRequest)
                            .withAssistantMessage(assistantMessage.toString())
                            .withError(error.getMessage())
                            .dispatch(hookDispatcher);
                    throw error;
                }
            }
            if (!completed) {
                state.set(state.get()
                        .withTransition(AgentLoopTransition.complete(AgentFinishReason.MAX_LOOP))
                        .withPhase(AgentLoopPhase.FAILED));
                throw new IllegalStateException("agent loop exceeded max iterations: " + maxLoops());
            }

            consumer.accept(new AgentStreamEventVO("done", requestId, Map.of(
                    "done", true,
                    "finish_reason", state.get().transition().finishReason().name()
            )));
            return new AgentLoopResult(
                    profile.name(),
                    requestId,
                    assistantMessage.toString(),
                    List.copyOf(toolCalls),
                    state.get().transition().finishReason()
            );
        } finally {
            interrupter.close(requestId);
        }
    }

    protected int maxLoops() {
        return DEFAULT_MAX_AGENT_LOOPS;
    }

    private AgentLoopHookContext hook(String eventName, String requestId, int loopIndex, AgentChatRequestDTO request) {
        return AgentLoopHookContext.of(eventName, requestId, profile, loopIndex, request);
    }

    private AgentChatRequestDTO applyHookContext(AgentChatRequestDTO request, AgentLoopHookResult hookResult) {
        if (!hookResult.hasAdditionalContext()) {
            return request;
        }
        Map<String, Object> context = new java.util.LinkedHashMap<>(request.resolvedContext());
        Map<String, Object> hookContext = new java.util.LinkedHashMap<>();
        Object existing = context.get("hook_context");
        if (existing instanceof Map<?, ?> existingMap) {
            for (Map.Entry<?, ?> entry : existingMap.entrySet()) {
                if (entry.getKey() instanceof String key && entry.getValue() != null) {
                    hookContext.put(key, entry.getValue());
                }
            }
        }
        hookContext.putAll(hookResult.additionalContext());
        context.put("hook_context", Map.copyOf(hookContext));
        return withContext(request, context);
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

    private AgentStreamEventVO interruptedEvent(String requestId, String reason) {
        return new AgentStreamEventVO("interrupted", requestId, Map.of(
                "request_id", requestId,
                "reason", reason == null || reason.isBlank() ? "interrupted" : reason
        ));
    }

    private void throwIfInterrupted(AgentInterruptContext interruptContext) {
        if (interruptContext.interrupted()) {
            throw new AgentLoopInterruptedSignal(interruptContext.reason());
        }
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

    private Map<String, Object> hookResultPayload(String eventName, String status, String message) {
        return Map.of(
                "tool_call_id", "hook_" + eventName,
                "tool_name", "hook:" + eventName,
                "service", "rs-service-agent",
                "status", status,
                "metadata", Map.of("message", message == null ? "" : message)
        );
    }

    private AgentToolCallVO blockedToolCall(String toolCallId, AgentModelStreamEvent event, String message) {
        return new AgentToolCallVO(
                toolCallId,
                event.toolName(),
                profile.serviceForTool(event.toolName()),
                "BLOCKED",
                Map.of(
                        "status", "BLOCKED",
                        "tool_name", event.toolName(),
                        "arguments", event.arguments(),
                        "message", message == null ? "" : message
                )
        );
    }

    private AgentToolCallVO failedToolCall(String toolCallId, AgentModelStreamEvent event, CompletionException error) {
        Throwable cause = error.getCause() == null ? error : error.getCause();
        if (cause instanceof InterruptedException) {
            Thread.currentThread().interrupt();
        }
        return new AgentToolCallVO(
                toolCallId,
                event.toolName(),
                profile.serviceForTool(event.toolName()),
                cause instanceof InterruptedException ? "INTERRUPTED" : "FAILED",
                Map.of(
                        "status", cause instanceof InterruptedException ? "INTERRUPTED" : "FAILED",
                        "tool_name", event.toolName(),
                        "arguments", event.arguments(),
                        "message", cause.getMessage() == null ? cause.getClass().getSimpleName() : cause.getMessage()
                )
        );
    }

    private AgentToolCallVO interruptedToolCall(String toolCallId, AgentModelStreamEvent event, String reason) {
        return new AgentToolCallVO(
                toolCallId,
                event.toolName(),
                profile.serviceForTool(event.toolName()),
                "INTERRUPTED",
                Map.of(
                        "status", "INTERRUPTED",
                        "tool_name", event.toolName(),
                        "arguments", event.arguments(),
                        "message", reason == null || reason.isBlank() ? "interrupted" : reason
                )
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

    private static class AgentLoopHookStoppedSignal extends RuntimeException {

        private final String message;

        AgentLoopHookStoppedSignal(String message) {
            this.message = message == null ? "" : message;
        }

        String message() {
            return message;
        }
    }

    private static class AgentLoopInterruptedSignal extends RuntimeException {

        private final String reason;

        AgentLoopInterruptedSignal(String reason) {
            this.reason = reason == null || reason.isBlank() ? "interrupted" : reason;
        }

        String reason() {
            return reason;
        }
    }
}
