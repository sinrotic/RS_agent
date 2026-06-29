package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentTraceReporterProperties;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentTraceReporter;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class HttpAgentTraceReporter implements AgentTraceReporter {

    private final RestClient client;
    private final ExecutorService executorService = Executors.newVirtualThreadPerTaskExecutor();

    public HttpAgentTraceReporter(RestClient.Builder restClientBuilder, AgentTraceReporterProperties properties) {
        this.client = restClientBuilder.clone()
                .baseUrl(properties.getPlatformTraceBaseUrl())
                .build();
    }

    @Override
    public void report(AgentTraceEventVO event) {
        if (event == null || event.requestId() == null || event.requestId().isBlank()) {
            return;
        }
        executorService.submit(() -> {
            try {
                client.post()
                        .uri("/internal/platform-trace/agent/events")
                        .body(event)
                        .retrieve()
                        .toBodilessEntity();
            } catch (RestClientException ignored) {
            }
        });
    }
}
