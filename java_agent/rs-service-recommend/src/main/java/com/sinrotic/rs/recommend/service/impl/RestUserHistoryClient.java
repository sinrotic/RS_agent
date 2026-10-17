package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.service.UserHistoryClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import java.util.List;
import java.util.Map;

@Service
public class RestUserHistoryClient implements UserHistoryClient {
    private final RestClient client;
    public RestUserHistoryClient(RestClient.Builder builder, @Value("${rs.user.base-url:http://rs-service-user:18101}") String baseUrl) {
        client = builder.baseUrl(baseUrl).build();
    }
    @Override public List<String> recentItemIds(String userId, int limit) {
        List<String> result = client.post().uri("/internal/users/context/positive-history")
                .body(Map.of("profile_user_id", userId, "limit", limit)).retrieve().body(new ParameterizedTypeReference<>() { });
        return result == null ? List.of() : result.stream().distinct().toList();
    }
}
