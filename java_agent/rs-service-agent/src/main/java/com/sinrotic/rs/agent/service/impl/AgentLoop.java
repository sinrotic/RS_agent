package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentExecutionLimiter;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.PublicAgentResponseProjector;
import com.sinrotic.rs.agent.service.A2uiMessageProjector;
import com.sinrotic.rs.agent.service.AgentToolUseOrchestrator;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.AgentToolUseResult;
import com.sinrotic.rs.agent.config.AgentExecutionProperties;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

public abstract class AgentLoop {

    static final String INTERNAL_REQUEST_ID_CONTEXT_KEY = "__agent_turn_request_id";
    static final String INTERNAL_SKILL_REUSE_CONTEXT_KEY = "__agent_allow_loaded_skill_reuse";

    private static final int DEFAULT_MAX_AGENT_LOOPS = 8;

    private static final int MAX_FINAL_ANSWER_BLOCKS = 12;

    private static final int MAX_FAILED_TOOLS_PER_TURN = 2;

    private static final Set<String> FINAL_ANSWER_BLOCK_TYPES = Set.of(
            "text",
            "product_cards",
            "comparison_table",
            "followup_question"
    );

    private static final Set<String> FINAL_ANSWER_BLOCK_FIELDS = Set.of(
            "type",
            "content",
            "card_set_id",
            "item_ids",
            "layout"
    );

    private final AgentProfile profile;

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    private final AgentToolUseExecutor toolUseExecutor;

    private final AgentModelStreamClient modelStreamClient;

    private final AgentExecutionLimiter executionLimiter;

    private final AgentLoopHookDispatcher hookDispatcher;

    private final AgentInterrupter interrupter;

