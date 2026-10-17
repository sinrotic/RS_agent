package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.function.LongSupplier;

/** 一次模型客户端调用的最终观测；SDK 内部的网络重试尚不独立计数。 */
public final class AgentModelCallObservation {
    private static final List<String> TOKEN_FIELDS = List.of("prompt_tokens", "completion_tokens", "total_tokens",
            "cache_read_input_tokens", "cache_write_input_tokens");
    private static final System.Logger LOG = System.getLogger(AgentModelCallObservation.class.getName());
    private final String requestId;
    private final Map<String, Object> identity;
    private final Consumer<AgentStreamEventVO> sink;
    private final LongSupplier nanoTime;
    private final long started;
    private Map<String, Object> usage = Map.of();
    private Long firstToken;
    private boolean finished;
    private boolean explicitlyFinalUsage;

    public AgentModelCallObservation(String requestId, String sessionId, int loopIndex,
                                     Consumer<AgentStreamEventVO> sink) {
        this(requestId, sessionId, loopIndex, sink, System::nanoTime);
    }

    public AgentModelCallObservation(String requestId, String sessionId, int loopIndex,
                                     Consumer<AgentStreamEventVO> sink, LongSupplier nanoTime) {
        this.requestId = requestId;
        this.sink = sink;
        this.nanoTime = nanoTime;
        this.started = nanoTime.getAsLong();
        this.identity = Map.of("model_call_id", "model_" + UUID.randomUUID(), "run_id", requestId,
                "turn_id", requestId, "session_id", sessionId, "loop_index", loopIndex,
                "call_kind", "generation", "attempt_scope", "agent_model_stream_client_invocation");
        publish("model_call_started", identity);
    }

    public synchronized void record(AgentModelStreamEvent event) {
        if (finished) return;
        if (event.isToken() && !event.delta().isBlank() && firstToken == null) firstToken = nanoTime.getAsLong();
        if (event.isUsage()) {
            var snapshot = new LinkedHashMap<String, Object>();
            for (String key : TOKEN_FIELDS) {
                Object value = event.arguments().get(key);
                if ((value instanceof Integer || value instanceof Long) && ((Number) value).longValue() >= 0)
                    snapshot.put(key, value);
            }
            usage = Map.copyOf(snapshot);
            explicitlyFinalUsage = Boolean.TRUE.equals(event.arguments().get("usage_final"));
        }
    }

    public synchronized void finish(String status, boolean transportFinished) {
        if (finished) return;
        finished = true;
        var data = new LinkedHashMap<>(identity);
        data.put("status", status);
        data.put("latency_ms", Math.max(0L, (nanoTime.getAsLong() - started) / 1_000_000));
        if (firstToken != null) data.put("first_token_ms", Math.max(0L, (firstToken - started) / 1_000_000));
        data.put("transport_finished", transportFinished);
        data.put("usage_final", (transportFinished || explicitlyFinalUsage) && !usage.isEmpty());
        data.put("usage_status", usage.isEmpty() ? "missing"
                : usage.containsKey("prompt_tokens") && usage.containsKey("completion_tokens")
                && usage.containsKey("total_tokens") ? "complete" : "partial");
        data.put("usage", usage);
        // 账本仅消费此嵌套快照；不再复制到顶层，避免旧平台将它和 model_usage 再累加一次。
        publish("model_call_completed", Map.copyOf(data));
    }

    private void publish(String type, Map<String, Object> data) {
        try {
            sink.accept(new AgentStreamEventVO(type, requestId, data));
        } catch (RuntimeException ignored) {
            // 观测失败不能变更 Agent 行为，也不能覆盖真实异常；不记录异常内容或模型输入。
            LOG.log(System.Logger.Level.WARNING, "Agent model observation delivery failed");
        }
    }
}
