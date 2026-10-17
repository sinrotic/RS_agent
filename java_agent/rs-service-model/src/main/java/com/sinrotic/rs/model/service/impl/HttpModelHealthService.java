package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.vo.*;
import com.sinrotic.rs.model.service.ModelHealthService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.time.Instant;
import java.util.List;
import java.util.Map;

@Service
@Profile("!mock-models")
public class HttpModelHealthService implements ModelHealthService {
    private final RestClient.Builder builder;
    private final String embeddingBaseUrl;
    private final String rerankBaseUrl;

    public HttpModelHealthService(RestClient.Builder builder,
            @Value("${rs.model.runtime.embedding-base-url:}") String embeddingBaseUrl,
            @Value("${rs.model.runtime.rerank-base-url:}") String rerankBaseUrl) {
        this.builder = builder;
        this.embeddingBaseUrl = embeddingBaseUrl;
        this.rerankBaseUrl = rerankBaseUrl;
    }

    @Override
    public ModelRuntimeHealthVO getModelHealth(String modelKey) {
        String endpoint = switch (modelKey == null ? "" : modelKey) {
            case "bge-m3", "bge_m3_embedding" -> embeddingBaseUrl;
            case "bge-reranker-v2-m3", "bge_reranker" -> rerankBaseUrl;
            default -> "";
        };
        String status = "UNCONFIGURED";
        long start = System.nanoTime();
        if (endpoint != null && !endpoint.isBlank()) {
            try {
                Map<?, ?> body = builder.clone().baseUrl(endpoint).build().get().uri("/health").retrieve().body(Map.class);
                String capability = "bge-m3".equals(modelKey) || "bge_m3_embedding".equals(modelKey) ? "embed" : "rank";
                status = body != null && "UP".equals(body.get("status"))
                        && body.get("capabilities") instanceof List<?> capabilities && capabilities.contains(capability)
                        ? "UP" : "DOWN";
            } catch (RestClientException error) {
                status = "DOWN";
            }
        }
        return new ModelRuntimeHealthVO(modelKey, status, "http", endpoint == null ? "" : endpoint,
                Instant.now().toString(), (System.nanoTime() - start) / 1_000_000);
    }

    @Override
    public ModelHealthVO getHealth() {
        var embedding = getModelHealth("bge-m3");
        var reranking = getModelHealth("bge-reranker-v2-m3");
        long ready = List.of(embedding, reranking).stream().filter(model -> "UP".equals(model.status())).count();
        String status = ready == 2 ? "UP" : ready == 1 ? "DEGRADED" : "DOWN";
        return new ModelHealthVO(status, Map.of("status", status, "ready_model_count", ready), List.of(
                Map.of("name", "embedding", "status", embedding.status()),
                Map.of("name", "reranking", "status", reranking.status())));
    }
}
