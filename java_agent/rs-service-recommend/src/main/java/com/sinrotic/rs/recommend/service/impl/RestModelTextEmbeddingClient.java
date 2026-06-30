package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.sinrotic.rs.recommend.service.TextEmbeddingClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

@Service
public class RestModelTextEmbeddingClient implements TextEmbeddingClient {

    private final RestClient restClient;

    public RestModelTextEmbeddingClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.model.base-url:http://rs-service-model}") String modelBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(modelBaseUrl).build();
    }

    @Override
    public List<List<Float>> embedTexts(String modelKey, String requestId, List<String> texts) {
        ModelEmbedResponse response = restClient.post()
                .uri("/internal/model/embed")
                .body(Map.of(
                        "model_key", modelKey,
                        "request_id", requestId,
                        "inputs", Map.of("texts", texts),
                        "options", Map.of("normalize", true)
                ))
                .retrieve()
                .body(ModelEmbedResponse.class);
        if (response == null || response.vectors() == null) {
            return List.of();
        }
        return response.vectors().stream()
                .map(vector -> vector.vector().stream().map(Double::floatValue).toList())
                .toList();
    }

    private record ModelEmbedResponse(
            @JsonProperty("request_id")
            String requestId,
            @JsonProperty("model_key")
            String modelKey,
            List<EmbeddingVector> vectors
    ) {
    }

    private record EmbeddingVector(
            String id,
            List<Double> vector,
            Map<String, Object> metadata
    ) {
    }
}
