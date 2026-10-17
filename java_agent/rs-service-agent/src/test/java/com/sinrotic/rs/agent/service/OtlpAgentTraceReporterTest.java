package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentTraceReporterProperties;
import com.sinrotic.rs.agent.service.impl.CompositeAgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.HttpAgentTraceReporter;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class OtlpAgentTraceReporterTest {
    @Test
    void sendsJsonToExplicitEndpointWithLangfuseHeadersAndChecksPartialRejections() throws Exception {
        var bodies = new CopyOnWriteArrayList<String>();
        var headers = new CopyOnWriteArrayList<Map<String, String>>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/public/otel/v1/traces", exchange -> {
            bodies.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            headers.add(Map.of("auth", exchange.getRequestHeaders().getFirst("Authorization"),
                    "version", exchange.getRequestHeaders().getFirst("x-langfuse-ingestion-version"),
                    "type", exchange.getRequestHeaders().getFirst("Content-Type")));
            var response = (bodies.size() == 1 ? "{}" : "{\"partialSuccess\":{\"rejectedSpans\":\"1\"}}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        var props = properties(server);
        props.getOtlp().setLangfuse(true);
        props.getOtlp().setAuthorization("Basic test-credential");
        try (var reporter = HttpAgentTraceReporter.otlp(RestClient.builder(), props)) {
            reporter.report(OtlpAgentTraceEncoderTest.event("agent_started", "", Map.of(), 0));
            reporter.report(OtlpAgentTraceEncoderTest.event("agent_done", "", Map.of(), 1));
            reporter.report(OtlpAgentTraceEncoderTest.event("agent_done", "", Map.of(), 2));
            reporter.close();
            assertThat(reporter.statistics().accepted()).isEqualTo(2);
            assertThat(reporter.statistics().sent()).isEqualTo(1);
            assertThat(reporter.statistics().failed()).isEqualTo(1);
            assertThat(bodies).hasSize(2).allSatisfy(body -> assertThat(body).doesNotContain("private-body", "test-credential"));
            assertThat(headers).allSatisfy(row -> {
                assertThat(row.get("auth")).isEqualTo("Basic test-credential");
                assertThat(row.get("version")).isEqualTo("4");
                assertThat(row.get("type")).startsWith("application/json");
            });
            var span = OtlpAgentTraceEncoderTest.span(new ObjectMapper().readTree(bodies.getFirst()));
            assertThat(span.path("name").asText()).isEqualTo("agent.turn");
        } finally { server.stop(0); }
    }

    @Test
    void blockedPlatformQueueDoesNotPreventExternalDelivery() throws Exception {
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var received = new CountDownLatch(1);
        var platformServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var otlpServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        platformServer.createContext("/internal/platform-trace/agent/events", exchange -> {
            entered.countDown();
            try { release.await(5, TimeUnit.SECONDS); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
            exchange.sendResponseHeaders(503, -1); exchange.close();
        });
        otlpServer.createContext("/api/public/otel/v1/traces", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.sendResponseHeaders(200, 2); exchange.getResponseBody().write("{}".getBytes(StandardCharsets.UTF_8));
            exchange.close(); received.countDown();
        });
        platformServer.start(); otlpServer.start();
        var props = properties(otlpServer);
        props.setQueueCapacity(1);
        props.setPlatformTraceBaseUrl("http://127.0.0.1:" + platformServer.getAddress().getPort());
        var platform = new HttpAgentTraceReporter(RestClient.builder(), props);
        var otlp = HttpAgentTraceReporter.otlp(RestClient.builder(), props);
        try (var reporter = new CompositeAgentTraceReporter(List.of(platform, otlp))) {
            reporter.report(OtlpAgentTraceEncoderTest.event("agent_done", "", Map.of(), 1));
            assertThat(entered.await(2, TimeUnit.SECONDS)).isTrue();
            assertThat(received.await(2, TimeUnit.SECONDS)).isTrue();
            release.countDown(); reporter.close();
            assertThat(platform.statistics().failed()).isEqualTo(1);
            assertThat(otlp.statistics().sent()).isEqualTo(1);
        } finally { release.countDown(); platformServer.stop(0); otlpServer.stop(0); }
    }

    @Test
    void rejectsMalformedAndOversizedResponsesAndUnsafeConfiguration() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var count = new java.util.concurrent.atomic.AtomicInteger();
        server.createContext("/api/public/otel/v1/traces", exchange -> {
            exchange.getRequestBody().readAllBytes();
            var body = (count.getAndIncrement() == 0 ? "[invalid" : " ".repeat(4097)).getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        server.start();
        var props = properties(server);
        try (var reporter = HttpAgentTraceReporter.otlp(RestClient.builder(), props)) {
            reporter.report(OtlpAgentTraceEncoderTest.event("agent_done", "", Map.of(), 1));
            reporter.report(OtlpAgentTraceEncoderTest.event("agent_done", "", Map.of(), 2));
            reporter.close();
            assertThat(reporter.statistics().failed()).isEqualTo(2);
            assertThat(reporter.statistics().sent()).isZero();
        } finally { server.stop(0); }
        props.getOtlp().setEndpoint("https://user:secret@example.com/traces?key=secret");
        assertThatIllegalArgumentException().isThrownBy(() -> HttpAgentTraceReporter.otlp(RestClient.builder(), props))
                .withMessageNotContaining("secret");
        props.getOtlp().setEndpoint("https://example.com/traces");
        props.getOtlp().setLangfuse(true);
        assertThatIllegalArgumentException().isThrownBy(() -> HttpAgentTraceReporter.otlp(RestClient.builder(), props));
        props.getOtlp().setLangfuse(false);
        props.getOtlp().setIdentityKey("short");
        assertThatIllegalArgumentException().isThrownBy(() -> HttpAgentTraceReporter.otlp(RestClient.builder(), props));
    }

    private static AgentTraceReporterProperties properties(HttpServer server) {
        var properties = new AgentTraceReporterProperties();
        properties.getOtlp().setEndpoint("http://127.0.0.1:" + server.getAddress().getPort() + "/api/public/otel/v1/traces");
        properties.getOtlp().setIdentityKey(OtlpAgentTraceEncoderTest.config().getIdentityKey());
        return properties;
    }
}
