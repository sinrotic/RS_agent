package com.sinrotic.rs.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicInteger;

@Component
public class GatewayRequestFilter implements GlobalFilter, Ordered {

    private static final String REQUEST_ID_HEADER = "X-Request-Id";
    private static final List<String> AUTH_WHITELIST = List.of(
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/refresh"
    );
    private static final List<String> SPOOFABLE_USER_HEADERS = List.of(
            "X-Account-Id",
            "X-Profile-User-Id",
            "X-User-Roles"
    );
    private static final int DEFAULT_MAX_REQUESTS_PER_MINUTE = 120;

    private final int maxRequestsPerMinute;
    private final Clock clock;
    private final GatewayTokenValidator tokenValidator;
    private final ConcurrentMap<String, AtomicInteger> rateCounters = new ConcurrentHashMap<>();

    public GatewayRequestFilter() {
        this(DEFAULT_MAX_REQUESTS_PER_MINUTE, Clock.systemUTC(), new PresenceGatewayTokenValidator());
    }

    GatewayRequestFilter(int maxRequestsPerMinute, Clock clock) {
        this(maxRequestsPerMinute, clock, new PresenceGatewayTokenValidator());
    }

    GatewayRequestFilter(int maxRequestsPerMinute, Clock clock, GatewayTokenValidator tokenValidator) {
        this.maxRequestsPerMinute = maxRequestsPerMinute;
        this.clock = clock;
        this.tokenValidator = tokenValidator;
    }

    @Autowired
    public GatewayRequestFilter(GatewayTokenValidator tokenValidator) {
        this(DEFAULT_MAX_REQUESTS_PER_MINUTE, Clock.systemUTC(), tokenValidator);
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        String path = request.getURI().getPath();

        ServerHttpRequest.Builder requestBuilder = request.mutate()
                .headers(headers -> {
                    SPOOFABLE_USER_HEADERS.forEach(headers::remove);
                    String requestId = headers.getFirst(REQUEST_ID_HEADER);
                    if (requestId == null || requestId.isBlank()) {
                        headers.set(REQUEST_ID_HEADER, UUID.randomUUID().toString());
                    }
                });

        ServerWebExchange mutatedExchange = exchange.mutate().request(requestBuilder.build()).build();
        if (requiresAuthentication(request.getMethod(), path)) {
            Optional<String> accessToken = bearerToken(request.getHeaders());
            Optional<GatewayUserContext> userContext = accessToken.flatMap(tokenValidator::validate);
            if (userContext.isEmpty()) {
                return writeJsonError(
                        mutatedExchange,
                        HttpStatus.UNAUTHORIZED,
                        "UNAUTHORIZED",
                        "Authorization bearer token is required"
                );
            }
            mutatedExchange = withUserContext(mutatedExchange, userContext.get());
        }
        if (isApiRequest(request.getMethod(), path) && isRateLimited(request)) {
            return writeJsonError(
                    mutatedExchange,
                    HttpStatus.TOO_MANY_REQUESTS,
                    "TOO_MANY_REQUESTS",
                    "Too many requests"
            );
        }

        return chain.filter(mutatedExchange);
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }

    private boolean requiresAuthentication(HttpMethod method, String path) {
        if (HttpMethod.OPTIONS.equals(method)) {
            return false;
        }
        if (!isApiRequest(method, path)) {
            return false;
        }
        return AUTH_WHITELIST.stream().noneMatch(path::equals);
    }

    private boolean isApiRequest(HttpMethod method, String path) {
        return !HttpMethod.OPTIONS.equals(method) && path.startsWith("/api/");
    }

    private Optional<String> bearerToken(HttpHeaders headers) {
        String authorization = headers.getFirst(HttpHeaders.AUTHORIZATION);
        if (authorization == null || !authorization.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return Optional.empty();
        }
        String token = authorization.substring(7).trim();
        return token.isEmpty() ? Optional.empty() : Optional.of(token);
    }

    private ServerWebExchange withUserContext(ServerWebExchange exchange, GatewayUserContext userContext) {
        ServerHttpRequest.Builder requestBuilder = exchange.getRequest().mutate();
        if (userContext.accountId() != null && !userContext.accountId().isBlank()) {
            requestBuilder.header("X-Account-Id", userContext.accountId());
        }
        if (userContext.profileUserId() != null && !userContext.profileUserId().isBlank()) {
            requestBuilder.header("X-Profile-User-Id", userContext.profileUserId());
        }
        if (userContext.roles() != null && !userContext.roles().isBlank()) {
            requestBuilder.header("X-User-Roles", userContext.roles());
        }
        return exchange.mutate().request(requestBuilder.build()).build();
    }

    private boolean isRateLimited(ServerHttpRequest request) {
        if (maxRequestsPerMinute <= 0) {
            return false;
        }
        long minuteWindow = clock.instant().getEpochSecond() / 60;
        String key = clientKey(request) + ":" + minuteWindow;
        int currentCount = rateCounters.computeIfAbsent(key, ignored -> new AtomicInteger()).incrementAndGet();
        return currentCount > maxRequestsPerMinute;
    }

    private String clientKey(ServerHttpRequest request) {
        String forwardedFor = request.getHeaders().getFirst("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",")[0].trim();
        }
        if (request.getRemoteAddress() != null) {
            return request.getRemoteAddress().getHostString();
        }
        return "unknown";
    }

    private Mono<Void> writeJsonError(
            ServerWebExchange exchange,
            HttpStatus status,
            String code,
            String message
    ) {
        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        String body = "{\"code\":\"" + code + "\",\"message\":\"" + message + "\"}";
        return exchange.getResponse().writeWith(Mono.just(
                exchange.getResponse().bufferFactory().wrap(body.getBytes(StandardCharsets.UTF_8))
        ));
    }
}
