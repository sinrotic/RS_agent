package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentReasoningProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import java.util.function.Consumer;
import java.util.*;
import java.util.concurrent.*;
import com.sinrotic.rs.agent.service.AgentExecutionLimiter;
import com.sinrotic.rs.agent.config.AgentExecutionProperties;

/** 每个 Turn 的治理入口；预算的引用显式传给子调用，不依赖线程局部变量。 */
public final class AgentReasoningPolicy implements AutoCloseable {
    private static final AgentReasoningPolicy DISABLED;
    static {
        var settings = new AgentReasoningProperties(); settings.setBudgetEnabled(false); settings.setDriftEnabled(false);
        DISABLED = new AgentReasoningPolicy(settings);
    }
    private final AgentReasoningProperties settings;
    private final AgentSemanticDrift.Reviewer reviewer;
    private final ExecutorService reviewWorkers = Executors.newVirtualThreadPerTaskExecutor();
    public AgentReasoningPolicy(AgentReasoningProperties settings) {
        this(settings,null);
    }
    public AgentReasoningPolicy(AgentReasoningProperties settings, AgentSemanticDrift.Reviewer reviewer) {
        this.settings = settings;
        this.reviewer = reviewer;
        if (settings.isBudgetEnabled()) new AgentTurnBudget(settings).close(); // 启动即校验费用配置。
    }
    public static AgentReasoningPolicy disabled() { return DISABLED; }
    public AgentReasoningProperties settings() { return settings; }
    public Scope openTurn(AgentInterruptContext context, AgentChatRequestDTO request,
            Consumer<AgentStreamEventVO> events, AgentModelStreamClient model) {
        return openTurn(context,request,events,model,new AgentExecutionLimiter(new AgentExecutionProperties()));
    }
    public Scope openTurn(AgentInterruptContext context, AgentChatRequestDTO request,
            Consumer<AgentStreamEventVO> events, AgentModelStreamClient model, AgentExecutionLimiter limiter) {
        return new Scope(context, request, events, model, limiter);
    }
    public final class Scope implements AutoCloseable {
        private final AgentInterruptContext context;
        private final Consumer<AgentStreamEventVO> events;
        private final AgentTurnBudget budget;
        private final AgentChatRequestDTO request;
        private final AgentModelStreamClient model;
        private final AgentExecutionLimiter limiter;
        private final List<String> recent = new ArrayList<>();
        private int searches, violations;
        private boolean finalOnly;
        private boolean closed;
        private Scope(AgentInterruptContext context, AgentChatRequestDTO request, Consumer<AgentStreamEventVO> events,
                AgentModelStreamClient model, AgentExecutionLimiter limiter) {
            this.context = context; this.events = events;
            this.request = request; this.model = model; this.limiter = limiter;
            budget = settings.isBudgetEnabled() ? new AgentTurnBudget(settings) : null;
            if (budget != null) context.attachBudget(budget);
        }
        public boolean finalAnswerOnly() { return finalOnly; }
        public AgentSemanticDrift.Decision beforeTool(AgentModelStreamEvent tool) {
            String query = AgentSemanticDrift.query(tool);
            if (!settings.isDriftEnabled() || query.isBlank()) return new AgentSemanticDrift.Decision(false,false,"NOT_REVIEWED","not_applicable","none");
            searches++;
            String goal = request.userMessage() == null ? "" : request.userMessage();
            String signal = AgentSemanticDrift.signal(goal,query);
            boolean suspicious = signal.equals("category_switch");
            boolean selected = suspicious || searches % settings.getReviewEvery() == 0;
            long started = System.nanoTime();
            var review = AgentSemanticDrift.Review.unknown(selected ? "review_disabled" : "not_sampled");
            String status = "NOT_REVIEWED";
            if (selected && settings.isSemanticReviewEnabled()) {
                var child = context.fork("drift_check");
                var recentSnapshot = List.copyOf(recent);
                Future<AgentSemanticDrift.Review> task = reviewWorkers.submit(() -> reviewer != null
                        ? reviewer.review(goal,recentSnapshot,query,child) : modelReview(goal,recentSnapshot,query,child));
                child.onInterrupt(() -> task.cancel(true));
                try { review = task.get(settings.getReviewTimeoutMs(),TimeUnit.MILLISECONDS); status = review.status(); }
                catch (TimeoutException timeout) { review = AgentSemanticDrift.Review.unknown("review_timeout"); status = "UNKNOWN"; }
                catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); review = AgentSemanticDrift.Review.unknown("review_cancelled"); status = "UNKNOWN"; }
                catch (ExecutionException | RuntimeException failed) { review = AgentSemanticDrift.Review.unknown("review_failed"); status = "UNKNOWN"; }
                finally { child.interrupt("review_finished"); if (!task.isDone()) task.cancel(true); }
            }
            boolean blocked = status.equals("DRIFT") || suspicious && !status.equals("ALIGNED");
            if (blocked && ++violations >= settings.getMaxDriftViolations()) finalOnly = true;
            var decision = new AgentSemanticDrift.Decision(blocked,finalOnly,status,review.reason(),signal);
            if (recent.size() == 3) recent.removeFirst(); recent.add(query.length() > 512 ? query.substring(0,512) : query);
            var data = new LinkedHashMap<String,Object>();
            data.put("tool_call_id",tool.toolCallId()); data.put("review_status",status); data.put("reason",review.reason());
            data.put("signal",signal); data.put("blocked",blocked); data.put("final_answer_only",finalOnly);
            data.put("goal_sha256",AgentModelRequestFingerprint.sha256(goal)); data.put("query_sha256",AgentModelRequestFingerprint.sha256(query));
            data.put("latency_ms",Math.max(0,(System.nanoTime()-started)/1000000));
            try { events.accept(new AgentStreamEventVO("drift_check_completed",context.requestId(),Map.copyOf(data))); }
            catch (RuntimeException ignored) { }
            return decision;
        }
        private AgentSemanticDrift.Review modelReview(String goal, List<String> recent, String query, AgentInterruptContext child) {
            String payload;
            try { payload = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(Map.of("current_user_goal",goal,"recent_queries",recent,"candidate_query",query)); }
            catch (Exception invalid) { return AgentSemanticDrift.Review.unknown("invalid_input"); }
            var text = new StringBuilder();
            limiter.runWithModelStream(() -> {
                var observation = new AgentModelCallObservation(context.requestId(),request.sessionId(),-1,events,System::nanoTime,"drift_check");
                boolean completed = false;
                try {
                    model.streamAssistantEvents(context.requestId(),
                        new AgentChatRequestDTO(request.sessionId(),request.profileUserId(),payload,1,Map.of()), event -> {
                            observation.record(event);
                            if (event.isToolUse()) throw new IllegalStateException("Reviewer cannot call tools");
                            if (event.isToken()) {
                                if (text.length()+event.delta().length() > 4096) throw new IllegalStateException("Reviewer response too long");
                                text.append(event.delta());
                            }
                        },child,observation::recordRequest);
                    completed = !child.interrupted();
                } finally { observation.finish(completed ? "completed" : child.interrupted() ? "interrupted" : "error",completed); }
            },child::interrupted);
            return AgentSemanticDrift.parse(text.toString(),query);
        }
        @Override public void close() {
            if (closed) return; closed = true;
            if (budget != null) {
                budget.close();
                try { events.accept(new AgentStreamEventVO("model_budget_completed", context.requestId(), budget.snapshot())); }
                catch (RuntimeException ignored) { /* 观测故障不能改变预算执行。 */ }
            }
        }
    }
    @Override public void close() { reviewWorkers.shutdownNow(); }
}
