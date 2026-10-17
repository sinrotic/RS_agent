package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentChatService;
import com.sinrotic.rs.agent.service.AgentChatStreamService;
import com.sinrotic.rs.agent.service.AgentExecutionLimiter;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentRecommendationService;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentSessionJournal;
import com.sinrotic.rs.agent.service.AgentSessionNotFoundException;
import com.sinrotic.rs.agent.service.AgentSessionTurnScheduler;
import com.sinrotic.rs.agent.service.AgentTraceReporter;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.AgentTraceService;
import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

@Service
public class InMemoryAgentOrchestrationService implements AgentChatService, AgentChatStreamService, AgentTraceService {

    private record SessionView(String owner, String account, long seq, List<AgentTurnVO> turns) {
        private SessionView { turns = List.copyOf(turns); }
        private int weight() {
            long characters = turns.stream().mapToLong(turn -> turn.toString().length()).sum();
            return (int) Math.min(Integer.MAX_VALUE, Math.max(32768L, characters * 2 + 1024));
        }
    }
    private final com.github.benmanes.caffeine.cache.Cache<String, SessionView> sessionViews =
            com.github.benmanes.caffeine.cache.Caffeine.newBuilder().maximumWeight(8L * 1024 * 1024)
                    .weigher((String key, SessionView view) -> view.weight())
                    .expireAfterAccess(java.time.Duration.ofMinutes(30)).build();

    public long retainedSessionCount() { sessionViews.cleanUp(); return sessionViews.estimatedSize(); }

    private final AgentLoop agentLoop;

    private final AgentTraceReporter traceReporter;

    private final AgentHotSessionStore hotSessionStore;

    private final AgentExecutionLimiter executionLimiter;

    private final AgentSessionTurnScheduler sessionTurnScheduler;

    private final AgentSessionJournal sessionJournal;

    private AgentRecommendationService recommendationService = request -> List.of();
    private AgentDirectRecommendation directRecommendation;
    private AgentTurnObservation observation = new AgentTurnObservation(false);
    private com.sinrotic.rs.agent.service.AgentOnlineEvaluationObserver onlineEvaluation = (request, turn, previous) -> { };

    @Autowired(required = false)
    public void setOnlineEvaluationObserver(com.sinrotic.rs.agent.service.AgentOnlineEvaluationObserver observer) {
        this.onlineEvaluation = observer;
    }

    private void observeCompleted(AgentChatRequestDTO request, AgentTurnVO turn, List<AgentTurnVO> previous) {
        try { onlineEvaluation.completed(request, turn, previous); }
        catch (RuntimeException ignored) { /* Shadow evaluation never changes durable request outcome. */ }
    }

    private final com.fasterxml.jackson.databind.ObjectMapper responseMapper = new com.fasterxml.jackson.databind.ObjectMapper();
    private com.sinrotic.rs.agent.service.AgentSessionAdmissionClient sessionAdmission = request -> { };
    private com.sinrotic.rs.agent.service.AgentTranscriptRecoveryService transcriptRecovery;
    @Autowired
    public void setTranscriptRecoveryService(com.sinrotic.rs.agent.service.AgentTranscriptRecoveryService recovery) {
        this.transcriptRecovery = recovery;
    }
    @Autowired
    public void setSessionAdmissionClient(com.sinrotic.rs.agent.service.AgentSessionAdmissionClient admission) {
        this.sessionAdmission = admission;
    }

