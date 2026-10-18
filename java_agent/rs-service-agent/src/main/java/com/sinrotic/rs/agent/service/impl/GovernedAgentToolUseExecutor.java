package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentToolGovernanceProperties;
import com.sinrotic.rs.agent.service.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Turn 内共享期限/次数/无进展状态，依赖间共享熔断；每次重试仍经过原授权执行器。 */
public final class GovernedAgentToolUseExecutor implements AgentToolUseExecutor, AutoCloseable {
    private static final Set<String> INTERNAL_READS = Set.of("load_skill", "read_tool_result_lines", "render_product_cards");
    private static final Set<String> VOLATILE_FIELDS = Set.of("request_id", "tool_call_id", "trace_id", "span_id", "latency_ms", "thread_virtual", "governance");
    private final AgentToolUseExecutor delegate;
    private final AgentToolGovernanceProperties settings;
    private final AgentRuntimeConfigurationService runtime;
    private final AgentCapabilityRegistry registry;
    private final AgentToolCircuitBreaker circuits;
    private final ExecutorService coordinators = Executors.newVirtualThreadPerTaskExecutor();
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor(Thread.ofPlatform().daemon(true).name("agent-tool-deadline").factory());
    private final Set<Scope> scopes = ConcurrentHashMap.newKeySet();
    private final AtomicBoolean closed = new AtomicBoolean();

    public GovernedAgentToolUseExecutor(AgentToolUseExecutor delegate, AgentToolGovernanceProperties settings,
            AgentRuntimeConfigurationService runtime, AgentCapabilityRegistry registry) {
        this(delegate, settings, runtime, registry, new AgentToolCircuitBreaker(settings.getCircuitFailureThreshold(), settings.getCircuitOpenMs()));
    }
    public GovernedAgentToolUseExecutor(AgentToolUseExecutor delegate, AgentToolGovernanceProperties settings,
            AgentRuntimeConfigurationService runtime, AgentCapabilityRegistry registry, AgentToolCircuitBreaker circuits) {
        this.delegate = Objects.requireNonNull(delegate); this.settings = settings;
        this.runtime = runtime; this.registry = registry; this.circuits = circuits;
    }

    @Override public synchronized Turn openTurn(AgentInterruptContext context) {
        if (!settings.isEnabled()) return delegate.openTurn(context);
        if (closed.get()) throw new RejectedExecutionException("Tool executor is closed");
        var scope = new Scope(context); scopes.add(scope);
        try { scope.deadlineTask = timer.schedule(() -> {
            if (!scope.ended.get() && !closed.get()) {
                try { coordinators.execute(scope::expire); }
                catch (RejectedExecutionException ignored) { scope.close(); }
            }
        }, settings.getTurnTimeoutMs(), TimeUnit.MILLISECONDS); }
        catch (RejectedExecutionException shuttingDown) { scope.close(); throw shuttingDown; }
        context.onInterrupt(scope::cancelJobs);
        return scope;
    }

