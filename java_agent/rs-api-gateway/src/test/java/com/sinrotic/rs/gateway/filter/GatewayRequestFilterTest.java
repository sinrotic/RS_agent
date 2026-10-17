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
import java.time.ZoneId;
import java.util.Map;
import java.util.Set;
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
                token -> Mono.just(new GatewayUserContext("acc_001", "review_user_001", "USER"))
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

    @Test
    void ignoresForwardedForFromUntrustedClient() {
        GatewayRequestFilter filter = new GatewayRequestFilter(
                1,
                Clock.fixed(Instant.parse("2026-06-28T10:00:00Z"), ZoneOffset.UTC),
                token -> Mono.just(GatewayUserContext.anonymous()),
                Set.of()
        );
        GatewayFilterChain chain = exchange -> Mono.empty();

        filter.filter(authorizedExchange("req-001", "198.51.100.1"), chain).block();
        ServerWebExchange blocked = authorizedExchange("req-002", "198.51.100.2");
        filter.filter(blocked, chain).block();

        assertThat(blocked.getResponse().getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    @Test
    @SuppressWarnings("unchecked")
    void evictsCountersFromPreviousMinute() throws ReflectiveOperationException {
        MutableClock clock = new MutableClock(Instant.parse("2026-06-28T10:00:00Z"));
        GatewayRequestFilter filter = new GatewayRequestFilter(
                2,
                clock,
                token -> Mono.just(GatewayUserContext.anonymous()),
                Set.of()
        );

        filter.filter(authorizedExchange("req-001"), exchange -> Mono.empty()).block();
        clock.setInstant(Instant.parse("2026-06-28T10:01:00Z"));
        filter.filter(authorizedExchange("req-002"), exchange -> Mono.empty()).block();

        var field = GatewayRequestFilter.class.getDeclaredField("rateCounters");
        field.setAccessible(true);
        Map<String, ?> counters = (Map<String, ?>) field.get(filter);
        assertThat(counters).hasSize(1);
    }

    private ServerWebExchange authorizedExchange(String requestId) {
        return authorizedExchange(requestId, "127.0.0.1");
    }

    @Test
    void forwardedPrefixCannotGiveSameActualClientNewRateBuckets() {
        var clock = Clock.fixed(Instant.parse("2026-10-10T10:00:00Z"),ZoneOffset.UTC);
        var filter = new GatewayRequestFilter(2,clock,new PresenceGatewayTokenValidator(),Set.of("172.21.0.10"));
        assertThat(proxyRequest(filter,"172.21.0.10","198.51.100.1, 203.0.113.9")).isNull();
        assertThat(proxyRequest(filter,"172.21.0.10","198.51.100.2, 203.0.113.9")).isNull();
        assertThat(proxyRequest(filter,"172.21.0.10","198.51.100.3, 203.0.113.9")).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    @Test
    void deploymentProxyAliasSeparatesClientsAndDnsRunsOffEventLoop() {
        var clock = Clock.fixed(Instant.parse("2026-10-10T10:00:00Z"),ZoneOffset.UTC);
        var thread = new AtomicReference<String>();
        var resolver = new TrustedProxyResolver(Set.of("rs-frontend"),clock,hostname -> {
            assertThat(hostname).isEqualTo("rs-frontend");thread.set(Thread.currentThread().getName());return Set.of("172.21.0.10");
        });
        var filter = new GatewayRequestFilter(1,clock,new PresenceGatewayTokenValidator(),resolver);
        assertThat(proxyRequest(filter,"172.21.0.10","203.0.113.9")).isNull();
        assertThat(proxyRequest(filter,"172.21.0.10","203.0.113.10")).isNull();
        assertThat(proxyRequest(filter,"172.21.0.10","203.0.113.9")).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
        assertThat(thread.get()).startsWith("boundedElastic-");
    }

    @Test
    void proxyResolutionRefreshesAfterAddressChangeAndFailsClosed() {
        var clock = new MutableClock(Instant.parse("2026-10-10T10:00:00Z"));
        var addresses = new AtomicReference<>(Set.of("172.21.0.10"));
        var resolver = new TrustedProxyResolver(Set.of("rs-frontend"),clock,hostname -> addresses.get());
        assertThat(resolver.trusted("172.21.0.10")).isTrue();
        addresses.set(Set.of("172.21.0.11"));clock.setInstant(clock.instant().plusSeconds(31));
        assertThat(resolver.trusted("172.21.0.10")).isFalse();assertThat(resolver.trusted("172.21.0.11")).isTrue();
        addresses.set(Set.of());clock.setInstant(clock.instant().plusSeconds(31));
        assertThat(resolver.trusted("172.21.0.11")).isFalse();
    }

    @Test
    void invalidOrTrailingEmptyForwardedAddressCannotCreateRateBuckets() {
        var clock = Clock.fixed(Instant.parse("2026-10-10T10:00:00Z"),ZoneOffset.UTC);
        var filter = new GatewayRequestFilter(1,clock,new PresenceGatewayTokenValidator(),Set.of("172.21.0.10"));
        assertThat(proxyRequest(filter,"172.21.0.10","invented-host")).isNull();
        assertThat(proxyRequest(filter,"172.21.0.10","203.0.113.9,")).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    @Test
    void untrustedPeerCannotUseForwardedAddressEvenWhenProxyIsConfigured() {
        var clock = Clock.fixed(Instant.parse("2026-10-10T10:00:00Z"),ZoneOffset.UTC);
        var filter = new GatewayRequestFilter(1,clock,new PresenceGatewayTokenValidator(),Set.of("172.21.0.10"));
        assertThat(proxyRequest(filter,"172.21.0.99","203.0.113.9")).isNull();
        assertThat(proxyRequest(filter,"172.21.0.99","203.0.113.10")).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    private HttpStatus proxyRequest(GatewayRequestFilter filter,String remote,String forwarded) {
        var exchange = MockServerWebExchange.from(MockServerHttpRequest.post("/api/auth/login")
                .remoteAddress(new java.net.InetSocketAddress(remote,41000)).header("X-Forwarded-For",forwarded).build());
        filter.filter(exchange,ignored -> Mono.empty()).block();
        return (HttpStatus)exchange.getResponse().getStatusCode();
    }

    private ServerWebExchange authorizedExchange(String requestId, String forwardedFor) {
        return MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/agent/chat")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer access-token")
                        .header("X-Forwarded-For", forwardedFor)
                        .header("X-Request-Id", requestId)
                        .build()
        );
    }

    private static final class MutableClock extends Clock {

        private Instant instant;

        private MutableClock(Instant instant) {
            this.instant = instant;
        }

        void setInstant(Instant instant) {
            this.instant = instant;
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }
}
