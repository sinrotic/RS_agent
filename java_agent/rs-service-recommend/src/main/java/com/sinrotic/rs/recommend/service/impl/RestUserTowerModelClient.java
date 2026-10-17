package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;
import com.sinrotic.rs.recommend.service.UserTowerModelClient;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.*;

public final class RestUserTowerModelClient implements UserTowerModelClient {
    private final RestClient client;
    private final int dimension;
    public RestUserTowerModelClient(RestClient.Builder builder, String baseUrl) {
        this(builder, baseUrl, 64);
    }
    public RestUserTowerModelClient(RestClient.Builder builder, String baseUrl, int dimension) {
        if (dimension <= 0 || dimension > 4096) throw new IllegalArgumentException("invalid user tower dimension");
        this.dimension = dimension;
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build());
        factory.setReadTimeout(Duration.ofSeconds(2));
        client = builder.requestFactory(factory).baseUrl(baseUrl).build();
    }
    public Optional<UserEmbedding> inferUserEmbedding(String model, String requestId, String user, List<String> history) {
        var response = client.post().uri("/internal/model/two-tower/user-embedding")
                .body(Map.of("model_key", model, "request_id", requestId, "history_item_ids", history))
                .retrieve().body(Map.class);
        if (response == null || !model.equals(response.get("model_key")) || !(response.get("embedding") instanceof List<?> raw))
            throw new IllegalStateException("invalid two-tower model response");
        if (raw.isEmpty()) return Optional.empty();
        if (raw.size() != dimension) throw new IllegalStateException("unexpected user tower vector dimension");
        var vector = new ArrayList<Float>();
        double norm = 0;
        for (var value : raw) {
            if (!(value instanceof Number number) || !Float.isFinite(number.floatValue())) throw new IllegalStateException("invalid two-tower vector");
            vector.add(number.floatValue());
            norm += number.doubleValue() * number.doubleValue();
        }
        if (Math.abs(norm - 1) > .02) throw new IllegalStateException("two-tower vector is not normalized");
        return Optional.of(new UserEmbedding(model, user, vector, Objects.toString(response.get("query_source"), "trained_user_tower")));
    }
}
