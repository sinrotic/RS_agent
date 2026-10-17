package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import com.sinrotic.rs.agent.service.AgentCapabilityToolMapping;
import com.sinrotic.rs.agent.service.AgentOnlineEvaluationObserver;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/** Bounded asynchronous shadow export. Disk outbox is retried; never updates skills. */
@Component
public final class HttpAgentOnlineEvaluationObserver implements AgentOnlineEvaluationObserver {
    private static final Logger log = LoggerFactory.getLogger(HttpAgentOnlineEvaluationObserver.class);
    private static final int MAX_BYTES = 120_000;
    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
    private final ThreadPoolExecutor exporter = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(32), task -> { var t = new Thread(task, "online-evaluation-export"); t.setDaemon(true); return t; });
    private final ScheduledExecutorService retry = Executors.newSingleThreadScheduledExecutor(task -> {
        var t = new Thread(task, "online-evaluation-retry"); t.setDaemon(true); return t;
    });
    private final boolean enabled;
    private final URI endpoint;
    private final String token, skillVersion, modelVersion;
    private final Path outbox;
    private final AtomicLong delivered = new AtomicLong(), errors = new AtomicLong(), dropped = new AtomicLong();

    public HttpAgentOnlineEvaluationObserver(
            @Value("${rs.agent.online-evaluation.enabled:false}") boolean enabled,
            @Value("${rs.agent.online-evaluation.base-url:}") String baseUrl,
            @Value("${rs.agent.online-evaluation.token:}") String token,
            @Value("${rs.agent.online-evaluation.outbox:}") String outbox,
            @Value("${rs.agent.online-evaluation.skill-version:unknown}") String skillVersion,
            @Value("${rs.agent.online-evaluation.model-version:unknown}") String modelVersion) {
        this.enabled = enabled && !baseUrl.isBlank() && !token.isBlank() && !outbox.isBlank();
        this.endpoint = this.enabled ? URI.create(baseUrl.replaceAll("/+$", "") + "/internal/evaluation/turns") : null;
        if (this.enabled && (!List.of("http", "https").contains(endpoint.getScheme()) || endpoint.getUserInfo() != null))
            throw new IllegalArgumentException("Invalid evaluation endpoint");
        this.token = token; this.skillVersion = skillVersion; this.modelVersion = modelVersion;
        this.outbox = this.enabled ? Path.of(outbox).toAbsolutePath().normalize() : null;
        if (this.enabled) retry.scheduleWithFixedDelay(this::retryOutbox, 10, 10, TimeUnit.SECONDS);
        if (enabled && !this.enabled) log.warn("在线评价未启用：旁路配置不完整");
    }

    @Override public void completed(AgentChatRequestDTO request, AgentTurnVO turn, List<AgentTurnVO> previous) {
        if (!enabled) return;
        try {
            var event = payload(request, turn, previous);
            byte[] body = mapper.writeValueAsBytes(event);
            if (body.length > MAX_BYTES) { dropped.incrementAndGet(); return; }
            String key = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(
                    mapper.writeValueAsBytes(List.of(request.sessionId(), turn.requestId()))));
            exporter.execute(() -> {
                try {
                    Files.createDirectories(outbox);
                    try (var entries = Files.list(outbox)) {
                        if (entries.limit(1001).count() >= 1000) { dropped.incrementAndGet(); return; }
                    }
                    Path file = outbox.resolve(key + ".json");
                    if (!Files.exists(file)) {
                        Path pending = outbox.resolve(key + ".pending");
                        Files.write(pending, body, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
                        Files.move(pending, file, java.nio.file.StandardCopyOption.ATOMIC_MOVE);
                    }
                    send(file);
                } catch (Exception error) { errors.incrementAndGet(); }
            });
        } catch (java.util.concurrent.RejectedExecutionException error) {
            dropped.incrementAndGet();
        } catch (Exception error) { errors.incrementAndGet(); }
    }

    public Map<String, Object> diagnostics() {
        return Map.of("enabled", enabled, "delivered", delivered.get(), "errors", errors.get(),
                "dropped", dropped.get(), "auto_deploy", false);
    }

    private Map<String, Object> payload(AgentChatRequestDTO request, AgentTurnVO turn, List<AgentTurnVO> previous) {
        var messages = new ArrayList<String>();
        boolean truncated = previous.size() > 11;
        if (request.resolvedContext().get("session_effective_context") instanceof Map<?, ?> context)
            truncated |= Boolean.TRUE.equals(context.get("truncated"));
        for (var prior : previous.subList(Math.max(0, previous.size() - 11), previous.size())) {
            String message = prior.userMessage();
            if (message != null && !message.isBlank()) { truncated |= message.length() > 6000; messages.add(clean(message, 6000)); }
        }
        truncated |= request.userMessage().length() > 6000;
        truncated |= turn.assistantMessage() != null && turn.assistantMessage().length() > 20_000;
        messages.add(clean(request.userMessage(), 6000));
        var observed = new LinkedHashSet<>(turn.recommendedItemIds());
        var displayed = new ArrayList<>(turn.recommendedItemIds());
        for (var tool : turn.toolCalls()) {
            if (!"SUCCESS".equals(tool.status()) || !"recommend".equals(
                    AgentCapabilityToolMapping.capabilityForTool(tool.toolName()).orElse(""))) continue;
            Object raw = tool.metadata() == null ? null : tool.metadata().get("payload");
            if (raw instanceof Map<?, ?> map && map.get("items") instanceof List<?> items) {
                for (Object item : items) {
                    if (item instanceof AgentRecommendedItemVO product) observed.add(product.itemId());
                    else if (item instanceof Map<?, ?> product && product.get("item_id") instanceof String id) observed.add(id);
                }
            }
        }
        for (var block : turn.answerBlocks()) collectDisplayed(block, displayed, 0);
        var event = new LinkedHashMap<String, Object>();
        event.put("session_id", request.sessionId()); event.put("turn_id", turn.requestId());
        event.put("profile_user_id", request.profileUserId());
        event.put("customer_messages", messages); event.put("assistant_message", clean(turn.assistantMessage(), 20_000));
        event.put("item_ids", displayed); event.put("observed_item_ids", List.copyOf(observed));
        event.put("tool_statuses", turn.toolCalls().stream().limit(100).map(tool ->
                Map.of("tool_name", tool.toolName(), "status", tool.status())).toList());
        event.put("context_truncated", truncated); event.put("occurred_at", Instant.now().toString());
        event.put("skill_version", skillVersion); event.put("model_version", modelVersion);
        event.put("finish_reason", turn.finishReason());
        event.put("degradation_reasons", turn.degradationReasons());
        return event;
    }

    private void collectDisplayed(Object node, List<String> ids, int depth) {
        if (depth > 10 || ids.size() > 100) return;
        if (node instanceof Map<?, ?> map) {
            if (map.get("item_ids") instanceof List<?> values)
                for (Object value : values) if (value instanceof String id && !ids.contains(id)) ids.add(id);
            // A2UI shopping data may contain a singular item_id as well.
            if (map.get("item_id") instanceof String id && !ids.contains(id)) ids.add(id);
            for (Object value : map.values()) collectDisplayed(value, ids, depth + 1);
        } else if (node instanceof List<?> list) for (Object value : list) collectDisplayed(value, ids, depth + 1);
    }

    private String clean(String text, int limit) {
        if (text == null) return "";
        text = text.replaceAll("(?i)Bearer\\s+\\S+|(?:sk-|api[_-]?key[=:]\\s*)[A-Za-z0-9_-]+", "[凭证已脱敏]")
                .replaceAll("[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}", "[邮箱已脱敏]")
                .replaceAll("(?<!\\d)1[3-9]\\d{9}(?!\\d)", "[手机号已脱敏]");
        return text.substring(0, Math.min(limit, text.length()));
    }

    private void send(Path file) throws Exception {
        if (Files.size(file) > MAX_BYTES) { errors.incrementAndGet(); return; }
        var request = HttpRequest.newBuilder(endpoint).timeout(Duration.ofSeconds(5))
                .header("Authorization", "Bearer " + token).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(Files.readAllBytes(file))).build();
        int status = client.send(request, HttpResponse.BodyHandlers.discarding()).statusCode();
        if (status == 202) { Files.deleteIfExists(file); delivered.incrementAndGet(); }
        else errors.incrementAndGet();
    }

    private void retryOutbox() {
        if (!Files.isDirectory(outbox)) return;
        try (var files = Files.list(outbox)) {
            for (Path file : files.filter(path -> path.getFileName().toString().matches("[a-f0-9]{64}\\.json")).limit(32).toList()) {
                try { exporter.execute(() -> { try { if (Files.exists(file)) send(file); } catch (Exception error) { errors.incrementAndGet(); } }); }
                catch (java.util.concurrent.RejectedExecutionException error) { break; }
            }
        } catch (Exception error) { errors.incrementAndGet(); }
    }

    @PreDestroy public void close() { retry.shutdownNow(); exporter.shutdownNow(); }
}
