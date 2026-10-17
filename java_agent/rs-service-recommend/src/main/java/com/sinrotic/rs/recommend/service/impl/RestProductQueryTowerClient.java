package com.sinrotic.rs.recommend.service.impl;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.*;

/** 将冻结 BGE 查询投影到与商品、用户相同的残差空间。 */
@Service
public class RestProductQueryTowerClient {
    private final boolean enabled;
    private final String modelKey;
    private final String collection;
    private final RestClient client;

    public RestProductQueryTowerClient(RestClient.Builder builder,
            @Value("${rs.recommend.query-tower.enabled:false}") boolean enabled,
            @Value("${rs.recommend.two-tower.base-url:http://172.21.0.1:18120}") String baseUrl,
            @Value("${rs.recommend.two-tower.model-key:product_three_tower_v4_seed42_step6000}") String modelKey,
            @Value("${rs.recommend.two-tower.collection:rs_agent_product_three_tower_v4_20261011}") String collection) {
        this.enabled = enabled; this.modelKey = modelKey; this.collection = collection;
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build());
        factory.setReadTimeout(Duration.ofSeconds(2));
        this.client = builder.clone().requestFactory(factory).baseUrl(baseUrl).build();
    }
    public boolean enabled() { return enabled; }
    public String collection() { return collection; }
    public List<Float> project(List<Float> embedding) {
        var response = client.post().uri("/internal/model/product/query-embedding")
                .body(Map.of("model_key", modelKey, "embedding", embedding)).retrieve().body(Map.class);
        if (response == null || !modelKey.equals(response.get("model_key"))
                || !(response.get("embedding") instanceof List<?> raw) || raw.size() != 1024)
            throw new IllegalStateException("invalid product query projection");
        var result = new ArrayList<Float>(); double norm = 0;
        for (var value : raw) {
            if (!(value instanceof Number n) || !Float.isFinite(n.floatValue())) throw new IllegalStateException("nonfinite query projection");
            result.add(n.floatValue()); norm += n.doubleValue() * n.doubleValue();
        }
        if (Math.abs(norm - 1) > .02) throw new IllegalStateException("unnormalized query projection");
        return List.copyOf(result);
    }
}
