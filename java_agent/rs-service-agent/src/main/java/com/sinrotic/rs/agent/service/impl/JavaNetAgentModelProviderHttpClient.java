package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.function.Consumer;
import java.util.stream.Stream;

public class JavaNetAgentModelProviderHttpClient implements AgentModelProviderHttpClient {

    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    @Override
    public String postJson(String url, String payload, String accept) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .header("Accept", accept)
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new IllegalStateException("model provider returned HTTP " + response.statusCode());
            }
            return response.body();
        } catch (IOException ex) {
            throw new IllegalStateException("failed to call model provider", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("model provider call interrupted", ex);
        }
    }

    @Override
    public void streamJson(String url, String payload, String accept, Consumer<String> lineConsumer) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .header("Accept", accept)
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();
        try {
            HttpResponse<Stream<String>> response = httpClient.send(request, HttpResponse.BodyHandlers.ofLines());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new IllegalStateException("model provider returned HTTP " + response.statusCode());
            }
            try (Stream<String> lines = response.body()) {
                lines.forEach(lineConsumer);
            }
        } catch (IOException ex) {
            throw new IllegalStateException("failed to stream model provider response", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("model provider stream interrupted", ex);
        }
    }
}