    @Override public CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event) {
        if (!settings.isEnabled()) return delegate.execute(event);
        var turn = openTurn(new AgentInterruptContext("tool_" + UUID.randomUUID(), ""));
        var result = turn.execute(event); result.whenComplete((value, error) -> turn.close()); return result;
    }

    private final class Scope implements Turn {
        final AgentInterruptContext context;
        final long started = System.nanoTime(), timeoutNanos = TimeUnit.MILLISECONDS.toNanos(settings.getTurnTimeoutMs());
        final AtomicInteger submissions = new AtomicInteger(), attempts = new AtomicInteger();
        final AtomicBoolean ended = new AtomicBoolean();
        final List<Job> jobs = new CopyOnWriteArrayList<>();
        final Map<String, Progress> progress = new HashMap<>();
        volatile ScheduledFuture<?> deadlineTask;
        Scope(AgentInterruptContext context) { this.context = context; }
        long remaining() { return Math.max(0, timeoutNanos - (System.nanoTime() - started)); }

        @Override public CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event) {
            if (ended.get() || context.interrupted()) return CompletableFuture.failedFuture(new CancellationException("Turn is closed"));
            if (submissions.incrementAndGet() > settings.getMaxAttemptsPerTurn())
                return CompletableFuture.completedFuture(failure("TOOL_BUDGET_EXHAUSTED", "Tool execution budget exhausted", "budget_exhausted", 0, started));
            var job = new Job(); jobs.add(job);
            try { job.attach(coordinators.submit(() -> {
                if (job.isDone() || ended.get() || context.interrupted()) { job.cancel(true); return; }
                try { job.complete(run(event, this, job)); }
                catch (RuntimeException failure) { job.completeExceptionally(failure); }
            })); }
            catch (RejectedExecutionException stopped) { job.completeExceptionally(stopped); }
            if (context.interrupted() || ended.get()) job.cancel(true);
            return job;
        }

        synchronized boolean blocked(String signature) {
            var value = progress.get(signature); return value != null && value.repetitions >= settings.getNoProgressLimit();
        }
        synchronized boolean recordProgress(String signature, Map<String, Object> result) {
            if (signature == null) return false;
            String digest;
            try { digest = AgentModelRequestFingerprint.sha256(stable(result)); }
            catch (RuntimeException notJson) { return false; }
            var old = progress.get(signature);
            var next = new Progress(digest, old != null && old.digest.equals(digest) ? old.repetitions + 1 : 1);
            progress.put(signature, next);
            return next.repetitions >= settings.getNoProgressLimit();
        }
        void cancelJobs() { for (var job : jobs) if (!job.isDone()) job.cancel(true); }
        synchronized void expire() { if (!ended.get()) context.interrupt("turn_timeout"); }
        @Override public synchronized void close() {
            if (!ended.compareAndSet(false, true)) return;
            var scheduled = deadlineTask; if (scheduled != null) scheduled.cancel(false);
            cancelJobs(); scopes.remove(this);
        }
    }

    private Map<String, Object> run(AgentModelStreamEvent event, Scope scope, Job job) {
        long started = System.nanoTime(); int used = 0;
        String signature;
        try { signature = event.toolName() + ":" + AgentModelRequestFingerprint.sha256(stable(event.arguments())); }
        catch (RuntimeException invalid) { return failure("TOOL_INVALID_ARGUMENTS", "Tool arguments are not JSON", "invalid_arguments", 0, started); }
        if (scope.blocked(signature)) return failure("TOOL_NO_PROGRESS", "Repeated unchanged tool result; use existing evidence or revise the query", "no_progress", 0, started);
        Map<String, Object> result = Map.of(); AgentToolFailure outcome = AgentToolFailure.UNKNOWN;
        String dependency = dependency(event);
        while (!job.isDone() && !scope.ended.get() && !scope.context.interrupted()) {
            if (scope.remaining() == 0) return failure("TOOL_TIMEOUT", "Turn deadline exhausted", "timeout", used, started);
            var permit = circuits.acquire(dependency);
            if (permit == null) return failure("TOOL_CIRCUIT_OPEN", "Dependency circuit is open", "circuit_open", used, started);
            if (scope.attempts.incrementAndGet() > settings.getMaxAttemptsPerTurn()) {
                circuits.complete(permit, AgentToolFailure.CANCELLED);
                return failure("TOOL_BUDGET_EXHAUSTED", "Tool execution budget exhausted", "budget_exhausted", used, started);
            }
            used++;
            CompletableFuture<Map<String, Object>> raw = null;
            try {
                raw = delegate.execute(event);
                result = raw.get(Math.min(TimeUnit.MILLISECONDS.toNanos(settings.getCallTimeoutMs()), scope.remaining()), TimeUnit.NANOSECONDS);
                if (result == null) throw new IllegalStateException("Tool result is null");
                outcome = AgentToolFailure.from(result);
            } catch (TimeoutException timeout) {
                outcome = AgentToolFailure.TIMEOUT; result = error(outcome.code(), "Tool execution timed out");
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt(); outcome = AgentToolFailure.CANCELLED; result = error(outcome.code(), "Tool execution cancelled");
            } catch (ExecutionException | RuntimeException failed) {
                outcome = AgentToolFailure.from(failed); result = error(outcome.code(), "Tool execution failed: " + outcome.name());
            } finally {
                // CompletableFuture.cancel 本身不保证物理任务退出；原执行器负责中断与许可 finally 释放。
                if (raw != null && !raw.isDone()) raw.cancel(true);
            }
            circuits.complete(permit, outcome);
            // 超时不自动重试，避免未退出的旧执行与新尝试重叠；未知失败同样不猜测。
            if (outcome != AgentToolFailure.TRANSIENT_DEPENDENCY || used >= settings.getMaxAttempts()
                    || !replaySafe(event) || circuits.state(dependency).equals("OPEN")) break;
            long baseDelay = Math.min(10000, settings.getRetryDelayMs() << (used - 1));
            long delay = baseDelay == 0 ? 0 : ThreadLocalRandom.current().nextLong(baseDelay / 2, baseDelay + 1);
            if (scope.remaining() <= TimeUnit.MILLISECONDS.toNanos(delay)) break;
            try { TimeUnit.MILLISECONDS.sleep(delay); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); break; }
        }
        boolean stalled = outcome == AgentToolFailure.SUCCESS && scope.recordProgress(signature, result);
        var enriched = new LinkedHashMap<>(result);
        enriched.put("governance", Map.of("category", outcome.name().toLowerCase(Locale.ROOT), "attempts", used,
                "elapsed_ms", elapsed(started), "circuit_state", circuits.state(dependency), "no_progress", stalled));
        return Collections.unmodifiableMap(enriched);
    }

    private boolean replaySafe(AgentModelStreamEvent event) {
        if (runtime == null || runtime.toolsForProfile(runtime.defaultProfile()).stream().noneMatch(tool -> tool.name().equals(event.toolName()))) return false;
        var capability = AgentCapabilityToolMapping.capabilityForTool(event.toolName());
        if (capability.isPresent()) return registry != null && registry.descriptors().stream()
                .anyMatch(descriptor -> descriptor.id().equals(capability.get()) && descriptor.replaySafe());
        return INTERNAL_READS.contains(event.toolName()) || "call_agent".equals(event.toolName()) && "rag_agent".equals(event.arguments().get("agent_name"));
    }
    private static String dependency(AgentModelStreamEvent event) {
        if (event.toolName().startsWith("recommend_")) return "recommend";
        if (Set.of("rag_support", "rag_evidence_search", "call_agent").contains(event.toolName())) return "rag";
        return event.toolName().equals("session_memory") ? "session" : "internal";
    }
    private static Object stable(Object value) {
        if (value instanceof Map<?, ?> map) {
            var result = new TreeMap<String, Object>();
            boolean contentIdentified = Boolean.TRUE.equals(map.get("result_externalized"))
                    && map.get("result_sha256") instanceof String hash && hash.matches("[0-9a-f]{64}");
            map.forEach((key, nested) -> {
                if (key instanceof String text && !VOLATILE_FIELDS.contains(text)
                        && !(contentIdentified && text.equals("result_ref"))) result.put(text, stable(nested));
            });
            return result;
        }
        if (value instanceof List<?> list) return list.stream().map(GovernedAgentToolUseExecutor::stable).toList();
        return value;
    }
    private static Map<String, Object> error(String code, String message) { return Map.of("status", "FAILED", "error_code", code, "error_message", message); }
    private static Map<String, Object> failure(String code, String message, String category, int attempts, long started) {
        var result = new LinkedHashMap<>(error(code, message));
        result.put("governance", Map.of("category", category, "attempts", attempts, "elapsed_ms", elapsed(started)));
        return Map.copyOf(result);
    }
    private static long elapsed(long started) { return Math.max(0, (System.nanoTime() - started) / 1_000_000); }
    private record Progress(String digest, int repetitions) { }
    private static final class Job extends CompletableFuture<Map<String, Object>> {
        final AtomicReference<Future<?>> task = new AtomicReference<>();
        void attach(Future<?> value) { task.set(value); if (isCancelled()) value.cancel(true); }
        @Override public boolean cancel(boolean interrupt) {
            boolean cancelled = super.cancel(interrupt); var value = task.get();
            if (cancelled && value != null) value.cancel(interrupt); return cancelled;
        }
    }
    @Override public synchronized void close() {
        if (!closed.compareAndSet(false, true)) return;
        scopes.forEach(Scope::close); timer.shutdownNow(); coordinators.shutdownNow();
    }
}