    public InMemoryAgentOrchestrationService() {
        this(
                new MockAgentModelStreamClient(),
                new VirtualThreadAgentToolUseExecutor(),
                new InMemoryAgentRuntimeConfigurationService(),
                event -> {
                }
        );
    }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor
    ) {
        this(modelStreamClient, toolUseExecutor, new InMemoryAgentRuntimeConfigurationService(), event -> {
        });
    }

    @Autowired
    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentTraceReporter traceReporter,
            AgentLoopHookDispatcher hookDispatcher,
            AgentInterrupter interrupter,
            AgentHotSessionStore hotSessionStore,
            AgentExecutionLimiter executionLimiter,
            AgentSessionTurnScheduler sessionTurnScheduler,
            AgentSessionJournal sessionJournal
    ) {
        this(new RsAgentLoop(runtimeConfigurationService, toolUseExecutor, modelStreamClient, hookDispatcher, interrupter, executionLimiter),
                traceReporter,
                hotSessionStore,
                executionLimiter,
                sessionTurnScheduler,
                sessionJournal);
    }

    @Autowired
    public void setRecommendationService(AgentRecommendationService recommendationService) {
        this.recommendationService = recommendationService;
    }

    @Autowired
    public void setDirectRecommendation(AgentDirectRecommendation directRecommendation) {
        this.directRecommendation = directRecommendation;
    }

    @Autowired
    public void setObservation(AgentTurnObservation observation) { this.observation = observation; }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentTraceReporter traceReporter
    ) {
        this(
                modelStreamClient,
                toolUseExecutor,
                runtimeConfigurationService,
                traceReporter,
                new NoopAgentLoopHookDispatcher(),
                new InMemoryAgentInterrupter(),
                new InMemoryAgentHotSessionStore(),
                null,
                null,
                null
        );
    }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService
    ) {
        this(modelStreamClient, toolUseExecutor, runtimeConfigurationService, event -> {
        });
    }

    public InMemoryAgentOrchestrationService(AgentLoop agentLoop) {
        this(agentLoop, event -> {
        });
    }

    public InMemoryAgentOrchestrationService(AgentLoop agentLoop, AgentTraceReporter traceReporter) {
        this(agentLoop, traceReporter, new InMemoryAgentHotSessionStore());
    }

    public InMemoryAgentOrchestrationService(
            AgentLoop agentLoop,
            AgentTraceReporter traceReporter,
            AgentHotSessionStore hotSessionStore
    ) {
        this(
                agentLoop,
                traceReporter,
                hotSessionStore,
                new AgentExecutionLimiter(new AgentExecutionProperties()),
                new InMemoryAgentSessionTurnScheduler(new AgentExecutionProperties())
        );
    }

    public InMemoryAgentOrchestrationService(
            AgentLoop agentLoop,
            AgentTraceReporter traceReporter,
            AgentHotSessionStore hotSessionStore,
            AgentExecutionLimiter executionLimiter,
            AgentSessionTurnScheduler sessionTurnScheduler
    ) {
        this(agentLoop, traceReporter, hotSessionStore, executionLimiter, sessionTurnScheduler, null);
    }

    public InMemoryAgentOrchestrationService(
            AgentLoop agentLoop,
            AgentTraceReporter traceReporter,
            AgentHotSessionStore hotSessionStore,
            AgentExecutionLimiter executionLimiter,
            AgentSessionTurnScheduler sessionTurnScheduler,
            AgentSessionJournal sessionJournal
    ) {
        this.agentLoop = agentLoop;
        this.traceReporter = traceReporter == null ? event -> {
        } : traceReporter;
        AgentHotSessionStore resolvedHotSessionStore = hotSessionStore == null
                ? new InMemoryAgentHotSessionStore()
                : hotSessionStore;
        this.hotSessionStore = resolvedHotSessionStore;
        AgentExecutionProperties defaultProperties = new AgentExecutionProperties();
        this.executionLimiter = executionLimiter == null ? new AgentExecutionLimiter(defaultProperties) : executionLimiter;
        this.sessionTurnScheduler = sessionTurnScheduler == null
                ? new InMemoryAgentSessionTurnScheduler(defaultProperties)
                : sessionTurnScheduler;
        this.sessionJournal = sessionJournal == null
                ? new DefaultAgentSessionJournal(
                        new InMemoryAgentTranscriptEntryStore(),
                        new NoopAgentSessionProjectionStore(),
                        resolvedHotSessionStore
                )
                : sessionJournal;
    }

    @Override
    public AgentChatVO chat(AgentChatRequestDTO request) {
        long receivedNanos = System.nanoTime();
        AtomicReference<AgentChatVO> response = new AtomicReference<>();
        try (var timing = observation.start(receivedNanos)) {
            sessionTurnScheduler.runExclusive(request.sessionId(), () -> {
                claimSessionOwnership(request);
                executionLimiter.runWithActiveLoop(() -> response.set(executeTurn(request, event -> { }, timing)));
            });
        }
        return response.get();
    }

    @Override
    public void streamChat(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer) {
        long receivedNanos = System.nanoTime();
        try (var timing = observation.start(receivedNanos)) {
            sessionTurnScheduler.runExclusive(request.sessionId(), () -> {
                claimSessionOwnership(request);
                executionLimiter.runWithActiveLoop(() -> executeTurn(request, consumer, timing));
            });
        }
    }

    private AgentChatVO executeTurn(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer, AgentTurnObservation.Timing timing) {
        timing.record("admission", timing.receivedNanos());
        return executeObservedTurn(request, consumer, timing);
    }

    private AgentChatVO executeObservedTurn(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer,
                                          AgentTurnObservation.Timing timing) {
        long restoreStarted = System.nanoTime();
        String clientTurnId = stringValue(request.resolvedContext().get("client_turn_id"));
        String requestId = clientTurnId.isBlank() ? "agent_req_" + UUID.randomUUID().toString().substring(0, 8)
                : "agent_req_" + UUID.nameUUIDFromBytes((request.sessionId() + ":" + clientTurnId)
                        .getBytes(java.nio.charset.StandardCharsets.UTF_8)).toString().replace("-", "");
        if (!clientTurnId.isBlank() && !clientTurnId.matches("[A-Za-z0-9_-]{1,80}")) {
            throw new IllegalArgumentException("invalid client_turn_id");
        }
        var turnTranscript = clientTurnId.isBlank() ? null : sessionJournal.transcript(request.sessionId());
        if (turnTranscript != null) {
            var previous = turnTranscript.stream()
                    .filter(entry -> requestId.equals(entry.requestId())).toList();
            if (!previous.isEmpty()) {
                var user = previous.stream().filter(entry -> "USER_MESSAGE".equals(entry.entryType())).findFirst().orElseThrow();
                if (!request.userMessage().equals(user.payload().get("content"))) {
                    throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,
                            "client_turn_id already belongs to a different message");
                }
                var completed = previous.stream().filter(entry -> "ASSISTANT_FINAL".equals(entry.entryType()))
                        .filter(entry -> entry.payload().get("public_response") instanceof Map).findFirst();
                if (completed.isPresent()) {
                    AgentChatVO cached = responseMapper.convertValue(completed.get().payload().get("public_response"), AgentChatVO.class);
                    consumer.accept(new AgentStreamEventVO("done", requestId, Map.of("done", true,
                            "finish_reason", completed.get().payload().get("finish_reason"),
                            "response", completed.get().payload().get("public_response"))));
                    timing.route("replay");
                    if ("FINAL_ANSWER".equals(completed.get().payload().get("finish_reason"))) timing.success();
                    return cached;
                }
                throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,
                        "Turn has no confirmed final answer; inspect history before starting a new Turn");
            }
        }
        sessionAdmission.admit(request);
        var effectiveContext = new AgentEffectiveContextService(transcriptRecovery != null ? transcriptRecovery
                : id -> new com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript(id, "", 0, List.of(), List.of(), sessionJournal.transcript(id)))
                .recover(request.sessionId(), turnTranscript);
        var directPlan = directRecommendation != null && directRecommendation.enabled()
                ? directRecommendation.prepare(request,
                        (turnTranscript != null ? turnTranscript.isEmpty() : sessionJournal.latest(request.sessionId()).isEmpty())
                                && effectiveContext.get("messages") instanceof List<?> messages && messages.isEmpty()
                                && "".equals(effectiveContext.get("checkpoint_id"))
                                && !Boolean.TRUE.equals(effectiveContext.get("truncated")),
                        agentLoop.supportsDirectRecommendation())
                : java.util.Optional.<AgentDirectRecommendation.Plan>empty();
        timing.record("restore_and_routing", restoreStarted);
        long recommendStarted = System.nanoTime();
        var recommendationDelivery = executionLimiter.callWithRecommendationPermit(() ->
                recommendationService.recommendDelivery(directPlan.map(
                        AgentDirectRecommendation.Plan::request).orElse(request)));
        timing.record("recommendation", recommendStarted);
        List<AgentRecommendedItemVO> recommendations = recommendationDelivery.items().stream()
                .limit(request.resolvedLimit())
                .toList();
        int limit = recommendations.size();
        List<String> recommendedItemIds = recommendations.stream()
                .map(AgentRecommendedItemVO::itemId)
                .toList();
        List<AgentToolCallVO> toolCalls = new ArrayList<>();
        var previousView = turnTranscript == null ? recoverSession(request.sessionId())
                : recoverSession(request.sessionId(), turnTranscript);
        var previousTurns = previousView == null ? List.<AgentTurnVO>of() : previousView.turns();
        var turnStart = new AgentSessionJournal.TurnStart(
                request.sessionId(),
                requestId,
                request.profileUserId(),
                request.userMessage(),
                request.resolvedContext()
        );
        AgentSessionJournal.Turn journalTurn = turnTranscript == null ? sessionJournal.beginTurn(turnStart)
                : sessionJournal.beginTurn(turnStart, turnTranscript);
        var groundedContext = new java.util.LinkedHashMap<String, Object>(request.resolvedContext());
        directPlan.ifPresent(plan -> {
            if (plan.request().resolvedContext().containsKey("constraints"))
                groundedContext.put("constraints", plan.request().resolvedContext().get("constraints"));
        });
        groundedContext.put("session_effective_context", effectiveContext);
        if (Boolean.TRUE.equals(effectiveContext.get("truncated"))) {
            journalTurn.append("CONTEXT_TRUNCATED", "system", Map.of("character_budget", effectiveContext.get("character_budget"),
                    "omitted_message_count", effectiveContext.get("omitted_message_count"), "checkpoint_id", effectiveContext.get("checkpoint_id")));
            groundedContext.put("context_recovery_notice", "早期上下文已按预算裁剪。信息不足时澄清，不推测缺失需求。");
        }
        groundedContext.put("recommendation_items", recommendations);
        if (!recommendationDelivery.degradationReasons().isEmpty()) {
            groundedContext.put("recommendation_degradation_reasons", recommendationDelivery.degradationReasons());
            groundedContext.put("recommendation_degradation_notice", "推荐能力降级。仅根据已有候选提供建议；候选为空时询问需求或提供一般选购建议，不编造商品、库存、价格或已完成检索。");
        }
        directPlan.ifPresent(plan -> directRecommendation.synthesisContext(plan, recommendationDelivery).ifPresent(context -> {
            groundedContext.putAll(context);
            timing.route("llm_recommendation_synthesis");
        }));
        AgentChatRequestDTO groundedRequest = new AgentChatRequestDTO(request.sessionId(), request.profileUserId(),
                request.userMessage(), request.resolvedLimit(), groundedContext);
        AgentChatRequestDTO loopRequest = withTurnRequestId(withHotSessionContext(groundedRequest), requestId);

        for (AgentToolCallVO toolCall : toolCalls(limit, request.resolvedContext())) {
            toolCalls.add(toolCall);
        }

        AtomicBoolean startedReported = new AtomicBoolean(false);
        AtomicReference<AgentStreamEventVO> completedEvent = new AtomicReference<>();
        List<Map<String, Object>> answerBlocks = new ArrayList<>();
        AgentLoopResult loopResult;
        long answerStarted = System.nanoTime();
        try {
            Consumer<AgentStreamEventVO> eventConsumer = event -> {
            reportStartedOnce(request, event.requestId(), startedReported);
            appendSemanticStreamEvent(journalTurn, event);
            reportStreamEvent(request, event);
            if ("answer_block".equals(event.event())) {
                answerBlocks.add(new com.sinrotic.rs.agent.service.PublicAgentStreamProjector()
                        .project(event).orElseThrow().data());
            }
            if ("done".equals(event.event())) {
                completedEvent.set(event);
                return;
            }
            consumer.accept(event);
            };
            Runnable onReady = () -> toolCalls.forEach(toolCall -> consumer.accept(toolTraceEvent(requestId, toolCall)));
            if (directPlan.isPresent()) {
                loopResult = agentLoop.run(loopRequest, eventConsumer, onReady, ignored -> {
                    var answer = directRecommendation.answer(directPlan.get(), recommendationDelivery);
                    if (answer.isPresent()) timing.route("direct_recommendation");
                    return answer;
                });
            } else {
                loopResult = agentLoop.run(loopRequest, eventConsumer, onReady);
            }
        } catch (RuntimeException failed) {
            String failureMessage = "本轮未完成。可以重新发送需求开启新一轮对话。";
            var failedEntry = journalTurn.append("TURN_FAILED", "assistant", Map.of(
                    "finish_reason", "MODEL_ERROR", "assistant_message", failureMessage,
                    "degradation_reasons", recommendationDelivery.degradationReasons()));
            cacheTurn(request, failedEntry.seq(), previousTurns, new AgentTurnVO(requestId, request.userMessage(), failureMessage,
                    List.of(), List.of(), List.of(), "MODEL_ERROR", "", recommendationDelivery.degradationReasons()));
            observeCompleted(groundedRequest, new AgentTurnVO(requestId, request.userMessage(), failureMessage,
                    List.of(), List.of(), List.of(), "MODEL_ERROR", "", recommendationDelivery.degradationReasons()), previousTurns);
            reportTraceEvent(request, requestId, "agent_failed", Map.of("status", "FAILED", "error_code", "TURN_FAILED"), "", "");
            throw failed;
        }
        timing.record("answer", answerStarted);
        long finalizeStarted = System.nanoTime();
        toolCalls.addAll(loopResult.toolCalls());

        AgentTurnVO turn = new AgentTurnVO(
                loopResult.requestId(),
                request.userMessage(),
                loopResult.assistantMessage(),
                toolCalls,
                recommendedItemIds,
                List.copyOf(answerBlocks), loopResult.finishReason().name(),
                recommendations.isEmpty() ? "" : recommendations.getFirst().cardSetId(), recommendationDelivery.degradationReasons()
        );
        AgentChatVO response = new AgentChatVO(loopResult.requestId(), request.sessionId(), request.profileUserId(),
                recommendations.isEmpty() ? "" : recommendations.getFirst().cardSetId(),
                previousTurns.size() + 1, loopResult.assistantMessage(), recommendations,
                List.copyOf(toolCalls), List.copyOf(answerBlocks), recommendationDelivery.degradationReasons());
        var publicResponse = new java.util.LinkedHashMap<String, Object>();
        publicResponse.put("request_id", response.requestId()); publicResponse.put("session_id", response.sessionId());
        publicResponse.put("profile_user_id", response.profileUserId()); publicResponse.put("card_set_id", response.cardSetId());
        publicResponse.put("turn_index", response.turnIndex()); publicResponse.put("assistant_message", response.assistantMessage());
        publicResponse.put("recommended_items", response.recommendedItems()); publicResponse.put("answer_blocks", response.answerBlocks());
        publicResponse.put("degradation_reasons", response.degradationReasons());
        var finalEntry = journalTurn.append("ASSISTANT_FINAL", "assistant", Map.of(
                "assistant_message", stringValue(loopResult.assistantMessage()),
                "finish_reason", loopResult.finishReason().name(),
                "recommended_item_ids", recommendedItemIds,
                "answer_blocks", List.copyOf(answerBlocks),
                "card_set_id", recommendations.isEmpty() ? "" : recommendations.getFirst().cardSetId(),
                "degradation_reasons", response.degradationReasons(),
                "public_response", responseMapper.convertValue(publicResponse, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {})
        ));
        cacheTurn(request, finalEntry.seq(), previousTurns, turn);
        storeTurnSnapshot(request, loopResult, recommendedItemIds);
        observeCompleted(groundedRequest, turn, previousTurns);
        emitTurnCompleted(completedEvent.get(), loopResult, recommendedItemIds, response, consumer);
        timing.record("finalize", finalizeStarted);
        if (loopResult.finishReason() == AgentFinishReason.FINAL_ANSWER) timing.success();
        return response;
    }

    @Override
    public AgentSessionTraceVO sessionTurns(String sessionId) {
        SessionView view = recoverSession(sessionId);
        return new AgentSessionTraceVO(sessionId, view == null ? List.of() : view.turns());
    }

    @Override
    public AgentSessionTraceVO sessionTurns(String sessionId, String profileUserId) {
        SessionView view = recoverSession(sessionId);
        if (view == null || profileUserId == null || !profileUserId.equals(view.owner())) {
            throw new AgentSessionNotFoundException();
        }
        return new AgentSessionTraceVO(sessionId, view.turns());
    }

    @Override
    public AgentSessionTraceVO platformSessionTrace(String sessionId) {
        return sessionTurns(sessionId);
    }

    @Override
    public AgentSessionTraceVO sessionTurns(String sessionId, String profileUserId, String accountId) {
        if (accountId == null || accountId.isBlank()) throw new AgentSessionNotFoundException();
        SessionView view = recoverSession(sessionId);
        if (view == null || profileUserId == null || !profileUserId.equals(view.owner())
                || (!view.account().isBlank() && !accountId.equals(view.account()))) throw new AgentSessionNotFoundException();
        // 老历史可能没有 Account 字段，读取 User 的归属视图校验，不刷新聊天活动时间。
        sessionAdmission.verifyOwner(accountId, profileUserId, sessionId);
        return new AgentSessionTraceVO(sessionId, view.turns());
    }

    private void claimSessionOwnership(AgentChatRequestDTO request) {
        String profileUserId = request.profileUserId();
        if (profileUserId == null || profileUserId.isBlank()) {
            throw new AgentSessionNotFoundException();
        }
        SessionView view = recoverSession(request.sessionId());
        if (view != null && !view.owner().equals(profileUserId)) {
            throw new AgentSessionNotFoundException();
        }
        String accountId = stringValue(request.resolvedContext().get("authenticated_account_id"));
        if (view != null && !view.account().isBlank() && !view.account().equals(accountId)) {
            throw new AgentSessionNotFoundException();
        }
        if (view != null && view.account().isBlank()) {
            sessionAdmission.verifyOwner(accountId, profileUserId, request.sessionId());
        }
    }

    private SessionView recoverSession(String sessionId) {
        var latest = sessionJournal.latest(sessionId);
        if (latest.isEmpty()) return null;
        var cached = sessionViews.getIfPresent(sessionId);
        if (cached != null && cached.seq() == latest.get().seq()) return cached;
        var entries = sessionJournal.transcript(sessionId);
        return recoverSession(sessionId, entries);
    }

    private SessionView recoverSession(String sessionId,
            List<com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry> entries) {
        if (entries.isEmpty()) return null;
        var cached = sessionViews.getIfPresent(sessionId);
        if (cached != null && cached.seq() == entries.getLast().seq()) return cached;
        var firstUser = entries.stream().filter(entry -> "USER_MESSAGE".equals(entry.entryType()))
                .findFirst().orElseThrow(AgentSessionNotFoundException::new);
        String owner = stringValue(firstUser.payload().get("profile_user_id"));
        if (owner.isBlank()) throw new AgentSessionNotFoundException();
        String account = firstUser.payload().get("context") instanceof Map<?, ?> context
                ? stringValue(context.get("authenticated_account_id")) : "";
        var recovered = new ArrayList<AgentTurnVO>();
        Map<String, String> messages = new java.util.HashMap<>();
        for (var entry : entries) {
            if ("USER_MESSAGE".equals(entry.entryType())) {
                messages.put(entry.requestId(), stringValue(entry.payload().get("content")));
            } else if ("ASSISTANT_FINAL".equals(entry.entryType()) || "TURN_FAILED".equals(entry.entryType())) {
                Object itemIds = entry.payload().get("recommended_item_ids");
                List<String> ids = itemIds instanceof List<?> list ? list.stream().map(String::valueOf).toList() : List.of();
                Object rawBlocks = entry.payload().get("answer_blocks");
                List<Map<String, Object>> blocks = rawBlocks instanceof List<?> list
                        ? list.stream().filter(Map.class::isInstance).map(value -> {
                            Map<String, Object> block = new java.util.LinkedHashMap<>();
                            ((Map<?, ?>) value).forEach((key, item) -> { if (key instanceof String name && item != null) block.put(name, item); });
                            return new com.sinrotic.rs.agent.service.PublicAgentStreamProjector().project(
                                    new AgentStreamEventVO("answer_block", entry.requestId(), block)).orElseThrow().data();
                        }).toList() : List.of();
                recovered.add(new AgentTurnVO(entry.requestId(), messages.getOrDefault(entry.requestId(), ""),
                        stringValue(entry.payload().get("assistant_message")), List.of(), ids, blocks,
                        stringValue(entry.payload().getOrDefault("finish_reason", "FINAL_ANSWER")),
                        stringValue(entry.payload().get("card_set_id")),
                        com.sinrotic.rs.agent.service.AgentRecommendationDelivery.publicReasons(entry.payload().get("degradation_reasons"))));
            }
        }
        SessionView view = new SessionView(owner, account, entries.getLast().seq(), recovered);
        sessionViews.put(sessionId, view);
        return view;
    }

    private void cacheTurn(AgentChatRequestDTO request, long seq, List<AgentTurnVO> previous, AgentTurnVO turn) {
        var turns = new ArrayList<>(previous); turns.add(turn);
        sessionViews.put(request.sessionId(), new SessionView(request.profileUserId(),
                stringValue(request.resolvedContext().get("authenticated_account_id")), seq, turns));
    }

    private List<AgentToolCallVO> toolCalls(int limit, Map<String, Object> context) {
        return List.of(
                new AgentToolCallVO(
                        "recommend_candidates",
                        "rs-service-recommend",
                        "SUCCESS",
                        Map.of("limit", limit, "scene", context.getOrDefault("scene", "agent_chat"))
                )
        );
    }

    private AgentStreamEventVO toolTraceEvent(String requestId, AgentToolCallVO toolCall) {
        return new AgentStreamEventVO("trace", requestId, Map.of(
                "tool_call_id", toolCall.toolCallId(),
                "tool_name", toolCall.toolName(),
                "service", toolCall.service(),
                "status", toolCall.status(),
                "metadata", toolCall.metadata()
        ));
    }

    private void reportStartedOnce(AgentChatRequestDTO request, String requestId, AtomicBoolean startedReported) {
        if (startedReported.compareAndSet(false, true)) {
            reportTraceEvent(request, requestId, "agent_started", Map.of(), null, null);
        }
    }

    private AgentChatRequestDTO withHotSessionContext(AgentChatRequestDTO request) {
        return hotSessionStore.latestSnapshot(request.sessionId())
                .map(snapshot -> {
                    Map<String, Object> mergedContext = new java.util.LinkedHashMap<>(request.resolvedContext());
                    mergedContext.put("session_hot_context", snapshot.summaryPayload());
                    mergedContext.put("session_hot_snapshot_id", snapshot.snapshotId());
                    return new AgentChatRequestDTO(
                            request.sessionId(),
                            request.profileUserId(),
                            request.userMessage(),
                            request.limit(),
                            Map.copyOf(mergedContext)
                    );
                })
                .orElse(request);
    }

    private void appendSemanticStreamEvent(AgentSessionJournal.Turn turn, AgentStreamEventVO event) {
        switch (event.event()) {
            case "tool_use" -> turn.append("TOOL_USE", "assistant", event.data());
            case "tool_result" -> turn.append("TOOL_RESULT", "tool", event.data());
            case "answer_block" -> turn.append("ASSISTANT_MESSAGE", "assistant", event.data());
            default -> {
                // Token deltas, usage, trace, and done are transport/runtime events, not durable semantic events.
            }
        }
    }

    private AgentChatRequestDTO withTurnRequestId(AgentChatRequestDTO request, String requestId) {
        Map<String, Object> context = new java.util.LinkedHashMap<>(request.resolvedContext());
        context.put(AgentLoop.INTERNAL_REQUEST_ID_CONTEXT_KEY, requestId);
        return new AgentChatRequestDTO(
                request.sessionId(),
                request.profileUserId(),
                request.userMessage(),
                request.limit(),
                Map.copyOf(context)
        );
    }

    private void emitTurnCompleted(
            AgentStreamEventVO completedEvent,
            AgentLoopResult loopResult,
            List<String> recommendedItemIds,
            AgentChatVO response,
            Consumer<AgentStreamEventVO> consumer
    ) {
        Map<String, Object> doneData = new java.util.LinkedHashMap<>();
        if (completedEvent != null) {
            doneData.putAll(completedEvent.data());
        }
        doneData.put("done", true);
        doneData.put("recommended_item_ids", recommendedItemIds);
        doneData.put("response", Map.of(
                "request_id", response.requestId(), "session_id", response.sessionId(),
                "profile_user_id", response.profileUserId(), "card_set_id", response.cardSetId(),
                "turn_index", response.turnIndex(), "assistant_message", response.assistantMessage(),
                "recommended_items", response.recommendedItems(), "answer_blocks", response.answerBlocks(),
                "degradation_reasons", response.degradationReasons()));
        consumer.accept(new AgentStreamEventVO("done", loopResult.requestId(), Map.copyOf(doneData)));
    }

    private void storeTurnSnapshot(
            AgentChatRequestDTO request,
            AgentLoopResult loopResult,
            List<String> recommendedItemIds
    ) {
        List<AgentSessionEvent> events = hotSessionStore.events(request.sessionId());
        String compactBeforeEventId = events.isEmpty() ? "" : events.getLast().eventId();
        hotSessionStore.storeSnapshot(new AgentSessionSnapshot(
                "snapshot_" + UUID.randomUUID().toString().substring(0, 8),
                request.sessionId(),
                "turn_" + loopResult.requestId(),
                compactBeforeEventId,
                events.size(),
                sourceTokenCount(events),
                Map.of(
                        "last_request_id", loopResult.requestId(),
                        "last_user_message", stringValue(request.userMessage()),
                        "last_assistant_message", stringValue(loopResult.assistantMessage()),
                        "recommended_item_ids", recommendedItemIds,
                        "last_active_time", Instant.now().toString()
                ),
                Instant.now()
        ));
    }

    private int sourceTokenCount(List<AgentSessionEvent> events) {
        int total = 0;
        for (AgentSessionEvent event : events) {
            Object value = event.payload().get("token_count");
            if (value instanceof Number number) {
                total += number.intValue();
            }
        }
        return total;
    }

    private void reportStreamEvent(AgentChatRequestDTO request, AgentStreamEventVO event) {
        String eventType = "done".equals(event.event()) ? "agent_done" : event.event();
        reportTraceEvent(request, event.requestId(), eventType, event.data(), stringValue(event.data().get("tool_call_id")),
                stringValue(event.data().get("tool_name")));
    }

    private void reportTraceEvent(
            AgentChatRequestDTO request,
            String requestId,
            String eventType,
            Map<String, Object> data,
            String toolCallId,
            String toolName
    ) {
        Map<String, Object> traceData = publicTraceMetadata(request, eventType, data);
        traceReporter.report(new AgentTraceEventVO(
                "evt_" + UUID.randomUUID().toString().substring(0, 8),
                request.sessionId(),
                requestId,
                eventType,
                toolCallId,
                toolName,
                "rs_agent",
                stringValue(request.resolvedContext().getOrDefault("model_provider", "spring_ai")),
                stringValue(request.resolvedContext().getOrDefault("model_name", "")),
                longValue(traceData.get("latency_ms")),
                integerValue(traceData.get("prompt_tokens")),
                integerValue(traceData.get("completion_tokens")),
                integerValue(traceData.get("total_tokens")),
                longValue(traceData.get("cache_read_input_tokens")),
                longValue(traceData.get("cache_write_input_tokens")),
                inferPhase(eventType, toolName),
                inferStatus(eventType, traceData),
                stringValue(traceData.get("error_code")),
                stringValue(traceData.get("error_message")),
                inputSummary(traceData),
                outputSummary(traceData),
                traceData,
                java.time.Instant.now()
        ));
    }

    private Map<String, Object> publicTraceMetadata(
            AgentChatRequestDTO request,
            String eventType,
            Map<String, Object> data
    ) {
        if (!"answer_block".equals(eventType)) {
            return Map.copyOf(data);
        }
        Map<String, Object> safe = new java.util.LinkedHashMap<>();
        for (String key : List.of(
                "status", "error_code", "error_message", "latency_ms", "prompt_tokens",
                "completion_tokens", "total_tokens", "cache_read_input_tokens", "cache_write_input_tokens",
                "capability_id"
        )) {
            Object value = data.get(key);
            if (value != null) {
                safe.put(key, value);
            }
        }
        Object profileId = data.containsKey("profile_id")
                ? data.get("profile_id")
                : request.resolvedContext().get("agent_profile_id");
        if (profileId instanceof String value && !value.isBlank()) {
            safe.put("profile_id", value);
        }
        safe.put("projection_result", "allowed");
        Object type = data.get("type");
        if (type instanceof String value && !value.isBlank()) {
            safe.put("output_block_type", value);
        }
        return Map.copyOf(safe);
    }

    private String inferPhase(String eventType, String toolName) {
        if (hasText(toolName)) {
            String normalizedToolName = toolName.toLowerCase(Locale.ROOT);
            if (normalizedToolName.contains("rag")) {
                return "rag";
            }
            if (normalizedToolName.contains("recommend")) {
                return "recommend";
            }
            return "tool_call";
        }

        String normalizedEventType = stringValue(eventType).toLowerCase(Locale.ROOT);
        if (normalizedEventType.contains("model")) {
            return "model_call";
        }
        if (normalizedEventType.contains("done") || normalizedEventType.contains("final")) {
            return "final_answer";
        }
        return "agent";
    }

    private String inferStatus(String eventType, Map<String, Object> data) {
        String dataStatus = stringValue(data.get("status"));
        if (isErrorStatus(dataStatus)
                || hasText(stringValue(data.get("error_code")))
                || hasText(stringValue(data.get("error_message")))
                || stringValue(eventType).toLowerCase(Locale.ROOT).contains("error")) {
            return "error";
        }
        return "success";
    }

    private boolean isErrorStatus(String status) {
        return "ERROR".equalsIgnoreCase(status) || "FAILED".equalsIgnoreCase(status);
    }

    private String inputSummary(Map<String, Object> data) {
        if (data.containsKey("query")) {
            return "query=" + stringValue(data.get("query"));
        }
        if (data.containsKey("tool_arguments")) {
            return truncate(stringValue(data.get("tool_arguments")));
        }
        return "";
    }

    private String outputSummary(Map<String, Object> data) {
        if (data.containsKey("output_summary")) {
            return truncate(stringValue(data.get("output_summary")));
        }
        if (data.containsKey("status")) {
            return "status=" + stringValue(data.get("status"));
        }
        return "";
    }

    private String truncate(String value) {
        return value.length() <= 240 ? value : value.substring(0, 240);
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private Integer integerValue(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Integer.parseInt(text);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private Long longValue(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Long.parseLong(text);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

}
