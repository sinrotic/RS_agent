package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import com.sinrotic.rs.agent.service.impl.HttpAgentOnlineEvaluationObserver;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class OnlineEvaluationShadowTest {
    @TempDir Path directory;

    @Test void realChatNotifiesAfterItsFinalTurnIsVisibleAndObserverFailureDoesNotChangeAnswer() {
        var service = new InMemoryAgentOrchestrationService();
        service.setRecommendationService(request -> List.of(new AgentRecommendedItemVO("pen", "笔", "Pens", .9, "目录推荐")));
        AtomicReference<AgentTurnVO> observed = new AtomicReference<>();
        service.setOnlineEvaluationObserver((request, turn, previous) -> {
            assertThat(service.sessionTurns(request.sessionId()).turns()).isNotEmpty();
            assertThat(service.sessionTurns(request.sessionId()).turns().getLast().requestId()).isEqualTo(turn.requestId());
            observed.set(turn);
            throw new IllegalStateException("evaluation is unavailable");
        });
        var answer = service.chat(new AgentChatRequestDTO("real-session", "profile", "帮我买笔", 1, Map.of()));
        assertThat(answer.assistantMessage()).isNotBlank();
        assertThat(observed.get().requestId()).isEqualTo(answer.requestId());
        assertThat(observed.get().recommendedItemIds()).containsExactly("pen");
    }

    @Test void asynchronousAuthenticatedExportContainsOnlyAllowedEvidenceAndRedactedMessages() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var received = new CountDownLatch(1);
        var payload = new AtomicReference<Map<?, ?>>();
        var authorization = new AtomicReference<String>();
        server.createContext("/internal/evaluation/turns", exchange -> {
            payload.set(new ObjectMapper().readValue(exchange.getRequestBody(), Map.class));
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            exchange.sendResponseHeaders(202, -1); exchange.close(); received.countDown();
        });
        server.start();
        var observer = new HttpAgentOnlineEvaluationObserver(true, "http://127.0.0.1:" + server.getAddress().getPort(),
                "test-token", directory.resolve("outbox").toString(), "skill-v1", "model-v1");
        try {
            observer.completed(new AgentChatRequestDTO("session", "profile", "预算20元 me@example.com", 1,
                    Map.of("api_key", "never-export")),
                    new AgentTurnVO("turn", "预算20元", "参考商品", List.of(), List.of("pen")), List.of());
            assertThat(received.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(authorization.get()).isEqualTo("Bearer test-token");
            assertThat(payload.get().get("customer_messages").toString()).contains("[邮箱已脱敏]").doesNotContain("me@example.com");
            assertThat(payload.get().containsKey("context")).isFalse();
            assertThat(payload.get().get("observed_item_ids")).isEqualTo(List.of("pen"));
        } finally { observer.close(); server.stop(0); }
    }

    @Test void failedDeliveryRetainsOutboxForRestartInsteadOfChangingSkillOrDroppingAcceptedEvent() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var received = new CountDownLatch(1);
        server.createContext("/internal/evaluation/turns", exchange -> {
            exchange.getRequestBody().readAllBytes(); exchange.sendResponseHeaders(503, -1);
            exchange.close(); received.countDown();
        });
        server.start();
        Path outbox = directory.resolve("outbox");
        var observer = new HttpAgentOnlineEvaluationObserver(true, "http://127.0.0.1:" + server.getAddress().getPort(),
                "test-token", outbox.toString(), "skill-v1", "model-v1");
        try {
            observer.completed(new AgentChatRequestDTO("session", "profile", "买笔", 1, Map.of()),
                    new AgentTurnVO("turn", "买笔", "参考商品", List.of(), List.of("pen")), List.of());
            assertThat(received.await(5, TimeUnit.SECONDS)).isTrue();
            try (var files = Files.list(outbox)) { assertThat(files.filter(p -> p.toString().endsWith(".json")).count()).isEqualTo(1); }
            assertThat(observer.diagnostics().get("auto_deploy")).isEqualTo(false);
        } finally { observer.close(); server.stop(0); }
    }
}
