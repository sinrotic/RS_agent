package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentTraceReporterProperties;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentTraceReporter;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.http.MediaType;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.net.http.HttpClient;
import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.LongAdder;

public class HttpAgentTraceReporter implements AgentTraceReporter, AutoCloseable {

    private final RestClient client;
    private final HttpClient transport;
    private final ThreadPoolExecutor executor;
    private final ObjectMapper json = new ObjectMapper().findAndRegisterModules()
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    private final int maxEventBytes;
    private final int shutdownTimeoutMs;
    private final String endpoint;
    private final boolean otlp;
    private final Function<AgentTraceEventVO, Optional<Object>> encoder;
    private final LongAdder accepted = new LongAdder(), sent = new LongAdder(), failed = new LongAdder(),
            dropped = new LongAdder(), oversized = new LongAdder();
    private static final System.Logger LOG = System.getLogger(HttpAgentTraceReporter.class.getName());

    public HttpAgentTraceReporter(RestClient.Builder restClientBuilder, AgentTraceReporterProperties properties) {
        this(restClientBuilder, properties, properties.getPlatformTraceBaseUrl().replaceAll("/+$", "")
                + "/internal/platform-trace/agent/events", Map.of(), event -> Optional.of(event), false);
    }

    public static HttpAgentTraceReporter otlp(RestClient.Builder builder, AgentTraceReporterProperties properties) {
        var config = properties.getOtlp();
        URI uri;
        try { uri = URI.create(config.getEndpoint()); }
        catch (RuntimeException invalid) { throw new IllegalArgumentException("OTLP endpoint 无效"); }
        if (uri.getScheme() == null || !java.util.Set.of("http", "https").contains(uri.getScheme()) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null)
            throw new IllegalArgumentException("OTLP endpoint 需要不含凭据、查询或片段的 HTTP(S) 地址");
        if (config.isLangfuse() && (config.getAuthorization() == null || config.getAuthorization().isBlank()))
            throw new IllegalArgumentException("Langfuse 导出需要 Authorization 配置");
        var headers = new java.util.LinkedHashMap<String, String>();
        if (config.getAuthorization() != null && !config.getAuthorization().isBlank()) headers.put("Authorization", config.getAuthorization());
        if (config.isLangfuse()) headers.put("x-langfuse-ingestion-version", "4");
        return new HttpAgentTraceReporter(builder, properties, uri.toString(), headers, new OtlpAgentTraceEncoder(config), true);
    }

    private HttpAgentTraceReporter(RestClient.Builder restClientBuilder, AgentTraceReporterProperties properties,
            String endpoint, Map<String, String> headers, Function<AgentTraceEventVO, Optional<Object>> encoder, boolean otlp) {
        this.endpoint = endpoint;
        this.encoder = encoder;
        this.otlp = otlp;
        maxEventBytes = properties.getMaxEventBytes();
        shutdownTimeoutMs = properties.getShutdownTimeoutMs();
        var timeout = Duration.ofMillis(properties.getRequestTimeoutMs());
        transport = HttpClient.newBuilder().connectTimeout(timeout).build();
        var requests = new JdkClientHttpRequestFactory(transport);
        requests.setReadTimeout(timeout);
        this.client = restClientBuilder.clone()
                .defaultHeaders(values -> headers.forEach(values::set))
                .requestFactory(requests)
                .build();
        executor = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(properties.getQueueCapacity()),
                Thread.ofPlatform().daemon(true).name("agent-trace-export-", 0).factory(),
                new ThreadPoolExecutor.AbortPolicy());
    }

    @Override
    public void report(AgentTraceEventVO event) {
        if (event == null || event.requestId() == null || event.requestId().isBlank()) {
            return;
        }
        if (executor.isShutdown()) {
            drop(1);
            return;
        }
        try {
            var encoded = encoder.apply(event);
            if (encoded.isEmpty()) return;
            // 队列保存有大小上限的序列化快照，不持有可变业务对象或任意大的工具结果。
            byte[] payload = json.writeValueAsBytes(encoded.get());
            if (payload.length > maxEventBytes) {
                oversized.increment();
                drop(1);
                return;
            }
            executor.execute(() -> send(payload));
            accepted.increment();
        } catch (RejectedExecutionException fullOrClosing) {
            drop(1);
        } catch (Exception serializationFailure) {
            failed.increment();
            warnFirstFailure();
        }
    }

    private void send(byte[] payload) {
        try {
            var request = client.post().uri(endpoint).contentType(MediaType.APPLICATION_JSON).body(payload);
            if (!otlp) request.retrieve().toBodilessEntity();
            else request.exchange((ignored, response) -> {
                if (response.getStatusCode().value() != 200) throw new IllegalStateException("OTLP export rejected");
                byte[] body = response.getBody().readNBytes(4097);
                if (body.length > 4096) throw new IllegalStateException("OTLP response exceeds limit");
                if (body.length > 0) {
                    var result = json.readTree(body);
                    if (!result.isObject()) throw new IllegalStateException("OTLP response must be an object");
                    var partial = result.path("partialSuccess");
                    if (!partial.isMissingNode() && !partial.isObject())
                        throw new IllegalStateException("OTLP partialSuccess must be an object");
                    var rejected = partial.path("rejectedSpans");
                    if (!rejected.isMissingNode() && (!rejected.asText().matches("[0-9]+")
                            || new java.math.BigInteger(rejected.asText()).signum() > 0))
                        throw new IllegalStateException("OTLP spans partially rejected");
                }
                return null;
            });
            sent.increment();
        } catch (RuntimeException unavailable) {
            failed.increment();
            warnFirstFailure();
        }
    }

    private void warnFirstFailure() {
        if (failed.sum() == 1) LOG.log(System.Logger.Level.WARNING, "Agent trace export failed; see reporter statistics");
    }

    private void drop(long count) {
        dropped.add(count);
        if (count > 0 && dropped.sum() == count)
            LOG.log(System.Logger.Level.WARNING, "Agent trace events dropped; see reporter statistics");
    }

    public Statistics statistics() {
        return new Statistics(accepted.sum(), sent.sum(), failed.sum(), dropped.sum(), oversized.sum(), executor.getQueue().size());
    }

    public record Statistics(long accepted, long sent, long failed, long dropped, long oversized, int pending) { }

    @Override
    public void close() {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(shutdownTimeoutMs, TimeUnit.MILLISECONDS))
                drop(executor.shutdownNow().size());
        } catch (InterruptedException interrupted) {
            drop(executor.shutdownNow().size());
            Thread.currentThread().interrupt();
        } finally {
            transport.shutdownNow();
        }
    }
}
