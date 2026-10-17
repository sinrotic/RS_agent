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
import java.time.Duration;
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
    private final LongAdder accepted = new LongAdder(), sent = new LongAdder(), failed = new LongAdder(),
            dropped = new LongAdder(), oversized = new LongAdder();
    private static final System.Logger LOG = System.getLogger(HttpAgentTraceReporter.class.getName());

    public HttpAgentTraceReporter(RestClient.Builder restClientBuilder, AgentTraceReporterProperties properties) {
        maxEventBytes = properties.getMaxEventBytes();
        shutdownTimeoutMs = properties.getShutdownTimeoutMs();
        var timeout = Duration.ofMillis(properties.getRequestTimeoutMs());
        transport = HttpClient.newBuilder().connectTimeout(timeout).build();
        var requests = new JdkClientHttpRequestFactory(transport);
        requests.setReadTimeout(timeout);
        this.client = restClientBuilder.clone()
                .baseUrl(properties.getPlatformTraceBaseUrl())
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
            // 队列保存有大小上限的序列化快照，不持有可变业务对象或任意大的工具结果。
            byte[] payload = json.writeValueAsBytes(event);
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
            client.post().uri("/internal/platform-trace/agent/events")
                    .contentType(MediaType.APPLICATION_JSON).body(payload).retrieve().toBodilessEntity();
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
