package com.sinrotic.rs.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;

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
    private final TrustedProxyResolver trustedProxies;
    private final ConcurrentMap<String, AtomicInteger> rateCounters = new ConcurrentHashMap<>();
    private final AtomicLong activeRateWindow = new AtomicLong(Long.MIN_VALUE);

    public GatewayRequestFilter() {
        this(DEFAULT_MAX_REQUESTS_PER_MINUTE, Clock.systemUTC(), new PresenceGatewayTokenValidator(), Set.of());
    }

    GatewayRequestFilter(int maxRequestsPerMinute, Clock clock) {
        this(maxRequestsPerMinute, clock, new PresenceGatewayTokenValidator(), Set.of());
    }

    GatewayRequestFilter(int maxRequestsPerMinute, Clock clock, GatewayTokenValidator tokenValidator) {
        this(maxRequestsPerMinute, clock, tokenValidator, Set.of());
    }

    GatewayRequestFilter(
            int maxRequestsPerMinute,
            Clock clock,
            GatewayTokenValidator tokenValidator,
            Set<String> trustedProxyAddresses
    ) {
        this(maxRequestsPerMinute,clock,tokenValidator,new TrustedProxyResolver(trustedProxyAddresses,clock));
    }

    GatewayRequestFilter(int maxRequestsPerMinute,Clock clock,GatewayTokenValidator tokenValidator,
                         TrustedProxyResolver trustedProxies) {
        this.maxRequestsPerMinute = maxRequestsPerMinute;
        this.clock = clock;
        this.tokenValidator = tokenValidator;
        this.trustedProxies = trustedProxies;
    }

    @Autowired
    public GatewayRequestFilter(
            GatewayTokenValidator tokenValidator,
            @Value("${rs.gateway.rate-limit.max-requests-per-minute:120}") int maxRequestsPerMinute,
            @Value("${rs.gateway.rate-limit.trusted-proxies:}") String trustedProxies
    ) {
        this(maxRequestsPerMinute, Clock.systemUTC(), tokenValidator, parseTrustedProxies(trustedProxies));
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
            if (accessToken.isEmpty()) {
                return writeJsonError(
                        mutatedExchange,
                        HttpStatus.UNAUTHORIZED,
                        "UNAUTHORIZED",
                        "Authorization bearer token is required"
                );
            }
            ServerWebExchange authenticatedExchange = mutatedExchange;
            return tokenValidator.validate(accessToken.get())
                    .flatMap(userContext -> proceed(
                            withUserContext(authenticatedExchange, userContext),
                            request,
                            chain
                    ).thenReturn(Boolean.TRUE))
                    .switchIfEmpty(Mono.defer(() -> writeJsonError(
                            authenticatedExchange,
                            HttpStatus.UNAUTHORIZED,
                            "UNAUTHORIZED",
                            "Authorization bearer token is invalid"
                    ).thenReturn(Boolean.FALSE)))
                    .then();
        }
        return proceed(mutatedExchange, request, chain);
    }

    private Mono<Void> proceed(
            ServerWebExchange exchange,
            ServerHttpRequest originalRequest,
            GatewayFilterChain chain
    ) {
        if (!isApiRequest(originalRequest.getMethod(),originalRequest.getURI().getPath()) || maxRequestsPerMinute <= 0)
            return chain.filter(exchange);
        Mono<String> client = Mono.fromCallable(() -> clientKey(originalRequest));
        // DNS 只在缓存过期时查询，并放到有界线程池，避免阻塞 Gateway 的事件循环。
        if (trustedProxies.requiresLookup()) client = client.subscribeOn(Schedulers.boundedElastic());
        return client.flatMap(key -> {
            if (isRateLimited(key)) return writeJsonError(
                    exchange,
                    HttpStatus.TOO_MANY_REQUESTS,
                    "TOO_MANY_REQUESTS",
                    "Too many requests"
            );
            return chain.filter(exchange);
        });
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

    private boolean isRateLimited(String client) {
        if (maxRequestsPerMinute <= 0) {
            return false;
        }
        long minuteWindow = clock.instant().getEpochSecond() / 60;
        evictExpiredRateWindows(minuteWindow);
        String key = client + ":" + minuteWindow;
        int currentCount = rateCounters.computeIfAbsent(key, ignored -> new AtomicInteger()).incrementAndGet();
        return currentCount > maxRequestsPerMinute;
    }

    private String clientKey(ServerHttpRequest request) {
        String remoteAddress = request.getRemoteAddress() == null
                ? "unknown"
                : request.getRemoteAddress().getAddress() == null ? request.getRemoteAddress().getHostString()
                : request.getRemoteAddress().getAddress().getHostAddress();
        String forwardedFor = request.getHeaders().getFirst("X-Forwarded-For");
        if (trustedProxies.trusted(remoteAddress) && forwardedFor != null && !forwardedFor.isBlank()) {
            // 部署契约为单层可信入口；旧 Nginx 的追加模式也只能使用最右侧真实上游地址。
            String[] addresses = forwardedFor.split(",",-1);
            String client = addresses[addresses.length-1].trim();
            if (TrustedProxyResolver.numericAddress(client)) return TrustedProxyResolver.normalize(client);
        }
        return remoteAddress;
    }

    private void evictExpiredRateWindows(long minuteWindow) {
        long previousWindow = activeRateWindow.getAndSet(minuteWindow);
        if (previousWindow == minuteWindow) {
            return;
        }
        String currentSuffix = ":" + minuteWindow;
        rateCounters.keySet().removeIf(key -> !key.endsWith(currentSuffix));
    }

    private static Set<String> parseTrustedProxies(String value) {
        if (value == null || value.isBlank()) {
            return Set.of();
        }
        return java.util.Arrays.stream(value.split(","))
                .map(String::trim)
                .filter(item -> !item.isEmpty())
                .collect(Collectors.toUnmodifiableSet());
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