    private final PublicAgentResponseProjector responseProjector = new PublicAgentResponseProjector();

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
        this(
                profile,
                runtimeConfigurationService,
                toolUseExecutor,
                modelStreamClient,
                hookDispatcher,
                interrupter,
                new AgentExecutionLimiter(new AgentExecutionProperties())
        );
    }

    protected AgentLoop(
            AgentProfile profile,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient,
            AgentLoopHookDispatcher hookDispatcher,
            AgentInterrupter interrupter,
            AgentExecutionLimiter executionLimiter
    ) {
        this.profile = profile;
        this.runtimeConfigurationService = runtimeConfigurationService;
        this.toolUseExecutor = toolUseExecutor;
        this.modelStreamClient = modelStreamClient;
        this.executionLimiter = executionLimiter == null ? new AgentExecutionLimiter(new AgentExecutionProperties()) : executionLimiter;
        this.hookDispatcher = hookDispatcher == null ? new NoopAgentLoopHookDispatcher() : hookDispatcher;
        this.interrupter = interrupter == null ? new InMemoryAgentInterrupter() : interrupter;
    }

    public AgentLoopResult run(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer) {
        return run(request, consumer, () -> { });
    }

    public AgentLoopResult run(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer, Runnable onReady) {
        return run(request, consumer, onReady, ignored -> java.util.Optional.empty());
    }

    boolean supportsDirectRecommendation() {
        return getClass() == RsAgentLoop.class && hookDispatcher.supportsDirectRecommendation();
    }

    public AgentLoopResult run(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer, Runnable onReady,
            java.util.function.Function<AgentChatRequestDTO, java.util.Optional<Map<String, Object>>> directAnswer) {
        String requestId = resolveRequestId(request);
        request = withoutInternalRequestId(request);
        A2uiMessageProjector.State uiState = new A2uiMessageProjector.State(request.resolvedContext().get("a2ui_state"));
        AgentInterruptContext interruptContext = interrupter.createTurn(
                requestId,
                request.sessionId(),
                String.valueOf(request.resolvedContext().getOrDefault("authenticated_account_id", "")),
                request.profileUserId()
        );
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
        try (var reasoning = modelStreamClient.reasoningPolicy().openTurn(interruptContext, request, consumer, modelStreamClient, executionLimiter);
             var turnTools = toolUseExecutor.openTurn(interruptContext)) {
            var toolUseOrchestrator = new StreamingAgentToolUseOrchestrator(turnTools);
            onReady.run();
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
                AgentToolUseOrchestrator.Run toolRun = toolUseOrchestrator.start();
                interruptContext.onInterrupt(toolRun::cancel);
                try {
                    state.set(state.get().withLoopIndex(loopIndex));
                    throwIfInterrupted(interruptContext);
                    state.set(state.get().withPhase(AgentLoopPhase.BEFORE_MODEL_CALL_HOOK));
                    loopRequest = applyHookContext(
                        loopRequest,
                        hook(AgentLoopHookEvent.BEFORE_MODEL_CALL, requestId, loopIndex, loopRequest)
                                .dispatch(hookDispatcher)
                    );
                    long failures = toolCalls.stream().filter(call -> Set.of("FAILED", "ERROR", "UNAVAILABLE")
                            .contains(call.status())).count();
                    boolean executionLimit = toolResults.stream().anyMatch(result -> result.get("metadata") instanceof Map<?, ?> metadata
                            && (Set.of("TOOL_BUDGET_EXHAUSTED", "TOOL_NO_PROGRESS").contains(String.valueOf(metadata.get("error_code")))
                            || metadata.get("governance") instanceof Map<?, ?> governance && Boolean.TRUE.equals(governance.get("no_progress"))));
                    if (executionLimit || reasoning.finalAnswerOnly() || (loopIndex == maxLoops() - 1 && !toolResults.isEmpty())
                            || failures >= MAX_FAILED_TOOLS_PER_TURN) {
                        var finalContext = new java.util.LinkedHashMap<String, Object>(loopRequest.resolvedContext());
                        finalContext.put("final_answer_only", true);
                        loopRequest = withContext(loopRequest, finalContext);
                    }
                    state.set(state.get().withRequest(loopRequest).withPhase(AgentLoopPhase.MODEL_STREAMING));
                    AgentChatRequestDTO currentLoopRequest = loopRequest;
                    AtomicBoolean toolUseSeenThisTurn = new AtomicBoolean(false);
                    Consumer<AgentModelStreamEvent> modelConsumer = modelEvent -> {
                        throwIfInterrupted(interruptContext);
                        if (modelEvent.isToken()) {
                            if (toolUseSeenThisTurn.get()) {
                                return;
                            }
                            assistantMessage.append(modelEvent.delta());
                            consumer.accept(new AgentStreamEventVO("token", requestId, Map.of("delta", modelEvent.delta())));
                            throwIfInterrupted(interruptContext);
                            return;
                        }
                        if (modelEvent.isToolUse()) {
                            toolUseSeenThisTurn.set(true);
                            String toolCallId = resolveToolCallId(modelEvent);
                            if ("emit_final_answer".equals(modelEvent.toolName())) {
                                String finalMessage = emitFinalAnswerBlocks(requestId, modelEvent.arguments(), consumer, uiState);
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
                            if (Boolean.TRUE.equals(currentLoopRequest.resolvedContext().get("final_answer_only")) || reasoning.finalAnswerOnly()) {
                                toolRun.complete(toolCallId, toolEvent, Map.of("status", "FAILED", "error_code", "TOOL_FINAL_ANSWER_ONLY",
                                        "error_message", "Only the final answer is allowed after execution limits"));
                                return;
                            }
                            throwIfInterrupted(interruptContext);
                            if (preToolHook.blocked()) {
                                AgentToolCallVO toolCall = blockedToolCall(toolCallId, toolEvent, preToolHook.message());
                                toolRun.complete(toolCallId, toolEvent, toolCall.metadata());
                                state.set(state.get()
                                        .clearPendingToolCall()
                                        .withPhase(AgentLoopPhase.TOOL_RESULT_READY)
                                        .withTransition(AgentLoopTransition.continueLoop()));
                                return;
                            }
                            state.set(state.get().withPhase(AgentLoopPhase.TOOL_EXECUTING));
                            var drift = reasoning.beforeTool(toolEvent);
                            throwIfInterrupted(interruptContext);
                            if (drift.blocked()) { toolRun.complete(toolCallId,toolEvent,drift.result()); return; }
                            if ("emit_ui".equals(toolEvent.toolName())) {
                                try {
                                    if (runtimeConfigurationService.tools().stream().noneMatch(tool ->
                                            tool.enabled() && "emit_ui".equals(tool.name()))) {
                                        throw new IllegalArgumentException("emit_ui is disabled");
                                    }
                                    Map<String, Object> rawBlock = new java.util.LinkedHashMap<>();
                                    rawBlock.put("type", "a2ui");
                                    rawBlock.put("messages", toolEvent.arguments().get("messages"));
                                    Map<String, Object> block = responseProjector.projectBlock(rawBlock, runtimeProfile());
                                    uiState.accept(block.get("messages"));
                                    consumer.accept(new AgentStreamEventVO("answer_block", requestId, block));
                                    toolRun.complete(toolCallId, toolEvent, Map.of("status", "SUCCESS", "published", true));
                                } catch (IllegalArgumentException error) {
                                    toolRun.complete(toolCallId, toolEvent, Map.of("status", "FAILED", "message", error.getMessage()));
                                }
                                return;
                            }
                            toolRun.submit(toolCallId, toolEvent);
                        }
                        if (modelEvent.isUsage()) {
                            modelUsage.putAll(modelEvent.arguments());
                            consumer.accept(new AgentStreamEventVO("model_usage", requestId, modelEvent.arguments()));
                        }
                    };
                    var preparedAnswer = loopIndex == 0 && supportsDirectRecommendation()
                            ? directAnswer.apply(currentLoopRequest) : java.util.Optional.<Map<String, Object>>empty();
                    if (preparedAnswer.isPresent()) {
                        modelConsumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", preparedAnswer.get()));
                    } else {
                        modelUsage.clear();
                        streamAssistantEvents(requestId, loopIndex, currentLoopRequest, interruptContext, modelConsumer, consumer);
                    }
                    if (toolRun.hasSubmittedTools()) {
                        state.set(state.get().withPhase(AgentLoopPhase.TOOL_EXECUTING));
                        List<AgentToolUseResult> toolUseResults = toolRun.awaitResults();
                        for (AgentToolUseResult toolUseResult : toolUseResults) {
                            acceptToolUseResult(
                                    requestId,
                                    loopIndex,
                                    currentLoopRequest,
                                    toolUseResult,
                                    toolCalls,
                                    toolResults,
                                    consumer,
                                    interruptContext,
                                    state
                            );
                        }
                        state.set(state.get()
                                .clearPendingToolCall()
                                .withPhase(AgentLoopPhase.TOOL_RESULT_READY)
                                .withTransition(AgentLoopTransition.continueLoop()));
                        throw new AgentLoopToolUseSignal();
                    }
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
                    toolRun.cancel();
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
                    toolRun.cancel();
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
                    toolRun.cancel();
                    if (!signal.message().isBlank()) {
                        consumer.accept(new AgentStreamEventVO("hook_stopped", requestId, Map.of("message", signal.message())));
                    }
                    state.set(state.get()
                            .withTransition(AgentLoopTransition.complete(AgentFinishReason.HOOK_STOPPED))
                            .withPhase(AgentLoopPhase.COMPLETED));
                    completed = true;
                } catch (RuntimeException error) {
                    toolRun.cancel();
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
        return runtimeProfile().maxLoops();
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
        AgentRuntimeProfile runtimeProfile = runtimeProfile();
        context.put("agent_name", profile.name());
        context.put(INTERNAL_SKILL_REUSE_CONTEXT_KEY, supportsDirectRecommendation());
        context.put("agent_description", profile.description());
        context.putAll(runtimeConfigurationService.modelContext());
        context.put("agent_profile_id", runtimeProfile.id());
        context.put("agent_model_ref", runtimeProfile.modelRef());
        context.put("agent_system_prompt_ref", runtimeProfile.systemPromptRef());
        context.put("agent_allowed_capabilities", runtimeProfile.allowedCapabilities());
        context.put("agent_allowed_output_blocks", runtimeProfile.allowedOutputBlocks());
        context.put("agent_max_loops", runtimeProfile.maxLoops());
        context.put("available_tools", runtimeConfigurationService.toolsForProfile(runtimeProfile).stream()
                .map(tool -> Map.of(
                        "name", tool.name(),
                        "service", tool.service(),
                        "description", tool.description(),
                        "parameters_schema", tool.parametersSchema()
                ))
                .toList());
        return withContext(request, context);
    }

    private AgentRuntimeProfile runtimeProfile() {
        return runtimeConfigurationService.defaultProfile();
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

    private String resolveRequestId(AgentChatRequestDTO request) {
        Object configured = request.resolvedContext().get(INTERNAL_REQUEST_ID_CONTEXT_KEY);
        if (configured instanceof String requestId && !requestId.isBlank()) {
            return requestId;
        }
        return "agent_req_" + UUID.randomUUID().toString().substring(0, 8);
    }

    private AgentChatRequestDTO withoutInternalRequestId(AgentChatRequestDTO request) {
        if (!request.resolvedContext().containsKey(INTERNAL_REQUEST_ID_CONTEXT_KEY)) {
            return request;
        }
        Map<String, Object> context = new java.util.LinkedHashMap<>(request.resolvedContext());
        context.remove(INTERNAL_REQUEST_ID_CONTEXT_KEY);
        return new AgentChatRequestDTO(
                request.sessionId(),
                request.profileUserId(),
                request.userMessage(),
                request.limit(),
                Map.copyOf(context)
        );
    }

    private void acceptToolUseResult(
            String requestId,
            int loopIndex,
            AgentChatRequestDTO currentLoopRequest,
            AgentToolUseResult toolUseResult,
            List<AgentToolCallVO> toolCalls,
            List<Map<String, Object>> toolResults,
            Consumer<AgentStreamEventVO> consumer,
            AgentInterruptContext interruptContext,
            AtomicReference<AgentTurnState> state
    ) {
        AgentModelStreamEvent toolEvent = toolUseResult.event();
        String toolCallId = toolUseResult.toolCallId();
        if (!toolUseResult.succeeded()) {
            Throwable error = toolUseResult.error();
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
                    .withError(errorMessage(error))
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
            return;
        }

        AgentToolCallVO toolCall = completedToolCall(toolCallId, toolEvent, toolUseResult.metadata());
        if (!"BLOCKED".equals(toolCall.status())) {
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
        }
        toolCalls.add(toolCall);
        toolResults.add(toolResultPayload(toolCall));
        consumer.accept(toolResultEvent(requestId, toolCall));
    }

    private AgentToolCallVO completedToolCall(
            String toolCallId,
            AgentModelStreamEvent event,
            Map<String, Object> metadata
    ) {
        return new AgentToolCallVO(
                toolCallId,
                event.toolName(),
                profile.serviceForTool(event.toolName()),
                String.valueOf(metadata.getOrDefault("status", "SUCCESS")),
                metadata
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

    private void streamAssistantEvents(
            String requestId,
            int loopIndex,
            AgentChatRequestDTO request,
            AgentInterruptContext interruptContext,
            Consumer<AgentModelStreamEvent> consumer,
            Consumer<AgentStreamEventVO> observations
    ) {
        try {
            executionLimiter.runWithModelStream(() -> {
                var observation = new AgentModelCallObservation(requestId, request.sessionId(), loopIndex, observations);
                String status = "error";
                boolean transportFinished = false;
                try {
                    modelStreamClient.streamAssistantEvents(requestId, request, event -> {
                        observation.record(event);
                        consumer.accept(event);
                    }, interruptContext, observation::recordRequest);
                    transportFinished = !interruptContext.interrupted();
                    status = transportFinished ? "completed" : "interrupted";
                } catch (AgentLoopFinalAnswerSignal finalAnswer) {
                    status = "answer_emitted";
                    throw finalAnswer;
                } catch (AgentLoopHookStoppedSignal stopped) {
                    status = "hook_stopped";
                    throw stopped;
                } catch (RuntimeException failure) {
                    status = interruptContext.interrupted() || failure instanceof CancellationException
                            || failure instanceof AgentLoopInterruptedSignal ? "interrupted" : "error";
                    throw failure;
                } finally {
                    observation.finish(status, transportFinished);
                }
            }, interruptContext::interrupted);
        } catch (RuntimeException error) {
            if (error instanceof AgentModelBudgetException budgetFailure) {
                interruptContext.interrupt(budgetFailure.code().toLowerCase(java.util.Locale.ROOT));
            }
            if (error instanceof AgentLoopFinalAnswerSignal || error instanceof AgentLoopHookStoppedSignal) {
                throw error;
            }
            throwIfInterrupted(interruptContext);
            throw error;
        }
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

    private AgentToolCallVO failedToolCall(String toolCallId, AgentModelStreamEvent event, Throwable error) {
        Throwable cause = unwrap(error);
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

    private String errorMessage(Throwable error) {
        Throwable cause = unwrap(error);
        return cause.getMessage() == null ? cause.getClass().getSimpleName() : cause.getMessage();
    }

    private Throwable unwrap(Throwable error) {
        if (error instanceof CompletionException completionException && completionException.getCause() != null) {
            return completionException.getCause();
        }
        return error == null ? new IllegalStateException("tool use failed") : error;
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
            Consumer<AgentStreamEventVO> consumer,
            A2uiMessageProjector.State uiState
    ) {
        List<Map<String, Object>> blocks = responseProjector.projectBlocks(arguments.get("blocks"), runtimeProfile());
        for (Map<String, Object> block : blocks) {
            if ("a2ui".equals(block.get("type"))) uiState.accept(block.get("messages"));
        }
        uiState.validateComplete();
        List<String> textBlocks = new ArrayList<>();
        for (Map<String, Object> block : blocks) {
            String type = String.valueOf(block.get("type"));
            if ("text".equals(type)) {
                Object content = block.get("content");
                textBlocks.add((String) content);
            }
            Map<String, Object> traceableBlock = new java.util.LinkedHashMap<>(block);
            traceableBlock.put("profile_id", runtimeProfile().id());
            consumer.accept(new AgentStreamEventVO("answer_block", requestId, Map.copyOf(traceableBlock)));
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
