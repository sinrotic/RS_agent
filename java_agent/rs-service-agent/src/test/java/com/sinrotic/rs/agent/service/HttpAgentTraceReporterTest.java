package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentTraceReporterProperties;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.impl.HttpAgentTraceReporter;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.assertj.core.api.Assertions.*;

class HttpAgentTraceReporterTest {
    @Test
    void fullQueueDropsWithoutBlockingAndCloseFlushesAcceptedEvents() throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var payloads = new CopyOnWriteArrayList<String>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/platform-trace/agent/events", exchange -> {
            payloads.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            entered.countDown();
            try { release.await(5, TimeUnit.SECONDS); } catch (InterruptedException failure) { Thread.currentThread().interrupt(); }
            exchange.sendResponseHeaders(204, -1);
            exchange.close();
        });
        server.start();
        var properties = properties(server);
        properties.setQueueCapacity(1);
        properties.setRequestTimeoutMs(3000);
        try (var reporter = new HttpAgentTraceReporter(RestClient.builder(), properties)) {
            reporter.report(event("one"));
            assertThat(entered.await(2, TimeUnit.SECONDS)).isTrue();
            reporter.report(event("two"));
            reporter.report(event("three"));
            assertThat(reporter.statistics().accepted()).isEqualTo(2);
            assertThat(reporter.statistics().pending()).isEqualTo(1);
            assertThat(reporter.statistics().dropped()).isEqualTo(1);
            release.countDown();
            reporter.close();
            assertThat(reporter.statistics().sent()).isEqualTo(2);
            assertThat(reporter.statistics().failed()).isZero();
            assertThat(payloads).hasSize(2).allSatisfy(payload -> assertThat(payload).contains("\"request_id\":\"turn\""));
            reporter.report(event("after-close"));
            assertThat(reporter.statistics().dropped()).isEqualTo(2);
        } finally {
            release.countDown();
            server.stop(0);
        }
    }

    @Test
    void stalledTracePlatformTimesOutAndFailureIsObservable() throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/platform-trace/agent/events", exchange -> {
            entered.countDown();
            try { release.await(5, TimeUnit.SECONDS); } catch (InterruptedException failure) { Thread.currentThread().interrupt(); }
            exchange.close();
        });
        server.start();
        var properties = properties(server);
        properties.setRequestTimeoutMs(250);
        properties.setShutdownTimeoutMs(2000);
        try (var reporter = new HttpAgentTraceReporter(RestClient.builder(), properties)) {
            reporter.report(event("timeout"));
            assertThat(entered.await(2, TimeUnit.SECONDS)).isTrue();
            reporter.close();
            assertThat(reporter.statistics().sent()).isZero();
            assertThat(reporter.statistics().failed()).isEqualTo(1);
        } finally {
            release.countDown();
            server.stop(0);
        }
    }

    @Test
    void oversizedEventIsRejectedBeforeItCanOccupyTheQueue() {
        var properties = new AgentTraceReporterProperties();
        properties.setMaxEventBytes(32);
        try (var reporter = new HttpAgentTraceReporter(RestClient.builder(), properties)) {
            reporter.report(event("too-large"));
            assertThat(reporter.statistics().oversized()).isEqualTo(1);
            assertThat(reporter.statistics().dropped()).isEqualTo(1);
            assertThat(reporter.statistics().accepted()).isZero();
        }
        assertThatIllegalArgumentException().isThrownBy(() -> properties.setQueueCapacity(0));
        assertThatIllegalArgumentException().isThrownBy(() -> properties.setRequestTimeoutMs(0));
    }

    private AgentTraceReporterProperties properties(HttpServer server) {
        var properties = new AgentTraceReporterProperties();
        properties.setPlatformTraceBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        return properties;
    }

    private AgentTraceEventVO event(String id) {
        return new AgentTraceEventVO(id, "session", "turn", "model_call_completed", "", "", "agent", "", "",
                null, Map.of("status", "completed"), Instant.parse("2026-10-18T00:00:00Z"));
    }
}
