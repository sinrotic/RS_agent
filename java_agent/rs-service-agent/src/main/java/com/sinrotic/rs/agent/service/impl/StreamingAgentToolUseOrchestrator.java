package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.AgentToolUseOrchestrator;
import com.sinrotic.rs.agent.service.AgentToolUseResult;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;

@Service
public class StreamingAgentToolUseOrchestrator implements AgentToolUseOrchestrator {

    private static final Set<String> DEFAULT_CONCURRENT_SAFE_TOOLS = Set.of(
            "load_skill",
            "read_tool_result_lines",
            "rag_support",
            "rag_evidence_search",
            "recommend_candidates",
            "recommend_semantic_recall",
            "recommend_profile_pipeline",
            "recommend_cold_fallback",
            "recommend_rerank_candidates",
            "catalog_card",
            "render_product_cards",
            "model_chat"
    );

    private final AgentToolUseExecutor toolUseExecutor;

    private final Set<String> concurrentSafeTools;

    @Autowired
    public StreamingAgentToolUseOrchestrator(AgentToolUseExecutor toolUseExecutor) {
        this(toolUseExecutor, DEFAULT_CONCURRENT_SAFE_TOOLS);
    }

    public StreamingAgentToolUseOrchestrator(
            AgentToolUseExecutor toolUseExecutor,
            Set<String> concurrentSafeTools
    ) {
        this.toolUseExecutor = toolUseExecutor;
        this.concurrentSafeTools = concurrentSafeTools == null ? DEFAULT_CONCURRENT_SAFE_TOOLS : Set.copyOf(concurrentSafeTools);
    }

    @Override
    public Run start() {
        return new StreamingRun();
    }

    private boolean isConcurrentSafe(AgentModelStreamEvent event) {
        return concurrentSafeTools.contains(event.toolName());
    }

    private class StreamingRun implements AgentToolUseOrchestrator.Run {

        private final List<CompletableFuture<AgentToolUseResult>> resultFutures = new ArrayList<>();

        private final List<CompletableFuture<Map<String, Object>>> rawFutures = new CopyOnWriteArrayList<>();

        private final AtomicBoolean cancelled = new AtomicBoolean(false);

        private CompletableFuture<Void> serialBarrier = CompletableFuture.completedFuture(null);

        private CompletableFuture<Void> allSubmitted = CompletableFuture.completedFuture(null);

        @Override
        public synchronized void submit(String toolCallId, AgentModelStreamEvent event) {
            CompletableFuture<AgentToolUseResult> resultFuture;
            if (isConcurrentSafe(event)) {
                CompletableFuture<Void> startAfter = serialBarrier;
                resultFuture = startAfter.thenCompose(ignored -> execute(toolCallId, event));
                allSubmitted = CompletableFuture.allOf(allSubmitted, resultFuture);
            } else {
                CompletableFuture<Void> startAfter = allSubmitted;
                resultFuture = startAfter.thenCompose(ignored -> execute(toolCallId, event));
                serialBarrier = resultFuture.thenApply(ignored -> null);
                allSubmitted = serialBarrier;
            }
            resultFutures.add(resultFuture);
        }

        @Override
        public synchronized void complete(String toolCallId, AgentModelStreamEvent event, Map<String, Object> metadata) {
            CompletableFuture<AgentToolUseResult> resultFuture = CompletableFuture.completedFuture(new AgentToolUseResult(
                    toolCallId,
                    event,
                    metadata,
                    null
            ));
            resultFutures.add(resultFuture);
            allSubmitted = CompletableFuture.allOf(allSubmitted, resultFuture);
        }

        @Override
        public List<AgentToolUseResult> awaitResults() {
            List<CompletableFuture<AgentToolUseResult>> futures;
            synchronized (this) {
                futures = List.copyOf(resultFutures);
            }
            CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new)).join();
            return futures.stream()
                    .map(CompletableFuture::join)
                    .toList();
        }

        @Override
        public synchronized boolean hasSubmittedTools() {
            return !resultFutures.isEmpty();
        }

        @Override
        public void cancel() {
            cancelled.set(true);
            for (CompletableFuture<Map<String, Object>> future : rawFutures) {
                future.cancel(true);
            }
        }

        private CompletableFuture<AgentToolUseResult> execute(String toolCallId, AgentModelStreamEvent event) {
            if (cancelled.get()) {
                return CompletableFuture.completedFuture(new AgentToolUseResult(
                        toolCallId,
                        event,
                        Map.of(),
                        new CancellationException("interrupted")
                ));
            }
            CompletableFuture<Map<String, Object>> rawFuture = toolUseExecutor.execute(event);
            rawFutures.add(rawFuture);
            return rawFuture.handle((metadata, error) -> new AgentToolUseResult(
                    toolCallId,
                    event,
                    metadata,
                    error
            ));
        }
    }
}
