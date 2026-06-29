package com.sinrotic.rs.gateway.filter;

import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class GatewayRequestFilterTest {

    @Test
    void allowsWhitelistedAuthPathWithoutToken() {
        GatewayRequestFilter filter = new GatewayRequestFilter();
        AtomicReference<ServerWebExchange> downstream = new AtomicReference<>();
        GatewayFilterChain chain = exchange -> {
            downstream.set(exchange);
            return Mono.empty();
        };
        ServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/auth/login").build()
        );

        filter.filter(exchange, chain).block();

        assertThat(exchange.getResponse().getStatusCode()).isNull();
        assertThat(downstream.get()).isNotNull();
        assertThat(downstream.get().getRequest().getHeaders().getFirst("X-Request-Id")).isNotBlank();
    }

    @Test
    void rejectsApiRequestWithoutBearerToken() {
        GatewayRequestFilter filter = new GatewayRequestFilter();
        ServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/agent/chat").build()
        );

        filter.filter(exchange, ignored -> Mono.empty()).block();

        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void forwardsAuthorizedApiRequestAndPreservesRequestId() {
        GatewayRequestFilter filter = new GatewayRequestFilter();
        AtomicReference<ServerWebExchange> downstream = new AtomicReference<>();
        GatewayFilterChain chain = exchange -> {
            downstream.set(exchange);
            return Mono.empty();
        };
        ServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/recommend/home")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer access-token")
                        .header("X-Request-Id", "req-001")
                        .header("X-Account-Id", "spoofed")
                        .build()
        );

        filter.filter(exchange, chain).block();

        assertThat(exchange.getResponse().getStatusCode()).isNull();
        assertThat(downstream.get()).isNotNull();
        assertThat(downstream.get().getRequest().getHeaders().getFirst("X-Request-Id")).isEqualTo("req-001");
        assertThat(downstream.get().getRequest().getHeaders().getFirst("X-Account-Id")).isNull();
    }

    @Test
    void forwardsAuthenticatedUserContextFromTokenValidator() {
        GatewayRequestFilter filter = new GatewayRequestFilter(
                120,
                Clock.fixed(Instant.parse("2026-06-28T10:00:00Z"), ZoneOffset.UTC),
                token -> Optional.of(new GatewayUserContext("acc_001", "review_user_001", "USER"))
        );
        AtomicReference<ServerWebExchange> downstream = new AtomicReference<>();
        GatewayFilterChain chain = exchange -> {
            downstream.set(exchange);
            return Mono.empty();
        };
        ServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/agent/chat")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer access-token")
                        .build()
        );

        filter.filter(exchange, chain).block();

        assertThat(downstream.get()).isNotNull();
        assertThat(downstream.get().getRequest().getHeaders().getFirst("X-Account-Id")).isEqualTo("acc_001");
        assertThat(downstream.get().getRequest().getHeaders().getFirst("X-Profile-User-Id")).isEqualTo("review_user_001");
        assertThat(downstream.get().getRequest().getHeaders().getFirst("X-User-Roles")).isEqualTo("USER");
    }

    @Test
    void rateLimitsApiRequestsPerClientPerMinute() {
        GatewayRequestFilter filter = new GatewayRequestFilter(
                2,
                Clock.fixed(Instant.parse("2026-06-28T10:00:00Z"), ZoneOffset.UTC)
        );
        GatewayFilterChain chain = exchange -> Mono.empty();

        filter.filter(authorizedExchange("req-001"), chain).block();
        filter.filter(authorizedExchange("req-002"), chain).block();
        ServerWebExchange blocked = authorizedExchange("req-003");

        filter.filter(blocked, chain).block();

        assertThat(blocked.getResponse().getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    private ServerWebExchange authorizedExchange(String requestId) {
        return MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/agent/chat")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer access-token")
                        .header("X-Forwarded-For", "127.0.0.1")
                        .header("X-Request-Id", requestId)
                        .build()
        );
    }
}
