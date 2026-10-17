package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.service.RecommendationSessionValidator;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;

@Service
public class RestRecommendationSessionValidator implements RecommendationSessionValidator {
    private final RestClient client;

    public RestRecommendationSessionValidator(RestClient.Builder builder,
            @Value("${rs.user.base-url:http://rs-service-user:18101}") String baseUrl) {
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(1)).build());
        factory.setReadTimeout(Duration.ofSeconds(2));
        client = builder.clone().baseUrl(baseUrl).requestFactory(factory).build();
    }

    @Override
    public void requireActive(String accountId, String profileUserId, String sessionId) {
        readActivity(accountId, profileUserId, sessionId, true);
    }

    @Override
    public java.time.Instant activeUntil(String accountId, String profileUserId, String sessionId) {
        var session = readActivity(accountId, profileUserId, sessionId, false);
        try {
            return java.time.Instant.parse((String) session.get("expiresAt"));
        } catch (RuntimeException malformed) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session activity unavailable", malformed);
        }
    }

    @Override
    public java.util.List<com.sinrotic.rs.recommend.domain.preference.ActiveRecommendationSession> activeSessions(
            String afterSessionId, int limit) {
        if (limit < 1 || limit > 100) throw new IllegalArgumentException("会话分页大小必须在 1 到 100 之间");
        try {
            var rows = client.get().uri(builder -> builder.path("/internal/sessions/active")
                    .queryParam("after_session_id",afterSessionId).queryParam("limit",limit).build())
                    .exchange((request,response) -> {
                        if (response.getStatusCode().value() != 200) throw new IllegalStateException("活跃会话读取失败");
                        return response.bodyTo(java.util.List.class);
                    });
            if (rows == null || rows.size() > limit) throw new IllegalStateException("活跃会话分页响应异常");
            var result = new java.util.ArrayList<com.sinrotic.rs.recommend.domain.preference.ActiveRecommendationSession>();
            String previous = afterSessionId;
            for (var row : rows) {
                var session = (Map<?, ?>) row;
                String id = (String) session.get("sessionId");
                String account = (String) session.get("accountId");
                String profile = (String) session.get("profileUserId");
                if (id == null || id.compareTo(previous) <= 0 || account == null || account.isBlank()
                        || profile == null || profile.isBlank() || !"ACTIVE".equals(session.get("status")))
                    throw new IllegalStateException("活跃会话身份或分页顺序异常");
                result.add(new com.sinrotic.rs.recommend.domain.preference.ActiveRecommendationSession(
                        new com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity(account,profile,id),
                        java.time.Instant.parse((String) session.get("expiresAt"))));
                previous = id;
            }
            return java.util.List.copyOf(result);
        } catch (RuntimeException unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Session activity unavailable",unavailable);
        }
    }

    private Map<?, ?> readActivity(String accountId, String profileUserId, String sessionId, boolean touch) {
        if (accountId == null || accountId.isBlank() || profileUserId == null || profileUserId.isBlank())
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Trusted user identity is required");
        if (sessionId == null || sessionId.isBlank())
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "session_id is required");
        try {
            RestClient.RequestHeadersSpec<?> call = touch
                    ? client.post().uri("/internal/sessions/{sessionId}/touch", sessionId)
                        .body(Map.of("account_id", accountId, "profile_user_id", profileUserId))
                    : client.get().uri("/internal/sessions/{sessionId}/activity", sessionId);
            Map<?, ?> session = call.header("X-Account-Id", accountId).header("X-Profile-User-Id", profileUserId)
                    .exchange((request, response) -> {
                        int status = response.getStatusCode().value();
                        if (status == 401 || status == 403 || status == 404)
                            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
                        if (status == 410)
                            throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
                        if (status != 200)
                            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable");
                        return response.bodyTo(Map.class);
                    });
            if (session == null)
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable");
            if (!sessionId.equals(session.get("sessionId"))
                    || !accountId.equals(session.get("accountId"))
                    || !profileUserId.equals(session.get("profileUserId")))
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
            if (!"ACTIVE".equals(session.get("status")))
                throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
            return session;
        } catch (ResponseStatusException failure) {
            throw failure;
        } catch (RuntimeException unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Session validation unavailable", unavailable);
        }
    }
}
