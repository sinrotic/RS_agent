package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentExecutionLimiter;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolResultStore;

import java.util.Map;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;

public class VirtualThreadAgentToolUseExecutor implements AgentToolUseExecutor, AutoCloseable {

    private final ExecutorService executorService;

    private final Function<AgentModelStreamEvent, Map<String, Object>> toolHandler;

    private final AgentToolResultStore toolResultStore;

    private final AgentToolResultExternalizer toolResultExternalizer;

    private final AgentExecutionLimiter executionLimiter;

    public VirtualThreadAgentToolUseExecutor() {
        this(event -> Map.of(
                "status", "SUCCESS",
                "tool_name", event.toolName(),
                "arguments", event.arguments(),
                "thread_virtual", Thread.currentThread().isVirtual()
        ));
    }

    public VirtualThreadAgentToolUseExecutor(AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(runtimeConfigurationService, (TriFunction<String, String, Map<String, Object>, Map<String, Object>>) (requestId, agentName, arguments) -> Map.of(
                "status", "SUCCESS",
                "agent_name", agentName,
                "arguments", arguments
        ), new InMemoryAgentToolResultStore());
    }

    public VirtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentDelegateService agentDelegateService,
            AgentToolResultStore toolResultStore,
            AgentExecutionLimiter executionLimiter
    ) {
        this(runtimeConfigurationService, (TriFunction<String, String, Map<String, Object>, Map<String, Object>>) agentDelegateService::callAgent, toolResultStore, executionLimiter);
    }

    public VirtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentDelegateService agentDelegateService
    ) {
        this(runtimeConfigurationService, (TriFunction<String, String, Map<String, Object>, Map<String, Object>>) agentDelegateService::callAgent, new InMemoryAgentToolResultStore());
    }

    public VirtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            TriFunction<String, String, Map<String, Object>, Map<String, Object>> agentCaller,
            AgentToolResultStore toolResultStore
    ) {
        this(runtimeConfigurationService, agentCaller, toolResultStore, null);
    }

    public VirtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            TriFunction<String, String, Map<String, Object>, Map<String, Object>> agentCaller,
            AgentToolResultStore toolResultStore,
            AgentExecutionLimiter executionLimiter
    ) {
        this.executorService = Executors.newVirtualThreadPerTaskExecutor();
        this.toolResultStore = toolResultStore == null ? new InMemoryAgentToolResultStore() : toolResultStore;
        this.toolResultExternalizer = new AgentToolResultExternalizer(this.toolResultStore);
        this.executionLimiter = executionLimiter;
        this.toolHandler = event -> {
            if ("load_skill".equals(event.toolName())) {
                String skillName = String.valueOf(event.arguments().getOrDefault("skill_name", ""));
                var skill = runtimeConfigurationService.skill(skillName);
                if (!skill.enabled()) {
                    return Map.of("status", "FAILED", "error_code", "SKILL_DISABLED", "loaded", false,
                            "error_message", "Skill is disabled");
                }
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "skill",
                        "tool_name", event.toolName(),
                        "skill_name", skill.name(),
                        "loaded", true,
                        "description", skill.description(),
                        "content", skill.content(),
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            if ("render_product_cards".equals(event.toolName())) {
                List<?> itemIds = event.arguments().get("item_ids") instanceof List<?> values ? values : List.of();
                String layout = String.valueOf(event.arguments().getOrDefault("layout", "inline"));
                List<Map<String, Object>> cards = itemIds.stream()
                        .map(itemId -> Map.of(
                                "item_id", itemId,
                                "title", String.valueOf(itemId),
                                "reason", "Prepared for recommendation display."
                        ))
                        .toList();
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "presentation",
                        "tool_name", event.toolName(),
                        "card_set_id", "cards_" + Integer.toHexString(itemIds.hashCode()),
                        "layout", layout,
                        "cards", cards,
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            if ("call_agent".equals(event.toolName())) {
                String agentName = String.valueOf(event.arguments().getOrDefault("agent_name", ""));
                Map<String, Object> result = agentCaller.apply("", agentName, event.arguments());
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "agent",
                        "tool_name", event.toolName(),
                        "agent_name", agentName,
                        "result", result,
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            if ("rag_support".equals(event.toolName()) || "rag_evidence_search".equals(event.toolName())) {
                Map<String, Object> result = agentCaller.apply("", "rag_agent", event.arguments());
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "recommend_rag",
                        "tool_name", event.toolName(),
                        "agent_name", "rag_agent",
                        "result", result,
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            if ("read_tool_result_lines".equals(event.toolName())) {
                String resultRef = String.valueOf(event.arguments().getOrDefault("result_ref", ""));
                int offset = intArgument(event.arguments().get("offset"), 0);
                int limit = intArgument(event.arguments().get("limit"), 20);
                var segment = this.toolResultStore.readLines(resultRef, offset, limit);
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "tool_result_lines",
                        "tool_name", event.toolName(),
                        "result_ref", segment.resultRef(),
                        "offset", segment.offset(),
                        "limit", segment.limit(),
                        "total_lines", segment.totalLines(),
                        "has_more", segment.hasMore(),
                        "lines", segment.lines(),
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            return Map.of(
                    "status", "SUCCESS",
                    "tool_name", event.toolName(),
                    "arguments", event.arguments(),
                    "thread_virtual", Thread.currentThread().isVirtual()
            );
        };
    }

    private static int intArgument(Object value, int fallback) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            return Integer.parseInt(text);
        }
        return fallback;
    }

    @FunctionalInterface
    public interface TriFunction<A, B, C, R> {
        R apply(A first, B second, C third);
    }

    public VirtualThreadAgentToolUseExecutor(Function<AgentModelStreamEvent, Map<String, Object>> toolHandler) {
        this(toolHandler, new InMemoryAgentToolResultStore());
    }

    public VirtualThreadAgentToolUseExecutor(Function<AgentModelStreamEvent, Map<String, Object>> toolHandler, AgentToolResultStore toolResultStore) {
        this.executorService = Executors.newVirtualThreadPerTaskExecutor();
        this.toolHandler = toolHandler;
        this.toolResultStore = toolResultStore == null ? new InMemoryAgentToolResultStore() : toolResultStore;
        this.toolResultExternalizer = new AgentToolResultExternalizer(this.toolResultStore);
        this.executionLimiter = null;
    }

    @Override
    public CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event) {
        return execute(event, toolHandler);
    }

    // 能力注册器与内部工具共用同一执行资源、并发许可和可中断 Future。
    CompletableFuture<Map<String, Object>> execute(
            AgentModelStreamEvent event,
            Function<AgentModelStreamEvent, Map<String, Object>> handler
    ) {
        InterruptibleCompletableFuture<Map<String, Object>> result = new InterruptibleCompletableFuture<>();
        Future<?> task = executorService.submit(() -> {
            try {
                if (!result.isCancelled()) {
                    result.complete(executeWithPermit(event, handler));
                }
            } catch (Throwable error) {
                result.completeExceptionally(error);
            } finally {
                result.markTaskFinished();
            }
        });
        result.attach(task);
        return result;
    }

    private Map<String, Object> executeWithPermit(
            AgentModelStreamEvent event,
            Function<AgentModelStreamEvent, Map<String, Object>> handler
    ) {
        if (executionLimiter == null) {
            return toolResultExternalizer.externalizeLargeNestedResult(event, handler.apply(event));
        }
        return executionLimiter.callWithToolPermit(
                () -> toolResultExternalizer.externalizeLargeNestedResult(event, handler.apply(event))
        );
    }

    CompletableFuture<Map<String, Object>> executeRecommendation(
            AgentModelStreamEvent event,
            Function<AgentModelStreamEvent, Map<String, Object>> handler
    ) {
        return execute(event, current -> executionLimiter == null ? handler.apply(current)
                : executionLimiter.callWithRecommendationPermit(() -> handler.apply(current)));
    }

    @Override
    public void close() {
        executorService.close();
    }

    private static class InterruptibleCompletableFuture<T> extends CompletableFuture<T> {

        private final AtomicReference<Future<?>> task = new AtomicReference<>();

        private final CountDownLatch taskFinished = new CountDownLatch(1);

        void attach(Future<?> task) {
            this.task.set(task);
            if (isCancelled()) {
                task.cancel(true);
                waitForTaskToObserveInterrupt();
            }
        }

        void markTaskFinished() {
            taskFinished.countDown();
        }

        @Override
        public boolean cancel(boolean mayInterruptIfRunning) {
            Future<?> currentTask = task.get();
            if (currentTask != null) {
                currentTask.cancel(mayInterruptIfRunning);
                if (mayInterruptIfRunning) {
                    waitForTaskToObserveInterrupt();
                }
            }
            return super.cancel(mayInterruptIfRunning);
        }

        private void waitForTaskToObserveInterrupt() {
            try {
                taskFinished.await(500, TimeUnit.MILLISECONDS);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
            }
        }
    }
}
