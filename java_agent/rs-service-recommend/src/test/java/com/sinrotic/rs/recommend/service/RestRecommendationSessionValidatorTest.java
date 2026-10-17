package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.service.impl.RestRecommendationSessionValidator;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;

class RestRecommendationSessionValidatorTest {
    @Test
    void touchUsesPostWhileActivityAndActiveSessionScanRemainReadOnlyAndValidateExpiry() throws Exception {
        var body = new AtomicReference<>("{\"sessionId\":\"session\",\"accountId\":\"account\",\"profileUserId\":\"profile\",\"status\":\"ACTIVE\",\"expiresAt\":\"2026-10-12T00:00:00Z\"}");
        var method = new AtomicReference<String>();
        var payload = new AtomicReference<String>();
        var path = new AtomicReference<String>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/sessions/",exchange -> {
            method.set(exchange.getRequestMethod());
            payload.set(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));
            path.set(exchange.getRequestURI().toString());
            var bytes = body.get().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type","application/json");
            exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });
        server.start();
        try {
            var client = new RestRecommendationSessionValidator(RestClient.builder(),"http://127.0.0.1:"+server.getAddress().getPort());
            client.requireActive("account","profile","session");
            assertThat(method).hasValue("POST");
            var request = new com.fasterxml.jackson.databind.ObjectMapper().readTree(payload.get());
            assertThat(request.get("account_id").asText()).isEqualTo("account");
            assertThat(request.get("profile_user_id").asText()).isEqualTo("profile");
            assertThat(client.activeUntil("account","profile","session")).isEqualTo(java.time.Instant.parse("2026-10-12T00:00:00Z"));
            assertThat(method).hasValue("GET");
            assertThat(path).hasValue("/internal/sessions/session/activity");
            body.set("["+body.get()+"]");
            assertThat(client.activeSessions("",1)).singleElement().satisfies(session -> {
                assertThat(session.identity().accountId()).isEqualTo("account");
                assertThat(session.identity().profileUserId()).isEqualTo("profile");
            });
            assertThat(method).hasValue("GET");
            assertThat(path).hasValue("/internal/sessions/active?after_session_id=&limit=1");
            assertThatThrownBy(() -> client.activeSessions("session",1)).hasMessageContaining("503");
            body.set("{\"sessionId\":\"session\",\"accountId\":\"account\",\"profileUserId\":\"profile\",\"status\":\"ACTIVE\",\"expiresAt\":\"invalid\"}");
            assertThatThrownBy(() -> client.activeUntil("account","profile","session")).hasMessageContaining("503");
            body.set("null");
            assertThatThrownBy(() -> client.activeSessions("",1)).hasMessageContaining("503");
        } finally { server.stop(0); }
    }
    @Test
    void validatesTrustedOwnersStateAndEncodedSessionAndFailsClosed() throws Exception {
        var status = new AtomicInteger(200);
        var body = new AtomicReference<>("{\"sessionId\":\"session space\",\"accountId\":\"account\",\"profileUserId\":\"profile\",\"status\":\"ACTIVE\"}");
        var path = new AtomicReference<String>();
        var account = new AtomicReference<String>();
        var profile = new AtomicReference<String>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/sessions/", exchange -> {
            path.set(exchange.getRequestURI().getRawPath());
            account.set(exchange.getRequestHeaders().getFirst("X-Account-Id"));
            profile.set(exchange.getRequestHeaders().getFirst("X-Profile-User-Id"));
            byte[] response = body.get().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status.get(), response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        var client = new RestRecommendationSessionValidator(RestClient.builder(), "http://127.0.0.1:" + server.getAddress().getPort());
        try {
            client.requireActive("account", "profile", "session space");
            assertThat(path).hasValue("/internal/sessions/session%20space/touch");
            assertThat(account).hasValue("account");
            assertThat(profile).hasValue("profile");
            expect(client, "other-account", "profile", "session space", 404);
            expect(client, "account", "other-profile", "session space", 404);
            expect(client, "account", "profile", "other-session", 404);
            body.set("{\"sessionId\":\"session space\",\"accountId\":\"account\",\"profileUserId\":\"profile\",\"status\":\"ENDED\"}");
            expect(client, "account", "profile", "session space", 410);
            for (int code : new int[]{401,403,404,410,500,202}) {
                status.set(code);
                expect(client, "account", "profile", "session space", code == 410 ? 410 : code < 500 && code != 202 ? 404 : 503);
            }
            status.set(200); body.set("{invalid-json");
            expect(client, "account", "profile", "session space", 503);
            body.set("null");
            expect(client, "account", "profile", "session space", 503);
            expect(client, "account", "profile", " ", 400);
            expect(client, "", "profile", "session space", 401);
        } finally {
            server.stop(0);
        }
        expect(client, "account", "profile", "session space", 503);
    }

    private void expect(RecommendationSessionValidator client, String account, String profile, String session, int status) {
        assertThatThrownBy(() -> client.requireActive(account, profile, session))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        failure -> assertThat(failure.getStatusCode().value()).isEqualTo(status));
    }
}
