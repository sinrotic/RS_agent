package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;
import com.sinrotic.rs.recommend.service.impl.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;

class TwoTowerServingTest {
    @Test void changedHistoryOrCheckpointDoesNotReuseOldUserVector() {
        var store = new BoundedUserEmbeddingStore();
        var vector = new UserEmbedding("epoch5", "user", List.of(1f), "trained");
        store.save(vector, List.of("a", "b"));
        assertTrue(store.find("epoch5", "user", List.of("a", "b")).isPresent());
        assertTrue(store.find("epoch5", "user", List.of("new", "a", "b")).isEmpty());
        assertTrue(store.find("epoch1", "user", List.of("a", "b")).isEmpty());
    }

    @Test void runtimeContractAcceptsTrainedVectorAndRejectsWrongSpace() throws Exception {
        var key = DefaultTwoTowerRecallProvider.MODEL_NAME;
        var values = new ArrayList<>(Collections.nCopies(64, 0.0)); values.set(0, 1.0);
        var response = new AtomicReference<>("{\"model_key\":\"" + key + "\",\"embedding\":" + values + "}");
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/model/two-tower/user-embedding", exchange -> {
            byte[] bytes = response.get().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes); exchange.close();
        });
        server.start();
        try {
            var client = new RestUserTowerModelClient(RestClient.builder(), "http://127.0.0.1:" + server.getAddress().getPort());
            assertEquals(64, client.inferUserEmbedding(key, "request", "user", List.of("a", "b")).orElseThrow().embedding().size());
            var productClient = new RestUserTowerModelClient(RestClient.builder(), "http://127.0.0.1:" + server.getAddress().getPort(), 1024);
            assertThrows(IllegalStateException.class, () -> productClient.inferUserEmbedding(key, "request", "user", List.of("a", "b")));
            var productValues = new ArrayList<>(Collections.nCopies(1024, 0.0)); productValues.set(0, 1.0);
            response.set("{\"model_key\":\"" + key + "\",\"embedding\":" + productValues + "}");
            assertEquals(1024, productClient.inferUserEmbedding(key, "request", "user", List.of("a", "b")).orElseThrow().embedding().size());
            assertThrows(IllegalStateException.class, () -> client.inferUserEmbedding(key, "request", "user", List.of("a", "b")));
            response.set("{\"model_key\":\"" + key + "\",\"embedding\":[1,0,0]}");
            assertThrows(IllegalStateException.class, () -> client.inferUserEmbedding(key, "request", "user", List.of("a", "b")));
            response.set("{\"model_key\":\"wrong-checkpoint\",\"embedding\":" + values + "}");
            assertThrows(IllegalStateException.class, () -> client.inferUserEmbedding(key, "request", "user", List.of("a", "b")));
        } finally { server.stop(0); }
    }
}
