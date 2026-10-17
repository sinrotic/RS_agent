package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import java.util.function.Predicate;

/** Bounds health probes and temporarily hides tools whose HTTP dependency is unavailable. */
public final class AgentDependencyReadiness implements Predicate<String> {
    private final BooleanSupplier probe;
    private final LongSupplier clock;
    private final boolean httpRecommendations;
    private long expiresAt;
    private boolean ready;

    public AgentDependencyReadiness(String baseUrl, boolean httpRecommendations) {
        this(httpProbe(baseUrl), System::nanoTime, httpRecommendations);
    }

    public AgentDependencyReadiness(BooleanSupplier probe, LongSupplier clock, boolean httpRecommendations) {
        this.probe = probe;
        this.clock = clock;
        this.httpRecommendations = httpRecommendations;
    }

    @Override
    public boolean test(String tool) {
        boolean dependencyRequired = "call_agent".equals(tool) || "rag_support".equals(tool)
                || "rag_search_compress".equals(tool) || "rag_evidence_search".equals(tool)
                || (httpRecommendations && tool.startsWith("recommend_"));
        return !dependencyRequired || ready();
    }

    private synchronized boolean ready() {
        long now = clock.getAsLong();
        if (expiresAt == 0 || now - expiresAt >= 0) {
            try { ready = probe.getAsBoolean(); } catch (RuntimeException failure) { ready = false; }
            expiresAt = clock.getAsLong() + Duration.ofSeconds(ready ? 5 : 1).toNanos();
        }
        return ready;
    }

    private static BooleanSupplier httpProbe(String baseUrl) {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(500)).build();
        ObjectMapper mapper = new ObjectMapper();
        return () -> {
            try {
                URI uri = URI.create(baseUrl.replaceAll("/+$", "") + "/actuator/health/readiness");
                HttpRequest request = HttpRequest.newBuilder(uri).timeout(Duration.ofMillis(500)).GET().build();
                HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
                return response.statusCode() == 200 && "UP".equals(mapper.readTree(response.body()).path("status").asText());
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return false;
            } catch (Exception unavailable) {
                return false;
            }
        };
    }
}
